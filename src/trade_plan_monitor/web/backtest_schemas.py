"""Strict backtest-only API input and exact-value schemas."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Annotated, Any, Literal, Self
from uuid import RFC_4122, UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    ValidationInfo,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.canonical import canonical_decimal
from trade_plan_monitor.backtest.loop_account import LoopAccountReceipt, LoopAccountState
from trade_plan_monitor.backtest.loop_diagnostics import LoopDiagnostics
from trade_plan_monitor.backtest.loop_input import LoopAccountInput, LoopCosts, LoopResponsePolicy
from trade_plan_monitor.backtest.loop_report import (
    MAX_AUDIT_EVENTS,
    LoopAuditEvent,
    LoopCycleSummary,
    LoopMetrics,
    LoopValuation,
    MonitorLoopReport,
    ScheduledLoopAuditEvent,
)
from trade_plan_monitor.backtest.models import ExecutionStatus, UnfilledReason
from trade_plan_monitor.backtest.models import StableIdentifier as PreparedIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    LoopEndBoundary,
    LoopPlanVersion,
    LoopTimestamp,
)
from trade_plan_monitor.backtest.research_input import ResearchValue, UnifiedResearchInput
from trade_plan_monitor.backtest.research_report import (
    ResearchDecisionEvent,
    ResearchOperationOutcome,
)
from trade_plan_monitor.backtest.time import (
    format_shanghai_datetime,
    parse_shanghai_datetime,
)
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionOutcome,
    DataHealthStatus,
    DecisionZone,
    EpisodeStatus,
    EvidenceCode,
    EvidenceKey,
    EvidenceUnit,
    IndexConditionType,
    MissingInputCode,
    NextStepCode,
    RiskStatus,
    SignalType,
)
from trade_plan_monitor.market_index.identity import (
    Board,
    MarketIndexCode,
    identity_for_index_code,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexHealth,
    MarketIndexIssueCode,
    ReturnWindow,
)
from trade_plan_monitor.state.daily_state_models import DailyInventoryView
from trade_plan_monitor.web.preparation_schemas import CollectionVersionView
from trade_plan_monitor.web.routers.dashboard import (
    IndexConditionEvidenceView,
    MarketIndexIndicatorFactView,
)

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_INITIAL_LOTS = 200
MAX_BACKTEST_YEARS = 5
MAX_WARMUP_YEARS = 2
MAX_EXACT_TEXT_CHARACTERS = 4_096

_FEN_TEXT_PATTERN = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
_DECIMAL_TEXT_PATTERN = re.compile(r"^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$")
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
_PUBLIC_ERROR_MESSAGE_BY_STATUS = {
    "FAILED": "The job failed.",
    "CANCELLED": "The job was cancelled.",
}
_PUBLIC_ERROR_MESSAGES = frozenset(_PUBLIC_ERROR_MESSAGE_BY_STATUS.values())


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _validate_fen_text(value: object) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_EXACT_TEXT_CHARACTERS
        or _FEN_TEXT_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("FenText must be one canonical signed base-10 integer string")
    return value


def _validate_decimal_text(value: object) -> Decimal:
    if (
        type(value) is not str
        or len(value) > MAX_EXACT_TEXT_CHARACTERS
        or _DECIMAL_TEXT_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("DecimalText must be a non-exponent base-10 string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:  # pragma: no cover - guarded by the grammar
        raise ValueError("DecimalText must be finite") from error
    if not parsed.is_finite():
        raise ValueError("DecimalText must be finite")
    if canonical_decimal(parsed) != value:
        raise ValueError("DecimalText must use its canonical representation")
    return parsed


def _validate_explicit_true(value: object) -> bool:
    if value is not True:
        raise ValueError("allowNetwork must be the explicit boolean true")
    return True


def _validate_shanghai_datetime(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("ShanghaiDatetime input must be a string")
    parsed = parse_shanghai_datetime(value)
    if parsed.utcoffset() != timedelta(hours=8):
        raise ValueError("ShanghaiDatetime historical offset must remain +08:00")
    return parsed


def _validate_date_text(value: object) -> date:
    if type(value) is not str:
        raise ValueError("date input must be an ISO calendar-date string")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("date input must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date input must be a valid Gregorian calendar date") from error


def _validate_rfc4122_uuid(value: object) -> UUID:
    if type(value) is not str or _UUID_PATTERN.fullmatch(value) is None:
        raise ValueError("UUID input must use canonical hyphenated text")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as error:
        raise ValueError("UUID input must be RFC 4122") from error
    if parsed.variant != RFC_4122:
        raise ValueError("UUID input must be RFC 4122")
    return parsed


FenText = Annotated[
    str,
    BeforeValidator(_validate_fen_text, json_schema_input_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": _FEN_TEXT_PATTERN.pattern,
            "maxLength": MAX_EXACT_TEXT_CHARACTERS,
        }
    ),
]
DecimalText = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal_text, json_schema_input_type=str),
    PlainSerializer(canonical_decimal, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": _DECIMAL_TEXT_PATTERN.pattern,
            "maxLength": MAX_EXACT_TEXT_CHARACTERS,
        }
    ),
]
ShanghaiDatetime = Annotated[
    datetime,
    BeforeValidator(_validate_shanghai_datetime, json_schema_input_type=str),
    PlainSerializer(format_shanghai_datetime, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "pattern": (
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
                r"[0-9]{2}(?:\.[0-9]{1,6})?\+08:00$"
            ),
        }
    ),
]
ApiDate = Annotated[
    date,
    BeforeValidator(_validate_date_text, json_schema_input_type=str),
    PlainSerializer(date.isoformat, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "format": "date", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}
    ),
]
Rfc4122Uuid = Annotated[
    UUID,
    BeforeValidator(_validate_rfc4122_uuid, json_schema_input_type=str),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "uuid", "pattern": _UUID_PATTERN.pattern}),
]
JavaScriptSafeInteger = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_SAFE_INTEGER),
]
PositiveJavaScriptSafeInteger = Annotated[
    int,
    Field(strict=True, gt=0, le=MAX_SAFE_INTEGER),
]
PositiveSafeBoardLot = Annotated[
    int,
    Field(strict=True, gt=0, le=MAX_SAFE_INTEGER, multiple_of=100),
]
ExplicitTrue = Annotated[
    bool,
    BeforeValidator(_validate_explicit_true, json_schema_input_type=bool),
    WithJsonSchema({"type": "boolean", "const": True}),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
LotKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]


class _BacktestApiInput(BaseModel):
    """Keep public backtest request values closed, immutable, and canonical."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Revalidate updates so frozen values cannot bypass the API contract."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="json", by_alias=True, round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    def canonical_payload(self) -> dict[str, Any]:
        """Return the normalized JSON value used by identity and persistence layers."""

        return self.model_dump(mode="json", by_alias=True)


