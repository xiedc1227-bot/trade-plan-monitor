"""Drain a held proof from real RUNNING/DEGRADED owners before disposal."""

import asyncio
from datetime import timedelta
from threading import Event, get_ident

import pytest
from sqlalchemy import event
from test_live_pipeline_acceptance import NOW
from test_s3_permission_reservation_process import IDENTITY, _business_rows, _checkpoint_rows
from test_unified_permission_degraded import _degraded_composition
from test_unified_permission_running import _composition

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.health import RuntimeResourceStatus, RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository, RecoveryCheckpoint

SCOPE = TushareOperation.INDEX_HISTORICAL_MINUTES


@pytest.mark.parametrize("mode", (RuntimeServiceStatus.RUNNING, RuntimeServiceStatus.DEGRADED))
def test_scheduled_permission_stop_revokes_before_cancel_and_drains_late_proof(
    tmp_path, monkeypatch, mode,
):
    async def scenario():
        database = tmp_path / "monitor.sqlite3"
        due = NOW + timedelta(seconds=1)
        wait = None
        if mode is RuntimeServiceStatus.DEGRADED:
            composition, sdk, wait = _degraded_composition(
                tmp_path, monkeypatch,
                scopes=(TushareOperation.TRADING_CALENDAR, SCOPE), seconds=1,
            )
        else:
            composition, sdk = _composition(tmp_path, monkeypatch, stock=False)
            seed_engine = create_sqlite_engine(database)
            try:
                # Fixture latch only. The real automatic unit must replace this
                # deadline with its own durable now+300 reservation before the SDK.
                ProviderRecoveryRepository(
                    create_session_factory(seed_engine), provider_identity=IDENTITY,
                ).save((RecoveryCheckpoint("permission", SCOPE.value, due, 0),))
            finally:
                seed_engine.dispose()
        seeded = _checkpoint_rows(database)
        entered, release = Event(), Event()
        shutdown_published, owner_cancelled = asyncio.Event(), asyncio.Event()
        active_deadlines, boundaries, disposals, returned, executed = {}, [], [], [], []
        owner_thread = get_ident()
        drive = stop = None
        engine = disposal_listener = owner = None
        try:
            assert (await composition.start()).status is mode
            runtime, runner = composition._runtime, composition._runner_task
            state = runtime._run_deadline.__self__
            pipeline, control, clock = state._pipeline, runtime._request_controller, runtime._clock
            engine = state._engine
            generation = runtime.runtime_generation
            assert (pipeline._stock_semantics is None) is (mode is RuntimeServiceStatus.RUNNING)
            assert pipeline._index_semantics is not None
            assert runtime._accepting_work is (mode is RuntimeServiceStatus.RUNNING)
            assert runtime._shutdown_timeout_seconds == 5.0
            assert sdk.calls == [] and _checkpoint_rows(database) == seeded
            startup_due = runtime.health().next_retry_at
            if wait is None:
                assert await clock.park(failed=runner.done)
                assert clock.parked[0] == due
            else:
                assert startup_due == NOW + timedelta(seconds=30)
                assert runtime.health().degraded_reason == "REFERENCE_REFRESH_FAILED"
                assert state._stage_errors["trading_calendar"] == "REFERENCE_BLOCKED_PERMISSION"
                assert await wait.park() == due
                assert clock.sleep_calls == []
            before = _business_rows(database)
            original_deadline = runtime._run_deadline
            original_sdk = sdk._historical_index_minutes
            original_proof = pipeline.index_provider.probe_historical_minutes_permission
            original_begin_shutdown = runtime.begin_shutdown
            shutdown_at = []

            async def observe_deadline(deadline):
                task = asyncio.current_task()
                assert task in runtime._work_tasks
                assert deadline.kind is DeadlineKind.INDEX_PERMISSION
                assert runtime.status is mode
                assert runtime._accepting_work is (mode is RuntimeServiceStatus.RUNNING)
                executed.append(deadline)
                active_deadlines[task] = deadline
                try:
                    return await original_deadline(deadline)
                except asyncio.CancelledError:
                    boundaries.append("owner-cancelled")
                    owner_cancelled.set()
                    raise
                finally:
                    del active_deadlines[task]

            def held_sdk(kwargs):
                assert get_ident() != owner_thread
                assert kwargs["ts_code"] == MarketIndexCode.SSE_COMPOSITE.value
                assert clock.now() == due
                entered.set()
                assert release.wait(15), "test did not release the physical proof"
                frame = original_sdk(kwargs)
                returned.append(frame)
                boundaries.append("sdk-returned")
                return frame

            def observe_proof(*args, **kwargs):
                result = original_proof(*args, **kwargs)
                boundaries.append("valid-proof-returned")
                return result

            def observe_begin_shutdown():
                original_begin_shutdown()
                if not shutdown_published.is_set():
                    # Synchronous observation before composition.stop can cancel
                    # anything. Permission authority is revoked by the existing
                    # lifecycle/controller gates, not a fabricated recovery token.
                    assert not runtime.business_commit_admission_open
                    assert not pipeline._generation_current()
                    assert control._closed
                    assert owner.cancelling() == runner.cancelling() == 0
                    assert not owner.done()
                    shutdown_at.append(asyncio.get_running_loop().time())
                    boundaries.append("admission-before-cancel")
                    shutdown_published.set()

            def observe_disposal(_engine):
                disposals.append((
                    release.is_set(), control.active_count, control.waiting_count,
                    len(control._permission_rechecks), owner is not None and owner.done(),
                ))
                boundaries.append("database-disposed")

            monkeypatch.setattr(runtime, "_run_deadline", observe_deadline)
            monkeypatch.setattr(sdk, "_historical_index_minutes", held_sdk)
            monkeypatch.setattr(
                pipeline.index_provider, "probe_historical_minutes_permission", observe_proof,
            )
            event.listen(engine, "engine_disposed", observe_disposal)
            disposal_listener = observe_disposal
            if wait is None:
                drive = asyncio.create_task(clock.drive(
                    due, stop_when=entered.is_set,
                    failed=lambda: composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED",
                ))
            else:
                # Only release the genuine lifecycle retry wait. Its own loop
                # selects calendar, then the due historical sibling, without a
                # direct maintenance call or enabling ordinary market work.
                await wait.release(composition)
            async with asyncio.timeout(3):
                while not entered.is_set():
                    assert drive is None or not drive.done(), "owner did not enter permission SDK"
                    assert not runner.done() and not composition._runner_failed
                    await asyncio.sleep(0.005)
            (owner, deadline), = active_deadlines.items()
            assert deadline.kind is DeadlineKind.INDEX_PERMISSION and deadline.due_at == due
            assert owner in runtime._work_tasks and not owner.done()
            assert pipeline._running_deadline is False
            assert pipeline._permission_maintenance_lock.locked()
            assert control.active_count == 1 and control.waiting_count == 0
            probe = control._permission_rechecks[SCOPE]
            assert not probe.done()
            assert pipeline._permission_rotation_state.last_operation is SCOPE
            reserved = due + timedelta(seconds=300)
            assert control.is_permission_blocked(SCOPE)
            assert control.raw_permission_retry_at(SCOPE) == reserved
            persisted = _checkpoint_rows(database)
            assert persisted == ((
                "permission", SCOPE.value, reserved.isoformat(), 0, "BLOCKED_PERMISSION",
            ),)
            assert persisted != seeded and _business_rows(database) == before
            assert composition.health().status is mode
            assert runtime._accepting_work is (mode is RuntimeServiceStatus.RUNNING)
            assert runtime.business_commit_admission_open and pipeline._generation_current()
            assert runtime.health().next_retry_at == startup_due
            assert composition.health().runtime_generation == generation
            expected_calls = ("idx_mins",) if wait is None else ("trade_cal", "idx_mins")
            assert tuple(name for name, _ in sdk.calls) == expected_calls
            assert len(executed) == len(expected_calls)
            assert all(item.kind is DeadlineKind.INDEX_PERMISSION for item in executed)
            if wait is not None:
                assert not control.is_permission_blocked(TushareOperation.TRADING_CALENDAR)
                assert clock.sleep_calls == []  # No normal market scheduling while DEGRADED.
                assert state._pipeline is pipeline and before["minute_bar"]
            calls = tuple(sdk.calls)

            monkeypatch.setattr(runtime, "begin_shutdown", observe_begin_shutdown)
            stop = asyncio.create_task(composition.stop())
            await asyncio.wait_for(shutdown_published.wait(), timeout=2)
            # Keep the genuine five-second graceful-drain period. Cancellation
            # releases the logical owner/lock, not the controller's physical slot.
            await asyncio.wait_for(owner_cancelled.wait(), timeout=8)
            assert asyncio.get_running_loop().time() - shutdown_at[0] >= 5.0
            assert owner.cancelling() and not stop.done()
            assert not pipeline._permission_maintenance_lock.locked()
            assert not probe.done() and control.active_count == 1 and control.waiting_count == 0
            assert runtime._database_opened
            assert state._database_status is RuntimeResourceStatus.READY
            assert not returned and not disposals
            assert _checkpoint_rows(database) == persisted and _business_rows(database) == before
            assert tuple(sdk.calls) == calls
            assert composition._runtime is runtime and composition._runner_task is runner
            assert runtime.runtime_generation == generation
            assert not composition._runner_failed and not composition._restart_pending

            release.set()
            await asyncio.wait_for(asyncio.shield(stop), timeout=8)
            assert len(returned) == 1 and len(returned[0]) == 48
            assert boundaries == [
                "admission-before-cancel", "owner-cancelled", "sdk-returned",
                "valid-proof-returned", "database-disposed",
            ]
            assert probe.done() and not probe.cancelled()
            rejection = probe.exception()
            assert isinstance(rejection, RequestControlError)
            assert rejection.code is RequestControlErrorCode.INVALID_RESPONSE
            assert control.is_permission_blocked(SCOPE)
            assert control.raw_permission_retry_at(SCOPE) == reserved
            assert _checkpoint_rows(database) == persisted and _business_rows(database) == before
            assert tuple(sdk.calls) == calls
            assert disposals == [(True, 0, 0, 0, True)]
            assert owner.done() and runner.done() and not active_deadlines
            assert not runtime._work_tasks and not control._permission_rechecks
            assert control.active_count == control.waiting_count == 0
            assert not runtime._database_opened
            assert state._database_status is RuntimeResourceStatus.STOPPED
            assert runtime.health().status is RuntimeServiceStatus.STOPPED
            assert runtime.health().runtime_generation == generation
            assert composition._runtime is runtime and composition._runner_task is None
            assert not composition._runner_failed and not composition._restart_pending
            assert not runtime.unexpected_run_exit and not runtime.cleanup_failed
        finally:
            release.set()
            if drive is not None:
                if not drive.done():
                    drive.cancel()
                await asyncio.gather(drive, return_exceptions=True)
            if stop is not None:
                await asyncio.gather(stop, return_exceptions=True)
            await composition.stop()
            if disposal_listener is not None:
                event.remove(engine, "engine_disposed", disposal_listener)

    asyncio.run(scenario())
