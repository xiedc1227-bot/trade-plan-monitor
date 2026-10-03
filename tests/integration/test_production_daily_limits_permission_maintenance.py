"""Current DAILY_BARS maintenance and retired DAILY_LIMITS no-demand boundary."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from threading import Event, current_thread, main_thread

import pandas as pd
import pytest
from sqlalchemy import delete
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition as _base_composition
from test_production_index_daily_permission_maintenance import _one_official_index_day
from tests.integration.current_activation_fixture import (
    current_mixed_plan,
    current_sample_plan,
    seed_current,
)

from trade_plan_monitor.live_profiles import load_stock_certification
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.request_control import (
    PermissionReservationCallbackError,
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.runtime_recovery import RecoveryCheckpointError


def _composition(tmp_path, monkeypatch, **kwargs):
    """Exercise active current DAILY_BARS while retaining the frozen owner controls."""
    return _base_composition(
        tmp_path, monkeypatch,
        plan=current_mixed_plan() if kwargs.get("active_plan", True) else None,
        **kwargs,
    )


def _daily_call(symbol, anchor):
    return (
        "daily",
        {
            "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
            "ts_code": symbol,
            "start_date": anchor.strftime("%Y%m%d"),
            "end_date": anchor.strftime("%Y%m%d"),
        },
    )


@pytest.mark.parametrize("daily_rule", (False, True))
def test_current_plans_never_authorize_retired_daily_limits(tmp_path, monkeypatch, daily_rule):
    async def scenario():
        plan = current_mixed_plan() if daily_rule else current_sample_plan()
        composition, sdk, _ = _base_composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True, plan=plan,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_LIMITS)
            runtime._clock.current += timedelta(seconds=301)
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS)
            before = tuple(sdk.calls), pipeline._permission_rotation_state
            assert not any(candidate.operation is TushareOperation.DAILY_LIMITS
                for candidate in pipeline.permission_probe_candidates())
            assert await pipeline._maybe_recheck_daily_limits_permission() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS) == raw
            assert control.is_permission_blocked(TushareOperation.DAILY_LIMITS)
            assert control.active_count == 0
            assert (tuple(sdk.calls), pipeline._permission_rotation_state) == before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_due_daily_bars_proves_once_and_only_clears_own_permission(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            await _block(control, TushareOperation.CURRENT_DAY_MINUTES)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            original_work = pipeline._work
            with original_work() as work:
                limits_before = work.references.list_daily_limits(ANCHOR)
                bars_before = work.history.list_daily_bars(
                    current_mixed_plan().symbol, start=ANCHOR, end=ANCHOR,
                )
            calendar_before = dict(pipeline._calendar)

            def owner_only_work():
                assert current_thread() is main_thread()
                return original_work()

            monkeypatch.setattr(pipeline, "_work", owner_only_work)
            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.PROBED
            )
            assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert control.is_permission_blocked(TushareOperation.CURRENT_DAY_MINUTES)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
            assert tuple(sdk.calls[len(sdk_before):]) == (
                _daily_call(current_mixed_plan().symbol, ANCHOR),
            )
            with original_work() as work:
                assert work.references.list_daily_limits(ANCHOR) == limits_before
                assert work.history.list_daily_bars(
                    current_mixed_plan().symbol, start=ANCHOR, end=ANCHOR,
                ) == bars_before
            assert pipeline._calendar == calendar_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("terminal", ("none", "other_current", "minute_only"))
def test_daily_bar_response_requires_original_reviewed_activation(
    tmp_path, monkeypatch, terminal,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        entered, release = Event(), Event()
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            database = tmp_path / "monitor.sqlite3"
            _seed_open_day(database, ANCHOR)
            first = current_mixed_plan()
            replacement = None
            if terminal == "other_current":
                replacement = first.model_copy(update={
                    "symbol": "003044.SZ", "plan_id": "next-current",
                })
            elif terminal == "minute_only":
                replacement = current_sample_plan().model_copy(update={
                    "symbol": "003044.SZ", "plan_id": "next-minute",
                })
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            original_limits = sdk._stock_daily

            def waiting_limits(kwargs):
                entered.set()
                release.wait(3)
                return original_limits(kwargs)

            sdk._stock_daily = waiting_limits
            attempt = asyncio.create_task(pipeline._maybe_recheck_daily_bars_permission())
            assert await asyncio.to_thread(entered.wait, 1)
            with pipeline._work() as work:
                work.plans.deactivate(first.symbol, expected_revision=1)
                work.commit()
            if replacement is not None:
                seed_current(tmp_path, plan=replacement, clock=runtime._clock)
            release.set()
            result = await attempt
            assert result is PermissionMaintenanceResult.FAILED
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
            assert [name for name, _ in sdk.calls].count("daily") >= 1
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ("configuration", "semantic", "calendar_same_value"))
def test_queued_daily_bars_rejects_authority_aba_or_calendar_epoch(
    tmp_path, monkeypatch, change,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        occupied, release = Event(), Event()

        def occupy_worker() -> str:
            occupied.set()
            release.wait(3)
            return "released"

        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            database = tmp_path / "monitor.sqlite3"
            _seed_open_day(database, ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            blocker = asyncio.create_task(control.execute(
                TushareOperation.CURRENT_DAY_MINUTES,
                occupy_worker, work_key="hold:limits-aba",
            ))
            assert await asyncio.to_thread(occupied.wait, 1)
            attempt = asyncio.create_task(pipeline._maybe_recheck_daily_bars_permission())
            for _ in range(100):
                if control.waiting_count:
                    break
                await asyncio.sleep(0)
            assert control.waiting_count == 1
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
            if change == "calendar_same_value":
                before_epoch = pipeline._calendar_epoch
                today = runtime._clock.now().date()
                key = pipeline._reference_dependency_key(
                    today, pipeline.active_plans(today),
                )
                pipeline._commit_trading_days((TradingDay(
                    exchange="SSE", cal_date=ANCHOR, is_open=True,
                    previous_trade_date=ANCHOR - timedelta(days=3),
                ),), trade_date=today, captured_key=key)
                assert pipeline._calendar_epoch == before_epoch + 1
            else:
                path = (
                    tmp_path / "config/app.yaml"
                    if change == "configuration"
                    else tmp_path / "data/live-certification/stock-semantic.json"
                )
                original = path.read_bytes()
                try:
                    if change == "configuration":
                        path.write_bytes(original.replace(
                            b"offline-test-token", b"changed-token",
                        ))
                        assert not pipeline._configuration_current()
                    else:
                        path.write_text("{}", encoding="utf-8")
                        assert not pipeline._stock_certification_current()
                finally:
                    path.write_bytes(original)
            release.set()
            assert await blocker == "released"
            assert await attempt is PermissionMaintenanceResult.DEFERRED
            assert tuple(sdk.calls) == sdk_before
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_daily_bars_response_rereads_exact_anchor_before_unlock(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        entered, release = Event(), Event()
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            database = tmp_path / "monitor.sqlite3"
            _seed_open_day(database, ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            original_limits = sdk._stock_daily

            def waiting_limits(kwargs):
                entered.set()
                release.wait(3)
                return original_limits(kwargs)

            sdk._stock_daily = waiting_limits
            attempt = asyncio.create_task(pipeline._maybe_recheck_daily_bars_permission())
            assert await asyncio.to_thread(entered.wait, 1)
            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    row = session.get(TradingCalendar, ("SSE", ANCHOR))
                    assert row is not None
                    row.is_open = False
            finally:
                engine.dispose()
            release.set()
            assert await attempt is PermissionMaintenanceResult.FAILED
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_daily_bars_reselects_after_index_daily_uses_shared_maintenance_lock(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, include_index=True,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=1)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            sdk._index_daily = lambda kwargs: _one_official_index_day(
                MarketIndexCode(str(kwargs["ts_code"])),
            )

            first = asyncio.create_task(pipeline._maybe_recheck_index_daily_permission())
            await asyncio.sleep(0)
            second = asyncio.create_task(pipeline._maybe_recheck_daily_bars_permission())
            assert await first is PermissionMaintenanceResult.PROBED
            assert await second is PermissionMaintenanceResult.PROBED
            assert [name for name, _ in sdk.calls[len(sdk_before):]] == [
                "index_daily", "daily",
            ]
            assert not control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("authority", ("legacy_certificate", "missing_bound_semantics"))
def test_daily_bars_respects_legacy_and_bound_stock_authority_modes(
    tmp_path, monkeypatch, authority,
) -> None:
    async def scenario() -> None:
        composition, sdk, certification_path = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        if authority == "legacy_certificate":
            import trade_plan_monitor.web.monitor_composition as monitor_composition

            original_pipeline = monitor_composition.ProductionMonitorPipeline

            def legacy_pipeline(**kwargs):
                evidence = load_stock_certification(
                    certification_path, now=kwargs["clock"].now(),
                    endpoint_url=str(kwargs["configuration"].api_url).rstrip("/"),
                )
                assert evidence is not None and evidence.ready
                kwargs["stock_certification"] = evidence
                kwargs["semantic_bindings"] = None
                return original_pipeline(**kwargs)

            monkeypatch.setattr(
                monitor_composition, "ProductionMonitorPipeline", legacy_pipeline,
            )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            if authority == "legacy_certificate":
                assert pipeline._semantic_bindings is None
                assert pipeline._stock_semantics is None
                assert pipeline._stock_certification_current()
            else:
                pipeline._stock_semantics = None

            result = await pipeline._maybe_recheck_daily_bars_permission()
            if authority == "legacy_certificate":
                assert result is PermissionMaintenanceResult.PROBED
                assert [name for name, _ in sdk.calls[len(sdk_before):]] == ["daily"]
                assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            else:
                assert result is PermissionMaintenanceResult.DEFERRED
                local_due = runtime._clock.now() + timedelta(seconds=30)
                assert pipeline.next_permission_probe_due_at() == local_due
                assert pipeline.next_permission_probe_due_at() == local_due
                assert await pipeline._maybe_recheck_daily_bars_permission() is (
                    PermissionMaintenanceResult.SKIPPED
                )
                assert pipeline.next_permission_probe_due_at() == local_due
                runtime._clock.current = local_due
                assert await pipeline._maybe_recheck_daily_bars_permission() is (
                    PermissionMaintenanceResult.DEFERRED
                )
                assert pipeline.next_permission_probe_due_at() == (
                    local_due + timedelta(seconds=30)
                )
                assert tuple(sdk.calls) == sdk_before
                assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_restored_stock_semantic_file_keeps_restart_latch_and_local_defer(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            path = tmp_path / "data/live-certification/stock-semantic.json"
            original = path.read_bytes()
            try:
                path.write_text("{}", encoding="utf-8")
                assert not pipeline._stock_certification_current()
            finally:
                path.write_bytes(original)
            assert pipeline._admission_revoked()
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            for _ in range(2):
                with pytest.raises(RecoveryAdmissionChangedError):
                    await pipeline._maybe_recheck_daily_bars_permission()
                assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
                assert pipeline._permission_probe_deferred_until == {}
                assert pipeline._permission_rotation_state.last_operation is None
                assert pipeline._admission_revoked()
            assert tuple(sdk.calls) == sdk_before
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_unauthorized_daily_bars_defer_does_not_take_index_due_slot(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, include_index=True,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            pipeline._stock_semantics = None
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            expected_check = runtime._clock.now() + timedelta(seconds=30)

            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert pipeline._permission_probe_deferred_until[TushareOperation.DAILY_BARS] == (
                expected_check
            )
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            due = pipeline.select_due_permission_probe()
            assert due is not None and due.operation is TushareOperation.INDEX_DAILY
            assert pipeline._permission_rotation_state.last_operation is None
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_weekend_current_daily_proves_only_last_real_weekday_anchor(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            friday = ANCHOR + timedelta(days=4)
            saturday = friday + timedelta(days=1)
            database = tmp_path / "monitor.sqlite3"
            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    session.execute(delete(TradingCalendar).where(
                        TradingCalendar.exchange == "SSE",
                        TradingCalendar.cal_date < saturday,
                    ))
            finally:
                engine.dispose()
            _seed_open_day(database, friday)
            _seed_open_day(database, saturday)  # Corrupt weekend-open row.
            runtime._clock.current = datetime.combine(
                saturday, datetime.min.time(), runtime._clock.now().tzinfo,
            ).replace(hour=10, minute=5)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            assert pipeline._stock_certification_current()

            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.PROBED
            )
            assert tuple(sdk.calls[len(sdk_before):]) == (
                _daily_call(current_mixed_plan().symbol, friday),
            )
            assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_daily_bars_transport_seam_rechecks_after_worker_entry(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            original_probe = pipeline.provider.probe_daily_bars_permission

            def revoke_after_worker_gate(_provider, symbol, anchor, *, _physical_start=None):
                pipeline._generation_current = lambda: False
                return original_probe(symbol, anchor, _physical_start=_physical_start)

            monkeypatch.setattr(
                type(pipeline.provider), "probe_daily_bars_permission",
                revoke_after_worker_gate,
            )
            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert tuple(sdk.calls) == sdk_before
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) >= (
                runtime._clock.now() + timedelta(seconds=299)
            )
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ("not_due", "shared_429", "no_authority", "other_scope"))
def test_daily_bars_gate_does_not_reserve_or_call_sdk(
    tmp_path, monkeypatch, reason,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            if reason == "other_scope":
                await _block(control, TushareOperation.TRADING_CALENDAR)
            await _block(control, TushareOperation.DAILY_BARS)
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            sdk_before = tuple(sdk.calls)
            if reason != "not_due":
                runtime._clock.current += timedelta(seconds=301)
            if reason == "shared_429":
                def rate_limited() -> None:
                    raise TushareProviderError(
                        TushareErrorCode.RATE_LIMITED, "current_day_minutes",
                    )

                with pytest.raises(RequestControlError):
                    await control.execute(
                        TushareOperation.CURRENT_DAY_MINUTES, rate_limited,
                        work_key="seed:limits-shared",
                    )
            if reason == "no_authority":
                pipeline._generation_current = lambda: False
            result = await pipeline._maybe_recheck_daily_bars_permission()
            if reason == "no_authority":
                assert result is PermissionMaintenanceResult.SKIPPED
                assert pipeline._permission_probe_deferred_until == {}
                assert await pipeline._maybe_recheck_daily_bars_permission() is (
                    PermissionMaintenanceResult.SKIPPED
                )
                assert pipeline._permission_probe_deferred_until == {}
            else:
                assert result is PermissionMaintenanceResult.SKIPPED
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            assert pipeline._permission_rotation_state.last_operation is None
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ("save", "callback"))
def test_daily_bars_reservation_fault_never_calls_sdk_or_clears(
    tmp_path, monkeypatch, fault,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            before_cursor = pipeline._permission_rotation_state
            repository = control._recovery_repository
            assert repository is not None
            if fault == "save":
                def failed_save(_rows):
                    raise RecoveryCheckpointError("offline save failed")

                with monkeypatch.context() as patch:
                    patch.setattr(repository, "save", failed_save)
                    with pytest.raises(RecoveryCheckpointError):
                        await pipeline._maybe_recheck_daily_bars_permission()
                assert pipeline._permission_rotation_state == before_cursor
                control._recovery_fault = False
            else:
                def failing_callback(_candidate):
                    def fail_after_save() -> None:
                        raise RuntimeError("private callback detail")

                    return fail_after_save

                monkeypatch.setattr(
                    pipeline, "_permission_probe_reservation_callback",
                    failing_callback,
                )
                with pytest.raises(PermissionReservationCallbackError) as caught:
                    await pipeline._maybe_recheck_daily_bars_permission()
                assert str(caught.value) == "permission reservation callback failed"
                assert pipeline._permission_rotation_state == before_cursor
                assert not control._closed
                assert not control._recovery_fault
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ("queue_abort", "stop", "failed_response", "timeout"))
def test_reserved_daily_bars_keeps_block_after_nonproof_outcome(
    tmp_path, monkeypatch, outcome,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        occupied, release = Event(), Event()

        def occupy_worker() -> str:
            occupied.set()
            release.wait(3)
            return "released"

        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            if outcome == "failed_response":
                sdk._stock_daily = lambda _kwargs: pd.DataFrame()
            elif outcome == "timeout":
                control._timeout_seconds = 0.05
                original_limits = sdk._stock_daily

                def slow_limits(kwargs):
                    release.wait(3)
                    return original_limits(kwargs)

                sdk._stock_daily = slow_limits
            blocker = None
            if outcome in {"queue_abort", "stop"}:
                blocker = asyncio.create_task(control.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    occupy_worker, work_key="hold:daily-limits",
                ))
                assert await asyncio.to_thread(occupied.wait, 1)
            attempt = asyncio.create_task(pipeline._maybe_recheck_daily_bars_permission())
            if outcome in {"queue_abort", "stop"}:
                for _ in range(100):
                    if control.waiting_count:
                        break
                    await asyncio.sleep(0)
                assert control.waiting_count == 1
                assert pipeline._permission_rotation_state.last_operation is (
                    TushareOperation.DAILY_BARS
                )
                if outcome == "queue_abort":
                    pipeline._generation_current = lambda: False
                else:
                    control.close()
                release.set()
                assert await blocker == "released"
                if outcome == "queue_abort":
                    assert await attempt is PermissionMaintenanceResult.DEFERRED
                else:
                    with pytest.raises(RequestControlError) as caught:
                        await attempt
                    assert caught.value.code is RequestControlErrorCode.CLOSED
                    assert caught.value.operation is TushareOperation.DAILY_BARS
                    assert caught.value.attempts == 0
                assert tuple(sdk.calls) == sdk_before
            else:
                assert await attempt is PermissionMaintenanceResult.FAILED
            assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.DAILY_BARS
            )
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) >= (
                runtime._clock.now() + timedelta(seconds=299)
            )
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("response", ("near_deadline", "clock_rewind", "midnight"))
def test_daily_bars_response_uses_frozen_start_and_same_date_authority(
    tmp_path, monkeypatch, response,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            captured_at = runtime._clock.now()
            if response == "near_deadline":
                next_due = min(
                    item.due_at for item in runtime._scheduler.deadlines_for_date(
                        captured_at.date(),
                    ) if item.due_at > captured_at
                )
                assert next_due - captured_at > timedelta(seconds=31.25)
                response_at = next_due - timedelta(seconds=17)
            elif response == "clock_rewind":
                response_at = captured_at - timedelta(seconds=1)
            else:
                response_at = datetime.combine(
                    captured_at.date() + timedelta(days=1),
                    datetime.min.time(), captured_at.tzinfo,
                )
            original_limits = sdk._stock_daily

            def moved_response(kwargs):
                runtime._clock.current = response_at
                return original_limits(kwargs)

            sdk._stock_daily = moved_response
            result = await pipeline._maybe_recheck_daily_bars_permission()
            if response == "near_deadline":
                assert result is PermissionMaintenanceResult.PROBED
                assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            else:
                assert result is PermissionMaintenanceResult.FAILED
                assert control.is_permission_blocked(TushareOperation.DAILY_BARS)
                assert pipeline._permission_rotation_state.last_operation is (
                    TushareOperation.DAILY_BARS
                )
            assert [name for name, _ in sdk.calls].count("daily") >= 1
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("demand", ("no_current", "no_anchor"))
def test_missing_daily_bars_demand_or_anchor_sets_fixed_local_defer(
    tmp_path, monkeypatch, demand,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=demand != "no_current",
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            if demand == "no_current":
                _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            else:
                engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
                try:
                    with create_session_factory(engine).begin() as session:
                        session.execute(delete(TradingCalendar).where(
                            TradingCalendar.exchange == "SSE",
                            TradingCalendar.cal_date < runtime._clock.now().date(),
                        ))
                finally:
                    engine.dispose()
            await _block(control, TushareOperation.DAILY_BARS)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            raw = control.raw_permission_retry_at(TushareOperation.DAILY_BARS)
            expected = runtime._clock.now() + timedelta(seconds=30)

            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert pipeline._permission_probe_deferred_until[
                TushareOperation.DAILY_BARS
            ] == expected
            assert pipeline.next_permission_probe_due_at() == expected
            assert pipeline.next_permission_probe_due_at() == expected
            assert await pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.SKIPPED
            )
            assert pipeline._permission_probe_deferred_until[
                TushareOperation.DAILY_BARS
            ] == expected
            assert control.raw_permission_retry_at(TushareOperation.DAILY_BARS) == raw
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())
