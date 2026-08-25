import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import (
    DatabaseHealthSnapshot,
    DeliveryHealthSnapshot,
    ExecutorHealthSnapshot,
    ProviderHealthSnapshot,
    RuntimeGapSnapshot,
    RuntimeHealthDetails,
    RuntimeHealthSnapshot,
    RuntimeResourceStatus,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import (
    ActiveSymbolLimitError,
    MaintenanceCommandService,
    RuntimeLifecycleService,
    RuntimeShutdownError,
)


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 24, hour, minute, second, tzinfo=SHANGHAI)


def _deadline() -> MarketDeadline:
    return MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=date(2026, 8, 24),
        bar_end=_at(9, 31),
        due_at=_at(9, 31, 12),
    )


def _ready_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        realtime_minutes=ProviderCapabilityStatus.READY,
        current_day_minutes=ProviderCapabilityStatus.READY,
        trading_calendar=ProviderCapabilityStatus.READY,
        daily_limits=ProviderCapabilityStatus.READY,
        daily_bars=ProviderCapabilityStatus.READY,
    )


def _healthy_runtime_details() -> RuntimeHealthDetails:
    return RuntimeHealthDetails(
        last_completed_minute=None,
        latest_evaluation_at=None,
        gaps=(),
        next_retry_at=None,
        cooldown_until=None,
        providers=(),
        executor=ExecutorHealthSnapshot(max_workers=2, active_count=0, waiting_count=0),
        database=DatabaseHealthSnapshot(
            status=RuntimeResourceStatus.READY,
            wal_status=RuntimeResourceStatus.READY,
        ),
        delivery=DeliveryHealthSnapshot(
            status=RuntimeResourceStatus.READY,
            pending_count=0,
            failed_count=0,
        ),
    )


@dataclass
class _Clock:
    current: datetime = field(default_factory=lambda: _at(9, 30))

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.current = deadline


@dataclass
class _Scheduler:
    deadline: MarketDeadline | None = field(default_factory=_deadline)
    wait_started: asyncio.Event | None = None
    wait_cancelled: bool = False
    calls: int = 0

    def next_deadline(self, *, after: datetime | None = None) -> MarketDeadline | None:
        if after is not None:
            return None
        return self.deadline

    async def wait_for_next(self, *, after: datetime | None = None) -> MarketDeadline | None:
        self.calls += 1
        if self.calls == 1 and after is None:
            return self.deadline
        if self.wait_started is not None:
            self.wait_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.wait_cancelled = True
            raise
        return None


@dataclass
class _AsyncCloser:
    events: list[str]

    async def aclose(self) -> None:
        self.events.append("dispatcher-close")


@dataclass
class _SyncCloser:
    events: list[str]

    def close(self) -> None:
        self.events.append("controller-close")


