from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import r24_calendar_diagnostic as r24

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_r24_contract_allows_only_one_calendar_start_and_no_ai() -> None:
    assert r24._eligible(datetime(2026, 9, 15, 14, 18, tzinfo=_SHANGHAI))
    assert r24._eligible(datetime(2026, 9, 15, 14, 35, tzinfo=_SHANGHAI))
    assert not r24._eligible(datetime(2026, 9, 15, 14, 35, 1, tzinfo=_SHANGHAI))
    assert r24.PROPOSAL_ID == "R24-20260915-PM-CALENDAR-1"
    assert r24.RUN_ID == "r24-20260915-a"
    assert r24.BIND_PORT == 18769
    assert r24.AI_TOTAL == 0
    assert r24.MARKET_TOTAL == 1
    assert r24.MARKET_CAPS == {
        "trade_cal": 1,
        "stk_limit": 0,
        "daily": 0,
        "rt_min_daily": 0,
        "rt_min": 0,
        "idx_mins": 0,
        "rt_idx_min_daily": 0,
        "index_daily": 0,
    }
    assert r24.WALL_SECONDS == 20
    assert r24.STOP_ON_MARKET_FAILURE_KEYS == frozenset({"trade_cal"})
    assert r24.STOP_ON_REFERENCE_FAILURE is True


def test_r24_preflight_exposes_zero_ai_and_single_calendar_caps(monkeypatch) -> None:
    monkeypatch.setattr(r24, "_eligible", lambda _now: True)

    result = r24._preflight()

    assert result["limits"]["aiPhysicalAttempts"] == 0
    assert result["limits"]["marketPhysicalAttempts"] == 1
    assert result["limits"]["marketPerEndpointAttempts"] == r24.MARKET_CAPS
    assert result["proposalId"] == r24.PROPOSAL_ID
    assert result["runId"] == r24.RUN_ID
    assert result["diagnosticOnly"] is True
    assert result["aiCostUsd"] == 0
    assert result["marketCostStatus"] == "UNKNOWN"
    assert result["mode"] == "DRY_RUN_NO_NETWORK"
