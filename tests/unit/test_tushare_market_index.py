"""Offline contracts for the independent Tushare board-index live profile."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexProviderError,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
    unverified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.request_control import TushareOperation


def test_unverified_index_profile_is_separate_and_fails_before_any_sdk_call() -> None:
    profile = unverified_tushare_market_index_profile()
    stock_label = SourceTimeLabel.START
    provider = TushareMarketIndexProvider(profile=profile)

    assert profile.profile_id == "tushare-board-index-live-v1"
    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED
    assert profile.source_time_label != stock_label
    assert set(profile.capabilities) == set(MarketIndexCode)
    assert set(profile.capabilities.values()) == {TushareMarketIndexCapabilityStatus.UNVERIFIED}
    assert profile.five_minute_endpoint is None
    assert profile.realtime_five_minute_endpoint is None
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


class _Controller:
    def __init__(self) -> None:
        self.calls: list[tuple[TushareOperation, str]] = []

    async def execute(
        self,
        operation: TushareOperation,
        call: object,
        *,
        work_key: str,
        priority: object,
    ) -> object:
        del priority
        self.calls.append((operation, work_key))
        assert callable(call)
        return call()


class _Client:
    def __init__(self) -> None:
        self.idx_calls: list[dict[str, object]] = []
        self.realtime_idx_calls: list[dict[str, object]] = []
        self.daily_calls: list[dict[str, object]] = []

    def idx_mins(self, **kwargs: object) -> pd.DataFrame:
        self.idx_calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "ts_code": "399001.SZ",
                    "trade_time": "2026-09-04 14:55:00",
                    "open": "101.1",
                    "high": "102.2",
                    "low": "100.5",
                    "close": "102.0",
                    "vol": "12",
                    "amount": "34.5",
                    "ignored": "provider-extension",
                },
                {
                    "ts_code": "399001.SZ",
                    "trade_time": "2026-09-04 15:00:00",
                    "open": "102.0",
                    "high": "103.0",
                    "low": "101.8",
                    "close": "102.5",
                    "vol": "13",
                    "amount": "35.5",
                    "ignored": "provider-extension",
                },
            ]
        )

    def rt_idx_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.realtime_idx_calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "ts_code": "399001.SZ",
                    "time": "2026-09-07 09:55:00",
                    "open": "101.1",
                    "high": "102.2",
                    "low": "100.5",
                    "close": "102.0",
                    "vol": "12",
                    "amount": "34.5",
                },
                {
                    "ts_code": "399001.SZ",
                    "time": "2026-09-07 10:00:00",
                    "open": "102.0",
                    "high": "103.0",
                    "low": "101.8",
                    "close": "102.5",
                    "vol": "13",
                    "amount": "35.5",
                },
            ]
        )

    def index_daily(self, **kwargs: object) -> pd.DataFrame:
        self.daily_calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "ts_code": "399001.SZ",
                    "trade_date": "20260903",
                    "open": "98",
                    "high": "101",
                    "low": "97",
                    "close": "100",
                    "vol": "2",
                    "amount": "3",
                },
                {
                    "ts_code": "399001.SZ",
                    "trade_date": "20260904",
                    "open": "100",
                    "high": "102",
                    "low": "99",
                    "close": "101",
                    "vol": "4",
                    "amount": "5",
                },
            ]
        )


class _WrongRealtimeFrequencyClient(_Client):
    def rt_idx_min_daily(self, **kwargs: object) -> pd.DataFrame:
        frame = super().rt_idx_min_daily(**kwargs)
        frame["freq"] = "1MIN"
        return frame


def _ready_profile():
    return certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.DEFERRED
                if code is MarketIndexCode.BSE_50
                else TushareMarketIndexCapabilityStatus.READY
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )


@pytest.mark.parametrize("conflict_in_required_history", [False, True])
def test_index_daily_conflicts_are_checked_in_the_exact_required_history(
    conflict_in_required_history,
):
    class Client(_Client):
        def index_daily(self, **kwargs):
            frame = super().index_daily(**kwargs)
            duplicate = frame.iloc[[0]].copy()
            duplicate["close"] = "99"
            if not conflict_in_required_history:
                old = frame.iloc[[0]].copy()
                old["trade_date"] = "20260801"
                duplicate["trade_date"] = "20260801"
                return pd.concat([old, duplicate, frame], ignore_index=True)
            return pd.concat([frame, duplicate], ignore_index=True)

    provider = TushareMarketIndexProvider(
        client=Client(),
        profile=_ready_profile(),
        request_controller=_Controller(),
        now=lambda: datetime(2026, 9, 7, 10, 0, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    async def acquire():
        return await provider.acquire_index_data(
            index_code=MarketIndexCode.SHENZHEN_COMPONENT,
            decision_cutoff=datetime(2026, 9, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            five_minute_bar_count=2,
            official_daily_bar_count=2,
        )

    if conflict_in_required_history:
        with pytest.raises(TushareMarketIndexProviderError):
            asyncio.run(acquire())
    else:
        assert len(asyncio.run(acquire()).official_daily_bars) == 2


def test_certified_index_profile_requires_dedicated_evidence_values() -> None:
    profile = _ready_profile()

    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.END
    assert profile.five_minute_endpoint == "idx_mins"
    assert profile.realtime_five_minute_endpoint == "rt_idx_min_daily"
    assert profile.official_daily_endpoint == "index_daily"
    assert profile.capabilities[MarketIndexCode.BSE_50] is (
        TushareMarketIndexCapabilityStatus.DEFERRED
    )
    assert all(
        status is TushareMarketIndexCapabilityStatus.READY
        for code, status in profile.capabilities.items()
        if code is not MarketIndexCode.BSE_50
    )


def test_certified_index_provider_fetches_each_endpoint_once_and_normalizes_units() -> None:
    client = _Client()
    controller = _Controller()
    provider = TushareMarketIndexProvider(
        client=client,
        profile=_ready_profile(),
        request_controller=controller,
        now=lambda: datetime(2026, 9, 7, 10, 0, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    batch = asyncio.run(
        provider.acquire_index_data(
            index_code=MarketIndexCode.SHENZHEN_COMPONENT,
            decision_cutoff=datetime(
                2026,
                9,
                7,
                10,
                0,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
            five_minute_bar_count=2,
            official_daily_bar_count=2,
        )
    )

    assert controller.calls == [
        (TushareOperation.INDEX_MINUTES, "index:399001.SZ:20260907T1000:minutes"),
        (
            TushareOperation.INDEX_MINUTES,
            "index:399001.SZ:20260907T1000:realtime-minutes",
        ),
        (TushareOperation.INDEX_DAILY, "index:399001.SZ:20260907T1000:daily"),
    ]
    assert len(client.idx_calls) == 1
    assert len(client.realtime_idx_calls) == 1
    assert len(client.daily_calls) == 1
    assert [bar.bar_at.isoformat(timespec="minutes") for bar in batch.five_minute_bars] == [
        "2026-09-07T09:55+08:00",
        "2026-09-07T10:00+08:00",
    ]
    assert [bar.close_points for bar in batch.official_daily_bars] == [
        Decimal("100"),
        Decimal("101"),
    ]
    assert batch.official_daily_bars[-1].volume == Decimal("400")
    assert batch.official_daily_bars[-1].amount == Decimal("5000")
    assert all(bar.provider_revision == batch.content_revision for bar in batch.five_minute_bars)
    assert all(bar.provider_revision == batch.content_revision for bar in batch.official_daily_bars)


def test_index_provider_reuses_stable_reference_frames_during_intraday_refresh() -> None:
    client = _Client()
    controller = _Controller()
    provider = TushareMarketIndexProvider(
        client=client,
        profile=_ready_profile(),
        request_controller=controller,
        now=lambda: datetime(2026, 9, 7, 10, 5, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    async def scenario() -> None:
        for minute in (0, 5):
            await provider.acquire_index_data(
                index_code=MarketIndexCode.SHENZHEN_COMPONENT,
                decision_cutoff=datetime(
                    2026,
                    9,
                    7,
                    10,
                    minute,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                five_minute_bar_count=2,
                official_daily_bar_count=2,
            )

    asyncio.run(scenario())

    assert len(client.realtime_idx_calls) == 2
    assert len(client.idx_calls) == 1
    assert len(client.daily_calls) == 1
    assert [operation for operation, _work_key in controller.calls] == [
        TushareOperation.INDEX_MINUTES,
        TushareOperation.INDEX_MINUTES,
        TushareOperation.INDEX_DAILY,
        TushareOperation.INDEX_MINUTES,
    ]


def test_index_provider_rejects_wrong_returned_realtime_frequency() -> None:
    provider = TushareMarketIndexProvider(
        client=_WrongRealtimeFrequencyClient(),
        profile=_ready_profile(),
        request_controller=_Controller(),
        now=lambda: datetime(2026, 9, 7, 10, 0, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    with pytest.raises(TushareMarketIndexProviderError):
        asyncio.run(
            provider.acquire_index_data(
                index_code=MarketIndexCode.SHENZHEN_COMPONENT,
                decision_cutoff=datetime(
                    2026,
                    9,
                    7,
                    10,
                    0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                five_minute_bar_count=2,
                official_daily_bar_count=2,
            )
        )


def test_index_provider_fails_before_request_control_for_uncertified_index() -> None:
    profile = certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.DEFERRED
                if code is MarketIndexCode.BSE_50
                else TushareMarketIndexCapabilityStatus.READY
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    controller = _Controller()
    provider = TushareMarketIndexProvider(
        client=_Client(),
        profile=profile,
        request_controller=controller,
        now=lambda: datetime(2026, 9, 7, 10, 0, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    with pytest.raises(TushareMarketIndexProviderError):
        asyncio.run(
            provider.acquire_index_data(
                index_code=MarketIndexCode.BSE_50,
                decision_cutoff=datetime(
                    2026,
                    9,
                    7,
                    10,
                    0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                five_minute_bar_count=1,
                official_daily_bar_count=1,
            )
        )

    assert controller.calls == []


def test_certified_index_profile_rejects_ready_bse_50_while_live_scope_is_deferred() -> None:
    with pytest.raises(ValueError, match="BSE 50 live index is deferred"):
        certified_tushare_market_index_profile(
            capabilities={
                code: TushareMarketIndexCapabilityStatus.READY for code in MarketIndexCode
            },
            source_time_label=TushareMarketIndexSourceTimeLabel.END,
        )