def _service(
    *,
    symbols: tuple[str, ...] = ("600000.SH",),
    capabilities: ProviderCapabilities | None = None,
    events: list[str] | None = None,
    scheduler: _Scheduler | None = None,
    run_deadline: Callable[[MarketDeadline], Awaitable[object]] | None = None,
    open_database: Callable[[], object] | None = None,
    close_database: Callable[[], object] | None = None,
    refresh_references: Callable[[date], object] | None = None,
    health_details: Callable[[], RuntimeHealthDetails] = _healthy_runtime_details,
    shutdown_timeout_seconds: float = 0.05,
) -> RuntimeLifecycleService:
    observed = events if events is not None else []

    async def record_deadline(_deadline: MarketDeadline) -> None:
        observed.append("deadline")

    async def recover_startup(_trade_date: date) -> None:
        observed.append("recover")

    return RuntimeLifecycleService(
        clock=_Clock(),
        validate_configuration=lambda: observed.append("config"),
        open_database=(
            open_database if open_database is not None else lambda: observed.append("database")
        ),
        load_active_symbols=lambda: (observed.append("plans"), symbols)[1],
        probe_capabilities=lambda: (
            observed.append("probe"),
            capabilities if capabilities is not None else _ready_capabilities(),
        )[1],
        refresh_references=(
            refresh_references
            if refresh_references is not None
            else lambda _trade_date: observed.append("references")
        ),
        recover_startup=recover_startup,
        scheduler=scheduler if scheduler is not None else _Scheduler(),
        run_deadline=run_deadline if run_deadline is not None else record_deadline,
        dispatcher=_AsyncCloser(observed),
        request_controller=_SyncCloser(observed),
        checkpoint_wal=lambda: observed.append("wal-checkpoint"),
        close_database=(
            close_database
            if close_database is not None
            else lambda: observed.append("database-close")
        ),
        health_details=health_details,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def test_startup_owns_the_required_sequence_and_accepts_exactly_ten_symbols() -> None:
    events: list[str] = []
    symbols = tuple(f"60000{index}.SH" for index in range(10))
    service = _service(symbols=symbols, events=events)

    result = asyncio.run(service.start())

    assert events == ["config", "database", "plans", "probe", "references", "recover"]
    assert result.active_symbols == symbols
    assert result.status is RuntimeServiceStatus.RUNNING
    assert result.read_only is False
    assert result.next_poll_at == _deadline().due_at
    asyncio.run(service.stop())


def test_startup_rejects_more_than_ten_symbols_before_provider_work() -> None:
    events: list[str] = []
    symbols = tuple(f"6000{index:02d}.SH" for index in range(11))
    service = _service(symbols=symbols, events=events)

    with pytest.raises(ActiveSymbolLimitError, match="at most 10"):
        asyncio.run(service.start())

    assert events == [
        "config",
        "database",
        "plans",
        "dispatcher-close",
        "controller-close",
        "wal-checkpoint",
        "database-close",
    ]


def test_blocked_capability_starts_degraded_read_only_and_suppresses_work() -> None:
    events: list[str] = []
    capabilities = _ready_capabilities().model_copy(
        update={"realtime_minutes": ProviderCapabilityStatus.BLOCKED_PERMISSION}
    )
    service = _service(capabilities=capabilities, events=events)

    result = asyncio.run(service.start())

    assert events == ["config", "database", "plans", "probe", "references", "recover"]
    assert result.status is RuntimeServiceStatus.DEGRADED
    assert result.read_only is True
    assert result.next_poll_at is None
    assert asyncio.run(service.run_once()) is None
    assert "deadline" not in events
    asyncio.run(service.stop())


def test_reference_failure_does_not_skip_independent_startup_recovery() -> None:
    events: list[str] = []

    def fail_references(_trade_date: date) -> None:
        events.append("references")
        raise RuntimeError("unavailable")

    service = _service(events=events, refresh_references=fail_references)

    result = asyncio.run(service.start())

    assert events == ["config", "database", "plans", "probe", "references", "recover"]
    assert result.status is RuntimeServiceStatus.DEGRADED
    assert result.read_only is True
    asyncio.run(service.stop())


def test_unknown_next_deadline_starts_degraded_instead_of_claiming_running() -> None:
    service = _service(scheduler=_Scheduler(deadline=None))

    result = asyncio.run(service.start())

    assert result.status is RuntimeServiceStatus.DEGRADED
    assert result.read_only is True
    assert result.next_poll_at is None
    asyncio.run(service.stop())


def test_runtime_health_exposes_sanitized_operational_facts_and_exact_ages() -> None:
    observed_at = _at(10, 0)
    last_minute = _at(9, 59)
    latest_evaluation = _at(9, 55)
    snapshot = RuntimeHealthSnapshot(
        status=RuntimeServiceStatus.DEGRADED,
        read_only=True,
        observed_at=observed_at,
        started_at=_at(9, 0),
        stopped_at=None,
        last_completed_minute=last_minute,
        last_completed_minute_age_seconds=60,
        latest_evaluation_at=latest_evaluation,
        latest_evaluation_age_seconds=300,
        gaps=(RuntimeGapSnapshot(symbol="600000.SH", bar_end=_at(9, 58)),),
        next_poll_at=_at(10, 0, 12),
        next_retry_at=_at(10, 1),
        cooldown_until=_at(10, 5),
        providers=(
            ProviderHealthSnapshot(
                capability="realtime_minutes",
                status=ProviderCapabilityStatus.RATE_LIMITED,
                checked_at=_at(9, 59),
                latency_ms=125,
                error_code="RATE_LIMITED",
                next_retry_at=_at(10, 1),
            ),
        ),
        executor=ExecutorHealthSnapshot(max_workers=2, active_count=1, waiting_count=3),
        database=DatabaseHealthSnapshot(
            status=RuntimeResourceStatus.READY,
            wal_status=RuntimeResourceStatus.READY,
            last_checkpoint_at=_at(9, 50),
            last_backup_at=_at(8, 0),
            error_code=None,
        ),
        delivery=DeliveryHealthSnapshot(
            status=RuntimeResourceStatus.DEGRADED,
            pending_count=2,
            failed_count=1,
            last_delivered_at=_at(9, 54),
            next_retry_at=_at(10, 1),
            error_code="WEBHOOK_TRANSIENT",
        ),
    )

    payload = snapshot.model_dump_json()

    assert snapshot.last_completed_minute_age_seconds == 60
    assert snapshot.latest_evaluation_age_seconds == 300
    assert snapshot.gaps[0].bar_end == _at(9, 58)
    assert snapshot.cooldown_until == _at(10, 5)
    assert snapshot.executor.model_dump() == {
        "max_workers": 2,
        "active_count": 1,
        "waiting_count": 3,
    }
    assert snapshot.database.wal_status is RuntimeResourceStatus.READY
    assert snapshot.delivery.pending_count == 2
    assert "secret-value" not in payload
    assert "raw_provider_body" not in payload

    invalid = {**snapshot.model_dump(mode="python"), "raw_provider_body": "secret-value"}
    validators = (
        lambda: RuntimeHealthSnapshot(**invalid),
        lambda: RuntimeHealthSnapshot.model_validate(invalid),
        lambda: RuntimeHealthSnapshot.model_validate_json(
            RuntimeHealthSnapshot.model_validate(snapshot).model_dump_json(exclude_none=False)[:-1]
            + ',"raw_provider_body":"secret-value"}'
        ),
    )
    for validate in validators:
        with pytest.raises(ValidationError) as error:
            validate()
        surfaces = (
            str(error.value),
            repr(error.value),
            repr(error.value.errors()),
            repr(error.value.__context__),
            repr(error.value.__cause__),
        )
        assert all("secret-value" not in surface for surface in surfaces)


@pytest.mark.parametrize(
    ("status", "read_only"),
    [
        (RuntimeServiceStatus.RUNNING, True),
        (RuntimeServiceStatus.DEGRADED, False),
    ],
)
def test_runtime_health_rejects_dishonest_running_and_degraded_modes(
    status: RuntimeServiceStatus,
    read_only: bool,
) -> None:
    with pytest.raises(ValidationError, match="read_only"):
        RuntimeHealthSnapshot(
            status=status,
            read_only=read_only,
            observed_at=_at(10, 0),
            started_at=_at(9, 0),
            executor=ExecutorHealthSnapshot(max_workers=2, active_count=0, waiting_count=0),
            database=DatabaseHealthSnapshot(
                status=RuntimeResourceStatus.READY,
                wal_status=RuntimeResourceStatus.READY,
            ),
            delivery=DeliveryHealthSnapshot(
                status=RuntimeResourceStatus.READY,
                pending_count=0,
                failed_count=0,
            ),
        )


def test_lifecycle_builds_current_health_from_owned_and_injected_facts() -> None:
    details = _healthy_runtime_details().model_copy(
        update={
            "last_completed_minute": _at(9, 29),
            "latest_evaluation_at": _at(9, 25),
            "gaps": (RuntimeGapSnapshot(symbol="600000.SH", bar_end=_at(9, 28)),),
        }
    )
    service = _service(health_details=lambda: details)

    startup = asyncio.run(service.start())
    snapshot = service.health()

    assert snapshot.status is RuntimeServiceStatus.RUNNING
    assert snapshot.read_only is False
    assert snapshot.started_at == _at(9, 30)
    assert snapshot.last_completed_minute_age_seconds == 60
    assert snapshot.latest_evaluation_age_seconds == 300
    assert snapshot.gaps == details.gaps
    assert snapshot.next_poll_at == startup.next_poll_at
    asyncio.run(service.stop())


def test_shutdown_stops_scheduling_allows_bounded_finish_and_checkpoints_wal() -> None:
    async def scenario() -> tuple[list[str], bool, int]:
        events: list[str] = []
        scheduler = _Scheduler(wait_started=asyncio.Event())
        work_started = asyncio.Event()
        release_work = asyncio.Event()

        async def run_deadline(_deadline: MarketDeadline) -> None:
            events.append("work-start")
            work_started.set()
            await release_work.wait()
            events.append("work-finish")

        service = _service(
            events=events,
            scheduler=scheduler,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.1,
        )
        await service.start()
        run_task = asyncio.create_task(service.run())
        await work_started.wait()
        asyncio.get_running_loop().call_soon(release_work.set)
        await service.stop()
        await run_task
        return events, scheduler.wait_cancelled, service.owned_task_count

    events, wait_cancelled, owned_task_count = asyncio.run(scenario())

    assert "work-finish" in events
    assert wait_cancelled is False
    assert events[-4:] == [
        "dispatcher-close",
        "controller-close",
        "wal-checkpoint",
        "database-close",
    ]
    assert owned_task_count == 0


def test_shutdown_cancels_the_owned_scheduler_wait_before_it_can_admit_work() -> None:
    async def scenario() -> tuple[bool, list[str], int]:
        events: list[str] = []
        scheduler = _Scheduler(wait_started=asyncio.Event(), calls=1)
        service = _service(events=events, scheduler=scheduler)
        await service.start()
        run_task = asyncio.create_task(service.run())
        await scheduler.wait_started.wait()
        await service.stop()
        await run_task
        return scheduler.wait_cancelled, events, service.owned_task_count

    wait_cancelled, events, owned_task_count = asyncio.run(scenario())

    assert wait_cancelled is True
    assert "deadline" not in events
    assert owned_task_count == 0


def test_shutdown_cancels_overdue_work_and_joins_every_owned_task() -> None:
    async def scenario() -> tuple[list[str], int]:
        events: list[str] = []
        work_started = asyncio.Event()

        async def run_deadline(_deadline: MarketDeadline) -> None:
            events.append("work-start")
            work_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("work-cancelled")
                raise

        service = _service(
            events=events,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.001,
        )
        await service.start()
        run_task = asyncio.create_task(service.run())
        await work_started.wait()
        await service.stop()
        await run_task
        return events, service.owned_task_count

    events, owned_task_count = asyncio.run(scenario())

    assert events.index("work-cancelled") < events.index("wal-checkpoint")
    assert owned_task_count == 0


def test_degraded_run_remains_alive_until_explicit_shutdown() -> None:
    async def scenario() -> tuple[bool, RuntimeServiceStatus]:
        capabilities = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.BLOCKED_PERMISSION}
        )
        service = _service(capabilities=capabilities)
        run_task = asyncio.create_task(service.run())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        remained_alive = not run_task.done()
        await service.stop()
        await run_task
        return remained_alive, service.status

    remained_alive, status = asyncio.run(scenario())

    assert remained_alive is True
    assert status is RuntimeServiceStatus.STOPPED


