"""Actual installed reads distinguish lunch standby from an overdue scheduler."""

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
import requests
from sqlalchemy import text
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)
from test_s3_startup_outcome_association import _DeadlineClock

from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness


def test_installed_lunch_standby_and_heartbeat_cannot_hide_overdue_progress(tmp_path, monkeypatch):
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as composition_module

    async def scenario():
        initial = NOW.replace(hour=11, minute=29)
        clock = _DeadlineClock(initial)
        database = tmp_path / "monitor.sqlite3"
        plan = _sample_plan()
        seed_clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0))
        _activate_plans(database, seed_clock, (plan,))
        engine = create_sqlite_engine(database)
        sessions = create_session_factory(engine)
        with sessions.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0, last_alive_at=seed_clock.now().isoformat(),
            ))
        config = _write_configuration_and_evidence(
            tmp_path, observed_at=initial, include_index=False,
        )
        sdk = OfflineSDK(clock, (plan.symbol,))
        make_controller = composition_module.create_live_tushare_request_controller

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return make_controller(
                clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        def forbid_network(*_args, **_kwargs):
            pytest.fail("S3 read-liveness evidence must stay offline")

        monkeypatch.setattr(requests.Session, "request", forbid_network)
        monkeypatch.setattr(httpx.Client, "send", forbid_network)
        monkeypatch.setattr(httpx.AsyncClient, "send", forbid_network)
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        monkeypatch.setattr(composition_module, "SystemClock", lambda: clock)
        monkeypatch.setattr(
            composition_module, "create_live_tushare_request_controller", controller_factory,
        )
        composition = composition_module.create_monitor_composition(
            config_path=config, database_path=database,
        )

        def business_rows():
            with engine.connect() as connection:
                return {
                    table: tuple(tuple(row) for row in connection.execute(text(
                        f"SELECT * FROM {table} ORDER BY rowid"
                    )))
                    for table in (
                        "evaluation_ledger", "evaluation_result", "symbol_decision_head",
                        "alert_event", "delivery_attempt", "pending_official_close",
                    )
                }

        def runner_failed():
            return composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED"

        try:
            async with asyncio.timeout(30):
                started = await composition.start()
                assert started.status.value == "RUNNING"
                generation = started.runtime_generation
                await clock.park(failed=runner_failed)
                market_due = initial.replace(minute=30, second=12)
                await clock.drive(market_due, failed=runner_failed)
                assert not runner_failed()
                assert any(name == "rt_min" for name, _ in sdk.calls)
                baseline = business_rows()
                assert len(baseline["evaluation_result"]) == 1
                assert len(baseline["evaluation_ledger"]) == 1
                assert baseline["pending_official_close"] == ()
                fresh = await composition.read_service.get_dashboard()
                assert fresh.connection_status.value == "CONNECTED"
                assert fresh.runtime_generation == generation
                summary, = fresh.symbols
                assert summary.connected and summary.decision.data_health.status.value == "LIVE"
                original_decision = summary.decision
                assert original_decision.evaluated_at == market_due
                assert original_decision.market_data_at == market_due.replace(second=0)

                # Release only genuine scheduler sleeps through lunch, including any
                # bounded maintenance polls added by later approved owner wiring.
                lunch = initial.replace(hour=12, minute=0, second=0)
                await clock.drive(lunch, failed=runner_failed)
                clock.current = lunch
                health = await composition.read_service.get_health()
                assert composition.health().runtime_generation == generation and not runner_failed()
                assert health.status.value == "RUNNING" and not health.read_only
                assert health.next_poll_at == clock.parked[0] and health.next_poll_at > lunch
                assert business_rows() == baseline
                waiting = await composition.read_service.get_dashboard()
                assert waiting.connection_status.value == "CONNECTED"
                assert waiting.runtime_generation == generation
                assert waiting.symbols[0].connected
                assert waiting.symbols[0].decision == original_decision
                current_health = await composition.read_service.get_symbol_health(
                    symbol=plan.symbol,
                )
                assert current_health is not None and current_health.actionable
                frame = composition.websocket_service._heartbeat_frame(waiting.sequence)
                assert frame["runtimeLive"] is True
                assert frame["runtimeGeneration"] == str(generation)
                assert frame["runtimeStartedAt"] == started.started_at.isoformat()
                assert frame["sequence"] == waiting.sequence

                # Keep the actual scheduler's permit blocked. Advance only observation
                # time past its real promised deadline; do not forge runtime health.
                due = health.next_poll_at
                calls_before = tuple(sdk.calls)
                clock.current = due + timedelta(microseconds=1)
                await composition._runtime._liveness_owner.heartbeat()
                with sessions() as session:
                    heartbeat = session.get(RuntimeLiveness, 1)
                    assert datetime.fromisoformat(heartbeat.last_alive_at) == clock.now()
                assert composition.health().runtime_generation == generation
                assert composition.health().status.value == "RUNNING"
                assert composition.health().next_poll_at == due
                assert not clock.parked[1].done()
                stale = await composition.read_service.get_dashboard()
                assert stale.connection_status.value == "DISCONNECTED"
                assert stale.runtime_generation is None
                assert not stale.symbols[0].connected
                assert await composition.read_service.get_symbol_health(symbol=plan.symbol) is None
                frame = composition.websocket_service._heartbeat_frame(waiting.sequence)
                assert frame["sequence"] == waiting.sequence
                assert frame["runtimeLive"] is False and frame["runtimeGeneration"] is None
                assert frame["runtimeStartedAt"] is None
                # Stored history stays historical LIVE; only current admission closes.
                assert stale.symbols[0].decision == original_decision
                assert business_rows() == baseline and tuple(sdk.calls) == calls_before
        finally:
            await asyncio.wait_for(composition.stop(), timeout=10)
            engine.dispose()

    asyncio.run(scenario())
