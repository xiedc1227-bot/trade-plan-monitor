"""T028-T029 contracts for deadlines and bounded runtime request control."""

from __future__ import annotations

import asyncio
import threading
import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import Clock
from trade_plan_monitor.runtime.request_control import (
    DEFAULT_AI_MAX_CONCURRENCY,
    DEFAULT_AI_QUEUE_LIMIT,
    DEFAULT_IN_CYCLE_RETRIES,
    DEFAULT_JITTER,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_SHARED_RATE_LIMIT_COOLDOWN,
    DEFAULT_SYMBOL_BACKOFF,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT,
    DEFAULT_TUSHARE_EXECUTOR_WORKERS,
    DEFAULT_TUSHARE_MAX_CONCURRENCY,
    DEFAULT_TUSHARE_QUEUE_LIMIT,
    RequestControlError,
    RequestControlErrorCode,
    RequestPriority,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.runtime.scheduler import (
    DEFAULT_OFFICIAL_CLOSE_ATTEMPTS,
    DeadlineKind,
    MarketSessionScheduler,
)

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
OPEN_MONDAY: Final = date(2026, 8, 24)


def _shanghai(
    hour: int,
    minute: int,
    second: int = 0,
    *,
    day: int = 24,
) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, tzinfo=SHANGHAI)


class _FakeClock:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.sleep_deadlines: list[datetime] = []

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_deadlines.append(deadline)
        if deadline > self.current:
            self.current = deadline


class _BlockingPaceClock(_FakeClock):
    def __init__(self, current: datetime) -> None:
        super().__init__(current)
        self.sleep_started = asyncio.Event()
        self.release_sleep = asyncio.Event()

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_deadlines.append(deadline)
        self.sleep_started.set()
        await self.release_sleep.wait()
        if deadline > self.current:
            self.current = deadline


class _FailingPaceClock(_FakeClock):
    def __init__(self, current: datetime, sentinel: str) -> None:
        super().__init__(current)
        self.sentinel = sentinel
        self.sleep_calls = 0

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_deadlines.append(deadline)
        self.sleep_calls += 1
        raise RuntimeError(self.sentinel)


class _Calendar:
    def __init__(self, days: dict[date, bool | None]) -> None:
        self.days = days
        self.calls: list[date] = []

    def __call__(self, trade_date: date) -> bool | None:
        self.calls.append(trade_date)
        return self.days.get(trade_date)


def _scheduler(
    current: datetime,
    *,
    calendar: _Calendar | None = None,
    grace: timedelta = timedelta(seconds=12),
    official_close_attempts: tuple[time, ...] = DEFAULT_OFFICIAL_CLOSE_ATTEMPTS,
) -> tuple[_FakeClock, _Calendar, MarketSessionScheduler]:
    clock = _FakeClock(current)
    market_calendar = calendar or _Calendar({OPEN_MONDAY: True})
    scheduler = MarketSessionScheduler(
        clock=clock,
        is_open_on=market_calendar,
        grace=grace,
        official_close_attempts=official_close_attempts,
    )
    return clock, market_calendar, scheduler


def test_monitor_clock_protocol_accepts_injected_fake_clock() -> None:
    clock = _FakeClock(_shanghai(9, 0))

    assert isinstance(clock, Clock)
    assert clock.now() == _shanghai(9, 0)


def test_monitor_schedule_open_day_has_one_deadline_per_canonical_minute() -> None:
    _, calendar, scheduler = _scheduler(_shanghai(8, 0))

    deadlines = scheduler.deadlines_for_date(OPEN_MONDAY)
    realtime = tuple(
        deadline for deadline in deadlines if deadline.kind is DeadlineKind.REALTIME_MINUTE
    )

    assert len(realtime) == 240
    assert len({deadline.bar_end for deadline in realtime}) == 240
    assert len({deadline.due_at for deadline in realtime}) == 240
    assert realtime[0].bar_end == _shanghai(9, 31)
    assert realtime[0].due_at == _shanghai(9, 31, 12)
    assert realtime[119].bar_end == _shanghai(11, 30)
    assert realtime[120].bar_end == _shanghai(13, 1)
    assert realtime[-1].bar_end == _shanghai(15, 0)
    assert realtime[-1].due_at == _shanghai(15, 0, 12)
    assert all(
        deadline.due_at == deadline.bar_end + timedelta(seconds=12)
        for deadline in realtime
        if deadline.bar_end is not None
    )
    assert calendar.calls == [OPEN_MONDAY]


