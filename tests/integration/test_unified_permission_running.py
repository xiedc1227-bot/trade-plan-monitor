"""UPD-S4 real RUNNING scheduler integration; DEGRADED belongs to S5."""

import asyncio
from datetime import timedelta
from threading import Event

import pytest
import test_production_certification_gate as certification_fixture
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_index_daily_permission_maintenance import _one_official_index_day
from test_production_index_historical_permission_probe import _complete_index_day
from test_s3_permission_reservation_process import _business_rows, _checkpoint_rows
from test_s3_startup_minute_coverage import _DeadlineClock

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.production import _PERMISSION_SCOPES, PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import TushareOperation
from trade_plan_monitor.runtime.scheduler import DeadlineKind


def _composition(tmp_path, monkeypatch, *, stock=True):
    monkeypatch.setattr(certification_fixture, "ControlledClock", _DeadlineClock)
    composition, sdk, _ = certification_fixture._composition(
        tmp_path, monkeypatch, active_plan=stock, include_index=True,
        stock_certification=stock, persisted_calendar=True,
    )
    _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
    monkeypatch.setattr(sdk, "_historical_index_minutes", lambda _: _complete_index_day(
        MarketIndexCode.SSE_COMPOSITE, ANCHOR,
    ))
    monkeypatch.setattr(sdk, "_index_daily", lambda kwargs: _one_official_index_day(
        MarketIndexCode(kwargs["ts_code"]), ANCHOR,
    ))
    return composition, sdk


async def _drive_live(composition, through, *, stop_when=lambda: False):
    """Publish the real same-owner heartbeat before each bounded virtual wake."""
    runtime = composition._runtime
    clock = runtime._clock
    state = runtime._probe_capabilities.__self__
    async with asyncio.timeout(15):
        while clock.parked[0] <= through and not stop_when():
            clock.current = max(clock.current, clock.parked[0])
            await state.heartbeat()
            released = clock.released
            await clock.drive(
                through, stop_when=lambda before=released: clock.released > before,
                failed=lambda: composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED",
            )
            assert composition.health().degraded_reason != "RUNTIME_RUNNER_FAILED"


@pytest.mark.parametrize("late_session,release_minute,release_second,expected", [
    (False, 6, 13, 1), (False, 7, 13, 0), (True, 31, 31, 0),
])
def test_actual_permission_sdk_overrun_preserves_original_market_review(
    tmp_path, monkeypatch, late_session, release_minute, release_second, expected,
):
    async def scenario():
        composition, sdk = _composition(tmp_path, monkeypatch, stock=False)
        entered, release = Event(), Event()
        try:
            assert (await composition.start()).status.value == "RUNNING"
            runtime = composition._runtime
            state = runtime._run_deadline.__self__
            control, clock = runtime._request_controller, runtime._clock
            assert await clock.park()
            if late_session:
                clock.current = clock.now().replace(hour=11, minute=24)
                await state.heartbeat()
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            due = control.raw_permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            await _drive_live(composition, due - timedelta(microseconds=1))
            original_sdk, original_deadline = sdk._historical_index_minutes, runtime._run_deadline
            original_review = type(runtime._scheduler).elapsed_market_deadlines
            physical, executed, reviews, failures, permission_results = [], [], [], [], []
            cursor = runtime._last_deadline_at
            generation, runner = runtime.runtime_generation, composition._runner_task

            def hold(kwargs):
                physical.append(clock.now())
                assert control.active_count == 1
                entered.set()
                assert release.wait(5)
                return original_sdk(kwargs)

            def review(scheduler, *, after, through):
                reviews.append((after, through))
                return original_review(scheduler, after=after, through=through)

            async def record(deadline):
                executed.append((deadline, clock.now()))
                try:
                    if deadline.kind is DeadlineKind.INDEX_PERMISSION:
                        assert asyncio.current_task() in runtime._work_tasks
                        before, calls = _business_rows(tmp_path / "monitor.sqlite3"), len(sdk.calls)
                        assert runtime._last_deadline_at == cursor
                        result = await original_deadline(deadline)
                        assert _business_rows(tmp_path / "monitor.sqlite3") == before
                        assert len(sdk.calls) == calls + 1
                        assert runtime._last_deadline_at == cursor
                        permission_results.append(result)
                        return result
                    return await original_deadline(deadline)
                except Exception as error:
                    failures.append(error)
                    raise

            monkeypatch.setattr(sdk, "_historical_index_minutes", hold)
            monkeypatch.setattr(type(runtime._scheduler), "elapsed_market_deadlines", review)
            runtime._run_deadline = record
            driving = asyncio.create_task(_drive_live(composition, due))
            assert await asyncio.to_thread(entered.wait, 5)
            assert physical == [due]
            target = due.replace(second=0) + timedelta(minutes=1)
            assert target + timedelta(seconds=12) - physical[0] > timedelta(seconds=31.25)
            clock.current = due.replace(minute=release_minute, second=release_second)
            await state.heartbeat()
            release.set()
            await driving
            if failures:
                raise failures[0]
            assert len(permission_results) == 1
            markets = [(item, at) for item, at in executed
                       if item.kind is DeadlineKind.REALTIME_MINUTE]
            assert len(markets) == expected
            if expected:
                assert markets[0][0].bar_end == target
                assert markets[0][1] == target + timedelta(seconds=13)
                assert runtime._last_deadline_at == target + timedelta(seconds=12)
            else:
                assert runtime._last_deadline_at == cursor
            assert (cursor, clock.now()) in reviews
            assert runtime.runtime_generation == generation
            assert composition._runner_task is runner
            assert composition.health().status.value == "RUNNING"
        finally:
            release.set()
            await composition.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("stock", [True, False])
