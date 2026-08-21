"""Pure session-contained minute-bucket boundaries and completeness checks."""

from __future__ import annotations

from datetime import datetime, timedelta

from trade_plan_monitor.market_data.sessions import (
    SHANGHAI,
    TradingSession,
    _is_open_trading_date,
    _session_start,
    session_for_minute_end,
)

_ONE_MINUTE = timedelta(minutes=1)
_FIVE_MINUTES = 5


def _canonical_session_minute_end(value: datetime) -> tuple[datetime, TradingSession]:
    session = session_for_minute_end(value)
    if session is None:
        raise ValueError("minute end must be inside one monitoring session")
    return value.replace(tzinfo=SHANGHAI), session


def five_minute_bucket_end(minute_end: datetime) -> datetime:
    """Return the session-relative 5-minute bucket end for one minute."""

    canonical, session = _canonical_session_minute_end(minute_end)
    session_start = datetime.combine(canonical.date(), _session_start(session), SHANGHAI)
    elapsed_minutes = (canonical - session_start) // _ONE_MINUTE
    bucket_number = (elapsed_minutes + _FIVE_MINUTES - 1) // _FIVE_MINUTES
    return session_start + bucket_number * _FIVE_MINUTES * _ONE_MINUTE


def expected_five_minute_ends(bucket_end: datetime) -> tuple[datetime, ...]:
    """Return the five canonical minute ends required by one complete bucket."""

    canonical, session = _canonical_session_minute_end(bucket_end)
    if five_minute_bucket_end(canonical) != canonical:
        raise ValueError("bucket_end must be a five-minute boundary")

    expected = tuple(canonical - offset * _ONE_MINUTE for offset in range(4, -1, -1))
    if any(session_for_minute_end(item) is not session for item in expected):
        raise ValueError("five-minute bucket cannot cross a monitoring session")
    return expected


def is_complete_five_minute_bucket(
    minute_ends: tuple[datetime, ...],
    *,
    bucket_end: datetime,
    is_open: bool | None,
) -> bool:
    """Fail closed unless exactly the five expected session minutes are present."""

    expected = expected_five_minute_ends(bucket_end)
    if not _is_open_trading_date(expected[0].date(), is_open):
        return False
    if type(minute_ends) is not tuple or len(minute_ends) != _FIVE_MINUTES:
        return False
    try:
        if any(session_for_minute_end(item) is None for item in minute_ends):
            return False
    except (TypeError, ValueError):
        return False
    return set(minute_ends) == set(expected)


__all__ = [
    "expected_five_minute_ends",
    "five_minute_bucket_end",
    "is_complete_five_minute_bucket",
]
