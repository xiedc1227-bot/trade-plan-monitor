"""Independent bounded and tamper-resistant current source evidence."""

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, SourceObligation


def obligation(**changes):
    values = dict(source_hash="a" * 64, clause_id="clause-1", start=0, end=10,
                  excerpt="close > 10", kind="PREDICATE", scope="BUY", state="MAPPED",
                  semantics_json='{"comparator":"GT","value":"10"}', paths=("rule.price",))
    return SourceObligation.build(**(values | changes))


def assessment(**changes):
    values = dict(source_hash="a" * 64, content_hash="b" * 64,
                  mapping_hash="c" * 64, origin="AI_HISTORICAL",
                  obligations=(obligation(),), issues=())
    return CoverageAssessment.build(**(values | changes))


def test_exact_obligation_and_assessment_roundtrip_grant_no_authority():
    result = assessment()
    assert result.coverage_complete and result.status == "COMPLETE"
    assert result.authority_granted is False
    assert not result.automatic_fidelity_verified
    assert CoverageAssessment.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("changes", [
    {"start": -1}, {"end": 0}, {"end": 150001}, {"excerpt": "x" * 513},
    {"start": True}, {"kind": "IGNORE"}, {"scope": "ANYTHING"},
    {"state": "CONFIRMED"}, {"paths": ("x" * 513,)},
    {"semantics_json": '{"value":NaN}'}, {"semantics_json": '{"a": 1}'},
])
def test_invalid_scalar_scope_or_noncanonical_meaning_is_rejected(changes):
    with pytest.raises((ValidationError, ValueError)):
        obligation(**changes)


def test_state_and_binding_changes_preserve_source_obligation_identity():
    before = obligation()
    after = obligation(state="UNRESOLVED", paths=())
    assert before.obligation_id == after.obligation_id
    assert before != after
    changed = assessment(obligations=(after,))
    assert not changed.coverage_complete
    assert changed.evidence_hash != assessment().evidence_hash


def test_duplicate_obligations_and_proof_status_tamper_are_rejected():
    with pytest.raises((ValidationError, ValueError), match="duplicate"):
        assessment(obligations=(obligation(), obligation()))
    raw = assessment().model_dump(mode="json")
    raw["source_hash"] = "d" * 64
    with pytest.raises((ValidationError, ValueError)):
        CoverageAssessment.model_validate(raw)


def test_model_bounds_never_truncate_atoms_or_paths():
    with pytest.raises((ValidationError, ValueError)):
        obligation(paths=tuple(str(i) for i in range(513)))
    many = tuple(obligation(clause_id=f"c{i}") for i in range(4097))
    with pytest.raises((ValidationError, ValueError)):
        assessment(obligations=many)


def test_per_clause_bound_accepts_64_and_rejects_65_without_truncating():
    rows = tuple(obligation(start=i, end=i + 10) for i in range(65))
    assert len(assessment(obligations=rows[:64]).obligations) == 64
    with pytest.raises((ValidationError, ValueError), match="LIMIT_EXCEEDED"):
        assessment(obligations=rows)


def test_unknown_source_state_cannot_be_complete_even_without_a_separate_issue():
    assert not assessment(obligations=(obligation(state="UNSUPPORTED"),)).coverage_complete
    assert not assessment(obligations=()).coverage_complete


def test_new_ai_requires_a_normalization_preimage_for_automatic_acceptance():
    result = assessment(origin="AI_NEW")
    assert not result.coverage_complete and not result.automatic_fidelity_verified
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" for i in result.issues)
