"""Scheduled stock repair cannot survive a worker-published source revocation."""

import asyncio
import sqlite3
from contextlib import closing, suppress
from datetime import timedelta
from threading import Event, get_ident

from test_s3_startup_minute_coverage import BUSINESS_TABLES, FIRST_END, NOW, SYMBOL, _running


def _facts(database):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return {
            table: tuple(dict(row) for row in db.execute(
                f"SELECT * FROM {table} WHERE symbol=? ORDER BY rowid", (SYMBOL,),
            ))
            for table in ("minute_bar", "latest_quote")
        }


def test_scheduled_stock_recovery_source_revocation_blocks_without_rearming(
    tmp_path, monkeypatch,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "partial") as run:
            composition = run.composition
            runtime = composition._runtime
            state = runtime._run_deadline.__self__
            pipeline = state._pipeline
            generation = runtime.runtime_generation
            runner = composition._runner_task
            owner_thread = get_ident()
            loop = asyncio.get_running_loop()
            entered = asyncio.Event()
            release = Event()
            worker_threads = []
            returned_history = []
            deadlines = []
            original_deadline = runtime._run_deadline
            original_minutes = run.sdk._stock_minutes
            original_config = run.config.read_text(encoding="utf-8")
            assert "offline-test-token" in original_config

            async def observe_deadline(deadline):
                # Observe the existing scheduler owner; do not select or invoke a duty here.
                deadlines.append(deadline)
                return await original_deadline(deadline)

            def held_sdk(name, kwargs):
                if name == "rt_min_daily":
                    worker_threads.append(get_ident())
                    loop.call_soon_threadsafe(entered.set)
                    assert release.wait(10), "test must release the offline SDK worker"
                frame = original_minutes(name, kwargs)
                if name == "rt_min_daily":
                    returned_history.append(tuple(frame["time"]))
                return frame

            monkeypatch.setattr(runtime, "_run_deadline", observe_deadline)
            monkeypatch.setattr(run.sdk, "_stock_minutes", held_sdk)
            run.sdk.phase = "scheduled-authority"
            run.sdk.history_available = True
            drive = asyncio.create_task(run.clock.drive(
                NOW.replace(minute=3, second=12), failed=run.runner_failed,
            ))
            entry_wait = asyncio.create_task(entered.wait())
            try:
                done, _ = await asyncio.wait(
                    (drive, entry_wait), timeout=10, return_when=asyncio.FIRST_COMPLETED,
                )
                assert entered.is_set(), (
                    "real scheduled stock maintenance did not enter its SDK", run.sdk.trace,
                    [deadline.kind.value for deadline in deadlines],
                )
                assert entry_wait in done or entry_wait.done()
                assert deadlines[-1].kind.value == "STOCK_RECOVERY"
                assert worker_threads and all(thread != owner_thread for thread in worker_threads)
                assert runtime._work_tasks and pipeline._active_recovery_attempts
                before_facts = _facts(run.database)
                before_business = run.state()
                assert before_facts["minute_bar"] and before_facts["latest_quote"]
                assert all(before_business[table] == () for table in BUSINESS_TABLES)
                assert not run.sent
                calls = tuple(run.sdk.trace)

                run.config.write_text(
                    original_config.replace("offline-test-token", "offline-new-token"),
                    encoding="utf-8",
                )

                def validate_in_worker():
                    # A second worker performs the real file comparison and publication.
                    # No mock validator, direct Event.set or replacement admission result.
                    return get_ident(), state.configuration_is_current()

                validator_thread, current = await asyncio.to_thread(validate_in_worker)
                assert validator_thread != owner_thread and current is False
                assert validator_thread not in worker_threads
                assert state._process_baseline.revoked.is_set()
                assert _facts(run.database) == before_facts
                release.set()
                async with asyncio.timeout(10):
                    while runtime._work_tasks or runtime._block_reason != "NEEDS_RESTART":
                        await asyncio.sleep(0.005)

                assert not pipeline._active_recovery_attempts
                assert len(returned_history) == 1
                assert (FIRST_END - timedelta(minutes=1)).strftime(
                    "%Y-%m-%d %H:%M:%S",
                ) in returned_history[0]
                assert composition._runtime is runtime and composition._runner_task is runner
                assert not composition._runner_failed and not composition._restart_pending
                assert runner is not None and not runner.done()
                assert _facts(run.database) == before_facts  # Includes values and received_at.
                assert run.state() == before_business
                assert tuple(run.sdk.trace) == calls and not run.sent
                blocked = composition.health()
                assert blocked.status.value == "BLOCKED" and blocked.read_only
                assert blocked.block_reason == "NEEDS_RESTART"
                assert blocked.degraded_reason is None
                # The v1 health copy excludes this internal field; inspect its owner,
                # and use the public unavailable/heartbeat contracts for current state.
                assert runtime.runtime_generation == generation
                assert runtime.health().runtime_generation == generation
                assert blocked.next_poll_at is None and blocked.next_retry_at is None
                dashboard = await composition.read_service.get_dashboard()
                assert dashboard.availability == "UNAVAILABLE"
                assert dashboard.reason.value == "AWAITING_FIRST_EVALUATION"
                assert await composition.read_service.get_symbol_health(symbol=SYMBOL) is None
                frame = composition.websocket_service._heartbeat_frame(dashboard.sequence)
                assert frame["runtimeLive"] is False and frame["runtimeGeneration"] is None

                # Restoring a file is not hot reload and cannot unlock the old baseline.
                run.config.write_text(original_config, encoding="utf-8")
                assert not state.configuration_is_current()
                run.clock.current += timedelta(minutes=5)
                for _ in range(10):
                    await asyncio.sleep(0)
                assert not runtime._accepting_work
                assert runtime._shutdown_requested_event is not None
                assert not runtime._shutdown_requested_event.is_set()
                assert composition.health().block_reason == "NEEDS_RESTART"
                assert runtime.runtime_generation == generation
                assert runtime.health().runtime_generation == generation
                assert composition._runtime is runtime and composition._runner_task is runner
                assert tuple(run.sdk.trace) == calls and not run.sent
                assert _facts(run.database) == before_facts
                assert run.state() == before_business
            finally:
                release.set()
                run.config.write_text(original_config, encoding="utf-8")
                for task in (drive, entry_wait):
                    if not task.done():
                        task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    asyncio.run(scenario())
