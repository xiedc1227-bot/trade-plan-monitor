"""Actual originals and unedited real responses complete the scoped review chain."""

import asyncio
import json
from pathlib import Path

import pytest
from tests.integration.test_generic_live_paraphrases import kwargs

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.preparation_repairs import correction_context, correction_feedback

FIXTURES = Path(__file__).parents[1] / 'fixtures/ai'


def _third_review():
    cases = json.loads((FIXTURES / 'generic-live-four-plan-chain.json').read_text('utf-8'))
    args = kwargs(cases[0])
    first = asyncio.run(extract_loop_plan(**args))
    review = build_initial_review(first.draft, first.daily_mapping, args['source'])
    reviews = [review]
    for case in cases[1:3]:
        args = kwargs(case)
        context = context_from_review(review, review.evidence_hash)
        result = asyncio.run(extract_plan_update(**args, context=context))
        review = materialize_extraction(review, context.base_hash, args['source'], result).review
        assert not review.issues
        reviews.append(review)
    return cases[-1]['source'], reviews


def test_actual_four_originals_retain_old_exit_and_do_not_apply_it_to_new_positions():
    source, reviews = _third_review()
    live = json.loads((FIXTURES / 'cohort-scope-live.json').read_text('utf-8'))
    context = context_from_review(reviews[-1], reviews[-1].evidence_hash)
    args = kwargs(dict(source=source, response=live['initial_response']))
    first = asyncio.run(extract_plan_update(**args, context=context))
    candidate = materialize_extraction(reviews[-1], context.base_hash, args['source'], first)
    assert candidate.review.issues == ('UPDATE_CHANGE_ASSESSMENT_REQUIRED',)
    assert not candidate.to_preparation_candidate().policy_ready
    feedback = correction_feedback(candidate.to_preparation_candidate())
    repair = correction_context(first)
    assert len(repair) <= 32000
    args = kwargs(dict(source=source, response=live['focused_response']))
    result = asyncio.run(extract_plan_update(**args, context=context,
                                           feedback=feedback, repair_context=repair))
    final = materialize_extraction(reviews[-1], context.base_hash, args['source'], result)
    prepared = final.to_preparation_candidate()
    assert prepared.policy_ready and not final.review.issues
    assert MaterializedUpdateCandidate.model_validate_json(prepared.payload_json) == final
    reviews.append(final.review)
    assert [r.draft.position.max_qty for r in reviews] == [300] * 4
    assert [len(r.draft.ordinary_rules) for r in reviews] == [1, 0, 1, 2]
    branch = final.review.draft.risk_branches[0]
    assert branch.holding_scope.model_dump(mode='json') == {
        'mode': 'BEFORE_TRADE_DATE', 'trade_date': '2026-10-09'}
    assert branch.target_core_qty == branch.target_tactical_qty == 0
    assert branch.suspension_confirmation_policy == 'RESUME_FIRST_CLOSE'
    assert final.review.draft.levels.risk_line_fen == 2599
    assert [r.quantity for r in final.review.draft.ordinary_rules] == [100, 100]
    assert final.review.draft.ordinary_rules[1].independent_signal.mode == 'AFTER_RULE_COMPLETED'
    assert next(c for c in final.review.changes if c.target == 'risk_branches').action == 'MODIFY'


def test_compact_candidate_cannot_be_valid_when_its_evidence_cannot_be_read():
    case = json.loads((FIXTURES / 'risk-scope-fourth-live.json').read_text('utf-8'))
    from trade_plan_monitor.ai.update_review import PlanCandidateReview
    base = PlanCandidateReview.model_validate_json(json.dumps(case['base_review']))
    live = json.loads((FIXTURES / 'cohort-scope-live.json').read_text('utf-8'))
    args = kwargs(dict(source=case['source'], response=live['oversized_prior_response']))
    context = context_from_review(base, 'a' * 64)
    result = asyncio.run(extract_plan_update(**args, context=context))
    materialized = materialize_extraction(base, context.base_hash, args['source'], result)
    with pytest.raises(ValueError, match='expansion exceeds byte limit'):
        materialized.to_preparation_candidate()
