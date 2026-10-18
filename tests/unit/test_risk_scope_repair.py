"""Focused AI corrections repair representation without inventing risk authority."""

import json
from copy import deepcopy
from datetime import date

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_risk_withdrawal_scope import baseline

from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.risk_scope_repair import (
    RiskApplicabilityAssessment,
    RiskScopeCorrection,
    apply_scope_correction,
    focused_prior,
)
from trade_plan_monitor.ai.update_review import build_update_review, context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.backtest.preparation_repairs import correction_context
from trade_plan_monitor.domain.risk_scope import risk_identity


def _case(text="旧持仓继续执行原风险退出，新开仓位不适用该风险线。"):
    base = baseline()
    context = context_from_review(base, "a" * 64)
    identity = risk_identity(context.snapshot.risk_branches[0])
    _, wire = delta(text, target="risk_branches", rule_id=identity, action="RETAIN")
    wire = wire.model_copy(update={
        "schema_version": "monitor-loop-delta-wire-v4",
        "operations": tuple(op.model_copy(update={
            "scope_assessment": "PARTIAL_RULE", "intent": "CONTEXT",
        }) for op in wire.operations),
    })
    source = PreparationSource(
        source_id="risk-scope-repair", text=text, effective_trade_date=date(2026, 10, 9),
    )
    output = expand_compact_output(expand_delta_output(wire, context), source, context=context)
    encoded = correction_context(output)
    assert encoded is not None
    return base, source, context, json.loads(encoded)


def _assessment(prior, identity="ORDINARY_TECHNICAL", *, existing="UNCHANGED", new="EXCLUDED"):
    return RiskApplicabilityAssessment(
        rule_id=identity, existing_positions=existing, new_positions=new,
        clause_ids=tuple(prior["clause_groups"][0]["clause_ids"]),
        rationale="Existing positions inherit the reviewed rule; new positions are excluded.",
    )


def _correction(*assessments):
    return RiskScopeCorrection(
        schema_version="monitor-loop-risk-scope-correction-v1", assessments=assessments,
    )


@pytest.mark.parametrize("feedback", [
    ("UPDATE_SCOPE_DIRECTION_REQUIRED: risk_branches.ORDINARY_TECHNICAL",),
    ("UPDATE_CHANGE_ASSESSMENT_REQUIRED: risk_branches.ORDINARY_TECHNICAL",),
    ("UPDATE_WITHDRAWAL_SCOPE_REQUIRED: risk_branches.ORDINARY_TECHNICAL",
     "UPDATE_WITHDRAWAL_CONTEXT_ONLY: risk_branches.ORDINARY_TECHNICAL"),
])
def test_only_scope_processing_feedback_with_reusable_bindings_selects_focused_repair(feedback):
    _, _, _, prior = _case()

    assert focused_prior(feedback, json.dumps(prior)) == prior

    without_bindings = {key: value for key, value in prior.items() if key != "binding_groups"}
    assert focused_prior(feedback, json.dumps(without_bindings)) is None


@pytest.mark.parametrize("feedback", [
    (),
    ("UPDATE_SOURCE_AMBIGUITY: risk_branches.ORDINARY_TECHNICAL",),
    ("SOURCE_CONTENT_AMBIGUOUS: clauses[0]",),
    ("PLAN_PARAMETER_REQUIRED: position.max_qty",),
    ("UPDATE_SCOPE_DIRECTION_REQUIRED: risk_branches.ORDINARY_TECHNICAL",
     "UPDATE_SOURCE_AMBIGUITY: risk_branches.ORDINARY_TECHNICAL"),
])
def test_genuine_ambiguity_or_other_missing_parameters_never_select_focused_repair(feedback):
    _, _, _, prior = _case()

    assert focused_prior(feedback, json.dumps(prior)) is None


def test_invalid_output_retry_requires_an_explicit_prior_scope_correction_marker():
    _, _, _, prior = _case()
    feedback = ("AI_OUTPUT_INVALID",)
    assert prior["risk_scope_correction"] is True
    assert focused_prior(feedback, json.dumps(prior)) == prior

    prior["risk_scope_correction"] = False

    assert focused_prior(feedback, json.dumps(prior)) is None