def test_shutdown_reissues_cancel_before_checkpointing_delayed_cancellation() -> None:
    async def scenario() -> tuple[list[str], int]:
        events: list[str] = []
        work_started = asyncio.Event()

        async def run_deadline(_deadline: MarketDeadline) -> None:
            events.append("work-start")
            work_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("cancel-delayed")
                await asyncio.Event().wait()

        service = _service(
            events=events,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.001,
        )
        await service.start()
        run_task = asyncio.create_task(service.run())
        await work_started.wait()
        await asyncio.wait_for(service.stop(), timeout=0.1)
        await run_task
        return events, service.owned_task_count

    events, owned_task_count = asyncio.run(scenario())

    assert events.index("cancel-delayed") < events.index("wal-checkpoint")
    assert owned_task_count == 0


def test_cancellation_resistant_work_keeps_shutdown_failed_and_database_open_for_retry() -> None:
    async def scenario() -> tuple[
        RuntimeServiceStatus,
        int,
        bool,
        RuntimeServiceStatus,
        int,
        bool,
    ]:
        events: list[str] = []
        work_started = asyncio.Event()
        release_work = asyncio.Event()

        async def run_deadline(_deadline: MarketDeadline) -> None:
            work_started.set()
            cancellations = 0
            while cancellations < 2:
                try:
                    await release_work.wait()
                except asyncio.CancelledError:
                    cancellations += 1
                    events.append(f"cancel-{cancellations}")
            await release_work.wait()

        service = _service(
            events=events,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.001,
        )
        await service.start()
        run_task = asyncio.create_task(service.run())
        await work_started.wait()
        with pytest.raises(RuntimeShutdownError, match="owned task"):
            await asyncio.wait_for(service.stop(), timeout=0.1)
        failed = (
            service.status,
            service.owned_task_count,
            "wal-checkpoint" in events,
        )
        release_work.set()
        await run_task
        completed = (
            service.status,
            service.owned_task_count,
            "wal-checkpoint" in events,
        )
        return (*failed, *completed)

    failed_status, failed_owned, failed_checkpoint, status, owned, checkpoint = asyncio.run(
        scenario()
    )

    assert failed_status is RuntimeServiceStatus.STOPPING
    assert failed_owned == 1
    assert failed_checkpoint is False
    assert status is RuntimeServiceStatus.STOPPED
    assert owned == 0
    assert checkpoint is True


