"""An already-started provider call must not erase a still-fresh market target."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_production_certification_gate import _composition

from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.models import (
    AlertEvent,
    EvaluationResult,
    SymbolHealth,
    SymbolHealthProjection,
)


async def _until(predicate) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=5)


def _release_through(clock, final_due):
    """Allow real scheduler duties through the crossing trigger, then freeze time."""
    parked = asyncio.Event()

    async def sleep_until(deadline):
        clock.sleep_calls.append(deadline)
        if deadline <= final_due:
            assert len(clock.sleep_calls) <= 10, "scheduler failed to reach crossing trigger"
            clock.current = max(clock.current, deadline)
            await asyncio.sleep(0)
            return
        parked.set()
        await asyncio.Event().wait()

    clock.sleep_until = sleep_until
    return parked


def test_runtime_run_consumes_still_fresh_market_target_after_sdk_crosses_due(
    tmp_path, monkeypatch,
) -> None:
    async def scenario() -> None:
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, include_index=False,
            stock_certification=True, persisted_calendar=True,
        )
        runtime = composition._runtime
        first_due = datetime(2026, 9, 8, 10, 4, 12, tzinfo=SHANGHAI)
        crossed_due = datetime(2026, 9, 8, 10, 5, 12, tzinfo=SHANGHAI)
        observed: list[tuple[MarketDeadline, object, object]] = []
        completed: list[MarketDeadline] = []
        crossed_in_sdk = False
        health_revision_after_first: int | None = None
        try:
            parked = _release_through(runtime._clock, first_due)
            original_minutes = sdk._stock_minutes

            def cross_due_in_started_sdk(name, kwargs):
                nonlocal crossed_in_sdk
                if (
                    name == "rt_min" and runtime._clock.now() == first_due
                    and not crossed_in_sdk
                ):
                    crossed_in_sdk = True
                    runtime._clock.current = crossed_due.replace(second=13)
                return original_minutes(name, kwargs)

            sdk._stock_minutes = cross_due_in_started_sdk
            original_run = runtime._run_deadline

            async def capture(deadline: MarketDeadline):
                nonlocal health_revision_after_first
                observed.append((deadline, runtime.health().runtime_generation,
                                 runtime._schedule_owner))
                result = await original_run(deadline)
                completed.append(deadline)
                if deadline.due_at == first_due:
                    state = runtime._probe_capabilities.__self__
                    with state._session_factory() as session:
                        health_revision_after_first = session.scalar(
                            select(SymbolHealthProjection.revision)
                        )
                return result

            runtime._run_deadline = capture
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            generation = runtime.health().runtime_generation
            await _until(lambda: crossed_in_sdk and any(
                deadline.due_at == crossed_due for deadline in completed
            ) and parked.is_set())

            assert all(deadline.kind in {DeadlineKind.REALTIME_MINUTE, DeadlineKind.STOCK_RECOVERY}
                       for deadline, _, _ in observed)
            market = [deadline.due_at for deadline, _, _ in observed
                      if deadline.kind is DeadlineKind.REALTIME_MINUTE]
            assert market == [first_due + timedelta(minutes=offset) for offset in range(-3, 2)]
            assert runtime._clock.now() == crossed_due.replace(second=13)
            assert generation == runtime.health().runtime_generation
            assert all(item_generation == generation for _, item_generation, _ in observed)
            assert all(owner is composition._runner_task for _, _, owner in observed)

            state = runtime._probe_capabilities.__self__
            with state._session_factory() as session:
                projection = session.scalar(select(SymbolHealthProjection))
                health = session.scalar(select(SymbolHealth))
                assert health_revision_after_first is not None
                assert projection is not None
                assert projection.revision > health_revision_after_first
                assert projection.runtime_generation == str(generation)
                assert health is not None and health.status == "GAPPED"
                assert "2026-09-08T10:04:00+08:00" in health.gap_json
                assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "clock_after_handler",
    (
        datetime(2026, 9, 8, 10, 4, 11, tzinfo=SHANGHAI),
        datetime(2026, 9, 11, 10, 4, 13, tzinfo=SHANGHAI),
    ),
    ids=("clock-rollback", "beyond-two-day-review"),
)
def test_invalid_elapsed_review_stays_read_only_and_visible_without_runner_exit(
    tmp_path, monkeypatch, clock_after_handler: datetime,
) -> None:
    async def scenario() -> None:
        composition, _, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, include_index=False,
            stock_certification=True, persisted_calendar=True,
        )
        runtime = composition._runtime
        first_due = datetime(2026, 9, 8, 10, 4, 12, tzinfo=SHANGHAI)
        _release_through(runtime._clock, first_due)
        original_run = runtime._run_deadline
        changed = False
        observed = []

        async def jump_after_handler(deadline: MarketDeadline):
            nonlocal changed
            observed.append((deadline, runtime.runtime_generation, runtime._schedule_owner))
            result = await original_run(deadline)
            if deadline.due_at == first_due:
                runtime._clock.current = clock_after_handler
                changed = True
            return result

        runtime._run_deadline = jump_after_handler
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            generation = runtime.runtime_generation
            await _until(lambda: changed)
            await _until(lambda: (
                composition._runner_task.done()
                or composition.health().status is RuntimeServiceStatus.DEGRADED
            ))
            health = composition.health()
            assert health.status is RuntimeServiceStatus.DEGRADED
            assert health.read_only is True
            assert health.degraded_reason == "MARKET_DEADLINE_REVIEW_UNAVAILABLE"
            assert health.next_poll_at is None
            assert health.next_retry_at is None
            assert not composition._runner_task.done()
            assert runtime._last_deadline_at == first_due
            assert runtime.runtime_generation == generation
            assert all(item_generation == generation and owner is composition._runner_task
                       for _, item_generation, owner in observed)
            assert [deadline.due_at for deadline, _, _ in observed
                    if deadline.kind is DeadlineKind.REALTIME_MINUTE] == [
                first_due + timedelta(minutes=offset) for offset in range(-3, 1)
            ]
            with runtime._probe_capabilities.__self__._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
                assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())
