"""Offline historical index permission rechecks use only certified anchor data."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from threading import Event, current_thread, main_thread

import pandas as pd
import pytest
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select
from test_production_certification_gate import _composition

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import (
    ProviderRecoveryRepository,
    RecoveryCheckpoint,
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import MarketIndexSnapshot, TradingCalendar
from trade_plan_monitor.web.monitor_composition import (
    _provider_recovery_identity,
    create_monitor_composition,
)

ANCHOR = date(2026, 9, 7)


def _complete_index_day(index_code: MarketIndexCode, anchor: date) -> pd.DataFrame:
    rows = []
    for start_hour, start_minute in ((9, 35), (13, 5)):
        first = datetime.combine(anchor, datetime.min.time()).replace(
            hour=start_hour, minute=start_minute
        )
        for offset in range(24):
            rows.append(
                {
                    "ts_code": index_code.value,
                    "trade_time": (first + timedelta(minutes=5 * offset)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100",
                    "vol": "1000",
                    "amount": "10000",
                }
            )
    return pd.DataFrame(rows)


def _seed_anchor(database, anchor: date, *, is_open: bool = True) -> None:
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            session.add(
                TradingCalendar(
                    exchange="SSE",
                    cal_date=anchor,
                    is_open=is_open,
                    previous_trade_date=anchor - timedelta(days=3),
                )
            )
    finally:
        engine.dispose()


async def _block(controller, operation: TushareOperation) -> None:
    # A direct provider permission denial creates the durable operation latch.
    def permission_denied():
        raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, operation.value)

    with pytest.raises(RequestControlError) as caught:
        await controller.execute(operation, permission_denied, work_key=f"seed:{operation.value}")
    assert caught.value.code is RequestControlErrorCode.BLOCKED_PERMISSION


async def _blocked_case(tmp_path, monkeypatch, *, anchor: bool | None = True):
    composition, sdk, _ = _composition(
        tmp_path,
        monkeypatch,
        active_plan=False,
        include_index=True,
        stock_certification=False,
        persisted_calendar=True,
    )
    if anchor is not None:
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR, is_open=anchor)
    assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
    runtime = composition._runtime
    state = runtime._probe_capabilities.__self__
    pipeline = state._pipeline
    assert pipeline is not None
    control = runtime._request_controller
    await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
    runtime._clock.current += timedelta(seconds=301)
    return composition, sdk, pipeline, control


async def _until(predicate) -> None:
    async def poll():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=5)


@pytest.mark.parametrize("extra_row", (False, True))
def test_start_labeled_historical_probe_requires_complete_shifted_session(
    extra_row: bool,
) -> None:
    frame = _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
    frame["trade_time"] = (pd.to_datetime(frame["trade_time"]) - timedelta(minutes=5)).dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    if extra_row:
        frame = pd.concat((frame, frame.iloc[[0]]), ignore_index=True)

    class SDK:
        def idx_mins(self, **kwargs):
            assert kwargs["freq"] == "5min"
            return frame

    profile = certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.READY
                if code is MarketIndexCode.SSE_COMPOSITE
                else TushareMarketIndexCapabilityStatus.DEFERRED
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.START,
    )
    provider = TushareMarketIndexProvider(
        profile=profile,
        client=SDK(),
        now=lambda: datetime(2026, 9, 8, 10, 0, 15, tzinfo=SHANGHAI),
    )
    if extra_row:
        with pytest.raises(TushareProviderError) as caught:
            provider.probe_historical_minutes_permission(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
        assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    else:
        provider.probe_historical_minutes_permission(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
        assert provider._historical_minute_cache == {}


@pytest.mark.parametrize(
    ("extra_time", "damage"),
    (
        ("09:30:00", None),
        ("09:25:00", None),
        ("15:05:00", None),
        ("09:30:00", "bad_high"),
        ("09:30:00", "bad_volume"),
        ("09:30:00", "wrong_index"),
    ),
)
def test_end_labeled_49th_row_accepts_only_valid_opening_label(
    extra_time: str, damage: str | None,
) -> None:
    frame = _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
    extra = frame.iloc[0].copy()
    extra["trade_time"] = f"{ANCHOR:%Y-%m-%d} {extra_time}"
    if damage == "bad_high":
        extra["high"] = "1"
    elif damage == "bad_volume":
        extra["vol"] = "nan"
    elif damage == "wrong_index":
        extra["ts_code"] = MarketIndexCode.STAR_50.value
    frame = pd.concat((frame, pd.DataFrame([extra])), ignore_index=True)

    class SDK:
        def idx_mins(self, **_kwargs):
            return frame

    profile = certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.READY
                if code is MarketIndexCode.SSE_COMPOSITE
                else TushareMarketIndexCapabilityStatus.DEFERRED
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    provider = TushareMarketIndexProvider(
        profile=profile,
        client=SDK(),
        now=lambda: datetime(2026, 9, 8, 10, 0, 15, tzinfo=SHANGHAI),
    )
    if extra_time == "09:30:00" and damage is None:
        provider.probe_historical_minutes_permission(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
        assert provider._historical_minute_cache == {}
    else:
        with pytest.raises(TushareProviderError) as caught:
            provider.probe_historical_minutes_permission(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
        assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_valid_completed_sse_day_clears_only_historical_permission_without_business_write(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            control = runtime._request_controller
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            await _block(control, TushareOperation.INDEX_REALTIME_MINUTES)
            runtime._clock.current += timedelta(seconds=301)
            sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
                MarketIndexCode.SSE_COMPOSITE, ANCHOR
            )
            before = len(sdk.calls)

            await pipeline._maybe_recheck_historical_index_permission()

            assert len(sdk.calls) == before + 1
            assert sdk.calls[-1] == (
                "idx_mins",
                {
                    "ts_code": MarketIndexCode.SSE_COMPOSITE.value,
                    "freq": "5min",
                    "start_date": "2026-09-07 09:30:00",
                    "end_date": "2026-09-07 15:00:00",
                    "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
                },
            )
            assert not control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert control.is_permission_blocked(TushareOperation.INDEX_REALTIME_MINUTES)
            assert pipeline.index_provider._historical_minute_cache == {}
            with state._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(MarketIndexSnapshot)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("anchor", (None, False))
def test_missing_or_closed_calendar_anchor_keeps_historical_block_without_sdk(
    tmp_path,
    monkeypatch,
    anchor,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(
            tmp_path,
            monkeypatch,
            anchor=anchor,
        )
        try:
            before = tuple(sdk.calls)
            await pipeline._maybe_recheck_historical_index_permission()
            assert tuple(sdk.calls) == before
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_missing_anchor_memory_defer_is_honored_if_anchor_arrives_early(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(
            tmp_path, monkeypatch, anchor=None,
        )
        try:
            await pipeline._maybe_recheck_historical_index_permission()
            first_due = pipeline.next_historical_index_permission_due_at()
            assert first_due == pipeline._clock.now() + timedelta(seconds=30)
            _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
            sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
                MarketIndexCode.SSE_COMPOSITE, ANCHOR
            )
            await pipeline._maybe_recheck_historical_index_permission()
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            pipeline._clock.current = first_due
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.DEFERRED
            )
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            pipeline._clock.current = pipeline.next_historical_index_permission_due_at()
            await pipeline._maybe_recheck_historical_index_permission()
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
            assert not control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert pipeline.next_historical_index_permission_due_at() is None
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    ("semantic", "configuration", "generation", "stopping", "expiry", "cooldown", "no_ready_sse"),
)
def test_stale_authority_or_cooldown_cannot_start_historical_probe(
    tmp_path,
    monkeypatch,
    change,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        try:
            if change == "semantic":
                semantic = tmp_path / "data/live-certification/index-semantic.json"
                semantic.write_text("{}", encoding="utf-8")
            elif change == "configuration":
                config = tmp_path / "config/app.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "offline-test-token",
                        "changed-token",
                    ),
                    encoding="utf-8",
                )
            elif change == "generation":
                pipeline._generation_current = lambda: False
            elif change == "stopping":
                pipeline._admission_revoked = lambda: True
            elif change == "expiry":
                expired = pipeline._index_semantics.provenance.valid_until
                pipeline._clock.current = expired + timedelta(seconds=1)
                _seed_anchor(tmp_path / "monitor.sqlite3", expired.date())
            elif change == "no_ready_sse":
                profile = pipeline.index_provider.profile
                capabilities = dict(profile.capabilities)
                capabilities[MarketIndexCode.SSE_COMPOSITE] = (
                    TushareMarketIndexCapabilityStatus.DEFERRED
                )
                capabilities[MarketIndexCode.STAR_50] = TushareMarketIndexCapabilityStatus.DEFERRED
                pipeline.index_provider._profile = replace(
                    profile,
                    capabilities=capabilities,
                )
            else:

                def limited():
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "index_daily")

                with pytest.raises(RequestControlError):
                    await control.execute(
                        TushareOperation.INDEX_DAILY,
                        limited,
                        work_key="shared-cooldown",
                    )
            before = tuple(sdk.calls)
            await pipeline._maybe_recheck_historical_index_permission()
            assert tuple(sdk.calls) == before
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            if change == "cooldown":
                assert pipeline.next_historical_index_permission_due_at() > pipeline._clock.now()
            else:
                assert pipeline.next_historical_index_permission_due_at() is None
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ("permission", "rate_limit", "connection", "timeout"))
def test_provider_failure_retains_historical_permission_and_reservation(
    tmp_path,
    monkeypatch,
    failure,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        try:

            def fail(_kwargs):
                if failure == "permission":
                    raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "idx_mins")
                if failure == "rate_limit":
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "idx_mins")
                if failure == "connection":
                    raise ProviderConnectionError("offline transport interruption")
                raise TimeoutError("offline provider timeout")

            sdk._historical_index_minutes = fail
            await pipeline._maybe_recheck_historical_index_permission()
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert control.permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            ) >= pipeline._clock.now() + timedelta(seconds=300)
            if failure == "rate_limit":
                assert control.cooldown_until >= pipeline._clock.now() + timedelta(seconds=300)
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "damage",
    ("empty", "missing", "mixed", "duplicate", "wrong_day", "bad_numeric", "extra_column"),
)
def test_incomplete_or_mixed_historical_response_retains_block_and_reservation(
    tmp_path,
    monkeypatch,
    damage,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        try:
            frame = _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)
            if damage == "empty":
                frame = frame.iloc[0:0]
            elif damage == "missing":
                frame = frame.iloc[:-1]
            elif damage == "mixed":
                frame.loc[0, "ts_code"] = MarketIndexCode.STAR_50.value
            elif damage == "duplicate":
                frame.loc[1, "trade_time"] = frame.loc[0, "trade_time"]
            elif damage == "wrong_day":
                frame.loc[0, "trade_time"] = "2026-09-06 09:35:00"
            elif damage == "bad_numeric":
                frame.loc[0, "close"] = "nan"
            else:
                frame["unexpected"] = "value"
            sdk._historical_index_minutes = lambda _kwargs: frame
            await pipeline._maybe_recheck_historical_index_permission()
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert control.permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            ) >= pipeline._clock.now() + timedelta(seconds=300)
            assert pipeline.index_provider._historical_minute_cache == {}
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_queued_historical_probe_crossing_midnight_never_calls_sdk(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        started = Event()
        release = Event()

        def occupy_worker():
            started.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return "released"

        hold_task = asyncio.create_task(
            control.execute(
                TushareOperation.INDEX_DAILY,
                occupy_worker,
                work_key="hold-worker",
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 5)
            probe_task = asyncio.create_task(pipeline._maybe_recheck_historical_index_permission())
            await _until(lambda: control.waiting_count > 0)
            reservation = control.permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert reservation is not None
            pipeline._clock.current += timedelta(days=1)
            release.set()
            assert await hold_task == "released"
            await probe_task
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_queued_probe_yields_to_market_without_spending_permission_failure_budget(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        entered = Event()
        release = Event()

        def occupy_worker():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return "released"

        hold_task = asyncio.create_task(control.execute(
            TushareOperation.INDEX_DAILY, occupy_worker, work_key="hold-market-guard",
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            probe_task = asyncio.create_task(pipeline._maybe_recheck_historical_index_permission())
            await _until(lambda: control.waiting_count > 0)
            reserved = control.permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert reserved is not None
            pipeline._clock.current = datetime(2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI)
            release.set()
            assert await hold_task == "released"
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            assert (
                control.permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
                == reserved
            )
            assert control.backoff_until(
                f"permission:idx_mins:{MarketIndexCode.SSE_COMPOSITE.value}:{ANCHOR}"
            ) is None
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            pipeline._clock.current = reserved
            sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
                MarketIndexCode.SSE_COMPOSITE, ANCHOR
            )
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ("configuration", "semantic_revision", "semantic_corrupt"))
def test_queued_file_change_and_restore_never_starts_or_unlocks_probe(
    tmp_path, monkeypatch, change,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        entered = Event()
        release = Event()

        def occupy_worker():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker hold expired")
            return "released"

        hold_task = asyncio.create_task(control.execute(
            TushareOperation.INDEX_DAILY, occupy_worker,
            work_key=f"hold-file-change:{change}",
        ))
        path = (
            tmp_path / "config/app.yaml"
            if change == "configuration"
            else tmp_path / "data/live-certification/index-semantic.json"
        )
        original = path.read_bytes()
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            probe_task = asyncio.create_task(pipeline._maybe_recheck_historical_index_permission())
            await _until(lambda: control.waiting_count > 0)
            if change == "configuration":
                path.write_bytes(original.replace(b"offline-test-token", b"changed-token"))
            elif change == "semantic_revision":
                payload = json.loads(original)
                assert "semanticRevision" in payload
                payload["semanticRevision"] = "0" * 64
                path.write_text(json.dumps(payload), encoding="utf-8")
            else:
                path.write_text("{}", encoding="utf-8")
            release.set()
            assert await hold_task == "released"
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            path.write_bytes(original)
            assert pipeline._admission_revoked()
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.SKIPPED
            )
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
        finally:
            release.set()
            path.write_bytes(original)
            await composition.stop()

    asyncio.run(scenario())


def test_sdk_worker_start_rechecks_market_window_after_admission(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        original_submit = control._executor.submit

        def advance_before_worker(call, *args, **kwargs):
            def worker():
                pipeline._clock.current = datetime(
                    2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI,
                )
                return call(*args, **kwargs)

            return original_submit(worker)

        monkeypatch.setattr(control._executor, "submit", advance_before_worker)
        try:
            before = tuple(sdk.calls)
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.DEFERRED
            )
            assert tuple(sdk.calls) == before
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert control.permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            ) >= pipeline._clock.now() + timedelta(seconds=266)
        finally:
            monkeypatch.setattr(control._executor, "submit", original_submit)
            await composition.stop()

    asyncio.run(scenario())


def test_sdk_worker_admission_uses_frozen_calendar_without_database_read(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        scheduler = composition._runtime._scheduler
        original_calendar = scheduler._is_open_on
        worker_reads: list[date] = []

        def checked_calendar(trade_date: date):
            if current_thread() is not main_thread():
                worker_reads.append(trade_date)
            return original_calendar(trade_date)

        monkeypatch.setattr(scheduler, "_is_open_on", checked_calendar)
        sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
            MarketIndexCode.SSE_COMPOSITE, ANCHOR
        )
        try:
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert worker_reads == []
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_sdk_worker_after_stop_cannot_start_historical_probe(tmp_path, monkeypatch) -> None:
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        entered = Event()
        release = Event()
        original_submit = control._executor.submit

        def hold_before_worker(call, *args, **kwargs):
            def worker():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test worker hold expired")
                return call(*args, **kwargs)

            return original_submit(worker)

        monkeypatch.setattr(control._executor, "submit", hold_before_worker)
        try:
            probe_task = asyncio.create_task(pipeline._maybe_recheck_historical_index_permission())
            assert await asyncio.to_thread(entered.wait, 5)
            stop_task = asyncio.create_task(composition.stop())
            await _until(lambda: not pipeline._generation_current())
            release.set()
            assert await probe_task is PermissionMaintenanceResult.DEFERRED
            await stop_task
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
        finally:
            release.set()
            monkeypatch.setattr(control._executor, "submit", original_submit)
            await composition.stop()

    asyncio.run(scenario())


def test_unknown_weekday_calendar_uses_possible_minute_window(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=False,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            await _block(runtime._request_controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
            runtime._clock.current = datetime(2026, 9, 8, 10, 5, 50, tzinfo=SHANGHAI)
            assert state.is_open_on(runtime._clock.now().date()) is None
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.DEFERRED
            )
            assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            possible_due = datetime(2026, 9, 8, 10, 6, 12, tzinfo=SHANGHAI)
            assert pipeline.next_historical_index_permission_due_at() == (
                possible_due + timedelta(microseconds=1)
            )
            runtime._clock.current = possible_due + timedelta(microseconds=1)
            sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
                MarketIndexCode.SSE_COMPOSITE, ANCHOR
            )
            assert (
                await pipeline._maybe_recheck_historical_index_permission()
                is PermissionMaintenanceResult.PROBED
            )
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_historical_response_after_midnight_cannot_unlock(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, pipeline, control = await _blocked_case(tmp_path, monkeypatch)
        entered = Event()
        release = Event()
        frame = _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)

        def delayed(_kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test response hold expired")
            return frame

        sdk._historical_index_minutes = delayed
        try:
            probe_task = asyncio.create_task(pipeline._maybe_recheck_historical_index_permission())
            assert await asyncio.to_thread(entered.wait, 5)
            pipeline._clock.current += timedelta(days=1)
            release.set()
            await probe_task
            assert [name for name, _ in sdk.calls].count("idx_mins") == 1
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert (
                control.permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES) is not None
            )
        finally:
            release.set()
            await composition.stop()

    asyncio.run(scenario())


def test_independent_deadline_rechecks_without_current_calendar_or_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=False,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            ProviderRecoveryRepository(
                create_session_factory(engine),
                provider_identity=_provider_recovery_identity("https://example.test"),
            ).save((
                RecoveryCheckpoint(
                    "permission", "idx_mins", datetime(2026, 9, 8, 10, 0, 14, tzinfo=SHANGHAI), 0,
                ),
            ))
        finally:
            engine.dispose()
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        runtime = composition._runtime
        state = runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        assert pipeline is not None
        control = runtime._request_controller
        assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
        sdk._historical_index_minutes = lambda _kwargs: _complete_index_day(
            MarketIndexCode.SSE_COMPOSITE, ANCHOR
        )
        try:
            assert state.is_open_on(runtime._clock.now().date()) is None
            assert pipeline.index_service.latest_snapshots() == {}
            deadline = runtime._scheduler.next_deadline()
            assert deadline is not None
            assert deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert deadline.due_at == runtime._clock.now()
            previous_market_cursor = runtime._last_deadline_at
            runtime._advance_progress_deadline(deadline)
            assert runtime._last_deadline_at == previous_market_cursor
            await state.run_deadline(deadline)
            minute_calls = [kwargs for name, kwargs in sdk.calls if name == "idx_mins"]
            assert len(minute_calls) == 1
            assert minute_calls[0]["start_date"] == "2026-09-07 09:30:00"
            assert not control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
            assert state.next_index_permission_at() is None
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_missing_anchor_defers_due_probe_in_memory_without_durable_write(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=False,
        )
        assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
        runtime = composition._runtime
        state = runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        assert pipeline is not None
        control = runtime._request_controller
        await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
        runtime._clock.current += timedelta(seconds=301)
        try:
            durable_due = control.permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            deadline = runtime._scheduler.next_deadline()
            assert deadline is not None and deadline.kind is DeadlineKind.INDEX_PERMISSION
            before = tuple(sdk.calls)
            await state.run_deadline(deadline)
            assert tuple(sdk.calls) == before
            assert state.next_index_permission_at() == runtime._clock.now() + timedelta(seconds=30)
            assert (
                control.permission_retry_at(TushareOperation.INDEX_HISTORICAL_MINUTES)
                == durable_due
            )
            assert runtime._scheduler.next_deadline().due_at > runtime._clock.now()
        finally:
            await composition.stop()

        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=tmp_path / "monitor.sqlite3",
        )
        try:
            assert (await replacement.start()).status in {
                RuntimeServiceStatus.RUNNING, RuntimeServiceStatus.DEGRADED,
            }
            restarted = replacement._runtime
            restarted_state = restarted._probe_capabilities.__self__
            assert restarted_state.next_index_permission_at() == durable_due
            restart_deadline = restarted._scheduler.next_deadline()
            assert restart_deadline is not None
            assert restart_deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert restart_deadline.due_at == restarted._clock.now()
            await restarted_state.run_deadline(restart_deadline)
            assert restarted_state.next_index_permission_at() == (
                restarted._clock.now() + timedelta(seconds=30)
            )
            assert tuple(sdk.calls) == before
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def test_permission_maintenance_one_second_before_market_deadline_yields_to_market(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            control = runtime._request_controller
            runtime._clock.current = runtime._clock.now().replace(second=11)
            await _block(control, TushareOperation.INDEX_HISTORICAL_MINUTES)
            runtime._clock.current += timedelta(seconds=300)
            deadline = runtime._scheduler.next_deadline()
            assert deadline is not None and deadline.kind is DeadlineKind.INDEX_PERMISSION
            assert deadline.due_at == runtime._clock.now()
            market_deadline = runtime._scheduler.deadlines_for_date(deadline.trade_date)
            next_market = next(item for item in market_deadline if item.due_at > deadline.due_at)
            assert next_market.due_at == deadline.due_at + timedelta(seconds=1)
            before = tuple(sdk.calls)

            def slow_probe(_kwargs):
                runtime._clock.current += timedelta(seconds=15)
                return _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)

            sdk._historical_index_minutes = slow_probe
            await state.run_deadline(deadline)
            assert tuple(sdk.calls) == before
            assert runtime._clock.now() < next_market.due_at
            assert control.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_runtime_loop_runs_market_minute_before_deferred_permission_probe(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            ProviderRecoveryRepository(
                create_session_factory(engine),
                provider_identity=_provider_recovery_identity("https://example.test"),
            ).save((RecoveryCheckpoint(
                "permission", "idx_mins",
                datetime(2026, 9, 8, 10, 5, 11, tzinfo=SHANGHAI), 0,
            ),))
        finally:
            engine.dispose()
        runtime = composition._runtime
        runtime._clock.current = datetime(2026, 9, 8, 10, 5, 11, tzinfo=SHANGHAI)
        runtime._clock.released_sleeps = 2
        observed: list[DeadlineKind] = []
        original_run = runtime._run_deadline

        async def capture(deadline: MarketDeadline):
            observed.append(deadline.kind)
            if deadline.kind is DeadlineKind.REALTIME_MINUTE:
                assert [name for name, _ in sdk.calls].count("idx_mins") == 0
            return await original_run(deadline)

        runtime._run_deadline = capture
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            await _until(lambda: len(observed) >= 2)
            assert observed[:2] == [DeadlineKind.INDEX_PERMISSION, DeadlineKind.REALTIME_MINUTE]
            assert runtime._last_deadline_at == datetime(
                2026, 9, 8, 10, 5, 12, tzinfo=SHANGHAI,
            )
            assert runtime._request_controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_blocked_historical_scope_defers_due_index_recovery_without_attempt_or_call(
    tmp_path, monkeypatch,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        failed_calls = []

        def fail_index(**kwargs):
            failed_calls.append(kwargs)
            raise ProviderConnectionError("offline historical index failure")

        sdk.idx_mins = fail_index
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=runtime._clock.now().date(),
                due_at=runtime._clock.now(),
                bar_end=runtime._clock.now().replace(second=0),
            ))
            records = pipeline.index_service.recovery_records()
            assert records
            due = min(record[4] for record in records)
            await _block(runtime._request_controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
            runtime._clock.current = due
            before = len(failed_calls)
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.INDEX_RECOVERY,
                trade_date=due.date(), due_at=due,
            ))
            assert len(failed_calls) == before
            assert pipeline.index_service.recovery_records() == records
            assert state.next_index_recovery_at() > due
            with state.unit_of_work_factory() as work:
                assert work.projections.list_market_index_recoveries() == records
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("probe_seconds", (0, 1))
def test_permission_and_index_recovery_due_at_five_minute_limit_probe_first(
    tmp_path, monkeypatch, probe_seconds,
) -> None:
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        _seed_anchor(tmp_path / "monitor.sqlite3", ANCHOR)

        def fail_index(**_kwargs):
            raise ProviderConnectionError("offline historical index failure")

        sdk.idx_mins = fail_index
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=runtime._clock.now().date(),
                due_at=runtime._clock.now(),
                bar_end=runtime._clock.now().replace(second=0),
            ))
            first_recoveries = pipeline.index_service.recovery_records()
            assert first_recoveries
            await _block(runtime._request_controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
            recovery_due = min(record[4] for record in first_recoveries)
            runtime._clock.current = recovery_due
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.INDEX_RECOVERY,
                trade_date=recovery_due.date(), due_at=recovery_due,
            ))
            assert pipeline.index_service.recovery_records() == first_recoveries
            permission_due = runtime._request_controller.permission_retry_at(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert permission_due is not None
            runtime._clock.current = permission_due
            assert state.next_index_recovery_at() <= permission_due
            assert state.next_index_permission_at() == permission_due
            deadline = runtime._scheduler.next_deadline()
            assert deadline is not None
            assert deadline.kind is DeadlineKind.INDEX_PERMISSION
            def complete_probe(**_kwargs):
                runtime._clock.current += timedelta(seconds=probe_seconds)
                return _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)

            sdk.idx_mins = complete_probe
            await state.run_deadline(deadline)
            assert not runtime._request_controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            del sdk.idx_mins
            if probe_seconds == 0:
                assert state.next_index_recovery_at() <= permission_due
                await state.run_deadline(MarketDeadline(
                    kind=DeadlineKind.INDEX_RECOVERY,
                    trade_date=permission_due.date(), due_at=permission_due,
                ))
                assert pipeline.index_service.recovery_records() != first_recoveries
            else:
                assert state.next_index_recovery_at() is None
                assert pipeline.index_service.recovery_records() == ()
        finally:
            await composition.stop()

    asyncio.run(scenario())
