"""Bounded runtime admission for synchronous Tushare and asynchronous AI work."""

from __future__ import annotations

import asyncio
import inspect
import math
import random
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from hashlib import sha256
from itertools import count
from typing import Final, TypeVar

import requests

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import Clock, _canonical_shanghai
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpoint,
    RecoveryCheckpointError,
)

T = TypeVar("T")

DEFAULT_TUSHARE_EXECUTOR_WORKERS: Final = 2
DEFAULT_TUSHARE_MAX_CONCURRENCY: Final = 2
DEFAULT_MIN_INTERVAL: Final = timedelta(seconds=1)
DEFAULT_JITTER: Final = timedelta(milliseconds=250)
DEFAULT_TIMEOUT_SECONDS: Final = 15
DEFAULT_IN_CYCLE_RETRIES: Final = 2
DEFAULT_SYMBOL_BACKOFF: Final = (
    timedelta(seconds=30),
    timedelta(seconds=60),
    timedelta(seconds=120),
    timedelta(seconds=300),
)
DEFAULT_SHARED_RATE_LIMIT_COOLDOWN: Final = timedelta(seconds=300)
PERMISSION_RECHECK_INTERVAL: Final = timedelta(seconds=300)
DEFAULT_TUSHARE_QUEUE_LIMIT: Final = 32
DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT: Final = 64
LIVE_TUSHARE_EXECUTOR_WORKERS: Final = 1
LIVE_TUSHARE_MAX_CONCURRENCY: Final = 1
LIVE_TUSHARE_MIN_INTERVAL: Final = timedelta(milliseconds=1_250)
LIVE_TUSHARE_TIMEOUT_SECONDS: Final = 15
LIVE_TUSHARE_IN_CYCLE_RETRIES: Final = 0
DEFAULT_AI_MAX_CONCURRENCY: Final = 1
DEFAULT_AI_QUEUE_LIMIT: Final = 5
_MAX_BACKOFF_STEPS: Final = 16
_MAX_WORK_KEY_LENGTH: Final = 128


class TushareOperation(StrEnum):
    """Stable provider operations controlled independently where required."""

    PROBE_CAPABILITIES = "probe_capabilities"
    REALTIME_MINUTES = "realtime_minutes"
    CURRENT_DAY_MINUTES = "current_day_minutes"
    HISTORICAL_MINUTES = "historical_minutes"
    TRADING_CALENDAR = "trading_calendar"
    DAILY_LIMITS = "daily_limits"
    DAILY_BARS = "daily_bars"
    INDEX_MINUTES = "index_minutes"
    INDEX_DAILY = "index_daily"


class RequestPriority(IntEnum):
    """Queued provider work order; running synchronous calls are not preempted."""

    MARKET_DEADLINE = 0
    RECOVERY = 10
    BACKGROUND = 20


class RequestControlErrorCode(StrEnum):
    """Sanitized runtime request-control outcomes."""

    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    ERROR = "ERROR"
    QUEUE_FULL = "QUEUE_FULL"
    CLOSED = "CLOSED"


class RequestControlError(RuntimeError):
    """One bounded Tushare request failure with no provider response details."""

    def __init__(
        self,
        code: RequestControlErrorCode,
        operation: TushareOperation,
        *,
        attempts: int,
        next_retry_at: datetime | None = None,
    ) -> None:
        if not isinstance(code, RequestControlErrorCode):
            raise TypeError("code must be a RequestControlErrorCode")
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        if type(attempts) is not int or not 0 <= attempts <= 3:
            raise ValueError("attempts must be between 0 and 3")
        if next_retry_at is not None:
            next_retry_at = _canonical_shanghai(next_retry_at)
        self.code = code
        self.operation = operation
        self.attempts = attempts
        self.next_retry_at = next_retry_at
        super().__init__(f"runtime {operation.value} failed ({code.value})")


class RequestNotStartedError(RuntimeError):
    """A worker's local guard rejected work before provider I/O.

    This is neither provider success nor failure: retain retry/permission state.
    Callers may raise it only before contacting the provider.
    """


class AIQueueFullError(RuntimeError):
    """The bounded AI admission queue has no remaining waiting slot."""

    def __init__(self) -> None:
        super().__init__("AI request queue is full")


class _QueueFullError(RuntimeError):
    pass


@dataclass(slots=True)
class _Waiter:
    priority: int
    sequence: int
    event: asyncio.Event = field(default_factory=asyncio.Event)
    granted: bool = False
    rejected: bool = False


