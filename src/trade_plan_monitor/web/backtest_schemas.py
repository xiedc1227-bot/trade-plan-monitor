"""Strict backtest-only API input and exact-value schemas."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Self
from uuid import RFC_4122, UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.canonical import canonical_decimal
from trade_plan_monitor.backtest.time import (
    format_shanghai_datetime,
    parse_shanghai_datetime,
)

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_INITIAL_LOTS = 200
MAX_BACKTEST_YEARS = 5
MAX_WARMUP_YEARS = 2

_FEN_TEXT_PATTERN = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
_DECIMAL_TEXT_PATTERN = re.compile(r"^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$")
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _validate_fen_text(value: object) -> str:
    if type(value) is not str or _FEN_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("FenText must be one canonical signed base-10 integer string")
    return value


def _validate_decimal_text(value: object) -> Decimal:
    if type(value) is not str or _DECIMAL_TEXT_PATTERN.fullmatch(value) is None:
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
    return parse_shanghai_datetime(value)


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
    WithJsonSchema({"type": "string", "pattern": _FEN_TEXT_PATTERN.pattern}),
]
DecimalText = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal_text, json_schema_input_type=str),
    PlainSerializer(canonical_decimal, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": _DECIMAL_TEXT_PATTERN.pattern}),
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
        core_target_qty: int,
        tactical_target_qty: int,
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
        ):
            raise ValueError("position caps must be non-negative safe board-lot integers")
        if any(lot.acquired_trade_date > dataset_start for lot in self.initial_lots):
            raise ValueError("initial-lot acquired trade date cannot be after dataset start")
        core_qty = sum(lot.quantity for lot in self.initial_lots if lot.bucket == "CORE")
        tactical_qty = sum(lot.quantity for lot in self.initial_lots if lot.bucket == "TACTICAL")
        if core_qty > core_target_qty:
            raise ValueError("initial CORE quantity exceeds the reviewed plan cap")
        if tactical_qty > tactical_target_qty:
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
    schema_version: Literal["backtest-dataset-v1"]
    scope: BacktestDatasetScopeView
    coverage: BacktestDatasetCoverageView
    created_at: ShanghaiDatetime
    verified_at: ShanghaiDatetime


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
        if value is not None and any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("errorMessage must not contain control characters")
        return value

    @model_validator(mode="after")
    def validate_closed_job_union(self) -> Self:
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


__all__ = [
    "MAX_INITIAL_LOTS",
    "MAX_SAFE_INTEGER",
    "BacktestDataSyncCommand",
    "BacktestDataSyncJobResultView",
    "BacktestDatasetCoverageView",
    "BacktestDatasetFiltersView",
    "BacktestDatasetPage",
    "BacktestDatasetScopeInput",
    "BacktestDatasetScopeView",
    "BacktestDatasetVerificationCommand",
    "BacktestDatasetVerificationJobResultView",
    "BacktestDatasetView",
    "BacktestExecutionConfigInput",
    "BacktestInitialLotInput",
    "BacktestJobProgressView",
    "BacktestJobReceipt",
    "BacktestJobResultView",
    "BacktestJobView",
    "BacktestRunCommand",
    "BacktestRunJobResultView",
    "DecimalText",
    "FenText",
    "JavaScriptSafeInteger",
    "PositiveJavaScriptSafeInteger",
    "Rfc4122Uuid",
    "Sha256Hex",
    "ShanghaiDatetime",
]
