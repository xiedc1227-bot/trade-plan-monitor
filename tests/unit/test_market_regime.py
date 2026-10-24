from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.market_index.identity import resolve_board_reference
from trade_plan_monitor.market_index.models import MarketIndexBar

TZ = ZoneInfo("Asia/Shanghai")


def index_fixture(count=60):
    days = tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(count))
    binding = resolve_board_reference("600000.SH").binding
    bars = tuple(
        MarketIndexBar(
            index_code=binding.index_code,
            interval="OFFICIAL_DAILY",
            bar_at=datetime.combine(day, time(15), TZ),
            observed_at=datetime.combine(day, time(16), TZ),
            open_points=Decimal(100 + i),
            close_points=Decimal(100 + i),
            high_points=Decimal(101 + i),
            low_points=Decimal(99 + i),
            source_kind="OFFICIAL",
            provider_revision=1,
        )
        for i, day in enumerate(days)
    )
    return binding, days, bars, datetime.combine(days[-1], time(17), TZ)


def test_dated_operands_use_exact_windows_and_new_formula_identity():
    from trade_plan_monitor.market_index.formulas import calculate_linked_index_facts

    binding, days, bars, cutoff = index_fixture()
    facts = calculate_linked_index_facts(
        reference_market=binding,
        bars=bars,
        session_dates=days,
        decision_session=days[-1],
        evidence_cutoff=cutoff,
    )
    assert (facts.close, facts.ma20, facts.ma60, facts.ma20_5, facts.low20) == (
        Decimal(159),
        Decimal("149.5"),
        Decimal("129.5"),
        Decimal("144.5"),
        Decimal(138),
    )
    changed = bars[:-1] + (bars[-1].model_copy(update={"low_points": Decimal(1)}),)
    other = calculate_linked_index_facts(
        reference_market=binding,
        bars=changed,
        session_dates=days,
        decision_session=days[-1],
        evidence_cutoff=cutoff,
    )
    assert other.low20 == facts.low20
    assert other.formula_version == "market-linkage-index-v1"


@pytest.mark.parametrize("change", ["missing_d", "gap", "future_revision", "short"])
def test_unavailable_index_observations_never_become_complete(change):
    from trade_plan_monitor.market_index.formulas import calculate_linked_index_facts

    binding, days, bars, cutoff = index_fixture()
    if change == "missing_d":
        bars = bars[:-1]
    elif change == "gap":
        bars = bars[:-10] + bars[-9:]
    elif change == "future_revision":
        bars = bars[:-1] + (
            bars[-1].model_copy(update={"observed_at": cutoff + timedelta(days=1)}),
        )
    else:
        bars = bars[1:]
    facts = calculate_linked_index_facts(
        reference_market=binding,
        bars=bars,
        session_dates=days,
        decision_session=days[-1],
        evidence_cutoff=cutoff,
    )
    assert facts.ma60 is None
    assert facts.reasons


@pytest.mark.parametrize(
    "values,expected",
    [
        ((90, 100, 100, 110, 95), "BROKEN"),
        ((95, 100, 90, 110, 95), "WEAK"),
        ((100, 100, 90, 110, 95), "NORMAL_TRANSITION"),
        ((95, 100, 90, 100, 95), "NORMAL_TRANSITION"),
        ((90, 100, None, 110, 95), "UNKNOWN"),
        ((90, None, 100, None, 95), "BROKEN"),
        ((100, 100, None, None, 95), "NORMAL_TRANSITION"),
    ],
)
def test_priority_strict_equality_and_decisive_unknowns(values, expected):
    from trade_plan_monitor.decision.market_regime import classify_market_regime
    from trade_plan_monitor.market_index.models import LinkedIndexFacts

    binding, days, _, cutoff = index_fixture()
    facts = LinkedIndexFacts(
        reference_market=binding,
        decision_session=days[-1],
        evidence_cutoff=cutoff,
        **dict(
            zip(
                ("close", "ma20", "ma60", "ma20_5", "low20"),
                (None if v is None else Decimal(v) for v in values),
                strict=True,
            )
        ),
    )
    assert classify_market_regime(facts).regime == expected