@pytest.mark.parametrize(
    ("current", "expected_due", "expected_bar_end", "expected_kind"),
    [
        (_shanghai(9, 15), _shanghai(9, 31, 12), _shanghai(9, 31), DeadlineKind.REALTIME_MINUTE),
        (
            _shanghai(9, 31, 11),
            _shanghai(9, 31, 12),
            _shanghai(9, 31),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (
            _shanghai(9, 31, 12),
            _shanghai(9, 31, 12),
            _shanghai(9, 31),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (
            _shanghai(10, 0, 13),
            _shanghai(10, 1, 12),
            _shanghai(10, 1),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (
            _shanghai(11, 30, 13),
            _shanghai(13, 1, 12),
            _shanghai(13, 1),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (_shanghai(12, 30), _shanghai(13, 1, 12), _shanghai(13, 1), DeadlineKind.REALTIME_MINUTE),
        (
            _shanghai(14, 59, 59),
            _shanghai(15, 0, 12),
            _shanghai(15, 0),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (
            _shanghai(15, 0, 12),
            _shanghai(15, 0, 12),
            _shanghai(15, 0),
            DeadlineKind.REALTIME_MINUTE,
        ),
        (_shanghai(15, 0, 13), _shanghai(15, 20), None, DeadlineKind.OFFICIAL_CLOSE),
    ],
)
def test_monitor_schedule_auction_sessions_lunch_final_minute_and_grace(
    current: datetime,
    expected_due: datetime,
    expected_bar_end: datetime | None,
    expected_kind: DeadlineKind,
) -> None:
    _, _, scheduler = _scheduler(current)

    deadline = scheduler.next_deadline()

    assert deadline is not None
    assert deadline.due_at == expected_due
    assert deadline.bar_end == expected_bar_end
    assert deadline.kind is expected_kind


def test_monitor_schedule_after_cursor_makes_each_due_deadline_eligible_once() -> None:
    _, _, scheduler = _scheduler(_shanghai(9, 31, 12))

    first = scheduler.next_deadline()
    assert first is not None
    second = scheduler.next_deadline(after=first.due_at)

    assert first.bar_end == _shanghai(9, 31)
    assert second is not None
    assert second.bar_end == _shanghai(9, 32)
    assert second.due_at == _shanghai(9, 32, 12)


def test_monitor_schedule_applies_configurable_grace_without_polling_closed_intervals() -> None:
    _, _, scheduler = _scheduler(_shanghai(11, 30, 29), grace=timedelta(seconds=30))

    last_morning = scheduler.next_deadline()
    assert last_morning is not None
    next_afternoon = scheduler.next_deadline(after=last_morning.due_at)

    assert last_morning.due_at == _shanghai(11, 30, 30)
    assert next_afternoon is not None
    assert next_afternoon.due_at == _shanghai(13, 1, 30)


def test_monitor_schedule_default_official_close_attempts_are_ordered_and_distinct() -> None:
    _, _, scheduler = _scheduler(_shanghai(15, 0, 13))

    deadlines = scheduler.deadlines_for_date(OPEN_MONDAY)
    close_attempts = tuple(
        deadline for deadline in deadlines if deadline.kind is DeadlineKind.OFFICIAL_CLOSE
    )

    assert DEFAULT_OFFICIAL_CLOSE_ATTEMPTS == (time(15, 20), time(16, 0), time(17, 0))
    assert tuple(deadline.due_at for deadline in close_attempts) == (
        _shanghai(15, 20),
        _shanghai(16, 0),
        _shanghai(17, 0),
    )
    assert tuple(deadline.close_attempt for deadline in close_attempts) == (1, 2, 3)
    assert all(deadline.bar_end is None for deadline in close_attempts)


def test_monitor_schedule_official_close_attempts_follow_clock_dynamically() -> None:
    clock, _, scheduler = _scheduler(_shanghai(15, 20))

    first = scheduler.next_deadline()
    assert first is not None
    assert first.due_at == _shanghai(15, 20)

    clock.current = _shanghai(15, 20, 1)
    second = scheduler.next_deadline(after=first.due_at)
    assert second is not None
    assert second.due_at == _shanghai(16, 0)

    clock.current = _shanghai(16, 0, 1)
    third = scheduler.next_deadline(after=second.due_at)
    assert third is not None
    assert third.due_at == _shanghai(17, 0)


def test_monitor_schedule_accepts_configured_official_close_attempts() -> None:
    custom = (time(15, 30), time(16, 30))
    _, _, scheduler = _scheduler(
        _shanghai(15, 1),
        official_close_attempts=custom,
    )

    close_attempts = tuple(
        deadline
        for deadline in scheduler.deadlines_for_date(OPEN_MONDAY)
        if deadline.kind is DeadlineKind.OFFICIAL_CLOSE
    )

    assert tuple(deadline.due_at.time() for deadline in close_attempts) == custom
    assert tuple(deadline.close_attempt for deadline in close_attempts) == (1, 2)


def test_monitor_schedule_skips_weekend_and_known_holiday() -> None:
    calendar = _Calendar(
        {
            date(2026, 8, 24): False,
            date(2026, 8, 25): True,
        }
    )
    _, _, scheduler = _scheduler(_shanghai(8, 0, day=22), calendar=calendar)

    deadline = scheduler.next_deadline()

    assert deadline is not None
    assert deadline.trade_date == date(2026, 8, 25)
    assert deadline.due_at == datetime(2026, 8, 25, 9, 31, 12, tzinfo=SHANGHAI)
    assert calendar.calls == [date(2026, 8, 24), date(2026, 8, 25)]


def test_monitor_schedule_unknown_calendar_fails_closed_without_scanning_past_it() -> None:
    calendar = _Calendar(
        {
            OPEN_MONDAY: None,
            date(2026, 8, 25): True,
        }
    )
    _, _, scheduler = _scheduler(_shanghai(8, 0), calendar=calendar)

    assert scheduler.next_deadline() is None
    assert scheduler.deadlines_for_date(OPEN_MONDAY) == ()
    assert calendar.calls == [OPEN_MONDAY, OPEN_MONDAY]


def test_monitor_schedule_closed_day_has_no_minute_or_close_deadlines() -> None:
    calendar = _Calendar({OPEN_MONDAY: False})
    _, _, scheduler = _scheduler(_shanghai(8, 0), calendar=calendar)

    assert scheduler.deadlines_for_date(OPEN_MONDAY) == ()


def test_monitor_schedule_date_upper_bound_fails_closed_without_overflow() -> None:
    current = datetime.max.replace(tzinfo=SHANGHAI)
    calendar = _Calendar({date.max: False})
    _, _, scheduler = _scheduler(current, calendar=calendar)

    assert scheduler.next_deadline() is None
    assert calendar.calls == [date.max]


def test_monitor_schedule_waits_with_injected_clock_to_dynamic_next_deadline() -> None:
    clock, _, scheduler = _scheduler(_shanghai(12, 30))

    deadline = asyncio.run(scheduler.wait_for_next())

    assert deadline is not None
    assert deadline.due_at == _shanghai(13, 1, 12)
    assert clock.sleep_deadlines == [_shanghai(13, 1, 12)]
    assert clock.now() == _shanghai(13, 1, 12)


def test_monitor_schedule_unknown_calendar_never_sleeps() -> None:
    calendar = _Calendar({OPEN_MONDAY: None})
    clock, _, scheduler = _scheduler(_shanghai(8, 0), calendar=calendar)

    assert asyncio.run(scheduler.wait_for_next()) is None
    assert clock.sleep_deadlines == []


@pytest.mark.parametrize(
    "current",
    [
        datetime(2026, 8, 24, 9, 0),
        datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    ],
)
def test_monitor_schedule_rejects_non_shanghai_clock_values(current: datetime) -> None:
    _, _, scheduler = _scheduler(current)

    with pytest.raises(ValueError, match="Asia/Shanghai"):
        scheduler.next_deadline()


@pytest.mark.parametrize(
    ("grace", "error"),
    [
        (12, TypeError),
        (timedelta(seconds=-1), ValueError),
    ],
)
def test_monitor_schedule_rejects_invalid_grace(
    grace: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        MarketSessionScheduler(
            clock=_FakeClock(_shanghai(8, 0)),
            is_open_on=_Calendar({OPEN_MONDAY: True}),
            grace=grace,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("grace", "attempts"),
    [
        (timedelta(minutes=20), DEFAULT_OFFICIAL_CLOSE_ATTEMPTS),
        (timedelta(days=1), DEFAULT_OFFICIAL_CLOSE_ATTEMPTS),
        (timedelta(minutes=1), (time(15, 1),)),
    ],
)
def test_monitor_schedule_rejects_grace_colliding_with_first_close_attempt(
    grace: timedelta,
    attempts: tuple[time, ...],
) -> None:
    with pytest.raises(ValueError, match="first official-close attempt"):
        MarketSessionScheduler(
            clock=_FakeClock(_shanghai(8, 0)),
            is_open_on=_Calendar({OPEN_MONDAY: True}),
            grace=grace,
            official_close_attempts=attempts,
        )


def test_monitor_schedule_accepts_grace_strictly_before_first_close_attempt() -> None:
    _, _, scheduler = _scheduler(
        _shanghai(14, 59),
        grace=timedelta(minutes=19, seconds=59, microseconds=999_999),
    )

    final_realtime = next(
        deadline
        for deadline in scheduler.deadlines_for_date(OPEN_MONDAY)
        if deadline.bar_end == _shanghai(15, 0)
    )
    first_close = next(
        deadline
        for deadline in scheduler.deadlines_for_date(OPEN_MONDAY)
        if deadline.kind is DeadlineKind.OFFICIAL_CLOSE
    )

    assert final_realtime.due_at < first_close.due_at


@pytest.mark.parametrize(
    "attempts",
    [
        [],
        (),
        (time(15, 0),),
        (time(16, 0), time(15, 20)),
        (time(15, 20), time(15, 20)),
        (datetime(2026, 8, 24, 15, 20),),
    ],
)
def test_monitor_schedule_rejects_invalid_official_close_attempts(attempts: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        MarketSessionScheduler(
            clock=_FakeClock(_shanghai(8, 0)),
            is_open_on=_Calendar({OPEN_MONDAY: True}),
            official_close_attempts=attempts,  # type: ignore[arg-type]
        )


def test_monitor_schedule_rejects_non_callable_dependencies_and_cursor_timezone() -> None:
    with pytest.raises(TypeError):
        MarketSessionScheduler(
            clock=object(),  # type: ignore[arg-type]
            is_open_on=_Calendar({OPEN_MONDAY: True}),
        )
    with pytest.raises(TypeError):
        MarketSessionScheduler(
            clock=_FakeClock(_shanghai(8, 0)),
            is_open_on=True,  # type: ignore[arg-type]
        )

    _, _, scheduler = _scheduler(_shanghai(8, 0))
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        scheduler.next_deadline(after=datetime(2026, 8, 24, 9, 0))


async def _wait_until(predicate: object, *, turns: int = 1_000) -> None:
    for _ in range(turns):
        if callable(predicate) and predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def _request_controller(
    clock: _FakeClock,
    **overrides: object,
) -> TushareRequestController:
    values: dict[str, object] = {
        "clock": clock,
        "min_interval": timedelta(0),
        "jitter": timedelta(0),
        "jitter_source": lambda: 0.0,
        "timeout_seconds": 1,
    }
    values.update(overrides)
    return TushareRequestController(**values)  # type: ignore[arg-type]


def test_request_concurrency_defaults_match_the_approved_runtime_contract() -> None:
    assert DEFAULT_TUSHARE_EXECUTOR_WORKERS == 2
    assert DEFAULT_TUSHARE_MAX_CONCURRENCY == 2
    assert DEFAULT_MIN_INTERVAL == timedelta(seconds=1)
    assert DEFAULT_JITTER == timedelta(milliseconds=250)
    assert DEFAULT_TIMEOUT_SECONDS == 15
    assert DEFAULT_IN_CYCLE_RETRIES == 2
    assert DEFAULT_SYMBOL_BACKOFF == (
        timedelta(seconds=30),
        timedelta(seconds=60),
        timedelta(seconds=120),
        timedelta(seconds=300),
    )
    assert DEFAULT_SHARED_RATE_LIMIT_COOLDOWN == timedelta(seconds=300)
    assert DEFAULT_TUSHARE_QUEUE_LIMIT == 32
    assert DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT == 64
    assert DEFAULT_AI_MAX_CONCURRENCY == 1
    assert DEFAULT_AI_QUEUE_LIMIT == 5

    controller = TushareRequestController(
        clock=_FakeClock(_shanghai(8, 0)),
        jitter_source=lambda: 0.0,
    )
    try:
        assert controller.executor_workers == 2
        assert controller.max_concurrency == 2
    finally:
        controller.close()


def test_request_concurrency_never_exceeds_two_dedicated_tushare_workers() -> None:
    async def scenario() -> tuple[list[int], int, set[str]]:
        controller = _request_controller(_FakeClock(_shanghai(8, 0)))
        release = threading.Event()
        two_started = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum_active = 0
        thread_names: set[str] = set()

        def call(value: int) -> int:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                thread_names.add(threading.current_thread().name)
                if active == 2:
                    two_started.set()
            release.wait(timeout=2)
            with lock:
                active -= 1
            return value

        try:
            tasks = [
                asyncio.create_task(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        lambda value=value: call(value),
                        work_key=f"realtime:{value}",
                        priority=RequestPriority.MARKET_DEADLINE,
                    )
                )
                for value in range(3)
            ]
            await _wait_until(two_started.is_set)
            assert controller.active_count == 2
            release.set()
            results = await asyncio.gather(*tasks)
            return results, maximum_active, thread_names
        finally:
            release.set()
            controller.close()

    results, maximum_active, thread_names = asyncio.run(scenario())

    assert results == [0, 1, 2]
    assert maximum_active == 2
    assert 1 <= len(thread_names) <= 2
    assert all(name.startswith("trade-plan-tushare") for name in thread_names)


def test_request_concurrency_rejects_work_beyond_bounded_tushare_queue() -> None:
    sentinel = "sensitive-queue-input"

    async def scenario() -> tuple[RequestControlError, int]:
        controller = _request_controller(
            _FakeClock(_shanghai(8, 0)),
            executor_workers=1,
            max_concurrency=1,
        )
        release = threading.Event()
        first_started = threading.Event()

        def blocking_call() -> None:
            first_started.set()
            release.wait(timeout=2)

        first = asyncio.create_task(
            controller.execute(
                TushareOperation.REALTIME_MINUTES,
                blocking_call,
                work_key="queue:active",
            )
        )
        queued: list[asyncio.Task[None]] = []
        try:
            await _wait_until(first_started.is_set)
            queued = [
                asyncio.create_task(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        lambda: None,
                        work_key=f"queue:{index}",
                    )
                )
                for index in range(DEFAULT_TUSHARE_QUEUE_LIMIT)
            ]
            await _wait_until(lambda: controller.waiting_count == DEFAULT_TUSHARE_QUEUE_LIMIT)
            with pytest.raises(RequestControlError) as captured:
                await asyncio.wait_for(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        lambda: (_ for _ in ()).throw(RuntimeError(sentinel)),
                        work_key="queue:overflow",
                    ),
                    timeout=0.1,
                )
            return captured.value, controller.waiting_count
        finally:
            for task in queued:
                task.cancel()
            await asyncio.gather(*queued, return_exceptions=True)
            release.set()
            await first
            controller.close()

    error, waiting_count = asyncio.run(scenario())
    surfaces = (str(error), repr(error), repr(error.__context__), repr(error.__cause__))

    assert error.code is RequestControlErrorCode.QUEUE_FULL
    assert error.attempts == 0
    assert waiting_count == DEFAULT_TUSHARE_QUEUE_LIMIT
    assert all(sentinel not in surface for surface in surfaces)
    assert error.__context__ is None
    assert error.__cause__ is None


def test_request_retry_bounds_backoff_keys_without_evicting_live_state() -> None:
    async def scenario() -> tuple[
        int,
        int,
        RequestControlError,
        RequestControlError,
        datetime | None,
        datetime | None,
    ]:
        clock = _FakeClock(_shanghai(9, 0))
        controller = _request_controller(clock, in_cycle_retries=0)
        calls = 0

        def transient() -> None:
            nonlocal calls
            calls += 1
            raise TushareProviderError(TushareErrorCode.TRANSIENT, "rt_min")

        try:
            for index in range(DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT):
                with pytest.raises(RequestControlError):
                    await controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        transient,
                        work_key=f"bounded:{index}",
                    )
            with pytest.raises(RequestControlError) as overflow_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="bounded:overflow",
                )
            with pytest.raises(RequestControlError) as oldest_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="bounded:0",
                )
            oldest_live = controller.backoff_until("bounded:0")
            clock.current = _shanghai(9, 0, 30)
            with pytest.raises(RequestControlError):
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="bounded:replacement",
                )
            return (
                controller.tracked_backoff_count,
                calls,
                overflow_captured.value,
                oldest_captured.value,
                oldest_live,
                controller.backoff_until("bounded:0"),
            )
        finally:
            controller.close()

    tracked_count, calls, overflow, oldest_error, oldest_live, oldest_after_reclaim = asyncio.run(
        scenario()
    )

    assert tracked_count == DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT
    assert calls == DEFAULT_TUSHARE_BACKOFF_KEY_LIMIT + 1
    assert overflow.code is RequestControlErrorCode.QUEUE_FULL
    assert overflow.attempts == 0
    assert oldest_error.code is RequestControlErrorCode.TRANSIENT
    assert oldest_error.attempts == 0
    assert oldest_live == _shanghai(9, 0, 30)
    assert oldest_after_reclaim is None


