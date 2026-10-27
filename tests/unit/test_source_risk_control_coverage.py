"""Risk control coverage proves exact cohort leaves and preserves every other meaning."""

import json
from datetime import date

import pytest
from tests.unit.test_source_change_scopes import _replace_parent
from tests.unit.test_source_control_changes import _assess
from tests.unit.test_source_risk_control_integration import _case
from tests.unit.test_source_risk_controls import _json, _parent

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateOperation
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_controls import parse_source_controls
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_human_change_assurance import assess_human_change_current
from trade_plan_monitor.ai.source_risk_control_models import SourceRiskControlAnalysis
from trade_plan_monitor.ai.source_risk_controls import parse_source_risk_controls
from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationItemReview,
)
from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand


def test_exact_risk_control_proves_only_the_full_matching_holding_scope_leaves():
    source, output, _, _, _, base, parent, _ = _case()
    risk = parse_source_risk_controls(source, base, parent)
    result = analyze_source(output.draft, output.review(source.text).mapping, source.text,
                            risk_controls=risk)

    assert result.issues == () and result.authority_granted is False
    assert set(result.proven_paths) == {
        "risk_branches[0].holding_scope.mode", "risk_branches[0].holding_scope.trade_date"}
    assert all(row.scope == "RISK" and row.state == "MAPPED" for row in result.obligations)
    assert all(set(row.paths) == set(result.proven_paths) for row in result.obligations)
    assert all(json.loads(row.semantics_json)["source_risk_control"] == (
        risk.controls[0].model_dump(mode="json")) for row in result.obligations)
    assert {row.clause_id for row in result.obligations} == {
        identity for identities in result.proven_paths.values() for identity in identities}


@pytest.mark.parametrize("problem", ["hash", "length", "control-excerpt", "unknown-excerpt"])
def test_private_risk_analysis_must_match_exact_source_hash_length_and_all_spans(problem):
    case = _case(_json() + "\nEverything else depends on the blue lantern.")
    source, output, _, _, _, base, parent, _ = case
    original = parse_source_risk_controls(source, base, parent)
    values = {name: getattr(original, name) for name in type(original).model_fields
              if name != "evidence_hash"}
    if problem == "hash":
        values |= dict(source_hash="f" * 64,
            controls=tuple(type(row).build(**({name: getattr(row, name)
                for name in type(row).model_fields if name != "control_id"}
                | {"source_hash": "f" * 64})) for row in original.controls),
            unresolved=tuple(row.model_copy(update={"source_hash": "f" * 64})
                             for row in original.unresolved))
    elif problem == "length":
        values["source_length"] += 1
    elif problem == "control-excerpt":
        row = original.controls[0]
        values["controls"] = (type(row).build(**(
            {name: getattr(row, name) for name in type(row).model_fields if name != "control_id"}
            | {"excerpt": "x" * len(row.excerpt)})),)
    else:
        row = original.unresolved[0]
        values["unresolved"] = (row.model_copy(update={"excerpt": "x" * len(row.excerpt)}),)
    damaged = SourceRiskControlAnalysis.build(**values)

    with pytest.raises(ValueError):
        analyze_source(output.draft, output.review(source.text).mapping, source.text,
                       risk_controls=damaged)


@pytest.mark.parametrize("text,direction", [
    ("旧持仓继续执行风险规则ORDINARY_TECHNICAL，新开仓位不适用该规则。",
     "EXISTING_POSITIONS_ONLY"),
    ("Risk rule ORDINARY_TECHNICAL continues for existing lots; exclude new holdings.",
     "EXISTING_POSITIONS_ONLY"),
    ("新开仓位继续执行风险规则ORDINARY_TECHNICAL，旧持仓不适用该规则。",
     "NEW_POSITIONS_ONLY"),
    ("Risk rule ORDINARY_TECHNICAL continues for new holdings; exclude existing lots.",
     "NEW_POSITIONS_ONLY"),
    (_json(direction="NEW_POSITIONS_ONLY"), "NEW_POSITIONS_ONLY"),
])
def test_registered_scope_forms_preserve_all_non_scope_policy(text, direction):
    case = _case(text, direction=direction)
    assert case[2].review.issues == ()
    result = _assess(case)

    assert result.coverage_complete, result.source_assessment.issues
    before, after = case[5].draft.risk_branches[0], case[2].review.draft.risk_branches[0]
    assert after.model_dump(mode="json", exclude={"holding_scope"}) == before.model_dump(
        mode="json", exclude={"holding_scope"})
    assert after.holding_scope.mode == (
        "BEFORE_TRADE_DATE" if direction == "EXISTING_POSITIONS_ONLY" else "FROM_TRADE_DATE")
    assert all("holding_scope." in path for path in result.source_assessment.changed_paths)


