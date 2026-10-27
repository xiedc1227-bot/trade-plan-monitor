"""Fresh provider calls require current predecessor proofs at the writer boundary."""

import asyncio
import sqlite3
from contextlib import closing, contextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from tests.integration.test_plan_preparation_worker import collection_claim
from tests.integration.test_preparation_current_assurance import _case, _rows
from tests.integration.test_preparation_human_assurance import _finish_item
from tests.integration.test_source_coverage_preparation_commit import _NOW

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_current_assurance import read_current_assurance_prefix
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    PlanCollectionPreparationInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor, run_attempt

_UNKNOWN = "Everything else depends on the blue lantern."


@pytest.mark.parametrize("problem", ["unknown", "missing"])
def test_unstarted_coverage_failure_ends_cleanly_without_provider_call_retry_or_unknown(
    tmp_path, problem,
):
    jobs = BacktestJobRepository(tmp_path / "preflight-jobs.sqlite3", clock=lambda: _NOW)
    store, running = _started_successor(tmp_path, problem=problem, jobs=jobs)
    calls = []

    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    service = PreparationService(store, jobs,
        PreparationExtractor(call=provider, max_retries=2, max_repairs=2))

    async def scenario():
        try:
            await service._watch(running, CancellationToken())
        finally:
            await service.stop()

    asyncio.run(scenario())

    ended = store.get(running.preparation_id)
    assert calls == [] and ended.work_claim is None and ended.status == "FAILED"
    assert ended.items[0] == running.items[0]
    attempt, = ended.items[1].attempts
    assert attempt.status == "FAILED" and attempt.error_code == "SOURCE_COVERAGE_REQUIRED"
    assert not attempt.retryable and ended.items[1].candidate is None
    assert jobs.get_run_submission_reservation(
        running.work_claim.intent_json, running.work_claim.admission_key) is None


@pytest.mark.parametrize("kind", ["transient", "retryable_coverage", "success"])
def test_ready_phase_cannot_end_as_a_physical_result_or_retryable_preflight(tmp_path, kind):
    from trade_plan_monitor.backtest.preparation_models import PreparationCandidateInput

    store, running = _started_successor(tmp_path)
    values = dict(error_code="TRANSIENT" if kind == "transient" else "SOURCE_COVERAGE_REQUIRED",
                  retryable=kind == "retryable_coverage")
    if kind == "success":
        values = dict(candidate=PreparationCandidateInput(payload_json='{"synthetic":true}',
            validation="VALID", evidence_hash="f" * 64))
    before = _all_rows(store)
    with pytest.raises(PreparationConflictError) as error:
        store.finish_attempt(running.preparation_id,
            attempt_id=running.work_claim.generation, expected_revision=running.revision,
            idempotency_key="cannot-fabricate-physical-end",
            worker_owner_id=running.work_claim.owner_id, **values)
    assert error.value.code == "STALE_WORKER" and _all_rows(store) == before


