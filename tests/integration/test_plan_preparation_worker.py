"""Durable single-source extraction, physical drain and existing global admission."""

import asyncio
import json
from datetime import datetime, timedelta
from hashlib import sha256
from threading import Event, get_ident
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from tests.integration.test_backtest_jobs import _SHANGHAI, _Clock
from tests.integration.test_backtest_single_task import request
from tests.integration.test_plan_preparation_store import candidate
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_monitor_loop_extraction import CASES, output_for

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderOperation,
    RawAIResponse,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.preparation_models import (
    PreparationRecord,
    PreparationSource,
    PreparationWorkClaim,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor, run_attempt
from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanExtractionCommand
from trade_plan_monitor.web.schemas import MutationContext


def stores(tmp_path):
    preparation = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
    source = PreparationSource(source_id="source-one", text="Actual holdings still need review.")
    record = preparation.create(
        SinglePlanPreparationInput(preparation_id="one", sources=(source,)),
        idempotency_key="create",
    )
    return preparation, jobs, record


def work_claim(jobs, record, key="extract-one", owner="owner-one"):

    intent = canonical_json(
        {"domain": "single-source-preparation-v1", "preparation_id": record.preparation_id}
    )
    reservation = jobs.claim_run_submission(intent, key)
    return PreparationWorkClaim(
        generation=str(uuid4()),
        owner_id=owner,
        source_revision=record.source_revision,
        source_hash=record.source.binding_hash,
        admission_key=reservation.idempotency_key,
        intent_hash=reservation.intent_hash,
        claimed_at=reservation.claimed_at,
        intent_json=intent,
        phase="READY",
    )


def test_worker_claim_and_progress_survive_restart_without_auto_reclaim(tmp_path):
    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    assert running.attempts[-1].attempt_id == claim.generation
    calling = store.begin_call(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    restored = PreparationStore(store.database_path).get("one")
    assert restored == calling
    assert restored.work_claim.phase == "CALLING"
    assert (
        jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key).intent_hash
        == claim.intent_hash
    )
    with pytest.raises(PreparationConflictError):
        store.begin_call(
            "one",
            generation=claim.generation,
            owner_id="other-owner",
            expected_revision=calling.revision,
        )
    assert store.get("one") == calling


def test_unknown_outcome_stays_occupied_until_explicit_ended_confirmation(tmp_path):
    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    calling = store.begin_call(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    unknown = store.mark_unknown(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=calling.revision,
    )
    assert unknown.status == "EXTRACTING"
    assert unknown.work_claim.phase == "UNKNOWN"
    with pytest.raises(PreparationConflictError):
        store.recover_unknown(
            "one",
            generation=claim.generation,
            expected_revision=unknown.revision,
            confirmed_ended=False,
            idempotency_key="recover",
        )
    ended = store.recover_unknown(
        "one",
        generation=claim.generation,
        expected_revision=unknown.revision,
        confirmed_ended=True,
        idempotency_key="recover",
    )
    assert ended.status == "FAILED"
    assert ended.attempts[-1].error_code == "UNKNOWN_PROVIDER_OUTCOME"
    assert ended.work_claim.phase == "ENDED"
    assert jobs.release_run_submission(
        jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key)
    )


def test_owned_completion_rejects_wrong_owner_and_keeps_release_binding_durable(tmp_path):
    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    calling = store.begin_call(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    for owner in (None, "other-owner"):
        with pytest.raises(PreparationConflictError):
            store.finish_attempt(
                "one",
                attempt_id=claim.generation,
                expected_revision=calling.revision,
                idempotency_key="finish",
                candidate=candidate(),
                worker_owner_id=owner,
            )
    finished = store.finish_attempt(
        "one",
        attempt_id=claim.generation,
        expected_revision=calling.revision,
        idempotency_key="finish",
        candidate=candidate(),
        worker_owner_id=claim.owner_id,
    )
    assert finished.work_claim.phase == "ENDED"
    assert PreparationStore(store.database_path).get("one").work_claim == finished.work_claim
    reservation = jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key)
    assert reservation.claimed_at == claim.claimed_at
    assert jobs.release_run_submission(reservation)
    cleared = store.clear_work_claim(
        "one", generation=claim.generation, expected_revision=finished.revision
    )
    assert cleared.work_claim is None


def test_exact_reservation_read_never_takes_over_other_intents(tmp_path):
    _, jobs, initial = stores(tmp_path)
    intent = canonical_json({"preparation_id": initial.preparation_id})
    reservation = jobs.claim_run_submission(intent, "one")
    assert jobs.get_run_submission_reservation(intent, "one") == reservation
    assert jobs.get_run_submission_reservation(intent, "missing") is None
    with pytest.raises(JobAdmissionError):
        jobs.get_run_submission_reservation(canonical_json({"preparation_id": "other"}), "one")


def test_call_authority_cannot_replay_after_cancel_or_progress(tmp_path):
    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    calling = store.begin_call(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    for revision in (running.revision, calling.revision):
        with pytest.raises(PreparationConflictError):
            store.begin_call(
                "one",
                generation=claim.generation,
                owner_id=claim.owner_id,
                expected_revision=revision,
            )
    cancelled = store.cancel("one", expected_revision=calling.revision, idempotency_key="cancel")
    with pytest.raises(PreparationConflictError):
        store.begin_call(
            "one",
            generation=claim.generation,
            owner_id=claim.owner_id,
            expected_revision=cancelled.revision,
        )
    assert (
        store.replay_start_attempt(
            "one", expected_revision=initial.revision, idempotency_key="start"
        )
        == running
    )
    assert store.get("one") == cancelled


def test_superseded_source_drain_retains_original_reservation(tmp_path):
    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    edited = store.edit_source(
        "one",
        source=initial.source.model_copy(update={"text": "Corrected source."}),
        expected_revision=running.revision,
        idempotency_key="edit",
    )
    ended = store.acknowledge_cancellation(
        "one",
        attempt_id=claim.generation,
        expected_revision=edited.revision,
        idempotency_key="ack",
        worker_owner_id=claim.owner_id,
    )
    assert ended.status == "DRAFT"
    assert ended.attempts == ()
    assert ended.work_claim.phase == "ENDED"
    restored = PreparationStore(store.database_path).get("one")
    assert restored == ended
    assert jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key) is not None


def test_old_documents_need_no_migration_and_ended_confirmation_is_strict(tmp_path):

    store, jobs, initial = stores(tmp_path)
    old = initial.model_dump(mode="json", exclude={"work_claim"})
    assert PreparationRecord.model_validate_json(canonical_json(old)) == initial
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    for confirmation in (False, 1, "true", None):
        with pytest.raises(PreparationConflictError, match="RECOVERY_CONFIRMATION_REQUIRED"):
            store.recover_unknown(
                "one",
                generation=claim.generation,
                expected_revision=running.revision,
                confirmed_ended=confirmation,
                idempotency_key="recover",
            )
    assert store.get("one") == running


def test_owned_worker_records_call_before_provider_and_fences_result(tmp_path):

    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one", expected_revision=initial.revision, idempotency_key="start", work_claim=claim
    )
    calls = []

    def extract(identity, source, token):
        calls.append(identity)
        assert store.get("one").work_claim.phase == "CALLING"
        assert source == initial.source
        raise RuntimeError("secret transport content must not be persisted")

    result = run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    assert result.unknown
    assert result.result is None
    assert len(calls) == 1
    with pytest.raises(PreparationConflictError):
        run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    assert len(calls) == 1


