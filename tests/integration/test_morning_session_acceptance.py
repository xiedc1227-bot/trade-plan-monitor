from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import requests
from scripts import bounded_live_acceptance as bounded
from scripts import morning_session_acceptance as r20

from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_r20_contract_is_new_date_bound_and_keeps_old_defaults() -> None:
    assert r20._eligible(datetime(2026, 9, 15, 10, 35, tzinfo=_SHANGHAI))
    assert r20._eligible(datetime(2026, 9, 15, 10, 50, tzinfo=_SHANGHAI))
    assert not r20._eligible(datetime(2026, 9, 15, 10, 50, 1, tzinfo=_SHANGHAI))
    assert r20.RUN_ID == "r20-20260915-a"
    assert r20.BIND_PORT == 18766
    assert r20.AI_OUTPUT_TOKENS == 8192
    assert r20.PROMPT_VERSION == PLAN_EXTRACTION_PROMPT_V5
    assert bounded.approved_sources() != bounded.approved_sources(
        prompt_version=PLAN_EXTRACTION_PROMPT_V5
    )


def test_r20_ai_guard_accepts_only_v5_8192_request() -> None:
    seen: list[dict[str, object]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [], "usage": {}})

    budget = bounded.Budget(
        total=3,
        per_key={case_id: 1 for case_id in bounded.approved_sources(
            prompt_version=PLAN_EXTRACTION_PROMPT_V5
        )},
        seconds=60,
    )
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(respond),
        prompt_version=PLAN_EXTRACTION_PROMPT_V5,
        max_output_tokens=8192,
    )
    _, prompt = bounded.approved_sources(
        prompt_version=PLAN_EXTRACTION_PROMPT_V5
    )["LITERAL"]
    request = httpx.Request(
        "POST",
        "https://api.deepseek.com/chat/completions",
        json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "stream": False,
        },
    )

    asyncio.run(transport.handle_async_request(request))

    assert seen[0]["max_tokens"] == 8192
    assert seen[0]["messages"][0]["content"].startswith("Prompt version: plan-extract-v5")
    assert "Prompt version: plan-extract-v5" in seen[0]["messages"][0]["content"]
    assert budget.snapshot()["attempts"] == {"LITERAL": 1}


def test_r20_first_calendar_failure_programmatically_stops_every_budget() -> None:
    stop_calls: list[bool] = []
    failures: list[tuple[str, dict[str, object]]] = []
    ai_budget, market_budget = bounded._session_budgets(
        lambda: stop_calls.append(True),
        market_caps=r20.MARKET_CAPS,
        market_total=r20.MARKET_TOTAL,
    )
    guard = bounded.MarketBudget(
        market_budget,
        stop_on_failure_keys=r20.STOP_ON_MARKET_FAILURE_KEYS,
        on_failure=lambda key, failure: failures.append((key, failure)),
    )
    physical_starts = 0

    def fail_calendar(_name: str, **_kwargs: object) -> object:
        nonlocal physical_starts
        physical_starts += 1
        raise requests.Timeout("SECRET remote timeout")

    with pytest.raises(requests.Timeout):
        guard.call(fail_calendar, "trade_cal", exchange="SSE")

    assert physical_starts == 1
    assert stop_calls == [True]
    assert market_budget.snapshot()["attempts"] == {"trade_cal": 1}
    assert market_budget.snapshot()["stopped"] is True
    assert ai_budget.snapshot()["stopped"] is True
    assert failures == [
        (
            "trade_cal",
            {
                "code": "TIMEOUT",
                "failureKind": "TRANSPORT_TIMEOUT",
                "httpStatusClass": None,
            },
        )
    ]
    with pytest.raises(bounded.BudgetDenied):
        guard.call(fail_calendar, "trade_cal", exchange="SSE")
    with pytest.raises(bounded.BudgetDenied):
        ai_budget.admit("LITERAL")
    assert physical_starts == 1


def test_physical_attempt_journal_survives_failed_calendar_cleanup_gap(tmp_path: Path) -> None:
    path = tmp_path / "physical-attempts.json"
    journal = bounded.PhysicalAttemptJournal(
        path,
        proposal_id="R21-OFFLINE",
        run_id="offline-r21",
        started_at="2026-09-15T10:40:25.420+08:00",
    )
    ai_budget, market_budget = bounded._session_budgets(
        lambda: None,
        market_caps=r20.MARKET_CAPS,
        market_total=r20.MARKET_TOTAL,
        on_ai_snapshot=lambda snapshot: journal.record_budget("ai", snapshot),
        on_market_snapshot=lambda snapshot: journal.record_budget("market", snapshot),
    )
    guard = bounded.MarketBudget(
        market_budget,
        stop_on_failure_keys=r20.STOP_ON_MARKET_FAILURE_KEYS,
        on_failure=journal.record_market_failure,
    )

    with pytest.raises(requests.ConnectionError):
        guard.call(
            lambda _name, **_kwargs: (_ for _ in ()).throw(
                requests.ConnectionError("SECRET provider body")
            ),
            "trade_cal",
            exchange="SSE",
        )

    evidence_text = path.read_text("utf-8")
    evidence = json.loads(evidence_text)
    assert "SECRET" not in evidence_text
    assert evidence["normalAuditPresent"] is False
    assert evidence["status"] == "FAILURE_STOP_REQUESTED"
    assert evidence["market"]["totalAttempts"] == 1
    assert evidence["market"]["attempts"] == {"trade_cal": 1}
    assert evidence["firstMarketFailure"] == {
        "operation": "trade_cal",
        "code": "TRANSIENT",
        "failureKind": "TRANSPORT_CONNECTION",
        "httpStatusClass": None,
    }
    with pytest.raises(bounded.BudgetDenied):
        ai_budget.admit("LITERAL")


