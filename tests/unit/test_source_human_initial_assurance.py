"""A registered human correction proves source policy without inventing AI preimages.

Pure fixtures retain a source-bound historical server PlanCandidateReview checkpoint.
They do not claim that an arbitrary self-signed operation is registered in real state;
the transactional preparation adapter must authenticate that separately.
"""

import importlib
import json
from datetime import timedelta

import pytest
from tests.integration.test_source_coverage_preparation_commit import _NOW
from tests.unit.test_source_coverage_baseline import _append_as_context
from tests.unit.test_source_coverage_treatments import _supplemented_maximum

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.update_review import PlanCandidateReview, build_initial_review
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationItemReview,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def _assess(*args, **kwargs):
    module = importlib.import_module("trade_plan_monitor.ai.source_human_initial_assurance")
    return module.assess_human_initial_current(*args, **kwargs)


def _source_binding(mapping, value):
    path = "position.max_qty"
    ids = tuple(clause.clause_id for clause in mapping.clauses if path in clause.paths)
    return tuple(binding.model_copy(update=dict(value=value, origin="SOURCE",
        clause_ids=ids, supplement_id=None)) if binding.path == path else binding
        for binding in mapping.bindings if value is not None or binding.path != path)


def _case(*, source_value=None, before_value=None, source_only=False, extra=None,
          role="COMMENTARY", available_at=_NOW):
    draft, text, mapping, span = _supplemented_maximum(source_value)
    if source_only:
        mapping = mapping.model_copy(update=dict(
            bindings=_source_binding(mapping, draft.position.max_qty), supplements=()))
    if extra is not None:
        text, mapping = _append_as_context(text, mapping, extra, semantic_role=role,
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Human says background"))
    source = PreparationSource(source_id="human-initial-source", text=text,
        available_at=available_at, effective_trade_date=available_at.date())
    before_draft = draft.model_copy(update={
        "position": draft.position.model_copy(update={"max_qty": before_value}),
    })
    before_mapping = mapping.model_copy(update=dict(supplements=(),
        candidate_content_hash=daily_draft_content_sha256(before_draft),
        bindings=_source_binding(mapping, before_value)))
    # An unresolved historical server checkpoint may have no accepted field owners.
    # Calling the successful old initial-review constructor here would fabricate
    # accepted provenance for the missing or source-conflicting original parameter.
    before = PlanCandidateReview(source_id=source.source_id, source_hash=source.binding_hash,
        available_at=source.execution_available_at, draft=before_draft, bindings=(),
        issues=("SOURCE_REASSESSMENT_REQUIRED: position.max_qty",))
    original = CollectionPreparationCandidate(**before.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=None)
    reviewed = build_initial_review(draft, mapping, source)
    after = CollectionPreparationCandidate(**reviewed.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=None)
    command = CollectionItemCorrectionCommand(expected_revision=7,
        binding=PreparationItemReview(source_id=source.source_id, source_revision=1,
            candidate_revision=1, candidate_hash=original.candidate_hash,
            evidence_hash=original.evidence_hash, base_hash=None),
        confirmed=True, evidence="Explicit correction of this exact supported source and policy.",
        draft=draft, mapping=mapping)
    binding = CandidateBinding(preparation_id="human-initial-pure", item_index=0,
        source_id=source.source_id, source_revision=1, source_binding_hash=source.binding_hash,
        candidate_revision=2, candidate_hash=after.candidate_hash,
        review_evidence_hash=reviewed.evidence_hash, attempt_id="server-historical-attempt",
        inputs_hash=None, independent=False)
    operation = PreparationHumanOperation.build(preparation_id=binding.preparation_id,
        item_index=0, operation="CORRECT_ITEM", source=source, source_revision=1,
        before_revision=7, after_revision=8, before_candidate_revision=1,
        before_candidate_hash=original.candidate_hash, before_evidence_hash=original.evidence_hash,
        after_candidate_revision=2, after_candidate_hash=after.candidate_hash,
        after_evidence_hash=after.evidence_hash, attempt_id=binding.attempt_id,
        original_input_state="MISSING", original_input_key=None, original_input_hash=None,
        original_candidate=original, original_candidate_revision=1,
        command_json=canonical_json(command), resolved_draft=draft, resolved_mapping=mapping,
        resolved_review=reviewed, assessment_binding=binding,
        prefix=(), prefix_hash=source_prefix_hash((), binding), parent_hash=None,
        independent=False, created_at=_NOW)
    return source, reviewed, mapping, operation, binding, before_draft, before_mapping, span


def _assert_human(result, operation):
    assert result.authority_granted is False
    assert result.source_assessment.authority_granted is False
    assert result.source_assessment.origin == "HUMAN"
    assert result.source_assessment.normalization_hash is None
    assert result.source_assessment.automatic_fidelity_verified is False
    assert result.current_automatic_fidelity_verified is False
    for owner in result.owners:
        if owner.origin != "PRODUCT_CONTRACT":
            assert owner.origin == "HUMAN"
            assert owner.human_receipt_hash == operation.evidence_hash


def test_fixture_is_actual_source_missing_parameter_and_explicit_source_bound_server_checkpoint():
    source, review, mapping, operation, _, before, before_map, span = _case()
    assert source.text[slice(*span)] == "position.max_qty = null"
    assert before.position.max_qty is None and review.draft.position.max_qty == 300
    checkpoint = operation.original_candidate
    assert checkpoint.source_hash == source.binding_hash
    assert checkpoint.source_revision == operation.source_revision
    assert json.loads(checkpoint.payload_json)["schema_version"] == (
        "monitor-loop-candidate-evidence-v1")
    assert operation.original_input_state == "MISSING"
    assert operation.original_input_key is operation.original_input_hash is None
    assert "normalization" not in type(operation).model_fields
    assert "derivation" not in type(operation).model_fields
    assert not assess_source_coverage(before, before_map, source.text,
                                      origin="AI_NEW").coverage_complete
    assert not assess_source_coverage(before, before_map, source.text,
                                      origin="HUMAN").coverage_complete
    assert assess_source_coverage(review.draft, mapping, source.text,
                                  origin="HUMAN").coverage_complete


def test_registered_null_fill_without_raw_inputs_has_fresh_human_proof_and_exact_span():
    source, review, mapping, operation, binding, _, _, span = _case()

    result = _assess(source, review, mapping, operation, binding=binding)

    assert result.coverage_complete and result.status == "COMPLETE"
    assert result.binding == binding and result.parent_hash is None
    _assert_human(result, operation)
    atom, = (atom for atom in result.source_assessment.obligations
             if (atom.start, atom.end) == span)
    assert atom.excerpt == "position.max_qty = null"
    assert atom.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert atom.paths == ("position.max_qty",)
    owner, = (owner for owner in result.owners if owner.path == "position.max_qty")
    assert owner.source_hash == source.source_hash
    assert owner.source_binding_hash == source.binding_hash
    assert atom.obligation_id in owner.obligation_ids
    assert source.text[atom.start:atom.end] == atom.excerpt
    assert operation.original_candidate.payload_json != canonical_json(review)


def test_supported_source_semantic_correction_fixes_the_candidate_instead_of_overriding_source():
    source, review, mapping, operation, binding, before, before_map, _ = _case(
        source_value=300, before_value=200, source_only=True)
    assert mapping.supplements == ()
    assert not assess_source_coverage(before, before_map, source.text,
                                      origin="HUMAN").coverage_complete

    result = _assess(source, review, mapping, operation, binding=binding)

    assert result.status == "COMPLETE"
    _assert_human(result, operation)
    assert result.source_assessment == assess_source_coverage(review.draft, mapping, source.text,
                                                              origin="HUMAN")
    owner, = (owner for owner in result.owners if owner.path == "position.max_qty")
    assert owner.obligation_ids and owner.human_receipt_hash == operation.evidence_hash


@pytest.mark.parametrize("role", ["COMMENTARY", "ACCOUNT", "HISTORICAL"])
@pytest.mark.parametrize("extra", [
    "Only buy when turnover exceeds 3 percent.", "等那扇门打开后再行动。",
])
def test_explicit_human_confirmation_cannot_waive_unknown_background(role, extra):
    source, review, mapping, operation, binding, *_ = _case(extra=extra, role=role)
    assert build_daily_review(review.draft, mapping, source.text).issues == ()

    result = _assess(source, review, mapping, operation, binding=binding)

    assert result.status == "BLOCKED" and not result.coverage_complete
    _assert_human(result, operation)
    atoms = [atom for atom in result.source_assessment.obligations if atom.excerpt == extra]
    assert atoms and all(atom.scope == "UNKNOWN" for atom in atoms)
    assert all(source.text[atom.start:atom.end] == atom.excerpt for atom in atoms)
    assert all(any(ref.obligation_id == atom.obligation_id for ref in result.global_obligations)
               for atom in atoms)


@pytest.mark.parametrize("source_value", [200, 400, "300"])
def test_human_supplement_cannot_override_a_known_nonnull_source_value(source_value):
    source, review, mapping, operation, binding, _, _, span = _case(
        source_value=source_value, before_value=source_value if type(source_value) is int else 300)

    result = _assess(source, review, mapping, operation, binding=binding)

    assert result.status == "BLOCKED"
    _assert_human(result, operation)
    atom, = (atom for atom in result.source_assessment.obligations
             if (atom.start, atom.end) == span)
    assert atom.state == "CONFLICT"


@pytest.mark.parametrize("mismatch", [
    "source", "review", "mapping", "binding", "operation", "prefix",
])
def test_human_operation_cannot_be_swapped_into_another_source_or_policy(mismatch):
    source, review, mapping, operation, binding, *_ = _case()
    prefix = ()
    if mismatch == "source":
        source = source.model_copy(update={
            "available_at": source.available_at + timedelta(minutes=1),
        })
    elif mismatch == "review":
        review = review.model_copy(update={
            "draft": review.draft.model_copy(update={"name": "A different complete draft"}),
        })
    elif mismatch == "mapping":
        mapping = mapping.model_copy(update={"clauses": (
            mapping.clauses[0].model_copy(update={"reason": "A different full mapping"}),
            *mapping.clauses[1:])})
    elif mismatch == "binding":
        binding = binding.model_copy(update={"candidate_hash": "f" * 64})
    elif mismatch == "operation":
        operation = _case(available_at=_NOW + timedelta(minutes=1))[3]
    else:
        prefix = (PrefixAssuranceRef(binding=binding, assurance_hash="f" * 64),)

    with pytest.raises(ValueError):
        _assess(source, review, mapping, operation, binding=binding, prefix=prefix)
