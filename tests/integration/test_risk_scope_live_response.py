"""Unedited actual AI response must retain, not discard, the new-position restriction."""

import asyncio
import json
from pathlib import Path

import pytest
from tests.integration.test_generic_live_paraphrases import kwargs

from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.update_review import (
    PlanCandidateReview,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.web.preparation_confirmations import confirmation_summary


def test_older_real_response_without_direction_requests_ai_correction_not_manual_facts():
    case = json.loads(
        (Path(__file__).parents[1] / "fixtures/ai/risk-scope-fourth-live.json").read_text("utf-8")
    )
    base = PlanCandidateReview.model_validate_json(json.dumps(case["base_review"]))
    context = context_from_review(base, "a" * 64)
    args = kwargs(case)
    result = asyncio.run(extract_plan_update(**args, context=context))
    materialized = materialize_extraction(base, context.base_hash, args["source"], result)
    review = materialized.review
    assert review.issues == ("UPDATE_SCOPE_DIRECTION_REQUIRED: risk_branches.ORDINARY_TECHNICAL",)
    # This older response also repeats enough source evidence to exceed the
    # stored-codec expansion budget. It must never be saved as a usable candidate.
    with pytest.raises(ValueError, match="candidate evidence expansion exceeds byte limit"):
        materialized.to_preparation_candidate()
    assert review.draft.risk_branches == base.draft.risk_branches
    assert review.draft.levels.risk_line_fen == 2599
    assert [rule.quantity for rule in review.draft.ordinary_rules] == [100, 100]
    assert review.draft.ordinary_rules[1].independent_signal.mode == "AFTER_RULE_COMPLETED"
    summary = confirmation_summary(args["source"], review.draft, result.output, review.issues)
    assert any(
        "提取处理问题" in message and "无需手工补填" in message
        for message in summary.processing_issues
    )
    assert not any(
        q.question_id in {"exit-policy", "exit-scope", "rule-inheritance", "risk-suspension"}
        for q in summary.questions
    )
