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

_ColumnContract = tuple[str, bool, str | None, int]

_MARKET_COLUMN_CONTRACTS: dict[str, dict[str, _ColumnContract]] = {
    "market_artifact": {
        "artifact_hash": ("TEXT", False, None, 1),
        "kind": ("TEXT", True, None, 0),
        "provider": ("TEXT", True, None, 0),
        "contract_version": ("TEXT", True, None, 0),
        "natural_key": ("TEXT", True, None, 0),
        "content_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "market_head": {
        "natural_key": ("TEXT", False, None, 1),
        "artifact_hash": ("TEXT", True, None, 0),
        "revision": ("INTEGER", True, None, 0),
        "kind": ("TEXT", True, None, 0),
        "symbol": ("TEXT", False, None, 0),
        "trade_date": ("TEXT", True, None, 0),
        "updated_at": ("TEXT", True, None, 0),
    },
    "market_minute_artifact": {
        "artifact_hash": ("TEXT", False, None, 1),
        "symbol": ("TEXT", True, None, 0),
        "bar_end": ("TEXT", True, None, 0),
        "content_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "market_minute_head": {
        "symbol": ("TEXT", True, None, 1),
        "bar_end": ("TEXT", True, None, 2),
        "artifact_hash": ("TEXT", True, None, 0),
        "revision": ("INTEGER", True, None, 0),
        "updated_at": ("TEXT", True, None, 0),
    },
    "market_dataset": {
        "dataset_hash": ("TEXT", False, None, 1),
        "manifest_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "market_dataset_item": {
        "dataset_hash": ("TEXT", True, None, 1),
        "natural_key": ("TEXT", True, None, 2),
        "artifact_hash": ("TEXT", True, None, 0),
        "kind": ("TEXT", True, None, 0),
        "symbol": ("TEXT", False, None, 0),
        "trade_date": ("TEXT", True, None, 0),
    },
}
_MARKET_TABLES = frozenset(_MARKET_COLUMN_CONTRACTS)
_MARKET_METADATA_COLUMNS = (
    ("market_artifact", "created_at"),
    ("market_head", "updated_at"),
    ("market_minute_artifact", "created_at"),
    ("market_minute_head", "updated_at"),
    ("market_dataset", "created_at"),
)
_RESULT_COLUMN_CONTRACTS: dict[str, dict[str, _ColumnContract]] = {
    "backtest_run": {
        "run_id": ("TEXT", False, None, 1),
        "plan_sha256": ("TEXT", True, None, 0),
        "dataset_hash": ("TEXT", True, None, 0),
        "status": ("TEXT", True, None, 0),
        "completed_at": ("TEXT", True, None, 0),
        "pinned": ("INTEGER", True, "0", 0),
        "materialized": ("INTEGER", True, "1", 0),
        "publication_fill_count": ("INTEGER", False, None, 0),
        "publication_detail_count": ("INTEGER", False, None, 0),
        "publication_fill_set_hash": ("TEXT", False, None, 0),
        "publication_detail_set_hash": ("TEXT", False, None, 0),
        "summary_hash": ("TEXT", True, None, 0),
        "summary_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "backtest_fill": {
        "fill_id": ("TEXT", False, None, 1),
        "run_id": ("TEXT", True, None, 0),
        "filled_at": ("TEXT", True, None, 0),
        "content_hash": ("TEXT", True, None, 0),
        "payload_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "backtest_detail": {
        "detail_id": ("TEXT", False, None, 1),
        "run_id": ("TEXT", True, None, 0),
        "kind": ("TEXT", True, None, 0),
        "event_at": ("TEXT", True, None, 0),
        "content_hash": ("TEXT", True, None, 0),
        "payload_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
}
_RESULT_TABLES = frozenset(_RESULT_COLUMN_CONTRACTS)

_ForeignKeyContract = tuple[str, str, str, str, str, str]
_MARKET_FOREIGN_KEY_CONTRACTS: dict[str, frozenset[_ForeignKeyContract]] = {
    "market_artifact": frozenset(),
    "market_head": frozenset(
        {("artifact_hash", "market_artifact", "artifact_hash", "NO ACTION", "NO ACTION", "NONE")}
    ),
    "market_minute_artifact": frozenset(),
    "market_minute_head": frozenset(
        {
            (
                "artifact_hash",
                "market_minute_artifact",
                "artifact_hash",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            )
        }
    ),
    "market_dataset": frozenset(),
    "market_dataset_item": frozenset(
        {
            (
                "dataset_hash",
                "market_dataset",
                "dataset_hash",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            ),
            (
                "artifact_hash",
                "market_artifact",
                "artifact_hash",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            ),
        }
    ),
}
_RESULT_FOREIGN_KEY_CONTRACTS: dict[str, frozenset[_ForeignKeyContract]] = {
    "backtest_run": frozenset(),
    "backtest_fill": frozenset(
        {("run_id", "backtest_run", "run_id", "NO ACTION", "RESTRICT", "NONE")}
    ),
    "backtest_detail": frozenset(
        {("run_id", "backtest_run", "run_id", "NO ACTION", "RESTRICT", "NONE")}
    ),
}

_MARKET_TABLE_SQL_CONTRACTS = {
    "market_artifact": """
        CREATE TABLE market_artifact (
            artifact_hash TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
            provider TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            natural_key TEXT NOT NULL,
            content_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "market_head": """
        CREATE TABLE market_head (
            natural_key TEXT PRIMARY KEY,
            artifact_hash TEXT NOT NULL REFERENCES market_artifact (artifact_hash),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
            symbol TEXT,
            trade_date TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "market_minute_artifact": """
        CREATE TABLE market_minute_artifact (
            artifact_hash TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            bar_end TEXT NOT NULL,
            content_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "market_minute_head": """
        CREATE TABLE market_minute_head (
            symbol TEXT NOT NULL,
            bar_end TEXT NOT NULL,
            artifact_hash TEXT NOT NULL
                REFERENCES market_minute_artifact (artifact_hash) ON DELETE RESTRICT,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, bar_end)
        )
    """,
    "market_dataset": """
        CREATE TABLE market_dataset (
            dataset_hash TEXT PRIMARY KEY,
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "market_dataset_item": """
        CREATE TABLE market_dataset_item (
            dataset_hash TEXT NOT NULL
                REFERENCES market_dataset (dataset_hash) ON DELETE RESTRICT,
            natural_key TEXT NOT NULL,
            artifact_hash TEXT NOT NULL
                REFERENCES market_artifact (artifact_hash) ON DELETE RESTRICT,
            kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
            symbol TEXT,
            trade_date TEXT NOT NULL,
            PRIMARY KEY (dataset_hash, natural_key)
        )
    """,
}
_RESULT_TABLE_SQL_CONTRACTS = {
    "backtest_run": """
        CREATE TABLE backtest_run (
            run_id TEXT PRIMARY KEY,
            plan_sha256 TEXT NOT NULL,
            dataset_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED', 'CANCELLED')),
            completed_at TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
            materialized INTEGER NOT NULL DEFAULT 1 CHECK (materialized IN (0, 1)),
            publication_fill_count INTEGER
                CHECK (publication_fill_count IS NULL OR publication_fill_count >= 0),
            publication_detail_count INTEGER
                CHECK (publication_detail_count IS NULL OR publication_detail_count >= 0),
            publication_fill_set_hash TEXT,
            publication_detail_set_hash TEXT,
            summary_hash TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "backtest_fill": """
        CREATE TABLE backtest_fill (
            fill_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
            filled_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "backtest_detail": """
        CREATE TABLE backtest_detail (
            detail_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
            kind TEXT NOT NULL CHECK (
                kind IN (
                    'DECISION', 'SIGNAL', 'EXECUTION_OUTCOME', 'DAILY_EQUITY',
                    'DIAGNOSTIC', 'DEBUG_TRACE'
                )
            ),
            event_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
}

_IndexColumnContract = tuple[str, bool, str]
_IndexContract = tuple[str, tuple[_IndexColumnContract, ...]]
_MARKET_INDEX_CONTRACTS: dict[str, _IndexContract] = {
    "ix_market_artifact_natural_key": (
        "market_artifact",
        (("natural_key", False, "BINARY"), ("created_at", False, "BINARY")),
    ),
    "ix_market_head_kind_symbol_date": (
        "market_head",
        (
            ("kind", False, "BINARY"),
            ("symbol", False, "BINARY"),
            ("trade_date", False, "BINARY"),
        ),
    ),
    "ix_market_minute_artifact_symbol_end": (
        "market_minute_artifact",
        (
            ("symbol", False, "BINARY"),
            ("bar_end", False, "BINARY"),
            ("artifact_hash", False, "BINARY"),
        ),
    ),
    "ix_market_minute_head_end": (
        "market_minute_head",
        (("bar_end", False, "BINARY"), ("symbol", False, "BINARY")),
    ),
    "ix_market_dataset_item_lookup": (
        "market_dataset_item",
        (
            ("dataset_hash", False, "BINARY"),
            ("kind", False, "BINARY"),
            ("symbol", False, "BINARY"),
            ("trade_date", False, "BINARY"),
        ),
    ),
}
_RESULT_INDEX_CONTRACTS: dict[str, _IndexContract] = {
    "ix_backtest_run_retention": (
        "backtest_run",
        (
            ("status", False, "BINARY"),
            ("pinned", False, "BINARY"),
            ("completed_at", True, "BINARY"),
            ("run_id", True, "BINARY"),
        ),
    ),
    "ix_backtest_run_retention_v2": (
        "backtest_run",
        (
            ("status", False, "BINARY"),
            ("pinned", False, "BINARY"),
            ("materialized", False, "BINARY"),
            ("created_at", True, "BINARY"),
            ("run_id", True, "BINARY"),
        ),
    ),
    "ix_backtest_fill_run": (
        "backtest_fill",
        (
            ("run_id", False, "BINARY"),
            ("filled_at", False, "BINARY"),
            ("fill_id", False, "BINARY"),
        ),
    ),
    "ix_backtest_detail_retention": (
        "backtest_detail",
        (
            ("kind", False, "BINARY"),
            ("run_id", False, "BINARY"),
            ("detail_id", False, "BINARY"),
        ),
    ),
    "ix_backtest_detail_run_event": (
        "backtest_detail",
        (
            ("run_id", False, "BINARY"),
            ("event_at", False, "BINARY"),
            ("detail_id", False, "BINARY"),
        ),
    ),
}


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
    if inventory.database_state is DatabaseState.UNKNOWN:
        raise MigrationPreflightError("UNRECOGNIZED_SCHEMA_CANNOT_BE_MIGRATED")
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
    current = _has_required_schema(
        connection,
        table_names,
        column_contracts=_MARKET_COLUMN_CONTRACTS,
        foreign_key_contracts=_MARKET_FOREIGN_KEY_CONTRACTS,
        table_sql_contracts=_MARKET_TABLE_SQL_CONTRACTS,
        index_contracts=_MARKET_INDEX_CONTRACTS,
    )
    state = (
        DatabaseState.CURRENT
        if current
        else DatabaseState.LEGACY
        if present
        else DatabaseState.UNKNOWN
    )
    reasons: list[str] = []
    if state == DatabaseState.LEGACY:
        reasons.append("LEGACY_SCHEMA")
    elif state == DatabaseState.UNKNOWN:
        reasons.append("UNRECOGNIZED_SCHEMA")
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
        "requires_schema_migration": state != DatabaseState.CURRENT,
    }


def _inspect_results(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> dict[str, object]:
    present = table_names & _RESULT_TABLES
    run_columns = (
        _table_columns(connection, "backtest_run") if "backtest_run" in table_names else ()
    )
    current = _has_required_schema(
        connection,
        table_names,
        column_contracts=_RESULT_COLUMN_CONTRACTS,
        foreign_key_contracts=_RESULT_FOREIGN_KEY_CONTRACTS,
        table_sql_contracts=_RESULT_TABLE_SQL_CONTRACTS,
        index_contracts=_RESULT_INDEX_CONTRACTS,
    )
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
    elif state == DatabaseState.UNKNOWN:
        reasons.append("UNRECOGNIZED_SCHEMA")
    if terminal_count:
        reasons.insert(0, "LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION")
    return {
        "database_state": state,
        "terminal_run_count": terminal_count,
        "compatibility_only_run_ids": compatibility_only,
        "migration_reasons": tuple(reasons),
        "requires_schema_migration": state != DatabaseState.CURRENT,
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


def _has_required_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
    *,
    column_contracts: dict[str, dict[str, _ColumnContract]],
    foreign_key_contracts: dict[str, frozenset[_ForeignKeyContract]],
    table_sql_contracts: dict[str, str],
    index_contracts: dict[str, _IndexContract],
) -> bool:
    if frozenset(column_contracts) != table_names:
        return False
    if not _has_exact_table_sql(connection, table_sql_contracts):
        return False
    for table, expected_columns in column_contracts.items():
        rows = tuple(connection.execute(f'PRAGMA table_xinfo("{table}")'))
        if any(len(row) <= 6 or int(row[6]) != 0 for row in rows):
            return False
        actual_columns = {str(row[1]): row for row in rows}
        if expected_columns.keys() != actual_columns.keys():
            return False
        for name, (declared_type, not_null, default_sql, primary_key) in expected_columns.items():
            row = actual_columns[name]
            actual_default = None if row[4] is None else str(row[4]).strip()
            if str(row[2]).strip().upper() != declared_type:
                return False
            if bool(row[3]) is not not_null:
                return False
            if actual_default != default_sql:
                return False
            if int(row[5]) != primary_key:
                return False
        actual_primary_key = tuple(
            str(row[1])
            for row in sorted(
                (row for row in rows if int(row[5]) > 0),
                key=lambda row: int(row[5]),
            )
        )
        expected_primary_key = tuple(
            name
            for name, contract in sorted(
                expected_columns.items(),
                key=lambda item: item[1][3],
            )
            if contract[3] > 0
        )
        if actual_primary_key != expected_primary_key:
            return False
        if not _primary_key_uses_binary_collation(
            connection,
            table,
            expected_primary_key,
        ):
            return False
        if _has_unexpected_unique_index(connection, table):
            return False
        if _foreign_key_contract(connection, table) != foreign_key_contracts[table]:
            return False
    if connection.execute("SELECT 1 FROM sqlite_schema WHERE type = 'trigger' LIMIT 1").fetchone():
        return False
    return _has_compatible_named_indexes(connection, index_contracts)


def _has_exact_table_sql(
    connection: sqlite3.Connection,
    table_sql_contracts: dict[str, str],
) -> bool:
    rows = connection.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'table'").fetchall()
    actual_sql = {str(row[0]): row[1] for row in rows}
    if table_sql_contracts.keys() != actual_sql.keys():
        return False
    return all(
        actual_sql[table] is not None
        and _tokenize_schema_sql(str(actual_sql[table])) == _tokenize_schema_sql(expected_sql)
        for table, expected_sql in table_sql_contracts.items()
    )


def _primary_key_uses_binary_collation(
    connection: sqlite3.Connection,
    table: str,
    expected_primary_key: tuple[str, ...],
) -> bool:
    primary_key_indexes = tuple(
        row
        for row in connection.execute(f'PRAGMA index_list("{table}")')
        if len(row) > 3 and str(row[3]).lower() == "pk"
    )
    if len(primary_key_indexes) != 1:
        return False
    index_name = str(primary_key_indexes[0][1]).replace('"', '""')
    key_rows = sorted(
        (
            row
            for row in connection.execute(f'PRAGMA index_xinfo("{index_name}")')
            if len(row) > 5 and int(row[5]) == 1
        ),
        key=lambda row: int(row[0]),
    )
    return tuple((str(row[2]), bool(row[3]), str(row[4]).upper()) for row in key_rows) == tuple(
        (name, False, "BINARY") for name in expected_primary_key
    )


def _has_unexpected_unique_index(connection: sqlite3.Connection, table: str) -> bool:
    return any(
        bool(row[2]) and (len(row) <= 3 or str(row[3]).lower() != "pk")
        for row in connection.execute(f'PRAGMA index_list("{table}")')
    )


def _foreign_key_contract(
    connection: sqlite3.Connection,
    table: str,
) -> frozenset[_ForeignKeyContract]:
    return frozenset(
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
            str(row[5]).upper(),
            str(row[6]).upper(),
            str(row[7]).upper(),
        )
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
    )


def _has_compatible_named_indexes(
    connection: sqlite3.Connection,
    index_contracts: dict[str, _IndexContract],
) -> bool:
    for index_name, (expected_table, expected_columns) in index_contracts.items():
        object_row = connection.execute(
            "SELECT type, tbl_name FROM sqlite_schema WHERE name = ?",
            (index_name,),
        ).fetchone()
        if object_row is None:
            return False
        if str(object_row[0]) != "index" or str(object_row[1]) != expected_table:
            return False
        index_list_rows = tuple(connection.execute(f'PRAGMA index_list("{expected_table}")'))
        matching_rows = tuple(row for row in index_list_rows if str(row[1]) == index_name)
        if len(matching_rows) != 1 or bool(matching_rows[0][2]) or bool(matching_rows[0][4]):
            return False
        escaped_name = index_name.replace('"', '""')
        index_rows = tuple(connection.execute(f'PRAGMA index_xinfo("{escaped_name}")'))
        actual_columns = tuple(
            (str(row[2]), bool(row[3]), str(row[4]).upper())
            for row in sorted(index_rows, key=lambda row: int(row[0]))
            if len(row) > 5 and int(row[5]) == 1
        )
        if actual_columns != expected_columns:
            return False
    return True


def _tokenize_schema_sql(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character.isspace():
            index += 1
            continue
        if value.startswith("--", index):
            newline = value.find("\n", index + 2)
            index = len(value) if newline < 0 else newline + 1
            continue
        if value.startswith("/*", index):
            end = value.find("*/", index + 2)
            index = len(value) if end < 0 else end + 2
            continue
        if character == "'":
            token, index = _consume_quoted_schema_token(value, index, "'", "STRING")
            tokens.append(token)
            continue
        if character in {'"', "`"}:
            token, index = _consume_quoted_schema_token(
                value,
                index,
                character,
                "QUOTED_IDENTIFIER",
            )
            tokens.append(token)
            continue
        if character == "[":
            end = value.find("]", index + 1)
            if end < 0:
                return ("INVALID_SCHEMA_SQL",)
            tokens.append(f"QUOTED_IDENTIFIER:{value[index + 1 : end]}")
            index = end + 1
            continue
        if character.isalnum() or character in {"_", "$"}:
            end = index + 1
            while end < len(value) and (value[end].isalnum() or value[end] in {"_", "$"}):
                end += 1
            tokens.append(value[index:end].upper())
            index = end
            continue
        if value[index : index + 3] == "->>":
            tokens.append("->>")
            index += 3
            continue
        two_character = value[index : index + 2]
        if two_character in {"<=", ">=", "<>", "!=", "==", "||", "->"}:
            tokens.append(two_character)
            index += 2
            continue
        tokens.append(character)
        index += 1
    return tuple(tokens)


def _consume_quoted_schema_token(
    value: str,
    start: int,
    quote: str,
    token_kind: str,
) -> tuple[str, int]:
    content: list[str] = []
    index = start + 1
    while index < len(value):
        character = value[index]
        if character == quote:
            if index + 1 < len(value) and value[index + 1] == quote:
                content.append(quote)
                index += 2
                continue
            normalized = "".join(content)
            if token_kind == "QUOTED_IDENTIFIER":
                normalized = normalized.upper()
            return f"{token_kind}:{normalized}", index + 1
        content.append(character)
        index += 1
    return "INVALID_SCHEMA_SQL", len(value)


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
