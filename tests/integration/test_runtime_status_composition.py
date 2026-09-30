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