class _PrioritySlots:
    """Event-loop-owned priority admission without background worker tasks."""

    __slots__ = ("_active", "_limit", "_max_waiters", "_sequence", "_waiters")

    def __init__(self, limit: int, *, max_waiters: int | None = None) -> None:
        self._limit = limit
        self._max_waiters = max_waiters
        self._active = 0
        self._sequence = count()
        self._waiters: list[_Waiter] = []

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)

    async def acquire(self, priority: int) -> None:
        if (
            self._max_waiters is not None
            and self._active >= self._limit
            and len(self._waiters) >= self._max_waiters
        ):
            raise _QueueFullError
        waiter = _Waiter(priority=priority, sequence=next(self._sequence))
        self._waiters.append(waiter)
        self._grant_waiters()
        try:
            await waiter.event.wait()
        except BaseException:
            if waiter.granted:
                self.release()
            else:
                self._waiters.remove(waiter)
                self._grant_waiters()
            raise

    def release(self) -> None:
        if self._active < 1:
            raise RuntimeError("request-control slot underflow")
        self._active -= 1
        self._grant_waiters()

    def _grant_waiters(self) -> None:
        while self._active < self._limit and self._waiters:
            waiter = min(
                self._waiters,
                key=lambda candidate: (candidate.priority, candidate.sequence),
            )
            self._waiters.remove(waiter)
            waiter.granted = True
            self._active += 1
            waiter.event.set()


class _ProviderAdmission:
    """Grant physical provider starts by priority, capacity, and global pacing."""

    __slots__ = (
        "_active",
        "_jitter",
        "_jitter_source",
        "_limit",
        "_max_waiters",
        "_min_interval",
        "_monotonic",
        "_next_start_monotonic",
        "_pace_sleep",
        "_sequence",
        "_waiters",
    )

    def __init__(
        self,
        *,
        limit: int,
        min_interval: timedelta,
        jitter: timedelta,
        jitter_source: Callable[[], float],
        max_waiters: int,
        monotonic: Callable[[], float],
        pace_sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._limit = limit
        self._min_interval = min_interval
        self._jitter = jitter
        self._jitter_source = jitter_source
        self._max_waiters = max_waiters
        self._monotonic = monotonic
        self._pace_sleep = pace_sleep
        self._active = 0
        self._next_start_monotonic: float | None = None
        self._sequence = count()
        self._waiters: list[_Waiter] = []

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)

    def defer_first_start(self) -> None:
        """Keep a new owner's first start clear of the previous owner's last start."""

        now = self._monotonic()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("monotonic must return a finite non-negative value")
        self._next_start_monotonic = now + self._min_interval.total_seconds()

    async def acquire(
        self,
        priority: int,
        before_start: Callable[[], RequestControlError | None],
    ) -> None:
        if len(self._waiters) >= self._max_waiters:
            displaced = max(
                self._waiters,
                key=lambda candidate: (candidate.priority, candidate.sequence),
            )
            if priority >= displaced.priority:
                raise _QueueFullError
            self._waiters.remove(displaced)
            displaced.rejected = True
            displaced.event.set()
        waiter = _Waiter(priority=priority, sequence=next(self._sequence))
        self._waiters.append(waiter)
        self._wake_waiters()
        try:
            while True:
                waiter.event.clear()
                if waiter.rejected:
                    raise _QueueFullError
                blocked = before_start()
                if blocked is not None:
                    raise blocked from None
                if self._is_next(waiter):
                    now = self._monotonic()
                    if (
                        type(now) not in (int, float)
                        or not math.isfinite(now)
                        or now < 0
                    ):
                        raise ValueError("monotonic must return a finite non-negative value")
                    if (
                        self._next_start_monotonic is None
                        or now >= self._next_start_monotonic
                    ):
                        blocked = before_start()
                        if blocked is not None:
                            raise blocked from None
                        next_start = self._calculate_next_start(now)
                        self._waiters.remove(waiter)
                        waiter.granted = True
                        self._active += 1
                        self._next_start_monotonic = next_start
                        self._wake_waiters()
                        return
                    await self._wait_for_time_or_change(
                        waiter,
                        self._next_start_monotonic - now,
                    )
                    continue
                await waiter.event.wait()
        except BaseException:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
                self._wake_waiters()
            raise

    def release(self) -> None:
        if self._active < 1:
            raise RuntimeError("provider admission underflow")
        self._active -= 1
        self._wake_waiters()

    def notify_state_change(self) -> None:
        """Wake queued requests so controller state can be re-evaluated."""

        self._wake_waiters()

    def _is_next(self, waiter: _Waiter) -> bool:
        if self._active >= self._limit:
            return False
        return waiter is min(
            self._waiters,
            key=lambda candidate: (candidate.priority, candidate.sequence),
        )

    def _calculate_next_start(self, now: float) -> float:
        factor = self._jitter_source()
        if type(factor) not in (int, float) or not math.isfinite(factor) or not 0 <= factor <= 1:
            raise ValueError("jitter_source must return a finite value from 0 to 1")
        return (
            now
            + self._min_interval.total_seconds()
            + self._jitter.total_seconds() * float(factor)
        )

    async def _wait_for_time_or_change(
        self,
        waiter: _Waiter,
        delay_seconds: float,
    ) -> None:
        sleep_task = asyncio.create_task(self._pace_sleep(max(0.0, delay_seconds)))
        change_task = asyncio.create_task(waiter.event.wait())
        tasks = (sleep_task, change_task)
        completed: set[asyncio.Task[None]] = set()
        try:
            completed, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        if sleep_task in completed and isinstance(results[0], BaseException):
            raise results[0]

    def _wake_waiters(self) -> None:
        for waiter in self._waiters:
            waiter.event.set()


