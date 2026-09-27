"""Exact durable permission floors through sequential installed OS processes."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, timedelta
from multiprocessing import get_context
from pathlib import Path

import pytest
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _write_configuration_and_evidence,
)
from test_production_index_historical_permission_probe import _complete_index_day

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.health import RuntimeResourceStatus, RuntimeServiceStatus
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness, TradingCalendar
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository, RecoveryCheckpoint
from trade_plan_monitor.web.monitor_composition import _provider_recovery_identity

ANCHOR = date(2026, 9, 7)
SCOPE = TushareOperation.INDEX_HISTORICAL_MINUTES
IDENTITY = _provider_recovery_identity("https://example.test")
RAW_FLOOR = NOW + timedelta(seconds=300)
SHARED_FLOOR = NOW + timedelta(seconds=420)
EPSILON = timedelta(microseconds=1)


def _checkpoint_rows(database: Path):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        return tuple(connection.execute(
            "SELECT kind, scope_key, retry_at, failures, reason_code "
            "FROM provider_recovery_checkpoint WHERE provider_identity=? "
            "ORDER BY kind, scope_key", (IDENTITY,),
        ))


def _business_rows(database: Path):
    """Keep full rows, including timestamps; only owner/controller state may change."""
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        ).fetchall()
        return {
            name: tuple(sorted(connection.execute(f'SELECT * FROM "{name}"'), key=repr))
            for (name,) in tables
            if name not in {"alembic_version", "runtime_liveness", "provider_recovery_checkpoint"}
        }


def _run_process(root: str, phase: int, later_429: bool, outcomes) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    base = Path(root)
    database = base / "monitor.sqlite3"
    clock = ControlledClock(NOW if phase == 1 else RAW_FLOOR - EPSILON)

    class ProbeSDK(OfflineSDK):
        failures = {"idx_mins": TushareErrorCode.BLOCKED_PERMISSION} if phase == 1 else {}

        def _historical_index_minutes(self, _kwargs):
            return _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)

        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                frame = request(**kwargs)
                if name in self.failures:
                    raise TushareProviderError(self.failures[name], name)
                return frame

            return call

    sdk = ProbeSDK(clock, ())
    real_controller = monitor_composition.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monitor_composition.SystemClock = lambda: clock
    monitor_composition.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _config: sdk

    async def scenario():
        initial_checkpoints = _checkpoint_rows(database)
        initial_business = _business_rows(database)
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config/app.yaml", database_path=database,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime, runner = composition._runtime, composition._runner_task
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            control = runtime._request_controller
            generation = composition.health().runtime_generation
            assert pipeline is not None and pipeline._stock_semantics is None
            assert pipeline._index_semantics is not None and control.repository_bound
            # The real owner reaches its actual scheduler wait, but this test
            # releases zero automatic duties. R18 covers automatic eight-scope wakes.
            async with asyncio.timeout(3):
                while not clock.sleep_calls:
                    assert runner is not None and not runner.done()
                    await asyncio.sleep(0.005)
            assert clock.released_sleeps == 0
            assert sdk.calls == []
            assert _checkpoint_rows(database) == initial_checkpoints
            assert _business_rows(database) == initial_business
            before = initial_business
            reservations, units = [], []
            original_factory = pipeline._permission_probe_reservation_callback

            def observe_reservation(candidate):
                original_ack = original_factory(candidate)

                def on_reserved():
                    assert candidate.operation is SCOPE and candidate.anchor_date == ANCHOR
                    assert candidate.index_code is MarketIndexCode.SSE_COMPOSITE
                    expected = clock.now() + timedelta(seconds=300)
                    # A second read-only SQLite connection must see the real
                    # committed reservation BEFORE forwarding its original ack.
                    rows = _checkpoint_rows(database)
                    own = [row for row in rows if row[:2] == ("permission", SCOPE.value)]
                    assert own == [("permission", SCOPE.value, expected.isoformat(), 0,
                                    "BLOCKED_PERMISSION")]
                    assert control.raw_permission_retry_at(SCOPE) == expected
                    assert expected != (NOW - timedelta(seconds=1) if phase == 1 else RAW_FLOOR)
                    original_ack()
                    assert pipeline._permission_rotation_state.last_operation is SCOPE
                    reservations.append(expected.isoformat())

                return on_reserved

            pipeline._permission_probe_reservation_callback = observe_reservation

            def unchanged():
                assert composition._runtime is runtime and composition._runner_task is runner
                assert composition.health().runtime_generation == generation
                assert composition.health().status is RuntimeServiceStatus.RUNNING
                assert not composition._runner_failed and not composition._restart_pending
                assert not runtime.unexpected_run_exit and not runner.done()
                assert not runtime._work_tasks
                assert control.active_count == control.waiting_count == 0
                assert _business_rows(database) == before

            async def common(at, expected_result, expected_calls):
                assert at >= clock.now()
                clock.current = at
                prior_calls, prior_reservations = len(sdk.calls), len(reservations)
                assert await pipeline.run_permission_maintenance_unit() is expected_result
                sdk_delta = len(sdk.calls) - prior_calls
                ack_delta = len(reservations) - prior_reservations
                assert sdk_delta == ack_delta == expected_calls <= 1
                if expected_calls:
                    name, kwargs = sdk.calls[-1]
                    assert name == "idx_mins"
                    assert kwargs["ts_code"] == MarketIndexCode.SSE_COMPOSITE.value
                    assert str(kwargs["start_date"]).startswith("2026-09-07")
                    assert str(kwargs["end_date"]).startswith("2026-09-07")
                units.append((at.isoformat(), sdk_delta, ack_delta))
                unchanged()

            def original_floor():
                assert control.is_permission_blocked(SCOPE)
                assert control.raw_permission_retry_at(SCOPE) == RAW_FLOOR
                assert control.permission_retry_at(SCOPE) == (
                    SHARED_FLOOR if later_429 else RAW_FLOOR
                )
                own = [row for row in _checkpoint_rows(database) if row[0] == "permission"]
                assert own == [("permission", SCOPE.value, RAW_FLOOR.isoformat(), 0,
                                "BLOCKED_PERMISSION")]

            setup_calls = 0
            if phase == 1:
                assert control.raw_permission_retry_at(SCOPE) == NOW - timedelta(seconds=1)
                await common(NOW, PermissionMaintenanceResult.FAILED, 1)
                assert control.raw_permission_retry_at(SCOPE) == RAW_FLOOR
                if later_429:
                    # Separate setup work, never counted as a second common-unit call.
                    clock.current = NOW + timedelta(seconds=120)
                    sdk.failures["index_daily"] = TushareErrorCode.RATE_LIMITED
                    prior_calls = len(sdk.calls)
                    with pytest.raises(RequestControlError) as caught:
                        await control.execute(
                            TushareOperation.INDEX_DAILY,
                            lambda: sdk.index_daily(
                                ts_code=MarketIndexCode.SSE_COMPOSITE.value,
                                start_date=ANCHOR.isoformat(), end_date=ANCHOR.isoformat(),
                            ), work_key="r17:later-shared-429",
                        )
                    assert caught.value.code is RequestControlErrorCode.RATE_LIMITED
                    assert caught.value.attempts == 1
                    setup_calls = len(sdk.calls) - prior_calls
                    assert setup_calls == 1 and sdk.calls[-1][0] == "index_daily"
                    assert control.cooldown_until == SHARED_FLOOR
                    assert len(reservations) == 1
                    unchanged()
                original_floor()
            else:
                original_floor()
                assert control.cooldown_until == (SHARED_FLOOR if later_429 else None)
                await common(RAW_FLOOR - EPSILON, PermissionMaintenanceResult.SKIPPED, 0)
                assert _checkpoint_rows(database) == initial_checkpoints
                original_floor()
                if later_429:
                    await common(RAW_FLOOR, PermissionMaintenanceResult.SKIPPED, 0)
                    original_floor()
                    await common(SHARED_FLOOR - EPSILON, PermissionMaintenanceResult.SKIPPED, 0)
                    original_floor()
                    assert _checkpoint_rows(database) == initial_checkpoints
                await common(
                    SHARED_FLOOR if later_429 else RAW_FLOOR,
                    PermissionMaintenanceResult.PROBED, 1,
                )
                assert not control.is_permission_blocked(SCOPE)
                assert control.raw_permission_retry_at(SCOPE) is None
                assert not [row for row in _checkpoint_rows(database) if row[0] == "permission"]
            assert len(reservations) == 1
            final_checkpoints = _checkpoint_rows(database)
            result = {
                "phase": phase, "units": units, "reservations": reservations,
                "setup_calls": setup_calls, "calls": tuple(name for name, _ in sdk.calls),
                "generation": generation, "checkpoints": final_checkpoints,
            }
            await composition.stop()
            assert runner.done() and composition._runner_task is None
            assert composition._runtime is runtime and not runtime._work_tasks
            assert not composition._runner_failed and not composition._restart_pending
            assert not runtime.unexpected_run_exit and not runtime.cleanup_failed
            assert runtime.health().runtime_generation == generation
            assert runtime.health().status is RuntimeServiceStatus.STOPPED
            assert not runtime._database_opened
            assert state._database_status is RuntimeResourceStatus.STOPPED
            assert control._closed and control.active_count == control.waiting_count == 0
            assert _business_rows(database) == before
            assert _checkpoint_rows(database) == final_checkpoints
            assert tuple(name for name, _ in sdk.calls) == result["calls"]
            return result
        finally:
            await composition.stop()

    outcomes.put(asyncio.run(scenario()))


def _spawn(root: Path, phase: int, later_429: bool):
    context = get_context("spawn")
    outcomes = context.Queue()
    process = context.Process(target=_run_process, args=(str(root), phase, later_429, outcomes))
    process.start()
    process.join(timeout=45)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("offline permission process did not exit")
    assert process.exitcode == 0
    result = outcomes.get(timeout=5)
    outcomes.close()
    outcomes.join_thread()
    process.close()
    return result


@pytest.mark.parametrize("later_429", (False, True), ids=("raw-floor", "shared-429-new-token"))
def test_common_permission_reservation_survives_process_exit_until_exact_floor(tmp_path, later_429):
    database = tmp_path / "monitor.sqlite3"
    seed_clock = ControlledClock(NOW.replace(hour=9, minute=0))
    _activate_plans(database, seed_clock, ())
    engine = create_sqlite_engine(database)
    try:
        factory = create_session_factory(engine)
        with factory.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0,
                last_alive_at=seed_clock.now().isoformat(),
            ))
            session.add_all((
                TradingCalendar(exchange="SSE", cal_date=ANCHOR, is_open=True,
                                previous_trade_date=date(2026, 9, 4)),
                TradingCalendar(exchange="SSE", cal_date=NOW.date(), is_open=True,
                                previous_trade_date=ANCHOR),
            ))
        # A due latch is fixture input, not evidence of a real reservation.
        ProviderRecoveryRepository(factory, provider_identity=IDENTITY).save((
            RecoveryCheckpoint("permission", SCOPE.value, NOW - timedelta(seconds=1), 0),
        ))
    finally:
        engine.dispose()
    _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=True)
    (tmp_path / "data/live-certification/tushare-stock-live.json").unlink()
    before = _business_rows(database)
    first = _spawn(tmp_path, 1, later_429)
    assert first["phase"] == 1
    assert first["units"] == [(NOW.isoformat(), 1, 1)]
    assert first["reservations"] == [RAW_FLOOR.isoformat()]
    assert first["setup_calls"] == int(later_429)
    assert first["calls"] == (("idx_mins", "index_daily") if later_429 else ("idx_mins",))
    assert _checkpoint_rows(database) == first["checkpoints"]
    assert _business_rows(database) == before
    if later_429:
        # A manual credential change between fully stopped owners is not hot reload.
        config = tmp_path / "config/app.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace(
            "offline-test-token", "offline-new-token",
        ), encoding="utf-8")
    second = _spawn(tmp_path, 2, later_429)
    refused = [RAW_FLOOR - EPSILON]
    if later_429:
        refused.extend((RAW_FLOOR, SHARED_FLOOR - EPSILON))
    equality = SHARED_FLOOR if later_429 else RAW_FLOOR
    assert second["units"] == [
        *((at.isoformat(), 0, 0) for at in refused), (equality.isoformat(), 1, 1),
    ]
    assert second["reservations"] == [(equality + timedelta(seconds=300)).isoformat()]
    assert second["setup_calls"] == 0 and second["calls"] == ("idx_mins",)
    assert first["generation"] != second["generation"]
    assert _checkpoint_rows(database) == second["checkpoints"]
    assert _business_rows(database) == before
