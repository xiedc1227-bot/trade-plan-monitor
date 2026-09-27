"""Offline current-day index permission rechecks preserve endpoint isolation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from threading import Event, current_thread, main_thread

import pandas as pd
import pytest
from sqlalchemy import func, select, text
from test_index_permission_scope_migration import _migrate
from test_live_pipeline_acceptance import NOW, _write_configuration_and_evidence
from test_production_certification_gate import _composition

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import (
    PermissionMaintenanceResult,
    ReferenceDependenciesChangedError,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertDeliveryEligibility,
    AlertEvent,
    DeliveryAttempt,
    EvaluationResult,
    MarketIndexSnapshot,
)
from trade_plan_monitor.web.monitor_composition import _provider_recovery_identity


async def _block(controller, operation: TushareOperation) -> None:
    def denied():
        raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, operation.value)

    with pytest.raises(RequestControlError) as caught:
        await controller.execute(operation, denied, work_key=f"seed:{operation.value}")
    assert caught.value.code is RequestControlErrorCode.BLOCKED_PERMISSION


async def _blocked_case(
    tmp_path, monkeypatch, *, persisted_calendar: bool = True,
    stock_certification: bool = False, block_historical: bool = True,
):
    composition, sdk, _ = _composition(
        tmp_path, monkeypatch, active_plan=False, include_index=True,
        stock_certification=stock_certification,
        persisted_calendar=persisted_calendar,
    )
    startup = await composition.start()
    assert startup.status in {RuntimeServiceStatus.RUNNING, RuntimeServiceStatus.DEGRADED}
    runtime = composition._runtime
    state = runtime._probe_capabilities.__self__
    pipeline = state._pipeline
    assert pipeline is not None
    controller = runtime._request_controller
    if block_historical:
        await _block(controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
    await _block(controller, TushareOperation.INDEX_REALTIME_MINUTES)
    runtime._clock.current += timedelta(seconds=301)
    return composition, sdk, state, pipeline, controller


async def _until(predicate) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=5)


def _assert_no_business_writes(state) -> None:
    with state._session_factory() as session:
        for model in (
            MarketIndexSnapshot, EvaluationResult, AlertEvent,
            AlertDeliveryEligibility, DeliveryAttempt,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def _rewrite_same_calendar(pipeline) -> None:
    today = pipeline._clock.now().date()
    captured_key = pipeline._reference_dependency_key(
        today, pipeline.active_plans(today),
    )
    with pipeline._work() as work:
        days = work.references.list_trading_days("SSE", today, today)
    assert len(days) == 1 and days[0].is_open
    pipeline._commit_trading_days(
        days, trade_date=today, captured_key=captured_key,
    )


def test_valid_current_day_probe_clears_only_realtime_permission(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        try:
            before = len(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert sdk.calls[before:] == [(
                "rt_idx_min_daily",
                {
                    "ts_code": MarketIndexCode.SSE_COMPOSITE.value,
                    "freq": "5MIN",
                    "fields": "ts_code,freq,time,open,close,high,low,vol,amount",
                },
            )]
            assert not controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert pipeline.index_provider._historical_minute_cache == {}
            assert pipeline.index_provider._intraday_daily_cache == {}
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_independent_realtime_permission_deadline_reaches_production_handler(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, _pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, block_historical=False,
        )
        try:
            due = state.next_index_permission_at()
            assert due is not None and due <= composition._runtime._clock.now()
            deadline = composition._runtime._scheduler.next_deadline()
            assert deadline is not None and deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert deadline.due_at == composition._runtime._clock.now()
            before = len(sdk.calls)

            assert await state.run_deadline(deadline) is PermissionMaintenanceResult.PROBED

            assert [name for name, _ in sdk.calls[before:]] == ["rt_idx_min_daily"]
            assert not controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_migrated_legacy_index_block_rechecks_only_realtime_scope(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            _migrate(engine, "0022_runtime_liveness", downgrade=True)
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO provider_recovery_checkpoint "
                    "(provider_identity, kind, scope_key, schema_version, retry_at, "
                    "failures, reason_code) VALUES "
                    "(:identity, 'permission', 'index_minutes', 1, :retry, 0, "
                    "'BLOCKED_PERMISSION')"
                ), {
                    "identity": _provider_recovery_identity("https://example.test"),
                    "retry": (NOW + timedelta(seconds=300)).isoformat(),
                })
        finally:
            engine.dispose()
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            controller = runtime._request_controller
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            runtime._clock.current += timedelta(seconds=301)
            before = len(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert [name for name, _ in sdk.calls[before:]] == ["rt_idx_min_daily"]
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert not controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_failed_calendar_transaction_keeps_old_token_revoked_until_fresh_read(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, stock_certification=True, block_historical=False,
        )
        today = pipeline._clock.now().date()
        captured_key = pipeline._reference_dependency_key(
            today, pipeline.active_plans(today),
        )
        with pipeline._work() as work:
            days = work.references.list_trading_days("SSE", today, today)
        assert len(days) == 1 and days[0].is_open
        previous_epoch = pipeline._calendar_epoch
        previous_token = pipeline._calendar_revoked
        original_assert = pipeline._assert_reference_generation

        def reject_commit(_trade_date, _captured_key):
            raise ReferenceDependenciesChangedError

        pipeline._assert_reference_generation = reject_commit
        try:
            with pytest.raises(ReferenceDependenciesChangedError):
                pipeline._commit_trading_days(
                    days, trade_date=today, captured_key=captured_key,
                )
            assert pipeline._calendar_epoch == previous_epoch + 1
            assert pipeline._calendar_revoked is previous_token
            assert previous_token.is_set()
            with pipeline._work() as work:
                persisted = work.references.list_trading_days("SSE", today, today)
            assert persisted == days
        finally:
            pipeline._assert_reference_generation = original_assert
        try:
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert pipeline._calendar_revoked is not previous_token
            assert not pipeline._calendar_revoked.is_set()
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 1
            assert not controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_queued_realtime_probe_yields_to_market_with_reservation_intact(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        entered = Event()
        release = Event()

        def occupy_worker():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return "released"

        hold_task = asyncio.create_task(controller.execute(
            TushareOperation.INDEX_DAILY, occupy_worker, work_key="hold-rt-probe",
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            probe_task = asyncio.create_task(
                pipeline._maybe_recheck_realtime_index_permission()
            )
            await _until(lambda: controller.waiting_count > 0)
            reserved = controller.permission_retry_at(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            assert reserved is not None
            pipeline._clock.current = datetime(2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI)
            release.set()
            assert await hold_task == "released"
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 0
            assert controller.permission_retry_at(
                TushareOperation.INDEX_REALTIME_MINUTES
            ) == reserved
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_realtime_worker_rechecks_frozen_window_without_sqlite(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        original_submit = controller._executor.submit
        original_work = pipeline._work
        worker_reads: list[str] = []

        def checked_work():
            if current_thread() is not main_thread():
                worker_reads.append("sqlite")
            return original_work()

        def advance_before_worker(call, *args, **kwargs):
            def worker():
                pipeline._clock.current = datetime(
                    2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI,
                )
                return call(*args, **kwargs)

            return original_submit(worker)

        pipeline._work = checked_work
        monkeypatch.setattr(controller._executor, "submit", advance_before_worker)
        try:
            before = tuple(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.DEFERRED
            )
            assert tuple(sdk.calls) == before
            assert worker_reads == []
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            pipeline._work = original_work
            monkeypatch.setattr(controller._executor, "submit", original_submit)
            await composition.stop()

    asyncio.run(scenario())


def test_delay_after_logical_admission_rechecks_physical_start_before_sdk(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        original_probe = pipeline.index_provider.probe_realtime_minutes_permission

        def delay_before_provider(*args):
            pipeline._clock.current = datetime(
                2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI,
            )
            return original_probe(*args)

        monkeypatch.setattr(
            pipeline.index_provider, "probe_realtime_minutes_permission",
            delay_before_provider,
        )
        try:
            before = tuple(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.DEFERRED
            )
            assert tuple(sdk.calls) == before
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_realtime_probe_uses_shared_1250ms_admission_pace(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        starts: list[float] = []
        original_minutes = sdk._index_minutes

        def observe_start(kwargs):
            starts.append(controller._monotonic())
            return original_minutes(kwargs)

        sdk._index_minutes = observe_start
        try:
            await controller.execute(
                TushareOperation.INDEX_DAILY,
                lambda: starts.append(controller._monotonic()),
                work_key="pace-before-rt-probe",
            )
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert len(starts) == 2
            assert starts[1] - starts[0] >= 1.25
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_realtime_response_uses_physical_start_cutoff_not_later_response_clock(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )

        def later_batch(kwargs):
            pipeline._clock.current = datetime(2026, 9, 8, 10, 10, 16, tzinfo=SHANGHAI)
            return sdk.__class__._index_minutes(sdk, kwargs)

        sdk._index_minutes = later_batch
        try:
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.FAILED
            )
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 1
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_same_value_calendar_commit_during_realtime_response_revokes_probe(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, stock_certification=True, block_historical=False,
        )
        entered = Event()
        release = Event()
        original_minutes = sdk._index_minutes

        def delayed(kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test response hold expired")
            return original_minutes(kwargs)

        sdk._index_minutes = delayed
        try:
            probe_task = asyncio.create_task(
                pipeline._maybe_recheck_realtime_index_permission()
            )
            assert await asyncio.to_thread(entered.wait, 5)
            _rewrite_same_calendar(pipeline)
            release.set()
            assert await probe_task is PermissionMaintenanceResult.FAILED
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            assert controller.permission_retry_at(
                TushareOperation.INDEX_REALTIME_MINUTES
            ) is not None
            _assert_no_business_writes(state)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_same_value_calendar_commit_while_probe_queued_prevents_sdk_start(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, stock_certification=True, block_historical=False,
        )
        entered = Event()
        release = Event()

        def occupy_worker():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return "released"

        hold_task = asyncio.create_task(controller.execute(
            TushareOperation.INDEX_DAILY, occupy_worker,
            work_key="hold-calendar-commit-before-rt",
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            probe_task = asyncio.create_task(
                pipeline._maybe_recheck_realtime_index_permission()
            )
            await _until(lambda: controller.waiting_count > 0)
            _rewrite_same_calendar(pipeline)
            release.set()
            assert await hold_task == "released"
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 0
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_revoke_before_worker_gate_prevents_physical_sdk_call(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, stock_certification=True, block_historical=False,
        )
        entered = Event()
        release = Event()
        original_submit = controller._executor.submit

        def hold_before_gate(call, *args, **kwargs):
            def worker():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test worker hold expired")
                return call(*args, **kwargs)

            return original_submit(worker)

        monkeypatch.setattr(controller._executor, "submit", hold_before_gate)
        try:
            probe_task = asyncio.create_task(
                pipeline._maybe_recheck_realtime_index_permission()
            )
            assert await asyncio.to_thread(entered.wait, 5)
            _rewrite_same_calendar(pipeline)
            release.set()
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 0
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            release.set()
            monkeypatch.setattr(controller._executor, "submit", original_submit)
            await composition.stop()

    asyncio.run(scenario())


def test_admitted_probe_rechecks_before_sdk_after_calendar_commit(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, stock_certification=True, block_historical=False,
        )
        entered = Event()
        release = Event()
        original_probe = pipeline.index_provider.probe_realtime_minutes_permission

        def hold_after_gate(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return original_probe(*args)

        monkeypatch.setattr(
            pipeline.index_provider, "probe_realtime_minutes_permission", hold_after_gate,
        )
        try:
            probe_task = asyncio.create_task(
                pipeline._maybe_recheck_realtime_index_permission()
            )
            assert await asyncio.to_thread(entered.wait, 5)
            _rewrite_same_calendar(pipeline)
            assert not probe_task.done()
            release.set()
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("rt_idx_min_daily") == 0
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            assert controller.permission_retry_at(
                TushareOperation.INDEX_REALTIME_MINUTES
            ) is not None
            _assert_no_business_writes(state)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "damage",
    ("empty", "mixed", "bad_freq", "duplicate", "future", "bad_price", "extra", "too_many"),
)
def test_invalid_current_day_batch_keeps_realtime_latch_and_reservation(
    tmp_path, monkeypatch, damage,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch,
        )
        try:
            frame = sdk._index_minutes({"ts_code": MarketIndexCode.SSE_COMPOSITE.value})
            if damage == "empty":
                frame = frame.iloc[0:0]
            elif damage == "mixed":
                frame.loc[0, "ts_code"] = MarketIndexCode.STAR_50.value
            elif damage == "bad_freq":
                frame.loc[0, "freq"] = "1MIN"
            elif damage == "duplicate":
                frame.loc[1, "time"] = frame.loc[0, "time"]
            elif damage == "future":
                frame.loc[0, "time"] = "2026-09-08 10:10:00"
            elif damage == "bad_price":
                frame.loc[0, "high"] = "0"
            elif damage == "extra":
                frame["unexpected"] = "value"
            else:
                frame = pd.concat((frame,) * 8, ignore_index=True)
            sdk._index_minutes = lambda _kwargs: frame
            before = len(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.FAILED
            )
            assert [name for name, _ in sdk.calls[before:]] == ["rt_idx_min_daily"]
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert controller.permission_retry_at(
                TushareOperation.INDEX_REALTIME_MINUTES
            ) >= pipeline._clock.now() + timedelta(seconds=300)
            assert pipeline.index_provider._historical_minute_cache == {}
            assert pipeline.index_provider._intraday_daily_cache == {}
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("barrier", ("missing_calendar", "shared_429"))
def test_current_day_probe_waits_for_calendar_and_shared_cooldown(
    tmp_path, monkeypatch, barrier,
):
    async def scenario():
        composition, sdk, state, pipeline, controller = await _blocked_case(
            tmp_path, monkeypatch, persisted_calendar=barrier != "missing_calendar",
            block_historical=barrier != "missing_calendar",
        )
        try:
            if barrier == "shared_429":
                def limited():
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "index_daily")

                with pytest.raises(RequestControlError):
                    await controller.execute(
                        TushareOperation.INDEX_DAILY, limited,
                        work_key="shared-index-cooldown",
                    )
            before = tuple(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                in {PermissionMaintenanceResult.SKIPPED, PermissionMaintenanceResult.DEFERRED}
            )
            assert tuple(sdk.calls) == before
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            if barrier == "missing_calendar":
                assert state.next_index_permission_at() > pipeline._clock.now()
            else:
                assert controller.is_permission_blocked(
                    TushareOperation.INDEX_HISTORICAL_MINUTES
                )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_first_current_day_five_minute_bar_waits_until_093512(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        runtime = composition._runtime
        runtime._clock.current = datetime(2026, 9, 8, 9, 30, tzinfo=SHANGHAI)
        _write_configuration_and_evidence(
            tmp_path, observed_at=runtime._clock.now(), include_index=True,
        )
        (tmp_path / "data/live-certification/tushare-stock-live.json").unlink()
        try:
            assert (await composition.start()).status in {
                RuntimeServiceStatus.RUNNING, RuntimeServiceStatus.DEGRADED,
            }
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            controller = runtime._request_controller
            await _block(controller, TushareOperation.INDEX_REALTIME_MINUTES)
            runtime._clock.current = datetime(2026, 9, 8, 9, 35, tzinfo=SHANGHAI)
            before = tuple(sdk.calls)
            assert (
                await pipeline._maybe_recheck_realtime_index_permission()
                is PermissionMaintenanceResult.SKIPPED
            )
            assert tuple(sdk.calls) == before
            assert state.next_index_permission_at() == datetime(
                2026, 9, 8, 9, 35, 12, tzinfo=SHANGHAI,
            )
            assert controller.is_permission_blocked(
                TushareOperation.INDEX_REALTIME_MINUTES
            )
            _assert_no_business_writes(state)
        finally:
            await composition.stop()

    asyncio.run(scenario())
