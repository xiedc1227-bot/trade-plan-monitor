"""Isolated SQLite persistence and bounded retention for backtest results."""

from __future__ import annotations

import base64
import json
import math
import sqlite3
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping
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
_PIN_REQUEST_HASH_DOMAIN = b"backtest-pin-request-v1\0"
_PIN_RESPONSE_HASH_DOMAIN = b"backtest-pin-response-v1\0"
_PIN_IDEMPOTENCY_DAYS = 14
_MAX_EQUITY_POINTS = 2_000
_DETAIL_PAYLOAD_MAGIC = b"TPM-DETAIL-ZLIB-DICT-V1\0"
_DETAIL_COMPRESSION_DICTIONARY = zlib.decompress(
    base64.b85decode(
        "".join(
            """
            c-rk+ZBwI25dJTGy=XzqoB4)hG}IArfoOSKTT>$$&6EVPFvRmL|NHd-0TT1Nt9x5l<bxH+bWiuwFVpjsuhN8a!hFmoQeTo95?
            #=MW5VI7DK|SOa`&X!b7iG}*6u6KQ#t+oA<KPPhSg6j5OM>g>5guh@Mcb4{E)!QSLxmly(b#QQvd5Wp_upy;VcYbFW7_emvm7AYdEH<o_9O
            S^7@VsVKhs8f)}6|bb$~jCkv&tMK@hr9jJH07M}!oO5$neTKqD*4}JLFNmZUYL+Py{1@v!@V@~J78ZVqsSa7TAF21yEtXZRL1Gxxas5WQ_LXPh#m
            ;j4{#P=IgM8792q7%%5dBRgy-^ANE@p*M?a6Eosu+9sE2@@#fu*B>!AOL^B0h6WHI3V+Q8uHAfTmaLB0M3KGzZRBW+sJXoHo~qo)`kKf;-zN1N>3C3m
            gZnfoJ17+;WK`q0W3)ZCc=A(M7%^)KvAdHliwQegr@9qx<jffH{~~QV#eZ_1&<XF8d8{WFPsS*$EKsYx^t<cfh6|urp%v2pfvTPd;p=sS>ZW<nP)EQ8p
            67X|FTR3d;b##RnJ8X-#g7by35;EXT@8w8dAPkJWyTa>LXN2>`%>7pD^$!xKn{cpe`g>;Q7fU-KAWAVOa)JD>6Jv=zAHl(LSM{iRpS6vkC_pSJhlyQw`Yb
            dqVOKpvZD#8EFR@hI(Nj{AH|~uI}F9D|cgjW9s|l-lw?GQ~2WyRY;7|oeF40t?rist19^s##sU8o)l7=HK?XY;a@50B~c{$DUS#sKOvm1CfUXWlRmGcW
            -MT{WQHTrh(V8h+L8+R$Jf`$#<#lmC$>SmwGI7bKBp0WX5Q0|d{s&i?nwk229LWcvRN*#sL#wSBvPv?kjba*3f8N>?GS1m0Pw-t{T@+SDIv9yYa<oT
            65ASK2O1U}l6a_J4Yy}@ERMB(-2fU`1z;cYD(3jOt`|`rQNj-k;d1d_Y@r`2?N+zj>OnepnhN}p+udHT-R*Xi^LFQ~eb$!Soz{617MypLP8SyaNDu+
            #UsomyBw7*E8_O7v#DR-PXrQZR8p?+B4C4p%d`NaML-gt*wwuh9Y|Aio^9twMZgq2D-AXIgk95cvSfZQPV|QO3=EiA;<)nut3@q5NZlR!us&Tm~)jU
            6pDdx|+lSXNtR}UUh%QH5ahfH*}<7M~vfn!Q@9fXzP>Vv|#AKGt)PSr3r7IiuOEdy9NL&m1NvF4KC2syc0LK%7o?6nu`qf#)(tReYuiSVn#sf{
            j?jZ6)d@N1UoAZ_gGHwdT5I`{$ss@Om`$k;s8<wI#iA7~^7;a$D%T<%nkVaN#TC7dm27TI$AQSCj$!mjnrBU{js`FhCd{Ie&}?@}}$oIVxx=G}i
            (lg-bm$;0#M;0x484C!??|FUfU9S)oyNpAW0b_rJ|f~S=Dd@2$=eIzhJKs$#($703+_u*uiW;fTyau^oF#=)dg(d<+GV9MO5oGvxSobUv;k_?E
            ?RvwAYS)6h*8HJP6U7+(&E^S64!GvWl^1}@O4DxD?HA^2;c5s@I7jhDVoqYMeVBwTTaZS!li7J=#K6H=b%D&?#4r$ChV8d2^-tso&tFMIR#RVw6>wt
            qSeo7}3xV(7N>McA+VBOb<g%QpM<6KSqT;Q}|nVWJY8#Lfe?9J%_1u&m%3w|2Ab?#`%1Lk!tVz^Cp-oC912iZ5GcbY;Td<)_#v6uui$fmV+ShI#T
            Ygn^}HEUS2hBa$gvxYTmShI#TYgn^}HEUS&EH!IbvxYTm_`hHc#Xn#rIcFuk{R^=DT2B
            """.split()
        )
    )
)
_PUBLIC_ARTIFACT_KINDS = (
    "DAILY_EQUITY",
    "DECISION",
    "EXECUTION_OUTCOME",
    "SIGNAL",
)
_COVERAGE_FIELDS = {
    "DAILY_EQUITY": "dailyEquityCount",
    "DECISION": "decisionCount",
    "EXECUTION_OUTCOME": "outcomeCount",
    "SIGNAL": "signalCount",
}
_ARTIFACT_COLUMNS = {
    "DAILY_EQUITY": ("daily_equity_original_count", "daily_equity_expired_at"),
    "DECISION": ("decision_original_count", "decision_expired_at"),
    "EXECUTION_OUTCOME": ("outcome_original_count", "outcome_expired_at"),
    "SIGNAL": ("signal_original_count", "signal_expired_at"),
}

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


class ExportCancelled(RuntimeError):
    """Internal control signal raised before the next bounded export batch."""


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


class BacktestArtifactAvailability(StrEnum):
    """Public lifecycle of one optional completed-result artifact family."""

    AVAILABLE = "AVAILABLE"
    EXPIRED = "EXPIRED"
    NOT_RECORDED = "NOT_RECORDED"


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


class BacktestArtifactState(_ResultValue):
    """Persisted original count plus its derived public availability."""

    kind: BacktestDetailKind
    availability: BacktestArtifactAvailability
    original_count: Annotated[int, Field(strict=True, ge=0)]


class BacktestRunRecord(_ResultValue):
    """Application-facing completed run with mutable metadata kept outside identity."""

    summary: BacktestRunSummary
    plan_version_id: str | None
    revision: Annotated[int, Field(strict=True, ge=0)]
    fill_count: Annotated[int, Field(strict=True, ge=0)]
    availability: tuple[BacktestArtifactState, ...]


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
    artifact_counts: tuple[tuple[str, int], ...]
    summary_fingerprint: str
    input_fingerprint: str | None
    already_materialized: bool
    read_batch_count: int
    max_read_batch_size: int
    _store_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class BacktestRunQueryRow:
    record: BacktestRunRecord
    position: tuple[str, str]


