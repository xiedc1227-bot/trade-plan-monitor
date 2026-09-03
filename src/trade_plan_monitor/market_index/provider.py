"""Validated provider boundary for live and historical board-index data."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol

from pydantic import AwareDatetime, Field, model_validator

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexBar, _IndexValue


class MarketIndexProviderBatch(_IndexValue):
    """One already-parsed response returned by an index-specific provider adapter."""

    index_code: MarketIndexCode
    five_minute_bars: tuple[MarketIndexBar, ...]
    official_daily_bars: tuple[MarketIndexBar, ...]
    content_revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_content_revision(self) -> MarketIndexProviderBatch:
        bars = self.five_minute_bars + self.official_daily_bars
        if any(bar.provider_revision != self.content_revision for bar in bars):
            raise ValueError("provider batch revision does not match its bars")
        return self


class LiveMarketIndexProvider(Protocol):
    """The only live provider surface accepted by snapshot coordination."""

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch: ...


class HistoricalMarketIndexProvider(LiveMarketIndexProvider, Protocol):
    """Historical adapters use the same bounded, index-specific acquisition contract."""


__all__ = [
    "HistoricalMarketIndexProvider",
    "LiveMarketIndexProvider",
    "MarketIndexProviderBatch",
]
