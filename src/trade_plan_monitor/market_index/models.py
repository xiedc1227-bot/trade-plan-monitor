"""Immutable board-index bars, fact requests, facts, health, and snapshots."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    Board,
    MarketIndexCode,
)

PositivePoints = Annotated[Decimal, Field(strict=True, gt=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(strict=True, ge=0, allow_inf_nan=False)]
FiniteDecimal = Annotated[Decimal, Field(strict=True, allow_inf_nan=False)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SmaPeriod = Annotated[int, Field(strict=True, ge=2, le=250)]
SmaLookback = Annotated[int, Field(strict=True, ge=1, le=60)]
ReturnWindowSize = Annotated[int, Field(strict=True, ge=1, le=250)]
_MAX_CANONICAL_DECIMAL_CHARACTERS = 10_000


class MarketIndexInterval(StrEnum):
    FIVE_MINUTE = "FIVE_MINUTE"
    OFFICIAL_DAILY = "OFFICIAL_DAILY"


class MarketIndexSourceKind(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"


class MarketIndexHealth(StrEnum):
    LIVE = "LIVE"
    STALE = "STALE"
    GAPPED = "GAPPED"
    BLOCKED = "BLOCKED"


class MarketIndexIssueCode(StrEnum):
    MISSING_FIVE_MINUTE_BAR = "MISSING_FIVE_MINUTE_BAR"
    MISSING_OFFICIAL_DAILY_BAR = "MISSING_OFFICIAL_DAILY_BAR"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE_DATA = "STALE_DATA"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    GAPPED_SERIES = "GAPPED_SERIES"
    INDEX_IDENTITY_MISMATCH = "INDEX_IDENTITY_MISMATCH"
    FUTURE_DATA = "FUTURE_DATA"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    NONCANONICAL_DECIMAL = "NONCANONICAL_DECIMAL"
    INVALID_OHLC = "INVALID_OHLC"
    FORMULA_MISMATCH = "FORMULA_MISMATCH"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class MarketIndexFactUnit(StrEnum):
    POINTS = "POINTS"
    RATIO = "RATIO"


class ReturnWindow(StrEnum):
    FIVE_MINUTE_BUCKETS = "FIVE_MINUTE_BUCKETS"
    OFFICIAL_OPEN_DAYS = "OFFICIAL_OPEN_DAYS"


class _IndexValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_shanghai_datetime(value: datetime, *, field_name: str) -> None:
    if value.utcoffset() != timedelta(hours=8):
        raise ValueError(f"{field_name} must use the Asia/Shanghai offset")


def _validate_decimal_expansion(value: Decimal) -> None:
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("canonical decimals must be finite")
    if not any(digits):
        return
    coefficient_length = len(digits)
    if exponent >= 0:
        expanded_length = coefficient_length + exponent
    else:
        decimal_position = coefficient_length + exponent
        expanded_length = coefficient_length + 1 if decimal_position > 0 else 2 - decimal_position
    if expanded_length + int(bool(sign)) > _MAX_CANONICAL_DECIMAL_CHARACTERS:
        raise ValueError("canonical decimal expansion is too large")


class MarketIndexBar(_IndexValue):
    """One validated, index-specific completed OHLC observation."""

    index_code: MarketIndexCode
    interval: MarketIndexInterval
    bar_at: AwareDatetime
    open_points: PositivePoints
    high_points: PositivePoints
    low_points: PositivePoints
    close_points: PositivePoints
    volume: NonNegativeDecimal | None = None
    amount: NonNegativeDecimal | None = None
    observed_at: AwareDatetime
    source_kind: MarketIndexSourceKind
    provider_revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]

    @model_validator(mode="after")
    def validate_bar(self) -> Self:
        _validate_shanghai_datetime(self.bar_at, field_name="bar_at")
        _validate_shanghai_datetime(self.observed_at, field_name="observed_at")
        for value in (
            self.open_points,
            self.high_points,
            self.low_points,
            self.close_points,
            self.volume,
            self.amount,
        ):
            if value is not None:
                _validate_decimal_expansion(value)
        if self.bar_at.second or self.bar_at.microsecond:
            raise ValueError("index bar identity must be an exact minute")
        if self.observed_at < self.bar_at:
            raise ValueError("observed_at cannot precede bar_at")
        if self.interval is MarketIndexInterval.OFFICIAL_DAILY:
            if self.bar_at.timetz().replace(tzinfo=None) != time(15, 0):
                raise ValueError("official daily index bar must use the canonical 15:00 cutoff")
            if self.source_kind is not MarketIndexSourceKind.OFFICIAL:
                raise ValueError("official daily index bar requires OFFICIAL source")
        else:
            minute_number = self.bar_at.hour * 60 + self.bar_at.minute
            is_morning = 9 * 60 + 35 <= minute_number <= 11 * 60 + 30
            is_afternoon = 13 * 60 + 5 <= minute_number <= 15 * 60
            if self.bar_at.minute % 5 or not (is_morning or is_afternoon):
                raise ValueError(
                    "index five-minute bar must end on a completed five-minute boundary"
                )
        if self.high_points < max(self.open_points, self.close_points):
            raise ValueError("index OHLC high is below open or close")
        if self.low_points > min(self.open_points, self.close_points):
            raise ValueError("index OHLC low is above open or close")
        if self.low_points > self.high_points:
            raise ValueError("index OHLC low cannot exceed high")
        return self


class SmaFactRequest(_IndexValue):
    formula_id: Literal["SMA"] = "SMA"
    period: SmaPeriod


class SmaLookbackFactRequest(_IndexValue):
    formula_id: Literal["SMA_LOOKBACK"] = "SMA_LOOKBACK"
    period: SmaPeriod
    lookback: SmaLookback


class ReturnFactRequest(_IndexValue):
    formula_id: Literal["RETURN"] = "RETURN"
    window: ReturnWindow
    window_size: ReturnWindowSize


MarketIndexFactRequest = Annotated[
    SmaFactRequest | SmaLookbackFactRequest | ReturnFactRequest,
    Field(discriminator="formula_id"),
]


class MarketIndexIndicatorFact(_IndexValue):
    """One deterministic reusable fact with exact input identity."""

    request: MarketIndexFactRequest
    value: FiniteDecimal
    comparison_value: FiniteDecimal | None = None
    unit: MarketIndexFactUnit
    input_cutoff: AwareDatetime
    source_bar_hash: Sha256Hex
    formula_definition_hash: Sha256Hex
    health: Literal[MarketIndexHealth.LIVE] = MarketIndexHealth.LIVE

    @model_validator(mode="after")
    def validate_fact(self) -> Self:
        _validate_shanghai_datetime(self.input_cutoff, field_name="input_cutoff")
        _validate_decimal_expansion(self.value)
        if self.comparison_value is not None:
            _validate_decimal_expansion(self.comparison_value)
        if isinstance(self.request, SmaLookbackFactRequest):
            if self.comparison_value is None:
                raise ValueError("SMA_LOOKBACK fact requires its comparison value")
        elif self.comparison_value is not None:
            raise ValueError("only SMA_LOOKBACK fact has a comparison value")
        expected_unit = (
            MarketIndexFactUnit.RATIO
            if isinstance(self.request, ReturnFactRequest)
            else MarketIndexFactUnit.POINTS
        )
        if self.unit is not expected_unit:
            raise ValueError("market-index fact unit does not match its formula")
        return self


class MarketIndexSnapshotCacheKey(_IndexValue):
    """The complete immutable cache identity of a published snapshot."""

    mapping_version: Literal["board-index-map-v1"] = MAPPING_VERSION
    index_code: MarketIndexCode
    decision_cutoff: AwareDatetime
    request_set_hash: Sha256Hex
    provider_content_revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]

    @model_validator(mode="after")
    def validate_cutoff(self) -> Self:
        _validate_shanghai_datetime(self.decision_cutoff, field_name="decision_cutoff")
        return self


class MarketIndexSnapshot(_IndexValue):
    """One plan-neutral, immutable shared board-index data snapshot."""

    index_code: MarketIndexCode
    display_name: Annotated[str, Field(min_length=1, max_length=32)]
    board: Board
    decision_cutoff: AwareDatetime
    latest_completed_five_minute: MarketIndexBar | None = None
    five_minute_bars: tuple[MarketIndexBar, ...] = ()
    official_daily_bars: tuple[MarketIndexBar, ...] = ()
    prior_official_close_points: PositivePoints | None = None
    fact_requests: tuple[MarketIndexFactRequest, ...] = ()
    indicator_facts: tuple[MarketIndexIndicatorFact, ...] = ()
    health: MarketIndexHealth
    issues: tuple[MarketIndexIssueCode, ...] = ()
    completed_bucket_at: AwareDatetime | None = None
    observed_at: AwareDatetime
    mapping_version: Literal["board-index-map-v1"] = MAPPING_VERSION
    revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
    bar_set_hash: Sha256Hex
    request_set_hash: Sha256Hex
    formula_definition_hash: Sha256Hex
    snapshot_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _validate_shanghai_datetime(self.decision_cutoff, field_name="decision_cutoff")
        _validate_shanghai_datetime(self.observed_at, field_name="observed_at")
        if self.completed_bucket_at is not None:
            _validate_shanghai_datetime(
                self.completed_bucket_at,
                field_name="completed_bucket_at",
            )
        if tuple(dict.fromkeys(self.issues)) != self.issues:
            raise ValueError("market-index issues must be ordered and unique")
        if len(set(self.fact_requests)) != len(self.fact_requests):
            raise ValueError("market-index fact requests must be unique")
        if self.health is MarketIndexHealth.LIVE:
            if self.issues:
                raise ValueError("LIVE market-index snapshot cannot contain issues")
            if self.latest_completed_five_minute is None:
                raise ValueError("LIVE market-index snapshot requires a completed five-minute bar")
            if self.prior_official_close_points is None:
                raise ValueError("LIVE market-index snapshot requires a prior official close")
            if self.completed_bucket_at != self.latest_completed_five_minute.bar_at:
                raise ValueError("completed bucket does not match latest five-minute bar")
            if tuple(fact.request for fact in self.indicator_facts) != self.fact_requests:
                raise ValueError("LIVE snapshot facts must match every requested fact in order")
        elif not self.issues:
            raise ValueError("non-LIVE market-index snapshot requires an issue")
        return self

    @property
    def cache_key(self) -> MarketIndexSnapshotCacheKey:
        return MarketIndexSnapshotCacheKey(
            index_code=self.index_code,
            decision_cutoff=self.decision_cutoff,
            request_set_hash=self.request_set_hash,
            provider_content_revision=self.revision,
        )


__all__ = [
    "FiniteDecimal",
    "MarketIndexBar",
    "MarketIndexFactRequest",
    "MarketIndexFactUnit",
    "MarketIndexHealth",
    "MarketIndexIndicatorFact",
    "MarketIndexInterval",
    "MarketIndexIssueCode",
    "MarketIndexSnapshot",
    "MarketIndexSnapshotCacheKey",
    "MarketIndexSourceKind",
    "ReturnFactRequest",
    "ReturnWindow",
    "SmaFactRequest",
    "SmaLookbackFactRequest",
]
