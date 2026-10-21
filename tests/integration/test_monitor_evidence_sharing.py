"""Real transaction snapshots and per-observer decisions around a shared index proof."""

import asyncio
import os
import sqlite3
from dataclasses import replace
from datetime import timedelta
from threading import Event, get_ident

import pytest
from test_persistent_monitor_read_service import _NOW, _setup
from test_runtime_status_projection import TARGET, _current_status

from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state import projections
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def seed(sessions, now, count=1):
    snapshots = []
    with SqlAlchemyUnitOfWork(sessions, clock=lambda: now) as work:
        for i in range(count):
            at = now - timedelta(minutes=5 * (count - i))
            snapshot = build_market_index_snapshot(
                index_code=DASHBOARD_INDEX_CODES[0], decision_cutoff=at,
                requests=(), five_minute_bars=(), official_daily_bars=(),
                content_revision=i + 1, observed_at=at, observed_no_later_than=at,
            )
            work.projections.put_market_index_snapshot(snapshot, provider_content_revision=i + 1)
            work.projections.advance_market_index_head(snapshot, provider_content_revision=i + 1)
            snapshots.append(snapshot)
        work.commit()
    return snapshots


def hold_first(monkeypatch):
    entered, release = Event(), Event()
    original = projections._latest_index_records
    calls = []

    def held(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(projections, "_latest_index_records", held)
    return entered, release


@pytest.mark.parametrize(
    "damage", ["canonical", "same_size", "missing", "provider", "formula", "blob", "retained"],
)
def test_new_snapshot_never_joins_valid_proof_after_unselected_tamper(
    tmp_path, monkeypatch, damage,
):
    engine, _, _, health = _setup(tmp_path)
    sessions = create_session_factory(engine)
    snapshots = seed(sessions, _NOW, 130)
    authority = RuntimeReadAuthority(
        token="stable", lifecycle="STOPPED", progress=None, health=health, owner_absent=True,
    )
    reader = RuntimeStatusReadService(sessions, lambda: authority, clock=lambda: _NOW)
    # First valid read cannot cache permission for any subsequent snapshot.
    asyncio.run(reader.get_dashboard())
    entered, release = hold_first(monkeypatch)

    async def scenario():
        first = asyncio.create_task(reader.get_dashboard())
        await until(entered.is_set)
        path = tmp_path / "monitor.db"
        before = path.stat()
        with sqlite3.connect(path) as connection:
            key = snapshots[1].snapshot_hash  # An unselected historical row across 128-row batches.
            if damage == "retained":
                connection.execute(
                    "DELETE FROM market_index_snapshot_head WHERE snapshot_hash=?", (key,),
                )
            elif damage == "missing":
                connection.execute(
                    "DELETE FROM market_index_snapshot WHERE snapshot_hash=?", (key,),
                )
            elif damage == "provider":
                connection.execute(
                    "UPDATE market_index_snapshot_head SET provider_content_revision=999 "
                    "WHERE snapshot_hash=?", (key,),
                )
            elif damage == "formula":
                connection.execute(
                    "UPDATE market_index_snapshot SET formula_definition_hash=? "
                    "WHERE snapshot_hash=?", ("0" * 64, key),
                )
            else:
                raw = connection.execute(
                    "SELECT snapshot_json FROM market_index_snapshot WHERE snapshot_hash=?", (key,),
                ).fetchone()[0]
                changed = raw.encode() if damage == "blob" else (
                    raw + " " if damage == "canonical" else
                    raw.replace(
                        f'"revision":{snapshots[1].revision}',
                        f'"revision":{snapshots[1].revision + 1}',
                    )
                )
                assert changed != raw
                if damage == "same_size":
                    assert len(changed.encode()) == len(raw.encode())
                connection.execute(
                    "UPDATE market_index_snapshot SET snapshot_json=? WHERE snapshot_hash=?",
                    (changed, key),
                )
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        second = asyncio.create_task(reader.get_dashboard())
        try:
            await until(lambda: reader._index_verifier.snapshot()["queued_owners"] == 1)
        finally:
            release.set()
        assert (await first).market_indexes
        if damage == "retained":
            assert (await second).market_indexes
        else:
            with pytest.raises(ApiError):
                await second
        assert reader._index_verifier.snapshot()["joins"] == 0
        assert reader._index_verifier.snapshot()["mismatches"] == 1
        # A failed future is not a cache either.
        if damage == "retained":
            assert (await reader.get_dashboard()).market_indexes
        else:
            with pytest.raises(ApiError):
                await reader.get_dashboard()
        await reader.stop()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        engine.dispose()


@pytest.mark.parametrize("later", [90, 302, 86462, -1])
def test_joined_index_proof_keeps_each_observers_time_target_and_eligibility(
    tmp_path, monkeypatch, later,
):
    env = _current_status(tmp_path, monkeypatch)
    seed(env.sessions, env.now)
    clock = [TARGET + timedelta(seconds=89)]
    env.reader._clock = lambda: clock[0]
    # Keep the owner's facts fixed: only the observer's time crosses the boundary.
    owner = env.current[0]
    env.current[0] = replace(owner, progress=replace(
        owner.progress, observed_at=clock[0], last_progress_at=clock[0],
        next_wake_at=clock[0] + timedelta(days=2),
        progress_due_at=clock[0] + timedelta(days=2, seconds=1),
    ))
    calls, loop_thread = [], get_ident()

    def authority():
        assert get_ident() == loop_thread
        calls.append(asyncio.current_task())
        return env.current[0]

    env.reader._authority = authority
    entered, release = hold_first(monkeypatch)

    async def scenario():
        first = asyncio.create_task(env.reader.get_dashboard())
        await until(entered.is_set)
        clock[0] = TARGET + timedelta(seconds=later)
        second = asyncio.create_task(env.reader.get_dashboard())
        try:
            if later < 0:
                await until(second.done)
            else:
                await until(lambda: env.reader._index_verifier.snapshot()["joins"] == 1)
        finally:
            release.set()
        a, b = await asyncio.gather(first, second, return_exceptions=True)
        assert a.observed_at == TARGET + timedelta(seconds=89)
        assert a.symbols[0].current_actionable
        if later < 0:
            assert isinstance(b, ApiError)  # A shared proof cannot retimestamp future evidence.
            assert len(set(calls)) == 2
            await env.reader.stop()
            return
        assert b.observed_at == clock[0]
        assert not b.symbols[0].current_actionable
        assert len(calls) == 4 and len(set(calls)) == 2
        if later == 90:
            assert b.symbols[0].availability == "CACHED" and b.symbols[0].scope.read_only
        else:
            assert b.symbols[0].scope.required_target != a.symbols[0].scope.required_target
        assert env.reader._index_verifier.snapshot()["physical_validations"] == 1
        await env.reader.stop()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        env.close()


@pytest.mark.parametrize(
    "change", ["configuration_revision", "generation", "STOPPING", "STALLED", "unknown"],
)
def test_shared_proof_cannot_bypass_each_authority_after_check(tmp_path, monkeypatch, change):
    env = _current_status(tmp_path, monkeypatch)
    seed(env.sessions, env.now)
    entered, release = hold_first(monkeypatch)
    calls = []

    def authority():
        calls.append(asyncio.current_task())
        return env.current[0]

    env.reader._authority = authority

    async def scenario():
        first = asyncio.create_task(env.reader.get_dashboard())
        await until(entered.is_set)
        second = asyncio.create_task(env.reader.get_dashboard())
        try:
            await until(lambda: env.reader._index_verifier.snapshot()["joins"] == 1)
            owner = env.current[0]
            if change == "unknown":
                env.current[0] = None
            elif change == "configuration_revision":
                env.current[0] = replace(owner, configuration_revision="new")
            elif change == "STOPPING":
                env.current[0] = replace(owner, lifecycle="STOPPING")
            elif change == "generation":
                from uuid import uuid4
                env.current[0] = replace(
                    owner, progress=replace(owner.progress, runtime_generation=uuid4()),
                )
            else:
                env.current[0] = replace(owner, progress=replace(owner.progress, state="STALLED"))
        finally:
            release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        for result in results:
            if change == "unknown" or change == "STALLED" and isinstance(result, ApiError):
                assert isinstance(result, ApiError)
            else:
                assert not isinstance(result, BaseException)
                assert not result.symbols[0].current_actionable
                assert result.symbols[0].scope.read_only
        assert len(set(calls)) == 2 and 6 <= len(calls) <= 8
        await env.reader.stop()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        env.close()


@pytest.mark.parametrize("change", ["inventory", "calendar", "proof", "activation"])
def test_same_index_proof_cannot_replace_new_request_plan_input_checks(
    tmp_path, monkeypatch, change,
):
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.models import PlanActivationState, TradingCalendar

    env = _current_status(tmp_path, monkeypatch)
    seed(env.sessions, env.now)
    entered, release = hold_first(monkeypatch)

    async def scenario():
        first = asyncio.create_task(env.reader.get_dashboard())
        await until(entered.is_set)
        with env.sessions.begin() as session:
            if change == "inventory":
                session.delete(session.get(DailyRecord, "simulation-position-" + env.plan.symbol))
            elif change == "calendar":
                session.get(TradingCalendar, (env.plan.market, TARGET.date())).is_open = False
            elif change == "activation":
                session.get(PlanActivationState, env.plan.symbol).revision += 1
            else:
                record = session.get(DailyRecord, "evaluation-head-" + env.plan.symbol)
                session.delete(record)
        second = asyncio.create_task(env.reader.get_dashboard())
        try:
            if change == "activation":
                await until(second.done)
            else:
                await until(lambda: env.reader._index_verifier.snapshot()["joins"] == 1)
        finally:
            release.set()
        a, b = await asyncio.gather(first, second, return_exceptions=True)
        if change == "activation":
            assert isinstance(a, ApiError) and isinstance(b, ApiError)
        else:
            assert a.symbols[0].current_actionable
            assert not b.symbols[0].current_actionable and b.symbols[0].scope.read_only
        await env.reader.stop()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        env.close()
