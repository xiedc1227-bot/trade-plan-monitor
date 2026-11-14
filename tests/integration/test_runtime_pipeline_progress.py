"""Offline real-pipeline work fences; no provider success can renew stalled work."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.progress import RuntimeProgress


class Owner:
    def __init__(self, clock):
        self.clock = clock
        self.tick = 0.0
        self.tracker = RuntimeProgress(uuid4(), clock=clock.now, monotonic=lambda: self.tick)
        self.events = []

    def progress_monotonic_now(self):
        return self.tick

    def begin_progress_step(self, *, timeout_seconds):
        self.events.append(("begin", timeout_seconds))
        return self.tracker.begin_step(timeout_seconds=timeout_seconds)

    def begin_progress_step_at(self, *, deadline):
        self.events.append(("begin_at", deadline))
        return self.tracker.begin_step_at(deadline=deadline)

    def complete_progress_step(self, token, *, next_wake_at):
        self.events.append(("complete", self.tick))
        return self.tracker.complete_step(token, next_wake_at=next_wake_at)


def test_unknown_local_failure_does_not_complete_or_allow_new_work():
    from test_explicit_runtime_production import PIPELINE_NOW, _PipelineClock

    owner = Owner(_PipelineClock(PIPELINE_NOW))
    pipeline = object.__new__(ProductionMonitorPipeline)
    pipeline._status_progress_owner = owner
    pipeline._clock = owner.clock
    with pytest.raises(RuntimeError, match="storage fault"):
        with pipeline._status_progress_unit(timeout_seconds=30):
            raise RuntimeError("storage fault")
    assert owner.events == [("begin", 30)]
    owner.tick = 31
    assert owner.tracker.snapshot().state == "STALLED"
    with pytest.raises(RuntimeError, match="unfinished"):
        owner.begin_progress_step(timeout_seconds=30)


@pytest.mark.parametrize("retry_installed", [False, True])
def test_only_installed_retry_disposition_can_complete_failure(retry_installed):
    from test_explicit_runtime_production import PIPELINE_NOW, _PipelineClock

    from trade_plan_monitor.runtime.request_control import (
        RequestControlError,
        RequestControlErrorCode,
        TushareOperation,
    )

    owner = Owner(_PipelineClock(PIPELINE_NOW))
    pipeline = object.__new__(ProductionMonitorPipeline)
    pipeline._status_progress_owner = owner
    pipeline._clock = owner.clock
    error = RequestControlError(
        RequestControlErrorCode.TRANSIENT if retry_installed else RequestControlErrorCode.ERROR,
        TushareOperation.TRADING_CALENDAR, attempts=1,
        next_retry_at=PIPELINE_NOW + timedelta(seconds=30) if retry_installed else None,
    )
    with pytest.raises(RequestControlError):
        with pipeline._status_progress_unit(timeout_seconds=90):
            raise error
    assert any(event[0] == "complete" for event in owner.events) is retry_installed


@pytest.mark.parametrize("expired", [False, True])
def test_persisted_permission_without_error_retry_completes_bounded_failure(
    tmp_path, monkeypatch, expired,
):
    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import (
        RequestControlError,
        RequestControlErrorCode,
        TushareOperation,
    )
    from trade_plan_monitor.state.database import create_session_factory
    from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64,
        )
        controller.bind_recovery_repository(repository)
        owner = Owner(pipeline._clock)
        pipeline._status_progress_owner = owner
        due = owner.clock.now() + timedelta(seconds=300)
        returned_error = None

        def denied():
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

        try:
            with pytest.raises(RequestControlError) as caught:
                with pipeline._status_progress_unit(timeout_seconds=90):
                    try:
                        await controller.execute(
                            TushareOperation.TRADING_CALENDAR, denied, work_key="calendar:progress",
                        )
                    except RequestControlError as error:
                        returned_error = error
                        assert error.code is RequestControlErrorCode.BLOCKED_PERMISSION
                        assert error.next_retry_at is None
                        assert controller.permission_retry_at(error.operation) == due
                        assert [
                            (row.kind, row.scope_key, row.retry_at) for row in repository.load()
                        ] == [
                            ("permission", error.operation.value, due),
                        ]
                        if expired:
                            owner.clock.current = due + timedelta(seconds=1)
                        raise
            assert caught.value is returned_error
            assert controller.permission_retry_at(TushareOperation.TRADING_CALENDAR) == due
            snapshot = owner.tracker.snapshot()
            assert snapshot.state == "SCHEDULED"
            assert snapshot.last_progress_at == owner.clock.now()
            assert snapshot.next_wake_at == owner.clock.now() + timedelta(seconds=30)
            with pipeline._status_progress_unit(timeout_seconds=30):
                assert owner.tracker.snapshot().state == "WORKING"
            assert owner.events == [
                ("begin", 90), ("complete", 0.0), ("begin", 30), ("complete", 0.0),
            ]
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_waiter", [False, True])
def test_named_maintenance_waiter_does_not_begin_progress_or_read_before_lock(
    tmp_path, monkeypatch, cancel_waiter,
):
    from threading import Event

    from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
    from test_production_daily_limits_permission_maintenance import (
        _composition,
        _named_permission_work,
    )

    from trade_plan_monitor.runtime.health import RuntimeServiceStatus
    from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
    from trade_plan_monitor.runtime.request_control import TushareOperation

    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch, persisted_calendar=True)
        entered, release = Event(), Event()
        tasks = []
        try:
            runtime = composition._runtime
            assert (await runtime.start()).status is RuntimeServiceStatus.RUNNING
            assert composition._runner_task is None
            pipeline = runtime._liveness_owner._pipeline
            control = runtime._request_controller
            permission_work = _named_permission_work(
                runtime, pipeline._maybe_recheck_daily_bars_permission,
            )
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_start = len(sdk.calls)
            reads, preparations, reservations, progress = [], [], [], []
            original_read = pipeline._permission_probe_state
            original_prepare = pipeline._prepare_daily_bar_permission_locked
            original_callback = pipeline._permission_probe_reservation_callback
            original_begin = runtime.begin_progress_step
            original_complete = runtime.complete_progress_step
            original_daily = sdk._stock_daily

            def read_state(*args, **kwargs):
                reads.append(runtime._clock.now())
                return original_read(*args, **kwargs)

            def prepare():
                preparations.append(runtime._clock.now())
                return original_prepare()

            def callback(candidate):
                acknowledge = original_callback(candidate)

                def reserved():
                    reservations.append(candidate.operation)
                    return acknowledge()

                return reserved

            def begin(*, timeout_seconds):
                token = original_begin(timeout_seconds=timeout_seconds)
                progress.append(("begin", token))
                return token

            def complete(token, *, next_wake_at):
                result = original_complete(token, next_wake_at=next_wake_at)
                progress.append(("complete", token))
                return result

            def daily(kwargs):
                entered.set()
                assert release.wait(3), "maintenance worker was not released"
                return original_daily(kwargs)

            monkeypatch.setattr(pipeline, "_permission_probe_state", read_state)
            monkeypatch.setattr(pipeline, "_prepare_daily_bar_permission_locked", prepare)
            monkeypatch.setattr(pipeline, "_permission_probe_reservation_callback", callback)
            monkeypatch.setattr(runtime, "begin_progress_step", begin)
            monkeypatch.setattr(runtime, "complete_progress_step", complete)
            sdk._stock_daily = daily
            first = asyncio.create_task(permission_work())
            tasks.append(first)
            assert await asyncio.to_thread(entered.wait, 2)
            record = runtime.progress_authority_token()
            token = record.token
            assert token is not None
            before = (tuple(reads), tuple(preparations), tuple(reservations), tuple(sdk.calls))
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            second = asyncio.create_task(permission_work())
            tasks.append(second)
            for _ in range(12):
                await asyncio.sleep(0)
                if second.done() or pipeline._permission_maintenance_lock._waiters:
                    break
            assert not second.done()
            assert len(pipeline._permission_maintenance_lock._waiters) == 1
            assert len(runtime._work_tasks) == 2
            assert not first.done()
            assert runtime.progress_authority_token() is record
            assert progress == [("begin", token)]
            assert (
                tuple(reads), tuple(preparations), tuple(reservations), tuple(sdk.calls)
            ) == before
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            if cancel_waiter:
                second.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await second
                assert not first.done()
                assert runtime.progress_authority_token() is record
                assert progress == [("begin", token)]
                assert (
                    tuple(reads), tuple(preparations), tuple(reservations), tuple(sdk.calls)
                ) == before
                assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            release.set()
            assert await first is PermissionMaintenanceResult.PROBED
            if cancel_waiter:
                assert progress == [("begin", token), ("complete", token)]
            else:
                assert await second is PermissionMaintenanceResult.SKIPPED
                second_token = progress[2][1]
                assert second_token is not token
                assert progress == [
                    ("begin", token), ("complete", token),
                    ("begin", second_token), ("complete", second_token),
                ]
            assert len(preparations) == 1
            assert reservations == [TushareOperation.DAILY_BARS]
            assert [name for name, _ in sdk.calls[sdk_start:]] == ["daily"]
            assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert runtime.progress_authority_token().token is None
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_kind", ["unknown", "nonowner", "stopping"])
def test_named_maintenance_failure_or_rejected_owner_cannot_refresh_progress(
    tmp_path, monkeypatch, failure_kind,
):
    from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
    from test_production_daily_limits_permission_maintenance import (
        _composition,
        _named_permission_work,
    )

    from trade_plan_monitor.runtime.health import RuntimeServiceStatus
    from trade_plan_monitor.runtime.request_control import TushareOperation

    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch, persisted_calendar=True)
        try:
            runtime = composition._runtime
            assert (await runtime.start()).status is RuntimeServiceStatus.RUNNING
            pipeline = runtime._liveness_owner._pipeline
            control = runtime._request_controller
            permission_work = _named_permission_work(
                runtime, pipeline._maybe_recheck_daily_bars_permission,
            )
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            reads = []
            failure = RuntimeError("offline unknown maintenance failure")

            def fail_read(*_args, **_kwargs):
                reads.append(runtime._clock.now())
                raise failure

            monkeypatch.setattr(pipeline, "_permission_probe_state", fail_read)
            before = runtime.progress_authority_token()
            if failure_kind == "unknown":
                with pytest.raises(RuntimeError) as caught:
                    await permission_work()
                assert caught.value is failure
                retained = runtime.progress_authority_token()
                assert retained.token is not None
                assert retained.last_progress == before.last_progress
                with pytest.raises(
                    RuntimeError, match="^unfinished progress step is already owned$",
                ):
                    await permission_work()
                assert runtime.progress_authority_token() is retained
                assert len(reads) == 1
            else:
                if failure_kind == "stopping":
                    runtime.begin_shutdown()
                    invocation = permission_work
                    message = "^runtime progress owner is stopping$"
                else:
                    invocation = pipeline._maybe_recheck_daily_bars_permission
                    message = "^progress updates require the lifecycle owner task$"
                with pytest.raises(RuntimeError, match=message):
                    await invocation()
                assert runtime.progress_authority_token() is before
                assert reads == []
            assert not pipeline._permission_maintenance_lock.locked()
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            assert tuple(sdk.calls) == sdk_before
            assert pipeline._permission_rotation_state.last_operation is None
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_cancelled_named_maintenance_keeps_token_through_physical_drain(tmp_path, monkeypatch):
    from threading import Event

    from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
    from test_production_daily_limits_permission_maintenance import (
        _composition,
        _named_permission_work,
    )

    from trade_plan_monitor.runtime.health import RuntimeServiceStatus
    from trade_plan_monitor.runtime.request_control import TushareOperation

    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch, persisted_calendar=True)
        entered, release = Event(), Event()
        attempt = closing = None
        try:
            runtime = composition._runtime
            assert (await runtime.start()).status is RuntimeServiceStatus.RUNNING
            pipeline = runtime._liveness_owner._pipeline
            control = runtime._request_controller
            permission_work = _named_permission_work(
                runtime, pipeline._maybe_recheck_daily_bars_permission,
            )
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            original = sdk._stock_daily

            def daily(kwargs):
                entered.set()
                assert release.wait(3), "cancelled maintenance worker was not released"
                return original(kwargs)

            sdk._stock_daily = daily
            attempt = asyncio.create_task(permission_work())
            assert await asyncio.to_thread(entered.wait, 2)
            retained = runtime.progress_authority_token()
            assert retained.token is not None
            attempt.cancel()
            with pytest.raises(asyncio.CancelledError):
                await attempt
            assert runtime.progress_authority_token() is retained
            assert not pipeline._permission_maintenance_lock.locked()
            with pytest.raises(RuntimeError, match="^unfinished progress step is already owned$"):
                await permission_work()
            assert runtime.progress_authority_token() is retained
            closing = asyncio.create_task(control.aclose())
            for _ in range(5):
                await asyncio.sleep(0)
            assert not closing.done()
            assert control.active_count == 1
            assert runtime.progress_authority_token() is retained
            release.set()
            await closing
            assert control.active_count == 0
            assert runtime.progress_authority_token() is retained
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
        finally:
            release.set()
            if attempt is not None:
                await asyncio.gather(attempt, return_exceptions=True)
            if closing is not None:
                await closing
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("reservation_operation", "code"),
    [(None, "BLOCKED_PERMISSION"), ("DAILY_BARS", "BLOCKED_PERMISSION")]
    + [("TRADING_CALENDAR", code) for code in (
        "ERROR", "RATE_LIMITED", "TRANSIENT", "TIMEOUT", "INVALID_RESPONSE",
    )],
)
def test_permission_completion_requires_same_operation_and_exact_error(
    tmp_path, monkeypatch, reservation_operation, code,
):
    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import (
        RequestControlError,
        RequestControlErrorCode,
        TushareOperation,
    )

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        owner = Owner(pipeline._clock)
        pipeline._status_progress_owner = owner

        def denied():
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "offline")

        try:
            if reservation_operation is not None:
                with pytest.raises(RequestControlError):
                    await controller.execute(
                        TushareOperation[reservation_operation], denied,
                        work_key="permission:setup",
                    )
            error = RequestControlError(
                RequestControlErrorCode[code], TushareOperation.TRADING_CALENDAR, attempts=1,
            )
            with pytest.raises(RequestControlError) as caught:
                with pipeline._status_progress_unit(timeout_seconds=90):
                    token = owner.tracker.authority_token().token
                    raise error
            assert caught.value is error
            assert owner.events == [("begin", 90)]
            assert owner.tracker.authority_token().token is token
            owner.tick = 91
            assert owner.tracker.snapshot().state == "STALLED"
            with pytest.raises(RuntimeError, match="unfinished progress step is already owned"):
                owner.begin_progress_step(timeout_seconds=30)
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_permission_persistence_failure_cannot_complete_progress(tmp_path, monkeypatch):
    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import TushareOperation
    from trade_plan_monitor.state.database import create_session_factory
    from trade_plan_monitor.state.runtime_recovery import (
        ProviderRecoveryRepository,
        RecoveryCheckpointError,
    )

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64,
        )
        controller.bind_recovery_repository(repository)
        owner = Owner(pipeline._clock)
        pipeline._status_progress_owner = owner
        failure = RecoveryCheckpointError("offline permission checkpoint failed")

        def fail_save(_rows):
            raise failure

        def denied():
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(repository, "save", fail_save)
                with pytest.raises(RecoveryCheckpointError) as caught:
                    with pipeline._status_progress_unit(timeout_seconds=90):
                        token = owner.tracker.authority_token().token
                        await controller.execute(
                            TushareOperation.TRADING_CALENDAR, denied,
                            work_key="calendar:failed-save",
                        )
                assert caught.value is failure
                assert controller.permission_retry_at(TushareOperation.TRADING_CALENDAR) is not None
                assert repository.load() == ()
                assert owner.events == [("begin", 90)]
                assert owner.tracker.authority_token().token is token
                with pytest.raises(RuntimeError, match="unfinished progress step is already owned"):
                    owner.begin_progress_step(timeout_seconds=30)
        finally:
            try:
                with pytest.raises(
                    RecoveryCheckpointError, match="^provider outcome could not be checkpointed$",
                ):
                    await controller.aclose()
                repository.assert_owner(controller)
            finally:
                repository.release_owner(controller)
                engine.dispose()

    asyncio.run(scenario())


def test_real_explicit_pipeline_reports_individual_committed_units(tmp_path, monkeypatch):
    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    owners = []

    def build(**kwargs):
        owner = Owner(kwargs["clock"])
        owners.append(owner)
        kwargs.update(enable_runtime_status=True, progress_owner=owner,
                      recovery_session_factory=kwargs["unit_of_work_factory"]()._session_factory)
        return ProductionMonitorPipeline(**kwargs)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", build)

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        try:
            assert pipeline.runtime_status_progress_coverage_ready
            await pipeline.refresh_references(fixture.TARGET.date())
            owner = owners[0]
            reference_count = len(owner.events)
            await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=fixture.TARGET.date(),
                due_at=fixture.PIPELINE_NOW, bar_end=fixture.TARGET,
            ))
            assert pipeline.runtime_status_snapshot()[2][0].completion is not None
            assert ("begin", 90) in owner.events[reference_count:]
            assert ("begin", 30) in owner.events[reference_count:]
            assert owner.tracker.snapshot().state == "SCHEDULED"
            from trade_plan_monitor.web.runtime_status_read_service import build_dependency_scopes

            frozen = pipeline.runtime_status_dependencies_snapshot()
            scopes = build_dependency_scopes(frozen)
            assert len(scopes) == len(frozen)
            keys = {scope.scope_key for scope in scopes}
            assert "provider:index:idx_mins" in keys
            assert "provider:index:rt_idx_min_daily" in keys
            assert "provider:stock:rt_min" in keys
            assert "calendar:SZSE" in keys
            pipeline._generation_current = lambda: False
            invalidated = pipeline.runtime_status_snapshot()[2][0]
            assert invalidated.completion is None
            assert invalidated.blocked is True
            assert invalidated.pending_reason == "GENERATION_CHANGED"
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_index_sibling_completion_cannot_extend_original_pending_deadline():
    from test_explicit_runtime_production import _PipelineClock
    from test_market_index_snapshots import CUTOFF, EVALUATED_AT, _batch

    from trade_plan_monitor.market_index.identity import MarketIndexCode
    from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator

    async def scenario():
        clock = _PipelineClock(EVALUATED_AT)
        owner = Owner(clock)
        releases = {code: asyncio.Event() for code in (
            MarketIndexCode.SSE_COMPOSITE, MarketIndexCode.SHENZHEN_COMPONENT,
        )}

        class Provider:
            async def acquire_index_data(self, *, index_code, **_kwargs):
                await releases[index_code].wait()
                return _batch(index_code)

        coordinator = MarketIndexSnapshotCoordinator(
            Provider(), clock=clock, progress_owner=owner,
        )

        task = asyncio.create_task(coordinator.get_snapshots(
            requirements={code: () for code in releases}, decision_cutoff=CUTOFF,
            observed_no_later_than=EVALUATED_AT,
        ))
        for _ in range(3):
            await asyncio.sleep(0)
        owner.tick = 100
        assert owner.tracker.snapshot().state == "WORKING"
        owner.tick = 290
        releases[MarketIndexCode.SSE_COMPOSITE].set()
        for _ in range(20):
            await asyncio.sleep(0)
            if len(owner.events) >= 3:
                break
        assert owner.tracker.snapshot().state == "WORKING"
        assert owner.tracker.snapshot().progress_due_at == EVALUATED_AT + timedelta(seconds=10)
        owner.tick = 301
        assert owner.tracker.snapshot().state == "STALLED"
        releases[MarketIndexCode.SHENZHEN_COMPONENT].set()
        result = await task
        assert all(snapshot.snapshot_hash for snapshot in result.values())
        assert owner.tracker.snapshot().state == "SCHEDULED"
        assert all(event[1] == 300 for event in owner.events if event[0] == "begin_at")

    asyncio.run(scenario())


@pytest.mark.parametrize("late_permission_failure", [False, True])
def test_cancelled_real_worker_cannot_complete_progress_before_physical_drain(
    tmp_path, monkeypatch, late_permission_failure,
):
    from threading import Event

    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import TushareOperation

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        owner = Owner(pipeline._clock)
        pipeline._status_progress_owner = owner
        pipeline.symbols._progress_unit = pipeline._status_progress_unit
        entered, release = Event(), Event()
        original = pipeline.provider.realtime_minutes

        def blocking(_provider, symbols):
            entered.set()
            assert release.wait(5), "offline worker was not released"
            if late_permission_failure:
                raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "rt_min")
            return original(symbols)

        monkeypatch.setattr(type(pipeline.provider), "realtime_minutes", blocking)
        task = asyncio.create_task(pipeline.symbols.run_realtime_batch(
            symbols=pipeline.active_symbols(), bar_end=fixture.TARGET,
            observed_at=fixture.PIPELINE_NOW,
        ))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            owner.tick = 91
            assert owner.tracker.snapshot().state == "STALLED"
            assert owner.tracker.snapshot().last_progress_at is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            closing = asyncio.create_task(controller.aclose())
            for _ in range(5):
                await asyncio.sleep(0)
            assert not closing.done()
            assert owner.tracker.snapshot().state == "STALLED"
            assert not any(event[0] == "complete" for event in owner.events)
        finally:
            release.set()
            if closing is not None:
                await closing
            else:
                await controller.aclose()
            engine.dispose()
        assert owner.tracker.snapshot().state == "STALLED"
        assert not any(event[0] == "complete" for event in owner.events)
        if late_permission_failure:
            assert controller.is_permission_blocked(TushareOperation.REALTIME_MINUTES)
            assert controller.permission_retry_at(TushareOperation.REALTIME_MINUTES) is not None

    asyncio.run(scenario())