def test_cancelling_one_stop_waiter_does_not_cancel_owned_cleanup() -> None:
    async def scenario() -> tuple[list[str], RuntimeServiceStatus, int]:
        events: list[str] = []
        work_started = asyncio.Event()

        async def run_deadline(_deadline: MarketDeadline) -> None:
            work_started.set()
            await asyncio.Event().wait()

        service = _service(
            events=events,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.01,
        )
        await service.start()
        run_task = asyncio.create_task(service.run())
        await work_started.wait()
        first_waiter = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        first_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_waiter
        await service.stop()
        await run_task
        return events, service.status, service.owned_task_count

    events, status, owned_task_count = asyncio.run(scenario())

    assert "wal-checkpoint" in events
    assert "database-close" in events
    assert status is RuntimeServiceStatus.STOPPED
    assert owned_task_count == 0


def test_failed_resource_close_stays_stopping_and_retries_only_unfinished_cleanup() -> None:
    async def scenario() -> tuple[
        RuntimeServiceStatus,
        RuntimeServiceStatus,
        list[str],
    ]:
        events: list[str] = []
        close_calls = 0

        def close_database() -> None:
            nonlocal close_calls
            close_calls += 1
            events.append(f"database-close-{close_calls}")
            if close_calls == 1:
                raise RuntimeError("close failure")

        service = _service(events=events, close_database=close_database)
        await service.start()
        with pytest.raises(RuntimeError, match="close failure"):
            await service.stop()
        failed_status = service.status
        await service.stop()
        return failed_status, service.status, events

    failed_status, status, events = asyncio.run(scenario())

    assert failed_status is RuntimeServiceStatus.STOPPING
    assert status is RuntimeServiceStatus.STOPPED
    assert events.count("dispatcher-close") == 1
    assert events.count("controller-close") == 1
    assert events.count("wal-checkpoint") == 1
    assert events[-2:] == ["database-close-1", "database-close-2"]


