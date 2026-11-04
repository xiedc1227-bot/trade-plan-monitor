"""Bounded original-cause diagnostics; never an action or quantity authorization."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.decision.daily_risk import DailyRiskBirth
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState, DailyRiskState
from trade_plan_monitor.state.models import (
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
    StoredPlanExtractionReview,
)
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.source_action_authority import (
    _fact_evidence_owned,
    _risk_dates_match,
    _risk_policy_matches,
    _risk_policy_values_match,
)
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_authority import (
    SourceCoverageAuthorityError,
    _verify_supplements,
)
from trade_plan_monitor.state.source_coverage_models import (
    CoverageAssessmentRow,
    CoverageInstallationRow,
    CoverageReviewRow,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


@dataclass(frozen=True, slots=True)
class RiskOriginRead:
    """Native facts and raw-value comparison binding for the caller's next read."""

    cause: DailyRiskState
    origin: DailyEvaluationState
    birth: DailyRiskBirth
    binding: str


def _version_values(reads, details):
    """Capture the actual source/review SQL owners, including their raw revisions."""
    rows = (
        reads._required(PlanVersion, details.id),
        reads._required(PlanSource, details.source_id),
        reads._required(PlanVersionReview, details.id),
        reads._required(PlanReviewProvenance, details.id),
    )
    if details.extraction_id is not None:
        rows += (reads._required(StoredPlanExtractionReview, details.extraction_id),)
    return tuple(
        {column.key: getattr(row, column.key) for column in row.__table__.columns} for row in rows
    )


def _original_coverage(reads, details, origin):
    store = SourceCoverageStore(reads.session)
    reads._reject_pending(CoverageInstallationRow)
    reads._reject_pending(CoverageReviewRow, review_id=details.review_id)
    marker = store.installation()
    receipt = store.receipt(details.review_id)
    if receipt is None:
        return None
    for revision in (receipt.coverage_revision, receipt.coverage_revision - 1):
        if revision > 0:
            reads._reject_pending(
                CoverageAssessmentRow, plan_version_id=details.id, revision=revision
            )
    stored = store.at_revision(details.id, receipt.coverage_revision)
    if stored is None:
        return None
    proof = stored.assessment
    if (
        not proof.coverage_complete
        or stored.created_at > receipt.confirmed_at
        or receipt.confirmed_at > origin.evaluated_at
        or (
            receipt.plan_version_id,
            receipt.review_id,
            receipt.review_revision,
            receipt.original_review_evidence_hash,
            receipt.confirmed_at,
            receipt.coverage_bundle_hash,
            receipt.coverage_evidence_hash,
            receipt.coverage_rules_version,
            receipt.source_hash,
            receipt.content_hash,
            receipt.mapping_hash,
        )
        != (
            details.id,
            details.review_id,
            details.review_revision,
            details.review_evidence_hash,
            details.review_confirmed_at,
            stored.evidence_hash,
            proof.evidence_hash,
            proof.rules_version,
            details.source_hash,
            details.content_hash,
            daily_hash("source-coverage-mapping-v1", details.daily_mapping.model_dump(mode="json")),
        )
        or (proof.source_hash, proof.content_hash, proof.mapping_hash)
        != (receipt.source_hash, receipt.content_hash, receipt.mapping_hash)
    ):
        return None
    supplement = None
    if details.daily_mapping.supplements:
        identity = daily_hash(
            "daily-human-supplements-v1",
            dict(symbol=details.symbol, content_hash=details.content_hash),
        )
        supplement = reads.daily(identity)
        _verify_supplements(
            reads.session,
            load_daily_draft_json(details.payload_json),
            details.daily_mapping,
            clock=reads.work.daily.clock,
        )
    return dict(
        marker=marker.model_dump(mode="json"),
        receipt=receipt.model_dump(mode="json"),
        assessment=stored.model_dump(mode="json"),
        supplement=supplement,
    )


def _fact_ids(roots):
    for root in roots:
        yield from root.fact_ids
        yield from _fact_ids(root.children)


