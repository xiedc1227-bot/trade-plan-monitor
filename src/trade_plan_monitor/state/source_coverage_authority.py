"""Current assurance orchestration; historical review derivation stays unchanged."""

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.ai.source_normalization import capture_normalization, validate_normalization
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageCommandConflict,
    SourceCoverageStore,
)
from trade_plan_monitor.state.source_coverage_values import CoverageInputs, CoverageReviewReceipt


class SourceCoverageAuthorityError(ValueError):
    def __init__(self, reason="SOURCE_COVERAGE_REQUIRED"):
        self.reason = reason
        super().__init__(reason)


def extraction_inputs(result):
    """Capture actual private carriers before the historical serializer excludes them."""
    issues = tuple(row if isinstance(row, CoverageIssue) else CoverageIssue(
        code=row if row in {"SOURCE_NORMALIZATION_LOSS", "SOURCE_COVERAGE_LIMIT_EXCEEDED"}
        else "SOURCE_NORMALIZATION_LOSS", path="source",
        message="The original extraction derivation is incomplete or exceeds its evidence limit.",
    ) for row in getattr(result, "derivation_issues", ()))
    return CoverageInputs.build(source_hash=result.source_text_sha256,
        source_binding_hash=getattr(result, "source_binding_hash", None),
        initial_coverage=getattr(result, "coverage", None),
        normalization=getattr(result, "normalization_trace", None),
        derivation=getattr(result, "source_derivation", None),
        derivation_issues=issues)


def save_extraction_inputs(work, result, *, replay=False):
    store = SourceCoverageStore(work.daily.session)
    identity = str(result.request_id)
    if replay and store.input(identity) is None:
        # A historical public JSON result cannot retrospectively acquire raw fidelity.
        raise SourceCoverageCommandConflict()
    return store.save_input(identity, extraction_inputs(result))


def _assessment(draft, mapping, source, *, inputs, origin):
    trace = None if inputs is None or origin != "AI_NEW" else inputs.normalization
    assessment = assess_source_coverage(draft, mapping, source, normalization=trace, origin=origin)
    if inputs is not None and origin == "AI_NEW" and inputs.derivation_issues:
        values = assessment.model_dump(mode="python", exclude={"evidence_hash", "status"})
        values["obligations"] = assessment.obligations
        values["issues"] = (*assessment.issues, *inputs.derivation_issues)
        assessment = CoverageAssessment.build(**values)
    return assessment


def save_version_coverage(work, version_id, draft, mapping, source, *, extraction_id, clock):
    store = SourceCoverageStore(work.daily.session)
    inputs, origin = None, "HUMAN"
    if extraction_id is not None:
        origin = "AI_NEW"
        inputs = store.input(extraction_id)
        original = work.daily.get("extraction-" + extraction_id)
        if original is None:
            raise ValueError("coverage extraction provenance was not recorded by the server")
        before = load_daily_draft_json(canonical(original["payload"]["draft"]))
        if daily_draft_content_sha256(before) != daily_draft_content_sha256(draft):
            # Explicitly saving an edited policy is a human change. Reassess every
            # source span; retain the old private input, without raw fidelity claims.
            origin = "HUMAN"
        elif inputs is not None and inputs.normalization is not None and before != draft:
            try:
                preimage = validate_normalization(inputs.normalization, before, source)
                trace = capture_normalization(preimage, draft.model_dump(mode="json"), source,
                                              reason="SERVER_VERSION_ASSIGNMENT")
            except (ValueError, TypeError, RecursionError):
                # Preserve the unproven trace and inspectable DRAFT. The independent
                # assessment records normalization loss; never invent its preimage.
                pass
            else:
                inputs = CoverageInputs.build(source_hash=inputs.source_hash,
                    source_binding_hash=inputs.source_binding_hash,
                    initial_coverage=inputs.initial_coverage,
                    normalization=trace, derivation=inputs.derivation,
                    derivation_issues=inputs.derivation_issues)
    assessment = _assessment(draft, mapping, source, inputs=inputs, origin=origin)
    return store.append(version_id, assessment, inputs=inputs, expected_revision=0,
                        command_id="coverage-save-" + version_id, now=clock())


