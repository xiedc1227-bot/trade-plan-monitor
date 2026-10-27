"""Human updates reuse complete semantics without inventing provider result wrappers."""

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_change_composition import compose_source_change_assurance
from trade_plan_monitor.ai.source_change_core import analyze_source_changes
from trade_plan_monitor.ai.source_human_change_models import HumanSourceChangeAssessment
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate


def assess_human_change_current(source, output, reviewed, complete_mapping, operation, *, context,
                                base_review, verified_parent, binding, prefix):
    """Actual state registration belongs to the authoritative preparation adapter.

    This entry verifies that the supplied registered operation and independently
    recomputed source semantics describe exactly the same current candidate.
    """
    operation = PreparationHumanOperation.model_validate_json(operation.model_dump_json())
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    if (operation.operation != "CORRECT_ITEM" or operation.independent
            or operation.resolved_update is None
            or operation.source != source or operation.source_binding_hash != source.binding_hash
            or operation.resolved_update.model_dump_json() != output.model_dump_json()
            or operation.resolved_review != reviewed
            or operation.resolved_mapping != complete_mapping
            or operation.assessment_binding != binding or operation.prefix != tuple(prefix)
            or operation.parent_hash != verified_parent.evidence_hash
            or operation.attempt_id != binding.attempt_id
            or not isinstance(operation.original_candidate, CollectionPreparationCandidate)
            or operation.original_candidate.base_hash != context.base_hash
            or (operation.original_input_state == "MISSING") != (binding.inputs_hash is None)):
        raise ValueError("human change differs from the exact source/policy/parent binding")
    candidate = CollectionPreparationCandidate(
        **reviewed.to_preparation_candidate().model_dump(mode="python"),
        source_revision=binding.source_revision, source_hash=source.binding_hash,
        base_hash=context.base_hash)
    if (binding.source_id, binding.source_binding_hash, binding.candidate_revision,
        binding.candidate_hash, binding.review_evidence_hash) != (
        source.source_id, source.binding_hash, operation.after_candidate_revision,
        operation.after_candidate_hash, operation.after_evidence_hash,
    ) or candidate.candidate_hash != binding.candidate_hash:
        raise ValueError("human change assessment differs from its actual candidate transition")
    analysis = analyze_source_changes(source, output, reviewed, complete_mapping, context=context,
        base_review=base_review, verified_parent=verified_parent)
    assessment = HumanSourceChangeAssessment.build(binding=binding,
        source_hash=analysis.source_hash, source_binding_hash=analysis.source_binding_hash,
        content_hash=analysis.content_hash, mapping_hash=analysis.mapping_hash,
        review_evidence_hash=analysis.review_evidence_hash, base_hash=analysis.base_hash,
        parent_assurance_hash=analysis.parent_assurance_hash, inputs_hash=binding.inputs_hash,
        parent_verified=analysis.parent_verified, operations=analysis.operations,
        changed_paths=analysis.changed_paths, obligations=analysis.obligations,
        issues=(*analysis.head_issues, *analysis.tail_issues),
        human_operation_hash=operation.evidence_hash)
    return compose_source_change_assurance(source, reviewed, assessment,
        base_review=base_review, verified_parent=verified_parent, binding=binding, prefix=prefix)