def test_request_priority_global_minimum_interval_and_jitter_space_attempt_starts() -> None:
    async def scenario() -> tuple[list[datetime], list[datetime]]:
        clock = _FakeClock(_shanghai(9, 0))
        controller = TushareRequestController(
            clock=clock,
            min_interval=timedelta(seconds=1),
            jitter=timedelta(milliseconds=250),
            jitter_source=lambda: 1.0,
            timeout_seconds=1,
        )
        starts: list[datetime] = []

        def call() -> None:
            starts.append(clock.now())

        try:
            for index in range(3):
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    call,
                    work_key=f"paced:{index}",
                    priority=RequestPriority.MARKET_DEADLINE,
                )
            return starts, clock.sleep_deadlines
        finally:
            controller.close()

    starts, sleeps = asyncio.run(scenario())

    assert starts == [
        _shanghai(9, 0),
        _shanghai(9, 0, 1) + timedelta(milliseconds=250),
        _shanghai(9, 0, 2) + timedelta(milliseconds=500),
    ]
    assert sleeps == starts[1:]


def test_request_priority_clock_failure_is_sanitized_without_busy_loop() -> None:
    sentinel = "sensitive-clock-failure"

    async def scenario() -> tuple[int, RequestControlError]:
        clock = _FailingPaceClock(_shanghai(9, 0), sentinel)
        controller = TushareRequestController(
            clock=clock,
            executor_workers=1,
            max_concurrency=1,
            min_interval=timedelta(seconds=1),
            jitter=timedelta(0),
            jitter_source=lambda: 0.0,
            timeout_seconds=0.1,
            in_cycle_retries=0,
        )
        try:
            await controller.execute(
                TushareOperation.REALTIME_MINUTES,
                lambda: None,
                work_key="clock:first",
            )
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: None,
                    work_key="clock:second",
                )
            return clock.sleep_calls, captured.value
        finally:
            controller.close()

    sleep_calls, error = asyncio.run(scenario())
    surfaces = (str(error), repr(error), repr(error.__context__), repr(error.__cause__))

    assert sleep_calls == 1
    assert error.code is RequestControlErrorCode.ERROR
    assert error.attempts == 1
    assert all(sentinel not in surface for surface in surfaces)
    assert error.__context__ is None
    assert error.__cause__ is None