def read_version_coverage(work, details):
    """Read/recompute current correspondence without writes or new authority."""
    return _read_version_coverage(work.daily.session, details)


def _read_version_coverage(session, details):
    stored = SourceCoverageStore(session).latest(details.id)
    if stored is None:
        return None
    draft = load_daily_draft_json(details.payload_json)
    _verify_supplements(session, draft, details.daily_mapping)
    if stored.assessment.source_hash != scope_hash(details.source_text):
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    current = _assessment(draft, details.daily_mapping, details.source_text,
                          inputs=stored.inputs, origin=stored.assessment.origin)
    if current.evidence_hash != stored.assessment.evidence_hash:
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    return stored


def _verify_supplements(session, draft, mapping):
    if not mapping.supplements:
        return
    from trade_plan_monitor.state.daily_repository import DailyRepository

    identity = daily_hash("daily-human-supplements-v1", dict(
        symbol=draft.symbol, content_hash=daily_draft_content_sha256(draft),
    ))
    record = DailyRepository(session, clock=None, id_factory=None).get(identity)
    if (record is None or record["kind"] != "DRAFT"
            or record["payload"].get("source") != "EXPLICIT_HUMAN_OPERATION"
            or record["payload"].get("supplements") != [
                row.model_dump(mode="json") for row in mapping.supplements]):
        raise SourceCoverageAuthorityError()


def _require_current_coverage(session, details, *, require_review=False):
    stored = _read_version_coverage(session, details)
    if stored is None or not stored.assessment.coverage_complete:
        raise SourceCoverageAuthorityError()
    if require_review:
        receipt = None if details.review_id is None else SourceCoverageStore(session).receipt(
            details.review_id)
        if receipt is None:
            raise SourceCoverageAuthorityError()
        assessment = stored.assessment
        if (receipt.plan_version_id, receipt.review_id, receipt.review_revision,
            receipt.original_review_evidence_hash, receipt.confirmed_at,
            receipt.coverage_revision, receipt.coverage_bundle_hash,
            receipt.coverage_evidence_hash, receipt.coverage_rules_version,
            receipt.source_hash, receipt.content_hash, receipt.mapping_hash) != (
            details.id, details.review_id, details.review_revision, details.review_evidence_hash,
            details.review_confirmed_at, stored.revision, stored.evidence_hash,
            assessment.evidence_hash, assessment.rules_version,
            assessment.source_hash, assessment.content_hash, assessment.mapping_hash,
        ):
            raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    return stored


def require_current_coverage(work, details, *, require_review=False):
    return _require_current_coverage(work.daily.session, details, require_review=require_review)


def require_confirmation_coverage(work, details, command):
    expected = (getattr(command, "coverage_evidence_hash", None),
                getattr(command, "coverage_rules_version", None))
    if None in expected:
        raise SourceCoverageAuthorityError()
    stored = require_current_coverage(work, details)
    if expected != (stored.assessment.evidence_hash, stored.assessment.rules_version):
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    if details.review_id is not None or details.review_revision != 0 or details.status != "DRAFT":
        # The old confirmation ID/revision/time are immutable. A fresh version is
        # required rather than upgrading a historical receipt in place.
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    return stored


def save_coverage_receipt(work, details, stored):
    proof = stored.assessment
    receipt = CoverageReviewReceipt.build(plan_version_id=details.id, review_id=details.review_id,
        review_revision=details.review_revision, coverage_revision=stored.revision,
        coverage_evidence_hash=proof.evidence_hash, coverage_bundle_hash=stored.evidence_hash,
        coverage_rules_version=proof.rules_version, source_hash=proof.source_hash,
        content_hash=proof.content_hash, mapping_hash=proof.mapping_hash,
        original_review_evidence_hash=details.review_evidence_hash,
        confirmed_at=details.review_confirmed_at)
    return SourceCoverageStore(work.daily.session).save_receipt(receipt)


def require_repository_review(repo, version_id):
    details = repo.get_version_details(version_id)
    if details is None or details.daily_mapping is None:
        raise SourceCoverageAuthorityError()
    return _require_current_coverage(repo._session, details, require_review=True)
