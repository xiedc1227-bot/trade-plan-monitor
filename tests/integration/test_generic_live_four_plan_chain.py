"""Replay saved responses, rejecting the historically overbroad fourth-source withdrawal."""

import asyncio
import json
from pathlib import Path

from tests.integration.test_generic_live_paraphrases import kwargs

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.domain.unified_plan_models import condition_leaves
from trade_plan_monitor.web.result_rule_changes import compare_plan_values


def test_actual_four_source_chain_rejects_historical_fourth_source_risk_withdrawal():
    cases = json.loads(
        (Path(__file__).parents[1] / "fixtures/ai/generic-live-four-plan-chain.json").read_text(
            "utf-8"
        )
    )
    args = kwargs(cases[0])
    first = asyncio.run(extract_loop_plan(**args))
    review = build_initial_review(first.draft, first.daily_mapping, args["source"])
    assert not review.issues
    reviews = [review]
    for index, case in enumerate(cases[1:], start=1):
        args = kwargs(case)
        context = context_from_review(review, review.evidence_hash)
        result = asyncio.run(extract_plan_update(**args, context=context))
        materialized = materialize_extraction(review, context.base_hash, args["source"], result)
        candidate = materialized.to_preparation_candidate()
        if index < 3:
            assert candidate.policy_ready and not candidate.issues
        else:
            assert not candidate.policy_ready
            assert any(i.startswith("UPDATE_WITHDRAWAL_SCOPE_REQUIRED") for i in candidate.issues)
        assert (
            MaterializedUpdateCandidate.model_validate_json(candidate.payload_json) == materialized
        )
        review = materialized.review
        reviews.append(review)
    root, second, third, fourth = [r.draft for r in reviews]
    assert all(p.position.max_qty == 300 for p in (root, second, third, fourth))
    assert [len(p.ordinary_rules) for p in (root, second, third, fourth)] == [1, 0, 1, 2]
    assert root.ordinary_rules[0].quantity == 100
    assert second.risk_branches == third.risk_branches
    risk = second.risk_branches[0]
    assert risk.involves_core and risk.target_core_qty == risk.target_tactical_qty == 0
    assert risk.suspension_confirmation_policy == "RESUME_FIRST_CLOSE"
    assert fourth.risk_branches == third.risk_branches
    assert fourth.levels.risk_line_fen == 2599
    assert fourth.levels.risk_comparison == "LT"
    assert third.ordinary_rules[0].rule_id == fourth.ordinary_rules[0].rule_id
    assert all(r.quantity == 100 for r in fourth.ordinary_rules)
    assert fourth.ordinary_rules[1].independent_signal.mode == "AFTER_RULE_COMPLETED"
    assert (
        fourth.ordinary_rules[1].independent_signal.prior_rule_id
        == fourth.ordinary_rules[0].rule_id
    )
    for plan, comparator, lower in ((third, "GTE", 2550), (fourth, "GT", 2570)):
        leaves = condition_leaves(plan.ordinary_rules[0].condition)
        prior = next(c for c in leaves if c.type == "DAILY_PRIOR_CLOSE")
        assert prior.price_fen == 2599 and prior.comparator == comparator
        zone = next(c for c in leaves if c.type == "DAILY_PRICE_IN_RANGE")
        assert (zone.range.low_fen, zone.range.high_fen) == (lower, 2600)
    fourth_leaves = condition_leaves(fourth.ordinary_rules[0].condition)
    assert [c.fact_kind for c in fourth_leaves if c.type == "REVIEWED_FACT"] == ["PRICE_STRUCTURE"]
    actions = {change.action for r in reviews[1:] for change in r.changes}
    assert actions == {"RETAIN", "MODIFY", "ADD", "REVOKE"}

    # Compare candidate values only: the fourth candidate remains unapproved and
    # cannot be submitted to replay with its unresolved holding-scope restriction.
    snapshots = [r.draft.to_executable().model_dump(mode="json") for r in reviews]
    comparisons = [compare_plan_values(snapshots[i - 1] if i else None, plan)
                   for i, plan in enumerate(snapshots)]
    assert all(c.action == "ADD" for c in comparisons[0])
    second_changes = {(c.target, c.rule_id): c for c in comparisons[1]}
    assert second_changes["ordinary_rules", "first-tranche-100"].action == "REVOKE"
    third_changes = {(c.target, c.rule_id): c for c in comparisons[2]}
    assert third_changes["risk_branches", "ORDINARY_TECHNICAL"].action == "RETAIN"
    fourth_changes = {(c.target, c.rule_id): c for c in comparisons[3]}
    assert fourth_changes["risk_branches", "ORDINARY_TECHNICAL"].action == "RETAIN"
    assert fourth_changes["ordinary_rules", "stand-2640-retest-second-lot"].action == "ADD"
    first_lot = fourth_changes["ordinary_rules", "retest-2550-2600-hold-first-lot"]
    assert first_lot.action == "MODIFY"
    assert first_lot.before["quantity"] == first_lot.after["quantity"] == 100
