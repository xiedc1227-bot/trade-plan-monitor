"""Actual prepared authority stays locked through the jobs admission transaction."""

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.integration.test_backtest_jobs import _scope
from tests.integration.test_monitor_loop_input_store import NOW, frozen_case

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.jobs.models import DatasetVerifyJobRequest, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import (
    BacktestJobRepository,
    BacktestJobSubmissionBinding,
    BacktestRunSubmissionReservation,
    JobAdmissionError,
)
from trade_plan_monitor.backtest.preparation_run_fence import current_prepared_run_fence
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.results import BacktestResultStore


def _case(tmp_path):
    preparation, market, prepared, run_input, dataset = frozen_case(tmp_path)
    repository = BacktestJobRepository(tmp_path / "guard-jobs.sqlite3", clock=lambda: NOW)
    results = BacktestResultStore(repository.database_path)
    reference = results.record_loop_input(prepared=prepared, run_input=run_input, dataset=dataset,
                                          market_source=market)
    record = preparation.get(prepared.preparation_id)
    return SimpleNamespace(preparation=preparation, prepared=prepared, repository=repository,
        request=MonitorLoopJobRequest(input_reference=reference), results=results,
        reference=reference, record=record,
        intent=canonical_json({"preparationId": prepared.preparation_id,
                               "manifestHash": prepared.manifest_hash}))


def _reservation(case, key="guard-finalize"):
    reservation = case.repository.claim_run_submission(case.intent, key)
    assert isinstance(reservation, BacktestRunSubmissionReservation)
    return reservation


