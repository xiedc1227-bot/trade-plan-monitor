"""PBS ordinary-only domain admission; no runtime or source authority is implied."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_market_exception_contract import exception_payload
from tests.unit.test_market_linkage_contract import linked_payload
from tests.unit.test_p2_policy_contract import p2_payload
from tests.unit.test_p3_policy_contract import p3_payload
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_issues,
    daily_draft_json,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.plan_hash import unified_plan_content_sha256
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def suspension_payload():
    raw = unified_payload()
    raw.update(schema_version=10, execution_version="condition-plan-v6")
    for branch in raw["risk_branches"]:
        branch.setdefault("suspension_confirmation_policy", None)
    raw["buy_suspension"] = {
        "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 2420},
        "effective_from": "2026-09-30T09:30:00+08:00",
    }
    return raw


def test_new_ordinary_contract_preserves_guard_across_model_and_draft_json():
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    plan = BuySuspensionTradePlan.model_validate(suspension_payload())
    draft = UnifiedPlanDraft.from_executable(plan)
    assert type(draft) is BuySuspensionPlanDraft
    assert type(draft.to_executable()) is BuySuspensionTradePlan
    assert draft.to_executable() == plan
    assert plan.buy_suspension.condition.price_fen == 2420
    assert plan.buy_suspension.effective_from.isoformat() == "2026-09-30T09:30:00+08:00"
    restored = load_daily_draft_json(daily_draft_json(draft))
    assert type(restored) is BuySuspensionPlanDraft
    assert restored == draft
    assert daily_draft_issues(restored) == ()
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    expected = sha256(
        b"plan-review-content-v7\x00"
        + json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert daily_draft_content_sha256(draft) == unified_plan_content_sha256(plan) == expected
    for path in ("effective_from", "condition"):
        changed = deepcopy(suspension_payload())
        if path == "effective_from":
            changed["buy_suspension"][path] = "2026-09-30T09:35:00+08:00"
        else:
            changed["buy_suspension"][path]["price_fen"] = 2421
        updated = BuySuspensionTradePlan.model_validate(changed)
        assert unified_plan_content_sha256(updated) != expected


@pytest.mark.parametrize("missing", ["condition", "effective_from"])
def test_unresolved_guard_draft_is_preserved_and_blocks_executable_conversion(missing):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = suspension_payload()
    raw["buy_suspension"][missing] = None
    draft = load_daily_draft_json(json.dumps(raw))
    assert type(draft) is BuySuspensionPlanDraft
    assert getattr(draft.buy_suspension, missing) is None
    assert draft.to_executable() is None
    assert load_daily_draft_json(daily_draft_json(draft)) == draft
    assert any(
        issue["path"] == "buy_suspension." + missing
        and issue["code"] == "PLAN_PARAMETER_REQUIRED" for issue in daily_draft_issues(draft)
    )
    with pytest.raises(ValidationError):
        BuySuspensionTradePlan.model_validate(raw)
    raw["buy_suspension"].pop(missing)
    with pytest.raises(ValidationError):
        BuySuspensionTradePlan.model_validate(raw)


@pytest.mark.parametrize("start", [
    "2026-09-30T09:31:00+08:00", "2026-09-30T09:30:01+08:00",
    "2026-09-30T09:30:00.000001+08:00", "2026-09-30T01:30:00Z",
    "2026-09-30T09:30:00", "2026-09-30", "2026-09-30T09:30:00+09:00",
])
def test_guard_start_requires_explicit_shanghai_five_minute_boundary(start):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = suspension_payload()
    raw["buy_suspension"]["effective_from"] = start
    for model in (BuySuspensionTradePlan, BuySuspensionPlanDraft):
        with pytest.raises(ValidationError):
            model.model_validate(raw)


@pytest.mark.parametrize("guard", [
    {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 1, "price_fen": 2420},
    {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 0},
    {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": True},
    {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 24.2},
    {"type": "MINUTE_CLOSE_IN_RANGE", "timeframe_minutes": 5, "low_fen": 2400,
     "high_fen": 2420, "include_low": True, "include_high": True},
])
def test_guard_has_only_the_existing_five_minute_below_predicate(guard):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = suspension_payload()
    raw["buy_suspension"]["condition"] = guard
    for model in (BuySuspensionTradePlan, BuySuspensionPlanDraft):
        with pytest.raises(ValidationError):
            model.model_validate(raw)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 5), ("execution_version", "condition-plan-v1"),
    ("execution_mode", "DAILY_CLOSE_PLAN"), ("reference_market", None),
])
def test_new_contract_rejects_mismatched_tuple_and_linked_top_level_fields(field, value):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = suspension_payload()
    raw[field] = value
    for model in (BuySuspensionTradePlan, BuySuspensionPlanDraft):
        with pytest.raises(ValidationError):
            model.model_validate(raw)


@pytest.mark.parametrize("payload", [linked_payload, exception_payload, p2_payload, p3_payload])
def test_new_contract_cannot_admit_extended_family_policies(payload):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = payload()
    raw.update(schema_version=10, execution_version="condition-plan-v6")
    raw["buy_suspension"] = suspension_payload()["buy_suspension"]
    for model in (BuySuspensionTradePlan, BuySuspensionPlanDraft):
        with pytest.raises(ValidationError):
            model.model_validate(raw)


@pytest.mark.parametrize("payload", [
    unified_payload, linked_payload, exception_payload, p2_payload, p3_payload,
])
def test_historical_families_keep_exact_payload_hash_and_reject_guard(payload):
    raw = payload()
    draft = load_daily_draft_json(json.dumps(raw))
    plan = draft.to_executable()
    assert plan is not None
    assert "buy_suspension" not in plan.model_dump(mode="json")
    assert "buy_suspension" not in draft.model_dump(mode="json")
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    domain = f"plan-review-content-v{plan.schema_version - 3}\x00".encode()
    expected = sha256(domain + json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert daily_draft_content_sha256(draft) == unified_plan_content_sha256(plan) == expected
    for guard in (None, suspension_payload()["buy_suspension"]):
        invalid = deepcopy(raw)
        invalid["buy_suspension"] = guard
        with pytest.raises(ValidationError):
            type(draft).model_validate(invalid)
        with pytest.raises(ValidationError):
            type(plan).model_validate(invalid)


@pytest.mark.parametrize("absent", [True, False])
def test_guard_absence_is_structural_only_and_does_not_infer_source_obligations(absent):
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

    raw = suspension_payload()
    if absent:
        raw.pop("buy_suspension")
    else:
        raw["buy_suspension"] = None
    plan = BuySuspensionTradePlan.model_validate(raw)
    assert plan.buy_suspension is None
    assert BuySuspensionPlanDraft.from_executable(plan).to_executable() == plan
    assert "buy_suspension" not in UnifiedTradePlan.model_fields
    assert "buy_suspension" not in UnifiedPlanDraft.model_fields
