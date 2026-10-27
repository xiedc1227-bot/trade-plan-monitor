"""Human deltas preserve source and parent proof without inventing provider input.

Pure fixtures use the existing typed CORRECT_ITEM command and source-bound server
review checkpoints. Their operation self-hash is not actual state registration;
the preparation adapter must authenticate it in its own transaction.
"""

import importlib
import json
from datetime import timedelta

import pytest
from tests.unit.test_source_change_assurance import _NOW, _parent
from tests.unit.test_source_change_attacks import _two_rule_parent

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
)
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateOperation,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_change_core import corresponding_path
from trade_plan_monitor.ai.update_review import (
    PlanCandidateReview,
    build_update_review,
    context_from_review,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationItemReview,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

_PATH = "position.max_qty"


def _assess(case, **changes):
    module = importlib.import_module("trade_plan_monitor.ai.source_human_change_assurance")
    source, output, reviewed, mapping, operation, context, base, parent, binding, prefix = case
    values = dict(source=source, output=output, reviewed=reviewed, complete_mapping=mapping,
        operation=operation, context=context, base_review=base, verified_parent=parent,
        binding=binding, prefix=prefix)
    return module.assess_human_change_current(**(values | changes))


def _case(*, source_value=None, extra=None, role="COMMENTARY", parent_extra=None,
          control=None, action="MODIFY"):
    base, parent = _parent(extra=parent_extra) if control is None else _two_rule_parent()
    context = context_from_review(base, parent.binding.candidate_hash)
    text = control if control is not None else _PATH + " = " + json.dumps(source_value)
    if extra is not None:
        text += "\n" + extra
    source = PreparationSource(source_id="human-change-source", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    target = "position" if control is None else "ordinary_rules"
    identity = None if control is None else base.draft.ordinary_rules[0].rule_id
    proposed = base.draft.model_copy(update={"version": base.draft.version + 1})
    if control is None:
        proposed = proposed.model_copy(update={
            "position": proposed.position.model_copy(update={"max_qty": 500})})
    elif action == "REVOKE":
        proposed = proposed.model_copy(update={"ordinary_rules": tuple(
            rule for rule in proposed.ordinary_rules if rule.rule_id != identity)})
    canonical = server_source_clauses(text)
    primary = tuple(row.clause_id for row in canonical if row.start < len(text.split("\n")[0]))
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
        disposition="POLICY" if control is None and row.clause_id in primary else "CONTEXT",
        semantic_role="DIRECTIVE" if control is None and row.clause_id in primary else role,
        paths=(_PATH,) if control is None and row.clause_id in primary else (),
        reason="Complete explicit source proposal; labels cannot waive omitted requirements"))
        for row in canonical)
    output = PlanUpdateExtractionOutput(schema_version="monitor-loop-update-extraction-v1",
        draft=proposed, clauses=clauses, bindings=(), scope="EXPLICIT_CHANGES",
        scope_clause_ids=primary, retain_unmentioned=True, inheritance_mode="PREDECESSOR_PATCH",
        operations=(PlanUpdateOperation(target=target, rule_id=identity, action=action,
            clause_ids=primary, intent="ASSERTED", rationale="Explicit current source operation"),))
    content_hash = daily_draft_content_sha256(proposed)
    supplements = () if control is not None else (DailySupplement(
        supplement_id="registered-human-change-maximum", candidate_content_hash=content_hash,
        path=_PATH, value=500,
        reason="Explicit registered fill of this missing supported parameter"),)
    bindings = () if control is not None else (DailyFieldBinding(
        path=_PATH, value=500, origin="HUMAN_SUPPLEMENT", unit="JSON", clause_ids=(),
        supplement_id=supplements[0].supplement_id),)
    mapping = DailyMapping(mapping_version="daily-mapping-v1", candidate_content_hash=content_hash,
        clauses=clauses, bindings=bindings, supplements=supplements)
    reviewed = build_update_review(base, source, output, mapping=mapping)
    before_draft = proposed if control is not None else proposed.model_copy(update={
        "position": proposed.position.model_copy(update={
            "max_qty": source_value if type(source_value) is int else None})})
    before = PlanCandidateReview(source_id=source.source_id, source_hash=source.binding_hash,
        available_at=source.execution_available_at, draft=before_draft, bindings=(),
        issues=("SOURCE_REASSESSMENT_REQUIRED: current source delta",))
    original = CollectionPreparationCandidate(**before.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=context.base_hash)
    after = CollectionPreparationCandidate(**reviewed.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=context.base_hash)
    command = CollectionItemCorrectionCommand(expected_revision=7,
        binding=PreparationItemReview(source_id=source.source_id, source_revision=1,
            candidate_revision=1, candidate_hash=original.candidate_hash,
            evidence_hash=original.evidence_hash, base_hash=context.base_hash),
        update=output, mapping=mapping, confirmed=True,
        evidence="Explicit correction of the exact current source and prior plan.")
    binding = CandidateBinding(preparation_id=parent.binding.preparation_id,
        item_index=parent.binding.item_index + 1, source_id=source.source_id, source_revision=1,
        source_binding_hash=source.binding_hash, candidate_revision=2,
        candidate_hash=after.candidate_hash, review_evidence_hash=reviewed.evidence_hash,
        attempt_id="server-historical-human-change-attempt", inputs_hash=None, independent=False)
    prefix = (*parent.prefix, PrefixAssuranceRef(binding=parent.binding,
                                                assurance_hash=parent.evidence_hash))
    operation = PreparationHumanOperation.build(preparation_id=binding.preparation_id,
        item_index=binding.item_index, operation="CORRECT_ITEM", source=source, source_revision=1,
        before_revision=7, after_revision=8, before_candidate_revision=1,
        before_candidate_hash=original.candidate_hash, before_evidence_hash=original.evidence_hash,
        after_candidate_revision=2, after_candidate_hash=after.candidate_hash,
        after_evidence_hash=after.evidence_hash, attempt_id=binding.attempt_id,
        original_input_state="MISSING", original_input_key=None, original_input_hash=None,
        original_candidate=original, original_candidate_revision=1,
        command_json=canonical_json(command), resolved_draft=output.draft,
        resolved_mapping=mapping, resolved_update=output, resolved_review=reviewed,
        assessment_binding=binding, prefix=prefix, prefix_hash=source_prefix_hash(prefix, binding),
        parent_hash=parent.evidence_hash, independent=False, created_at=_NOW)
    return source, output, reviewed, mapping, operation, context, base, parent, binding, prefix


