"""Deterministic ownership and wake tests for the injected recovery loop."""

import asyncio
from datetime import datetime, timedelta
from functools import wraps

import pytest

from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.reconciliation import (
    RecoveryCoordinator,
    RecoveryDisposition,
    RecoveryRequirement,
    RecoveryStepResult,
)

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=SHANGHAI)


def run_async(scenario):
    @wraps(scenario)
    def test():
        asyncio.run(scenario())
    return test


class ManualClock:
    def __init__(self):
        self.current = NOW
        self.sleeping = asyncio.Queue()
        self.advance = asyncio.Event()

    def now(self):
        return self.current

    async def sleep_until(self, deadline):
        await self.sleeping.put(deadline)
        await self.advance.wait()
        self.advance.clear()


@run_async
async def test_unknown_calendar_keeps_local_maintenance_alive_without_provider_calls():
    clock = ManualClock()
    stop = asyncio.Event()
    observations = []

    def requirements(now):
        observations.append(now)
        return ()

    async def execute(ticket):
        pytest.fail("empty local work must never probe the provider")

    coordinator = RecoveryCoordinator(clock=clock, requirements=requirements, execute=execute)
    task = asyncio.create_task(coordinator.run(stop=stop))
    assert await asyncio.wait_for(clock.sleeping.get(), 1) == NOW + timedelta(seconds=30)
    clock.current += timedelta(seconds=30)
    clock.advance.set()
    assert await asyncio.wait_for(clock.sleeping.get(), 1) == NOW + timedelta(seconds=60)
    stop.set()
    await asyncio.wait_for(task, 1)
    assert observations == [NOW, NOW + timedelta(seconds=30)]
    assert not coordinator.running


@run_async
async def test_retry_scope_does_not_starve_ready_sibling_or_spin_before_retry():
    clock = ManualClock()
    stop = asyncio.Event()
    attempted = []

    async def execute(ticket):
        attempted.append(ticket.requirement.scope_key)
        if ticket.requirement.scope_key == "stock":
            return RecoveryStepResult.retry(NOW + timedelta(seconds=60))
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (
            RecoveryRequirement("stock", "r1"), RecoveryRequirement("index", "r1")
        ),
        execute=execute,
    )
    task = asyncio.create_task(coordinator.run(stop=stop))
    await asyncio.wait_for(clock.sleeping.get(), 1)
    assert attempted == ["stock", "index"]
    assert [item.disposition for item in coordinator.snapshot()] == [
        RecoveryDisposition.RETRY, RecoveryDisposition.READY
    ]
    stop.set()
    await asyncio.wait_for(task, 1)


@run_async
async def test_requirements_changed_during_work_fence_old_ready_result():
    clock = ManualClock()
    stop = asyncio.Event()
    revision = "old"
    attempted = []

    async def execute(ticket):
        nonlocal revision
        attempted.append(ticket.requirement.revision)
        revision = "new"
        if len(attempted) == 2:
            stop.set()
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (RecoveryRequirement("stock", revision),),
        execute=execute,
    )
    await asyncio.wait_for(coordinator.run(stop=stop), 1)
    assert attempted == ["old", "new"]


@run_async
async def test_local_change_wakes_standby_and_no_parallel_run_owner():
    clock = ManualClock()
    stop = asyncio.Event()
    active = False

    async def execute(ticket):
        stop.set()
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (RecoveryRequirement("stock", "r1"),) if active else (),
        execute=execute,
    )
    task = asyncio.create_task(coordinator.run(stop=stop))
    await asyncio.wait_for(clock.sleeping.get(), 1)
    with pytest.raises(RuntimeError, match="owner"):
        await coordinator.run(stop=stop)
    active = True
    coordinator.wake()
    await asyncio.wait_for(task, 1)
    assert coordinator.snapshot()[0].disposition is RecoveryDisposition.READY


@run_async
async def test_stop_during_owned_work_joins_before_exit_and_admits_no_sibling():
    clock = ManualClock()
    stop = asyncio.Event()
    started, release = asyncio.Event(), asyncio.Event()
    attempted = []

    async def execute(ticket):
        attempted.append(ticket.requirement.scope_key)
        started.set()
        await release.wait()
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (
            RecoveryRequirement("one", "r1"), RecoveryRequirement("two", "r1")
        ),
        execute=execute,
    )
    task = asyncio.create_task(coordinator.run(stop=stop))
    await asyncio.wait_for(started.wait(), 1)
    stop.set()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    await asyncio.wait_for(task, 1)
    assert attempted == ["one"]


