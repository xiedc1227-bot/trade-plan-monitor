"""Provider-neutral synchronous market-data interface."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from trade_plan_monitor.market_data.models import (
    DailyBar,
    DailyLimit,
    MinuteBar,
    ProviderCapabilities,
    TradingDay,
)


class MarketDataProvider(Protocol):
    """Expose one capability probe and five normalized data operations."""

    def probe_capabilities(self) -> ProviderCapabilities: ...

    def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]: ...

    def current_day_minutes(self, symbol: str) -> list[MinuteBar]: ...

    def trading_calendar(self, start: date, end: date) -> list[TradingDay]: ...

    def daily_limits(self, trade_date: date) -> list[DailyLimit]: ...

    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...


__all__ = ["MarketDataProvider"]
