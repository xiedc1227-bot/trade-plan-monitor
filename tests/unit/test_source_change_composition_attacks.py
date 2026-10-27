"""Independent multi-hop inheritance tests preserve exact source proof ownership."""

from datetime import timedelta

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import _NOW, _assemble, _case, _current_binding
from tests.unit.test_source_change_attacks import _attack
from tests.unit.test_source_change_composition import _assess
from tests.unit.test_source_coverage_treatments import _supplemented_maximum
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import build_initial_review, context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _next(base, parent, *, maximum=600, action="MODIFY"):
    available = base.available_at + timedelta(days=1)
    source = PreparationSource(source_id=f"follow-up-{parent.binding.item_index + 1}",
        text=f"position.max_qty = {maximum}", available_at=available,
        effective_trade_date=available.date())
    context = context_from_review(base, parent.binding.candidate_hash)
    _, patch = delta(source.text, target="position", action=action,
                     values={"max_qty": maximum} if action == "MODIFY" else {})
    case = list(_assemble(base, parent, source, patch, context))
    case[7] = case[7].model_copy(update={"item_index": parent.binding.item_index + 1})
    assert not case[2].review.issues and len(case[3].derivation.stages) == 3
    return tuple(case)


def _initial(draft, text, mapping, *, source_id="independent-parent"):
    available = _NOW - timedelta(days=1)
    source = PreparationSource(source_id=source_id, text=text, available_at=available,
                               effective_trade_date=available.date())
    review = build_initial_review(draft, mapping, source)
    image = draft.model_dump(mode="json")
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash,
        normalization=capture_normalization(image, image, text))
    parent = assess_initial_current(source, review, mapping, inputs,
                                    binding=_binding(source, review, inputs))
    assert not review.issues
    return review, parent


def test_a_second_actual_delta_preserves_original_owner_atoms_across_the_entire_prefix():
    first = _case()
    middle = _assess(first)
    second = _next(first[2].review, middle)
    result = _assess(second)

    assert result.coverage_complete and not result.current_automatic_fidelity_verified
    assert result.parent_hash == middle.evidence_hash and len(result.prefix) == 2
    assert result.source_refs[:-1] == middle.source_refs
    assert {row.path for row in result.owners} == semantic_values(second[2].review.draft).keys()
    original = {row.path: row for row in first[6].owners}
    for owner in result.owners:
        if owner.path == "position.max_qty":
            assert owner.source_id == second[0].source_id and owner.origin == "CURRENT"
        else:
            assert owner == original[owner.path].model_copy(update={"origin": "BASE"})
    assert result.authority_granted is False


@pytest.mark.parametrize("where", ["initial", "middle"])
def test_an_unbound_unknown_source_requirement_survives_a_second_independent_update(where):
    text = "Every instruction also depends on a blue lantern."
    first = _case(**({"parent_extra": text} if where == "initial" else {"extra": text}))
    middle = _assess(first)
    unresolved = tuple(row for row in middle.global_obligations if row.scope == "UNKNOWN")
    assert unresolved and middle.status == "BLOCKED"
    assert all(atom.paths == () for atom in (
        first[6].source_assessment.obligations if where == "initial"
        else middle.source_assessment.obligations) if atom.excerpt == text)
    second = _next(first[2].review, middle)
    result = _assess(second)

    assert result.status == "BLOCKED" and result.authority_granted is False
    assert set(unresolved) <= set(result.global_obligations)
    assert result.source_refs[:-1] == middle.source_refs
    assert result.source_assessment.parent_verified is False
    assert len(result.owners) == len(semantic_values(second[2].review.draft))


def test_blocked_cancellation_keeps_the_same_value_siblings_original_owner_after_reindexing():
    case = _attack("implicit_cancellation")
    result = _assess(case)
    assert result.status == "BLOCKED" and result.owners
    original = {row.path: row for row in case[6].owners}
    current = {row.path: row for row in result.owners}
    for path, owner in current.items():
        if path.startswith("ordinary_rules[0]."):
            expected = original[path.replace("ordinary_rules[0]", "ordinary_rules[1]", 1)]
            assert owner == expected.model_copy(update={"path": path, "origin": "BASE"})
            assert owner.original_path.startswith("ordinary_rules[1].")
    # Both previous quantities are 100, so value equality cannot choose the owner.
    assert original["ordinary_rules[0].quantity"].obligation_ids != original[
        "ordinary_rules[1].quantity"].obligation_ids
    assert current["ordinary_rules[0].quantity"].obligation_ids == original[
        "ordinary_rules[1].quantity"].obligation_ids
    assert result.source_refs[:-1] == case[6].source_refs


