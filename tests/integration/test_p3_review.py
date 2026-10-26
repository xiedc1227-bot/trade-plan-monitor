"""Monetary limits need exact source meaning and cannot create opening costs."""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
from trade_plan_monitor.domain.p3_validation import P3PlanDraft


def test_schema9_draft_load_retains_exact_money_only_source_policy():
    draft = load_daily_draft_json(json.dumps(p3_payload()))
    assert isinstance(draft, P3PlanDraft) and draft.to_executable().schema_version == 9
    assert "max_qty" not in draft.position.model_dump()


@pytest.mark.parametrize("mode", ["OPEN_COST_CAP", "MARKET_VALUE_CAP"])
def test_complete_capital_review_retains_all_prior_strategy_expansions(mode):
    draft = P3PlanDraft.model_validate(p3_payload(mode))
    assert len([p for p in semantic_values(draft) if ".expanded." in p]) == 11
    source, mapping = source_mapping(draft)
    assert not build_daily_review(draft, mapping, source).issues
    assert "opening_cost" not in draft.model_dump_json()


def test_missing_cap_or_source_binding_cannot_be_acknowledged_away():
    raw = p3_payload()
    path = "position.limit.capital_policy.cap_fen"
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    changed = mapping.model_copy(update={"bindings": tuple(
        b for b in mapping.bindings if b.path != path)})
    assert any(i.path == path and i.code == "DAILY_SOURCE_BINDING_REQUIRED"
               for i in build_daily_review(draft, changed, source).issues)
    raw["position"]["limit"]["capital_policy"]["cap_fen"] = None
    missing = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(missing)
    assert any(i.code == "P3_PARAMETER_INVALID" for i in
               build_daily_review(missing, mapping, source).issues)


@pytest.mark.parametrize("mode,text,allowed", [
    ("OPEN_COST_CAP", "总投入预算", False),
    ("OPEN_COST_CAP", "持仓成本占用上限", True),
    ("OPEN_COST_CAP", "OPEN_COST_CAP", True),
    ("OPEN_COST_CAP", "不采用 OPEN_COST_CAP", False),
    ("OPEN_COST_CAP", "OPEN_COST_CAP means cumulative lifetime purchases", False),
    ("MARKET_VALUE_CAP", "持仓市值上限", True),
    ("MARKET_VALUE_CAP", "不采用 MARKET_VALUE_CAP", False),
])
def test_capital_mode_must_have_explicit_noncontradictory_source_meaning(mode, text, allowed):
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches

    draft = P3PlanDraft.model_validate(p3_payload(mode))
    assert semantic_interpretation_matches("position.limit.capital_policy.mode",
                                           mode, text, draft) is allowed


def test_fee_rate_source_must_match_exact_number_not_a_substring():
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches

    draft = P3PlanDraft.model_validate(p3_payload("OPEN_COST_CAP"))
    path = "position.limit.capital_policy.buy_cost_schedule.commission_rate"
    assert not semantic_interpretation_matches(path, "0", "commission_rate=0.03", draft)
    assert semantic_interpretation_matches(path, "0.0003", "佣金率0.03%", draft)


def test_current_extraction_prompt_declares_capital_scope_and_no_inferred_quantities():
    from trade_plan_monitor.ai.prompts import build_plan_extraction_prompt

    prompt = build_plan_extraction_prompt("Explicit source only")
    for value in ("plan-extract-v12", "capital-policy-v1", "CAPITAL_ONLY", "OPEN_COST_CAP",
                  "MARKET_VALUE_CAP", "schema_version=9", "no available-cash"):
        assert value in prompt


def test_followup_source_snapshot_preserves_money_only_policy():
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
    from trade_plan_monitor.domain.p3_policy_models import P3TradePlan

    plan = P3TradePlan.model_validate(p3_payload())
    context = PlanUpdateContext.model_validate(dict(base_hash="a"*64,
        snapshot=plan.model_dump(mode="json"), available_at="2026-10-26T10:00:00+08:00"))
    assert context.snapshot == plan


def test_real_current_extraction_produces_reviewed_capital_draft_without_authority():
    import asyncio
    from uuid import uuid4

    from tests.unit.test_ai_plan_extraction_v4 import _config

    from trade_plan_monitor.ai.extraction import extract_plan
    from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput
    from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse

    candidate = P3PlanDraft.model_validate(p3_payload())
    source, mapping = source_mapping(candidate)
    output = CurrentPlanExtractionOutput(draft=candidate, clauses=mapping.clauses,
                                          bindings=mapping.bindings)

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "plan-extract-v12"
            return RawAIResponse(request_id=request.request_id,
                provider_id=request.config.provider_id, model=request.config.model,
                content=output.model_dump_json(), finish_reason="stop", attempts=1,
                usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20))

    result = asyncio.run(extract_plan(request_id=uuid4(), source_text=source,
        config=_config().model_copy(update={"max_input_chars": 200000}), provider=Provider()))
    assert result.status == "SUCCEEDED" and result.draft.schema_version == 9
    assert result.validation_issues == ()
    from trade_plan_monitor.web.ai_service import _completed_extraction_view, _now
    now = _now()
    view = _completed_extraction_view(result=result, submitted_at=now, started_at=now,
                                     completed_at=now, diagnostic_status=None)
    assert view.status == "SUCCEEDED" and view.prompt_version == "plan-extract-v12"