def _assert_human(result, operation):
    assessment = result.source_assessment
    assert result.authority_granted is assessment.authority_granted is False
    assert assessment.version == "source-human-change-coverage-v1" and assessment.origin == "HUMAN"
    assert assessment.human_operation_hash == operation.evidence_hash
    assert assessment.raw_delta_verified is False
    assert assessment.provider_full_draft_supplied is False
    assert assessment.full_draft_fidelity_verified is False
    assert assessment.automatic_fidelity_verified is False
    assert result.current_automatic_fidelity_verified is False


def test_fixture_uses_registered_mapping_and_typed_actual_server_checkpoints_without_fake_raw():
    source, output, reviewed, mapping, operation, context, _, _, binding, _ = _case()
    assert source.text == "position.max_qty = null"
    assert reviewed.issues == () and reviewed.draft.position.max_qty == 500
    assert mapping.supplements and mapping.bindings[0].origin == "HUMAN_SUPPLEMENT"
    assert operation.original_input_state == "MISSING" and binding.inputs_hash is None
    assert operation.original_input_key is operation.original_input_hash is None
    assert operation.resolved_update == output and output.bindings == ()
    command = CollectionItemCorrectionCommand.model_validate_json(operation.command_json)
    assert command.confirmed is True and command.update == output and command.mapping == mapping
    checkpoint = operation.original_candidate
    before = PlanCandidateReview.model_validate_json(checkpoint.payload_json)
    assert before.issues and before.draft.position.max_qty is None
    assert before.bindings == () and before.source_hash == source.binding_hash
    assert checkpoint.base_hash == context.base_hash
    assert checkpoint.candidate_hash == command.binding.candidate_hash
    assert json.loads(checkpoint.payload_json)["schema_version"] == (
        "monitor-loop-candidate-evidence-v1")
    assert "extraction" not in json.loads(checkpoint.payload_json)
    assert "normalization" not in type(operation).model_fields
    assert "derivation" not in type(operation).model_fields


