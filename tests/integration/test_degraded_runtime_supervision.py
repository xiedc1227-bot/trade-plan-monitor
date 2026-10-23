"""An admitted read-only runtime must not silently lose its recovery runner."""

import asyncio

import pytest
from test_runtime_lifecycle import _Scheduler, _service

from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.runtime_liveness import RuntimeLivenessError
from trade_plan_monitor.web.monitor_composition import MonitorWebComposition


@pytest.mark.parametrize("failure", ["heartbeat", "retry"])
def test_degraded_runner_failure_cleans_and_restarts_fresh(failure, caplog):
    async def scenario():
        events = []
        failed = asyncio.Event()
        replacement_running = asyncio.Event()

        class Liveness:
            async def admit(self):
                pass

            async def heartbeat(self):
                failed.set()
                raise RuntimeLivenessError("runtime liveness changed")

        async def broken_retry(_shutdown, _delay):
            failed.set()
            raise ValueError("private-provider-body-must-not-be-logged")

        initial = _service(
            symbols=(), events=events, scheduler=_Scheduler(deadline=None),
            liveness_owner=Liveness() if failure == "heartbeat" else None,
            heartbeat_interval_seconds=0.01,
            retry_wait=broken_retry if failure == "retry" else None,
        )
        replacement = _service(
            symbols=(), scheduler=_Scheduler(wait_started=replacement_running),
        )
        replacements = []
        delays = []

        def factory():
            assert initial.status is RuntimeServiceStatus.STOPPED
            assert initial.owned_task_count == 0
            assert events.count("database-close") == 1
            replacements.append(replacement)
            return replacement

        async def delay(seconds):
            delays.append(seconds)

        composition = MonitorWebComposition(
            runtime=initial, runtime_factory=factory, restart_sleep=delay,
            read_service=object(),
        )
        try:
            await composition.start()
            await asyncio.wait_for(failed.wait(), 1)
            await asyncio.wait_for(replacement_running.wait(), 1)
            assert initial.unexpected_run_exit
            assert replacements == [replacement]
            assert delays == [1.0]
            assert composition.health().status is RuntimeServiceStatus.RUNNING
            assert "RUNTIME_RESTART_SCHEDULED" in caplog.text
            if failure == "heartbeat":
                assert "LIVENESS_REVISION_CHANGED" in caplog.text
            assert "private-provider-body" not in caplog.text
        finally:
            await composition.stop()
        assert initial.owned_task_count == replacement.owned_task_count == 0

    asyncio.run(scenario())


def test_explicit_stop_of_degraded_runtime_never_restarts():
    async def scenario():
        waiting = asyncio.Event()

        async def wait_for_stop(shutdown, _delay):
            from trade_plan_monitor.runtime.service import _RetryWaitOutcome
            waiting.set()
            await shutdown.wait()
            return _RetryWaitOutcome.SHUTDOWN

        runtime = _service(scheduler=_Scheduler(deadline=None), retry_wait=wait_for_stop)
        composition = MonitorWebComposition(
            runtime=runtime, runtime_factory=lambda: pytest.fail("explicit stop restarted"),
            read_service=object(),
        )
        await composition.start()
        await asyncio.wait_for(waiting.wait(), 1)
        await composition.stop()
        assert not runtime.unexpected_run_exit
        assert runtime.status is RuntimeServiceStatus.STOPPED
        assert runtime.owned_task_count == 0

    asyncio.run(scenario())


def test_degraded_failures_exhaust_the_existing_budget(caplog):
    async def scenario():
        runtimes = []
        delays = []

        async def fail(_shutdown, _delay):
            raise ValueError("private-provider-body")

        def factory():
            runtime = _service(scheduler=_Scheduler(deadline=None), retry_wait=fail)
            runtimes.append(runtime)
            return runtime

        async def delay(seconds):
            delays.append(seconds)

        composition = MonitorWebComposition(
            runtime=factory(), runtime_factory=factory, restart_sleep=delay,
            read_service=object(),
        )
        try:
            await composition.start()
            await asyncio.wait_for(asyncio.shield(composition._runner_task), 1)
            assert delays == [1.0, 2.0, 4.0]
            assert len(runtimes) == 4
            assert all(runtime.status is RuntimeServiceStatus.STOPPED for runtime in runtimes)
            assert all(runtime.owned_task_count == 0 for runtime in runtimes)
            assert composition.health().read_only
            assert "RUNTIME_RESTART_BUDGET_EXHAUSTED" in caplog.text
            assert "private-provider-body" not in caplog.text
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_production_degraded_heartbeat_failure_replaces_owner_offline(tmp_path, monkeypatch):
    from tushare.pro.client import DataApi

    from trade_plan_monitor.web.monitor_composition import create_monitor_composition

    monkeypatch.setattr(DataApi, "query", lambda *a, **k: pytest.fail("provider I/O"))
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf-8")
    composition = create_monitor_composition(
        config_path=config, database_path=tmp_path / "monitor.sqlite3",
        monitor_contract_version=2,
    )
    original = composition._runtime
    original._heartbeat_interval_seconds = 0.01

    async def fail():
        raise RuntimeLivenessError("invalid runtime liveness")

    monkeypatch.setattr(original._liveness_owner, "heartbeat", fail)
    composition._restart_sleep = lambda _delay: asyncio.sleep(0)

    async def scenario():
        try:
            await composition.start()
            assert original._startup_result.status is RuntimeServiceStatus.DEGRADED
            async with asyncio.timeout(5):
                while composition._runtime is original:
                    await asyncio.sleep(0.01)
            replacement = composition._runtime
            assert replacement.runtime_generation != original.runtime_generation
            assert original.status is RuntimeServiceStatus.STOPPED
            assert original.owned_task_count == 0
            assert replacement.status is RuntimeServiceStatus.DEGRADED
            assert not composition._runner_task.done()
            health = await composition.read_service.get_health()
            assert health.runtime_generation == replacement.runtime_generation
            assert health.stopped_at is None
            assert health.runtime_status.mode == "BLOCKED"
            assert composition._restart_attempts == 1
        finally:
            await composition.stop()
        assert composition._runtime.owned_task_count == 0

    asyncio.run(scenario())
