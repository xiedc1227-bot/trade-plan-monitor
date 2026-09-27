"""Offline INDEX_DAILY permission maintenance stays inside one serialized path."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from threading import Event, current_thread, main_thread

import pandas as pd
import pytest
from sqlalchemy import delete
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import (
    PermissionReservationCallbackError,
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
    TushareOperation,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.runtime_recovery import RecoveryCheckpointError
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


def _one_official_index_day(
    index_code: MarketIndexCode, trade_day: date = ANCHOR,
) -> pd.DataFrame:
    return pd.DataFrame(({
        "ts_code": index_code.value,
        "trade_date": trade_day.strftime("%Y%m%d"),
        "open": "100", "high": "101", "low": "99", "close": "100",
        "vol": "1000", "amount": "10000",
    },))


def test_due_index_daily_proves_once_without_business_cache_write(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            sdk._index_daily = lambda kwargs: _one_official_index_day(
                MarketIndexCode(str(kwargs["ts_code"])),
            )
            original_work = pipeline._work

            def owner_only_work():
                assert current_thread() is main_thread()
                return original_work()

            monkeypatch.setattr(pipeline, "_work", owner_only_work)

            assert (
                await pipeline._maybe_recheck_index_daily_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert not control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            assert tuple(sdk.calls[len(sdk_before):]) == ((
                "index_daily",
                {
                    "ts_code": MarketIndexCode.SSE_COMPOSITE.value,
                    "start_date": ANCHOR.strftime("%Y%m%d"),
                    "end_date": ANCHOR.strftime("%Y%m%d"),
                    "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
                },
            ),)
            assert pipeline.index_provider._intraday_daily_cache == {}
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_newer_persisted_weekend_open_cannot_replace_friday_index_daily_anchor(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            friday = ANCHOR - timedelta(days=3)
            sunday = ANCHOR - timedelta(days=1)
            _seed_open_day(tmp_path / "monitor.sqlite3", friday)
            _seed_open_day(tmp_path / "monitor.sqlite3", sunday)
            assert not pipeline._persisted_completed_sse_open_on(sunday)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            candidate = pipeline.select_due_permission_probe()
            assert candidate is not None
            assert candidate.operation is TushareOperation.INDEX_DAILY
            assert candidate.anchor_date == friday

            sdk_before = tuple(sdk.calls)
            sdk._index_daily = lambda kwargs: _one_official_index_day(
                MarketIndexCode(str(kwargs["ts_code"])), friday,
            )
            assert await pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.PROBED
            )
            assert tuple(sdk.calls[len(sdk_before):]) == ((
                "index_daily",
                {
                    "ts_code": MarketIndexCode.SSE_COMPOSITE.value,
                    "start_date": friday.strftime("%Y%m%d"),
                    "end_date": friday.strftime("%Y%m%d"),
                    "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
                },
            ),)
            assert not control.is_permission_blocked(TushareOperation.INDEX_DAILY)
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ("queue_abort", "stop", "failed_response", "timeout"))
def test_reserved_index_daily_advances_once_without_false_success(
    tmp_path, monkeypatch, outcome,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        hold_started, release = Event(), Event()

        def occupy_worker() -> str:
            hold_started.set()
            release.wait(3)
            return "released"

        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            if outcome == "failed_response":
                sdk._index_daily = lambda _kwargs: pd.DataFrame()
            elif outcome == "timeout":
                control._timeout_seconds = 0.05

                def slow_index(kwargs):
                    release.wait(3)
                    return _one_official_index_day(
                        MarketIndexCode(str(kwargs["ts_code"])),
                    )

                sdk._index_daily = slow_index
            blocker = None
            if outcome in {"queue_abort", "stop"}:
                blocker = asyncio.create_task(control.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    occupy_worker, work_key="hold:index-daily",
                ))
                assert await asyncio.to_thread(hold_started.wait, 1)
            attempt = asyncio.create_task(pipeline._maybe_recheck_index_daily_permission())
            if outcome in {"queue_abort", "stop"}:
                for _ in range(100):
                    if control.waiting_count:
                        break
                    await asyncio.sleep(0)
                assert control.waiting_count == 1
                assert pipeline._permission_rotation_state.last_operation is (
                    TushareOperation.INDEX_DAILY
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
                    assert caught.value.operation is TushareOperation.INDEX_DAILY
                    assert caught.value.attempts == 0
                assert tuple(sdk.calls) == sdk_before
            else:
                assert await attempt is PermissionMaintenanceResult.FAILED
                if outcome == "timeout":
                    release.set()
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) >= (
                runtime._clock.now() + timedelta(seconds=299)
            )
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_response_near_next_market_deadline_can_clear_index_daily_permission(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            initial_at = runtime._clock.now()
            next_market_due = min(
                item.due_at for item in runtime._scheduler.deadlines_for_date(
                    initial_at.date(),
                ) if item.due_at > initial_at
            )
            assert next_market_due - initial_at > timedelta(seconds=31.25)
            response_at = next_market_due - timedelta(seconds=17)
            assert timedelta(0) < next_market_due - response_at < timedelta(
                seconds=31.25,
            )

            def near_deadline(kwargs):
                runtime._clock.current = response_at
                return _one_official_index_day(
                    MarketIndexCode(str(kwargs["ts_code"])),
                )

            sdk._index_daily = near_deadline
            assert await pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.PROBED
            )
            assert not control.is_permission_blocked(TushareOperation.INDEX_DAILY)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_response_clock_rewind_keeps_index_daily_block_and_reservation(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            captured_at = runtime._clock.now()

            def rewind_on_response(kwargs):
                runtime._clock.current = captured_at - timedelta(seconds=1)
                return _one_official_index_day(
                    MarketIndexCode(str(kwargs["ts_code"])),
                )

            sdk._index_daily = rewind_on_response
            assert await pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.FAILED
            )
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) >= (
                captured_at + timedelta(seconds=299)
            )
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ("configuration", "semantic", "calendar_same_value"))
def test_queued_index_daily_rejects_restored_authority_or_calendar_epoch_aba(
    tmp_path, monkeypatch, change,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=change == "calendar_same_value",
            persisted_calendar=True,
        )
        entered, release = Event(), Event()

        def occupy_worker() -> str:
            entered.set()
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
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)
            blocker = asyncio.create_task(control.execute(
                TushareOperation.CURRENT_DAY_MINUTES,
                occupy_worker, work_key="hold:index-daily-aba",
            ))
            assert await asyncio.to_thread(entered.wait, 1)
            attempt = asyncio.create_task(pipeline._maybe_recheck_index_daily_permission())
            for _ in range(100):
                if control.waiting_count:
                    break
                await asyncio.sleep(0)
            assert control.waiting_count == 1
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            if change == "calendar_same_value":
                before_epoch = pipeline._calendar_epoch
                key = pipeline._reference_dependency_key(
                    runtime._clock.now().date(), (),
                )
                pipeline._commit_trading_days((TradingDay(
                    exchange="SSE", cal_date=ANCHOR, is_open=True,
                    previous_trade_date=ANCHOR - timedelta(days=3),
                ),), trade_date=runtime._clock.now().date(), captured_key=key)
                assert pipeline._calendar_epoch == before_epoch + 1
                engine = create_sqlite_engine(database)
                try:
                    with create_session_factory(engine)() as session:
                        row = session.get(TradingCalendar, ("SSE", ANCHOR))
                        assert row is not None and row.is_open is True
                finally:
                    engine.dispose()
            else:
                path = (
                    tmp_path / "config/app.yaml"
                    if change == "configuration"
                    else tmp_path / "data/live-certification/index-semantic.json"
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
                        assert not pipeline._index_certification_current()
                finally:
                    path.write_bytes(original)
            release.set()
            assert await blocker == "released"
            assert await attempt is PermissionMaintenanceResult.DEFERRED
            assert tuple(sdk.calls) == sdk_before
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ("save", "callback"))
def test_index_daily_reservation_fault_never_starts_sdk_or_clears_block(
    tmp_path, monkeypatch, fault,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
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
                        await pipeline._maybe_recheck_index_daily_permission()
                assert pipeline._permission_rotation_state == before_cursor
                control._recovery_fault = False  # Restore only for fixture teardown.
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
                    await pipeline._maybe_recheck_index_daily_permission()
                assert str(caught.value) == "permission reservation callback failed"
                assert pipeline._permission_rotation_state == before_cursor
                assert not control._closed
                assert not control._recovery_fault
                assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) == (
                    runtime._clock.now() + timedelta(seconds=300)
                )
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_two_scope_maintenance_tasks_reselect_serially_after_first_reservation(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            sdk._index_daily = lambda kwargs: _one_official_index_day(
                MarketIndexCode(str(kwargs["ts_code"])),
            )
            sdk_before = tuple(sdk.calls)

            async def first_scope() -> None:
                async with pipeline._permission_maintenance_lock:
                    entered.set()
                    await release.wait()
                    candidate = pipeline.select_due_permission_probe()
                    assert candidate is not None
                    assert candidate.operation is (
                        TushareOperation.INDEX_HISTORICAL_MINUTES
                    )
                    with pytest.raises(RequestNotStartedError):
                        await control.recheck_permission(
                            candidate.operation,
                            lambda: pytest.fail("historical SDK must not start"),
                            work_key="rotation:historical-first",
                            can_start=lambda: False,
                            on_reserved=(
                                pipeline._permission_probe_reservation_callback(candidate)
                            ),
                        )

            first = asyncio.create_task(first_scope())
            await entered.wait()
            second = asyncio.create_task(
                pipeline._maybe_recheck_index_daily_permission(),
            )
            await asyncio.sleep(0)
            assert pipeline._permission_rotation_state.last_operation is None
            release.set()
            await first
            assert await second is PermissionMaintenanceResult.PROBED
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            assert len(sdk.calls) == len(sdk_before) + 1
            assert sdk.calls[-1][0] == "index_daily"
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_new_runtime_restores_durable_index_daily_reservation_before_retry(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        first, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        second = None
        try:
            assert (await first.start()).status is RuntimeServiceStatus.RUNNING
            runtime = first._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            sdk._index_daily = lambda _kwargs: pd.DataFrame()
            assert await pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.FAILED
            )
            persisted_due = control.raw_permission_retry_at(TushareOperation.INDEX_DAILY)
            assert persisted_due == runtime._clock.now() + timedelta(seconds=300)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            await first.stop()

            second = create_monitor_composition(
                config_path=tmp_path / "config/app.yaml",
                database_path=tmp_path / "monitor.sqlite3",
            )
            await second.start()
            replacement = second._runtime
            new_pipeline = replacement._probe_capabilities.__self__._pipeline
            assert new_pipeline is not None
            new_control = replacement._request_controller
            assert new_control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) == (
                persisted_due
            )
            assert new_pipeline._permission_rotation_state.last_operation is None
            sdk_before = tuple(sdk.calls)
            assert await new_pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.SKIPPED
            )
            assert tuple(sdk.calls) == sdk_before
            assert new_control.is_permission_blocked(TushareOperation.INDEX_DAILY)
        finally:
            if second is not None:
                await second.stop()
            await first.stop()

    asyncio.run(scenario())


def test_index_daily_transport_seam_rechecks_after_worker_entry(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)
            original_probe = pipeline.index_provider.probe_official_daily_permission
            sdk_before = tuple(sdk.calls)

            def revoke_after_worker_gate(index_code, anchor, *, _physical_start=None):
                pipeline._generation_current = lambda: False
                return original_probe(
                    index_code, anchor, _physical_start=_physical_start,
                )

            monkeypatch.setattr(
                pipeline.index_provider, "probe_official_daily_permission",
                revoke_after_worker_gate,
            )
            assert await pipeline._maybe_recheck_index_daily_permission() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert tuple(sdk.calls) == sdk_before
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_index_daily_response_rereads_persisted_anchor_before_unlock(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
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
            await _block(control, TushareOperation.INDEX_DAILY)
            runtime._clock.current += timedelta(seconds=301)

            def waiting_response(kwargs):
                entered.set()
                release.wait(3)
                return _one_official_index_day(
                    MarketIndexCode(str(kwargs["ts_code"])),
                )

            sdk._index_daily = waiting_response
            attempt = asyncio.create_task(pipeline._maybe_recheck_index_daily_permission())
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
            assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
            assert pipeline._permission_rotation_state.last_operation is (
                TushareOperation.INDEX_DAILY
            )
            assert [name for name, _ in sdk.calls].count("index_daily") == 1
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reason", ("not_due", "shared_429", "no_authority", "no_anchor", "other_scope"),
)
def test_index_daily_gate_skips_or_defers_without_reservation_or_sdk(
    tmp_path, monkeypatch, reason,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            if reason != "no_anchor":
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
            if reason == "other_scope":
                await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            await _block(control, TushareOperation.INDEX_DAILY)
            original_due = control.raw_permission_retry_at(TushareOperation.INDEX_DAILY)
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
                        work_key="seed:shared",
                    )
            if reason == "no_authority":
                pipeline._generation_current = lambda: False
            result = await pipeline._maybe_recheck_index_daily_permission()
            if reason == "no_anchor":
                assert result is PermissionMaintenanceResult.DEFERRED
                local_due = runtime._clock.now() + timedelta(seconds=30)
                assert pipeline.next_permission_probe_due_at() == local_due
                assert pipeline.next_permission_probe_due_at() == local_due
                assert await pipeline._maybe_recheck_index_daily_permission() is (
                    PermissionMaintenanceResult.SKIPPED
                )
                assert pipeline.next_permission_probe_due_at() == local_due
            else:
                assert result is PermissionMaintenanceResult.SKIPPED
            assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) == (
                original_due
            )
            assert tuple(sdk.calls) == sdk_before
            assert pipeline._permission_rotation_state.last_operation is None
        finally:
            await composition.stop()

    asyncio.run(scenario())