def _calendar_years_after(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


class BacktestDatasetScopeInput(_BacktestApiInput):
    """Canonical requested historical range for sync and verification commands."""

    symbols: tuple[str, ...]
    start: ApiDate
    end: ApiDate
    warmup_start: ApiDate
    historical_profile: Literal["TUSHARE_STK_MINS_241_END_V1"]
    adjustment_policy: Literal["NONE"]

    @field_validator("symbols", mode="before")
    @classmethod
    def validate_and_normalize_symbols(cls, value: object) -> tuple[str, ...]:
        if type(value) is not list:
            raise ValueError("symbols must be a JSON array")
        if not 1 <= len(value) <= 10:
            raise ValueError("symbols must contain between 1 and 10 entries")
        if any(
            type(symbol) is not str or _SYMBOL_PATTERN.fullmatch(symbol) is None for symbol in value
        ):
            raise ValueError("symbols must use the canonical .SH or .SZ form")
        if len(set(value)) != len(value):
            raise ValueError("symbols must not contain duplicates")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.start > self.end:
            raise ValueError("start cannot be after end")
        if self.end > _calendar_years_after(self.start, MAX_BACKTEST_YEARS):
            raise ValueError("backtest date range cannot exceed 5 calendar years")
        if self.warmup_start > self.start:
            raise ValueError("warmupStart cannot be after start")
        if self.start > _calendar_years_after(self.warmup_start, MAX_WARMUP_YEARS):
            raise ValueError("warmup range cannot exceed 2 calendar years")
        return self

    def validate_authoritative_today(self, *, today: date) -> Self:
        """Apply the injected China-market date without consulting the host clock."""

        if type(today) is not date:
            raise TypeError("today must be a date")
        if self.end >= today:
            raise ValueError("end must be before the server-authoritative today")
        return self


class BacktestDataSyncCommand(_BacktestApiInput):
    """Explicitly authorized historical-data synchronization request."""

    scope: BacktestDatasetScopeInput
    refresh: bool = Field(strict=True)
    allow_network: ExplicitTrue


class BacktestDatasetVerificationCommand(_BacktestApiInput):
    """Offline verification request for one canonical dataset scope."""

    scope: BacktestDatasetScopeInput


class BacktestExecutionConfigInput(_BacktestApiInput):
    """Version-independent exact simulated execution assumptions."""

    commission_rate: DecimalText
    minimum_commission_fen: JavaScriptSafeInteger
    stamp_duty_rate: DecimalText
    transfer_fee_rate: DecimalText
    buy_slippage_bps: DecimalText
    sell_slippage_bps: DecimalText

    @model_validator(mode="after")
    def validate_decimal_ranges(self) -> Self:
        for name in ("commission_rate", "stamp_duty_rate", "transfer_fee_rate"):
            value = getattr(self, name)
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{_to_camel(name)} must be between 0 and 1")
        for name in ("buy_slippage_bps", "sell_slippage_bps"):
            value = getattr(self, name)
            if not Decimal("0") <= value < Decimal("10000"):
                raise ValueError(f"{_to_camel(name)} must be between 0 and 10000")
        return self


class BacktestInitialLotInput(_BacktestApiInput):
    """Caller-stable initial holding without a run-bound lot identity."""

    lot_key: LotKey
    bucket: Literal["CORE", "TACTICAL"]
    acquired_trade_date: ApiDate
    quantity: PositiveSafeBoardLot
    cost_basis_fen: PositiveJavaScriptSafeInteger


class BacktestLoopResponseInput(_BacktestApiInput):
    mode: Literal["FOLLOW_REMINDERS", "OBSERVE_ONLY"]
    response_delay_seconds: JavaScriptSafeInteger = 0


class BacktestLoopCostsInput(_BacktestApiInput):
    commission_rate: DecimalText
    minimum_commission_fen: JavaScriptSafeInteger
    stamp_duty_rate: DecimalText
    transfer_fee_rate: DecimalText
    buy_slippage_fen: JavaScriptSafeInteger
    sell_slippage_fen: JavaScriptSafeInteger

    @model_validator(mode="after")
    def rates(self) -> Self:
        if any(
            not Decimal(0) <= rate <= Decimal(1)
            for rate in (
                self.commission_rate,
                self.stamp_duty_rate,
                self.transfer_fee_rate,
            )
        ):
            raise ValueError("loop fee rates must be between 0 and 1")
        return self


class PreparedBacktestRunCommand(_BacktestApiInput):
    """This one frozen preparation supplies all plan and opening-account authority."""

    preparation_id: PreparedIdentifier
    manifest_hash: Sha256Hex
    response: BacktestLoopResponseInput
    costs: BacktestLoopCostsInput
    end_date: ApiDate | None = None


class ScheduledPreparedBacktestRunCommand(PreparedBacktestRunCommand):
    schema_version: Literal["prepared-loop-plan-v2"]


class BacktestRunCommand(_BacktestApiInput):
    """Canonical public request for one deterministic offline replay."""

    plan_version_id: Rfc4122Uuid
    dataset_hash: Sha256Hex
    initial_cash_fen: PositiveJavaScriptSafeInteger
    initial_lots: Annotated[
        tuple[BacktestInitialLotInput, ...],
        Field(max_length=MAX_INITIAL_LOTS),
    ]
    execution_config: BacktestExecutionConfigInput
    event_risk_assumption: Literal["NO_EVENT_RISK", "MANUAL_EVENT_RISK"]
    research_input: UnifiedResearchInput | None = None

    @field_validator("research_input", mode="before")
    @classmethod
    def parse_research(cls, value):
        if value is None or isinstance(value, UnifiedResearchInput):
            return value
        return UnifiedResearchInput.model_validate_json(json.dumps(value))

    def canonical_payload(self):
        payload = super().canonical_payload()
        if self.research_input is None:
            payload.pop("researchInput", None)
        return payload

    @field_validator("initial_lots", mode="before")
    @classmethod
    def require_json_lot_array(cls, value: object) -> tuple[object, ...]:
        if type(value) is not list:
            raise ValueError("initialLots must be a JSON array")
        return tuple(value)

    @field_validator("initial_lots")
    @classmethod
    def normalize_initial_lots(
        cls,
        value: tuple[BacktestInitialLotInput, ...],
    ) -> tuple[BacktestInitialLotInput, ...]:
        return tuple(
            sorted(
                value,
                key=lambda lot: (lot.bucket, lot.acquired_trade_date, lot.lot_key),
            )
        )

    @model_validator(mode="after")
    def validate_intrinsic_lot_constraints(self) -> Self:
        lot_keys = tuple(lot.lot_key for lot in self.initial_lots)
        if len(set(lot_keys)) != len(lot_keys):
            raise ValueError("initial-lot keys must be unique within one run command")
        if self.initial_cash_fen + sum(lot.cost_basis_fen for lot in self.initial_lots) > (
            MAX_SAFE_INTEGER
        ):
            raise ValueError("initial cash and lot costs must fit one JavaScript safe integer")
        return self

    def validate_initial_lot_limits(
        self,
        *,
        dataset_start: date,
        core_target_qty: int | None,
        tactical_target_qty: int | None,
        max_qty: int,
    ) -> Self:
        """Apply authoritative dataset and reviewed-plan constraints before hashing."""

        if type(dataset_start) is not date:
            raise TypeError("dataset_start must be a date")
        caps = {
            "core_target_qty": core_target_qty,
            "tactical_target_qty": tactical_target_qty,
            "max_qty": max_qty,
        }
        if any(
            type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER or value % 100 != 0
            for value in caps.values()
            if value is not None
        ):
            raise ValueError("position caps must be non-negative safe board-lot integers")
        if any(lot.acquired_trade_date > dataset_start for lot in self.initial_lots):
            raise ValueError("initial-lot acquired trade date cannot be after dataset start")
        core_qty = sum(lot.quantity for lot in self.initial_lots if lot.bucket == "CORE")
        tactical_qty = sum(lot.quantity for lot in self.initial_lots if lot.bucket == "TACTICAL")
        if core_target_qty is not None and core_qty > core_target_qty:
            raise ValueError("initial CORE quantity exceeds the reviewed plan cap")
        if tactical_target_qty is not None and tactical_qty > tactical_target_qty:
            raise ValueError("initial TACTICAL quantity exceeds the reviewed plan cap")
        if core_qty + tactical_qty > max_qty:
            raise ValueError("initial total quantity exceeds the reviewed plan maximum")
        return self


JobIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
StableErrorCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
StableBlockerCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
AShareSymbolText = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9]{6}\.(?:SH|SZ)$"),
]
CursorToken = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=3,
        max_length=512,
        pattern=r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
    ),
]


def _require_json_array(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) is not list:
        raise ValueError(f"{field_name} must be a JSON array")
    return tuple(value)


class BacktestDatasetScopeView(BacktestDatasetScopeInput):
    """Bounded public projection of one verified dataset scope."""


class BacktestDatasetCoverageView(_BacktestApiInput):
    """Exact public counts and stable blockers for one dataset."""

    symbol_count: JavaScriptSafeInteger
    trading_day_count: JavaScriptSafeInteger
    calendar_row_count: JavaScriptSafeInteger
    minute_day_count: JavaScriptSafeInteger
    minute_bar_count: JavaScriptSafeInteger
    daily_limit_row_count: JavaScriptSafeInteger
    daily_bar_row_count: JavaScriptSafeInteger
    blockers: Annotated[tuple[StableBlockerCode, ...], Field(max_length=100)]

    @field_validator("blockers", mode="before")
    @classmethod
    def require_blocker_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="blockers")

    @field_validator("blockers")
    @classmethod
    def validate_blocker_order(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("blockers must be ordered and unique")
        return value


class BacktestDatasetView(_BacktestApiInput):
    """Public dataset projection without manifest membership or provider payloads."""

    dataset_hash: Sha256Hex
    schema_version: Literal["backtest-dataset-v1", "backtest-dataset-v2"]
    scope: BacktestDatasetScopeView
    coverage: BacktestDatasetCoverageView
    created_at: ShanghaiDatetime
    verified_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_dataset_consistency(self) -> Self:
        if self.coverage.symbol_count != len(self.scope.symbols):
            raise ValueError("coverage.symbolCount must match scope symbols")
        if self.verified_at < self.created_at:
            raise ValueError("verifiedAt cannot precede createdAt")
        return self


class BacktestDatasetFiltersView(_BacktestApiInput):
    """Closed normalized filters echoed by a dataset traversal page."""

    symbol: AShareSymbolText | None
    start_on_or_after: ApiDate | None
    end_on_or_before: ApiDate | None
    historical_profile: Literal["TUSHARE_STK_MINS_241_END_V1"] | None
    adjustment_policy: Literal["NONE"] | None

    @model_validator(mode="after")
    def validate_date_filter_order(self) -> Self:
        if (
            self.start_on_or_after is not None
            and self.end_on_or_before is not None
            and self.start_on_or_after > self.end_on_or_before
        ):
            raise ValueError("startOnOrAfter cannot be after endOnOrBefore")
        return self


class BacktestDatasetPage(_BacktestApiInput):
    """One bounded dataset page anchored by signed cursor tokens."""

    filters: BacktestDatasetFiltersView
    items: Annotated[tuple[BacktestDatasetView, ...], Field(max_length=100)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: CursorToken | None
    has_more: bool = Field(strict=True)
    high_watermark: CursorToken

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_page_shape(self) -> Self:
        if len(self.items) > self.limit:
            raise ValueError("dataset page cannot contain more than limit items")
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("hasMore and nextCursor must agree")
        positions = tuple((item.created_at, item.dataset_hash) for item in self.items)
        _require_ordered_unique_positions(positions, reverse=True, resource="dataset")
        for item in self.items:
            if self.filters.symbol is not None and self.filters.symbol not in item.scope.symbols:
                raise ValueError("dataset item must match symbol filter")
            if (
                self.filters.start_on_or_after is not None
                and item.scope.start < self.filters.start_on_or_after
            ):
                raise ValueError("dataset item must match startOnOrAfter filter")
            if (
                self.filters.end_on_or_before is not None
                and item.scope.end > self.filters.end_on_or_before
            ):
                raise ValueError("dataset item must match endOnOrBefore filter")
            if (
                self.filters.historical_profile is not None
                and item.scope.historical_profile != self.filters.historical_profile
            ):
                raise ValueError("dataset item must match historicalProfile filter")
            if (
                self.filters.adjustment_policy is not None
                and item.scope.adjustment_policy != self.filters.adjustment_policy
            ):
                raise ValueError("dataset item must match adjustmentPolicy filter")
        _validate_bounded_page(self, self.items)
        return self


BacktestJobKind = Literal["DATA_SYNC", "DATASET_VERIFY", "BACKTEST_RUN"]
BacktestJobStatus = Literal[
    "QUEUED",
    "RUNNING",
    "CANCEL_REQUESTED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
BacktestJobPhase = Literal[
    "QUEUED",
    "VALIDATING_INPUT",
    "SYNCING_DATA",
    "VERIFYING_DATASET",
    "REPLAYING",
    "MATERIALIZING_RESULTS",
    "FINALIZING",
    "TERMINAL",
]
BacktestProgressUnit = Literal["ITEMS", "SYMBOL_DAYS", "EVENTS", "ROWS"]


class BacktestJobReceipt(_BacktestApiInput):
    """Canonical submission receipt for active or immediately reused work."""

    job_id: JobIdentifier
    kind: BacktestJobKind
    status: BacktestJobStatus
    run_id: Sha256Hex | None
    dataset_hash: Sha256Hex | None
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)]
    revision: JavaScriptSafeInteger
    reused: bool = Field(strict=True)
    submitted_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_receipt_shape(self) -> Self:
        if self.kind == "BACKTEST_RUN":
            if self.run_id is None or self.dataset_hash is None:
                raise ValueError("BACKTEST_RUN receipt requires runId and datasetHash")
        elif self.run_id is not None:
            raise ValueError("non-run receipt cannot expose runId")
        if self.kind == "DATA_SYNC" and self.dataset_hash is not None:
            raise ValueError("DATA_SYNC receipt cannot expose datasetHash")
        if self.status == "QUEUED" and self.attempt != 0:
            raise ValueError("queued receipt must have attempt=0")
        if self.status in {"RUNNING", "CANCEL_REQUESTED"} and self.attempt == 0:
            raise ValueError("active receipt must identify a claim generation")
        if self.status == "COMPLETED" and self.attempt == 0 and not self.reused:
            raise ValueError("attempt=0 completed receipt must be reused")
        if self.reused and (
            self.kind != "BACKTEST_RUN"
            or self.status != "COMPLETED"
            or self.attempt != 0
            or self.revision != 0
        ):
            raise ValueError("reused receipt must be an immediate completed run")
        return self


class BacktestJobProgressView(_BacktestApiInput):
    """Bounded public progress for one job claim generation."""

    phase: BacktestJobPhase
    completed_units: JavaScriptSafeInteger
    total_units: JavaScriptSafeInteger | None
    unit: BacktestProgressUnit
    updated_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.total_units is not None and self.completed_units > self.total_units:
            raise ValueError("completedUnits cannot exceed totalUnits")
        return self


class BacktestDataSyncJobResultView(_BacktestApiInput):
    kind: Literal["DATA_SYNC"]
    calendar_rows: JavaScriptSafeInteger
    minute_days: JavaScriptSafeInteger
    daily_limit_rows: JavaScriptSafeInteger
    daily_bar_rows: JavaScriptSafeInteger
    network_calls: JavaScriptSafeInteger


class BacktestDatasetVerificationJobResultView(_BacktestApiInput):
    kind: Literal["DATASET_VERIFY"]
    ready: bool = Field(strict=True)
    dataset_hash: Sha256Hex | None
    coverage: BacktestDatasetCoverageView
    blockers: Annotated[tuple[StableBlockerCode, ...], Field(max_length=100)]

    @field_validator("blockers", mode="before")
    @classmethod
    def require_blocker_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="blockers")

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("blockers must be ordered and unique")
        if self.blockers != self.coverage.blockers:
            raise ValueError("result blockers must match coverage blockers")
        if self.ready:
            if self.dataset_hash is None or self.blockers:
                raise ValueError("ready verification requires datasetHash and no blockers")
        elif self.dataset_hash is not None or not self.blockers:
            raise ValueError("blocked verification requires blockers and no datasetHash")
        return self


