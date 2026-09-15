from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import r20_bounded_acceptance as r20
from scripts import r23_bounded_acceptance as r23

from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_r23_contract_uses_a_fresh_afternoon_candidate() -> None:
    assert r23._eligible(datetime(2026, 9, 15, 12, 50, tzinfo=_SHANGHAI))
    assert r23._eligible(datetime(2026, 9, 15, 13, 5, tzinfo=_SHANGHAI))
    assert not r23._eligible(datetime(2026, 9, 15, 13, 5, 1, tzinfo=_SHANGHAI))
    assert r23.PROPOSAL_ID == "R23-20260915-PM-105"
    assert r23.RUN_ID == "r23-20260915-a"
    assert r23.BIND_PORT == 18768
    assert r23.PROMPT_VERSION == PLAN_EXTRACTION_PROMPT_V5
    assert r23.AI_OUTPUT_TOKENS == 8192
    assert r23.MARKET_CAPS == r20.MARKET_CAPS
    assert r23.MARKET_TOTAL == 105
    assert r23.WALL_SECONDS == 2280
    assert r23.STOP_ON_MARKET_FAILURE_KEYS == frozenset({"trade_cal"})
    assert r23.STOP_ON_REFERENCE_FAILURE is True


def test_r23_preflight_keeps_v5_and_bounded_physical_limits(monkeypatch) -> None:
    monkeypatch.setattr(r23, "_eligible", lambda _now: True)

    result = r23._preflight()

    assert result["limits"]["aiPhysicalAttempts"] == 3
    assert result["limits"]["aiOutputTokensPerRequest"] == 8192
    assert result["limits"]["promptVersion"] == PLAN_EXTRACTION_PROMPT_V5
    assert result["limits"]["marketPhysicalAttempts"] == 105
    assert result["limits"]["marketPerEndpointAttempts"] == r23.MARKET_CAPS
    assert result["proposalId"] == r23.PROPOSAL_ID
    assert result["runId"] == r23.RUN_ID
    assert result["mode"] == "DRY_RUN_NO_NETWORK"
