"""Six actual evidence routes share exactly the same live/replay policy output."""

from decimal import Decimal

import pytest
from tests.integration.test_market_linkage_runtime import index_snapshot
from tests.unit.test_market_linkage_contract import linked_payload
from tests.unit.test_relative_strength import stock_fixture

from trade_plan_monitor.backtest.market_linkage_input import LinkedIndexReplaySource
from trade_plan_monitor.decision.market_linkage import evaluate_market_linkage
from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan


@pytest.mark.parametrize("regime,q0,strong,group,blocker,candidate", [
    ("NORMAL_TRANSITION", 300, True, "S0", None, 300),
    ("WEAK", 300, True, "S1", None, 100),
    ("WEAK", 100, True, "S1", "P1_EXCEPTION_REQUIRED", None),
    ("BROKEN", 300, False, None, "MARKET_BROKEN", None),
    ("BROKEN", 300, True, "S2", "P1_EXCEPTION_REQUIRED", None),
    ("UNKNOWN", 300, True, None, "MARKET_INPUT_UNKNOWN", None),
])
def test_six_real_evidence_routes_match_frozen_replay(
    regime, q0, strong, group, blocker, candidate,
):
    raw = linked_payload()
    raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = q0
    plan = MarketLinkedTradePlan.model_validate(raw)
    snapshot, days = index_snapshot(plan)
    bars = snapshot.official_daily_bars
    if regime in {"WEAK", "BROKEN"}:
        bars = tuple(bar.model_copy(update={
            "open_points": Decimal(200-i), "close_points": Decimal(200-i),
            "high_points": Decimal(201-i), "low_points": Decimal(199-i),
        }) for i, bar in enumerate(bars))
        # D must be strictly below the previous low to qualify as BROKEN.
        bars = (*bars[:-1], bars[-1].model_copy(update={
            "open_points": Decimal(139), "close_points": Decimal(139),
            "low_points": Decimal(138), "high_points": Decimal(140)}))
        if regime == "WEAK":
            bars = (*bars[:-2], bars[-2].model_copy(update={"low_points": Decimal(1)}), bars[-1])
    elif regime == "UNKNOWN":
        bars = bars[:-1]
    series = stock_fixture(days, snapshot.observed_at)
    series = series.model_copy(update={"bars": tuple(bar.model_copy(update={
        "open": Decimal(3970 if strong else 12000-100*i),
        "close": Decimal(3970 if strong else 12000-100*i),
        "high": Decimal(3971 if strong else 12001-100*i),
        "low": Decimal(3969 if strong else 11999-100*i),
    }) for i, bar in enumerate(series.bars))})
    source = LinkedIndexReplaySource(reference_market=plan.reference_market, bars=bars)
    replay = source.snapshot_at(snapshot.observed_at, days)
    arguments = dict(series=series, session_dates=days, decision_session=days[-1],
                     cutoff=snapshot.observed_at, inventory={"known": True, "total_qty": 0},
                     risk="UNSATISFIED")
    live = evaluate_market_linkage(plan, plan.ordinary_rules[0], index_bars=bars, **arguments)
    frozen = evaluate_market_linkage(plan, plan.ordinary_rules[0],
                                    index_bars=replay.official_daily_bars, **arguments)
    assert frozen == live
    assert live.market.regime == regime
    assert live.selection.group == group
    assert live.selection.blocker == blocker
    assert live.calculation.candidate_quantity == candidate
    if blocker:
        assert live.calculation.authorized_quantity == 0