@run_async
async def test_programming_error_propagates_and_coordinator_cannot_be_reused():
    clock = ManualClock()

    async def execute(ticket):
        raise RuntimeError("unexpected defect")

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (RecoveryRequirement("one", "r1"),),
        execute=execute,
    )
    with pytest.raises(RuntimeError, match="unexpected defect"):
        await coordinator.run(stop=asyncio.Event())
    assert not coordinator.running
    with pytest.raises(RuntimeError, match="owner"):
        await coordinator.run(stop=asyncio.Event())


@run_async
async def test_wait_has_monotonic_ceiling_even_if_wall_clock_rolls_back():
    clock = ManualClock()
    stop = asyncio.Event()

    async def bounded_wait(tasks, *, return_when, timeout=None):
        assert timeout == 30
        clock.current -= timedelta(days=1)
        stop.set()
        return set(), set(tasks)

    async def execute(ticket):
        pytest.fail("no work")

    coordinator = RecoveryCoordinator(clock=clock, requirements=lambda now: (), execute=execute)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(asyncio, "wait", bounded_wait)
        await coordinator.run(stop=stop)
    assert len(asyncio.all_tasks()) == 1


@run_async
async def test_immediate_units_yield_to_stop_task_before_next_admission():
    clock = ManualClock()
    stop = asyncio.Event()
    attempted = []

    async def execute(ticket):
        attempted.append(ticket.requirement.scope_key)
        asyncio.get_running_loop().call_soon(stop.set)
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (
            RecoveryRequirement("one", "r1"), RecoveryRequirement("two", "r1")
        ),
        execute=execute,
    )
    await asyncio.wait_for(coordinator.run(stop=stop), 1)
    assert attempted == ["one"]


@run_async
async def test_cancellation_joins_wait_helpers_and_disallows_reuse():
    clock = ManualClock()

    async def execute(ticket):
        pytest.fail("no work")

    coordinator = RecoveryCoordinator(clock=clock, requirements=lambda now: (), execute=execute)
    task = asyncio.create_task(coordinator.run(stop=asyncio.Event()))
    await asyncio.wait_for(clock.sleeping.get(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(asyncio.all_tasks()) == 1
    with pytest.raises(RuntimeError, match="owner"):
        await coordinator.run(stop=asyncio.Event())


@run_async
async def test_blocked_configuration_change_is_reconciled_from_wake_during_step():
    clock = ManualClock()
    stop = asyncio.Event()
    revision = "missing-credentials"
    attempted = []

    async def execute(ticket):
        nonlocal revision
        attempted.append(ticket.requirement.revision)
        if len(attempted) == 1:
            revision = "credentials-present"
            coordinator.wake()
            return RecoveryStepResult.blocked()
        stop.set()
        return RecoveryStepResult.ready()

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (RecoveryRequirement("stock", revision),),
        execute=execute,
    )
    await asyncio.wait_for(coordinator.run(stop=stop), 1)
    assert attempted == ["missing-credentials", "credentials-present"]


@run_async
async def test_invalid_nonprogress_results_fail_instead_of_busy_loop():
    async def execute(ticket):
        return RecoveryStepResult(RecoveryDisposition.PENDING)

    coordinator = RecoveryCoordinator(
        clock=ManualClock(),
        requirements=lambda now: (RecoveryRequirement("stock", "r1"),),
        execute=execute,
    )
    with pytest.raises(ValueError):
        await coordinator.run(stop=asyncio.Event())


@run_async
async def test_clock_forward_during_retry_defers_to_maintenance_without_crashing_or_spinning():
    clock = ManualClock()
    stop = asyncio.Event()
    attempted = []

    async def execute(ticket):
        attempted.append(ticket)
        retry_at = clock.now() + timedelta(seconds=30)
        clock.current += timedelta(hours=1)
        return RecoveryStepResult.retry(retry_at)

    coordinator = RecoveryCoordinator(
        clock=clock,
        requirements=lambda now: (RecoveryRequirement("stock", str(now.date())),),
        execute=execute,
    )
    task = asyncio.create_task(coordinator.run(stop=stop))
    try:
        deadline = await asyncio.wait_for(clock.sleeping.get(), 1)
        assert deadline == clock.now() + timedelta(seconds=30)
        assert len(attempted) == 1
    finally:
        stop.set()
        await asyncio.wait_for(task, 1)