def test_request_retry_transient_is_bounded_and_uses_30_60_backoff_cycles() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError, object]:
        clock = _FakeClock(_shanghai(9, 0))
        controller = _request_controller(clock)
        calls = 0

        def transient() -> None:
            nonlocal calls
            calls += 1
            raise TushareProviderError(
                TushareErrorCode.TRANSIENT,
                "rt_min",
            )

        try:
            with pytest.raises(RequestControlError) as first_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="003043.SZ",
                )
            first = first_captured.value
            assert first.attempts == 3
            assert first.next_retry_at == _shanghai(9, 0, 30)

            with pytest.raises(RequestControlError) as blocked_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="003043.SZ",
                )
            blocked = blocked_captured.value
            assert blocked.attempts == 0
            assert calls == 3

            clock.current = first.next_retry_at
            with pytest.raises(RequestControlError) as second_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    transient,
                    work_key="003043.SZ",
                )
            second = second_captured.value
            assert second.attempts == 3
            assert second.next_retry_at == _shanghai(9, 1, 30)

            clock.current = second.next_retry_at
            result = await controller.execute(
                TushareOperation.REALTIME_MINUTES,
                lambda: "ready",
                work_key="003043.SZ",
            )
            return calls, first, second, result
        finally:
            controller.close()

    calls, first, second, result = asyncio.run(scenario())

    assert calls == 6
    assert first.code is RequestControlErrorCode.TRANSIENT
    assert second.code is RequestControlErrorCode.TRANSIENT
    assert result == "ready"


