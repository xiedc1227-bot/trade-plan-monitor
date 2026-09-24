"""Lazy production composition for the currently certified monitor boundary."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from threading import Event
from typing import Protocol
from uuid import UUID

from anyio import to_thread
from sqlalchemy import Engine, and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.config import ApplicationConfiguration, load_application_config
from trade_plan_monitor.live_profiles import load_stock_certification
from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.notifications.channels import InAppChannel
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.delivery_eligibility import DeliveryMetadataError
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
from trade_plan_monitor.runtime.production import (
    ProductionMonitorPipeline,
    ProductionSemanticBindings,
    ReferenceDataUnavailableError,
    SemanticContractBinding,
)
from trade_plan_monitor.runtime.provider_contract import (
    import_index_semantic_contract,
    import_stock_semantic_contract,
    load_semantic_contract,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    TushareOperation,
    TushareRequestController,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import MarketDeadline, MarketSessionScheduler
from trade_plan_monitor.runtime.service import RuntimeLifecycleService
from trade_plan_monitor.state.alert_invalidation_sweep import (
    MAX_SWEEP_BATCH,
    latest_alert_sequence,
    sweep_invalidated_alerts,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.legacy_plan_invalidation import (
    LegacyMaintenanceUnavailable,
    LegacyPlanPreview,
)
from trade_plan_monitor.state.models import AlertEvent, DeliveryAttempt, PlanVersionStatus
from trade_plan_monitor.state.runtime_liveness import RuntimeLivenessRepository
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.cursor_keys import load_or_create_cursor_key
from trade_plan_monitor.web.manual_event_risk_service import (
    PersistentManualEventRiskOperationService,
)
from trade_plan_monitor.web.persistent_market_index_history import (
    PersistentMarketIndexHistorySource,
)
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.plan_service import _reject_incompatible_database
from trade_plan_monitor.web.position_service import PersistentPositionOperationService
from trade_plan_monitor.web.routers.market_indexes import SignedMarketIndexHistoryService
from trade_plan_monitor.web.websocket import CommittedMonitorEventStream

_RUNNER_SHUTDOWN_SECONDS = 5.0
_RUNTIME_RESTART_DELAYS_SECONDS = (1.0, 2.0, 4.0)
_ACTIVE_PLAN_READ_LIMIT = 11
_LOGGER = logging.getLogger(__name__)
_PROVIDER_CAPABILITIES = (
    "current_day_minutes",
    "daily_bars",
    "daily_limits",
    "realtime_minutes",
    "trading_calendar",
)
_RECOVERY_PROFILE = "tushare-live-v1"


@dataclass
class _ProcessRuntimeBaseline:
    """Frozen provider configuration shared by every runtime in this process."""

    configuration: ApplicationConfiguration | None = None
    semantics_frozen: bool = False
    stock_semantic_revision: str | None = None
    index_semantic_revision: str | None = None
    revoked: Event = field(default_factory=Event)


def _provider_recovery_identity(endpoint: str) -> str:
    """Use the same effective endpoint as both live transport adapters."""

    return hashlib.sha256(
        f"{_RECOVERY_PROFILE}\0{endpoint}".encode()
    ).hexdigest()


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
        manual_event_risk_service: object | None = None,
        alert_service: object | None = None,
        market_index_read_service: object | None = None,
        legacy_maintenance_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
    ) -> None:
        self._validate_runtime(runtime)
        if runtime_factory is not None and not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        if not callable(restart_sleep):
            raise TypeError("restart_sleep must be callable")
        if read_service is None:
            raise TypeError("read_service is required")
        self._runtime = runtime
        self._candidate_runtime: MonitorRuntime | None = None
        self._runtime_factory = runtime_factory
        self._restart_sleep = restart_sleep
        self._read_service = read_service
        self._websocket_service = websocket_service
        self._position_service = position_service
        self._manual_event_risk_service = manual_event_risk_service
        self._alert_service = alert_service
        self._market_index_read_service = market_index_read_service
        self._legacy_maintenance_factory = legacy_maintenance_factory
        self._maintenance_lock = asyncio.Lock()
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
        self._configuration_restart_required = False

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
    def manual_event_risk_service(self) -> object | None:
        return self._manual_event_risk_service

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
            if self._needs_runner(self._runtime, status):
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
        self._configuration_restart_required |= getattr(
            self._runtime, "configuration_restart_required", False
        ) is True
        if self._configuration_restart_required and not self._stopping:
            return snapshot.model_copy(
                update={
                    "status": RuntimeServiceStatus.BLOCKED,
                    "read_only": True,
                    "block_reason": "NEEDS_RESTART",
                    "degraded_reason": None,
                    "next_poll_at": None,
                    "next_retry_at": None,
                    "stopped_at": None,
                }
            )
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
                "degraded_reason": "RUNTIME_RUNNER_FAILED",
                "stopped_at": None,
                "next_poll_at": None,
            }
        )

    async def preview_legacy_invalidation(self) -> LegacyPlanPreview:
        """Expose only the reviewable blocked-generation identities."""

        if not self._legacy_maintenance_allowed():
            raise LegacyMaintenanceUnavailable("legacy maintenance is not available")
        return await to_thread.run_sync(self._preview_legacy_sync)

    def _preview_legacy_sync(self) -> LegacyPlanPreview:
        factory = self._legacy_maintenance_factory
        if factory is None:
            raise LegacyMaintenanceUnavailable("legacy maintenance is not configured")
        with factory() as work:
            return work.preview_legacy_invalidation()

    async def invalidate_legacy_plans(self, *, expected_fingerprint: str) -> tuple[str, ...]:
        """Confirm only while this generation remains blocked and unscheduled."""

        async with self._maintenance_lock:
            if not self._legacy_maintenance_allowed():
                raise LegacyMaintenanceUnavailable("legacy maintenance is not available")
            return await to_thread.run_sync(self._invalidate_legacy_sync, expected_fingerprint)

    def _invalidate_legacy_sync(self, expected_fingerprint: str) -> tuple[str, ...]:
        factory = self._legacy_maintenance_factory
        if factory is None:
            raise LegacyMaintenanceUnavailable("legacy maintenance is not configured")
        with factory() as work:
            symbols = work.invalidate_legacy_plans(expected_fingerprint=expected_fingerprint)
            work.commit()
            return symbols

    def _legacy_maintenance_allowed(self) -> bool:
        if not self._started or self._stopping or self._stopped or self._runner_task is not None:
            return False
        snapshot = self.health()
        return (
            snapshot.status is RuntimeServiceStatus.BLOCKED
            and snapshot.read_only
            and snapshot.block_reason == "LEGACY_PLANS_REQUIRE_REVIEW"
        )

    async def stop(self) -> None:
        """Stop the runtime and reclaim the composition-owned runner task."""

        if self._stopped:
            return
        self._stopping = True
        first_error: BaseException | None = None
        candidate = self._candidate_runtime
        if candidate is not None:
            begin_shutdown = getattr(candidate, "begin_shutdown", None)
            if callable(begin_shutdown):
                try:
                    begin_shutdown()
                except BaseException as error:
                    first_error = error
        try:
            await self._stop_runtime()
        except BaseException as error:
            first_error = error

        if candidate is not None:
            try:
                await self._stop_runtime(candidate)
            except BaseException as error:
                if first_error is None:
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
            if getattr(runtime, "configuration_restart_required", False) is True:
                self._configuration_restart_required = True
                self._runner_failed = False
                await self._stop_runtime(runtime)
                return
            if not unexpected_exit and exit_health.status is not RuntimeServiceStatus.RUNNING:
                self._runner_failed = False
                return

            self._runner_failed = True
            try:
                await self._stop_runtime(runtime)
            except Exception:
                return
            if self._runtime_factory is None or self._restart_attempts >= len(
                _RUNTIME_RESTART_DELAYS_SECONDS
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

            if getattr(runtime, "configuration_restart_required", False) is True:
                self._configuration_restart_required = True
                return

            replacement: MonitorRuntime | None = None
            try:
                replacement = self._runtime_factory()
                self._candidate_runtime = replacement
                self._validate_runtime(replacement)
                if getattr(replacement, "configuration_restart_required", False) is True:
                    self._configuration_restart_required = True
                    await self._stop_runtime(replacement)
                    return
                startup = await replacement.start()
                if self._stopping:
                    await self._stop_runtime(replacement)
                    return
                if getattr(replacement, "configuration_restart_required", False) is True:
                    self._configuration_restart_required = True
                    await self._stop_runtime(replacement)
                    return
                status = self._validate_startup(startup)
                replacement_health = self._validated_health(replacement.health())
                if (
                    replacement_health.status is not status
                    or replacement_health.read_only is not startup.read_only
                ):
                    raise ValueError("runtime startup and health readiness are inconsistent")
                self._runtime = replacement
                self._candidate_runtime = None
                self._runtime_stopped = False
                self._last_runtime_health = replacement_health
            except asyncio.CancelledError:
                if self._stopping:
                    return
                raise
            except Exception:
                if replacement is not None and getattr(
                    replacement, "configuration_restart_required", False
                ) is True:
                    self._configuration_restart_required = True
                if replacement is not None:
                    try:
                        await self._stop_runtime(replacement)
                    except Exception:
                        pass
                return
            finally:
                if self._candidate_runtime is replacement:
                    self._candidate_runtime = None
            if not self._needs_runner(replacement, status):
                return
            self._runner_failed = False

    @staticmethod
    def _needs_runner(runtime: MonitorRuntime, status: RuntimeServiceStatus) -> bool:
        return status is RuntimeServiceStatus.RUNNING or (
            status is RuntimeServiceStatus.DEGRADED
            and isinstance(runtime, RuntimeLifecycleService)
        )

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
        if read_only != (
            status in {RuntimeServiceStatus.DEGRADED, RuntimeServiceStatus.BLOCKED}
        ):
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
        process_baseline: _ProcessRuntimeBaseline | None = None,
        runtime_generation: Callable[[], UUID] | None = None,
        business_commit_admission_open: Callable[[], bool] | None = None,
        publisher: Callable[..., object] | None = None,
        dispatcher: NotificationDispatcher | None = None,
        on_reference_failure: Callable[[str], None] | None = None,
    ) -> None:
        self._config_path = config_path
        self._database_path = database_path.expanduser().resolve()
        self._engine = engine
        self._session_factory = session_factory
        self._clock = clock
        self._request_controller = request_controller
        self._process_baseline = process_baseline or _ProcessRuntimeBaseline()
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._configuration: ApplicationConfiguration | None = None
        self._database_status = RuntimeResourceStatus.UNVERIFIED
        self._wal_status = RuntimeResourceStatus.UNVERIFIED
        self._last_checkpoint_at: datetime | None = None
        self._provider_checked_at: datetime | None = None
        self._capabilities = ProviderCapabilities()
        self._pipeline: ProductionMonitorPipeline | None = None
        self._semantic_reload_blocked = False
        self._configuration_restart_required = False
        self._runtime_generation = runtime_generation
        self._business_commit_admission_open = (
            business_commit_admission_open or (lambda: True)
        )
        self._publisher = publisher
        self._stage_errors: dict[str, str] = {}
        self._stage_retry_at: dict[str, datetime] = {}
        self._dispatcher = dispatcher
        self._on_reference_failure = on_reference_failure
        self._liveness = RuntimeLivenessRepository(session_factory)
        self._liveness_revision: int | None = None
        self._alert_sweep_cursor = 0
        self._alert_sweep_target = 0

    def next_index_recovery_at(self) -> datetime | None:
        return (
            None
            if self._pipeline is None
            else self._pipeline.index_service.next_recovery_due_at(now=self._clock.now())
        )

    async def validate_configuration(self) -> None:
        self._owner_loop = asyncio.get_running_loop()
        try:
            configuration = await to_thread.run_sync(load_application_config, self._config_path)
        except Exception:
            if self._process_baseline.configuration is not None:
                self._revoke_configuration()
            raise
        baseline = self._process_baseline.configuration
        if (
            (baseline is not None and configuration.tushare != baseline.tushare)
            or (
                self._configuration is not None
                and configuration.tushare != self._configuration.tushare
            )
        ):
            self._revoke_configuration()
            raise RuntimeError("monitor configuration changed; safe restart required")
        if baseline is None:
            self._process_baseline.configuration = configuration
        self._configuration = configuration
        self._require_frozen_semantics(configuration)

    def _require_frozen_semantics(self, configuration: ApplicationConfiguration) -> None:
        if self._process_baseline.semantics_frozen:
            directory = self._config_path.resolve().parent.parent / "data" / "live-certification"
            endpoint = str(configuration.tushare.api_url)
            for surface, filename, expected in (
                ("STOCK", "stock-semantic.json", self._process_baseline.stock_semantic_revision),
                (
                    "BOARD_INDEX", "index-semantic.json",
                    self._process_baseline.index_semantic_revision,
                ),
            ):
                observed = load_semantic_contract(
                    directory / filename, now=self._clock.now(), endpoint_url=endpoint,
                )
                revision = (
                    observed.semantic_revision
                    if observed is not None and observed.surface == surface
                    else None
                )
                if revision != expected:
                    self._revoke_semantics()
                    raise RuntimeError("monitor semantics changed; safe restart required")

    async def open_database(self) -> None:
        self._require_startup_baseline()
        await to_thread.run_sync(self._open_database_sync)

    def _require_startup_baseline(self) -> None:
        configuration = self._configuration
        if configuration is None or not self.configuration_is_current():
            raise RuntimeError("monitor configuration changed; safe restart required")
        self._require_frozen_semantics(configuration)

    async def admit(self) -> None:
        await to_thread.run_sync(self._admit_sync)

    def _admit_sync(self) -> None:
        observed_at = self._clock.now()
        snapshot = self._liveness.load()
        if snapshot is None:
            snapshot = self._liveness.initialize_empty(observed_at)
        else:
            with SqlAlchemyUnitOfWork(self._session_factory, clock=lambda: observed_at) as work:
                work.expire_active_plans_after_interruption()
                work.commit()
            snapshot = self._liveness.load()
            if snapshot is None:
                raise RuntimeError("runtime liveness disappeared after admission")
        self._liveness_revision = self._liveness.touch(
            observed_at, expected_revision=snapshot.revision
        ).revision
        with self._session_factory() as session:
            self._alert_sweep_target = latest_alert_sequence(session)
        self._alert_sweep_cursor = 0

    async def heartbeat(self) -> None:
        await to_thread.run_sync(self._heartbeat_sync)

    def _heartbeat_sync(self) -> None:
        revision = self._liveness_revision
        if revision is None:
            raise RuntimeError("runtime heartbeat requires successful admission")
        observed_at = self._clock.now()
        self._liveness_revision = self._liveness.touch(
            observed_at, expected_revision=revision
        ).revision
        if self._alert_sweep_cursor >= self._alert_sweep_target:
            return
        try:
            with self._session_factory.begin() as session:
                batch = sweep_invalidated_alerts(
                    session,
                    after_sequence=self._alert_sweep_cursor,
                    through_sequence=self._alert_sweep_target,
                    expected_liveness_revision=self._liveness_revision,
                    now=observed_at,
                )
        except (DeliveryMetadataError, SQLAlchemyError, TypeError, ValueError):
            _LOGGER.warning("Alert invalidation sweep will retry: code=ALERT_SWEEP_FAILED")
            return
        self._alert_sweep_cursor = (
            self._alert_sweep_target
            if batch.scanned < MAX_SWEEP_BATCH else batch.next_sequence
        )
        if batch.unclassified:
            _LOGGER.warning(
                "Alert invalidation sweep retained unclassified events: count=%d",
                batch.unclassified,
            )

    def _open_database_sync(self) -> None:
        self._require_startup_baseline()
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
        if self._semantic_reload_blocked and not self._configuration_restart_required:
            return self._capabilities
        if self._configuration is not None and not self.configuration_is_current():
            raise RuntimeError("monitor configuration changed; safe restart required")
        if self._semantic_reload_blocked:
            return self._capabilities
        if self._pipeline is not None:
            if self._pipeline._stock_certification_current():
                return self._capabilities
            self._pipeline = None
            self._revoke_semantics()
            self._capabilities = ProviderCapabilities()
            self._stage_errors.update({
                capability: "STOCK_SEMANTICS_UNAVAILABLE"
                for capability in _PROVIDER_CAPABILITIES
            })
            return self._capabilities
        self._capabilities = ProviderCapabilities()
        self._pipeline = None
        self._stage_errors.clear()
        self._stage_retry_at.clear()
        self._provider_checked_at = self._clock.now()
        validated = self._configuration
        if validated is None:
            if self._request_controller.repository_binding_required:
                raise RuntimeError("production configuration must be validated before recovery")
            validated = load_application_config(self._config_path)
        configuration = validated.tushare
        if configuration.api_url is None:
            self._stage_errors.update({
                capability: "TUSHARE_NOT_CONFIGURED"
                for capability in _PROVIDER_CAPABILITIES
            })
            return self._capabilities
        if self._request_controller.repository_binding_required:
            if (
                self._database_status is not RuntimeResourceStatus.READY
                or self._liveness_revision is None
            ):
                raise RuntimeError("provider recovery binding requires local admission")
            if not self._request_controller.repository_bound:
                endpoint_identity = str(configuration.api_url).rstrip("/")
                self._request_controller.bind_recovery_repository(
                    ProviderRecoveryRepository(
                        self._session_factory,
                        provider_identity=_provider_recovery_identity(endpoint_identity),
                    )
                )
        if configuration.token is None:
            self._stage_errors.update({
                capability: "TUSHARE_NOT_CONFIGURED"
                for capability in _PROVIDER_CAPABILITIES
            })
            return self._capabilities
        directory = self._config_path.resolve().parent.parent / "data" / "live-certification"
        endpoint = str(configuration.api_url)
        observed_at = self._clock.now()
        evidence = load_stock_certification(
            directory / "tushare-stock-live.json",
            now=observed_at,
            endpoint_url=endpoint,
        )
        stock_path = directory / "stock-semantic.json"
        stock_semantics = load_semantic_contract(
            stock_path, now=observed_at, endpoint_url=endpoint,
        )
        if stock_semantics is None and not self._process_baseline.semantics_frozen:
            try:
                stock_semantics = import_stock_semantic_contract(
                    directory / "tushare-stock-live.json", stock_path,
                    now=observed_at, endpoint_url=endpoint,
                )
            except OSError:
                stock_semantics = None
        index_path = directory / "index-semantic.json"
        index_semantics = load_semantic_contract(
            index_path, now=observed_at, endpoint_url=endpoint,
        )
        if index_semantics is None and not self._process_baseline.semantics_frozen:
            try:
                index_semantics = import_index_semantic_contract(
                    directory / "tushare-board-index-live.json", index_path,
                    now=observed_at, endpoint_url=endpoint,
                )
            except OSError:
                index_semantics = None
        stock_revision = (
            stock_semantics.semantic_revision
            if stock_semantics is not None and stock_semantics.surface == "STOCK"
            else None
        )
        index_revision = (
            index_semantics.semantic_revision
            if index_semantics is not None and index_semantics.surface == "BOARD_INDEX"
            else None
        )
        baseline = self._process_baseline
        if baseline.semantics_frozen:
            if (
                stock_revision != baseline.stock_semantic_revision
                or index_revision != baseline.index_semantic_revision
            ):
                self._revoke_semantics()
                return self._capabilities
        else:
            baseline.stock_semantic_revision = stock_revision
            baseline.index_semantic_revision = index_revision
            baseline.semantics_frozen = True
        if evidence is not None:
            self._capabilities = evidence.capabilities
        if evidence is not None and evidence.source_time_label is SourceTimeLabel.UNVERIFIED:
            self._capabilities = self._capabilities.model_copy(
                update={
                    "realtime_minutes": ProviderCapabilityStatus.UNVERIFIED,
                    "current_day_minutes": ProviderCapabilityStatus.UNVERIFIED,
                }
            )
        if stock_semantics is None or stock_semantics.surface != "STOCK":
            self._stage_errors.update({
                capability: "STOCK_SEMANTICS_UNAVAILABLE"
                for capability in _PROVIDER_CAPABILITIES
            })
        if (
            stock_semantics is not None
            and stock_semantics.surface == "STOCK"
            and self._runtime_generation is not None
            and self._publisher is not None
        ):
            generation = self._runtime_generation()
            index_binding = (
                SemanticContractBinding(index_path, index_semantics.semantic_revision)
                if index_semantics is not None and index_semantics.surface == "BOARD_INDEX"
                else None
            )
            self._pipeline = ProductionMonitorPipeline(
                configuration=configuration,
                certification_directory=directory,
                stock_certification=None,
                clock=self._clock,
                request_controller=self._request_controller,
                unit_of_work_factory=self.unit_of_work_factory,
                runtime_generation=generation,
                publisher=self._publisher,
                semantic_bindings=ProductionSemanticBindings(
                    stock=SemanticContractBinding(
                        stock_path, stock_semantics.semantic_revision,
                    ),
                    index=index_binding,
                ),
                recovery_session_factory=self._session_factory,
                configuration_current=self.configuration_is_current,
                admission_revoked=self._process_baseline.revoked.is_set,
                on_semantic_revoked=self._revoke_semantics,
                generation_current=lambda: (
                    self._database_status is RuntimeResourceStatus.READY
                    and self._business_commit_admission_open()
                    and self._runtime_generation() == generation
                ),
            )
        return self._capabilities

    def can_schedule(self, _capabilities: ProviderCapabilities) -> bool:
        """Semantic compatibility permits guarded requests; health stays observation-based."""

        return self._pipeline is not None

    async def refresh_references(self, trade_date: date) -> None:
        if self._pipeline is not None:
            try:
                await self._pipeline.refresh_references(trade_date)
            except Exception as error:
                stage = self._pipeline.reference_stage.value
                code = "REFERENCE_REFRESH_FAILED"
                if isinstance(error, RequestControlError):
                    code = f"REFERENCE_{error.code.value}"
                elif isinstance(error, SQLAlchemyError):
                    code = "REFERENCE_STORAGE_ERROR"
                elif isinstance(error, ReferenceDataUnavailableError):
                    code = "REFERENCE_DATA_UNAVAILABLE"
                self._stage_errors[stage] = code
                self._stage_retry_at.pop(stage, None)
                if isinstance(error, RequestControlError) and error.next_retry_at is not None:
                    self._stage_retry_at[stage] = error.next_retry_at
                # Only closed categories; never log exception text, traceback or provider data.
                _LOGGER.warning("Reference refresh failed: stage=%s code=%s", stage, code)
                if self._on_reference_failure is not None:
                    self._on_reference_failure(code)
                raise
            else:
                for stage in ("trading_calendar", "daily_limits", "daily_bars"):
                    self._stage_errors.pop(stage, None)
                    self._stage_retry_at.pop(stage, None)

    async def recover_startup(self, trade_date: date) -> None:
        if self._pipeline is not None:
            try:
                await self._pipeline.recover_startup(trade_date)
            except Exception:
                self._stage_errors["current_day_minutes"] = "STARTUP_RECOVERY_FAILED"
                raise
            if self._dispatcher is not None:
                await self._dispatcher.dispatch_pending()

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

    async def run_deadline(self, deadline: MarketDeadline) -> object:
        if self._pipeline is None:
            raise RuntimeError("live monitor requires a certified production pipeline")
        result = await self._pipeline.run_deadline(deadline)
        if self._dispatcher is not None:
            await self._dispatcher.dispatch_pending()
        return result

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
        providers = []
        for capability in _PROVIDER_CAPABILITIES:
            operation = TushareOperation(capability)
            blocked = self._request_controller.is_permission_blocked(operation)
            permission_due = (
                self._request_controller.permission_retry_at(operation) if blocked else None
            )
            observation_at = self._clock.now() if blocked else checked_at
            providers.append(ProviderHealthSnapshot(
                capability=capability,
                status=(
                    ProviderCapabilityStatus.BLOCKED_PERMISSION if blocked
                    else ProviderCapabilityStatus.ERROR if capability in self._stage_errors
                    else getattr(self._capabilities, capability)
                ),
                checked_at=observation_at,
                latency_ms=0,
                error_code=(
                    "BLOCKED_PERMISSION" if blocked else self._stage_errors.get(capability)
                ),
                next_retry_at=(
                    max(observation_at, permission_due) if permission_due is not None
                    else self._stage_retry_at.get(capability)
                ),
            ))
        return RuntimeHealthDetails(
            recovery_issues=(() if self._pipeline is None else self._pipeline.recovery_issues()),
            providers=tuple(providers),
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
            delivery=self._delivery_health(),
            cooldown_until=self._request_controller.cooldown_until,
        )

    def _delivery_health(self) -> DeliveryHealthSnapshot:
        if self._pipeline is None or self._database_status is not RuntimeResourceStatus.READY:
            return DeliveryHealthSnapshot(
                status=RuntimeResourceStatus.UNVERIFIED,
                pending_count=0,
                failed_count=0,
            )
        latest = (
            select(DeliveryAttempt.event_id, func.max(DeliveryAttempt.attempt).label("attempt"))
            .where(DeliveryAttempt.channel == "IN_APP")
            .group_by(DeliveryAttempt.event_id)
            .subquery()
        )
        attempts = (
            select(DeliveryAttempt)
            .join(
                latest,
                and_(
                    DeliveryAttempt.event_id == latest.c.event_id,
                    DeliveryAttempt.attempt == latest.c.attempt,
                    DeliveryAttempt.channel == "IN_APP",
                ),
            )
            .subquery()
        )
        statement = (
            select(attempts.c.status, func.count(AlertEvent.id))
            .select_from(AlertEvent)
            .outerjoin(attempts, attempts.c.event_id == AlertEvent.id)
            .group_by(attempts.c.status)
        )
        with self._session_factory() as session:
            counts = dict(session.execute(statement).all())
        failed = counts.get("FAILED", 0)
        pending = sum(
            count for status, count in counts.items() if status not in {"DELIVERED", "FAILED"}
        )
        return DeliveryHealthSnapshot(
            status=RuntimeResourceStatus.DEGRADED if failed else RuntimeResourceStatus.READY,
            pending_count=pending,
            failed_count=failed,
            error_code="DELIVERY_FAILED" if failed else None,
        )

    def unit_of_work_factory(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            self._session_factory,
            clock=self._clock.now,
        )

    def configuration_is_current(self) -> bool:
        if self._configuration_restart_required or self._process_baseline.revoked.is_set():
            return False
        try:
            current = (
                self._configuration is not None
                and load_application_config(self._config_path).tushare
                == self._configuration.tushare
            )
        except Exception:
            current = False
        if not current and self._configuration is not None:
            self._revoke_configuration()
        return current

    def _revoke_configuration(self) -> None:
        """Publish revocation now; leave the visible latch to the owning loop."""

        self._process_baseline.revoked.set()
        loop = self._owner_loop
        if loop is None:
            self._configuration_restart_required = True
            return
        try:
            same_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            same_loop = False
        if same_loop:
            self._configuration_restart_required = True
        else:
            loop.call_soon_threadsafe(self._set_configuration_restart_required)

    def _set_configuration_restart_required(self) -> None:
        self._configuration_restart_required = True

    def _revoke_semantics(self) -> None:
        self._process_baseline.revoked.set()
        loop = self._owner_loop
        if loop is None:
            self._semantic_reload_blocked = True
            return
        try:
            same_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            same_loop = False
        if same_loop:
            self._semantic_reload_blocked = True
        else:
            loop.call_soon_threadsafe(self._set_semantic_reload_blocked)

    def _set_semantic_reload_blocked(self) -> None:
        self._semantic_reload_blocked = True

    def configuration_restart_required(self) -> bool:
        """Latch relevant configuration or installed semantic drift until stop."""

        if self._configuration is None:
            return self._process_baseline.revoked.is_set()
        if not self.configuration_is_current() or self._semantic_reload_blocked:
            return True
        pipeline = self._pipeline
        if pipeline is None:
            return False
        if not pipeline._stock_certification_current() or (
            pipeline._index_semantics is not None
            and not pipeline._index_certification_current()
        ):
            self._revoke_semantics()
        return self._semantic_reload_blocked


def create_monitor_composition_factory(
    *,
    config_path: Path,
    database_path: Path,
    on_reference_failure: Callable[[str], None] | None = None,
) -> Callable[[], MonitorWebComposition]:
    """Capture paths without configuration, database, provider, or task work."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a Path")
    if on_reference_failure is not None and not callable(on_reference_failure):
        raise TypeError("on_reference_failure must be callable")

    def factory() -> MonitorWebComposition:
        return create_monitor_composition(
            config_path=config_path,
            database_path=database_path,
            on_reference_failure=on_reference_failure,
        )

    return factory


