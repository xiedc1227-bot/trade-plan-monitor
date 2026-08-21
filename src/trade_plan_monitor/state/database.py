"""SQLite engine and session construction for durable monitor state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_BUSY_TIMEOUT_MS = 5_000
MAX_BUSY_TIMEOUT_MS = 60_000


def create_sqlite_engine(
    database_path: str | Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> Engine:
    """Create a file-backed SQLite engine with required connection invariants."""

    path = _validate_database_path(database_path)
    timeout_ms = _validate_busy_timeout(busy_timeout_ms)
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(path)),
    )

    @event.listens_for(engine, "connect")
    def apply_sqlite_pragmas(
        dbapi_connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        _apply_sqlite_pragmas(dbapi_connection, timeout_ms)

    @event.listens_for(engine, "begin")
    def begin_sqlite_transaction(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return the application's explicitly bound SQLAlchemy session factory."""

    return sessionmaker(bind=engine, expire_on_commit=False)


def upgrade_database(engine: Engine) -> None:
    """Upgrade an engine's database to the packaged Alembic head revision."""

    if engine.dialect.name != "sqlite":
        raise ValueError("upgrade_database requires a SQLite engine")

    migrations_path = Path(__file__).with_name("migrations").resolve()
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(migrations_path))

    with engine.begin() as connection:
        journal_mode = str(connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()).lower()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
        if (
            journal_mode != "wal"
            or foreign_keys != 1
            or not 1 <= busy_timeout <= MAX_BUSY_TIMEOUT_MS
        ):
            raise RuntimeError("Database engine is missing required WAL and foreign-key invariants")

        alembic_config.attributes["connection"] = connection
        command.upgrade(alembic_config, "head")


def _validate_database_path(database_path: str | Path) -> Path:
    if not isinstance(database_path, (str, Path)):
        raise TypeError("database_path must be a string or Path")
    if isinstance(database_path, str) and not database_path.strip():
        raise ValueError("database_path must not be empty")

    path = Path(database_path).expanduser().resolve()
    if path.exists() and not path.is_file():
        raise ValueError("database_path must point to a file")
    return path


def _validate_busy_timeout(busy_timeout_ms: int) -> int:
    if type(busy_timeout_ms) is not int:
        raise TypeError("busy_timeout_ms must be an integer")
    if not 1 <= busy_timeout_ms <= MAX_BUSY_TIMEOUT_MS:
        raise ValueError(f"busy_timeout_ms must be between 1 and {MAX_BUSY_TIMEOUT_MS}")
    return busy_timeout_ms


def _apply_sqlite_pragmas(
    dbapi_connection: sqlite3.Connection,
    busy_timeout_ms: int,
) -> None:
    has_autocommit = hasattr(dbapi_connection, "autocommit")
    if has_autocommit:
        dbapi_connection.autocommit = True  # type: ignore[attr-defined]

    cursor = dbapi_connection.cursor()
    try:
        journal_mode_row = cursor.execute("PRAGMA journal_mode=WAL").fetchone()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")

        if journal_mode_row is None or str(journal_mode_row[0]).lower() != "wal":
            raise RuntimeError("SQLite database did not enter WAL journal mode")
        if cursor.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
        if cursor.execute("PRAGMA busy_timeout").fetchone() != (busy_timeout_ms,):
            raise RuntimeError("SQLite busy timeout could not be configured")
    finally:
        cursor.close()
        if has_autocommit:
            # Keep the all-version isolation-level recipe deterministic even
            # after sqlite3 eventually changes its default autocommit mode.
            dbapi_connection.autocommit = (  # type: ignore[attr-defined]
                sqlite3.LEGACY_TRANSACTION_CONTROL
            )

    # Disable sqlite3's legacy implicit transaction control. SQLAlchemy's
    # ``begin`` event above emits BEGIN for every explicit transaction instead.
    dbapi_connection.isolation_level = None


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "MAX_BUSY_TIMEOUT_MS",
    "create_session_factory",
    "create_sqlite_engine",
    "upgrade_database",
]
