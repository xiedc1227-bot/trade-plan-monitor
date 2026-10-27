"""Pure reuse aliases preserve original proof ownership without granting authority."""

import importlib

import pytest
from tests.unit.test_source_change_assurance import _case as _change_case
from tests.unit.test_source_change_assurance import _parent
from tests.unit.test_source_change_composition import _assess as _compose
from tests.unit.test_source_coverage_treatments import _supplemented_maximum
from tests.unit.test_source_initial_assurance import _binding
from tests.unit.test_source_initial_assurance import _case as _initial_case

from trade_plan_monitor.ai.source_candidate_models import (
    PrefixAssuranceRef,
    SourceCandidateAssurance,
)
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _alias(original, *, preparation_id="consumer", item_index=0, prefix=(), **updates):
    module = importlib.import_module("trade_plan_monitor.ai.source_reuse_assurance")
    binding = original.binding.model_copy(update={
        "preparation_id": preparation_id, "item_index": item_index,
    })
    return module.build_reuse_alias(original, binding=binding, prefix=prefix,
        **(dict(lineage_hash="a" * 64, current_review_hash="b" * 64,
                manifest_hash="c" * 64) | updates))


def _independent(source_id):
    source, review, mapping, inputs, _ = _initial_case()
    source = source.model_copy(update={"source_id": source_id})
    review = build_initial_review(review.draft, mapping, source)
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, initial_coverage=inputs.initial_coverage,
        normalization=inputs.normalization)
    return assess_initial_current(source, review, mapping, inputs,
        binding=_binding(source, review, inputs, independent=True))


def _reference(proof):
    return PrefixAssuranceRef(binding=proof.binding, assurance_hash=proof.evidence_hash)


def test_complete_alias_changes_only_consumer_placement_and_keeps_original_source_proof():
    _, original = _parent()
    before = original.model_dump_json()

    alias = _alias(original)

    assert alias.binding.preparation_id == "consumer"
    assert alias.source_assessment == original.source_assessment
    assert alias.source_refs == original.source_refs
    assert alias.owners == original.owners
    assert alias.global_obligations == original.global_obligations
    assert alias.content_hash == original.content_hash
    assert alias.issues == original.issues
    assert alias.coverage_complete is True and alias.authority_granted is False
    assert alias.reuse_ref.original_owner_binding == original.binding
    assert alias.reuse_ref.original_assurance_hash == original.evidence_hash
    assert alias.reuse_ref.original_current_review_hash == "b" * 64
    assert alias.reuse_ref.original_manifest_hash == "c" * 64
    assert alias.reuse_ref.lineage_hash == "a" * 64
    assert original.model_dump_json() == before


def test_absent_reuse_reference_is_not_added_to_old_serialized_or_hashed_payload():
    _, original = _parent()
    payload = original.model_dump(mode="json")
    assert original.reuse_ref is None and "reuse_ref" not in payload
    assert "reuse_ref" not in original.model_dump_json()
    assert SourceCandidateAssurance.model_validate(payload) == original
    assert SourceCandidateAssurance.model_validate(payload | {"reuse_ref": None}) == original
    assert original.model_copy(deep=True).model_dump_json() == original.model_dump_json()


def test_reference_has_exactly_five_required_fields_and_forbids_authority_or_unknown_keys():
    module = importlib.import_module("trade_plan_monitor.ai.source_reuse_models")
    _, original = _parent()
    reference = _alias(original).reuse_ref
    expected = {"original_owner_binding", "original_assurance_hash",
                "original_current_review_hash", "original_manifest_hash", "lineage_hash"}
    assert set(type(reference).model_fields) == expected
    payload = reference.model_dump(mode="json")
    for field in expected:
        with pytest.raises(ValueError):
            module.AssuranceReuseRef.model_validate(
                {key: value for key, value in payload.items() if key != field})
    for extra in ("authority_granted", "registered", "direct_owner_binding"):
        with pytest.raises(ValueError):
            module.AssuranceReuseRef.model_validate(payload | {extra: True})


