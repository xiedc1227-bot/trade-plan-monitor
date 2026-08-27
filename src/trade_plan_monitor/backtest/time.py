"""Strict Asia/Shanghai time primitives for active backtest metadata."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
_SHANGHAI_OFFSET = timedelta(hours=8)
_BASE_TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
_SHANGHAI_PATTERN = re.compile(rf"^{_BASE_TIMESTAMP}\+08:00$")
_UTC_METADATA_PATTERN = re.compile(rf"^{_BASE_TIMESTAMP}(?:Z|\+00:00)$")


def parse_shanghai_datetime(value: str) -> datetime:
    """Parse only an RFC 3339 timestamp with explicit ``+08:00`` offset."""

    if type(value) is not str:
        raise TypeError("Shanghai datetime must be a string")
    if _SHANGHAI_PATTERN.fullmatch(value) is None:
        raise ValueError("Shanghai datetime must use explicit +08:00 with 0..6 fractional digits")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Shanghai datetime is invalid") from error
    if parsed.utcoffset() != _SHANGHAI_OFFSET:
        raise ValueError("Shanghai datetime must use explicit +08:00")
    return parsed.astimezone(SHANGHAI)


def format_shanghai_datetime(value: datetime) -> str:
    """Serialize a China-business datetime with exactly six fractional digits."""

    if not isinstance(value, datetime):
        raise TypeError("Shanghai datetime must be a datetime")
    if value.tzinfo is None or value.utcoffset() != _SHANGHAI_OFFSET:
        raise ValueError("Shanghai datetime must use Asia/Shanghai or explicit +08:00")
    return value.astimezone(SHANGHAI).isoformat(timespec="microseconds")


def normalize_market_metadata_timestamp(value: str) -> tuple[str, bool]:
    """Validate active metadata or convert one strict legacy UTC timestamp."""

    if type(value) is not str:
        raise TypeError("market metadata timestamp must be a string")
    if _SHANGHAI_PATTERN.fullmatch(value) is not None:
        parsed = parse_shanghai_datetime(value)
        canonical = format_shanghai_datetime(parsed)
        if canonical != value:
            raise ValueError("active market metadata must use fixed-six-digit +08:00")
        return canonical, False
    if _UTC_METADATA_PATTERN.fullmatch(value) is None:
        raise ValueError("market metadata timestamp must be legacy UTC or canonical +08:00")
    normalized_utc = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed_utc = datetime.fromisoformat(normalized_utc)
    except ValueError as error:
        raise ValueError("legacy UTC market metadata timestamp is invalid") from error
    return format_shanghai_datetime(parsed_utc.astimezone(SHANGHAI)), True


def shanghai_now_text() -> str:
    """Return the current active-business timestamp in canonical wire/storage form."""

    return format_shanghai_datetime(datetime.now(SHANGHAI))


__all__ = [
    "SHANGHAI",
    "format_shanghai_datetime",
    "normalize_market_metadata_timestamp",
    "parse_shanghai_datetime",
    "shanghai_now_text",
]
