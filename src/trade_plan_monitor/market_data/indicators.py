"""Immutable versioned technical-indicator calculations for normalized bars."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
from typing import Annotated, Literal, Self
from weakref import WeakSet

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


_DAILY_TA_V1_PREFIX_PROOF = object()


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class _DailyTaV1Prefix:
    bars: tuple[DailyBar, ...]
    series: IndicatorSeries
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._proof is not _DAILY_TA_V1_PREFIX_PROOF:
            raise TypeError("daily indicator prefixes must be created by this module")


_ISSUED_DAILY_TA_V1_PREFIXES: WeakSet[_DailyTaV1Prefix] = WeakSet()


def calculate_ta_v1(
    bars: tuple[DailyBar | FiveMinuteBar, ...],
) -> IndicatorSeries:
    """Calculate pandas/Wilder `ta-v1` values in yuan for one ordered series."""

    normalized_bars, identities = _validate_bars(bars)
    return _calculate_ta_v1_series(normalized_bars, identities, point_prefix=())


def _calculate_daily_ta_v1_prefix(
    bars: tuple[DailyBar, ...],
) -> _DailyTaV1Prefix:
    """Create an immutable proof-bound daily indicator prefix."""

    normalized_bars, identities = _validate_bars(bars)
    if type(normalized_bars[0]) is not DailyBar:
        raise TypeError("daily indicator prefixes require DailyBar values")
    daily_bars = tuple(bar for bar in normalized_bars if type(bar) is DailyBar)
    series = _calculate_ta_v1_series(daily_bars, identities, point_prefix=())
    prefix = _DailyTaV1Prefix(
        bars=daily_bars,
        series=series,
        _proof=_DAILY_TA_V1_PREFIX_PROOF,
    )
    _ISSUED_DAILY_TA_V1_PREFIXES.add(prefix)
    return prefix


def _calculate_daily_ta_v1_from_prefix(
    bars: tuple[DailyBar, ...],
    prefix: _DailyTaV1Prefix,
) -> IndicatorSeries:
    """Append one derived point while preserving an exact validated indicator prefix."""

    normalized_bars, identities = _validate_bars(bars)
    if type(normalized_bars[0]) is not DailyBar:
        raise TypeError("daily indicator prefixes require DailyBar values")
    if type(prefix) is not _DailyTaV1Prefix:
        raise TypeError("prefix must be a daily ta-v1 prefix")
    if prefix not in _ISSUED_DAILY_TA_V1_PREFIXES:
        raise ValueError("prefix was not issued by the daily ta-v1 calculator")
    if len(prefix.bars) + 1 != len(normalized_bars):
        raise ValueError("prefix must cover every bar except the appended value")
    if any(
        current is not expected
        for current, expected in zip(normalized_bars[:-1], prefix.bars, strict=True)
    ):
        raise ValueError("prefix bars must be the exact immutable indicator input")
    if (
        prefix.series.formula_version != TA_FORMULA_VERSION
        or prefix.series.symbol != normalized_bars[0].symbol
    ):
        raise ValueError("prefix identity must match the indicator series")
    if tuple(point.bar_at for point in prefix.series.points) != identities[:-1]:
        raise ValueError("prefix bar identities must match the indicator input")
    return _calculate_ta_v1_series(
        normalized_bars,
        identities,
        point_prefix=prefix.series.points,
    )


def _calculate_ta_v1_series(
    normalized_bars: tuple[DailyBar | FiveMinuteBar, ...],
    identities: tuple[date | datetime, ...],
    *,
    point_prefix: tuple[IndicatorPoint, ...],
) -> IndicatorSeries:
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
    ema10_values = ema10.to_numpy(copy=False)
    ema12_values = ema12.to_numpy(copy=False)
    ema26_values = ema26.to_numpy(copy=False)
    macd_values = macd.to_numpy(copy=False)
    macd_signal_values = macd_signal.to_numpy(copy=False)
    macd_histogram_values = macd_histogram.to_numpy(copy=False)
    ma20_values = ma20.to_numpy(copy=False)
    boll_upper_values = boll_upper.to_numpy(copy=False)
    boll_lower_values = boll_lower.to_numpy(copy=False)
    ma50_values = ma50.to_numpy(copy=False)
    ma200_values = ma200.to_numpy(copy=False)

    point_values = tuple(
        {
            "bar_at": identities[index],
            "ema10_yuan": _required_float(ema10_values[index]),
            "ema12_yuan": _required_float(ema12_values[index]),
            "ema26_yuan": _required_float(ema26_values[index]),
            "macd_yuan": _required_float(macd_values[index]),
            "macd_signal_yuan": _required_float(macd_signal_values[index]),
            "macd_histogram_yuan": _required_float(macd_histogram_values[index]),
            "boll_middle_yuan": _optional_float(ma20_values[index]),
            "boll_upper_yuan": _optional_float(boll_upper_values[index]),
            "boll_lower_yuan": _optional_float(boll_lower_values[index]),
            "rsi14": rsi14[index],
            "atr14_yuan": atr14[index],
            "ma20_yuan": _optional_float(ma20_values[index]),
            "ma50_yuan": _optional_float(ma50_values[index]),
            "ma200_yuan": _optional_float(ma200_values[index]),
        }
        for index in range(len(point_prefix), len(normalized_bars))
    )
    return IndicatorSeries(
        symbol=normalized_bars[0].symbol,
        points=(*point_prefix, *point_values),
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

    values = close.to_numpy(copy=False)
    differences = [float(values[index] - values[index - 1]) for index in range(1, count)]
    gains = [max(value, 0.0) for value in differences]
    losses = [max(-value, 0.0) for value in differences]
    average_gain = sum(gains[:_RSI_ATR_PERIOD]) / _RSI_ATR_PERIOD
    average_loss = sum(losses[:_RSI_ATR_PERIOD]) / _RSI_ATR_PERIOD
    result[_RSI_ATR_PERIOD] = _rsi_value(average_gain, average_loss)

    for index in range(_RSI_ATR_PERIOD + 1, count):
        average_gain = (average_gain * (_RSI_ATR_PERIOD - 1) + gains[index - 1]) / _RSI_ATR_PERIOD
        average_loss = (average_loss * (_RSI_ATR_PERIOD - 1) + losses[index - 1]) / _RSI_ATR_PERIOD
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

    high_values = high.to_numpy(copy=False)
    low_values = low.to_numpy(copy=False)
    close_values = close.to_numpy(copy=False)
    true_ranges = [float(high_values[0] - low_values[0])]
    for index in range(1, count):
        true_ranges.append(
            max(
                float(high_values[index] - low_values[index]),
                abs(float(high_values[index] - close_values[index - 1])),
                abs(float(low_values[index] - close_values[index - 1])),
            )
        )
    average = sum(true_ranges[:_RSI_ATR_PERIOD]) / _RSI_ATR_PERIOD
    result[_RSI_ATR_PERIOD - 1] = average
    for index in range(_RSI_ATR_PERIOD, count):
        average = (average * (_RSI_ATR_PERIOD - 1) + true_ranges[index]) / _RSI_ATR_PERIOD
        result[index] = average
    return result


def _optional_float(value: object) -> float | None:
    normalized = float(value)
    if math.isnan(normalized):
        return None
    return _finite_float(normalized)


def _required_float(value: object) -> float:
    return _finite_float(float(value))


def _finite_float(normalized: float) -> float:
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