def test_two_independent_original_index_zero_proofs_keep_their_leaf_owner_at_consumer_index_one():
    first, second = _independent("first-source"), _independent("second-source")
    assert first.binding.item_index == second.binding.item_index == 0
    alias_first = _alias(first)
    alias_second = _alias(second, item_index=1, prefix=(_reference(alias_first),))

    assert alias_second.binding.item_index == 1 and alias_second.binding.independent is True
    assert alias_second.parent_hash is None
    assert alias_second.prefix == (_reference(alias_first),)
    assert alias_second.reuse_ref.original_owner_binding == second.binding
    assert alias_second.reuse_ref.original_owner_binding.item_index == 0
    assert alias_second.source_assessment == second.source_assessment
    assert alias_second.owners == second.owners
    assert alias_second.source_refs == second.source_refs
    assert alias_second.coverage_complete and alias_second.authority_granted is False


def test_change_source_keeps_its_original_inner_binding_and_original_parent_hash():
    original = _compose(_change_case())
    alias = _alias(original)
    assert original.binding.item_index == 1 and alias.binding.item_index == 0
    assert alias.parent_hash is None
    assert alias.source_assessment == original.source_assessment
    assert alias.source_assessment.binding == original.binding
    assert alias.source_assessment.parent_assurance_hash == original.parent_hash
    assert alias.current_automatic_fidelity_verified is False


def test_a_second_reuse_keeps_original_leaf_four_fields_and_replaces_only_lineage_hash():
    _, original = _parent()
    middle = _alias(original, preparation_id="middle")
    last = _alias(middle, preparation_id="last", lineage_hash="d" * 64,
                  current_review_hash="e" * 64, manifest_hash="f" * 64)
    assert last.reuse_ref == middle.reuse_ref.model_copy(update={"lineage_hash": "d" * 64})
    assert last.reuse_ref.original_owner_binding == original.binding
    assert last.reuse_ref.original_assurance_hash == original.evidence_hash != middle.evidence_hash
    assert last.source_assessment == original.source_assessment
    assert last.owners == original.owners


@pytest.mark.parametrize("where", ["initial", "current", "inherited"])
def test_unknown_obligations_remain_blocked_inspectable_and_at_the_original_source(where):
    text = "Every action also depends on the blue lantern."
    if where == "initial":
        _, original = _parent(extra=text)
    else:
        original = _compose(_change_case(**{
            "extra" if where == "current" else "parent_extra": text}))
    alias = _alias(original)
    assert alias.status == original.status == "BLOCKED"
    assert alias.global_obligations == original.global_obligations
    assert alias.issues == original.issues and alias.owners == original.owners
    assert any(row.scope == "UNKNOWN" for row in alias.global_obligations)
    assert not alias.current_automatic_fidelity_verified and alias.authority_granted is False


def test_a_human_supplement_without_receipt_stays_blocked_and_never_gets_a_receipt():
    draft, text, mapping, _ = _supplemented_maximum()
    source, *_ = _initial_case()
    source = source.model_copy(update={"text": text})
    review = build_initial_review(draft, mapping, source)
    # This case deliberately has no raw input for its corrected human field.
    original = assess_initial_current(source, review, mapping, None,
        binding=_binding(source, review, None))
    human = tuple(owner for owner in original.owners if owner.origin == "HUMAN")
    assert human and all(owner.human_receipt_hash is None for owner in human)
    alias = _alias(original)
    assert alias.status == "BLOCKED" and alias.owners == original.owners
    assert alias.source_assessment == original.source_assessment
    assert all(owner.human_receipt_hash is None for owner in alias.owners
               if owner.origin == "HUMAN")
    assert alias.authority_granted is False


@pytest.mark.parametrize("kind", ["initial", "change"])
def test_genuine_pure_human_operation_provenance_stays_human_and_keeps_original_receipt(kind):
    if kind == "initial":
        from tests.unit.test_source_human_initial_assurance import _assess, _case

        source, reviewed, mapping, operation, binding, *_ = _case()
        original = _assess(source, reviewed, mapping, operation, binding=binding)
    else:
        from tests.unit.test_source_human_change_assurance import _assess, _case

        case = _case()
        operation = case[4]
        original = _assess(case)
    assert original.coverage_complete and original.current_automatic_fidelity_verified is False
    alias = _alias(original)
    assert alias.source_assessment == original.source_assessment
    assert alias.source_refs == original.source_refs and alias.owners == original.owners
    assert alias.global_obligations == original.global_obligations
    assert {owner.human_receipt_hash for owner in alias.owners if owner.origin == "HUMAN"} == {
        operation.evidence_hash}
    assert alias.coverage_complete and alias.current_automatic_fidelity_verified is False
    assert alias.authority_granted is False


