"""Multi-source owners and unresolved obligations survive exact delta composition."""

import importlib

import pytest
from tests.unit.test_source_change_assurance import _case

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef


def _assess(case, *, prefix=None):
    source, output, materialized, inputs, context, base, parent, binding = case
    if prefix is None:
        prefix = (*parent.prefix, PrefixAssuranceRef(
            binding=parent.binding, assurance_hash=parent.evidence_hash))
    module = importlib.import_module("trade_plan_monitor.ai.source_change_composition")
    return module.assess_change_current(source, output, materialized, inputs,
        context=context, base_review=base, verified_parent=parent, binding=binding,
        prefix=prefix)


def test_current_delta_owns_only_its_actual_changed_leaf_and_keeps_original_source_ids():
    case = _case()
    source, _, materialized, _, _, _, parent, binding = case
    result = _assess(case)
    assert result.coverage_complete is True
    assert result.authority_granted is False
    assert result.current_automatic_fidelity_verified is False
    assert result.binding == binding
    assert result.parent_hash == parent.evidence_hash
    assert result.source_refs[:-1] == parent.source_refs
    assert result.source_refs[-1].source_id == source.source_id
    assert result.source_refs[-1].proof_kind == "CHANGE"
    assert {row.path for row in result.owners} == semantic_values(materialized.review.draft).keys()
    owners = {row.path: row for row in result.owners}
    old = {row.path: row for row in parent.owners}
    assert owners["position.max_qty"].source_id == source.source_id
    assert owners["position.max_qty"].origin == "CURRENT"
    assert owners["position.max_qty"].obligation_ids
    for path in owners.keys() - {"position.max_qty"}:
        assert owners[path].source_id == old[path].source_id
        assert owners[path].proof_hash == old[path].proof_hash
        assert owners[path].obligation_ids == old[path].obligation_ids
        assert owners[path].original_path == old[path].original_path
        assert owners[path].origin == "BASE"


@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_unrecognized_current_condition_remains_an_independent_global_blocker(role):
    case = _case(extra="Buy only after the blue lantern turns green.", role=role)
    result = _assess(case)
    assert result.status == "BLOCKED"
    assert any(row.scope == "UNKNOWN" and row.source_id == case[0].source_id
               for row in result.global_obligations)
    assert len(result.owners) == len(semantic_values(case[2].review.draft))


def test_old_unknown_requirement_is_not_erased_when_no_current_field_uses_its_clause():
    case = _case(parent_extra="Every action also depends on the blue lantern.")
    parent = case[6]
    assert parent.global_obligations
    result = _assess(case)
    assert result.status == "BLOCKED"
    assert set(parent.global_obligations) <= set(result.global_obligations)
    assert result.source_refs[:-1] == parent.source_refs


@pytest.mark.parametrize("missing", ["empty", "wrong_hash", "wrong_binding"])
def test_prefix_is_exact_and_cannot_replace_the_policy_parent(missing):
    case = _case()
    parent = case[6]
    reference = PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash)
    if missing == "empty":
        prefix = ()
    elif missing == "wrong_hash":
        prefix = (reference.model_copy(update={"assurance_hash": "a" * 64}),)
    else:
        prefix = (reference.model_copy(update={"binding": parent.binding.model_copy(
            update={"candidate_revision": 2})}),)
    with pytest.raises(ValueError):
        _assess(case, prefix=prefix)


def test_source_composition_is_deterministic_and_does_not_mutate_old_proofs_or_candidate():
    case = _case()
    before = tuple(value.model_dump_json() for value in case)
    first, second = _assess(case), _assess(case)
    assert first == second
    assert tuple(value.model_dump_json() for value in case) == before


def test_missing_original_delta_retains_current_and_inherited_inspectable_evidence():
    case = list(_case())
    case[3] = None
    case[7] = case[7].model_copy(update={"inputs_hash": None})
    result = _assess(tuple(case))
    assert result.status == "BLOCKED"
    assert result.source_assessment.raw_delta_verified is False
    assert result.source_refs[:-1] == case[6].source_refs
    assert result.owners and result.authority_granted is False
