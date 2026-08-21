"""Immutable versioned technical-indicator calculations for normalized bars."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from itertools import pairwise
from typing import Annotated, Literal, Self

import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from trade_plan_monitor.market_data.aggregation import TA_FORMULA_VERSION, FiveMinuteBar
from trade_plan_monitor.market_data.models import AShareSymbol, DailyBar

_MAX_INDICATOR_BARS = 10_000
_RSI_ATR_PERIOD = 14
_BOLLINGER_MA_PERIOD = 20
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9

_FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
_RsiFloat = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class _IndicatorValue(BaseModel):
    """Closed immutable base that revalidates public copy updates."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

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


class IndicatorPoint(_IndicatorValue):
    """One immutable time-aligned `ta-v1` indicator snapshot."""

    bar_at: AwareDatetime | date
    ema10_yuan: _FiniteFloat
    ema12_yuan: _FiniteFloat
    ema26_yuan: _FiniteFloat
    macd_yuan: _FiniteFloat
    macd_signal_yuan: _FiniteFloat
    macd_histogram_yuan: _FiniteFloat
    boll_middle_yuan: _FiniteFloat | None = None
    boll_upper_yuan: _FiniteFloat | None = None
    boll_lower_yuan: _FiniteFloat | None = None
    rsi14: _RsiFloat | None = None
    atr14_yuan: _FiniteFloat | None = None
    ma20_yuan: _FiniteFloat | None = None
    ma50_yuan: _FiniteFloat | None = None
    ma200_yuan: _FiniteFloat | None = None


class IndicatorSeries(_IndicatorValue):
    """Closed immutable indicator series for one symbol and formula version."""

    formula_version: Literal["ta-v1"] = TA_FORMULA_VERSION
    symbol: AShareSymbol
    points: tuple[IndicatorPoint, ...] = Field(
        min_length=1,
        max_length=_MAX_INDICATOR_BARS,
    )


def calculate_ta_v1(
    bars: tuple[DailyBar | FiveMinuteBar, ...],
) -> IndicatorSeries:
    """Calculate pandas/Wilder `ta-v1` values in yuan for one ordered series."""

    normalized_bars, identities = _validate_bars(bars)
    close = pd.Series(
        [_fen_to_yuan(bar.close_fen) for bar in normalized_bars],
        dtype="float64",
    )
    high = pd.Series(
        [_fen_to_yuan(bar.high_fen) for bar in normalized_bars],
        dtype="float64",
    )
    low = pd.Series(
        [_fen_to_yuan(bar.low_fen) for bar in normalized_bars],
        dtype="float64",
    )

    ema10 = close.ewm(span=10, adjust=False).mean()
    ema12 = close.ewm(span=_MACD_FAST, adjust=False).mean()
    ema26 = close.ewm(span=_MACD_SLOW, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=_MACD_SIGNAL, adjust=False).mean()
    macd_histogram = macd - macd_signal

    ma20 = close.rolling(_BOLLINGER_MA_PERIOD).mean()
    bollinger_std = close.rolling(_BOLLINGER_MA_PERIOD).std(ddof=0)
    boll_upper = ma20 + 2 * bollinger_std
    boll_lower = ma20 - 2 * bollinger_std
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    rsi14 = _wilder_rsi(close)
    atr14 = _wilder_atr(high, low, close)

    points = tuple(
        IndicatorPoint(
            bar_at=identities[index],
            ema10_yuan=_required_float(ema10.iloc[index]),
            ema12_yuan=_required_float(ema12.iloc[index]),
            ema26_yuan=_required_float(ema26.iloc[index]),
            macd_yuan=_required_float(macd.iloc[index]),
            macd_signal_yuan=_required_float(macd_signal.iloc[index]),
            macd_histogram_yuan=_required_float(macd_histogram.iloc[index]),
            boll_middle_yuan=_optional_float(ma20.iloc[index]),
            boll_upper_yuan=_optional_float(boll_upper.iloc[index]),
            boll_lower_yuan=_optional_float(boll_lower.iloc[index]),
            rsi14=rsi14[index],
            atr14_yuan=atr14[index],
            ma20_yuan=_optional_float(ma20.iloc[index]),
            ma50_yuan=_optional_float(ma50.iloc[index]),
            ma200_yuan=_optional_float(ma200.iloc[index]),
        )
        for index in range(len(normalized_bars))
    )
    return IndicatorSeries(
        symbol=normalized_bars[0].symbol,
        points=points,
    )


