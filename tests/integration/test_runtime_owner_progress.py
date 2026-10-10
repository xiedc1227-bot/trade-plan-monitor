"""Offline lifecycle evidence: reads and physical ownership are independent."""

import asyncio
from datetime import datetime, timedelta

import pytest

from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.scheduler import (
    DeadlineKind,
    MarketDeadline,
    MarketSessionScheduler,
)
from trade_plan_monitor.runtime.service import RuntimeLifecycleService, _RetryWaitOutcome


class Clock:
    wall = datetime(2026, 9, 27, 12, tzinfo=SHANGHAI)
    tick = 100.0

    def now(self):
        return self.wall

    async def sleep_until(self, deadline):
        await asyncio.Event().wait()


class Scheduler:
    def next_deadline(self, *, after=None):
        return None

    async def wait_for_next(self, *, after=None):
        return None


class Resources:
    def close(self):
        pass

    async def aclose(self):
        pass


def service(
    clock, *, enabled=True, validate=None, dispatcher=None, scheduler=None,
    configuration_restart_required=None,
    retry_wait=None, retry_interval_seconds=30,
    run_deadline=None,
):
    ready = ProviderCapabilityStatus.READY
    return RuntimeLifecycleService(
        clock=clock, validate_configuration=validate or (lambda: None),
        configuration_restart_required=configuration_restart_required,
        open_database=lambda: None, load_active_symbols=lambda: (),
        probe_capabilities=lambda: ProviderCapabilities(
            realtime_minutes=ready, current_day_minutes=ready, trading_calendar=ready,
            daily_limits=ready, daily_bars=ready,
        ),
        refresh_references=lambda _: None, recover_startup=lambda _: None,
        scheduler=scheduler or Scheduler(), run_deadline=run_deadline or (lambda _: None),
        dispatcher=dispatcher or Resources(), request_controller=Resources(),
        checkpoint_wal=lambda: None, close_database=lambda: None,
        health_details=lambda: None,
        progress_monotonic=(lambda: clock.tick) if enabled else None,
        retry_wait=retry_wait, retry_interval_seconds=retry_interval_seconds,
    )


def test_default_has_no_progress_authority_and_opt_in_shares_generation():
    clock = Clock()
    assert service(clock, enabled=False).progress_snapshot() is None
    owner = service(clock)
    snapshot = owner.progress_snapshot()
    assert snapshot.runtime_generation == owner.runtime_generation
    assert snapshot.state == "STARTING"
    assert snapshot.last_progress_at is None


def test_only_owner_task_can_report_completed_bounded_work():
    async def scenario():
        clock = Clock()

        def validate():
            token = owner.begin_progress_step(timeout_seconds=15)
            assert owner.progress_snapshot().last_progress_at is None
            clock.tick += 2
            assert owner.complete_progress_step(token, next_wake_at=clock.wall)

        owner = service(clock, validate=validate)
        await owner.start()
        snapshot = owner.progress_snapshot()
        assert snapshot.last_progress_at == clock.wall
        with pytest.raises(RuntimeError, match="owner task"):
            owner.begin_progress_step(timeout_seconds=15)
        clock.tick += 1
        assert owner.progress_snapshot().state == "STALLED"
        assert owner.progress_snapshot().last_progress_at == snapshot.last_progress_at
        await owner.stop()

    asyncio.run(scenario())


def test_local_validation_unit_only_completes_after_actual_return():
    async def scenario():
        clock = Clock()
        entered, release = asyncio.Event(), asyncio.Event()

        async def local_validation():
            entered.set()
            await release.wait()

        async def validate():
            await owner.run_local_progress_unit(local_validation)

        owner = service(clock, validate=validate)
        starting = asyncio.create_task(owner.start())
        await asyncio.wait_for(entered.wait(), 1)
        assert owner.progress_snapshot().state == "WORKING"
        assert owner.progress_snapshot().last_progress_at is None
        clock.tick += 31
        assert owner.progress_snapshot().state == "STALLED"
        release.set()
        await starting
        assert owner.progress_snapshot().last_progress_at == clock.wall
        await owner.stop()

    asyncio.run(scenario())


def test_scheduled_wait_rechecks_installed_identity_without_provider_calls():
    async def scenario():
        sleeping = asyncio.Queue()
        resume = asyncio.Queue()

        class ControlledClock(Clock):
            async def sleep_until(self, deadline):
                await sleeping.put(deadline)
                await resume.get()
                self.tick += (deadline - self.wall).total_seconds()
                self.wall = deadline

        clock = ControlledClock()
        initial = clock.wall
        checks = []
        deadline = MarketDeadline(
            kind=DeadlineKind.REALTIME_MINUTE, trade_date=initial.date(),
            bar_end=initial + timedelta(minutes=2),
            due_at=initial + timedelta(minutes=2, seconds=12),
        )

        class FutureScheduler(Scheduler):
            def next_deadline(self, *, after=None):
                return deadline

        def validate():
            token = owner.begin_progress_step(timeout_seconds=15)
            owner.complete_progress_step(token, next_wake_at=clock.wall)

        owner = service(
            clock, validate=validate, scheduler=FutureScheduler(),
            configuration_restart_required=lambda: checks.append(clock.wall) or False,
        )
        running = asyncio.create_task(owner.run())
        assert await asyncio.wait_for(sleeping.get(), 1) == initial + timedelta(seconds=30)
        first = owner.progress_snapshot()
        assert first.state == "SCHEDULED"
        assert first.last_progress_at == initial
        await resume.put(None)
        assert await asyncio.wait_for(sleeping.get(), 1) == initial + timedelta(seconds=60)
        second = owner.progress_snapshot()
        assert second.last_progress_at == initial + timedelta(seconds=30)
        assert second.next_wake_at == initial + timedelta(seconds=60)
        assert second.last_progress_at in checks
        await owner.stop()
        await running

    asyncio.run(scenario())


