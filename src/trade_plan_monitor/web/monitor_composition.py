"""Lazy production composition for the currently certified monitor boundary."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from anyio import to_thread
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.notifications.channels import InAppChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.clock import Clock, SystemClock
from trade_plan_monitor.runtime.health import (
    DatabaseHealthSnapshot,
    DeliveryHealthSnapshot,
    ExecutorHealthSnapshot,
    ProviderHealthSnapshot,
    RuntimeHealthDetails,
    RuntimeHealthSnapshot,
    RuntimeResourceStatus,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.request_control import (
    TushareRequestController,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import MarketDeadline, MarketSessionScheduler
from trade_plan_monitor.runtime.service import RuntimeLifecycleService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import PlanVersionStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.plan_service import _reject_incompatible_database
from trade_plan_monitor.web.position_service import PersistentPositionOperationService
from trade_plan_monitor.web.websocket import CommittedMonitorEventStream

_RUNNER_SHUTDOWN_SECONDS = 5.0
_RUNTIME_RESTART_DELAYS_SECONDS = (1.0, 2.0, 4.0)
_ACTIVE_PLAN_READ_LIMIT = 11
_PROVIDER_CAPABILITIES = (
    "current_day_minutes",
    "daily_bars",
    "daily_limits",
    "realtime_minutes",
    "trading_calendar",
)


class MonitorRuntime(Protocol):
    """Runtime surface owned by one monitor Web composition."""

    async def start(self) -> object: ...

    async def run(self) -> None: ...

    async def stop(self) -> None: ...

    def health(self) -> RuntimeHealthSnapshot: ...


class MonitorWebComposition:
    """Own one runtime loop and the services backed by its exact state boundary."""

    def __init__(
        self,
        *,
        runtime: MonitorRuntime,
        read_service: object,
        runtime_factory: Callable[[], MonitorRuntime] | None = None,
        restart_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        websocket_service: object | None = None,
        position_service: object | None = None,
        alert_service: object | None = None,
        market_index_read_service: object | None = None,
    ) -> None:
        self._validate_runtime(runtime)
        if runtime_factory is not None and not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        if not callable(restart_sleep):
            raise TypeError("restart_sleep must be callable")
        if read_service is None:
            raise TypeError("read_service is required")
        self._runtime = runtime
        self._runtime_factory = runtime_factory
        self._restart_sleep = restart_sleep
        self._read_service = read_service
        self._websocket_service = websocket_service
        self._position_service = position_service
        self._alert_service = alert_service
        self._market_index_read_service = market_index_read_service
        self._runner_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._runtime_stop_lock = asyncio.Lock()
        self._runtime_stopped = False
        self._last_runtime_health: RuntimeHealthSnapshot | None = None
        self._started = False
        self._stopping = False
        self._stopped = False
        self._runner_failed = False
        self._restart_pending = False
        self._restart_attempts = 0

    @property
    def read_service(self) -> object:
        return self._read_service

    @property
    def websocket_service(self) -> object | None:
        return self._websocket_service

    @property
    def position_service(self) -> object | None:
        return self._position_service

    @property
    def alert_service(self) -> object | None:
        return self._alert_service

    @property
    def market_index_read_service(self) -> object | None:
        return self._market_index_read_service

    async def start(self) -> RuntimeHealthSnapshot:
        """Start once and supervise scheduling only for an honestly ready runtime."""

        async with self._start_lock:
            if self._stopped:
                raise RuntimeError("monitor composition is already stopped")
            if self._stopping:
                raise RuntimeError("monitor composition startup is terminal")
            if self._started:
                return self.health()

            try:
                startup = await self._runtime.start()
                status = self._validate_startup(startup)
                runtime_health = self._validated_health(self._runtime.health())
                if (
                    runtime_health.status is not status
                    or runtime_health.read_only is not startup.read_only
                ):
                    raise ValueError("runtime startup and health readiness are inconsistent")
            except BaseException as startup_error:
                self._stopping = True
                try:
                    await self._stop_runtime()
                except BaseException as cleanup_error:
                    raise cleanup_error from startup_error
                self._stopped = True
                raise
            self._last_runtime_health = runtime_health
            if status is RuntimeServiceStatus.RUNNING:
                runner = asyncio.create_task(
                    self._supervise_runtime(),
                    name="trade-plan-monitor-runtime",
                )
                runner.add_done_callback(self._observe_runner)
                self._runner_task = runner
                await asyncio.sleep(0)
                if runner.done():
                    self._runner_failed = True
                    await asyncio.gather(runner, return_exceptions=True)
            self._started = True
            return self.health()

    def health(self) -> RuntimeHealthSnapshot:
        """Return the runtime snapshot, degrading any prematurely exited runner."""

        try:
            snapshot = self._validated_health(self._runtime.health())
        except Exception:
            if not self._runner_failed or self._last_runtime_health is None:
                raise
            snapshot = self._last_runtime_health
        else:
            self._last_runtime_health = snapshot
        runner = self._runner_task
        runner_failed = (
            not self._stopping
            and not self._stopped
            and (
                self._runner_failed
                or self._restart_pending
                or (
                    runner is not None
                    and runner.done()
                    and snapshot.status is RuntimeServiceStatus.RUNNING
                )
            )
        )
        if not runner_failed:
            return snapshot
        return snapshot.model_copy(
            update={
                "status": RuntimeServiceStatus.DEGRADED,
                "read_only": True,
                "stopped_at": None,
                "next_poll_at": None,
            }
        )

    async def stop(self) -> None:
        """Stop the runtime and reclaim the composition-owned runner task."""

        if self._stopped:
            return
        self._stopping = True
        first_error: BaseException | None = None
        try:
            await self._stop_runtime()
        except BaseException as error:
            first_error = error

        runner = self._runner_task
        if runner is not None:
            if self._restart_pending and not runner.done():
                runner.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(runner),
                    timeout=_RUNNER_SHUTDOWN_SECONDS,
                )
            except TimeoutError:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
                if first_error is None:
                    first_error = RuntimeError("monitor runtime runner did not stop")
            except BaseException as error:
                if first_error is None:
                    first_error = error
        self._runner_task = None
        self._started = False
        self._stopped = first_error is None
        if first_error is not None:
            raise first_error

    async def _supervise_runtime(self) -> None:
        """Restart only a post-start failed runner after exact cleanup."""

        while not self._stopping:
            runtime = self._runtime
            try:
                await runtime.run()
            except asyncio.CancelledError:
                if self._stopping:
                    return
                self._runner_failed = True
                raise
            except Exception:
                pass
            if self._stopping:
                return

            try:
                exit_health = self._validated_health(runtime.health())
            except Exception:
                return
            self._last_runtime_health = exit_health
            unexpected_exit = getattr(runtime, "unexpected_run_exit", False)
            if type(unexpected_exit) is not bool:
                return
            cleanup_failed = getattr(runtime, "cleanup_failed", False)
            if type(cleanup_failed) is not bool or cleanup_failed:
                self._runner_failed = True
                return
            if (
                not unexpected_exit
                and exit_health.status is not RuntimeServiceStatus.RUNNING
            ):
                self._runner_failed = False
                return

            self._runner_failed = True
            try:
                await self._stop_runtime(runtime)
            except Exception:
                return
            if (
                self._runtime_factory is None
                or self._restart_attempts >= len(_RUNTIME_RESTART_DELAYS_SECONDS)
            ):
                return

            delay = _RUNTIME_RESTART_DELAYS_SECONDS[self._restart_attempts]
            self._restart_attempts += 1
            self._restart_pending = True
            try:
                await self._restart_sleep(delay)
            except asyncio.CancelledError:
                if self._stopping:
                    return
                raise
            finally:
                self._restart_pending = False
            if self._stopping:
                return

            replacement: MonitorRuntime | None = None
            try:
                replacement = self._runtime_factory()
                self._validate_runtime(replacement)
                self._runtime = replacement
                self._runtime_stopped = False
                startup = await replacement.start()
                status = self._validate_startup(startup)
                replacement_health = self._validated_health(replacement.health())
                if (
                    replacement_health.status is not status
                    or replacement_health.read_only is not startup.read_only
                ):
                    raise ValueError("runtime startup and health readiness are inconsistent")
                self._last_runtime_health = replacement_health
            except asyncio.CancelledError:
                if self._stopping:
                    return
                raise
            except Exception:
                if replacement is not None:
                    try:
                        await self._stop_runtime(replacement)
                    except Exception:
                        pass
                return
            if status is not RuntimeServiceStatus.RUNNING:
                return
            self._runner_failed = False

    async def _stop_runtime(self, runtime: MonitorRuntime | None = None) -> None:
        target = self._runtime if runtime is None else runtime
        async with self._runtime_stop_lock:
            if target is self._runtime and self._runtime_stopped:
                return
            await target.stop()
            if target is self._runtime:
                self._runtime_stopped = True

    def _observe_runner(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    def _validate_runtime(runtime: object) -> None:
        for name in ("start", "run", "stop", "health"):
            if not callable(getattr(runtime, name, None)):
                raise TypeError(f"runtime must expose {name}")

    @staticmethod
    def _validate_startup(startup: object) -> RuntimeServiceStatus:
        status = getattr(startup, "status", None)
        read_only = getattr(startup, "read_only", None)
        if not isinstance(status, RuntimeServiceStatus) or type(read_only) is not bool:
            raise TypeError("runtime startup must expose typed status and read_only")
        if read_only != (status is RuntimeServiceStatus.DEGRADED):
            raise ValueError("runtime startup readiness is inconsistent")
        return status

    @staticmethod
    def _validated_health(value: object) -> RuntimeHealthSnapshot:
        if not isinstance(value, RuntimeHealthSnapshot):
            raise TypeError("runtime health must return RuntimeHealthSnapshot")
        return value


class _HealthBinding:
    """Bind the read façade after its owning composition exists."""

    def __init__(self) -> None:
        self._health: Callable[[], RuntimeHealthSnapshot] | None = None

    def bind(self, health: Callable[[], RuntimeHealthSnapshot]) -> None:
        if self._health is not None:
            raise RuntimeError("monitor health is already bound")
        if not callable(health):
            raise TypeError("health must be callable")
        self._health = health

    def __call__(self) -> RuntimeHealthSnapshot:
        if self._health is None:
            raise RuntimeError("monitor health is not bound")
        return self._health()


class _ProductionRuntimeState:
    """Local, secret-free facts used by the production runtime lifecycle."""

    def __init__(
        self,
        *,
        config_path: Path,
        database_path: Path,
        engine: Engine,
        session_factory: sessionmaker[Session],
        clock: Clock,
        request_controller: TushareRequestController,
    ) -> None:
        self._config_path = config_path
        self._database_path = database_path.expanduser().resolve()
        self._engine = engine
        self._session_factory = session_factory
        self._clock = clock
        self._request_controller = request_controller
        self._database_status = RuntimeResourceStatus.UNVERIFIED
        self._wal_status = RuntimeResourceStatus.UNVERIFIED
        self._last_checkpoint_at: datetime | None = None
        self._provider_checked_at: datetime | None = None

    async def validate_configuration(self) -> None:
        await to_thread.run_sync(load_application_config, self._config_path)

    async def open_database(self) -> None:
        await to_thread.run_sync(self._open_database_sync)

    def _open_database_sync(self) -> None:
        _reject_incompatible_database(self._database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            upgrade_database(self._engine)
        except BaseException:
            self._engine.dispose()
            raise
        self._database_status = RuntimeResourceStatus.READY
        self._wal_status = RuntimeResourceStatus.READY

    async def load_active_symbols(self) -> tuple[str, ...]:
        return await to_thread.run_sync(self._load_active_symbols_sync)

    def _load_active_symbols_sync(self) -> tuple[str, ...]:
        with self.unit_of_work_factory() as work:
            records, _ = work.plans.list_version_details(
                offset=0,
                limit=_ACTIVE_PLAN_READ_LIMIT,
                status=PlanVersionStatus.ACTIVE,
            )
        return tuple(sorted(record.symbol for record in records))

    def probe_capabilities(self) -> ProviderCapabilities:
        # The live minute source-time profile is not yet certified. Returning the
        # closed UNVERIFIED contract here prevents any token read or provider call.
        self._provider_checked_at = self._clock.now()
        return ProviderCapabilities()

    def refresh_references(self, _trade_date: date) -> None:
        return None

    def recover_startup(self, _trade_date: date) -> None:
        return None

    def is_open_on(self, trade_date: date) -> bool | None:
        if type(trade_date) is not date:
            raise TypeError("trade_date must be a date")
        with self.unit_of_work_factory() as work:
            rows = work.references.list_trading_days("SSE", trade_date, trade_date)
        if not rows:
            return None
        if len(rows) != 1 or rows[0].cal_date != trade_date:
            raise RuntimeError("stored trading calendar is inconsistent")
        return rows[0].is_open

    def run_deadline(self, _deadline: MarketDeadline) -> None:
        raise RuntimeError("live monitor execution is unavailable while source time is unverified")

    async def checkpoint_wal(self) -> None:
        await to_thread.run_sync(self._checkpoint_wal_sync)

    def _checkpoint_wal_sync(self) -> None:
        with closing(sqlite3.connect(self._database_path, timeout=5)) as connection:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is None or len(row) != 3 or row[0] != 0:
            raise RuntimeError("SQLite WAL checkpoint did not complete")
        self._last_checkpoint_at = self._clock.now()

    async def close_database(self) -> None:
        await to_thread.run_sync(self._engine.dispose)
        self._database_status = RuntimeResourceStatus.STOPPED
        self._wal_status = RuntimeResourceStatus.STOPPED

    def health_details(self) -> RuntimeHealthDetails:
        checked_at = self._provider_checked_at or self._clock.now()
        providers = tuple(
            ProviderHealthSnapshot(
                capability=capability,
                status=ProviderCapabilityStatus.UNVERIFIED,
                checked_at=checked_at,
                latency_ms=0,
            )
            for capability in _PROVIDER_CAPABILITIES
        )
        return RuntimeHealthDetails(
            providers=providers,
            executor=ExecutorHealthSnapshot(
                max_workers=self._request_controller.executor_workers,
                active_count=self._request_controller.active_count,
                waiting_count=self._request_controller.waiting_count,
            ),
            database=DatabaseHealthSnapshot(
                status=self._database_status,
                wal_status=self._wal_status,
                last_checkpoint_at=self._last_checkpoint_at,
            ),
            delivery=DeliveryHealthSnapshot(
                status=RuntimeResourceStatus.UNVERIFIED,
                pending_count=0,
                failed_count=0,
            ),
        )

    def unit_of_work_factory(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            self._session_factory,
            clock=self._clock.now,
        )


def create_monitor_composition_factory(
    *,
    config_path: Path,
    database_path: Path,
) -> Callable[[], MonitorWebComposition]:
    """Capture paths without configuration, database, provider, or task work."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a Path")

    def factory() -> MonitorWebComposition:
        return create_monitor_composition(
            config_path=config_path,
            database_path=database_path,
        )

    return factory


