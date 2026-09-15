from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import r22_calendar_diagnostic as r22

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_r22_contract_allows_only_one_calendar_start_and_no_ai() -> None:
    assert r22._eligible(datetime(2026, 9, 15, 11, 20, tzinfo=_SHANGHAI))
    assert r22._eligible(datetime(2026, 9, 15, 11, 55, tzinfo=_SHANGHAI))
    assert not r22._eligible(datetime(2026, 9, 15, 11, 55, 1, tzinfo=_SHANGHAI))
    assert r22.RUN_ID == "r22-20260915-a"
    assert r22.BIND_PORT == 18767
    assert r22.AI_TOTAL == 0
    assert r22.MARKET_TOTAL == 1
    assert r22.MARKET_CAPS == {
        "trade_cal": 1,
        "stk_limit": 0,
        "daily": 0,
        "rt_min_daily": 0,
        "rt_min": 0,
        "idx_mins": 0,
        "rt_idx_min_daily": 0,
        "index_daily": 0,
    }
    assert r22.WALL_SECONDS == 15
    assert r22.STOP_ON_MARKET_FAILURE_KEYS == frozenset({"trade_cal"})
    assert r22.STOP_ON_REFERENCE_FAILURE is True


def test_r22_preflight_exposes_zero_ai_and_single_calendar_caps(monkeypatch) -> None:
    monkeypatch.setattr(r22, "_eligible", lambda _now: True)

    result = r22._preflight()

    assert result["limits"]["aiPhysicalAttempts"] == 0
    assert result["limits"]["marketPhysicalAttempts"] == 1
    assert result["limits"]["marketPerEndpointAttempts"] == r22.MARKET_CAPS
    assert result["proposalId"] == r22.PROPOSAL_ID
    assert result["runId"] == r22.RUN_ID
    assert result["mode"] == "DRY_RUN_NO_NETWORK"
