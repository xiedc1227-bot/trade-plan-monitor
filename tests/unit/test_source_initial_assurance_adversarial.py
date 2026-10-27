"""Initial assurance rechecks observations, rather than trusting cached self-hashes."""

import json
from copy import deepcopy

import pytest
from tests.unit.test_source_initial_assurance import _binding, _case

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.update_review import build_initial_review, context_from_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.p3_validation import P3PlanDraft
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _inputs(original, **updates):
    values = {
        "source_hash": original.source_hash, "source_binding_hash": original.source_binding_hash,
        "initial_coverage": original.initial_coverage, "normalization": original.normalization,
        "derivation": original.derivation, "derivation_issues": original.derivation_issues,
    }
    return CoverageInputs.build(**(values | updates))


def _run(source, review, mapping, inputs):
    # Derive the header from this actual body; these tests do not invent an authorization header.
    return assess_initial_current(source, review, mapping, inputs,
                                  binding=_binding(source, review, inputs))


def _packet(draft, mapping):
    return {
        "draft": draft.model_dump(mode="json"),
        "clauses": [clause.model_dump(mode="json") for clause in mapping.clauses],
        "bindings": [binding.model_dump(mode="json") for binding in mapping.bindings],
        "assumptions": [], "warnings": [],
    }


def _derivation(source, review, mapping, *, raw=None, normalized=None):
    raw = _packet(review.draft, mapping) if raw is None else raw
    normalized = _packet(review.draft, mapping) if normalized is None else normalized
    return SourceDerivationEvidence.build(
        kind="FULL_DRAFT", source_hash=source.source_hash,
        raw_json="\n" + json.dumps(raw, ensure_ascii=False, indent=2) + "\n\t",
        context_json=None, base_hash=None,
        stages=(DerivationStage.build(phase="SOURCE_NORMALIZED",
                                     output_json=canonical(normalized)),),
    )


def _blocked(result):
    assert result.coverage_complete is False
    assert result.status == "BLOCKED"
    assert result.current_automatic_fidelity_verified is False
    assert result.authority_granted is False
    assert result.issues or result.source_assessment.issues


def _other_draft(draft):
    image = deepcopy(draft.model_dump(mode="json"))
    image["position"]["limit"]["capital_policy"]["cap_fen"] += 1000
    changed = P3PlanDraft.model_validate(image)
    assert changed.to_executable() is not None
    assert daily_draft_content_sha256(changed) != daily_draft_content_sha256(draft)
    return changed


def test_matching_observed_full_draft_and_complete_normalized_map_remain_supported():
    source, review, mapping, inputs, _ = _case(extra="历史记录：2026-10-01买入100股。")
    derivation = _derivation(source, review, mapping)
    augmented = _inputs(inputs, derivation=derivation)

    result = _run(source, review, mapping, augmented)

    assert result.coverage_complete is True
    assert result.current_automatic_fidelity_verified is True
    assert result.authority_granted is False
    assert result.source_assessment == inputs.initial_coverage
    assert mapping.clauses[-1].paths == ()
    observed = json.loads(derivation.stages[0].output_json)["clauses"][-1]
    assert observed == mapping.clauses[-1].model_dump(mode="json")


@pytest.mark.parametrize("location", ["raw-preimage", "normalized-afterimage"])
def test_contradictory_observed_full_draft_cannot_borrow_an_unrelated_valid_normalization(location):
    source, review, mapping, inputs, _ = _case()
    packet = _packet(_other_draft(review.draft), mapping)
    derivation = _derivation(source, review, mapping, **{
        "raw" if location == "raw-preimage" else "normalized": packet,
    })
    augmented = _inputs(inputs, derivation=derivation)
    assert augmented.normalization == inputs.normalization
    assert SourceDerivationEvidence.model_validate_json(derivation.model_dump_json()) == derivation

    result = _run(source, review, mapping, augmented)

    _blocked(result)


def test_predecessor_patch_evidence_cannot_be_silently_accepted_as_initial_full_draft_observation():
    source, review, mapping, inputs, _ = _case()
    binding = _binding(source, review, inputs)
    context = context_from_review(review, binding.candidate_hash)
    packet = canonical(_packet(review.draft, mapping))
    derivation = SourceDerivationEvidence.build(
        kind="PREDECESSOR_PATCH", source_hash=source.source_hash,
        raw_json=canonical({"schema_version": "monitor-loop-delta-wire-v1", "operations": []}),
        context_json=canonical(context.model_dump(mode="json")), base_hash=context.base_hash,
        stages=(DerivationStage.build(phase="DELTA_EXPANDED", output_json=packet),
                DerivationStage.build(phase="SOURCE_NORMALIZED", output_json=packet)),
    )

    result = _run(source, review, mapping, _inputs(inputs, derivation=derivation))

    _blocked(result)