def test_running_real_scheduler_repairs_all_eight_scopes_without_business_writes(
    tmp_path, monkeypatch, stock,
):
    async def scenario():
        composition, sdk = _composition(tmp_path, monkeypatch, stock=stock)
        try:
            assert (await composition.start()).status.value == "RUNNING"
            runtime = composition._runtime
            state = runtime._run_deadline.__self__
            pipe, control, clock = state._pipeline, runtime._request_controller, runtime._clock
            generation, runner = runtime.runtime_generation, composition._runner_task
            assert await clock.park()
            scopes = _PERMISSION_SCOPES if stock else tuple(
                op for op in _PERMISSION_SCOPES if op.value.startswith("index_")
            )
            for operation in scopes:
                await _block(control, operation)
            raw = control.raw_permission_retry_at(scopes[0])
            assert all(control.raw_permission_retry_at(op) == raw for op in scopes)
            completed = []
            observed = []
            failures = []
            acknowledgments = []
            original_ack = pipe._permission_probe_reservation_callback
            def callback(candidate):
                acknowledge = original_ack(candidate)
                def ack():
                    acknowledge()
                    acknowledgments.append(candidate.operation)
                return ack
            monkeypatch.setattr(pipe, "_permission_probe_reservation_callback", callback)
            original = runtime._run_deadline
            async def record(deadline):
                observed.append((deadline, clock.now()))
                if deadline.kind is not DeadlineKind.INDEX_PERMISSION:
                    return await original(deadline)
                assert asyncio.current_task() in runtime._work_tasks
                assert pipe._running_deadline is False
                before, count = _business_rows(tmp_path / "monitor.sqlite3"), len(sdk.calls)
                blocked = {op for op in _PERMISSION_SCOPES if control.is_permission_blocked(op)}
                ack_count = len(acknowledgments)
                def forbidden(*_args, **_kwargs):
                    pytest.fail("permission maintenance invoked business evaluation/delivery")
                with monkeypatch.context() as guard:
                    guard.setattr(type(pipe.coordinator), "run_deadline", forbidden)
                    if state._dispatcher is not None:
                        guard.setattr(type(state._dispatcher), "dispatch_pending", forbidden)
                    result = await original(deadline)
                assert result is PermissionMaintenanceResult.PROBED
                selected = pipe._permission_rotation_state.last_operation
                assert acknowledgments[ack_count:] == [selected]
                assert len(sdk.calls) == count + 1
                assert {op for op in _PERMISSION_SCOPES if control.is_permission_blocked(op)} == (
                    blocked - {selected}
                )
                assert _business_rows(tmp_path / "monitor.sqlite3") == before
                assert runtime.runtime_generation == generation
                assert composition._runner_task is runner
                completed.append(selected)
                return result
            async def supervise(deadline):
                try:
                    return await record(deadline)
                except Exception as error:
                    failures.append(error)
                    raise
            runtime._run_deadline = supervise
            # Release the existing real wait after a clock jump; do not fabricate a duty.
            clock.current = raw
            await state.heartbeat()
            def same_owner():
                assert composition._runtime is runtime
                assert composition._runner_task is runner
                assert not runner.done()
                assert runtime.runtime_generation == generation
                assert composition.health().status.value == "RUNNING"
            async with asyncio.timeout(10):
                await clock.drive(
                    raw + timedelta(seconds=1),
                    stop_when=lambda: len(completed) == len(scopes),
                    failed=lambda: composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED",
                    after_wake=same_owner,
                )
            if runner.done() and not runner.cancelled() and runner.exception() is not None:
                raise runner.exception()
            if failures:
                raise failures[0]
            assert completed == list(scopes), (
                observed, clock.parked, composition.health(), pipe.next_permission_probe_due_at(),
            )
            assert composition.health().status.value == "RUNNING"
            assert pipe.next_permission_probe_due_at() is None
            if not stock:
                assert all(name not in {"rt_min", "rt_min_daily", "daily", "stk_limit"}
                           for name, _ in sdk.calls)
        finally:
            await composition.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("after_due", [False, True])
