"""The R18 candidate has a distinct date, claim and physical-call boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from scripts import r14_bounded_acceptance as r14
from scripts import r17_bounded_acceptance as r17
from scripts import r18_bounded_acceptance as r18


def test_window_and_limits_are_bound_to_the_new_session() -> None:
    assert r18.AUTHORIZATION not in {r14.AUTHORIZATION, r17.AUTHORIZATION}
    assert r18.RUN_ID not in {"r14-20260914-a", r17.RUN_ID}
    assert r18.PROPOSAL_ID == "R18-20260915-OPEN-105"
    assert r18.MARKET_CAPS["rt_idx_min_daily"] == 50
    assert r18.MARKET_CAPS["rt_min"] == 40
    assert sum(r18.MARKET_CAPS.values()) == r18.MARKET_TOTAL == 105
    assert r18.WALL_SECONDS == 2280
    assert r18._eligible(datetime(2026, 9, 15, 9, 30))
    assert r18._eligible(datetime(2026, 9, 15, 9, 31))
    for instant in (
        datetime(2026, 9, 14, 14, 35),
        datetime(2026, 9, 15, 9, 29, 59),
        datetime(2026, 9, 15, 9, 31, 0, 1),
        datetime(2026, 9, 16, 14, 35),
    ):
        assert not r18._eligible(instant)


def test_default_and_invalid_authorization_never_start(monkeypatch, capsys) -> None:
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(r18.bounded, "_serve", forbidden)
    monkeypatch.setattr(r18, "_preflight", lambda: {"ready": True})
    assert r18.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"ready": True}
    assert r18.main(["--execute", "--authorize", r17.AUTHORIZATION, "--run-id", r18.RUN_ID]) == 2
    assert r18.main(["--execute", "--authorize", r18.AUTHORIZATION, "--run-id", r17.RUN_ID]) == 2
    monkeypatch.setattr(r18, "_preflight", lambda: {"ready": False})
    assert r18.main(["--execute", "--authorize", r18.AUTHORIZATION, "--run-id", r18.RUN_ID]) == 2
    assert calls == []


def test_only_new_root_and_claim_are_used(tmp_path: Path, monkeypatch) -> None:
    calls = []

    async def serve(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(r18.bounded, "_ROOT", tmp_path)
    monkeypatch.setattr(r18.bounded, "_serve", serve)
    monkeypatch.setattr(r18, "_preflight", lambda: {"ready": True})
    monkeypatch.setattr(r18, "_eligible", lambda _now: True)
    assert r18.main(["--execute", "--authorize", r18.AUTHORIZATION, "--run-id", r18.RUN_ID]) == 0
    assert calls == [
        (
            (r18.RUN_ID,),
            {
                "session_root": tmp_path / "data/r18-acceptance",
                "market_caps": r18.MARKET_CAPS,
                "market_total": r18.MARKET_TOTAL,
                "wall_seconds": r18.WALL_SECONDS,
                "proposal_id": r18.PROPOSAL_ID,
            },
        )
    ]
    for previous in ("r14-acceptance", "r17-acceptance"):
        claim = tmp_path / "data" / previous / "_session_claimed"
        claim.mkdir(parents=True)
    root = tmp_path / "data/r18-acceptance"
    assert r14._claim_session(root, r18.RUN_ID) == root / r18.RUN_ID
    with pytest.raises(FileExistsError):
        r14._claim_session(root, r18.RUN_ID)
    assert all(
        (tmp_path / "data" / old / "_session_claimed").is_dir()
        for old in ("r14-acceptance", "r17-acceptance")
    )


def test_shared_market_denial_stops_ai_before_network() -> None:
    ai, market = r14._session_budgets(
        lambda: None,
        market_caps=r18.MARKET_CAPS,
        market_total=r18.MARKET_TOTAL,
        wall_seconds=r18.WALL_SECONDS,
    )
    for _ in range(50):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        ai.admit("LITERAL")
    assert market.snapshot()["totalAttempts"] == 50
    assert ai.snapshot()["totalAttempts"] == 0
    assert market.snapshot()["deniedBeforeNetwork"] == 1


def test_105th_market_start_is_last_admitted_start() -> None:
    ai, market = r14._session_budgets(
        lambda: None,
        market_caps=r18.MARKET_CAPS,
        market_total=r18.MARKET_TOTAL,
        wall_seconds=r18.WALL_SECONDS,
    )
    for operation, cap in r18.MARKET_CAPS.items():
        for _ in range(cap):
            market.admit(operation)
    assert market.snapshot()["totalAttempts"] == 105
    with pytest.raises(r14.BudgetDenied):
        market.admit("trade_cal")
    with pytest.raises(r14.BudgetDenied):
        ai.admit("SEM-AMB-01")
    assert market.snapshot()["totalAttempts"] == 105


def test_opening_session_deadline_denies_both_sides_after_38_minutes(monkeypatch) -> None:
    tick = [100.0]
    monkeypatch.setattr(r14, "monotonic", lambda: tick[0])
    ai, market = r14._session_budgets(
        lambda: None,
        market_caps=r18.MARKET_CAPS,
        market_total=r18.MARKET_TOTAL,
        wall_seconds=r18.WALL_SECONDS,
    )
    tick[0] += r18.WALL_SECONDS
    with pytest.raises(r14.BudgetDenied):
        ai.admit("LITERAL")
    with pytest.raises(r14.BudgetDenied):
        market.admit("trade_cal")
    assert ai.snapshot()["totalAttempts"] == market.snapshot()["totalAttempts"] == 0


def test_fresh_opening_day_needs_six_completed_bars_for_volume_rule() -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition
    from trade_plan_monitor.decision.models import ConditionOutcome, MissingInputCode
    from trade_plan_monitor.domain.plan_models import VolumeToMeanGteCondition
    from trade_plan_monitor.market_data.aggregation import FiveMinuteBar

    shanghai = ZoneInfo("Asia/Shanghai")
    first_end = datetime(2026, 9, 15, 9, 35, tzinfo=shanghai)
    bars = tuple(
        FiveMinuteBar(
            symbol="003043.SZ",
            bar_end=first_end + timedelta(minutes=5 * index),
            open_fen=990,
            high_fen=990,
            low_fen=990,
            close_fen=990,
            volume_shares=100,
            amount_yuan=Decimal("0"),
        )
        for index in range(6)
    )
    condition = VolumeToMeanGteCondition(
        window_bars=5, minimum_ratio="1.5", history_scope="CONTIGUOUS_TRADING_BARS"
    )
    early = evaluate_explicit_condition(
        condition,
        bars=bars[:5],
        target_bucket_end=bars[4].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition.conditions[1]",
    )
    first_eligible = evaluate_explicit_condition(
        condition,
        bars=bars,
        target_bucket_end=bars[5].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition.conditions[1]",
    )
    assert early.outcome is ConditionOutcome.MISSING_INPUT
    assert early.missing_inputs == (MissingInputCode.ROLLING_VOLUME_WINDOW,)
    assert first_eligible.outcome is ConditionOutcome.UNSATISFIED
