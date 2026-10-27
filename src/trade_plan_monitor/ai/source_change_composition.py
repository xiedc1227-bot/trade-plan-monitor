"""Compose current owners without rewriting or dropping earlier source obligations."""

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_candidate_models import (
    AssuranceSourceRef,
    PrefixAssuranceRef,
    SourceCandidateAssurance,
    SourceObligationRef,
    SourceOwner,
    source_prefix_hash,
)
from trade_plan_monitor.ai.source_change_assurance import assess_source_changes, corresponding_path
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def assess_change_current(source, output, materialized, inputs, *, context, base_review,
                          verified_parent, binding, prefix):
    """Current-source proof and parent ownership are separate, exact dependencies."""
    prefix = tuple(PrefixAssuranceRef.model_validate_json(row.model_dump_json()) for row in prefix)
    expected_prefix = (*verified_parent.prefix, PrefixAssuranceRef(
        binding=verified_parent.binding, assurance_hash=verified_parent.evidence_hash))
    if prefix != expected_prefix:
        raise ValueError("current source prefix differs from the exact verified predecessor")
    assessment = assess_source_changes(source, output, materialized, inputs, context=context,
        base_review=base_review, verified_parent=verified_parent, binding=binding)
    ref = AssuranceSourceRef(source_id=source.source_id, source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, proof_hash=assessment.evidence_hash,
        proof_kind="CHANGE")
    if source.source_id in {row.source_id for row in verified_parent.source_refs}:
        raise ValueError("current source reuses an earlier immutable source identity")
    common = dict(source_id=ref.source_id, source_hash=ref.source_hash,
                  source_binding_hash=ref.source_binding_hash, proof_hash=ref.proof_hash)
    previous_owners = {row.path: row for row in verified_parent.owners}
    previous_values = semantic_values(base_review.draft)
    previous_bindings = {row.path: row for row in base_review.bindings}
    values = semantic_values(materialized.review.draft)
    owners, issues = [], []
    for bound in materialized.review.bindings:
        if (bound.source_id, bound.source_hash) == (source.source_id, source.binding_hash):
            linked = tuple(row.obligation_id for row in assessment.obligations if any(
                bound.original_path == path or bound.original_path.startswith(path + ".")
                or bound.original_path.startswith(path + "[") for path in row.paths))
            if len(linked) > 64:
                issues.append(CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED", path=bound.path,
                    message="Complete current field ownership exceeds its evidence bound."))
                continue
            origin = ("PRODUCT_CONTRACT" if bound.binding.origin == "PRODUCT_CONTRACT"
                      else "HUMAN" if bound.binding.origin == "HUMAN_SUPPLEMENT" else "CURRENT")
            if not linked and origin != "PRODUCT_CONTRACT":
                issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path=bound.path,
                    message="The current field has no independent complete source obligation."))
            owners.append(SourceOwner(**common, path=bound.path,
                original_path=bound.original_path, origin=origin, obligation_ids=linked))
        else:
            previous_path = corresponding_path(bound.path, materialized.review.draft,
                                               base_review.draft)
            owner = previous_owners.get(previous_path)
            prior = previous_bindings.get(previous_path)
            if (owner is None or prior is None or previous_path not in previous_values
                    or bound.path not in values
                    or type(values[bound.path]) is not type(previous_values[previous_path])
                    or values[bound.path] != previous_values[previous_path]
                    or bound != prior.model_copy(update={"path": bound.path})
                    or (owner.source_id, owner.source_binding_hash, owner.original_path)
                    != (bound.source_id, bound.source_hash, bound.original_path)):
                issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path=bound.path,
                    message="The inherited field differs from its exact predecessor owner."))
                continue
            owners.append(owner.model_copy(update={"path": bound.path, "origin": "BASE"}))
    if {row.path for row in owners} != values.keys():
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", path="draft",
            message="The complete materialized candidate has unproven field ownership."))
    globals_ = (*verified_parent.global_obligations, *(SourceObligationRef(**common,
        obligation_id=row.obligation_id, scope=row.scope, state=row.state)
        for row in assessment.obligations if row.scope == "UNKNOWN" or not row.paths
        and row.kind not in {"CONTEXT", "SCOPE_EXCLUSION"}))
    return SourceCandidateAssurance.build(binding=binding,
        content_hash=daily_draft_content_sha256(materialized.review.draft),
        source_assessment=assessment, source_refs=(*verified_parent.source_refs, ref),
        owners=tuple(owners), global_obligations=globals_, prefix=prefix,
        prefix_hash=source_prefix_hash(prefix, binding), parent_hash=verified_parent.evidence_hash,
        issues=tuple(issues))
