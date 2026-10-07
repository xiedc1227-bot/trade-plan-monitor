"""ML-T32: shared first use, bounded observation and physical ownership."""

import asyncio
from threading import Event, current_thread

import pytest

from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_contract import BacktestCapability, BacktestServiceState
from trade_plan_monitor.backtest.service_lifecycle import (
    BacktestServiceUnavailable,
    LazyBacktestLifecycle,
)
from trade_plan_monitor.backtest.thread_lifecycle import BacktestMetadataThread


class Lifecycle:
    read_service = object()
    operation_service = object()

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    async def start(self) -> None:
        self.starts += 1

    async def stop(self) -> None:
        self.stops += 1


def test_concurrent_first_use_and_cancelled_waiter_share_owned_preparation() -> None:
    entered, release = Event(), Event()
    lifecycle = Lifecycle()
    factory_threads = []

    def factory():
        factory_threads.append(current_thread().name)
        entered.set()
        assert release.wait(2)
        return lifecycle

    async def scenario():
        manager = LazyBacktestLifecycle(factory)
        assert manager.snapshot.state is BacktestServiceState.NOT_INITIALIZED
        first = asyncio.create_task(manager.ensure())
        second = asyncio.create_task(manager.ensure())
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert manager.snapshot.outstanding_work == 1
            release.set()
            assert await second is lifecycle
            assert manager.snapshot.state is BacktestServiceState.READ_READY
            assert lifecycle.starts == 0
            await asyncio.gather(*(manager.ensure(execution=True) for _ in range(8)))
            assert lifecycle.starts == 1
        finally:
            release.set()
            await manager.stop()
        assert manager.snapshot.physically_drained
        assert lifecycle.stops == 1

    asyncio.run(scenario())
    assert len(factory_threads) == 1
    assert factory_threads[0].startswith("backtest-service")


def test_watchdog_and_shutdown_timeout_keep_late_work_owned_until_drain() -> None:
    entered, release = Event(), Event()
    lifecycle = Lifecycle()
    calls = []

    def factory():
        calls.append("factory")
        entered.set()
        assert release.wait(2)
        return lifecycle

    async def scenario():
        manager = LazyBacktestLifecycle(factory, config=BacktestServiceConfig(
            request_wait_seconds=0.01, initialization_watchdog_seconds=0.03,
            shutdown_wait_seconds=0.01,
        ))
        try:
            with pytest.raises(BacktestServiceUnavailable):
                await manager.ensure()
            await asyncio.sleep(0.04)
            assert manager.snapshot.state is BacktestServiceState.DEGRADED
            assert not manager.snapshot.physically_drained
            with pytest.raises(BacktestServiceUnavailable):
                await manager.retry()
            with pytest.raises(BacktestServiceUnavailable):
                await manager.stop()
            assert not manager.snapshot.physically_drained
            release.set()
            await manager.wait_for_drain()
            assert lifecycle.stops == 1
            assert manager.snapshot.state is BacktestServiceState.STOPPED
            assert calls == ["factory"]
        finally:
            release.set()
            await manager.wait_for_drain()

    asyncio.run(scenario())


def test_failed_initialization_only_retries_after_explicit_request() -> None:
    calls = []
    lifecycle = Lifecycle()

    def factory():
        calls.append("factory")
        if len(calls) == 1:
            raise OSError("private initialization failure")
        return lifecycle

    async def scenario():
        manager = LazyBacktestLifecycle(factory)
        for _ in range(3):
            with pytest.raises(BacktestServiceUnavailable):
                await manager.ensure()
        assert calls == ["factory"]
        await manager.retry()
        assert await manager.ensure() is lifecycle
        assert calls == ["factory", "factory"]
        await manager.stop()

    asyncio.run(scenario())


def test_metadata_calls_are_owned_bounded_and_cancelled_waiters_do_not_release_threads() -> None:
    entered, release = Event(), Event()
    names = []

    def query():
        names.append(current_thread().name)
        entered.set()
        assert release.wait(2)
        return "history"

    async def scenario():
        thread = BacktestMetadataThread()
        waiter = asyncio.create_task(thread.run(query))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            with pytest.raises(BacktestServiceUnavailable):
                await thread.run(lambda: "must not run")
            cleanup = asyncio.create_task(thread.stop())
            await asyncio.sleep(0)
            assert not cleanup.done()
            assert thread.outstanding_work == 1
            release.set()
            await cleanup
            assert thread.outstanding_work == 0
        finally:
            release.set()
            await thread.stop()

    asyncio.run(scenario())
    assert names == ["backtest-metadata_0"]


def test_execution_failure_preserves_already_healthy_history_capability() -> None:
    class FailedExecution(Lifecycle):
        async def start(self) -> None:
            self.starts += 1
            raise OSError("execution-only defect")

    async def scenario():
        lifecycle = FailedExecution()
        manager = LazyBacktestLifecycle(lambda: lifecycle)
        try:
            assert await manager.ensure() is lifecycle
            with pytest.raises(BacktestServiceUnavailable):
                await manager.ensure(execution=True)
            assert manager.snapshot.state is BacktestServiceState.DEGRADED
            assert await manager.ensure() is lifecycle
            assert manager.snapshot.allows(BacktestCapability.METADATA)
            assert not manager.snapshot.allows(BacktestCapability.EXECUTION)
            with pytest.raises(BacktestServiceUnavailable):
                await manager.ensure(execution=True)
            assert lifecycle.starts == 1
        finally:
            await manager.stop()
        assert not manager.snapshot.allows(BacktestCapability.METADATA)

    asyncio.run(scenario())
