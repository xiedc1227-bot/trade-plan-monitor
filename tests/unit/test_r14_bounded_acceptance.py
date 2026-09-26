"""Offline guard tests for the optional R14 real-interface harness."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from scripts.r14_bounded_acceptance import (
    APPROVED_MODEL,
    AIBudgetTransport,
    Budget,
    BudgetDenied,
    MarketBudget,
    _bounded_ai_factory,
    _claim_session,
    _deactivate_isolated_plan,
    _recover_activated_symbol,
    _session_budgets,
    _start_window_eligible,
    _valid_run_id,
    approved_sources,
)


def test_market_guard_counts_attempts_and_rejects_other_symbols() -> None:
    budget = Budget(total=2, per_key={"rt_min": 1, "trade_cal": 1}, seconds=60)
    guard = MarketBudget(budget)
    calls: list[str] = []

    def query(name: str, fields: str = "", **kwargs: object) -> str:
        calls.append(name)
        return "ok"

    assert guard.call(query, "rt_min", ts_code="003043.SZ") == "ok"
    with pytest.raises(BudgetDenied):
        guard.call(query, "rt_min", ts_code="003043.SZ")
    with pytest.raises(BudgetDenied):
        guard.call(query, "rt_min_daily", ts_code="600000.SH")
    with pytest.raises(BudgetDenied):
        guard.call(query, "trade_cal", exchange="NYSE")
    assert budget.snapshot()["attempts"] == {"rt_min": 1}
    assert calls == ["rt_min"]


def test_deadline_refusal_stops_before_sdk_and_counts_denial(monkeypatch) -> None:
    import scripts.r14_bounded_acceptance as launcher

    ticks = [100.0]
    stopped: list[bool] = []
    monkeypatch.setattr(launcher, "monotonic", lambda: ticks[0])
    budget = Budget(
        total=60,
        per_key={"rt_min": 15},
        seconds=1,
        on_denied=lambda: stopped.append(True),
    )
    ticks[0] = 101.0
    calls: list[str] = []
    with pytest.raises(BudgetDenied):
        MarketBudget(budget).call(
            lambda name, **kwargs: calls.append(name), "rt_min", ts_code="003043.SZ"
        )
    assert calls == []
    assert stopped == [True]
    assert budget.snapshot()["totalAttempts"] == 0
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def test_launcher_budgets_signal_server_stop_on_overuse() -> None:
    stopped: list[str] = []
    ai, market = _session_budgets(lambda: stopped.append("stop"))
    assert ai.snapshot()["totalCap"] == 3
    assert market.snapshot()["totalCap"] == 60
    market.admit("rt_min")
    for _ in range(14):
        market.admit("rt_min")
    with pytest.raises(BudgetDenied):
        market.admit("rt_min")
    with pytest.raises(BudgetDenied):
        ai.admit("LITERAL")
    assert stopped == ["stop", "stop"]
    assert market.snapshot()["attempts"]["rt_min"] == 15
    assert market.snapshot()["deniedBeforeNetwork"] == 1
    assert ai.snapshot()["totalAttempts"] == 0
    assert ai.snapshot()["stopped"] is True


def test_proposed_dates_and_one_local_session_slot(tmp_path: Path) -> None:
    from trade_plan_monitor.runtime.clock import SHANGHAI

    for day in (14, 15, 16):
        now = datetime(2026, 9, day, 10, 12, tzinfo=SHANGHAI)
        assert _valid_run_id(f"r14-202609{day}-a", now)
        assert not _valid_run_id(f"r14-202609{day}-b", now)
    assert not _valid_run_id("r14-20260917-a", datetime(2026, 9, 17, 10, 12, tzinfo=SHANGHAI))
    root = tmp_path / "r14"
    assert _claim_session(root, "r14-20260914-a").is_dir()
    with pytest.raises(FileExistsError):
        _claim_session(root, "r14-20260915-a")
    assert not (root / "r14-20260915-a").exists()


def test_morning_start_window_boundaries() -> None:
    from trade_plan_monitor.runtime.clock import SHANGHAI

    def at(day: int, hour: int, minute: int, second: int) -> datetime:
        return datetime(2026, 9, day, hour, minute, second, tzinfo=SHANGHAI)

    assert not _start_window_eligible(at(14, 10, 9, 59))
    assert _start_window_eligible(at(14, 10, 10, 0))
    assert _start_window_eligible(at(14, 11, 0, 0))
    assert not _start_window_eligible(at(14, 11, 0, 1))
    assert not _start_window_eligible(at(14, 13, 10, 0))
    assert not _start_window_eligible(at(17, 10, 12, 0))


def test_direct_market_sdk_enforces_15_seconds_and_no_transport_retry(monkeypatch) -> None:
    import pandas as pd
    import urllib3

    from trade_plan_monitor.config import TushareConfiguration
    from trade_plan_monitor.market_data.tushare_client import create_tushare_client

    observed: dict[str, object] = {}

    class Pool:
        def __init__(self, **kwargs: object) -> None:
            observed.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def request(self, method: str, path: str, **kwargs: object):
            observed["method"] = method
            observed["path"] = path
            observed["requestRetries"] = kwargs["retries"]
            return SimpleNamespace(
                status=200,
                data=b'{"code":0,"data":{"fields":["ts_code"],"items":[["003043.SZ"]]}}',
            )

    class DataApi:
        _DataApi__http_url = ""
        query = None

        def __init__(self, _token: str, _timeout: int) -> None:
            pass

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    settings = TushareConfiguration(
        api_url="https://api.quicksync.cn",
        connect_ip="127.0.0.1",
        timeout_seconds=15,
        token="offline-test-token",
    )
    client = create_tushare_client(settings, data_api_factory=DataApi)
    frame = client.query("rt_min", ts_code="003043.SZ")
    assert isinstance(frame, pd.DataFrame)
    assert frame.iloc[0]["ts_code"] == "003043.SZ"
    assert observed["timeout"].total == 15
    assert observed["retries"] is False
    assert observed["requestRetries"] is False
    assert observed["server_hostname"] == "api.quicksync.cn"
    assert observed["assert_hostname"] == "api.quicksync.cn"


def test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt() -> None:
    source, prompt = next(iter(approved_sources().values()))
    del source
    budget = Budget(total=1, per_key={key: 1 for key in approved_sources()}, seconds=60)
    sent: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503)

    transport = AIBudgetTransport(budget, inner=httpx.MockTransport(handler))
    payload = {
        "model": APPROVED_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post("https://api.deepseek.com/chat/completions", json=payload)
            assert response.status_code == 503
            with pytest.raises(BudgetDenied):
                await client.post("https://api.deepseek.com/chat/completions", json=payload)
            payload["model"] = "deepseek-flash"
            with pytest.raises(BudgetDenied):
                await client.post("https://api.deepseek.com/chat/completions", json=payload)

    asyncio.run(exercise())
    assert len(sent) == 1
    assert budget.snapshot()["totalAttempts"] == 1


@pytest.mark.parametrize("temperature", [None, 0.1], ids=["missing", "nonzero"])
def test_ai_guard_rejects_unapproved_temperature_before_transport(temperature) -> None:
    _, prompt = next(iter(approved_sources().values()))
    budget = Budget(total=1, per_key={key: 1 for key in approved_sources()}, seconds=60)
    sent: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503)

    payload = {
        "model": APPROVED_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature

    async def exercise() -> None:
        transport = AIBudgetTransport(budget, inner=httpx.MockTransport(handler))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(BudgetDenied):
                await client.post("https://api.deepseek.com/chat/completions", json=payload)

    asyncio.run(exercise())
    assert sent == []
    assert budget.snapshot()["totalAttempts"] == 0


def test_approved_sources_are_the_three_fixed_repository_inputs() -> None:
    sources = approved_sources()
    assert set(sources) == {"LITERAL", "SEM-AMB-01", "SEM-UNS-01"}
    assert all(len(prompt.encode("utf-8")) <= 19_000 for _, prompt in sources.values())
    fixture = json.loads(
        Path("tests/fixtures/ai/explicit-plan-literal-source-v3.json").read_text("utf-8")
    )
    assert sources["LITERAL"][0] == fixture["sourceText"]


def test_cleanup_only_opens_its_isolated_database(tmp_path: Path) -> None:
    database = tmp_path / "monitor.sqlite3"
    assert asyncio.run(_deactivate_isolated_plan(database)) == "NO_DATABASE"
    assert not database.exists()


def test_isolated_ai_lifecycle_selects_pro_and_removes_retries(tmp_path: Path) -> None:
    config = tmp_path / "app.yaml"
    config.write_text(
        "ai:\n"
        "  profile: DEEPSEEK\n"
        "  model: deepseek-flash\n"
        "  additional_models:\n"
        "    - display_name: DeepSeek Pro\n"
        "      model: deepseek-v4-pro\n"
        "  api_key: test-only-key\n",
        encoding="utf-8",
    )
    budget = Budget(total=3, per_key={key: 1 for key in approved_sources()}, seconds=60)
    lifecycle = _bounded_ai_factory(config, None, budget)

    async def exercise() -> None:
        await lifecycle.start()
        try:
            assert len(lifecycle._bindings) == 1
            binding = next(iter(lifecycle._bindings.values()))
            assert binding.config.model == APPROVED_MODEL
            assert binding.config.max_retries == 0
            assert binding.config.max_output_tokens == 4096
        finally:
            await lifecycle.stop()

    asyncio.run(exercise())
    assert budget.snapshot()["totalAttempts"] == 0


def test_simulated_r14_launcher_refuses_unwritable_diagnostics_before_ai(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "app.yaml"
    config.write_text(
        "ai:\n"
        "  profile: DEEPSEEK\n"
        "  model: deepseek-flash\n"
        "  additional_models:\n"
        "    - display_name: DeepSeek Pro\n"
        "      model: deepseek-v4-pro\n"
        "  api_key: test-only-key\n",
        encoding="utf-8",
    )
    budget = Budget(total=3, per_key={key: 1 for key in approved_sources()}, seconds=60)

    def fail_sink(_path: Path) -> None:
        raise OSError("SIMULATED diagnostic disk denial")

    monkeypatch.setattr("trade_plan_monitor.web.ai_service.ensure_diagnostic_sink", fail_sink)
    lifecycle = _bounded_ai_factory(
        config, None, budget, database=tmp_path / "isolated/monitor.sqlite3"
    )

    async def exercise() -> None:
        try:
            with pytest.raises(BudgetDenied):
                await lifecycle.start()
        finally:
            await lifecycle.stop()

    asyncio.run(exercise())
    assert budget.snapshot()["totalAttempts"] == 0


def test_isolated_app_constructs_without_database_or_network(tmp_path: Path) -> None:
    from trade_plan_monitor.web.app import create_app, installed_web_assets
    from trade_plan_monitor.web.monitor_composition import create_monitor_composition_factory
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    config = tmp_path / "app.yaml"
    config.write_text("web:\n  host: 127.0.0.1\n  port: 18765\n", encoding="utf-8")
    database = tmp_path / "monitor.sqlite3"
    plans = PersistentPlanWebLifecycle(database_path=database)
    budget = Budget(total=3, per_key={key: 1 for key in approved_sources()}, seconds=60)
    with installed_web_assets() as assets:
        app = create_app(
            runtime_factory=create_monitor_composition_factory(
                config_path=config, database_path=database
            ),
            plan_lifecycle_factory=lambda: plans,
            ai_lifecycle_factory=lambda: _bounded_ai_factory(config, plans, budget),
            bind_host="127.0.0.1",
            bind_port=18765,
            static_directory=assets,
        )
        assert "/api/v1/plan-extractions" in app.openapi()["paths"]
    assert not database.exists()
    assert budget.snapshot()["totalAttempts"] == 0


def test_activation_recovery_uses_existing_pipeline_once() -> None:
    requested_dates: list[date] = []

    class Recovery:
        async def recover_startup(self, *, trade_date: date) -> SimpleNamespace:
            requested_dates.append(trade_date)
            return SimpleNamespace(
                attempted_symbols=("003043.SZ",),
                persisted_bar_count=31,
                yielded_to_realtime=False,
                results=(SimpleNamespace(error_code=None),),
            )

    class State:
        _pipeline = SimpleNamespace(recovery=Recovery())

        async def run_deadline(self) -> None:
            return None

    runtime = SimpleNamespace(_runtime=SimpleNamespace(_run_deadline=State().run_deadline))
    report = asyncio.run(_recover_activated_symbol(runtime, date(2026, 9, 14)))
    assert requested_dates == [date(2026, 9, 14)]
    assert report == {
        "mode": "TEST_TRIGGERED_PRODUCTION_RECOVERY",
        "attemptedSymbols": ["003043.SZ"],
        "persistedMinuteBars": 31,
        "yieldedToRealtime": False,
        "errorCodes": [None],
    }