def test_registered_missing_raw_human_delta_keeps_parent_owners_and_marks_only_changed_owner():
    case = _case()
    source, _, reviewed, _, operation, context, base, parent, binding, prefix = case

    result = _assess(case)

    assert result.coverage_complete and result.status == "COMPLETE"
    _assert_human(result, operation)
    assert result.binding == binding and result.prefix == prefix
    assert result.parent_hash == parent.evidence_hash
    assert result.source_assessment.base_hash == context.base_hash
    assert result.source_refs[:-1] == parent.source_refs
    atom, = result.source_assessment.obligations
    assert atom.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT" and atom.paths == (_PATH,)
    assert source.text[atom.start:atom.end] == atom.excerpt
    changed = next(owner for owner in result.owners if owner.path == _PATH)
    assert changed.origin == "HUMAN" and changed.human_receipt_hash == operation.evidence_hash
    assert changed.source_binding_hash == source.binding_hash
    assert atom.obligation_id in changed.obligation_ids
    previous = {owner.path: owner for owner in parent.owners}
    for owner in result.owners:
        if owner.path == _PATH:
            continue
        old_path = corresponding_path(owner.path, reviewed.draft, base.draft)
        assert owner == previous[old_path].model_copy(update={"path": owner.path, "origin": "BASE"})


@pytest.mark.parametrize("source_value", [200, 400, "500"])
def test_human_delta_supplement_cannot_override_any_known_nonnull_source_value(source_value):
    case = _case(source_value=source_value)
    assert case[2].issues == ()

    result = _assess(case)

    _assert_human(result, case[4])
    assert result.status == "BLOCKED" and not result.coverage_complete
    atom, = result.source_assessment.obligations
    assert atom.state == "CONFLICT"
    assert atom.excerpt == _PATH + " = " + json.dumps(source_value)


@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
@pytest.mark.parametrize("extra", [
    "Only buy when turnover exceeds 3 percent.", "等那扇门打开后再行动。",
])
def test_complete_human_confirmation_does_not_waive_unknown_current_background(role, extra):
    case = _case(extra=extra, role=role)
    assert case[2].issues == ()

    result = _assess(case)

    _assert_human(result, case[4])
    assert result.status == "BLOCKED"
    atoms = [row for row in result.source_assessment.obligations if row.excerpt == extra]
    assert atoms and all(row.scope == "UNKNOWN" and row.state == "UNRESOLVED" for row in atoms)
    assert all(case[0].text[row.start:row.end] == row.excerpt for row in atoms)
    assert all(any(ref.obligation_id == row.obligation_id for ref in result.global_obligations)
               for row in atoms)


def test_old_zero_issue_parent_review_cannot_replace_its_incomplete_current_source_proof():
    extra = "Every risk exit also waits for a blue lantern."
    case = _case(parent_extra=extra)
    assert case[6].issues == () and not case[7].coverage_complete
    assert case[7].global_obligations and case[2].issues == ()

    result = _assess(case)

    _assert_human(result, case[4])
    assert result.status == "BLOCKED" and result.source_assessment.parent_verified is False
    assert result.source_assessment.parent_assurance_hash == case[7].evidence_hash
    assert set(case[7].global_obligations) <= set(result.global_obligations)


