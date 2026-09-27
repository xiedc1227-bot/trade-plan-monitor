"""Exchange-session-aware realtime-minute and official-close deadlines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final

from trade_plan_monitor.market_data.sessions import (
    DEFAULT_DATA_GRACE,
    expected_minute_ends,
)
from trade_plan_monitor.runtime.clock import (
    SHANGHAI,
    Clock,
    _canonical_shanghai,
)

DEFAULT_OFFICIAL_CLOSE_ATTEMPTS: Final = (
    time(15, 20),
    time(16, 0),
    time(17, 0),
)
MAX_CALENDAR_LOOKAHEAD_DAYS: Final = 366
_ONE_DAY: Final = timedelta(days=1)
_SESSION_CLOSE: Final = time(15, 0)


class DeadlineKind(StrEnum):
    """One kind of scheduled market deadline."""

    REALTIME_MINUTE = "REALTIME_MINUTE"
    OFFICIAL_CLOSE = "OFFICIAL_CLOSE"
    INDEX_RECOVERY = "INDEX_RECOVERY"
    INDEX_PERMISSION = "INDEX_PERMISSION"
    STOCK_RECOVERY = "STOCK_RECOVERY"


class MarketDeadlineReviewError(ValueError):
    """Elapsed market duties cannot be reviewed within the bounded interval."""


@dataclass(frozen=True, slots=True)
class MarketDeadline:
    """One immutable session deadline in canonical Shanghai time."""

    kind: DeadlineKind
    trade_date: date
    due_at: datetime
    bar_end: datetime | None = None
    close_attempt: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DeadlineKind):
            raise TypeError("kind must be a DeadlineKind")
        if isinstance(self.trade_date, datetime) or not isinstance(self.trade_date, date):
            raise TypeError("trade_date must be a date")
        canonical_due = _canonical_shanghai(self.due_at)
        object.__setattr__(self, "due_at", canonical_due)
        if canonical_due.date() != self.trade_date:
            raise ValueError("due_at must match trade_date")

        if self.kind in (
            DeadlineKind.INDEX_RECOVERY, DeadlineKind.INDEX_PERMISSION, DeadlineKind.STOCK_RECOVERY,
        ):
            if self.bar_end is not None or self.close_attempt is not None:
                raise ValueError("index recovery has no market bar or close attempt")
            return

        if self.kind is DeadlineKind.REALTIME_MINUTE:
            if self.bar_end is None or self.close_attempt is not None:
                raise ValueError("realtime deadline requires only bar_end")
            canonical_end = _canonical_shanghai(self.bar_end)
            object.__setattr__(self, "bar_end", canonical_end)
            if canonical_end.date() != self.trade_date or canonical_due < canonical_end:
                raise ValueError("realtime deadline must follow its same-date bar_end")
            return

        if self.bar_end is not None:
            raise ValueError("official-close deadline cannot have bar_end")
        if type(self.close_attempt) is not int or self.close_attempt < 1:
            raise ValueError("official-close deadline requires a positive attempt")


class MarketSessionScheduler:
    """Build the next eligible deadline from an injected clock and calendar."""

    __slots__ = (
        "_clock",
        "_grace",
        "_is_open_on",
        "_next_index_recovery_at",
        "_next_index_permission_at",
        "_next_stock_recovery_at",
        "_official_close_attempts",
    )

    def __init__(
        self,
        *,
        clock: Clock,
        is_open_on: Callable[[date], bool | None],
        grace: timedelta = DEFAULT_DATA_GRACE,
        official_close_attempts: tuple[time, ...] = DEFAULT_OFFICIAL_CLOSE_ATTEMPTS,
        next_index_recovery_at: Callable[[], datetime | None] | None = None,
        next_index_permission_at: Callable[[], datetime | None] | None = None,
        next_stock_recovery_at: Callable[[], datetime | None] | None = None,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not callable(is_open_on):
            raise TypeError("is_open_on must be callable")
        if not isinstance(grace, timedelta):
            raise TypeError("grace must be a timedelta")
        if grace < timedelta(0):
            raise ValueError("grace cannot be negative")
        self._validate_official_close_attempts(official_close_attempts)
        first_close_offset = timedelta(
            hours=official_close_attempts[0].hour - _SESSION_CLOSE.hour,
            minutes=official_close_attempts[0].minute,
        )
        if grace >= first_close_offset:
            raise ValueError("grace must end before the first official-close attempt")

        self._clock = clock
        self._is_open_on = is_open_on
        self._grace = grace
        self._official_close_attempts = official_close_attempts
        self._next_index_recovery_at = next_index_recovery_at
        self._next_index_permission_at = next_index_permission_at
        self._next_stock_recovery_at = next_stock_recovery_at

    @staticmethod
    def _validate_official_close_attempts(attempts: tuple[time, ...]) -> None:
        if type(attempts) is not tuple:
            raise TypeError("official_close_attempts must be a tuple")
        if not attempts:
            raise ValueError("official_close_attempts cannot be empty")
        previous: time | None = None
        for attempt in attempts:
            if type(attempt) is not time:
                raise TypeError("official_close_attempts must contain only time values")
            if attempt.tzinfo is not None:
                raise ValueError("official_close_attempts must use local wall-clock times")
            if attempt.second != 0 or attempt.microsecond != 0:
                raise ValueError("official_close_attempts must identify whole minutes")
            if attempt <= _SESSION_CLOSE:
                raise ValueError("official_close_attempts must follow the 15:00 close")
            if previous is not None and attempt <= previous:
                raise ValueError("official_close_attempts must be strictly increasing")
            previous = attempt

    def _calendar_state(self, trade_date: date) -> bool | None:
        if trade_date.weekday() >= 5:
            return False
        state = self._is_open_on(trade_date)
        if state is not None and type(state) is not bool:
            raise TypeError("trading calendar must return bool or None")
        return state

    def _deadlines_for_open_date(self, trade_date: date) -> tuple[MarketDeadline, ...]:
        deadlines = [
            MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=trade_date,
                due_at=bar_end + self._grace,
                bar_end=bar_end,
            )
            for bar_end in expected_minute_ends(trade_date, is_open=True)
        ]
        deadlines.extend(
            MarketDeadline(
                kind=DeadlineKind.OFFICIAL_CLOSE,
                trade_date=trade_date,
                due_at=datetime.combine(trade_date, attempt_time, SHANGHAI),
                close_attempt=attempt,
            )
            for attempt, attempt_time in enumerate(
                self._official_close_attempts,
                start=1,
            )
        )
        deadlines.sort(key=lambda deadline: deadline.due_at)
        return tuple(deadlines)

    def deadlines_for_date(self, trade_date: date) -> tuple[MarketDeadline, ...]:
        """Return all deadlines for one known-open weekday, else an empty tuple."""

        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        if self._calendar_state(trade_date) is not True:
            return ()
        return self._deadlines_for_open_date(trade_date)

    def elapsed_market_deadlines(
        self, *, after: datetime, through: datetime,
    ) -> tuple[MarketDeadline, ...]:
        """Read original market duties independently of the current scheduler clock."""
        start = _canonical_shanghai(after)
        end = _canonical_shanghai(through)
        if end < start or (end.date() - start.date()).days > 2:
            raise MarketDeadlineReviewError(
                "market deadline review is outside bounded lookahead"
            )
        elapsed: list[MarketDeadline] = []
        trade_date = start.date()
        while trade_date <= end.date():
            elapsed.extend(
                deadline for deadline in self.deadlines_for_date(trade_date)
                if start < deadline.due_at <= end
            )
            if trade_date == end.date():
                break
            trade_date += _ONE_DAY
        return tuple(elapsed)

    def permission_market_window(
        self, *, since: datetime, through: datetime,
    ) -> tuple[tuple[datetime, bool], ...]:
        """Freeze bounded known and possible market times on the owning event loop."""
        start = _canonical_shanghai(since)
        horizon = _canonical_shanghai(through)
        if horizon < start or (horizon.date() - start.date()).days > 2:
            raise ValueError("market admission elapsed beyond bounded calendar lookahead")
        deadlines: list[tuple[datetime, bool]] = []
        trade_date = start.date()
        while trade_date <= horizon.date():
            known_open = self._calendar_state(trade_date)
            if known_open is not False:
                for deadline in self._deadlines_for_open_date(trade_date):
                    if deadline.due_at > horizon:
                        break
                    if deadline.due_at >= start:
                        deadlines.append((deadline.due_at, known_open is True))
            trade_date += _ONE_DAY
        return tuple(deadlines)

    def next_deadline(self, *, after: datetime | None = None) -> MarketDeadline | None:
        """Return the next due-at-or-after-now deadline, exclusive of ``after``."""

        now = _canonical_shanghai(self._clock.now())
        canonical_after = None if after is None else _canonical_shanghai(after)
        maintenance_deadlines: list[MarketDeadline] = []
        for kind, callback in (
            (DeadlineKind.INDEX_PERMISSION, self._next_index_permission_at),
            (DeadlineKind.INDEX_RECOVERY, self._next_index_recovery_at),
            (DeadlineKind.STOCK_RECOVERY, self._next_stock_recovery_at),
        ):
            due_at = None if callback is None else callback()
            if due_at is not None:
                due_at = max(
                    _canonical_shanghai(due_at),
                    now,
                    (canonical_after + timedelta(microseconds=1))
                    if canonical_after is not None else now,
                )
                maintenance_deadlines.append(MarketDeadline(
                    kind=kind, trade_date=due_at.date(), due_at=due_at,
                ))
        recovery_deadline = min(
            maintenance_deadlines, key=lambda item: item.due_at, default=None,
        )
        start_date = max(
            now.date(),
            canonical_after.date() if canonical_after is not None else now.date(),
        )

        trade_date = start_date
        for _ in range(MAX_CALENDAR_LOOKAHEAD_DAYS):
            calendar_state = self._calendar_state(trade_date)
            if calendar_state is None:
                return recovery_deadline
            if calendar_state:
                for deadline in self._deadlines_for_open_date(trade_date):
                    if deadline.due_at < now:
                        continue
                    if canonical_after is not None and deadline.due_at <= canonical_after:
                        continue
                    if recovery_deadline is not None and recovery_deadline.due_at < deadline.due_at:
                        return recovery_deadline
                    return deadline
            if trade_date == date.max:
                return recovery_deadline
            trade_date += _ONE_DAY
        return recovery_deadline

    async def wait_for_next(self, *, after: datetime | None = None) -> MarketDeadline | None:
        """Sleep through the injected clock until the next known deadline."""

        deadline = self.next_deadline(after=after)
        if deadline is None:
            return None
        await self._clock.sleep_until(deadline.due_at)
        return deadline


__all__ = [
    "DEFAULT_OFFICIAL_CLOSE_ATTEMPTS",
    "DeadlineKind",
    "MarketDeadline",
    "MarketSessionScheduler",
]
