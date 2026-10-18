"""New patch semantics preserve prior authority without sentence templates."""

import json

import pytest
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_unified_preparation_updates import buy_and_sell_plan, revoke_update

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.update_review import build_update_review


def patch(output, *, intent="ASSERTED"):
    raw = output.model_dump(mode="json")
    raw["inheritance_mode"] = "PREDECESSOR_PATCH"
    for op in raw["operations"]:
        op.update(
            intent=intent, rationale="Current source specifies this change to the prior rule."
        )
    return PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "text",
    [
        "这次最大仓位定在300股。",
        "持仓总量上限采用300股。",
        "最大仓位300股。",
    ],
)
def test_unmentioned_rules_retain_exact_prior_evidence_without_restatement(text):
    source, output = current_update(text)
    base = prior_review()
    review = build_update_review(base, source, patch(output))
    assert review.issues == ()
    old = next(b for b in base.bindings if b.path == "ordinary_rules[0].quantity")
    assert next(b for b in review.bindings if b.path == old.path) == old
    assert review.draft.position.max_qty == 300


def test_null_without_current_binding_restores_predecessor_but_explicit_clear_does_not():
    from trade_plan_monitor.ai.predecessor_patch import restore_unmentioned_fields
    from trade_plan_monitor.ai.preparation_wire import EvidenceReference
    from trade_plan_monitor.ai.update_review import context_from_review

    base = prior_review(buy_and_sell_plan())
    context = context_from_review(base, "a" * 64)
    data = base.draft.model_dump(mode="json")
    data["position"]["max_qty"] = None
    restored = restore_unmentioned_fields(data, context, ())
    assert restored["position"]["max_qty"] == base.draft.position.max_qty
    assert data["position"]["max_qty"] is None
    explicit = restore_unmentioned_fields(
        data, context, (EvidenceReference(path="position.max_qty", clause_ids=("clause-one",)),)
    )
    assert explicit["position"]["max_qty"] is None


def test_null_restoration_matches_stable_identity_after_rule_reordering():
    from trade_plan_monitor.ai.predecessor_patch import restore_unmentioned_fields
    from trade_plan_monitor.ai.update_review import context_from_review

    base = prior_review(buy_and_sell_plan())
    data = base.draft.model_dump(mode="json")
    data["ordinary_rules"].reverse()
    for rule in data["ordinary_rules"]:
        rule["quantity"] = None
    restored = restore_unmentioned_fields(data, context_from_review(base, "a" * 64), ())
    assert [r["quantity"] for r in restored["ordinary_rules"]] == [
        200,
        base.draft.ordinary_rules[0].quantity,
    ]


def test_nonexistent_cancellation_target_is_processing_error_not_silent_success():
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, "撤下旧的入场指令。", rule_id="nonexistent")
    with pytest.raises(ValueError, match="predecessor identity"):
        build_update_review(prior_review(plan), source, patch(output))


def test_typed_condition_names_in_prose_require_automatic_correction():
    from trade_plan_monitor.ai.semantic_validation import semantic_representation_issues
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    data = prior_review().draft.model_dump(mode="json")
    data["ordinary_rules"][0]["condition"] = dict(
        type="REVIEWED_FACT",
        fact_kind="PRICE_STRUCTURE",
        validity_scope="TRADE_DATE",
        evidence_requirement="Use DAILY_CLOSE_SEQUENCE to check the preceding closes.",
    )
    draft = UnifiedPlanDraft.model_validate_json(json.dumps(data))
    assert semantic_representation_issues(draft) == (
        ("AI_COMPUTABLE_CONDITION_UNEXPANDED", "ordinary_rules[0].condition.evidence_requirement"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "上一版的买入安排就此作废。",
        "不再执行此前那笔买入。",
        "撤下旧的入场指令。",
    ],
)
def test_semantic_cancellation_needs_citations_and_identity_not_internal_name_or_verb(text):
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, text)
    review = build_update_review(prior_review(plan), source, patch(output))
    assert review.issues == ()
    assert [r.side for r in review.draft.ordinary_rules] == ["SELL"]
    assert any(c.action == "REVOKE" for c in review.changes)


def test_ambiguous_semantic_target_is_not_treated_as_a_confirmed_cancellation():
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, "其中一笔先不要做，具体哪笔稍后确定。")
    review = build_update_review(prior_review(plan), source, patch(output, intent="AMBIGUOUS"))
    assert "UPDATE_SOURCE_AMBIGUITY" in review.issues


def test_patch_does_not_bypass_value_evidence():
    source, output = current_update("最大仓位300股。")
    raw = patch(output).model_dump(mode="json")
    raw["draft"]["position"]["max_qty"] = 500
    raw["bindings"][0]["value"] = 500
    with pytest.raises(ValueError, match="source value"):
        build_update_review(
            prior_review(), source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
        )


def test_unchanged_rule_proposed_as_modified_is_retained_with_original_evidence():
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, "这一笔买入照原安排执行。")
    raw = patch(output).model_dump(mode="json")
    raw["operations"][0]["action"] = "MODIFY"
    base = prior_review(plan)
    review = build_update_review(
        base, source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    )
    assert review.issues == ()
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert review.changes[0].action == "RETAIN"


def test_modified_rule_keeps_unchanged_fields_and_exact_prior_provenance():
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, "买入数量改为200股。")
    raw = patch(output).model_dump(mode="json")
    raw["operations"][0]["action"] = "MODIFY"
    raw["draft"]["ordinary_rules"][0]["quantity"] = 200
    raw["bindings"] = [
        dict(
            path="ordinary_rules[0].quantity",
            value=200,
            origin="SOURCE",
            unit="SHARES",
            clause_ids=raw["operations"][0]["clause_ids"],
            supplement_id=None,
        )
    ]
    raw["clauses"][0].update(disposition="POLICY", paths=["ordinary_rules[0].quantity"])
    base = prior_review(plan)
    review = build_update_review(
        base, source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    )
    assert review.issues == ()
    assert review.draft.ordinary_rules[0].quantity == 200
    old = next(b for b in base.bindings if b.path == "ordinary_rules[0].side")
    assert next(b for b in review.bindings if b.path == old.path) == old
