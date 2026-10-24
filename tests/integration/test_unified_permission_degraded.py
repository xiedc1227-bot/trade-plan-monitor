"""UPD-S5 fixed startup/permission clocks and actual DEGRADED ownership."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError
from test_live_pipeline_acceptance import _sample_plan
from test_runtime_lifecycle import (
    _AsyncCloser,
    _Clock,
    _healthy_runtime_details,
    _ready_capabilities,
    _Scheduler,
    _SyncCloser,
)
from test_s3_permission_reservation_process import IDENTITY, _business_rows
from test_unified_permission_running import _composition as _running_composition

from trade_plan_monitor.market_data.models import MinuteBar, ProviderCapabilityStatus
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import _PERMISSION_SCOPES, PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind
from trade_plan_monitor.runtime.service import RuntimeLifecycleService, _RetryWaitOutcome
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository, RecoveryCheckpoint
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web import monitor_composition

CURRENT_SCOPES = tuple(
    operation for operation in _PERMISSION_SCOPES
    if operation is not TushareOperation.DAILY_LIMITS
)


class _RetryWait:
    """Release the actual lifecycle retry wait without substituting owner work."""

    def __init__(self, clock):
        self.clock = clock
        self.waits = asyncio.Queue()
        self.parked = None

    async def __call__(self, shutdown, delay):
        permit = asyncio.get_running_loop().create_future()
        await self.waits.put((self.clock.now() + timedelta(seconds=delay), permit))
        stopped = asyncio.create_task(shutdown.wait())
        try:
            await asyncio.wait((permit, stopped), return_when=asyncio.FIRST_COMPLETED)
            return _RetryWaitOutcome.SHUTDOWN if shutdown.is_set() else _RetryWaitOutcome.TIMEOUT
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)

    async def park(self):
        async with asyncio.timeout(5):
            self.parked = await self.waits.get()
        return self.parked[0]

    async def release(self, composition):
        deadline, permit = self.parked
        self.clock.current = max(self.clock.current, deadline)
        await composition._runtime._probe_capabilities.__self__.heartbeat()
        permit.set_result(None)


def _degraded_composition(tmp_path, monkeypatch, *, scopes=_PERMISSION_SCOPES, seconds=1):
    composition, sdk = _running_composition(tmp_path, monkeypatch, stock=True)
    clock = composition._runtime._clock
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    try:
        sessions = create_session_factory(engine)
        ProviderRecoveryRepository(sessions, provider_identity=IDENTITY).save(
            tuple(
                RecoveryCheckpoint(
                    "permission", scope.value, clock.now() + timedelta(seconds=seconds), 0
                )
                for scope in scopes
            ),
        )
        # Legal committed prefix makes startup's blocked-minute path a zero-fetch
        # success; the real blocked reference request is the DEGRADED cause.
        with SqlAlchemyUnitOfWork(sessions) as work:
            work.history.upsert_minutes(
                tuple(
                    MinuteBar(
                        symbol=_sample_plan().symbol,
                        bar_end=clock.now().replace(hour=9, minute=30, second=0)
                        + timedelta(minutes=i),
                        open_fen=6400,
                        high_fen=6410,
                        low_fen=6390,
                        close_fen=6405,
                        volume_shares=1000,
                        amount_yuan=Decimal("64000"),
                        received_at=clock.now(),
                    )
                    for i in range(1, 31)
                )
            )
            work.commit()
    finally:
        engine.dispose()
    wait = _RetryWait(clock)
    composition._runtime._retry_wait = wait
    return composition, sdk, wait


def test_real_degraded_current_permission_wakes_retain_owner_then_startup_restores(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, wait = _degraded_composition(
            tmp_path, monkeypatch, scopes=CURRENT_SCOPES
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runtime, runner = composition._runtime, composition._runner_task
            state = runtime._probe_capabilities.__self__
            pipe, control, clock = state._pipeline, runtime._request_controller, runtime._clock
            generation, lock = runtime.runtime_generation, pipe._permission_maintenance_lock
            startup_due = runtime.health().next_retry_at
            initial = clock.now()
            assert startup_due == initial + timedelta(seconds=30)
            assert await wait.park() == initial + timedelta(seconds=1)
            completed, failures = [], []
            original = runtime._run_deadline

            async def record(deadline):
                try:
                    assert deadline.kind is DeadlineKind.INDEX_PERMISSION
                    assert asyncio.current_task() in runtime._work_tasks
                    assert runtime._accepting_work is False
                    before = _business_rows(tmp_path / "monitor.sqlite3")
                    calls = len(sdk.calls)
                    blocked = {op for op in _PERMISSION_SCOPES if control.is_permission_blocked(op)}
                    result = await original(deadline)
                    selected = pipe._permission_rotation_state.last_operation
                    assert result is PermissionMaintenanceResult.PROBED
                    assert len(sdk.calls) == calls + 1
                    assert {
                        op for op in _PERMISSION_SCOPES if control.is_permission_blocked(op)
                    } == (blocked - {selected})
                    assert _business_rows(tmp_path / "monitor.sqlite3") == before
                    assert runtime.health().next_retry_at == startup_due
                    assert runtime.status is RuntimeServiceStatus.DEGRADED
                    assert runtime._accepting_work is False
                    assert runtime.runtime_generation == generation
                    assert composition._runner_task is runner
                    assert state._pipeline is pipe and pipe._permission_maintenance_lock is lock
                    completed.append(selected)
                    return result
                except Exception as error:
                    failures.append(error)
                    raise

            runtime._run_deadline = record
            await wait.release(composition)
            assert await wait.park() == startup_due
            if failures:
                raise failures[0]
            assert completed == list(CURRENT_SCOPES)
            assert runtime.status is RuntimeServiceStatus.DEGRADED
            public_health = await composition.read_service.get_health()
            assert public_health.status is RuntimeServiceStatus.DEGRADED and public_health.read_only
            assert public_health.next_retry_at == startup_due
            assert public_health.block_reason is None
            dashboard = await composition.read_service.get_dashboard()
            assert dashboard.availability == "UNAVAILABLE"
            assert dashboard.reason.value == "AWAITING_FIRST_EVALUATION"
            assert (
                await composition.read_service.get_symbol_health(symbol=_sample_plan().symbol)
                is None
            )
            frame = composition.websocket_service._heartbeat_frame(dashboard.sequence)
            assert frame["runtimeLive"] is False and frame["runtimeGeneration"] is None
            rotation = pipe._permission_rotation_state
            deferred = dict(pipe._permission_probe_deferred_until)
            runtime._run_deadline = original
            await wait.release(composition)
            assert await clock.park(failed=runner.done)
            assert runtime.status is RuntimeServiceStatus.RUNNING
            assert runtime._accepting_work is True
            assert composition._runtime is runtime and composition._runner_task is runner
            assert runtime.runtime_generation == generation
            assert state._pipeline is pipe and pipe._permission_maintenance_lock is lock
            assert pipe._permission_rotation_state == rotation
            assert pipe._permission_probe_deferred_until == deferred
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("related", [True, False])
def test_real_permission_failure_extends_only_its_related_startup_floor(
    tmp_path,
    monkeypatch,
    related,
):
    async def scenario():
        calendar, history = (
            TushareOperation.TRADING_CALENDAR,
            TushareOperation.INDEX_HISTORICAL_MINUTES,
        )
        composition, sdk, wait = _degraded_composition(
            tmp_path,
            monkeypatch,
            scopes=(calendar, history),
        )
        failed_operation = calendar if related else history
        endpoint = "_calendar" if related else "_historical_index_minutes"

        def denied(_kwargs):
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "offline proof denied")

        monkeypatch.setattr(sdk, endpoint, denied)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runtime = composition._runtime
            initial = runtime._clock.now()
            control = runtime._request_controller
            assert runtime.health().degraded_reason == "REFERENCE_REFRESH_FAILED"
            assert runtime.health().next_retry_at == initial + timedelta(seconds=30)
            assert await wait.park() == initial + timedelta(seconds=1)
            await wait.release(composition)
            next_wake = await wait.park()
            assert control.is_permission_blocked(failed_operation)
            assert control.raw_permission_retry_at(failed_operation) == initial + timedelta(
                seconds=301
            )
            expected = initial + timedelta(seconds=301 if related else 30)
            assert runtime.health().next_retry_at == expected
            assert next_wake == expected
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_real_heartbeat_revocation_during_retry_wait_requires_explicit_stop(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, wait = _degraded_composition(tmp_path, monkeypatch)
        runtime = composition._runtime
        runtime._heartbeat_interval_seconds = 0.01
        config = tmp_path / "config/app.yaml"
        original_config = config.read_text(encoding="utf-8")
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runner, generation = composition._runner_task, runtime.runtime_generation
            state = runtime._probe_capabilities.__self__
            pipe = state._pipeline
            assert await wait.park()
            before = _business_rows(tmp_path / "monitor.sqlite3")
            calls = tuple(sdk.calls)
            config.write_text(
                original_config.replace("offline-test-token", "offline-new-token"), encoding="utf-8"
            )
            assert await asyncio.to_thread(state.configuration_is_current) is False
            async with asyncio.timeout(5):
                while runtime._block_reason != "NEEDS_RESTART":
                    await asyncio.sleep(0.005)
            assert runtime.status is RuntimeServiceStatus.BLOCKED
            # Release the already-issued wait only after the actual heartbeat
            # has published BLOCKED; this must not be treated as normal exit.
            prior_shutdown = runtime._shutdown_requested_event
            # The real heartbeat loop is already running in this case; do not
            # concurrently publish a second manual liveness revision.
            runtime._clock.current = wait.parked[0]
            wait.parked[1].set_result(None)
            async with asyncio.timeout(5):
                while runtime._shutdown_requested_event is prior_shutdown and not runner.done():
                    await asyncio.sleep(0.005)
            assert not runner.done()
            assert not runtime._stopping and not runtime._cleanup_complete
            assert composition._runtime is runtime and composition._runner_task is runner
            assert runtime.runtime_generation == generation and state._pipeline is pipe
            assert runtime.health().next_retry_at is None
            assert runtime.status is RuntimeServiceStatus.BLOCKED
            assert _business_rows(tmp_path / "monitor.sqlite3") == before
            assert tuple(sdk.calls) == calls
            config.write_text(original_config, encoding="utf-8")
            assert state.configuration_is_current() is False
            assert not runtime._accepting_work and not runner.done()
        finally:
            config.write_text(original_config, encoding="utf-8")
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure_code", [TushareErrorCode.BLOCKED_PERMISSION, TushareErrorCode.RATE_LIMITED]
)
def test_real_both_due_retries_startup_once_then_permission_failure_extends_floor(
    tmp_path,
    monkeypatch,
    failure_code,
):
    async def scenario():
        calendar = TushareOperation.TRADING_CALENDAR
        composition, sdk, wait = _degraded_composition(
            tmp_path,
            monkeypatch,
            scopes=(calendar,),
            seconds=300,
        )

        def denied(_kwargs):
            raise TushareProviderError(failure_code, "offline proof failure")

        monkeypatch.setattr(sdk, "_calendar", denied)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runtime, runner = composition._runtime, composition._runner_task
            clock, control = runtime._clock, runtime._request_controller
            state = runtime._probe_capabilities.__self__
            pipe, generation = state._pipeline, runtime.runtime_generation
            lock = pipe._permission_maintenance_lock
            initial = clock.now()
            first_due = initial + timedelta(seconds=300)
            assert runtime.health().next_retry_at == first_due
            assert await wait.park() == first_due
            rotation = pipe._permission_rotation_state
            deferred = dict(pipe._permission_probe_deferred_until)
            events, failures = [], []
            original_startup, original_permission = (
                runtime._recheck_degraded_startup,
                runtime._run_deadline,
            )

            async def startup():
                events.append(("startup", clock.now()))
                await original_startup()
                assert state._pipeline is pipe and pipe._permission_maintenance_lock is lock
                assert pipe._permission_rotation_state == rotation
                assert pipe._permission_probe_deferred_until == deferred

            async def permission(deadline):
                events.append(("permission", clock.now()))
                assert asyncio.current_task() in runtime._work_tasks
                assert deadline.kind is DeadlineKind.INDEX_PERMISSION
                before = _business_rows(tmp_path / "monitor.sqlite3")
                calls = len(sdk.calls)
                try:
                    result = await original_permission(deadline)
                    assert result is PermissionMaintenanceResult.FAILED
                    assert len(sdk.calls) == calls + 1
                    assert _business_rows(tmp_path / "monitor.sqlite3") == before
                    assert runtime.health().next_retry_at == first_due + timedelta(seconds=60)
                    return result
                except Exception as error:
                    failures.append(error)
                    raise

            runtime._recheck_degraded_startup, runtime._run_deadline = startup, permission
            await wait.release(composition)
            next_due = await wait.park()
            if failures:
                raise failures[0]
            assert events == [("startup", first_due), ("permission", first_due)]
            assert next_due == initial + timedelta(seconds=600)
            assert control.raw_permission_retry_at(calendar) == next_due
            if failure_code is TushareErrorCode.RATE_LIMITED:
                assert control.cooldown_until == next_due
            assert runtime.health().next_retry_at == next_due
            assert runtime.status is RuntimeServiceStatus.DEGRADED and not runtime._accepting_work
            assert composition._runtime is runtime and composition._runner_task is runner
            assert not runner.done() and not composition._runner_failed
            assert runtime.runtime_generation == generation and state._pipeline is pipe
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_real_degraded_permission_fatal_response_uses_existing_cleanup(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, wait = _degraded_composition(
            tmp_path,
            monkeypatch,
            scopes=(TushareOperation.TRADING_CALENDAR,),
        )

        def fatal(_kwargs):
            raise TushareProviderError(TushareErrorCode.ERROR, "offline fatal response")

        monkeypatch.setattr(sdk, "_calendar", fatal)
        restart_entered, allow_restart = asyncio.Event(), asyncio.Event()

        async def controlled_restart(delay):
            assert delay == 1.0
            restart_entered.set()
            await allow_restart.wait()

        composition._restart_sleep = controlled_restart
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runtime, runner = composition._runtime, composition._runner_task
            captured = []
            original = runtime._run_deadline

            async def observe(deadline):
                assert deadline.kind is DeadlineKind.INDEX_PERMISSION
                assert asyncio.current_task() in runtime._work_tasks
                try:
                    return await original(deadline)
                except RequestControlError as error:
                    captured.append(error)
                    raise

            runtime._run_deadline = observe
            assert await wait.park()
            before = _business_rows(tmp_path / "monitor.sqlite3")
            await wait.release(composition)
            async with asyncio.timeout(5):
                await restart_entered.wait()
            assert len(captured) == 1 and captured[0].code is RequestControlErrorCode.ERROR
            assert captured[0].operation is TushareOperation.TRADING_CALENDAR
            assert captured[0].attempts == 1
            assert runtime.status is RuntimeServiceStatus.STOPPED and runtime._cleanup_complete
            assert _business_rows(tmp_path / "monitor.sqlite3") == before
            assert composition._runtime is runtime
            assert runtime.unexpected_run_exit and not runner.done()
            # SPEC-monitor-runtime admits DEGRADED owners into supervised recovery.
            # Cleanup is complete before a fresh owner may repeat startup checks.
            assert composition._restart_pending and composition._restart_attempts == 1
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_real_absent_pipeline_retries_only_startup_with_unchanged_configuration(
    tmp_path, monkeypatch
):
    async def scenario():
        from tushare.pro.client import DataApi

        clock = _Clock()
        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
        config = tmp_path / "app.yaml"
        config.write_text("{}\n", encoding="utf-8")
        calls = []

        def unexpected_sdk(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("unconfigured pipeline must never request a provider")

        monkeypatch.setattr(DataApi, "query", unexpected_sdk)
        composition = monitor_composition.create_monitor_composition(
            config_path=config,
            database_path=tmp_path / "monitor.sqlite3",
        )
        runtime = composition._runtime
        wait = _RetryWait(clock)
        runtime._retry_wait = wait
        maintenance, starts = [], []
        original_recheck = runtime._recheck_degraded_startup

        async def unexpected_maintenance(deadline):
            maintenance.append(deadline)
            raise AssertionError("absent pipeline cannot schedule permission or market work")

        async def recheck():
            starts.append(clock.now())
            return await original_recheck()

        runtime._run_deadline = unexpected_maintenance
        runtime._recheck_degraded_startup = recheck
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            initial, generation, runner = (
                clock.now(),
                runtime.runtime_generation,
                composition._runner_task,
            )
            state = runtime._probe_capabilities.__self__
            assert await wait.park() == initial + timedelta(seconds=30)
            for offset in (90, 210):
                assert state._pipeline is None and state.next_index_permission_at() is None
                await wait.release(composition)
                assert await wait.park() == initial + timedelta(seconds=offset)
                assert runtime.health().next_retry_at == initial + timedelta(seconds=offset)
                assert (
                    runtime.status is RuntimeServiceStatus.DEGRADED and not runtime._accepting_work
                )
                assert state._pipeline is None and state.next_index_permission_at() is None
                assert composition._runtime is runtime and composition._runner_task is runner
                assert not runner.done() and not composition._runner_failed
                assert runtime.runtime_generation == generation
            assert starts == [initial + timedelta(seconds=s) for s in (30, 90)]
            assert maintenance == calls == []
            assert config.read_text(encoding="utf-8") == "{}\n"
        finally:
            await composition.stop()

    asyncio.run(scenario())


def _service(*, clock, retry_wait, probe, run_deadline, **optional):
    events = []
    return RuntimeLifecycleService(
        clock=clock,
        validate_configuration=lambda: None,
        open_database=lambda: None,
        load_active_symbols=lambda: (),
        probe_capabilities=probe,
        refresh_references=lambda _date: None,
        recover_startup=lambda _date: None,
        scheduler=_Scheduler(),
        run_deadline=run_deadline,
        dispatcher=_AsyncCloser(events),
        request_controller=_SyncCloser(events),
        checkpoint_wal=lambda: None,
        close_database=lambda: None,
        health_details=_healthy_runtime_details,
        retry_wait=retry_wait,
        **optional,
    )


def _unavailable():
    return _ready_capabilities().model_copy(
        update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED},
    )


def test_published_startup_deadline_does_not_slide_when_run_enters_late():
    async def scenario():
        clock, waits = _Clock(), []
        initial = clock.now()

        async def wait(_stop, delay):
            waits.append((delay, service.health().next_retry_at))
            return _RetryWaitOutcome.SHUTDOWN

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=_unavailable,
            run_deadline=lambda _: pytest.fail("no maintenance configured"),
        )
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        assert service.health().next_retry_at == initial + timedelta(seconds=30)
        clock.current += timedelta(seconds=12)
        await service.run()
        assert waits == [(18.0, initial + timedelta(seconds=30))]

    asyncio.run(scenario())


def test_permission_wakes_do_not_slide_startup_or_publish_permission_as_retry():
    async def scenario():
        clock, waits, starts, maintenance = _Clock(), [], [], []
        initial = clock.now()
        permission_times = [initial + timedelta(seconds=s) for s in (5, 10, 15)]
        outcomes = iter(
            (
                PermissionMaintenanceResult.PROBED,
                PermissionMaintenanceResult.FAILED,
                PermissionMaintenanceResult.DEFERRED,
            )
        )

        def probe():
            starts.append(clock.now())
            if len(starts) > 1:
                clock.current += timedelta(seconds=7)
            return _unavailable()

        async def wait(_stop, delay):
            waits.append((delay, service.health().next_retry_at))
            if len(starts) == 2:
                return _RetryWaitOutcome.SHUTDOWN
            clock.current += timedelta(seconds=delay)
            return _RetryWaitOutcome.TIMEOUT

        async def run(deadline):
            assert asyncio.current_task() in service._work_tasks
            assert deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert not service._accepting_work
            maintenance.append((clock.now(), service.health().next_retry_at))
            permission_times.pop(0)
            return next(outcomes)

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=probe,
            run_deadline=run,
            next_permission_maintenance_at=lambda: next(iter(permission_times), None),
        )
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        await service.run()
        assert starts == [initial, initial + timedelta(seconds=30)]
        assert maintenance == [
            (initial + timedelta(seconds=s), initial + timedelta(seconds=30)) for s in (5, 10, 15)
        ]
        assert [delay for delay, _ in waits] == [5, 5, 5, 15, 60]
        assert waits[-1][1] == initial + timedelta(seconds=97)
        assert service._scheduler.calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("permission_second", [10, 30])
def test_degraded_tie_and_permission_overrun_do_not_replay_startup(permission_second):
    async def scenario():
        clock, events, waits = _Clock(), [], []
        initial = clock.now()
        permission_due = initial + timedelta(seconds=permission_second)

        def probe():
            events.append(("startup", clock.now()))
            return _unavailable()

        async def wait(_stop, delay):
            waits.append(delay)
            if any(name == "permission" for name, _ in events) and sum(
                name == "startup" for name, _ in events
            ) >= (3 if permission_second == 30 else 2):
                return _RetryWaitOutcome.SHUTDOWN
            clock.current += timedelta(seconds=delay)
            return _RetryWaitOutcome.TIMEOUT

        async def run(deadline):
            nonlocal permission_due
            assert deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert len(service._work_tasks) == 1
            events.append(("permission", clock.now()))
            permission_due = None
            clock.current += timedelta(seconds=70)
            return PermissionMaintenanceResult.PROBED

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=probe,
            run_deadline=run,
            next_permission_maintenance_at=lambda: permission_due,
        )
        await service.start()
        await service.run()
        expected = [("startup", initial)]
        if permission_second == 30:
            expected.append(("startup", initial + timedelta(seconds=30)))
        expected.extend(
            [
                ("permission", initial + timedelta(seconds=permission_second)),
                ("startup", initial + timedelta(seconds=permission_second + 70)),
            ]
        )
        assert events == expected
        assert service._scheduler.calls == 0
        assert all(delay > 0 for delay in waits)

    asyncio.run(scenario())


def test_full_startup_progression_uses_each_completion_and_caps_at_300():
    async def scenario():
        clock, starts, waits = _Clock(), [], []
        initial = clock.now()

        def probe():
            starts.append(clock.now())
            if len(starts) > 1:
                clock.current += timedelta(seconds=7)
            return _unavailable()

        async def wait(_stop, delay):
            waits.append(delay)
            if len(starts) == 6:
                return _RetryWaitOutcome.SHUTDOWN
            clock.current += timedelta(seconds=delay)
            return _RetryWaitOutcome.TIMEOUT

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=probe,
            run_deadline=lambda _: pytest.fail("no permission due"),
        )
        await service.run()
        assert waits == [30, 60, 120, 300, 300, 300]
        assert starts == [
            initial + timedelta(seconds=seconds) for seconds in (0, 30, 97, 224, 531, 838)
        ]

    asyncio.run(scenario())


def test_later_shared_floor_only_extends_fixed_startup_deadline():
    async def scenario():
        clock, starts, published = _Clock(), [], []
        initial = clock.now()
        permissions = [initial + timedelta(seconds=s) for s in (5, 10)]

        def probe():
            starts.append(clock.now())
            return _unavailable()

        async def wait(_stop, delay):
            published.append(service.health().next_retry_at)
            if len(starts) == 2:
                return _RetryWaitOutcome.SHUTDOWN
            clock.current += timedelta(seconds=delay)
            return _RetryWaitOutcome.TIMEOUT

        async def permission(_deadline):
            permissions.pop(0)
            # A later shared controller floor may extend startup; a subsequent
            # lower/expired floor cannot undo that already-published extension.
            service._request_controller.cooldown_until = initial + timedelta(
                seconds=100 if permissions else 20,
            )
            return PermissionMaintenanceResult.FAILED

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=probe,
            run_deadline=permission,
            next_permission_maintenance_at=lambda: next(iter(permissions), None),
        )
        await service.run()
        assert starts == [initial, initial + timedelta(seconds=100)]
        assert published[:3] == [initial + timedelta(seconds=s) for s in (30, 100, 100)]
        assert published[-1] == initial + timedelta(seconds=160)

    asyncio.run(scenario())


@pytest.mark.parametrize("has_floors", [True, False])
def test_initial_two_real_failures_retain_only_their_operation_floors(has_floors):
    async def scenario():
        clock, queried, waits = _Clock(), [], []
        initial = clock.now()
        calendar, history = (
            TushareOperation.TRADING_CALENDAR,
            TushareOperation.CURRENT_DAY_MINUTES,
        )

        def fail(operation):
            raise RequestControlError(
                RequestControlErrorCode.BLOCKED_PERMISSION, operation, attempts=0
            )

        async def wait(_stop, delay):
            waits.append((delay, service.health().next_retry_at))
            return _RetryWaitOutcome.SHUTDOWN

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=_unavailable,
            run_deadline=lambda _: pytest.fail("no permission due"),
        )
        service._refresh_references = lambda _: fail(calendar)
        service._recover_startup = lambda _: fail(history)

        def floor(operation):
            queried.append(operation)
            return (
                initial + timedelta(seconds=60 if operation is calendar else 90)
                if has_floors
                else None
            )

        service._request_controller.permission_retry_at = floor
        await service.run()
        expected = 90 if has_floors else 30
        assert waits == [(expected, initial + timedelta(seconds=expected))]
        assert set(queried) == {calendar, history}

    asyncio.run(scenario())


def test_completed_reference_and_recovery_clear_old_dependency_without_shortening_due():
    async def scenario():
        clock, starts, queries = _Clock(), [], []
        initial = clock.now()
        calendar = TushareOperation.TRADING_CALENDAR
        permission_due = initial + timedelta(seconds=35)
        later_floor = None
        reference_calls = 0

        def probe():
            starts.append(clock.now())
            return _unavailable()

        def references(_date):
            nonlocal reference_calls
            reference_calls += 1
            if reference_calls == 1:
                raise RequestControlError(
                    RequestControlErrorCode.BLOCKED_PERMISSION, calendar, attempts=0
                )

        def floor(operation):
            queries.append((operation, clock.now()))
            return later_floor

        async def permission(_deadline):
            nonlocal permission_due, later_floor
            permission_due = None
            later_floor = initial + timedelta(seconds=500)

        async def wait(_stop, delay):
            if len(starts) == 3:
                return _RetryWaitOutcome.SHUTDOWN
            clock.current += timedelta(seconds=delay)
            return _RetryWaitOutcome.TIMEOUT

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=probe,
            run_deadline=permission,
            next_permission_maintenance_at=lambda: permission_due,
        )
        service._refresh_references = references
        service._request_controller.permission_retry_at = floor
        await service.run()
        assert starts == [initial + timedelta(seconds=s) for s in (0, 30, 90)]
        assert queries and all(at <= initial + timedelta(seconds=30) for _, at in queries)

    asyncio.run(scenario())


@pytest.mark.parametrize("bad_callback", [0, False, "due"])
def test_permission_callback_must_be_callable(bad_callback):
    with pytest.raises(TypeError, match="next_permission_maintenance_at must be callable"):
        _service(
            clock=_Clock(),
            retry_wait=None,
            probe=_unavailable,
            run_deadline=lambda _: None,
            next_permission_maintenance_at=bad_callback,
        )


@pytest.mark.parametrize("bad_due", [False, 1, "tomorrow"])
def test_permission_callback_bad_result_is_not_a_normal_retry(bad_due):
    async def scenario():
        service = _service(
            clock=_Clock(),
            retry_wait=None,
            probe=_unavailable,
            run_deadline=lambda _: pytest.fail("invalid callback cannot run"),
            next_permission_maintenance_at=lambda: bad_due,
        )
        with pytest.raises(TypeError, match="must return datetime or None"):
            await service.run()
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_falsey_callable_is_used_and_permission_alone_cannot_enable_business():
    async def scenario():
        clock, observed = _Clock(), []

        class Due:
            def __bool__(self):
                return False

            def __call__(self):
                return clock.now() if not observed else None

        async def permission(_deadline):
            observed.append(service.health())
            return PermissionMaintenanceResult.PROBED

        async def wait(_stop, _delay):
            assert service.status is RuntimeServiceStatus.DEGRADED
            assert service._accepting_work is False
            return _RetryWaitOutcome.SHUTDOWN

        service = _service(
            clock=clock,
            retry_wait=wait,
            probe=_unavailable,
            run_deadline=permission,
            next_permission_maintenance_at=Due(),
        )
        await service.run()
        assert len(observed) == 1
        assert observed[0].status is RuntimeServiceStatus.DEGRADED and observed[0].read_only

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        RequestControlError(code, TushareOperation.TRADING_CALENDAR, attempts=0)
        for code in (
            RequestControlErrorCode.ERROR,
            RequestControlErrorCode.CLOSED,
            RequestControlErrorCode.QUEUE_FULL,
        )
    ]
    + [SQLAlchemyError("temporary storage fault"), TypeError("permission contract fault")],
)
def test_degraded_permission_fatal_error_reaches_existing_owner(failure):
    async def scenario():
        clock = _Clock()

        async def permission(_deadline):
            assert asyncio.current_task() in service._work_tasks
            raise failure

        service = _service(
            clock=clock,
            retry_wait=None,
            probe=_unavailable,
            run_deadline=permission,
            next_permission_maintenance_at=clock.now,
        )
        with pytest.raises(type(failure)) as caught:
            await service.run()
        assert caught.value is failure
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())
