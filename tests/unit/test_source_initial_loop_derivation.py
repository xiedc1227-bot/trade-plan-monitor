"""Actual loop full-output evidence retains its protocol and opening-account facts."""

import json
from uuid import UUID

import pytest
from tests.integration.test_source_coverage_preparation_commit import _initial_loop_case
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _case():
    source, mapping, result, inputs = _initial_loop_case(UUID(int=101))
    review = build_initial_review(result.draft, mapping, source)
    binding = _binding(source, review, inputs)
    return source, review, mapping, inputs, binding


def _with_derivation(case, evidence):
    source, review, mapping, inputs, binding = case
    values = {name: getattr(inputs, name) for name in type(inputs).model_fields
              if name != "evidence_hash"}
    inputs = CoverageInputs.build(**(values | {"derivation": evidence}))
    return source, review, mapping, inputs, binding.model_copy(
        update={"inputs_hash": inputs.evidence_hash})


def _assess(case):
    source, review, mapping, inputs, binding = case
    return assess_initial_current(source, review, mapping, inputs, binding=binding)


def test_real_full_loop_protocol_is_verified_without_removing_its_opening_account():
    case = _case()
    raw = case[3].derivation.raw_json
    assert json.loads(raw)["schema_version"] == "monitor-loop-extraction-v1"
    assert "opening_account" in json.loads(raw)
    result = _assess(case)
    assert result.coverage_complete is True
    assert result.current_automatic_fidelity_verified is True
    assert case[3].derivation.raw_json == raw
    assert result.authority_granted is False


def test_initial_full_protocol_cannot_substitute_another_source_hash():
    case = _case()
    original = case[3].derivation
    evidence = SourceDerivationEvidence.build(**(original.model_dump(mode="python", exclude={
        "evidence_hash", "raw_hash", "context_hash"}) | {"source_hash": "f" * 64}))
    with pytest.raises(ValueError, match="another source"):
        _with_derivation(case, evidence)


def test_initial_normalization_cannot_rewrite_opening_account_facts():
    case = _case()
    original = case[3].derivation
    stage = json.loads(original.stages[0].output_json)
    assert stage["opening_account"]["inventory_quantity"]["value"] == 0
    stage["opening_account"]["inventory_quantity"]["value"] = 1
    evidence = SourceDerivationEvidence.build(**(original.model_dump(mode="python", exclude={
        "evidence_hash", "raw_hash", "context_hash", "stages"}) | dict(stages=(
        DerivationStage.build(phase="SOURCE_NORMALIZED", output_json=canonical(stage)),))))
    result = _assess(_with_derivation(case, evidence))
    assert result.status == "BLOCKED"
    assert any(row.code == "SOURCE_NORMALIZATION_LOSS" for row in result.issues)
