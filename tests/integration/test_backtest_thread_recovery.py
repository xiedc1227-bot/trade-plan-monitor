"""ML-T33: explicit queue authority and non-cooperative work ownership."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier, Event
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest import composition as composition_module
from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestJobCoordinator,
    BacktestJobRepository,
    BacktestJobStatus,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.jobs.models import BacktestDataSyncJobResult, BacktestJobPhase
from trade_plan_monitor.backtest.service_contract import BacktestServiceState
from trade_plan_monitor.backtest.service_lifecycle import LazyBacktestLifecycle
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.web.backtest_schemas import BacktestDatasetVerificationCommand
from trade_plan_monitor.web.schemas import MutationContext


def request():
    return DataSyncJobRequest(scope=BacktestDatasetScopeRequest(
        symbols=("600000.SH",), start=date(2026, 8, 24), end=date(2026, 8, 24),
        warmup_start=date(2026, 8, 24),
        historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        adjustment_policy="NONE",
    ), refresh=False, allow_network=True)


class Operations:
    def __init__(self):
        self.entered = Event()
        self.release = Event()

    def execute(self, claim, *, cancellation_token, progress_callback):
        self.entered.set()
        assert self.release.wait(2)
        cancellation_token.raise_if_cancelled("SYNC_CALENDAR")
        raise RuntimeError("controlled job failure")


def test_scoped_claim_leaves_old_queue_dormant_and_selected_resume_is_explicit(tmp_path):
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    old = repository.submit(request(), "old", request_id="1" * 32)
    assert repository.claim_next(authorized_job_ids=frozenset()) is None
    assert repository.get(old.job_id).status is BacktestJobStatus.QUEUED
    selected = repository.claim_next(authorized_job_ids=frozenset({old.job_id}))
    assert selected.job_id == old.job_id


def test_new_admission_authorizes_only_new_job_not_deduplicated_backlog(tmp_path):
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    old = repository.submit(request(), "old", request_id="1" * 32)
    authorized = []
    replay = repository.submit(
        request(), "new-key-same-operation", request_id="2" * 32,
        on_admitted=authorized.append,
    )
    assert replay.job_id == old.job_id
    assert authorized == []
    repository.request_cancel(old.job_id, "cancel-old")
    new = repository.submit(
        request(), "new-operation", request_id="3" * 32, on_admitted=authorized.append,
    )
    assert authorized == [new.job_id]


def test_unselected_expired_claim_is_untouched_and_old_completion_cannot_publish(tmp_path):
    now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=lambda: now)
    job = repository.submit(request(), "old-claim", request_id="1" * 32)
    old_claim = repository.claim_next()
    before = repository.get(job.job_id)
    now += timedelta(seconds=31)
    assert repository.recover_expired(authorized_job_ids=frozenset()) is None
    unselected = frozenset({"00000000-0000-0000-0000-000000000000"})
    assert repository.recover_expired(authorized_job_ids=unselected) is None
    assert repository.get(job.job_id) == before
    renewed = repository.recover_expired(authorized_job_ids=frozenset({job.job_id}))
    assert renewed.attempt == 2
    assert renewed.claim_token != old_claim.claim_token
    assert not repository.heartbeat(job.job_id, old_claim.claim_token.get_secret_value())


@pytest.mark.parametrize("cancelled", (False, True))
def test_expired_history_releases_slot_without_mutation_and_resume_waits_for_live_lease(
    tmp_path, cancelled,
):
    now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=lambda: now)
    old = repository.submit(request(), "old", request_id="1" * 32)
    old_claim = repository.claim_next()
    if cancelled:
        repository.request_cancel(old.job_id, "cancel-old")
    before = repository.get(old.job_id)
    new = repository.submit(
        DatasetVerifyJobRequest(scope=request().scope), "new", request_id="2" * 32,
    )
    assert repository.claim_next(authorized_job_ids=frozenset({new.job_id})) is None
    now += timedelta(seconds=30)
    assert repository.recover_expired(authorized_job_ids=frozenset({new.job_id})) is None
    new_claim = repository.claim_next(authorized_job_ids=frozenset({new.job_id}))
    assert new_claim.job_id == new.job_id
    assert repository.get(old.job_id) == before
    assert repository.recover_expired(authorized_job_ids=frozenset({old.job_id})) is None
    old_token = old_claim.claim_token.get_secret_value()
    assert not repository.heartbeat(old.job_id, old_token)
    assert not repository.update_progress(
        old.job_id, old_token, phase=BacktestJobPhase.SYNCING_DATA, completed_units=1,
    )
    assert not repository.complete(old.job_id, old_token, BacktestDataSyncJobResult(
        calendar_rows=0, minute_days=0, daily_limit_rows=0, daily_bar_rows=0, network_calls=0,
    ))
    assert repository.fail(new.job_id, new_claim.claim_token.get_secret_value(), "TEST", "Test.")
    resumed = repository.recover_expired(authorized_job_ids=frozenset({old.job_id}))
    if cancelled:
        assert resumed is None
        assert repository.get(old.job_id).status is BacktestJobStatus.CANCELLED
    else:
        assert resumed.job_id == old.job_id
        assert resumed.attempt == 2
        assert resumed.claim_token != old_claim.claim_token


def test_multiple_dormant_claims_do_not_starve_selected_recovery(tmp_path):
    now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=lambda: now)
    old = repository.submit(request(), "old", request_id="1" * 32)
    repository.claim_next()
    now += timedelta(seconds=31)
    selected = repository.submit(
        DatasetVerifyJobRequest(scope=request().scope), "selected", request_id="2" * 32,
    )
    repository.claim_next(authorized_job_ids=frozenset({selected.job_id}))
    now += timedelta(seconds=31)
    before = repository.get(old.job_id)
    selected_before = repository.get(selected.job_id)
    fresh = repository.submit(
        request().model_copy(update={"refresh": True}), "fresh", request_id="3" * 32,
    )
    fresh_claim = repository.claim_next(authorized_job_ids=frozenset({fresh.job_id}))
    assert fresh_claim.job_id == fresh.job_id
    assert repository.recover_expired(authorized_job_ids=frozenset({selected.job_id})) is None
    assert repository.get(old.job_id) == before
    assert repository.get(selected.job_id) == selected_before
    assert repository.fail(
        fresh.job_id, fresh_claim.claim_token.get_secret_value(), "TEST", "Test.",
    )
    recovered = repository.recover_expired(authorized_job_ids=frozenset({selected.job_id}))
    assert recovered.job_id == selected.job_id
    assert recovered.attempt == 2
    assert repository.get(old.job_id) == before
    assert repository.recover_expired(authorized_job_ids=frozenset({old.job_id})) is None


def test_new_claim_and_selected_recovery_race_admit_only_one_lease(tmp_path):
    now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    path = tmp_path / "jobs.sqlite3"
    repository = BacktestJobRepository(path, clock=lambda: now)
    other = BacktestJobRepository(path, clock=lambda: now)
    old = repository.submit(request(), "old", request_id="1" * 32)
    repository.claim_next()
    now += timedelta(seconds=31)
    fresh = repository.submit(
        DatasetVerifyJobRequest(scope=request().scope), "fresh", request_id="2" * 32,
    )
    barrier = Barrier(2)

    def claim_new():
        barrier.wait()
        return repository.claim_next(authorized_job_ids=frozenset({fresh.job_id}))

    def resume_old():
        barrier.wait()
        return other.recover_expired(authorized_job_ids=frozenset({old.job_id}))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(claim_new), executor.submit(resume_old))
        claims = [future.result() for future in futures]
    assert sum(claim is not None for claim in claims) == 1
    assert repository.claim_next(authorized_job_ids=frozenset({fresh.job_id})) is None
    assert other.recover_expired(authorized_job_ids=frozenset({old.job_id})) is None


def test_unknown_lease_blocks_claim_and_recovery(tmp_path):
    now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    repository = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=lambda: now)
    old = repository.submit(request(), "old", request_id="1" * 32)
    repository.claim_next()
    new = repository.submit(
        DatasetVerifyJobRequest(scope=request().scope), "new", request_id="2" * 32,
    )
    # Model a damaged legacy store; the production schema normally rejects NULL.
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("UPDATE backtest_job SET lease_expires_at = NULL WHERE job_id = ?",
                           (old.job_id,))
    now += timedelta(seconds=31)
    assert repository.claim_next(authorized_job_ids=frozenset({new.job_id})) is None
    assert repository.recover_expired(authorized_job_ids=frozenset({old.job_id})) is None


def test_expired_physical_worker_still_blocks_next_job_in_same_coordinator(tmp_path):
    async def scenario():
        now = datetime(2026, 8, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
        repository = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=lambda: now)
        first = repository.submit(request(), "first", request_id="1" * 32)
        second = repository.submit(
            DatasetVerifyJobRequest(scope=request().scope), "second", request_id="2" * 32,
        )
        entered = Event()
        release = Event()
        calls = []

        class HeldOperations:
            def execute(self, claim, *, cancellation_token, progress_callback):
                calls.append(claim.job_id)
                if claim.job_id == first.job_id:
                    entered.set()
                    assert release.wait(3)
                raise RuntimeError("controlled failure")

        coordinator = BacktestJobCoordinator(
            repository=repository, operations=HeldOperations(),
            authorized_job_ids=frozenset({first.job_id, second.job_id}),
            poll_interval_seconds=0.01, heartbeat_interval_seconds=0.01,
        )
        await coordinator.start()
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            now += timedelta(seconds=31)
            await asyncio.sleep(0.06)
            assert not coordinator.physically_drained
            assert calls == [first.job_id]
            assert repository.get(second.job_id).status is BacktestJobStatus.QUEUED
            release.set()
            async with asyncio.timeout(2):
                while repository.get(second.job_id).status is not BacktestJobStatus.FAILED:
                    await asyncio.sleep(0.005)
            assert calls == [first.job_id, second.job_id]
            assert repository.get(first.job_id).status is BacktestJobStatus.RUNNING
        finally:
            release.set()
            await coordinator.shutdown()

    asyncio.run(scenario())


def test_timeout_does_not_release_executor_or_publish_late_worker_result(tmp_path):
    async def scenario():
        repository = BacktestJobRepository(tmp_path / "jobs.sqlite3")
        job = repository.submit(request(), "work", request_id="1" * 32)
        operations = Operations()
        coordinator = BacktestJobCoordinator(
            repository=repository, operations=operations, authorized_job_ids=frozenset(),
            poll_interval_seconds=0.01, shutdown_timeout_seconds=0.02,
        )
        await coordinator.start()
        await asyncio.sleep(0.02)
        assert not operations.entered.is_set()
        coordinator.authorize_jobs(frozenset({job.job_id}))
        try:
            while not operations.entered.is_set():
                await asyncio.sleep(0.001)
            repository.request_cancel(job.job_id, "cancel-work")
            with pytest.raises(RuntimeError, match="shutdown safe boundary"):
                await coordinator.shutdown()
            assert not coordinator.physically_drained
            assert repository.get(job.job_id).status is BacktestJobStatus.CANCEL_REQUESTED
            operations.release.set()
            await coordinator.shutdown()
            assert coordinator.physically_drained
            assert repository.get(job.job_id).status is BacktestJobStatus.CANCELLED
        finally:
            operations.release.set()
            await coordinator.shutdown()

    asyncio.run(scenario())


def test_production_history_and_readiness_leave_backlog_dormant_until_selected(
    tmp_path, monkeypatch,
):
    operations = Operations()
    operations.release.set()
    monkeypatch.setattr(
        composition_module, "create_backtest_job_operations", lambda **_: operations,
    )
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml", plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3", results_database=tmp_path / "jobs.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )
    command = BacktestDatasetVerificationCommand.model_validate({"scope": {
        "symbols": ["600000.SH"], "start": "2026-08-24", "end": "2026-08-24",
        "warmupStart": "2026-08-24", "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }})

    async def wait_terminal(repository, job_id):
        async with asyncio.timeout(2):
            while repository.get(job_id).status is not BacktestJobStatus.FAILED:
                await asyncio.sleep(0.005)

    async def scenario():
        manager = LazyBacktestLifecycle(factory)
        composition = await manager.ensure()
        repository = composition.operation_service._repository
        old = repository.submit(request(), "backlog", request_id="1" * 32)
        await composition.read_service.get_job(job_id=old.job_id)
        assert manager.snapshot.state is BacktestServiceState.READ_READY
        assert not operations.entered.is_set()
        await manager.ensure(execution=True)
        await asyncio.sleep(0.03)
        assert repository.get(old.job_id).status is BacktestJobStatus.QUEUED
        receipt = await composition.operation_service.submit_dataset_verification(
            command=command, context=MutationContext(idempotency_key="new", request_id="2" * 32),
        )
        await wait_terminal(repository, receipt.receipt.job_id)
        assert repository.get(old.job_id).status is BacktestJobStatus.QUEUED
        assert manager.snapshot.state is BacktestServiceState.READY
        await manager.stop()
        restarted = LazyBacktestLifecycle(factory)
        await restarted.ensure()
        assert repository.get(old.job_id).status is BacktestJobStatus.QUEUED
        await restarted.resume_jobs(frozenset({old.job_id}))
        await wait_terminal(repository, old.job_id)
        await restarted.stop()

    asyncio.run(scenario())
