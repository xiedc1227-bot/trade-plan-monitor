import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

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
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import (
    ActiveSymbolLimitError,
    MaintenanceCommandService,
    RuntimeLifecycleService,
    RuntimeShutdownError,
    _RetryWaitOutcome,
    _wait_for_retry_or_shutdown,
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

    def elapsed_market_deadlines(
        self, *, after: datetime, through: datetime,
    ) -> tuple[MarketDeadline, ...]:
        if self.deadline is not None and after < self.deadline.due_at <= through:
            return (self.deadline,)
        return ()

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
    liveness_owner: object | None = None,
    heartbeat_interval_seconds: float = 30.0,
    retry_interval_seconds: float = 30.0,
    retry_wait: Callable[[asyncio.Event, float], Awaitable[_RetryWaitOutcome]] | None = None,
    probe_capabilities: Callable[[], ProviderCapabilities] | None = None,
    can_schedule: Callable[[ProviderCapabilities], bool] | None = None,
    health_details: Callable[[], RuntimeHealthDetails] = _healthy_runtime_details,
    shutdown_timeout_seconds: float = 0.05,
    request_controller: object | None = None,
    dispatcher: object | None = None,
    configuration_restart_required: Callable[[], bool] | None = None,
) -> RuntimeLifecycleService:
    observed = events if events is not None else []
    clock = _Clock()

    async def default_retry_wait(shutdown: asyncio.Event, delay: float) -> _RetryWaitOutcome:
        outcome = await _wait_for_retry_or_shutdown(shutdown, delay)
        if outcome is _RetryWaitOutcome.TIMEOUT:
            clock.current += timedelta(seconds=delay)
        return outcome

    async def record_deadline(_deadline: MarketDeadline) -> None:
        observed.append("deadline")

    async def recover_startup(_trade_date: date) -> None:
        observed.append("recover")

    return RuntimeLifecycleService(
        clock=clock,
        validate_configuration=lambda: observed.append("config"),
        configuration_restart_required=configuration_restart_required,
        open_database=(
            open_database if open_database is not None else lambda: observed.append("database")
        ),
        liveness_owner=liveness_owner,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        retry_interval_seconds=retry_interval_seconds,
        retry_wait=default_retry_wait if retry_wait is None else retry_wait,
        load_active_symbols=lambda: (observed.append("plans"), symbols)[1],
        probe_capabilities=probe_capabilities or (lambda: (
            observed.append("probe"),
            capabilities if capabilities is not None else _ready_capabilities(),
        )[1]),
        can_schedule=can_schedule,
        refresh_references=(
            refresh_references
            if refresh_references is not None
            else lambda _trade_date: observed.append("references")
        ),
        recover_startup=recover_startup,
        scheduler=scheduler if scheduler is not None else _Scheduler(),
        run_deadline=run_deadline if run_deadline is not None else record_deadline,
        dispatcher=dispatcher or _AsyncCloser(observed),
        request_controller=request_controller or _SyncCloser(observed),
        checkpoint_wal=lambda: observed.append("wal-checkpoint"),
        close_database=(
            close_database
            if close_database is not None
            else lambda: observed.append("database-close")
        ),
        health_details=health_details,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def test_liveness_admission_precedes_plan_loading_and_heartbeat_drains_before_database_close():
    events: list[str] = []
    beat_seen = asyncio.Event()

    class Liveness:
        async def admit(self):
            events.append("admit")

        async def heartbeat(self):
            events.append("beat")
            beat_seen.set()

    async def scenario():
        service = _service(
            events=events,
            liveness_owner=Liveness(),
            heartbeat_interval_seconds=0.01,
        )
        await service.start()
        assert service.owned_task_count == 1
        await asyncio.wait_for(beat_seen.wait(), timeout=1)
        await service.stop()
        assert service.owned_task_count == 0

    asyncio.run(scenario())
    assert events[:4] == ["config", "database", "admit", "plans"]
    assert events.index("beat") < events.index("database-close")


def test_failed_liveness_admission_blocks_plan_loading_and_provider_probe():
    events: list[str] = []

    class Liveness:
        async def admit(self):
            events.append("admit")
            raise RuntimeError("liveness unknown")

        async def heartbeat(self):
            events.append("beat")

    service = _service(events=events, liveness_owner=Liveness())
    with pytest.raises(RuntimeError, match="liveness unknown"):
        asyncio.run(service.start())
    assert "plans" not in events
    assert "probe" not in events
    assert "database-close" in events


def test_legacy_liveness_block_serves_read_only_health_without_provider_work():
    from trade_plan_monitor.state.runtime_liveness import LegacyPlansRequireReview

    events: list[str] = []

    class Liveness:
        async def admit(self):
            events.append("admit")
            raise LegacyPlansRequireReview("legacy plans require review")

        async def heartbeat(self):
            events.append("beat")

    async def scenario():
        service = _service(events=events, liveness_owner=Liveness())
        startup = await service.start()
        health = service.health()
        assert startup.status is RuntimeServiceStatus.BLOCKED
        assert startup.read_only is True
        assert health.status is RuntimeServiceStatus.BLOCKED
        assert health.block_reason == "LEGACY_PLANS_REQUIRE_REVIEW"
        assert service.owned_task_count == 0
        await service.stop()

    asyncio.run(scenario())
    assert events[:3] == ["config", "database", "admit"]
    assert "plans" not in events
    assert "probe" not in events
    assert "recover" not in events
    assert "beat" not in events


def test_failed_heartbeat_stops_runtime_without_marking_cleanup_failed():
    events: list[str] = []

    class Liveness:
        async def admit(self):
            events.append("admit")

        async def heartbeat(self):
            events.append("beat")
            raise RuntimeError("heartbeat storage failed")

    async def scenario():
        service = _service(
            events=events,
            liveness_owner=Liveness(),
            heartbeat_interval_seconds=0.01,
        )
        await service.start()
        for _ in range(100):
            if service.status is RuntimeServiceStatus.STOPPED:
                break
            await asyncio.sleep(0.01)
        assert service.status is RuntimeServiceStatus.STOPPED
        assert service.cleanup_failed is False

    asyncio.run(scenario())
    assert events.index("beat") < events.index("database-close")


def test_read_only_standby_keeps_local_heartbeat_alive():
    beats = asyncio.Event()

    class Liveness:
        async def admit(self):
            return None

        async def heartbeat(self):
            beats.set()

    async def scenario():
        service = _service(
            scheduler=_Scheduler(deadline=None),
            liveness_owner=Liveness(),
            heartbeat_interval_seconds=0.01,
        )
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        await asyncio.wait_for(beats.wait(), timeout=1)
        await service.stop()

    asyncio.run(scenario())


def test_provider_outage_keeps_legal_software_owner_heartbeat_alive():
    beats = asyncio.Event()

    class Liveness:
        async def admit(self):
            return None

        async def heartbeat(self):
            beats.set()

    def disconnected(_trade_date: date):
        raise RequestControlError(
            RequestControlErrorCode.TRANSIENT,
            TushareOperation.TRADING_CALENDAR,
            attempts=1,
        )

    async def scenario():
        service = _service(
            liveness_owner=Liveness(),
            refresh_references=disconnected,
            heartbeat_interval_seconds=0.01,
        )
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        await asyncio.wait_for(beats.wait(), timeout=1)
        assert service.health().status is RuntimeServiceStatus.DEGRADED
        await service.stop()

    asyncio.run(scenario())


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
        "controller-close",
        "dispatcher-close",
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
        raise RequestControlError(
            RequestControlErrorCode.TRANSIENT,
            TushareOperation.TRADING_CALENDAR,
            attempts=1,
            next_retry_at=_at(9, 30),
        )

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


def test_startup_storage_fault_does_not_become_provider_retry() -> None:
    def fail_references(_trade_date: date) -> None:
        raise SQLAlchemyError("offline storage fault")

    async def scenario() -> None:
        service = _service(refresh_references=fail_references)
        with pytest.raises(SQLAlchemyError):
            await service.start()
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_startup_rate_limit_keeps_shared_cooldown_as_retry_floor() -> None:
    def rate_limited(_trade_date: date) -> None:
        raise RequestControlError(
            RequestControlErrorCode.RATE_LIMITED,
            TushareOperation.TRADING_CALENDAR,
            attempts=1,
            next_retry_at=_at(9, 35),
        )

    async def scenario() -> None:
        service = _service(refresh_references=rate_limited)
        try:
            assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
            assert service.health().next_retry_at == _at(9, 35)
        finally:
            await service.stop()

    asyncio.run(scenario())


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


def test_runtime_health_rejects_a_non_uuid4_generation() -> None:
    with pytest.raises(ValidationError, match="UUID version 4"):
        RuntimeHealthSnapshot(
            status=RuntimeServiceStatus.DEGRADED,
            read_only=True,
            runtime_generation=UUID("00000000-0000-1000-8000-000000000001"),
            observed_at=_at(10, 0),
            started_at=_at(9, 0),
            executor=ExecutorHealthSnapshot(max_workers=1, active_count=0, waiting_count=0),
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
        stop_task = asyncio.create_task(service.stop())
        for _ in range(10):
            if "controller-close" in events:
                break
            await asyncio.sleep(0)
        assert "controller-close" in events
        release_work.set()
        await stop_task
        await run_task
        return events, scheduler.wait_cancelled, service.owned_task_count

    events, wait_cancelled, owned_task_count = asyncio.run(scenario())

    assert "work-finish" in events
    assert wait_cancelled is False
    assert events.index("controller-close") < events.index("work-finish")
    assert events[-4:] == [
        "work-finish",
        "dispatcher-close",
        "wal-checkpoint",
        "database-close",
    ]
    assert owned_task_count == 0


def test_failed_physical_join_keeps_database_open_until_cleanup_succeeds() -> None:
    class PhysicalController:
        def __init__(self, events: list[str]) -> None:
            self.events = events
            self.can_join = False

        def close(self) -> None:
            self.events.append("controller-close")

        async def aclose(self) -> None:
            self.events.append("controller-join")
            if not self.can_join:
                raise RuntimeError("physical worker remains active")

    async def scenario() -> None:
        events: list[str] = []
        controller = PhysicalController(events)
        service = _service(events=events, request_controller=controller)
        assert (await service.start()).status is RuntimeServiceStatus.RUNNING
        with pytest.raises(RuntimeError, match="physical worker"):
            await service.stop()
        assert "wal-checkpoint" not in events
        assert "database-close" not in events
        assert service.status is RuntimeServiceStatus.STOPPING
        controller.can_join = True
        await service.stop()
        assert events.index("controller-join") < events.index("wal-checkpoint")
        assert events[-1] == "database-close"

    asyncio.run(scenario())


def test_failed_dispatcher_drain_keeps_provider_owner_and_database_open() -> None:
    class OwnedController:
        def __init__(self, events: list[str]) -> None:
            self.events = events

        def close(self) -> None:
            self.events.append("controller-stop-admission")

        async def aclose(self) -> None:
            self.events.append("controller-release-owner")

    class DrainingDispatcher:
        def __init__(self, events: list[str]) -> None:
            self.events = events
            self.can_drain = False

        async def aclose(self) -> None:
            self.events.append("dispatcher-drain")
            if not self.can_drain:
                raise RuntimeError("delivery remains active")

    async def scenario() -> None:
        events: list[str] = []
        dispatcher = DrainingDispatcher(events)
        service = _service(
            events=events, dispatcher=dispatcher,
            request_controller=OwnedController(events),
        )
        assert (await service.start()).status is RuntimeServiceStatus.RUNNING
        with pytest.raises(RuntimeError, match="delivery remains active"):
            await service.stop()
        assert "controller-stop-admission" in events
        assert "controller-release-owner" not in events
        assert "wal-checkpoint" not in events
        assert "database-close" not in events
        dispatcher.can_drain = True
        await service.stop()
        assert events.index("dispatcher-drain") < events.index("database-close")
        assert events.index("controller-release-owner") < events.index("database-close")

    asyncio.run(scenario())


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


def test_retry_wait_stop_before_wait_does_not_start_recheck() -> None:
    async def scenario() -> None:
        events: list[str] = []
        waits: list[float] = []

        async def retry_wait(_shutdown: asyncio.Event, delay: float) -> _RetryWaitOutcome:
            waits.append(delay)
            return _RetryWaitOutcome.TIMEOUT

        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service = _service(events=events, capabilities=unavailable, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        service.begin_shutdown()
        await service._retry_degraded_startup()
        await service.stop()
        assert waits == []
        assert events.count("probe") == 1
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_retry_wait_stop_during_wait_wakes_without_recheck() -> None:
    async def scenario() -> None:
        events: list[str] = []
        entered = asyncio.Event()

        async def retry_wait(shutdown: asyncio.Event, _delay: float) -> _RetryWaitOutcome:
            entered.set()
            await shutdown.wait()
            return _RetryWaitOutcome.SHUTDOWN

        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service = _service(events=events, capabilities=unavailable, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        runner = asyncio.create_task(service.run())
        await asyncio.wait_for(entered.wait(), timeout=1)
        await service.stop()
        await runner
        assert events.count("probe") == 1
        assert service.owned_task_count == 0

    asyncio.run(scenario())


def test_retry_wait_timeout_after_begin_shutdown_does_not_recheck() -> None:
    async def scenario() -> None:
        events: list[str] = []
        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service: RuntimeLifecycleService

        async def retry_wait(_shutdown: asyncio.Event, _delay: float) -> _RetryWaitOutcome:
            service.begin_shutdown()
            return _RetryWaitOutcome.TIMEOUT

        service = _service(events=events, capabilities=unavailable, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        await service.run()
        assert events.count("probe") == 1
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_retry_wait_timeout_before_begin_shutdown_allows_only_started_recheck() -> None:
    async def scenario() -> None:
        attempts = 0
        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service: RuntimeLifecycleService

        def probe() -> ProviderCapabilities:
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                service.begin_shutdown()
            return unavailable

        async def retry_wait(_shutdown: asyncio.Event, _delay: float) -> _RetryWaitOutcome:
            service._clock.current += timedelta(seconds=_delay)
            return _RetryWaitOutcome.TIMEOUT

        service = _service(probe_capabilities=probe, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        await service.run()
        assert attempts == 2
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_retry_wait_external_cancellation_never_rechecks() -> None:
    async def scenario() -> None:
        events: list[str] = []
        entered = asyncio.Event()

        async def retry_wait(_shutdown: asyncio.Event, _delay: float) -> _RetryWaitOutcome:
            entered.set()
            await asyncio.Event().wait()
            return _RetryWaitOutcome.TIMEOUT

        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service = _service(events=events, capabilities=unavailable, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        runner = asyncio.create_task(service.run())
        await asyncio.wait_for(entered.wait(), timeout=1)
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert events.count("probe") == 1
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_default_retry_wait_returns_timeout_or_shutdown() -> None:
    async def scenario() -> None:
        shutdown = asyncio.Event()
        assert await _wait_for_retry_or_shutdown(shutdown, 0.001) is (
            _RetryWaitOutcome.TIMEOUT
        )
        shutdown.set()
        assert await _wait_for_retry_or_shutdown(shutdown, 1) is (
            _RetryWaitOutcome.SHUTDOWN
        )
        pending = asyncio.create_task(
            _wait_for_retry_or_shutdown(asyncio.Event(), 60)
        )
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(scenario())


def test_retry_wait_preserves_later_controller_floor() -> None:
    async def scenario() -> None:
        observed: list[tuple[float, datetime | None]] = []
        unavailable = _ready_capabilities().model_copy(
            update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
        )
        service: RuntimeLifecycleService

        async def retry_wait(_shutdown: asyncio.Event, delay: float) -> _RetryWaitOutcome:
            observed.append((delay, service.health().next_retry_at))
            return _RetryWaitOutcome.SHUTDOWN

        service = _service(capabilities=unavailable, retry_wait=retry_wait)
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        service._retry_at = _at(9, 35)
        await service.run()
        assert observed == [(300.0, _at(9, 35))]

    asyncio.run(scenario())


def test_degraded_startup_retries_and_resumes_scheduling_without_process_restart() -> None:
    async def scenario() -> list[str]:
        events: list[str] = []
        attempts = 0

        def probe() -> ProviderCapabilities:
            nonlocal attempts
            attempts += 1
            events.append("probe")
            if attempts == 1:
                return _ready_capabilities().model_copy(
                    update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
                )
            return _ready_capabilities()

        service = _service(
            events=events,
            probe_capabilities=probe,
            retry_interval_seconds=0.01,
        )
        assert (await service.start()).status is RuntimeServiceStatus.DEGRADED
        assert service.health().degraded_reason == "PROVIDER_UNAVAILABLE"
        running = asyncio.create_task(service.run())
        try:
            for _ in range(100):
                if service.health().status is RuntimeServiceStatus.RUNNING:
                    break
                await asyncio.sleep(0.01)
            assert service.health().status is RuntimeServiceStatus.RUNNING
            assert service.health().degraded_reason is None
            assert events.count("probe") >= 2
            assert events.count("recover") >= 2
        finally:
            await service.stop()
            await running
        return events

    assert "deadline" in asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure_code",
    (RequestControlErrorCode.TRANSIENT, RequestControlErrorCode.RATE_LIMITED),
)
def test_retryable_deadline_failure_keeps_owner_and_resumes_after_recovery(
    failure_code: RequestControlErrorCode,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        second = MarketDeadline(
            kind=DeadlineKind.REALTIME_MINUTE,
            trade_date=date(2026, 8, 24),
            bar_end=_at(9, 32),
            due_at=_at(9, 32, 12),
        )

        class TwoDeadlines:
            def next_deadline(self, *, after=None):
                return second if after is not None else _deadline()

            def elapsed_market_deadlines(self, *, after, through):
                return tuple(
                    deadline for deadline in (_deadline(), second)
                    if after < deadline.due_at <= through
                )

            async def wait_for_next(self, *, after=None):
                if after is None:
                    return _deadline()
                if after == _deadline().due_at:
                    return second
                await asyncio.Event().wait()

        completed = asyncio.Event()

        async def run_deadline(deadline: MarketDeadline) -> None:
            if deadline == _deadline():
                events.append("transient-failure")
                raise RequestControlError(
                    failure_code,
                    TushareOperation.REALTIME_MINUTES,
                    attempts=1,
                    next_retry_at=_at(9, 30),
                )
            events.append("resumed-deadline")
            completed.set()

        service = _service(
            events=events,
            scheduler=TwoDeadlines(),
            run_deadline=run_deadline,
            retry_interval_seconds=0.01,
        )
        generation = service.runtime_generation
        runner = asyncio.create_task(service.run())
        try:
            await asyncio.wait_for(completed.wait(), 1)
            assert not runner.done()
            assert service.runtime_generation == generation
            assert service.status is RuntimeServiceStatus.RUNNING
            assert events.count("recover") >= 2
            assert "controller-close" not in events
        finally:
            await service.stop()
            await runner
        assert events.count("controller-close") == 1

    asyncio.run(scenario())


def test_unclassified_provider_failure_is_not_silently_retried() -> None:
    async def fail_deadline(_deadline: MarketDeadline) -> None:
        raise RequestControlError(
            RequestControlErrorCode.ERROR,
            TushareOperation.REALTIME_MINUTES,
            attempts=1,
        )

    async def scenario() -> None:
        service = _service(run_deadline=fail_deadline, retry_interval_seconds=0.01)
        with pytest.raises(RequestControlError) as error:
            await asyncio.wait_for(service.run(), 1)
        assert error.value.code is RequestControlErrorCode.ERROR
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_transient_cooldown_wait_is_visible_and_interruptible() -> None:
    async def fail_deadline(_deadline: MarketDeadline) -> None:
        raise RequestControlError(
            RequestControlErrorCode.TRANSIENT,
            TushareOperation.REALTIME_MINUTES,
            attempts=1,
            next_retry_at=_at(9, 35),
        )

    async def scenario() -> None:
        events: list[str] = []
        service = _service(events=events, run_deadline=fail_deadline)
        runner = asyncio.create_task(service.run())
        try:
            for _ in range(100):
                if service.status is RuntimeServiceStatus.DEGRADED:
                    break
                await asyncio.sleep(0)
            assert service.status is RuntimeServiceStatus.DEGRADED
            assert service.health().next_retry_at == _at(9, 35)
            await asyncio.sleep(0.03)
            assert events.count("probe") == 1
            assert not runner.done()
        finally:
            await asyncio.wait_for(service.stop(), 1)
            await runner
        assert events.count("controller-close") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", (SQLAlchemyError("storage"), TypeError("contract")))
def test_degraded_recheck_does_not_swallow_storage_or_contract_fault(
    failure: Exception,
) -> None:
    async def scenario() -> None:
        probes = 0
        references = 0

        def probe() -> ProviderCapabilities:
            nonlocal probes
            probes += 1
            if probes == 1:
                return _ready_capabilities().model_copy(
                    update={"daily_bars": ProviderCapabilityStatus.UNVERIFIED}
                )
            return _ready_capabilities()

        def refresh(_trade_date: date) -> None:
            nonlocal references
            references += 1
            if references == 2:
                raise failure

        service = _service(
            probe_capabilities=probe,
            refresh_references=refresh,
            retry_interval_seconds=0.01,
        )
        with pytest.raises(type(failure)):
            await asyncio.wait_for(service.run(), 1)
        assert references == 2
        assert service.status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_compatible_semantics_can_schedule_without_claiming_provider_ready() -> None:
    async def scenario() -> tuple[RuntimeServiceStatus, ProviderCapabilities]:
        service = _service(
            capabilities=ProviderCapabilities(),
            can_schedule=lambda _capabilities: True,
        )
        startup = await service.start()
        await service.stop()
        return startup.status, startup.capabilities

    status, capabilities = asyncio.run(scenario())
    assert status is RuntimeServiceStatus.RUNNING
    assert capabilities == ProviderCapabilities()


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


def test_configuration_drift_blocks_without_supervisor_exit_and_keeps_owner_heartbeat() -> None:
    async def scenario() -> None:
        drift = False
        events: list[str] = []

        class Owner:
            def admit(self) -> None:
                events.append("admit")

            def heartbeat(self) -> None:
                events.append("heartbeat")

        async def deadline(_target: MarketDeadline) -> None:
            nonlocal drift
            drift = True
            raise RuntimeError("configuration changed")

        service = _service(
            events=events,
            run_deadline=deadline,
            liveness_owner=Owner(),
            heartbeat_interval_seconds=0.01,
            configuration_restart_required=lambda: drift,
        )
        await service.start()
        running = asyncio.create_task(service.run())
        for _ in range(100):
            if service.health().status is RuntimeServiceStatus.BLOCKED:
                break
            await asyncio.sleep(0.001)
        assert service.health().block_reason == "NEEDS_RESTART"
        assert not running.done()
        await asyncio.sleep(0.03)
        assert "heartbeat" in events
        assert "controller-close" not in events
        await service.stop()
        await running
        assert service.health().status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())
