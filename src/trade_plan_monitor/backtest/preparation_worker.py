"""One fenced physical extraction call; its caller owns drain and durable completion."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
from trade_plan_monitor.ai.models import ExtractionDiagnostic, PlanExtractionResult
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_models import PreparationRecord, PreparationSource
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore


@dataclass(frozen=True, slots=True)
class PreparationExtractor:
    """A single-call adapter; retries are durable attempts, never hidden transport retries."""

    call: Callable[
        [UUID, PreparationSource, CancellationToken],
        LoopPlanExtractionResult | PlanExtractionResult | None,
    ]
    max_retries: int = 0

    def __post_init__(self):
        if not callable(self.call):
            raise TypeError("call must be callable")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")


@dataclass(frozen=True, slots=True)
class PreparationCallOutcome:
    result: LoopPlanExtractionResult | PlanExtractionResult | None = None
    unknown: bool = False


def run_attempt(
    store: PreparationStore,
    jobs: BacktestJobRepository,
    record: PreparationRecord,
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
        result = extractor.call(UUID(claim.generation), record.source, token)
        if result is None:
            return PreparationCallOutcome(unknown=not token.cancelled)
        if not isinstance(result, (LoopPlanExtractionResult, PlanExtractionResult)):
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
            sha256(record.source.text.encode()).hexdigest(),
        ):
            return PreparationCallOutcome(unknown=True)
        if isinstance(result, LoopPlanExtractionResult) and (
            result.source_id != record.source.source_id
            or result.source_binding_hash != claim.source_hash
        ):
            return PreparationCallOutcome(unknown=True)
        diagnostics = (diagnostic,) if diagnostic else ()
        code = next((d.provider_error_code for d in diagnostics if d.provider_error_code), None)
        unknown = code == "TIMEOUT" or any(
            d.provider_error_code == "TRANSIENT"
            and d.transient_kind not in {"HTTP_408", "HTTP_5XX", "DNS", "TLS", "CONNECT", "PROXY"}
            for d in diagnostics
        )
        return PreparationCallOutcome(result=result, unknown=unknown)
    except Exception:
        # No exception text, response body or credential enters durable preparation state.
        return PreparationCallOutcome(unknown=True)