def test_composition_permission_timing_adapter_is_pure_and_eight_scope(
    tmp_path, monkeypatch, after_due,
):
    async def scenario():
        composition, sdk = _composition(tmp_path, monkeypatch)
        try:
            assert (await composition.start()).status.value == "RUNNING"
            runtime = composition._runtime
            state = runtime._run_deadline.__self__
            pipe, control = state._pipeline, runtime._request_controller
            assert await runtime._clock.park()
            await _block(control, _PERMISSION_SCOPES[0])
            expected = control.raw_permission_retry_at(_PERMISSION_SCOPES[0])
            runtime._clock.current = expected + timedelta(seconds=1 if after_due else -1)
            before = tuple(sdk.calls), pipe._permission_rotation_state
            def forbidden(*_args, **_kwargs):
                pytest.fail("pure adapter performed clock/SQL/authority or bootstrap work")
            with monkeypatch.context() as guard:
                for name in (
                    "next_historical_index_permission_due_at",
                    "next_realtime_index_permission_due_at",
                    "_permission_probe_state", "_stock_certification_current",
                    "_index_certification_current", "_permission_session_factory", "_work",
                ):
                    guard.setattr(pipe, name, forbidden)
                guard.setattr(type(runtime._clock), "now", forbidden)
                for _ in range(3):
                    assert state.next_index_permission_at() == expected
                    assert pipe.next_permission_probe_due_at() == expected
            assert (tuple(sdk.calls), pipe._permission_rotation_state) == before
        finally:
            await composition.stop()
    asyncio.run(scenario())


def test_absent_pipeline_permission_getter_does_not_bootstrap(tmp_path, monkeypatch):
    composition, _ = _composition(tmp_path, monkeypatch)
    state = composition._runtime._probe_capabilities.__self__
    assert state._pipeline is None
    for _ in range(3):
        assert state.next_index_permission_at() is None
    assert state._pipeline is None