def test_local_wake_preserves_due_market_unit_when_clock_crosses_deadline():
    async def scenario():
        sleeps, resumes = asyncio.Queue(), asyncio.Queue()
        completed = asyncio.Event()
        dispatched = []

        class ControlledClock(Clock):
            wall = datetime(2026, 9, 14, 10, 4, 15, tzinfo=SHANGHAI)

            async def sleep_until(self, deadline):
                await sleeps.put(deadline)
                await resumes.get()

        clock = ControlledClock()

        def validate():
            token = owner.begin_progress_step(timeout_seconds=15)
            owner.complete_progress_step(token, next_wake_at=clock.wall)

        def run_deadline(deadline):
            dispatched.append(deadline)
            token = owner.begin_progress_step(timeout_seconds=30)
            owner.complete_progress_step(token, next_wake_at=clock.wall)
            completed.set()

        owner = service(
            clock, validate=validate,
            scheduler=MarketSessionScheduler(clock=clock, is_open_on=lambda _day: True),
            run_deadline=run_deadline,
        )
        running = asyncio.create_task(owner.run())
        try:
            wake = await asyncio.wait_for(sleeps.get(), 1)
            assert wake == clock.wall + timedelta(seconds=30)
            clock.wall += timedelta(minutes=1)
            clock.tick += 60
            await resumes.put(None)
            await asyncio.wait_for(completed.wait(), 1)
            assert dispatched[0].bar_end == clock.wall.replace(second=0)
            assert dispatched[0].due_at == clock.wall.replace(second=12)
        finally:
            await owner.stop()
            await running

    asyncio.run(scenario())


def test_due_market_unit_dispatches_when_wall_clock_advances_between_reads():
    async def scenario():
        class AdvancingClock(Clock):
            wall = datetime(2026, 9, 14, 10, 4, 15, tzinfo=SHANGHAI)

            def now(self):
                value = self.wall
                self.wall += timedelta(microseconds=1)
                self.tick += 0.000001
                return value

            async def sleep_until(self, deadline):
                self.tick += max(0, (deadline - self.wall).total_seconds())
                self.wall = max(self.wall, deadline) + timedelta(microseconds=1)
                await asyncio.sleep(0)

        clock = AdvancingClock()
        completed = asyncio.Event()
        dispatched = []

        def validate():
            token = owner.begin_progress_step(timeout_seconds=15)
            owner.complete_progress_step(
                token, next_wake_at=clock.now() + timedelta(seconds=30),
            )

        def run_deadline(deadline):
            dispatched.append(deadline)
            token = owner.begin_progress_step(timeout_seconds=30)
            owner.complete_progress_step(
                token, next_wake_at=clock.now() + timedelta(seconds=30),
            )
            completed.set()

        owner = service(
            clock, validate=validate,
            scheduler=MarketSessionScheduler(clock=clock, is_open_on=lambda _day: True),
            run_deadline=run_deadline,
        )
        running = asyncio.create_task(owner.run())
        try:
            await asyncio.wait_for(completed.wait(), 1)
            assert dispatched[0].bar_end == datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
            assert owner.status.value == "RUNNING"
        finally:
            await owner.stop()
            await running

    asyncio.run(scenario())


def test_stop_evidence_waits_for_physical_cleanup_and_failed_cleanup_is_not_stopped():
    async def scenario():
        clock = Clock()
        draining = asyncio.Event()
        release = asyncio.Event()

        class Drain(Resources):
            async def aclose(self):
                draining.set()
                await release.wait()
                raise RuntimeError("physical drain failed")

        owner = service(clock, dispatcher=Drain())
        await owner.start()
        stopping = asyncio.create_task(owner.stop())
        await draining.wait()
        assert owner.progress_snapshot().state != "STOPPED"
        release.set()
        with pytest.raises(RuntimeError, match="physical drain failed"):
            await stopping
        assert owner.progress_snapshot().state != "STOPPED"

        owner = service(clock)
        await owner.start()
        await owner.stop()
        assert owner.progress_snapshot().state == "STOPPED"

    asyncio.run(scenario())


@pytest.mark.parametrize("bootstrap_completed", [True, False])
def test_backoff_maintenance_requires_genuine_bootstrap_and_does_not_retry_provider(
    bootstrap_completed,
):
    async def scenario():
        clock = Clock()
        waits = asyncio.Queue()
        validations = []

        async def wait(shutdown, delay):
            await waits.put(delay)
            await shutdown.wait()
            return _RetryWaitOutcome.SHUTDOWN

        def validate():
            validations.append(True)
            if bootstrap_completed:
                token = owner.begin_progress_step(timeout_seconds=15)
                owner.complete_progress_step(token, next_wake_at=clock.wall)

        owner = service(
            clock, validate=validate, retry_wait=wait, retry_interval_seconds=300,
        )
        running = asyncio.create_task(owner.run())
        delay = await asyncio.wait_for(waits.get(), 1)
        assert delay == (30 if bootstrap_completed else 300)
        snapshot = owner.progress_snapshot()
        assert snapshot.state == ("SCHEDULED" if bootstrap_completed else "STARTING")
        assert validations == [True]
        await owner.stop()
        await running

    asyncio.run(scenario())