class BacktestRunJobResultView(_BacktestApiInput):
    kind: Literal["BACKTEST_RUN"]
    run_id: Sha256Hex
    report_hash: Sha256Hex
    reused: bool = Field(strict=True)


type BacktestJobResultView = Annotated[
    BacktestDataSyncJobResultView
    | BacktestDatasetVerificationJobResultView
    | BacktestRunJobResultView,
    Field(discriminator="kind"),
]


class BacktestJobView(_BacktestApiInput):
    """Closed public job state with jointly validated lifecycle discriminators."""

    job_id: JobIdentifier
    kind: BacktestJobKind
    status: BacktestJobStatus
    request_hash: Sha256Hex
    run_id: Sha256Hex | None
    dataset_hash: Sha256Hex | None
    progress: BacktestJobProgressView
    result: BacktestJobResultView | None
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)]
    revision: JavaScriptSafeInteger
    created_at: ShanghaiDatetime
    started_at: ShanghaiDatetime | None
    updated_at: ShanghaiDatetime
    finished_at: ShanghaiDatetime | None
    cancel_requested_at: ShanghaiDatetime | None
    reused: bool = Field(strict=True)
    error_code: StableErrorCode | None
    error_message: Annotated[str, Field(strict=True, min_length=1, max_length=512)] | None

    @field_validator("error_message")
    @classmethod
    def validate_sanitized_error(cls, value: str | None) -> str | None:
        if value is not None and value not in _PUBLIC_ERROR_MESSAGES:
            raise ValueError("errorMessage must contain allowlisted sanitized public text only")
        return value

    @model_validator(mode="after")
    def validate_closed_job_union(self) -> Self:
        if not self.created_at <= self.progress.updated_at <= self.updated_at:
            raise ValueError("job timestamp chronology is contradictory")
        if self.started_at is not None and not (
            self.created_at <= self.started_at <= self.progress.updated_at
        ):
            raise ValueError("job timestamp chronology is contradictory")
        if self.finished_at is not None and self.finished_at < self.updated_at:
            raise ValueError("job timestamp chronology is contradictory")
        if self.cancel_requested_at is not None:
            cancel_lower_bound = self.started_at or self.created_at
            if not cancel_lower_bound <= self.cancel_requested_at <= self.updated_at:
                raise ValueError("job timestamp chronology is contradictory")

        terminal = self.status in {"COMPLETED", "FAILED", "CANCELLED"}
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal status and finishedAt must agree")
        if terminal != (self.progress.phase == "TERMINAL"):
            raise ValueError("terminal status and progress phase must agree")

        if self.status == "COMPLETED":
            if self.result is None:
                raise ValueError("completed job requires result")
        elif self.result is not None:
            raise ValueError("only completed job may expose result")
        if self.result is not None and self.result.kind != self.kind:
            raise ValueError("result kind must match job kind")

        has_error = self.error_code is not None and self.error_message is not None
        if (self.error_code is None) != (self.error_message is None):
            raise ValueError("errorCode and errorMessage must appear together")
        if (self.status in {"FAILED", "CANCELLED"}) != has_error:
            raise ValueError("only failed or cancelled jobs require public errors")
        if self.error_message != _PUBLIC_ERROR_MESSAGE_BY_STATUS.get(self.status):
            raise ValueError("errorMessage must match the stable public status message")

        if self.kind == "BACKTEST_RUN":
            if self.run_id is None or self.dataset_hash is None:
                raise ValueError("BACKTEST_RUN job requires runId and datasetHash")
        elif self.run_id is not None:
            raise ValueError("non-run job cannot expose runId")
        if self.kind == "DATA_SYNC" and self.dataset_hash is not None:
            raise ValueError("DATA_SYNC job cannot expose datasetHash")
        if isinstance(self.result, BacktestRunJobResultView):
            if self.run_id != self.result.run_id:
                raise ValueError("run result must match runId")
            if self.reused != self.result.reused:
                raise ValueError("run result reused flag must match job")
        if isinstance(self.result, BacktestDatasetVerificationJobResultView):
            if self.dataset_hash != self.result.dataset_hash:
                raise ValueError("verification result must match datasetHash")

        allowed_phases = {
            "DATA_SYNC": {"QUEUED", "VALIDATING_INPUT", "SYNCING_DATA", "FINALIZING", "TERMINAL"},
            "DATASET_VERIFY": {
                "QUEUED",
                "VALIDATING_INPUT",
                "VERIFYING_DATASET",
                "FINALIZING",
                "TERMINAL",
            },
            "BACKTEST_RUN": {
                "QUEUED",
                "VALIDATING_INPUT",
                "REPLAYING",
                "MATERIALIZING_RESULTS",
                "FINALIZING",
                "TERMINAL",
            },
        }
        if self.progress.phase not in allowed_phases[self.kind]:
            raise ValueError("progress phase must match job kind")

        if self.status == "QUEUED":
            if self.attempt != 0 or self.started_at is not None or self.progress.phase != "QUEUED":
                raise ValueError("queued job must be unclaimed and remain in QUEUED phase")
        elif self.status in {"RUNNING", "CANCEL_REQUESTED"}:
            if self.attempt == 0 or self.started_at is None or self.progress.phase == "QUEUED":
                raise ValueError("active job requires a claim generation and active phase")
        elif self.attempt == 0 and self.started_at is not None:
            raise ValueError("unclaimed terminal job cannot expose startedAt")
        elif self.attempt > 0 and self.started_at is None:
            raise ValueError("claimed terminal job requires startedAt")

        if self.status in {"CANCEL_REQUESTED", "CANCELLED"}:
            if self.cancel_requested_at is None:
                raise ValueError("cancelling or cancelled job requires cancelRequestedAt")
        elif self.cancel_requested_at is not None:
            raise ValueError("only cancelling or cancelled job exposes cancelRequestedAt")

        if self.status == "COMPLETED" and self.attempt == 0 and not self.reused:
            raise ValueError("attempt=0 completed job must be reused")
        if self.status == "FAILED" and self.attempt == 0:
            raise ValueError("failed job must have a claim generation")
        if self.reused and (
            self.kind != "BACKTEST_RUN"
            or self.status != "COMPLETED"
            or self.attempt != 0
            or self.revision != 0
        ):
            raise ValueError("reused job must be an immediate completed run")
        return self


def _validate_non_negative_fen(value: str) -> str:
    if int(value) < 0:
        raise ValueError("fen value must be non-negative")
    return value


def _validate_positive_fen(value: str) -> str:
    if int(value) <= 0:
        raise ValueError("fen value must be positive")
    return value


NonNegativeFenText = Annotated[FenText, AfterValidator(_validate_non_negative_fen)]
PositiveFenText = Annotated[FenText, AfterValidator(_validate_positive_fen)]
StableIdentifier = JobIdentifier
StableToken = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
BacktestArtifactAvailability = Literal["AVAILABLE", "EXPIRED", "NOT_RECORDED"]


class BacktestResultAvailabilityView(_BacktestApiInput):
    """Exact lifecycle states for optional completed-result artifacts."""

    decision_details: BacktestArtifactAvailability
    signal_details: BacktestArtifactAvailability
    execution_outcome_details: BacktestArtifactAvailability
    equity_series: BacktestArtifactAvailability


class BacktestMetricsView(_BacktestApiInput):
    """Exact completed-run metrics with all money represented as FenText."""

    initial_cash_fen: PositiveFenText
    initial_equity_fen: PositiveFenText
    final_cash_fen: NonNegativeFenText
    final_equity_fen: NonNegativeFenText
    total_return: DecimalText
    maximum_drawdown: DecimalText
    trade_count: JavaScriptSafeInteger
    winning_sell_count: JavaScriptSafeInteger
    win_rate: DecimalText
    turnover_fen: NonNegativeFenText
    total_cost_fen: NonNegativeFenText
    realized_pnl_fen: FenText
    unrealized_pnl_fen: FenText
    blocked_count: JavaScriptSafeInteger
    skipped_count: JavaScriptSafeInteger

    @model_validator(mode="after")
    def validate_metric_domains(self) -> Self:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            expected_return = Decimal(
                int(self.final_equity_fen) - int(self.initial_equity_fen)
            ) / Decimal(int(self.initial_equity_fen))
        if self.total_return != expected_return:
            raise ValueError("totalReturn must match initial and final equity")
        if self.total_return < Decimal("-1"):
            raise ValueError("totalReturn cannot be below -1")
        if not Decimal("0") <= self.maximum_drawdown <= Decimal("1"):
            raise ValueError("maximumDrawdown must be between 0 and 1")
        if not Decimal("0") <= self.win_rate <= Decimal("1"):
            raise ValueError("winRate must be between 0 and 1")
        if self.winning_sell_count > self.trade_count:
            raise ValueError("winningSellCount cannot exceed tradeCount")
        return self


class ResearchMetricsView(_BacktestApiInput):
    schema_version: Literal["explicit-simulation-metrics-v1"]
    initial_cash_fen: PositiveFenText
    initial_equity_fen: PositiveFenText | None
    final_cash_fen: NonNegativeFenText | None
    final_equity_fen: NonNegativeFenText | None
    total_return: DecimalText | None
    total_cost_fen: NonNegativeFenText
    trade_count: JavaScriptSafeInteger
    blocked_count: JavaScriptSafeInteger
    valuation_valid: bool