def test_request_retry_permission_denial_blocks_operation_without_blind_retry() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError, str]:
        controller = _request_controller(_FakeClock(_shanghai(9, 0)))
        calls = 0

        def denied() -> None:
            nonlocal calls
            calls += 1
            raise TushareProviderError(
                TushareErrorCode.BLOCKED_PERMISSION,
                "rt_min_daily",
            )

        try:
            with pytest.raises(RequestControlError) as first_captured:
                await controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    denied,
                    work_key="003043.SZ",
                )
            with pytest.raises(RequestControlError) as blocked_captured:
                await controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    denied,
                    work_key="000001.SZ",
                )
            controller.reset_permission_block(TushareOperation.CURRENT_DAY_MINUTES)
            result = await controller.execute(
                TushareOperation.CURRENT_DAY_MINUTES,
                lambda: "reprobed",
                work_key="000001.SZ",
            )
            return calls, first_captured.value, blocked_captured.value, result
        finally:
            controller.close()

    calls, first, blocked, result = asyncio.run(scenario())

    assert calls == 1
    assert first.code is RequestControlErrorCode.BLOCKED_PERMISSION
    assert first.attempts == 1
    assert blocked.code is RequestControlErrorCode.BLOCKED_PERMISSION
    assert blocked.attempts == 0
    assert result == "reprobed"


def test_request_retry_queued_call_rechecks_new_permission_block_before_sdk_start() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
            in_cycle_retries=0,
        )
        release = threading.Event()
        first_started = threading.Event()
        calls = 0

        def denied() -> None:
            nonlocal calls
            calls += 1
            first_started.set()
            release.wait(timeout=2)
            raise TushareProviderError(
                TushareErrorCode.BLOCKED_PERMISSION,
                "rt_min_daily",
            )

        def unexpected() -> None:
            nonlocal calls
            calls += 1

        async def capture(call: object) -> RequestControlError:
            with pytest.raises(RequestControlError) as captured:
                await call  # type: ignore[misc]
            return captured.value

        try:
            first = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.CURRENT_DAY_MINUTES,
                        denied,
                        work_key="permission:first",
                    )
                )
            )
            await _wait_until(first_started.is_set)
            queued = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.CURRENT_DAY_MINUTES,
                        unexpected,
                        work_key="permission:queued",
                    )
                )
            )
            await _wait_until(lambda: controller.waiting_count == 1)
            release.set()
            first_error, queued_error = await asyncio.gather(first, queued)
            return calls, first_error, queued_error
        finally:
            release.set()
            controller.close()

    calls, first_error, queued_error = asyncio.run(scenario())

    assert calls == 1
    assert first_error.code is RequestControlErrorCode.BLOCKED_PERMISSION
    assert first_error.attempts == 1
    assert queued_error.code is RequestControlErrorCode.BLOCKED_PERMISSION
    assert queued_error.attempts == 0


def test_request_priority_pre_start_block_does_not_consume_physical_pacing() -> None:
    async def scenario() -> tuple[list[datetime], RequestControlError]:
        clock = _FakeClock(_shanghai(9, 0))
        controller = TushareRequestController(
            clock=clock,
            executor_workers=1,
            max_concurrency=1,
            min_interval=timedelta(seconds=1),
            jitter=timedelta(0),
            jitter_source=lambda: 0.0,
            timeout_seconds=1,
            in_cycle_retries=0,
        )
        release = threading.Event()
        first_started = threading.Event()
        physical_starts: list[datetime] = []

        def denied() -> None:
            physical_starts.append(clock.now())
            first_started.set()
            release.wait(timeout=2)
            raise TushareProviderError(
                TushareErrorCode.BLOCKED_PERMISSION,
                "rt_min_daily",
            )

        async def capture(call: object) -> RequestControlError:
            with pytest.raises(RequestControlError) as captured:
                await call  # type: ignore[misc]
            return captured.value

        try:
            first = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.CURRENT_DAY_MINUTES,
                        denied,
                        work_key="phantom:first",
                        priority=RequestPriority.RECOVERY,
                    )
                )
            )
            await _wait_until(first_started.is_set)
            queued = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.CURRENT_DAY_MINUTES,
                        lambda: physical_starts.append(clock.now()),
                        work_key="phantom:queued",
                        priority=RequestPriority.RECOVERY,
                    )
                )
            )
            await _wait_until(lambda: controller.waiting_count == 1)
            release.set()
            first_error, queued_error = await asyncio.gather(first, queued)
            assert first_error.code is RequestControlErrorCode.BLOCKED_PERMISSION
            await controller.execute(
                TushareOperation.TRADING_CALENDAR,
                lambda: physical_starts.append(clock.now()),
                work_key="phantom:market",
                priority=RequestPriority.MARKET_DEADLINE,
            )
            return physical_starts, queued_error
        finally:
            release.set()
            controller.close()

    physical_starts, queued_error = asyncio.run(scenario())

    assert physical_starts == [_shanghai(9, 0), _shanghai(9, 0, 1)]
    assert queued_error.code is RequestControlErrorCode.BLOCKED_PERMISSION
    assert queued_error.attempts == 0


