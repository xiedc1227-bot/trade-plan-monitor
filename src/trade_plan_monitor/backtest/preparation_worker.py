"""One fenced physical extraction call; its caller owns drain and durable completion."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
from trade_plan_monitor.ai.models import ExtractionDiagnostic, PlanExtractionResult
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionResult
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    PlanCandidateReview,
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    PreparationCandidateInput,
    PreparationRecord,
)
from trade_plan_monitor.backtest.preparation_review import _original_extraction
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore


@dataclass(frozen=True, slots=True)
class PreparationExtractor:
    """A single-call adapter; retries are durable attempts, never hidden transport retries."""

    call: Callable[..., LoopPlanExtractionResult | PlanUpdateExtractionResult
                   | PlanExtractionResult | None]
    max_retries: int = 0

    def __post_init__(self):
        if not callable(self.call):
            raise TypeError("call must be callable")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")


@dataclass(frozen=True, slots=True)
class PreparationCallOutcome:
    result: (
        LoopPlanExtractionResult | PlanUpdateExtractionResult | PlanExtractionResult | None
    ) = None
    unknown: bool = False
    candidate: PreparationCandidateInput | None = None
    error_code: str | None = None


def preparation_candidate_review(record: CollectionPreparationRecord, index: int):
    """Revalidate the stored prefix against original sources, never future items."""
    base = None
    for offset, item in enumerate(record.items[:index + 1]):
        candidate = item.candidate
        if candidate is None or candidate.validation != "VALID":
            raise ValueError("unresolved predecessor")
        # This separate server evidence codec can be written by explicit review, not AI.
        schema = json.loads(candidate.payload_json).get("schema_version")
        if schema == "monitor-loop-candidate-evidence-v1":
            reviewed = PlanCandidateReview.model_validate_json(candidate.payload_json)
            if reviewed.evidence_hash != candidate.evidence_hash:
                raise ValueError("reviewed predecessor evidence changed")
        elif offset == 0:
            original = _original_extraction(item)
            if original.validation_issues:
                raise ValueError("unresolved initial extraction")
            reviewed = build_initial_review(original.draft, original.daily_mapping, item.source)
        else:
            materialized = MaterializedUpdateCandidate.model_validate_json(candidate.payload_json)
            expected = materialize_extraction(
                base, record.items[offset - 1].candidate.candidate_hash,
                item.source, materialized.extraction,
            )
            if expected != materialized or (
                str(materialized.extraction.request_id) != item.attempts[-1].attempt_id
                or expected.review.evidence_hash != candidate.evidence_hash
            ):
                raise ValueError("stored successor differs from its source/base binding")
            reviewed = expected.review
        if reviewed.issues or (
            reviewed.source_id, reviewed.source_hash, reviewed.available_at
        ) != (item.source.source_id, item.source.binding_hash, item.source.available_at):
            raise ValueError("stored predecessor is unresolved or bound to another source")
        base = reviewed
    if base is None:
        raise ValueError("predecessor is absent")
    return base


def run_attempt(
    store: PreparationStore,
    jobs: BacktestJobRepository,
    record: PreparationRecord | CollectionPreparationRecord,
    extractor: PreparationExtractor,
    token: CancellationToken,
) -> PreparationCallOutcome:
    """Persist authority before HTTP; no database transaction remains open during the call."""
    claim = record.work_claim
    if claim is None:
        raise PreparationConflictError("STALE_WORKER")
    reservation = jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key)
    if reservation is None or (reservation.intent_hash, reservation.claimed_at) != (
        claim.intent_hash,
        claim.claimed_at,
    ):
        raise PreparationConflictError("STALE_WORKER")
    if token.cancelled:
        return PreparationCallOutcome()
    store.begin_call(
        record.preparation_id,
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=record.revision,
    )
    if token.cancelled:
        return PreparationCallOutcome()
    try:
        collection = isinstance(record, CollectionPreparationRecord)
        index, item = store._collection_active_item(record, claim.generation) if collection else (
            0, record,
        )
        source, context, base = item.source, None, None
        if collection and index:
            try:
                base = preparation_candidate_review(record, index - 1)
                context = context_from_review(base, claim.base_hash)
                if source.available_at is None or context.available_at > source.available_at:
                    raise ValueError("predecessor context is unavailable")
            except ValueError:
                return PreparationCallOutcome(error_code="PREDECESSOR_UNRESOLVED")
        result = (extractor.call(UUID(claim.generation), source, token, context=context)
                  if context is not None else extractor.call(UUID(claim.generation), source, token))
        if result is None:
            return PreparationCallOutcome(unknown=not token.cancelled)
        if not isinstance(result, (
            LoopPlanExtractionResult, PlanUpdateExtractionResult, PlanExtractionResult,
        )):
            return PreparationCallOutcome(unknown=True)
        diagnostic = (
            ExtractionDiagnostic.model_validate(result.diagnostic.model_dump(mode="python"))
            if result.diagnostic
            else None
        )
        result = (
            type(result)
            .model_validate_json(result.model_dump_json())
            .model_copy(
                update={"diagnostic": diagnostic},
            )
        )
        if (str(result.request_id), result.source_text_sha256) != (
            claim.generation,
            sha256(source.text.encode()).hexdigest(),
        ):
            return PreparationCallOutcome(unknown=True)
        if isinstance(result, (LoopPlanExtractionResult, PlanUpdateExtractionResult)) and (
            result.source_id != source.source_id
            or result.source_binding_hash != claim.source_hash
        ):
            return PreparationCallOutcome(unknown=True)
        if context is not None and isinstance(result, LoopPlanExtractionResult):
            return PreparationCallOutcome(unknown=True)
        candidate = None
        if isinstance(result, PlanUpdateExtractionResult):
            if context is None or result.base_hash != claim.base_hash:
                return PreparationCallOutcome(unknown=True)
            digest = sha256(canonical_json({
                "domain": "monitor-loop-update-evidence-v1",
                "source_binding_hash": source.binding_hash,
                "context": context, "output": result.output,
            }).encode()).hexdigest()
            if result.evidence_hash != digest or (
                result.authored_at, result.available_at, result.effective_trade_date
            ) != (source.authored_at, source.available_at, source.effective_trade_date):
                return PreparationCallOutcome(unknown=True)
            try:
                candidate = (result.to_preparation_candidate()
                             if result.output.scope == "UNRESOLVED" else materialize_extraction(
                                 base, claim.base_hash, source, result,
                             ).to_preparation_candidate())
            except ValueError:
                return PreparationCallOutcome(result=result, error_code="INVALID_UPDATE_EVIDENCE")
        diagnostics = (diagnostic,) if diagnostic else ()
        code = next((d.provider_error_code for d in diagnostics if d.provider_error_code), None)
        unknown = code == "TIMEOUT" or any(
            d.provider_error_code == "TRANSIENT"
            and d.transient_kind not in {"HTTP_408", "HTTP_5XX", "DNS", "TLS", "CONNECT", "PROXY"}
            for d in diagnostics
        )
        return PreparationCallOutcome(result=result, unknown=unknown, candidate=candidate)
    except Exception:
        # No exception text, response body or credential enters durable preparation state.
        return PreparationCallOutcome(unknown=True)