class BacktestExecutionConfigView(_BacktestApiInput):
    """Exact execution assumptions with FenText money and DecimalText rates."""

    commission_rate: DecimalText
    minimum_commission_fen: NonNegativeFenText
    stamp_duty_rate: DecimalText
    transfer_fee_rate: DecimalText
    buy_slippage_bps: DecimalText
    sell_slippage_bps: DecimalText

    @model_validator(mode="after")
    def validate_decimal_ranges(self) -> Self:
        for name in ("commission_rate", "stamp_duty_rate", "transfer_fee_rate"):
            if not Decimal("0") <= getattr(self, name) <= Decimal("1"):
                raise ValueError(f"{_to_camel(name)} must be between 0 and 1")
        for name in ("buy_slippage_bps", "sell_slippage_bps"):
            if not Decimal("0") <= getattr(self, name) < Decimal("10000"):
                raise ValueError(f"{_to_camel(name)} must be between 0 and 10000")
        return self


class BacktestAssumptionsView(_BacktestApiInput):
    event_risk_assumption: Literal["NO_EVENT_RISK", "MANUAL_EVENT_RISK"]
    execution_config: BacktestExecutionConfigView
    execution_config_hash: Sha256Hex
    price_adjustment_policy: Literal["NONE"]
    historical_profile: Literal["TUSHARE_STK_MINS_241_END_V1"]


class BacktestFormulaVersionsView(_BacktestApiInput):
    run_formula_version: StableToken
    report_schema_version: StableToken
    execution_formula_version: StableToken
    metric_formula_version: StableToken


class BacktestRunCoverageView(_BacktestApiInput):
    event_start: ApiDate
    event_end: ApiDate
    trading_day_count: JavaScriptSafeInteger
    decision_count: JavaScriptSafeInteger
    signal_count: JavaScriptSafeInteger
    order_count: JavaScriptSafeInteger
    fill_count: JavaScriptSafeInteger
    outcome_count: JavaScriptSafeInteger
    equity_point_count: JavaScriptSafeInteger

    @model_validator(mode="after")
    def validate_event_range(self) -> Self:
        if self.event_end < self.event_start:
            raise ValueError("eventEnd cannot precede eventStart")
        return self


class BacktestIndexMaParametersView(_BacktestApiInput):
    period: Annotated[int, Field(strict=True, ge=2, le=250)]


class BacktestIndexMaLookbackParametersView(BacktestIndexMaParametersView):
    lookback: Annotated[int, Field(strict=True, ge=1, le=60)]


class BacktestIndexReturnParametersView(_BacktestApiInput):
    window: Annotated[ReturnWindow, Field(strict=False)]
    window_size: Annotated[int, Field(strict=True, ge=1, le=250)]
    threshold_ratio: DecimalText


BacktestIndexConditionParametersView = (
    BacktestIndexMaParametersView
    | BacktestIndexMaLookbackParametersView
    | BacktestIndexReturnParametersView
)


class BacktestIndexConditionSummaryView(_BacktestApiInput):
    """Server-counted outcomes for one exact plan-owned index leaf path."""

    plan_path: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    condition_type: IndexConditionType
    parameters: BacktestIndexConditionParametersView
    formula_id: Literal["SMA", "SMA_LOOKBACK", "RETURN"]
    satisfied_count: JavaScriptSafeInteger
    unsatisfied_count: JavaScriptSafeInteger
    missing_count: JavaScriptSafeInteger
    applicable_branch_count: JavaScriptSafeInteger

    @model_validator(mode="after")
    def validate_formula_and_counts(self) -> Self:
        close_types = {"INDEX_CLOSE_GTE_MA", "INDEX_CLOSE_LTE_MA"}
        trend_types = {
            "INDEX_MA_NON_DECREASING",
            "INDEX_MA_NON_INCREASING",
        }
        if self.condition_type in close_types:
            valid_parameters = type(self.parameters) is BacktestIndexMaParametersView
            expected_formula = "SMA"
        elif self.condition_type in trend_types:
            valid_parameters = isinstance(
                self.parameters,
                BacktestIndexMaLookbackParametersView,
            )
            expected_formula = "SMA_LOOKBACK"
        else:
            valid_parameters = isinstance(
                self.parameters,
                BacktestIndexReturnParametersView,
            )
            expected_formula = "RETURN"
        if not valid_parameters or self.formula_id != expected_formula:
            raise ValueError("index condition parameters and formula must match its type")
        if (
            self.satisfied_count + self.unsatisfied_count + self.missing_count
            != self.applicable_branch_count
        ):
            raise ValueError("index condition counts must sum to applicableBranchCount")
        return self


class BacktestReferenceMarketBindingView(_BacktestApiInput):
    selection: Literal["AUTO_BOARD"]
    mapping_version: Literal["board-index-map-v1"]
    index_code: Annotated[MarketIndexCode, Field(strict=False)]
    display_name: Annotated[str, Field(strict=True, min_length=1, max_length=32)]
    board: Annotated[Board, Field(strict=False)]

    @model_validator(mode="after")
    def validate_derived_identity(self) -> Self:
        board, display_name = identity_for_index_code(self.index_code)
        if self.board is not board or self.display_name != display_name:
            raise ValueError("reference-market binding identity is inconsistent")
        return self