def test_request_cooldown_rate_limit_is_shared_and_exactly_300_seconds() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError, str]:
        clock = _FakeClock(_shanghai(9, 0))
        controller = _request_controller(clock)
        calls = 0

        def limited() -> None:
            nonlocal calls
            calls += 1
            raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")

        try:
            with pytest.raises(RequestControlError) as first_captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    limited,
                    work_key="realtime",
                )
            with pytest.raises(RequestControlError) as shared_captured:
                await controller.execute(
                    TushareOperation.TRADING_CALENDAR,
                    lambda: "must-not-run",
                    work_key="calendar",
                )
            clock.current = first_captured.value.next_retry_at
            result = await controller.execute(
                TushareOperation.TRADING_CALENDAR,
                lambda: "ready",
                work_key="calendar",
            )
            return calls, first_captured.value, shared_captured.value, result
        finally:
            controller.close()

    calls, first, shared, result = asyncio.run(scenario())

    assert calls == 1
    assert first.code is RequestControlErrorCode.RATE_LIMITED
    assert first.attempts == 1
    assert first.next_retry_at == _shanghai(9, 5)
    assert shared.code is RequestControlErrorCode.RATE_LIMITED
    assert shared.attempts == 0
    assert shared.next_retry_at == first.next_retry_at
    assert result == "ready"


def test_request_cooldown_queued_other_operation_rechecks_before_sdk_start() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
            in_cycle_retries=0,
        )
        release = threading.Event()
        first_started = threading.Event()
        calls = 0

        def limited() -> None:
            nonlocal calls
            calls += 1
            first_started.set()
            release.wait(timeout=2)
            raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")

        def unexpected() -> None:
            nonlocal calls
            calls += 1

        async def capture(call: object) -> RequestControlError:
            with pytest.raises(RequestControlError) as captured:
                await call  # type: ignore[misc]
            return captured.value

        try:
            first = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        limited,
                        work_key="cooldown:first",
                    )
                )
            )
            await _wait_until(first_started.is_set)
            queued = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.TRADING_CALENDAR,
                        unexpected,
                        work_key="cooldown:queued",
                    )
                )
            )
            await _wait_until(lambda: controller.waiting_count == 1)
            release.set()
            first_error, queued_error = await asyncio.gather(first, queued)
            return calls, first_error, queued_error
        finally:
            release.set()
            controller.close()

    calls, first_error, queued_error = asyncio.run(scenario())

    assert calls == 1
    assert first_error.code is RequestControlErrorCode.RATE_LIMITED
    assert first_error.attempts == 1
    assert queued_error.code is RequestControlErrorCode.RATE_LIMITED
    assert queued_error.attempts == 0
    assert queued_error.next_retry_at == first_error.next_retry_at


def test_request_retry_queued_same_key_rechecks_new_backoff_before_sdk_start() -> None:
    async def scenario() -> tuple[int, RequestControlError, RequestControlError]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
            in_cycle_retries=0,
        )
        release = threading.Event()
        first_started = threading.Event()
        calls = 0

        def transient() -> None:
            nonlocal calls
            calls += 1
            first_started.set()
            release.wait(timeout=2)
            raise TushareProviderError(TushareErrorCode.TRANSIENT, "rt_min")

        def unexpected() -> None:
            nonlocal calls
            calls += 1

        async def capture(call: object) -> RequestControlError:
            with pytest.raises(RequestControlError) as captured:
                await call  # type: ignore[misc]
            return captured.value

        try:
            first = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        transient,
                        work_key="same-key",
                    )
                )
            )
            await _wait_until(first_started.is_set)
            queued = asyncio.create_task(
                capture(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        unexpected,
                        work_key="same-key",
                    )
                )
            )
            await _wait_until(lambda: controller.waiting_count == 1)
            release.set()
            first_error, queued_error = await asyncio.gather(first, queued)
            return calls, first_error, queued_error
        finally:
            release.set()
            controller.close()

    calls, first_error, queued_error = asyncio.run(scenario())

    assert calls == 1
    assert first_error.code is RequestControlErrorCode.TRANSIENT
    assert first_error.attempts == 1
    assert queued_error.code is RequestControlErrorCode.TRANSIENT
    assert queued_error.attempts == 0
    assert queued_error.next_retry_at == first_error.next_retry_at


def test_request_retry_timeout_uses_at_most_two_physical_workers_and_three_attempts() -> None:
    async def scenario() -> tuple[int, int, RequestControlError]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            timeout_seconds=0.05,
        )
        lock = threading.Lock()
        started = [threading.Event() for _ in range(3)]
        releases = [threading.Event() for _ in range(3)]
        calls = 0
        active = 0
        maximum_active = 0

        def blocked() -> None:
            nonlocal calls, active, maximum_active
            with lock:
                call_index = calls
                calls += 1
                active += 1
                maximum_active = max(maximum_active, active)
            started[call_index].set()
            releases[call_index].wait(timeout=2)
            with lock:
                active -= 1

        request = asyncio.create_task(
            controller.execute(
                TushareOperation.REALTIME_MINUTES,
                blocked,
                work_key="timeout",
            )
        )
        try:
            assert await asyncio.to_thread(started[0].wait, 1)
            assert await asyncio.to_thread(started[1].wait, 1)
            releases[0].set()
            assert await asyncio.to_thread(started[2].wait, 1)
            with pytest.raises(RequestControlError) as captured:
                await request
            return calls, maximum_active, captured.value
        finally:
            for release in releases:
                release.set()
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
            await _wait_until(lambda: controller.active_count == 0)
            controller.close()

    calls, maximum_active, error = asyncio.run(scenario())

    assert calls == 3
    assert 1 <= maximum_active <= 2
    assert error.code is RequestControlErrorCode.TIMEOUT
    assert error.attempts == 3
    assert error.next_retry_at == _shanghai(9, 0, 30)


