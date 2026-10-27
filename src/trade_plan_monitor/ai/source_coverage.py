"""Current complete-source proof, separate from historical integrity and change proof."""

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def assess_source_coverage(draft, mapping, source, *, normalization=None, origin="AI_HISTORICAL"):
    """Prove the entire source and complete candidate; partial changes use another owner."""
    analysis = analyze_source(draft, mapping, source, normalization=normalization)
    mapping = analysis.mapping
    issues = list(analysis.issues)
    obligations = analysis.obligations
    proven_paths = analysis.proven_paths
    source_hash = analysis.source_hash
    normalization_hash = analysis.normalization_hash
    for binding in mapping.bindings:
        if (binding.origin in {"SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC"}
                and (binding.path not in proven_paths or not set(binding.clause_ids)
                     <= proven_paths[binding.path])):
            issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH", path=binding.path,
                message="Candidate policy lacks an independent complete source derivation."))

    # The old verifier still owns its field/provenance constraints. Its success
    # cannot waive the independent source obligations above.
    try:
        old = build_daily_review(draft, mapping, source)
    except ValueError as error:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
            message=str(error)[:512] or "Existing source evidence is invalid."))
    else:
        issues.extend(CoverageIssue(code=i.code, path=i.path[:512] or "draft",
            message=i.reason[:512]) for i in old.issues)
    return CoverageAssessment.build(source_hash=source_hash,
        content_hash=daily_draft_content_sha256(draft),
        mapping_hash=daily_hash("source-coverage-mapping-v1", mapping.model_dump(mode="json")),
        normalization_hash=normalization_hash,
        origin=origin, obligations=tuple(obligations), issues=tuple(issues))
