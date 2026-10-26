"""Independent fen/quantity examples for the approved capital constraints."""

from datetime import date

import pytest
from tests.unit.test_p2_economics import economics
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.decision.p2_economics import calculate_buy_debit
from trade_plan_monitor.domain.p2_policy_models import FeeSchedule
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan


def schedule(**changes):
    return FeeSchedule.model_validate(economics()["fee_schedule"] | changes)


def debit(**changes):
    return calculate_buy_debit(schedule(), **({"quantity": 100, "entry_fen": 1000,
        "symbol": "600000.SH", "session": date(2026, 10, 26)} | changes))


def test_budget_debit_uses_exact_buy_fees_without_target_or_risk_inputs():
    result = debit()
    assert result.outcome == "PASS"
    assert (result.notional_fen, result.total_fees_fen, result.debit_fen) == (100000, 500, 100500)
    assert debit(entry_fen=1001).debit_fen == 100600


@pytest.mark.parametrize("changes,reason", [
    ({"quantity": None}, "ECONOMICS_INPUT_UNKNOWN"),
    ({"quantity": True}, "ECONOMICS_INPUT_UNKNOWN"),
    ({"quantity": 99}, "ECONOMICS_INPUT_UNKNOWN"),
    ({"entry_fen": None}, "ECONOMICS_INPUT_UNKNOWN"),
    ({"entry_fen": 9007199254740991}, "ECONOMICS_OVERFLOW"),
    ({"session": date(2026, 11, 1)}, "FEE_SCHEDULE_NOT_APPLICABLE"),
    ({"symbol": "000001.SZ"}, "FEE_SCHEDULE_NOT_APPLICABLE"),
])
def test_unavailable_or_unsafe_buy_cost_never_invents_a_debit(changes, reason):
    result = debit(**changes)
    assert result.outcome == "UNKNOWN" and result.reason == reason
    assert result.debit_fen is None


def test_slippage_fractional_rounding_and_inclusion_share_the_p2_fee_engine():
    fees = schedule(commission_rate="0.000001", minimum_commission_fen=0,
        buy_slippage_fen=1, components=[
            {"id": "HANDLING", "side": "BUY", "kind": "HANDLING", "rate": "0.1",
             "included_in": "COMMISSION"},
            {"id": "TRANSFER", "side": "BOTH", "kind": "TRANSFER", "rate": "0.000001",
             "included_in": None}])
    result = calculate_buy_debit(fees, quantity=100, entry_fen=1000,
        symbol="600000.SH", session=date(2026, 10, 26))
    assert result.notional_fen == 100100
    assert result.fees == {"COMMISSION": 1, "TRANSFER": 1}
    assert result.debit_fen == 100102


def capital(mode="OPEN_COST_CAP", **changes):
    from trade_plan_monitor.decision.p3_capital import assess_capital

    raw = p3_payload(mode)
    cap = raw["position"]["limit"]["capital_policy"]
    cap["cap_fen"] = 550500 if mode == "OPEN_COST_CAP" else 500000
    plan = P3TradePlan.model_validate(raw)
    return assess_capital(plan.position, **({"quantity": 100, "price_fen": 1000,
        "total_qty": 400, "retained_basis_fen": 450000, "symbol": plan.symbol,
        "session": date(2026, 10, 26)} | changes))


@pytest.mark.parametrize("price,expected,after", [(1000, "PASS", 550500),
                                                (1001, "FAIL", 550600)])
def test_open_cost_equality_and_whole_rejection(price, expected, after):
    result = capital(price_fen=price)
    assert result.outcome == expected
    assert result.quantity == 100
    assert result.before_fen == 450000 and result.after_fen == after
    assert result.remaining_fen == 550500-after
    assert result.share_capacity.mode == "UNBOUNDED"


@pytest.mark.parametrize("price,expected,after", [(1000, "PASS", 500000),
    (1001, "FAIL", 500500), (990, "PASS", 495000)])
def test_value_cap_uses_all_holdings_not_costs_or_tactical_only(price, expected, after):
    result = capital("MARKET_VALUE_CAP", price_fen=price, retained_basis_fen=None)
    assert result.outcome == expected and result.after_fen == after
    assert result.buy_debit is None


@pytest.mark.parametrize("changes,reason", [
    ({"total_qty": None}, "CAPITAL_POSITION_UNKNOWN"),
    ({"total_qty": True}, "CAPITAL_POSITION_UNKNOWN"),
    ({"quantity": 99}, "CAPITAL_QUANTITY_UNKNOWN"),
    ({"price_fen": None}, "CAPITAL_QUOTE_UNKNOWN"),
    ({"retained_basis_fen": None}, "CAPITAL_BASE_UNKNOWN"),
    ({"retained_basis_fen": -1}, "CAPITAL_BASE_UNKNOWN"),
    ({"retained_basis_fen": 9007199254740991}, "CAPITAL_OVERFLOW"),
    ({"price_fen": 9007199254740991}, "CAPITAL_OVERFLOW"),
])
def test_unknown_inputs_block_only_the_dependent_calculation(changes, reason):
    result = capital(**changes)
    assert result.outcome == "UNKNOWN" and reason in result.blockers
    assert result.quantity in (None, 100)


def test_combined_share_limit_and_amount_only_are_distinct():
    from trade_plan_monitor.decision.p3_capital import assess_capital

    raw = p3_payload("MARKET_VALUE_CAP", combined=True)
    raw["position"]["limit"].update(max_qty=500)
    plan = P3TradePlan.model_validate(raw)
    kwargs = dict(quantity=100, price_fen=1000, total_qty=400, retained_basis_fen=None,
        symbol=plan.symbol, session=date(2026, 10, 26))
    result = assess_capital(plan.position, **kwargs)
    assert result.outcome == "PASS" and result.share_capacity.remaining_qty == 100
    result = assess_capital(plan.position, **(kwargs | {"total_qty": 500, "price_fen": 100}))
    assert result.outcome == "FAIL" and result.blockers == ("MAX_QUANTITY_CAPACITY",)
    assert result.share_capacity.remaining_qty == 0
    assert capital(total_qty=None).share_capacity.mode == "UNKNOWN"


def test_capital_assessment_detects_tampering_and_never_selects_a_sell():
    from pydantic import ValidationError

    from trade_plan_monitor.decision.p3_capital import CapitalAssessment

    result = capital("MARKET_VALUE_CAP", total_qty=600)
    assert result.outcome == "FAIL" and result.quantity == 100
    assert "side" not in result.model_dump()
    raw = result.model_dump(mode="json")
    raw["after_fen"] = 1
    with pytest.raises(ValidationError, match="hash"):
        CapitalAssessment.model_validate(raw)
