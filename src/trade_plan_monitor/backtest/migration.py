"""Read-only inventory and fail-closed authorization for backtest migrations."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SQLITE_HEADER = b"SQLite format 3\x00"
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_MAX_INVENTORIED_IDENTITIES = 10_000
_UTC_SUFFIXES = ("Z", "+00:00")

_MARKET_TABLES = frozenset(
    {
        "market_artifact",
        "market_head",
        "market_minute_artifact",
        "market_minute_head",
        "market_dataset",
        "market_dataset_item",
    }
)
_MARKET_METADATA_COLUMNS = (
    ("market_artifact", "created_at"),
    ("market_head", "updated_at"),
    ("market_minute_artifact", "created_at"),
    ("market_minute_head", "updated_at"),
    ("market_dataset", "created_at"),
)
_RESULT_TABLES = frozenset({"backtest_run", "backtest_fill", "backtest_detail"})
_CURRENT_RESULT_COLUMNS = frozenset(
    {
        "run_id",
        "plan_sha256",
        "dataset_hash",
        "status",
        "completed_at",
        "pinned",
        "materialized",
        "publication_fill_count",
        "publication_detail_count",
        "publication_fill_set_hash",
        "publication_detail_set_hash",
        "summary_hash",
        "summary_json",
        "created_at",
    }
)


class MigrationPreflightError(RuntimeError):
    """A stable blocker raised before a migration or store mutation can start."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DatabaseState(StrEnum):
    """Structural state observed through an immutable read-only connection."""

    FRESH = "FRESH"
    CURRENT = "CURRENT"
    LEGACY = "LEGACY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SidecarFingerprint:
    suffix: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Path-independent byte fingerprint for one SQLite main file and its sidecars."""

    exists: bool
    size_bytes: int
    main_sha256: str | None
    sidecars: tuple[SidecarFingerprint, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class TimestampMetadataInventory:
    """Bounded evidence for one ordered SQLite timestamp column."""

    table: str
    column: str
    value_count: int
    utc_value_count: int
    ordered_values_sha256: str


@dataclass(frozen=True, slots=True)
class MigrationInventory:
    """Immutable evidence gathered before any WAL pragma or DDL operation."""

    database_path: Path
    database_state: DatabaseState
    source_fingerprint: SourceFingerprint
    schema_sha256: str
    schema_version: int | None
    journal_mode: str | None
    table_names: tuple[str, ...]
    dataset_hash_goldens: tuple[bytes, ...] = ()
    utc_metadata: tuple[TimestampMetadataInventory, ...] = ()
    terminal_run_count: int = 0
    compatibility_only_run_ids: tuple[str, ...] = ()
    migration_reasons: tuple[str, ...] = ()
    requires_schema_migration: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedBackupFacts:
    """Facts supplied by a separately verified, stopped-coordinator backup workflow."""

    source_fingerprint: str
    backup_sha256: str
    backup_size_bytes: int
    verified_at: datetime
    coordinator_stopped: bool

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.source_fingerprint):
            raise ValueError("source_fingerprint must be a lowercase SHA-256 value")
        if not _SHA256_PATTERN.fullmatch(self.backup_sha256):
            raise ValueError("backup_sha256 must be a lowercase SHA-256 value")
        if type(self.backup_size_bytes) is not int or self.backup_size_bytes <= 0:
            raise ValueError("backup_size_bytes must be a positive integer")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        if self.verified_at.utcoffset() != timedelta(hours=8):
            raise ValueError("verified_at must use Asia/Shanghai or explicit +08:00")
        if type(self.coordinator_stopped) is not bool:
            raise TypeError("coordinator_stopped must be a bool")


@dataclass(frozen=True, slots=True)
class MigrationDecision:
    """Authorization evidence bound to one unchanged inspected source."""

    authorized: bool
    source_fingerprint: str
    migration_reasons: tuple[str, ...]
    verified_backup: VerifiedBackupFacts


def inspect_market_database(path: str | Path) -> MigrationInventory:
    """Inventory market schema, UTC metadata, and dataset identities without mutation."""

    return _inspect_database(path, store="market")


def inspect_result_database(path: str | Path) -> MigrationInventory:
    """Inventory result schema and legacy rows without mutation or content guessing."""

    return _inspect_database(path, store="result")


def require_safe_store_initialization(inventory: MigrationInventory) -> None:
    """Block automatic initialization when it would perform an unapproved migration."""

    if not isinstance(inventory, MigrationInventory):
        raise TypeError("inventory must be a MigrationInventory")
    if inventory.terminal_run_count:
        raise MigrationPreflightError("LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION")
    if inventory.source_fingerprint.sidecars:
        raise MigrationPreflightError("SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT")
    if inventory.requires_schema_migration:
        raise MigrationPreflightError("LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION")
    assert_source_unchanged(inventory)


def assert_source_unchanged(inventory: MigrationInventory) -> None:
    """Rebind a decision/use to the exact bytes inspected by the read-only preflight."""

    if _source_fingerprint(inventory.database_path) != inventory.source_fingerprint:
        raise MigrationPreflightError("MIGRATION_SOURCE_CHANGED_AFTER_PREFLIGHT")


def authorize_migration(
    inventory: MigrationInventory,
    verified_backup: VerifiedBackupFacts,
) -> MigrationDecision:
    """Authorize no mutation, but prove a future migration has the required evidence."""

    if not isinstance(inventory, MigrationInventory):
        raise TypeError("inventory must be a MigrationInventory")
    if not isinstance(verified_backup, VerifiedBackupFacts):
        raise TypeError("verified_backup must be VerifiedBackupFacts")
    if inventory.terminal_run_count:
        raise MigrationPreflightError("LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION")
    if not inventory.migration_reasons:
        raise MigrationPreflightError("MIGRATION_NOT_REQUIRED")
    if not verified_backup.coordinator_stopped:
        raise MigrationPreflightError("MIGRATION_REQUIRES_STOPPED_COORDINATOR")
    if verified_backup.source_fingerprint != inventory.source_fingerprint.digest:
        raise MigrationPreflightError("BACKUP_SOURCE_FINGERPRINT_MISMATCH")
    if inventory.source_fingerprint.sidecars:
        raise MigrationPreflightError("SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT")
    assert_source_unchanged(inventory)
    return MigrationDecision(
        authorized=True,
        source_fingerprint=inventory.source_fingerprint.digest,
        migration_reasons=inventory.migration_reasons,
        verified_backup=verified_backup,
    )


def _inspect_database(path: str | Path, *, store: str) -> MigrationInventory:
    normalized_path = _normalize_path(path)
    before = _source_fingerprint(normalized_path)
    if not before.exists or before.size_bytes == 0:
        if before.sidecars:
            raise MigrationPreflightError("ORPHANED_SQLITE_SIDECARS")
        return MigrationInventory(
            database_path=normalized_path,
            database_state=DatabaseState.FRESH,
            source_fingerprint=before,
            schema_sha256=_empty_hash(),
            schema_version=None,
            journal_mode=None,
            table_names=(),
        )
    if _read_header(normalized_path) != _SQLITE_HEADER:
        raise MigrationPreflightError("MIGRATION_SOURCE_NOT_SQLITE")
    if before.sidecars:
        raise MigrationPreflightError("SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT")

    try:
        with closing(
            sqlite3.connect(
                f"{normalized_path.as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=5,
            )
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
            schema_rows = tuple(
                connection.execute(
                    "SELECT type, name, tbl_name, COALESCE(sql, '') "
                    "FROM sqlite_schema ORDER BY type, name, tbl_name"
                )
            )
            table_names = tuple(str(row[1]) for row in schema_rows if str(row[0]) == "table")
            if store == "market":
                inventory_fields = _inspect_market(connection, frozenset(table_names))
            else:
                inventory_fields = _inspect_results(connection, frozenset(table_names))
    except sqlite3.Error as error:
        raise MigrationPreflightError("MIGRATION_SOURCE_NOT_READABLE") from error

    after = _source_fingerprint(normalized_path)
    if after != before:
        raise MigrationPreflightError("MIGRATION_SOURCE_CHANGED_DURING_PREFLIGHT")
    return MigrationInventory(
        database_path=normalized_path,
        source_fingerprint=before,
        schema_sha256=_schema_hash(schema_rows),
        schema_version=schema_version,
        journal_mode=journal_mode,
        table_names=table_names,
        **inventory_fields,
    )


def _inspect_market(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> dict[str, object]:
    present = table_names & _MARKET_TABLES
    state = (
        DatabaseState.CURRENT
        if _MARKET_TABLES <= table_names
        else DatabaseState.LEGACY
        if present
        else DatabaseState.UNKNOWN
    )
    reasons: list[str] = []
    if state == DatabaseState.LEGACY:
        reasons.append("LEGACY_SCHEMA")
    dataset_hashes: tuple[bytes, ...] = ()
    if "market_dataset" in table_names and "dataset_hash" in _table_columns(
        connection, "market_dataset"
    ):
        rows = connection.execute(
            "SELECT dataset_hash FROM market_dataset ORDER BY CAST(dataset_hash AS BLOB)"
        ).fetchmany(_MAX_INVENTORIED_IDENTITIES + 1)
        if len(rows) > _MAX_INVENTORIED_IDENTITIES:
            raise MigrationPreflightError("DATASET_HASH_INVENTORY_LIMIT_EXCEEDED")
        dataset_hashes = tuple(_raw_bytes(row[0]) for row in rows)

    metadata = tuple(
        evidence
        for table, column in _MARKET_METADATA_COLUMNS
        if table in table_names and column in _table_columns(connection, table)
        for evidence in (_timestamp_inventory(connection, table, column),)
    )
    if any(item.utc_value_count for item in metadata):
        reasons.append("UTC_MARKET_METADATA")
    return {
        "database_state": state,
        "dataset_hash_goldens": dataset_hashes,
        "utc_metadata": metadata,
        "migration_reasons": tuple(reasons),
        "requires_schema_migration": state == DatabaseState.LEGACY,
    }


def _inspect_results(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> dict[str, object]:
    present = table_names & _RESULT_TABLES
    run_columns = (
        _table_columns(connection, "backtest_run") if "backtest_run" in table_names else ()
    )
    current = _RESULT_TABLES <= table_names and _CURRENT_RESULT_COLUMNS <= set(run_columns)
    state = (
        DatabaseState.CURRENT
        if current
        else DatabaseState.LEGACY
        if present
        else DatabaseState.UNKNOWN
    )
    terminal_count = 0
    compatibility_only: tuple[str, ...] = ()
    if {"run_id", "status"} <= set(run_columns):
        terminal_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM backtest_run WHERE status IN ('FAILED', 'CANCELLED')"
            ).fetchone()[0]
        )
        rows = connection.execute(
            "SELECT run_id FROM backtest_run WHERE status = 'COMPLETED' ORDER BY run_id"
        ).fetchmany(_MAX_INVENTORIED_IDENTITIES + 1)
        if len(rows) > _MAX_INVENTORIED_IDENTITIES:
            raise MigrationPreflightError("LEGACY_RESULT_INVENTORY_LIMIT_EXCEEDED")
        compatibility_only = tuple(str(row[0]) for row in rows)

    reasons: list[str] = []
    if compatibility_only:
        reasons.append("LEGACY_COMPLETED_RESULTS_COMPATIBILITY_ONLY")
    if state == DatabaseState.LEGACY:
        reasons.append("LEGACY_SCHEMA")
    if terminal_count:
        reasons.insert(0, "LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION")
    return {
        "database_state": state,
        "terminal_run_count": terminal_count,
        "compatibility_only_run_ids": compatibility_only,
        "migration_reasons": tuple(reasons),
        "requires_schema_migration": state == DatabaseState.LEGACY,
    }


def _timestamp_inventory(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> TimestampMetadataInventory:
    digest = sha256()
    value_count = 0
    utc_count = 0
    cursor = connection.execute(
        f'SELECT "{column}" FROM "{table}" ORDER BY CAST("{column}" AS BLOB), rowid'
    )
    while rows := cursor.fetchmany(1_000):
        for row in rows:
            raw = _raw_bytes(row[0])
            _hash_component(digest, raw)
            value_count += 1
            text = raw.decode("utf-8", errors="replace")
            if text.endswith(_UTC_SUFFIXES):
                utc_count += 1
    return TimestampMetadataInventory(
        table=table,
        column=column,
        value_count=value_count,
        utc_value_count=utc_count,
        ordered_values_sha256=digest.hexdigest(),
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))


def _schema_hash(rows: tuple[tuple[object, ...], ...]) -> str:
    digest = sha256()
    for row in rows:
        for value in row:
            _hash_component(digest, _raw_bytes(value))
    return digest.hexdigest()


def _source_fingerprint(path: Path) -> SourceFingerprint:
    sidecars = tuple(
        SidecarFingerprint(
            suffix=suffix,
            size_bytes=candidate.stat().st_size,
            sha256=_hash_file(candidate),
        )
        for suffix in _SIDECAR_SUFFIXES
        for candidate in (Path(f"{path}{suffix}"),)
        if candidate.is_file()
    )
    exists = path.is_file()
    size_bytes = path.stat().st_size if exists else 0
    main_sha256 = _hash_file(path) if exists else None
    digest = sha256()
    _hash_component(digest, b"sqlite-migration-source-v1")
    _hash_component(digest, b"1" if exists else b"0")
    _hash_component(digest, str(size_bytes).encode("ascii"))
    _hash_component(digest, b"" if main_sha256 is None else main_sha256.encode("ascii"))
    for sidecar in sidecars:
        _hash_component(digest, sidecar.suffix.encode("ascii"))
        _hash_component(digest, str(sidecar.size_bytes).encode("ascii"))
        _hash_component(digest, sidecar.sha256.encode("ascii"))
    return SourceFingerprint(
        exists=exists,
        size_bytes=size_bytes,
        main_sha256=main_sha256,
        sidecars=sidecars,
        digest=digest.hexdigest(),
    )


def _normalize_path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be a string or Path")
    if isinstance(path, str) and not path.strip():
        raise ValueError("path must not be empty")
    normalized = Path(path).expanduser().resolve()
    if normalized.exists() and not normalized.is_file():
        raise ValueError("path must point to a file")
    return normalized


def _read_header(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(len(_SQLITE_HEADER))


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _hash_component(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _empty_hash() -> str:
    return sha256(b"").hexdigest()


__all__ = [
    "DatabaseState",
    "MigrationDecision",
    "MigrationInventory",
    "MigrationPreflightError",
    "SidecarFingerprint",
    "SourceFingerprint",
    "TimestampMetadataInventory",
    "VerifiedBackupFacts",
    "assert_source_unchanged",
    "authorize_migration",
    "inspect_market_database",
    "inspect_result_database",
    "require_safe_store_initialization",
]
