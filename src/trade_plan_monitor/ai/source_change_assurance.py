"""AI extraction provenance and raw replay wrap shared complete change semantics."""

import json

from trade_plan_monitor.ai.source_candidate_models import CandidateBinding, SourceCandidateAssurance
from trade_plan_monitor.ai.source_change_core import analyze_source_changes
from trade_plan_monitor.ai.source_change_core import corresponding_path as corresponding_path
from trade_plan_monitor.ai.source_change_models import SourceChangeAssessment
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_derivation_replay import verify_update_derivation
from trade_plan_monitor.ai.update_review import materialize_extraction
from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def assess_source_changes(source, output, materialized, inputs, *, context, base_review,
                          verified_parent, binding):
    """This proof covers the whole current source and writes, never an invented full draft."""
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    verified_parent = SourceCandidateAssurance.model_validate_json(
        verified_parent.model_dump_json())
    if inputs is not None:
        inputs = CoverageInputs.model_validate_json(inputs.model_dump_json())
    candidate = CollectionPreparationCandidate(
        **materialized.to_preparation_candidate().model_dump(mode="python"),
        source_revision=binding.source_revision, source_hash=source.binding_hash,
        base_hash=context.base_hash)
    if (binding.independent or binding.preparation_id != verified_parent.binding.preparation_id
            or binding.item_index != verified_parent.binding.item_index + 1
            or binding.source_id == verified_parent.binding.source_id
            or binding.candidate_hash != candidate.candidate_hash
            or binding.attempt_id != str(materialized.extraction.request_id)):
        raise ValueError("current update belongs to another preparation/candidate/attempt")
    if (binding.source_id, binding.source_binding_hash, binding.review_evidence_hash,
        binding.inputs_hash, materialized.review.source_id, materialized.review.source_hash,
        materialized.extraction.base_hash, materialized.extraction.output.model_dump_json()) != (
        source.source_id, source.binding_hash, materialized.review.evidence_hash,
        None if inputs is None else inputs.evidence_hash, source.source_id, source.binding_hash,
        context.base_hash, output.model_dump_json(),
    ) or inputs is not None and (
        inputs.source_hash != source.source_hash
        or inputs.source_binding_hash != source.binding_hash
    ):
        raise ValueError("current update source/candidate/input binding differs")
    expected = materialize_extraction(base_review, context.base_hash, source,
                                     materialized.extraction)
    if materialized.review != expected.review:
        raise ValueError("current materialization differs from its exact source and predecessor")
    analysis = analyze_source_changes(source, output, materialized.review,
        output.review(source.text).mapping, context=context, base_review=base_review,
        verified_parent=verified_parent)
    issues = list(analysis.head_issues)

    def issue(message, path="source", code="SOURCE_COVERAGE_REQUIRED"):
        issues.append(CoverageIssue(code=code, path=path, message=message))

    evidence = None if inputs is None else inputs.derivation
    raw_verified, full_supplied = False, False
    if inputs is not None:
        issues.extend(inputs.derivation_issues)
    if evidence is not None:
        try:
            if len(evidence.stages) != 3:
                raise ValueError("materialized derivation is incomplete")
            verify_update_derivation(evidence, source, context, output)
        except (ValueError, TypeError, RecursionError):
            issue("The original current-source delta or deterministic derivation is unproven.",
                  code="SOURCE_NORMALIZATION_LOSS")
        else:
            raw_verified = True
            full_supplied = isinstance(json.loads(evidence.raw_json).get("draft"), dict)
    else:
        issue("The observed provider delta is missing; a reconstructed full draft is not evidence.",
              code="SOURCE_NORMALIZATION_LOSS")
    issues.extend(analysis.tail_issues)
    return SourceChangeAssessment.build(binding=binding, source_hash=analysis.source_hash,
        source_binding_hash=analysis.source_binding_hash,
        content_hash=analysis.content_hash, mapping_hash=analysis.mapping_hash,
        review_evidence_hash=analysis.review_evidence_hash, base_hash=analysis.base_hash,
        parent_assurance_hash=analysis.parent_assurance_hash,
        inputs_hash=None if inputs is None else inputs.evidence_hash,
        derivation_hash=None if evidence is None else evidence.evidence_hash,
        raw_delta_verified=raw_verified, provider_full_draft_supplied=full_supplied,
        full_draft_fidelity_verified=False, parent_verified=analysis.parent_verified,
        operations=analysis.operations, changed_paths=analysis.changed_paths,
        obligations=analysis.obligations, issues=tuple(issues))