class BacktestReferenceMarketCoverageView(_BacktestApiInput):
    """Server-resolved plan/dataset coverage shown before run submission."""

    plan_version_id: Rfc4122Uuid
    dataset_hash: Sha256Hex
    binding: BacktestReferenceMarketBindingView
    required: bool = Field(strict=True)
    condition_paths: Annotated[tuple[str, ...], Field(max_length=50)]
    required_five_minute_count: JavaScriptSafeInteger
    available_five_minute_count: JavaScriptSafeInteger
    required_official_day_count: JavaScriptSafeInteger
    available_official_day_count: JavaScriptSafeInteger
    warmup_start: ApiDate
    warmup_end: ApiDate
    coverage_status: Literal["AVAILABLE", "BLOCKED", "NOT_REQUIRED"]
    blockers: Annotated[tuple[StableBlockerCode, ...], Field(max_length=100)]
    market_index_data_hash: Sha256Hex | None
    index_requirement_hash: Sha256Hex
    formula_definition_hash: Sha256Hex

    @field_validator("condition_paths", "blockers", mode="before")
    @classmethod
    def require_coverage_arrays(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> tuple[object, ...]:
        return _require_json_array(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.condition_paths != tuple(sorted(set(self.condition_paths))):
            raise ValueError("conditionPaths must be ordered and unique")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("blockers must be ordered and unique")
        if self.warmup_end < self.warmup_start:
            raise ValueError("warmupEnd cannot precede warmupStart")
        if self.required != bool(self.condition_paths):
            raise ValueError("required must match conditionPaths")
        if not self.required:
            if (
                self.coverage_status != "NOT_REQUIRED"
                or self.blockers
                or self.required_five_minute_count
                or self.required_official_day_count
            ):
                raise ValueError("unused reference market cannot block a run")
            return self
        if self.coverage_status == "NOT_REQUIRED":
            raise ValueError("required reference market needs a coverage result")
        if (self.coverage_status == "AVAILABLE") != (not self.blockers):
            raise ValueError("coverage status must agree with blockers")
        if self.coverage_status == "AVAILABLE" and self.market_index_data_hash is None:
            raise ValueError("available reference market needs a data hash")
        return self


class BacktestReferenceMarketView(_BacktestApiInput):
    """Exact server-authored coverage and condition summary for one run."""

    binding: BacktestReferenceMarketBindingView
    required: Literal[True]
    condition_paths: Annotated[tuple[str, ...], Field(min_length=1, max_length=50)]
    warmup_start: ApiDate
    coverage_status: Literal["AVAILABLE", "BLOCKED", "EXPIRED", "NOT_RECORDED"]
    blockers: Annotated[tuple[StableBlockerCode, ...], Field(max_length=100)]
    market_index_data_hash: Sha256Hex
    index_requirement_hash: Sha256Hex
    formula_definition_hash: Sha256Hex
    dataset_hash: Sha256Hex
    condition_summaries: Annotated[
        tuple[BacktestIndexConditionSummaryView, ...],
        Field(min_length=1, max_length=50),
    ]

    @field_validator("condition_paths", "blockers", mode="before")
    @classmethod
    def require_array(cls, value: object, info: ValidationInfo) -> tuple[object, ...]:
        return _require_json_array(value, field_name=info.field_name)

    @field_validator("condition_summaries", mode="before")
    @classmethod
    def require_summary_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="conditionSummaries")

    @model_validator(mode="after")
    def validate_reference_market(self) -> Self:
        if self.condition_paths != tuple(sorted(set(self.condition_paths))):
            raise ValueError("conditionPaths must be ordered and unique")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("blockers must be ordered and unique")
        summary_paths = tuple(item.plan_path for item in self.condition_summaries)
        if summary_paths != self.condition_paths:
            raise ValueError("condition summaries must match every ordered plan path")
        if (self.coverage_status == "AVAILABLE") != (not self.blockers):
            raise ValueError("coverage status must agree with blockers")
        return self


class BacktestMarketIndexPointView(_BacktestApiInput):
    """One exact official-daily display point and its server-computed facts."""

    trade_date: ApiDate
    data_at: ShanghaiDatetime
    close_points: DecimalText
    snapshot_hash: Sha256Hex
    indicator_facts: Annotated[tuple[MarketIndexIndicatorFactView, ...], Field(max_length=50)]
    health: Annotated[MarketIndexHealth, Field(strict=False)]
    issues: Annotated[
        tuple[Annotated[MarketIndexIssueCode, Field(strict=False)], ...],
        Field(max_length=16),
    ]

    @field_validator("indicator_facts", "issues", mode="before")
    @classmethod
    def require_point_arrays(cls, value: object, info: ValidationInfo) -> tuple[object, ...]:
        return _require_json_array(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_point(self) -> Self:
        if self.data_at.date() != self.trade_date:
            raise ValueError("index point dataAt must fall on tradeDate")
        if tuple(dict.fromkeys(self.issues)) != self.issues:
            raise ValueError("index point issues must be unique")
        if self.health is MarketIndexHealth.LIVE and self.issues:
            raise ValueError("LIVE index point cannot contain issues")
        if self.health is not MarketIndexHealth.LIVE and not self.issues:
            raise ValueError("non-LIVE index point requires an issue")
        return self


class BacktestMarketIndexHealthPointView(_BacktestApiInput):
    data_at: ShanghaiDatetime
    health: Annotated[MarketIndexHealth, Field(strict=False)]
    issues: Annotated[
        tuple[Annotated[MarketIndexIssueCode, Field(strict=False)], ...],
        Field(max_length=16),
    ]

    @field_validator("issues", mode="before")
    @classmethod
    def require_issue_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="issues")

    @model_validator(mode="after")
    def validate_health(self) -> Self:
        if tuple(dict.fromkeys(self.issues)) != self.issues:
            raise ValueError("health issues must be unique")
        if self.health is MarketIndexHealth.LIVE and self.issues:
            raise ValueError("LIVE health cannot contain issues")
        if self.health is not MarketIndexHealth.LIVE and not self.issues:
            raise ValueError("non-LIVE health requires an issue")
        return self


class BacktestMarketIndexSeriesView(_BacktestApiInput):
    """Bounded reference-index series that never synthesizes an old run's data."""

    run_id: Sha256Hex
    reference_market: BacktestReferenceMarketView | None
    items: Annotated[tuple[BacktestMarketIndexPointView, ...], Field(max_length=512)]
    health_timeline: Annotated[
        tuple[BacktestMarketIndexHealthPointView, ...],
        Field(max_length=512),
    ]
    condition_summaries: Annotated[
        tuple[BacktestIndexConditionSummaryView, ...],
        Field(max_length=50),
    ]

    @field_validator("items", "health_timeline", "condition_summaries", mode="before")
    @classmethod
    def require_series_arrays(cls, value: object, info: ValidationInfo) -> tuple[object, ...]:
        return _require_json_array(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        if self.reference_market is None:
            if self.items or self.health_timeline or self.condition_summaries:
                raise ValueError("no-index run series must remain explicitly empty")
            return self
        if self.condition_summaries != self.reference_market.condition_summaries:
            raise ValueError("series condition summaries must match the run identity")
        positions = tuple((item.trade_date, item.data_at) for item in self.items)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("index display points must be ordered and unique")
        health_positions = tuple(item.data_at for item in self.health_timeline)
        if health_positions != tuple(sorted(set(health_positions))):
            raise ValueError("index health timeline must be ordered and unique")
        if len(self.model_dump_json().encode("utf-8")) >= MAX_RESULT_PAGE_BYTES:
            raise ValueError("encoded index series must be smaller than 4 MiB")
        return self


class BacktestRunSummaryView(_BacktestApiInput):
    """Public run summary that can exist only after completed publication."""

    run_id: Sha256Hex
    report_hash: Sha256Hex
    plan_version_id: Rfc4122Uuid | None
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    symbol: AShareSymbolText
    status: Literal["COMPLETED"]
    event_start: ApiDate
    event_end: ApiDate
    completed_at: ShanghaiDatetime
    pinned: bool = Field(strict=True)
    revision: JavaScriptSafeInteger
    fill_count: JavaScriptSafeInteger
    metrics: BacktestMetricsView | ResearchMetricsView
    availability: BacktestResultAvailabilityView

    @model_validator(mode="after")
    def validate_completed_summary(self) -> Self:
        if self.event_end < self.event_start:
            raise ValueError("eventEnd cannot precede eventStart")
        if self.fill_count != self.metrics.trade_count:
            raise ValueError("fillCount must match metrics.tradeCount")
        _require_max_item_bytes(self)
        return self


class BacktestRunView(BacktestRunSummaryView):
    """Complete public run projection with no staged or failed variant."""

    initial_cash_fen: PositiveFenText
    coverage: BacktestRunCoverageView
    assumptions: BacktestAssumptionsView
    formula_versions: BacktestFormulaVersionsView
    limitations: Annotated[tuple[StableToken, ...], Field(max_length=32)]
    reference_market: BacktestReferenceMarketView | None = None

    @field_validator("limitations", mode="before")
    @classmethod
    def require_limitation_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="limitations")

    @model_validator(mode="after")
    def validate_complete_run(self) -> Self:
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("limitations must be ordered and unique")
        if self.initial_cash_fen != self.metrics.initial_cash_fen:
            raise ValueError("initialCashFen must match metrics.initialCashFen")
        if (self.coverage.event_start, self.coverage.event_end) != (
            self.event_start,
            self.event_end,
        ):
            raise ValueError("coverage event range must match the run")
        if self.coverage.fill_count != self.fill_count:
            raise ValueError("coverage.fillCount must match fillCount")
        artifact_counts = (
            ("decisionDetails", self.coverage.decision_count, self.availability.decision_details),
            ("signalDetails", self.coverage.signal_count, self.availability.signal_details),
            (
                "executionOutcomeDetails",
                self.coverage.outcome_count,
                self.availability.execution_outcome_details,
            ),
            ("equitySeries", self.coverage.equity_point_count, self.availability.equity_series),
        )
        for name, count, availability in artifact_counts:
            if (count == 0) != (availability == "NOT_RECORDED"):
                raise ValueError(f"{name} availability must match its original count")
        return self


MAX_RESULT_ITEM_BYTES = 32 * 1024
MAX_RESULT_PAGE_BYTES = 4 * 1024 * 1024
MAX_EQUITY_POINTS = 2_000
MAX_EVIDENCE = 50
MAX_EVIDENCE_FACTS = 512
MAX_MISSING_INPUTS = 16


def _require_max_item_bytes(value: BaseModel) -> None:
    if len(value.model_dump_json().encode("utf-8")) > MAX_RESULT_ITEM_BYTES:
        raise ValueError("encoded result item must not exceed 32 KiB")


ConditionOutcomeValue = Annotated[ConditionOutcome, Field(strict=False)]
DataHealthStatusValue = Annotated[DataHealthStatus, Field(strict=False)]
DecisionZoneValue = Annotated[DecisionZone, Field(strict=False)]
EpisodeStatusValue = Annotated[EpisodeStatus, Field(strict=False)]
EvidenceUnitValue = Annotated[EvidenceUnit, Field(strict=False)]
MissingInputCodeValue = Annotated[MissingInputCode, Field(strict=False)]
NextStepCodeValue = Annotated[NextStepCode, Field(strict=False)]
RiskStatusValue = Annotated[RiskStatus, Field(strict=False)]
SignalTypeValue = Annotated[SignalType, Field(strict=False)]
ActionableSignalTypeValue = Annotated[ActionableSignalType, Field(strict=False)]
ExecutionStatusValue = Annotated[ExecutionStatus, Field(strict=False)]
UnfilledReasonValue = Annotated[UnfilledReason, Field(strict=False)]
type BacktestEvidenceScalar = bool | int | Decimal | ShanghaiDatetime | ApiDate | EvidenceCode


class BacktestEvidenceFactView(_BacktestApiInput):
    key: EvidenceKey
    value: BacktestEvidenceScalar
    unit: EvidenceUnitValue


class BacktestDecisionEvidenceView(_BacktestApiInput):
    kind: Literal["CONDITION", "RULE"]
    code: EvidenceCode
    outcome: ConditionOutcomeValue
    facts: Annotated[tuple[BacktestEvidenceFactView, ...], Field(max_length=MAX_EVIDENCE_FACTS)]
    missing_inputs: Annotated[
        tuple[MissingInputCodeValue, ...],
        Field(max_length=MAX_MISSING_INPUTS),
    ]
    children: Annotated[tuple[BacktestDecisionEvidenceView, ...], Field(max_length=MAX_EVIDENCE)]

    @field_validator("facts", "missing_inputs", "children", mode="before")
    @classmethod
    def require_evidence_arrays(cls, value: object, info: Any) -> tuple[object, ...]:
        return _require_json_array(value, field_name=_to_camel(info.field_name))

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("evidence fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            child_missing = any(
                child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children
            )
            if not self.missing_inputs and not child_missing:
                raise ValueError("missing evidence must identify unavailable input")
        elif self.missing_inputs:
            raise ValueError("non-missing evidence cannot contain missing inputs")
        return self


class BacktestPositionSummaryView(_BacktestApiInput):
    core_quantity: JavaScriptSafeInteger
    tactical_quantity: JavaScriptSafeInteger
    total_quantity: JavaScriptSafeInteger
    sellable_core_quantity: JavaScriptSafeInteger
    sellable_tactical_quantity: JavaScriptSafeInteger

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if self.total_quantity != self.core_quantity + self.tactical_quantity:
            raise ValueError("totalQuantity must equal core plus tactical quantity")
        if self.sellable_core_quantity > self.core_quantity:
            raise ValueError("sellableCoreQuantity cannot exceed coreQuantity")
        if self.sellable_tactical_quantity > self.tactical_quantity:
            raise ValueError("sellableTacticalQuantity cannot exceed tacticalQuantity")
        return self


class BacktestDataHealthView(_BacktestApiInput):
    status: DataHealthStatusValue
    latest_bar_end: ShanghaiDatetime | None
    data_age_seconds: JavaScriptSafeInteger | None
    required_data_complete: bool = Field(strict=True)
    fresh: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_health(self) -> Self:
        if (self.latest_bar_end is None) != (self.data_age_seconds is None):
            raise ValueError("latest bar and data age must appear together")
        if self.fresh and self.latest_bar_end is None:
            raise ValueError("fresh health requires a latest bar")
        if self.status is DataHealthStatus.LIVE and (
            not self.fresh or not self.required_data_complete or self.latest_bar_end is None
        ):
            raise ValueError("LIVE health requires fresh complete data")
        if self.status is DataHealthStatus.STALE and self.fresh:
            raise ValueError("STALE health cannot be fresh")
        if self.status in {DataHealthStatus.GAPPED, DataHealthStatus.BLOCKED} and (
            self.required_data_complete
        ):
            raise ValueError("gapped or blocked health cannot be complete")
        return self


class BacktestNextStepView(_BacktestApiInput):
    code: NextStepCodeValue
    not_before: ShanghaiDatetime | ApiDate | None
    required_inputs: Annotated[
        tuple[MissingInputCodeValue, ...],
        Field(max_length=MAX_MISSING_INPUTS),
    ]

    @field_validator("required_inputs", mode="before")
    @classmethod
    def require_input_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="requiredInputs")

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError("next-step inputs must be unique")
        return self


class BacktestDecisionReferenceMarketView(_BacktestApiInput):
    """Compact immutable index identity and exact path evidence for one decision."""

    index_code: Annotated[MarketIndexCode, Field(strict=False)]
    snapshot_hash: Sha256Hex | None
    data_at: ShanghaiDatetime | None
    health: Annotated[MarketIndexHealth, Field(strict=False)]
    evidence: Annotated[tuple[IndexConditionEvidenceView, ...], Field(min_length=1, max_length=50)]

    @field_validator("evidence", mode="before")
    @classmethod
    def require_evidence_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="evidence")

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        paths = tuple(item.plan_path for item in self.evidence)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("decision index evidence must be path-ordered and unique")
        if any(item.index_code is not self.index_code for item in self.evidence):
            raise ValueError("decision index evidence must share one index identity")
        if self.health is MarketIndexHealth.LIVE:
            if (
                self.snapshot_hash is None
                or self.data_at is None
                or any(item.snapshot_hash != self.snapshot_hash for item in self.evidence)
            ):
                raise ValueError("LIVE decision index evidence needs complete snapshot identity")
        return self


