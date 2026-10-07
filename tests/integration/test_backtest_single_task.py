"""One unfinished operation excludes all new backtest work, even after lease expiry."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from tests.integration.test_backtest_jobs import _SHANGHAI, _Clock, _run_input, _scope

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.jobs import (
    BacktestJobRepository,
    BacktestJobStatus,
    BacktestRunJobRequest,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
    JobAdmissionError,
)


def request(kind, day=20):
    if kind == "RUN":
        return BacktestRunJobRequest(run_input=_run_input(str(day)))
    if kind == "SYNC":
        return DataSyncJobRequest(scope=_scope(day=day), refresh=False, allow_network=True)
    return DatasetVerifyJobRequest(scope=_scope(day=day))


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "EXPIRED"])
@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
def test_unfinished_task_rejects_every_new_mutually_exclusive_operation(tmp_path, state, kind):
    clock = _Clock(datetime(2026, 8, 28, 10, tzinfo=_SHANGHAI))
    store = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    first = store.submit(request("RUN"), "first")
    if state != "QUEUED":
        store.claim_next()
    if state == "CANCEL_REQUESTED":
        store.request_cancel(first.job_id, "cancel")
    if state == "EXPIRED":
        clock.advance(timedelta(seconds=31))
    with pytest.raises(JobAdmissionError) as blocked:
        store.submit(request(kind, 21), "second", request_id="1" * 32)
    assert blocked.value.code == "BACKTEST_BUSY"
    assert len(store.list_jobs()) == 1
    assert store.submit(request("RUN"), "first").job_id == first.job_id


def test_concurrent_different_submissions_admit_only_one(tmp_path):
    store = BacktestJobRepository(
        tmp_path / "race.sqlite3", clock=lambda: datetime(2026, 8, 28, 10, tzinfo=_SHANGHAI)
    )
    barrier = Barrier(8)

    def submit(day):
        barrier.wait()
        try:
            return store.submit(request("VERIFY", day), f"request-{day}").job_id
        except JobAdmissionError as error:
            assert error.code == "BACKTEST_BUSY"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(submit, range(8)))
    assert len([value for value in outcomes if value is not None]) == 1
    assert len(store.list_jobs()) == 1


@pytest.mark.parametrize("expired", [False, True])
def test_pending_run_snapshot_reservation_also_excludes_new_work(tmp_path, expired):
    clock = _Clock(datetime(2026, 8, 28, 10, tzinfo=_SHANGHAI))
    store = BacktestJobRepository(tmp_path / "reservation.sqlite3", clock=clock)
    intent = canonical_json({"planVersionId": "reviewed-one"})
    reservation = store.claim_run_submission(intent, "first")
    assert reservation is not None
    if expired:
        clock.advance(timedelta(seconds=31))
    with pytest.raises(JobAdmissionError) as blocked:
        store.submit(request("VERIFY"), "verify")
    assert blocked.value.code == "BACKTEST_BUSY"
    with pytest.raises(JobAdmissionError):
        store.claim_run_submission(canonical_json({"planVersionId": "other"}), "second")
    assert store.release_run_submission(reservation)
    assert store.submit(request("VERIFY"), "verify").status == BacktestJobStatus.QUEUED


def test_terminal_task_releases_admission_and_cancel_request_does_not(tmp_path):
    store = BacktestJobRepository(tmp_path / "terminal.sqlite3")
    first = store.submit(request("VERIFY"), "first")
    claim = store.claim_next()
    store.request_cancel(first.job_id, "cancel")
    with pytest.raises(JobAdmissionError):
        store.submit(request("SYNC"), "next", request_id="2" * 32)
    assert store.acknowledge_cancel(claim.job_id, claim.claim_token.get_secret_value())
    assert store.submit(request("SYNC"), "next", request_id="2" * 32).job_id != first.job_id