def test_launcher_calendar_failure_closes_and_writes_normal_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn
    from tests.integration.test_live_acceptance_offline_wiring import (
        QuerySDK,
        _write_end_label_stock_evidence,
    )
    from tests.integration.test_live_pipeline_acceptance import (
        ControlledClock,
        _write_configuration_and_evidence,
    )

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    clock = ControlledClock(datetime(2026, 9, 15, 10, 40, tzinfo=_SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path,
        observed_at=clock.now(),
        include_index=True,
    )
    _write_end_label_stock_evidence(tmp_path, clock.now())
    config.write_text(
        config.read_text("utf-8")
        + "  connect_ip: 127.0.0.1\n"
        + "ai:\n  profile: DEEPSEEK\n  model: deepseek-flash\n"
        + "  additional_models:\n    - display_name: DeepSeek Pro\n"
        + "      model: deepseek-v4-pro\n  api_key: offline-test-key\n",
        encoding="utf-8",
    )
    sources = bounded.approved_sources()
    monkeypatch.setattr(bounded, "_ROOT", tmp_path)
    monkeypatch.setattr(bounded, "approved_sources", lambda: sources)
    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)

    class FailingCalendarSDK(QuerySDK):
        def query(self, name: str, fields: str = "", **kwargs: object):
            if name == "trade_cal":
                raise requests.Timeout("SECRET provider timeout")
            return super().query(name, fields=fields, **kwargs)

    monkeypatch.setattr(
        production,
        "create_tushare_client",
        lambda _settings: FailingCalendarSDK(clock, ()),
    )

    class LocalServer:
        def __init__(self, settings: uvicorn.Config) -> None:
            self.app = settings.app
            self.started = False
            self.should_exit = False

        async def serve(self, *, sockets: object) -> None:
            assert sockets
            async with self.app.router.lifespan_context(self.app):
                self.started = True
                assert self.should_exit is True

    monkeypatch.setattr(uvicorn, "Server", LocalServer)

    result = asyncio.run(
        bounded._serve(
            "offline-r21",
            session_root=tmp_path / "data/r21-offline",
            market_caps=r20.MARKET_CAPS,
            market_total=r20.MARKET_TOTAL,
            proposal_id="R21-OFFLINE",
            stop_on_market_failure_keys=r20.STOP_ON_MARKET_FAILURE_KEYS,
            stop_on_reference_failure=r20.STOP_ON_REFERENCE_FAILURE,
        )
    )

    folder = tmp_path / "data/r21-offline/offline-r21"
    audit_text = (folder / "audit.json").read_text("utf-8")
    audit = json.loads(audit_text)
    journal = json.loads((folder / "physical-attempts.json").read_text("utf-8"))
    assert result == 1
    assert "SECRET" not in audit_text
    assert audit["status"] == "REFERENCE_FAILED"
    assert audit["referenceFailureCode"] == "REFERENCE_TIMEOUT"
    assert audit["ai"]["totalAttempts"] == 0
    assert audit["market"]["attempts"] == {"trade_cal": 1}
    assert audit["firstMarketFailure"] == {
        "operation": "trade_cal",
        "code": "TIMEOUT",
        "failureKind": "TRANSPORT_TIMEOUT",
        "httpStatusClass": None,
    }
    assert audit["isolatedPlanCleanup"] == "INACTIVE"
    assert journal["normalAuditPresent"] is True
    assert journal["status"] == "REFERENCE_FAILED"
    assert journal["ai"] == audit["ai"]
    assert journal["market"] == audit["market"]


def test_journal_write_failure_denies_before_physical_start() -> None:
    stop_calls: list[bool] = []

    def fail_write(_snapshot: dict[str, object]) -> None:
        raise OSError("simulated local journal failure")

    budget = bounded.Budget(
        total=1,
        per_key={"trade_cal": 1},
        seconds=60,
        on_denied=lambda: stop_calls.append(True),
        on_snapshot=fail_write,
    )

    with pytest.raises(bounded.BudgetDenied):
        budget.admit("trade_cal")

    assert budget.snapshot()["attempts"] == {}
    assert budget.snapshot()["deniedBeforeNetwork"] == 1
    assert budget.snapshot()["stopped"] is True
    assert stop_calls == [True]
