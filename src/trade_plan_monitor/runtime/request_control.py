"""Bounded runtime admission for synchronous Tushare and asynchronous AI work."""

from __future__ import annotations

import asyncio
import inspect
import math
import random
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from itertools import count
from typing import Final, TypeVar

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import Clock, _canonical_shanghai

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
DEFAULT_TUSHARE_QUEUE_LIMIT: Final = 32
DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT: Final = 64
DEFAULT_AI_MAX_CONCURRENCY: Final = 1
DEFAULT_AI_QUEUE_LIMIT: Final = 5
_MAX_BACKOFF_STEPS: Final = 16
_MAX_WORK_KEY_LENGTH: Final = 128


class TushareOperation(StrEnum):
    """Stable provider operations controlled independently where required."""

    PROBE_CAPABILITIES = "probe_capabilities"
    REALTIME_MINUTES = "realtime_minutes"
    CURRENT_DAY_MINUTES = "current_day_minutes"
    TRADING_CALENDAR = "trading_calendar"
    DAILY_LIMITS = "daily_limits"
    DAILY_BARS = "daily_bars"


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
        "_clock",
        "_jitter",
        "_jitter_source",
        "_limit",
        "_max_waiters",
        "_min_interval",
        "_next_start_at",
        "_sequence",
        "_waiters",
    )

    def __init__(
        self,
        *,
        limit: int,
        clock: Clock,
        min_interval: timedelta,
        jitter: timedelta,
        jitter_source: Callable[[], float],
        max_waiters: int,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._min_interval = min_interval
        self._jitter = jitter
        self._jitter_source = jitter_source
        self._max_waiters = max_waiters
        self._active = 0
        self._next_start_at: datetime | None = None
        self._sequence = count()
        self._waiters: list[_Waiter] = []

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)

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
                if self._is_next(waiter):
                    now = _canonical_shanghai(self._clock.now())
                    if self._next_start_at is None or now >= self._next_start_at:
                        blocked = before_start()
                        if blocked is not None:
                            raise blocked from None
                        next_start_at = self._calculate_next_start(now)
                        self._waiters.remove(waiter)
                        waiter.granted = True
                        self._active += 1
                        self._next_start_at = next_start_at
                        self._wake_waiters()
                        return
                    await self._wait_for_time_or_change(waiter, self._next_start_at)
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

    def _is_next(self, waiter: _Waiter) -> bool:
        if self._active >= self._limit:
            return False
        return waiter is min(
            self._waiters,
            key=lambda candidate: (candidate.priority, candidate.sequence),
        )

    def _calculate_next_start(self, now: datetime) -> datetime:
        factor = self._jitter_source()
        if type(factor) not in (int, float) or not math.isfinite(factor) or not 0 <= factor <= 1:
            raise ValueError("jitter_source must return a finite value from 0 to 1")
        return now + self._min_interval + self._jitter * float(factor)

    async def _wait_for_time_or_change(
        self,
        waiter: _Waiter,
        deadline: datetime,
    ) -> None:
        sleep_task = asyncio.create_task(self._clock.sleep_until(deadline))
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
        "_max_concurrency",
        "_rate_limit_cooldown",
        "_timeout_seconds",
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
    ) -> None:
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
        )
        self._clock = clock
        self._executor_workers = executor_workers
        self._max_concurrency = max_concurrency
        self._timeout_seconds = float(timeout_seconds)
        self._in_cycle_retries = in_cycle_retries
        self._backoff = backoff
        self._rate_limit_cooldown = rate_limit_cooldown
        self._admission = _ProviderAdmission(
            limit=max_concurrency,
            clock=clock,
            min_interval=min_interval,
            jitter=jitter,
            jitter_source=jitter_source,
            max_waiters=DEFAULT_TUSHARE_QUEUE_LIMIT,
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

    def backoff_until(self, work_key: str) -> datetime | None:
        return self._backoff_until.get(self._validate_work_key(work_key))

    def is_permission_blocked(self, operation: TushareOperation) -> bool:
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        return operation in self._blocked_operations

    def reset_permission_block(self, operation: TushareOperation) -> None:
        if not isinstance(operation, TushareOperation):
            raise TypeError("operation must be a TushareOperation")
        self._blocked_operations.discard(operation)

    async def execute(
        self,
        operation: TushareOperation,
        call: Callable[[], T],
        *,
        work_key: str,
        priority: RequestPriority = RequestPriority.MARKET_DEADLINE,
    ) -> T:
        """Run one repeatable synchronous call under bounded runtime policy."""

        self._validate_request(operation, call, priority)
        normalized_key = self._validate_work_key(work_key)
        blocked = self._preflight_error(operation, normalized_key)
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
                )
            except RequestControlError as caught:
                deferred_error = caught
            except _QueueFullError:
                deferred_error = RequestControlError(
                    RequestControlErrorCode.QUEUE_FULL,
                    operation,
                    attempts=0,
                )
            except TimeoutError:
                failure_code = RequestControlErrorCode.TIMEOUT
            except TushareProviderError as caught:
                failure_code = _TUSHARE_ERROR_CODES[caught.code]
            except Exception:
                failure_code = RequestControlErrorCode.ERROR

            if deferred_error is not None:
                raise deferred_error from None

            if failure_code is None:
                self._backoff_failures.pop(normalized_key, None)
                self._backoff_until.pop(normalized_key, None)
                return result  # type: ignore[return-value]

            if failure_code is RequestControlErrorCode.BLOCKED_PERMISSION:
                self._blocked_operations.add(operation)
                error = RequestControlError(failure_code, operation, attempts=attempts)
                raise error from None

            if failure_code is RequestControlErrorCode.RATE_LIMITED:
                next_retry_at = _saturating_add(self._now(), self._rate_limit_cooldown)
                self._cooldown_until = next_retry_at
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
            if retryable and attempts <= self._in_cycle_retries:
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

    def _preflight_error(
        self,
        operation: TushareOperation,
        work_key: str,
    ) -> RequestControlError | None:
        if operation in self._blocked_operations:
            return RequestControlError(
                RequestControlErrorCode.BLOCKED_PERMISSION,
                operation,
                attempts=0,
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

    async def _run_sync_attempt(
        self,
        call: Callable[[], T],
        priority: RequestPriority,
        operation: TushareOperation,
        work_key: str,
    ) -> T:
        async with asyncio.timeout(self._timeout_seconds):
            await self._admission.acquire(
                int(priority),
                lambda: self._preflight_error(operation, work_key),
            )
        future: asyncio.Future[T] | None = None
        slot_held = True

        def release_once() -> None:
            nonlocal slot_held
            if slot_held:
                slot_held = False
                self._admission.release()

        def consume_and_release(completed: asyncio.Future[T]) -> None:
            try:
                if not completed.cancelled():
                    completed.exception()
            finally:
                release_once()

        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(self._executor, call)
            done, _ = await asyncio.wait((future,), timeout=self._timeout_seconds)
            if future not in done:
                raise TimeoutError
            return future.result()
        finally:
            if future is None:
                release_once()
            elif future.done():
                consume_and_release(future)
            else:
                future.add_done_callback(consume_and_release)

    def _record_backoff(self, work_key: str) -> datetime | None:
        now = self._now()
        if work_key not in self._backoff_failures and not self._reserve_backoff_key(now):
            return None
        failure_count = self._backoff_failures.get(work_key, 0)
        delay = self._backoff[min(failure_count, len(self._backoff) - 1)]
        self._backoff_failures[work_key] = min(failure_count + 1, len(self._backoff))
        next_retry_at = _saturating_add(now, delay)
        self._backoff_until[work_key] = next_retry_at
        return next_retry_at

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
        """Stop accepting work and shut down the owned executor."""

        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)


_NO_RESULT: Final = object()


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
    "RequestControlError",
    "RequestControlErrorCode",
    "RequestPriority",
    "TushareOperation",
    "TushareRequestController",
]