def test_concurrent_start_is_shared_and_stop_cancels_incomplete_startup() -> None:
    async def shared_start() -> tuple[int, bool]:
        calls = 0
        open_started = asyncio.Event()
        release_open = asyncio.Event()

        async def open_database() -> None:
            nonlocal calls
            calls += 1
            open_started.set()
            await release_open.wait()

        service = _service(open_database=open_database)
        first = asyncio.create_task(service.start())
        await open_started.wait()
        second = asyncio.create_task(service.start())
        release_open.set()
        first_result, second_result = await asyncio.gather(first, second)
        await service.stop()
        return calls, first_result is second_result

    async def interrupted_start() -> tuple[RuntimeServiceStatus, bool]:
        open_started = asyncio.Event()
        cancelled = False

        async def open_database() -> None:
            nonlocal cancelled
            open_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

        service = _service(open_database=open_database)
        startup_task = asyncio.create_task(service.start())
        await open_started.wait()
        await service.stop()
        with pytest.raises(asyncio.CancelledError):
            await startup_task
        return service.status, cancelled

    calls, shared_result = asyncio.run(shared_start())
    status, cancelled = asyncio.run(interrupted_start())

    assert calls == 1
    assert shared_result is True
    assert status is RuntimeServiceStatus.STOPPED
    assert cancelled is True


