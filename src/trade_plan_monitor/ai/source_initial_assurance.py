"""Initial current evidence never inherits the old zero-issue completeness shortcut."""

import json

from trade_plan_monitor.ai.daily_review import semantic_values
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
from trade_plan_monitor.ai.source_normalization import validate_normalization
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _verify_initial_derivation(inputs, review, mapping, source):
    from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput

    evidence = inputs.derivation
    if (evidence.kind != "FULL_DRAFT" or len(evidence.stages) != 1
            or evidence.stages[0].phase != "SOURCE_NORMALIZED" or inputs.normalization is None):
        raise ValueError("initial evidence has no complete observed full-draft protocol")
    before = validate_normalization(inputs.normalization, review.draft, source.text)
    raw = json.loads(evidence.raw_json)
    after = json.loads(evidence.stages[0].output_json)
    original = CurrentPlanExtractionOutput.model_validate_json(evidence.raw_json)
    CurrentPlanExtractionOutput.model_validate_json(evidence.stages[0].output_json)
    if (raw.get("draft") != before or after.get("draft") != review.draft.model_dump(mode="json")
            or original.review(source.text).issues
            or after.get("clauses") != [row.model_dump(mode="json") for row in mapping.clauses]
            or after.get("bindings") != [row.model_dump(mode="json") for row in mapping.bindings]):
        raise ValueError("observed initial draft or complete source map differs")


def assess_initial_current(source, review, mapping, inputs, *, binding, prefix=()):
    """Verify one complete source and retain its original obligation/span identities."""
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    if inputs is not None:
        inputs = CoverageInputs.model_validate_json(inputs.model_dump_json())
    if (binding.source_id, binding.source_binding_hash, binding.review_evidence_hash,
        binding.inputs_hash, review.source_id, review.source_hash) != (
        source.source_id, source.binding_hash, review.evidence_hash,
        None if inputs is None else inputs.evidence_hash, source.source_id, source.binding_hash,
    ) or inputs is not None and (
        inputs.source_hash != scope_hash(source.text)
        or inputs.source_binding_hash != source.binding_hash
    ):
        raise ValueError("initial source/candidate/input binding differs")
    expected = build_initial_review(review.draft, mapping, source)
    if expected != review:
        raise ValueError("initial review differs from its original complete source mapping")
    assessment = assess_source_coverage(review.draft, mapping, source.text,
        normalization=None if inputs is None else inputs.normalization, origin="AI_NEW")
    issues = []
    if review.issues or mapping.supplements:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path="draft",
            message="Initial automatic evidence cannot register human corrections or waive review.",
        ))
    if inputs is not None:
        issues.extend(inputs.derivation_issues)
        if inputs.derivation is not None:
            try:
                _verify_initial_derivation(inputs, review, mapping, source)
            except (ValueError, TypeError, RecursionError):
                issues.append(CoverageIssue(code="SOURCE_NORMALIZATION_LOSS", path="source",
                    message="Observed initial derivation differs from its draft or complete map."))
    ref = AssuranceSourceRef(source_id=source.source_id, source_hash=scope_hash(source.text),
        source_binding_hash=source.binding_hash, proof_hash=assessment.evidence_hash,
        proof_kind="INITIAL")
    common = dict(source_id=ref.source_id, source_hash=ref.source_hash,
                  source_binding_hash=ref.source_binding_hash, proof_hash=ref.proof_hash)
    owners = []
    for bound in review.bindings:
        if (bound.source_id, bound.source_hash) != (source.source_id, source.binding_hash):
            raise ValueError("initial field belongs to another source binding")
        linked = tuple(row.obligation_id for row in assessment.obligations if any(
            bound.path == path or bound.path.startswith(path + ".")
            or bound.path.startswith(path + "[") for path in row.paths
        ))
        if len(linked) > 64:
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED", path=bound.path,
                message="Complete ownership evidence exceeds its bounded relation contract."))
            continue
        origin = ("PRODUCT_CONTRACT" if bound.binding.origin == "PRODUCT_CONTRACT"
                  else "HUMAN" if bound.binding.origin == "HUMAN_SUPPLEMENT" else "CURRENT")
        if not linked and origin != "PRODUCT_CONTRACT":
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path=bound.path,
                message="The candidate field has no independently proven source obligation."))
        owners.append(SourceOwner(**common, path=bound.path, original_path=bound.original_path,
                                  origin=origin, obligation_ids=linked))
    if {row.path for row in owners} != semantic_values(review.draft).keys():
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path="draft",
            message="The complete candidate has unproven source ownership."))
    global_obligations = tuple(SourceObligationRef(**common, obligation_id=row.obligation_id,
        scope=row.scope, state=row.state) for row in assessment.obligations
        if row.scope == "UNKNOWN" or not row.paths
        and row.kind not in {"CONTEXT", "SCOPE_EXCLUSION"})
    return SourceCandidateAssurance.build(binding=binding,
        content_hash=daily_draft_content_sha256(review.draft), source_assessment=assessment,
        source_refs=(ref,), owners=tuple(owners), global_obligations=global_obligations,
        prefix=tuple(prefix), prefix_hash=source_prefix_hash(prefix, binding), parent_hash=None,
        issues=tuple(issues))