def _rows(case):
    with closing(sqlite3.connect(case.repository.database_path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("backtest_job", "backtest_job_idempotency", "backtest_job_state",
                              "backtest_run_input")}


def _trace(monkeypatch, repository, events):
    original = repository._connect

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(lambda sql: events.append("JOBS:" + sql))
            yield connection

    monkeypatch.setattr(repository, "_connect", traced)


def _guard(case, events, *, failure=None, locked_probe=None):
    @contextmanager
    def enter():
        events.append("GUARD_FACTORY")
        try:
            with current_prepared_run_fence(case.preparation, case.prepared.preparation_id,
                                            case.prepared.manifest_hash) as current:
                events.append("GUARD_ENTER")
                try:
                    if locked_probe is not None:
                        locked_probe()
                    if failure is not None:
                        raise failure
                    yield current
                finally:
                    events.append("GUARD_EXIT_LOCKED")
                    if locked_probe is not None:
                        locked_probe()
        finally:
            events.append("GUARD_RELEASED")

    return enter


def _edit_source(case, *, store=None):
    return (case.preparation if store is None else store).edit_source(
        case.record.preparation_id, expected_revision=case.record.revision,
        source=case.record.source.model_copy(update={"text": "A newly clarified source."}),
        idempotency_key="source-edit-after-freeze")


def _private_submit(case, key, guard, *, on_admitted=None):
    return case.repository._submit(case.request, key, request_id=None, reservation=None,
        on_admitted=on_admitted, admission_guard=guard)


def test_frozen_case_has_a_real_current_review_and_an_immutable_stored_loop_input(tmp_path):
    case = _case(tmp_path)
    with current_prepared_run_fence(case.preparation, case.prepared.preparation_id,
                                    case.prepared.manifest_hash) as current:
        assert current == case.prepared
    assert case.results.get_loop_input(case.reference).prepared == case.prepared


def test_finalization_enters_after_reservation_check_and_holds_source_through_jobs_commit(
    tmp_path, monkeypatch,
):
    case, events = _case(tmp_path), []
    reservation = _reservation(case)
    other = PreparationStore(case.preparation.database_path, busy_timeout_ms=30)
    probes = []

    def source_stays_locked():
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _edit_source(case, store=other)
        probes.append(True)

    _trace(monkeypatch, case.repository, events)
    receipt = case.repository.finalize_run_submission(case.request, reservation,
        admission_guard=_guard(case, events, locked_probe=source_stays_locked),
        on_admitted=lambda job_id: events.append("ADMITTED:" + job_id))

    assert receipt.job_id and probes == [True, True]
    assert events.index("JOBS:BEGIN IMMEDIATE") < events.index("GUARD_FACTORY")
    assert any("FROM backtest_job_idempotency WHERE idempotency_key" in sql
               for sql in events[:events.index("GUARD_FACTORY")])
    assert events.index("GUARD_ENTER") < next(index for index, sql in enumerate(events)
        if "WHERE operation_hash =" in sql)
    assert events.index("JOBS:COMMIT") < events.index("ADMITTED:" + receipt.job_id)
    assert events.index("JOBS:COMMIT") < events.index("GUARD_EXIT_LOCKED")
    assert _edit_source(case, store=other).review is None


def test_a_new_key_reusing_an_active_job_still_enters_guard_before_binding_its_response(
    tmp_path, monkeypatch,
):
    case, events, callbacks = _case(tmp_path), [], []
    original = case.repository.submit(case.request, "active-original")
    _trace(monkeypatch, case.repository, events)

    reused = _private_submit(case, "active-new-key", _guard(case, events),
                             on_admitted=callbacks.append)

    assert reused == original and len(case.repository.list_jobs()) == 1
    assert events.count("GUARD_ENTER") == events.count("GUARD_RELEASED") == 1
    assert events.index("GUARD_ENTER") < next(index for index, sql in enumerate(events)
        if "WHERE operation_hash =" in sql)
    assert events.index("JOBS:COMMIT") < events.index("GUARD_EXIT_LOCKED")
    assert callbacks == []
    assert case.repository.get_submission_binding("active-new-key").receipt == original


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("failure", [PreparationConflictError("SOURCE_COVERAGE_REQUIRED"),
                                      RuntimeError("Synthetic guard failure")])
def test_guard_rejection_rolls_back_all_jobs_rows_and_never_calls_postcommit(
    tmp_path, active, failure,
):
    case, events, callbacks = _case(tmp_path), [], []
    if active:
        case.repository.submit(case.request, "active-original")
        reservation = None
    else:
        reservation = _reservation(case)
    before = _rows(case)
    with pytest.raises(type(failure), match=str(failure)):
        if reservation is None:
            _private_submit(case, "denied-active-key", _guard(case, events, failure=failure),
                            on_admitted=callbacks.append)
        else:
            case.repository.finalize_run_submission(case.request, reservation,
                admission_guard=_guard(case, events, failure=failure),
                on_admitted=callbacks.append)
    assert events.count("GUARD_ENTER") == events.count("GUARD_RELEASED") == 1
    assert _rows(case) == before and callbacks == []


def test_internal_job_write_failure_rolls_back_before_releasing_source_guard(tmp_path, monkeypatch):
    case, events, callbacks = _case(tmp_path), [], []
    reservation = _reservation(case)
    with closing(sqlite3.connect(case.repository.database_path)) as connection, connection:
        connection.execute("CREATE TRIGGER guard_test_fail_job BEFORE INSERT ON backtest_job "
                           "BEGIN SELECT RAISE(ABORT, 'Synthetic job insert failure'); END")
    before = _rows(case)
    _trace(monkeypatch, case.repository, events)

    with pytest.raises(sqlite3.IntegrityError, match="Synthetic job insert failure"):
        case.repository.finalize_run_submission(case.request, reservation,
            admission_guard=_guard(case, events), on_admitted=callbacks.append)

    assert events.index("JOBS:ROLLBACK") < events.index("GUARD_EXIT_LOCKED")
    assert _rows(case) == before and callbacks == []
    assert _edit_source(case).review is None  # Both writer locks have been released.


def test_source_changed_after_freezing_cannot_finalize_but_immutable_input_survives(tmp_path):
    case, events, callbacks = _case(tmp_path), [], []
    reservation = _reservation(case)
    _edit_source(case)
    before = _rows(case)

    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
        case.repository.finalize_run_submission(case.request, reservation,
            admission_guard=_guard(case, events), on_admitted=callbacks.append)

    assert _rows(case) == before and callbacks == []
    assert case.results.get_loop_input(case.reference).prepared == case.prepared


def test_completed_binding_replays_history_without_reentering_fresh_source_authority(tmp_path):
    case, events = _case(tmp_path), []
    reservation = _reservation(case)
    receipt = case.repository.finalize_run_submission(case.request, reservation,
        admission_guard=_guard(case, events))
    _edit_source(case)
    before = _rows(case)
    replay = case.repository.claim_run_submission(case.intent, reservation.idempotency_key)
    assert isinstance(replay, BacktestJobSubmissionBinding) and replay.receipt == receipt
    assert events.count("GUARD_ENTER") == 1 and _rows(case) == before
    with pytest.raises(JobAdmissionError, match="Idempotency key"):
        case.repository.finalize_run_submission(case.request, reservation,
            admission_guard=_guard(case, events))
    assert events.count("GUARD_ENTER") == 1


def test_existing_unreserved_submit_receipt_returns_before_a_private_guard(tmp_path):
    case, events, callbacks = _case(tmp_path), [], []
    receipt = case.repository.submit(case.request, "ordinary-original")
    _edit_source(case)
    before = _rows(case)
    assert _private_submit(case, "ordinary-original", _guard(case, events),
                           on_admitted=callbacks.append) == receipt
    assert events == callbacks == [] and _rows(case) == before


def test_wrong_reservation_never_enters_the_guard_or_changes_rows(tmp_path):
    case, events, callbacks = _case(tmp_path), [], []
    reservation = replace(_reservation(case), intent_hash="f" * 64)
    before = _rows(case)
    with pytest.raises(JobAdmissionError):
        case.repository.finalize_run_submission(case.request, reservation,
            admission_guard=_guard(case, events), on_admitted=callbacks.append)
    assert events == callbacks == [] and _rows(case) == before


@pytest.mark.parametrize("invalid", [False, 3, object()])
def test_noncallable_guard_is_rejected_without_consuming_the_real_reservation(tmp_path, invalid):
    case = _case(tmp_path)
    reservation, before = _reservation(case), _rows(case)
    with pytest.raises(TypeError):
        case.repository.finalize_run_submission(case.request, reservation, admission_guard=invalid)
    assert _rows(case) == before


def test_nonprepared_ordinary_submit_keeps_its_existing_contract(tmp_path):
    repository = BacktestJobRepository(tmp_path / "ordinary.sqlite3", clock=lambda: NOW)
    request = DatasetVerifyJobRequest(scope=_scope())
    receipt = repository.submit(request, "ordinary")
    assert repository.submit(request, "ordinary") == receipt
    assert len(repository.list_jobs()) == 1