def test_subset_matrix_keeps_old_rule_and_preserves_unrelated_and_new_risk_operations():
    _, _, context, prior = _case()
    clause_ids = prior["clause_groups"][0]["clause_ids"]
    position = dict(target="position", action="MODIFY", clause_ids=clause_ids,
                    intent="ASSERTED", rationale="Synthetic explicit maximum change.")
    new = dict(target="risk_branches", action="ADD", rule_id="new-position-risk",
               clause_ids=clause_ids, intent="ASSERTED",
               rationale="Synthetic explicitly authorized new-position rule.")
    prior["operations"].extend((position, new))
    new_branch = deepcopy(prior["draft"]["risk_branches"][0])
    new_branch["rule_id"] = "new-position-risk"
    prior["draft"]["risk_branches"].append(new_branch)
    prior["draft"]["position"]["max_qty"] = 500

    corrected = apply_scope_correction(_correction(_assessment(prior)), prior, context)

    old = next(op for op in corrected.operations if op.rule_id == "ORDINARY_TECHNICAL")
    assert old.action == "RETAIN"
    assert old.intent == "ASSERTED"
    assert old.scope_assessment == "PARTIAL_RULE"
    assert old.scope_change == "EXISTING_POSITIONS_ONLY"
    assert next(op for op in corrected.operations if op.target == "position").model_dump(
        mode="json", exclude_none=True
    ) == position
    assert next(op for op in corrected.operations if op.rule_id == "new-position-risk").model_dump(
        mode="json", exclude_none=True
    ) == new
    assert corrected.draft.position.max_qty == 500
    assert any(branch.rule_id == "new-position-risk" for branch in corrected.draft.risk_branches)


@pytest.mark.parametrize("invalid", ["unknown", "duplicate", "missing"])
def test_every_predecessor_identity_must_be_assessed_exactly_once(invalid):
    _, _, context, prior = _case()
    if invalid == "unknown":
        assessments = (_assessment(prior, "unknown-risk"),)
    elif invalid == "duplicate":
        assessments = (_assessment(prior), _assessment(prior))
    else:
        extra = context.snapshot.risk_branches[0].model_copy(update={"rule_id": "another-risk"})
        snapshot = context.snapshot.model_copy(update={
            "risk_branches": (*context.snapshot.risk_branches, extra),
        })
        context = context.model_copy(update={"snapshot": snapshot})
        assessments = (_assessment(prior),)

    with pytest.raises(ValueError, match="predecessor risk applicability assessment required"):
        apply_scope_correction(_correction(*assessments), prior, context)


def test_unclear_source_scope_remains_unapproved_after_focused_matrix_correction():
    base, source, context, prior = _case("风险规则对哪些仓位适用仍无法确定。")
    corrected = apply_scope_correction(
        _correction(_assessment(prior, existing="UNCLEAR", new="UNCLEAR")), prior, context,
    )
    operation = corrected.operations[0]
    assert operation.intent == "AMBIGUOUS"
    assert operation.scope_assessment == "UNCLEAR"
    assert operation.scope_change is None

    output = expand_compact_output(corrected, source, context=context)
    review = build_update_review(base, source, output)

    assert not review.to_preparation_candidate().policy_ready
    assert any("AMBIGU" in issue for issue in review.issues)
    assert review.draft.risk_branches == base.draft.risk_branches
    assert review.draft.levels.risk_line_fen == base.draft.levels.risk_line_fen


def test_asserted_matrix_cannot_erase_prior_genuine_source_ambiguity():
    base, source, context, prior = _case("风险规则对哪些仓位适用仍无法确定。")
    for group in prior["clause_groups"]:
        group.update(
            meaning="AMBIGUOUS", disposition="UNRESOLVED",
            reason="The source genuinely leaves its holding scope unresolved.",
        )
    corrected = apply_scope_correction(_correction(_assessment(prior)), prior, context)

    output = expand_compact_output(corrected, source, context=context)
    review = build_update_review(base, source, output)

    assert not review.to_preparation_candidate().policy_ready
    assert any("AMBIGU" in issue for issue in review.issues)