@pytest.mark.parametrize("scope,direction", [
    ({"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-25"}, "EXISTING_POSITIONS_ONLY"),
    ({"mode": "FROM_TRADE_DATE", "trade_date": "2026-10-25", "end_trade_date": "2026-11-01"},
     "NEW_POSITIONS_ONLY"),
])
def test_restrictions_intersect_previous_scope_and_exact_noop_has_source_linked_retention(
    scope, direction,
):
    case = _case(scope=scope, direction=direction)
    assert case[2].review.issues == ()
    result = _assess(case)

    assert result.coverage_complete, result.source_assessment.issues
    operation = next(row for row in result.source_assessment.operations
                     if row.target == "risk_branches" and row.rule_id == "ORDINARY_TECHNICAL")
    assert operation.obligation_ids and operation.origin == "SOURCE"
    if direction == "EXISTING_POSITIONS_ONLY":
        assert operation.action == "RETAIN" and operation.changed_paths == ()
        assert case[2].review.draft.risk_branches[0].holding_scope.model_dump(mode="json") == scope
    else:
        scope = case[2].review.draft.risk_branches[0].holding_scope
        assert scope.trade_date == date(2026, 10, 27) and scope.end_trade_date == date(2026, 11, 1)


@pytest.mark.parametrize("problem", [
    "partial-as-whole-revoke", "enlarged-scope", "wrong-date", "unapplied", "other-field",
    "wrong-id", "wrong-target", "retain-as-revoke",
])
def test_ai_operation_cannot_replace_or_expand_the_full_independent_source_control(problem):
    options = {}
    text = _json()
    if problem == "partial-as-whole-revoke":
        options["action"] = "REVOKE"
    elif problem == "enlarged-scope":
        options |= dict(proposed_scope=None, direction_claim=False)
    elif problem == "wrong-date":
        options |= dict(proposed_scope={"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-28"},
                        direction_claim=False)
    elif problem == "unapplied":
        options["no_operations"] = True
    elif problem == "other-field":
        text += '\nrisk_branches[0].risk_line_fen = 1234\nrisk_branches[0].risk_comparison = "LT"'
        options["other_update"] = {"risk_line_fen": 1234, "risk_comparison": "LT"}
    elif problem == "wrong-id":
        text = _json(rule_id="SEVERE_TECHNICAL")
    elif problem == "wrong-target":
        base, _ = _parent()
        text = 'operations[0] = ' + json.dumps(dict(target="ordinary_rules",
            rule_id=base.draft.ordinary_rules[0].rule_id, action="RETAIN"))
    else:
        text, options["action"] = _json("RETAIN"), "REVOKE"
    case = _case(text, **options)
    assert case[2].review.issues == (), case[2].review.issues

    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert result.authority_granted is False


@pytest.mark.parametrize("suffix", [
    "Everything else depends on the blue lantern.", "Only buy when turnover exceeds 3 percent.",
])
def test_unknown_remainder_survives_the_exact_risk_control_and_still_blocks(suffix):
    case = _case(_json() + "\n" + suffix)
    assert case[2].review.issues == ()
    result = _assess(case)
    assert not result.coverage_complete
    assert any(row.scope == "RISK" and row.state == "MAPPED"
               for row in result.source_assessment.obligations)
    assert any(row.excerpt == suffix and row.scope == "UNKNOWN" and row.state == "UNRESOLVED"
               for row in result.source_assessment.obligations)


def test_background_risk_control_does_not_authorize_a_new_policy():
    case = _case("B. Background\n" + _json())
    assert case[2].review.issues == ()
    result = _assess(case)
    assert not result.coverage_complete and result.source_assessment.issues


