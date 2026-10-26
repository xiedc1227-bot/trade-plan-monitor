"""Actual signal confirmation freezes P3 q without a synthetic share ceiling."""

from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.decision.p3_composition import evaluate_p3_market
from trade_plan_monitor.decision.unified_lifecycle import confirm_signal
from trade_plan_monitor.state.daily_state_models import DailySignalState


def signal_fixture():
    plan, inputs = inputs_for()
    rule = plan.ordinary_rules[0]
    result = evaluate_p3_market(plan, rule, **inputs)
    signal = confirm_signal(plan, rule, series=inputs["series"], facts=(), previous=(),
        session_dates=inputs["session_dates"], plan_version_id="p3-plan", review_id="p3-review",
        linkage=result.decision)
    assert signal is not None
    return plan, inputs, signal


def test_current_signal_freezes_quantity_and_roundtrips_complete_capital_evidence():
    plan, _, raw = signal_fixture()
    signal = DailySignalState.model_validate(raw)
    assert signal.planned_qty == 200
    assert signal.pretrade.sizing.q0 == 500
    assert signal.market_linkage.calculation.share_capacity.mode == "UNBOUNDED"
    assert signal.market_linkage.calculation.capital.after_fen == 32200
    assert DailySignalState.model_validate_json(signal.model_dump_json()) == signal
    assert "max_qty" not in plan.position.model_dump()


def test_new_budget_or_inventory_cannot_rearm_existing_signal():
    plan, inputs, raw = signal_fixture()
    changed = inputs | {"inventory": {"known": True, "total_qty": 100, "revision": 4}}
    result = evaluate_p3_market(plan, plan.ordinary_rules[0], **changed)
    assert result.decision.consumed_hash == raw["market_linkage"]["consumed_hash"]
    again = confirm_signal(plan, plan.ordinary_rules[0], series=inputs["series"], facts=(),
        previous=(raw,), session_dates=inputs["session_dates"], plan_version_id="p3-plan",
        review_id="p3-review", linkage=result.decision)
    assert again is None
