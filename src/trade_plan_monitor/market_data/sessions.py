"""Canonical A-share monitoring sessions and explicit source-time mapping.

The afternoon monitoring session includes the closing call auction through 15:00.
Tushare documents ``time`` only as trading time, so callers must supply a verified
start/end label policy instead of relying on a default.

Sources:
- https://tushare.pro/document/2?doc_id=374
- https://docs.python.org/3.11/library/zoneinfo.html
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_DATA_GRACE = timedelta(seconds=12)
_ONE_MINUTE = timedelta(minutes=1)


class TradingSession(StrEnum):
    """One intraday interval admitted to the first-release rule stream."""

    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


class SourceTimeLabel(StrEnum):
    """Verified meaning of one raw provider minute timestamp."""

    UNVERIFIED = "UNVERIFIED"
    START = "START"
    END = "END"


class SourceTimeMappingUnverifiedError(ValueError):
    """Raised when raw provider labels have not passed the live contract gate."""


_SESSION_WINDOWS = (
    (TradingSession.MORNING, time(9, 30), time(11, 30)),
    (TradingSession.AFTERNOON, time(13, 0), time(15, 0)),
)


def _session_start(session: TradingSession) -> time:
    for candidate, start, _ in _SESSION_WINDOWS:
        if candidate is session:
            return start
    raise ValueError("unknown monitoring session")


def _canonical_shanghai(value: datetime, *, whole_minute: bool) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp timezone must be Asia/Shanghai")
    canonical = value.replace(tzinfo=SHANGHAI)
    if value.utcoffset() != canonical.utcoffset():
        raise ValueError("timestamp timezone must be Asia/Shanghai")
    # pandas.Timestamp keeps sub-microsecond residue outside datetime.microsecond.
    nanosecond = getattr(value, "nanosecond", 0)
    if whole_minute and (value.second != 0 or value.microsecond != 0 or nanosecond != 0):
        raise ValueError("timestamp must identify a whole minute")
    return canonical


def _is_open_trading_date(trade_date: date, is_open: bool | None) -> bool:
    if is_open is not None and type(is_open) is not bool:
        raise TypeError("is_open must be bool or None")
    return is_open is True and trade_date.weekday() < 5


def session_for_minute_end(bar_end: datetime) -> TradingSession | None:
    """Return the monitoring session containing one canonical minute end."""

    canonical = _canonical_shanghai(bar_end, whole_minute=True)
    clock_time = canonical.time()
    for session, start, end in _SESSION_WINDOWS:
        if start < clock_time <= end:
            return session
    return None


def expected_minute_ends(
    trade_date: date,
    *,
    is_open: bool | None,
) -> tuple[datetime, ...]:
    """Return all canonical minute ends for one explicitly open trading day."""

    if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
        raise TypeError("trade_date must be a date")
    if not _is_open_trading_date(trade_date, is_open):
        return ()

    minute_ends: list[datetime] = []
    for _, start, end in _SESSION_WINDOWS:
        cursor = datetime.combine(trade_date, start, SHANGHAI) + _ONE_MINUTE
        session_end = datetime.combine(trade_date, end, SHANGHAI)
        while cursor <= session_end:
            minute_ends.append(cursor)
            cursor += _ONE_MINUTE
    return tuple(minute_ends)


def normalize_source_minute(
    source_time: datetime,
    *,
    label: SourceTimeLabel,
    is_open: bool | None,
) -> datetime:
    """Map one verified raw start/end label to a canonical minute end."""

    if not isinstance(label, SourceTimeLabel):
        raise TypeError("label must be a SourceTimeLabel")
    if label is SourceTimeLabel.UNVERIFIED:
        raise SourceTimeMappingUnverifiedError("source time label mapping is UNVERIFIED")

    canonical = _canonical_shanghai(source_time, whole_minute=True)
    if not _is_open_trading_date(canonical.date(), is_open):
        raise ValueError("trading day is closed or unknown")
    bar_end = canonical + _ONE_MINUTE if label is SourceTimeLabel.START else canonical
    if session_for_minute_end(bar_end) is None:
        raise ValueError("source timestamp does not map inside one monitoring session")
    return bar_end


def is_minute_usable(
    bar_end: datetime,
    *,
    as_of: datetime,
    is_open: bool | None,
    grace: timedelta = DEFAULT_DATA_GRACE,
) -> bool:
    """Return whether a session minute has ended and its ingestion grace has passed."""

    if not isinstance(grace, timedelta):
        raise TypeError("grace must be a timedelta")
    if grace < timedelta(0):
        raise ValueError("grace cannot be negative")

    canonical_end = _canonical_shanghai(bar_end, whole_minute=True)
    canonical_as_of = _canonical_shanghai(as_of, whole_minute=False)
    if not _is_open_trading_date(canonical_end.date(), is_open):
        return False
    return (
        session_for_minute_end(canonical_end) is not None
        and canonical_as_of >= canonical_end + grace
    )


__all__ = [
    "DEFAULT_DATA_GRACE",
    "SourceTimeLabel",
    "SourceTimeMappingUnverifiedError",
    "TradingSession",
    "expected_minute_ends",
    "is_minute_usable",
    "normalize_source_minute",
    "session_for_minute_end",
]