def test_request_retry_never_returning_sync_calls_do_not_stall_logical_timeout() -> None:
    async def scenario() -> tuple[int, int, RequestControlError]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            timeout_seconds=0.01,
        )
        release = threading.Event()
        lock = threading.Lock()
        calls = 0
        active = 0

        def blocked() -> None:
            nonlocal calls, active
            with lock:
                calls += 1
                active += 1
            release.wait(timeout=2)
            with lock:
                active -= 1

        try:
            with pytest.raises(RequestControlError) as captured:
                await asyncio.wait_for(
                    controller.execute(
                        TushareOperation.REALTIME_MINUTES,
                        blocked,
                        work_key="never-returning",
                    ),
                    timeout=0.2,
                )
            return calls, controller.active_count, captured.value
        finally:
            release.set()
            await _wait_until(lambda: controller.active_count == 0)
            controller.close()

    calls, active_count_at_error, error = asyncio.run(scenario())

    assert calls == 2
    assert active_count_at_error == 2
    assert error.code is RequestControlErrorCode.TIMEOUT
    assert error.attempts == 3


def test_request_retry_late_thread_exception_after_timeout_is_consumed_safely() -> None:
    sentinel = "sensitive-late-timeout-provider-body"

    async def scenario() -> tuple[RequestControlError, list[dict[str, object]]]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
            timeout_seconds=0.005,
            in_cycle_retries=0,
        )
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(dict(context)))

        def late_failure() -> None:
            time_module.sleep(0.02)
            raise RuntimeError(sentinel)

        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    late_failure,
                    work_key="late-timeout",
                )
            await asyncio.sleep(0.03)
            await _wait_until(lambda: controller.active_count == 0)
            await asyncio.sleep(0)
            return captured.value, contexts
        finally:
            loop.set_exception_handler(previous_handler)
            controller.close()

    error, contexts = asyncio.run(scenario())

    assert error.code is RequestControlErrorCode.TIMEOUT
    assert error.attempts == 1
    assert contexts == []


def test_request_retry_late_thread_exception_after_cancellation_is_consumed_safely() -> None:
    sentinel = "sensitive-late-cancelled-provider-body"

    async def scenario() -> list[dict[str, object]]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
            in_cycle_retries=0,
        )
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(dict(context)))
        started = threading.Event()
        release = threading.Event()

        def late_failure() -> None:
            started.set()
            release.wait(timeout=2)
            raise RuntimeError(sentinel)

        task = asyncio.create_task(
            controller.execute(
                TushareOperation.REALTIME_MINUTES,
                late_failure,
                work_key="late-cancelled",
            )
        )
        try:
            await _wait_until(started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            await _wait_until(lambda: controller.active_count == 0)
            await asyncio.sleep(0)
            return contexts
        finally:
            release.set()
            loop.set_exception_handler(previous_handler)
            controller.close()

    assert asyncio.run(scenario()) == []


def test_request_priority_market_deadline_overtakes_queued_recovery() -> None:
    async def scenario() -> list[str]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=2,
            max_concurrency=1,
        )
        release = threading.Event()
        blocker_started = threading.Event()
        order: list[str] = []

        def blocker() -> str:
            order.append("blocker")
            blocker_started.set()
            release.wait(timeout=2)
            return "blocker"

        def record(label: str) -> str:
            order.append(label)
            return label

        try:
            first = asyncio.create_task(
                controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    blocker,
                    work_key="blocker",
                    priority=RequestPriority.RECOVERY,
                )
            )
            await _wait_until(blocker_started.is_set)
            recovery = asyncio.create_task(
                controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    lambda: record("recovery"),
                    work_key="recovery",
                    priority=RequestPriority.RECOVERY,
                )
            )
            await _wait_until(lambda: controller.waiting_count == 1)
            market = asyncio.create_task(
                controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: record("market"),
                    work_key="market",
                    priority=RequestPriority.MARKET_DEADLINE,
                )
            )
            await _wait_until(lambda: controller.waiting_count == 2)
            release.set()
            await asyncio.gather(first, recovery, market)
            return order
        finally:
            release.set()
            controller.close()

    assert asyncio.run(scenario()) == ["blocker", "market", "recovery"]


def test_request_priority_market_displaces_recovery_when_queue_is_full() -> None:
    async def scenario() -> tuple[RequestControlError, str, int]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
        )
        release = threading.Event()
        active_started = threading.Event()

        def active_call() -> str:
            active_started.set()
            release.wait(timeout=2)
            return "active"

        active = asyncio.create_task(
            controller.execute(
                TushareOperation.DAILY_BARS,
                active_call,
                work_key="full-priority:active",
                priority=RequestPriority.RECOVERY,
            )
        )
        queued: list[asyncio.Task[str]] = []
        market: asyncio.Task[str] | None = None
        try:
            await _wait_until(active_started.is_set)
            queued = [
                asyncio.create_task(
                    controller.execute(
                        TushareOperation.DAILY_BARS,
                        lambda: "recovery",
                        work_key=f"full-priority:recovery:{index}",
                        priority=RequestPriority.RECOVERY,
                    )
                )
                for index in range(DEFAULT_TUSHARE_QUEUE_LIMIT)
            ]
            await _wait_until(lambda: controller.waiting_count == DEFAULT_TUSHARE_QUEUE_LIMIT)
            market = asyncio.create_task(
                controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: "market",
                    work_key="full-priority:market",
                    priority=RequestPriority.MARKET_DEADLINE,
                )
            )
            await _wait_until(queued[-1].done)
            with pytest.raises(RequestControlError) as displaced_captured:
                await queued[-1]
            queued_depth = controller.waiting_count
            for task in queued[:-1]:
                task.cancel()
            await asyncio.gather(*queued[:-1], return_exceptions=True)
            release.set()
            active_result, market_result = await asyncio.gather(active, market)
            assert active_result == "active"
            return displaced_captured.value, market_result, queued_depth
        finally:
            for task in queued:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*queued, return_exceptions=True)
            release.set()
            if not active.done():
                await active
            if market is not None and not market.done():
                await market
            controller.close()

    displaced, market_result, queued_depth = asyncio.run(scenario())

    assert displaced.code is RequestControlErrorCode.QUEUE_FULL
    assert displaced.attempts == 0
    assert displaced.__context__ is None
    assert displaced.__cause__ is None
    assert market_result == "market"
    assert queued_depth == DEFAULT_TUSHARE_QUEUE_LIMIT


