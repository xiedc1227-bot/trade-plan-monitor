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
    SourceCoverageIntegrityError,
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
    return _read_version_coverage(work.daily.session, details, clock=work.daily.clock)


def _read_version_coverage(session, details, *, clock):
    stored = SourceCoverageStore(session).latest(details.id)
    if stored is None:
        return None
    draft = load_daily_draft_json(details.payload_json)
    _verify_supplements(session, draft, details.daily_mapping, clock=clock)
    validate_buy_suspension_clarifications(draft, details.daily_mapping.supplements,
                                          details.source_text)
    _verify_buy_suspension_replacement_intent(session, details, draft, clock=clock)
    if stored.assessment.source_hash != scope_hash(details.source_text):
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    current = _assessment(draft, details.daily_mapping, details.source_text,
                          inputs=stored.inputs, origin=stored.assessment.origin)
    if current.evidence_hash != stored.assessment.evidence_hash:
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    return stored


def _verify_supplements(session, draft, mapping, *, clock):
    if not mapping.supplements:
        return
    from trade_plan_monitor.state.daily_repository import DailyRepository

    identity = daily_hash("daily-human-supplements-v1", dict(
        symbol=draft.symbol, content_hash=daily_draft_content_sha256(draft),
    ))
    try:
        record = DailyRepository(session, clock=clock, id_factory=None).get(identity)
    except (ValueError, TypeError, RecursionError):
        raise SourceCoverageIntegrityError() from None
    if (record is None or record["kind"] != "DRAFT"
            or record["payload"].get("source") != "EXPLICIT_HUMAN_OPERATION"
            or record["payload"].get("supplements") != [
                row.model_dump(mode="json") for row in mapping.supplements]):
        raise SourceCoverageAuthorityError()


def validate_buy_suspension_clarifications(draft, supplements, source_text):
    """Resolve every claimed obligation from the actual source, never a client ID list."""
    import json

    from trade_plan_monitor.ai.daily_review import DailyMapping, daily_source_clauses
    from trade_plan_monitor.ai.source_coverage_core import analyze_source
    from trade_plan_monitor.ai.source_obligations import MISSING, declarations, declared_value_at

    scoped = tuple(s for s in supplements if s.source_hash is not None)
    if not scoped:
        return
    if draft.schema_version != 10 or source_text is None:
        raise ValueError("persistent BUY clarification requires its exact source text")
    digest = daily_draft_content_sha256(draft)
    mapping = DailyMapping(mapping_version="daily-mapping-v1", candidate_content_hash=digest,
        clauses=daily_source_clauses(source_text), bindings=(), supplements=())
    raw = analyze_source(draft, mapping, source_text, allow_buy_suspension_clarifications=False)
    obligations = {o.obligation_id: o for o in raw.obligations if o.semantics_json is not None
                   and json.loads(o.semantics_json).get("treatment") == "PERSISTENT_BUY_SUSPENSION"}
    parsed = declarations(source_text)
    allowed = {"buy_suspension.condition.type", "buy_suspension.condition.timeframe_minutes",
               "buy_suspension.condition.price_fen", "buy_suspension.effective_from"}
    for supplement in scoped:
        obligation = obligations.get(supplement.obligation_id)
        if (supplement.source_hash != scope_hash(source_text) or obligation is None
                or supplement.candidate_content_hash != digest or supplement.path not in allowed):
            raise ValueError("persistent BUY clarification belongs to another source or obligation")
        meaning = json.loads(obligation.semantics_json)
        known = declared_value_at(parsed, supplement.path)
        if supplement.path == "buy_suspension.condition.price_fen":
            known = meaning["price_fen"]
        elif supplement.path == "buy_suspension.condition.timeframe_minutes" and (
                meaning["timeframe_minutes"] is not None):
            known = meaning["timeframe_minutes"]
        if known is not MISSING and known is not None and canonical(known) != canonical(
                supplement.value):
            raise ValueError("clarification cannot override an explicit source value")


def validate_buy_suspension_replacement_intent(draft, intent, source_text):
    """Validate a finite explicit source proposal, without resolving runtime ancestry."""
    from trade_plan_monitor.ai.source_boundaries import partition_at, source_partitions

    if (draft.schema_version != 10 or source_text is None
            or intent.source_hash != scope_hash(source_text)
            or intent.candidate_content_hash != daily_draft_content_sha256(draft)
            or source_text[intent.source_start:intent.source_end] != intent.excerpt
            or intent.source_start and source_text[intent.source_start - 1] not in "\r\n"
            or intent.source_end < len(source_text) and source_text[intent.source_end] not in "\r\n"
            or partition_at(source_partitions(source_text), intent.source_start) == "B"):
        raise ValueError("replacement intent differs from the exact complete new source statement")
    retirement = {
        "This new plan replaces the predecessor BUY suspension and explicitly retires its guard.",
        "本新计划明确接替前序计划的持续禁买义务，并明确废止旧保护条件。",
    }
    new_guard = {
        "This new plan replaces the predecessor BUY suspension and supplies a new guard.",
        "本新计划明确接替前序计划的持续禁买义务，并采用新保护条件。",
    }
    if (intent.excerpt not in (retirement if intent.retire_predecessor_guard else new_guard)
            or draft.buy_suspension is None and not intent.retire_predecessor_guard
            or not any(r.side == "BUY" and r.status == "ENABLED" for r in draft.ordinary_rules)):
        raise ValueError("explicit new BUY and guard replacement/retirement are required")


def _verify_buy_suspension_replacement_intent(session, details, draft, *, clock):
    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementIntent

    daily = DailyRepository(session, clock=clock, id_factory=None)
    review = daily.get("review-" + details.id)
    intent = None if review is None else review["payload"].get("buy_suspension_replacement_intent")
    if intent is None:
        return
    registered = daily.get(daily_hash("daily-human-supplements-v1", dict(
        symbol=draft.symbol, content_hash=daily_draft_content_sha256(draft))))
    if (registered is None or registered["kind"] != "DRAFT"
            or registered["payload"].get("buy_suspension_replacement_intent") != intent):
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    validate_buy_suspension_replacement_intent(draft,
        BuySuspensionReplacementIntent.model_validate(intent), details.source_text)


def _require_buy_suspension_replacement_review(work, details):
    review = work.daily.get("review-" + details.id)
    if (review is not None
            and review["payload"].get("buy_suspension_replacement_intent") is not None):
        # A registered source proposal is not runtime replacement authority. T08
        # admits exact receipts only with the real predecessor/guard snapshot.
        raise SourceCoverageAuthorityError("BUY_SUSPENSION_REPLACEMENT_REVIEW_REQUIRED")


def _require_current_coverage(session, details, *, clock, require_review=False):
    stored = _read_version_coverage(session, details, clock=clock)
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
    return _require_current_coverage(work.daily.session, details, clock=work.daily.clock,
                                     require_review=require_review)


def require_confirmation_coverage(work, details, command):
    _require_buy_suspension_replacement_review(work, details)
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
    return _require_current_coverage(repo._session, details, clock=repo._clock, require_review=True)
