"""Offline contracts for the independent Tushare board-index live profile."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexProviderError,
    TushareMarketIndexSourceTimeLabel,
    unverified_tushare_market_index_profile,
)


def test_unverified_index_profile_is_separate_and_fails_before_any_sdk_call() -> None:
    profile = unverified_tushare_market_index_profile()
    stock_label = SourceTimeLabel.START
    provider = TushareMarketIndexProvider(profile=profile)

    assert profile.profile_id == "tushare-board-index-live-v1"
    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED
    assert profile.source_time_label != stock_label
    assert set(profile.capabilities) == set(MarketIndexCode)
    assert set(profile.capabilities.values()) == {
        TushareMarketIndexCapabilityStatus.UNVERIFIED
    }
    assert profile.five_minute_endpoint is None
    assert profile.official_daily_endpoint is None

    with pytest.raises(TushareMarketIndexProviderError) as captured:
        asyncio.run(
            provider.acquire_index_data(
                index_code=MarketIndexCode.SSE_COMPOSITE,
                decision_cutoff=datetime(
                    2026,
                    9,
                    4,
                    9,
                    35,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                five_minute_bar_count=1,
                official_daily_bar_count=1,
            )
        )

    assert captured.value.code == "PROVIDER_UNAVAILABLE"
    assert str(captured.value) == "Tushare market-index provider unavailable"
    assert captured.value.__cause__ is None
