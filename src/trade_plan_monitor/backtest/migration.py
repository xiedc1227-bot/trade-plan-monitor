"""Read-only inventory and fail-closed authorization for backtest migrations."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from trade_plan_monitor.backtest.time import normalize_market_metadata_timestamp

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SQLITE_HEADER = b"SQLite format 3\x00"
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_MAX_INVENTORIED_IDENTITIES = 10_000

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
    "market_index_artifact": {
        "artifact_hash": ("TEXT", False, None, 1),
        "natural_key": ("TEXT", True, None, 0),
        "index_code": ("TEXT", True, None, 0),
        "interval": ("TEXT", True, None, 0),
        "bar_at": ("TEXT", True, None, 0),
        "provider_revision": ("INTEGER", True, None, 0),
        "content_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "market_index_head": {
        "natural_key": ("TEXT", False, None, 1),
        "artifact_hash": ("TEXT", True, None, 0),
        "index_code": ("TEXT", True, None, 0),
        "interval": ("TEXT", True, None, 0),
        "bar_at": ("TEXT", True, None, 0),
        "revision": ("INTEGER", True, None, 0),
        "updated_at": ("TEXT", True, None, 0),
    },
    "market_dataset_index_item": {
        "dataset_hash": ("TEXT", True, None, 1),
        "natural_key": ("TEXT", True, None, 2),
        "artifact_hash": ("TEXT", True, None, 0),
        "index_code": ("TEXT", True, None, 0),
        "interval": ("TEXT", True, None, 0),
        "bar_at": ("TEXT", True, None, 0),
        "provider_revision": ("INTEGER", True, None, 0),
    },
}
_MARKET_TABLES = frozenset(_MARKET_COLUMN_CONTRACTS)
_MARKET_INDEX_EXTENSION_TABLES = (
    "market_index_artifact",
    "market_index_head",
    "market_dataset_index_item",
)
_MARKET_METADATA_COLUMNS = (
    ("market_artifact", "created_at"),
    ("market_head", "updated_at"),
    ("market_minute_artifact", "created_at"),
    ("market_minute_head", "updated_at"),
    ("market_dataset", "created_at"),
    ("market_index_artifact", "created_at"),
    ("market_index_head", "updated_at"),
)
_RESULT_COLUMN_CONTRACTS: dict[str, dict[str, _ColumnContract]] = {
    "backtest_run": {
        "run_id": ("TEXT", False, None, 1),
        "plan_sha256": ("TEXT", True, None, 0),
        "dataset_hash": ("TEXT", True, None, 0),
        "status": ("TEXT", True, None, 0),
        "completed_at": ("TEXT", True, None, 0),
        "pinned": ("INTEGER", True, "0", 0),
        "pin_revision": ("INTEGER", True, "0", 0),
        "catalog_revision": ("INTEGER", False, None, 0),
        "materialized": ("INTEGER", True, "1", 0),
        "publication_fill_count": ("INTEGER", False, None, 0),
        "publication_detail_count": ("INTEGER", False, None, 0),
        "publication_fill_set_hash": ("TEXT", False, None, 0),
        "publication_detail_set_hash": ("TEXT", False, None, 0),
        "summary_domain": ("TEXT", True, "'backtest-run-summary-v1'", 0),
        "publication_fill_set_domain": ("TEXT", False, None, 0),
        "publication_detail_set_domain": ("TEXT", False, None, 0),
        "summary_hash": ("TEXT", True, None, 0),
        "summary_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
        "stage_revision": ("INTEGER", True, "1", 0),
        "decision_original_count": ("INTEGER", False, None, 0),
        "decision_expired_at": ("TEXT", False, None, 0),
        "signal_original_count": ("INTEGER", False, None, 0),
        "signal_expired_at": ("TEXT", False, None, 0),
        "outcome_original_count": ("INTEGER", False, None, 0),
        "outcome_expired_at": ("TEXT", False, None, 0),
        "daily_equity_original_count": ("INTEGER", False, None, 0),
        "daily_equity_expired_at": ("TEXT", False, None, 0),
        "pin_idempotency_json": ("TEXT", True, "'{}'", 0),
    },
    "backtest_fill": {
        "fill_id": ("TEXT", False, None, 1),
        "run_id": ("TEXT", True, None, 0),
        "filled_at": ("TEXT", True, None, 0),
        "content_domain": ("TEXT", True, "'backtest-fill-record-v1'", 0),
        "content_hash": ("TEXT", True, None, 0),
        "payload_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "backtest_detail": {
        "detail_id": ("TEXT", False, None, 1),
        "run_id": ("TEXT", True, None, 0),
        "kind": ("TEXT", True, None, 0),
        "event_at": ("TEXT", True, None, 0),
        "content_domain": ("TEXT", True, "'backtest-detail-record-v1'", 0),
        "content_hash": ("TEXT", True, None, 0),
        "payload_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "backtest_plan_snapshot": {
        "plan_sha256": ("TEXT", False, None, 1),
        "snapshot_json": ("TEXT", True, None, 0),
        "created_at": ("TEXT", True, None, 0),
    },
    "backtest_run_input": {
        "run_id": ("TEXT", False, None, 1),
        "plan_sha256": ("TEXT", True, None, 0),
        "input_hash": ("TEXT", True, None, 0),
        "input_json": ("TEXT", True, None, 0),
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
    "market_index_artifact": frozenset(),
    "market_index_head": frozenset(
        {
            (
                "artifact_hash",
                "market_index_artifact",
                "artifact_hash",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            )
        }
    ),
    "market_dataset_index_item": frozenset(
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
                "market_index_artifact",
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
    "backtest_plan_snapshot": frozenset(),
    "backtest_run_input": frozenset(
        {
            (
                "plan_sha256",
                "backtest_plan_snapshot",
                "plan_sha256",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            )
        }
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
    "market_index_artifact": """
        CREATE TABLE market_index_artifact (
            artifact_hash TEXT PRIMARY KEY,
            natural_key TEXT NOT NULL,
            index_code TEXT NOT NULL,
            interval TEXT NOT NULL CHECK (interval IN ('FIVE_MINUTE', 'OFFICIAL_DAILY')),
            bar_at TEXT NOT NULL,
            provider_revision INTEGER NOT NULL CHECK (provider_revision >= 1),
            content_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "market_index_head": """
        CREATE TABLE market_index_head (
            natural_key TEXT PRIMARY KEY,
            artifact_hash TEXT NOT NULL
                REFERENCES market_index_artifact (artifact_hash) ON DELETE RESTRICT,
            index_code TEXT NOT NULL,
            interval TEXT NOT NULL CHECK (interval IN ('FIVE_MINUTE', 'OFFICIAL_DAILY')),
            bar_at TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            updated_at TEXT NOT NULL
        )
    """,
    "market_dataset_index_item": """
        CREATE TABLE market_dataset_index_item (
            dataset_hash TEXT NOT NULL
                REFERENCES market_dataset (dataset_hash) ON DELETE RESTRICT,
            natural_key TEXT NOT NULL,
            artifact_hash TEXT NOT NULL
                REFERENCES market_index_artifact (artifact_hash) ON DELETE RESTRICT,
            index_code TEXT NOT NULL,
            interval TEXT NOT NULL CHECK (interval IN ('FIVE_MINUTE', 'OFFICIAL_DAILY')),
            bar_at TEXT NOT NULL,
            provider_revision INTEGER NOT NULL CHECK (provider_revision >= 1),
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
            summary_domain TEXT NOT NULL DEFAULT 'backtest-run-summary-v1' CHECK (
                summary_domain IN ('backtest-run-summary-v1', 'backtest-run-summary-v2')
            ),
            publication_fill_set_domain TEXT CHECK (
                publication_fill_set_domain IS NULL OR publication_fill_set_domain IN (
                    'backtest-fill-set-v1', 'backtest-fill-set-v2'
                )
            ),
            publication_detail_set_domain TEXT CHECK (
                publication_detail_set_domain IS NULL OR publication_detail_set_domain IN (
                    'backtest-detail-set-v1', 'backtest-detail-set-v2'
                )
            ),
            summary_hash TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            stage_revision INTEGER NOT NULL DEFAULT 1 CHECK (stage_revision >= 1),
            pin_revision INTEGER NOT NULL DEFAULT 0 CHECK (pin_revision >= 0),
            catalog_revision INTEGER
                CHECK (catalog_revision IS NULL OR catalog_revision >= 1),
            decision_original_count INTEGER
                CHECK (decision_original_count IS NULL OR decision_original_count >= 0),
            decision_expired_at TEXT,
            signal_original_count INTEGER
                CHECK (signal_original_count IS NULL OR signal_original_count >= 0),
            signal_expired_at TEXT,
            outcome_original_count INTEGER
                CHECK (outcome_original_count IS NULL OR outcome_original_count >= 0),
            outcome_expired_at TEXT,
            daily_equity_original_count INTEGER
                CHECK (daily_equity_original_count IS NULL OR daily_equity_original_count >= 0),
            daily_equity_expired_at TEXT,
            pin_idempotency_json TEXT NOT NULL DEFAULT '{}'
        )
    """,
    "backtest_fill": """
        CREATE TABLE backtest_fill (
            fill_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
            filled_at TEXT NOT NULL,
            content_domain TEXT NOT NULL DEFAULT 'backtest-fill-record-v1' CHECK (
                content_domain IN ('backtest-fill-record-v1', 'backtest-fill-record-v2')
            ),
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
            content_domain TEXT NOT NULL DEFAULT 'backtest-detail-record-v1' CHECK (
                content_domain IN ('backtest-detail-record-v1', 'backtest-detail-record-v2')
            ),
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "backtest_plan_snapshot": """
        CREATE TABLE backtest_plan_snapshot (
            plan_sha256 TEXT PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "backtest_run_input": """
        CREATE TABLE backtest_run_input (
            run_id TEXT PRIMARY KEY,
            plan_sha256 TEXT NOT NULL
                REFERENCES backtest_plan_snapshot (plan_sha256) ON DELETE RESTRICT,
            input_hash TEXT NOT NULL,
            input_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
}

_RESULT_TRIGGER_SQL_CONTRACTS = {
    "trg_backtest_run_completed_only_insert": """
        CREATE TRIGGER trg_backtest_run_completed_only_insert
        BEFORE INSERT ON backtest_run
        WHEN NEW.status <> 'COMPLETED'
        BEGIN
            SELECT RAISE(ABORT, 'BACKTEST_RESULTS_COMPLETED_ONLY');
        END
    """,
    "trg_backtest_run_completed_only_update": """
        CREATE TRIGGER trg_backtest_run_completed_only_update
        BEFORE UPDATE OF status ON backtest_run
        WHEN NEW.status <> 'COMPLETED'
        BEGIN
            SELECT RAISE(ABORT, 'BACKTEST_RESULTS_COMPLETED_ONLY');
        END
    """,
    "trg_backtest_fill_stage_revision_insert": """
        CREATE TRIGGER trg_backtest_fill_stage_revision_insert
        AFTER INSERT ON backtest_fill
        WHEN (SELECT materialized FROM backtest_run WHERE run_id = NEW.run_id) = 0
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id = NEW.run_id;
        END
    """,
    "trg_backtest_fill_stage_revision_update": """
        CREATE TRIGGER trg_backtest_fill_stage_revision_update
        AFTER UPDATE OF run_id, filled_at, content_domain, content_hash, payload_json
        ON backtest_fill
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id IN (OLD.run_id, NEW.run_id) AND materialized = 0;
        END
    """,
    "trg_backtest_fill_stage_revision_delete": """
        CREATE TRIGGER trg_backtest_fill_stage_revision_delete
        AFTER DELETE ON backtest_fill
        WHEN (SELECT materialized FROM backtest_run WHERE run_id = OLD.run_id) = 0
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id = OLD.run_id;
        END
    """,
    "trg_backtest_detail_stage_revision_insert": """
        CREATE TRIGGER trg_backtest_detail_stage_revision_insert
        AFTER INSERT ON backtest_detail
        WHEN (SELECT materialized FROM backtest_run WHERE run_id = NEW.run_id) = 0
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id = NEW.run_id;
        END
    """,
    "trg_backtest_detail_stage_revision_update": """
        CREATE TRIGGER trg_backtest_detail_stage_revision_update
        AFTER UPDATE OF run_id, kind, event_at, content_domain, content_hash, payload_json
        ON backtest_detail
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id IN (OLD.run_id, NEW.run_id) AND materialized = 0;
        END
    """,
    "trg_backtest_detail_stage_revision_delete": """
        CREATE TRIGGER trg_backtest_detail_stage_revision_delete
        AFTER DELETE ON backtest_detail
        WHEN (SELECT materialized FROM backtest_run WHERE run_id = OLD.run_id) = 0
        BEGIN
            UPDATE backtest_run SET stage_revision = stage_revision + 1
            WHERE run_id = OLD.run_id;
        END
    """,
}

_BT017_RESULT_COLUMN_CONTRACTS = {
    table: dict(columns) for table, columns in _RESULT_COLUMN_CONTRACTS.items()
}
for _column_name in (
    "pin_revision",
    "catalog_revision",
    "decision_original_count",
    "decision_expired_at",
    "signal_original_count",
    "signal_expired_at",
    "outcome_original_count",
    "outcome_expired_at",
    "daily_equity_original_count",
    "daily_equity_expired_at",
    "pin_idempotency_json",
):
    del _BT017_RESULT_COLUMN_CONTRACTS["backtest_run"][_column_name]
_BT017_RESULT_TABLE_SQL_CONTRACTS = dict(_RESULT_TABLE_SQL_CONTRACTS)
_BT017_RESULT_TABLE_SQL_CONTRACTS["backtest_run"] = _RESULT_TABLE_SQL_CONTRACTS[
    "backtest_run"
].replace(
    """,\n            pin_revision INTEGER NOT NULL DEFAULT 0 CHECK (pin_revision >= 0),
            catalog_revision INTEGER
                CHECK (catalog_revision IS NULL OR catalog_revision >= 1),
            decision_original_count INTEGER
                CHECK (decision_original_count IS NULL OR decision_original_count >= 0),
            decision_expired_at TEXT,
            signal_original_count INTEGER
                CHECK (signal_original_count IS NULL OR signal_original_count >= 0),
            signal_expired_at TEXT,
            outcome_original_count INTEGER
                CHECK (outcome_original_count IS NULL OR outcome_original_count >= 0),
            outcome_expired_at TEXT,
            daily_equity_original_count INTEGER
                CHECK (daily_equity_original_count IS NULL OR daily_equity_original_count >= 0),
            daily_equity_expired_at TEXT,
            pin_idempotency_json TEXT NOT NULL DEFAULT '{}'\n""",
    "",
)
_BT017_RESULT_FOREIGN_KEY_CONTRACTS = {
    table: contracts
    for table, contracts in _RESULT_FOREIGN_KEY_CONTRACTS.items()
    if table in _BT017_RESULT_COLUMN_CONTRACTS
}
_BT017_RESULT_TRIGGER_SQL_CONTRACTS = dict(_RESULT_TRIGGER_SQL_CONTRACTS)

_BT016_RESULT_COLUMN_CONTRACTS = {
    table: dict(columns) for table, columns in _BT017_RESULT_COLUMN_CONTRACTS.items()
}
del _BT016_RESULT_COLUMN_CONTRACTS["backtest_run"]["stage_revision"]
_BT016_RESULT_TABLE_SQL_CONTRACTS = {
    **_BT017_RESULT_TABLE_SQL_CONTRACTS,
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
            summary_domain TEXT NOT NULL DEFAULT 'backtest-run-summary-v1' CHECK (
                summary_domain IN ('backtest-run-summary-v1', 'backtest-run-summary-v2')
            ),
            publication_fill_set_domain TEXT CHECK (
                publication_fill_set_domain IS NULL OR publication_fill_set_domain IN (
                    'backtest-fill-set-v1', 'backtest-fill-set-v2'
                )
            ),
            publication_detail_set_domain TEXT CHECK (
                publication_detail_set_domain IS NULL OR publication_detail_set_domain IN (
                    'backtest-detail-set-v1', 'backtest-detail-set-v2'
                )
            ),
            summary_hash TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
}
_BT016_RESULT_TRIGGER_SQL_CONTRACTS = {
    name: sql
    for name, sql in _BT017_RESULT_TRIGGER_SQL_CONTRACTS.items()
    if name.startswith("trg_backtest_run_completed_only_")
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
    "ix_market_index_artifact_identity": (
        "market_index_artifact",
        (
            ("natural_key", False, "BINARY"),
            ("provider_revision", False, "BINARY"),
        ),
    ),
    "ix_market_index_head_code_time": (
        "market_index_head",
        (
            ("index_code", False, "BINARY"),
            ("bar_at", False, "BINARY"),
            ("interval", False, "BINARY"),
        ),
    ),
    "ix_market_dataset_index_item_lookup": (
        "market_dataset_index_item",
        (
            ("dataset_hash", False, "BINARY"),
            ("index_code", False, "BINARY"),
            ("bar_at", False, "BINARY"),
            ("interval", False, "BINARY"),
        ),
    ),
}
_MARKET_INDEX_EXTENSION_INDEXES = frozenset(
    {
        "ix_market_index_artifact_identity",
        "ix_market_index_head_code_time",
        "ix_market_dataset_index_item_lookup",
    }
)
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
_BT017_RESULT_INDEX_CONTRACTS = dict(_RESULT_INDEX_CONTRACTS)

# BT020 keeps the prior completed-result schema as a readable compatibility state while
# defining the exact additive job schema used by the shared results database. Existing
# databases require the verified migration workflow; a fresh job repository creates both
# domains before acknowledging any submission.
_BT019_RESULT_COLUMN_CONTRACTS = {
    table: dict(columns) for table, columns in _RESULT_COLUMN_CONTRACTS.items()
}
_BT019_RESULT_TABLE_SQL_CONTRACTS = dict(_RESULT_TABLE_SQL_CONTRACTS)
_BT019_RESULT_FOREIGN_KEY_CONTRACTS = dict(_RESULT_FOREIGN_KEY_CONTRACTS)
_BT019_RESULT_INDEX_CONTRACTS = dict(_RESULT_INDEX_CONTRACTS)
_BT019_RESULT_TRIGGER_SQL_CONTRACTS = dict(_RESULT_TRIGGER_SQL_CONTRACTS)

_JOB_COLUMN_CONTRACTS: dict[str, dict[str, _ColumnContract]] = {
    "backtest_job": {
        "job_id": ("TEXT", False, None, 1),
        "kind": ("TEXT", True, None, 0),
        "status": ("TEXT", True, None, 0),
        "request_hash": ("TEXT", True, None, 0),
        "operation_hash": ("TEXT", True, None, 0),
        "request_json": ("TEXT", True, None, 0),
        "run_id": ("TEXT", False, None, 0),
        "dataset_hash": ("TEXT", False, None, 0),
        "phase": ("TEXT", True, None, 0),
        "progress_unit": ("TEXT", True, None, 0),
        "completed_units": ("INTEGER", True, "0", 0),
        "total_units": ("INTEGER", False, None, 0),
        "attempt": ("INTEGER", True, "0", 0),
        "revision": ("INTEGER", True, "0", 0),
        "membership_revision": ("INTEGER", True, "0", 0),
        "created_at": ("TEXT", True, None, 0),
        "started_at": ("TEXT", False, None, 0),
        "updated_at": ("TEXT", True, None, 0),
        "finished_at": ("TEXT", False, None, 0),
        "cancel_requested_at": ("TEXT", False, None, 0),
        "reused": ("INTEGER", True, "0", 0),
        "result_json": ("TEXT", False, None, 0),
        "error_code": ("TEXT", False, None, 0),
        "error_message": ("TEXT", False, None, 0),
        "network_authorized_at": ("TEXT", False, None, 0),
        "request_id": ("TEXT", False, None, 0),
        "claim_token": ("TEXT", False, None, 0),
        "lease_expires_at": ("TEXT", False, None, 0),
        "heartbeat_at": ("TEXT", False, None, 0),
        "progress_updated_at": ("TEXT", False, None, 0),
    },
    "backtest_job_idempotency": {
        "idempotency_key": ("TEXT", False, None, 1),
        "operation": ("TEXT", True, None, 0),
        "request_hash": ("TEXT", True, None, 0),
        "job_id": ("TEXT", False, None, 0),
        "response_json": ("TEXT", False, None, 0),
        "created_at": ("TEXT", True, None, 0),
        "expires_at": ("TEXT", False, None, 0),
    },
    "backtest_job_state": {
        "state_key": ("TEXT", False, None, 1),
        "membership_revision": ("INTEGER", True, "0", 0),
    },
}
_JOB_TABLE_SQL_CONTRACTS = {
    "backtest_job": """
        CREATE TABLE backtest_job (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (
                kind IN ('DATA_SYNC', 'DATASET_VERIFY', 'BACKTEST_RUN')
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'QUEUED', 'RUNNING', 'CANCEL_REQUESTED',
                    'COMPLETED', 'FAILED', 'CANCELLED'
                )
            ),
            request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
            operation_hash TEXT NOT NULL CHECK (length(operation_hash) = 64),
            request_json TEXT NOT NULL CHECK (
                length(CAST(request_json AS BLOB)) <= 262144
            ),
            run_id TEXT CHECK (run_id IS NULL OR length(run_id) = 64),
            dataset_hash TEXT CHECK (dataset_hash IS NULL OR length(dataset_hash) = 64),
            phase TEXT NOT NULL CHECK (
                phase IN (
                    'QUEUED', 'VALIDATING_INPUT', 'SYNCING_DATA',
                    'VERIFYING_DATASET', 'REPLAYING', 'MATERIALIZING_RESULTS',
                    'FINALIZING', 'TERMINAL'
                )
            ),
            progress_unit TEXT NOT NULL CHECK (
                progress_unit IN ('ITEMS', 'SYMBOL_DAYS', 'EVENTS', 'ROWS')
            ),
            completed_units INTEGER NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
            total_units INTEGER CHECK (
                total_units IS NULL OR total_units >= completed_units
            ),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt BETWEEN 0 AND 3),
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            membership_revision INTEGER NOT NULL DEFAULT 0 CHECK (membership_revision >= 0),
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            cancel_requested_at TEXT,
            reused INTEGER NOT NULL DEFAULT 0 CHECK (reused IN (0, 1)),
            result_json TEXT,
            error_code TEXT CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 128),
            error_message TEXT CHECK (
                error_message IS NULL OR length(error_message) BETWEEN 1 AND 512
            ),
            network_authorized_at TEXT,
            request_id TEXT,
            claim_token TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            progress_updated_at TEXT,
            CHECK (
                (kind = 'BACKTEST_RUN' AND run_id IS NOT NULL AND dataset_hash IS NOT NULL)
                OR (kind <> 'BACKTEST_RUN' AND run_id IS NULL)
            ),
            CHECK (kind <> 'DATA_SYNC' OR dataset_hash IS NULL),
            CHECK (
                (kind = 'DATA_SYNC' AND network_authorized_at IS NOT NULL
                    AND request_id IS NOT NULL)
                OR (kind <> 'DATA_SYNC' AND network_authorized_at IS NULL
                    AND request_id IS NULL)
            ),
            CHECK (reused = 0 OR status = 'COMPLETED'),
            CHECK (
                (status IN ('COMPLETED', 'FAILED', 'CANCELLED'))
                = (finished_at IS NOT NULL)
            ),
            CHECK ((status = 'COMPLETED') = (result_json IS NOT NULL)),
            CHECK ((error_code IS NULL) = (error_message IS NULL))
        )
    """,
    "backtest_job_idempotency": """
        CREATE TABLE backtest_job_idempotency (
            idempotency_key TEXT PRIMARY KEY CHECK (
                length(idempotency_key) BETWEEN 1 AND 128
            ),
            operation TEXT NOT NULL CHECK (operation IN ('SUBMIT', 'CANCEL')),
            request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
            job_id TEXT
                REFERENCES backtest_job (job_id) ON DELETE RESTRICT,
            response_json TEXT CHECK (
                response_json IS NULL
                OR length(CAST(response_json AS BLOB)) <= 65536
            ),
            created_at TEXT NOT NULL,
            expires_at TEXT,
            CHECK ((job_id IS NULL) = (response_json IS NULL))
        )
    """,
    "backtest_job_state": """
        CREATE TABLE backtest_job_state (
            state_key TEXT PRIMARY KEY CHECK (state_key = 'GLOBAL'),
            membership_revision INTEGER NOT NULL DEFAULT 0 CHECK (membership_revision >= 0)
        )
    """,
}
_JOB_FOREIGN_KEY_CONTRACTS: dict[str, frozenset[_ForeignKeyContract]] = {
    "backtest_job": frozenset(),
    "backtest_job_idempotency": frozenset(
        {
            (
                "job_id",
                "backtest_job",
                "job_id",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            )
        }
    ),
    "backtest_job_state": frozenset(),
}
_JOB_INDEX_CONTRACTS: dict[str, _IndexContract] = {
    "ix_backtest_job_active_operation": (
        "backtest_job",
        (
            ("operation_hash", False, "BINARY"),
            ("status", False, "BINARY"),
            ("created_at", False, "BINARY"),
            ("job_id", False, "BINARY"),
        ),
    ),
    "ix_backtest_job_queue": (
        "backtest_job",
        (
            ("status", False, "BINARY"),
            ("created_at", False, "BINARY"),
            ("job_id", False, "BINARY"),
        ),
    ),
    "ix_backtest_job_list": (
        "backtest_job",
        (("created_at", True, "BINARY"), ("job_id", True, "BINARY")),
    ),
    "ix_backtest_job_idempotency_expiry": (
        "backtest_job_idempotency",
        (("expires_at", False, "BINARY"), ("idempotency_key", False, "BINARY")),
    ),
}

_RESULT_COLUMN_CONTRACTS = {
    **_BT019_RESULT_COLUMN_CONTRACTS,
    **_JOB_COLUMN_CONTRACTS,
}
_RESULT_TABLE_SQL_CONTRACTS = {
    **_BT019_RESULT_TABLE_SQL_CONTRACTS,
    **_JOB_TABLE_SQL_CONTRACTS,
}
_RESULT_FOREIGN_KEY_CONTRACTS = {
    **_BT019_RESULT_FOREIGN_KEY_CONTRACTS,
    **_JOB_FOREIGN_KEY_CONTRACTS,
}
_RESULT_INDEX_CONTRACTS = {
    **_BT019_RESULT_INDEX_CONTRACTS,
    **_JOB_INDEX_CONTRACTS,
}
_RESULT_TABLES = frozenset(_RESULT_COLUMN_CONTRACTS)


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
    invalid_value_count: int = 0


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
    if "INVALID_MARKET_METADATA_TIMESTAMP" in inventory.migration_reasons:
        raise MigrationPreflightError("INVALID_MARKET_METADATA_TIMESTAMP")
    if "UTC_MARKET_METADATA" in inventory.migration_reasons:
        raise MigrationPreflightError("MARKET_METADATA_REQUIRES_VERIFIED_MIGRATION")
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
    if "INVALID_MARKET_METADATA_TIMESTAMP" in inventory.migration_reasons:
        raise MigrationPreflightError("INVALID_MARKET_METADATA_TIMESTAMP")
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


def migrate_market_metadata(
    inventory: MigrationInventory,
    decision: MigrationDecision,
) -> MigrationInventory:
    """Convert only authorized market operational timestamps to canonical China time."""

    if not isinstance(inventory, MigrationInventory):
        raise TypeError("inventory must be a MigrationInventory")
    if not isinstance(decision, MigrationDecision):
        raise TypeError("decision must be a MigrationDecision")
    if not decision.authorized:
        raise MigrationPreflightError("MARKET_METADATA_MIGRATION_NOT_AUTHORIZED")
    if inventory.database_state is not DatabaseState.CURRENT:
        raise MigrationPreflightError("MARKET_METADATA_REQUIRES_CURRENT_SCHEMA")
    if "INVALID_MARKET_METADATA_TIMESTAMP" in inventory.migration_reasons:
        raise MigrationPreflightError("INVALID_MARKET_METADATA_TIMESTAMP")
    if inventory.migration_reasons != ("UTC_MARKET_METADATA",):
        raise MigrationPreflightError("MARKET_METADATA_MIGRATION_SCOPE_MISMATCH")
    if (
        decision.source_fingerprint != inventory.source_fingerprint.digest
        or decision.migration_reasons != inventory.migration_reasons
        or decision.verified_backup.source_fingerprint != inventory.source_fingerprint.digest
    ):
        raise MigrationPreflightError("MIGRATION_DECISION_SOURCE_MISMATCH")
    if not decision.verified_backup.coordinator_stopped:
        raise MigrationPreflightError("MIGRATION_REQUIRES_STOPPED_COORDINATOR")
    assert_source_unchanged(inventory)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(inventory.database_path, isolation_level=None, timeout=5)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN IMMEDIATE")
        before = _inspect_market(connection, frozenset(inventory.table_names))
        if (
            before["database_state"] is not DatabaseState.CURRENT
            or before["dataset_hash_goldens"] != inventory.dataset_hash_goldens
            or before["utc_metadata"] != inventory.utc_metadata
            or before["migration_reasons"] != inventory.migration_reasons
        ):
            raise MigrationPreflightError("MIGRATION_SOURCE_CHANGED_AFTER_PREFLIGHT")
        for table, column in _MARKET_METADATA_COLUMNS:
            cursor = connection.execute(f'SELECT rowid, "{column}" FROM "{table}" ORDER BY rowid')
            while rows := cursor.fetchmany(1_000):
                updates: list[tuple[str, int, str]] = []
                for rowid, raw_value in rows:
                    try:
                        normalized, converted = normalize_market_metadata_timestamp(raw_value)
                    except (TypeError, ValueError) as error:
                        raise MigrationPreflightError(
                            "INVALID_MARKET_METADATA_TIMESTAMP"
                        ) from error
                    if converted:
                        updates.append((normalized, int(rowid), str(raw_value)))
                if not updates:
                    continue
                connection.executemany(
                    f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ? AND "{column}" = ?',
                    updates,
                )
        after = _inspect_market(connection, frozenset(inventory.table_names))
        if (
            after["database_state"] is not DatabaseState.CURRENT
            or after["dataset_hash_goldens"] != inventory.dataset_hash_goldens
            or after["migration_reasons"]
        ):
            raise MigrationPreflightError("MARKET_METADATA_POST_MIGRATION_MISMATCH")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationPreflightError("MARKET_METADATA_FOREIGN_KEY_CHECK_FAILED")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise MigrationPreflightError("MARKET_METADATA_INTEGRITY_CHECK_FAILED")
        connection.commit()
    except MigrationPreflightError:
        if connection is not None:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()
        raise MigrationPreflightError("MARKET_METADATA_MIGRATION_FAILED") from error
    finally:
        if connection is not None:
            connection.close()

    migrated = inspect_market_database(inventory.database_path)
    if (
        migrated.database_state is not DatabaseState.CURRENT
        or migrated.schema_sha256 != inventory.schema_sha256
        or migrated.table_names != inventory.table_names
        or migrated.dataset_hash_goldens != inventory.dataset_hash_goldens
        or migrated.migration_reasons
    ):
        raise MigrationPreflightError("MARKET_METADATA_POST_MIGRATION_MISMATCH")
    return migrated


def migrate_result_database(
    inventory: MigrationInventory,
    decision: MigrationDecision,
) -> MigrationInventory:
    """Upgrade a verified completed-only result store without changing result identity."""

    if not isinstance(inventory, MigrationInventory):
        raise TypeError("inventory must be a MigrationInventory")
    if not isinstance(decision, MigrationDecision):
        raise TypeError("decision must be a MigrationDecision")
    if inventory.terminal_run_count:
        raise MigrationPreflightError("LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION")
    additive_job_migration = (
        inventory.database_state is DatabaseState.CURRENT
        and "MISSING_BACKTEST_JOB_SCHEMA" in inventory.migration_reasons
    )
    if inventory.database_state is not DatabaseState.LEGACY and not additive_job_migration:
        raise MigrationPreflightError("RESULT_SCHEMA_MIGRATION_REQUIRES_LEGACY_SCHEMA")
    if not decision.authorized:
        raise MigrationPreflightError("RESULT_SCHEMA_MIGRATION_NOT_AUTHORIZED")
    if (
        decision.source_fingerprint != inventory.source_fingerprint.digest
        or decision.migration_reasons != inventory.migration_reasons
        or decision.verified_backup.source_fingerprint != inventory.source_fingerprint.digest
    ):
        raise MigrationPreflightError("MIGRATION_DECISION_SOURCE_MISMATCH")
    if not decision.verified_backup.coordinator_stopped:
        raise MigrationPreflightError("MIGRATION_REQUIRES_STOPPED_COORDINATOR")
    assert_source_unchanged(inventory)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(inventory.database_path, isolation_level=None, timeout=5)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN IMMEDIATE")
        table_names = frozenset(
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        )
        before = _inspect_results(connection, table_names)
        if (
            before["database_state"] is not inventory.database_state
            or before["terminal_run_count"]
            or before["migration_reasons"] != inventory.migration_reasons
            or before["compatibility_only_run_ids"] != inventory.compatibility_only_run_ids
        ):
            raise MigrationPreflightError("MIGRATION_SOURCE_CHANGED_AFTER_PREFLIGHT")
        legacy_v1 = _is_supported_legacy_result_schema(connection, table_names)
        bt016_schema = _is_supported_bt016_result_schema(connection, table_names)
        bt017_schema = _is_supported_bt017_result_schema(connection, table_names)
        bt019_schema = _is_supported_bt019_result_schema(connection, table_names)
        if not legacy_v1 and not bt016_schema and not bt017_schema and not bt019_schema:
            raise MigrationPreflightError("RESULT_SCHEMA_MIGRATION_SCOPE_MISMATCH")
        content_hash = (
            _result_completed_only_content_hash(connection)
            if bt016_schema or bt017_schema or bt019_schema
            else _result_v1_content_hash(connection)
        )
        if bt016_schema:
            _add_result_stage_revision_fence(connection)
        elif legacy_v1:
            _rebuild_completed_only_result_schema(connection)
        if not bt019_schema:
            _add_result_query_metadata(connection)
        create_backtest_job_schema(connection)
        after = _inspect_results(connection, _RESULT_TABLES)
        if (
            after["database_state"] is not DatabaseState.CURRENT
            or after["terminal_run_count"]
            or after["compatibility_only_run_ids"] != inventory.compatibility_only_run_ids
            or (
                _result_completed_only_content_hash(connection)
                if bt016_schema or bt017_schema or bt019_schema
                else _result_v1_content_hash(connection)
            )
            != content_hash
        ):
            raise MigrationPreflightError("RESULT_SCHEMA_POST_MIGRATION_MISMATCH")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationPreflightError("RESULT_SCHEMA_FOREIGN_KEY_CHECK_FAILED")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise MigrationPreflightError("RESULT_SCHEMA_INTEGRITY_CHECK_FAILED")
        connection.commit()
    except MigrationPreflightError:
        if connection is not None:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()
        raise MigrationPreflightError("RESULT_SCHEMA_MIGRATION_FAILED") from error
    finally:
        if connection is not None:
            connection.close()

    migrated = inspect_result_database(inventory.database_path)
    if (
        migrated.database_state is not DatabaseState.CURRENT
        or migrated.terminal_run_count
        or migrated.compatibility_only_run_ids != inventory.compatibility_only_run_ids
        or migrated.requires_schema_migration
    ):
        raise MigrationPreflightError("RESULT_SCHEMA_POST_MIGRATION_MISMATCH")
    return migrated


def _is_supported_legacy_result_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> bool:
    if table_names != frozenset({"backtest_run", "backtest_fill", "backtest_detail"}):
        return False
    if connection.execute("SELECT 1 FROM sqlite_schema WHERE type = 'trigger'").fetchone():
        return False
    required = {
        "backtest_run": {
            "run_id",
            "plan_sha256",
            "dataset_hash",
            "status",
            "completed_at",
            "pinned",
            "summary_hash",
            "summary_json",
            "created_at",
        },
        "backtest_fill": {
            "fill_id",
            "run_id",
            "filled_at",
            "content_hash",
            "payload_json",
            "created_at",
        },
        "backtest_detail": {
            "detail_id",
            "run_id",
            "kind",
            "event_at",
            "content_hash",
            "payload_json",
            "created_at",
        },
    }
    optional_run = {
        "materialized",
        "publication_fill_count",
        "publication_detail_count",
        "publication_fill_set_hash",
        "publication_detail_set_hash",
    }
    for table, required_columns in required.items():
        columns = set(_table_columns(connection, table))
        allowed = required_columns | (optional_run if table == "backtest_run" else set())
        if not required_columns <= columns or not columns <= allowed:
            return False
    return True


def _is_supported_bt016_result_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> bool:
    return _has_required_schema(
        connection,
        table_names,
        column_contracts=_BT016_RESULT_COLUMN_CONTRACTS,
        foreign_key_contracts=_BT017_RESULT_FOREIGN_KEY_CONTRACTS,
        table_sql_contracts=_BT016_RESULT_TABLE_SQL_CONTRACTS,
        index_contracts=_BT017_RESULT_INDEX_CONTRACTS,
        trigger_sql_contracts=_BT016_RESULT_TRIGGER_SQL_CONTRACTS,
    )


def _is_supported_bt017_result_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> bool:
    return _has_required_schema(
        connection,
        table_names,
        column_contracts=_BT017_RESULT_COLUMN_CONTRACTS,
        foreign_key_contracts=_BT017_RESULT_FOREIGN_KEY_CONTRACTS,
        table_sql_contracts=_BT017_RESULT_TABLE_SQL_CONTRACTS,
        index_contracts=_BT017_RESULT_INDEX_CONTRACTS,
        trigger_sql_contracts=_BT017_RESULT_TRIGGER_SQL_CONTRACTS,
    )


def _is_supported_bt019_result_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> bool:
    return _has_required_schema(
        connection,
        table_names,
        column_contracts=_BT019_RESULT_COLUMN_CONTRACTS,
        foreign_key_contracts=_BT019_RESULT_FOREIGN_KEY_CONTRACTS,
        table_sql_contracts=_BT019_RESULT_TABLE_SQL_CONTRACTS,
        index_contracts=_BT019_RESULT_INDEX_CONTRACTS,
        trigger_sql_contracts=_BT019_RESULT_TRIGGER_SQL_CONTRACTS,
    )


def _add_result_stage_revision_fence(connection: sqlite3.Connection) -> None:
    connection.execute(
        "ALTER TABLE backtest_run ADD COLUMN stage_revision "
        "INTEGER NOT NULL DEFAULT 1 CHECK (stage_revision >= 1)"
    )
    for name, statement in _RESULT_TRIGGER_SQL_CONTRACTS.items():
        if name not in _BT016_RESULT_TRIGGER_SQL_CONTRACTS:
            connection.execute(statement)


def _add_result_query_metadata(connection: sqlite3.Connection) -> None:
    for definition in (
        "pin_revision INTEGER NOT NULL DEFAULT 0 CHECK (pin_revision >= 0)",
        "catalog_revision INTEGER CHECK (catalog_revision IS NULL OR catalog_revision >= 1)",
        "decision_original_count INTEGER "
        "CHECK (decision_original_count IS NULL OR decision_original_count >= 0)",
        "decision_expired_at TEXT",
        "signal_original_count INTEGER "
        "CHECK (signal_original_count IS NULL OR signal_original_count >= 0)",
        "signal_expired_at TEXT",
        "outcome_original_count INTEGER "
        "CHECK (outcome_original_count IS NULL OR outcome_original_count >= 0)",
        "outcome_expired_at TEXT",
        "daily_equity_original_count INTEGER "
        "CHECK (daily_equity_original_count IS NULL OR daily_equity_original_count >= 0)",
        "daily_equity_expired_at TEXT",
        "pin_idempotency_json TEXT NOT NULL DEFAULT '{}'",
    ):
        connection.execute(f"ALTER TABLE backtest_run ADD COLUMN {definition}")
    coverage_fields = (
        ("DAILY_EQUITY", "dailyEquityCount"),
        ("DECISION", "decisionCount"),
        ("EXECUTION_OUTCOME", "outcomeCount"),
        ("SIGNAL", "signalCount"),
    )
    rows = connection.execute(
        """
        SELECT run.run_id, run.summary_json, run.publication_detail_count
        FROM backtest_run AS run
        JOIN backtest_run_input AS input ON input.run_id = run.run_id
        WHERE run.materialized = 1
          AND run.summary_domain = 'backtest-run-summary-v2'
        ORDER BY run.created_at, run.run_id
        """
    ).fetchall()
    for catalog_revision, (
        run_id_value,
        summary_json,
        publication_detail_count,
    ) in enumerate(rows, start=1):
        run_id = str(run_id_value)
        try:
            payload = json.loads(str(summary_json))
            coverage = payload["coverage"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise MigrationPreflightError(
                "RESULT_QUERY_METADATA_REQUIRES_CANONICAL_COVERAGE"
            ) from error
        if not isinstance(coverage, dict):
            raise MigrationPreflightError("RESULT_QUERY_METADATA_REQUIRES_CANONICAL_COVERAGE")
        counts: list[tuple[str, int]] = []
        for kind, field in coverage_fields:
            count = coverage.get(field)
            if type(count) is not int or count < 0:
                raise MigrationPreflightError("RESULT_QUERY_METADATA_REQUIRES_CANONICAL_COVERAGE")
            if kind == "DAILY_EQUITY" and count > 2_000:
                raise MigrationPreflightError("RESULT_EQUITY_POINT_LIMIT_EXCEEDED")
            counts.append((kind, count))
        if publication_detail_count is None or int(publication_detail_count) != sum(
            count for _kind, count in counts
        ):
            raise MigrationPreflightError("RESULT_QUERY_METADATA_COUNT_MISMATCH")
        actual = {
            str(kind): int(count)
            for kind, count in connection.execute(
                "SELECT kind, COUNT(*) FROM backtest_detail WHERE run_id = ? GROUP BY kind",
                (run_id,),
            ).fetchall()
        }
        if any(kind not in dict(coverage_fields) for kind in actual) or tuple(
            (kind, actual.get(kind, 0)) for kind, _field in coverage_fields
        ) != tuple(counts):
            raise MigrationPreflightError("RESULT_QUERY_METADATA_COUNT_MISMATCH")
        count_by_kind = dict(counts)
        connection.execute(
            """
            UPDATE backtest_run SET
                catalog_revision = ?,
                decision_original_count = ?, signal_original_count = ?,
                outcome_original_count = ?, daily_equity_original_count = ?
            WHERE run_id = ?
            """,
            (
                catalog_revision,
                count_by_kind["DECISION"],
                count_by_kind["SIGNAL"],
                count_by_kind["EXECUTION_OUTCOME"],
                count_by_kind["DAILY_EQUITY"],
                run_id,
            ),
        )


def _rebuild_completed_only_result_schema(connection: sqlite3.Connection) -> None:
    run_columns = set(_table_columns(connection, "backtest_run"))
    for index_name in _BT017_RESULT_INDEX_CONTRACTS:
        connection.execute(f'DROP INDEX IF EXISTS "{index_name}"')
    for table in ("backtest_detail", "backtest_fill", "backtest_run"):
        connection.execute(f'ALTER TABLE "{table}" RENAME TO "{table}_bt016_v1"')
    for table in (
        "backtest_run",
        "backtest_plan_snapshot",
        "backtest_run_input",
        "backtest_fill",
        "backtest_detail",
    ):
        connection.execute(_BT017_RESULT_TABLE_SQL_CONTRACTS[table])
    optional = {
        name: name if name in run_columns else default
        for name, default in (
            ("materialized", "1"),
            ("publication_fill_count", "NULL"),
            ("publication_detail_count", "NULL"),
            ("publication_fill_set_hash", "NULL"),
            ("publication_detail_set_hash", "NULL"),
        )
    }
    connection.execute(
        f"""
        INSERT INTO backtest_run (
            run_id, plan_sha256, dataset_hash, status, completed_at, pinned,
            materialized, publication_fill_count, publication_detail_count,
            publication_fill_set_hash, publication_detail_set_hash,
            summary_domain, publication_fill_set_domain,
            publication_detail_set_domain, summary_hash, summary_json, created_at
        )
        SELECT
            run_id, plan_sha256, dataset_hash, status, completed_at, pinned,
            {optional["materialized"]}, {optional["publication_fill_count"]},
            {optional["publication_detail_count"]}, {optional["publication_fill_set_hash"]},
            {optional["publication_detail_set_hash"]}, 'backtest-run-summary-v1',
            CASE WHEN {optional["publication_fill_set_hash"]} IS NULL THEN NULL
                 ELSE 'backtest-fill-set-v1' END,
            CASE WHEN {optional["publication_detail_set_hash"]} IS NULL THEN NULL
                 ELSE 'backtest-detail-set-v1' END,
            summary_hash, summary_json, created_at
        FROM backtest_run_bt016_v1
        """
    )
    connection.execute(
        """
        INSERT INTO backtest_fill (
            fill_id, run_id, filled_at, content_domain, content_hash, payload_json, created_at
        )
        SELECT fill_id, run_id, filled_at, 'backtest-fill-record-v1',
               content_hash, payload_json, created_at
        FROM backtest_fill_bt016_v1
        """
    )
    connection.execute(
        """
        INSERT INTO backtest_detail (
            detail_id, run_id, kind, event_at, content_domain,
            content_hash, payload_json, created_at
        )
        SELECT detail_id, run_id, kind, event_at, 'backtest-detail-record-v1',
               content_hash, payload_json, created_at
        FROM backtest_detail_bt016_v1
        """
    )
    for table in ("backtest_detail_bt016_v1", "backtest_fill_bt016_v1", "backtest_run_bt016_v1"):
        connection.execute(f'DROP TABLE "{table}"')
    _create_result_indexes_and_triggers(connection)


def _create_result_indexes_and_triggers(connection: sqlite3.Connection) -> None:
    for statement in (
        "CREATE INDEX ix_backtest_run_retention "
        "ON backtest_run (status, pinned, completed_at DESC, run_id DESC)",
        "CREATE INDEX ix_backtest_run_retention_v2 "
        "ON backtest_run (status, pinned, materialized, created_at DESC, run_id DESC)",
        "CREATE INDEX ix_backtest_fill_run ON backtest_fill (run_id, filled_at, fill_id)",
        "CREATE INDEX ix_backtest_detail_retention ON backtest_detail (kind, run_id, detail_id)",
        "CREATE INDEX ix_backtest_detail_run_event "
        "ON backtest_detail (run_id, event_at, detail_id)",
        *_BT017_RESULT_TRIGGER_SQL_CONTRACTS.values(),
    ):
        connection.execute(statement)


def create_backtest_job_schema(connection: sqlite3.Connection) -> None:
    """Create the exact additive BT020 tables inside an already-authorized transaction."""

    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    table_names = frozenset(
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    )
    present = table_names & frozenset(_JOB_COLUMN_CONTRACTS)
    if present:
        if present == frozenset(_JOB_COLUMN_CONTRACTS):
            return
        raise MigrationPreflightError("PARTIAL_BACKTEST_JOB_SCHEMA")
    for statement in _JOB_TABLE_SQL_CONTRACTS.values():
        connection.execute(statement)
    for statement in (
        "CREATE INDEX ix_backtest_job_active_operation "
        "ON backtest_job (operation_hash, status, created_at, job_id)",
        "CREATE INDEX ix_backtest_job_queue ON backtest_job (status, created_at, job_id)",
        "CREATE INDEX ix_backtest_job_list ON backtest_job (created_at DESC, job_id DESC)",
        "CREATE INDEX ix_backtest_job_idempotency_expiry "
        "ON backtest_job_idempotency (expires_at, idempotency_key)",
    ):
        connection.execute(statement)
    connection.execute(
        "INSERT INTO backtest_job_state (state_key, membership_revision) VALUES ('GLOBAL', 0)"
    )


def create_market_index_schema(connection: sqlite3.Connection) -> None:
    """Transactionally expand one exact pre-index market schema with empty index tables."""

    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    table_names = frozenset(
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    )
    present = table_names & frozenset(_MARKET_INDEX_EXTENSION_TABLES)
    if present:
        raise MigrationPreflightError("PARTIAL_MARKET_INDEX_SCHEMA")
    if not _is_supported_pre_index_market_schema(connection, table_names):
        raise MigrationPreflightError("MARKET_INDEX_SCHEMA_EXPANSION_SOURCE_CHANGED")
    for table in _MARKET_INDEX_EXTENSION_TABLES:
        connection.execute(_MARKET_TABLE_SQL_CONTRACTS[table])
    for statement in (
        "CREATE INDEX ix_market_index_artifact_identity "
        "ON market_index_artifact (natural_key, provider_revision)",
        "CREATE INDEX ix_market_index_head_code_time "
        "ON market_index_head (index_code, bar_at, interval)",
        "CREATE INDEX ix_market_dataset_index_item_lookup "
        "ON market_dataset_index_item (dataset_hash, index_code, bar_at, interval)",
    ):
        connection.execute(statement)


def _result_v1_content_hash(connection: sqlite3.Connection) -> str:
    digest = sha256()
    for query in (
        "SELECT run_id, plan_sha256, dataset_hash, status, completed_at, pinned, "
        "summary_hash, summary_json, created_at FROM backtest_run ORDER BY run_id",
        "SELECT fill_id, run_id, filled_at, content_hash, payload_json, created_at "
        "FROM backtest_fill ORDER BY fill_id",
        "SELECT detail_id, run_id, kind, event_at, content_hash, payload_json, created_at "
        "FROM backtest_detail ORDER BY detail_id",
    ):
        cursor = connection.execute(query)
        while rows := cursor.fetchmany(1_000):
            for row in rows:
                for value in row:
                    _hash_component(digest, _raw_bytes(value))
                _hash_component(digest, b"\n")
    return digest.hexdigest()


def _result_completed_only_content_hash(connection: sqlite3.Connection) -> str:
    digest = sha256()
    for query in (
        "SELECT run_id, plan_sha256, dataset_hash, status, completed_at, pinned, "
        "materialized, publication_fill_count, publication_detail_count, "
        "publication_fill_set_hash, publication_detail_set_hash, summary_domain, "
        "publication_fill_set_domain, publication_detail_set_domain, summary_hash, "
        "summary_json, created_at FROM backtest_run ORDER BY run_id",
        "SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json, "
        "created_at FROM backtest_fill ORDER BY fill_id",
        "SELECT detail_id, run_id, kind, event_at, content_domain, content_hash, "
        "payload_json, created_at FROM backtest_detail ORDER BY detail_id",
        "SELECT plan_sha256, snapshot_json, created_at FROM backtest_plan_snapshot "
        "ORDER BY plan_sha256",
        "SELECT run_id, plan_sha256, input_hash, input_json, created_at "
        "FROM backtest_run_input ORDER BY run_id",
    ):
        cursor = connection.execute(query)
        while rows := cursor.fetchmany(1_000):
            for row in rows:
                for value in row:
                    _hash_component(digest, _raw_bytes(value))
                _hash_component(digest, b"\n")
    return digest.hexdigest()


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
        trigger_sql_contracts={},
    )
    pre_index_current = _is_supported_pre_index_market_schema(connection, table_names)
    state = (
        DatabaseState.CURRENT
        if current or pre_index_current
        else DatabaseState.LEGACY
        if present
        else DatabaseState.UNKNOWN
    )
    reasons: list[str] = []
    if state == DatabaseState.LEGACY:
        reasons.append("LEGACY_SCHEMA")
    elif state == DatabaseState.UNKNOWN:
        reasons.append("UNRECOGNIZED_SCHEMA")
    elif pre_index_current:
        reasons.append("MISSING_MARKET_INDEX_SCHEMA")
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
    if any(item.invalid_value_count for item in metadata):
        reasons.append("INVALID_MARKET_METADATA_TIMESTAMP")
    return {
        "database_state": state,
        "dataset_hash_goldens": dataset_hashes,
        "utc_metadata": metadata,
        "migration_reasons": tuple(reasons),
        "requires_schema_migration": state != DatabaseState.CURRENT,
    }


def _is_supported_pre_index_market_schema(
    connection: sqlite3.Connection,
    table_names: frozenset[str],
) -> bool:
    extension_tables = frozenset(_MARKET_INDEX_EXTENSION_TABLES)
    return _has_required_schema(
        connection,
        table_names,
        column_contracts={
            name: contract
            for name, contract in _MARKET_COLUMN_CONTRACTS.items()
            if name not in extension_tables
        },
        foreign_key_contracts={
            name: contract
            for name, contract in _MARKET_FOREIGN_KEY_CONTRACTS.items()
            if name not in extension_tables
        },
        table_sql_contracts={
            name: contract
            for name, contract in _MARKET_TABLE_SQL_CONTRACTS.items()
            if name not in extension_tables
        },
        index_contracts={
            name: contract
            for name, contract in _MARKET_INDEX_CONTRACTS.items()
            if name not in _MARKET_INDEX_EXTENSION_INDEXES
        },
        trigger_sql_contracts={},
    )


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
        trigger_sql_contracts=_RESULT_TRIGGER_SQL_CONTRACTS,
    )
    bt019_current = _is_supported_bt019_result_schema(connection, table_names)
    state = (
        DatabaseState.CURRENT
        if current or bt019_current
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
        if "backtest_run_input" in table_names and "run_id" in _table_columns(
            connection, "backtest_run_input"
        ):
            domain_filter = (
                " OR run.summary_domain <> 'backtest-run-summary-v2'"
                if "summary_domain" in run_columns
                else ""
            )
            compatibility_query = (
                "SELECT run.run_id FROM backtest_run AS run "
                "LEFT JOIN backtest_run_input AS input ON input.run_id = run.run_id "
                "WHERE run.status = 'COMPLETED' AND (input.run_id IS NULL"
                f"{domain_filter}) ORDER BY run.run_id"
            )
        else:
            compatibility_query = (
                "SELECT run_id FROM backtest_run WHERE status = 'COMPLETED' ORDER BY run_id"
            )
        rows = connection.execute(compatibility_query).fetchmany(_MAX_INVENTORIED_IDENTITIES + 1)
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
    elif bt019_current:
        reasons.append("MISSING_BACKTEST_JOB_SCHEMA")
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
    invalid_count = 0
    cursor = connection.execute(
        f'SELECT "{column}" FROM "{table}" ORDER BY CAST("{column}" AS BLOB), rowid'
    )
    while rows := cursor.fetchmany(1_000):
        for row in rows:
            raw = _raw_bytes(row[0])
            _hash_component(digest, raw)
            value_count += 1
            text = raw.decode("utf-8", errors="replace")
            try:
                _, converted = normalize_market_metadata_timestamp(text)
            except TypeError, ValueError:
                invalid_count += 1
            else:
                utc_count += int(converted)
    return TimestampMetadataInventory(
        table=table,
        column=column,
        value_count=value_count,
        utc_value_count=utc_count,
        invalid_value_count=invalid_count,
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
    trigger_sql_contracts: dict[str, str],
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
    if not _has_exact_trigger_sql(connection, trigger_sql_contracts):
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


def _has_exact_trigger_sql(
    connection: sqlite3.Connection,
    trigger_sql_contracts: dict[str, str],
) -> bool:
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type = 'trigger'"
    ).fetchall()
    actual_sql = {str(row[0]): row[1] for row in rows}
    return trigger_sql_contracts.keys() == actual_sql.keys() and all(
        actual_sql[name] is not None
        and _tokenize_schema_sql(str(actual_sql[name])) == _tokenize_schema_sql(expected_sql)
        for name, expected_sql in trigger_sql_contracts.items()
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
    "create_market_index_schema",
    "inspect_market_database",
    "inspect_result_database",
    "migrate_market_metadata",
    "migrate_result_database",
    "require_safe_store_initialization",
]
