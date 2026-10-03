"""Offline B1 permission demand and anchor selection reads only persisted facts."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from current_activation_fixture import current_mixed_plan
from sqlalchemy import delete
from test_explicit_runtime_production import _plan as _explicit_plan
from test_explicit_runtime_production import _seed_active as _seed_explicit_active
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    _activate_plans,
    _sample_plan,
)
from test_production_certification_gate import _composition

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.models import DailyBar
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    TushareOperation,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.repositories import MarketHistoryRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

ANCHOR = date(2026, 9, 7)
EARLIER = ANCHOR - timedelta(days=3)


def _seed_open_day(database, day: date) -> None:
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            row = session.get(TradingCalendar, ("SSE", day))
            if row is None:
                session.add(
                    TradingCalendar(
                        exchange="SSE",
                        cal_date=day,
                        is_open=True,
                        previous_trade_date=day - timedelta(days=3),
                    )
                )
            else:
                row.is_open = True
    finally:
        engine.dispose()


def _seed_official_bar(
    database,
    symbol: str,
    day: date,
    received_at,
    *,
    official: bool = True,
) -> None:
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            MarketHistoryRepository(session).upsert_daily_bars(
                (
                    DailyBar(
                        symbol=symbol,
                        trade_date=day,
                        open_fen=6400,
                        high_fen=6900,
                        low_fen=6300,
                        close_fen=6600,
                        volume_shares=1000,
                        amount_yuan=Decimal("10000"),
                        is_official=official,
                        received_at=received_at,
                    ),
                )
            )
    finally:
        engine.dispose()


async def _block(control, operation: TushareOperation) -> None:
    def denied() -> None:
        raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, operation.value)

    with pytest.raises(RequestControlError):
        await control.execute(operation, denied, work_key=f"seed:{operation.value}")


def test_anchorless_scope_does_not_reserve_and_index_daily_has_no_stock_dependency(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            await _block(control, TushareOperation.DAILY_LIMITS)
            await _block(control, TushareOperation.INDEX_DAILY)
            raw_limits = control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS)
            raw_index = control.raw_permission_retry_at(TushareOperation.INDEX_DAILY)
            sdk_before = tuple(sdk.calls)

            assert pipeline.permission_probe_candidates() == ()
            with monkeypatch.context() as patch:
                patch.setattr(
                    pipeline,
                    "_read_permission_evidence",
                    lambda *_args, **_kwargs: pytest.fail("deadline read must not scan SQLite"),
                )
                assert pipeline.next_permission_probe_due_at() == min(raw_limits, raw_index)
                assert pipeline.next_permission_probe_due_at() == min(raw_limits, raw_index)
            assert control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS) == raw_limits
            assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) == raw_index
            assert tuple(sdk.calls) == sdk_before

            runtime._clock.current += timedelta(seconds=301)
            local_due = runtime._clock.now() + timedelta(seconds=30)
            pipeline._permission_probe_deferred_until[TushareOperation.DAILY_LIMITS] = local_due
            pipeline._permission_probe_deferred_until[TushareOperation.INDEX_DAILY] = local_due
            assert pipeline.next_permission_probe_due_at() == local_due
            assert pipeline.next_permission_probe_due_at() == local_due
            assert control.raw_permission_retry_at(TushareOperation.INDEX_DAILY) == raw_index
            assert tuple(sdk.calls) == sdk_before

            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            weekend = ANCHOR - timedelta(days=2)
            outside = ANCHOR - timedelta(days=371)
            _seed_open_day(tmp_path / "monitor.sqlite3", weekend)
            _seed_open_day(tmp_path / "monitor.sqlite3", outside)
            evidence = pipeline._read_permission_evidence(
                runtime._clock.now(),
                include_legacy=False,
                include_history=False,
            )
            assert weekend not in evidence.completed_open_days
            assert outside not in evidence.completed_open_days
            candidates = pipeline.permission_probe_candidates()
            assert [candidate.operation for candidate in candidates] == [
                TushareOperation.INDEX_DAILY,
            ]
            assert candidates[0].anchor_date == ANCHOR
            assert candidates[0].index_code is not None
            assert control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS) == raw_limits
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_daily_bar_pool_orders_official_then_bounded_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, _sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=False,
            persisted_calendar=True,
        )
        database = tmp_path / "monitor.sqlite3"
        first = _sample_plan()
        second_payload = _sample_plan().model_dump(mode="python")
        second_payload.update({"symbol": "003044.SZ", "plan_id": "second-legacy"})
        second = TradePlan.model_validate(second_payload)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            _activate_plans(database, ControlledClock(NOW), (first, second))
            _seed_open_day(database, ANCHOR)
            _seed_open_day(database, EARLIER)
            _seed_official_bar(database, "003043.SZ", ANCHOR, NOW)
            _seed_official_bar(database, "003044.SZ", EARLIER, NOW, official=False)
            _seed_official_bar(database, "003045.SZ", ANCHOR, NOW)
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            await _block(runtime._request_controller, TushareOperation.DAILY_BARS)
            evidence = pipeline._read_permission_evidence(
                NOW,
                include_legacy=True,
                include_history=True,
            )
            assert pipeline._daily_bar_permission_pools(
                ("003043.SZ", "003044.SZ"),
                (ANCHOR, EARLIER),
                evidence.official_pairs
                | frozenset(
                    {
                        ("003045.SZ", ANCHOR),
                        ("003043.SZ", ANCHOR - timedelta(days=367)),
                    }
                ),
            ) == (
                (("003043.SZ", ANCHOR),),
                (
                    ("003044.SZ", ANCHOR),
                    ("003043.SZ", EARLIER),
                    ("003044.SZ", EARLIER),
                ),
            )
            candidate = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            assert (candidate.symbol, candidate.anchor_date) == ("003043.SZ", ANCHOR)
            symbols = tuple(f"{index:06d}.SZ" for index in range(10))
            days = tuple(ANCHOR - timedelta(days=offset) for offset in range(366))
            preferred, fallback = pipeline._daily_bar_permission_pools(
                symbols,
                days,
                frozenset({(symbols[0], days[0])}),
            )
            assert len(preferred) + len(fallback) == 3660
            assert set(preferred).isdisjoint(fallback)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_current_scope_candidates_peek_without_reservation_or_sdk_call(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            include_index=True,
            persisted_calendar=True,
            plan=current_mixed_plan(),
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            scopes = (
                TushareOperation.TRADING_CALENDAR,
                TushareOperation.INDEX_HISTORICAL_MINUTES,
                TushareOperation.INDEX_REALTIME_MINUTES,
                TushareOperation.DAILY_BARS,
                TushareOperation.INDEX_DAILY,
            )
            for operation in scopes:
                await _block(control, operation)
            await _block(control, TushareOperation.DAILY_LIMITS)
            retired_due = control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS)
            sdk_before = tuple(sdk.calls)
            raw_before = tuple(control.raw_permission_retry_at(item) for item in scopes)

            first = pipeline.permission_probe_candidates()
            second = pipeline.permission_probe_candidates()
            assert first == second
            assert {item.operation for item in first} == set(scopes)
            assert TushareOperation.DAILY_LIMITS not in {item.operation for item in first}
            assert all(item.raw_due_at == item.next_due_at for item in first)
            assert pipeline.next_permission_probe_due_at() == min(raw_before)
            assert pipeline.select_due_permission_probe() is None
            runtime._clock.current += timedelta(seconds=301)
            assert pipeline.select_due_permission_probe() == first[0]
            assert pipeline.select_due_permission_probe() == first[0]
            pipeline._permission_probe_deferred_until[first[0].operation] = (
                runtime._clock.now() + timedelta(seconds=30)
            )
            assert pipeline.select_due_permission_probe() == first[1]
            pipeline._permission_probe_deferred_until.pop(first[0].operation)
            assert tuple(control.raw_permission_retry_at(item) for item in scopes) == raw_before
            assert control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS) == retired_due

            def limited() -> None:
                raise TushareProviderError(
                    TushareErrorCode.RATE_LIMITED,
                    "current_day_minutes",
                )

            with pytest.raises(RequestControlError):
                await control.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    limited,
                    work_key="seed:shared-cooldown",
                )
            cooldown = control.cooldown_until
            assert cooldown is not None
            delayed = pipeline.permission_probe_candidates()
            assert tuple(item.operation for item in delayed) == tuple(
                item.operation for item in first
            )
            assert all(item.next_due_at == cooldown for item in delayed)
            assert pipeline.next_permission_probe_due_at() == cooldown
            assert pipeline.select_due_permission_probe() is None
            local_defer = cooldown + timedelta(seconds=30)
            pipeline._permission_probe_deferred_until[TushareOperation.INDEX_DAILY] = local_defer
            deferred = pipeline.permission_probe_candidates()
            assert (
                next(
                    item.next_due_at
                    for item in deferred
                    if item.operation is TushareOperation.INDEX_DAILY
                )
                == local_defer
            )
            assert pipeline.next_permission_probe_due_at() == cooldown
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_calendar_seven_day_and_daily_366_day_boundaries(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            control = runtime._request_controller
            await _block(control, TushareOperation.TRADING_CALENDAR)
            await _block(control, TushareOperation.INDEX_DAILY)
            yesterday = NOW.date() - timedelta(days=1)
            seventh = yesterday - timedelta(days=6)
            eighth = seventh - timedelta(days=1)
            day_365 = yesterday - timedelta(days=364)
            day_366 = yesterday - timedelta(days=365)
            day_367 = day_366 - timedelta(days=1)
            database = tmp_path / "monitor.sqlite3"
            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    session.execute(
                        delete(TradingCalendar).where(
                            TradingCalendar.exchange == "SSE",
                            TradingCalendar.cal_date >= day_367,
                            TradingCalendar.cal_date <= yesterday,
                        )
                    )
            finally:
                engine.dispose()
            for day in (day_366, day_367):
                _seed_open_day(database, day)
            sdk_before = tuple(sdk.calls)

            candidates = pipeline.permission_probe_candidates()
            assert TushareOperation.TRADING_CALENDAR not in {item.operation for item in candidates}
            assert TushareOperation.INDEX_DAILY not in {item.operation for item in candidates}
            _seed_open_day(database, day_365)
            candidates = pipeline.permission_probe_candidates()
            daily = next(
                item for item in candidates if item.operation is TushareOperation.INDEX_DAILY
            )
            assert daily.anchor_date == day_365
            assert (
                day_365
                in pipeline._read_permission_evidence(
                    NOW,
                    include_legacy=False,
                    include_history=False,
                ).completed_open_days
            )
            assert (
                day_366
                not in pipeline._read_permission_evidence(
                    NOW,
                    include_legacy=False,
                    include_history=False,
                ).completed_open_days
            )
            assert (
                day_367
                not in pipeline._read_permission_evidence(
                    NOW,
                    include_legacy=False,
                    include_history=False,
                ).completed_open_days
            )

            _seed_open_day(database, eighth)
            candidates = pipeline.permission_probe_candidates()
            assert TushareOperation.TRADING_CALENDAR not in {item.operation for item in candidates}
            assert (
                next(
                    item.anchor_date
                    for item in candidates
                    if item.operation is TushareOperation.INDEX_DAILY
                )
                == eighth
            )

            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    session.add(
                        TradingCalendar(
                            exchange="SSE",
                            cal_date=seventh,
                            is_open=False,
                            previous_trade_date=eighth,
                        )
                    )
            finally:
                engine.dispose()
            calendar = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.TRADING_CALENDAR
            )
            assert calendar.anchor_date == seventh
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_explicit_only_plan_does_not_demand_legacy_reference_probes(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            database = tmp_path / "monitor.sqlite3"
            engine = create_sqlite_engine(database)
            try:
                _seed_explicit_active(engine, _explicit_plan(active_date=NOW.date()))
            finally:
                engine.dispose()
            _seed_open_day(database, ANCHOR)
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            control = runtime._request_controller
            await _block(control, TushareOperation.DAILY_LIMITS)
            await _block(control, TushareOperation.DAILY_BARS)
            sdk_before = tuple(sdk.calls)
            assert pipeline.permission_probe_candidates() == ()
            assert pipeline.next_permission_probe_due_at() == min(
                control.raw_permission_retry_at(TushareOperation.DAILY_LIMITS),
                control.raw_permission_retry_at(TushareOperation.DAILY_BARS),
            )
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("obligation", ("pending", "historical"))
def test_expired_legacy_close_obligation_demands_daily_bars(
    tmp_path,
    monkeypatch,
    obligation,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            persisted_calendar=True,
        )
        database = tmp_path / "monitor.sqlite3"
        payload = _sample_plan().model_dump(mode="python")
        payload["activation"] = {
            "mode": "TRADING_DAY",
            "trading_day": ANCHOR.isoformat(),
        }
        plan = TradePlan.model_validate(payload)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            _activate_plans(
                database,
                ControlledClock(datetime.combine(ANCHOR, time(9), NOW.tzinfo)),
                (plan,),
            )
            _seed_open_day(database, ANCHOR)
            if obligation == "pending":
                engine = create_sqlite_engine(database)
                try:
                    with SqlAlchemyUnitOfWork(
                        create_session_factory(engine),
                        clock=lambda: NOW,
                    ) as work:
                        work.projections.put_pending_official_close(
                            plan_hash=plan_sha256(plan),
                            symbol=plan.symbol,
                            trade_date=ANCHOR,
                            formula_version=plan.monitoring.indicator_formula_version,
                            pending={"resume": {}},
                            observed_at=NOW,
                        )
                        work.commit()
                finally:
                    engine.dispose()
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            if obligation == "historical":
                assert pipeline._historical_reader is not None
                assert pipeline._historical_reader.missing_targets(
                    plan.symbol,
                    NOW,
                ) == (ANCHOR,)
            control = runtime._request_controller
            await _block(control, TushareOperation.DAILY_LIMITS)
            await _block(control, TushareOperation.DAILY_BARS)
            sdk_before = tuple(sdk.calls)
            evidence = pipeline._read_permission_evidence(
                NOW,
                include_legacy=True,
                include_history=True,
            )
            assert evidence.legacy_symbols == ()
            assert evidence.legacy_bar_symbols == (plan.symbol,)
            candidates = pipeline.permission_probe_candidates()
            assert TushareOperation.DAILY_LIMITS not in {item.operation for item in candidates}
            daily_bar = next(
                item for item in candidates if item.operation is TushareOperation.DAILY_BARS
            )
            assert (daily_bar.symbol, daily_bar.anchor_date) == (plan.symbol, ANCHOR)
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_candidate_read_uses_one_snapshot_and_propagates_read_fault(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            include_index=True,
            persisted_calendar=True,
            plan=current_mixed_plan(),
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(runtime._request_controller, TushareOperation.DAILY_BARS)
            await _block(runtime._request_controller, TushareOperation.INDEX_DAILY)
            sdk_before = tuple(sdk.calls)
            original_work = pipeline._work
            reads = 0

            def counted_work():
                nonlocal reads
                reads += 1
                return original_work()

            with monkeypatch.context() as patch:
                patch.setattr(pipeline, "_work", counted_work)
                assert len(pipeline.permission_probe_candidates()) == 2
                assert reads == 1

            with original_work() as work:
                references_type = type(work.references)

            def fail_read(*_args, **_kwargs):
                raise RuntimeError("offline SQLite read failed")

            with monkeypatch.context() as patch:
                patch.setattr(references_type, "list_trading_days", fail_read)
                with pytest.raises(RuntimeError, match="offline SQLite read failed"):
                    pipeline.permission_probe_candidates()
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())
