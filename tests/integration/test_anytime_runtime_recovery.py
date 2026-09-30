"""Normal installed entry preserves source truth across isolated session restarts.

Crash/close delivery windows and long migrations remain covered by the existing
S3 process suites. This matrix exercises the default Web entry and its lifespan.
"""

import asyncio
import os
import sqlite3
import traceback
from contextlib import closing
from datetime import datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import test_explicit_runtime_production as explicit
from test_live_pipeline_acceptance import OfflineSDK, VirtualPace, _write_configuration_and_evidence

from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.runtime_liveness import RuntimeLivenessRepository

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE = datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
SYMBOL = "003043.SZ"
IDENTITY_TABLES = (
    "active_plan", "plan_activation_state", "plan_version", "alert_event",
    "explicit_evaluation_ledger", "explicit_rule_occurrence_state",
)


def _source_rows(database):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        return {
            table: tuple(sorted(connection.execute(f'SELECT * FROM "{table}"'), key=repr))
            for table in IDENTITY_TABLES
        }


def _seed_source(root, monkeypatch, *, missing_configuration=False):
    """Create the historical reminder through a real explicit business commit."""
    with monkeypatch.context() as patch:
        patch.setattr(explicit, "TARGET", SOURCE)
        patch.setattr(explicit, "TARGET_DATE", SOURCE.date())
        patch.setattr(explicit, "PREPARED_AT", SOURCE - timedelta(minutes=10))
        patch.setattr(explicit, "NOW", SOURCE + timedelta(seconds=2))
        payload = explicit._plan().model_dump(mode="python")
        payload["activation"] = {
            "mode": "DATE_RANGE", "start_date": SOURCE.date(),
            "end_date": SOURCE.date() + timedelta(days=14),
        }
        rule = payload["rules"][0]
        rule.update(
            condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            action={"type": "RISK_ALERT"},
        )
        plan = explicit.ExplicitTradePlan.model_validate(payload)
        database = root / "monitor.sqlite3"
        engine = create_sqlite_engine(database)
        upgrade_database(engine)
        try:
            liveness = RuntimeLivenessRepository(create_session_factory(engine))
            liveness.initialize_empty(SOURCE - timedelta(minutes=10))
            explicit._seed_active(engine, plan)
            explicit._seed_facts(engine, plan)
            outcome = ExplicitRuntimeEvaluationService(
                lambda: explicit._work(engine, now=SOURCE + timedelta(seconds=2)),
            ).run_intraday(
                plan=plan, target_bucket_end=SOURCE, evaluated_at=SOURCE + timedelta(seconds=2),
            )
            assert outcome.status is explicit.ExplicitRuntimeCycleStatus.COMMITTED
            assert len(outcome.committed_events) == 1
            liveness.touch(SOURCE + timedelta(seconds=2), expected_revision=0)
        finally:
            engine.dispose()
    config = _write_configuration_and_evidence(
        root, observed_at=SOURCE, include_index=False,
    )
    if missing_configuration:
        config.write_text("tushare: {}\n", encoding="utf-8")
    return _source_rows(database)


