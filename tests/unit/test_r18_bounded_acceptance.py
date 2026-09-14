"""The R18 candidate has a distinct date, claim and physical-call boundary."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from scripts import r14_bounded_acceptance as r14
from scripts import r17_bounded_acceptance as r17
from scripts import r18_bounded_acceptance as r18


def test_window_and_limits_are_bound_to_the_new_session() -> None:
    assert r18.AUTHORIZATION not in {r14.AUTHORIZATION, r17.AUTHORIZATION}
    assert r18.RUN_ID not in {"r14-20260914-a", r17.RUN_ID}
    assert r18.PROPOSAL_ID == "R18-20260915-AFTERNOON-60"
    assert r18.MARKET_CAPS == r17.MARKET_CAPS
    assert sum(r18.MARKET_CAPS.values()) == 60
    assert r18._eligible(datetime(2026, 9, 15, 14, 30))
    assert r18._eligible(datetime(2026, 9, 15, 14, 40))
    for instant in (
        datetime(2026, 9, 14, 14, 35),
        datetime(2026, 9, 15, 14, 29, 59),
        datetime(2026, 9, 15, 14, 40, 0, 1),
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
    ai, market = r14._session_budgets(lambda: None, market_caps=r18.MARKET_CAPS)
    for _ in range(30):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        market.admit("rt_idx_min_daily")
    with pytest.raises(r14.BudgetDenied):
        ai.admit("LITERAL")
    assert market.snapshot()["totalAttempts"] == 30
    assert ai.snapshot()["totalAttempts"] == 0
    assert market.snapshot()["deniedBeforeNetwork"] == 1
