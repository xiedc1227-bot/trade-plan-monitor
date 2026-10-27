"""Initial assurance keeps raw AI fidelity and current source bindings separate.

Pure synthetic fixtures exercise local proof composition, without provider,
database, human approval, activation or changes to old review/hash contracts.
"""

import importlib
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline
from tests.unit.test_source_coverage_treatments import _supplemented_maximum

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.backtest.preparation_models import PreparationCandidate, PreparationSource
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _models():
    return importlib.import_module("trade_plan_monitor.ai.source_candidate_models")


def _assess(*args, **kwargs):
    module = importlib.import_module("trade_plan_monitor.ai.source_initial_assurance")
    return module.assess_initial_current(*args, **kwargs)


def _binding(source, review, inputs, **updates):
    candidate = PreparationCandidate(**review.to_preparation_candidate().model_dump(mode="python"),
        source_revision=1, source_hash=source.binding_hash)
    return _models().CandidateBinding(**(dict(preparation_id="initial-assurance", item_index=0,
        source_id=source.source_id, source_revision=1, source_binding_hash=source.binding_hash,
        candidate_revision=1, candidate_hash=candidate.candidate_hash,
        review_evidence_hash=review.evidence_hash, attempt_id=str(UUID(int=123)),
        inputs_hash=None if inputs is None else inputs.evidence_hash, independent=False) | updates))


def _case(*, extra=None, role="COMMENTARY", available_at=_NOW):
    draft, text, mapping = _baseline()
    if extra is not None:
        text, mapping = _append_as_context(text, mapping, extra, semantic_role=role,
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Background commentary"))
    source = PreparationSource(source_id="initial-source", text=text, available_at=available_at,
                               effective_trade_date=_NOW.date())
    review = build_initial_review(draft, mapping, source)
    image = draft.model_dump(mode="json")
    normalization = capture_normalization(image, image, text)
    assessment = assess_source_coverage(draft, mapping, text,
        normalization=normalization, origin="AI_NEW")
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, initial_coverage=assessment,
        normalization=normalization)
    binding = _binding(source, review, inputs)
    return source, review, mapping, inputs, binding


def test_complete_initial_native_source_with_actual_normalization_has_current_assurance():
    source, review, mapping, inputs, binding = _case()

    result = _assess(source, review, mapping, inputs, binding=binding)

    assert result.binding == binding
    assert result.status == "COMPLETE" and result.coverage_complete is True
    assert result.source_assessment.origin == "AI_NEW"
    assert result.source_assessment == inputs.initial_coverage
    assert result.current_automatic_fidelity_verified is True
    assert result.parent_hash is None and result.authority_granted is False
    assert result.content_hash == daily_draft_content_sha256(review.draft)
    assert len(result.source_refs) == 1
    ref = result.source_refs[0]
    assert ref.source_id == source.source_id and ref.source_hash == source.source_hash
    assert ref.source_binding_hash == source.binding_hash
    assert ref.proof_hash == result.source_assessment.evidence_hash


@pytest.mark.parametrize("field", ["source_revision", "candidate_revision"])
def test_current_binding_revisions_reject_values_outside_the_safe_integer_contract(field):
    *_, binding = _case()
    with pytest.raises(ValueError):
        _models().CandidateBinding.model_validate(binding.model_dump(mode="json") | {
            field: 9_007_199_254_740_992,
        })


def test_original_source_atoms_and_owner_links_keep_exact_hashes_paths_and_codepoint_spans():
    source, review, mapping, inputs, binding = _case()

    result = _assess(source, review, mapping, inputs, binding=binding)

    expected = inputs.initial_coverage
    assert result.source_assessment.obligations == expected.obligations
    ids = {atom.obligation_id for atom in expected.obligations}
    assert {owner.path for owner in result.owners} == set(semantic_values(review.draft))
    for atom in result.source_assessment.obligations:
        assert atom.source_hash == source.source_hash
        assert source.text[atom.start:atom.end] == atom.excerpt
    for owner in result.owners:
        assert owner.source_id == source.source_id
        assert owner.source_hash == source.source_hash
        assert owner.source_binding_hash == source.binding_hash
        assert owner.proof_hash == expected.evidence_hash
        assert set(owner.obligation_ids) <= ids
    ceiling = next(owner for owner in result.owners
                   if owner.path == "position.limit.capital_policy.cap_fen")
    assert ceiling.original_path == ceiling.path and ceiling.origin == "CURRENT"
    assert ceiling.obligation_ids
    # Existing SourceBoundField uses the metadata binding hash, while new
    # obligation references retain the actual original-text hash.
    assert review.bindings[0].source_hash == source.binding_hash != source.source_hash


