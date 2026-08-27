"""Isolated SQLite persistence and bounded retention for backtest results."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
from itertools import islice
from pathlib import Path
from typing import Annotated, Protocol, Self
from weakref import WeakSet
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.canonical import canonical_decimal, canonical_json
from trade_plan_monitor.backtest.migration import (
    MigrationInventory,
    inspect_result_database,
    require_safe_store_initialization,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.storage_guard import reject_incompatible_database
from trade_plan_monitor.backtest.time import format_shanghai_datetime
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256

Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
StableIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
UtcDatetime = Annotated[datetime, AwareDatetime()]


class _HashDigest(Protocol):
    def update(self, value: bytes) -> None: ...


_MAX_BATCH_SIZE = 1_000
_MAX_ITEM_BYTES = 32 * 1_024
_SUCCESS_DETAIL_DAYS = 90
_SUCCESS_DETAIL_RUNS = 100
_DIAGNOSTIC_DETAIL_DAYS = 14
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_VERSIONS = frozenset({"v1", "v2"})
_RUN_DOMAINS = {version: f"backtest-run-summary-{version}" for version in _VERSIONS}
_FILL_DOMAINS = {version: f"backtest-fill-record-{version}" for version in _VERSIONS}
_DETAIL_DOMAINS = {version: f"backtest-detail-record-{version}" for version in _VERSIONS}
_FILL_SET_DOMAINS = {version: f"backtest-fill-set-{version}" for version in _VERSIONS}
_DETAIL_SET_DOMAINS = {version: f"backtest-detail-set-{version}" for version in _VERSIONS}
_RUN_INPUT_HASH_DOMAIN = b"backtest-run-input-record-v1\0"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_run (
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
    stage_revision INTEGER NOT NULL DEFAULT 1 CHECK (stage_revision >= 1)
);
CREATE INDEX IF NOT EXISTS ix_backtest_run_retention
    ON backtest_run (status, pinned, completed_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS ix_backtest_run_retention_v2
    ON backtest_run (status, pinned, materialized, created_at DESC, run_id DESC);
CREATE TABLE IF NOT EXISTS backtest_fill (
    fill_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
    filled_at TEXT NOT NULL,
    content_domain TEXT NOT NULL DEFAULT 'backtest-fill-record-v1' CHECK (
        content_domain IN ('backtest-fill-record-v1', 'backtest-fill-record-v2')
    ),
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_backtest_fill_run
    ON backtest_fill (run_id, filled_at, fill_id);

CREATE TABLE IF NOT EXISTS backtest_detail (
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
);
CREATE INDEX IF NOT EXISTS ix_backtest_detail_retention
    ON backtest_detail (kind, run_id, detail_id);
CREATE INDEX IF NOT EXISTS ix_backtest_detail_run_event
    ON backtest_detail (run_id, event_at, detail_id);
CREATE TABLE IF NOT EXISTS backtest_plan_snapshot (
    plan_sha256 TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_run_input (
    run_id TEXT PRIMARY KEY,
    plan_sha256 TEXT NOT NULL
        REFERENCES backtest_plan_snapshot (plan_sha256) ON DELETE RESTRICT,
    input_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_backtest_run_completed_only_insert
BEFORE INSERT ON backtest_run WHEN NEW.status <> 'COMPLETED'
BEGIN SELECT RAISE(ABORT, 'BACKTEST_RESULTS_COMPLETED_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_run_completed_only_update
BEFORE UPDATE OF status ON backtest_run WHEN NEW.status <> 'COMPLETED'
BEGIN SELECT RAISE(ABORT, 'BACKTEST_RESULTS_COMPLETED_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_fill_stage_revision_insert
AFTER INSERT ON backtest_fill
WHEN (SELECT materialized FROM backtest_run WHERE run_id = NEW.run_id) = 0
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id = NEW.run_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_fill_stage_revision_update
AFTER UPDATE OF run_id, filled_at, content_domain, content_hash, payload_json ON backtest_fill
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id IN (OLD.run_id, NEW.run_id) AND materialized = 0;
END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_fill_stage_revision_delete
AFTER DELETE ON backtest_fill
WHEN (SELECT materialized FROM backtest_run WHERE run_id = OLD.run_id) = 0
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id = OLD.run_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_detail_stage_revision_insert
AFTER INSERT ON backtest_detail
WHEN (SELECT materialized FROM backtest_run WHERE run_id = NEW.run_id) = 0
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id = NEW.run_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_detail_stage_revision_update
AFTER UPDATE OF run_id, kind, event_at, content_domain, content_hash, payload_json
ON backtest_detail
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id IN (OLD.run_id, NEW.run_id) AND materialized = 0;
END;
CREATE TRIGGER IF NOT EXISTS trg_backtest_detail_stage_revision_delete
AFTER DELETE ON backtest_detail
WHEN (SELECT materialized FROM backtest_run WHERE run_id = OLD.run_id) = 0
BEGIN
    UPDATE backtest_run SET stage_revision = stage_revision + 1
    WHERE run_id = OLD.run_id;
END;
"""


class ResultConflictError(ValueError):
    """An immutable identity already exists with different canonical content."""