def create_monitor_composition(
    *,
    config_path: Path,
    database_path: Path,
) -> MonitorWebComposition:
    """Compose local persistence and an honestly degraded live-monitor gate."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a Path")
    clock = SystemClock()
    engine = create_sqlite_engine(database_path)
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock=clock.now)

    def runtime_factory() -> RuntimeLifecycleService:
        request_controller = create_live_tushare_request_controller(clock=clock)
        dispatcher = NotificationDispatcher(
            session_factory,
            channels=(InAppChannel(),),
            clock=clock.now,
        )
        state = _ProductionRuntimeState(
            config_path=config_path,
            database_path=database_path,
            engine=engine,
            session_factory=session_factory,
            clock=clock,
            request_controller=request_controller,
        )
        scheduler = MarketSessionScheduler(clock=clock, is_open_on=state.is_open_on)
        return RuntimeLifecycleService(
            clock=clock,
            validate_configuration=state.validate_configuration,
            open_database=state.open_database,
            load_active_symbols=state.load_active_symbols,
            probe_capabilities=state.probe_capabilities,
            refresh_references=state.refresh_references,
            recover_startup=state.recover_startup,
            scheduler=scheduler,
            run_deadline=state.run_deadline,
            dispatcher=dispatcher,
            request_controller=request_controller,
            checkpoint_wal=state.checkpoint_wal,
            close_database=state.close_database,
            health_details=state.health_details,
        )

    runtime = runtime_factory()
    health_binding = _HealthBinding()
    read_service = PersistentMonitorReadService(
        unit_of_work_factory,
        health_binding,
        clock=clock.now,
    )
    composition = MonitorWebComposition(
        runtime=runtime,
        runtime_factory=runtime_factory,
        read_service=read_service,
        websocket_service=CommittedMonitorEventStream(
            unit_of_work_factory=unit_of_work_factory,
            runtime_liveness_provider=health_binding,
            clock=clock.now,
        ),
        position_service=PersistentPositionOperationService(
            unit_of_work_factory=unit_of_work_factory,
        ),
        alert_service=PersistentAlertOperationService(
            unit_of_work_factory=unit_of_work_factory,
        ),
    )
    health_binding.bind(composition.health)
    return composition


__all__ = [
    "MonitorRuntime",
    "MonitorWebComposition",
    "create_monitor_composition",
    "create_monitor_composition_factory",
]