def test_assessment_is_deterministic_and_never_modifies_old_payload_or_review_hashes():
    source, review, mapping, inputs, binding = _case()
    before = (source.model_dump_json(), review.model_dump_json(), review.evidence_hash,
              mapping.model_dump_json(), inputs.model_dump_json(), binding.model_dump_json(),
              review.to_preparation_candidate().model_dump_json())

    first = _assess(source, review, mapping, inputs, binding=binding)
    second = _assess(source, review, mapping, inputs, binding=binding)

    assert first == second and first.evidence_hash == second.evidence_hash
    assert before == (source.model_dump_json(), review.model_dump_json(), review.evidence_hash,
                      mapping.model_dump_json(), inputs.model_dump_json(),
                      binding.model_dump_json(),
                      review.to_preparation_candidate().model_dump_json())
    assert _models().SourceCandidateAssurance.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
@pytest.mark.parametrize("extra", [
    "Only buy when turnover exceeds 3 percent.",
    "仅当换手率超过3%时才允许买入。",
    "Everything else depends on the blue lantern.",
    "等那扇门打开后再行动。",
], ids=["mandatory_en", "mandatory_zh", "indirect_en", "indirect_zh"])
def test_background_roles_and_keyword_free_requirements_remain_global_unknown_blockers(role, extra):
    source, review, mapping, inputs, binding = _case(extra=extra, role=role)
    assert review.issues == ()  # Historical validity cannot certify current completeness.

    result = _assess(source, review, mapping, inputs, binding=binding)

    assert result.status == "BLOCKED" and result.coverage_complete is False
    assert result.current_automatic_fidelity_verified is False
    assert result.source_assessment.origin == "AI_NEW"
    assert result.authority_granted is False
    atoms = [atom for atom in result.source_assessment.obligations if atom.excerpt == extra]
    assert atoms and any(atom.scope == "UNKNOWN" for atom in atoms)
    refs = {ref.obligation_id: ref for ref in result.global_obligations}
    for atom in atoms:
        assert atom.obligation_id in refs
        assert refs[atom.obligation_id].source_hash == atom.source_hash == source.source_hash
        assert refs[atom.obligation_id].scope == "UNKNOWN"
        assert refs[atom.obligation_id].state == atom.state
        assert source.text[atom.start:atom.end] == extra


@pytest.mark.parametrize("kind", ["absent", "plain", "human", "historical"])
def test_missing_raw_never_fabricates_identity_or_adopts_a_weaker_origin(kind):
    source, review, mapping, _, _ = _case()
    inputs = None
    if kind != "absent":
        origin = {"human": "HUMAN", "historical": "AI_HISTORICAL"}.get(kind)
        previous = (None if origin is None else assess_source_coverage(
            review.draft, mapping, source.text, origin=origin))
        inputs = CoverageInputs.build(source_hash=source.source_hash,
            source_binding_hash=source.binding_hash, initial_coverage=previous)
    binding = _binding(source, review, inputs)

    result = _assess(source, review, mapping, inputs, binding=binding)

    assert result.status == "BLOCKED"
    assert result.source_assessment.origin == "AI_NEW"
    assert result.source_assessment.normalization_hash is None
    assert any(issue.code == "SOURCE_NORMALIZATION_LOSS"
               for issue in result.source_assessment.issues)
    assert result.current_automatic_fidelity_verified is False
    assert result.authority_granted is False
    assert inputs is None or inputs.normalization is None


@pytest.mark.parametrize("field,value", [
    ("source_id", "another-source"), ("source_binding_hash", "f" * 64),
    ("inputs_hash", "e" * 64), ("review_evidence_hash", "d" * 64),
])
def test_mismatched_source_input_or_original_review_binding_is_structurally_invalid(field, value):
    source, review, mapping, inputs, binding = _case()
    binding = binding.model_copy(update={field: value})

    with pytest.raises(ValueError):
        _assess(source, review, mapping, inputs, binding=binding)