class BacktestAuthoritativeDecisionView(_BacktestApiInput):
    """Live-decision-equivalent projection with FenText money only for backtests."""

    symbol: AShareSymbolText
    result_hash: Sha256Hex
    plan_id: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    plan_version: PositiveJavaScriptSafeInteger
    plan_hash: Sha256Hex
    evaluated_at: ShanghaiDatetime
    market_data_at: ShanghaiDatetime | None
    data_age_seconds: JavaScriptSafeInteger | None
    price_fen: PositiveFenText | None
    zone: DecisionZoneValue
    signal_type: SignalTypeValue
    position: BacktestPositionSummaryView
    episode_status: EpisodeStatusValue | None
    episode_low_fen: PositiveFenText | None
    risk_status: RiskStatusValue
    risk_breach_trade_date: ApiDate | None
    data_health: BacktestDataHealthView
    evidence: Annotated[tuple[BacktestDecisionEvidenceView, ...], Field(max_length=MAX_EVIDENCE)]
    next_step: BacktestNextStepView
    reference_market: BacktestDecisionReferenceMarketView | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def require_evidence_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="evidence")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        market_values = (self.market_data_at, self.data_age_seconds, self.price_fen)
        if any(value is None for value in market_values) and any(
            value is not None for value in market_values
        ):
            raise ValueError("market time, data age, and price must appear together")
        if self.market_data_at is not None:
            age = self.evaluated_at - self.market_data_at
            if age < timedelta(0) or int(age.total_seconds()) != self.data_age_seconds:
                raise ValueError("decision data age must match its timestamps")
        if self.data_health.latest_bar_end is not None:
            health_age = self.evaluated_at - self.data_health.latest_bar_end
            if health_age < timedelta(0) or int(health_age.total_seconds()) != (
                self.data_health.data_age_seconds
            ):
                raise ValueError("health data age must match evaluation time")
        if (self.episode_status is None) != (self.episode_low_fen is None):
            raise ValueError("episode status and low must appear together")
        if self.risk_status is RiskStatus.CLEAR:
            if self.risk_breach_trade_date is not None:
                raise ValueError("clear risk cannot retain a breach date")
        elif self.risk_breach_trade_date is None:
            raise ValueError("active risk requires a breach date")
        if (
            self.risk_breach_trade_date is not None
            and self.risk_breach_trade_date > self.evaluated_at.date()
        ):
            raise ValueError("risk breach cannot follow evaluation")
        actionable = {signal.value for signal in ActionableSignalType}
        if (
            self.signal_type.value in actionable
            and self.data_health.status is not DataHealthStatus.LIVE
        ):
            raise ValueError("actionable decisions require LIVE data")
        return self


class BacktestFeeBreakdownView(_BacktestApiInput):
    commission_fen: NonNegativeFenText
    stamp_duty_fen: NonNegativeFenText
    transfer_fee_fen: NonNegativeFenText
    total_fen: NonNegativeFenText

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        components = (
            int(self.commission_fen) + int(self.stamp_duty_fen) + int(self.transfer_fee_fen)
        )
        if int(self.total_fen) != components:
            raise ValueError("fee total must equal its components")
        return self


class BacktestFillView(_BacktestApiInput):
    fill_id: StableIdentifier
    order_id: StableIdentifier
    signal_id: StableIdentifier
    run_id: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    result_hash: Sha256Hex
    config_hash: Sha256Hex
    source_bar_id: StableIdentifier
    side: Literal["BUY", "SELL"]
    symbol: AShareSymbolText
    bucket: Literal["CORE", "TACTICAL"]
    target_lot_id: StableIdentifier | None
    filled_at: ShanghaiDatetime
    requested_quantity: PositiveSafeBoardLot
    quantity: PositiveSafeBoardLot
    price_fen: PositiveFenText
    notional_fen: PositiveFenText
    fees: BacktestFeeBreakdownView
    cash_delta_fen: FenText
    cost_basis_released_fen: NonNegativeFenText
    realized_pnl_fen: FenText | None

    @model_validator(mode="after")
    def validate_fill(self) -> Self:
        if self.quantity > self.requested_quantity:
            raise ValueError("quantity cannot exceed requestedQuantity")
        notional = int(self.price_fen) * self.quantity
        if int(self.notional_fen) != notional:
            raise ValueError("notionalFen must equal priceFen times quantity")
        cash_delta = int(self.cash_delta_fen)
        fees = int(self.fees.total_fen)
        released = int(self.cost_basis_released_fen)
        if self.side == "BUY":
            if cash_delta != -(notional + fees):
                raise ValueError("buy cashDeltaFen must include notional and fees")
            if released != 0 or self.realized_pnl_fen is not None or self.target_lot_id is not None:
                raise ValueError("buy fill cannot release, realize, or target a lot")
        else:
            if cash_delta != notional - fees:
                raise ValueError("sell cashDeltaFen must equal net proceeds")
            if self.target_lot_id is None or self.realized_pnl_fen is None:
                raise ValueError("sell fill requires a target lot and realizedPnlFen")
            if int(self.realized_pnl_fen) != cash_delta - released:
                raise ValueError("sell realizedPnlFen must equal net proceeds less cost basis")
        _require_max_item_bytes(self)
        return self


class _BacktestDetailBase(_BacktestApiInput):
    detail_id: StableIdentifier
    run_id: Sha256Hex
    event_at: ShanghaiDatetime


class BacktestDecisionView(_BacktestDetailBase):
    kind: Literal["DECISION"]
    result_hash: Sha256Hex
    decision: BacktestAuthoritativeDecisionView

    @model_validator(mode="after")
    def validate_identity_and_item_size(self) -> Self:
        if self.result_hash != self.decision.result_hash:
            raise ValueError("resultHash must match the authoritative decision")
        if self.event_at != self.decision.evaluated_at:
            raise ValueError("eventAt must match the authoritative decision evaluation time")
        _require_max_item_bytes(self)
        return self


class BacktestSignalView(_BacktestDetailBase):
    kind: Literal["SIGNAL"]
    signal_id: StableIdentifier
    result_hash: Sha256Hex
    signal_type: ActionableSignalTypeValue
    symbol: AShareSymbolText
    quantity: PositiveSafeBoardLot | None
    bucket: Literal["CORE", "TACTICAL"] | None
    target_lot_id: StableIdentifier | None
    cause_id: StableIdentifier

    @model_validator(mode="after")
    def validate_signal_shape(self) -> Self:
        if self.signal_type is ActionableSignalType.RISK_BREACH:
            if any(value is not None for value in (self.quantity, self.bucket, self.target_lot_id)):
                raise ValueError("risk breach cannot imply an execution order")
        else:
            if self.quantity is None or self.bucket is None:
                raise ValueError("trade-shaped signal requires quantity and bucket")
            buy = self.signal_type in {
                ActionableSignalType.BUY_CORE_READY,
                ActionableSignalType.BUY_TACTICAL_READY,
            }
            if buy == (self.target_lot_id is not None):
                raise ValueError("only sell-shaped signals require targetLotId")
            if self.signal_type is ActionableSignalType.BUY_CORE_READY and self.bucket != "CORE":
                raise ValueError("core buy must use CORE bucket")
            if (
                self.signal_type
                in {
                    ActionableSignalType.BUY_TACTICAL_READY,
                    ActionableSignalType.PRESSURE_REDUCE_READY,
                }
                and self.bucket != "TACTICAL"
            ):
                raise ValueError("tactical signal must use TACTICAL bucket")
        _require_max_item_bytes(self)
        return self


class BacktestExecutionOutcomeView(_BacktestDetailBase):
    kind: Literal["EXECUTION_OUTCOME"]
    outcome_id: StableIdentifier
    signal_id: StableIdentifier
    order_id: StableIdentifier | None
    source_bar_id: StableIdentifier | None
    status: ExecutionStatusValue
    reason: UnfilledReasonValue | None
    fill_id: StableIdentifier | None

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> Self:
        if self.status is ExecutionStatus.FILLED:
            if (
                self.fill_id is None
                or self.reason is not None
                or self.order_id is None
                or self.source_bar_id is None
            ):
                raise ValueError("filled outcome requires order/fill/source bar and no reason")
        elif self.fill_id is not None or self.reason is None:
            raise ValueError("non-filled outcome requires a reason and no fill")
        if self.status is ExecutionStatus.UNFILLED and self.order_id is None:
            raise ValueError("unfilled outcome requires an accepted order")
        if self.status is ExecutionStatus.IGNORED and (
            self.order_id is not None or self.source_bar_id is not None
        ):
            raise ValueError("ignored outcome cannot identify an order or source bar")
        if self.status is ExecutionStatus.UNFILLED:
            if (self.reason is UnfilledReason.NO_NEXT_MINUTE) != (self.source_bar_id is None):
                raise ValueError("unfilled source bar must match its reason")
        _require_max_item_bytes(self)
        return self


class ResearchDecisionView(_BacktestDetailBase):
    kind: Literal["DECISION"]
    research_decision: ResearchDecisionEvent

    @field_validator("research_decision", mode="before")
    @classmethod
    def parse_evidence(cls, value):
        if isinstance(value, ResearchDecisionEvent):
            return value
        return ResearchDecisionEvent.model_validate_json(json.dumps(value))

    @model_validator(mode="after")
    def bounded(self):
        _require_max_item_bytes(self)
        return self


class ResearchOperationView(_BacktestDetailBase):
    kind: Literal["EXECUTION_OUTCOME"]
    research_operation: ResearchOperationOutcome

    @field_validator("research_operation", mode="before")
    @classmethod
    def parse_evidence(cls, value):
        if isinstance(value, ResearchOperationOutcome):
            return value
        return ResearchOperationOutcome.model_validate_json(json.dumps(value))

    @model_validator(mode="after")
    def bounded(self):
        _require_max_item_bytes(self)
        return self


class BacktestLoopProvenanceView(_BacktestApiInput):
    preparation_id: PreparedIdentifier
    manifest_hash: Sha256Hex
    source_revision: JavaScriptSafeInteger
    candidate_revision: JavaScriptSafeInteger
    candidate_hash: Sha256Hex
    input_hash: Sha256Hex


class BacktestLoopRunSummaryView(_BacktestApiInput):
    """Separate loop metrics; legacy cash/return assumptions are never synthesized."""

    schema_version: Literal["monitor-loop-result-v1"]
    run_id: Sha256Hex
    report_hash: Sha256Hex
    plan_version_id: None
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    symbol: AShareSymbolText
    status: Literal["COMPLETED"]
    event_start: ApiDate
    event_end: ApiDate
    completed_at: ShanghaiDatetime
    pinned: bool = Field(strict=True)
    revision: JavaScriptSafeInteger
    fill_count: JavaScriptSafeInteger
    metrics: LoopMetrics
    availability: BacktestResultAvailabilityView

    @field_validator("metrics", mode="before")
    @classmethod
    def native_metrics(cls, value):
        return _native_loop_value(value, LoopMetrics)

    @model_validator(mode="after")
    def bounded_summary(self) -> Self:
        if self.event_end < self.event_start:
            raise ValueError("eventEnd cannot precede eventStart")
        # Full headers have a distinct bounded response, while list items keep 32 KiB.
        summary = self.model_dump(
            mode="json", by_alias=True, include=set(BacktestLoopRunSummaryView.model_fields)
        )
        if (
            len(
                json.dumps(
                    summary,
                    ensure_ascii=False,
                ).encode()
            )
            > MAX_RESULT_ITEM_BYTES
        ):
            raise ValueError("encoded loop summary must not exceed 32 KiB")
        return self


