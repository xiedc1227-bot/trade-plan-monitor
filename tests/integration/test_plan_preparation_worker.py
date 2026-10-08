"""Durable single-source extraction, physical drain and existing global admission."""

from uuid import uuid4

import pytest
from tests.integration.test_plan_preparation_store import candidate

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore


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
    from trade_plan_monitor.backtest.preparation_models import PreparationWorkClaim

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
    from trade_plan_monitor.backtest.preparation_models import PreparationRecord

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
