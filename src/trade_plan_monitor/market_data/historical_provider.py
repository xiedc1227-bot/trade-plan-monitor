"""Provider-neutral contracts for versioned historical minute acquisition."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    DailyBar,
    DailyLimit,
    MinuteBar,
    ShanghaiDatetime,
    TradingDay,
)
from trade_plan_monitor.market_data.sessions import DEFAULT_DATA_GRACE, expected_minute_ends


class HistoricalMinuteProfile(StrEnum):
    """Versioned, independently verified historical timestamp interpretation."""

    UNVERIFIED = "UNVERIFIED"
    TUSHARE_STK_MINS_241_END_V1 = "TUSHARE_STK_MINS_241_END_V1"


class HistoricalMinuteProfileUnverifiedError(ValueError):
    """Historical facts cannot be normalized under an unverified profile."""


class _HistoricalValue(BaseModel):
    """Closed immutable historical value with revalidated public copies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class HistoricalOpeningSpecial(_HistoricalValue):
    """The preserved non-strategy 09:30 source row for the verified v1 profile."""

    symbol: AShareSymbol
    source_time: ShanghaiDatetime
    open_fen: int = Field(strict=True, gt=0)
    high_fen: int = Field(strict=True, gt=0)
    low_fen: int = Field(strict=True, gt=0)
    close_fen: int = Field(strict=True, gt=0)
    volume_shares: int = Field(strict=True, ge=0)
    amount_yuan: Decimal = Field(strict=True, ge=Decimal("0"), allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        if self.low_fen > self.high_fen:
            raise ValueError("low_fen cannot exceed high_fen")
        if not self.low_fen <= self.open_fen <= self.high_fen:
            raise ValueError("open_fen must be between low_fen and high_fen")
        if not self.low_fen <= self.close_fen <= self.high_fen:
            raise ValueError("close_fen must be between low_fen and high_fen")
        return self


class HistoricalMinuteBatch(_HistoricalValue):
    """One completely validated source day plus its 240 executable minutes."""

    symbol: AShareSymbol
    trade_date: date = Field(strict=True)
    contract_version: HistoricalMinuteProfile
    bars: tuple[MinuteBar, ...] = Field(min_length=240, max_length=240)
    opening_special: HistoricalOpeningSpecial

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.contract_version is HistoricalMinuteProfile.UNVERIFIED:
            raise ValueError("contract_version must be verified")
        if self.contract_version is not HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1:
            raise ValueError("unsupported historical minute contract version")

        expected = expected_minute_ends(self.trade_date, is_open=True)
        if tuple(bar.bar_end for bar in self.bars) != expected:
            raise ValueError("bars must match the exact canonical minute-end set")
        for bar in self.bars:
            if bar.symbol != self.symbol:
                raise ValueError("bar symbol must match batch symbol")
            if bar.received_at != bar.bar_end + DEFAULT_DATA_GRACE:
                raise ValueError("historical minute receipt must use the deterministic grace")

        special = self.opening_special
        if special.symbol != self.symbol:
            raise ValueError("opening-special symbol must match batch symbol")
        if special.source_time != datetime.combine(
            self.trade_date,
            time(9, 30),
            special.source_time.tzinfo,
        ):
            raise ValueError("v1 opening-special row must use the verified 09:30 label")
        return self


class HistoricalMinuteProvider(Protocol):
    """Expose historical data without implementing any realtime operation."""

    def historical_minute_batch(
        self,
        symbol: str,
        trade_date: date,
    ) -> HistoricalMinuteBatch: ...

    def historical_minutes(self, symbol: str, trade_date: date) -> tuple[MinuteBar, ...]: ...

    def trading_calendar(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[TradingDay, ...]: ...

    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]: ...

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]: ...


__all__ = [
    "HistoricalMinuteBatch",
    "HistoricalMinuteProfile",
    "HistoricalMinuteProfileUnverifiedError",
    "HistoricalMinuteProvider",
    "HistoricalOpeningSpecial",
]