class BacktestLoopRunView(BacktestLoopRunSummaryView):
    """Verified native header and one reviewed plan, without the raw source text."""

    provenance: BacktestLoopProvenanceView
    frozen_plan: LoopPlanVersion
    opening_account: LoopAccountInput
    response: LoopResponsePolicy
    costs: LoopCosts
    report: MonitorLoopReport
    plan_diagnostics: LoopDiagnostics | None = None

    @field_validator("frozen_plan", "opening_account", "response", "costs", "report", mode="before")
    @classmethod
    def native_values(cls, value, info: ValidationInfo):
        model = {
            "frozen_plan": LoopPlanVersion,
            "opening_account": LoopAccountInput,
            "response": LoopResponsePolicy,
            "costs": LoopCosts,
            "report": MonitorLoopReport,
        }[info.field_name]
        return _native_loop_value(value, model)

    @model_validator(mode="after")
    def bind_header(self) -> Self:
        report = self.report
        if (
            (
                report.run_id,
                report.report_hash,
                report.plan_hash,
                report.dataset_hash,
                report.symbol,
            )
            != (self.run_id, self.report_hash, self.plan_hash, self.dataset_hash, self.symbol)
            or report.input_hash != self.provenance.input_hash
            or report.metrics != self.metrics
            or report.cycle.fills != self.fill_count
            or report.boundary.started_at.date() != self.event_start
            or report.boundary.resolved_end_date != self.event_end
            or report.boundary.evidence_cutoff != self.completed_at
            or self.frozen_plan.plan_hash != self.plan_hash
            or self.frozen_plan.snapshot.symbol != self.symbol
        ):
            raise ValueError("loop result must bind its native header and frozen plan")
        _bind_loop_diagnostics(
            self.plan_diagnostics, [self.frozen_plan.version_id], self.fill_count,
        )
        if len(self.model_dump_json().encode()) >= MAX_RESULT_PAGE_BYTES:
            raise ValueError("encoded loop result must be below 4 MiB")
        return self



class BacktestScheduledSourceView(_BacktestApiInput):
    source_id: PreparedIdentifier
    source_hash: Sha256Hex
    source_revision: PositiveJavaScriptSafeInteger
    candidate_revision: PositiveJavaScriptSafeInteger
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    base_hash: Sha256Hex | None


class BacktestScheduledProvenanceView(_BacktestApiInput):
    preparation_id: PreparedIdentifier
    manifest_hash: Sha256Hex
    input_hash: Sha256Hex
    revision: PositiveJavaScriptSafeInteger
    sources: tuple[BacktestScheduledSourceView, ...] = Field(min_length=1, max_length=256)


class BacktestScheduledReportHeader(ResearchValue):
    """Bounded projection of an already verified immutable report, not its private codec."""

    report_schema_version: Literal["backtest-report-v5"]
    run_id: Sha256Hex
    input_hash: Sha256Hex
    dataset_hash: Sha256Hex
    symbol: str
    boundary: LoopEndBoundary
    cycle: LoopCycleSummary
    event_count: int = Field(ge=1, le=MAX_AUDIT_EVENTS)
    event_set_hash: Sha256Hex
    opening_valuation: LoopValuation
    final_valuation: LoopValuation
    final_account: LoopAccountState
    final_inventory: DailyInventoryView
    last_evidence_at: LoopTimestamp | None
    last_valuation_at: LoopTimestamp
    metrics: LoopMetrics
    report_hash: Sha256Hex


class BacktestScheduledRunSummaryView(BacktestLoopRunSummaryView):
    schema_version: Literal["monitor-loop-result-v2"]


class BacktestScheduledRunView(BacktestScheduledRunSummaryView):
    provenance: BacktestScheduledProvenanceView
    versions: tuple[CollectionVersionView, ...] = Field(min_length=1, max_length=256)
    opening_account: LoopAccountInput
    response: LoopResponsePolicy
    costs: LoopCosts
    report: BacktestScheduledReportHeader
    plan_diagnostics: LoopDiagnostics | None = None

    @field_validator("opening_account", "response", "costs", "report", mode="before")
    @classmethod
    def native_values(cls, value, info: ValidationInfo):
        model = {"opening_account": LoopAccountInput, "response": LoopResponsePolicy,
                 "costs": LoopCosts, "report": BacktestScheduledReportHeader}[info.field_name]
        return _native_loop_value(value, model)

    @field_validator("versions", mode="before")
    @classmethod
    def native_versions(cls, value):
        if not isinstance(value, (tuple, list)):
            raise ValueError("versions must be an array")
        return tuple(_native_loop_value(item, CollectionVersionView) for item in value)

    @model_validator(mode="after")
    def bind_header(self):
        report = self.report
        if ((report.run_id, report.report_hash, report.dataset_hash, report.symbol)
                != (self.run_id, self.report_hash, self.dataset_hash, self.symbol)
                or report.input_hash != self.provenance.input_hash
                or report.metrics != self.metrics or report.cycle.fills != self.fill_count
                or report.boundary.started_at.date() != self.event_start
                or report.boundary.resolved_end_date != self.event_end
                or report.boundary.evidence_cutoff != self.completed_at
                or self.versions[0].plan_hash != self.plan_hash
                or len(self.versions) != len(self.provenance.sources)):
            raise ValueError("scheduled result must bind its verified header and versions")
        for source, version in zip(self.provenance.sources, self.versions, strict=True):
            if (source.source_id, source.source_revision, source.candidate_revision) != (
                version.source_id, version.source_revision, version.candidate_revision,
            ):
                raise ValueError("scheduled version reference differs from its frozen source")
        _bind_loop_diagnostics(self.plan_diagnostics, [v.version_id for v in self.versions],
                               self.fill_count)
        if self.plan_diagnostics is not None:
            for diagnostic, version in zip(self.plan_diagnostics.plans, self.versions, strict=True):
                if (diagnostic.source_id, diagnostic.effective_trade_date) != (
                    version.source_id, version.effective_trade_date,
                ):
                    raise ValueError("diagnostic source identity differs from frozen version")
        if len(self.model_dump_json().encode()) >= MAX_RESULT_PAGE_BYTES:
            raise ValueError("encoded loop result must be below 4 MiB")
        return self

def _bind_loop_diagnostics(diagnostics, versions, fills):
    if diagnostics is None:
        return
    if [p.version_id for p in diagnostics.plans] != versions:
        raise ValueError("diagnostic versions differ from the report")
    if diagnostics.availability == "AVAILABLE" and (
        any(p.fill_count is None for p in diagnostics.plans)
        or sum(p.fill_count for p in diagnostics.plans) != fills
    ):
        raise ValueError("diagnostic fills differ from the report")


def _native_loop_value(value, model):
    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        return model.model_validate_json(value.model_dump_json())
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


class BacktestLoopEventView(_BacktestDetailBase):
    kind: Literal["DECISION"]
    schema_version: Literal["monitor-loop-event-v1"]
    event: LoopAuditEvent

    @field_validator("event", mode="before")
    @classmethod
    def native_event(cls, value):
        return _native_loop_value(value, LoopAuditEvent)

    @model_validator(mode="after")
    def bind_event(self) -> Self:
        if (
            self.event.run_id != self.run_id
            or self.event.at != self.event_at
            or self.detail_id != f"loop-{self.event.sequence:06d}-{self.run_id[:16]}"
        ):
            raise ValueError("loop event must match its public row identity")
        _require_max_item_bytes(self)
        return self



class BacktestScheduledEventView(BacktestLoopEventView):
    schema_version: Literal["monitor-loop-event-v2"]
    event: ScheduledLoopAuditEvent

    @field_validator("event", mode="before")
    @classmethod
    def native_event(cls, value):
        return _native_loop_value(value, ScheduledLoopAuditEvent)


class BacktestLoopFillView(_BacktestApiInput):
    schema_version: Literal["monitor-loop-fill-v1"]
    fill_id: StableIdentifier
    run_id: Sha256Hex
    filled_at: ShanghaiDatetime
    event_id: Sha256Hex
    receipt: LoopAccountReceipt

    @field_validator("receipt", mode="before")
    @classmethod
    def native_receipt(cls, value):
        return _native_loop_value(value, LoopAccountReceipt)

    @model_validator(mode="after")
    def bind_receipt(self) -> Self:
        if (
            self.fill_id != self.receipt.authority_receipt.simulation_id
            or self.filled_at != self.receipt.authority_receipt.simulated_at
        ):
            raise ValueError("loop fill must match its simulation receipt")
        _require_max_item_bytes(self)
        return self


type BacktestDetailView = (
    BacktestDecisionView
    | BacktestSignalView
    | BacktestExecutionOutcomeView
    | ResearchDecisionView
    | ResearchOperationView
    | BacktestLoopEventView
    | BacktestScheduledEventView
)


class BacktestEquityPointView(_BacktestApiInput):
    snapshot_id: StableIdentifier
    run_id: Sha256Hex
    symbol: AShareSymbolText
    marked_at: ShanghaiDatetime
    mark_price_fen: PositiveFenText
    cash_fen: NonNegativeFenText
    position_quantity: Annotated[
        int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER, multiple_of=100)
    ]
    market_value_fen: NonNegativeFenText
    cost_basis_fen: NonNegativeFenText
    realized_pnl_fen: FenText
    unrealized_pnl_fen: FenText
    total_cost_fen: NonNegativeFenText
    equity_fen: NonNegativeFenText

    @model_validator(mode="after")
    def validate_equity(self) -> Self:
        market_value = int(self.mark_price_fen) * self.position_quantity
        if int(self.market_value_fen) != market_value:
            raise ValueError("marketValueFen must equal markPriceFen times positionQuantity")
        if int(self.unrealized_pnl_fen) != market_value - int(self.cost_basis_fen):
            raise ValueError("unrealizedPnlFen must equal market value less cost basis")
        if int(self.equity_fen) != int(self.cash_fen) + market_value:
            raise ValueError("equityFen must equal cashFen plus marketValueFen")
        _require_max_item_bytes(self)
        return self


def _validate_bounded_page(value: BaseModel, items: tuple[BaseModel, ...]) -> None:
    limit = value.limit
    next_cursor = value.next_cursor
    has_more = value.has_more
    if len(items) > limit:
        raise ValueError("page cannot contain more than limit items")
    if has_more != (next_cursor is not None):
        raise ValueError("hasMore and nextCursor must agree")
    for item in items:
        _require_max_item_bytes(item)
    if len(value.model_dump_json().encode("utf-8")) >= MAX_RESULT_PAGE_BYTES:
        raise ValueError("encoded page must be smaller than 4 MiB")