def test_request_priority_market_overtakes_recovery_waiting_for_pacing_with_two_slots() -> None:
    async def scenario() -> list[str]:
        clock = _BlockingPaceClock(_shanghai(9, 0))
        controller = TushareRequestController(
            clock=clock,
            min_interval=timedelta(seconds=1),
            jitter=timedelta(0),
            jitter_source=lambda: 0.0,
            timeout_seconds=1,
        )
        release_first = threading.Event()
        first_started = threading.Event()
        order: list[str] = []

        def first_recovery() -> str:
            order.append("first")
            first_started.set()
            release_first.wait(timeout=2)
            return "first"

        def record(label: str) -> str:
            order.append(label)
            return label

        try:
            first = asyncio.create_task(
                controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    first_recovery,
                    work_key="first",
                    priority=RequestPriority.RECOVERY,
                )
            )
            await _wait_until(first_started.is_set)
            recovery = asyncio.create_task(
                controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    lambda: record("recovery"),
                    work_key="recovery",
                    priority=RequestPriority.RECOVERY,
                )
            )
            await clock.sleep_started.wait()
            market = asyncio.create_task(
                controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: record("market"),
                    work_key="market",
                    priority=RequestPriority.MARKET_DEADLINE,
                )
            )
            await asyncio.sleep(0)
            clock.release_sleep.set()
            await asyncio.gather(recovery, market)
            release_first.set()
            await first
            return order
        finally:
            clock.release_sleep.set()
            release_first.set()
            controller.close()

    assert asyncio.run(scenario()) == ["first", "market", "recovery"]


def test_request_concurrency_cancellation_does_not_release_running_sync_worker_early() -> None:
    async def scenario() -> tuple[bool, str]:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            executor_workers=1,
            max_concurrency=1,
        )
        release = threading.Event()
        first_started = threading.Event()
        second_started = threading.Event()

        def first_call() -> None:
            first_started.set()
            release.wait(timeout=2)

        def second_call() -> str:
            second_started.set()
            return "second"

        try:
            first = asyncio.create_task(
                controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    first_call,
                    work_key="first",
                )
            )
            await _wait_until(first_started.is_set)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first

            second = asyncio.create_task(
                controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    second_call,
                    work_key="second",
                )
            )
            await asyncio.sleep(0)
            started_before_release = second_started.is_set()
            release.set()
            result = await second
            return started_before_release, result
        finally:
            release.set()
            controller.close()

    started_before_release, result = asyncio.run(scenario())

    assert started_before_release is False
    assert result == "second"


def test_request_retry_redacts_provider_exception_context_and_cause() -> None:
    sentinel = "sensitive-provider-body"

    async def scenario() -> RequestControlError:
        controller = _request_controller(
            _FakeClock(_shanghai(9, 0)),
            in_cycle_retries=0,
        )

        def fail_with_context() -> None:
            try:
                raise ValueError(sentinel)
            except ValueError as caught:
                raise TushareProviderError(
                    TushareErrorCode.TRANSIENT,
                    "rt_min",
                ) from caught

        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    fail_with_context,
                    work_key="redacted",
                )
            return captured.value
        finally:
            controller.close()

    error = asyncio.run(scenario())
    surfaces = (str(error), repr(error), repr(error.__context__), repr(error.__cause__))

    assert error.code is RequestControlErrorCode.TRANSIENT
    assert all(sentinel not in surface for surface in surfaces)
    assert error.__context__ is None
    assert error.__cause__ is None


def test_request_cooldown_and_retry_backoff_saturate_at_datetime_max() -> None:
    async def rate_limited() -> RequestControlError:
        controller = _request_controller(
            _FakeClock(datetime.max.replace(tzinfo=SHANGHAI)),
            in_cycle_retries=0,
        )
        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: (_ for _ in ()).throw(
                        TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
                    ),
                    work_key="rate-limit-max",
                )
            return captured.value
        finally:
            controller.close()

    async def transient() -> RequestControlError:
        controller = _request_controller(
            _FakeClock(datetime.max.replace(tzinfo=SHANGHAI)),
            in_cycle_retries=0,
        )
        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: (_ for _ in ()).throw(
                        TushareProviderError(TushareErrorCode.TRANSIENT, "rt_min")
                    ),
                    work_key="backoff-max",
                )
            return captured.value
        finally:
            controller.close()

    cooldown_error = asyncio.run(rate_limited())
    backoff_error = asyncio.run(transient())

    assert cooldown_error.next_retry_at == datetime.max.replace(tzinfo=SHANGHAI)
    assert backoff_error.next_retry_at == datetime.max.replace(tzinfo=SHANGHAI)


def test_request_concurrency_close_cannot_abandon_owned_threads() -> None:
    controller = _request_controller(_FakeClock(_shanghai(9, 0)))
    try:
        with pytest.raises(TypeError):
            controller.close(wait=False)  # type: ignore[call-arg]
    finally:
        controller.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"executor_workers": 0},
        {"executor_workers": 3},
        {"max_concurrency": 0},
        {"executor_workers": 1, "max_concurrency": 2},
        {"min_interval": timedelta(seconds=-1)},
        {"jitter": timedelta(seconds=-1)},
        {"timeout_seconds": 0},
        {"in_cycle_retries": 3},
        {"backoff": []},
        {"backoff": ()},
        {"backoff": (timedelta(seconds=60), timedelta(seconds=30))},
        {"rate_limit_cooldown": timedelta(0)},
    ],
)
def test_request_concurrency_rejects_unbounded_or_invalid_controls(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _request_controller(_FakeClock(_shanghai(9, 0)), **changes)
