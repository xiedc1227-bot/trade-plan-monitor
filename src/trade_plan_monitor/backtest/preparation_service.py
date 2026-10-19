"""Private single-source preparation orchestration using existing global admission."""

import asyncio
from collections.abc import Callable
from functools import partial
from hashlib import sha256
from uuid import uuid4

from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs.repository import (
    BacktestJobRepository,
    BacktestRunSubmissionReservation,
    JobAdmissionError,
)
from trade_plan_monitor.backtest.loop_input import MAX_EXTRACTION_ATTEMPTS
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    CollectionPreparationWorkClaim,
    PlanCollectionPreparationInput,
    PreparationRecord,
    PreparationSource,
    PreparationWorkClaim,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    CollectionPreparationReviewCommand,
    FrozenPreparedPlan,
    PreparationReviewCommand,
    PreparationSemanticError,
    frozen_preparation,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import (
    PreparationCallOutcome,
    PreparationExtractor,
    run_attempt,
)
from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.backtest.thread_lifecycle import BacktestMetadataThread
from trade_plan_monitor.backtest.thread_ownership import BacktestThreadOwner


class PreparationService:
    """Reads never dispatch; only a fresh explicit request can own a new generation."""

    def __init__(
        self,
        store: PreparationStore,
        jobs: BacktestJobRepository,
        extractor: PreparationExtractor | None = None,
        *,
        config: BacktestServiceConfig | None = None,
    ) -> None:
        if extractor is not None and not isinstance(extractor, PreparationExtractor):
            raise TypeError("extractor must be PreparationExtractor")
        self._store, self._jobs, self._extractor = store, jobs, extractor
        self._owner_id = str(uuid4())
        self._metadata = BacktestMetadataThread()
        self._owner = BacktestThreadOwner(thread_name_prefix="backtest-plan-extraction")
        self._tasks: set[asyncio.Task[PreparationRecord]] = set()
        self._worker: asyncio.Task[None] | None = None
        self._token: CancellationToken | None = None
        self._preparation_id: str | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._config = config or BacktestServiceConfig()
        self._closed = False

    @property
    def outstanding_work(self) -> int:
        return (self._metadata.outstanding_work + self._owner.outstanding_work
                + sum(not task.done() for task in self._tasks)
                + int(self._worker is not None and not self._worker.done()))

    async def create(
        self, command: SinglePlanPreparationInput | PlanCollectionPreparationInput,
        *, idempotency_key: str,
    ) -> PreparationRecord:
        if not isinstance(command, (SinglePlanPreparationInput, PlanCollectionPreparationInput)):
            raise TypeError("command must be a versioned preparation input")
        command = type(command).model_validate(command.model_dump(mode="python"))
        return await self._metadata.run(self._create, command, idempotency_key)

    def _create(self, command, key):
        if self._closed:
            raise BacktestServiceUnavailable()
        intent = canonical_json({
            "domain": "single-source-create-v1", "preparation_id": command.preparation_id,
            "command_hash": sha256(canonical_json(command).encode()).hexdigest(),
        })
        admission_key = "prep-create-" + sha256(canonical_json({
            "preparation_id": command.preparation_id, "idempotency_key": key,
        }).encode()).hexdigest()
        replay = self._store.replay_create(command, idempotency_key=key)
        if replay is not None:
            reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
            if reservation is not None:
                self._jobs.release_run_submission(reservation)
            return replay
        reservation = self._jobs.claim_run_submission(intent, admission_key)
        if not isinstance(reservation, BacktestRunSubmissionReservation):
            raise JobAdmissionError("BACKTEST_BUSY")
        try:
            return self._store.create(command, idempotency_key=key)
        finally:
            self._jobs.release_run_submission(reservation)

    async def get(self, preparation_id: str) -> PreparationRecord | None:
        return await self._metadata.read(self._store.get, preparation_id)

    async def selection(self, operation, *args):
        from trade_plan_monitor.backtest.workbench_selection import WorkbenchSelectionStore

        selections = WorkbenchSelectionStore(self._store)
        method = getattr(selections, operation)
        runner = self._metadata.run if operation == "save" else self._metadata.read
        return await runner(method, *args)

    async def list_reviewed(self, *, offset=0, limit=20):
        from trade_plan_monitor.backtest.plan_library import list_reviewed_plans
        return await self._metadata.read(
            list_reviewed_plans, self._store, offset=offset, limit=limit,
        )

    async def library_write(self, command, *, idempotency_key):
        from trade_plan_monitor.backtest.preparation_models import (
            PreparedPlanCompositionInput,
            SingleSourcePreparationInput,
        )
        if not isinstance(command, (SingleSourcePreparationInput, PreparedPlanCompositionInput)):
            raise TypeError("library command required")
        command = type(command).model_validate_json(command.model_dump_json())
        return await self._metadata.run(self._library_write, command, idempotency_key)

    def _library_write(self, command, key):
        from trade_plan_monitor.backtest.plan_library import (
            compose_reviewed_plans,
            create_single_preparation,
        )
        from trade_plan_monitor.backtest.preparation_models import SingleSourcePreparationInput
        if self._closed:
            raise BacktestServiceUnavailable()
        intent = canonical_json({"domain": "plan-library-write-v1",
            "command_hash": sha256(canonical_json(command).encode()).hexdigest()})
        admission_key = "library-" + sha256(key.encode()).hexdigest()
        single = isinstance(command, SingleSourcePreparationInput)
        operation_name = "CREATE_SINGLE" if single else "COMPOSE_REVIEWED"
        replay = self._store.replay_create(command, idempotency_key=key, operation=operation_name)
        if replay is not None:
            reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
            if reservation is not None:
                self._jobs.release_run_submission(reservation)
            return replay
        reservation = self._jobs.claim_run_submission(intent, admission_key)
        if not isinstance(reservation, BacktestRunSubmissionReservation):
            raise JobAdmissionError("BACKTEST_BUSY")
        try:
            operation = create_single_preparation if single else compose_reviewed_plans
            return operation(self._store, command, idempotency_key=key)
        finally:
            self._jobs.release_run_submission(reservation)

    async def get_frozen(self, preparation_id: str) -> FrozenPreparedPlan:
        return await self._metadata.run(self._read_frozen, preparation_id)

    @staticmethod
    def _frozen(record):
        if record is None:
            raise PreparationConflictError("PREPARATION_NOT_FOUND")
        try:
            return frozen_preparation(record)
        except PreparationSemanticError as error:
            raise PreparationConflictError(error.code) from None

    def _read_frozen(self, preparation_id):
        return self._frozen(self._store.get(preparation_id))

    async def review_and_freeze(
        self, preparation_id: str, *, command: PreparationReviewCommand, idempotency_key: str,
    ) -> FrozenPreparedPlan:
        if self._closed:
            raise BacktestServiceUnavailable()
        if not isinstance(command, (PreparationReviewCommand, CollectionPreparationReviewCommand)):
            raise TypeError("command must be a versioned preparation review")
        model = (CollectionPreparationReviewCommand
                 if isinstance(command, CollectionPreparationReviewCommand)
                 else PreparationReviewCommand)
        command = model.model_validate_json(command.model_dump_json())
        return await self._metadata.run(self._review, preparation_id, command, idempotency_key)

    async def correct_collection_item(self, preparation_id, *, command, idempotency_key):
        if self._closed:
            raise BacktestServiceUnavailable()
        command = CollectionItemCorrectionCommand.model_validate_json(command.model_dump_json())
        return await self._metadata.run(self._review, preparation_id, command, idempotency_key)

    def _review(self, identity, command, key):
        if self._closed:
            raise BacktestServiceUnavailable()
        correction = isinstance(command, CollectionItemCorrectionCommand)
        domain = ("collection-item-correction-v2" if correction else "collection-review-v2"
                  if isinstance(command, CollectionPreparationReviewCommand)
                  else "single-source-review-v1")
        intent = canonical_json({
            "domain": domain, "preparation_id": identity,
            "command_hash": sha256(canonical_json(command).encode()).hexdigest(),
        })
        admission_key = "prep-review-" + sha256(canonical_json({
            "preparation_id": identity, "idempotency_key": key,
        }).encode()).hexdigest()
        replay = self._store.replay_review(identity, command=command, idempotency_key=key)
        if replay is not None:
            frozen = replay if correction else self._frozen(replay)
            # The durable receipt proves completion if a crash preceded gate release.
            reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
            if reservation is not None:
                self._jobs.release_run_submission(reservation)
            return frozen
        reservation = self._jobs.claim_run_submission(intent, admission_key)
        if not isinstance(reservation, BacktestRunSubmissionReservation):
            raise JobAdmissionError("BACKTEST_BUSY")
        try:
            if correction:
                return self._store.correct_collection_item(
                    identity, command=command, idempotency_key=key,
                )
            return self._frozen(self._store.review_and_freeze(
                identity, command=command, idempotency_key=key,
            ))
        finally:
            self._jobs.release_run_submission(reservation)

    async def submit_extraction(
        self,
        preparation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        extractor_factory: Callable[[], PreparationExtractor] | None = None,
        item_binding=None,
        collection_mode=None,
    ) -> PreparationRecord:
        if self._closed:
            raise BacktestServiceUnavailable()
        task = asyncio.create_task(self._submit(
            preparation_id, expected_revision, idempotency_key, extractor_factory,
            item_binding, collection_mode,
        ))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await asyncio.shield(task)

    async def _submit(self, preparation_id, expected_revision, key, extractor_factory=None,
                      item_binding=None, collection_mode=None):
        record, dispatch = await self._metadata.run(
            self._admit, preparation_id, expected_revision, key, extractor_factory,
            item_binding, collection_mode,
        )
        if dispatch:
            self._preparation_id = preparation_id
            self._token = CancellationToken()
            self._worker = asyncio.create_task(self._watch(record, self._token))
        return record

    @staticmethod
    def _extraction_binding(record, binding, collection_mode, *, replay=False):
        collection = isinstance(record, CollectionPreparationRecord)
        if collection_mode is not None and collection != collection_mode:
            raise PreparationConflictError("PREPARATION_SCHEMA_CONFLICT")
        if binding is None:
            return
        if not collection:
            raise PreparationConflictError("PREPARATION_SCHEMA_CONFLICT")
        if replay:
            claim = record.work_claim
            expected = (claim.source_id, claim.source_revision, claim.base_hash)
        else:
            index, item = PreparationStore.next_collection_item(record)
            expected = (item.source.source_id, item.source_revision,
                        record.items[index - 1].candidate.candidate_hash
                        if index and not item.independent else None)
        if binding != expected:
            raise PreparationConflictError("PREPARATION_ITEM_BINDING_CONFLICT")

    def _admit(self, preparation_id, expected_revision, key, extractor_factory=None,
               item_binding=None, collection_mode=None):
        if self._closed:
            raise BacktestServiceUnavailable()
        replay = self._store.replay_start_attempt(
            preparation_id,
            expected_revision=expected_revision,
            idempotency_key=key,
        )
        if replay is not None:
            self._extraction_binding(replay, item_binding, collection_mode, replay=True)
            return replay, False
        record = self._store._require_revision(self._store.get(preparation_id), expected_revision)
        sources = (tuple(item.source for item in record.items)
                   if isinstance(record, CollectionPreparationRecord) else (record.source,))
        if any(source.effective_trade_date is None for source in sources):
            raise PreparationConflictError("SOURCE_DATE_REQUIRED")
        if len({source.effective_trade_date for source in sources}) != len(sources):
            raise PreparationConflictError("SOURCE_DATE_CONFLICT")
        self._extraction_binding(record, item_binding, collection_mode)
        collection = isinstance(record, CollectionPreparationRecord)
        if collection:
            index, item = self._store.next_collection_item(record)
            intent_fields = {
                "domain": "collection-preparation-v2", "preparation_id": preparation_id,
                "expected_revision": expected_revision,
                "sources_hash": sha256(canonical_json(tuple(
                    (item.source.binding_hash, item.source_revision) for item in record.items
                )).encode()).hexdigest(),
            }
        else:
            item = record
            intent_fields = {
                "domain": "single-source-preparation-v1",
                "preparation_id": preparation_id,
                "source_revision": record.source_revision,
                "source_hash": record.source.binding_hash,
                "expected_revision": expected_revision,
            }
        intent = canonical_json(intent_fields)
        admission_key = (
            "prep-extract-"
            + sha256(
                canonical_json(
                    {
                        "preparation_id": preparation_id,
                        "idempotency_key": key,
                    }
                ).encode()
            ).hexdigest()
        )
        reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
        created = reservation is None
        if created:
            reservation = self._jobs.claim_run_submission(intent, admission_key)
        if not isinstance(reservation, BacktestRunSubmissionReservation):
            raise JobAdmissionError("BACKTEST_BUSY")
        claim_type = CollectionPreparationWorkClaim if collection else PreparationWorkClaim
        extra = {} if not collection else {
            "source_id": item.source.source_id,
            "base_hash": (record.items[index - 1].candidate.candidate_hash
                          if index and not item.independent else None),
        }
        claim = claim_type(
            generation=str(uuid4()),
            owner_id=self._owner_id,
            source_revision=item.source_revision,
            source_hash=item.source.binding_hash,
            admission_key=admission_key,
            intent_hash=reservation.intent_hash,
            claimed_at=reservation.claimed_at,
            intent_json=intent,
            phase="READY",
            **extra,
        )
        try:
            extractor = extractor_factory() if extractor_factory is not None else self._extractor
            if extractor is None:
                raise BacktestServiceUnavailable()
            if not isinstance(extractor, PreparationExtractor):
                raise TypeError("extractor factory must return PreparationExtractor")
            started = self._store.start_attempt(
                preparation_id,
                expected_revision=expected_revision,
                idempotency_key=key,
                work_claim=claim,
            )
            self._extractor = extractor
            return started, started.work_claim == claim
        except Exception:
            if created:
                self._jobs.release_run_submission(reservation)
            raise

    async def _watch(self, record, token):
        retries = self._extractor.max_retries
        while record is not None:
            future = self._owner.submit(
                partial(
                    run_attempt,
                    self._store,
                    self._jobs,
                    record,
                    self._extractor,
                    token,
                )
            )
            try:
                outcome = await asyncio.shield(asyncio.wrap_future(future))
            except PreparationConflictError:
                outcome = PreparationCallOutcome(unknown=not token.cancelled)
            # Completion waits for admitted reads as well as the physical transaction.
            while self._metadata.occupied:
                await asyncio.sleep(0.005)
            previous = record
            record = await self._metadata.run(self._complete, record, outcome, retries, token)
            retries = (self._extractor.max_retries
                       if isinstance(record, CollectionPreparationRecord)
                       and record.work_claim.source_id != previous.work_claim.source_id
                       else retries - 1)

    def _complete(self, original, outcome, retries, token):
        from trade_plan_monitor.backtest.preparation_repairs import (
            REPAIR_ERRORS,
            correction_context,
            correction_feedback,
        )

        identity = original.preparation_id
        record = self._store.get(identity)
        claim = original.work_claim
        if record.work_claim is None or (
            record.work_claim.generation,
            record.work_claim.owner_id,
        ) != (claim.generation, claim.owner_id):
            return None
        common = {
            "attempt_id": claim.generation,
            "expected_revision": record.revision,
            "idempotency_key": f"{claim.generation}.complete",
            "worker_owner_id": claim.owner_id,
        }
        item = (self._store._collection_active_item(record, claim.generation)[1]
                if isinstance(record, CollectionPreparationRecord) else record)
        can_repair = (len(item.attempts) <= self._extractor.max_repairs
                      and len(item.attempts) < MAX_EXTRACTION_ATTEMPTS)
        candidate = outcome.candidate
        if candidate is None and isinstance(outcome.result, LoopPlanExtractionResult):
            candidate = outcome.result.to_preparation_candidate()
        feedback = correction_feedback(candidate)
        semantic = (getattr(outcome.result, "preparation_contract", None) == "SEMANTIC_PATCH"
                    or getattr(getattr(outcome.result, "output", None), "inheritance_mode", None)
                    == "PREDECESSOR_PATCH")
        if outcome.unknown:
            self._store.mark_unknown(
                identity,
                generation=claim.generation,
                owner_id=claim.owner_id,
                expected_revision=record.revision,
            )
            return None
        if record.status == "CANCEL_REQUESTED":
            ended = self._store.acknowledge_cancellation(identity, **common)
        elif outcome.error_code is not None:
            repair = can_repair and outcome.error_code in REPAIR_ERRORS
            ended = self._store.finish_attempt(identity, **common, error_code=outcome.error_code,
                retryable=repair, repair_feedback=(outcome.error_code,) if repair else (),
                repair_context_json=correction_context(outcome.result) if repair else None)
        elif feedback and can_repair and semantic:
            ended = self._store.finish_attempt(identity, **common, error_code="AI_REPAIR_REQUIRED",
                retryable=True, repair_feedback=feedback,
                repair_context_json=correction_context(outcome.result))
        elif outcome.candidate is not None:
            ended = self._store.finish_attempt(identity, **common, candidate=outcome.candidate)
        elif isinstance(outcome.result, LoopPlanExtractionResult):
            ended = self._store.finish_attempt(
                identity,
                **common,
                candidate=outcome.result.to_preparation_candidate(),
            )
        else:
            result = outcome.result
            if result is None or result.status is PlanExtractionStatus.SUCCEEDED:
                self._store.mark_unknown(
                    identity,
                    generation=claim.generation,
                    owner_id=claim.owner_id,
                    expected_revision=record.revision,
                )
                return None
            code = result.diagnostic.provider_error_code if result.diagnostic else None
            if code is None:
                # Preserve server-owned actionable reasons, never raw provider text.
                safe_codes = {"AI_INPUT_TOO_LARGE", "AI_FIELD_EVIDENCE_INVALID",
                              "AI_OUTPUT_INVALID", "AI_OUTPUT_TRUNCATED"}
                code = next((issue.code for issue in result.validation_issues
                             if issue.code in safe_codes), "INVALID_OUTPUT")
                if result.diagnostic and result.diagnostic.finish_reason == "length":
                    code = "AI_OUTPUT_TRUNCATED"
            ended = self._store.finish_attempt(
                identity,
                **common,
                error_code=code or "INVALID_OUTPUT",
                retryable=(code in {"TRANSIENT", "RATE_LIMITED", "AI_INPUT_TOO_LARGE"}
                           or (can_repair and code in REPAIR_ERRORS)),
                repair_feedback=(code,) if can_repair and code in REPAIR_ERRORS else (),
            )
        if isinstance(ended, CollectionPreparationRecord):
            return self._advance_collection(ended, retries, token)
        if (
            ended.status == "FAILED"
            and ended.attempts[-1].retryable
            and ended.attempts[-1].error_code != "AI_INPUT_TOO_LARGE"
            and (retries > 0 or ended.attempts[-1].repair_feedback)
            and len(ended.attempts) < MAX_EXTRACTION_ATTEMPTS
            and not token.cancelled
            and not self._closed
        ):
            return self._store.start_attempt(
                identity,
                expected_revision=ended.revision,
                idempotency_key=str(uuid4()),
                work_claim=claim.model_copy(update={"generation": str(uuid4()), "phase": "READY"}),
            )
        self._release(ended)
        return None

    def _advance_collection(self, ended, retries, token):
        claim = ended.work_claim
        index, item = self._store._collection_active_item(ended, claim.generation)
        retry = (item.status == "FAILED" and item.attempts[-1].retryable
                 and (retries > 0 or item.attempts[-1].repair_feedback)
                 and item.attempts[-1].error_code != "AI_INPUT_TOO_LARGE"
                 and len(item.attempts) < MAX_EXTRACTION_ATTEMPTS)
        successor = (item.candidate is not None and item.candidate.validation == "VALID"
                     and index + 1 < len(ended.items))
        if (retry or successor) and not token.cancelled and not self._closed:
            selected = ended.items[index + 1] if successor else item
            return self._store.start_attempt(
                ended.preparation_id, expected_revision=ended.revision,
                idempotency_key=str(uuid4()), work_claim=claim.model_copy(update={
                    "generation": str(uuid4()), "phase": "READY",
                    "source_id": selected.source.source_id,
                    "source_revision": selected.source_revision,
                    "source_hash": selected.source.binding_hash,
                    "base_hash": item.candidate.candidate_hash if successor else item.base_hash,
                }),
            )
        self._release(ended)
        return None

    def _release(self, record):
        claim = record.work_claim
        if claim is None or claim.phase != "ENDED":
            raise PreparationConflictError("WORKER_CLAIM_PENDING")
        reservation = self._jobs.get_run_submission_reservation(
            claim.intent_json, claim.admission_key
        )
        if reservation is not None:
            if (reservation.intent_hash, reservation.claimed_at) != (
                claim.intent_hash,
                claim.claimed_at,
            ):
                raise PreparationConflictError("STALE_WORKER")
            self._jobs.release_run_submission(reservation)
        return self._store.clear_work_claim(
            record.preparation_id,
            generation=claim.generation,
            expected_revision=record.revision,
        )

    async def cancel(
        self,
        preparation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> PreparationRecord:
        return await self._metadata.run(
            self._mutate,
            "CANCEL",
            preparation_id,
            expected_revision,
            idempotency_key,
            None,
        )

    async def edit_source(
        self,
        preparation_id: str,
        *,
        source: PreparationSource,
        expected_revision: int,
        idempotency_key: str,
    ) -> PreparationRecord:
        return await self._metadata.run(
            self._mutate,
            "EDIT",
            preparation_id,
            expected_revision,
            idempotency_key,
            source,
        )

    async def edit_collection(
        self, preparation_id, *, expected_revision, idempotency_key,
        source: PreparationSource | None = None, source_order: tuple[str, ...] | None = None,
    ):
        if self._closed:
            raise BacktestServiceUnavailable()
        return await self._metadata.run(
            self._edit_collection, preparation_id, expected_revision, idempotency_key,
            source, source_order,
        )

    def _edit_collection(self, identity, revision, key, source, order):
        if self._closed:
            raise BacktestServiceUnavailable()
        kwargs = {"expected_revision": revision, "idempotency_key": key,
                  "source": source, "source_order": order}
        intent = canonical_json({
            "domain": "collection-source-edit-v2", "preparation_id": identity,
            "command_hash": sha256(canonical_json(kwargs).encode()).hexdigest(),
        })
        admission_key = "prep-collection-edit-" + sha256(key.encode()).hexdigest()
        replay = self._store.replay_mutation("EDIT_COLLECTION", identity, **kwargs)
        if replay is not None:
            reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
            if reservation is not None:
                self._jobs.release_run_submission(reservation)
            return replay
        reservation = self._jobs.claim_run_submission(intent, admission_key)
        if not isinstance(reservation, BacktestRunSubmissionReservation):
            raise JobAdmissionError("BACKTEST_BUSY")
        try:
            return self._store.edit_collection(identity, **kwargs)
        finally:
            self._jobs.release_run_submission(reservation)

    def _mutate(self, operation, identity, revision, key, source):
        if self._closed:
            raise BacktestServiceUnavailable()
        intent = canonical_json({
            "domain": "single-source-mutation-v1", "operation": operation,
            "preparation_id": identity, "expected_revision": revision,
            "source_hash": source.binding_hash if source else None,
        })
        admission_key = "prep-mutate-" + sha256(key.encode()).hexdigest()
        replay = self._store.replay_mutation(operation, identity, expected_revision=revision,
            idempotency_key=key, source=source)
        if replay is not None:
            if replay.work_claim is None:
                reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
                if reservation is not None:
                    self._jobs.release_run_submission(reservation)
            return replay
        record = self._store.get(identity)
        claim = record.work_claim if record else None
        if claim and claim.phase == "ENDED":
            raise PreparationConflictError("WORKER_CLAIM_PENDING")
        reservation = None
        if claim is None:
            reservation = self._jobs.get_run_submission_reservation(intent, admission_key)
            if reservation is None:
                reservation = self._jobs.claim_run_submission(intent, admission_key)
            if not isinstance(reservation, BacktestRunSubmissionReservation):
                raise JobAdmissionError("BACKTEST_BUSY")
        try:
            kwargs = {"expected_revision": revision, "idempotency_key": key}
            updated = (
                self._store.cancel(identity, **kwargs)
                if operation == "CANCEL"
                else self._store.edit_source(identity, source=source, **kwargs)
            )
            current = self._store.get(identity)
            if (
                updated.status == "CANCEL_REQUESTED"
                and updated.work_claim is not None
                and updated.work_claim.owner_id == self._owner_id
                and current.status == "CANCEL_REQUESTED"
                and current.work_claim is not None
                and current.work_claim.generation == updated.work_claim.generation
                and self._token is not None
            ):
                self._token.cancel()
            return updated
        finally:
            if reservation is not None:
                self._jobs.release_run_submission(reservation)

    async def recover(
        self,
        preparation_id: str,
        *,
        generation: str,
        expected_revision: int,
        confirmed_ended: bool,
        idempotency_key: str,
    ) -> PreparationRecord:
        if self._closed:
            raise BacktestServiceUnavailable()
        if self._owner.outstanding_work or (self._worker is not None and not self._worker.done()):
            raise PreparationConflictError("WORKER_NOT_DRAINED")
        return await self._metadata.run(
            self._recover,
            preparation_id,
            generation,
            expected_revision,
            confirmed_ended,
            idempotency_key,
        )

    def _recover(self, identity, generation, revision, confirmed, key):
        if type(confirmed) is not bool or not confirmed:
            raise PreparationConflictError("RECOVERY_CONFIRMATION_REQUIRED")
        current = self._store.get(identity)
        if current and current.work_claim and current.work_claim.phase == "ENDED":
            self._store._require_revision(current, revision)
            if current.work_claim.generation != generation:
                raise PreparationConflictError("STALE_WORKER")
            return self._release(current)
        ended = self._store.recover_unknown(
            identity,
            generation=generation,
            expected_revision=revision,
            confirmed_ended=confirmed,
            idempotency_key=key,
        )
        current = self._store.get(identity)
        if current.work_claim is not None and current.work_claim.generation == generation:
            self._release(current)
        return ended

    async def wait_for_drain(self) -> None:
        if self._cleanup is not None:
            await asyncio.shield(self._cleanup)
        else:
            await self._wait_work()

    async def _wait_work(self):
        if self._tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._tasks)))
        if self._worker is not None:
            await asyncio.shield(self._worker)

    async def stop(self) -> None:
        self._closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._drain_and_close())
        try:
            await asyncio.wait_for(
                asyncio.shield(self._cleanup), self._config.shutdown_wait_seconds
            )
        except TimeoutError:
            raise BacktestServiceUnavailable() from None

    async def _drain_and_close(self):
        if self._tasks:
            await asyncio.gather(
                *(asyncio.shield(task) for task in tuple(self._tasks)),
                return_exceptions=True,
            )
        while self._metadata.occupied:
            await asyncio.sleep(0.005)
        if self._preparation_id is not None:
            await self._metadata.run(self._cancel_owned_work)
        try:
            if self._worker is not None:
                await asyncio.shield(self._worker)
        finally:
            self._owner.close()
            await self._metadata.stop()

    def _cancel_owned_work(self):
        if self._preparation_id is None:
            return
        record = self._store.get(self._preparation_id)
        if (
            record.work_claim is not None
            and record.work_claim.owner_id == self._owner_id
            and record.status == "EXTRACTING"
            and record.work_claim.phase != "UNKNOWN"
        ):
            self._store.cancel(
                record.preparation_id,
                expected_revision=record.revision,
                idempotency_key=str(uuid4()),
            )
            self._token.cancel()
