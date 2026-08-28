"""Single-thread backtest coordinator and blocking-operation coverage."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from inspect import getsource
from pathlib import Path
from threading import Event, get_ident
from time import monotonic
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest import application as backtest_application
from trade_plan_monitor.backtest.application import BacktestApplicationService
from trade_plan_monitor.backtest.control import (
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import (
    BacktestDatasetCoverage,
    DatasetManifest,
    DatasetScope,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
    BacktestJobCoordinator,
    BacktestJobOperations,
    BacktestJobRepository,
    BacktestJobStatus,
    BacktestRunJobRequest,
    BacktestRunJobResult,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.results import (
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.sync import BlockingBacktestSyncCore
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.models import TradingDay

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRADE_DATE = date(2026, 8, 24)
_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _scope_request() -> BacktestDatasetScopeRequest:
    return BacktestDatasetScopeRequest(
        symbols=("600000.SH",),
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        warmup_start=_TRADE_DATE,
        historical_profile=_PROFILE,
        adjustment_policy="NONE",
    )


def _sync_request() -> DataSyncJobRequest:
    return DataSyncJobRequest(scope=_scope_request(), refresh=False, allow_network=True)


def _run_input() -> BacktestRunInput:
    plan = load_plan_yaml(_PLAN_PATH.read_text(encoding="utf-8"))
    manifest = DatasetManifest(
        dataset_hash=_hash("coordinator-dataset"),
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=_TRADE_DATE,
            end=_TRADE_DATE,
            warmup_start=_TRADE_DATE,
            historical_profile=_PROFILE,
        ),
        items=(),
    )
    return BacktestRunInput.create(
        plan=plan,
        manifest=manifest,
        initial_cash_fen=10_000_000,
        initial_lots=(),
        execution_config=ExecutionConfig(
            commission_rate=Decimal("0.0003"),
            minimum_commission_fen=500,
            stamp_duty_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            buy_slippage_bps=Decimal("2"),
            sell_slippage_bps=Decimal("2"),
        ),
        manual_event_risk=False,
    )


def _stage_empty_run(
    store: BacktestResultStore,
    run_input: BacktestRunInput,
    *,
    retention_at: datetime | None = None,
) -> str:
    report_hash = _hash(f"report:{run_input.run_id}")
    summary = BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 28, 15, 0, tzinfo=_SHANGHAI),
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={
            "dailyEquityCount": 0,
            "decisionCount": 0,
            "detailCount": 0,
            "fillCount": 0,
            "outcomeCount": 0,
            "signalCount": 0,
        },
        assumptions={
            "executionConfigHash": run_input.execution_config.config_hash,
            "manualEventRisk": run_input.manual_event_risk,
            "reportHash": report_hash,
        },
        formula_versions={
            "execution": run_input.execution_config.formula_version,
            "indicator": run_input.indicator_formula_version,
            "runner": run_input.run_formula_version,
        },
        final_metrics={},
    )
    assert (
        store.record_verified_run(
            summary,
            run_input=run_input,
            retention_at=retention_at,
        )
        is True
    )
    return report_hash


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("condition was not met before the deadline")
        await asyncio.sleep(0.005)


class _RecordingRepository:
    def __init__(self, repository: BacktestJobRepository) -> None:
        self._repository = repository
        self.heartbeat_times: list[float] = []

    def heartbeat(self, job_id: str, claim_token: str) -> bool:
        self.heartbeat_times.append(monotonic())
        return self._repository.heartbeat(job_id, claim_token)

    def __getattr__(self, name: str):
        return getattr(self._repository, name)


class _BlockingOperations:
    def __init__(self, *, stop_on_cancel: bool = False) -> None:
        self.started = Event()
        self.release = Event()
        self.cancel_seen = Event()
        self.stop_on_cancel = stop_on_cancel
        self.thread_ids: list[int] = []

    def execute(self, _claim, *, cancellation_token, progress_callback):
        self.thread_ids.append(get_ident())
        self.started.set()
        progress_callback(
            BacktestProgress(
                phase="SYNC_CALENDAR",
                completed_units=1,
                total_units=2,
            )
        )
        progress_callback(
            BacktestProgress(
                phase="SYNC_CALENDAR",
                completed_units=2,
                total_units=2,
            )
        )
        while not self.release.wait(0.005):
            if cancellation_token.cancelled:
                self.cancel_seen.set()
                if self.stop_on_cancel:
                    raise BacktestOperationCancelled("SYNC_CALENDAR")
        return BacktestDataSyncJobResult(
            calendar_rows=1,
            minute_days=0,
            daily_limit_rows=0,
            daily_bar_rows=0,
            network_calls=1,
        )


def test_operation_dispatch_validates_persisted_request_and_shared_controls(tmp_path) -> None:
    repository = BacktestJobRepository(tmp_path / "operations.sqlite3")
    repository.submit(_sync_request(), "dispatch", request_id="1" * 32)
    claim = repository.claim_next()
    assert claim is not None
    observed: list[DataSyncJobRequest] = []

    def sync_operation(request, *, cancellation_token, progress_callback):
        assert isinstance(request, DataSyncJobRequest)
        assert isinstance(cancellation_token, CancellationToken)
        assert callable(progress_callback)
        observed.append(request)
        return BacktestDataSyncJobResult(
            calendar_rows=0,
            minute_days=0,
            daily_limit_rows=0,
            daily_bar_rows=0,
            network_calls=0,
        )

    operations = BacktestJobOperations(
        data_sync=sync_operation,
        dataset_verify=lambda *_args, **_kwargs: None,
        backtest_run=lambda *_args, **_kwargs: None,
    )
    result = operations.execute(
        claim,
        cancellation_token=CancellationToken(),
        progress_callback=lambda _progress: None,
    )

    assert result.kind == claim.kind
    assert observed == [_sync_request()]


def test_blocking_sync_core_calls_provider_on_its_current_thread_without_an_executor(
    tmp_path,
) -> None:
    thread_ids: list[int] = []

    class ClosedDayProvider:
        def trading_calendar(self, exchange: str, start: date, end: date):
            thread_ids.append(get_ident())
            assert (exchange, start, end) == ("SSE", _TRADE_DATE, _TRADE_DATE)
            return (
                TradingDay(
                    exchange="SSE",
                    cal_date=_TRADE_DATE,
                    is_open=False,
                    previous_trade_date=date(2026, 8, 21),
                ),
            )

        def historical_minute_batch(self, *_args):
            raise AssertionError("closed day must not request minutes")

        def daily_limits(self, *_args):
            raise AssertionError("closed day must not request limits")

        def daily_bars(self, *_args):
            raise AssertionError("closed day must not request daily bars")

    core = BlockingBacktestSyncCore(
        provider=ClosedDayProvider(),
        store=BacktestMarketStore(tmp_path / "market.sqlite3"),
        today=lambda: date(2026, 8, 25),
    )
    scope = DatasetScope(
        symbols=("600000.SH",),
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        warmup_start=_TRADE_DATE,
        historical_profile=_PROFILE,
    )

    result = core.sync(scope)

    assert result.network_calls == 1
    assert thread_ids == [get_ident()]
    assert all("executor" not in name.casefold() for name in vars(core))


def test_blocking_job_keeps_event_loop_responsive_and_heartbeats_on_one_owned_thread(
    tmp_path,
) -> None:
    async def scenario() -> None:
        raw_repository = BacktestJobRepository(tmp_path / "coordinator.sqlite3")
        receipt = raw_repository.submit(_sync_request(), "blocking", request_id="2" * 32)
        repository = _RecordingRepository(raw_repository)
        operations = _BlockingOperations()
        coordinator = BacktestJobCoordinator(
            repository=repository,
            operations=operations,
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0.02,
            shutdown_timeout_seconds=1.0,
        )
        loop = asyncio.get_running_loop()
        explicit_executors: list[object | None] = []
        original_run_in_executor = loop.run_in_executor

        def record_executor(executor, function, *args):
            explicit_executors.append(executor)
            return original_run_in_executor(executor, function, *args)

        loop.run_in_executor = record_executor  # type: ignore[method-assign]
        try:
            await coordinator.start()
            await _wait_until(operations.started.is_set)
            event_loop_probe = 0
            for _ in range(5):
                await asyncio.sleep(0.01)
                event_loop_probe += 1
            await _wait_until(lambda: len(repository.heartbeat_times) >= 2)
            operations.release.set()
            await _wait_until(
                lambda: raw_repository.get(receipt.job_id).status is BacktestJobStatus.COMPLETED
            )
        finally:
            operations.release.set()
            await coordinator.shutdown()
            loop.run_in_executor = original_run_in_executor  # type: ignore[method-assign]

        assert event_loop_probe == 5
        assert len(set(operations.thread_ids)) == 1
        assert operations.thread_ids[0] != get_ident()
        assert explicit_executors and all(value is not None for value in explicit_executors)
        heartbeat_gaps = [
            later - earlier
            for earlier, later in zip(
                repository.heartbeat_times,
                repository.heartbeat_times[1:],
                strict=False,
            )
        ]
        assert heartbeat_gaps and max(heartbeat_gaps) < 0.1
        assert not any(
            thread.name.startswith("backtest-job-worker")
            for thread in __import__("threading").enumerate()
        )
        assert not any(
            task.get_name().startswith("backtest-job") and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_shutdown_stops_claiming_cancels_active_work_and_joins_owned_resources(
    tmp_path,
) -> None:
    async def scenario() -> None:
        repository = BacktestJobRepository(tmp_path / "shutdown.sqlite3")
        first = repository.submit(_sync_request(), "first", request_id="3" * 32)
        second = repository.submit(
            DataSyncJobRequest(
                scope=_scope_request(),
                refresh=True,
                allow_network=True,
            ),
            "second",
            request_id="4" * 32,
        )
        operations = _BlockingOperations(stop_on_cancel=True)
        coordinator = BacktestJobCoordinator(
            repository=repository,
            operations=operations,
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0.02,
            shutdown_timeout_seconds=1.0,
        )

        await coordinator.start()
        await _wait_until(operations.started.is_set)
        started_at = monotonic()
        await coordinator.shutdown()
        elapsed = monotonic() - started_at

        assert elapsed < 1.0
        assert operations.cancel_seen.is_set()
        assert len(operations.thread_ids) == 1
        assert repository.get(first.job_id).status is BacktestJobStatus.RUNNING
        assert repository.get(second.job_id).status is BacktestJobStatus.QUEUED
        assert not any(
            thread.name.startswith("backtest-job-worker")
            for thread in __import__("threading").enumerate()
        )
        assert not any(
            task.get_name().startswith("backtest-job") and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_local_job_composition_binds_transport_sqlite_and_shutdown_to_one_policy(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "tushare:\n  api_url: https://api.quicksync.cn\n  timeout_seconds: 30\n",
        encoding="utf-8",
    )
    captured_timeouts: list[int] = []

    def capture_client(configuration):
        captured_timeouts.append(configuration.timeout_seconds)
        return object()

    class ClosedDayProvider:
        def trading_calendar(self, exchange: str, start: date, end: date):
            assert (exchange, start, end) == ("SSE", _TRADE_DATE, _TRADE_DATE)
            return (
                TradingDay(
                    exchange="SSE",
                    cal_date=_TRADE_DATE,
                    is_open=False,
                    previous_trade_date=date(2026, 8, 21),
                ),
            )

        def historical_minute_batch(self, *_args):
            raise AssertionError("closed day must not request minutes")

        def daily_limits(self, *_args):
            raise AssertionError("closed day must not request limits")

        def daily_bars(self, *_args):
            raise AssertionError("closed day must not request daily bars")

    monkeypatch.setattr(backtest_application, "create_tushare_client", capture_client)
    monkeypatch.setattr(
        backtest_application,
        "TushareHistoricalMinuteProvider",
        lambda *_args, **_kwargs: ClosedDayProvider(),
    )
    use_cases = backtest_application._LocalBacktestJobUseCases(
        config_path=config_path,
        market_database=tmp_path / "bounded-market.sqlite3",
        results_database=tmp_path / "bounded-results.sqlite3",
    )

    result = use_cases._sync(
        _sync_request(),
        cancellation_token=CancellationToken(),
        progress_callback=lambda _progress: None,
    )

    assert result.network_calls == 1
    assert captured_timeouts == [2]
    assert use_cases._market_store._busy_timeout_ms == 2_000
    assert use_cases._repository._busy_timeout_ms == 2_000
    assert use_cases._results._busy_timeout_ms == 2_000
    assert use_cases._shutdown_policy.cancellation_safe_boundary_seconds == 4.5
    assert use_cases._shutdown_policy.shutdown_timeout_seconds == 5.0


def test_atomic_completion_gives_cancellation_first_one_terminal_and_no_partial_result(
    tmp_path,
) -> None:
    database = tmp_path / "cancel-first.sqlite3"
    repository = BacktestJobRepository(database)
    result_store = BacktestResultStore(database)
    run_input = _run_input()
    report_hash = _stage_empty_run(result_store, run_input)
    receipt = repository.submit(
        BacktestRunJobRequest(run_input=run_input),
        "atomic-cancel-submit",
    )
    claim = repository.claim_next()
    assert claim is not None and claim.job_id == receipt.job_id

    cancellation = repository.request_cancel(receipt.job_id, "atomic-cancel-request")
    assert cancellation.status is BacktestJobStatus.CANCEL_REQUESTED
    assert (
        repository.complete(
            receipt.job_id,
            claim.claim_token.get_secret_value(),
            BacktestRunJobResult(
                run_id=run_input.run_id,
                report_hash=report_hash,
                reused=False,
            ),
        )
        is False
    )
    assert result_store.get_verified_run(run_input.run_id) is None
    assert (
        repository.acknowledge_cancel(
            receipt.job_id,
            claim.claim_token.get_secret_value(),
        )
        is True
    )
    assert repository.get(receipt.job_id).status is BacktestJobStatus.CANCELLED


def test_atomic_completion_gives_publication_first_one_terminal_and_visible_result(
    tmp_path,
) -> None:
    database = tmp_path / "publish-first.sqlite3"
    repository = BacktestJobRepository(database)
    result_store = BacktestResultStore(database)
    run_input = _run_input()
    report_hash = _stage_empty_run(result_store, run_input)
    receipt = repository.submit(
        BacktestRunJobRequest(run_input=run_input),
        "atomic-publish-submit",
    )
    claim = repository.claim_next()
    assert claim is not None

    assert (
        repository.complete(
            receipt.job_id,
            claim.claim_token.get_secret_value(),
            BacktestRunJobResult(
                run_id=run_input.run_id,
                report_hash=report_hash,
                reused=False,
            ),
        )
        is True
    )
    assert result_store.get_verified_run(run_input.run_id) is not None
    cancellation = repository.request_cancel(receipt.job_id, "atomic-publish-cancel")
    assert cancellation.status is BacktestJobStatus.COMPLETED
    assert repository.get(receipt.job_id).status is BacktestJobStatus.COMPLETED


def test_atomic_completion_rolls_back_publication_when_job_update_fails(tmp_path) -> None:
    database = tmp_path / "atomic-rollback.sqlite3"
    repository = BacktestJobRepository(database)
    result_store = BacktestResultStore(database)
    run_input = _run_input()
    report_hash = _stage_empty_run(result_store, run_input)
    receipt = repository.submit(
        BacktestRunJobRequest(run_input=run_input),
        "atomic-rollback-submit",
    )
    claim = repository.claim_next()
    assert claim is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_job_completion
            BEFORE UPDATE OF status ON backtest_job
            WHEN NEW.status = 'COMPLETED' AND OLD.status = 'RUNNING'
            BEGIN
                SELECT RAISE(ABORT, 'forced completion failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced completion failure"):
        repository.complete(
            receipt.job_id,
            claim.claim_token.get_secret_value(),
            BacktestRunJobResult(
                run_id=run_input.run_id,
                report_hash=report_hash,
                reused=False,
            ),
        )

    assert result_store.get_verified_run(run_input.run_id) is None
    assert repository.get(receipt.job_id).status is BacktestJobStatus.RUNNING


def test_maintenance_shares_one_total_budget_between_jobs_and_result_rows(tmp_path) -> None:
    now = [datetime(2026, 8, 1, 9, 30, tzinfo=_SHANGHAI)]
    database = tmp_path / "maintenance.sqlite3"
    repository = BacktestJobRepository(database, clock=lambda: now[0])
    result_store = BacktestResultStore(database)
    for index in range(2):
        receipt = repository.submit(
            _sync_request(),
            f"maintenance-submit-{index}",
            request_id=f"{index + 1:032x}",
        )
        repository.request_cancel(receipt.job_id, f"maintenance-cancel-{index}")
    run_input = _run_input()
    _stage_empty_run(result_store, run_input, retention_at=now[0])
    now[0] += timedelta(days=15)
    maintenance = BacktestJobMaintenance(repository=repository, results=result_store)

    first = maintenance.prune(as_of=now[0], batch_size=2)

    assert first.deleted_count == 2
    assert first.has_more is True
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM backtest_job").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM backtest_run WHERE materialized = 0"
        ).fetchone() == (1,)

    second = maintenance.prune(as_of=now[0], batch_size=2)
    assert second.deleted_count == 1
    assert second.has_more is False


def test_maintenance_rolls_back_job_pruning_when_result_participant_fails(
    tmp_path,
) -> None:
    now = [datetime(2026, 8, 1, 9, 30, tzinfo=_SHANGHAI)]
    database = tmp_path / "maintenance-transaction.sqlite3"
    repository = BacktestJobRepository(database, clock=lambda: now[0])
    result_store = BacktestResultStore(database)
    receipt = repository.submit(
        _sync_request(),
        "maintenance-transaction-submit",
        request_id="6" * 32,
    )
    repository.request_cancel(receipt.job_id, "maintenance-transaction-cancel")
    _stage_empty_run(result_store, _run_input(), retention_at=now[0])
    now[0] += timedelta(days=15)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_result_prune
            BEFORE DELETE ON backtest_run
            BEGIN SELECT RAISE(ABORT, 'injected result participant failure'); END
            """
        )
        connection.commit()
    maintenance = BacktestJobMaintenance(repository=repository, results=result_store)
    with pytest.raises(sqlite3.IntegrityError, match="injected result participant failure"):
        maintenance.prune(as_of=now[0], batch_size=1_000)

    assert repository.get(receipt.job_id) is not None


