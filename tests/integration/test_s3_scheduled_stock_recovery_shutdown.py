"""Stop a genuine scheduled stock-recovery owner while its SDK worker is held."""

import asyncio
from datetime import timedelta
from threading import Event, get_ident

from sqlalchemy import event
from test_s3_startup_minute_coverage import FIRST_END, NOW, SYMBOL, _running
from test_s3_stock_recovery_identity import _assert_no_first_decision, _snapshot

from trade_plan_monitor.runtime.health import RuntimeResourceStatus, RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind


def test_scheduled_stock_recovery_stop_revokes_then_drains_before_database_disposal(
    tmp_path, monkeypatch,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "partial") as run:
            composition = run.composition
            runtime = composition._runtime
            runner = composition._runner_task
            real_run_deadline = runtime._run_deadline
            state = real_run_deadline.__self__
            pipeline = state._pipeline
            controller = pipeline._controller
            generation = composition.health().runtime_generation
            entered, release = Event(), Event()
            shutdown_published = asyncio.Event()
            active_deadlines = {}
            boundaries = []
            disposals = []
            returned = []
            owner_thread = get_ident()
            drive = stop = None

            async def observe_deadline(deadline):
                # Forward the scheduler-selected duty unchanged; no direct unit
                # invocation or manual registration in runtime._work_tasks.
                task = asyncio.current_task()
                active_deadlines[task] = deadline
                try:
                    return await real_run_deadline(deadline)
                finally:
                    del active_deadlines[task]

            real_stock_minutes = run.sdk._stock_minutes

            def held_sdk(name, kwargs):
                if name == "rt_min_daily":
                    assert get_ident() != owner_thread
                    entered.set()
                    assert release.wait(15), "test did not release the physical SDK"
                frame = real_stock_minutes(name, kwargs)
                if name == "rt_min_daily":
                    returned.append(frame["time"].tolist())
                    boundaries.append("sdk-returned")
                return frame

            def observe_disposal(_engine):
                # This callback runs at actual Engine disposal, after the real
                # cleanup path, not at a mocked close_database boundary.
                disposals.append((
                    release.is_set(), controller.active_count, controller.waiting_count,
                    len(pipeline._active_recovery_attempts), owner.done(),
                ))
                boundaries.append("database-disposed")

            monkeypatch.setattr(runtime, "_run_deadline", observe_deadline)
            monkeypatch.setattr(run.sdk, "_stock_minutes", held_sdk)
            event.listen(state._engine, "engine_disposed", observe_disposal)
            run.sdk.phase = "scheduled-shutdown"
            run.sdk.history_available = True
            try:
                drive = asyncio.create_task(run.clock.drive(
                    NOW.replace(minute=2, second=12),
                    stop_when=entered.is_set, failed=run.runner_failed,
                ))
                async with asyncio.timeout(8):
                    while not entered.is_set():
                        assert not drive.done(), ("scheduler did not enter recovery", run.sdk.trace)
                        await asyncio.sleep(0.005)
                (owner, deadline), = active_deadlines.items()
                assert deadline.kind is DeadlineKind.STOCK_RECOVERY
                assert owner in runtime._work_tasks and not owner.done()
                scope, = (
                    item for item in pipeline._stock_recovery_schedule.snapshot()
                    if item.requirement.scope_key == f"stock-prefix:{SYMBOL}"
                )
                assert scope.in_progress
                (token,) = pipeline._active_recovery_attempts
                assert not token.is_set()
                assert controller.active_count == 1 and controller.waiting_count == 0
                assert composition.health().status is RuntimeServiceStatus.RUNNING
                assert composition.health().runtime_generation == generation
                before = _snapshot(run.database)
                assert before["minute_bar"] and before["latest_quote"]
                assert FIRST_END.isoformat() not in {row["bar_end"] for row in before["minute_bar"]}
                _assert_no_first_decision(before)
                calls = tuple(dict(entry) for entry in run.sdk.trace)
                assert len(run.sdk.entries("rt_min_daily")) == 2
                real_begin_shutdown = runtime.begin_shutdown

                def observe_begin_shutdown():
                    real_begin_shutdown()
                    if not shutdown_published.is_set():
                        # A synchronous observation in the real composition.stop
                        # call proves token publication precedes any cancellation.
                        assert token.is_set()
                        assert owner.cancelling() == runner.cancelling() == 0
                        assert not owner.done()
                        boundaries.append("token-before-cancel")
                        shutdown_published.set()

                monkeypatch.setattr(runtime, "begin_shutdown", observe_begin_shutdown)
                stop = asyncio.create_task(composition.stop())
                await asyncio.wait_for(shutdown_published.wait(), timeout=2)
                # Preserve the real lifecycle's five-second graceful drain period;
                # only release after its actual owned-task cancellation is visible.
                async with asyncio.timeout(8):
                    while owner.cancelling() == 0:
                        assert not stop.done()
                        await asyncio.sleep(0.005)
                assert token.is_set() and not owner.done() and not stop.done()
                assert controller.active_count == 1 and controller.waiting_count == 0
                assert runtime._database_opened
                assert state._database_status is RuntimeResourceStatus.READY
                assert not disposals and not returned
                assert tuple(run.sdk.trace) == calls
                assert _snapshot(run.database) == before
                assert run.sent == []
                assert composition._runtime is runtime and composition._runner_task is runner
                assert not composition._runner_failed and not composition._restart_pending
                assert runtime.health().runtime_generation == generation

                release.set()
                await asyncio.wait_for(asyncio.shield(stop), timeout=8)
                # A useful late response really returned. Its missing prefix and
                # refreshed quote still cannot be committed after shutdown.
                (raw_times,) = returned
                assert (FIRST_END - timedelta(minutes=1)).strftime(
                    "%Y-%m-%d %H:%M:%S",
                ) in raw_times
                assert _snapshot(run.database) == before
                assert tuple(run.sdk.trace) == calls and run.sent == []
                assert boundaries == ["token-before-cancel", "sdk-returned", "database-disposed"]
                assert disposals == [(True, 0, 0, 0, True)]
                assert owner.done() and runner.done() and not active_deadlines
                assert not runtime._work_tasks and not pipeline._active_recovery_attempts
                assert controller.active_count == controller.waiting_count == 0
                assert all(
                    not item.in_progress for item in pipeline._stock_recovery_schedule.snapshot()
                )
                assert pipeline.next_stock_recovery_at() is None
                assert not runtime._database_opened
                assert state._database_status is RuntimeResourceStatus.STOPPED
                assert runtime.health().status is RuntimeServiceStatus.STOPPED
                assert runtime.health().runtime_generation == generation
                assert composition._runtime is runtime and composition._runner_task is None
                assert not composition._runner_failed and not composition._restart_pending
                assert not runtime.unexpected_run_exit and not runtime.cleanup_failed
            finally:
                release.set()
                if drive is not None and not drive.done():
                    drive.cancel()
                if drive is not None:
                    await asyncio.gather(drive, return_exceptions=True)
                if stop is not None:
                    await asyncio.gather(stop, return_exceptions=True)
                event.remove(state._engine, "engine_disposed", observe_disposal)

    asyncio.run(scenario())
