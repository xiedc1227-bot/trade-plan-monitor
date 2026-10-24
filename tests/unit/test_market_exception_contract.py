"""Schema 7 permission is explicit and cannot alter old linked contracts."""

import json
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_market_linkage_contract import linked_payload

from trade_plan_monitor.domain.plan_codec import (
    dump_plan_json,
    dump_plan_yaml,
    load_plan_json,
    load_plan_yaml,
)


def exception_payload():
    raw = linked_payload()
    raw.update(schema_version=7, execution_version="condition-plan-v3")
    buy = next(r for r in raw["ordinary_rules"] if r["side"] == "BUY")
    buy["market_policy"] = {
        "policy_version": "market-linkage-v2",
        "base_confirmation": "S0",
        "exception_policy": "REVIEW_PER_OCCURRENCE",
        "exception_routes": {
            "weak_minimum": "PER_OCCURRENCE",
            "broken_strong": "PER_OCCURRENCE",
        },
    }
    return raw


def test_exception_plan_round_trips_without_quantity_or_approval_defaults():
    plan = load_plan_json(json.dumps(exception_payload()))
    assert plan.schema_version == 7
    assert load_plan_yaml(dump_plan_yaml(plan)) == plan
    assert load_plan_json(dump_plan_json(plan)) == plan
    rule = next(r for r in plan.ordinary_rules if r.side == "BUY")
    assert rule.market_policy.exception_routes.weak_minimum == "PER_OCCURRENCE"
    assert "quantity" not in rule.model_dump()
    assert "approved_quantity" not in rule.model_dump()


@pytest.mark.parametrize("change", ["missing", "null", "auto", "approval", "quantity", "core"])
def test_exception_plan_rejects_missing_or_fabricated_authority(change):
    from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan

    raw = exception_payload()
    buy = next(r for r in raw["ordinary_rules"] if r["side"] == "BUY")
    if change in {"missing", "null", "auto"}:
        flags = buy["market_policy"]["exception_routes"]
        if change == "missing":
            del flags["broken_strong"]
        else:
            flags["broken_strong"] = None if change == "null" else "AUTO_APPROVE"
    elif change == "core":
        buy["bucket"] = "CORE"
    else:
        buy["approval_id" if change == "approval" else "quantity"] = 100
    with pytest.raises(ValidationError):
        MarketExceptionTradePlan.model_validate(raw)


def test_disabled_routes_remain_explicit_and_do_not_downgrade():
    raw = exception_payload()
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"] = {
        "weak_minimum": "DISABLED", "broken_strong": "DISABLED"
    }
    assert load_plan_json(json.dumps(raw)).schema_version == 7


def test_old_linked_reader_refuses_new_authority():
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    with pytest.raises(ValidationError):
        MarketLinkedTradePlan.model_validate(exception_payload())
    old = load_plan_json(json.dumps(linked_payload()))
    assert old.schema_version == 6
    assert old.ordinary_rules[0].market_policy.exception_policy == "BLOCK_P1"


def test_exception_draft_hash_and_executable_share_a_separate_domain():
    from trade_plan_monitor.domain.daily_plan_validation import (
        daily_draft_content_sha256,
        daily_draft_issues,
        load_daily_draft_json,
    )
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    plan = load_plan_json(json.dumps(exception_payload()))
    draft = load_daily_draft_json(dump_plan_json(plan))
    assert draft.to_executable() == plan
    assert daily_draft_issues(draft) == ()
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    expected = sha256(b"plan-review-content-v4\x00" + json.dumps(
        content, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert daily_plan_content_sha256(plan) == daily_draft_content_sha256(draft) == expected


def test_incomplete_permission_is_preserved_without_approval():
    from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json

    raw = exception_payload()
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"]["broken_strong"] = None
    draft = load_daily_draft_json(json.dumps(raw))
    assert draft.ordinary_rules[0].market_policy.exception_routes.broken_strong is None
    assert draft.to_executable() is None


def test_common_draft_constructor_retains_exception_permission():
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    plan = load_plan_json(json.dumps(exception_payload()))
    draft = UnifiedPlanDraft.from_executable(plan)
    assert draft.schema_version == 7
    assert draft.to_executable() == plan
