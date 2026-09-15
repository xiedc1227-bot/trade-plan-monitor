from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from scripts import r14_bounded_acceptance as bounded
from scripts import r20_bounded_acceptance as r20

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
