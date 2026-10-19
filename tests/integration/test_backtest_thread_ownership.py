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
from trade_plan_monitor.backtest.thread_lifecycle import (
    BacktestMetadataThread,
    BacktestResultReadThread,
)


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


def test_metadata_reads_serialize_short_overlap_without_rejecting_normal_page_reads() -> None:
    entered, release = Event(), Event()
    calls = []

    def first():
        entered.set()
        assert release.wait(2)
        calls.append("first")
        return 1

    async def scenario():
        thread = BacktestMetadataThread()
        active = asyncio.create_task(thread.run(first))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            readers = [
                asyncio.create_task(thread.read(lambda: calls.append("read"))) for _ in range(4)
            ]
            await asyncio.sleep(0)
            assert thread.outstanding_work == 1
            assert not any(task.done() for task in readers)
            release.set()
            assert await active == 1
            await asyncio.gather(*readers)
            assert calls == ["first", "read", "read", "read", "read"]
        finally:
            release.set()
            await thread.stop()
    asyncio.run(scenario())


def test_metadata_read_wait_is_bounded_and_cancelled_read_never_executes() -> None:
    entered, release = Event(), Event()
    calls = []

    def block():
        entered.set()
        assert release.wait(2)

    async def scenario():
        thread = BacktestMetadataThread(max_waiting_reads=1, read_wait_seconds=0.03)
        active = asyncio.create_task(thread.run(block))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            waiting = asyncio.create_task(thread.read(lambda: calls.append("cancelled")))
            await asyncio.sleep(0)
            with pytest.raises(BacktestServiceUnavailable):
                await thread.read(lambda: calls.append("overflow"))
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            with pytest.raises(BacktestServiceUnavailable):
                await thread.read(lambda: calls.append("expired"))
            with pytest.raises(BacktestServiceUnavailable):
                await thread.run(lambda: calls.append("mutation"))
            release.set()
            await active
            await thread.read(lambda: calls.append("fresh"))
            assert calls == ["fresh"]
            await thread.stop()
            with pytest.raises(BacktestServiceUnavailable):
                await thread.read(lambda: calls.append("stopped"))
        finally:
            release.set()
            await thread.stop()
    asyncio.run(scenario())


def test_shared_result_read_keeps_cancelled_observers_owned_and_does_not_cache():
    entered, release = Event(), Event()
    calls = []

    def read():
        calls.append("read")
        entered.set()
        assert release.wait(2)
        return len(calls)

    async def scenario():
        thread = BacktestResultReadThread(max_readers=2)
        first = asyncio.create_task(thread.read_shared(("run", "a"), read))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            second = asyncio.create_task(thread.read_shared(("run", "a"), read))
            await asyncio.sleep(0)
            with pytest.raises(BacktestServiceUnavailable):
                await thread.read_shared(("run", "a"), read)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert thread.outstanding_work == 1
            release.set()
            assert await second == 1
            assert await thread.read_shared(("run", "a"), read) == 2
            assert calls == ["read", "read"]
        finally:
            release.set()
            await thread.stop()
        assert thread.outstanding_work == 0
        with pytest.raises(BacktestServiceUnavailable):
            await thread.read_shared(("run", "a"), read)

    asyncio.run(scenario())


def test_shared_result_queue_timeout_and_shutdown_never_execute_waiting_reads():
    entered, release = Event(), Event()
    calls = []

    def held():
        entered.set()
        assert release.wait(2)

    async def scenario():
        thread = BacktestResultReadThread(read_wait_seconds=0.03)
        first = asyncio.create_task(thread.read_shared(("run", "a"), held))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            with pytest.raises(BacktestServiceUnavailable):
                await thread.read_shared(("run", "b"), lambda: calls.append("expired"))
            waiting = asyncio.create_task(thread.read_shared(
                ("run", "c"), lambda: calls.append("stopped"),
            ))
            await asyncio.sleep(0)
            stopping = asyncio.create_task(thread.stop())
            await asyncio.sleep(0)
            assert not stopping.done() and thread.outstanding_work == 1
            release.set()
            await first
            await stopping
            with pytest.raises(BacktestServiceUnavailable):
                await waiting
            assert calls == []
        finally:
            release.set()
            await thread.stop()

    asyncio.run(scenario())