def test_cli_facade_routes_typed_sync_and_verify_through_durable_job_use_cases(
    tmp_path,
) -> None:
    calls: list[tuple[object, str | None]] = []
    coverage = BacktestDatasetCoverage(
        symbol_count=1,
        trading_day_count=1,
        calendar_row_count=1,
        minute_day_count=1,
        minute_bar_count=240,
        daily_limit_row_count=1,
        daily_bar_row_count=1,
        blockers=(),
    )

    class DurableUseCases:
        async def execute(self, request, *, request_id=None):
            calls.append((request, request_id))
            if isinstance(request, DataSyncJobRequest):
                return BacktestDataSyncJobResult(
                    calendar_rows=1,
                    minute_days=1,
                    daily_limit_rows=1,
                    daily_bar_rows=1,
                    network_calls=4,
                )
            assert isinstance(request, DatasetVerifyJobRequest)
            return BacktestDatasetVerificationJobResult(
                ready=True,
                dataset_hash=_hash("verified-dataset"),
                coverage=coverage,
                blockers=(),
            )

    service = BacktestApplicationService(
        config_path=tmp_path / "unused.yaml",
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        report_directory=tmp_path / "reports",
        job_use_cases=DurableUseCases(),
    )

    sync_result = asyncio.run(
        service.sync(
            symbols=("600000.SH",),
            start=_TRADE_DATE,
            end=_TRADE_DATE,
            warmup_start=_TRADE_DATE,
            refresh=False,
            allow_network=True,
        )
    )
    verify_result = service.verify(
        symbols=("600000.SH",),
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        warmup_start=_TRADE_DATE,
    )

    assert sync_result.network_calls == 4
    assert verify_result.ready is True
    assert verify_result.dataset_hash == _hash("verified-dataset")
    assert isinstance(calls[0][0], DataSyncJobRequest)
    assert calls[0][0].allow_network is True
    assert calls[0][1] is not None
    assert isinstance(calls[1][0], DatasetVerifyJobRequest)
    assert calls[1][1] is None
    run_source = getsource(BacktestApplicationService.run)
    assert "OfflineBacktestRunner" not in run_source
    assert "persist_report" not in run_source
    assert "_execute_job" in run_source