@pytest.mark.parametrize("ordinal,complete", [(0, False), (1, True)])
def test_cross_registry_ordinals_cannot_authorize_two_operations(ordinal, complete):
    base, _ = _parent()
    identifier = base.draft.ordinary_rules[0].rule_id
    ordinary = f"operations[{ordinal}] = " + json.dumps(dict(target="ordinary_rules",
        rule_id=identifier, action="RETAIN"))
    text = _json() + "\n" + ordinary
    start = text.index(ordinary)
    ids = tuple(row.clause_id for row in server_source_clauses(text) if row.start >= start)
    extra = PlanUpdateOperation(target="ordinary_rules", rule_id=identifier, action="RETAIN",
        clause_ids=ids, intent="ASSERTED", rationale="Exact independent ordinary retention")
    case = _case(text, extra_operation=extra)
    assert case[2].review.issues == ()

    result = _assess(case)

    assert result.coverage_complete is complete, result.source_assessment.issues
    if not complete:
        controls = [row for row in result.source_assessment.obligations
                    if json.loads(row.semantics_json or "{}").get("treatment") in {
                        "REGISTERED_SOURCE_CONTROL", "REGISTERED_SOURCE_RISK_CONTROL"}]
        assert controls and all(row.state == "CONFLICT" for row in controls)
        assert any(row.code == "SOURCE_RELATION_MISMATCH"
                   for row in result.source_assessment.issues)


@pytest.mark.parametrize("ordinal,complete", [(0, False), (1, True)])
def test_bold_ordinary_json_after_plain_risk_json_preserves_joint_operation_ordinals(
    ordinal, complete,
):
    base, parent = _parent()
    identifier = base.draft.ordinary_rules[0].rule_id
    ordinary = "**" + f"operations[{ordinal}] = " + json.dumps(dict(
        target="ordinary_rules", rule_id=identifier, action="RETAIN")) + "**"
    text = _json() + "\n" + ordinary
    start = text.index(ordinary)
    ids = tuple(row.clause_id for row in server_source_clauses(text) if row.start >= start)
    extra = PlanUpdateOperation(target="ordinary_rules", rule_id=identifier, action="RETAIN",
        clause_ids=ids, intent="ASSERTED", rationale="Exact independent ordinary retention")
    case = _case(text, extra_operation=extra)
    source = case[0]
    regular = parse_source_controls(source, base, parent)
    risk = parse_source_risk_controls(source, base, parent)
    assert len(regular.controls) == len(risk.controls) == 1
    assert regular.controls[0].excerpt == ordinary
    assert regular.controls[0].grammar_id == "EXACT_OPERATION_JSON_V1"
    assert risk.controls[0].excerpt == _json()
    assert regular.issues == risk.issues == ()
    assert case[2].review.issues == () and len(case[3].derivation.stages) == 3

    result = _assess(case)

    assert result.coverage_complete is complete, result.source_assessment.issues
    if not complete:
        rows = result.source_assessment.obligations
        assert rows and all(row.state == "CONFLICT" for row in rows)
        assert {json.loads(row.semantics_json)["treatment"] for row in rows} == {
            "REGISTERED_SOURCE_CONTROL", "REGISTERED_SOURCE_RISK_CONTROL"}
        assert any(row.code == "SOURCE_RELATION_MISMATCH"
                   for row in result.source_assessment.issues)


def test_recognized_risk_control_without_raw_provider_evidence_still_blocks():
    case = list(_case())
    case[3] = None
    case[7] = case[7].model_copy(update={"inputs_hash": None})
    result = _assess(tuple(case))
    assert not result.coverage_complete
    assert any(row.code == "SOURCE_NORMALIZATION_LOSS" for row in result.source_assessment.issues)


def test_old_zero_issue_parent_cannot_lend_current_risk_control_authority_when_incomplete():
    case = list(_case())
    assert case[5].issues == ()
    case[6] = _replace_parent(case[6], issues=(CoverageIssue(
        code="SOURCE_COVERAGE_REQUIRED", message="An original parent requirement is unproven"),))

    result = _assess(tuple(case))

    assert not result.coverage_complete and not result.source_assessment.parent_verified
    assert not any(json.loads(row.semantics_json or "{}").get("treatment") == (
        "REGISTERED_SOURCE_RISK_CONTROL") for row in result.source_assessment.obligations)
    assert result.source_assessment.issues


