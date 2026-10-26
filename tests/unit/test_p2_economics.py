"""Independent scenario arithmetic, source boundaries and optional gates."""

from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from trade_plan_monitor.decision.p2_economics import calculate_economics
from trade_plan_monitor.domain.p2_policy_models import RequiredEconomics


def economics():
    return {"mode": "REQUIRED",
            "entry_price_mode": "CONFIRMED_CLOSE_THEN_EXECUTION_QUOTE",
            "target_price_fen": 1100, "risk_price_fen": 950,
            "gates": {"min_net_reward_fen": 9000, "min_reward_risk_ratio": "1.5"},
            "fee_schedule": {"schedule_id": "synthetic", "version": "test-v1", "currency": "CNY",
                "symbols": ["600000.SH"], "effective_from": "2026-10-01",
                "effective_through": "2026-10-31",
                "provenance": {"source": "fixture", "excerpt": "synthetic, not market rates",
                               "as_of": None, "classification": "ESTIMATE"},
                "commission_rate": "0", "minimum_commission_fen": 500,
                "components": [], "buy_slippage_fen": 0, "sell_slippage_fen": 0}}


def calc(raw=None, **kwargs):
    return calculate_economics(RequiredEconomics.model_validate(raw or economics()),
        **({"quantity": 100, "entry_fen": 1000, "symbol": "600000.SH",
            "session": date(2026, 10, 26)} | kwargs))


def test_specification_scenario_and_exact_gate_equality():
    r = calc()
    assert (r.entry_debit_fen, r.target_proceeds_fen, r.risk_proceeds_fen) == (
        100500, 109500, 94500)
    assert (r.net_reward_fen, r.planned_loss_fen, r.total_cost_fen) == (9000, 6000, 1000)
    assert (r.spread_numerator, r.spread_denominator) == (10, 1)
    assert r.outcome == "PASS" and r.blockers == ()


def test_current_quote_can_fail_then_recover_without_resizing():
    assert calc(entry_fen=1001).outcome == "FAIL"
    assert calc(entry_fen=1000).outcome == "PASS"
    assert calc(entry_fen=999).outcome == "PASS"
    assert calc(quantity=200).total_cost_fen == 1000


@pytest.mark.parametrize("change", ["expiry", "symbol", "missing", "price", "overflow"])
def test_required_unknown_never_passes(change):
    values = {"expiry": {"session": date(2026, 11, 1)},
              "symbol": {"symbol": "000001.SZ"}, "missing": {"entry_fen": None},
              "price": {"entry_fen": 1100}, "overflow": {"quantity": 9007199254740900}}
    r = calc(**values[change])
    assert r.outcome == "UNKNOWN" and r.blockers


def test_included_fee_is_not_charged_twice_and_fractional_fees_round_up():
    raw = economics()
    raw["fee_schedule"]["components"] = [
        {"id": "HANDLING", "side": "BOTH", "kind": "HANDLING", "rate": "0.0001",
         "included_in": "COMMISSION"},
        {"id": "TAX", "side": "SELL", "kind": "TAX", "rate": "0.000001",
         "included_in": None}]
    r = calc(raw)
    assert r.entry_debit_fen == 100500
    assert r.target_proceeds_fen == 109499
    assert r.total_cost_fen == 1001


@pytest.mark.parametrize("change", ["both_missing", "negative", "float", "cycle", "side"])
def test_invalid_fee_and_gate_contracts_are_rejected(change):
    raw = deepcopy(economics())
    if change == "both_missing":
        raw["gates"] = {"min_net_reward_fen": None, "min_reward_risk_ratio": None}
    elif change == "negative":
        raw["fee_schedule"]["minimum_commission_fen"] = -1
    elif change == "float":
        raw["fee_schedule"]["commission_rate"] = 0.003
    else:
        raw["fee_schedule"]["components"] = [
            {"id": "ONE", "side": "BOTH", "kind": "HANDLING", "rate": "0.001",
             "included_in": "ONE" if change == "cycle" else "TWO"},
            {"id": "TWO", "side": "SELL", "kind": "TAX", "rate": "0.001",
             "included_in": None}]
    with pytest.raises(ValidationError):
        RequiredEconomics.model_validate(raw)


def test_preview_only_unknown_is_visible_without_blocking():
    from trade_plan_monitor.domain.p2_policy_models import EconomicsPreview

    raw = economics()
    raw["mode"] = "PREVIEW_ONLY"
    del raw["gates"]
    r = calculate_economics(EconomicsPreview.model_validate(raw), quantity=100, entry_fen=None,
                            symbol="600000.SH", session=date(2026, 10, 26))
    assert r.outcome == "UNKNOWN" and not r.blockers
