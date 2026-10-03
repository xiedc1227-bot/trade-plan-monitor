"""Offline B2 cursor movement occurs only after a durable controller reservation."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from current_activation_fixture import current_mixed_plan
from sqlalchemy import delete
from test_live_pipeline_acceptance import NOW, ControlledClock, _activate_plans, _sample_plan
from test_permission_candidate_selection import (
    ANCHOR,
    EARLIER,
    _block,
    _seed_official_bar,
    _seed_open_day,
)
from test_production_certification_gate import _composition

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestNotStartedError,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import DailyBar as StoredDailyBar
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpointError,
)


def test_current_scope_tie_rotates_only_after_reservation_even_when_queue_aborts(
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
            sdk_before = tuple(sdk.calls)
            initial = pipeline.permission_probe_candidates()
            assert tuple(item.operation for item in initial) == scopes
            assert pipeline.permission_probe_candidates() == initial
            assert pipeline._permission_rotation_state.last_operation is None

            runtime._clock.current += timedelta(seconds=300)
            first = pipeline.select_due_permission_probe()
            assert first == initial[0]
            acknowledgements: list[str] = []
            advance = pipeline._permission_probe_reservation_callback(first)

            def on_reserved() -> None:
                acknowledgements.append("durable")
                advance()

            with pytest.raises(RequestNotStartedError):
                await control.recheck_permission(
                    first.operation,
                    lambda: pytest.fail("SDK must not start"),
                    work_key="rotation:queue-abort",
                    can_start=lambda: False,
                    on_reserved=on_reserved,
                )
            assert acknowledgements == ["durable"]
            assert pipeline._permission_rotation_state.last_operation is first.operation
            for operation in scopes[1:]:
                control.reset_permission_block(operation)
                await _block(control, operation)
            rotated = pipeline.permission_probe_candidates()
            assert rotated[0].operation is scopes[1]
            assert pipeline.permission_probe_candidates() == rotated
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_daily_bar_pools_alternate_and_follow_missing_pair_sort_key(
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
        database = tmp_path / "monitor.sqlite3"
        first_plan = _sample_plan()
        second_payload = first_plan.model_dump(mode="python")
        second_payload.update({"symbol": "003044.SZ", "plan_id": "second-legacy"})
        second_plan = TradePlan.model_validate(second_payload)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            _activate_plans(database, ControlledClock(NOW), (first_plan, second_plan))
            for day in (ANCHOR, EARLIER):
                _seed_open_day(database, day)
            _seed_official_bar(database, first_plan.symbol, ANCHOR, NOW)
            _seed_official_bar(database, second_plan.symbol, EARLIER, NOW)
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            assert pipeline is not None
            await _block(control, TushareOperation.DAILY_BARS)
            sdk_before = tuple(sdk.calls)

            def denied() -> None:
                raise TushareProviderError(
                    TushareErrorCode.BLOCKED_PERMISSION,
                    TushareOperation.DAILY_BARS.value,
                )

            expected = (
                ("O", first_plan.symbol, ANCHOR),
                ("F", second_plan.symbol, ANCHOR),
                ("O", second_plan.symbol, EARLIER),
                ("F", first_plan.symbol, EARLIER),
            )
            for pool, symbol, day in expected:
                candidate = next(
                    item
                    for item in pipeline.permission_probe_candidates()
                    if item.operation is TushareOperation.DAILY_BARS
                )
                assert (candidate.daily_bar_pool, candidate.symbol, candidate.anchor_date) == (
                    pool,
                    symbol,
                    day,
                )
                assert (
                    next(
                        item
                        for item in pipeline.permission_probe_candidates()
                        if item.operation is TushareOperation.DAILY_BARS
                    )
                    == candidate
                )
                runtime._clock.current += timedelta(seconds=300)
                with pytest.raises(RequestControlError):
                    await control.recheck_permission(
                        TushareOperation.DAILY_BARS,
                        denied,
                        work_key="rotation:daily-bars",
                        on_reserved=pipeline._permission_probe_reservation_callback(candidate),
                    )

            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    session.execute(
                        delete(StoredDailyBar).where(
                            StoredDailyBar.symbol == second_plan.symbol,
                            StoredDailyBar.trade_date == EARLIER,
                            StoredDailyBar.is_official.is_(True),
                        )
                    )
            finally:
                engine.dispose()
            _seed_official_bar(database, first_plan.symbol, EARLIER, NOW)
            candidate = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            assert (candidate.daily_bar_pool, candidate.symbol, candidate.anchor_date) == (
                "O",
                first_plan.symbol,
                ANCHOR,
            )
            runtime._clock.current += timedelta(seconds=300)
            with pytest.raises(RequestControlError):
                await control.recheck_permission(
                    TushareOperation.DAILY_BARS,
                    denied,
                    work_key="rotation:daily-bars",
                    on_reserved=pipeline._permission_probe_reservation_callback(candidate),
                )
            candidate = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            assert (candidate.daily_bar_pool, candidate.symbol, candidate.anchor_date) == (
                "F",
                second_plan.symbol,
                EARLIER,
            )
            runtime._clock.current += timedelta(seconds=300)
            with pytest.raises(RequestControlError):
                await control.recheck_permission(
                    TushareOperation.DAILY_BARS,
                    denied,
                    work_key="rotation:daily-bars",
                    on_reserved=pipeline._permission_probe_reservation_callback(candidate),
                )
            engine = create_sqlite_engine(database)
            try:
                with create_session_factory(engine).begin() as session:
                    session.execute(
                        delete(StoredDailyBar).where(
                            StoredDailyBar.is_official.is_(True),
                            StoredDailyBar.symbol.in_((first_plan.symbol, second_plan.symbol)),
                        )
                    )
            finally:
                engine.dispose()
            assert (
                next(
                    item
                    for item in pipeline.permission_probe_candidates()
                    if item.operation is TushareOperation.DAILY_BARS
                ).daily_bar_pool
                == "F"
            )
            candidate = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            runtime._clock.current += timedelta(seconds=300)
            with pytest.raises(RequestControlError):
                await control.recheck_permission(
                    TushareOperation.DAILY_BARS,
                    denied,
                    work_key="rotation:daily-bars",
                    on_reserved=pipeline._permission_probe_reservation_callback(candidate),
                )
            _seed_official_bar(database, first_plan.symbol, ANCHOR, NOW)
            _seed_official_bar(database, second_plan.symbol, EARLIER, NOW)
            restored = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            assert (restored.daily_bar_pool, restored.symbol, restored.anchor_date) == (
                "O",
                second_plan.symbol,
                EARLIER,
            )
            assert tuple(sdk.calls) == sdk_before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_missing_pair_uses_strict_successor_across_symbol_and_date() -> None:
    third_day = EARLIER - timedelta(days=3)
    pool = (
        ("003043.SZ", ANCHOR),
        ("003045.SZ", ANCHOR),
        ("003043.SZ", EARLIER),
        ("003044.SZ", EARLIER),
        ("003043.SZ", third_day),
    )
    next_pair = ProductionMonitorPipeline._next_daily_bar_pair
    assert next_pair(pool, ("003044.SZ", ANCHOR)) == ("003045.SZ", ANCHOR)
    assert next_pair(pool, ("003046.SZ", ANCHOR)) == ("003043.SZ", EARLIER)
    assert next_pair(pool, ("003043.SZ", EARLIER)) == ("003044.SZ", EARLIER)
    assert next_pair(pool, ("003044.SZ", EARLIER)) == ("003043.SZ", third_day)
    assert next_pair(pool, ("003044.SZ", third_day)) == pool[0]
    assert next_pair((), ("003043.SZ", ANCHOR)) is None
    assert next_pair(pool, None) == pool[0]
    same_symbol = (("003043.SZ", ANCHOR), ("003043.SZ", EARLIER))
    assert next_pair(same_symbol, same_symbol[0]) == same_symbol[1]


def test_failed_reservation_save_does_not_advance_pipeline_rotation(
    tmp_path,
    monkeypatch,
) -> None:
    class FailingRepository(ProviderRecoveryRepository):
        fail_save = False

        def save(self, rows):
            if self.fail_save:
                raise RecoveryCheckpointError("offline write failed")
            return super().save(rows)

    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            persisted_calendar=True,
            plan=current_mixed_plan(),
        )
        engine = create_sqlite_engine(tmp_path / "reservation-failure.db")
        upgrade_database(engine)
        repository = FailingRepository(
            create_session_factory(engine),
            provider_identity="b" * 64,
        )
        clock = ControlledClock(NOW)
        control = TushareRequestController(
            clock=clock,
            executor_workers=1,
            max_concurrency=1,
            min_interval=timedelta(0),
            jitter=timedelta(0),
            in_cycle_retries=0,
            recovery_repository=repository,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            pipeline = composition._runtime._probe_capabilities.__self__._pipeline
            assert pipeline is not None
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            await _block(
                composition._runtime._request_controller,
                TushareOperation.DAILY_BARS,
            )
            candidate = next(
                item
                for item in pipeline.permission_probe_candidates()
                if item.operation is TushareOperation.DAILY_BARS
            )
            before = pipeline._permission_rotation_state
            await _block(control, TushareOperation.DAILY_BARS)
            clock.current += timedelta(seconds=300)
            repository.fail_save = True
            sdk_before = tuple(sdk.calls)
            with pytest.raises(RecoveryCheckpointError):
                await control.recheck_permission(
                    TushareOperation.DAILY_BARS,
                    lambda: pytest.fail("SDK must not start"),
                    work_key="rotation:failed-save",
                    on_reserved=pipeline._permission_probe_reservation_callback(candidate),
                )
            assert pipeline._permission_rotation_state == before
            assert tuple(sdk.calls) == sdk_before
        finally:
            control.close()
            repository.release_owner(control)
            engine.dispose()
            await composition.stop()

    asyncio.run(scenario())
