"""Offline guard tests for the optional R14 real-interface harness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from scripts.r14_bounded_acceptance import (
    APPROVED_MODEL,
    AIBudgetTransport,
    Budget,
    BudgetDenied,
    MarketBudget,
    _bounded_ai_factory,
    _deactivate_isolated_plan,
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
    assert budget.snapshot()["attempts"] == {"rt_min": 1}
    assert calls == ["rt_min"]


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