def loop_extractor(*, block=None, error=None, retries=0):

    calls = []

    def call(identity, source, token):
        calls.append(get_ident())
        if block is not None:
            assert block.wait(5), "test did not drain its fake provider"

        class Provider:
            async def extract_plan(self, request):
                if error is not None:
                    raise error
                return RawAIResponse(
                    request_id=request.request_id,
                    provider_id=request.config.provider_id,
                    content=json.dumps(output_for(CASES[0])),
                    model=request.config.model,
                    finish_reason="stop",
                    attempts=1,
                    usage=None,
                )

        return asyncio.run(
            extract_loop_plan(
                request_id=identity,
                source=source,
                config=_config(),
                provider=Provider(),
            )
        )

    return PreparationExtractor(call, max_retries=retries), calls


def service_setup(tmp_path, **options):

    store, jobs, initial = stores(tmp_path)
    initial = store.edit_source(
        "one",
        source=initial.source.model_copy(update={"text": CASES[0]["source"]}),
        expected_revision=initial.revision,
        idempotency_key="fixture-source",
    )
    extractor, calls = loop_extractor(**options)
    return PreparationService(store, jobs, extractor), store, jobs, initial, calls


def test_actual_extraction_release_failure_keeps_admission_until_explicit_recovery(
    tmp_path, monkeypatch
):
    async def scenario():
        service, store, jobs, initial, calls = service_setup(tmp_path)
        original = jobs.release_run_submission

        def fail(*args, **kwargs):
            raise RuntimeError("injected preparation release failure")

        monkeypatch.setattr(jobs, "release_run_submission", fail)
        try:
            await service.submit_extraction(
                "one", expected_revision=initial.revision, idempotency_key="extract"
            )
            with pytest.raises(RuntimeError, match="preparation release failure"):
                await service.wait_for_drain()
            ended = store.get("one")
            assert ended.status == "CANDIDATE" and ended.work_claim.phase == "ENDED"
            assert len(calls) == 1
            with pytest.raises(JobAdmissionError):
                jobs.submit(request("VERIFY"), "other")
            monkeypatch.setattr(jobs, "release_run_submission", original)
            restored = PreparationService(store, jobs, service._extractor)
            try:
                await restored.recover(
                    "one", generation=ended.work_claim.generation,
                    expected_revision=ended.revision, confirmed_ended=True,
                    idempotency_key="recover-release",
                )
                assert store.get("one").candidate == ended.candidate
                assert store.get("one").work_claim is None and len(calls) == 1
                assert jobs.submit(request("VERIFY"), "other").job_id
            finally:
                await restored.stop()
        finally:
            monkeypatch.setattr(jobs, "release_run_submission", original)
            with pytest.raises(RuntimeError, match="preparation release failure"):
                await service.stop()

    asyncio.run(scenario())


def collection_record_fixture():
    from tests.integration.test_plan_preparation_store import NOW, collection_input

    from trade_plan_monitor.backtest.preparation_models import (
        CollectionPreparationRecord,
        PreparationItem,
    )

    value = collection_input()
    return CollectionPreparationRecord(
        preparation_id=value.preparation_id,
        items=tuple(PreparationItem(source=source, status="DRAFT" if i == 0 else "WAITING")
                    for i, source in enumerate(value.sources)),
        revision=1, created_at=NOW, updated_at=NOW,
    )


def test_collection_cancelled_successor_preserves_original_predecessor_attempt_binding():
    from tests.integration.test_plan_preparation_store import materialized_collection

    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationRecord

    ready = materialized_collection(collection_record_fixture())
    raw = ready.model_dump(mode="python")
    raw.update(items=raw["items"][:2], status="CANCELLED")
    successor = raw["items"][1]
    successor.update(candidate=None, status="CANCELLED")
    successor["attempts"][0]["status"] = "CANCELLED"
    result = CollectionPreparationRecord.model_validate(raw)
    assert result.items[0] == ready.items[0]
    assert result.items[1].candidate is None
    assert result.items[1].base_hash == ready.items[0].candidate.candidate_hash
    assert result.items[1].attempts[-1].base_hash == result.items[1].base_hash
    assert result.items[1].attempts[-1].status == "CANCELLED"
    assert CollectionPreparationRecord.model_validate_json(result.model_dump_json()) == result


def test_collection_cancelled_item_cannot_relabel_a_succeeded_attempt():
    from tests.integration.test_plan_preparation_store import materialized_collection

    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationRecord

    raw = materialized_collection(collection_record_fixture()).model_dump(mode="python")
    raw.update(items=raw["items"][:1], status="CANCELLED")
    raw["items"][0].update(candidate=None, status="CANCELLED")
    with pytest.raises(ValueError):
        CollectionPreparationRecord.model_validate(raw)


def collection_claim(record, index, *, generation="generation-first"):
    from tests.integration.test_plan_preparation_store import NOW

    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationWorkClaim

    item = record.items[index]
    predecessor = record.items[index - 1].candidate if index else None
    return CollectionPreparationWorkClaim(
        generation=generation, owner_id="collection-owner", source_id=item.source.source_id,
        source_revision=item.source_revision, source_hash=item.source.binding_hash,
        base_hash=predecessor.candidate_hash if predecessor else None,
        admission_key="collection-reservation", intent_hash="a" * 64,
        claimed_at=NOW, intent_json='{"synthetic":"collection-extraction"}', phase="READY",
    )