def test_actual_equal_due_market_runs_before_permission(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk = _composition(tmp_path, monkeypatch, stock=False)
        try:
            assert (await composition.start()).status.value == "RUNNING"
            runtime = composition._runtime
            clock, control = runtime._clock, runtime._request_controller
            assert await clock.park()
            await _drive_live(composition, clock.now().replace(minute=1, second=12))
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            due = control.raw_permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            events, errors = [], []
            original = runtime._run_deadline

            async def record(deadline):
                events.append((deadline, clock.now()))
                try:
                    if deadline.kind is DeadlineKind.INDEX_PERMISSION:
                        before = _business_rows(tmp_path / "monitor.sqlite3")
                        assert asyncio.current_task() in runtime._work_tasks
                        result = await original(deadline)
                        assert result is PermissionMaintenanceResult.PROBED
                        assert _business_rows(tmp_path / "monitor.sqlite3") == before
                        return result
                    return await original(deadline)
                except Exception as error:
                    errors.append(error)
                    raise

            runtime._run_deadline = record
            await _drive_live(composition, due + timedelta(microseconds=1))
            if errors:
                raise errors[0]
            at_boundary = [(d, at) for d, at in events if at >= due]
            assert [d.kind for d, _ in at_boundary] == [
                DeadlineKind.REALTIME_MINUTE, DeadlineKind.INDEX_PERMISSION,
            ]
            assert at_boundary[0][0].due_at == due
            assert at_boundary[0][0].bar_end == due - timedelta(seconds=12)
            assert at_boundary[1][1] == due + timedelta(microseconds=1)
            assert runtime._last_deadline_at == due
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
            assert not control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
        finally:
            await composition.stop()
    asyncio.run(scenario())


def test_actual_queued_permission_reserve_veto_keeps_durable_ack_and_market_target(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk = _composition(tmp_path, monkeypatch, stock=False)
        entered, release = Event(), Event()
        hold_task = None
        try:
            assert (await composition.start()).status.value == "RUNNING"
            runtime = composition._runtime
            state = runtime._run_deadline.__self__
            clock, control, pipe = runtime._clock, runtime._request_controller, state._pipeline
            assert await clock.park()
            clock.current = clock.now().replace(second=35)
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            due = control.raw_permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            await _drive_live(composition, due - timedelta(microseconds=1))
            results, acks, executed, errors = [], [], [], []
            original_ack = pipe._permission_probe_reservation_callback
            original = runtime._run_deadline

            def callback(candidate):
                acknowledge = original_ack(candidate)
                def ack():
                    acknowledge()
                    acks.append(candidate.operation)
                return ack

            async def record(deadline):
                executed.append(deadline)
                try:
                    if deadline.kind is DeadlineKind.INDEX_PERMISSION:
                        before = _business_rows(tmp_path / "monitor.sqlite3")
                        assert asyncio.current_task() in runtime._work_tasks
                        result = await original(deadline)
                        assert _business_rows(tmp_path / "monitor.sqlite3") == before
                        results.append(result)
                        return result
                    return await original(deadline)
                except Exception as error:
                    errors.append(error)
                    raise

            def hold():
                entered.set()
                assert release.wait(5)

            monkeypatch.setattr(pipe, "_permission_probe_reservation_callback", callback)
            runtime._run_deadline = record
            hold_task = asyncio.create_task(control.execute(
                TushareOperation.INDEX_DAILY, hold, work_key="s4-queued-reserve-control",
            ))
            assert await asyncio.to_thread(entered.wait, 5)
            driving = asyncio.create_task(_drive_live(composition, due))
            async with asyncio.timeout(5):
                while control.waiting_count == 0:
                    await asyncio.sleep(0.005)
            reserved = control.raw_permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert reserved == due + timedelta(seconds=300)
            durable = _checkpoint_rows(tmp_path / "monitor.sqlite3")
            assert acks == [TushareOperation.INDEX_HISTORICAL_MINUTES]
            clock.current = due + timedelta(seconds=8)
            market_due = due.replace(minute=6, second=12)
            assert clock.now() - due <= timedelta(seconds=15)
            assert timedelta(0) < market_due - clock.now() < timedelta(seconds=31.25)
            release.set()
            await hold_task
            await driving
            if errors:
                raise errors[0]
            assert results == [PermissionMaintenanceResult.DEFERRED]
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert control.raw_permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES,
            ) == reserved
            assert _checkpoint_rows(tmp_path / "monitor.sqlite3") == durable
            assert acks == [TushareOperation.INDEX_HISTORICAL_MINUTES]
            await _drive_live(composition, market_due)
            markets = [d for d in executed if d.kind is DeadlineKind.REALTIME_MINUTE]
            assert len(markets) == 1
            assert markets[0].due_at == market_due
            assert markets[0].bar_end == market_due - timedelta(seconds=12)
            assert len(results) == 1
        finally:
            release.set()
            if hold_task is not None:
                await asyncio.gather(hold_task, return_exceptions=True)
            await composition.stop()
    asyncio.run(scenario())
