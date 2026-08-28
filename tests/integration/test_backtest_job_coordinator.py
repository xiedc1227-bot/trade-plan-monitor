"""Single-thread backtest coordinator and blocking-operation coverage."""

from __future__ import annotations

import asyncio
from datetime import date
from threading import Event, get_ident
from time import monotonic
from zoneinfo import ZoneInfo

from trade_plan_monitor.backtest.control import (
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestDataSyncJobResult,
    BacktestJobCoordinator,
    BacktestJobOperations,
    BacktestJobRepository,
    BacktestJobStatus,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.sync import BlockingBacktestSyncCore
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.models import TradingDay

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRADE_DATE = date(2026, 8, 24)
_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


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
