"""Use actual daily/index evidence to prove P2 ordering and P1 boundaries."""

from datetime import datetime, time
from types import SimpleNamespace

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.unit.test_p2_policy_contract import p2_payload

from trade_plan_monitor.decision.p2_composition import evaluate_p2_market
from trade_plan_monitor.domain.p2_policy_models import P2TradePlan


def fixture(base, route="WEAK_MINIMUM"):
    raw = p2_payload()
    raw["risk_branches"] = []
    raw["position"]["max_qty"] = 2000
    zone = dict(low_fen=100, high_fen=200, include_low=True, include_high=True)
    raw["levels"]["low_buy"] = zone
    rule = raw["ordinary_rules"][0]
    rule["condition"] = dict(type="DAILY_PRICE_IN_RANGE", field="close", offset=0, range=zone)
    rule["pretrade_policy"]["sizing"].update(base_qty=base,
        tiers=[{"lower": "0", "upper": None, "multiplier": "0.5"}])
    plan = P2TradePlan.model_validate(raw)
    chain = SimpleNamespace(plan=plan, route=route, now=datetime.combine(FRIDAY, time(16), SH))
    inputs = exception_inputs(chain)
    return plan, dict(series=inputs.series, index_bars=inputs.linked_index.official_daily_bars,
        session_dates=inputs.session_dates, decision_session=FRIDAY, cutoff=chain.now,
        inventory={"known": True, "total_qty": 0}, risk="UNSATISFIED")


def test_volatility_then_market_reduction_not_reversed_or_replaced():
    plan, inputs = fixture(1000)
    result = evaluate_p2_market(plan, plan.ordinary_rules[0], **inputs)
    assert result.sizing.q0 == 500
    assert result.decision.calculation.candidate_quantity == 200
    assert result.decision.calculation.authorized_quantity == 200


def test_volatility_below_minimum_never_offers_weak_exception():
    plan, inputs = fixture(100)
    result = evaluate_p2_market(plan, plan.ordinary_rules[0], **inputs)
    assert result.decision is None
    assert result.sizing.blocker == "VOLATILITY_BELOW_MINIMUM"


@pytest.mark.parametrize(("base", "route", "candidate"), [
    (200, "WEAK_MINIMUM", 100), (1000, "BROKEN_STRONG", None)])
def test_both_exception_routes_preserve_zero_authority(base, route, candidate):
    plan, inputs = fixture(base, route)
    result = evaluate_p2_market(plan, plan.ordinary_rules[0], **inputs)
    assert result.decision.calculation.route == route
    assert result.decision.calculation.candidate_quantity == candidate
    assert result.decision.calculation.authorized_quantity == 0


def test_missing_daily_evidence_never_fabricates_q0():
    plan, inputs = fixture(1000)
    result = evaluate_p2_market(plan, plan.ordinary_rules[0], **(inputs | {"series": None}))
    assert result.decision is None and result.sizing.q0 is None
