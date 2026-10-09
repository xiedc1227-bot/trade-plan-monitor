"""Native frozen worker dispatch has no provider/configuration or live authority."""

import asyncio
import sqlite3
from threading import Event, get_ident
from time import monotonic

import pytest
from tests.integration.test_monitor_loop_publication import publication_case

from trade_plan_monitor.backtest.application import create_backtest_job_operations
from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.jobs.coordinator import BacktestJobCoordinator
from trade_plan_monitor.backtest.jobs.models import BacktestJobStatus, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.market_store import BacktestMarketStore


def worker_case(tmp_path):
    store, reference, _, _ = publication_case(tmp_path)
    market = BacktestMarketStore(tmp_path / "loop-market.sqlite3")
    with sqlite3.connect(market.database_path) as connection:
        connection.execute("DELETE FROM market_minute_head")
        connection.execute("DELETE FROM market_head")
        connection.execute("DELETE FROM market_minute_artifact")
        connection.execute("DELETE FROM market_artifact")
    operations = create_backtest_job_operations(
        config_path=tmp_path / "nonexistent.yaml",
        market_store=market,
        result_store=store,
    )
    repository = BacktestJobRepository(store.database_path)
    receipt = repository.submit(MonitorLoopJobRequest(input_reference=reference), "run")
    return store, reference, operations, repository, receipt


def test_native_dispatch_runs_copied_facts_without_original_market_or_config(tmp_path):
    store, reference, operations, repository, receipt = worker_case(tmp_path)
    claim = repository.claim_next()
    progress = []
    result = operations.execute(
        claim, cancellation_token=CancellationToken(), progress_callback=progress.append
    )
    assert result.run_id == reference.run_id and not result.reused
    assert store.get_run(reference.run_id) is None
    assert repository.complete(claim.job_id, claim.claim_token.get_secret_value(), result)
    report = store.get_loop_report(reference.run_id)
    assert report.cycle.fills == 1
    assert report.boundary == store.get_loop_input(reference).run_input.boundary
    assert progress[-1].phase == "RUN_REPORT_HANDOFF"
    assert not tuple(tmp_path.glob(".loop-worker-*"))


def test_cancelled_native_dispatch_never_publishes_partial_result(tmp_path):
    store, reference, operations, repository, _ = worker_case(tmp_path)
    token = CancellationToken()
    token.cancel()
    claim = repository.claim_next()
    with pytest.raises(BacktestOperationCancelled):
        operations.execute(claim, cancellation_token=token, progress_callback=lambda _: None)
    assert store.get_run(reference.run_id) is None
    assert not tuple(tmp_path.glob(".loop-worker-*"))


@pytest.mark.parametrize("field", ["run_id", "dataset_hash"])
def test_claim_identity_mismatch_is_rejected_before_native_execution(tmp_path, field):
    store, reference, operations, repository, _ = worker_case(tmp_path)
    claim = repository.claim_next().model_copy(update={field: "f" * 64})
    with pytest.raises(ValueError, match="claim"):
        operations.execute(
            claim, cancellation_token=CancellationToken(), progress_callback=lambda _: None
        )
    assert store.get_run(reference.run_id, include_unmaterialized=True) is None
    assert not tuple(tmp_path.glob(".loop-worker-*"))


def test_cancel_during_frames_drains_private_files_without_staging_a_completed_report(tmp_path):
    store, reference, operations, repository, _ = worker_case(tmp_path)
    token = CancellationToken()

    def cancel(progress):
        if progress.completed_units >= 3:
            token.cancel()

    with pytest.raises(BacktestOperationCancelled):
        operations.execute(
            repository.claim_next(), cancellation_token=token, progress_callback=cancel
        )
    assert store.get_run(reference.run_id, include_unmaterialized=True) is None
    assert not tuple(tmp_path.glob(".loop-worker-*"))
    with pytest.raises(JobAdmissionError, match="unfinished"):
        repository.claim_run_submission('{"other":"work"}', "other")


def test_identical_frozen_worker_replay_preserves_report_bytes_and_verified_reuse(tmp_path):
    from trade_plan_monitor.backtest.canonical import canonical_json
    from trade_plan_monitor.backtest.loop_replay import run_frozen_loop

    store, reference, operations, repository, _ = worker_case(tmp_path)
    claim = repository.claim_next()
    first = operations.execute(
        claim, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    replayed = run_frozen_loop(
        store, reference, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert replayed.report_hash == first.report_hash
    assert repository.complete(claim.job_id, claim.claim_token.get_secret_value(), first)
    before = canonical_json(store.get_loop_report(reference.run_id))
    reused = operations.execute(
        claim, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert reused.reused and reused.report_hash == first.report_hash
    assert canonical_json(store.get_loop_report(reference.run_id)) == before


def test_dedicated_thread_requires_authorization_and_keeps_single_unfinished_slot(tmp_path):
    store, reference, operations, repository, receipt = worker_case(tmp_path)
    threads = []
    failures = []
    maintained = Event()
    maintenance_threads = []
    orphan = store.loop_input_store.root / ("day-" + "f" * 64 + ".json")
    orphan.write_bytes(b"synthetic interrupted copy")
    original = operations.execute

    def tracked(*args, **kwargs):
        threads.append(get_ident())
        try:
            return original(*args, **kwargs)
        except Exception as error:
            failures.append(repr(error))
            raise

    operations.execute = tracked
    original_cleanup = operations.after_completion

    def cleanup(*args, **kwargs):
        maintenance_threads.append(get_ident())
        try:
            return original_cleanup(*args, **kwargs)
        finally:
            maintained.set()

    operations.after_completion = cleanup

    async def exercise():
        owner = get_ident()
        coordinator = BacktestJobCoordinator(
            repository=repository,
            operations=operations,
            poll_interval_seconds=0.01,
            authorized_job_ids=frozenset(),
        )
        await coordinator.start()
        try:
            await asyncio.sleep(0.05)
            assert repository.get(receipt.job_id).status is BacktestJobStatus.QUEUED
            assert not threads
            with pytest.raises(JobAdmissionError, match="unfinished"):
                repository.claim_run_submission('{"different":"one"}', "second")
            coordinator.authorize_jobs(frozenset({receipt.job_id}))
            deadline = monotonic() + 15
            while (
                repository.get(receipt.job_id).status is not BacktestJobStatus.COMPLETED
                or not maintained.is_set()
            ):
                assert repository.get(receipt.job_id).status is not BacktestJobStatus.FAILED, (
                    failures
                )
                coordinator.raise_if_failed()
                assert monotonic() < deadline
                await asyncio.sleep(0.02)
        finally:
            await coordinator.shutdown()
        assert threads and threads[0] != owner
        assert coordinator.physically_drained
        assert maintenance_threads == threads
        assert not orphan.exists()
        assert store.get_loop_report(reference.run_id).cycle.fills == 1

    asyncio.run(exercise())
