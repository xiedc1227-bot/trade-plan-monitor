"""Opt-in composition keeps genuine ownership even without configured providers."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


@pytest.mark.parametrize(
    ("hour", "minute", "is_open", "expected"),
    [
        (9, 30, True, "BEFORE_FIRST_MINUTE"),
        (9, 31, True, "AWAITING_FIRST_EVALUATION"),
        (12, 0, True, "SESSION_BREAK"),
        (15, 0, True, "SESSION_CLOSED"),
        (10, 0, False, "SESSION_CLOSED"),
        (10, 0, None, "CALENDAR_UNKNOWN"),
    ],
)
def test_idle_reason_uses_installed_session_facts(hour, minute, is_open, expected):
    from trade_plan_monitor.web.monitor_composition import _runtime_standby_reason

    pipeline = SimpleNamespace(is_open_on=lambda _day: is_open)
    observed = datetime(2026, 9, 14, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert _runtime_standby_reason(
        plans=(object(),), pipeline=pipeline, observed_at=observed,
    ) == expected
    assert _runtime_standby_reason(
        plans=(), pipeline=None, observed_at=observed,
    ) == "NO_ACTIVE_PLANS"


def test_v2_composition_retains_generation_and_actual_stop_without_provider_calls(
    tmp_path, monkeypatch
):
    from tushare.pro.client import DataApi

    def reject(*args, **kwargs):
        raise AssertionError("offline composition attempted provider I/O")

    monkeypatch.setattr(DataApi, "query", reject)
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf-8")
    composition = create_monitor_composition(
        config_path=config,
        database_path=tmp_path / "monitor.sqlite3",
        monitor_contract_version=2,
    )
    assert composition.read_service.monitor_contract_version == 2
    assert composition.websocket_service.monitor_contract_version == 2

    async def scenario():
        with pytest.raises(ApiError):
            await composition.read_service.get_health()
        await composition.start()
        first = await composition.read_service.get_health()
        assert first.runtime_generation == composition._runtime.runtime_generation
        assert first.runtime_status.lifecycle == "RUNNING"
        assert first.runtime_status.last_progress_at is not None
        assert first.runtime_status.coordinator.state == "SCHEDULED"
        assert first.database.status == "READY"
        await composition.stop()
        stopped = await composition.read_service.get_health()
        assert stopped.runtime_generation == first.runtime_generation
        assert stopped.runtime_status.lifecycle == "STOPPED"
        assert stopped.stopped_at is not None

    asyncio.run(scenario())


def test_v2_health_retains_stop_timestamp_after_supervised_runner_failure(tmp_path, monkeypatch):
    from tushare.pro.client import DataApi

    def reject(*args, **kwargs):
        raise AssertionError("offline composition attempted provider I/O")

    monkeypatch.setattr(DataApi, "query", reject)
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf-8")
    composition = create_monitor_composition(
        config_path=config,
        database_path=tmp_path / "monitor.sqlite3",
        monitor_contract_version=2,
    )
    owner = composition._runtime

    async def fail_run():
        await owner.stop()
        owner._unexpected_run_exit = True
        raise ValueError("scheduled progress failed")

    monkeypatch.setattr(owner, "run", fail_run)
    monkeypatch.setattr(composition, "_runtime_factory", None)

    async def scenario():
        try:
            await composition.start()
            await composition._runner_task
            health = await composition.read_service.get_health()
            dashboard = await composition.read_service.get_dashboard()
            assert health.runtime_status.lifecycle == "STOPPED"
            assert health.runtime_status.reason_code == "RUNTIME_STOPPED"
            assert health.stopped_at == owner.health().stopped_at
            assert health.runtime_generation == owner.runtime_generation
            assert health.runtime_status == dashboard.runtime_status
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_normal_production_entry_defers_v2_owner_and_rejects_old_clients(tmp_path, monkeypatch):
    from importlib import resources

    from fastapi.testclient import TestClient
    from tushare.pro.client import DataApi

    from trade_plan_monitor.web.app import create_production_app

    def reject(*args, **kwargs):
        raise AssertionError("normal entry attempted provider I/O")

    monkeypatch.setattr(DataApi, "query", reject)
    distribution = tmp_path / "dist"
    (distribution / "assets").mkdir(parents=True)
    (distribution / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (distribution / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (distribution / "monitor-contract.json").write_text(
        '{"monitorContractVersion":2}', encoding="utf-8",
    )
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf-8")
    database = tmp_path / "state" / "monitor.sqlite3"

    class InertBacktest:
        read_service = object()
        operation_service = object()

        async def start(self):
            pass

        async def stop(self):
            pass

    with create_production_app(
        config_path=config, database_path=database, ai_service=object(),
        backtest_lifecycle_factory=InertBacktest,
    ) as app:
        assert not database.exists()
        assert app.state.monitor_contract_version == 2
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            assert client.get("/api/v1/health").status_code == 409
            response = client.get(
                "/api/v1/health", headers={"X-Monitor-Contract-Version": "2"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["monitorContractVersion"] == 2
            assert body["runtimeGeneration"] is not None
            assert body["runtimeStatus"]["lifecycle"] == "RUNNING"
            assert body["runtimeStatus"]["mode"] == "BLOCKED"
            assert database.exists()
        assert not hasattr(app.state, "monitor_read_service")


def test_declared_v2_factory_rejects_actual_old_reader_before_start():
    from fastapi.testclient import TestClient

    from trade_plan_monitor.web.app import create_app

    events = []

    class OldRuntime:
        read_service = object()

        async def start(self):
            events.append("start")

        async def stop(self):
            events.append("stop")

    def factory():
        return OldRuntime()

    factory.monitor_contract_version = 2
    app = create_app(runtime_factory=factory, monitor_contract_version=2)
    with pytest.raises(TypeError, match="authoritative v2"):
        with TestClient(app):
            pytest.fail("mismatched owner must not start")
    assert events == ["stop"]
    assert not hasattr(app.state, "runtime_lifecycle")


def test_unverified_lazy_factory_cannot_bypass_v2_authority_requirement():
    from trade_plan_monitor.web.app import create_app

    with pytest.raises(ValueError, match="authoritative v2"):
        create_app(runtime_factory=lambda: object(), monitor_contract_version=2)