@pytest.mark.parametrize("mismatch", [
    "source", "output", "review", "mapping", "binding", "preparation", "context", "prefix",
])
def test_human_operation_is_bound_to_its_exact_source_update_mapping_parent_and_candidate(mismatch):
    case = _case()
    source, output, reviewed, mapping, _, context, _, _, binding, _ = case
    if mismatch == "source":
        changes = dict(source=source.model_copy(update={
            "available_at": source.available_at + timedelta(minutes=1)}))
    elif mismatch == "output":
        changes = dict(output=output.model_copy(update={"scope_clause_ids": ()}))
    elif mismatch == "review":
        changes = dict(reviewed=reviewed.model_copy(update={"source_id": "another-source"}))
    elif mismatch == "mapping":
        changes = dict(complete_mapping=mapping.model_copy(update={"clauses": (
            mapping.clauses[0].model_copy(update={
                "reason": "Different complete human mapping"}),)}))
    elif mismatch == "binding":
        changes = dict(binding=binding.model_copy(update={"candidate_hash": "f" * 64}))
    elif mismatch == "preparation":
        changes = dict(binding=binding.model_copy(update={"preparation_id": "another-preparation"}))
    elif mismatch == "context":
        changes = dict(context=context.model_copy(update={"base_hash": "f" * 64}))
    else:
        changes = dict(prefix=())

    with pytest.raises(ValueError):
        _assess(case, **changes)


def test_human_operation_cannot_be_replaced_by_a_different_self_consistent_resolved_operation():
    case = _case()
    foreign = _case(extra="Historical record: bought 100 shares on 2026-09-24.")[4]

    with pytest.raises(ValueError):
        _assess(case, operation=foreign)


@pytest.mark.parametrize("text,action", [
    ("取消原来的买入规则。", "REVOKE"),
    ("不要撤销原买入指令。", "RETAIN"),
])
def test_registered_whole_rule_human_controls_match_the_same_source_owned_targets(text, action):
    case = _case(control=text, action=action)
    assert case[2].issues == ()

    result = _assess(case)

    _assert_human(result, case[4])
    assert result.status == "COMPLETE"
    operation = next(row for row in result.source_assessment.operations
                     if row.target == "ordinary_rules" and row.rule_id == "low-buy")
    assert operation.action == action
    if action == "REVOKE":
        assert operation.obligation_ids and operation.changed_paths
        assert [rule.rule_id for rule in case[2].draft.ordinary_rules] == ["remaining-sell"]
    else:
        assert operation.changed_paths == ()
        assert case[2].draft.ordinary_rules == case[6].draft.ordinary_rules
    previous = {owner.path: owner for owner in case[7].owners}
    for owner in result.owners:
        old_path = corresponding_path(owner.path, case[2].draft, case[6].draft)
        assert owner == previous[old_path].model_copy(update={"path": owner.path, "origin": "BASE"})


@pytest.mark.parametrize("text,action", [
    ("取消原来的买入规则。", "RETAIN"),
    ("不要撤销原买入指令。", "REVOKE"),
    ("仅对新仓取消原来的买入规则。", "REVOKE"),
])
def test_human_confirmation_cannot_ignore_invert_or_broaden_a_source_control(text, action):
    case = _case(control=text, action=action)
    assert case[2].issues == ()

    result = _assess(case)

    _assert_human(result, case[4])
    assert result.status == "BLOCKED" and result.source_assessment.issues
    assert not result.coverage_complete


def test_human_delta_proof_is_deterministic_and_never_rewrites_any_original_parent_or_source():
    case = _case()
    before = tuple(value.model_dump_json() if hasattr(value, "model_dump_json") else tuple(
        row.model_dump_json() for row in value) for value in case)

    first, second = _assess(case), _assess(case)

    assert first == second and first.evidence_hash == second.evidence_hash
    assert tuple(value.model_dump_json() if hasattr(value, "model_dump_json") else tuple(
        row.model_dump_json() for row in value) for value in case) == before
