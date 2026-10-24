from decimal import Decimal
from itertools import product

import pytest
from tests.unit.test_market_regime import index_fixture

from trade_plan_monitor.market_data.daily_data import CertifiedDailyBar, DailySeries


def stock_fixture(days, cutoff, *, slope=2):
    return DailySeries(
        symbol="600000.SH",
        basis_id="frozen-qfq",
        provider="fixture",
        adjustment_as_of=days[-1],
        quote_comparable=True,
        session_dates=days,
        suspended_dates=(),
        cutoff=cutoff,
        bars=tuple(
            CertifiedDailyBar(
                bar_id=str(day),
                symbol="600000.SH",
                trade_date=day,
                open=Decimal(100 + i * slope),
                close=Decimal(100 + i * slope),
                high=Decimal(101 + i * slope),
                low=Decimal(99 + i * slope),
                volume_shares=1000,
                official=True,
                provider="fixture",
                basis_id="frozen-qfq",
                adjustment_as_of=days[-1],
                received_at=cutoff,
                available_at=cutoff,
            )
            for i, day in enumerate(days)
        ),
    )


def test_returns_endpoints_and_ma_are_independently_calculated():
    from trade_plan_monitor.decision.relative_strength import evaluate_relative_strength

    binding, days, bars, cutoff = index_fixture(21)
    result = evaluate_relative_strength(
        series=stock_fixture(days, cutoff),
        index_bars=bars,
        reference_market=binding,
        session_dates=days,
        decision_session=days[-1],
        cutoff=cutoff,
    )
    assert result.strength == "STRONG"
    assert result.stock_return20 == Decimal("0.4")
    assert result.index_return20 == Decimal("0.2")
    assert result.stock_ma20 == Decimal(121)
    assert result.endpoint_dates == (days[-21], days[-6], days[-1])


def test_equal_returns_are_not_strong():
    from trade_plan_monitor.decision.relative_strength import evaluate_relative_strength

    binding, days, bars, cutoff = index_fixture(21)
    result = evaluate_relative_strength(
        series=stock_fixture(days, cutoff, slope=1),
        index_bars=bars,
        reference_market=binding,
        session_dates=days,
        decision_session=days[-1],
        cutoff=cutoff,
    )
    assert result.strength == "NOT_STRONG"


@pytest.mark.parametrize("change", ["suspension", "missing_index", "missing_d", "basis"])
def test_required_alignment_cannot_be_shortened(change):
    from trade_plan_monitor.decision.relative_strength import evaluate_relative_strength

    binding, days, bars, cutoff = index_fixture(21)
    series = stock_fixture(days, cutoff)
    if change == "suspension":
        series = series.model_copy(
            update={"bars": series.bars[:5] + series.bars[6:], "suspended_dates": (days[5],)}
        )
    elif change == "missing_index":
        bars = bars[:5] + bars[6:]
    elif change == "missing_d":
        bars = bars[:-1]
    else:
        with pytest.raises(ValueError):
            series.model_copy(update={"basis_id": "other"})
        return
    result = evaluate_relative_strength(
        series=series,
        index_bars=bars,
        reference_market=binding,
        session_dates=days,
        decision_session=days[-1],
        cutoff=cutoff,
    )
    assert result.strength == "UNKNOWN"


def test_three_valued_strength_truth_table():
    from trade_plan_monitor.decision.relative_strength import strength_from_predicates

    for values in product(("SATISFIED", "UNSATISFIED", "MISSING_INPUT"), repeat=3):
        expected = (
            "NOT_STRONG"
            if "UNSATISFIED" in values
            else "UNKNOWN"
            if "MISSING_INPUT" in values
            else "STRONG"
        )
        assert strength_from_predicates(*values) == expected
