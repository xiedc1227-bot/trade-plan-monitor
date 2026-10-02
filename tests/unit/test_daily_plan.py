"""Daily contract tests. All completed examples are synthetic human supplements."""

import json

import pytest
from pydantic import ValidationError

from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan, DailyZone
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256


def synthetic_plan_payload():
    """Synthetic human-reviewed supplements; not thresholds from the old source."""

    def fact(kind):
        return {
            "type": "REVIEWED_FACT",
            "fact_kind": kind,
            "evidence_requirement": "Synthetic reviewer checks complete official evidence",
            "validity_scope": "TRADE_DATE",
        }

    return {
        "schema_version": 4,
        "execution_mode": "DAILY_CLOSE_PLAN",
        "execution_version": "daily-close-v1",
        "plan_id": "synthetic-daily",
        "version": 1,
        "symbol": "601021.SH",
        "name": "Synthetic reviewed plan",
        "market": "SSE",
        "metadata": {},
        "activation": {"mode": "MANUAL"},
        "levels": {
            "low_buy": {
                "low_fen": 3945,
                "high_fen": 3990,
                "include_low": True,
                "include_high": True,
            },
            "pressure": {
                "low_fen": 4180,
                "high_fen": 4220,
                "include_low": True,
                "include_high": True,
            },
            "risk_line_fen": 3818,
            "risk_comparison": "LT",
        },
        "position": {
            "max_qty": 300,
            "core_target_qty": 100,
            "tactical_target_qty": 0,
            "allocation_provenance": "PROPOSED",
            "allocation_evidence": "Synthetic human proposal",
        },
        "trading_rules": {
            "settlement": "NEXT_EXCHANGE_SESSION",
            "tick_size_fen": 1,
            "special_state_restrictions": "BLOCK_UNVERIFIED",
        },
        "monitoring": {
            "timeframe": "DAILY",
            "indicator_formula_version": "daily-ta-v2",
            "price_basis": "QFQ",
            "source_requirement": "ONE_VERIFIED_PROVIDER",
            "comparability_requirement": "CURRENT_QUOTE_BASIS",
            "macd_min_observations": 60,
        },
        "ordinary_rules": [
            {
                "status": "ENABLED",
                "side": "BUY",
                "rule_id": "low-buy",
                "zone": "LOW_BUY",
                "quantity": 100,
                "bucket": "TACTICAL",
                "price_structure": fact("PRICE_STRUCTURE"),
                "volume_or_candle": fact("VOLUME_OR_CANDLE"),
                "technical": fact("TECHNICAL"),
                "prerequisites": [],
                "validity": {"start_date": "2026-09-01", "end_date": "2026-12-31"},
                "invalidation": "RISK_OR_REVIEWED_INVALIDATION",
                "independent_signal": {
                    "mode": "REVIEWED_INDEPENDENT_EVENT",
                    "evidence_requirement": "New structure linked to prior signal",
                },
            },
            {
                "status": "DISABLED",
                "side": "SELL",
                "reason": "Synthetic tactical inventory is zero",
            },
        ],
        "risk_branches": [
            {
                "kind": kind,
                "involves_core": True,
                "scope_evidence": "Synthetic reviewed holding structure invalidation",
                "target_core_qty": 0,
                "target_tactical_qty": 0,
                "priority": priority,
                "evidence_mode": mode,
                **(
                    {"suspension_confirmation_policy": "RESUME_FIRST_CLOSE"}
                    if kind == "ORDINARY_TECHNICAL"
                    else {}
                ),
            }
            for kind, priority, mode in [
                ("ORDINARY_TECHNICAL", 3, "TWO_OFFICIAL_CLOSES"),
                ("SEVERE_TECHNICAL", 2, "STRUCTURE_AND_DETERIORATION"),
            ]
        ],
        "execution_policy": {
            "confirmation": "OFFICIAL_DAILY_CLOSE",
            "ordinary_window": "NEXT_EXCHANGE_SESSION_ONLY",
            "same_signal": "ONE_PLANNED_QUANTITY",
            "risk_priority": "SEVERE_THEN_ORDINARY",
            "ordinary_conflict": "BLOCK_BOTH",
        },
    }