class BacktestRunStatus(StrEnum):
    """Completed state plus readable compatibility values from legacy payloads."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BacktestDetailKind(StrEnum):
    """Bounded artifacts; simulated fills deliberately live in their own ledger."""

    DECISION = "DECISION"
    SIGNAL = "SIGNAL"
    EXECUTION_OUTCOME = "EXECUTION_OUTCOME"
    DAILY_EQUITY = "DAILY_EQUITY"
    DIAGNOSTIC = "DIAGNOSTIC"
    DEBUG_TRACE = "DEBUG_TRACE"


class _ResultValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BacktestRunSummary(_ResultValue):
    """Long-lived immutable run summary plus separately mutable pin metadata."""

    run_id: Sha256Hex
    plan_sha256: Sha256Hex
    dataset_hash: Sha256Hex
    status: BacktestRunStatus
    completed_at: UtcDatetime
    event_start: Annotated[date, Field(strict=True)]
    event_end: Annotated[date, Field(strict=True)]
    symbols: tuple[str, ...]
    coverage: dict[str, object]
    assumptions: dict[str, object]
    formula_versions: dict[str, str]
    final_metrics: dict[str, object]
    blockers: tuple[str, ...] = ()
    pinned: Annotated[bool, Field(strict=True)] = False

    @field_validator("completed_at")
    @classmethod
    def normalize_completed_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not 1 <= len(value) <= 10:
            raise ValueError("symbols must contain between 1 and 10 values")
        canonical = tuple(sorted(value))
        if len(set(canonical)) != len(canonical):
            raise ValueError("symbols must be unique")
        for symbol in canonical:
            if (
                len(symbol) != 9
                or not symbol[:6].isdigit()
                or symbol[6:] not in {".SH", ".SZ", ".BJ"}
            ):
                raise ValueError("symbols must use canonical A-share identities")
        return canonical

    @field_validator("coverage", "assumptions", "final_metrics", mode="before")
    @classmethod
    def canonicalize_mapping(cls, value: object) -> dict[str, object]:
        return _canonical_mapping(value)

    @field_validator("formula_versions")
    @classmethod
    def validate_formula_versions(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"indicator", "execution"}
        if not required <= value.keys():
            raise ValueError("formula_versions must identify indicator and execution")
        if any(not key or not version for key, version in value.items()):
            raise ValueError("formula_versions keys and values must not be empty")
        return dict(sorted(value.items()))

    @field_validator("blockers")
    @classmethod
    def validate_blockers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not blocker or len(blocker) > 256 for blocker in value):
            raise ValueError("blockers must contain bounded non-empty values")
        if len(set(value)) != len(value):
            raise ValueError("blockers must be unique")
        return value

    @model_validator(mode="after")
    def validate_event_range(self) -> Self:
        if self.event_end < self.event_start:
            raise ValueError("event_end must not precede event_start")
        return self


class BacktestFillRecord(_ResultValue):
    """Long-lived canonical simulated fill, without any copied market minute."""

    fill_id: StableIdentifier
    run_id: Sha256Hex
    filled_at: UtcDatetime
    payload: dict[str, object]

    @field_validator("filled_at")
    @classmethod
    def normalize_filled_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("payload", mode="before")
    @classmethod
    def canonicalize_payload(cls, value: object) -> dict[str, object]:
        return _canonical_mapping(value)

    @model_validator(mode="after")
    def validate_payload_identity(self) -> Self:
        for key, expected in (("fill_id", self.fill_id), ("run_id", self.run_id)):
            present = self.payload.get(key)
            if present is not None and present != expected:
                raise ValueError(f"payload {key} must match the fill record")
        return self

    @classmethod
    def from_value(
        cls,
        value: BaseModel | Mapping[str, object],
        *,
        version: str = "v1",
    ) -> Self:
        """Wrap an ``ExecutionFill`` or fill-shaped mapping losslessly."""

        raw_payload = _model_or_mapping(value, "fill")
        try:
            fill_id = raw_payload["fill_id"]
            run_id = raw_payload["run_id"]
            filled_at = raw_payload["filled_at"]
        except KeyError as error:
            raise ValueError(f"fill payload is missing {error.args[0]}") from None
        payload = _canonical_mapping(raw_payload, version=version)
        return cls(
            fill_id=fill_id,
            run_id=run_id,
            filled_at=filled_at,
            payload=payload,
        )


class BacktestDetailRecord(_ResultValue):
    """One bounded decision, signal, outcome, daily equity, or diagnostic artifact."""

    detail_id: StableIdentifier
    run_id: Sha256Hex
    kind: BacktestDetailKind
    event_at: UtcDatetime
    payload: dict[str, object]

    @field_validator("event_at")
    @classmethod
    def normalize_event_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("payload", mode="before")
    @classmethod
    def canonicalize_payload(cls, value: object) -> dict[str, object]:
        return _canonical_mapping(value)

    @model_validator(mode="after")
    def validate_payload_scope(self) -> Self:
        present_run_id = self.payload.get("run_id")
        if present_run_id is not None and present_run_id != self.run_id:
            raise ValueError("payload run_id must match the detail record")
        return self

    @classmethod
    def from_value(
        cls,
        kind: BacktestDetailKind,
        value: BaseModel | Mapping[str, object],
        *,
        run_id: str | None = None,
        event_at: datetime | None = None,
        detail_id: str | None = None,
        version: str = "v1",
    ) -> Self:
        """Wrap execution signals/outcomes/equity or another normalized model.

        ``ExecutionOutcome`` has no run field, so callers provide it explicitly.
        Event times for execution and other models are inferred by field name.
        """

        raw_payload = _model_or_mapping(value, "detail")
        resolved_id = detail_id or _first_string(
            raw_payload,
            ("detail_id", "snapshot_id", "outcome_id", "signal_id", "result_hash"),
        )
        resolved_run = run_id or _optional_string(raw_payload.get("run_id"))
        resolved_event = event_at or _first_datetime(
            raw_payload,
            (
                "event_at",
                "resolved_at",
                "marked_at",
                "signal_at",
                "evaluated_at",
                "filled_at",
            ),
        )
        if resolved_id is None:
            raise ValueError("detail_id could not be inferred")
        if resolved_run is None:
            raise ValueError("run_id could not be inferred")
        if resolved_event is None:
            raise ValueError("event_at could not be inferred")
        payload = _canonical_mapping(raw_payload, version=version)
        return cls(
            detail_id=resolved_id,
            run_id=resolved_run,
            kind=kind,
            event_at=resolved_event,
            payload=payload,
        )


class BacktestResultStatistics(_ResultValue):
    run_count: Annotated[int, Field(strict=True, ge=0)]
    fill_count: Annotated[int, Field(strict=True, ge=0)]
    detail_count: Annotated[int, Field(strict=True, ge=0)]


class RetentionPruneResult(_ResultValue):
    deleted_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_BATCH_SIZE)]
    has_more: Annotated[bool, Field(strict=True)]


@dataclass(frozen=True, slots=True, weakref_slot=True)
class VerifiedBacktestPublication:
    run_id: str
    stage_revision: int
    fill_count: int
    detail_count: int
    fill_set_hash: str
    detail_set_hash: str
    fill_set_domain: str
    detail_set_domain: str
    summary_fingerprint: str
    input_fingerprint: str | None
    already_materialized: bool
    read_batch_count: int
    max_read_batch_size: int
    _store_token: object = field(repr=False, compare=False)


class BacktestResultStore:
    """Own the independent result database; never opens live or market stores."""

    def __init__(self, database_path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        if isinstance(database_path, str) and not database_path.strip():
            raise ValueError("database_path must not be empty")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        self._path = Path(database_path).expanduser().resolve()
        if self._path.exists() and not self._path.is_file():
            raise ValueError("database_path must point to a file")
        self._migration_inventory = inspect_result_database(self._path)
        reject_incompatible_database(
            self._path,
            store_name="backtest result",
            forbidden_prefixes=("market_",),
            observed_table_names=self._migration_inventory.table_names,
        )
        require_safe_store_initialization(self._migration_inventory)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = busy_timeout_ms
        self._publication_token = object()
        self._verified_publications: WeakSet[VerifiedBacktestPublication] = WeakSet()
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._path

    @property
    def migration_inventory(self) -> MigrationInventory:
        """Return the immutable inventory captured before initialization."""

        return self._migration_inventory

    def record_run_input(self, run_input: BacktestRunInput) -> bool:
        """Persist one canonical input and its deduplicated immutable plan snapshot."""

        if not isinstance(run_input, BacktestRunInput):
            raise TypeError("run_input must be a BacktestRunInput")
        run_input.validate_canonical_input()
        snapshot_json = dump_plan_json(run_input.plan_snapshot)
        if plan_sha256(run_input.plan_snapshot) != run_input.plan_sha256:
            raise ValueError("run input plan hash does not match its canonical snapshot")
        input_json = canonical_json(
            run_input.model_dump(
                mode="python",
                round_trip=True,
                exclude={"plan_snapshot"},
            )
        )
        input_hash = _content_hash(_RUN_INPUT_HASH_DOMAIN, input_json)
        now = _datetime_text(datetime.now(_SHANGHAI), version="v2")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = connection.execute(
                "SELECT snapshot_json FROM backtest_plan_snapshot WHERE plan_sha256 = ?",
                (run_input.plan_sha256,),
            ).fetchone()
            if snapshot is None:
                connection.execute(
                    "INSERT INTO backtest_plan_snapshot "
                    "(plan_sha256, snapshot_json, created_at) VALUES (?, ?, ?)",
                    (run_input.plan_sha256, snapshot_json, now),
                )
            elif str(snapshot[0]) != snapshot_json:
                raise ResultConflictError(
                    "conflicting plan snapshot content under an existing plan_sha256"
                )
            existing = connection.execute(
                "SELECT plan_sha256, input_hash, input_json FROM backtest_run_input "
                "WHERE run_id = ?",
                (run_input.run_id,),
            ).fetchone()
            if existing is not None:
                if tuple(map(str, existing)) != (
                    run_input.plan_sha256,
                    input_hash,
                    input_json,
                ):
                    raise ResultConflictError(
                        "conflicting canonical input under an existing run_id"
                    )
                connection.commit()
                return False
            connection.execute(
                "INSERT INTO backtest_run_input "
                "(run_id, plan_sha256, input_hash, input_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_input.run_id, run_input.plan_sha256, input_hash, input_json, now),
            )
            connection.commit()
        return True

    def get_run_input(self, run_id: str) -> BacktestRunInput | None:
        """Return a hash-verified canonical input, or ``None`` for compatibility rows."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        with self._connect() as connection:
            run_input, _fingerprint = _publication_run_input(
                connection,
                normalized_run_id,
            )
        return run_input

    def record_verified_run(
        self,
        summary: BacktestRunSummary,
        *,
        run_input: BacktestRunInput,
        retention_at: datetime | None = None,
    ) -> bool:
        """Stage one active v2 completed row backed by independently verified input."""

        _validate_summary_input(summary, run_input)
        self.record_run_input(run_input)
        return self._record_run(summary, version="v2", retention_at=retention_at)

    def record_run(
        self,
        summary: BacktestRunSummary,
        *,
        materialized: bool = False,
        retention_at: datetime | None = None,
    ) -> bool:
        """Stage an explicit v1 compatibility row; active callers use verified input."""

        if not isinstance(summary, BacktestRunSummary):
            raise TypeError("summary must be a BacktestRunSummary")
        if type(materialized) is not bool:
            raise TypeError("materialized must be a bool")
        if materialized:
            raise ValueError("direct materialization is not allowed")
        return self._record_run(summary, version="v1", retention_at=retention_at)

    def _record_run(
        self,
        summary: BacktestRunSummary,
        *,
        version: str,
        retention_at: datetime | None,
    ) -> bool:
        if summary.status is not BacktestRunStatus.COMPLETED:
            raise ValueError("backtest results are completed-only")
        normalized_retention_at = (
            summary.completed_at
            if retention_at is None
            else _normalize_datetime(retention_at, "retention_at")
        )
        summary_json = _summary_json(summary, version=version)
        _require_item_size(summary_json, "backtest summary")
        summary_domain = _domain(_RUN_DOMAINS, version)
        summary_hash = _content_hash(_domain_bytes(summary_domain), summary_json)
        now = _datetime_text(normalized_retention_at, version=version)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT summary_hash FROM backtest_run WHERE run_id = ?",
                (summary.run_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != summary_hash:
                    raise ResultConflictError(
                        "conflicting summary content under an existing run_id"
                    )
                connection.commit()
                return False
            connection.execute(
                """
                INSERT INTO backtest_run (
                    run_id, plan_sha256, dataset_hash, status, completed_at,
                    pinned, materialized, summary_domain, summary_hash,
                    summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.run_id,
                    summary.plan_sha256,
                    summary.dataset_hash,
                    summary.status.value,
                    _datetime_text(summary.completed_at, version=version),
                    int(summary.pinned),
                    0,
                    summary_domain,
                    summary_hash,
                    summary_json,
                    now,
                ),
            )
            connection.commit()
        return True

    def record_fills(
        self,
        run_id: str,
        fills: Iterable[BacktestFillRecord | BaseModel | Mapping[str, object]],
    ) -> int:
        """Persist at most 1,000 fill-ledger rows atomically and idempotently."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        values = _bounded_values(fills, "fills")
        with self._connect() as connection:
            _status, _materialized, version = _require_run_state(
                connection,
                normalized_run_id,
            )
        records = tuple(
            value
            if isinstance(value, BacktestFillRecord)
            else BacktestFillRecord.from_value(value, version=version)
            for value in values
        )
        if any(record.run_id != normalized_run_id for record in records):
            raise ValueError("every fill run_id must match the requested run_id")
        return self._record_fills(normalized_run_id, records)

    def record_details(
        self,
        run_id: str,
        details: Iterable[BacktestDetailRecord],
    ) -> int:
        """Persist at most 1,000 bounded detail rows atomically and idempotently."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        values = _bounded_values(details, "details")
        if any(not isinstance(value, BacktestDetailRecord) for value in values):
            raise TypeError("details must contain BacktestDetailRecord values")
        records = tuple(values)
        if any(record.run_id != normalized_run_id for record in records):
            raise ValueError("every detail run_id must match the requested run_id")
        return self._record_details(normalized_run_id, records)

    def get_run(
        self,
        run_id: str,
        *,
        include_unmaterialized: bool = False,
    ) -> BacktestRunSummary | None:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if type(include_unmaterialized) is not bool:
            raise TypeError("include_unmaterialized must be a bool")
        materialized_filter = "" if include_unmaterialized else " AND materialized = 1"
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT run_id, plan_sha256, dataset_hash, status, completed_at,
                       summary_domain, summary_hash, summary_json, pinned
                FROM backtest_run WHERE run_id = ?{materialized_filter}
                """,
                (normalized_run_id,),
            ).fetchone()
        if row is None:
            return None
        return _load_summary_row(row, expected_run_id=normalized_run_id)

    def get_verified_run(self, run_id: str) -> BacktestRunSummary | None:
        """Return only active v2 rows whose persisted input independently re-derives identity."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        run_input = self.get_run_input(normalized_run_id)
        if run_input is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, plan_sha256, dataset_hash, status, completed_at,
                       summary_domain, summary_hash, summary_json, pinned
                FROM backtest_run
                WHERE run_id = ? AND materialized = 1
                  AND summary_domain = 'backtest-run-summary-v2'
                """,
                (normalized_run_id,),
            ).fetchone()
        if row is None:
            return None
        summary = _load_summary_row(row, expected_run_id=normalized_run_id)
        _validate_summary_input(summary, run_input)
        return summary

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> tuple[BacktestRunSummary, ...]:
        if type(limit) is not int or not 1 <= limit <= _MAX_BATCH_SIZE:
            raise ValueError("limit must be between 1 and 1000")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, plan_sha256, dataset_hash, status, completed_at,
                       summary_domain, summary_hash, summary_json, pinned
                FROM backtest_run
                WHERE materialized = 1
                ORDER BY created_at DESC, run_id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return tuple(_load_summary_row(row) for row in rows)

    def list_fills(self, run_id: str) -> tuple[BacktestFillRecord, ...]:
        normalized_run_id = _validate_hash(run_id, "run_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.fill_id, f.run_id, f.filled_at, f.content_domain,
                       f.content_hash, f.payload_json
                FROM backtest_fill AS f
                JOIN backtest_run AS r ON r.run_id = f.run_id
                WHERE f.run_id = ? AND r.materialized = 1
                ORDER BY f.filled_at, f.fill_id
                """,
                (normalized_run_id,),
            ).fetchall()
        return tuple(_load_fill_row(row, expected_run_id=normalized_run_id) for row in rows)

    def list_details(
        self,
        run_id: str,
        *,
        kind: BacktestDetailKind | None = None,
    ) -> tuple[BacktestDetailRecord, ...]:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if kind is not None and not isinstance(kind, BacktestDetailKind):
            raise TypeError("kind must be a BacktestDetailKind or None")
        query = """
            SELECT d.detail_id, d.run_id, d.kind, d.event_at, d.content_domain,
                   d.content_hash, d.payload_json
            FROM backtest_detail AS d
            JOIN backtest_run AS r ON r.run_id = d.run_id
            WHERE d.run_id = ? AND r.materialized = 1
        """
        query += " ORDER BY d.event_at, d.detail_id"
        with self._connect() as connection:
            rows = connection.execute(query, (normalized_run_id,)).fetchall()
        records = tuple(_load_detail_row(row, expected_run_id=normalized_run_id) for row in rows)
        if kind is None:
            return records
        return tuple(record for record in records if record.kind is kind)

    def statistics(self) -> BacktestResultStatistics:
        with self._connect() as connection:
            return BacktestResultStatistics(
                run_count=int(
                    connection.execute(
                        "SELECT COUNT(*) FROM backtest_run WHERE materialized = 1"
                    ).fetchone()[0]
                ),
                fill_count=_materialized_count(connection, "backtest_fill"),
                detail_count=_materialized_count(connection, "backtest_detail"),
            )

    def set_pinned(self, run_id: str, pinned: bool) -> bool:
        """Change only retention metadata; immutable summary identity is untouched."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        if type(pinned) is not bool:
            raise TypeError("pinned must be a bool")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT pinned FROM backtest_run WHERE run_id = ?",
                (normalized_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run_id: {normalized_run_id}")
            if bool(row[0]) is pinned:
                connection.commit()
                return False
            connection.execute(
                "UPDATE backtest_run SET pinned = ? WHERE run_id = ?",
                (int(pinned), normalized_run_id),
            )
            connection.commit()
        return True

    def prune_details(
        self,
        *,
        as_of: datetime,
        batch_size: int = _MAX_BATCH_SIZE,
    ) -> RetentionPruneResult:
        """Delete one bounded retention batch, including abandoned staged rows."""

        normalized_as_of = _normalize_datetime(as_of, "as_of")
        if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError("batch_size must be between 1 and 1000")
        parameters = _retention_parameters(normalized_as_of)
        staged_cutoff = parameters[0]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted_count = 0
            remaining = batch_size
            staged_detail_ids = _candidate_ids(
                connection,
                _STALE_STAGED_DETAIL_SQL,
                (staged_cutoff, remaining),
            )
            deleted_count += _delete_ids(
                connection,
                "backtest_detail",
                "detail_id",
                staged_detail_ids,
            )
            remaining = batch_size - deleted_count
            staged_fill_ids = _candidate_ids(
                connection,
                _STALE_STAGED_FILL_SQL,
                (staged_cutoff, remaining),
            )
            deleted_count += _delete_ids(
                connection,
                "backtest_fill",
                "fill_id",
                staged_fill_ids,
            )
            remaining = batch_size - deleted_count
            staged_run_ids = _candidate_ids(
                connection,
                _STALE_STAGED_RUN_SQL,
                (staged_cutoff, remaining),
            )
            deleted_count += _delete_ids(
                connection,
                "backtest_run",
                "run_id",
                staged_run_ids,
            )
            remaining = batch_size - deleted_count
            retained_detail_ids = _candidate_ids(
                connection,
                _RETENTION_CANDIDATES_SQL,
                (*parameters, remaining),
            )
            deleted_count += _delete_ids(
                connection,
                "backtest_detail",
                "detail_id",
                retained_detail_ids,
            )
            has_more = any(
                _has_candidate(connection, query, query_parameters)
                for query, query_parameters in (
                    (_STALE_STAGED_DETAIL_SQL, (staged_cutoff, 1)),
                    (_STALE_STAGED_FILL_SQL, (staged_cutoff, 1)),
                    (_STALE_STAGED_RUN_SQL, (staged_cutoff, 1)),
                    (_RETENTION_CANDIDATES_SQL, (*parameters, 1)),
                )
            )
            connection.commit()
        return RetentionPruneResult(deleted_count=deleted_count, has_more=has_more)

    def checkpoint_wal(self) -> tuple[int, int, int]:
        """Run a non-blocking passive checkpoint at an explicit safe boundary."""

        with self._connect() as connection:
            row = connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        if row is None or len(row) != 3:
            raise RuntimeError("SQLite did not return a WAL checkpoint result")
        return int(row[0]), int(row[1]), int(row[2])

    def mark_run_materialized(
        self,
        run_id: str,
        *,
        expected_fill_count: int,
        expected_detail_count: int,
        expected_report_hash: str,
        expected_fill_set_hash: str,
        expected_detail_set_hash: str,
    ) -> bool:
        """Compatibility wrapper around bounded verification and short publication."""

        proof = self.verify_staged_publication(
            run_id,
            expected_fill_count=expected_fill_count,
            expected_detail_count=expected_detail_count,
            expected_report_hash=expected_report_hash,
            expected_fill_set_hash=expected_fill_set_hash,
            expected_detail_set_hash=expected_detail_set_hash,
        )
        return self.publish_verified_publication(proof)

    def verify_staged_publication(
        self,
        run_id: str,
        *,
        expected_fill_count: int,
        expected_detail_count: int,
        expected_report_hash: str,
        expected_fill_set_hash: str,
        expected_detail_set_hash: str,
    ) -> VerifiedBacktestPublication:
        """Verify exact staged content in one bounded, query-only WAL snapshot."""

        expectations = _publication_expectations(
            run_id,
            expected_fill_count=expected_fill_count,
            expected_detail_count=expected_detail_count,
            expected_report_hash=expected_report_hash,
            expected_fill_set_hash=expected_fill_set_hash,
            expected_detail_set_hash=expected_detail_set_hash,
        )
        normalized_run_id = expectations[0]
        with self._connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            row = _publication_run_row(connection, normalized_run_id)
            summary = _load_summary_row(row[:9], expected_run_id=normalized_run_id)
            _require_item_size(str(row[7]), "backtest summary")
            version = _version_from_domain(str(row[5]), _RUN_DOMAINS)
            if summary.assumptions.get("reportHash") != expectations[3]:
                raise ResultConflictError("completed report hash does not match the staged summary")
            run_input, input_fingerprint = _publication_run_input(
                connection,
                normalized_run_id,
            )
            if version == "v2":
                if run_input is None:
                    raise ResultConflictError(
                        "active v2 publication requires a canonical run input"
                    )
                _validate_summary_input(summary, run_input)

            stored_metadata = row[10:16]
            already_materialized = bool(row[9])
            if any(value is None for value in stored_metadata) and not all(
                value is None for value in stored_metadata
            ):
                raise RuntimeError("materialized publication metadata is incomplete")
            if already_materialized and all(value is not None for value in stored_metadata):
                metadata = _stored_publication_metadata(stored_metadata)
                read_batch_count = 0
                max_read_batch_size = 0
            else:
                metadata, read_batch_count, max_read_batch_size = _bounded_materialization_metadata(
                    connection,
                    normalized_run_id,
                    version=version,
                )
            _require_publication_metadata(
                metadata,
                expected_fill_count=expectations[1],
                expected_detail_count=expectations[2],
                expected_fill_set_hash=expectations[4],
                expected_detail_set_hash=expectations[5],
                version=version,
                staged=not already_materialized,
            )
            proof = VerifiedBacktestPublication(
                run_id=normalized_run_id,
                stage_revision=int(row[16]),
                fill_count=metadata[0],
                detail_count=metadata[1],
                fill_set_hash=metadata[2],
                detail_set_hash=metadata[3],
                fill_set_domain=metadata[4],
                detail_set_domain=metadata[5],
                summary_fingerprint=_publication_summary_fingerprint(row),
                input_fingerprint=input_fingerprint,
                already_materialized=already_materialized,
                read_batch_count=read_batch_count,
                max_read_batch_size=max_read_batch_size,
                _store_token=self._publication_token,
            )
            self._verified_publications.add(proof)
            return proof

    def materialize_verified_publication(
        self,
        connection: sqlite3.Connection,
        proof: VerifiedBacktestPublication,
    ) -> bool:
        """Participate in a caller-owned writer transaction without committing it."""

        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if not isinstance(proof, VerifiedBacktestPublication):
            raise TypeError("proof must come from verify_staged_publication")
        if proof._store_token is not self._publication_token:
            raise ValueError("publication proof belongs to another result store instance")
        if proof not in self._verified_publications:
            raise ValueError("publication proof was not issued by this result store instance")
        if not connection.in_transaction:
            raise RuntimeError("publication participant requires an active transaction")
        _require_store_connection(connection, self._path)
        row = _publication_run_row(connection, proof.run_id)
        if int(row[16]) != proof.stage_revision:
            raise ResultConflictError("staged result changed after its stage revision snapshot")
        if _publication_summary_fingerprint(row) != proof.summary_fingerprint:
            raise ResultConflictError("staged summary changed after verification")
        input_fingerprint = _publication_input_fingerprint(connection, proof.run_id)
        if input_fingerprint != proof.input_fingerprint:
            raise ResultConflictError("staged run input or plan changed after verification")

        metadata = _proof_metadata(proof)
        stored_metadata = row[10:16]
        if bool(row[9]):
            if all(value is None for value in stored_metadata):
                connection.execute(
                    """
                    UPDATE backtest_run SET
                        publication_fill_count = ?, publication_detail_count = ?,
                        publication_fill_set_hash = ?, publication_detail_set_hash = ?,
                        publication_fill_set_domain = ?, publication_detail_set_domain = ?
                    WHERE run_id = ? AND stage_revision = ? AND materialized = 1
                    """,
                    (*metadata, proof.run_id, proof.stage_revision),
                )
            elif any(value is None for value in stored_metadata):
                raise RuntimeError("materialized publication metadata is incomplete")
            elif _stored_publication_metadata(stored_metadata) != metadata:
                raise ResultConflictError("materialized publication metadata changed")
            return False
        if proof.already_materialized:
            raise ResultConflictError("materialized publication state regressed")
        if any(value is not None for value in stored_metadata):
            raise ResultConflictError("staged publication metadata must be empty")
        cursor = connection.execute(
            """
            UPDATE backtest_run SET
                materialized = 1,
                publication_fill_count = ?, publication_detail_count = ?,
                publication_fill_set_hash = ?, publication_detail_set_hash = ?,
                publication_fill_set_domain = ?, publication_detail_set_domain = ?
            WHERE run_id = ? AND stage_revision = ? AND materialized = 0
            """,
            (*metadata, proof.run_id, proof.stage_revision),
        )
        if cursor.rowcount != 1:
            raise ResultConflictError("staged result changed before publication")
        return True

    def publish_verified_publication(self, proof: VerifiedBacktestPublication) -> bool:
        """Commit one pre-verified publication in its own short transaction."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = self.materialize_verified_publication(connection, proof)
            connection.commit()
        return changed

    def _initialize(self) -> None:
        with self._connect() as connection:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                raise RuntimeError("backtest result database did not enter WAL mode")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _record_fills(
        self,
        run_id: str,
        records: tuple[BacktestFillRecord, ...],
    ) -> int:
        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _status, materialized, version = _require_run_state(connection, run_id)
            content_domain = _domain(_FILL_DOMAINS, version)
            now = _now_text(version)
            for record in records:
                payload_json = _canonical_json(
                    record.model_dump(mode="python", round_trip=True),
                    version=version,
                )
                _require_item_size(payload_json, "backtest fill")
                content_hash = _content_hash(_domain_bytes(content_domain), payload_json)
                existing = connection.execute(
                    """
                    SELECT run_id, filled_at, content_domain, content_hash, payload_json
                    FROM backtest_fill WHERE fill_id = ?
                    """,
                    (record.fill_id,),
                ).fetchone()
                if existing is not None:
                    stored = _load_fill(str(existing[2]), str(existing[3]), str(existing[4]))
                    if (
                        str(existing[0]) != run_id
                        or str(existing[1]) != _datetime_text(stored.filled_at, version=version)
                        or stored.fill_id != record.fill_id
                        or stored.run_id != run_id
                        or str(existing[2]) != content_domain
                        or str(existing[3]) != content_hash
                    ):
                        raise ResultConflictError(
                            "conflicting fill content under an existing fill_id"
                        )
                    continue
                if materialized:
                    raise ResultConflictError("cannot append fills to a materialized run")
                connection.execute(
                    """
                    INSERT INTO backtest_fill (
                        fill_id, run_id, filled_at, content_domain,
                        content_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.fill_id,
                        run_id,
                        _datetime_text(record.filled_at, version=version),
                        content_domain,
                        content_hash,
                        payload_json,
                        now,
                    ),
                )
                inserted += 1
            connection.commit()
        return inserted

    def _record_details(
        self,
        run_id: str,
        records: tuple[BacktestDetailRecord, ...],
    ) -> int:
        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            status, materialized, version = _require_run_state(connection, run_id)
            content_domain = _domain(_DETAIL_DOMAINS, version)
            now = _now_text(version)
            for record in records:
                _validate_detail_status(status, record.kind)
                payload_json = _canonical_json(
                    record.model_dump(mode="python", round_trip=True),
                    version=version,
                )
                _require_item_size(payload_json, "backtest detail")
                content_hash = _content_hash(_domain_bytes(content_domain), payload_json)
                existing = connection.execute(
                    """
                    SELECT run_id, kind, event_at, content_domain, content_hash, payload_json
                    FROM backtest_detail WHERE detail_id = ?
                    """,
                    (record.detail_id,),
                ).fetchone()
                if existing is not None:
                    stored = _load_detail(str(existing[3]), str(existing[4]), str(existing[5]))
                    if (
                        str(existing[0]) != run_id
                        or str(existing[1]) != stored.kind.value
                        or str(existing[2]) != _datetime_text(stored.event_at, version=version)
                        or stored.detail_id != record.detail_id
                        or stored.run_id != run_id
                        or str(existing[3]) != content_domain
                        or str(existing[4]) != content_hash
                    ):
                        raise ResultConflictError(
                            "conflicting detail content under an existing detail_id"
                        )
                    continue
                if materialized:
                    raise ResultConflictError("cannot append details to a materialized run")
                connection.execute(
                    """
                    INSERT INTO backtest_detail (
                        detail_id, run_id, kind, event_at,
                        content_domain, content_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.detail_id,
                        run_id,
                        record.kind.value,
                        _datetime_text(record.event_at, version=version),
                        content_domain,
                        content_hash,
                        payload_json,
                        now,
                    ),
                )
                inserted += 1
            connection.commit()
        return inserted


_STALE_STAGED_DETAIL_SQL = """
SELECT d.detail_id
FROM backtest_detail AS d
JOIN backtest_run AS r ON r.run_id = d.run_id
WHERE r.materialized = 0 AND r.pinned = 0 AND r.created_at < ?
ORDER BY r.created_at, d.detail_id
LIMIT ?
"""

_STALE_STAGED_FILL_SQL = """
SELECT f.fill_id
FROM backtest_fill AS f
JOIN backtest_run AS r ON r.run_id = f.run_id
WHERE r.materialized = 0 AND r.pinned = 0 AND r.created_at < ?
ORDER BY r.created_at, f.fill_id
LIMIT ?
"""

_STALE_STAGED_RUN_SQL = """
SELECT r.run_id
FROM backtest_run AS r
WHERE r.materialized = 0
  AND r.pinned = 0
  AND r.created_at < ?
  AND NOT EXISTS (SELECT 1 FROM backtest_detail AS d WHERE d.run_id = r.run_id)
  AND NOT EXISTS (SELECT 1 FROM backtest_fill AS f WHERE f.run_id = r.run_id)
ORDER BY r.created_at, r.run_id
LIMIT ?
"""

_RETENTION_CANDIDATES_SQL = """
WITH ranked_success AS (
    SELECT
        run_id,
        ROW_NUMBER() OVER (ORDER BY created_at DESC, run_id DESC) AS run_rank
    FROM backtest_run
    WHERE status = 'COMPLETED' AND pinned = 0 AND materialized = 1
)
SELECT d.detail_id
FROM backtest_detail AS d
JOIN backtest_run AS r ON r.run_id = d.run_id
LEFT JOIN ranked_success AS ranked ON ranked.run_id = r.run_id
WHERE r.pinned = 0
  AND r.materialized = 1
  AND (
      (d.kind = 'DEBUG_TRACE' AND r.created_at < ?)
      OR (
          r.status = 'COMPLETED'
          AND d.kind != 'DEBUG_TRACE'
          AND (r.created_at < ? OR ranked.run_rank > ?)
      )
  )
ORDER BY r.created_at, d.detail_id
LIMIT ?
"""


def _retention_parameters(as_of: datetime) -> tuple[str, str, int]:
    diagnostic_cutoff = _datetime_text(as_of - timedelta(days=_DIAGNOSTIC_DETAIL_DAYS))
    success_cutoff = _datetime_text(as_of - timedelta(days=_SUCCESS_DETAIL_DAYS))
    return diagnostic_cutoff, success_cutoff, _SUCCESS_DETAIL_RUNS


def _candidate_ids(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> tuple[str, ...]:
    return tuple(str(row[0]) for row in connection.execute(query, parameters).fetchall())


def _has_candidate(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> bool:
    return connection.execute(query, parameters).fetchone() is not None


def _delete_ids(
    connection: sqlite3.Connection,
    table: str,
    identity_column: str,
    identities: tuple[str, ...],
) -> int:
    supported = {
        ("backtest_detail", "detail_id"),
        ("backtest_fill", "fill_id"),
        ("backtest_run", "run_id"),
    }
    if (table, identity_column) not in supported:
        raise ValueError("unsupported result retention identity")
    if not identities:
        return 0
    placeholders = ",".join("?" for _ in identities)
    connection.execute(
        f"DELETE FROM {table} WHERE {identity_column} IN ({placeholders})",
        identities,
    )
    return len(identities)


def _validate_detail_status(status: BacktestRunStatus, kind: BacktestDetailKind) -> None:
    successful = {
        BacktestDetailKind.DECISION,
        BacktestDetailKind.SIGNAL,
        BacktestDetailKind.EXECUTION_OUTCOME,
        BacktestDetailKind.DAILY_EQUITY,
        BacktestDetailKind.DEBUG_TRACE,
    }
    if status is not BacktestRunStatus.COMPLETED or kind not in successful:
        raise ValueError(f"{kind.value} detail is not valid for {status.value} runs")


def _require_run_state(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[BacktestRunStatus, bool, str]:
    row = connection.execute(
        "SELECT status, materialized, summary_domain FROM backtest_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown run_id: {run_id}")
    return (
        BacktestRunStatus(str(row[0])),
        bool(row[1]),
        _version_from_domain(str(row[2]), _RUN_DOMAINS),
    )


def _summary_json(summary: BacktestRunSummary, *, version: str) -> str:
    payload = summary.model_dump(mode="python", exclude={"pinned"}, round_trip=True)
    return _canonical_json(payload, version=version)


def _load_summary(
    summary_domain: str,
    summary_hash: str,
    summary_json: str,
    pinned: bool,
) -> BacktestRunSummary:
    expected = _content_hash(_domain_bytes(summary_domain), summary_json)
    if summary_hash != expected:
        raise RuntimeError("stored backtest summary failed its content hash")
    summary = BacktestRunSummary.model_validate_json(summary_json)
    if _version_from_domain(summary_domain, _RUN_DOMAINS) == "v2":
        summary = summary.model_copy(
            update={"completed_at": summary.completed_at.astimezone(_SHANGHAI)}
        )
    return summary.model_copy(update={"pinned": pinned})


def _load_summary_row(
    row: tuple[object, ...],
    *,
    expected_run_id: str | None = None,
) -> BacktestRunSummary:
    if len(row) != 9:
        raise RuntimeError("stored backtest summary row shape is invalid")
    version = _version_from_domain(str(row[5]), _RUN_DOMAINS)
    summary = _load_summary(str(row[5]), str(row[6]), str(row[7]), bool(row[8]))
    sql_identity = (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        str(row[4]),
    )
    canonical_identity = (
        summary.run_id,
        summary.plan_sha256,
        summary.dataset_hash,
        summary.status.value,
        _datetime_text(summary.completed_at, version=version),
    )
    if sql_identity != canonical_identity:
        raise RuntimeError("stored backtest summary SQL identity is invalid")
    if expected_run_id is not None and summary.run_id != expected_run_id:
        raise RuntimeError("stored backtest summary does not match the requested run")
    return summary


def _load_fill(
    content_domain: str,
    content_hash: str,
    payload_json: str,
) -> BacktestFillRecord:
    _version_from_domain(content_domain, _FILL_DOMAINS)
    expected = _content_hash(_domain_bytes(content_domain), payload_json)
    if content_hash != expected:
        raise RuntimeError("stored backtest fill failed its content hash")
    record = BacktestFillRecord.model_validate_json(payload_json)
    if _version_from_domain(content_domain, _FILL_DOMAINS) == "v2":
        return record.model_copy(update={"filled_at": record.filled_at.astimezone(_SHANGHAI)})
    return record


def _load_fill_row(
    row: tuple[object, ...],
    *,
    expected_run_id: str,
) -> BacktestFillRecord:
    if len(row) != 6:
        raise RuntimeError("stored backtest fill row shape is invalid")
    version = _version_from_domain(str(row[3]), _FILL_DOMAINS)
    record = _load_fill(str(row[3]), str(row[4]), str(row[5]))
    if (
        record.fill_id != str(row[0])
        or record.run_id != str(row[1])
        or record.run_id != expected_run_id
        or _datetime_text(record.filled_at, version=version) != str(row[2])
    ):
        raise RuntimeError("stored backtest fill SQL identity is invalid")
    return record


def _load_detail(
    content_domain: str,
    content_hash: str,
    payload_json: str,
) -> BacktestDetailRecord:
    _version_from_domain(content_domain, _DETAIL_DOMAINS)
    expected = _content_hash(_domain_bytes(content_domain), payload_json)
    if content_hash != expected:
        raise RuntimeError("stored backtest detail failed its content hash")
    record = BacktestDetailRecord.model_validate_json(payload_json)
    if _version_from_domain(content_domain, _DETAIL_DOMAINS) == "v2":
        return record.model_copy(update={"event_at": record.event_at.astimezone(_SHANGHAI)})
    return record


def _load_detail_row(
    row: tuple[object, ...],
    *,
    expected_run_id: str,
) -> BacktestDetailRecord:
    if len(row) != 7:
        raise RuntimeError("stored backtest detail row shape is invalid")
    version = _version_from_domain(str(row[4]), _DETAIL_DOMAINS)
    record = _load_detail(str(row[4]), str(row[5]), str(row[6]))
    if (
        record.detail_id != str(row[0])
        or record.run_id != str(row[1])
        or record.run_id != expected_run_id
        or record.kind.value != str(row[2])
        or _datetime_text(record.event_at, version=version) != str(row[3])
    ):
        raise RuntimeError("stored backtest detail SQL identity is invalid")
    return record


def _publication_expectations(
    run_id: str,
    *,
    expected_fill_count: int,
    expected_detail_count: int,
    expected_report_hash: str,
    expected_fill_set_hash: str,
    expected_detail_set_hash: str,
) -> tuple[str, int, int, str, str, str]:
    normalized_run_id = _validate_hash(run_id, "run_id")
    normalized_report_hash = _validate_hash(expected_report_hash, "expected_report_hash")
    normalized_fill_set_hash = _validate_hash(
        expected_fill_set_hash,
        "expected_fill_set_hash",
    )
    normalized_detail_set_hash = _validate_hash(
        expected_detail_set_hash,
        "expected_detail_set_hash",
    )
    for value, name in (
        (expected_fill_count, "expected_fill_count"),
        (expected_detail_count, "expected_detail_count"),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return (
        normalized_run_id,
        expected_fill_count,
        expected_detail_count,
        normalized_report_hash,
        normalized_fill_set_hash,
        normalized_detail_set_hash,
    )


def _publication_run_row(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[object, ...]:
    row = connection.execute(
        """
        SELECT run_id, plan_sha256, dataset_hash, status, completed_at,
               summary_domain, summary_hash, summary_json, pinned, materialized,
               publication_fill_count, publication_detail_count,
               publication_fill_set_hash, publication_detail_set_hash,
               publication_fill_set_domain, publication_detail_set_domain,
               stage_revision
        FROM backtest_run WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown run_id: {run_id}")
    return tuple(row)


def _publication_run_input(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[BacktestRunInput | None, str | None]:
    row = _publication_input_row(connection, run_id)
    if row is None:
        return None, None
    try:
        snapshot = load_plan_json(str(row[4]))
        input_json = str(row[3])
        if dump_plan_json(snapshot) != str(row[4]) or plan_sha256(snapshot) != str(row[1]):
            raise RuntimeError("stored canonical plan snapshot failed verification")
        if _content_hash(_RUN_INPUT_HASH_DOMAIN, input_json) != str(row[2]):
            raise RuntimeError("stored backtest run input failed its content hash")
        payload = json.loads(input_json)
        if not isinstance(payload, dict):
            raise RuntimeError("stored backtest run input payload is invalid")
        run_input = BacktestRunInput.model_validate(
            {**payload, "plan_snapshot": snapshot},
            strict=False,
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError("stored backtest run input or plan is invalid") from error
    if (
        run_input.run_id != run_id
        or run_input.run_id != str(row[0])
        or run_input.plan_sha256 != str(row[1])
        or canonical_json(
            run_input.model_dump(
                mode="python",
                round_trip=True,
                exclude={"plan_snapshot"},
            )
        )
        != input_json
    ):
        raise RuntimeError("stored backtest run input identity is invalid")
    return run_input, _publication_input_fingerprint_from_row(row)


def _publication_input_row(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[object, ...] | None:
    row = connection.execute(
        """
        SELECT input.run_id, input.plan_sha256, input.input_hash, input.input_json,
               snapshot.snapshot_json
        FROM backtest_run_input AS input
        JOIN backtest_plan_snapshot AS snapshot
          ON snapshot.plan_sha256 = input.plan_sha256
        WHERE input.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    return None if row is None else tuple(row)


def _publication_input_fingerprint(
    connection: sqlite3.Connection,
    run_id: str,
) -> str | None:
    row = _publication_input_row(connection, run_id)
    return None if row is None else _publication_input_fingerprint_from_row(row)


def _publication_input_fingerprint_from_row(row: tuple[object, ...]) -> str:
    return _row_fingerprint(b"backtest-publication-input-v1\0", row)


def _publication_summary_fingerprint(row: tuple[object, ...]) -> str:
    return _row_fingerprint(b"backtest-publication-summary-v1\0", row[:9])


def _row_fingerprint(domain: bytes, row: tuple[object, ...]) -> str:
    digest = sha256(domain)
    for value in row:
        encoded = str(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _stored_publication_metadata(
    values: tuple[object, ...],
) -> tuple[int, int, str, str, str, str]:
    if len(values) != 6 or any(value is None for value in values):
        raise RuntimeError("materialized publication metadata is incomplete")
    return (
        int(values[0]),
        int(values[1]),
        str(values[2]),
        str(values[3]),
        str(values[4]),
        str(values[5]),
    )


def _proof_metadata(
    proof: VerifiedBacktestPublication,
) -> tuple[int, int, str, str, str, str]:
    return (
        proof.fill_count,
        proof.detail_count,
        proof.fill_set_hash,
        proof.detail_set_hash,
        proof.fill_set_domain,
        proof.detail_set_domain,
    )


def _require_store_connection(connection: sqlite3.Connection, path: Path) -> None:
    rows = tuple(connection.execute("PRAGMA database_list"))
    main_rows = tuple(row for row in rows if len(row) >= 3 and str(row[1]) == "main")
    if len(main_rows) != 1 or not str(main_rows[0][2]):
        raise ValueError("publication connection must have one file-backed main database")
    if Path(str(main_rows[0][2])).resolve() != path:
        raise ValueError("publication connection targets another result database")


def _require_item_size(payload_json: str, label: str) -> None:
    if len(payload_json.encode("utf-8")) > _MAX_ITEM_BYTES:
        raise ResultConflictError(f"{label} exceeds the 32 KiB publication limit")


def backtest_fill_set_hash(
    records: Iterable[BacktestFillRecord],
    *,
    version: str = "v1",
) -> str:
    """Hash an exact canonical fill identity/content set for publication."""

    entries: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, BacktestFillRecord):
            raise TypeError("records must contain BacktestFillRecord values")
        payload_json = _canonical_json(
            record.model_dump(mode="python", round_trip=True),
            version=version,
        )
        entries.append(
            (
                record.fill_id,
                _content_hash(_domain_bytes(_domain(_FILL_DOMAINS, version)), payload_json),
            )
        )
    return _record_set_hash(
        _domain_bytes(_domain(_FILL_SET_DOMAINS, version)),
        sorted(entries),
        version=version,
    )


def backtest_detail_set_hash(
    records: Iterable[BacktestDetailRecord],
    *,
    version: str = "v1",
) -> str:
    """Hash an exact canonical detail identity/content set for publication."""

    entries: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, BacktestDetailRecord):
            raise TypeError("records must contain BacktestDetailRecord values")
        payload_json = _canonical_json(
            record.model_dump(mode="python", round_trip=True),
            version=version,
        )
        entries.append(
            (
                record.detail_id,
                _content_hash(_domain_bytes(_domain(_DETAIL_DOMAINS, version)), payload_json),
            )
        )
    return _record_set_hash(
        _domain_bytes(_domain(_DETAIL_SET_DOMAINS, version)),
        sorted(entries),
        version=version,
    )


def _bounded_materialization_metadata(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    version: str,
) -> tuple[tuple[int, int, str, str, str, str], int, int]:
    fill_count, fill_hash, fill_batches, fill_maximum = _validated_fill_set_hash(
        connection,
        run_id,
        version=version,
    )
    detail_count, detail_hash, detail_batches, detail_maximum = _validated_detail_set_hash(
        connection,
        run_id,
        version=version,
    )
    return (
        (
            fill_count,
            detail_count,
            fill_hash,
            detail_hash,
            _domain(_FILL_SET_DOMAINS, version),
            _domain(_DETAIL_SET_DOMAINS, version),
        ),
        fill_batches + detail_batches,
        max(fill_maximum, detail_maximum),
    )


def _require_publication_metadata(
    actual: tuple[int, int, str, str, str, str],
    *,
    expected_fill_count: int,
    expected_detail_count: int,
    expected_fill_set_hash: str,
    expected_detail_set_hash: str,
    version: str,
    staged: bool,
) -> None:
    expected = (
        expected_fill_count,
        expected_detail_count,
        expected_fill_set_hash,
        expected_detail_set_hash,
        _domain(_FILL_SET_DOMAINS, version),
        _domain(_DETAIL_SET_DOMAINS, version),
    )
    if actual[:2] != expected[:2]:
        if staged:
            raise RuntimeError("staged backtest result is incomplete")
        raise ResultConflictError("materialized publication counts do not match")
    if actual[2] != expected[2]:
        label = "staged fill ledger" if staged else "materialized fill publication"
        raise ResultConflictError(f"{label} does not match the expected report")
    if actual[3] != expected[3]:
        label = "staged detail set" if staged else "materialized detail publication"
        raise ResultConflictError(f"{label} does not match the expected report")
    if actual[4:] != expected[4:]:
        raise ResultConflictError("publication set domains do not match the result version")


def _validated_fill_set_hash(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    version: str,
) -> tuple[int, str, int, int]:
    digest = sha256(_domain_bytes(_domain(_FILL_SET_DOMAINS, version)))
    cursor = connection.execute(
        """
        SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json
        FROM backtest_fill WHERE run_id = ? ORDER BY fill_id
        """,
        (run_id,),
    )
    count = 0
    batch_count = 0
    maximum = 0
    while rows := cursor.fetchmany(_MAX_BATCH_SIZE):
        batch_count += 1
        maximum = max(maximum, len(rows))
        for row in rows:
            _require_item_size(str(row[5]), "backtest fill")
            expected_domain = _domain(_FILL_DOMAINS, version)
            record = _load_fill(str(row[3]), str(row[4]), str(row[5]))
            if (
                record.fill_id != str(row[0])
                or record.run_id != str(row[1])
                or record.run_id != run_id
                or _datetime_text(record.filled_at, version=version) != str(row[2])
                or str(row[3]) != expected_domain
            ):
                raise ResultConflictError("staged fill row identity is invalid")
            _update_record_set_hash(
                digest,
                record.fill_id,
                str(row[4]),
                version=version,
            )
            count += 1
    return count, digest.hexdigest(), batch_count, maximum


def _validated_detail_set_hash(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    version: str,
) -> tuple[int, str, int, int]:
    digest = sha256(_domain_bytes(_domain(_DETAIL_SET_DOMAINS, version)))
    cursor = connection.execute(
        """
        SELECT detail_id, run_id, kind, event_at, content_domain, content_hash, payload_json
        FROM backtest_detail WHERE run_id = ? ORDER BY detail_id
        """,
        (run_id,),
    )
    count = 0
    batch_count = 0
    maximum = 0
    while rows := cursor.fetchmany(_MAX_BATCH_SIZE):
        batch_count += 1
        maximum = max(maximum, len(rows))
        for row in rows:
            _require_item_size(str(row[6]), "backtest detail")
            expected_domain = _domain(_DETAIL_DOMAINS, version)
            record = _load_detail(str(row[4]), str(row[5]), str(row[6]))
            if (
                record.detail_id != str(row[0])
                or record.run_id != str(row[1])
                or record.run_id != run_id
                or record.kind.value != str(row[2])
                or _datetime_text(record.event_at, version=version) != str(row[3])
                or str(row[4]) != expected_domain
            ):
                raise ResultConflictError("staged detail row identity is invalid")
            _update_record_set_hash(
                digest,
                record.detail_id,
                str(row[5]),
                version=version,
            )
            count += 1
    return count, digest.hexdigest(), batch_count, maximum


def _record_set_hash(
    domain: bytes,
    entries: Iterable[tuple[str, str]],
    *,
    version: str,
) -> str:
    digest = sha256(domain)
    for identity, content_hash in entries:
        _update_record_set_hash(digest, identity, content_hash, version=version)
    return digest.hexdigest()


def _update_record_set_hash(
    digest: _HashDigest,
    identity: str,
    content_hash: str,
    *,
    version: str,
) -> None:
    digest.update(
        _canonical_json(
            {"contentHash": content_hash, "identity": identity},
            version=version,
        ).encode("utf-8")
    )
    digest.update(b"\n")


def _bounded_values(values: Iterable[object], name: str) -> tuple[object, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise TypeError(f"{name} must be an iterable of records")
    try:
        iterator = iter(values)
    except TypeError:
        raise TypeError(f"{name} must be an iterable of records") from None
    bounded = tuple(islice(iterator, _MAX_BATCH_SIZE + 1))
    if len(bounded) > _MAX_BATCH_SIZE:
        raise ValueError(f"{name} may contain at most 1000 records")
    return bounded


def _model_or_mapping(
    value: BaseModel | Mapping[str, object],
    name: str,
) -> dict[str, object]:
    if isinstance(value, BaseModel):
        raw = value.model_dump(mode="python", round_trip=True)
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError(f"{name} must be a Pydantic model or mapping")
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{name} keys must be strings")
    return raw


def _canonical_mapping(value: object, *, version: str = "v1") -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    canonical = _canonical_value(value, version=version)
    if not isinstance(canonical, dict):
        raise TypeError("value must canonicalize to an object")
    return canonical


def _canonical_value(value: object, *, version: str) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(
            value.model_dump(mode="python", round_trip=True),
            version=version,
        )
    if isinstance(value, Enum):
        return _canonical_value(value.value, version=version)
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        return _datetime_text(value, version=version)
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical floats must be finite")
        raise ValueError("canonical result values must not use binary floating point")
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError("canonical object keys must be strings")
            normalized[key] = _canonical_value(value[key], version=version)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, version=version) for item in value]
    raise TypeError(f"unsupported canonical result value: {type(value).__name__}")


def _canonical_json(value: object, *, version: str = "v1") -> str:
    _validate_version(version)
    return json.dumps(
        _canonical_value(value, version=version),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _content_hash(domain: bytes, canonical_json: str) -> str:
    return sha256(domain + canonical_json.encode("utf-8")).hexdigest()


def _normalize_datetime(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _datetime_text(value: datetime, *, version: str = "v1") -> str:
    _validate_version(version)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("result datetime must be timezone-aware")
    if version == "v2":
        return format_shanghai_datetime(value.astimezone(_SHANGHAI))
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _first_string(payload: Mapping[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_datetime(payload: Mapping[str, object], keys: tuple[str, ...]) -> datetime | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, datetime):
            return value
    return None


def _validate_hash(value: str, name: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _materialized_count(connection: sqlite3.Connection, table: str) -> int:
    if table not in {"backtest_fill", "backtest_detail"}:
        raise ValueError("unsupported result count table")
    return int(
        connection.execute(
            f"""
            SELECT COUNT(*) FROM {table} AS item
            JOIN backtest_run AS run ON run.run_id = item.run_id
            WHERE run.materialized = 1
            """
        ).fetchone()[0]
    )


def _now_text(version: str) -> str:
    zone = _SHANGHAI if version == "v2" else UTC
    return _datetime_text(datetime.now(zone), version=version)


def _validate_version(version: str) -> str:
    if version not in _VERSIONS:
        raise ValueError("result version must be v1 or v2")
    return version


def _domain(domains: Mapping[str, str], version: str) -> str:
    return domains[_validate_version(version)]


def _version_from_domain(value: str, domains: Mapping[str, str]) -> str:
    for version, domain in domains.items():
        if value == domain:
            return version
    raise RuntimeError("stored backtest result domain is unsupported")


def _domain_bytes(value: str) -> bytes:
    return value.encode("ascii") + b"\0"


def _validate_summary_input(
    summary: BacktestRunSummary,
    run_input: BacktestRunInput,
) -> None:
    if not isinstance(summary, BacktestRunSummary):
        raise TypeError("summary must be a BacktestRunSummary")
    if not isinstance(run_input, BacktestRunInput):
        raise TypeError("run_input must be a BacktestRunInput")
    expected = (
        run_input.run_id,
        run_input.plan_sha256,
        run_input.dataset_hash,
        run_input.start,
        run_input.end,
        (run_input.plan_snapshot.symbol,),
    )
    actual = (
        summary.run_id,
        summary.plan_sha256,
        summary.dataset_hash,
        summary.event_start,
        summary.event_end,
        summary.symbols,
    )
    if actual != expected:
        raise ValueError("summary identity must match the canonical run input")
    if summary.status is not BacktestRunStatus.COMPLETED:
        raise ValueError("backtest results are completed-only")
    expected_versions = {
        "execution": run_input.execution_config.formula_version,
        "indicator": run_input.indicator_formula_version,
        "runner": run_input.run_formula_version,
    }
    if any(summary.formula_versions.get(key) != value for key, value in expected_versions.items()):
        raise ValueError("summary formula versions must match the canonical run input")
    if (
        summary.assumptions.get("executionConfigHash") != run_input.execution_config.config_hash
        or summary.assumptions.get("manualEventRisk") is not run_input.manual_event_risk
    ):
        raise ValueError("summary assumptions must match the canonical run input")


__all__ = [
    "BacktestDetailKind",
    "BacktestDetailRecord",
    "BacktestFillRecord",
    "BacktestResultStatistics",
    "BacktestResultStore",
    "BacktestRunStatus",
    "BacktestRunSummary",
    "ResultConflictError",
    "RetentionPruneResult",
    "VerifiedBacktestPublication",
    "backtest_detail_set_hash",
    "backtest_fill_set_hash",
]
