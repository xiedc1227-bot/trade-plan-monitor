"""Pure reusable board-index facts for live monitoring and replay."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
    market_index_bar_set_hash,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactRequest,
    MarketIndexFactUnit,
    MarketIndexIndicatorFact,
    MarketIndexInterval,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)

_CALCULATION_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _validated_series(
    bars: tuple[MarketIndexBar, ...],
    *,
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    input_cutoff: datetime,
) -> tuple[MarketIndexBar, ...]:
    if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
        raise TypeError("index bars must be an exact tuple")
    ordered = tuple(sorted(bars, key=lambda bar: bar.bar_at))
    identities = tuple(bar.bar_at for bar in ordered)
    if len(set(identities)) != len(identities):
        raise ValueError("DUPLICATE_IDENTITY")
    if any(bar.index_code is not index_code for bar in ordered):
        raise ValueError("INDEX_IDENTITY_MISMATCH")
    if any(bar.interval is not interval for bar in ordered):
        raise ValueError("INDEX_IDENTITY_MISMATCH")
    if any(bar.bar_at > input_cutoff for bar in ordered):
        raise ValueError("FUTURE_DATA")
    return ordered


def _mean(bars: tuple[MarketIndexBar, ...]) -> Decimal:
    with localcontext(_CALCULATION_CONTEXT):
        return sum((bar.close_points for bar in bars), Decimal(0)) / Decimal(len(bars))


def _return(bars: tuple[MarketIndexBar, ...]) -> Decimal:
    with localcontext(_CALCULATION_CONTEXT):
        return bars[-1].close_points / bars[0].close_points - Decimal(1)


def _require_history(
    bars: tuple[MarketIndexBar, ...],
    required: int,
) -> tuple[MarketIndexBar, ...]:
    if len(bars) < required:
        raise ValueError("INSUFFICIENT_HISTORY")
    return bars[-required:]


def calculate_requested_facts(
    *,
    index_code: MarketIndexCode,
    five_minute_bars: tuple[MarketIndexBar, ...],
    official_daily_bars: tuple[MarketIndexBar, ...],
    requests: tuple[MarketIndexFactRequest, ...],
    input_cutoff: datetime,
) -> tuple[MarketIndexIndicatorFact, ...]:
    """Calculate only the requested facts with exact bounded arithmetic."""

    if not isinstance(index_code, MarketIndexCode):
        raise TypeError("index_code must be a MarketIndexCode")
    if type(requests) is not tuple:
        raise TypeError("requests must be a tuple")
    five_minute = _validated_series(
        five_minute_bars,
        index_code=index_code,
        interval=MarketIndexInterval.FIVE_MINUTE,
        input_cutoff=input_cutoff,
    )
    daily = _validated_series(
        official_daily_bars,
        index_code=index_code,
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        input_cutoff=input_cutoff,
    )
    facts: list[MarketIndexIndicatorFact] = []
    for request in requests:
        if isinstance(request, SmaFactRequest):
            used = _require_history(daily, request.period)
            value = _mean(used)
            comparison = None
            unit = MarketIndexFactUnit.POINTS
        elif isinstance(request, SmaLookbackFactRequest):
            used = _require_history(daily, request.period + request.lookback)
            value = _mean(used[-request.period :])
            comparison = _mean(used[: request.period])
            unit = MarketIndexFactUnit.POINTS
        elif isinstance(request, ReturnFactRequest):
            source = five_minute if request.window is ReturnWindow.FIVE_MINUTE_BUCKETS else daily
            used = _require_history(source, request.window_size + 1)
            value = _return(used)
            comparison = None
            unit = MarketIndexFactUnit.RATIO
        else:  # pragma: no cover - closed request union
            raise TypeError("unsupported market-index fact request")
        facts.append(
            MarketIndexIndicatorFact(
                request=request,
                value=value,
                comparison_value=comparison,
                unit=unit,
                input_cutoff=input_cutoff,
                source_bar_hash=market_index_bar_set_hash(used),
                formula_definition_hash=FORMULA_DEFINITION_HASH,
            )
        )
    return tuple(facts)


__all__ = ["calculate_requested_facts"]
