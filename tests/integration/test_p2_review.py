"""P2 source review cannot infer omitted strategy or evidence authority."""

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p2_policy_contract import p2_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.domain.p2_validation import P2PlanDraft


def test_p2_exact_source_review_retains_all_market_expansions():
    draft = P2PlanDraft.model_validate(p2_payload())
    assert len([p for p in semantic_values(draft) if ".expanded." in p]) == 11
    source, mapping = source_mapping(draft)
    assert not build_daily_review(draft, mapping, source).issues


def test_omitted_p2_source_binding_blocks_review():
    draft = P2PlanDraft.model_validate(p2_payload())
    source, mapping = source_mapping(draft)
    path = "ordinary_rules[0].pretrade_policy.sizing.tiers[1].multiplier"
    mapping = mapping.model_copy(update={
        "bindings": tuple(b for b in mapping.bindings if b.path != path)})
    assert any(i.path == path and i.code == "DAILY_SOURCE_BINDING_REQUIRED"
               for i in build_daily_review(draft, mapping, source).issues)


@pytest.mark.parametrize("field", ["base_qty", "multiplier", "economics"])
def test_missing_p2_parameter_survives_as_null_but_cannot_execute(field):
    raw = p2_payload()
    policy = raw["ordinary_rules"][0]["pretrade_policy"]
    if field == "base_qty":
        policy["sizing"][field] = None
    elif field == "multiplier":
        policy["sizing"]["tiers"][0][field] = None
    else:
        policy[field] = None
    draft = P2PlanDraft.model_validate(raw)
    assert draft.to_executable() is None
    source, mapping = source_mapping(draft)
    assert any(i.code == "P2_PARAMETER_INVALID" for i in
               build_daily_review(draft, mapping, source).issues)


@pytest.mark.parametrize("value", ["0.1", "0.05"])
def test_decimal_semantic_binding_requires_the_actual_source_number(value):
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches

    draft = P2PlanDraft.model_validate(p2_payload())
    path = "ordinary_rules[0].pretrade_policy.sizing.tiers[0].upper"
    assert semantic_interpretation_matches(path, value, f"upper={value}", draft)
    assert not semantic_interpretation_matches(path, value, "threshold is unknown", draft)
    assert not semantic_interpretation_matches(path, value, "upper=0.2", draft)


def test_required_economics_needs_two_dimensions_and_bound_levels():
    from tests.unit.test_p2_economics import economics

    raw = p2_payload()
    raw["ordinary_rules"][0]["pretrade_policy"]["economics"] = economics()
    draft = P2PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    codes = {i.code for i in build_daily_review(draft, mapping, source).issues}
    assert "P2_LEVEL_EVIDENCE_REQUIRED" in codes
    assert "P2_LEVEL_REFERENCE_MISMATCH" in codes


@pytest.mark.parametrize(("target", "allowed"), [(190, True), (201, False)])
def test_explicit_target_must_bind_to_reviewed_pressure_range(target, allowed):
    from tests.integration.test_p2_chain import with_economics
    from tests.unit.test_p2_composition import fixture

    plan, _ = fixture(1000)
    raw = with_economics(plan).model_dump(mode="json")
    raw["ordinary_rules"][0]["pretrade_policy"]["economics"]["target_price_fen"] = target
    draft = P2PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    issues = build_daily_review(draft, mapping, source).issues
    assert any(i.code == "P2_LEVEL_REFERENCE_MISMATCH" for i in issues) is not allowed


def test_current_prompt_explicitly_preserves_p2_without_invented_authority():
    from trade_plan_monitor.ai.prompts import build_plan_extraction_prompt

    prompt = build_plan_extraction_prompt("A: volatility and fees. B: background only.")
    for required in ("schema_version=8", "pretrade-policy-v1", "ATR_RATIO_TIERS",
                     "PREVIEW_ONLY", "REQUIRED", "DERIVED_MARKET_FACTOR"):
        assert required in prompt


def test_followup_snapshot_keeps_p2_policy():
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
    from trade_plan_monitor.domain.p2_policy_models import P2TradePlan

    plan = P2TradePlan.model_validate(p2_payload())
    context = PlanUpdateContext.model_validate({"base_hash": "a" * 64,
        "snapshot": plan.model_dump(mode="json"), "available_at": "2026-09-18T15:05:00+08:00"})
    assert context.snapshot == plan


def test_p2_real_extraction_service_retains_policy_and_source():
    import asyncio
    from uuid import uuid4

    from tests.unit.test_ai_plan_extraction_v4 import _config

    from trade_plan_monitor.ai.extraction import extract_plan
    from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput
    from trade_plan_monitor.ai.provider import RawAIResponse
    candidate = P2PlanDraft.model_validate(p2_payload())
    source, mapping = source_mapping(candidate)
    output = CurrentPlanExtractionOutput(
        draft=candidate, clauses=mapping.clauses, bindings=mapping.bindings,
    )

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "plan-extract-v11"
            return RawAIResponse(request_id=request.request_id,
                provider_id=request.config.provider_id, model=request.config.model,
                content=output.model_dump_json(), finish_reason="stop", attempts=1, usage=None)

    # The synthetic source spells out every field; the separate default-budget
    # regression retains 50,000 for the user's real source fixture.
    result = asyncio.run(extract_plan(request_id=uuid4(), source_text=source,
        config=_config().model_copy(update={"max_input_chars": 200_000}), provider=Provider()))
    assert result.status == "SUCCEEDED"
    assert result.prompt_version == "plan-extract-v11"
    assert result.draft.schema_version == 8
    assert result.validation_issues == ()