def create_monitor_composition(
    *,
    config_path: Path,
    database_path: Path,
    on_reference_failure: Callable[[str], None] | None = None,
) -> MonitorWebComposition:
    """Compose certified providers and the recoverable local monitoring runtime."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a Path")
    if on_reference_failure is not None and not callable(on_reference_failure):
        raise TypeError("on_reference_failure must be callable")
    clock = SystemClock()
    process_baseline = _ProcessRuntimeBaseline()
    engine = create_sqlite_engine(database_path)
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock=clock.now)

    health_binding = _HealthBinding()
    stream = CommittedMonitorEventStream(
        unit_of_work_factory=unit_of_work_factory,
        runtime_liveness_provider=health_binding,
        clock=clock.now,
    )

    def runtime_factory() -> RuntimeLifecycleService:
        request_controller = create_live_tushare_request_controller(
            clock=clock, require_repository_binding=True,
        )
        request_controller.set_runtime_admission(
            lambda: not process_baseline.revoked.is_set()
        )
        current_delivery_admission = CurrentDeliveryAdmission(
            session_factory,
            runtime_generation=lambda: lifecycle.runtime_generation,
        )

        def delivery_admission(event, now) -> bool:
            return (
                not state.configuration_restart_required()
                and current_delivery_admission(event, now)
                and not process_baseline.revoked.is_set()
            )

        dispatcher = NotificationDispatcher(
            session_factory,
            channels=(InAppChannel(),),
            clock=clock.now,
            enforce_current_plan=True,
            admission=delivery_admission,
        )
        state = _ProductionRuntimeState(
            config_path=config_path,
            database_path=database_path,
            engine=engine,
            session_factory=session_factory,
            clock=clock,
            request_controller=request_controller,
            process_baseline=process_baseline,
            runtime_generation=lambda: lifecycle.runtime_generation,
            business_commit_admission_open=lambda: lifecycle.business_commit_admission_open,
            publisher=stream.publish_committed,
            dispatcher=dispatcher,
            on_reference_failure=on_reference_failure,
        )
        scheduler = MarketSessionScheduler(
            clock=clock,
            is_open_on=state.is_open_on,
            next_index_recovery_at=state.next_index_recovery_at,
        )
        lifecycle = RuntimeLifecycleService(
            clock=clock,
            validate_configuration=state.validate_configuration,
            configuration_restart_required=state.configuration_restart_required,
            open_database=state.open_database,
            load_active_symbols=state.load_active_symbols,
            probe_capabilities=state.probe_capabilities,
            can_schedule=state.can_schedule,
            refresh_references=state.refresh_references,
            recover_startup=state.recover_startup,
            scheduler=scheduler,
            run_deadline=state.run_deadline,
            dispatcher=dispatcher,
            request_controller=request_controller,
            checkpoint_wal=state.checkpoint_wal,
            close_database=state.close_database,
            health_details=state.health_details,
            liveness_owner=state,
        )
        return lifecycle

    runtime = runtime_factory()
    read_service = PersistentMonitorReadService(
        unit_of_work_factory,
        health_binding,
        clock=clock.now,
    )
    market_index_read_service = SignedMarketIndexHistoryService(
        source=PersistentMarketIndexHistorySource(unit_of_work_factory),
        cursor_signer=BacktestApiCursorSigner(
            load_or_create_cursor_key(database_path.with_suffix(".cursor.key"))
        ),
    )
    composition = MonitorWebComposition(
        runtime=runtime,
        runtime_factory=runtime_factory,
        read_service=read_service,
        websocket_service=stream,
        position_service=PersistentPositionOperationService(
            unit_of_work_factory=unit_of_work_factory,
            clock=clock.now,
        ),
        manual_event_risk_service=PersistentManualEventRiskOperationService(
            unit_of_work_factory=unit_of_work_factory,
            clock=clock.now,
        ),
        alert_service=PersistentAlertOperationService(
            unit_of_work_factory=unit_of_work_factory,
            clock=clock.now,
        ),
        market_index_read_service=market_index_read_service,
        legacy_maintenance_factory=unit_of_work_factory,
    )
    health_binding.bind(composition.health)
    return composition


__all__ = [
    "MonitorRuntime",
    "MonitorWebComposition",
    "create_monitor_composition",
    "create_monitor_composition_factory",
]
