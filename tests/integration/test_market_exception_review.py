"""Real review boundaries for explicit per-occurrence permission, never grants."""

import json

import pytest
from pydantic import ValidationError
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_market_exception_contract import exception_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json


def draft():
    return load_daily_draft_json(json.dumps(exception_payload()))


def test_complete_exception_review_has_all_expanded_conditions_and_no_approval():
    candidate = draft()
    paths = [p for p in semantic_values(candidate) if ".expanded." in p]
    assert len(paths) == 11
    source, mapping = source_mapping(candidate)
    output = CurrentPlanExtractionOutput(
        draft=candidate, clauses=mapping.clauses, bindings=mapping.bindings,
    )
    assert not output.review(source).issues
    assert "approval_id" not in output.model_dump_json()
    missing = mapping.model_copy(update={
        "bindings": tuple(b for b in mapping.bindings if b.path not in paths),
    })
    assert any(i.code == "DAILY_SOURCE_BINDING_REQUIRED"
               for i in build_daily_review(candidate, missing, source).issues)


@pytest.mark.parametrize("key", ["weak_exception", "broken_exception", "authorization"])
def test_english_and_chinese_expanded_exception_meanings_are_source_bound(key):
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches
    from trade_plan_monitor.domain.market_linkage_definitions import (
        EXPANDED_EXCEPTION_POLICY,
        EXPANDED_EXCEPTION_POLICY_ZH,
    )

    path = "ordinary_rules[0].market_policy.expanded." + key
    value = EXPANDED_EXCEPTION_POLICY[key]
    for excerpt in (value, EXPANDED_EXCEPTION_POLICY_ZH[key]):
        assert semantic_interpretation_matches(path, value, excerpt, draft())
        assert not semantic_interpretation_matches(path, value, "Do not apply: " + excerpt, draft())
    assert not semantic_interpretation_matches(path, value, "market-linkage-v2", draft())


@pytest.mark.parametrize("prefix", ["不允许启用：", "Do not enable: "])
def test_negated_permission_cannot_be_bound_as_source_semantic(prefix):
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches

    assert not semantic_interpretation_matches(
        "ordinary_rules[0].market_policy.exception_routes.weak_minimum",
        "PER_OCCURRENCE", prefix + "PER_OCCURRENCE", draft(),
    )


def test_plan_permission_edit_requires_new_source_review():
    candidate = draft()
    source, mapping = source_mapping(candidate)
    raw = candidate.model_dump(mode="json")
    raw["ordinary_rules"][0]["market_policy"]["exception_routes"]["broken_strong"] = "DISABLED"
    changed = load_daily_draft_json(json.dumps(raw))
    with pytest.raises(ValueError, match="content changed"):
        build_daily_review(changed, mapping, source)


def test_extraction_cannot_inject_an_approval_record():
    candidate = draft()
    _, mapping = source_mapping(candidate)
    with pytest.raises(ValidationError):
        CurrentPlanExtractionOutput.model_validate(dict(
            draft=candidate, clauses=mapping.clauses, bindings=mapping.bindings,
            approval_id="invented", approved_quantity=100,
        ))


@pytest.mark.parametrize("origin", ["SOURCE", "SOURCE_SEMANTIC", "SOURCE_INTERPRETATION"])
@pytest.mark.parametrize("prefix", ["不允许启用 ", "Do not enable "])
def test_literal_source_cannot_bypass_negative_permission(origin, prefix):
    from trade_plan_monitor.ai.review import server_source_clauses

    candidate = draft()
    source, mapping = source_mapping(candidate)
    path = "ordinary_rules[0].market_policy.exception_routes.weak_minimum"
    source = source.replace(f'{path} = "PER_OCCURRENCE"',
                            f'{path} = {prefix}"PER_OCCURRENCE"')
    actual = server_source_clauses(source)
    assert len(actual) == len(mapping.clauses)
    ids = {old.clause_id: new.clause_id
           for old, new in zip(mapping.clauses, actual, strict=True)}
    mapping = mapping.model_copy(update={
        "clauses": tuple(old.model_copy(update=new.model_dump(
            include={"clause_id", "start", "end", "excerpt"}))
                         for old, new in zip(mapping.clauses, actual, strict=True)),
        "bindings": tuple(b.model_copy(update={
            "clause_ids": tuple(ids[i] for i in b.clause_ids),
            "origin": origin if b.path == path else b.origin,
        }) for b in mapping.bindings),
    })
    with pytest.raises(ValueError, match="exception permission"):
        build_daily_review(candidate, mapping, source)


def test_current_prompt_describes_explicit_exception_permission_without_grant():
    from trade_plan_monitor.ai.plan_extraction import build_current_plan_prompt

    prompt = build_current_plan_prompt("Review an explicitly source-defined exception plan.")
    assert "plan-extract-v10:" in prompt
    assert "schema_version=7/condition-plan-v3" in prompt
    assert "P1 exceptions always remain blocked" not in prompt
    assert "exception_routes" in prompt
    assert "not occurrence approval" in prompt


def test_real_extraction_service_returns_only_a_v10_reviewable_candidate():
    import asyncio
    from uuid import uuid4

    from tests.unit.test_ai_plan_extraction_v4 import _config

    from trade_plan_monitor.ai.extraction import extract_plan
    from trade_plan_monitor.ai.provider import RawAIResponse

    candidate = draft()
    source, mapping = source_mapping(candidate)
    output = CurrentPlanExtractionOutput(
        draft=candidate, clauses=mapping.clauses, bindings=mapping.bindings,
    )

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "plan-extract-v10"
            return RawAIResponse(request_id=request.request_id,
                provider_id=request.config.provider_id, model=request.config.model,
                content=output.model_dump_json(), finish_reason="stop", attempts=1, usage=None)

    # The synthetic source spells out every field; the separate default-budget
    # regression retains 50,000 for the user's real source fixture.
    result = asyncio.run(extract_plan(request_id=uuid4(), source_text=source,
        config=_config().model_copy(update={"max_input_chars": 200_000}), provider=Provider()))
    assert result.status == "SUCCEEDED"
    assert result.prompt_version == "plan-extract-v10"
    assert result.draft.schema_version == 7
    assert result.validation_issues == ()