def test_cancelling_one_start_waiter_does_not_cancel_shared_startup() -> None:
    async def scenario() -> tuple[RuntimeServiceStatus, list[str]]:
        events: list[str] = []
        open_started = asyncio.Event()
        release_open = asyncio.Event()

        async def open_database() -> None:
            open_started.set()
            await release_open.wait()
            events.append("database-opened")

        service = _service(events=events, open_database=open_database)
        first_waiter = asyncio.create_task(service.start())
        await open_started.wait()
        cancelled_waiter = asyncio.create_task(service.start())
        await asyncio.sleep(0)
        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter

        assert first_waiter.done() is False
        release_open.set()
        startup = await asyncio.wait_for(first_waiter, timeout=0.1)
        await service.stop()
        return startup.status, events

    status, events = asyncio.run(scenario())

    assert status is RuntimeServiceStatus.RUNNING
    assert events.count("database-opened") == 1


def test_run_once_joining_an_inflight_start_does_not_own_lifecycle_shutdown() -> None:
    async def scenario() -> tuple[RuntimeServiceStatus, bool, list[str]]:
        events: list[str] = []
        open_started = asyncio.Event()
        release_open = asyncio.Event()

        async def open_database() -> None:
            open_started.set()
            await release_open.wait()

        service = _service(events=events, open_database=open_database)
        startup_task = asyncio.create_task(service.start())
        await open_started.wait()
        run_once_task = asyncio.create_task(service.run_once())
        await asyncio.sleep(0)
        release_open.set()

        await asyncio.wait_for(startup_task, timeout=0.1)
        await asyncio.wait_for(run_once_task, timeout=0.1)
        status_before_explicit_stop = service.status
        checkpoint_before_explicit_stop = "wal-checkpoint" in events
        await service.stop()
        return status_before_explicit_stop, checkpoint_before_explicit_stop, events

    status, checkpointed_early, events = asyncio.run(scenario())

    assert status is RuntimeServiceStatus.RUNNING
    assert checkpointed_early is False
    assert events.count("deadline") == 1
    assert events.count("wal-checkpoint") == 1


def test_concurrent_scheduling_entrypoints_reject_a_second_owner() -> None:
    async def scenario() -> tuple[bool, int, int]:
        scheduler = _Scheduler(wait_started=asyncio.Event(), calls=1)
        service = _service(scheduler=scheduler)
        run_task = asyncio.create_task(service.run())
        await scheduler.wait_started.wait()

        with pytest.raises(RuntimeError, match="scheduling loop is already active"):
            await asyncio.wait_for(service.run(), timeout=0.05)
        with pytest.raises(RuntimeError, match="scheduling loop is already active"):
            await asyncio.wait_for(service.run_once(), timeout=0.05)

        await service.stop()
        await asyncio.wait_for(run_task, timeout=0.1)
        return scheduler.wait_cancelled, scheduler.calls, service.owned_task_count

    wait_cancelled, scheduler_calls, owned_task_count = asyncio.run(scenario())

    assert wait_cancelled is True
    assert scheduler_calls == 2
    assert owned_task_count == 0


def test_stopped_lifecycle_rejects_restart_instead_of_returning_stale_result() -> None:
    service = _service()
    asyncio.run(service.start())
    asyncio.run(service.stop())

    with pytest.raises(RuntimeError, match="cannot be restarted"):
        asyncio.run(service.start())


def test_owned_deadline_may_request_shutdown_without_awaiting_itself() -> None:
    async def scenario() -> tuple[object | None, list[str], int]:
        events: list[str] = []
        service: RuntimeLifecycleService

        async def run_deadline(_deadline: MarketDeadline) -> str:
            events.append("work-stop")
            await service.stop()
            return "stopped"

        service = _service(
            events=events,
            run_deadline=run_deadline,
            shutdown_timeout_seconds=0.001,
        )
        result = await service.run_once()
        return result, events, service.owned_task_count

    result, events, owned_task_count = asyncio.run(scenario())

    assert result == "stopped"
    assert events.index("work-stop") < events.index("wal-checkpoint")
    assert owned_task_count == 0


def test_maintenance_service_wires_validate_once_run_replay_and_backup() -> None:
    async def scenario() -> list[str]:
        events: list[str] = []

        class Lifecycle:
            async def run_once(self) -> None:
                events.append("once")

            async def run(self) -> None:
                events.append("run")

        service = MaintenanceCommandService(
            lifecycle=Lifecycle(),
            validate=lambda: events.append("validate"),
            replay=lambda: events.append("replay"),
            backup=lambda: events.append("backup"),
        )
        await service.validate()
        await service.once()
        await service.run()
        await service.replay()
        await service.backup()
        return events

    assert asyncio.run(scenario()) == ["validate", "once", "run", "replay", "backup"]
