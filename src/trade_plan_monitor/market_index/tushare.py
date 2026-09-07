"""Fail-closed Tushare board-index profile pending independent live certification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexIssueCode
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch

_PROFILE_ID: Final = "tushare-board-index-live-v1"


class TushareMarketIndexCapabilityStatus(StrEnum):
    """Index-only certification state; it is not a stock-provider capability."""

    UNVERIFIED = "UNVERIFIED"
    READY = "READY"
    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class TushareMarketIndexSourceTimeLabel(StrEnum):
    """Index-only raw timestamp interpretation established by index evidence."""

    UNVERIFIED = "UNVERIFIED"
    START = "START"
    END = "END"


@dataclass(frozen=True, slots=True)
class TushareMarketIndexProfile:
    """Independent board-index profile with no guessed endpoint or time label."""

    profile_id: str
    capabilities: Mapping[MarketIndexCode, TushareMarketIndexCapabilityStatus]
    source_time_label: TushareMarketIndexSourceTimeLabel
    five_minute_endpoint: str | None
    official_daily_endpoint: str | None

    def __post_init__(self) -> None:
        if self.profile_id != _PROFILE_ID:
            raise ValueError("unsupported Tushare market-index profile")
        capabilities = dict(self.capabilities)
        if set(capabilities) != set(MarketIndexCode):
            raise ValueError("market-index profile must classify every approved index")
        if any(
            not isinstance(index_code, MarketIndexCode)
            or not isinstance(status, TushareMarketIndexCapabilityStatus)
            for index_code, status in capabilities.items()
        ):
            raise TypeError("market-index capabilities use dedicated enum values")
        if (
            self.source_time_label is not TushareMarketIndexSourceTimeLabel.UNVERIFIED
            or self.five_minute_endpoint is not None
            or self.official_daily_endpoint is not None
            or any(
                status is not TushareMarketIndexCapabilityStatus.UNVERIFIED
                for status in capabilities.values()
            )
        ):
            raise ValueError("market-index profile requires independent live certification")
        object.__setattr__(self, "capabilities", MappingProxyType(capabilities))


def unverified_tushare_market_index_profile() -> TushareMarketIndexProfile:
    """Return the only truthful profile before an authorized index observation."""

    return TushareMarketIndexProfile(
        profile_id=_PROFILE_ID,
        capabilities={
            index_code: TushareMarketIndexCapabilityStatus.UNVERIFIED
            for index_code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.UNVERIFIED,
        five_minute_endpoint=None,
        official_daily_endpoint=None,
    )


class TushareMarketIndexProviderError(RuntimeError):
    """Stable index-provider failure without SDK response or credential context."""

    def __init__(self) -> None:
        self.code = MarketIndexIssueCode.PROVIDER_UNAVAILABLE.value
        super().__init__("Tushare market-index provider unavailable")


class TushareMarketIndexProvider:
    """Independent live surface that cannot call an uncertified index endpoint."""

    def __init__(self, *, profile: TushareMarketIndexProfile) -> None:
        if not isinstance(profile, TushareMarketIndexProfile):
            raise TypeError("profile must be a TushareMarketIndexProfile")
        self._profile = profile

    @property
    def profile(self) -> TushareMarketIndexProfile:
        return self._profile

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        del index_code, decision_cutoff, five_minute_bar_count, official_daily_bar_count
        raise TushareMarketIndexProviderError from None


__all__ = [
    "TushareMarketIndexCapabilityStatus",
    "TushareMarketIndexProfile",
    "TushareMarketIndexProvider",
    "TushareMarketIndexProviderError",
    "TushareMarketIndexSourceTimeLabel",
    "unverified_tushare_market_index_profile",
]
