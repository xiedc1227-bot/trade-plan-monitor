"""Aligned exchange-session strength without interpolating suspended observations."""

from datetime import date
from decimal import Context, Decimal, localcontext
from typing import Literal

from pydantic import AwareDatetime

from trade_plan_monitor.decision.market_regime import Truth, all_truth, predicate
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.market_data.daily_data import DailySeries
from trade_plan_monitor.market_index.canonical import market_index_bar_set_hash
from trade_plan_monitor.market_index.models import MarketIndexBar


def strength_from_predicates(*values: Truth):
    return {"SATISFIED": "STRONG", "UNSATISFIED": "NOT_STRONG", "MISSING_INPUT": "UNKNOWN"}[
        all_truth(*values)
    ]


class RelativeStrengthEvidence(DailyValue):
    formula_version: Literal["market-linkage-strength-v1"] = "market-linkage-strength-v1"
    strength: Literal["STRONG", "NOT_STRONG", "UNKNOWN"]
    decision_session: date
    cutoff: AwareDatetime
    endpoint_dates: tuple[date, ...] = ()
    stock_endpoints: tuple[Decimal, ...] = ()
    index_endpoints: tuple[Decimal, ...] = ()
    stock_return5: Decimal | None = None
    stock_return20: Decimal | None = None
    index_return5: Decimal | None = None
    index_return20: Decimal | None = None
    difference5: Decimal | None = None
    difference20: Decimal | None = None
    stock_close: Decimal | None = None
    stock_ma20: Decimal | None = None
    outperform5: Truth = "MISSING_INPUT"
    outperform20: Truth = "MISSING_INPUT"
    above_ma20: Truth = "MISSING_INPUT"
    basis_id: str | None = None
    stock_provider: str | None = None
    source_hashes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def evaluate_relative_strength(
    *, series, index_bars, reference_market, session_dates, decision_session, cutoff
):
    base = dict(decision_session=decision_session, cutoff=cutoff)
    days = tuple(d for d in session_dates if d <= decision_session)
    if days != tuple(sorted(set(days))) or len(days) < 21 or days[-1] != decision_session:
        return RelativeStrengthEvidence(
            **base, strength="UNKNOWN", reasons=("ALIGNED_HISTORY_REQUIRED",)
        )
    wanted = days[-21:]
    if series is None:
        return RelativeStrengthEvidence(
            **base, strength="UNKNOWN", reasons=("PRICE_BASIS_UNVERIFIED",)
        )
    series = DailySeries.model_validate(series.model_dump())
    stock = tuple(b for b in series.bars if b.trade_date in wanted and b.received_at <= cutoff)
    index = tuple(
        sorted(
            (
                MarketIndexBar.model_validate(b.model_dump())
                for b in index_bars
                if b.bar_at.date() in wanted and b.observed_at <= cutoff
            ),
            key=lambda b: b.bar_at,
        )
    )
    stock_ok = (
        tuple(b.trade_date for b in stock) == wanted and series.adjustment_as_of <= cutoff.date()
    )
    index_ok = tuple(b.bar_at.date() for b in index) == wanted and all(
        b.index_code == reference_market.index_code and b.interval == "OFFICIAL_DAILY"
        for b in index
    )
    values = dict(
        basis_id=series.basis_id,
        stock_provider=series.provider,
        endpoint_dates=(wanted[0], wanted[-6], wanted[-1]),
    )
    # Return comparisons require both complete aligned windows. The MA
    # predicate can still establish a definite NOT_STRONG independently.
    with localcontext(Context(prec=50)):
        if stock_ok:
            values.update(
                stock_close=stock[-1].close,
                stock_ma20=sum(b.close for b in stock[-20:]) / Decimal(20),
                stock_endpoints=tuple(stock[i].close for i in (0, -6, -1)),
            )
            values["above_ma20"] = predicate(
                values["stock_ma20"], values["stock_close"], inclusive=True
            )
        if stock_ok and index_ok:
            values["index_endpoints"] = tuple(index[i].close_points for i in (0, -6, -1))
            for n in (5, 20):
                sr = stock[-1].close / stock[-n - 1].close - 1
                ir = index[-1].close_points / index[-n - 1].close_points - 1
                values.update(
                    {
                        f"stock_return{n}": sr,
                        f"index_return{n}": ir,
                        f"difference{n}": sr - ir,
                        f"outperform{n}": predicate(ir, sr),
                    }
                )
    predicates = tuple(
        values.get(k, "MISSING_INPUT") for k in ("outperform5", "outperform20", "above_ma20")
    )
    hashes = tuple(b.bar_id for b in stock) if stock_ok else ()
    if index_ok:
        hashes += (market_index_bar_set_hash(index),)
    return RelativeStrengthEvidence(
        **base,
        **values,
        strength=strength_from_predicates(*predicates),
        source_hashes=hashes,
        reasons=() if stock_ok and index_ok else ("ALIGNED_HISTORY_REQUIRED",),
    )
