"""Explicit human source reassessment never manufactures original AI fidelity."""

from trade_plan_monitor.ai.daily_review import DailyMapping, semantic_values
from trade_plan_monitor.ai.source_candidate_models import (
    AssuranceSourceRef,
    CandidateBinding,
    SourceCandidateAssurance,
    SourceObligationRef,
    SourceOwner,
    source_prefix_hash,
)
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.update_review import PlanCandidateReview, build_initial_review
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def assess_human_initial_current(
    source, review, complete_mapping, operation, *, binding, prefix=(),
):
    """The state adapter must independently authenticate this exact registered operation.

    This pure function proves complete supported source meaning for its resolved
    policy. A valid operation self-hash alone is never registration or authority.
    """
    operation = PreparationHumanOperation.model_validate_json(operation.model_dump_json())
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    review = PlanCandidateReview.model_validate_json(review.model_dump_json())
    mapping = DailyMapping.model_validate_json(complete_mapping.model_dump_json())
    if (operation.source != source or operation.source_binding_hash != source.binding_hash
            or operation.resolved_update is not None
            or operation.resolved_draft != review.draft
            or operation.resolved_review != review or operation.resolved_mapping != mapping
            or operation.assessment_binding != binding or operation.prefix != tuple(prefix)
            or binding.item_index and not binding.independent
            or (binding.source_id, binding.source_binding_hash, binding.review_evidence_hash,
                binding.attempt_id) != (source.source_id, source.binding_hash,
                review.evidence_hash, operation.attempt_id)
            or (operation.original_input_state == "MISSING") != (binding.inputs_hash is None)):
        raise ValueError("human initial operation differs from the exact source/policy binding")
    if operation.operation == "CORRECT_ITEM" and (
        binding.candidate_hash, binding.candidate_revision, binding.review_evidence_hash,
    ) != (operation.after_candidate_hash, operation.after_candidate_revision,
          operation.after_evidence_hash):
        raise ValueError("human correction assessment differs from its actual candidate transition")
    if build_initial_review(review.draft, mapping, source) != review:
        raise ValueError("human initial review differs from its complete original source mapping")
    assessment = assess_source_coverage(review.draft, mapping, source.text, origin="HUMAN")
    ref = AssuranceSourceRef(source_id=source.source_id, source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, proof_hash=assessment.evidence_hash,
        proof_kind="INITIAL")
    common = dict(source_id=ref.source_id, source_hash=ref.source_hash,
                  source_binding_hash=ref.source_binding_hash, proof_hash=ref.proof_hash)
    owners, issues = [], []
    if review.issues:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path="draft",
            message="The explicit human candidate still has unresolved source or policy issues."))
    supplements = {row.supplement_id: row for row in mapping.supplements}
    for bound in review.bindings:
        if (bound.source_id, bound.source_hash) != (source.source_id, source.binding_hash):
            raise ValueError("human initial field belongs to another exact source")
        linked = tuple(row.obligation_id for row in assessment.obligations if any(
            bound.path == path or bound.path.startswith(path + ".")
            or bound.path.startswith(path + "[") for path in row.paths))
        if len(linked) > 64:
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED", path=bound.path,
                message="Complete human field ownership exceeds its bounded evidence contract."))
            continue
        product = bound.binding.origin == "PRODUCT_CONTRACT"
        supplied = (bound.binding.origin == "HUMAN_SUPPLEMENT"
                    and bound.binding.supplement_id in supplements)
        if not linked and not product and not supplied:
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path=bound.path,
                message="Human confirmation cannot waive a missing independent source obligation."))
        owners.append(SourceOwner(**common, path=bound.path, original_path=bound.original_path,
            origin="PRODUCT_CONTRACT" if product else "HUMAN", obligation_ids=linked,
            human_receipt_hash=None if product else operation.evidence_hash))
    if {row.path for row in owners} != semantic_values(review.draft).keys():
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path="draft",
            message="The complete human candidate has unproven field ownership."))
    global_obligations = tuple(SourceObligationRef(**common, obligation_id=row.obligation_id,
        scope=row.scope, state=row.state) for row in assessment.obligations
        if row.scope == "UNKNOWN" or not row.paths
        and row.kind not in {"CONTEXT", "SCOPE_EXCLUSION"})
    return SourceCandidateAssurance.build(binding=binding,
        content_hash=daily_draft_content_sha256(review.draft), source_assessment=assessment,
        source_refs=(ref,), owners=tuple(owners), global_obligations=global_obligations,
        prefix=tuple(prefix), prefix_hash=source_prefix_hash(prefix, binding), parent_hash=None,
        issues=tuple(issues))
