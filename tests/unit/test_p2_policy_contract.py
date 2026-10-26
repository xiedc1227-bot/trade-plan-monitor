"""P2 opt-in contracts preserve source meaning and old readers."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from tests.unit.test_market_exception_contract import exception_payload

from trade_plan_monitor.domain.p2_policy_models import P2TradePlan, PretradePolicy


def sizing():
    return {"mode": "ATR_RATIO_TIERS", "metric": "ATR14_OVER_CLOSE", "base_qty": 1000,
            "tiers": [{"lower": "0", "upper": "0.05", "multiplier": "1"},
                      {"lower": "0.05", "upper": None, "multiplier": "0.5"}]}


def policy():
    return {"policy_version": "pretrade-policy-v1", "sizing": sizing(),
            "economics": {"mode": "NONE"}, "level_evidence": []}


def p2_payload():
    raw = exception_payload()
    raw.update(schema_version=8, execution_version="condition-plan-v4")
    rule = raw["ordinary_rules"][0]
    rule["quantity_policy"].pop("base_quantity")
    rule["quantity_policy"]["mode"] = "DERIVED_MARKET_FACTOR"
    rule["pretrade_policy"] = policy()
    return raw


def test_tier_plan_roundtrip_has_no_input_q0_or_approval():
    plan = P2TradePlan.model_validate(p2_payload())
    assert P2TradePlan.model_validate_json(plan.model_dump_json()) == plan
    rule = plan.ordinary_rules[0]
    assert "base_quantity" not in rule.quantity_policy.model_dump()
    assert rule.pretrade_policy.sizing.base_qty == 1000
    assert "approval" not in rule.model_dump()


@pytest.mark.parametrize("mutation", ["gap", "overlap", "increase", "empty", "float",
                                     "negative", "unbounded", "unsafe", "eleven"])
def test_tier_contract_rejects_ambiguous_or_unsafe_tables(mutation):
    raw = policy()
    tiers = raw["sizing"]["tiers"]
    if mutation == "gap":
        tiers[1]["lower"] = "0.06"
    elif mutation == "overlap":
        tiers[1]["lower"] = "0.04"
    elif mutation == "increase":
        tiers[0]["multiplier"] = "0.4"
    elif mutation == "empty":
        raw["sizing"]["tiers"] = []
    elif mutation == "float":
        tiers[0]["upper"] = 0.05
    elif mutation == "negative":
        tiers[0]["lower"] = "-0.1"
    elif mutation == "unbounded":
        tiers[1]["upper"] = "1"
    elif mutation == "unsafe":
        raw["sizing"]["base_qty"] = 9007199254741000
    else:
        raw["sizing"]["tiers"] = tiers * 6
    with pytest.raises(ValidationError):
        PretradePolicy.model_validate(raw)


def test_mixed_fixed_and_derived_quantity_is_rejected():
    raw = p2_payload()
    raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = 1000
    with pytest.raises(ValidationError):
        P2TradePlan.model_validate(raw)
    raw = p2_payload()
    raw["ordinary_rules"][0]["pretrade_policy"]["sizing"] = {"mode": "FIXED_Q0"}
    with pytest.raises(ValidationError):
        P2TradePlan.model_validate(raw)


def test_fixed_q0_keeps_explicit_original_quantity():
    raw = p2_payload()
    raw["ordinary_rules"][0]["pretrade_policy"]["sizing"] = {"mode": "FIXED_Q0"}
    raw["ordinary_rules"][0]["quantity_policy"] = deepcopy(
        exception_payload()["ordinary_rules"][0]["quantity_policy"])
    assert P2TradePlan.model_validate(raw).schema_version == 8


def test_old_reader_still_refuses_schema8():
    from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan

    with pytest.raises(ValidationError):
        MarketExceptionTradePlan.model_validate(p2_payload())


def test_p2_draft_and_plan_bind_new_review_domain():
    import json
    from hashlib import sha256

    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
    from trade_plan_monitor.domain.p2_validation import P2PlanDraft
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    plan = P2TradePlan.model_validate(p2_payload())
    draft = P2PlanDraft.from_executable(plan)
    assert draft.to_executable() == plan
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    expected = sha256(b"plan-review-content-v5\x00" + json.dumps(
        content, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert daily_plan_content_sha256(plan) == daily_draft_content_sha256(draft) == expected


def test_equivalent_decimal_spellings_have_identical_p2_review_hashes():
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    raw = p2_payload()
    original = P2TradePlan.model_validate(raw)
    raw["ordinary_rules"][0]["pretrade_policy"]["sizing"]["tiers"][0]["upper"] = "0.0500"
    assert daily_plan_content_sha256(P2TradePlan.model_validate(raw)) == (
        daily_plan_content_sha256(original))


def test_extreme_decimal_expansion_is_rejected_before_arithmetic():
    raw = policy()
    raw["sizing"]["tiers"][0]["upper"] = "1e-1000000000"
    raw["sizing"]["tiers"][1]["lower"] = "1e-1000000000"
    with pytest.raises(ValidationError):
        PretradePolicy.model_validate(raw)


def test_invalid_decimal_is_a_validation_error():
    raw = policy()
    raw["sizing"]["tiers"][0]["upper"] = "not-a-number"
    with pytest.raises(ValidationError):
        PretradePolicy.model_validate(raw)


def test_nullable_draft_retains_collection_bounds():
    from trade_plan_monitor.domain.p2_policy_drafts import DraftPretradePolicy

    raw = policy()
    raw["sizing"]["tiers"] *= 6
    with pytest.raises(ValidationError):
        DraftPretradePolicy.model_validate(raw)
