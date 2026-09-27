"""Bounded, side-effect-free recovery targets and persisted minute coverage.

These values do not authorize evaluation or change production scheduling. Callers
retain plan-specific lookbacks, calendar refresh scheduling and freshness gates.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from threading import Event
from uuid import UUID

from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.market_data.sessions import (
    SHANGHAI,
    expected_minute_ends,
    session_for_minute_end,
)

_MAX_MINUTES = 240
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


@dataclass(frozen=True)
class RecoveryCapture:
    """Original acquisition identity; neither a response nor a retry may advance it."""

    symbol: str
    target: RecoveryTarget
    required_ends: tuple[datetime, ...]
    plan_id: str
    plan_version: int
    plan_version_id: str
    plan_hash: str
    payload_json: str
    activation_revision: int
    activated_at: datetime
    configuration_revision: str
    semantic_revision: str | None
    runtime_generation: UUID
    authority_epoch: int
    authority_revoked: Event
    source_provider: object
    source_client: object
    source_inner_client: object
    source_time_label: object


class RecoveryPhase(StrEnum):
    """Session facts, independent of operational readiness or alert eligibility."""

    PREOPEN = "PREOPEN"
    INTRADAY = "INTRADAY"
    LUNCH = "LUNCH"
    AFTER_CLOSE = "AFTER_CLOSE"
    CLOSED = "CLOSED"
    CALENDAR_UNKNOWN = "CALENDAR_UNKNOWN"


@dataclass(frozen=True)
class RecoveryTarget:
    """One observation frozen before acquisition, with an optional known cutoff."""

    observed_at: datetime
    phase: RecoveryPhase
    trade_date: date | None = None
    completed_minute_end: datetime | None = None

    def __post_init__(self) -> None:
        observed = _shanghai(self.observed_at)
        object.__setattr__(self, "observed_at", observed)
        if not isinstance(self.phase, RecoveryPhase):
            raise TypeError("phase must be a RecoveryPhase")
        if (self.trade_date is None) != (self.completed_minute_end is None):
            raise ValueError("target date and completed cutoff must be present together")
        if self.completed_minute_end is None:
            if self.phase not in (
                RecoveryPhase.PREOPEN, RecoveryPhase.CLOSED, RecoveryPhase.CALENDAR_UNKNOWN,
            ):
                raise ValueError("completed session phase requires a cutoff")
            return
        if type(self.trade_date) is not date:
            raise TypeError("target trade_date must be a date")
        cutoff = _shanghai(self.completed_minute_end)
        if cutoff > observed:
            raise ValueError("target cutoff must already be completed")
        if cutoff.date() != self.trade_date or session_for_minute_end(cutoff) is None:
            raise ValueError("target cutoff must match its canonical session date")
        if self.phase in (RecoveryPhase.PREOPEN, RecoveryPhase.CALENDAR_UNKNOWN):
            raise ValueError("phase cannot have a completed cutoff")
        if self.phase is RecoveryPhase.CLOSED:
            if self.trade_date >= observed.date() or cutoff.time() != time(15):
                raise ValueError("closed target must be a previous completed session")
        elif self.trade_date != observed.date():
            raise ValueError("open target must match the observation date")
        object.__setattr__(self, "completed_minute_end", cutoff)

    @property
    def requires_calendar_refresh(self) -> bool:
        return self.phase is RecoveryPhase.CALENDAR_UNKNOWN or (
            self.phase is RecoveryPhase.CLOSED and self.trade_date is None
        )


@dataclass(frozen=True)
class MinuteCoverage:
    """Exact identities read from persistence; successful fetches are not evidence."""

    required_ends: tuple[datetime, ...]
    covered_ends: tuple[datetime, ...]
    missing_ends: tuple[datetime, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_ends


def derive_recovery_target(
    *,
    now: datetime,
    is_open_on: Callable[[date], bool | None],
    last_completed_trade_date: date | None = None,
) -> RecoveryTarget:
    """Use injected exchange facts, never a weekday fallback or calendar search.

    The cutoff is the latest completed minute, without the scheduler's ingestion
    grace. An earlier display date must be supplied and independently known open.
    """

    observed_at = _shanghai(now)
    today = observed_at.date()
    if not callable(is_open_on):
        raise TypeError("is_open_on must be callable")
    if last_completed_trade_date is not None:
        if type(last_completed_trade_date) is not date:
            raise TypeError("last_completed_trade_date must be a date")
        if last_completed_trade_date >= today:
            raise ValueError("last_completed_trade_date must precede the observation date")

    current_open = _known_open(is_open_on, today)
    if current_open is None:
        return RecoveryTarget(observed_at, RecoveryPhase.CALENDAR_UNKNOWN)
    if current_open is False:
        if last_completed_trade_date is not None and (
            _known_open(is_open_on, last_completed_trade_date) is True
        ):
            previous = expected_minute_ends(last_completed_trade_date, is_open=True)
            if previous:
                return RecoveryTarget(
                    observed_at, RecoveryPhase.CLOSED, last_completed_trade_date, previous[-1],
                )
        return RecoveryTarget(observed_at, RecoveryPhase.CLOSED)

    minutes = expected_minute_ends(today, is_open=True)
    if not minutes:
        return RecoveryTarget(observed_at, RecoveryPhase.CALENDAR_UNKNOWN)
    completed = tuple(value for value in minutes if value <= observed_at)
    if not completed:
        return RecoveryTarget(observed_at, RecoveryPhase.PREOPEN)
    clock = observed_at.time()
    if clock >= time(15):
        phase = RecoveryPhase.AFTER_CLOSE
    elif time(11, 30) <= clock < time(13):
        phase = RecoveryPhase.LUNCH
    else:
        phase = RecoveryPhase.INTRADAY
    return RecoveryTarget(observed_at, phase, today, completed[-1])


def completed_minute_ends(target: RecoveryTarget) -> tuple[datetime, ...]:
    """List at most one completed session date, without shortening plan lookbacks."""

    if target.trade_date is None or target.completed_minute_end is None:
        return ()
    return tuple(
        value for value in expected_minute_ends(target.trade_date, is_open=True)
        if value <= target.completed_minute_end
    )


def check_minute_coverage(
    *,
    required_ends: tuple[datetime, ...],
    persisted_ends: tuple[datetime, ...],
    cutoff: datetime,
) -> MinuteCoverage:
    """Check a bounded requirement against a persisted read for one selected scope.

    The caller owns symbol/dependency selection. Requirements may span dates, but
    may not exceed 240 identities; larger history must be checked in bounded units.
    Future or unrelated persisted facts never substitute for required identities.
    """

    cutoff = _shanghai(cutoff)
    _validate_ends(required_ends)
    _validate_ends(persisted_ends)
    if required_ends != tuple(sorted(set(required_ends))):
        raise ValueError("required minutes must be unique and ordered")
    if any(value > cutoff for value in required_ends):
        raise ValueError("required minutes cannot follow cutoff")
    persisted = {value for value in persisted_ends if value <= cutoff}
    return MinuteCoverage(
        required_ends=required_ends,
        covered_ends=tuple(value for value in required_ends if value in persisted),
        missing_ends=tuple(value for value in required_ends if value not in persisted),
    )


def select_current_day_rows(
    *,
    rows: tuple[MinuteBar, ...],
    symbol: str,
    target: RecoveryTarget,
    now: datetime,
) -> tuple[MinuteBar, ...]:
    """Validate one bounded acquisition and exclude rows past its frozen cutoff.

    Call before persistence with the current clock. Date rollover and a reversed
    clock invalidate the acquisition; an existing target cannot be moved forward
    merely because a slow request returned newer bars. This additive seam is not
    yet installed in RecoveryService.
    """

    current = _shanghai(now)
    if current < target.observed_at or current.date() != target.observed_at.date():
        raise ValueError("clock changed during acquisition; retarget before persistence")
    if target.trade_date != current.date() or target.completed_minute_end is None:
        raise ValueError("current-day acquisition needs a completed current-day target")
    if type(symbol) is not str or _SYMBOL_PATTERN.fullmatch(symbol) is None:
        raise ValueError("symbol must use a canonical A-share identity")
    _bounded_tuple(rows)
    by_end: dict[datetime, MinuteBar] = {}
    for row in rows:
        if not isinstance(row, MinuteBar):
            raise TypeError("rows must contain normalized MinuteBar values")
        if (
            row.symbol != symbol
            or row.bar_end.date() != target.trade_date
            or session_for_minute_end(row.bar_end) is None
        ):
            raise ValueError("response row does not match the requested symbol/session date")
        previous = by_end.get(row.bar_end)
        if previous is not None and previous != row:
            raise ValueError("response contains conflicting duplicate minutes")
        by_end[row.bar_end] = row
    return tuple(
        by_end[value] for value in sorted(by_end)
        if value <= target.completed_minute_end
    )


def _known_open(lookup: Callable[[date], bool | None], day: date) -> bool | None:
    try:
        value = lookup(day)
    except Exception:
        return None
    return value if type(value) is bool else None


def _shanghai(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must have Asia/Shanghai timezone")
    canonical = value.replace(tzinfo=SHANGHAI)
    if value.utcoffset() != canonical.utcoffset():
        raise ValueError("clock must have Asia/Shanghai timezone")
    return canonical


def _bounded_tuple(values: tuple[object, ...]) -> None:
    if type(values) is not tuple:
        raise TypeError("minute collection must be a tuple")
    if len(values) > _MAX_MINUTES:
        raise ValueError("minute collection cannot exceed 240 entries")


def _validate_ends(values: tuple[datetime, ...]) -> None:
    _bounded_tuple(values)
    if any(session_for_minute_end(value) is None for value in values):
        raise ValueError("coverage must contain canonical session minute ends")
