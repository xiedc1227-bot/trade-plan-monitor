"""Current delta evidence proves changes separately from exact parent assurance.

Pure fixtures preserve actual admitted delta/derivation images without providers,
databases, human approval or modifications to historical review/hash contracts.
"""

import importlib
import json
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.integration.test_current_plan_api import simple_plan
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_plan_preparation_worker import collection_update_result
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_coverage_baseline import _append_as_context
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_candidate_models import CandidateBinding
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_derivation_replay import expand_update_with_evidence
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import (
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationSource,
)
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.source_coverage_authority import extraction_inputs
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _assess(*args, **kwargs):
    module = importlib.import_module("trade_plan_monitor.ai.source_change_assurance")
    return module.assess_source_changes(*args, **kwargs)


def _parent(*, extra=None, with_normalization=True):
    draft = UnifiedPlanDraft.from_executable(simple_plan())
    text, mapping = source_mapping(draft)
    if extra is not None:
        text, mapping = _append_as_context(text, mapping, extra, semantic_role="COMMENTARY",
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Background commentary"))
    source = PreparationSource(source_id="parent-source", text=text,
        available_at=_NOW - timedelta(days=1),
        effective_trade_date=(_NOW - timedelta(days=1)).date())
    review = build_initial_review(draft, mapping, source)
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text) if with_normalization else None
    assessment = assess_source_coverage(draft, mapping, text, normalization=trace, origin="AI_NEW")
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace, initial_coverage=assessment)
    binding = _binding(source, review, inputs)
    current = assess_initial_current(source, review, mapping, inputs, binding=binding)
    assert current.coverage_complete is (extra is None and with_normalization)
    return review, current


def _current_binding(source, materialized, inputs, context, parent):
    candidate = CollectionPreparationCandidate(
        **materialized.to_preparation_candidate().model_dump(mode="python"),
        source_revision=1, source_hash=source.binding_hash, base_hash=context.base_hash)
    return CandidateBinding(preparation_id=parent.binding.preparation_id, item_index=1,
        source_id=source.source_id, source_revision=1, source_binding_hash=source.binding_hash,
        candidate_revision=1, candidate_hash=candidate.candidate_hash,
        review_evidence_hash=materialized.review.evidence_hash,
        attempt_id=str(materialized.extraction.request_id),
        inputs_hash=None if inputs is None else inputs.evidence_hash, independent=False)


def _assemble(base, parent, source, patch, context):
    raw = json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    output, derivation = expand_update_with_evidence(raw, source, context)
    extraction = collection_update_result(base, source, output, UUID(int=124), context)
    extraction = extraction.model_copy(update={"source_derivation": derivation})
    materialized = materialize_extraction(base, context.base_hash, source, extraction)
    inputs = extraction_inputs(materialized.extraction)
    binding = _current_binding(source, materialized, inputs, context, parent)
    return source, output, materialized, inputs, context, base, parent, binding