def test_an_inherited_human_supplement_does_not_turn_into_an_automatic_receipt():
    draft, text, mapping, _ = _supplemented_maximum()
    base, parent = _initial(draft, text, mapping)
    original = next(row for row in parent.owners if row.path == "position.max_qty")
    assert original.origin == "HUMAN" and original.human_receipt_hash is None
    assert parent.status == "BLOCKED"
    case = _next(base, parent, maximum=300, action="RETAIN")
    result = _assess(case)

    inherited = next(row for row in result.owners if row.path == "position.max_qty")
    assert result.status == "BLOCKED" and result.authority_granted is False
    assert inherited.human_receipt_hash is None
    assert inherited.source_id == original.source_id
    assert inherited.proof_hash == original.proof_hash
    assert inherited.obligation_ids == original.obligation_ids
    assert result.source_assessment.parent_verified is False
    assert not result.current_automatic_fidelity_verified


@pytest.mark.parametrize("problem", ["reordered", "omitted_initial", "duplicate", "future"])
def test_a_second_update_cannot_substitute_a_different_complete_prefix(problem):
    first = _case()
    middle = _assess(first)
    second = _next(first[2].review, middle)
    prefix = (*middle.prefix, PrefixAssuranceRef(
        binding=middle.binding, assurance_hash=middle.evidence_hash))
    assert len(prefix) == 2
    if problem == "reordered":
        changed = tuple(reversed(prefix))
    elif problem == "omitted_initial":
        changed = prefix[1:]
    elif problem == "duplicate":
        changed = (*prefix, prefix[-1])
    else:
        changed = (*prefix, PrefixAssuranceRef(binding=second[7], assurance_hash="f" * 64))

    with pytest.raises(ValueError):
        _assess(second, prefix=changed)


@pytest.mark.parametrize("replace_review", [False, True])
def test_a_separately_valid_parent_with_identical_plan_values_cannot_replace_the_bound_parent(
    replace_review,
):
    case = list(_case())
    text, mapping = source_mapping(case[5].draft)
    replacement_review, replacement = _initial(case[5].draft, text, mapping,
                                               source_id="another-valid-parent")
    assert replacement.coverage_complete and case[6].coverage_complete
    assert replacement.content_hash == case[6].content_hash
    assert replacement.source_assessment.source_hash == case[6].source_assessment.source_hash
    assert replacement.binding != case[6].binding
    case[6] = replacement
    if replace_review:
        case[5] = replacement_review

    with pytest.raises(ValueError):
        _assess(tuple(case))


def test_same_value_after_reindexing_cannot_borrow_the_removed_siblings_source_binding():
    case = list(_attack("implicit_cancellation"))
    source, _, original, inputs, context, base, parent, _ = case
    target = "ordinary_rules[0].quantity"
    deleted = next(row for row in base.bindings if row.path == target)
    retained = next(row for row in original.review.bindings if row.path == target)
    assert deleted.binding.value == retained.binding.value == 100
    assert deleted.original_path != retained.original_path
    bindings = tuple(deleted.model_copy(update={"path": target}) if row.path == target else row
                     for row in original.review.bindings)
    review = original.review.model_copy(update={"bindings": bindings})
    type(review).model_validate(review.model_dump(mode="python"))
    case[2] = original.model_copy(update={"review": review})
    case[7] = _current_binding(source, case[2], inputs, context, parent)
    assert case[2].review.issues == ()

    with pytest.raises(ValueError):
        _assess(tuple(case))


def test_the_complete_multi_hop_assessment_is_deterministic_and_preserves_every_prior_byte():
    first = _case()
    middle = _assess(first)
    second = _next(first[2].review, middle)
    before = tuple(value.model_dump_json() for value in (*first, middle, *second))

    one = _assess(second)
    two = _assess(second)

    assert one == two and one.evidence_hash == two.evidence_hash
    assert tuple(value.model_dump_json() for value in (*first, middle, *second)) == before
