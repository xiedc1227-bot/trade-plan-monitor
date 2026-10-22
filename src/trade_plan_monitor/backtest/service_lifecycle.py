"""On-demand capability initialization with independent error and drain ownership."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from re import fullmatch
from typing import Protocol
from uuid import uuid4

from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_contract import (
    BacktestServiceSnapshot,
    BacktestServiceState,
)
from trade_plan_monitor.backtest.thread_ownership import BacktestThreadOwner

_LOGGER = logging.getLogger(__name__)


class BacktestServiceUnavailable(RuntimeError):
    """A capability is unavailable; no operation has been admitted by this gate."""


class BacktestControlConflict(ValueError):
    """A control targets a stale epoch/revision or undrained physical work."""


class BacktestLifecycle(Protocol):
    @property
    def read_service(self) -> object: ...

    @property
    def operation_service(self) -> object: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class LazyBacktestLifecycle:
    """No factory call, executor, I/O or background task until explicit use."""

    def __init__(
        self, factory: Callable[[], BacktestLifecycle], *,
        config: BacktestServiceConfig | None = None,
    ) -> None:
        self._factory = factory
        self._config = config or BacktestServiceConfig()
        self._owner = BacktestThreadOwner()
        self._instance: BacktestLifecycle | None = None
        self._preparation: asyncio.Task[None] | None = None
        self._activation: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._state = BacktestServiceState.NOT_INITIALIZED
        self._generation = 0
        self._stopping = False
        self._metadata_ready = False
        self.epoch = uuid4().hex
        self.control_revision = 0
        self._control_task: asyncio.Task[None] | None = None
        self._control_receipts: dict[str, tuple[tuple, int]] = {}

    def request_control(self, *, epoch, revision, key, action, job_ids=()):
        """Acknowledge one explicit control without waiting for physical completion."""
        intent = (epoch, revision, action, tuple(job_ids))
        if epoch != self.epoch:
            raise BacktestControlConflict()
        previous = self._control_receipts.get(key)
        if previous is not None:
            if previous[0] != intent:
                raise BacktestControlConflict()
            return previous[1]
        if revision != self.control_revision or (
            self._control_task is not None and not self._control_task.done()
        ):
            raise BacktestControlConflict()
        if action not in {"STOP", "RETRY_PREPARATION", "RESUME_JOBS"} or (
            action == "RESUME_JOBS" and len(job_ids) != 1
        ) or (action != "RESUME_JOBS" and job_ids):
            raise BacktestControlConflict()
        if action == "RETRY_PREPARATION" and not self.snapshot.physically_drained:
            raise BacktestControlConflict()
        self.control_revision += 1
        if len(self._control_receipts) == 1000:
            del self._control_receipts[next(iter(self._control_receipts))]
        self._control_receipts[key] = (intent, self.control_revision)
        self._control_task = asyncio.create_task(self._run_control(action, frozenset(job_ids)))
        return self.control_revision

    async def _run_control(self, action, job_ids):
        try:
            if action == "STOP":
                await self.stop()
            elif action == "RETRY_PREPARATION":
                await self.retry()
                await self.ensure()
            else:
                await self.resume_jobs(job_ids)
        except Exception:
            # Safe status only; store/provider diagnostics never cross this boundary.
            self._state = BacktestServiceState.DEGRADED

    @property
    def snapshot(self) -> BacktestServiceSnapshot:
        tasks = (self._preparation, self._activation, self._cleanup)
        outstanding = sum(task is not None and not task.done() for task in tasks)
        return BacktestServiceSnapshot(
            state=self._state, generation=self._generation,
            authorized_job_ids=getattr(self._instance, "authorized_job_ids", frozenset()),
            outstanding_work=max(
                outstanding, self._owner.outstanding_work,
                getattr(self._instance, "outstanding_work", 0),
            ),
            read_capability_available=self._metadata_ready,
        )

    async def ensure(self, *, execution: bool = False) -> BacktestLifecycle:
        if self._stopping or (
            self._state is BacktestServiceState.DEGRADED and (execution or not self._metadata_ready)
        ):
            raise BacktestServiceUnavailable()
        if self._preparation is None:
            self._preparation = asyncio.create_task(self._prepare(self._generation))
        await self._observe(self._preparation, self._config.request_wait_seconds)
        if self._stopping or (
            self._state is BacktestServiceState.DEGRADED and (execution or not self._metadata_ready)
        ):
            raise BacktestServiceUnavailable()
        if execution:
            if self._activation is None:
                self._activation = asyncio.create_task(self._activate())
            await self._observe(self._activation, self._config.request_wait_seconds)
        if self._stopping or self._instance is None:
            raise BacktestServiceUnavailable()
        return self._instance

    async def _prepare(self, generation: int) -> None:
        self._state = BacktestServiceState.STARTING
        future = asyncio.wrap_future(self._owner.submit(self._factory))
        try:
            try:
                self._instance = await asyncio.wait_for(
                    asyncio.shield(future), self._config.initialization_watchdog_seconds,
                )
            except TimeoutError:
                _LOGGER.warning(
                    "Backtest metadata preparation watchdog expired; owned work is still draining"
                )
                self._state = BacktestServiceState.DEGRADED
                # Keep the physical call and any late acquired resources owned.
                self._instance = await asyncio.shield(future)
                return
            if any(not callable(getattr(self._instance, name, None)) for name in ("start", "stop")):
                raise TypeError("backtest lifecycle must expose start and stop")
            if not hasattr(self._instance, "read_service") or not hasattr(
                self._instance, "operation_service",
            ):
                raise TypeError("backtest lifecycle must expose both services")
            if not self._stopping and generation == self._generation:
                self._metadata_ready = True
                self._state = BacktestServiceState.READ_READY
        except Exception as error:
            # Resolve store errors only on failure; unused startup stays inert.
            from trade_plan_monitor.backtest.migration import MigrationPreflightError

            code = "UNCLASSIFIED"
            if (
                isinstance(error, MigrationPreflightError)
                and isinstance(error.code, str)
                and fullmatch(r"[A-Z][A-Z0-9_]{0,95}", error.code)
            ):
                code = error.code
            origin = error.__traceback__
            while origin is not None and origin.tb_next is not None:
                origin = origin.tb_next
            # Exception messages, file paths and source lines may contain secrets.
            _LOGGER.warning(
                "Backtest metadata preparation failed: %s code=%s errno=%s "
                "winerror=%s origin=%s:%s generation=%s",
                type(error).__name__, code,
                error.errno if isinstance(error, OSError) else None,
                getattr(error, "winerror", None) if isinstance(error, OSError) else None,
                origin.tb_frame.f_code.co_name if origin is not None else "unknown",
                origin.tb_lineno if origin is not None else 0, generation,
            )
            self._state = BacktestServiceState.DEGRADED
            raise BacktestServiceUnavailable() from None

    async def _activate(self) -> None:
        try:
            await self._instance.start()
            if not self._stopping:
                self._state = BacktestServiceState.READY
        except Exception:
            self._state = BacktestServiceState.DEGRADED
            raise BacktestServiceUnavailable() from None

    async def _observe(self, task: asyncio.Task, timeout: float) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        except TimeoutError:
            raise BacktestServiceUnavailable() from None

    async def stop(self) -> None:
        if self._control_task is not None and self._control_task is not asyncio.current_task():
            await asyncio.shield(self._control_task)
        self._stopping = True
        self._metadata_ready = False
        if self._cleanup is not None and self._cleanup.done() and self._cleanup.exception():
            self._cleanup = None
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._drain_and_close())
        try:
            await self._observe(self._cleanup, self._config.shutdown_wait_seconds)
        except BacktestServiceUnavailable:
            self._state = BacktestServiceState.DEGRADED
            raise

    async def _drain_and_close(self) -> None:
        self._state = BacktestServiceState.STOPPING
        for task in (self._preparation, self._activation):
            if task is not None:
                await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        if self._instance is not None:
            await self._instance.stop()
        self._owner.close()
        self._state = BacktestServiceState.STOPPED

    async def wait_for_drain(self) -> None:
        """Wait on the already requested cleanup, without preparing unused resources."""
        if self._cleanup is not None:
            await asyncio.shield(self._cleanup)

    async def retry(self) -> None:
        """Explicit repair only after physical work and prior resources drain."""
        if not self.snapshot.physically_drained:
            raise BacktestServiceUnavailable()
        await self.stop()
        self._generation += 1
        self._owner = BacktestThreadOwner()
        self._instance = None
        self._preparation = self._activation = self._cleanup = None
        self._stopping = False
        self._metadata_ready = False
        self._state = BacktestServiceState.NOT_INITIALIZED

    async def resume_jobs(self, job_ids: frozenset[str]) -> None:
        if (
            not isinstance(job_ids, frozenset)
            or not 1 <= len(job_ids) <= self._config.max_resume_jobs
        ):
            raise ValueError("resume requires a bounded explicit selection")
        instance = await self.ensure(execution=True)
        await instance.resume_jobs(job_ids)
