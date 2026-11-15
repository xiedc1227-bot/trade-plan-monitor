"""Current complete-source proof, separate from historical integrity and change proof."""

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.ai.source_obligations import MAX_SOURCE_CODEPOINTS
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash


def assess_source_coverage(draft, mapping, source, *, normalization=None, origin="AI_HISTORICAL",
                           allow_buy_suspension_clarifications=True):
    """Prove the entire source and complete candidate; partial changes use another owner."""
    if isinstance(source, str) and len(source) > MAX_SOURCE_CODEPOINTS:
        return _source_work_limit(draft, mapping, source, origin=origin)
    analysis = analyze_source(draft, mapping, source, normalization=normalization,
        allow_buy_suspension_clarifications=allow_buy_suspension_clarifications)
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


def _source_work_limit(draft, mapping, source, *, origin):
    """Retain native-valid incomplete drafts without claiming source analysis.

    This is an explicit work-cap preflight, not an exception fallback. The full
    old verifier still rejects invalid text, spans, candidate hashes and mapping
    ownership. No oversized source is parsed by the current recognizer, no
    partial obligation list is retained, and no normalization is marked verified.
    """
    native = build_daily_review(draft, mapping, source)
    issues = (CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED", path="source",
        message="The complete preserved source exceeds the current source-analysis work limit; "
                "no source obligations or automatic fidelity have been verified."),
        *(CoverageIssue(code=row.code, path=row.path[:512] or "draft", message=row.reason[:512])
          for row in native.issues))
    return CoverageAssessment.build(source_hash=scope_hash(source),
        content_hash=daily_draft_content_sha256(draft),
        mapping_hash=daily_hash("source-coverage-mapping-v1",
                                native.mapping.model_dump(mode="json")),
        normalization_hash=None, origin=origin, obligations=(), issues=issues)
