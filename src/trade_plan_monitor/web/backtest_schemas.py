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


__all__ = [
    "MAX_INITIAL_LOTS",
    "MAX_SAFE_INTEGER",
    "BacktestDataSyncCommand",
    "BacktestDatasetScopeInput",
    "BacktestDatasetVerificationCommand",
    "BacktestExecutionConfigInput",
    "BacktestInitialLotInput",
    "BacktestRunCommand",
    "DecimalText",
    "FenText",
    "JavaScriptSafeInteger",
    "PositiveJavaScriptSafeInteger",
    "Rfc4122Uuid",
    "Sha256Hex",
    "ShanghaiDatetime",
]
