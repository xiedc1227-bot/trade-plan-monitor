"""T028 fake-clock contract for market-session-aware deadlines."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.runtime.clock import Clock
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