def test_daily_round_trip_and_content_review_identity():
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    assert load_plan_json(dump_plan_json(plan)) == plan
    changed = plan.model_copy(update={"name": "Different display"})
    assert plan_sha256(changed) != plan_sha256(plan)
    assert daily_plan_content_sha256(changed) == daily_plan_content_sha256(plan)
    raw = json.loads(dump_plan_json(plan))
    raw["levels"]["low_buy"]["include_low"] = False
    assert daily_plan_content_sha256(
        DailyTradePlan.model_validate(raw)
    ) != daily_plan_content_sha256(plan)


def test_daily_zone_never_defaults_endpoints_or_accepts_empty_ticks():
    with pytest.raises(ValidationError):
        DailyZone(low_fen=3945, high_fen=3990)
    with pytest.raises(ValidationError):
        DailyZone(low_fen=3945, high_fen=3946, include_low=False, include_high=False)


def test_no_default_suspension_or_executable_missing_group():
    raw = synthetic_plan_payload()
    raw["risk_branches"][0].pop("suspension_confirmation_policy")
    with pytest.raises(ValidationError):
        DailyTradePlan.model_validate(raw)


@pytest.mark.parametrize("variant", ["MACD", "VOLUME", "SEQUENCE", "DYNAMIC_REFERENCE"])
def test_500_bar_contract_counts_condition_and_reference_offsets(variant):
    raw = synthetic_plan_payload()
    raw["monitoring"]["macd_min_observations"] = 500
    reference = {
        "mode": "FIXED",
        "value": "0",
        "unit": "INDICATOR",
        "as_of": "2026-09-18",
        "source": "Synthetic reviewed threshold",
    }
    key = "technical"
    condition = {
        "type": "DAILY_INDICATOR_COMPARE",
        "indicator": "MACD_HIST",
        "formula_version": "daily-ta-v2",
        "parameters": {"fast": 12, "slow": 26, "signal": 9},
        "offset": 0,
        "comparator": "GT",
        "reference": reference,
    }
    if variant == "VOLUME":
        key = "volume_or_candle"
        condition = {
            "type": "DAILY_VOLUME_RATIO",
            "offset": 0,
            "baseline": "MEAN",
            "window": 499,
            "comparator": "GT",
            "ratio": "1",
        }
    elif variant == "SEQUENCE":
        key = "price_structure"
        condition = {
            "type": "DAILY_CLOSE_SEQUENCE",
            "offset": 0,
            "sessions": 500,
            "mode": "PAIRWISE_NONDECREASING",
            "comparator": None,
            "reference": None,
        }
    elif variant == "DYNAMIC_REFERENCE":
        key = "price_structure"
        condition = {
            "type": "DAILY_PRICE_COMPARE",
            "field": "close",
            "offset": 0,
            "comparator": "GT",
            "reference": {
                "mode": "DYNAMIC",
                "indicator": "MACD_DIF",
                "formula_version": "daily-ta-v2",
                "parameters": {"fast": 12, "slow": 26, "signal": 9},
                "offset": 0,
            },
        }
    raw["ordinary_rules"][0][key] = condition
    assert DailyTradePlan.model_validate(raw)
    if variant == "DYNAMIC_REFERENCE":
        condition["reference"]["offset"] = 1
    else:
        condition["offset"] = 1
    with pytest.raises(ValidationError, match="500-bar history contract"):
        DailyTradePlan.model_validate(raw)
    raw = synthetic_plan_payload()
    raw["ordinary_rules"][0]["technical"] = None
    with pytest.raises(ValidationError):
        DailyTradePlan.model_validate(raw)
