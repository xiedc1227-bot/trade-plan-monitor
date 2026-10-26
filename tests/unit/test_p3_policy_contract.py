"""Money-only inputs must not manufacture a share ceiling or account costs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from tests.unit.test_p2_economics import economics
from tests.unit.test_p2_policy_contract import p2_payload

from trade_plan_monitor.domain.p3_policy_models import P3TradePlan


def capital_policy(mode="MARKET_VALUE_CAP"):
    raw = {"policy_version": "capital-policy-v1", "currency": "CNY",
           "scope": "SYMBOL_CORE_AND_TACTICAL", "account_scope": "SIMULATION",
           "cap_fen": 550500, "mode": mode}
    if mode == "MARKET_VALUE_CAP":
        raw["valuation"] = "CURRENT_ADMITTED_QUOTE"
    else:
        raw["buy_cost_schedule"] = economics()["fee_schedule"]
    return raw


def p3_payload(mode="MARKET_VALUE_CAP", combined=False):
    raw = p2_payload()
    raw.update(schema_version=9, execution_version="condition-plan-v5")
    original_max = raw["position"].pop("max_qty")
    raw["position"]["limit"] = {
        "mode": "QUANTITY_AND_CAPITAL" if combined else "CAPITAL_ONLY",
        "capital_policy": capital_policy(mode),
        **({"max_qty": original_max} if combined else {}),
    }
    if mode == "OPEN_COST_CAP":
        raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"]["symbols"] = [raw["symbol"]]
    return raw


@pytest.mark.parametrize("mode", ["OPEN_COST_CAP", "MARKET_VALUE_CAP"])
@pytest.mark.parametrize("combined", [False, True])
def test_explicit_position_variants_roundtrip_without_inferred_capacity(mode, combined):
    raw = p3_payload(mode, combined)
    plan = P3TradePlan.model_validate(raw)
    assert P3TradePlan.model_validate_json(plan.model_dump_json()) == plan
    limit = plan.position.limit
    assert ("max_qty" in limit.model_dump()) == combined
    assert "max_qty" not in plan.position.model_dump()
    assert "cash" not in plan.model_dump_json()
    if mode == "OPEN_COST_CAP":
        assert plan.ordinary_rules[0].pretrade_policy.economics.mode == "NONE"


@pytest.mark.parametrize("mutation", ["no_cap", "zero", "negative", "float", "bool",
    "unsafe", "missing_mode", "net_cash", "actual_account", "portfolio", "fake_max",
    "cost_missing_fees", "value_extra_fees", "bad_quantity", "no_max"])
def test_capital_contract_rejects_ambiguous_or_unsafe_source(mutation):
    raw = p3_payload("OPEN_COST_CAP" if mutation == "cost_missing_fees" else
                     "MARKET_VALUE_CAP", combined=mutation in {"bad_quantity", "no_max"})
    limit = raw["position"]["limit"]
    cap = limit["capital_policy"]
    if mutation == "no_cap":
        limit.pop("capital_policy")
    elif mutation in {"zero", "negative", "float", "bool", "unsafe"}:
        cap["cap_fen"] = {"zero": 0, "negative": -1, "float": 1.0,
                          "bool": True, "unsafe": 9007199254740992}[mutation]
    elif mutation == "missing_mode":
        cap.pop("mode")
    elif mutation == "net_cash":
        cap["mode"] = "NET_INVESTED_CASH"
    elif mutation == "actual_account":
        cap["account_scope"] = "ACTUAL"
    elif mutation == "portfolio":
        cap["scope"] = "PORTFOLIO"
    elif mutation == "fake_max":
        limit["max_qty"] = 9007199254740900
    elif mutation == "cost_missing_fees":
        cap.pop("buy_cost_schedule")
    elif mutation == "value_extra_fees":
        cap["buy_cost_schedule"] = economics()["fee_schedule"]
    elif mutation == "bad_quantity":
        limit["max_qty"] = 199
    else:
        limit.pop("max_qty")
    with pytest.raises(ValidationError):
        P3TradePlan.model_validate(raw)


def test_cost_schedule_matches_security_and_optional_p2_schedule():
    raw = p3_payload("OPEN_COST_CAP")
    raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"]["symbols"] = [raw["symbol"]]
    rule = raw["ordinary_rules"][0]
    rule["pretrade_policy"]["economics"] = economics()
    rule["pretrade_policy"]["economics"]["fee_schedule"]["symbols"] = [raw["symbol"]]
    assert P3TradePlan.model_validate(raw).schema_version == 9
    rule["pretrade_policy"]["economics"]["fee_schedule"]["commission_rate"] = "0.1"
    with pytest.raises(ValidationError, match="schedule"):
        P3TradePlan.model_validate(raw)
    raw = p3_payload("OPEN_COST_CAP")
    raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"]["symbols"] = ["000001.SZ"]
    with pytest.raises(ValidationError, match="security"):
        P3TradePlan.model_validate(raw)


def test_old_reader_rejects_nine_and_fixed_buy_cannot_drop_linkage():
    from trade_plan_monitor.domain.p2_policy_models import P2TradePlan
    raw = p3_payload()
    with pytest.raises(ValidationError):
        P2TradePlan.model_validate(raw)
    buy = raw["ordinary_rules"][0]
    for field in ("market_policy", "quantity_policy", "pretrade_policy"):
        buy.pop(field)
    buy["quantity"] = 100
    with pytest.raises(ValidationError):
        P3TradePlan.model_validate(raw)


def test_nullable_candidates_preserve_unknowns_but_keep_collection_limits():
    from trade_plan_monitor.domain.p3_policy_drafts import DraftP3Position
    raw = deepcopy(p3_payload("OPEN_COST_CAP")["position"])
    raw["limit"]["capital_policy"]["cap_fen"] = None
    draft = DraftP3Position.model_validate(raw)
    assert draft.limit.capital_policy.cap_fen is None
    raw["limit"]["capital_policy"]["buy_cost_schedule"]["components"] = [
        {"id": "FEE", "side": "BUY", "kind": "HANDLING", "rate": "0", "included_in": None}
    ] * 21
    with pytest.raises(ValidationError):
        DraftP3Position.model_validate(raw)