def _read(work, cause_id, now):
    reads = ActionOwnerReader(work)
    current = reads.daily(cause_id)
    if current is None or current["kind"] != "RISK":
        return None
    state = DailyRiskState.model_validate_json(canonical(current["payload"]))
    if (
        state.status == "CLEAR"
        or state.risk_id != cause_id
        or state.origin_evaluation_id is None
        or state.origin_evaluation_id.startswith("evaluation-head-")
        or cause_id
        != daily_hash(
            "daily-risk-obligation-v1", dict(symbol=current["symbol"], kind=risk_identity(state))
        )
        or datetime.fromisoformat(current["updated_at"]) > now
    ):
        return None
    row = reads.daily(state.origin_evaluation_id)
    if (
        row is None
        or row["kind"] != "EVALUATION"
        or row["symbol"] != current["symbol"]
        or row["revision"] != 1
        or row["created_at"] != row["updated_at"]
    ):
        return None
    origin = DailyEvaluationState.model_validate_json(canonical(row["payload"]))
    if (
        origin.symbol != current["symbol"]
        or origin.evaluated_at > now
        or origin.activation_revision < 1
    ):
        return None
    births = [
        birth
        for birth in origin.risk_births or ()
        if (birth.risk_identity, birth.kind) == (risk_identity(state), state.kind)
    ]
    originals = [
        risk
        for risk in origin.risks
        if risk.risk_id == cause_id
        and (risk_identity(risk), risk.kind) == (risk_identity(state), state.kind)
    ]
    if len(births) != 1 or len(originals) != 1:
        return None
    birth, original = births[0], originals[0]
    if (
        original.status == "CLEAR"
        or original.origin_evaluation_id != row["id"]
        or current["lineage"] != current["symbol"]
        or state.reassessment_id != original.reassessment_id
    ):
        return None
    if any(
        risk.status in {"CONFIRMED", "FULFILLED"} and not _risk_dates_match(risk, instant)
        for risk, instant in ((original, origin.evaluated_at), (state, now))
    ):
        return None
    details = reads.details(origin.plan_version_id)
    if (
        details.symbol != origin.symbol
        or details.plan_id != row["lineage"]
        or details.daily_mapping is None
        or (details.plan_hash, details.content_hash, details.review_id)
        != (origin.plan_hash, origin.content_hash, origin.review_id)
        or details.review_confirmed_at is None
        or details.review_confirmed_at > origin.evaluated_at
        or birth.close_date < details.review_confirmed_at.date()
    ):
        return None
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        return None
    shadow = reads.daily("review-" + details.id)
    expected = dict(
        plan_version_id=details.id,
        content_hash=details.content_hash,
        source_hash=details.source_hash,
        review_id=details.review_id,
        review_revision=details.review_revision,
        evidence_hash=details.review_evidence_hash,
        confirmed=True,
    )
    if (
        shadow is None
        or shadow["kind"] != "REVIEW"
        or shadow["symbol"] != plan.symbol
        or shadow["lineage"] != plan.plan_id
        or any(shadow["payload"].get(key) != value for key, value in expected.items())
    ):
        return None
    branches = [
        branch
        for branch in plan.risk_branches
        if (risk_identity(branch), branch.kind) == (risk_identity(state), state.kind)
    ]
    if len(branches) != 1 or not all(
        _risk_policy_values_match(plan, branches[0], payload)
        for payload in (current["payload"], original.model_dump(mode="json"))
    ):
        return None
    if state.kind == "ORDINARY_TECHNICAL":
        if (
            original.breach_trade_date is None
            or original.breach_trade_date < birth.close_date
            or state.breach_trade_date is None
            or state.breach_trade_date < birth.close_date
            or original.breach_trade_date > origin.evaluated_at.date()
            or state.breach_trade_date > now.date()
            or original.basis_id is None
            or origin.daily_evidence is None
            or original.basis_id != origin.daily_evidence.basis_id
            or state.basis_id != original.basis_id
            or "PERSISTED_RISK_BASIS_EQUIVALENCE_REQUIRED" in state.blockers
        ):
            return None
    elif (
        original.confirmed_trade_date != birth.close_date
        or state.confirmed_trade_date != birth.close_date
        or state.technical_evidence != original.technical_evidence
        or not all(
            _risk_policy_matches(plan, branches[0], payload)
            for payload in (current["payload"], original.model_dump(mode="json"))
        )
        or not all(
            _fact_evidence_owned(work, plan, risk, origin.evaluated_at)
            for risk in (original, state)
        )
    ):
        return None
    coverage = _original_coverage(reads, details, origin)
    if coverage is None:
        return None
    facts = []
    revisions = {fact.id: fact.revision for fact in origin.fact_revisions}
    for identity in dict.fromkeys(_fact_ids(original.technical_evidence)):
        fact = reads.daily(identity)
        if (
            fact is None
            or fact["kind"] != "FACT"
            or fact["symbol"] != plan.symbol
            or fact["revision"] != revisions.get(identity)
        ):
            return None
        owner = reads.details(fact["payload"]["plan_version_id"])
        facts.append((fact, _version_values(reads, owner)))
    binding = canonical(
        dict(
            cause=current,
            evaluation=row,
            original_version=_version_values(reads, details),
            shadow=shadow,
            coverage=coverage,
            facts=facts,
        )
    )
    return RiskOriginRead(state, origin, birth, binding)


def read_risk_origin(work, *, cause_id: str, now: datetime) -> RiskOriginRead | None:
    """Point-read native original ownership or return unknown; perform zero writes.

    The caller compares two bindings in its existing snapshot retry. A successful
    diagnosis grants no SELL permission and does not inspect the current BUY book.
    """
    if now.tzinfo is None:
        return None
    try:
        with work.daily.session.no_autoflush:
            return _read(work, cause_id, now)
    except (
        SourceCoverageAuthorityError,
        RepositoryError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
    ):
        return None
