"""Persisted weekend rows cannot masquerade as open index sessions."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import TushareOperation
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import TradingCalendar


def _seed_closed_day(database, day: date) -> None:
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            row = session.get(TradingCalendar, ("SSE", day))
            if row is None:
                session.add(TradingCalendar(
                    exchange="SSE", cal_date=day, is_open=False,
                    previous_trade_date=day - timedelta(days=3),
                ))
            else:
                row.is_open = False
    finally:
        engine.dispose()


def test_newer_false_weekend_open_keeps_friday_historical_index_anchor(
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
            assert pipeline is not None
            friday = ANCHOR - timedelta(days=3)
            sunday = ANCHOR - timedelta(days=1)
            _seed_open_day(tmp_path / "monitor.sqlite3", friday)
            _seed_open_day(tmp_path / "monitor.sqlite3", sunday)
            await _block(runtime._request_controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)

            evidence = pipeline._read_permission_evidence(
                runtime._clock.now(), include_legacy=False, include_history=False,
            )
            assert evidence.historical_anchor == friday
            assert pipeline._historical_index_permission_anchor() == friday
            candidate = next(
                item for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.INDEX_HISTORICAL_MINUTES
            )
            assert candidate.anchor_date == friday
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_false_weekend_open_today_has_no_realtime_index_candidate(
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
            assert pipeline is not None
            saturday = ANCHOR + timedelta(days=5)
            runtime._clock.current = datetime.combine(
                saturday, datetime.min.time(), runtime._clock.now().tzinfo,
            ).replace(hour=10)
            _seed_open_day(tmp_path / "monitor.sqlite3", saturday)
            monkeypatch.setattr(
                pipeline, "_permission_index_code",
                lambda endpoint: (
                    MarketIndexCode.SSE_COMPOSITE
                    if endpoint == "rt_idx_min_daily" else None
                ),
            )
            await _block(runtime._request_controller, TushareOperation.INDEX_REALTIME_MINUTES)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)

            evidence = pipeline._read_permission_evidence(
                runtime._clock.now(), include_legacy=False, include_history=False,
            )
            assert not evidence.current_open
            assert TushareOperation.INDEX_REALTIME_MINUTES not in {
                item.operation for item in pipeline.permission_probe_candidates()
            }
            assert pipeline.select_due_permission_probe() is None
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_completed_weekend_closed_row_remains_calendar_permission_anchor(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=False,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            sunday = ANCHOR - timedelta(days=1)
            _seed_closed_day(tmp_path / "monitor.sqlite3", sunday)
            engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
            try:
                with create_session_factory(engine).begin() as session:
                    monday = session.get(TradingCalendar, ("SSE", ANCHOR))
                    if monday is not None:
                        session.delete(monday)
            finally:
                engine.dispose()
            await _block(runtime._request_controller, TushareOperation.TRADING_CALENDAR)
            runtime._clock.current += timedelta(seconds=301)
            sdk_before = tuple(sdk.calls)

            candidate = next(
                item for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.TRADING_CALENDAR
            )
            assert candidate.anchor_date == sunday
            assert pipeline._calendar_permission_anchor() == sunday
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())