def _validate_bars(
    bars: tuple[DailyBar | FiveMinuteBar, ...],
) -> tuple[tuple[DailyBar | FiveMinuteBar, ...], tuple[date | datetime, ...]]:
    if type(bars) is not tuple:
        raise TypeError("bars must be a tuple")
    if not bars:
        raise ValueError("bars must contain at least one value")
    if len(bars) > _MAX_INDICATOR_BARS:
        raise ValueError(f"bars must not exceed {_MAX_INDICATOR_BARS} values")

    bar_type = type(bars[0])
    if bar_type not in {DailyBar, FiveMinuteBar}:
        raise TypeError("bars must contain normalized market bars")
    if any(type(bar) is not bar_type for bar in bars):
        raise TypeError("bars must contain one bar type")
    if len({bar.symbol for bar in bars}) != 1:
        raise ValueError("bars must contain one symbol")

    if bar_type is DailyBar:
        identities: tuple[date | datetime, ...] = tuple(
            bar.trade_date for bar in bars if isinstance(bar, DailyBar)
        )
    else:
        identities = tuple(bar.bar_end for bar in bars if isinstance(bar, FiveMinuteBar))
    if any(current <= previous for previous, current in pairwise(identities)):
        raise ValueError("bar identities must be strictly increasing")
    return bars, identities


def _wilder_rsi(close: pd.Series) -> list[float | None]:
    count = len(close)
    result: list[float | None] = [None] * count
    if count <= _RSI_ATR_PERIOD:
        return result

    differences = close.diff()
    gains = differences.clip(lower=0)
    losses = (-differences).clip(lower=0)
    average_gain = float(gains.iloc[1 : _RSI_ATR_PERIOD + 1].sum()) / _RSI_ATR_PERIOD
    average_loss = float(losses.iloc[1 : _RSI_ATR_PERIOD + 1].sum()) / _RSI_ATR_PERIOD
    result[_RSI_ATR_PERIOD] = _rsi_value(average_gain, average_loss)

    for index in range(_RSI_ATR_PERIOD + 1, count):
        average_gain = (
            average_gain * (_RSI_ATR_PERIOD - 1) + float(gains.iloc[index])
        ) / _RSI_ATR_PERIOD
        average_loss = (
            average_loss * (_RSI_ATR_PERIOD - 1) + float(losses.iloc[index])
        ) / _RSI_ATR_PERIOD
        result[index] = _rsi_value(average_gain, average_loss)
    return result


def _rsi_value(average_gain: float, average_loss: float) -> float | None:
    if average_loss == 0:
        return 100.0 if average_gain > 0 else None
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _wilder_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> list[float | None]:
    count = len(close)
    result: list[float | None] = [None] * count
    if count < _RSI_ATR_PERIOD:
        return result

    true_ranges = [float(high.iloc[0] - low.iloc[0])]
    for index in range(1, count):
        true_ranges.append(
            max(
                float(high.iloc[index] - low.iloc[index]),
                abs(float(high.iloc[index] - close.iloc[index - 1])),
                abs(float(low.iloc[index] - close.iloc[index - 1])),
            )
        )
    average = sum(true_ranges[:_RSI_ATR_PERIOD]) / _RSI_ATR_PERIOD
    result[_RSI_ATR_PERIOD - 1] = average
    for index in range(_RSI_ATR_PERIOD, count):
        average = (average * (_RSI_ATR_PERIOD - 1) + true_ranges[index]) / _RSI_ATR_PERIOD
        result[index] = average
    return result


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return _required_float(value)


def _required_float(value: object) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("indicator result must be finite")
    return 0.0 if normalized == 0 else normalized


def _fen_to_yuan(value: int) -> float:
    try:
        normalized = value / 100
    except OverflowError:
        raise ValueError("price must fit the finite float range") from None
    if not math.isfinite(normalized):
        raise ValueError("price must fit the finite float range")
    return normalized


__all__ = [
    "IndicatorPoint",
    "IndicatorSeries",
    "TA_FORMULA_VERSION",
    "calculate_ta_v1",
]
