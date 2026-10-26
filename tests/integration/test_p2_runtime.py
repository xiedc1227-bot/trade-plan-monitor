"""Frozen quantities and execution economics use the production lifecycle."""

from datetime import datetime, time

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.unit.test_p2_composition import fixture
from tests.unit.test_p2_economics import economics

from trade_plan_monitor.decision.p2_composition import evaluate_p2_market
from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
from trade_plan_monitor.domain.p2_policy_models import P2TradePlan


def signal_fixture():
    plan, inputs = fixture(1000)
    rule = plan.ordinary_rules[0]
    result = evaluate_p2_market(plan, rule, **inputs)
    signal = confirm_signal(plan, rule, series=inputs["series"], facts=(), previous=(),
        session_dates=inputs["session_dates"], plan_version_id="p2-plan", review_id="p2-review",
        linkage=result.decision)
    assert signal is not None
    return plan, signal


def test_signal_freezes_original_derived_q0_and_evidence():
    plan, signal = signal_fixture()
    assert signal["planned_qty"] == 200
    assert signal["pretrade"]["sizing"]["q0"] == 500
    assert signal["pretrade"]["content_hash"] == signal["market_linkage"]["content_hash"]
    assert plan.ordinary_rules[0].pretrade_policy.sizing.base_qty == 1000


def economics_plan():
    plan, signal = signal_fixture()
    raw = plan.model_dump(mode="json")
    raw["levels"]["low_buy"].update(low_fen=950, high_fen=1050)
    e = economics()
    e["fee_schedule"]["symbols"] = [plan.symbol]
    e["fee_schedule"].update(effective_from="2026-01-01", effective_through="2026-12-31")
    # gate at q=200: 20000 gross - 1000 fees = 19000
    e["gates"] = {"min_net_reward_fen": 19000, "min_reward_risk_ratio": None}
    raw["ordinary_rules"][0]["pretrade_policy"]["economics"] = e
    return P2TradePlan.model_validate(raw), signal


@pytest.mark.parametrize(("quote", "quantity"), [(1000, 200), (1001, 0), (999, 200)])
def test_execution_gate_recomputes_at_the_exact_frozen_quantity(quote, quantity):
    # Rebuilding evidence is test setup only; production uses the original plan hash.
    from trade_plan_monitor.domain.p2_evidence import freeze_pretrade
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    plan, signal = economics_plan()
    prior = signal["pretrade"]
    signal["pretrade"] = freeze_pretrade(plan, plan.ordinary_rules[0],
        sizing=prior["sizing"], economics=None, decision_session=prior["decision_session"],
        cutoff=prior["cutoff"]).model_dump(mode="json")
    signal["market_linkage"]["content_hash"] = daily_plan_content_sha256(plan)
    r = check_execution(plan, signal, inventory={"known": True,"total_qty": 0},
        quote_fen=quote, evaluated_at=datetime.combine(TUESDAY, time(10), SH),
        tradable=True, risk_blocked=False, risk_known=True)
    assert r["executable_qty"] == quantity
    assert r["planned_qty"] == 200


def test_changed_policy_invalidates_execution():
    plan, signal = economics_plan()
    r = check_execution(plan, signal, inventory={"known": True,"total_qty": 0},
        quote_fen=1000, evaluated_at=datetime.combine(TUESDAY, time(10), SH),
        tradable=True, risk_blocked=False, risk_known=True)
    assert r["executable_qty"] == 0
    assert "P2_FROZEN_POLICY_CHANGED" in r["blockers"]


def test_research_projection_preserves_validated_p2_evidence():
    from types import SimpleNamespace

    from trade_plan_monitor.backtest.research_signal_projection import (
        compact_signal_evidence,
        validate_signal_references,
    )
    from trade_plan_monitor.state.daily_state_models import DailySignalState

    _, raw = signal_fixture()
    signal = DailySignalState.model_validate(raw)
    values = compact_signal_evidence(dict(signals=(signal,), resulting_signals=(signal,),
                                         market_linkage=(signal.market_linkage,)))
    validate_signal_references(SimpleNamespace(**values))
    assert values["signal_pretrade"] == (signal.pretrade,)
    projected = values["signals"][0]
    assert DailySignalState.model_validate({
        **projected.model_dump(mode="python", exclude={"market_linkage_ref", "pretrade_ref"}),
        "pretrade": values["signal_pretrade"][0],
        "market_linkage": signal.market_linkage}) == signal
    with pytest.raises(ValueError):
        DailySignalState.model_validate_json(projected.model_dump_json())
