"""Updates preserve permission, while approvals remain outside plan data."""

import pytest
from tests.unit.test_market_exception_contract import exception_payload
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_plan_update_bindings import prior_review

from trade_plan_monitor.ai.plan_delta_wire import build_delta_prompt, expand_delta_output
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
from trade_plan_monitor.ai.preparation_wire import CompactPlanOutput, expand_compact_output
from trade_plan_monitor.ai.update_review import build_update_review, context_from_review
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
from trade_plan_monitor.domain.market_linkage_validation import parse_current_draft


def base_review():
    return prior_review(MarketExceptionTradePlan.model_validate(exception_payload()))


def test_context_roundtrip_keeps_exception_contract():
    context = context_from_review(base_review(), "a" * 64)
    restored = PlanUpdateContext.model_validate_json(context.model_dump_json())
    assert restored.snapshot == context.snapshot
    assert restored.snapshot.schema_version == 7


def test_delta_retains_permissions_and_bindings_without_grants():
    base = base_review()
    context = context_from_review(base, "a" * 64)
    source, output = delta("总持仓最多1000股。", values={"max_qty": 1000})
    assert "exception_routes" in build_delta_prompt(source, context)
    expanded = expand_compact_output(expand_delta_output(output, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert not review.issues
    assert review.draft.schema_version == 7
    assert review.draft.position.max_qty == 1000
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    for binding in base.bindings:
        if ".market_policy." in binding.path:
            assert binding in review.bindings
    assert "approval_id" not in review.draft.model_dump_json()


@pytest.mark.parametrize("permission", ["DISABLED", "PER_OCCURRENCE"])
def test_full_preparation_preserves_deliberate_permission(permission):
    raw = base_review().draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"]["weak_minimum"] = permission
    output = CompactPlanOutput.model_validate({"draft": raw})
    restored = parse_current_draft(output.draft.model_dump(mode="json"))
    assert restored.ordinary_rules[0].market_policy.exception_routes.weak_minimum == permission
    assert restored.schema_version == 7


def test_compact_copy_rejects_occurrence_authority():
    raw = base_review().draft.model_dump(mode="json")
    raw["approval_id"] = "foreign-approval"
    with pytest.raises(ValueError):
        CompactPlanOutput.model_validate({"draft": raw})


@pytest.mark.parametrize("old,new", [
    ("DISABLED", "PER_OCCURRENCE"), ("PER_OCCURRENCE", "DISABLED"),
])
def test_permission_change_changes_review_identity_and_requires_source(old, new):
    raw = exception_payload()
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"]["weak_minimum"] = old
    base = prior_review(MarketExceptionTradePlan.model_validate(raw))
    context = context_from_review(base, "a" * 64)
    source, output = delta(
        "总持仓最多1000股。", target="ordinary_rules",
        rule_id=base.draft.ordinary_rules[0].rule_id,
        values={"market_policy": {"exception_routes": {"weak_minimum": new}}},
    )
    expanded = expand_compact_output(expand_delta_output(output, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert review.issues  # An unrelated clause cannot authorize the changed permission.
    assert daily_draft_content_sha256(review.draft) != daily_draft_content_sha256(base.draft)


def test_missing_permission_stays_unresolved_in_preparation():
    raw = base_review().draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"]["weak_minimum"] = None
    output = CompactPlanOutput.model_validate({"draft": raw})
    assert parse_current_draft(output.draft.model_dump(mode="json")).to_executable() is None