@pytest.mark.parametrize("field", ["source_hash", "source_binding_hash"])
def test_validly_rehashed_private_inputs_must_match_the_exact_original_source(field):
    source, review, mapping, _, _ = _case()
    values = dict(source_hash=source.source_hash, source_binding_hash=source.binding_hash)
    values[field] = "f" * 64
    inputs = CoverageInputs.build(**values)
    binding = _binding(source, review, inputs)

    with pytest.raises(ValueError):
        _assess(source, review, mapping, inputs, binding=binding)


def test_same_source_text_with_changed_metadata_cannot_reuse_the_old_binding():
    source, review, mapping, inputs, binding = _case()
    changed = source.model_copy(update={"available_at": source.available_at + timedelta(minutes=1)})
    assert changed.source_hash == source.source_hash and changed.binding_hash != source.binding_hash

    with pytest.raises(ValueError):
        _assess(changed, review, mapping, inputs, binding=binding)


def test_rebuilt_metadata_binding_changes_aggregate_identity_without_rewriting_source_atoms():
    first = _case()
    second = _case(available_at=_NOW + timedelta(minutes=1))

    left = _assess(*first[:4], binding=first[4])
    right = _assess(*second[:4], binding=second[4])

    assert left.coverage_complete and right.coverage_complete
    assert first[0].source_hash == second[0].source_hash
    assert first[0].binding_hash != second[0].binding_hash
    assert left.source_assessment == right.source_assessment
    assert left.source_assessment.obligations == right.source_assessment.obligations
    assert left.prefix_hash != right.prefix_hash
    assert left.evidence_hash != right.evidence_hash


def test_opaque_candidate_attempt_identity_is_bound_but_is_not_an_authorization_claim():
    source, review, mapping, inputs, binding = _case()
    changed = binding.model_copy(update={"candidate_hash": "c" * 64, "attempt_id": "other-attempt"})

    original = _assess(source, review, mapping, inputs, binding=binding)
    result = _assess(source, review, mapping, inputs, binding=changed)

    assert original.evidence_hash != result.evidence_hash
    assert original.prefix_hash != result.prefix_hash
    assert original.source_assessment == result.source_assessment
    assert result.authority_granted is False


@pytest.mark.parametrize("kind", ["content_hash", "missing_binding", "review_header"])
def test_wrong_mapping_or_review_header_cannot_pass_current_initial_assurance(kind):
    source, review, mapping, inputs, binding = _case()
    if kind == "content_hash":
        mapping = mapping.model_copy(update={"candidate_content_hash": "0" * 64})
    elif kind == "missing_binding":
        mapping = mapping.model_copy(update={"bindings": mapping.bindings[:-1]})
    else:
        review = review.model_copy(update={"issues": ("Unproven previous review header.",)})
        binding = _binding(source, review, inputs)

    with pytest.raises(ValueError):
        _assess(source, review, mapping, inputs, binding=binding)


def test_matching_rehashed_review_header_cannot_move_source_availability_time():
    source, review, mapping, inputs, _ = _case()
    review = review.model_copy(update={"available_at": review.available_at + timedelta(minutes=1)})
    binding = _binding(source, review, inputs)

    with pytest.raises(ValueError):
        _assess(source, review, mapping, inputs, binding=binding)


def test_human_shaped_supplements_do_not_become_automatic_authorization_in_initial_codec():
    draft, text, mapping, _ = _supplemented_maximum()
    source = PreparationSource(source_id="initial-supplement", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    review = build_initial_review(draft, mapping, source)
    assert review.issues == () and mapping.supplements
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace)
    binding = _binding(source, review, inputs)

    result = _assess(source, review, mapping, inputs, binding=binding)

    assert result.status == "BLOCKED" and result.current_automatic_fidelity_verified is False
    assert result.source_assessment.origin == "AI_NEW"
    assert any(owner.origin == "HUMAN" and owner.human_receipt_hash is None
               for owner in result.owners)
    assert any(issue.code == "SOURCE_COVERAGE_REQUIRED" for issue in result.issues)
    assert result.authority_granted is False
