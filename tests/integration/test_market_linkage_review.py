import pytest
from tests.unit.test_market_linkage_contract import linked_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
from trade_plan_monitor.domain.market_linkage_validation import MarketLinkedPlanDraft


def source_mapping(draft):
    import json

    from trade_plan_monitor.ai.daily_review import DailyMapping
    from trade_plan_monitor.ai.review import server_source_clauses
    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

    values = semantic_values(draft)
    source = "\n".join(
        f"{path} = {json.dumps(value, ensure_ascii=False)}" for path, value in values.items()
    )
    clauses = server_source_clauses(source)
    by_path = {}
    cursor = 0
    for path, line in zip(values, source.splitlines(), strict=True):
        by_path[path] = tuple(c for c in clauses if cursor <= c.start < cursor + len(line))
        cursor += len(line) + 1
    return source, DailyMapping.model_validate(
        dict(
            mapping_version="daily-mapping-v1",
            candidate_content_hash=daily_draft_content_sha256(draft),
            supplements=[],
            clauses=[
                dict(c.model_dump(), disposition="POLICY", paths=[path], reason="Exact fixture")
                for path, group in by_path.items()
                for c in group
            ],
            bindings=[
                dict(
                    path=path,
                    value=value,
                    origin="SOURCE_SEMANTIC"
                    if value is None or type(value) is bool or ".expanded." in path
                    else "SOURCE",
                    unit="JSON",
                    clause_ids=[c.clause_id for c in by_path[path]],
                    supplement_id=None,
                )
                for path, value in values.items()
            ],
        )
    )


def test_linked_review_binds_expanded_policy_and_quantity():
    draft = MarketLinkedPlanDraft.from_executable(
        MarketLinkedTradePlan.model_validate(linked_payload())
    )
    values = semantic_values(draft)
    expanded = [path for path in values if ".market_policy.expanded." in path]
    assert len(expanded) >= 6
    source, mapping = source_mapping(draft)
    review = build_daily_review(draft, mapping, source)
    assert not review.issues
    missing = mapping.model_copy(
        update={"bindings": tuple(b for b in mapping.bindings if b.path not in expanded)}
    )
    assert any(
        i.code == "DAILY_SOURCE_BINDING_REQUIRED"
        for i in build_daily_review(draft, missing, source).issues
    )


def test_policy_edit_invalidates_old_review():
    draft = MarketLinkedPlanDraft.from_executable(
        MarketLinkedTradePlan.model_validate(linked_payload())
    )
    source, mapping = source_mapping(draft)
    raw = draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = 400
    changed = MarketLinkedPlanDraft.model_validate(raw)
    with pytest.raises(ValueError, match="content changed"):
        build_daily_review(changed, mapping, source)


@pytest.mark.parametrize("prefix", ["不采用以下定义：", "Do not apply this definition: "])
def test_negated_expanded_definition_is_not_source_authority(prefix):
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches
    from trade_plan_monitor.domain.market_linkage_definitions import EXPANDED_LINKAGE_POLICY

    draft = MarketLinkedPlanDraft.from_executable(
        MarketLinkedTradePlan.model_validate(linked_payload()))
    value = EXPANDED_LINKAGE_POLICY["s1"]
    assert not semantic_interpretation_matches(
        "ordinary_rules[0].market_policy.expanded.s1", value, prefix + value, draft)


def test_extraction_accepts_linkage_without_creating_human_authority():
    from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput

    draft = MarketLinkedPlanDraft.from_executable(
        MarketLinkedTradePlan.model_validate(linked_payload())
    )
    source, mapping = source_mapping(draft)
    output = CurrentPlanExtractionOutput(
        draft=draft, clauses=mapping.clauses, bindings=mapping.bindings
    )
    assert output.draft.schema_version == 6
    assert not output.review(source).issues


def test_followup_delta_preserves_complete_linked_policy_and_its_source_bindings():
    from tests.unit.test_plan_delta_wire import delta
    from tests.unit.test_plan_update_bindings import prior_review

    from trade_plan_monitor.ai.plan_delta_wire import build_delta_prompt, expand_delta_output
    from trade_plan_monitor.ai.preparation_wire import expand_compact_output
    from trade_plan_monitor.ai.update_review import build_update_review, context_from_review

    plan = MarketLinkedTradePlan.model_validate(linked_payload())
    base = prior_review(plan)
    context = context_from_review(base, "a"*64)
    source, output = delta("总持仓最多1000股。", values={"max_qty": 1000})
    prompt = build_delta_prompt(source, context)
    assert "DraftQuantityPolicy" in prompt and "base_quantity" in prompt
    expanded = expand_compact_output(expand_delta_output(output, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert not review.issues
    assert review.draft.schema_version == 6
    assert review.draft.position.max_qty == 1000
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    for binding in base.bindings:
        if ".market_policy." in binding.path or ".quantity_policy." in binding.path:
            assert binding in review.bindings
