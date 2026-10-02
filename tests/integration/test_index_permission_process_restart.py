"""Migrated index permission reservations survive installed process restarts."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from multiprocessing import get_context
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from test_index_permission_scope_migration import _migrate
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
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import TushareOperation
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertEvent,
    EvaluationResult,
    MarketIndexSnapshot,
    RuntimeLiveness,
    TradingCalendar,
)
from trade_plan_monitor.web.monitor_composition import _provider_recovery_identity

ANCHOR = date(2026, 9, 7)
HISTORICAL = TushareOperation.INDEX_HISTORICAL_MINUTES
REALTIME = TushareOperation.INDEX_REALTIME_MINUTES
ENDPOINTS = {HISTORICAL: "idx_mins", REALTIME: "rt_idx_min_daily"}


def _run_installed_process(
    root: str, observed_at, first_scope: str, phase: int, outcomes,
) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    clock = ControlledClock(observed_at)

    class ProbeSDK(OfflineSDK):
        fail_endpoint: str | None = None

        def _historical_index_minutes(self, _kwargs):
            return _complete_index_day(MarketIndexCode.SSE_COMPOSITE, ANCHOR)

        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                result = request(**kwargs)
                if name == self.fail_endpoint:
                    raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, name)
                return result

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
        base = Path(root)
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config/app.yaml",
            database_path=base / "monitor.sqlite3",
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            state = runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            control = runtime._request_controller
            assert control.repository_bound
            assert state._liveness_revision is not None
            first = TushareOperation(first_scope)
            second = REALTIME if first is HISTORICAL else HISTORICAL

            async def probe(scope):
                if scope is HISTORICAL:
                    return await pipeline._maybe_recheck_historical_index_permission()
                return await pipeline._maybe_recheck_realtime_index_permission()

            if phase == 1:
                assert control.is_permission_blocked(HISTORICAL)
                assert control.is_permission_blocked(REALTIME)
                assert control.permission_retry_at(HISTORICAL) == NOW - timedelta(seconds=1)
                assert control.permission_retry_at(REALTIME) == NOW - timedelta(seconds=1)
                assert [name for name, _ in sdk.calls if name in ENDPOINTS.values()] == []
                sdk.fail_endpoint = ENDPOINTS[second]
                if first is REALTIME:
                    rotation = pipeline._permission_rotation_state
                    assert await probe(first) is PermissionMaintenanceResult.SKIPPED
                    assert pipeline._permission_rotation_state == rotation
                    assert all(control.is_permission_blocked(op) for op in (HISTORICAL, REALTIME))
                    assert all(control.raw_permission_retry_at(op) == NOW - timedelta(seconds=1)
                               for op in (HISTORICAL, REALTIME))
                    assert not [name for name, _ in sdk.calls if name in ENDPOINTS.values()]
                for operation in (HISTORICAL, REALTIME):
                    before = len(sdk.calls)
                    sibling = REALTIME if operation is HISTORICAL else HISTORICAL
                    sibling_state = (
                        control.is_permission_blocked(sibling),
                        control.raw_permission_retry_at(sibling),
                    )
                    expected = (PermissionMaintenanceResult.PROBED if operation is first
                                else PermissionMaintenanceResult.FAILED)
                    assert await pipeline.run_permission_maintenance_unit() is expected
                    assert [name for name, _ in sdk.calls[before:]] == [ENDPOINTS[operation]]
                    assert control.is_permission_blocked(operation) is (operation is second)
                    assert (
                        control.is_permission_blocked(sibling),
                        control.raw_permission_retry_at(sibling),
                    ) == sibling_state
                    if operation is second:
                        assert control.raw_permission_retry_at(operation) == (
                            NOW + timedelta(seconds=300)
                        )
                assert not control.is_permission_blocked(first)
                assert control.is_permission_blocked(second)
                assert control.permission_retry_at(second) == NOW + timedelta(seconds=300)
                assert [name for name, _ in sdk.calls if name in ENDPOINTS.values()] == [
                    ENDPOINTS[HISTORICAL], ENDPOINTS[REALTIME],
                ]
            else:
                assert not control.is_permission_blocked(first)
                assert control.is_permission_blocked(second)
                assert control.permission_retry_at(second) == NOW + timedelta(seconds=300)
                assert await probe(second) is PermissionMaintenanceResult.SKIPPED
                assert [name for name, _ in sdk.calls if name in ENDPOINTS.values()] == []
                clock.current = NOW + timedelta(minutes=10)
                assert await probe(second) is PermissionMaintenanceResult.PROBED
                assert not control.is_permission_blocked(first)
                assert not control.is_permission_blocked(second)
                assert [name for name, _ in sdk.calls if name in ENDPOINTS.values()] == [
                    ENDPOINTS[second],
                ]

            with state._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(MarketIndexSnapshot)) == 0
                assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            return (
                phase,
                control.permission_retry_at(second).isoformat()
                if control.permission_retry_at(second) is not None else None,
                tuple(name for name, _ in sdk.calls if name in ENDPOINTS.values()),
            )
        finally:
            await composition.stop()

    outcomes.put(asyncio.run(scenario()))


def _spawn(root: Path, observed_at, first_scope: TushareOperation, phase: int):
    context = get_context("spawn")
    outcomes = context.Queue()
    process = context.Process(
        target=_run_installed_process,
        args=(str(root), observed_at, first_scope.value, phase, outcomes),
    )
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("offline index permission child did not stop")
    assert process.exitcode == 0
    return outcomes.get(timeout=5)


@pytest.mark.parametrize("first_scope", (HISTORICAL, REALTIME))
def test_migrated_index_permissions_recheck_independently_across_processes(
    tmp_path, first_scope,
):
    database = tmp_path / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0))
    _activate_plans(database, clock, ())
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0,
                last_alive_at=clock.now().isoformat(),
            ))
            session.add_all((
                TradingCalendar(
                    exchange="SSE", cal_date=ANCHOR, is_open=True,
                    previous_trade_date=date(2026, 9, 4),
                ),
                TradingCalendar(
                    exchange="SSE", cal_date=NOW.date(), is_open=True,
                    previous_trade_date=ANCHOR,
                ),
            ))
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
                "retry": (NOW - timedelta(seconds=1)).isoformat(),
            })
    finally:
        engine.dispose()
    _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=True)
    (tmp_path / "data/live-certification/tushare-stock-live.json").unlink()

    first = _spawn(tmp_path, NOW, first_scope, 1)
    assert first == (
        1, (NOW + timedelta(seconds=300)).isoformat(),
        (ENDPOINTS[HISTORICAL], ENDPOINTS[REALTIME]),
    )
    engine = create_sqlite_engine(database)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version"))
            assert version.scalar_one() == "0024_daily_plan"
            assert connection.execute(text(
                "SELECT scope_key, retry_at FROM provider_recovery_checkpoint "
                "WHERE kind='permission'"
            )).all() == [(
                ENDPOINTS[REALTIME if first_scope is HISTORICAL else HISTORICAL],
                (NOW + timedelta(seconds=300)).isoformat(),
            )]
    finally:
        engine.dispose()
    second = _spawn(tmp_path, NOW + timedelta(seconds=100), first_scope, 2)
    assert second == (
        2, None,
        (ENDPOINTS[REALTIME if first_scope is HISTORICAL else HISTORICAL],),
    )