def _case(text="position.max_qty = 500", *, extra=None, role="COMMENTARY",
          parent_extra=None, parent_normalization=True, context_base_hash=None):
    base, parent = _parent(extra=parent_extra, with_normalization=parent_normalization)
    primary_text = text
    if extra is not None:
        text += "\n" + extra
    source = PreparationSource(source_id="change-source", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    context = context_from_review(base, parent.binding.candidate_hash)
    if context_base_hash is not None:
        context = context.model_copy(update={"base_hash": context_base_hash})
    _, patch = delta(text, values={"max_qty": 500})
    if extra is not None:
        primary_ids = tuple(clause.clause_id for clause in server_source_clauses(text)
                            if clause.start < len(primary_text))
        patch = patch.model_copy(update={
            "operations": tuple(operation.model_copy(update={"clause_ids": primary_ids})
                                for operation in patch.operations),
            "clauses": tuple(clause if clause.clause_id in primary_ids else clause.model_copy(
                update={"disposition": "BACKGROUND", "meaning": role, "paths": ()})
                for clause in patch.clauses),
        })
    return _assemble(base, parent, source, patch, context)


def test_exact_current_scalar_change_does_not_require_requoting_unchanged_parent_fields():
    source, output, materialized, inputs, context, base, parent, binding = _case()
    assert "draft" not in json.loads(inputs.derivation.raw_json)

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "COMPLETE" and result.coverage_complete is True
    assert result.source_hash == source.source_hash
    assert result.source_binding_hash == source.binding_hash
    assert result.parent_assurance_hash == parent.evidence_hash
    assert result.base_hash == context.base_hash
    assert result.derivation_hash == inputs.derivation.evidence_hash
    assert result.content_hash == daily_draft_content_sha256(materialized.review.draft)
    assert result.review_evidence_hash == materialized.review.evidence_hash
    assert set(result.changed_paths) == {"position.max_qty"}
    assert result.operation_ids
    assert result.raw_delta_verified is True and result.provider_full_draft_supplied is False
    assert result.automatic_fidelity_verified is False and result.authority_granted is False


@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
@pytest.mark.parametrize("extra", [
    "Only buy when turnover exceeds 3 percent.",
    "仅当换手率超过3%时才允许买入。",
    "等那扇门打开后再行动。",
], ids=["mandatory_en", "mandatory_zh", "keyword_free"])
def test_current_background_roles_cannot_drop_unknown_conditions_or_assume_buy_scope(role, extra):
    source, output, materialized, inputs, context, base, parent, binding = _case(
        extra=extra, role=role)
    assert materialized.review.issues == ()
    original_review = materialized.review.model_dump_json()

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "BLOCKED" and result.coverage_complete is False
    assert result.issues and result.authority_granted is False
    unknown = [atom for atom in result.obligations if atom.excerpt == extra]
    assert unknown and all(atom.scope == "UNKNOWN" for atom in unknown)
    assert all(atom.source_hash == source.source_hash for atom in unknown)
    assert all(source.text[atom.start:atom.end] == extra for atom in unknown)
    assert materialized.review.model_dump_json() == original_review


@pytest.mark.parametrize("missing", ["all_inputs", "raw_derivation"])
def test_missing_original_patch_blocks_without_fabricating_full_draft_or_discarding_candidate(
    missing,
):
    source, output, materialized, _, context, base, parent, _ = _case()
    extraction = materialized.extraction.model_copy(update={"source_derivation": None})
    materialized = materialized.model_copy(update={"extraction": extraction})
    inputs = (None if missing == "all_inputs" else extraction_inputs(extraction))
    binding = _current_binding(source, materialized, inputs, context, parent)
    original = materialized.model_dump_json()

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "BLOCKED"
    assert result.raw_delta_verified is False
    assert result.provider_full_draft_supplied is False
    assert result.automatic_fidelity_verified is False
    assert result.authority_granted is False and result.issues
    assert materialized.model_dump_json() == original
    assert inputs is None or (inputs.derivation is None and inputs.normalization is None)


@pytest.mark.parametrize("problem", ["missing_raw", "global_unknown"])
def test_incomplete_current_parent_cannot_be_replaced_by_its_old_zero_issue_review(problem):
    arguments = ({"parent_normalization": False} if problem == "missing_raw" else {
        "parent_extra": "Everything else depends on the blue lantern.",
    })
    source, output, materialized, inputs, context, base, parent, binding = _case(**arguments)
    assert base.issues == () and parent.coverage_complete is False
    assert materialized.review.issues == ()

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "BLOCKED" and result.issues
    assert result.parent_assurance_hash == parent.evidence_hash
    assert result.authority_granted is False


def test_a_self_consistent_replayed_context_cannot_substitute_its_own_untrusted_base_hash():
    source, output, materialized, inputs, context, base, parent, binding = _case(
        context_base_hash="f" * 64)
    assert context.base_hash != parent.binding.candidate_hash
    assert inputs.derivation.base_hash == context.base_hash
    assert materialized.extraction.base_hash == context.base_hash
    assert len(inputs.derivation.stages) == 3
    # The existing materializer and exact local derivation already accepted this
    # self-consistent context. Only the trusted parent relation can reject it.

    with pytest.raises(ValueError):
        _assess(source, output, materialized, inputs, context=context,
            base_review=base, verified_parent=parent, binding=binding)


def test_same_base_hash_cannot_hide_a_different_assessment_context():
    source, output, materialized, inputs, context, base, parent, binding = _case()
    context = context.model_copy(update={
        "available_at": context.available_at - timedelta(minutes=1),
    })
    assert context.base_hash == parent.binding.candidate_hash
    assert context != context_from_review(base, parent.binding.candidate_hash)
    assert len(inputs.derivation.stages) == 3 and not materialized.review.issues

    with pytest.raises(ValueError):
        _assess(source, output, materialized, inputs, context=context,
            base_review=base, verified_parent=parent, binding=binding)


@pytest.mark.parametrize("field,value", [
    ("source_binding_hash", "a" * 64), ("inputs_hash", "b" * 64),
    ("review_evidence_hash", "c" * 64),
])
def test_current_binding_must_match_source_private_inputs_and_materialized_review(field, value):
    source, output, materialized, inputs, context, base, parent, binding = _case()
    binding = binding.model_copy(update={field: value})

    with pytest.raises(ValueError):
        _assess(source, output, materialized, inputs, context=context,
            base_review=base, verified_parent=parent, binding=binding)


def test_source_change_composition_is_deterministic_and_keeps_all_historical_inputs_unchanged():
    source, output, materialized, inputs, context, base, parent, binding = _case()
    objects = (source, output, materialized, inputs, context, base, parent, binding)
    before = tuple(value.model_dump_json() for value in objects)
    old_review_hash = materialized.review.evidence_hash

    first = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)
    second = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert first == second and first.evidence_hash == second.evidence_hash
    assert tuple(value.model_dump_json() for value in objects) == before
    assert materialized.review.evidence_hash == old_review_hash