@pytest.mark.parametrize(("field", "replacement"), [
    ("source_id", "another-source"), ("source_revision", 2),
    ("source_binding_hash", "0" * 64), ("candidate_revision", 2),
    ("candidate_hash", "0" * 64), ("review_evidence_hash", "0" * 64),
    ("attempt_id", None), ("inputs_hash", None), ("independent", True),
])
def test_alias_rejects_each_nonplacement_binding_change(field, replacement):
    _, original = _parent()
    module = importlib.import_module("trade_plan_monitor.ai.source_reuse_assurance")
    binding = original.binding.model_copy(update={
        "preparation_id": "consumer", "item_index": 0, field: replacement,
    })
    with pytest.raises(ValueError, match="binding coordinates"):
        module.build_reuse_alias(original, binding=binding,
            lineage_hash="a" * 64, current_review_hash="b" * 64, manifest_hash="c" * 64)


@pytest.mark.parametrize("mutation", ["missing", "foreign", "repeated", "reordered", "future"])
def test_consumer_prefix_requires_exact_length_preparation_and_order(mutation):
    _, original = _parent()
    first = _alias(original)
    second = _alias(original, item_index=1, prefix=(_reference(first),))
    prefix = (_reference(first), _reference(second))
    if mutation == "missing":
        prefix = prefix[:1]
    elif mutation == "foreign":
        prefix = (_reference(original), prefix[1])
    elif mutation == "repeated":
        prefix = (prefix[0], prefix[0])
    elif mutation == "reordered":
        prefix = prefix[::-1]
    else:
        prefix = (prefix[0], prefix[1].model_copy(update={
            "binding": second.binding.model_copy(update={"item_index": 2})}))
    with pytest.raises(ValueError, match="consumer prefix"):
        _alias(original, item_index=2, prefix=prefix)


@pytest.mark.parametrize("field", ["lineage_hash", "current_review_hash", "manifest_hash"])
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, True])
def test_all_direct_reference_hash_arguments_require_the_closed_hash_contract(field, value):
    _, original = _parent()
    with pytest.raises(ValueError):
        _alias(original, **{field: value})


def test_reused_references_still_validate_current_direct_review_and_manifest_hash_shapes():
    _, original = _parent()
    middle = _alias(original)
    with pytest.raises(ValueError):
        _alias(middle, current_review_hash="not-a-review-hash")
    with pytest.raises(ValueError):
        _alias(middle, manifest_hash="not-a-manifest-hash")


def test_tampered_original_self_hash_is_not_accepted_as_an_alias_input():
    _, original = _parent()
    forged = original.model_construct(**(dict(original) | {"evidence_hash": "0" * 64}))
    with pytest.raises(ValueError, match="hash differs"):
        _alias(forged)


def test_alias_roundtrips_copies_and_deterministically_hashes_without_mutating_parent():
    _, original = _parent()
    original_json = original.model_dump_json()
    first, second = _alias(original), _alias(original)
    assert first == second and first.evidence_hash != original.evidence_hash
    assert first.model_dump_json() == second.model_dump_json()
    assert SourceCandidateAssurance.model_validate_json(first.model_dump_json()) == first
    assert first.model_copy(deep=True) == first
    assert original.model_dump_json() == original_json
    with pytest.raises(ValueError):
        first.model_copy(update={"authority_granted": True})


def test_reuse_reference_cannot_relabel_the_leaf_source_even_after_rehashing_the_alias():
    _, original = _parent()
    alias = _alias(original)
    forged_owner = original.binding.model_copy(update={"source_id": "forged-source"})
    reference = alias.reuse_ref.model_copy(update={"original_owner_binding": forged_owner})
    values = {name: getattr(alias, name) for name in type(alias).model_fields
              if name not in {"evidence_hash", "status"}}
    with pytest.raises(ValueError, match="original owner"):
        SourceCandidateAssurance.build(**(values | {"reuse_ref": reference}))