def _started_successor(tmp_path, *, problem=None, independent=False, jobs=None):
    source, _, result, inputs = _case(extra=_UNKNOWN if problem == "unknown" else None)
    available = source.available_at + timedelta(days=1)
    next_source = PreparationSource(source_id="next-source", text="position.max_qty = 500",
        available_at=available, effective_trade_date=available.date())
    store = PreparationStore(tmp_path / "current-reuse.sqlite3", clock=lambda: _NOW)
    initial = store.create(PlanCollectionPreparationInput(preparation_id="current-reuse",
        sources=(source, next_source)), idempotency_key="create")
    ready = _finish_item(store, initial, 0, result, None if problem == "missing" else inputs)
    assert ready.items[0].candidate.validation == "VALID"
    assert ready.items[0].candidate.policy_ready
    if independent:
        # Existing server-owned independent item shape: no invented LINEAGE,
        # HUMAN_OPERATION, review receipt, or INPUT registration.
        ready = CollectionPreparationRecord.model_validate(ready.model_dump(mode="python") | {
            "items": (ready.items[0], ready.items[1].model_copy(update={"independent": True})),
        })
        with closing(sqlite3.connect(store.database_path)) as connection, connection:
            connection.execute("UPDATE backtest_preparation SET document_json=? "
                "WHERE preparation_id=?", (ready.model_dump_json(), ready.preparation_id))
    claim = collection_claim(ready, 1, generation=str(UUID(int=202))).model_copy(update={
        "claimed_at": _NOW,
        "base_hash": None if independent else ready.items[0].candidate.candidate_hash,
    })
    if jobs is not None:
        intent = canonical_json({"synthetic": "physical call only", "independent": independent})
        reservation = jobs.claim_run_submission(intent, "real-call-reservation")
        claim = claim.model_copy(update={
            "admission_key": reservation.idempotency_key, "intent_hash": reservation.intent_hash,
            "claimed_at": reservation.claimed_at, "intent_json": intent,
        })
    running = store.start_attempt(ready.preparation_id, expected_revision=ready.revision,
        idempotency_key="start-successor", work_claim=claim)
    assert running.work_claim.phase == "READY"
    assert running.items[1].attempts[-1].base_hash == (
        None if independent else ready.items[0].candidate.candidate_hash)
    return store, running


def _all_rows(store):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return _rows(connection)


def _trace_connections(monkeypatch, store):
    """Observe actual SQL without replacing proof readers or transaction behavior."""
    original, statements = store._connect, []

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(store, "_connect", traced)
    return statements


def _begin(store, record):
    return store.begin_call(record.preparation_id, generation=record.work_claim.generation,
        owner_id=record.work_claim.owner_id, expected_revision=record.revision)


@pytest.mark.parametrize("problem", ["unknown", "missing"])
def test_dependent_begin_rejects_old_valid_predecessor_without_current_complete_proof(
    tmp_path, monkeypatch, problem,
):
    store, running = _started_successor(tmp_path, problem=problem)
    with closing(sqlite3.connect(store.database_path)) as connection:
        if problem == "unknown":
            proofs = read_current_assurance_prefix(connection, running, 1)
            assert len(proofs) == 1 and proofs[0].status == "BLOCKED"
            assert any(row.excerpt == _UNKNOWN
                       for row in proofs[0].source_assessment.obligations)
        else:
            assert store.input_evidence(running.preparation_id,
                running.items[0].attempts[-1].attempt_id) is None
    before = _all_rows(store)
    statements = _trace_connections(monkeypatch, store)

    with pytest.raises(PreparationConflictError) as error:
        _begin(store, running)

    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"
    assert store.get(running.preparation_id) == running
    assert _all_rows(store) == before
    assert statements.count("BEGIN IMMEDIATE") == 1
    assert "ROLLBACK" in statements
    assert not any(sql.startswith(("INSERT INTO backtest_preparation ",
                                   "INSERT INTO backtest_preparation_idempotency"))
                   for sql in statements)