def test_same_canonical_clause_risk_control_cannot_swallow_a_following_unknown_sentence():
    control = "Risk rule ORDINARY_TECHNICAL continues for existing lots; exclude new holdings."
    unknown = "Every risk exit must also wait for the blue lantern."
    case = _case(control + " " + unknown)
    assert case[2].review.issues == ()
    result = _assess(case)

    assert not result.coverage_complete
    assert any(row.scope == "RISK" and row.state == "MAPPED"
               for row in result.source_assessment.obligations)
    rows = [row for row in result.source_assessment.obligations if row.scope == "UNKNOWN"]
    assert any(row.excerpt.strip() == unknown and row.state == "UNRESOLVED" for row in rows)
    assert all(case[0].text[row.start:row.end] == row.excerpt for row in rows)


@pytest.mark.parametrize("mismatch", [False, True], ids=["exact-human", "wrong-human-after"])
def test_human_shared_core_obeys_the_same_full_risk_control_without_claiming_ai_fidelity(mismatch):
    options = {} if not mismatch else dict(proposed_scope=None, direction_claim=False)
    source, output, materialized, _, context, base, parent, binding = _case(**options)
    reviewed = materialized.review
    assert reviewed.issues == ()
    mapping = output.review(source.text).mapping
    # A real server checkpoint codec represents missing original INPUT, not a
    # fabricated AI response/preimage. Actual SQL registration is tested by its adapter.
    checkpoint = PlanCandidateReview(source_id=source.source_id, source_hash=source.binding_hash,
        available_at=source.execution_available_at, draft=base.draft, bindings=(),
        issues=("SOURCE_REASSESSMENT_REQUIRED: original risk delta",))
    before = CollectionPreparationCandidate(**checkpoint.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=context.base_hash)
    after = CollectionPreparationCandidate(**reviewed.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=context.base_hash)
    binding = binding.model_copy(update=dict(candidate_revision=2, inputs_hash=None,
                                             candidate_hash=after.candidate_hash))
    prefix = (PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash),)
    command = CollectionItemCorrectionCommand(expected_revision=7,
        binding=PreparationItemReview(source_id=source.source_id, source_revision=1,
            candidate_revision=1, candidate_hash=before.candidate_hash,
            evidence_hash=before.evidence_hash, base_hash=context.base_hash),
        update=output, mapping=mapping, confirmed=True,
        evidence="Exact synthetic manual risk control reassessment")
    operation = PreparationHumanOperation.build(preparation_id=binding.preparation_id,
        item_index=binding.item_index, operation="CORRECT_ITEM", source=source, source_revision=1,
        before_revision=7, after_revision=8, before_candidate_revision=1,
        before_candidate_hash=before.candidate_hash, before_evidence_hash=before.evidence_hash,
        after_candidate_revision=2, after_candidate_hash=after.candidate_hash,
        after_evidence_hash=after.evidence_hash, attempt_id=binding.attempt_id,
        original_input_state="MISSING", original_input_key=None, original_input_hash=None,
        original_candidate=before, original_candidate_revision=1,
        command_json=canonical_json(command), resolved_draft=output.draft,
        resolved_mapping=mapping, resolved_update=output, resolved_review=reviewed,
        assessment_binding=binding, prefix=prefix, prefix_hash=source_prefix_hash(prefix, binding),
        parent_hash=parent.evidence_hash, independent=False, created_at=source.available_at)

    result = assess_human_change_current(source, output, reviewed, mapping, operation,
        context=context, base_review=base, verified_parent=parent, binding=binding, prefix=prefix)

    assert result.coverage_complete is not mismatch
    assert result.source_assessment.origin == "HUMAN"
    assert result.source_assessment.human_operation_hash == operation.evidence_hash
    assert not result.current_automatic_fidelity_verified
    assert result.authority_granted is result.source_assessment.authority_granted is False
