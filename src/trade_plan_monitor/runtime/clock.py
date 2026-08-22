"""Injectable wall clock for the monitoring runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _canonical_shanghai(value: datetime) -> datetime:
    """Validate and normalize one aware Asia/Shanghai wall-clock value."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp timezone must be Asia/Shanghai")
    canonical = value.replace(tzinfo=SHANGHAI)
    if value.utcoffset() != canonical.utcoffset():
        raise ValueError("timestamp timezone must be Asia/Shanghai")
    return canonical


@runtime_checkable
class Clock(Protocol):
    """Minimal real/fake clock contract owned by the scheduler."""

    def now(self) -> datetime: ...

    async def sleep_until(self, deadline: datetime) -> None: ...


class SystemClock:
    """Production wall clock backed by ``asyncio.sleep``."""

    def now(self) -> datetime:
        return datetime.now(tz=SHANGHAI)

    async def sleep_until(self, deadline: datetime) -> None:
        canonical_deadline = _canonical_shanghai(deadline)
        delay_seconds = (canonical_deadline - self.now()).total_seconds()
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)


__all__ = ["Clock", "SystemClock"]