def _normal_entry_child(root, observed_at, connection):
    """A fresh OS process replaces only external I/O and the market clock."""
    import httpx
    import pandas as pd
    import requests
    from fastapi.testclient import TestClient

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as composition_module
    from trade_plan_monitor.web.app import create_production_app

    base = Path(root)
    # The normal entry also owns relative backtest stores. Keep every default
    # resource inside this child's isolated root, including its cursor key.
    os.chdir(base)
    external_calls = []

    def reject_network(*_args, **_kwargs):
        external_calls.append("network")
        raise AssertionError("normal-entry acceptance attempted external I/O")

    requests.Session.request = reject_network
    httpx.HTTPTransport.handle_request = reject_network
    httpx.AsyncHTTPTransport.handle_async_request = reject_network

    class ParkedClock:
        def __init__(self):
            self.current = observed_at
            self.sleep_calls = []

        def now(self):
            return self.current

        async def sleep_until(self, deadline):
            self.sleep_calls.append(deadline)
            await asyncio.Event().wait()

    clock = ParkedClock()

    class SessionSDK(OfflineSDK):
        def _stock_minutes(self, name, kwargs):
            cutoff = clock.now().replace(second=0, microsecond=0)
            ends = tuple(end for end in expected_minute_ends(
                cutoff.date(), is_open=cutoff.weekday() < 5,
            ) if end <= cutoff)
            if name == "rt_min":
                ends = ends[-1:]
            symbols = str(kwargs["ts_code"]).split(",")
            return pd.DataFrame([
                {
                    "ts_code": symbol, "freq": "1MIN",
                    "time": (end - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": "64.00", "high": "64.10", "low": "63.90", "close": "64.05",
                    "vol": "1000", "amount": "64000",
                }
                for symbol in symbols for end in ends
            ])

    sdk = SessionSDK(clock, (SYMBOL,))
    real_controller = composition_module.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    composition_module.SystemClock = lambda: clock
    composition_module.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _config: sdk
    try:
        # No opt-in version, injected read service, or custom runtime factory.
        with create_production_app(
            config_path=base / "config/app.yaml", database_path=base / "monitor.sqlite3",
        ) as app:
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                composition = app.state.runtime_lifecycle
                composition.websocket_service._heartbeat_interval_seconds = 0.01
                headers = {"X-Monitor-Contract-Version": "2"}
                responses = {
                    path: client.get(path, headers=headers)
                    for path in ("/api/v1/health", "/api/v1/dashboard",
                                 f"/api/v1/explicit-plan-runtime/{SYMBOL}")
                }
                for response in responses.values():
                    assert response.status_code == 200, response.text
                    assert response.headers["X-Monitor-Contract-Version"] == "2"
                    assert response.headers["Cache-Control"] == "no-store"
                health = responses["/api/v1/health"].json()
                dashboard = responses["/api/v1/dashboard"].json()
                detail = responses[f"/api/v1/explicit-plan-runtime/{SYMBOL}"].json()
                assert health["monitorContractVersion"] == dashboard["monitorContractVersion"] == 2
                generation = health["runtimeGeneration"]
                assert generation and generation == dashboard["runtimeGeneration"]
                assert health["runtimeStatus"]["lifecycle"] == "RUNNING"
                assert health["runtimeStatus"]["coordinator"]["state"] == "SCHEDULED"
                assert dashboard["symbols"][0]["availability"] == "CACHED"
                assert not dashboard["symbols"][0]["currentActionable"]
                assert detail["summary"]["planHash"] == dashboard["symbols"][0]["planHash"]
                eligibility = detail["summary"]["ruleEligibility"][0]
                assert not eligibility["currentActionable"]
                assert eligibility["sourceAlert"]["dataCutoff"] == SOURCE.isoformat(
                    timespec="microseconds",
                )
                with client.websocket_connect(
                    f"/ws/v1/monitor?after={dashboard['sequence']}&monitorContractVersion=2",
                    headers={"Origin": "http://127.0.0.1:8765"},
                ) as socket:
                    heartbeat = socket.receive_json()
                assert heartbeat["type"] == "heartbeat"
                assert heartbeat["monitorContractVersion"] == 2
                assert heartbeat["runtimeGeneration"] == generation
                first_status, streamed_status = health["runtimeStatus"], heartbeat["runtimeStatus"]
                for key in ("lifecycle", "mode", "reasonCode", "nextRetryAt",
                            "lastProgressAt", "scopes"):
                    assert streamed_status[key] == first_status[key]
                assert streamed_status["coordinator"]["state"] == "SCHEDULED"
                # Market observation is parked while real monotonic time passes.
                # The same owned deadline loses remaining time; a heartbeat must
                # never extend it or claim new progress merely by being received.
                for key, prior, later in (
                    ("wake", first_status["nextWakeAt"], streamed_status["nextWakeAt"]),
                    ("due", first_status["coordinator"]["progressDueAt"],
                     streamed_status["coordinator"]["progressDueAt"]),
                ):
                    assert observed_at < datetime.fromisoformat(later) <= datetime.fromisoformat(
                        prior,
                    ) <= observed_at + timedelta(seconds=30), key
                assert not external_calls
            assert composition.health().status.value == "STOPPED"
            assert composition._runner_task is None
            assert not hasattr(app.state, "runtime_lifecycle")
        connection.send({
            "pid": os.getpid(), "generation": generation,
            "mode": health["runtimeStatus"]["mode"],
            "reason": health["runtimeStatus"]["reasonCode"],
            "scope": dashboard["symbols"][0]["scope"],
            "calls": tuple(name for name, _ in sdk.calls),
            "sleeps": tuple(value.isoformat() for value in clock.sleep_calls),
            "stopped": True,
        })
    except BaseException:
        connection.send({"pid": os.getpid(), "error": traceback.format_exc()})
        raise
    finally:
        connection.close()


def _spawn_normal_entry(root, observed_at):
    context = get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    child = context.Process(target=_normal_entry_child, args=(str(root), observed_at, send))
    child.start()
    send.close()
    try:
        assert receive.poll(30), "normal production child did not report within its bound"
        result = receive.recv()
        assert "error" not in result, result.get("error")
        child.join(timeout=10)
        assert not child.is_alive() and child.exitcode == 0
        assert result["pid"] == child.pid and child.pid != os.getpid()
        return result
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        receive.close()


@pytest.mark.parametrize("observed_at", [
    datetime(2026, 9, 15, 9, 20, tzinfo=SHANGHAI),
    datetime(2026, 9, 15, 10, 0, tzinfo=SHANGHAI),
    datetime(2026, 9, 15, 12, 0, tzinfo=SHANGHAI),
    datetime(2026, 9, 15, 16, 0, tzinfo=SHANGHAI),
    datetime(2026, 9, 19, 10, 0, tzinfo=SHANGHAI),
], ids=["before-open", "open", "lunch", "after-close", "weekend"])
def test_normal_entry_process_restart_preserves_identity_and_reminder_source(
    tmp_path, monkeypatch, observed_at,
):
    before = _seed_source(tmp_path, monkeypatch)
    first = _spawn_normal_entry(tmp_path, observed_at)
    assert _source_rows(tmp_path / "monitor.sqlite3") == before
    second = _spawn_normal_entry(tmp_path, observed_at)
    assert _source_rows(tmp_path / "monitor.sqlite3") == before
    assert first["pid"] != second["pid"]
    assert first["generation"] != second["generation"]
    assert first["stopped"] and second["stopped"]
    for result in (first, second):
        assert result["reason"] != "LEGACY_PLANS_REQUIRE_REVIEW"
        assert "trade_cal" in result["calls"]
        assert result["scope"]["status"] != "READY"
        assert all(datetime.fromisoformat(due) > observed_at for due in result["sleeps"])
        if observed_at.weekday() >= 5:
            assert "rt_min_daily" not in result["calls"]


def test_normal_entry_missing_credentials_retains_honest_blocked_source(tmp_path, monkeypatch):
    before = _seed_source(tmp_path, monkeypatch, missing_configuration=True)
    result = _spawn_normal_entry(tmp_path, datetime(2026, 9, 15, 10, 0, tzinfo=SHANGHAI))
    assert result["reason"] == "CREDENTIAL_MISSING"
    assert result["mode"] == "BLOCKED"
    # No pipeline owns a current plan target when credentials are missing.
    # The aggregate exposes the blocker; its source-only plan remains waiting.
    assert result["scope"]["status"] == "WAITING"
    assert result["scope"]["reasonCode"] == "AWAITING_FIRST_EVALUATION"
    assert result["scope"]["readOnly"]
    assert result["calls"] == ()
    assert _source_rows(tmp_path / "monitor.sqlite3") == before