def _require_ordered_unique_positions(
    positions: tuple[tuple[Any, ...], ...],
    *,
    reverse: bool,
    resource: str,
) -> None:
    if len(set(positions)) != len(positions):
        raise ValueError(f"{resource} page positions must be unique")
    if positions != tuple(sorted(positions, reverse=reverse)):
        direction = "descending" if reverse else "ascending"
        raise ValueError(f"{resource} page must use canonical {direction} order")


class ResearchEquityView(_BacktestApiInput):
    schema_version: Literal["unified-research-equity-v1"]
    snapshot_id: Sha256Hex
    run_id: Sha256Hex
    marked_at: ShanghaiDatetime
    mark_price_fen: PositiveFenText | None
    cash_fen: NonNegativeFenText | None
    position_quantity: JavaScriptSafeInteger | None
    market_value_fen: NonNegativeFenText | None
    equity_fen: NonNegativeFenText | None
    valuation_valid: bool
    blockers: tuple[str, ...]

    @field_validator("blockers", mode="before")
    @classmethod
    def array(cls, value):
        return tuple(value)


class BacktestEquitySeries(_BacktestApiInput):
    availability: BacktestArtifactAvailability
    items: Annotated[
        tuple[BacktestEquityPointView | ResearchEquityView, ...],
        Field(max_length=MAX_EQUITY_POINTS),
    ]

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        if (self.availability == "AVAILABLE") != bool(self.items):
            raise ValueError("equity availability must match its empty or non-empty shape")
        positions = tuple((item.marked_at, item.snapshot_id) for item in self.items)
        if positions != tuple(sorted(positions)):
            raise ValueError("equity points must be ordered by markedAt and snapshotId")
        if len({item.snapshot_id for item in self.items}) != len(self.items):
            raise ValueError("equity snapshot identities must be unique")
        if len(self.model_dump_json().encode("utf-8")) >= MAX_RESULT_PAGE_BYTES:
            raise ValueError("encoded equity series must be smaller than 4 MiB")
        return self


class BacktestJobFiltersView(_BacktestApiInput):
    kind: Annotated[tuple[BacktestJobKind, ...], Field(min_length=1, max_length=3)] | None
    status: Annotated[tuple[BacktestJobStatus, ...], Field(min_length=1, max_length=6)] | None
    run_id: Sha256Hex | None
    dataset_hash: Sha256Hex | None
    created_from: ShanghaiDatetime | None
    created_to: ShanghaiDatetime | None

    @field_validator("kind", "status", mode="before")
    @classmethod
    def normalize_repeated_enums(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return None
        items = _require_json_array(value, field_name=info.field_name)
        if not items or any(type(item) is not str for item in items):
            raise ValueError(f"{info.field_name} must be a non-empty string array")
        return tuple(sorted(set(items)))

    @model_validator(mode="after")
    def validate_created_range(self) -> Self:
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise ValueError("createdFrom cannot be after createdTo")
        return self


class BacktestRunFiltersView(_BacktestApiInput):
    symbol: AShareSymbolText | None
    plan_version_id: Rfc4122Uuid | None
    dataset_hash: Sha256Hex | None
    completed_from: ShanghaiDatetime | None
    completed_to: ShanghaiDatetime | None
    pinned: bool | None

    @field_validator("pinned", mode="before")
    @classmethod
    def require_strict_optional_boolean(cls, value: object) -> object:
        if value is not None and type(value) is not bool:
            raise ValueError("pinned must be a boolean or null")
        return value

    @model_validator(mode="after")
    def validate_completed_range(self) -> Self:
        if (
            self.completed_from is not None
            and self.completed_to is not None
            and self.completed_from > self.completed_to
        ):
            raise ValueError("completedFrom cannot be after completedTo")
        return self


class BacktestFillFiltersView(_BacktestApiInput):
    """Closed empty filter object for one run's long-lived fill ledger."""


BacktestPublicDetailKind = Literal["DECISION", "SIGNAL", "EXECUTION_OUTCOME"]


class BacktestDetailFiltersView(_BacktestApiInput):
    kind: BacktestPublicDetailKind


class BacktestJobPage(_BacktestApiInput):
    filters: BacktestJobFiltersView
    items: Annotated[tuple[BacktestJobView, ...], Field(max_length=100)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: CursorToken | None
    has_more: bool = Field(strict=True)
    high_watermark: CursorToken

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        positions = tuple((item.created_at, item.job_id) for item in self.items)
        _require_ordered_unique_positions(positions, reverse=True, resource="job")
        for item in self.items:
            if self.filters.kind is not None and item.kind not in self.filters.kind:
                raise ValueError("job item must match kind filter")
            if self.filters.status is not None and item.status not in self.filters.status:
                raise ValueError("job item must match status filter")
            if self.filters.run_id is not None and item.run_id != self.filters.run_id:
                raise ValueError("job item must match runId filter")
            if (
                self.filters.dataset_hash is not None
                and item.dataset_hash != self.filters.dataset_hash
            ):
                raise ValueError("job item must match datasetHash filter")
            if (
                self.filters.created_from is not None
                and item.created_at < self.filters.created_from
            ):
                raise ValueError("job item must match createdFrom filter")
            if self.filters.created_to is not None and item.created_at > self.filters.created_to:
                raise ValueError("job item must match createdTo filter")
        _validate_bounded_page(self, self.items)
        return self


class BacktestRunPage(_BacktestApiInput):
    filters: BacktestRunFiltersView
    items: Annotated[
        tuple[BacktestRunSummaryView | BacktestLoopRunSummaryView
              | BacktestScheduledRunSummaryView, ...], Field(max_length=100)
    ]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: CursorToken | None
    has_more: bool = Field(strict=True)
    high_watermark: CursorToken

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        positions = tuple((item.completed_at, item.run_id) for item in self.items)
        _require_ordered_unique_positions(positions, reverse=True, resource="run")
        for item in self.items:
            if self.filters.symbol is not None and item.symbol != self.filters.symbol:
                raise ValueError("run item must match symbol filter")
            if (
                self.filters.plan_version_id is not None
                and item.plan_version_id != self.filters.plan_version_id
            ):
                raise ValueError("run item must match planVersionId filter")
            if (
                self.filters.dataset_hash is not None
                and item.dataset_hash != self.filters.dataset_hash
            ):
                raise ValueError("run item must match datasetHash filter")
            if (
                self.filters.completed_from is not None
                and item.completed_at < self.filters.completed_from
            ):
                raise ValueError("run item must match completedFrom filter")
            if (
                self.filters.completed_to is not None
                and item.completed_at > self.filters.completed_to
            ):
                raise ValueError("run item must match completedTo filter")
            if self.filters.pinned is not None and item.pinned != self.filters.pinned:
                raise ValueError("run item must match pinned filter")
        _validate_bounded_page(self, self.items)
        return self


class BacktestFillPage(_BacktestApiInput):
    filters: BacktestFillFiltersView
    items: Annotated[tuple[BacktestFillView | BacktestLoopFillView, ...], Field(max_length=100)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: CursorToken | None
    has_more: bool = Field(strict=True)
    high_watermark: CursorToken

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        positions = tuple((item.filled_at, item.fill_id) for item in self.items)
        _require_ordered_unique_positions(positions, reverse=False, resource="fill")
        _validate_bounded_page(self, self.items)
        return self


class BacktestDetailPage(_BacktestApiInput):
    kind: BacktestPublicDetailKind
    availability: BacktestArtifactAvailability
    filters: BacktestDetailFiltersView
    items: Annotated[tuple[BacktestDetailView, ...], Field(max_length=100)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: CursorToken | None
    has_more: bool = Field(strict=True)
    high_watermark: CursorToken

    @field_validator("items", mode="before")
    @classmethod
    def require_item_array(cls, value: object) -> tuple[object, ...]:
        return _require_json_array(value, field_name="items")

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if self.kind != self.filters.kind:
            raise ValueError("detail kind must match normalized filters")
        if any(item.kind != self.kind for item in self.items):
            raise ValueError("detail item discriminator must match page kind")
        if self.availability == "AVAILABLE" and not self.items:
            raise ValueError("available detail page must contain an item")
        if self.availability != "AVAILABLE" and (
            self.items or self.next_cursor is not None or self.has_more
        ):
            raise ValueError("unavailable detail page must be empty and terminal")
        positions = tuple((item.event_at, item.detail_id) for item in self.items)
        _require_ordered_unique_positions(positions, reverse=False, resource="detail")
        _validate_bounded_page(self, self.items)
        return self


__all__ = [
    "MAX_INITIAL_LOTS",
    "MAX_SAFE_INTEGER",
    "BacktestArtifactAvailability",
    "BacktestAssumptionsView",
    "BacktestAuthoritativeDecisionView",
    "BacktestDataSyncCommand",
    "BacktestDataSyncJobResultView",
    "BacktestDecisionReferenceMarketView",
    "BacktestDecisionView",
    "BacktestDatasetCoverageView",
    "BacktestDatasetFiltersView",
    "BacktestDatasetPage",
    "BacktestDatasetScopeInput",
    "BacktestDatasetScopeView",
    "BacktestDatasetVerificationCommand",
    "BacktestDatasetVerificationJobResultView",
    "BacktestDatasetView",
    "BacktestDetailFiltersView",
    "BacktestDetailPage",
    "BacktestDetailView",
    "BacktestEquityPointView",
    "BacktestEquitySeries",
    "BacktestExecutionConfigInput",
    "BacktestExecutionConfigView",
    "BacktestExecutionOutcomeView",
    "BacktestFeeBreakdownView",
    "BacktestFillFiltersView",
    "BacktestFillPage",
    "BacktestFillView",
    "BacktestFormulaVersionsView",
    "BacktestInitialLotInput",
    "BacktestIndexConditionSummaryView",
    "BacktestJobFiltersView",
    "BacktestJobPage",
    "BacktestJobProgressView",
    "BacktestJobReceipt",
    "BacktestJobResultView",
    "BacktestJobView",
    "BacktestMarketIndexPointView",
    "BacktestMarketIndexSeriesView",
    "BacktestMetricsView",
    "BacktestResultAvailabilityView",
    "BacktestRunCommand",
    "BacktestRunCoverageView",
    "BacktestRunFiltersView",
    "BacktestRunJobResultView",
    "BacktestRunPage",
    "BacktestRunSummaryView",
    "BacktestRunView",
    "BacktestReferenceMarketBindingView",
    "BacktestReferenceMarketView",
    "BacktestSignalView",
    "DecimalText",
    "FenText",
    "JavaScriptSafeInteger",
    "PositiveJavaScriptSafeInteger",
    "Rfc4122Uuid",
    "Sha256Hex",
    "ShanghaiDatetime",
]