@dataclass(frozen=True, slots=True)
class BacktestFillQueryRow:
    record: BacktestFillRecord
    position: tuple[str, str]


@dataclass(frozen=True, slots=True)
class BacktestDetailQueryRow:
    record: BacktestDetailRecord
    position: tuple[str, str]


@dataclass(frozen=True, slots=True)
class BacktestDetailReadSnapshot:
    """Availability, traversal fence, and rows from one SQLite read snapshot."""

    state: BacktestArtifactState
    high_water: tuple[str, str] | None
    rows: tuple[BacktestDetailQueryRow, ...]


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

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            created = self._record_run_input_participant(connection, run_input)
            connection.commit()
        return created

    def _record_run_input_participant(
        self,
        connection: sqlite3.Connection,
        run_input: BacktestRunInput,
    ) -> bool:
        """Persist canonical input rows inside the caller-owned transaction."""

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
            "SELECT plan_sha256, input_hash, input_json FROM backtest_run_input WHERE run_id = ?",
            (run_input.run_id,),
        ).fetchone()
        if existing is not None:
            if tuple(map(str, existing)) != (
                run_input.plan_sha256,
                input_hash,
                input_json,
            ):
                raise ResultConflictError("conflicting canonical input under an existing run_id")
            return False
        connection.execute(
            "INSERT INTO backtest_run_input "
            "(run_id, plan_sha256, input_hash, input_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_input.run_id, run_input.plan_sha256, input_hash, input_json, now),
        )
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_run_input_participant(connection, run_input)
            created = self._record_run_participant(
                connection,
                summary,
                version="v2",
                retention_at=retention_at,
            )
            connection.commit()
        return created

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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            created = self._record_run_participant(
                connection,
                summary,
                version=version,
                retention_at=retention_at,
            )
            connection.commit()
        return created

    def _record_run_participant(
        self,
        connection: sqlite3.Connection,
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
        existing = connection.execute(
            "SELECT summary_hash FROM backtest_run WHERE run_id = ?",
            (summary.run_id,),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != summary_hash:
                raise ResultConflictError("conflicting summary content under an existing run_id")
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

    def get_result_run(self, run_id: str) -> BacktestRunRecord | None:
        """Return one active v2 completed result with verified mutable metadata."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        rows = self._query_result_runs(run_id=normalized_run_id, limit=1)
        return None if not rows else rows[0].record

    def export_summary(self, run_id: str) -> BacktestRunSummary:
        """Return one verified active-v2 summary for incremental export encoding."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        with self._connect() as connection:
            summary, _fill_count, _fill_set_hash = _active_v2_export_metadata(
                connection,
                normalized_run_id,
            )
        return summary

    def iter_export_fill_batches(
        self,
        run_id: str,
        cancelled: Callable[[], bool],
    ) -> Iterator[tuple[BacktestFillRecord, ...]]:
        """Yield verified active-v2 fills from one stable snapshot in bounded batches."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        if not callable(cancelled):
            raise TypeError("cancelled must be callable")
        with self._connect() as connection:
            connection.execute("BEGIN")
            _summary, expected_count, expected_set_hash = _active_v2_export_metadata(
                connection,
                normalized_run_id,
            )
            actual_count, actual_set_hash, _batch_count, _maximum = _validated_export_fill_set_hash(
                connection,
                normalized_run_id,
                cancelled=cancelled,
            )
            if (actual_count, actual_set_hash) != (expected_count, expected_set_hash):
                raise RuntimeError("materialized v2 fill ledger failed publication verification")
            cursor = connection.execute(
                """
                SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json
                FROM backtest_fill
                WHERE run_id = ?
                ORDER BY filled_at, fill_id
                """,
                (normalized_run_id,),
            )
            yielded = 0
            while True:
                if cancelled():
                    raise ExportCancelled
                rows = cursor.fetchmany(_MAX_BATCH_SIZE)
                if not rows:
                    break
                batch = tuple(
                    _load_fill_row(tuple(row), expected_run_id=normalized_run_id) for row in rows
                )
                if any(
                    _datetime_text(record.filled_at, version="v2") != str(row[2])
                    or str(row[3]) != _FILL_DOMAINS["v2"]
                    for record, row in zip(batch, rows, strict=True)
                ):
                    raise RuntimeError("materialized v2 fill ledger contains a non-v2 row")
                yielded += len(batch)
                yield batch
            if yielded != expected_count:
                raise RuntimeError("materialized v2 fill ledger changed during export")

    def result_run_high_water(self) -> int:
        """Capture the immutable publication-membership fence for one traversal."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(catalog_revision), 0) FROM backtest_run
                WHERE materialized = 1 AND summary_domain = 'backtest-run-summary-v2'
                """
            ).fetchone()
        return int(row[0])

    def result_pin_membership_revision(self) -> int:
        """Return a monotone fence for mutable public pin membership."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(pin_revision), 0) FROM backtest_run
                WHERE materialized = 1 AND summary_domain = 'backtest-run-summary-v2'
                """
            ).fetchone()
        return int(row[0])

    def query_result_runs(
        self,
        *,
        limit: int,
        snapshot_revision: int,
        symbol: str | None = None,
        plan_version_id: str | None = None,
        dataset_hash: str | None = None,
        completed_from: datetime | None = None,
        completed_to: datetime | None = None,
        pinned: bool | None = None,
        high_water: tuple[str, str] | None = None,
        last_seen: tuple[str, str] | None = None,
    ) -> tuple[BacktestRunQueryRow, ...]:
        """Read one bounded descending keyset page behind an insertion fence."""

        if type(limit) is not int or not 1 <= limit <= 101:
            raise ValueError("query limit must be between 1 and 101")
        if type(snapshot_revision) is not int or snapshot_revision < 0:
            raise ValueError("snapshot_revision must be a non-negative integer")
        if dataset_hash is not None:
            dataset_hash = _validate_hash(dataset_hash, "dataset_hash")
        if pinned is not None and type(pinned) is not bool:
            raise TypeError("pinned must be a bool or None")
        if high_water is not None:
            _require_position(high_water, "high_water")
        if last_seen is not None:
            _require_position(last_seen, "last_seen")
        clauses = [
            "r.materialized = 1",
            "r.summary_domain = 'backtest-run-summary-v2'",
            "r.catalog_revision IS NOT NULL",
            "r.catalog_revision <= ?",
        ]
        parameters: list[object] = [snapshot_revision]
        if symbol is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(r.summary_json, '$.symbols') WHERE value = ?)"
            )
            parameters.append(symbol)
        if plan_version_id is not None:
            clauses.append("json_extract(input.input_json, '$.plan_version_id') = ?")
            parameters.append(plan_version_id)
        if dataset_hash is not None:
            clauses.append("r.dataset_hash = ?")
            parameters.append(dataset_hash)
        if completed_from is not None:
            clauses.append("r.completed_at >= ?")
            parameters.append(_datetime_text(completed_from, version="v2"))
        if completed_to is not None:
            clauses.append("r.completed_at <= ?")
            parameters.append(_datetime_text(completed_to, version="v2"))
        if pinned is not None:
            clauses.append("r.pinned = ?")
            parameters.append(int(pinned))
        if high_water is not None:
            clauses.append("(r.completed_at < ? OR (r.completed_at = ? AND r.run_id <= ?))")
            parameters.extend((high_water[0], high_water[0], high_water[1]))
        if last_seen is not None:
            clauses.append("(r.completed_at < ? OR (r.completed_at = ? AND r.run_id < ?))")
            parameters.extend((last_seen[0], last_seen[0], last_seen[1]))
        parameters.append(limit)
        query = f"""
            SELECT r.run_id, r.plan_sha256, r.dataset_hash, r.status, r.completed_at,
                   r.summary_domain, r.summary_hash, r.summary_json, r.pinned,
                   r.pin_revision, r.publication_fill_count,
                   input.run_id, input.plan_sha256, input.input_hash, input.input_json,
                   snapshot.snapshot_json
            FROM backtest_run AS r
            JOIN backtest_run_input AS input ON input.run_id = r.run_id
            JOIN backtest_plan_snapshot AS snapshot
              ON snapshot.plan_sha256 = input.plan_sha256
            WHERE {" AND ".join(clauses)}
            ORDER BY r.completed_at DESC, r.run_id DESC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = tuple(connection.execute(query, tuple(parameters)).fetchall())
            availability = _availability_by_run(
                connection,
                tuple(str(row[0]) for row in rows),
            )
            return tuple(_load_run_query_row(tuple(row), availability[str(row[0])]) for row in rows)

    def _query_result_runs(
        self,
        *,
        run_id: str,
        limit: int,
    ) -> tuple[BacktestRunQueryRow, ...]:
        with self._connect() as connection:
            rows = tuple(
                connection.execute(
                    """
                    SELECT r.run_id, r.plan_sha256, r.dataset_hash, r.status, r.completed_at,
                           r.summary_domain, r.summary_hash, r.summary_json, r.pinned,
                           r.pin_revision, r.publication_fill_count,
                           input.run_id, input.plan_sha256, input.input_hash,
                           input.input_json, snapshot.snapshot_json
                    FROM backtest_run AS r
                    JOIN backtest_run_input AS input ON input.run_id = r.run_id
                    JOIN backtest_plan_snapshot AS snapshot
                      ON snapshot.plan_sha256 = input.plan_sha256
                    WHERE r.run_id = ? AND r.materialized = 1
                      AND r.summary_domain = 'backtest-run-summary-v2'
                      AND r.catalog_revision IS NOT NULL
                    LIMIT ?
                    """,
                    (run_id, limit),
                ).fetchall()
            )
            availability = _availability_by_run(
                connection,
                tuple(str(row[0]) for row in rows),
            )
            return tuple(_load_run_query_row(tuple(row), availability[str(row[0])]) for row in rows)

    def query_result_fills(
        self,
        run_id: str,
        *,
        limit: int,
        high_water: tuple[str, str] | None,
        last_seen: tuple[str, str] | None,
    ) -> tuple[BacktestFillQueryRow, ...]:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if type(limit) is not int or not 1 <= limit <= 101:
            raise ValueError("query limit must be between 1 and 101")
        clauses = ["f.run_id = ?", "r.materialized = 1"]
        parameters: list[object] = [normalized_run_id]
        for value, name, operator in (
            (high_water, "high_water", "<="),
            (last_seen, "last_seen", ">"),
        ):
            if value is not None:
                _require_position(value, name)
                clauses.append(f"(f.filled_at, f.fill_id) {operator} (?, ?)")
                parameters.extend(value)
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT f.fill_id, f.run_id, f.filled_at, f.content_domain,
                       f.content_hash, f.payload_json
                FROM backtest_fill AS f
                JOIN backtest_run AS r ON r.run_id = f.run_id
                WHERE {" AND ".join(clauses)}
                ORDER BY f.filled_at, f.fill_id
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(
            BacktestFillQueryRow(
                record=_load_fill_row(tuple(row), expected_run_id=normalized_run_id),
                position=(str(row[2]), str(row[0])),
            )
            for row in rows
        )

    def result_fill_high_water(self, run_id: str) -> tuple[str, str] | None:
        return self._result_item_high_water(run_id, table="backtest_fill")

    def query_result_details(
        self,
        run_id: str,
        *,
        kind: BacktestDetailKind,
        limit: int,
        high_water: tuple[str, str] | None,
        last_seen: tuple[str, str] | None,
    ) -> tuple[BacktestDetailQueryRow, ...]:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if not isinstance(kind, BacktestDetailKind):
            raise TypeError("kind must be a BacktestDetailKind")
        if type(limit) is not int or not 1 <= limit <= 2_001:
            raise ValueError("query limit must be between 1 and 2001")
        if high_water is not None:
            _require_position(high_water, "high_water")
        if last_seen is not None:
            _require_position(last_seen, "last_seen")
        with self._connect() as connection:
            return _query_result_detail_rows(
                connection,
                normalized_run_id,
                kind=kind,
                limit=limit,
                high_water=high_water,
                last_seen=last_seen,
            )

    def read_result_detail_snapshot(
        self,
        run_id: str,
        *,
        kind: BacktestDetailKind,
        limit: int,
        high_water: tuple[str, str] | None,
        last_seen: tuple[str, str] | None,
    ) -> BacktestDetailReadSnapshot | None:
        """Read availability, traversal fence, and rows from one short WAL snapshot."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        if not isinstance(kind, BacktestDetailKind):
            raise TypeError("kind must be a BacktestDetailKind")
        if kind.value not in _PUBLIC_ARTIFACT_KINDS:
            raise ValueError("kind is not a public result artifact")
        if type(limit) is not int or not 1 <= limit <= 2_001:
            raise ValueError("query limit must be between 1 and 2001")
        if high_water is not None:
            _require_position(high_water, "high_water")
        if last_seen is not None:
            _require_position(last_seen, "last_seen")
        if last_seen is not None and high_water is None:
            raise ValueError("last_seen requires a high_water position")
        with self._connect() as connection:
            connection.execute("BEGIN")
            state = _artifact_state(connection, normalized_run_id, kind)
            if state is None:
                connection.commit()
                return None
            if state.availability is not BacktestArtifactAvailability.AVAILABLE:
                snapshot = BacktestDetailReadSnapshot(state=state, high_water=None, rows=())
            else:
                resolved_high_water = high_water or _result_detail_high_water(
                    connection,
                    normalized_run_id,
                    kind,
                )
                if resolved_high_water is None:
                    raise RuntimeError("available backtest artifact is missing its high-water mark")
                rows = _query_result_detail_rows(
                    connection,
                    normalized_run_id,
                    kind=kind,
                    limit=limit,
                    high_water=resolved_high_water,
                    last_seen=last_seen,
                )
                snapshot = BacktestDetailReadSnapshot(
                    state=state,
                    high_water=resolved_high_water,
                    rows=rows,
                )
            connection.commit()
        return snapshot

    def result_detail_high_water(
        self,
        run_id: str,
        *,
        kind: BacktestDetailKind,
    ) -> tuple[str, str] | None:
        normalized_run_id = _validate_hash(run_id, "run_id")
        with self._connect() as connection:
            return _result_detail_high_water(connection, normalized_run_id, kind)

    def artifact_state(
        self,
        run_id: str,
        kind: BacktestDetailKind,
    ) -> BacktestArtifactState | None:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if kind.value not in _PUBLIC_ARTIFACT_KINDS:
            raise ValueError("kind is not a public result artifact")
        with self._connect() as connection:
            return _artifact_state(connection, normalized_run_id, kind)

    def _result_item_high_water(
        self,
        run_id: str,
        *,
        table: str,
    ) -> tuple[str, str] | None:
        normalized_run_id = _validate_hash(run_id, "run_id")
        if table != "backtest_fill":
            raise ValueError("unsupported result item table")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT f.filled_at, f.fill_id
                FROM backtest_fill AS f
                JOIN backtest_run AS r ON r.run_id = f.run_id
                WHERE f.run_id = ? AND r.materialized = 1
                ORDER BY f.filled_at DESC, f.fill_id DESC LIMIT 1
                """,
                (normalized_run_id,),
            ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

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
                "UPDATE backtest_run SET pinned = ?, pin_revision = pin_revision + 1 "
                "WHERE run_id = ?",
                (int(pinned), normalized_run_id),
            )
            connection.commit()
        return True

    def set_pinned_idempotent(
        self,
        run_id: str,
        *,
        pinned: bool,
        expected_revision: int,
        idempotency_key: str,
        recorded_at: datetime,
    ) -> BacktestRunRecord:
        """Atomically apply or replay one revision-checked pin intent."""

        normalized_run_id = _validate_hash(run_id, "run_id")
        if type(pinned) is not bool:
            raise TypeError("pinned must be a bool")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        normalized_key = _validate_stable_identifier(idempotency_key, "idempotency_key")
        normalized_recorded_at = _normalize_datetime(recorded_at, "recorded_at")
        recorded_text = _datetime_text(normalized_recorded_at, version="v2")
        expires_text = _datetime_text(
            normalized_recorded_at + timedelta(days=_PIN_IDEMPOTENCY_DAYS),
            version="v2",
        )
        request_json = canonical_json(
            {
                "expectedRevision": expected_revision,
                "pinned": pinned,
                "runId": normalized_run_id,
            }
        )
        request_hash = _content_hash(_PIN_REQUEST_HASH_DOMAIN, request_json)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = _find_pin_idempotency(
                connection,
                normalized_key,
                as_of=recorded_text,
            )
            if existing is not None:
                if existing["requestHash"] != request_hash:
                    raise ResultConflictError("idempotency key already belongs to another intent")
                response_json = existing["responseJson"]
                if (
                    _content_hash(_PIN_RESPONSE_HASH_DOMAIN, response_json)
                    != existing["responseHash"]
                ):
                    raise RuntimeError("stored pin idempotency response failed its content hash")
                try:
                    response = BacktestRunRecord.model_validate_json(response_json)
                except (TypeError, ValueError) as error:
                    raise RuntimeError("stored pin idempotency response is invalid") from error
                connection.commit()
                return response

            row = _active_result_run_row(connection, normalized_run_id)
            if row is None:
                raise KeyError(f"unknown run_id: {normalized_run_id}")
            current_revision = int(row[9])
            if current_revision != expected_revision:
                raise ResultConflictError("pin revision does not match expected revision")
            current_pinned = bool(row[8])
            if current_pinned is not pinned:
                cursor = connection.execute(
                    """
                    UPDATE backtest_run
                    SET pinned = ?, pin_revision = pin_revision + 1
                    WHERE run_id = ? AND pin_revision = ? AND materialized = 1
                    """,
                    (int(pinned), normalized_run_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise ResultConflictError("pin revision changed before update")
                row = _active_result_run_row(connection, normalized_run_id)
                assert row is not None
            availability = _availability_by_run(connection, (normalized_run_id,))[normalized_run_id]
            response = _load_run_query_row(row, availability).record
            response_json = canonical_json(response.model_dump(mode="python", round_trip=True))
            _require_item_size(response_json, "pin response")
            response_hash = _content_hash(_PIN_RESPONSE_HASH_DOMAIN, response_json)
            stored_map = connection.execute(
                "SELECT pin_idempotency_json FROM backtest_run WHERE run_id = ?",
                (normalized_run_id,),
            ).fetchone()
            if stored_map is None:
                raise KeyError(f"unknown run_id: {normalized_run_id}")
            idempotency = _load_pin_idempotency_map(str(stored_map[0]))
            if normalized_key in idempotency:
                raise RuntimeError("pin idempotency key was duplicated during one transaction")
            idempotency[normalized_key] = {
                "expiresAt": expires_text,
                "recordedAt": recorded_text,
                "requestHash": request_hash,
                "responseHash": response_hash,
                "responseJson": response_json,
            }
            idempotency_json = canonical_json(idempotency)
            if len(idempotency_json.encode("utf-8")) >= 4 * 1024 * 1024:
                raise ResultConflictError("pin idempotency metadata exceeds 4 MiB")
            connection.execute(
                "UPDATE backtest_run SET pin_idempotency_json = ? WHERE run_id = ?",
                (idempotency_json, normalized_run_id),
            )
            connection.commit()
        return response

    def prune_details(
        self,
        *,
        as_of: datetime,
        batch_size: int = _MAX_BATCH_SIZE,
    ) -> RetentionPruneResult:
        """Compatibility wrapper for the caller-budgeted result participant."""

        if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError("batch_size must be between 1 and 1000")
        return self.prune_result_rows(as_of=as_of, remaining_budget=batch_size)

    def prune_result_rows(
        self,
        *,
        as_of: datetime,
        remaining_budget: int,
    ) -> RetentionPruneResult:
        """Consume at most the caller's remaining maintenance row budget once."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self.prune_result_rows_participant(
                connection,
                as_of=as_of,
                remaining_budget=remaining_budget,
            )
            connection.commit()
        return result

    def prune_result_rows_participant(
        self,
        connection: sqlite3.Connection,
        *,
        as_of: datetime,
        remaining_budget: int,
    ) -> RetentionPruneResult:
        """Consume remaining row budget inside the jobs-owned maintenance transaction."""

        _require_store_connection(connection, self._path)
        normalized_as_of = _normalize_datetime(as_of, "as_of")
        if type(remaining_budget) is not int or not 0 <= remaining_budget <= _MAX_BATCH_SIZE:
            raise ValueError("remaining_budget must be between 0 and 1000")
        parameters = _retention_parameters(normalized_as_of)
        staged_cutoffs = parameters[:2]
        retention_parameters = parameters[2:]
        stale_input_query = _stale_run_input_query(connection)
        if remaining_budget == 0:
            has_more = _result_retention_has_more(
                connection,
                staged_cutoffs=staged_cutoffs,
                retention_parameters=retention_parameters,
                stale_input_query=stale_input_query,
            )
            return RetentionPruneResult(deleted_count=0, has_more=has_more)
        deleted_count = 0
        remaining = remaining_budget
        staged_detail_ids = _candidate_ids(
            connection,
            _STALE_STAGED_DETAIL_SQL,
            (*staged_cutoffs, remaining),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_detail",
            "detail_id",
            staged_detail_ids,
        )
        remaining = remaining_budget - deleted_count
        staged_fill_ids = _candidate_ids(
            connection,
            _STALE_STAGED_FILL_SQL,
            (*staged_cutoffs, remaining),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_fill",
            "fill_id",
            staged_fill_ids,
        )
        remaining = remaining_budget - deleted_count
        staged_run_ids = _candidate_ids(
            connection,
            _STALE_STAGED_RUN_SQL,
            (*staged_cutoffs, remaining),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_run",
            "run_id",
            staged_run_ids,
        )
        remaining = remaining_budget - deleted_count
        stale_input_ids = _candidate_ids(
            connection,
            stale_input_query,
            (staged_cutoffs[1], remaining),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_run_input",
            "run_id",
            stale_input_ids,
        )
        remaining = remaining_budget - deleted_count
        stale_snapshot_ids = _candidate_ids(
            connection,
            _STALE_PLAN_SNAPSHOT_SQL,
            (staged_cutoffs[1], remaining),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_plan_snapshot",
            "plan_sha256",
            stale_snapshot_ids,
        )
        remaining = remaining_budget - deleted_count
        retained_detail_ids = _candidate_ids(
            connection,
            _RETENTION_CANDIDATES_SQL,
            (*retention_parameters, remaining),
        )
        _mark_expired_artifacts(
            connection,
            retained_detail_ids,
            expired_at=_datetime_text(normalized_as_of, version="v2"),
        )
        deleted_count += _delete_ids(
            connection,
            "backtest_detail",
            "detail_id",
            retained_detail_ids,
        )
        has_more = _result_retention_has_more(
            connection,
            staged_cutoffs=staged_cutoffs,
            retention_parameters=retention_parameters,
            stale_input_query=stale_input_query,
        )
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
        return self._verify_staged_publication(expectations)

    def verify_job_publication(
        self,
        run_id: str,
        *,
        expected_report_hash: str,
    ) -> VerifiedBacktestPublication:
        """Build the bounded participant proof carried by a completed run job."""

        expectations: tuple[str, int | None, int | None, str, str | None, str | None] = (
            _validate_hash(run_id, "run_id"),
            None,
            None,
            _validate_hash(expected_report_hash, "expected_report_hash"),
            None,
            None,
        )
        return self._verify_staged_publication(expectations)

    def _verify_staged_publication(
        self,
        expectations: tuple[
            str,
            int | None,
            int | None,
            str,
            str | None,
            str | None,
        ],
    ) -> VerifiedBacktestPublication:
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
            expected_fill_count = metadata[0] if expectations[1] is None else expectations[1]
            expected_detail_count = metadata[1] if expectations[2] is None else expectations[2]
            expected_fill_set_hash = metadata[2] if expectations[4] is None else expectations[4]
            expected_detail_set_hash = metadata[3] if expectations[5] is None else expectations[5]
            _require_publication_metadata(
                metadata,
                expected_fill_count=expected_fill_count,
                expected_detail_count=expected_detail_count,
                expected_fill_set_hash=expected_fill_set_hash,
                expected_detail_set_hash=expected_detail_set_hash,
                version=version,
                staged=not already_materialized,
            )
            artifact_counts = (
                _publication_artifact_counts(
                    connection,
                    summary,
                    staged=not already_materialized,
                )
                if version == "v2"
                else ()
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
                artifact_counts=artifact_counts,
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
            _persist_artifact_counts(connection, proof.run_id, proof.artifact_counts)
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
        _persist_artifact_counts(connection, proof.run_id, proof.artifact_counts)
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
                    stored = _load_detail(existing[3], existing[4], existing[5])
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
                        _encode_detail_payload(payload_json),
                        now,
                    ),
                )
                inserted += 1
            connection.commit()
        return inserted


def _find_pin_idempotency(
    connection: sqlite3.Connection,
    idempotency_key: str,
    *,
    as_of: str,
) -> dict[str, str] | None:
    active: dict[str, str] | None = None
    cursor = connection.execute(
        """
        SELECT run_id, pin_idempotency_json FROM backtest_run
        WHERE pin_idempotency_json <> '{}' ORDER BY run_id
        """
    )
    while rows := cursor.fetchmany(_MAX_BATCH_SIZE):
        for run_id, payload_json in rows:
            payload = _load_pin_idempotency_map(str(payload_json))
            expired_keys = tuple(
                key for key, candidate in payload.items() if candidate["expiresAt"] <= as_of
            )
            for expired_key in expired_keys:
                del payload[expired_key]
            if expired_keys:
                connection.execute(
                    "UPDATE backtest_run SET pin_idempotency_json = ? WHERE run_id = ?",
                    (canonical_json(payload), str(run_id)),
                )
            entry = payload.get(idempotency_key)
            if entry is None:
                continue
            if active is not None:
                raise RuntimeError("pin idempotency key is stored more than once")
            active = entry
    return active


def _load_pin_idempotency_map(value: str) -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as error:
        raise RuntimeError("stored pin idempotency metadata is invalid") from error
    if not isinstance(raw, dict) or canonical_json(raw) != value:
        raise RuntimeError("stored pin idempotency metadata is not canonical")
    result: dict[str, dict[str, str]] = {}
    expected_fields = {
        "expiresAt",
        "recordedAt",
        "requestHash",
        "responseHash",
        "responseJson",
    }
    for key, raw_entry in raw.items():
        try:
            normalized_key = _validate_stable_identifier(key, "idempotency_key")
        except (TypeError, ValueError) as error:
            raise RuntimeError("stored pin idempotency key is invalid") from error
        if (
            not isinstance(raw_entry, dict)
            or set(raw_entry) != expected_fields
            or any(type(item) is not str for item in raw_entry.values())
        ):
            raise RuntimeError("stored pin idempotency entry is invalid")
        entry = {name: str(raw_entry[name]) for name in sorted(expected_fields)}
        for field_name in ("requestHash", "responseHash"):
            try:
                _validate_hash(entry[field_name], field_name)
            except (TypeError, ValueError) as error:
                raise RuntimeError("stored pin idempotency hash is invalid") from error
        for field_name in ("recordedAt", "expiresAt"):
            try:
                parsed = datetime.fromisoformat(entry[field_name])
            except ValueError as error:
                raise RuntimeError("stored pin idempotency timestamp is invalid") from error
            if (
                parsed.utcoffset() != timedelta(hours=8)
                or _datetime_text(parsed, version="v2") != entry[field_name]
            ):
                raise RuntimeError("stored pin idempotency timestamp is not canonical +08:00")
        result[normalized_key] = entry
    return result


def _active_result_run_row(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[object, ...] | None:
    row = connection.execute(
        """
        SELECT r.run_id, r.plan_sha256, r.dataset_hash, r.status, r.completed_at,
               r.summary_domain, r.summary_hash, r.summary_json, r.pinned,
               r.pin_revision, r.publication_fill_count,
               input.run_id, input.plan_sha256, input.input_hash, input.input_json,
               snapshot.snapshot_json
        FROM backtest_run AS r
        JOIN backtest_run_input AS input ON input.run_id = r.run_id
        JOIN backtest_plan_snapshot AS snapshot
          ON snapshot.plan_sha256 = input.plan_sha256
        WHERE r.run_id = ? AND r.materialized = 1
          AND r.summary_domain = 'backtest-run-summary-v2'
          AND r.catalog_revision IS NOT NULL
        """,
        (run_id,),
    ).fetchone()
    return None if row is None else tuple(row)


def _active_v2_export_metadata(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[BacktestRunSummary, int, str]:
    row = _active_result_run_row(connection, run_id)
    if row is None:
        raise KeyError(f"active v2 run not found: {run_id}")
    availability = _availability_by_run(connection, (run_id,))[run_id]
    record = _load_run_query_row(row, availability).record
    publication = connection.execute(
        """
        SELECT publication_fill_count, publication_fill_set_hash,
               publication_fill_set_domain
        FROM backtest_run WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if (
        publication is None
        or publication[0] is None
        or publication[1] is None
        or str(publication[2]) != _FILL_SET_DOMAINS["v2"]
    ):
        raise RuntimeError("active v2 run is missing fill publication metadata")
    fill_count = int(publication[0])
    fill_set_hash = _validate_hash(str(publication[1]), "publication_fill_set_hash")
    if fill_count != record.fill_count:
        raise RuntimeError("active v2 run fill count is inconsistent")
    return record.summary, fill_count, fill_set_hash


def _load_run_query_row(
    row: tuple[object, ...],
    availability: tuple[BacktestArtifactState, ...],
) -> BacktestRunQueryRow:
    if len(row) != 16:
        raise RuntimeError("stored result run query row shape is invalid")
    run_id = str(row[0])
    summary = _load_summary_row(row[:9], expected_run_id=run_id)
    run_input = _load_run_input_row(row[11:16], expected_run_id=run_id)
    _validate_summary_input(summary, run_input)
    if row[10] is None:
        raise RuntimeError("materialized result is missing its fill count")
    return BacktestRunQueryRow(
        record=BacktestRunRecord(
            summary=summary,
            plan_version_id=(
                None if run_input.plan_version_id is None else str(run_input.plan_version_id)
            ),
            revision=int(row[9]),
            fill_count=int(row[10]),
            availability=availability,
        ),
        position=(str(row[4]), run_id),
    )


def _query_result_detail_rows(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    kind: BacktestDetailKind,
    limit: int,
    high_water: tuple[str, str] | None,
    last_seen: tuple[str, str] | None,
) -> tuple[BacktestDetailQueryRow, ...]:
    clauses = ["d.run_id = ?", "d.kind = ?", "r.materialized = 1"]
    parameters: list[object] = [run_id, kind.value]
    for value, operator in ((high_water, "<="), (last_seen, ">")):
        if value is not None:
            clauses.append(f"(d.event_at, d.detail_id) {operator} (?, ?)")
            parameters.extend(value)
    parameters.append(limit)
    rows = connection.execute(
        f"""
        SELECT d.detail_id, d.run_id, d.kind, d.event_at, d.content_domain,
               d.content_hash, d.payload_json
        FROM backtest_detail AS d
        JOIN backtest_run AS r ON r.run_id = d.run_id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.event_at, d.detail_id
        LIMIT ?
        """,
        tuple(parameters),
    ).fetchall()
    return tuple(
        BacktestDetailQueryRow(
            record=_load_detail_row(tuple(row), expected_run_id=run_id),
            position=(str(row[3]), str(row[0])),
        )
        for row in rows
    )


def _result_detail_high_water(
    connection: sqlite3.Connection,
    run_id: str,
    kind: BacktestDetailKind,
) -> tuple[str, str] | None:
    row = connection.execute(
        """
        SELECT d.event_at, d.detail_id
        FROM backtest_detail AS d
        JOIN backtest_run AS r ON r.run_id = d.run_id
        WHERE d.run_id = ? AND d.kind = ? AND r.materialized = 1
        ORDER BY d.event_at DESC, d.detail_id DESC LIMIT 1
        """,
        (run_id, kind.value),
    ).fetchone()
    return None if row is None else (str(row[0]), str(row[1]))


def _artifact_state(
    connection: sqlite3.Connection,
    run_id: str,
    kind: BacktestDetailKind,
) -> BacktestArtifactState | None:
    exists = connection.execute(
        """
        SELECT 1 FROM backtest_run
        WHERE run_id = ? AND materialized = 1
          AND summary_domain = 'backtest-run-summary-v2'
        """,
        (run_id,),
    ).fetchone()
    if exists is None:
        return None
    rows = _availability_by_run(connection, (run_id,))[run_id]
    state = next(item for item in rows if item.kind is kind)
    if state.availability is BacktestArtifactAvailability.AVAILABLE:
        actual = int(
            connection.execute(
                "SELECT COUNT(*) FROM backtest_detail WHERE run_id = ? AND kind = ?",
                (run_id, kind.value),
            ).fetchone()[0]
        )
        if actual != state.original_count:
            raise RuntimeError("available backtest artifact count is inconsistent")
    return state


def _availability_by_run(
    connection: sqlite3.Connection,
    run_ids: tuple[str, ...],
) -> dict[str, tuple[BacktestArtifactState, ...]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id,
               daily_equity_original_count, daily_equity_expired_at,
               decision_original_count, decision_expired_at,
               outcome_original_count, outcome_expired_at,
               signal_original_count, signal_expired_at
        FROM backtest_run WHERE run_id IN ({placeholders})
        ORDER BY run_id
        """,
        run_ids,
    ).fetchall()
    result: dict[str, tuple[BacktestArtifactState, ...]] = {}
    for row in rows:
        run_id = str(row[0])
        states: list[BacktestArtifactState] = []
        for index, kind_text in enumerate(_PUBLIC_ARTIFACT_KINDS):
            raw_count = row[1 + index * 2]
            expired_at = None if row[2 + index * 2] is None else str(row[2 + index * 2])
            if raw_count is None or int(raw_count) < 0:
                raise RuntimeError("materialized result availability metadata is incomplete")
            original_count = int(raw_count)
            if expired_at is not None:
                try:
                    parsed_expired_at = datetime.fromisoformat(expired_at)
                except ValueError as error:
                    raise RuntimeError("stored result expiry marker is invalid") from error
                if (
                    parsed_expired_at.utcoffset() != timedelta(hours=8)
                    or _datetime_text(parsed_expired_at, version="v2") != expired_at
                ):
                    raise RuntimeError("stored result expiry marker is not canonical +08:00")
            if original_count == 0 and expired_at is not None:
                raise RuntimeError("unrecorded result artifact cannot be expired")
            availability = (
                BacktestArtifactAvailability.NOT_RECORDED
                if original_count == 0
                else BacktestArtifactAvailability.EXPIRED
                if expired_at is not None
                else BacktestArtifactAvailability.AVAILABLE
            )
            states.append(
                BacktestArtifactState(
                    kind=BacktestDetailKind(kind_text),
                    availability=availability,
                    original_count=original_count,
                )
            )
        result[run_id] = tuple(states)
    if result.keys() != dict.fromkeys(run_ids).keys():
        raise RuntimeError("materialized result availability metadata is incomplete")
    return result


def _load_run_input_row(
    row: tuple[object, ...],
    *,
    expected_run_id: str,
) -> BacktestRunInput:
    if len(row) != 5:
        raise RuntimeError("stored backtest run input row shape is invalid")
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
        run_input.run_id != expected_run_id
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
    return run_input


def _publication_artifact_counts(
    connection: sqlite3.Connection,
    summary: BacktestRunSummary,
    *,
    staged: bool,
) -> tuple[tuple[str, int], ...]:
    actual_by_kind: dict[str, int] = {}
    if staged:
        actual_by_kind = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """
                SELECT kind, COUNT(*) FROM backtest_detail
                WHERE run_id = ? GROUP BY kind
                """,
                (summary.run_id,),
            ).fetchall()
        }
        if any(kind not in _PUBLIC_ARTIFACT_KINDS for kind in actual_by_kind):
            raise ResultConflictError("active v2 publication contains a non-public detail kind")
    expected: list[tuple[str, int]] = []
    for kind in _PUBLIC_ARTIFACT_KINDS:
        raw_count = summary.coverage.get(_COVERAGE_FIELDS[kind])
        if raw_count is None and staged:
            raw_count = actual_by_kind.get(kind, 0)
        if type(raw_count) is not int or raw_count < 0:
            raise ResultConflictError(
                f"completed summary is missing canonical {_COVERAGE_FIELDS[kind]}"
            )
        if kind == "DAILY_EQUITY" and raw_count > _MAX_EQUITY_POINTS:
            raise ResultConflictError("daily equity must not exceed 2,000 points")
        expected.append((kind, raw_count))
    counts = tuple(expected)
    if staged:
        if tuple((kind, actual_by_kind.get(kind, 0)) for kind in _PUBLIC_ARTIFACT_KINDS) != counts:
            raise ResultConflictError("completed summary artifact counts do not match staged rows")
    return counts


def _persist_artifact_counts(
    connection: sqlite3.Connection,
    run_id: str,
    counts: tuple[tuple[str, int], ...],
) -> None:
    for kind, count in counts:
        count_column, _expired_column = _ARTIFACT_COLUMNS[kind]
        existing = connection.execute(
            f"SELECT {count_column} FROM backtest_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if existing[0] is None:
            connection.execute(
                f"UPDATE backtest_run SET {count_column} = ? WHERE run_id = ?",
                (count, run_id),
            )
        elif int(existing[0]) != count:
            raise ResultConflictError("persisted result availability count changed")
    if counts:
        row = connection.execute(
            "SELECT catalog_revision FROM backtest_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if row[0] is None:
            cursor = connection.execute(
                """
                UPDATE backtest_run SET catalog_revision = (
                    SELECT COALESCE(MAX(catalog_revision), 0) + 1 FROM backtest_run
                )
                WHERE run_id = ? AND catalog_revision IS NULL AND materialized = 1
                """,
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise ResultConflictError("result catalog revision changed before publication")


def _mark_expired_artifacts(
    connection: sqlite3.Connection,
    detail_ids: tuple[str, ...],
    *,
    expired_at: str,
) -> None:
    if not detail_ids:
        return
    placeholders = ",".join("?" for _ in detail_ids)
    rows = connection.execute(
        f"""
        SELECT DISTINCT run_id, kind FROM backtest_detail
        WHERE detail_id IN ({placeholders})
          AND kind IN ('DECISION', 'SIGNAL', 'EXECUTION_OUTCOME', 'DAILY_EQUITY')
        """,
        detail_ids,
    ).fetchall()
    for run_id, kind in rows:
        count_column, expired_column = _ARTIFACT_COLUMNS[str(kind)]
        metadata = connection.execute(
            f"SELECT summary_domain, {count_column} FROM backtest_run WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if metadata is None:
            raise RuntimeError("retained detail belongs to an unknown run")
        if str(metadata[0]) != "backtest-run-summary-v2":
            continue
        if metadata[1] is None or int(metadata[1]) <= 0:
            raise RuntimeError("active result is missing availability metadata")
        cursor = connection.execute(
            f"""
            UPDATE backtest_run
            SET {expired_column} = COALESCE({expired_column}, ?)
            WHERE run_id = ?
            """,
            (expired_at, str(run_id)),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("active result is missing availability metadata")


def _require_position(value: tuple[str, str], name: str) -> None:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) is not str or not item for item in value)
    ):
        raise ValueError(f"{name} must contain two non-empty strings")


def _validate_stable_identifier(value: str, name: str) -> str:
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or not value[0].isalnum()
        or any(character not in allowed for character in value)
    ):
        raise ValueError(f"{name} must be a stable identifier")
    return value


_STALE_STAGED_DETAIL_SQL = """
SELECT d.detail_id
FROM backtest_detail AS d
JOIN backtest_run AS r ON r.run_id = d.run_id
WHERE r.materialized = 0 AND r.pinned = 0
  AND (
      (r.summary_domain = 'backtest-run-summary-v1' AND r.created_at < ?)
      OR (r.summary_domain = 'backtest-run-summary-v2' AND r.created_at < ?)
  )
ORDER BY r.created_at, d.detail_id
LIMIT ?
"""

_STALE_STAGED_FILL_SQL = """
SELECT f.fill_id
FROM backtest_fill AS f
JOIN backtest_run AS r ON r.run_id = f.run_id
WHERE r.materialized = 0 AND r.pinned = 0
  AND (
      (r.summary_domain = 'backtest-run-summary-v1' AND r.created_at < ?)
      OR (r.summary_domain = 'backtest-run-summary-v2' AND r.created_at < ?)
  )
ORDER BY r.created_at, f.fill_id
LIMIT ?
"""

_STALE_STAGED_RUN_SQL = """
SELECT r.run_id
FROM backtest_run AS r
WHERE r.materialized = 0
  AND r.pinned = 0
  AND (
      (r.summary_domain = 'backtest-run-summary-v1' AND r.created_at < ?)
      OR (r.summary_domain = 'backtest-run-summary-v2' AND r.created_at < ?)
  )
  AND NOT EXISTS (SELECT 1 FROM backtest_detail AS d WHERE d.run_id = r.run_id)
  AND NOT EXISTS (SELECT 1 FROM backtest_fill AS f WHERE f.run_id = r.run_id)
ORDER BY r.created_at, r.run_id
LIMIT ?
"""

_STALE_RUN_INPUT_SQL = """
SELECT input.run_id
FROM backtest_run_input AS input
WHERE input.created_at < ?
  AND NOT EXISTS (
      SELECT 1 FROM backtest_run AS run WHERE run.run_id = input.run_id
  )
"""

_STALE_RUN_INPUT_JOB_GUARD_SQL = """
  AND NOT EXISTS (
      SELECT 1 FROM backtest_job AS job WHERE job.run_id = input.run_id
  )
"""

_STALE_RUN_INPUT_ORDER_SQL = """
ORDER BY input.created_at, input.run_id
LIMIT ?
"""

_STALE_PLAN_SNAPSHOT_SQL = """
SELECT snapshot.plan_sha256
FROM backtest_plan_snapshot AS snapshot
WHERE snapshot.created_at < ?
  AND NOT EXISTS (
      SELECT 1 FROM backtest_run_input AS input
      WHERE input.plan_sha256 = snapshot.plan_sha256
  )
ORDER BY snapshot.created_at, snapshot.plan_sha256
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
      (
          d.kind = 'DEBUG_TRACE'
          AND (
              (r.summary_domain = 'backtest-run-summary-v1' AND r.created_at < ?)
              OR (r.summary_domain = 'backtest-run-summary-v2' AND r.created_at < ?)
          )
      )
      OR (
          r.status = 'COMPLETED'
          AND d.kind != 'DEBUG_TRACE'
          AND (
              (r.summary_domain = 'backtest-run-summary-v1' AND r.created_at < ?)
              OR (r.summary_domain = 'backtest-run-summary-v2' AND r.created_at < ?)
              OR ranked.run_rank > ?
          )
      )
  )
ORDER BY r.created_at, d.detail_id
LIMIT ?
"""


def _retention_parameters(as_of: datetime) -> tuple[str, str, str, str, str, str, int]:
    staged_at = as_of - timedelta(days=_DIAGNOSTIC_DETAIL_DAYS)
    diagnostic_at = as_of - timedelta(days=_DIAGNOSTIC_DETAIL_DAYS)
    success_at = as_of - timedelta(days=_SUCCESS_DETAIL_DAYS)
    return (
        _datetime_text(staged_at, version="v1"),
        _datetime_text(staged_at, version="v2"),
        _datetime_text(diagnostic_at, version="v1"),
        _datetime_text(diagnostic_at, version="v2"),
        _datetime_text(success_at, version="v1"),
        _datetime_text(success_at, version="v2"),
        _SUCCESS_DETAIL_RUNS,
    )


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


def _stale_run_input_query(connection: sqlite3.Connection) -> str:
    has_job_table = (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'backtest_job'"
        ).fetchone()
        is not None
    )
    job_guard = _STALE_RUN_INPUT_JOB_GUARD_SQL if has_job_table else ""
    return _STALE_RUN_INPUT_SQL + job_guard + _STALE_RUN_INPUT_ORDER_SQL


def _result_retention_has_more(
    connection: sqlite3.Connection,
    *,
    staged_cutoffs: tuple[object, ...],
    retention_parameters: tuple[object, ...],
    stale_input_query: str,
) -> bool:
    return any(
        _has_candidate(connection, query, query_parameters)
        for query, query_parameters in (
            (_STALE_STAGED_DETAIL_SQL, (*staged_cutoffs, 1)),
            (_STALE_STAGED_FILL_SQL, (*staged_cutoffs, 1)),
            (_STALE_STAGED_RUN_SQL, (*staged_cutoffs, 1)),
            (stale_input_query, (staged_cutoffs[1], 1)),
            (_STALE_PLAN_SNAPSHOT_SQL, (staged_cutoffs[1], 1)),
            (_RETENTION_CANDIDATES_SQL, (*retention_parameters, 1)),
        )
    )


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
        ("backtest_run_input", "run_id"),
        ("backtest_plan_snapshot", "plan_sha256"),
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
    content_domain: object,
    content_hash: object,
    stored_payload: object,
) -> BacktestDetailRecord:
    content_domain = str(content_domain)
    content_hash = str(content_hash)
    payload_json = _decode_detail_payload(stored_payload)
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
    record = _load_detail(row[4], row[5], row[6])
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


def _encode_detail_payload(payload_json: str) -> sqlite3.Binary:
    raw = payload_json.encode("utf-8")
    compressor = zlib.compressobj(
        level=6,
        method=zlib.DEFLATED,
        wbits=zlib.MAX_WBITS,
        zdict=_DETAIL_COMPRESSION_DICTIONARY,
    )
    compressed = compressor.compress(raw) + compressor.flush()
    return sqlite3.Binary(_DETAIL_PAYLOAD_MAGIC + compressed)


def _decode_detail_payload(stored_payload: object) -> str:
    if type(stored_payload) is str:
        payload_json = stored_payload
    else:
        if isinstance(stored_payload, memoryview):
            stored_payload = stored_payload.tobytes()
        if not isinstance(stored_payload, bytes) or not stored_payload.startswith(
            _DETAIL_PAYLOAD_MAGIC
        ):
            raise RuntimeError("stored backtest detail payload encoding is invalid")
        compressed = stored_payload[len(_DETAIL_PAYLOAD_MAGIC) :]
        if len(compressed) > _MAX_ITEM_BYTES + 1_024:
            raise RuntimeError("stored backtest detail compressed payload is oversized")
        decompressor = zlib.decompressobj(
            wbits=zlib.MAX_WBITS,
            zdict=_DETAIL_COMPRESSION_DICTIONARY,
        )
        try:
            raw = decompressor.decompress(compressed, _MAX_ITEM_BYTES + 1)
            if len(raw) > _MAX_ITEM_BYTES or decompressor.unconsumed_tail:
                raise RuntimeError("stored backtest detail payload is oversized")
            remaining = _MAX_ITEM_BYTES + 1 - len(raw)
            raw += decompressor.flush(remaining)
        except zlib.error as error:
            raise RuntimeError("stored backtest detail payload is corrupt") from error
        if len(raw) > _MAX_ITEM_BYTES or not decompressor.eof or decompressor.unused_data:
            raise RuntimeError("stored backtest detail payload is invalid")
        try:
            payload_json = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError("stored backtest detail payload is not UTF-8") from error
    _require_item_size(payload_json, "backtest detail")
    return payload_json


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
    cancelled: Callable[[], bool] | None = None,
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
    while True:
        if cancelled is not None and cancelled():
            raise ExportCancelled
        rows = cursor.fetchmany(_MAX_BATCH_SIZE)
        if not rows:
            break
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


def _validated_export_fill_set_hash(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    cancelled: Callable[[], bool],
) -> tuple[int, str, int, int]:
    """Verify one published v2 fill set without constructing export models twice."""

    digest = sha256(_domain_bytes(_FILL_SET_DOMAINS["v2"]))
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
    while True:
        if cancelled():
            raise ExportCancelled
        rows = cursor.fetchmany(_MAX_BATCH_SIZE)
        if not rows:
            break
        batch_count += 1
        maximum = max(maximum, len(rows))
        for row in rows:
            fill_id = _validate_hash(str(row[0]), "fill_id")
            stored_run_id = str(row[1])
            filled_at = str(row[2])
            content_domain = str(row[3])
            content_hash = _validate_hash(str(row[4]), "content_hash")
            payload_json = str(row[5])
            _require_item_size(payload_json, "backtest fill")
            if content_domain != _FILL_DOMAINS["v2"]:
                raise ResultConflictError("staged fill row identity is invalid")
            if content_hash != _content_hash(
                _domain_bytes(content_domain),
                payload_json,
            ):
                raise RuntimeError("stored backtest fill failed its content hash")
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError as error:
                raise RuntimeError("stored backtest fill payload is invalid") from error
            if (
                not isinstance(payload, dict)
                or payload.get("fill_id") != fill_id
                or payload.get("run_id") != stored_run_id
                or stored_run_id != run_id
                or payload.get("filled_at") != filled_at
            ):
                raise ResultConflictError("staged fill row identity is invalid")
            digest.update(
                (f'{{"contentHash":"{content_hash}","identity":"{fill_id}"}}\n').encode("ascii")
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
            expected_domain = _domain(_DETAIL_DOMAINS, version)
            record = _load_detail(row[4], row[5], row[6])
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
    "BacktestArtifactAvailability",
    "BacktestArtifactState",
    "BacktestDetailKind",
    "BacktestDetailReadSnapshot",
    "BacktestDetailRecord",
    "BacktestFillRecord",
    "BacktestResultStatistics",
    "BacktestResultStore",
    "BacktestRunRecord",
    "BacktestRunStatus",
    "BacktestRunSummary",
    "ExportCancelled",
    "ResultConflictError",
    "RetentionPruneResult",
    "VerifiedBacktestPublication",
    "backtest_detail_set_hash",
    "backtest_fill_set_hash",
]
