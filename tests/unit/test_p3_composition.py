"""Independent quantities prove capital gates cannot create or resize authority."""

import pytest
from tests.unit.test_p2_composition import fixture
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.decision.p3_composition import evaluate_p3_market
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan


def inputs_for(base=1000, route="WEAK_MINIMUM", mode="MARKET_VALUE_CAP", combined=False):
    previous, inputs = fixture(base, route)
    raw = previous.model_dump(mode="json")
    p3 = p3_payload(mode, combined)
    raw.update(schema_version=9, execution_version="condition-plan-v5", position=p3["position"])
    return P3TradePlan.model_validate(raw), inputs


def test_amount_only_keeps_p2_then_market_quantity_without_fake_capacity():
    plan, inputs = inputs_for()
    result = evaluate_p3_market(plan, plan.ordinary_rules[0], **inputs)
    calc = result.decision.calculation
    assert result.sizing.q0 == 500
    assert calc.candidate_quantity == calc.authorized_quantity == 200
    assert calc.share_capacity.mode == "UNBOUNDED"
    assert "capacity" not in calc.model_dump()
    assert calc.capital.outcome == "PASS"
    assert result.decision.model_validate_json(result.decision.model_dump_json()) == result.decision


@pytest.mark.parametrize("kind", ["cap", "inventory", "basis", "shares"])
def test_gate_rejects_the_full_selected_quantity_without_resizing(kind):
    plan, inputs = inputs_for(mode="OPEN_COST_CAP" if kind == "basis" else
                             "MARKET_VALUE_CAP", combined=kind == "shares")
    raw = plan.model_dump(mode="json")
    if kind == "cap":
        raw["position"]["limit"]["capital_policy"]["cap_fen"] = 1
    if kind == "shares":
        raw["position"]["limit"]["max_qty"] = 100
    if kind == "inventory":
        inputs["inventory"] = {"known": False, "total_qty": 0}
    plan = P3TradePlan.model_validate(raw)
    result = evaluate_p3_market(plan, plan.ordinary_rules[0], **inputs)
    calc = result.decision.calculation
    assert calc.candidate_quantity == 200 and calc.authorized_quantity == 0
    assert calc.blockers
    if kind == "inventory":
        assert calc.share_capacity.mode == "UNKNOWN"


def test_cost_and_inventory_changes_do_not_create_new_occurrence():
    plan, inputs = inputs_for()
    first = evaluate_p3_market(plan, plan.ordinary_rules[0], **inputs)
    second = evaluate_p3_market(plan, plan.ordinary_rules[0], **(inputs | {
        "inventory": {"known": True, "total_qty": 5000, "revision": 20},
        "retained_basis_fen": 90000, "book_revision": 40}))
    assert first.decision.consumed_hash == second.decision.consumed_hash
    assert first.decision.evidence_hash != second.decision.evidence_hash
    assert second.decision.calculation.authorized_quantity == 0


@pytest.mark.parametrize(("base", "route", "candidate"), [
    (200, "WEAK_MINIMUM", 100), (1000, "BROKEN_STRONG", None)])
def test_exception_candidate_never_gets_automatic_authority(base, route, candidate):
    plan, inputs = inputs_for(base, route)
    result = evaluate_p3_market(plan, plan.ordinary_rules[0], **inputs)
    assert result.decision.calculation.route == route
    assert result.decision.calculation.candidate_quantity == candidate
    assert result.decision.calculation.authorized_quantity == 0
