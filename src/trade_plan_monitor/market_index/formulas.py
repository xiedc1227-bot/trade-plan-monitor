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


def calculate_linked_index_facts(*, reference_market, bars, session_dates,
                               decision_session, evidence_cutoff):
    """Compute each dated operand only from its complete, cutoff-admitted window.

    The caller supplies the certified exchange calendar, including D. Future
    observations are never consumed; a late correction makes its window unknown.
    """
    from trade_plan_monitor.market_index.canonical import LINKED_INDEX_FORMULA_HASH
    from trade_plan_monitor.market_index.models import LinkedIndexFacts

    days = tuple(d for d in session_dates if d <= decision_session)
    if days != tuple(sorted(set(days))) or not days or days[-1] != decision_session:
        raise ValueError("LINKED_CALENDAR_UNVERIFIED")
    if evidence_cutoff.date() < decision_session:
        raise ValueError("LINKED_FUTURE_SESSION")
    relevant = tuple(b for b in bars if b.bar_at.date() in days[-60:])
    relevant = tuple(MarketIndexBar.model_validate(b.model_dump()) for b in relevant)
    if any(b.index_code != reference_market.index_code
           or b.interval != MarketIndexInterval.OFFICIAL_DAILY for b in relevant):
        raise ValueError("INDEX_IDENTITY_MISMATCH")
    by_day = {b.bar_at.date(): b for b in relevant}
    if len(by_day) != len(relevant):
        raise ValueError("DUPLICATE_IDENTITY")
    values, hashes, reasons = {}, [("formula", LINKED_INDEX_FORMULA_HASH)], []
    for name, count, offset in (("close", 1, 0), ("ma20", 20, 0), ("ma60", 60, 0),
                                ("ma20_5", 20, 5), ("low20", 20, 1)):
        wanted = days[len(days)-count-offset:len(days)-offset] if len(days) >= count+offset else ()
        used = tuple(by_day[d] for d in wanted if d in by_day
                     and by_day[d].observed_at <= evidence_cutoff)
        if len(used) != count:
            values[name] = None
            reasons.append(f"{name.upper()}_HISTORY_UNAVAILABLE")
            continue
        hashes.append((name, market_index_bar_set_hash(used)))
        values[name] = min(b.low_points for b in used) if name == "low20" else _mean(used)
    return LinkedIndexFacts(
        reference_market=reference_market,
        decision_session=decision_session,
        evidence_cutoff=evidence_cutoff,
        source_hashes=tuple(hashes),
        reasons=tuple(reasons),
        **values,
    )
