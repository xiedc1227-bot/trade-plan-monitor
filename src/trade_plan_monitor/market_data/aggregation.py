"""Pure session-contained minute-bucket boundaries and completeness checks."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_data.models import AShareSymbol, MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_data.sessions import (
    SHANGHAI,
    TradingSession,
    _is_open_trading_date,
    _session_start,
    session_for_minute_end,
)

_ONE_MINUTE = timedelta(minutes=1)
_FIVE_MINUTES = 5
_MAX_EXACT_AMOUNT_DIGITS = 640
TA_FORMULA_VERSION = "ta-v1"

_PositiveFen = Annotated[int, Field(strict=True, gt=0)]
_NonNegativeShares = Annotated[int, Field(strict=True, ge=0)]
_NonNegativeYuan = Annotated[
    Decimal,
    Field(strict=True, ge=Decimal("0"), allow_inf_nan=False),
]


class FiveMinuteBar(BaseModel):
    """Immutable complete session-contained five-minute aggregate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: AShareSymbol
    bar_end: ShanghaiDatetime
    formula_version: Literal["ta-v1"] = TA_FORMULA_VERSION
    open_fen: _PositiveFen
    high_fen: _PositiveFen
    low_fen: _PositiveFen
    close_fen: _PositiveFen
    volume_shares: _NonNegativeShares
    amount_yuan: _NonNegativeYuan

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy while revalidating any public field updates."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        expected_five_minute_ends(self.bar_end)
        if self.low_fen > self.high_fen:
            raise ValueError("low_fen cannot exceed high_fen")
        if not self.low_fen <= self.open_fen <= self.high_fen:
            raise ValueError("open_fen must be between low_fen and high_fen")
        if not self.low_fen <= self.close_fen <= self.high_fen:
            raise ValueError("close_fen must be between low_fen and high_fen")
        return self


def _canonical_session_minute_end(value: datetime) -> tuple[datetime, TradingSession]:
    session = session_for_minute_end(value)
    if session is None:
        raise ValueError("minute end must be inside one monitoring session")
    return value.replace(tzinfo=SHANGHAI), session


def five_minute_bucket_end(minute_end: datetime) -> datetime:
    """Return the session-relative 5-minute bucket end for one minute."""

    canonical, session = _canonical_session_minute_end(minute_end)
    session_start = datetime.combine(canonical.date(), _session_start(session), SHANGHAI)
    elapsed_minutes = (canonical - session_start) // _ONE_MINUTE
    bucket_number = (elapsed_minutes + _FIVE_MINUTES - 1) // _FIVE_MINUTES
    return session_start + bucket_number * _FIVE_MINUTES * _ONE_MINUTE


def expected_five_minute_ends(bucket_end: datetime) -> tuple[datetime, ...]:
    """Return the five canonical minute ends required by one complete bucket."""

    canonical, session = _canonical_session_minute_end(bucket_end)
    if five_minute_bucket_end(canonical) != canonical:
        raise ValueError("bucket_end must be a five-minute boundary")

    expected = tuple(canonical - offset * _ONE_MINUTE for offset in range(4, -1, -1))
    if any(session_for_minute_end(item) is not session for item in expected):
        raise ValueError("five-minute bucket cannot cross a monitoring session")
    return expected


def is_complete_five_minute_bucket(
    minute_ends: tuple[datetime, ...],
    *,
    bucket_end: datetime,
    is_open: bool | None,
) -> bool:
    """Fail closed unless exactly the five expected session minutes are present."""

    expected = expected_five_minute_ends(bucket_end)
    if not _is_open_trading_date(expected[0].date(), is_open):
        return False
    if type(minute_ends) is not tuple or len(minute_ends) != _FIVE_MINUTES:
        return False
    try:
        if any(session_for_minute_end(item) is None for item in minute_ends):
            return False
    except TypeError, ValueError:
        return False
    return set(minute_ends) == set(expected)


def _sum_decimal_amounts_exact(values: tuple[Decimal, ...]) -> Decimal:
    """Add non-negative amounts exactly without ambient Decimal arithmetic."""

    nonzero = tuple(value for value in values if not value.is_zero())
    if not nonzero:
        return Decimal("0")

    minimum_exponent = min(int(value.as_tuple().exponent) for value in nonzero)
    total_coefficient = 0
    for value in nonzero:
        decimal_tuple = value.as_tuple()
        shift = int(decimal_tuple.exponent) - minimum_exponent
        if len(decimal_tuple.digits) + shift > _MAX_EXACT_AMOUNT_DIGITS:
            raise ValueError("amount sum exceeds the safe digit span")
        coefficient = 0
        for digit in decimal_tuple.digits:
            coefficient = coefficient * 10 + digit
        total_coefficient += coefficient * 10**shift

    if total_coefficient >= 10**_MAX_EXACT_AMOUNT_DIGITS:
        raise ValueError("amount sum exceeds the safe digit span")
    return Decimal(
        (
            0,
            tuple(int(digit) for digit in str(total_coefficient)),
            minimum_exponent,
        )
    )


def aggregate_five_minute_bar(
    minutes: tuple[MinuteBar, ...],
    *,
    bucket_end: datetime,
    is_open: bool | None,
) -> FiveMinuteBar | None:
    """Aggregate exactly one complete normalized bucket, otherwise fail closed."""

    if type(minutes) is not tuple or len(minutes) != _FIVE_MINUTES:
        return None
    if any(not isinstance(minute, MinuteBar) for minute in minutes):
        return None
    symbols = {minute.symbol for minute in minutes}
    if len(symbols) != 1:
        raise ValueError("five-minute input must contain one symbol")
    if not is_complete_five_minute_bucket(
        tuple(minute.bar_end for minute in minutes),
        bucket_end=bucket_end,
        is_open=is_open,
    ):
        return None

    ordered = tuple(sorted(minutes, key=lambda minute: minute.bar_end))
    return FiveMinuteBar(
        symbol=ordered[0].symbol,
        bar_end=ordered[-1].bar_end,
        open_fen=ordered[0].open_fen,
        high_fen=max(minute.high_fen for minute in ordered),
        low_fen=min(minute.low_fen for minute in ordered),
        close_fen=ordered[-1].close_fen,
        volume_shares=sum(minute.volume_shares for minute in ordered),
        amount_yuan=_sum_decimal_amounts_exact(tuple(minute.amount_yuan for minute in ordered)),
    )


__all__ = [
    "FiveMinuteBar",
    "TA_FORMULA_VERSION",
    "aggregate_five_minute_bar",
    "expected_five_minute_ends",
    "five_minute_bucket_end",
    "is_complete_five_minute_bucket",
]
