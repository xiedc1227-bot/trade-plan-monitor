"""R17 uses a separate one-shot authorization and a fixed new cap profile."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from scripts import r14_bounded_acceptance as r14
from scripts import r17_bounded_acceptance as r17


def test_distinct_date_run_id_and_endpoint_sum() -> None:
    assert r17.PROPOSAL_ID != "R14"
    assert r17.AUTHORIZATION != r14.AUTHORIZATION
    assert r17.RUN_ID != "r14-20260914-a"
    assert sum(r17.MARKET_CAPS.values()) == 60
    assert r17.MARKET_CAPS["trade_cal"] == 3
    assert r17.MARKET_CAPS["rt_min"] == 15
    assert r17.MARKET_CAPS["rt_min_daily"] == 2
    assert r17.MARKET_CAPS["rt_idx_min_daily"] == 30
    assert r14._MARKET_CAPS["rt_idx_min_daily"] == 25
    assert r17._eligible(datetime(2026, 9, 15, 10, 10))
    assert r17._eligible(datetime(2026, 9, 15, 10, 30))
    for value in (
        datetime(2026, 9, 14, 10, 12),
        datetime(2026, 9, 15, 10, 9),
        datetime(2026, 9, 15, 10, 30, 0, 1),
        datetime(2026, 9, 16, 10, 12),
    ):
        assert not r17._eligible(value)


def test_old_token_bad_id_and_preflight_never_start(monkeypatch, capsys) -> None:
    started = []

    async def forbidden(*args, **kwargs):
        started.append((args, kwargs))

    monkeypatch.setattr(r17.bounded, "_serve", forbidden)
    monkeypatch.setattr(r17, "_preflight", lambda: {"ready": True})
    assert r17.main(["--execute", "--authorize", r14.AUTHORIZATION, "--run-id", r17.RUN_ID]) == 2
    assert (
        r17.main(["--execute", "--authorize", r17.AUTHORIZATION, "--run-id", "r14-20260914-a"]) == 2
    )
    monkeypatch.setattr(r17, "_preflight", lambda: {"ready": False})
    assert r17.main(["--execute", "--authorize", r17.AUTHORIZATION, "--run-id", r17.RUN_ID]) == 2
    assert r17.main([]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == {"ready": False}
    assert not started


def test_approved_route_passes_only_r17_root_and_caps(tmp_path: Path, monkeypatch) -> None:
    received = []

    async def serve(*args, **kwargs):
        received.append((args, kwargs))
        return 0

    monkeypatch.setattr(r17.bounded, "_ROOT", tmp_path)
    monkeypatch.setattr(r17.bounded, "_serve", serve)
    monkeypatch.setattr(r17, "_preflight", lambda: {"ready": True})
    monkeypatch.setattr(r17, "_eligible", lambda _now: True)
    assert r17.main(["--execute", "--authorize", r14.AUTHORIZATION, "--run-id", r17.RUN_ID]) == 2
    assert (
        r17.main(["--execute", "--authorize", r17.AUTHORIZATION, "--run-id", "r14-20260914-a"]) == 2
    )
    assert not received
    assert r17.main(["--execute", "--authorize", r17.AUTHORIZATION, "--run-id", r17.RUN_ID]) == 0
    assert received == [
        (
            (r17.RUN_ID,),
            {
                "session_root": tmp_path / "data/r17-acceptance",
                "market_caps": r17.MARKET_CAPS,
                "proposal_id": r17.PROPOSAL_ID,
            },
        )
    ]


def test_new_claim_is_one_shot_and_old_claim_is_untouched(tmp_path: Path) -> None:
    old_claim = tmp_path / "data/r14-acceptance/_session_claimed"
    old_claim.mkdir(parents=True)
    new_root = tmp_path / "data/r17-acceptance"
    assert r14._claim_session(new_root, r17.RUN_ID) == new_root / r17.RUN_ID
    with pytest.raises(FileExistsError):
        r14._claim_session(new_root, r17.RUN_ID)
    assert old_claim.is_dir()


def test_shared_stop_and_timeout_deny_before_physical_call(monkeypatch) -> None:
    ticks = [100.0]
    monkeypatch.setattr(r14, "monotonic", lambda: ticks[0])
    ai, market = r14._session_budgets(lambda: None, market_caps=r17.MARKET_CAPS)
    for _ in range(30):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        ai.admit("LITERAL")
    assert market.snapshot()["attempts"] == {"rt_idx_min_daily": 30}
    assert market.snapshot()["deniedBeforeNetwork"] == 1
    assert ai.snapshot()["deniedBeforeNetwork"] == 1

    ai, market = r14._session_budgets(lambda: None, market_caps=r17.MARKET_CAPS)
    ticks[0] = 1000.0
    with pytest.raises(r14.BudgetDenied):
        market.admit("trade_cal")
    with pytest.raises(r14.BudgetDenied):
        ai.admit("LITERAL")
    assert market.snapshot()["totalAttempts"] == ai.snapshot()["totalAttempts"] == 0
