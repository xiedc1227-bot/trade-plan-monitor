"""HTTP cancellation is not physical monitor-read completion."""

import asyncio
from datetime import datetime
from threading import Event, get_ident
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.index_evidence_flights import EvidenceUnavailable
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.monitor_read_ownership import MonitorReadOwner
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


def test_cancelled_read_stays_owned_until_physical_drain(caplog):
    async def scenario():
        entered, release = Event(), Event()
        authority = RuntimeReadAuthority(
            token="owner", lifecycle="STOPPED", progress=None, health=None, owner_absent=True,
        )
        reader = RuntimeStatusReadService(
            None, lambda: authority,
            clock=lambda: datetime(2026, 10, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        def assemble(*args):
            entered.set()
            assert release.wait(3)
            return ("result", {}, (), authority), ()

        reader._assemble = assemble
        reader._identities = lambda: ()
        task = asyncio.create_task(reader._read())
        while not entered.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader.outstanding_work == 1
        with pytest.raises(TimeoutError):
            await reader.stop(timeout=0.01)
        assert reader.outstanding_work == 1
        with pytest.raises(ApiError):
            await reader._read()
        release.set()
        await reader.stop(timeout=1)
        assert reader.outstanding_work == 0

    asyncio.run(scenario())
    assert not [r for r in caplog.records if r.name == "asyncio" and r.levelno >= 40]


def test_storage_resume_releases_only_its_own_pause_and_never_permanent_close():
    async def scenario():
        owner = MonitorReadOwner()

        async def operation():
            return "fresh"

        owner.pause_storage("old")
        owner.pause_storage("new")
        owner.resume_storage("old")
        with pytest.raises(EvidenceUnavailable):
            await owner.run(operation)
        owner.resume_storage("new")
        assert await owner.run(operation) == "fresh"
        owner.begin_shutdown()
        owner.resume_storage("old")
        with pytest.raises(EvidenceUnavailable):
            await owner.run(operation)
        await owner.stop(timeout=1)

    asyncio.run(scenario())


def test_all_cancelled_observers_still_consume_eight_physical_admissions():
    async def scenario():
        owner = MonitorReadOwner()
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0

        async def operation():
            nonlocal count
            count += 1
            if count == 8:
                entered.set()
            await release.wait()

        tasks = [asyncio.create_task(owner.run(operation)) for _ in range(8)]
        await asyncio.wait_for(entered.wait(), timeout=1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert owner.outstanding_work == 8
        with pytest.raises(EvidenceUnavailable):
            await owner.run(operation)
        with pytest.raises(TimeoutError):
            await owner.stop(timeout=0.01)
        assert owner.outstanding_work == 8
        release.set()
        await owner.stop(timeout=1)
        assert owner.outstanding_work == 0

    asyncio.run(scenario())


def test_each_reader_keeps_its_own_owner_loop_checks_and_two_attempt_budget():
    async def scenario():
        loop_thread, calls = get_ident(), []

        def authority():
            assert get_ident() == loop_thread
            calls.append(len(calls))
            return RuntimeReadAuthority(
                token=len(calls), lifecycle="STOPPED", progress=None, health=None,
                owner_absent=True,
            )

        reader = RuntimeStatusReadService(
            None, authority,
            clock=lambda: datetime(2026, 10, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        reader._assemble = lambda owner, now: (("result", {}, (), owner), ())
        reader._identities = lambda: ()
        with pytest.raises(ApiError):
            await reader._read()
        assert len(calls) == 4
        await reader.stop()

    asyncio.run(scenario())
