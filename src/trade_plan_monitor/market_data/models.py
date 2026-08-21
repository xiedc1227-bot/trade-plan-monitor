"""Immutable normalized values at the external market-data boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


def _normalize_shanghai_timezone(value: datetime) -> datetime:
    timezone_info = value.tzinfo
    if isinstance(timezone_info, ZoneInfo) and timezone_info.key == _SHANGHAI_ZONE.key:
        return value
    canonical_value = value.replace(tzinfo=_SHANGHAI_ZONE)
    if value.utcoffset() != canonical_value.utcoffset():
        raise ValueError("timestamp timezone must be Asia/Shanghai")
    return canonical_value


AShareSymbol = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$"),
]
Exchange = Literal["SSE", "SZSE", "BSE"]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
NonNegativeShares = Annotated[int, Field(strict=True, ge=0)]
NonNegativeYuan = Annotated[
    Decimal,
    Field(strict=True, ge=Decimal("0"), allow_inf_nan=False),
]
StrictBoolean = Annotated[bool, Field(strict=True)]
StrictDate = Annotated[date, Field(strict=True)]
ShanghaiDatetime = Annotated[AwareDatetime, AfterValidator(_normalize_shanghai_timezone)]


class _MarketDataValue(BaseModel):
    """Keep normalized external values closed and immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy a normalized value while revalidating any public updates."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class _OhlcValue(_MarketDataValue):
    """Validate one positive integer-fen OHLC tuple."""

    open_fen: PositiveFen
    high_fen: PositiveFen
    low_fen: PositiveFen
    close_fen: PositiveFen

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        if self.low_fen > self.high_fen:
            raise ValueError("low_fen cannot exceed high_fen")
        if not self.low_fen <= self.open_fen <= self.high_fen:
            raise ValueError("open_fen must be between low_fen and high_fen")
        if not self.low_fen <= self.close_fen <= self.high_fen:
            raise ValueError("close_fen must be between low_fen and high_fen")
        return self


class ProviderCapabilityStatus(StrEnum):
    """One independently probed provider capability state."""

    UNVERIFIED = "UNVERIFIED"
    READY = "READY"
    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class ProviderCapabilities(_MarketDataValue):
    """Independent fail-closed states for the five provider data methods."""

    realtime_minutes: ProviderCapabilityStatus = ProviderCapabilityStatus.UNVERIFIED
    current_day_minutes: ProviderCapabilityStatus = ProviderCapabilityStatus.UNVERIFIED
    trading_calendar: ProviderCapabilityStatus = ProviderCapabilityStatus.UNVERIFIED
    daily_limits: ProviderCapabilityStatus = ProviderCapabilityStatus.UNVERIFIED
    daily_bars: ProviderCapabilityStatus = ProviderCapabilityStatus.UNVERIFIED


class MinuteBar(_OhlcValue):
    """One normalized completed minute in integer fen, shares, and yuan."""

    symbol: AShareSymbol
    bar_end: ShanghaiDatetime
    volume_shares: NonNegativeShares
    amount_yuan: NonNegativeYuan
    received_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_receipt_order(self) -> Self:
        if self.received_at < self.bar_end:
            raise ValueError("received_at cannot be before bar_end")
        return self


class TradingDay(_MarketDataValue):
    """One normalized A-share exchange-calendar row."""

    exchange: Exchange
    cal_date: StrictDate
    is_open: StrictBoolean
    previous_trade_date: StrictDate

    @model_validator(mode="after")
    def validate_previous_trade_date(self) -> Self:
        if self.previous_trade_date >= self.cal_date:
            raise ValueError("previous_trade_date must precede cal_date")
        return self


class DailyLimit(_MarketDataValue):
    """Actual provider-supplied daily limit prices in integer fen."""

    symbol: AShareSymbol
    trade_date: StrictDate
    up_limit_fen: PositiveFen
    down_limit_fen: PositiveFen
    received_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_daily_limit(self) -> Self:
        if self.down_limit_fen >= self.up_limit_fen:
            raise ValueError("down_limit_fen must be below up_limit_fen")
        if self.received_at.date() < self.trade_date:
            raise ValueError("received_at cannot precede trade_date")
        return self


class DailyBar(_OhlcValue):
    """One normalized provisional or official unadjusted daily bar."""

    symbol: AShareSymbol
    trade_date: StrictDate
    volume_shares: NonNegativeShares
    amount_yuan: NonNegativeYuan
    is_official: StrictBoolean
    received_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_receipt_date(self) -> Self:
        if self.received_at.date() < self.trade_date:
            raise ValueError("received_at cannot precede trade_date")
        return self


__all__ = [
    "AShareSymbol",
    "DailyBar",
    "DailyLimit",
    "Exchange",
    "MinuteBar",
    "ProviderCapabilities",
    "ProviderCapabilityStatus",
    "ShanghaiDatetime",
    "TradingDay",
]