_TUSHARE_ERROR_CODES: Final = {
    TushareErrorCode.BLOCKED_PERMISSION: RequestControlErrorCode.BLOCKED_PERMISSION,
    TushareErrorCode.RATE_LIMITED: RequestControlErrorCode.RATE_LIMITED,
    TushareErrorCode.TRANSIENT: RequestControlErrorCode.TRANSIENT,
    TushareErrorCode.TIMEOUT: RequestControlErrorCode.TIMEOUT,
    TushareErrorCode.INVALID_RESPONSE: RequestControlErrorCode.INVALID_RESPONSE,
    TushareErrorCode.ERROR: RequestControlErrorCode.ERROR,
}


class TushareRequestController:
    """Own a two-thread executor and bounded, priority-aware provider attempts."""

    __slots__ = (
        "_backoff",
        "_backoff_failures",
        "_backoff_until",
        "_blocked_operations",
        "_clock",
        "_closed",
        "_cooldown_until",
        "_admission",
        "_executor",
        "_executor_workers",
        "_in_cycle_retries",
        "_inflight_futures",
        "_max_concurrency",
        "_monotonic",
        "_pace_sleep",
        "_rate_limit_cooldown",
        "_timeout_seconds",
        "_permission_retry_at",
        "_permission_rechecks",
        "_recovery_repository",
        "_repository_required",
        "_recovery_fault",
        "_persisted_recovery",
        "_runtime_admission_open",
    )

    def __init__(
        self,
        *,
        clock: Clock,
        executor_workers: int = DEFAULT_TUSHARE_EXECUTOR_WORKERS,
        max_concurrency: int = DEFAULT_TUSHARE_MAX_CONCURRENCY,
        min_interval: timedelta = DEFAULT_MIN_INTERVAL,
        jitter: timedelta = DEFAULT_JITTER,
        jitter_source: Callable[[], float] = random.random,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        in_cycle_retries: int = DEFAULT_IN_CYCLE_RETRIES,
        backoff: tuple[timedelta, ...] = DEFAULT_SYMBOL_BACKOFF,
        rate_limit_cooldown: timedelta = DEFAULT_SHARED_RATE_LIMIT_COOLDOWN,
        monotonic: Callable[[], float] = time.monotonic,
        pace_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        recovery_repository: ProviderRecoveryRepository | None = None,
        require_repository_binding: bool = False,
    ) -> None:
        if type(require_repository_binding) is not bool:
            raise TypeError("require_repository_binding must be a bool")
        self._validate_configuration(
            clock=clock,
            executor_workers=executor_workers,
            max_concurrency=max_concurrency,
            min_interval=min_interval,
            jitter=jitter,
            jitter_source=jitter_source,
            timeout_seconds=timeout_seconds,
            in_cycle_retries=in_cycle_retries,
            backoff=backoff,
            rate_limit_cooldown=rate_limit_cooldown,
            monotonic=monotonic,
            pace_sleep=pace_sleep,
        )
        self._clock = clock
        self._executor_workers = executor_workers
        self._max_concurrency = max_concurrency
        self._timeout_seconds = float(timeout_seconds)
        self._in_cycle_retries = in_cycle_retries
        self._backoff = backoff
        self._rate_limit_cooldown = rate_limit_cooldown
        self._monotonic = monotonic
        self._pace_sleep = pace_sleep
        self._admission = _ProviderAdmission(
            limit=max_concurrency,
            min_interval=min_interval,
            jitter=jitter,
            jitter_source=jitter_source,
            max_waiters=DEFAULT_TUSHARE_QUEUE_LIMIT,
            monotonic=monotonic,
            pace_sleep=pace_sleep,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=executor_workers,
            thread_name_prefix="trade-plan-tushare",
        )
        self._blocked_operations: set[TushareOperation] = set()
        self._backoff_failures: dict[str, int] = {}
        self._backoff_until: dict[str, datetime] = {}
        self._cooldown_until: datetime | None = None
        self._closed = False
        self._runtime_admission_open: Callable[[], bool] = lambda: True
        self._inflight_futures: set[asyncio.Future[object]] = set()
        self._permission_retry_at: dict[TushareOperation, datetime] = {}
        self._permission_rechecks: dict[TushareOperation, asyncio.Task[object]] = {}
        self._recovery_repository: ProviderRecoveryRepository | None = None
        self._repository_required = require_repository_binding
        self._recovery_fault = False
        self._persisted_recovery: tuple[RecoveryCheckpoint, ...] = ()
        if recovery_repository is not None:
            try:
                self.bind_recovery_repository(recovery_repository)
            except RecoveryCheckpointError:
                self._executor.shutdown(wait=False, cancel_futures=True)
                raise

    def bind_recovery_repository(self, repository: ProviderRecoveryRepository) -> None:
        """Install one restored checkpoint before admitting any physical request."""

        if not isinstance(repository, ProviderRecoveryRepository):
            raise TypeError("repository must be a ProviderRecoveryRepository")
        if self._closed or self._recovery_repository is not None:
            raise RecoveryCheckpointError("provider recovery binding is unavailable")
        if (
            self._admission.active_count or self._admission.waiting_count
            or self._inflight_futures or self._permission_rechecks
            or self._backoff_failures or self._blocked_operations
            or self._cooldown_until is not None
        ):
            raise RecoveryCheckpointError("provider recovery binding requires idle admission")
        acquired = False
        try:
            repository.acquire_owner(self)
            acquired = True
            restored = repository.load()
            if self._repository_required:
                self._admission.defer_first_start()
        except BaseException:
            if acquired:
                repository.release_owner(self)
            raise
        self._persisted_recovery = tuple(
            sorted(restored, key=lambda item: (item.kind, item.scope_key))
        )
        for item in restored:
            if item.kind == "cooldown":
                self._cooldown_until = item.retry_at
            elif item.kind == "permission":
                operation = TushareOperation(item.scope_key)
                self._blocked_operations.add(operation)
                self._permission_retry_at[operation] = item.retry_at
            else:
                self._backoff_failures[item.scope_key] = item.failures
                self._backoff_until[item.scope_key] = item.retry_at
        self._recovery_repository = repository

    def _require_bound_repository(self) -> None:
        if self._repository_required and self._recovery_repository is None:
            raise RecoveryCheckpointError("provider recovery checkpoint is not bound")

    @staticmethod
    def _validate_configuration(
        *,
        clock: Clock,
        executor_workers: int,
        max_concurrency: int,
        min_interval: timedelta,
        jitter: timedelta,
        jitter_source: Callable[[], float],
        timeout_seconds: float,
        in_cycle_retries: int,
        backoff: tuple[timedelta, ...],
        rate_limit_cooldown: timedelta,
        monotonic: Callable[[], float],
        pace_sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if type(executor_workers) is not int or not 1 <= executor_workers <= 2:
            raise ValueError("executor_workers must be between 1 and 2")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= executor_workers:
            raise ValueError("max_concurrency must be between 1 and executor_workers")
        for name, value in (("min_interval", min_interval), ("jitter", jitter)):
            if not isinstance(value, timedelta):
                raise TypeError(f"{name} must be a timedelta")
            if value < timedelta(0):
                raise ValueError(f"{name} cannot be negative")
        if not callable(jitter_source):
            raise TypeError("jitter_source must be callable")
        if not callable(monotonic) or not callable(pace_sleep):
            raise TypeError("monotonic and pace_sleep must be callable")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if type(in_cycle_retries) is not int or not 0 <= in_cycle_retries <= 2:
            raise ValueError("in_cycle_retries must be between 0 and 2")
        if type(backoff) is not tuple:
            raise TypeError("backoff must be a tuple")
        if not 1 <= len(backoff) <= _MAX_BACKOFF_STEPS:
            raise ValueError("backoff must contain between 1 and 16 delays")
        previous = timedelta(0)
        for delay in backoff:
            if not isinstance(delay, timedelta):
                raise TypeError("backoff must contain only timedelta values")
            if delay <= previous:
                raise ValueError("backoff delays must be positive and strictly increasing")
            previous = delay
        if not isinstance(rate_limit_cooldown, timedelta):
            raise TypeError("rate_limit_cooldown must be a timedelta")
        if rate_limit_cooldown <= timedelta(0):
            raise ValueError("rate_limit_cooldown must be positive")

    @property
    def executor_workers(self) -> int:
        return self._executor_workers

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def active_count(self) -> int:
        return self._admission.active_count

    @property
    def waiting_count(self) -> int:
        return self._admission.waiting_count

    @property
    def tracked_backoff_count(self) -> int:
        return len(self._backoff_failures)

    @property
    def cooldown_until(self) -> datetime | None:
        return self._cooldown_until

    @property
    def repository_binding_required(self) -> bool:
        return self._repository_required

    @property
    def repository_bound(self) -> bool:
        return self._recovery_repository is not None

    def backoff_until(self, work_key: str) -> datetime | None:
        return self._backoff_until.get(self._storage_key(work_key))

    def is_permission_blocked(self, operation: TushareOperation) -> bool:
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        return operation in self._blocked_operations

    def reset_permission_block(self, operation: TushareOperation) -> None:
        self._require_bound_repository()
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        self._blocked_operations.discard(operation)
        self._permission_retry_at.pop(operation, None)
        self._persist_recovery()

    def permission_retry_at(self, operation: TushareOperation) -> datetime | None:
        """Earliest controlled permission recheck, including shared cooldown."""
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        deadline = self._permission_retry_at.get(operation)
        if deadline is not None and self._cooldown_until is not None:
            return max(deadline, self._cooldown_until)
        return deadline

    async def recheck_permission(
        self,
        operation: TushareOperation,
        call: Callable[[], T],
        *,
        work_key: str,
        priority: RequestPriority = RequestPriority.RECOVERY,
        validate_after: Callable[[], bool] | None = None,
    ) -> T:
        """Coalesce one operation probe while keeping ordinary work blocked.

        Reservation is durable before queue admission. Cancellation of a waiter
        cannot cancel a shared probe or release its reservation early.
        """
        self._require_bound_repository()
        self._validate_request(operation, call, priority)
        self._validate_work_key(work_key)
        if validate_after is not None and not callable(validate_after):
            raise TypeError("validate_after must be callable")
        running = self._permission_rechecks.get(operation)
        if running is None:
            due = self.permission_retry_at(operation)
            if due is None or self._now() < due:
                raise RequestControlError(
                    RequestControlErrorCode.BLOCKED_PERMISSION,
                    operation,
                    attempts=0,
                    next_retry_at=due,
                )
            self._permission_retry_at[operation] = _saturating_add(
                self._now(),
                PERMISSION_RECHECK_INTERVAL,
            )
            self._persist_recovery()

            async def probe() -> T:
                try:
                    result = await self._execute(
                        operation,
                        call,
                        work_key=work_key,
                        priority=priority,
                        permission_recheck=True,
                    )
                    if validate_after is not None and validate_after() is not True:
                        raise RequestControlError(
                            RequestControlErrorCode.INVALID_RESPONSE,
                            operation,
                            attempts=0,
                        )
                    self.reset_permission_block(operation)
                    return result
                finally:
                    self._permission_rechecks.pop(operation, None)

            running = asyncio.create_task(probe())
            # Consume an eventual error even if every waiting caller is cancelled.
            running.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            self._permission_rechecks[operation] = running
        return await asyncio.shield(running)

    async def execute(
        self,
        operation: TushareOperation,
        call: Callable[[], T],
        *,
        work_key: str,
        priority: RequestPriority = RequestPriority.MARKET_DEADLINE,
    ) -> T:
        """Run one repeatable synchronous call under bounded runtime policy."""

        self._require_bound_repository()
        return await self._execute(operation, call, work_key=work_key, priority=priority)

    async def _execute(
        self,
        operation: TushareOperation,
        call: Callable[[], T],
        *,
        work_key: str,
        priority: RequestPriority,
        permission_recheck: bool = False,
    ) -> T:
        self._validate_request(operation, call, priority)
        normalized_key = self._storage_key(work_key)
        blocked = self._preflight_error(operation, normalized_key, permission_recheck)
        if blocked is not None:
            raise blocked from None

        attempts = 0
        while attempts <= self._in_cycle_retries:
            attempts += 1
            result: object = _NO_RESULT
            failure_code: RequestControlErrorCode | None = None
            deferred_error: RequestControlError | None = None
            try:
                result = await self._run_sync_attempt(
                    call,
                    priority,
                    operation,
                    normalized_key,
                    permission_recheck,
                )
            except RequestControlError as caught:
                deferred_error = caught
            except _QueueFullError:
                deferred_error = RequestControlError(
                    RequestControlErrorCode.QUEUE_FULL,
                    operation,
                    attempts=0,
                )
            except (RecoveryCheckpointError, RequestNotStartedError):
                raise
            except Exception as caught:
                failure_code = _provider_failure_code(caught)

            if deferred_error is not None:
                raise deferred_error from None

            if failure_code is None:
                self._backoff_failures.pop(normalized_key, None)
                self._backoff_until.pop(normalized_key, None)
                self._persist_recovery()
                return result  # type: ignore[return-value]

            if failure_code in (
                RequestControlErrorCode.BLOCKED_PERMISSION,
                RequestControlErrorCode.RATE_LIMITED,
            ):
                next_retry_at = self._record_provider_block(failure_code, operation)
                error = RequestControlError(
                    failure_code,
                    operation,
                    attempts=attempts,
                    next_retry_at=next_retry_at,
                )
                raise error from None

            retryable = failure_code in (
                RequestControlErrorCode.TRANSIENT,
                RequestControlErrorCode.TIMEOUT,
            )
            if retryable and attempts <= self._in_cycle_retries and not permission_recheck:
                continue
            next_retry_at = self._record_backoff(normalized_key) if retryable else None
            if retryable and next_retry_at is None:
                error = RequestControlError(
                    RequestControlErrorCode.QUEUE_FULL,
                    operation,
                    attempts=attempts,
                )
                raise error from None
            error = RequestControlError(
                failure_code,
                operation,
                attempts=attempts,
                next_retry_at=next_retry_at,
            )
            raise error from None
        raise AssertionError("bounded request attempt loop exhausted without a result")

    def _validate_request(
        self,
        operation: TushareOperation,
        call: Callable[[], object],
        priority: RequestPriority,
    ) -> None:
        if self._closed:
            raise RequestControlError(
                RequestControlErrorCode.CLOSED,
                operation,
                attempts=0,
            ) from None
        if self._recovery_fault:
            raise RecoveryCheckpointError("provider recovery persistence is faulted")
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        if not callable(call):
            raise TypeError("call must be callable")
        if not isinstance(priority, RequestPriority):
            raise TypeError("priority must be a RequestPriority")

    @staticmethod
    def _validate_work_key(work_key: str) -> str:
        if type(work_key) is not str:
            raise TypeError("work_key must be a string")
        if not work_key or not work_key.strip() or len(work_key) > _MAX_WORK_KEY_LENGTH:
            raise ValueError("work_key must contain between 1 and 128 visible characters")
        return work_key

    def _storage_key(self, work_key: str) -> str:
        key = self._validate_work_key(work_key)
        if self._recovery_repository is None:
            return key
        return sha256(key.encode("utf-8")).hexdigest()

    def _preflight_error(
        self,
        operation: TushareOperation,
        work_key: str,
        permission_recheck: bool = False,
    ) -> RequestControlError | None:
        if self._recovery_fault:
            raise RecoveryCheckpointError("provider recovery persistence is faulted")
        if self._closed or not self._runtime_admission_open():
            return RequestControlError(
                RequestControlErrorCode.CLOSED,
                operation,
                attempts=0,
            )
        if operation in self._blocked_operations and not permission_recheck:
            return RequestControlError(
                RequestControlErrorCode.BLOCKED_PERMISSION,
                operation,
                attempts=0,
                next_retry_at=self.permission_retry_at(operation),
            )
        now = self._now()
        if self._cooldown_until is not None:
            if now < self._cooldown_until:
                return RequestControlError(
                    RequestControlErrorCode.RATE_LIMITED,
                    operation,
                    attempts=0,
                    next_retry_at=self._cooldown_until,
                )
            self._cooldown_until = None
        next_retry_at = self._backoff_until.get(work_key)
        if next_retry_at is not None:
            if now < next_retry_at:
                return RequestControlError(
                    RequestControlErrorCode.TRANSIENT,
                    operation,
                    attempts=0,
                    next_retry_at=next_retry_at,
                )
        if work_key not in self._backoff_failures and not self._reserve_backoff_key(now):
            return RequestControlError(
                RequestControlErrorCode.QUEUE_FULL,
                operation,
                attempts=0,
            )
        return None

    def set_runtime_admission(self, admission_open: Callable[[], bool]) -> None:
        """Bind process revocation to future physical provider attempts."""

        if not callable(admission_open):
            raise TypeError("admission_open must be callable")
        self._runtime_admission_open = admission_open

    async def _run_sync_attempt(
        self,
        call: Callable[[], T],
        priority: RequestPriority,
        operation: TushareOperation,
        work_key: str,
        permission_recheck: bool = False,
    ) -> T:
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(self._timeout_seconds):
            await self._admission.acquire(
                int(priority),
                lambda: self._preflight_error(operation, work_key, permission_recheck),
            )
        future: asyncio.Future[T] | None = None
        slot_held = True
        outcome_observed = False
        timeout_recorded = False

        def release_once() -> None:
            nonlocal slot_held
            if slot_held:
                slot_held = False
                self._admission.release()

        def consume_and_release(completed: asyncio.Future[T]) -> None:
            try:
                if not completed.cancelled():
                    error = completed.exception()
                    if error is not None and not outcome_observed:
                        self._record_late_failure(
                            error, operation, work_key, timeout_recorded=timeout_recorded,
                        )
            except Exception:
                # No awaiting caller remains to receive this storage fault. Keep
                # admission closed and surface it when the runtime joins us.
                self._recovery_fault = True
            finally:
                release_once()
                self._inflight_futures.discard(completed)

        try:
            if permission_recheck:
                self._permission_retry_at[operation] = max(
                    self._permission_retry_at[operation],
                    _saturating_add(self._now(), PERMISSION_RECHECK_INTERVAL),
                )
                self._persist_recovery()
            future = loop.run_in_executor(self._executor, call)
            self._inflight_futures.add(future)
            done, _ = await asyncio.wait((future,), timeout=self._timeout_seconds)
            if future not in done:
                timeout_recorded = True
                raise TimeoutError
            outcome_observed = True
            return future.result()
        finally:
            if future is None:
                release_once()
            elif future.done():
                consume_and_release(future)
            else:
                future.add_done_callback(consume_and_release)

    def _record_provider_block(
        self, code: RequestControlErrorCode, operation: TushareOperation,
    ) -> datetime | None:
        if code is RequestControlErrorCode.BLOCKED_PERMISSION:
            self._blocked_operations.add(operation)
            deadline = _saturating_add(self._now(), PERMISSION_RECHECK_INTERVAL)
            self._permission_retry_at[operation] = max(
                deadline, self._permission_retry_at.get(operation, deadline),
            )
            self._persist_recovery()
            return None
        deadline = _saturating_add(self._now(), self._rate_limit_cooldown)
        self._cooldown_until = max(deadline, self._cooldown_until or deadline)
        self._persist_recovery()
        return self._cooldown_until

    def _record_late_failure(
        self, error: BaseException, operation: TushareOperation, work_key: str,
        *, timeout_recorded: bool,
    ) -> None:
        """Retain a physical failure after its caller cancelled or timed out."""
        code = _provider_failure_code(error)
        if code in (
            RequestControlErrorCode.BLOCKED_PERMISSION,
            RequestControlErrorCode.RATE_LIMITED,
        ):
            self._record_provider_block(code, operation)
        elif not timeout_recorded and code in (
            RequestControlErrorCode.TRANSIENT, RequestControlErrorCode.TIMEOUT,
        ):
            if self._record_backoff(work_key) is None:
                raise RecoveryCheckpointError("late provider backoff capacity exhausted")

    def _record_backoff(self, work_key: str) -> datetime | None:
        now = self._now()
        if work_key not in self._backoff_failures and not self._reserve_backoff_key(now):
            return None
        failure_count = self._backoff_failures.get(work_key, 0)
        delay = self._backoff[min(failure_count, len(self._backoff) - 1)]
        self._backoff_failures[work_key] = min(failure_count + 1, len(self._backoff))
        next_retry_at = _saturating_add(now, delay)
        self._backoff_until[work_key] = next_retry_at
        self._persist_recovery()
        return next_retry_at

    def _persist_recovery(self) -> None:
        if self._recovery_repository is None:
            return
        rows = [
            RecoveryCheckpoint("backoff", key, self._backoff_until[key], failures)
            for key, failures in self._backoff_failures.items()
        ]
        rows.extend(
            RecoveryCheckpoint("permission", operation.value, deadline, 0)
            for operation, deadline in self._permission_retry_at.items()
        )
        if self._cooldown_until is not None:
            rows.append(RecoveryCheckpoint("cooldown", "shared", self._cooldown_until, 0))
        snapshot = tuple(sorted(rows, key=lambda item: (item.kind, item.scope_key)))
        if snapshot == self._persisted_recovery:
            return
        try:
            self._recovery_repository.assert_owner(self)
            self._recovery_repository.save(snapshot)
            self._persisted_recovery = snapshot
        except RecoveryCheckpointError:
            self._recovery_fault = True
            raise

    def _reserve_backoff_key(self, now: datetime) -> bool:
        if len(self._backoff_failures) < DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT:
            return True
        expired = [
            (deadline, work_key)
            for work_key, deadline in self._backoff_until.items()
            if deadline <= now
        ]
        if not expired:
            return False
        _, evicted_key = min(expired)
        self._backoff_failures.pop(evicted_key, None)
        self._backoff_until.pop(evicted_key, None)
        return True

    def _now(self) -> datetime:
        return _canonical_shanghai(self._clock.now())

    def close(self) -> None:
        """Stop admission immediately without blocking the caller's event loop."""

        if self._closed:
            return
        self._closed = True
        self._admission.notify_state_change()
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def aclose(self) -> None:
        """Join bounded provider work before allowing a replacement runtime."""

        self.close()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_seconds
        while (self._inflight_futures or self._permission_rechecks) and loop.time() < deadline:
            await asyncio.sleep(min(0.01, max(0.0, deadline - loop.time())))
        if self._inflight_futures or self._permission_rechecks:
            raise RuntimeError("Tushare executor did not stop within its transport timeout")
        await asyncio.to_thread(
            self._executor.shutdown,
            wait=True,
            cancel_futures=True,
        )
        if self._recovery_fault:
            raise RecoveryCheckpointError("provider outcome could not be checkpointed")
        if self._recovery_repository is not None:
            self._recovery_repository.release_owner(self)


def create_live_tushare_request_controller(
    *,
    clock: Clock,
    monotonic: Callable[[], float] = time.monotonic,
    pace_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    recovery_repository: ProviderRecoveryRepository | None = None,
    require_repository_binding: bool = False,
) -> TushareRequestController:
    """Build the production live profile without inheriting retry-oriented defaults."""

    return TushareRequestController(
        clock=clock,
        executor_workers=LIVE_TUSHARE_EXECUTOR_WORKERS,
        max_concurrency=LIVE_TUSHARE_MAX_CONCURRENCY,
        min_interval=LIVE_TUSHARE_MIN_INTERVAL,
        jitter=timedelta(0),
        jitter_source=lambda: 0.0,
        timeout_seconds=LIVE_TUSHARE_TIMEOUT_SECONDS,
        in_cycle_retries=LIVE_TUSHARE_IN_CYCLE_RETRIES,
        monotonic=monotonic,
        pace_sleep=pace_sleep,
        recovery_repository=recovery_repository,
        require_repository_binding=require_repository_binding,
    )


_NO_RESULT: Final = object()


def _provider_failure_code(error: BaseException) -> RequestControlErrorCode:
    if isinstance(error, (TimeoutError, requests.Timeout)):
        return RequestControlErrorCode.TIMEOUT
    if isinstance(error, requests.ConnectionError):
        return RequestControlErrorCode.TRANSIENT
    if isinstance(error, TushareProviderError):
        return _TUSHARE_ERROR_CODES[error.code]
    return RequestControlErrorCode.ERROR


def _saturating_add(value: datetime, delay: timedelta) -> datetime:
    try:
        return value + delay
    except OverflowError:
        return datetime.max.replace(tzinfo=value.tzinfo)


class AIRequestController:
    """Bound AI coroutines separately without adding provider retries or workers."""

    __slots__ = ("_slots",)

    def __init__(
        self,
        *,
        max_concurrency: int = DEFAULT_AI_MAX_CONCURRENCY,
        queue_limit: int = DEFAULT_AI_QUEUE_LIMIT,
    ) -> None:
        if type(max_concurrency) is not int or max_concurrency != 1:
            raise ValueError("max_concurrency must be exactly 1")
        if type(queue_limit) is not int or not 1 <= queue_limit <= 5:
            raise ValueError("queue_limit must be between 1 and 5")
        self._slots = _PrioritySlots(max_concurrency, max_waiters=queue_limit)

    @property
    def active_count(self) -> int:
        return self._slots.active_count

    @property
    def queue_depth(self) -> int:
        return self._slots.waiting_count

    async def execute(self, call: Callable[[], Awaitable[T]]) -> T:
        """Run one admitted AI coroutine on the application event loop."""

        if not callable(call):
            raise TypeError("call must be callable")
        queue_full = False
        try:
            await self._slots.acquire(0)
        except _QueueFullError:
            queue_full = True
        if queue_full:
            raise AIQueueFullError from None

        try:
            result = call()
            if not inspect.isawaitable(result):
                raise TypeError("call must return an awaitable")
            return await result
        finally:
            self._slots.release()


__all__ = [
    "AIQueueFullError",
    "AIRequestController",
    "DEFAULT_AI_MAX_CONCURRENCY",
    "DEFAULT_AI_QUEUE_LIMIT",
    "DEFAULT_IN_CYCLE_RETRIES",
    "DEFAULT_JITTER",
    "DEFAULT_MIN_INTERVAL",
    "DEFAULT_SHARED_RATE_LIMIT_COOLDOWN",
    "DEFAULT_SYMBOL_BACKOFF",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT",
    "DEFAULT_TUSHARE_EXECUTOR_WORKERS",
    "DEFAULT_TUSHARE_MAX_CONCURRENCY",
    "DEFAULT_TUSHARE_QUEUE_LIMIT",
    "LIVE_TUSHARE_EXECUTOR_WORKERS",
    "LIVE_TUSHARE_IN_CYCLE_RETRIES",
    "LIVE_TUSHARE_MAX_CONCURRENCY",
    "LIVE_TUSHARE_MIN_INTERVAL",
    "LIVE_TUSHARE_TIMEOUT_SECONDS",
    "RequestControlError",
    "RequestControlErrorCode",
    "RequestPriority",
    "TushareOperation",
    "TushareRequestController",
    "create_live_tushare_request_controller",
]