@pytest.mark.parametrize("missing", ["clauses", "bindings"])
def test_normalized_stage_without_the_complete_original_map_is_unproven(missing):
    source, review, mapping, inputs, _ = _case()
    packet = _packet(review.draft, mapping)
    packet.pop(missing)
    derivation = _derivation(source, review, mapping, normalized=packet)

    result = _run(source, review, mapping, _inputs(inputs, derivation=derivation))

    _blocked(result)


@pytest.mark.parametrize("location", ["raw", "normalized"])
def test_observed_map_cannot_lose_an_unbound_original_background_clause(location):
    source, review, mapping, inputs, _ = _case(extra="历史记录：2026-10-01买入100股。")
    assert mapping.clauses[-1].paths == ()
    assert all(mapping.clauses[-1].clause_id not in binding.clause_ids
               for binding in mapping.bindings)
    packet = _packet(review.draft, mapping)
    packet["clauses"].pop()
    derivation = _derivation(source, review, mapping, **{location: packet})

    result = _run(source, review, mapping, _inputs(inputs, derivation=derivation))

    _blocked(result)


@pytest.mark.parametrize("extra", [
    "Only buy when turnover exceeds 3 percent.", "等那扇门打开后再行动。",
])
def test_optimistic_cached_coverage_cannot_remove_a_real_unconsumed_source_remainder(extra):
    source, review, mapping, inputs, _ = _case(extra=extra)
    cached = inputs.initial_coverage
    assert cached.coverage_complete is False and review.issues == ()
    retained = tuple(row for row in cached.obligations if row.excerpt != extra)
    values = cached.model_dump(mode="python", exclude={
        "evidence_hash", "status", "issues", "obligations",
    })
    optimistic = CoverageAssessment.build(**values, obligations=retained, issues=())
    assert optimistic.coverage_complete is True

    result = _run(source, review, mapping, _inputs(inputs, initial_coverage=optimistic))

    _blocked(result)
    assert result.source_assessment != optimistic
    assert any(row.excerpt == extra for row in result.source_assessment.obligations)
    unknown_ids = {row.obligation_id for row in result.source_assessment.obligations
                   if row.excerpt == extra}
    assert unknown_ids <= {row.obligation_id for row in result.global_obligations}


def test_cached_foreign_content_and_mapping_hashes_are_never_the_fresh_server_proof():
    source, review, mapping, inputs, _ = _case()
    cached = inputs.initial_coverage
    values = cached.model_dump(mode="python", exclude={
        "evidence_hash", "status", "issues", "obligations", "content_hash", "mapping_hash",
    })
    foreign = CoverageAssessment.build(**values, obligations=cached.obligations, issues=(),
                                       content_hash="f" * 64, mapping_hash="e" * 64)

    result = _run(source, review, mapping, _inputs(inputs, initial_coverage=foreign))

    expected = assess_source_coverage(review.draft, mapping, source.text,
                                      normalization=inputs.normalization, origin="AI_NEW")
    assert result.source_assessment == expected != foreign
    assert result.content_hash == daily_draft_content_sha256(review.draft)
    assert result.authority_granted is False


def test_full_normalized_afterimage_is_required_even_when_semantic_content_hash_did_not_change():
    source, original, mapping, inputs, _ = _case()
    draft = original.draft.model_copy(update={"name": "A different actual normalized display name"})
    assert daily_draft_content_sha256(draft) == daily_draft_content_sha256(original.draft)
    actual = build_initial_review(draft, mapping, source)

    result = _run(source, actual, mapping, inputs)

    _blocked(result)
    assert any(issue.code == "SOURCE_NORMALIZATION_LOSS"
               for issue in result.source_assessment.issues)


@pytest.mark.parametrize("field", ["source_hash", "candidate_content_hash"])
def test_source_bound_field_projection_must_match_the_full_actual_old_review(field):
    source, review, mapping, inputs, _ = _case()
    first = review.bindings[0]
    wrong = source.source_hash if field == "source_hash" else "f" * 64
    assert wrong != getattr(first, field)
    changed = review.model_copy(update={
        "bindings": (first.model_copy(update={field: wrong}), *review.bindings[1:]),
    })

    with pytest.raises(ValueError):
        _run(source, changed, mapping, inputs)


def test_a_different_complete_map_cannot_reuse_the_original_review_evidence_hash():
    source, review, mapping, inputs, _ = _case()
    first = mapping.clauses[0].model_copy(update={"reason": "A different observed proposal reason"})
    changed = mapping.model_copy(update={"clauses": (first, *mapping.clauses[1:])})
    expected = build_initial_review(review.draft, changed, source)
    assert expected.evidence_hash != review.evidence_hash

    with pytest.raises(ValueError):
        _run(source, review, changed, inputs)


def test_observed_private_derivation_failure_remains_blocking_even_when_fresh_source_is_complete():
    source, review, mapping, inputs, _ = _case()
    observed = CoverageIssue(code="SOURCE_NORMALIZATION_LOSS", path="draft",
                             message="The observed provider derivation failed verification.")

    result = _run(source, review, mapping, _inputs(inputs, derivation_issues=(observed,)))

    _blocked(result)
    assert result.source_assessment.coverage_complete is True
    assert observed in result.issues