def test_complete_predecessor_is_recomputed_within_the_begin_call_writer_transaction(
    tmp_path, monkeypatch,
):
    store, running = _started_successor(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        proofs = read_current_assurance_prefix(connection, running, 1)
    assert len(proofs) == 1 and proofs[0].coverage_complete
    statements = _trace_connections(monkeypatch, store)

    calling = _begin(store, running)

    assert calling.work_claim.phase == "CALLING"
    assert calling.revision == running.revision + 1
    assert calling.items == running.items
    begin = statements.index("BEGIN IMMEDIATE")
    write = next(index for index, sql in enumerate(statements)
                 if sql.startswith("INSERT INTO backtest_preparation "))
    input_reads = [index for index, sql in enumerate(statements)
                   if " FROM backtest_preparation_assurance WHERE " in sql]
    assert input_reads and all(begin < index < write for index in input_reads)
    assert statements.count("BEGIN IMMEDIATE") == 1
    assert statements[-1] == "COMMIT"


def test_cancelled_ready_successor_cannot_acquire_a_provider_call_and_original_start_replays(
    tmp_path,
):
    store, running = _started_successor(tmp_path)
    cancelled = store.cancel(running.preparation_id, expected_revision=running.revision,
                             idempotency_key="cancel-before-call")
    before = _all_rows(store)

    with pytest.raises(PreparationConflictError) as error:
        _begin(store, cancelled)

    assert error.value.code == "STALE_WORKER"
    assert _all_rows(store) == before
    assert store.replay_start_attempt(running.preparation_id,
        expected_revision=running.revision - 1, idempotency_key="start-successor") == running


def test_retry_rechecks_the_current_predecessor_and_old_call_authority_cannot_replay(tmp_path):
    store, running = _started_successor(tmp_path)
    calling = _begin(store, running)
    failed = store.finish_attempt(running.preparation_id,
        attempt_id=calling.work_claim.generation, expected_revision=calling.revision,
        idempotency_key="failed-successor", error_code="TRANSIENT", retryable=True,
        worker_owner_id=calling.work_claim.owner_id)
    cleared = store.clear_work_claim(failed.preparation_id,
        generation=failed.work_claim.generation, expected_revision=failed.revision)
    retry_claim = collection_claim(cleared, 1, generation=str(UUID(int=203))).model_copy(update={
        "claimed_at": _NOW,
    })
    retry = store.start_attempt(cleared.preparation_id, expected_revision=cleared.revision,
        idempotency_key="retry-successor", work_claim=retry_claim)
    before = _all_rows(store)
    with pytest.raises(PreparationConflictError) as error:
        _begin(store, running)
    assert error.value.code == "REVISION_CONFLICT"
    assert _all_rows(store) == before
    retried = _begin(store, retry)
    assert retried.work_claim.phase == "CALLING"
    assert retried.work_claim.generation != calling.work_claim.generation
    assert len(retried.items[1].attempts) == 2
    assert retried.items[1].attempts[0].status == "FAILED"
    assert retried.items[1].attempts[-1].base_hash == running.items[0].candidate.candidate_hash


@pytest.mark.parametrize("problem", ["unknown", "missing"])
def test_independent_source_does_not_inherit_an_unproved_predecessor_policy(tmp_path, problem):
    jobs = BacktestJobRepository(tmp_path / "independent-jobs.sqlite3", clock=lambda: _NOW)
    store, running = _started_successor(tmp_path, problem=problem, independent=True, jobs=jobs)
    assert running.items[1].independent is True
    assert running.work_claim.base_hash is None
    assert running.items[1].base_hash is None
    if problem == "unknown":
        with closing(sqlite3.connect(store.database_path)) as connection:
            prefix = read_current_assurance_prefix(connection, running, 1)
        assert len(prefix) == 1 and prefix[0].status == "BLOCKED"
    else:
        assert store.input_evidence(running.preparation_id,
            running.items[0].attempts[-1].attempt_id) is None
    before = _all_rows(store)
    with pytest.raises(PreparationConflictError) as error:
        store.begin_call(running.preparation_id, generation=running.work_claim.generation,
            owner_id="not-the-current-owner", expected_revision=running.revision)
    assert error.value.code == "STALE_WORKER" and _all_rows(store) == before
    calls = []

    def extraction(identity, source, token, **kwargs):
        calls.append((identity, source, token, kwargs))
        return None  # Synthetic physical timeout; no provider or forged AI response.

    token = CancellationToken()
    outcome = run_attempt(store, jobs, running, PreparationExtractor(extraction), token)

    assert calls == [(UUID(running.work_claim.generation), running.items[1].source, token, {})]
    assert outcome.unknown is True and outcome.candidate is None and outcome.inputs is None
    current = store.get(running.preparation_id)
    assert current.work_claim.phase == "CALLING"
    assert current.work_claim.base_hash is None
    assert current.items[1].attempts[-1].base_hash is None
    assert current.items[0] == running.items[0]
    assert store.input_evidence(current.preparation_id, current.work_claim.generation) is None