def test_collection_store_requires_owned_claim_and_valid_predecessor(tmp_path):
    from tests.integration.test_plan_preparation_store import NOW, collection_input

    store = PreparationStore(tmp_path / "collection.sqlite", clock=lambda: NOW)
    record = store.create(collection_input(), idempotency_key="create-collection")
    with pytest.raises(PreparationConflictError):
        store.start_attempt(
            record.preparation_id, expected_revision=record.revision, idempotency_key="unowned",
        )
    with pytest.raises(PreparationConflictError):
        store.start_attempt(
            record.preparation_id, expected_revision=record.revision, idempotency_key="skip-first",
            work_claim=collection_claim(record, 1),
        )
    assert store.get(record.preparation_id) == record


def test_collection_store_advances_serially_and_fences_wrong_base_or_old_generation(tmp_path):
    from tests.integration.test_plan_preparation_store import NOW, collection_input

    store = PreparationStore(tmp_path / "collection.sqlite", clock=lambda: NOW)
    record = store.create(collection_input(), idempotency_key="create-collection")
    claim = collection_claim(record, 0)
    running = store.start_attempt(
        record.preparation_id, expected_revision=record.revision, idempotency_key="first-start",
        work_claim=claim,
    )
    assert [item.status for item in running.items] == ["EXTRACTING", "WAITING", "WAITING"]
    calling = store.begin_call(
        record.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    first = store.finish_attempt(
        record.preparation_id, attempt_id=claim.generation, expected_revision=calling.revision,
        idempotency_key="first-finish", candidate=candidate(), worker_owner_id=claim.owner_id,
    )
    assert first.items[0].candidate.validation == "VALID"
    assert first.items[0].candidate.base_hash is None
    assert first.items[1].candidate is None and not first.items[1].attempts
    assert first.work_claim.phase == "ENDED"
    second_claim = collection_claim(first, 1, generation="generation-second")
    with pytest.raises(PreparationConflictError):
        store.start_attempt(
            record.preparation_id, expected_revision=first.revision, idempotency_key="wrong-base",
            work_claim=second_claim.model_copy(update={"base_hash": "f" * 64}),
        )
    second = store.start_attempt(
        record.preparation_id, expected_revision=first.revision, idempotency_key="second-start",
        work_claim=second_claim,
    )
    assert second.items[0] == first.items[0]
    assert second.items[1].attempts[-1].base_hash == first.items[0].candidate.candidate_hash
    assert second.work_claim.admission_key == first.work_claim.admission_key
    assert PreparationStore(store.database_path).get(record.preparation_id) == second
    with pytest.raises(PreparationConflictError):
        store.finish_attempt(
            record.preparation_id, attempt_id=claim.generation, expected_revision=second.revision,
            idempotency_key="late-first", candidate=candidate(), worker_owner_id=claim.owner_id,
        )
    assert store.get(record.preparation_id) == second


def collection_worker_setup(tmp_path, *, future_source=None, start_successor=True):
    from tests.integration.test_plan_preparation_store import NOW
    from tests.unit.test_monitor_loop_schedule import at
    from tests.unit.test_plan_update_bindings import current_update, prior_review

    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput

    base = prior_review()
    current, output = current_update()
    first = PreparationSource(
        source_id="first", text="Synthetic human-reviewed supplements for this fixture.",
        authored_at=at(19), available_at=at(19), effective_trade_date=at(19).date(),
    )
    future = future_source or PreparationSource(
        source_id="future", text="FUTURE_CONTENT_MUST_NOT_REACH_CURRENT_PROVIDER",
        authored_at=at(21), available_at=at(21), effective_trade_date=at(21).date(),
    )
    assert first.binding_hash == base.source_hash
    store = PreparationStore(tmp_path / "collection.sqlite", clock=lambda: NOW)
    jobs = BacktestJobRepository(tmp_path / "results.sqlite", clock=lambda: NOW)
    record = store.create(
        PlanCollectionPreparationInput(
            preparation_id="worker-collection", sources=(first, current, future),
        ), idempotency_key="create-collection",
    )
    intent = canonical_json({"synthetic": "whole-collection-reservation"})
    reservation = jobs.claim_run_submission(intent, "collection-reservation")
    claim = collection_claim(record, 0, generation=str(uuid4())).model_copy(update={
        "intent_json": intent, "intent_hash": reservation.intent_hash,
        "claimed_at": reservation.claimed_at,
    })
    running = store.start_attempt(
        record.preparation_id, expected_revision=record.revision,
        idempotency_key="seed-start", work_claim=claim,
    )
    calling = store.begin_call(
        record.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    seeded = store.finish_attempt(
        record.preparation_id, attempt_id=claim.generation, expected_revision=calling.revision,
        idempotency_key="seed-finish", candidate=base.to_preparation_candidate(),
        worker_owner_id=claim.owner_id,
    )
    if not start_successor:
        jobs.release_run_submission(reservation)
        seeded = store.clear_work_claim(
            record.preparation_id, generation=claim.generation, expected_revision=seeded.revision,
        )
        return store, jobs, seeded, base, output
    next_claim = claim.model_copy(update={
        "generation": str(uuid4()), "source_id": current.source_id,
        "source_hash": current.binding_hash, "base_hash": seeded.items[0].candidate.candidate_hash,
    })
    next_record = store.start_attempt(
        record.preparation_id, expected_revision=seeded.revision,
        idempotency_key="second-start", work_claim=next_claim,
    )
    return store, jobs, next_record, base, output


def collection_update_result(base, source, output, identity, context):
    from tests.unit.test_plan_update_bindings import extraction_for

    result = extraction_for(base, source, output)
    digest = sha256(canonical_json({
        "domain": "monitor-loop-update-evidence-v1",
        "source_binding_hash": source.binding_hash, "context": context, "output": output,
    }).encode()).hexdigest()
    return result.model_copy(update={
        "request_id": identity, "base_hash": context.base_hash, "evidence_hash": digest,
    })


def test_collection_worker_only_sends_current_source_and_bound_predecessor(tmp_path):
    store, jobs, running, base, output = collection_worker_setup(tmp_path)
    calls = []

    def extract(identity, source, token, *, context):
        calls.append((identity, source, context))
        return collection_update_result(base, source, output, identity, context)

    outcome = run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    assert len(calls) == 1
    identity, source, context = calls[0]
    assert str(identity) == running.work_claim.generation
    assert source == running.items[1].source
    assert context.base_hash == running.items[0].candidate.candidate_hash
    assert context.snapshot == base.draft.to_executable()
    assert context.available_at == running.items[0].source.available_at
    assert "FUTURE_CONTENT" not in canonical_json(context)
    assert not outcome.unknown
    assert outcome.candidate.validation == "VALID"
    payload = json.loads(outcome.candidate.payload_json)
    assert payload["review"]["draft"]["position"]["max_qty"] == 300
    durable = store.get(running.preparation_id)
    assert durable.items[1].candidate is None and durable.work_claim.phase == "CALLING"
    assert durable.items[2] == running.items[2]


@pytest.mark.parametrize("tamper", ["generation", "base", "source", "digest", "review-type"])
def test_collection_worker_rejects_unbound_provider_result_without_candidate(tmp_path, tamper):
    store, jobs, running, base, output = collection_worker_setup(tmp_path)
    calls = []

    def extract(identity, source, token, *, context):
        calls.append(identity)
        if tamper == "review-type":
            return base  # A provider cannot return trusted server-reviewed evidence.
        result = collection_update_result(base, source, output, identity, context)
        changes = {
            "generation": {"request_id": uuid4()},
            "base": {"base_hash": "f" * 64},
            "source": {"source_id": "future"},
            "digest": {"evidence_hash": "0" * 64},
        }
        return result.model_copy(update=changes[tamper])

    outcome = run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    assert len(calls) == 1
    assert outcome.unknown and outcome.candidate is None
    durable = store.get(running.preparation_id)
    assert durable.items[0] == running.items[0]
    assert durable.items[1].candidate is None
    assert durable.items[2] == running.items[2]
    with pytest.raises(PreparationConflictError):
        run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    assert len(calls) == 1


def test_collection_unknown_recovery_retains_prefix_and_bounds_owned_retries(tmp_path):
    store, jobs, running, _, _ = collection_worker_setup(tmp_path)
    original_claim = running.work_claim
    calling = store.begin_call(
        running.preparation_id, generation=original_claim.generation,
        owner_id=original_claim.owner_id, expected_revision=running.revision,
    )
    unknown = store.mark_unknown(
        running.preparation_id, generation=original_claim.generation,
        owner_id=original_claim.owner_id, expected_revision=calling.revision,
    )
    assert unknown.work_claim.phase == "UNKNOWN"
    for confirmation in (False, 1):
        with pytest.raises(PreparationConflictError, match="RECOVERY_CONFIRMATION_REQUIRED"):
            store.recover_unknown(
                running.preparation_id, generation=original_claim.generation,
                expected_revision=unknown.revision, confirmed_ended=confirmation,
                idempotency_key="bad-recovery",
            )
    recovered = store.recover_unknown(
        running.preparation_id, generation=original_claim.generation,
        expected_revision=unknown.revision, confirmed_ended=True, idempotency_key="recover-v2",
    )
    item = recovered.items[1]
    assert recovered.status == item.status == "FAILED"
    assert item.attempts[-1].status == "FAILED"
    assert item.attempts[-1].error_code == "UNKNOWN_PROVIDER_OUTCOME"
    assert item.attempts[-1].retryable
    assert item.base_hash == item.attempts[-1].base_hash == running.items[1].base_hash
    assert recovered.items[0] == running.items[0]
    assert recovered.items[2] == running.items[2]
    assert recovered.work_claim.phase == "ENDED"
    reservation = jobs.get_run_submission_reservation(
        original_claim.intent_json, original_claim.admission_key,
    )
    assert jobs.release_run_submission(reservation)
    current = store.clear_work_claim(
        running.preparation_id, generation=original_claim.generation,
        expected_revision=recovered.revision,
    )
    reservation = jobs.claim_run_submission(original_claim.intent_json, "recovery-retry")
    retry_claim = original_claim.model_copy(update={
        "generation": str(uuid4()), "phase": "READY",
        "admission_key": reservation.idempotency_key, "intent_hash": reservation.intent_hash,
        "claimed_at": reservation.claimed_at,
    })
    for number in (2, 3):
        retry_claim = retry_claim.model_copy(update={"generation": str(uuid4())})
        active = store.start_attempt(
            running.preparation_id, expected_revision=current.revision,
            idempotency_key=f"retry-{number}", work_claim=retry_claim,
        )
        assert len(active.items[1].attempts) == number
        with pytest.raises(PreparationConflictError):
            store.finish_attempt(
                running.preparation_id, attempt_id=original_claim.generation,
                expected_revision=active.revision, idempotency_key=f"stale-{number}",
                candidate=candidate(), worker_owner_id=original_claim.owner_id,
            )
        calling = store.begin_call(
            running.preparation_id, generation=retry_claim.generation,
            owner_id=retry_claim.owner_id, expected_revision=active.revision,
        )
        current = store.finish_attempt(
            running.preparation_id, attempt_id=retry_claim.generation,
            expected_revision=calling.revision, idempotency_key=f"retry-finish-{number}",
            error_code="TRANSIENT", retryable=True, worker_owner_id=retry_claim.owner_id,
        )
        assert current.items[0] == running.items[0]
        assert current.items[2] == running.items[2]
        assert current.items[1].base_hash == running.items[1].base_hash
    with pytest.raises(PreparationConflictError, match="ATTEMPTS_EXHAUSTED"):
        store.start_attempt(
            running.preparation_id, expected_revision=current.revision,
            idempotency_key="retry-fourth",
            work_claim=retry_claim.model_copy(update={"generation": str(uuid4())}),
        )
    assert store.get(running.preparation_id) == current


def test_collection_explicitly_corrected_successor_can_seed_next_context(tmp_path):
    from trade_plan_monitor.ai.update_review import build_update_review, context_from_review
    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationRecord
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    store, _, running, base, output = collection_worker_setup(tmp_path)
    source = running.items[1].source
    # This is trusted server review evidence persisted by an explicit correction,
    # distinct from the provider's allowed extraction result type.
    corrected = build_update_review(base, source, output)
    claim = running.work_claim
    calling = store.begin_call(
        running.preparation_id, generation=claim.generation,
        owner_id=claim.owner_id, expected_revision=running.revision,
    )
    ready = store.finish_attempt(
        running.preparation_id, attempt_id=claim.generation,
        expected_revision=calling.revision, idempotency_key="explicit-successor-review",
        candidate=corrected.to_preparation_candidate(), worker_owner_id=claim.owner_id,
    )
    predecessor = preparation_candidate_review(ready, 1)
    assert predecessor == corrected
    context = context_from_review(predecessor, ready.items[1].candidate.candidate_hash)
    assert context.snapshot.position.max_qty == 300
    assert context.available_at == source.available_at < ready.items[2].source.available_at
    assert context.base_hash == ready.items[1].candidate.candidate_hash
    assert "FUTURE_CONTENT" not in canonical_json(context)

    moved_source = source.model_copy(update={"text": source.text + "Changed source."})
    with pytest.raises(ValueError):
        changed_item = ready.items[1].model_copy(update={"source": moved_source})
        changed = ready.model_copy(update={"items": (ready.items[0], changed_item, ready.items[2])})
        preparation_candidate_review(changed, 1)
    raw = ready.model_dump(mode="python")
    raw["items"][1]["base_hash"] = "f" * 64
    raw["items"][1]["candidate"]["base_hash"] = "f" * 64
    raw["items"][1]["attempts"][-1]["base_hash"] = "f" * 64
    with pytest.raises(ValueError):
        CollectionPreparationRecord.model_validate(raw)


def test_service_runs_one_owned_call_and_idempotency_never_redispatches(tmp_path):

    async def scenario():
        service, store, jobs, initial, calls = service_setup(tmp_path)
        try:
            first = await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await service.wait_for_drain()
            completed = store.get("one")
            assert completed.status == "CANDIDATE"
            assert completed.review is None
            assert completed.work_claim is None
            assert calls and calls[0] != get_ident()
            assert (
                await service.submit_extraction(
                    "one",
                    expected_revision=initial.revision,
                    idempotency_key="extract",
                )
                == first
            )
            assert len(calls) == 1
            assert jobs.list_jobs() == ()
        finally:
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "code,expected_calls",
    [("RATE_LIMITED", 3), ("AUTHENTICATION", 1), ("TIMEOUT", 1), ("TRANSIENT", 1)],
)
def test_bounded_known_retries_and_unknown_outcomes_require_recovery(
    tmp_path, code, expected_calls
):

    async def scenario():
        error = AIProviderError(
            AIProviderErrorCode(code), AIProviderOperation.EXTRACT_PLAN, attempts=1
        )
        service, store, jobs, initial, calls = service_setup(tmp_path, error=error, retries=2)
        restored = None
        try:
            first = await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await service.wait_for_drain()
            assert len(calls) == expected_calls
            current = store.get("one")
            restored = PreparationService(
                PreparationStore(store.database_path), jobs, service._extractor
            )
            assert await restored.get("one") == current
            assert (
                await restored.submit_extraction(
                    "one",
                    expected_revision=initial.revision,
                    idempotency_key="extract",
                )
                == first
            )
            assert len(calls) == expected_calls
            if code in {"TIMEOUT", "TRANSIENT"}:
                assert current.work_claim.phase == "UNKNOWN"
                with pytest.raises(JobAdmissionError):
                    jobs.submit(request("VERIFY"), "blocked")
                with pytest.raises(
                    PreparationConflictError, match="RECOVERY_CONFIRMATION_REQUIRED"
                ):
                    await restored.recover(
                        "one",
                        generation=current.work_claim.generation,
                        expected_revision=current.revision,
                        confirmed_ended=False,
                        idempotency_key="recover",
                    )
                recovered = await restored.recover(
                    "one",
                    generation=current.work_claim.generation,
                    expected_revision=current.revision,
                    confirmed_ended=True,
                    idempotency_key="recover",
                )
                assert recovered.status == "FAILED"
                assert store.get("one").work_claim is None
                assert len(calls) == 1  # Recovery never repeats the paid request.
            else:
                assert current.status == "FAILED" and current.work_claim is None
                assert len(current.attempts) == expected_calls
        finally:
            if restored:
                await restored.stop()
            await service.stop()

    asyncio.run(scenario())


async def wait_calling(store, calls):

    for _ in range(200):
        record = store.get("one")
        if calls and record.work_claim and record.work_claim.phase == "CALLING":
            return record
        await asyncio.sleep(0.005)
    raise AssertionError("fake provider was not called")


def test_shutdown_timeout_and_cancelled_observer_keep_physical_ownership(tmp_path):

    async def scenario():
        block = Event()
        service, store, jobs, initial, calls = service_setup(tmp_path, block=block)
        service._config = BacktestServiceConfig(shutdown_wait_seconds=0.02)
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await wait_calling(store, calls)
            observer = asyncio.create_task(service.wait_for_drain())
            await asyncio.sleep(0)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            with pytest.raises(BacktestServiceUnavailable):
                await service.stop()
            assert store.get("one").status == "CANCEL_REQUESTED"
            assert service._owner.outstanding_work == 1
            with pytest.raises(JobAdmissionError):
                jobs.submit(request("VERIFY"), "blocked")
            block.set()
            await service.wait_for_drain()
            assert store.get("one").status == "CANCELLED"
            assert store.get("one").work_claim is None
            assert service._owner.outstanding_work == 0
        finally:
            block.set()
            await service.stop()

    asyncio.run(scenario())


def test_same_source_edit_is_noop_and_other_mutations_obey_global_admission(tmp_path):

    async def scenario():
        block = Event()
        service, store, jobs, initial, calls = service_setup(tmp_path, block=block)
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            calling = await wait_calling(store, calls)
            assert (
                await service.edit_source(
                    "one",
                    source=calling.source,
                    expected_revision=calling.revision,
                    idempotency_key="same-source",
                )
                == calling
            )
            assert not service._token.cancelled
            block.set()
            await service.wait_for_drain()
            assert store.get("one").status == "CANDIDATE"
            jobs.submit(request("VERIFY"), "verify")
            current = store.get("one")
            with pytest.raises(JobAdmissionError):
                await service.edit_source(
                    "one",
                    source=current.source.model_copy(update={"text": "Correction."}),
                    expected_revision=current.revision,
                    idempotency_key="blocked-edit",
                )
            with pytest.raises(JobAdmissionError):
                await service.cancel(
                    "one",
                    expected_revision=current.revision,
                    idempotency_key="blocked-cancel",
                )
            assert store.get("one") == current
        finally:
            block.set()
            await service.stop()

    asyncio.run(scenario())


def test_configured_ai_transport_is_owned_and_shares_existing_single_call_slot(tmp_path):

    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "ai:\n  profile: DEEPSEEK\n  base_url: https://api.deepseek.com\n"
        "  model: offline-v4\n  api_key: synthetic-test-key\n  max_retries: 2\n",
        encoding="utf-8",
    )
    block = Event()
    created, closed, calls = [], [], []

    class Client(httpx.AsyncClient):
        async def __aexit__(self, *args):
            closed.append(get_ident())
            await super().__aexit__(*args)

        async def aclose(self):
            closed.append(get_ident())
            await super().aclose()

    async def handler(request):
        calls.append(get_ident())
        if len(calls) == 1:
            while not block.is_set():
                await asyncio.sleep(0.005)
            content = json.dumps(output_for(CASES[0]))
        else:
            content = "{}"
        return httpx.Response(
            200,
            json={
                "model": "offline-v4",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    def factory():
        created.append(get_ident())
        return Client(transport=httpx.MockTransport(handler), trust_env=False)

    async def scenario():
        lifecycle = ConfiguredAIWebLifecycle(config_path=config_path, client_factory=factory)
        await lifecycle.start()
        service = None
        try:
            extractor = lifecycle.backtest_extractor()
            assert extractor.max_retries == 2
            _, store, jobs, initial, _ = service_setup(tmp_path)
            service = PreparationService(store, jobs, extractor)
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await wait_calling(store, calls)
            provider_id = lifecycle._binding.config.provider_id
            receipt = await lifecycle.submit_plan_extraction(
                command=PlanExtractionCommand(
                    provider_id=provider_id,
                    source_text="Synthetic ordinary source.",
                    expected_revision=0,
                ),
                context=MutationContext(idempotency_key="ordinary", request_id="a" * 32),
            )
            await asyncio.sleep(0.03)
            assert len(calls) == 1
            view = await lifecycle.get_plan_extraction(operation_id=str(receipt.operation_id))
            assert view.status.value == "QUEUED"
            block.set()
            await service.wait_for_drain()
            await asyncio.gather(*tuple(lifecycle._tasks))
            assert store.get("one").status == "CANDIDATE"
            assert len(calls) == 2
            assert created[0] == calls[1] == get_ident()
            assert created[1] == calls[0] == closed[0] != get_ident()
        finally:
            block.set()
            if service:
                await service.stop()
            await lifecycle.stop()

    asyncio.run(scenario())
    assert closed == [created[1], created[0]]


@pytest.mark.parametrize("field", ["request_id", "source_text_sha256", "source_binding_hash"])
def test_late_or_foreign_provider_result_cannot_create_candidate(tmp_path, field):

    async def scenario():
        service, store, _, initial, calls = service_setup(tmp_path)
        actual = service._extractor

        def stale(identity, source, token):
            result = actual.call(identity, source, token)
            replacement = uuid4() if field == "request_id" else "0" * 64
            return result.model_copy(update={field: replacement})

        service._extractor = PreparationExtractor(stale)
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await service.wait_for_drain()
            current = store.get("one")
            assert current.work_claim.phase == "UNKNOWN"
            assert current.candidate is None and current.review is None
            assert len(calls) == 1
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_crash_before_attempt_commit_can_reuse_exact_unresolved_admission(tmp_path):

    async def scenario():
        service, store, jobs, initial, calls = service_setup(tmp_path)
        key = "extract"
        intent = canonical_json(
            {
                "domain": "single-source-preparation-v1",
                "preparation_id": "one",
                "source_revision": initial.source_revision,
                "source_hash": initial.source.binding_hash,
                "expected_revision": initial.revision,
            }
        )
        admission_key = (
            "prep-extract-"
            + sha256(
                canonical_json(
                    {
                        "preparation_id": "one",
                        "idempotency_key": key,
                    }
                ).encode()
            ).hexdigest()
        )
        reserved = jobs.claim_run_submission(intent, admission_key)
        try:
            first = await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key=key,
            )
            assert first.work_claim.claimed_at == reserved.claimed_at
            await service.wait_for_drain()
            assert store.get("one").status == "CANDIDATE"
            assert len(calls) == 1
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_crash_after_durable_end_releases_exact_reservation_without_ai(tmp_path):

    store, jobs, initial = stores(tmp_path)
    claim = work_claim(jobs, initial)
    running = store.start_attempt(
        "one",
        expected_revision=initial.revision,
        idempotency_key="start",
        work_claim=claim,
    )
    calling = store.begin_call(
        "one",
        generation=claim.generation,
        owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    ended = store.finish_attempt(
        "one",
        attempt_id=claim.generation,
        expected_revision=calling.revision,
        worker_owner_id=claim.owner_id,
        candidate=candidate(),
        idempotency_key="finish",
    )
    extractor, calls = loop_extractor()

    async def scenario():
        restored = PreparationService(store, jobs, extractor)
        try:
            await restored.recover(
                "one",
                generation=claim.generation,
                expected_revision=ended.revision,
                confirmed_ended=True,
                idempotency_key="cleanup",
            )
            assert store.get("one").candidate == ended.candidate
            assert store.get("one").work_claim is None
            assert not calls
        finally:
            await restored.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("same_key", [True, False])
def test_two_service_instances_cannot_dispatch_two_calls(tmp_path, same_key):

    async def scenario():
        block = Event()
        first, store, jobs, initial, calls = service_setup(tmp_path, block=block)
        second = PreparationService(PreparationStore(store.database_path), jobs, first._extractor)
        try:
            outcomes = await asyncio.gather(
                first.submit_extraction(
                    "one",
                    expected_revision=initial.revision,
                    idempotency_key="extract",
                ),
                second.submit_extraction(
                    "one",
                    expected_revision=initial.revision,
                    idempotency_key="extract" if same_key else "other-extract",
                ),
                return_exceptions=True,
            )
            assert any(not isinstance(result, Exception) for result in outcomes)
            for result in outcomes:
                if isinstance(result, Exception):
                    assert isinstance(result, (JobAdmissionError, PreparationConflictError))
            await wait_calling(store, calls)
            assert len(calls) == 1
            block.set()
            await first.wait_for_drain()
            await second.wait_for_drain()
            assert store.get("one").status == "CANDIDATE"
            assert store.get("one").work_claim is None
        finally:
            block.set()
            await first.stop()
            await second.stop()

    asyncio.run(scenario())


def test_expired_unknown_reservation_remains_occupied_and_explicit_retry_uses_budget(tmp_path):

    async def scenario():
        error = AIProviderError(
            AIProviderErrorCode.TIMEOUT, AIProviderOperation.EXTRACT_PLAN, attempts=1
        )
        service, store, jobs, initial, calls = service_setup(tmp_path, error=error, retries=2)
        clock = _Clock(datetime(2026, 10, 8, 10, tzinfo=_SHANGHAI))
        jobs._clock = clock
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await service.wait_for_drain()
            clock.advance(timedelta(seconds=31))
            unknown = store.get("one")
            token = jobs.get_run_submission_reservation(
                unknown.work_claim.intent_json,
                unknown.work_claim.admission_key,
            )
            assert token.claimed_at == unknown.work_claim.claimed_at
            for kind in ("RUN", "SYNC", "VERIFY"):
                with pytest.raises(JobAdmissionError):
                    jobs.submit(request(kind), kind, request_id="3" * 32)
            for attempt in range(1, 4):
                current = store.get("one")
                if current.work_claim:
                    await service.recover(
                        "one",
                        generation=current.work_claim.generation,
                        expected_revision=current.revision,
                        confirmed_ended=True,
                        idempotency_key=f"recover-{attempt}",
                    )
                current = store.get("one")
                if attempt == 3:
                    with pytest.raises(PreparationConflictError, match="ATTEMPTS_EXHAUSTED"):
                        await service.submit_extraction(
                            "one",
                            expected_revision=current.revision,
                            idempotency_key="exhausted",
                        )
                else:
                    await service.submit_extraction(
                        "one",
                        expected_revision=current.revision,
                        idempotency_key=f"explicit-retry-{attempt}",
                    )
                    await service.wait_for_drain()
            assert len(calls) == len(store.get("one").attempts) == 3
            jobs.submit(request("VERIFY"), "after-exhaustion")
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_configured_retries_make_one_paid_request_per_durable_attempt(tmp_path):

    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "ai:\n  profile: DEEPSEEK\n  base_url: https://api.deepseek.com\n"
        "  model: offline-v4\n  api_key: synthetic-test-key\n  max_retries: 2\n",
        encoding="utf-8",
    )
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"error": "synthetic rate limit"})

    async def scenario():
        lifecycle = ConfiguredAIWebLifecycle(
            config_path=config_path,
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        await lifecycle.start()
        service = None
        try:
            _, store, jobs, initial, _ = service_setup(tmp_path)
            service = PreparationService(store, jobs, lifecycle.backtest_extractor())
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            await service.wait_for_drain()
            failed = store.get("one")
            assert failed.status == "FAILED"
            assert len(calls) == len(failed.attempts) == 3
            assert all(attempt.error_code == "RATE_LIMITED" for attempt in failed.attempts)
            assert failed.work_claim is None
        finally:
            if service:
                await service.stop()
            await lifecycle.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_replaying_old_edit_receipt_cannot_cancel_a_new_generation(tmp_path, external_cancel):

    async def scenario():
        first_block, second_block = Event(), Event()
        service, store, _, initial, first_calls = service_setup(tmp_path, block=first_block)
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract-one",
            )
            calling = await wait_calling(store, first_calls)
            source = initial.source.model_copy(
                update={
                    "authored_at": datetime(2026, 10, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
                }
            )
            edited = await service.edit_source(
                "one",
                source=source,
                expected_revision=calling.revision,
                idempotency_key="edit",
            )
            first_block.set()
            await service.wait_for_drain()
            service._extractor, calls = loop_extractor(block=second_block)
            current = store.get("one")
            await service.submit_extraction(
                "one",
                expected_revision=current.revision,
                idempotency_key="extract-two",
            )
            new_calling = await wait_calling(store, calls)
            if external_cancel:
                # Another owner changes durable state without touching this local token.
                store.cancel(
                    "one",
                    expected_revision=new_calling.revision,
                    idempotency_key="external-cancel",
                )
            assert (
                await service.edit_source(
                    "one",
                    source=source,
                    expected_revision=calling.revision,
                    idempotency_key="edit",
                )
                == edited
            )
            assert not service._token.cancelled
            assert store.get("one").status == (
                "CANCEL_REQUESTED" if external_cancel else "EXTRACTING"
            )
            second_block.set()
            await service.wait_for_drain()
            assert store.get("one").status == ("CANCELLED" if external_cancel else "CANDIDATE")
        finally:
            first_block.set()
            second_block.set()
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["cancel", "edit"])
def test_pending_call_blocks_all_jobs_until_physical_drain(tmp_path, action):

    async def scenario():
        block = Event()
        service, store, jobs, initial, calls = service_setup(tmp_path, block=block)
        try:
            await service.submit_extraction(
                "one",
                expected_revision=initial.revision,
                idempotency_key="extract",
            )
            calling = await wait_calling(store, calls)
            if action == "cancel":
                pending = await service.cancel(
                    "one",
                    expected_revision=calling.revision,
                    idempotency_key="cancel",
                )
            else:
                pending = await service.edit_source(
                    "one",
                    source=initial.source.model_copy(update={"text": "Correction."}),
                    expected_revision=calling.revision,
                    idempotency_key="edit",
                )
            assert pending.status == "CANCEL_REQUESTED"
            for kind in ("RUN", "SYNC", "VERIFY"):
                with pytest.raises(JobAdmissionError, match="unfinished"):
                    jobs.submit(request(kind), f"new-{kind}", request_id="1" * 32)
            with pytest.raises(PreparationConflictError, match="WORKER_NOT_DRAINED"):
                await service.recover(
                    "one",
                    generation=pending.work_claim.generation,
                    expected_revision=pending.revision,
                    confirmed_ended=True,
                    idempotency_key="recover",
                )
            assert len(calls) == 1
            block.set()
            await service.wait_for_drain()
            ended = store.get("one")
            assert ended.status == ("CANCELLED" if action == "cancel" else "DRAFT")
            assert ended.candidate is None and ended.review is None and ended.work_claim is None
            jobs.submit(request("VERIFY"), "after-drain", request_id="2" * 32)
        finally:
            block.set()
            await service.stop()

    asyncio.run(scenario())


def test_collection_successor_cancel_waits_for_physical_call_and_preserves_prefix(tmp_path):
    store, jobs, prepared, base, output = collection_worker_setup(tmp_path, start_successor=False)
    entered, release = Event(), Event()
    calls = []

    def extract(identity, source, token, *, context):
        calls.append(source.source_id)
        entered.set()
        assert release.wait(10), "synthetic provider was not drained"
        return collection_update_result(base, source, output, identity, context)

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(extract))
        try:
            await service.submit_extraction(
                prepared.preparation_id, expected_revision=prepared.revision,
                idempotency_key="cancel-successor-start",
            )
            assert await asyncio.to_thread(entered.wait, 5)
            calling = store.get(prepared.preparation_id)
            assert calling.work_claim.phase == "CALLING"
            assert calling.items[1].base_hash == prepared.items[0].candidate.candidate_hash
            pending = await service.cancel(
                prepared.preparation_id, expected_revision=calling.revision,
                idempotency_key="cancel-successor",
            )
            assert pending.status == pending.items[1].status == "CANCEL_REQUESTED"
            assert pending.items[1].attempts[-1].status == "CANCEL_REQUESTED"
            assert pending.items[1].attempts[-1].finished_at is None
            assert pending.items[0] == prepared.items[0]
            for kind in ("RUN", "SYNC", "VERIFY"):
                with pytest.raises(JobAdmissionError):
                    jobs.submit(request(kind), "blocked-collection-" + kind, request_id="a" * 32)
            with pytest.raises(PreparationConflictError, match="WORKER_NOT_DRAINED"):
                await service.recover(
                    prepared.preparation_id, generation=pending.work_claim.generation,
                    expected_revision=pending.revision, confirmed_ended=True,
                    idempotency_key="premature-recovery",
                )
            with pytest.raises(PreparationConflictError):
                store.finish_attempt(
                    prepared.preparation_id, attempt_id=calling.work_claim.generation,
                    expected_revision=pending.revision, idempotency_key="late-success",
                    candidate=candidate(), worker_owner_id=calling.work_claim.owner_id,
                )
            release.set()
            await service.wait_for_drain()
            ended = store.get(prepared.preparation_id)
            assert ended.status == ended.items[1].status == "CANCELLED"
            assert ended.work_claim is None and ended.review is None
            assert ended.items[0] == prepared.items[0]
            assert ended.items[1].candidate is None
            attempt = ended.items[1].attempts[-1]
            assert attempt.status == "CANCELLED" and attempt.finished_at is not None
            assert attempt.base_hash == calling.items[1].base_hash == ended.items[1].base_hash
            assert attempt.attempt_id == calling.work_claim.generation
            assert not ended.items[2].attempts and ended.items[2].candidate is None
            assert calls == ["second"]
            assert await service.cancel(
                prepared.preparation_id, expected_revision=calling.revision,
                idempotency_key="cancel-successor",
            ) == pending
            assert store.get(prepared.preparation_id) == ended
            assert jobs.submit(request("VERIFY"), "after-collection-drain").job_id
        finally:
            release.set()
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("unknown", [False, True], ids=["calling", "unknown"])
def test_collection_cancelled_successor_restarts_without_losing_attempt_base(tmp_path, unknown):
    from tests.integration.test_plan_preparation_store import NOW

    store, jobs, running, _, _ = collection_worker_setup(tmp_path)
    claim = running.work_claim
    calling = store.begin_call(
        running.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
        expected_revision=running.revision,
    )
    if unknown:
        calling = store.mark_unknown(
            running.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
            expected_revision=calling.revision,
        )
    pending = store.cancel(
        running.preparation_id, expected_revision=calling.revision,
        idempotency_key="cancel-before-restart",
    )
    reopened = PreparationStore(store.database_path, clock=lambda: NOW)
    assert reopened.get(running.preparation_id) == pending
    assert pending.items[0] == running.items[0]
    with pytest.raises(JobAdmissionError):
        jobs.submit(request("VERIFY"), "restart-still-occupied")
    for generation, confirmed in (("wrong-generation", True), (claim.generation, False)):
        with pytest.raises(PreparationConflictError):
            reopened.recover_unknown(
                running.preparation_id, generation=generation, expected_revision=pending.revision,
                confirmed_ended=confirmed, idempotency_key="reject-cancel-recovery",
            )
    ended = reopened.recover_unknown(
        running.preparation_id, generation=claim.generation, expected_revision=pending.revision,
        confirmed_ended=True, idempotency_key="recover-cancelled-successor",
    )
    assert ended.status == ended.items[1].status == "CANCELLED"
    assert ended.items[0] == running.items[0]
    assert ended.items[1].base_hash == running.items[1].base_hash
    assert ended.items[1].attempts[-1].base_hash == running.items[1].base_hash
    assert ended.items[1].attempts[-1].status == "CANCELLED"
    assert ended.items[1].candidate is None and not ended.items[2].attempts
    assert ended.work_claim.phase == "ENDED"
    with pytest.raises(PreparationConflictError):
        reopened.finish_attempt(
            running.preparation_id, attempt_id=claim.generation, expected_revision=ended.revision,
            idempotency_key="stale-after-recovery", candidate=candidate(),
            worker_owner_id=claim.owner_id,
        )
    reservation = jobs.get_run_submission_reservation(claim.intent_json, claim.admission_key)
    assert jobs.release_run_submission(reservation)
    cleaned = reopened.clear_work_claim(
        running.preparation_id, generation=claim.generation, expected_revision=ended.revision,
    )
    assert cleaned.items == ended.items and cleaned.work_claim is None
    assert jobs.submit(request("VERIFY"), "after-restart-recovery").job_id
