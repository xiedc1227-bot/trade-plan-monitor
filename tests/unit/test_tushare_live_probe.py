"""Offline contracts for sanitized stock and board-index live probes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.models import ProviderCapabilityStatus
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)
from trade_plan_monitor.runtime.request_control import TushareOperation
from trade_plan_monitor.tushare_live_probe import certify_board_indexes, certify_stock

SHANGHAI = ZoneInfo("Asia/Shanghai")
OBSERVED_AT = datetime(2026, 9, 7, 10, 15, 2, tzinfo=SHANGHAI)
AFTERNOON_OBSERVED_AT = datetime(2026, 9, 7, 14, 46, 2, tzinfo=SHANGHAI)
STOCK_AFTERNOON_OBSERVED_AT = datetime(2026, 9, 7, 13, 18, 13, tzinfo=SHANGHAI)


class _Controller:
    def __init__(self) -> None:
        self.calls: list[TushareOperation] = []

    async def execute(
        self,
        operation: TushareOperation,
        call: object,
        *,
        work_key: str,
        priority: object,
    ) -> object:
        del work_key, priority
        self.calls.append(operation)
        assert callable(call)
        return call()


class _Client:
    def __init__(self, *, blocked_index: str | None = None) -> None:
        self.blocked_index = blocked_index
        self.calls: list[tuple[str, dict[str, object]]] = []

    def trade_cal(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame(
            [
                {
                    "exchange": "SSE",
                    "cal_date": "20260904",
                    "is_open": "1",
                    "pretrade_date": "20260903",
                },
                {
                    "exchange": "SSE",
                    "cal_date": "20260907",
                    "is_open": "1",
                    "pretrade_date": "20260904",
                },
            ]
        )

    def stk_limit(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260904",
                    "ts_code": "600000.SH",
                    "up_limit": "11",
                    "down_limit": "9",
                }
            ]
        )

    def daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260904",
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
            ]
        )

    def rt_min(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_min", kwargs))
        symbols = str(kwargs["ts_code"]).split(",")
        return pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "time": "2026-09-07 10:14:00",
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
                for symbol in symbols
            ]
        )

    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_min_daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "freq": "1MIN",
                    "time": timestamp,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
                for timestamp in pd.date_range(
                    "2026-09-07 09:30:00",
                    "2026-09-07 10:15:00",
                    freq="min",
                )
            ]
        )

    def idx_mins(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("idx_mins", kwargs))
        code = str(kwargs["ts_code"])
        if code == self.blocked_index:
            raise RuntimeError("permission denied")
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_time": "2026-09-04 09:30:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                },
                {
                    "ts_code": code,
                    "trade_time": "2026-09-04 15:00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                },
            ]
        )

    def rt_idx_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_idx_min_daily", kwargs))
        code = str(kwargs["ts_code"])
        if code == self.blocked_index:
            raise RuntimeError("permission denied")
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "time": "2026-09-07 09:30:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                },
                {
                    "ts_code": code,
                    "time": "2026-09-07 10:10:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                },
            ]
        )

    def index_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("index_daily", kwargs))
        code = str(kwargs["ts_code"])
        if code == self.blocked_index:
            raise RuntimeError("permission denied")
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": "20260904",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                }
            ]
        )


class _RateLimitedStockClient(_Client):
    def daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("daily", kwargs))
        raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "daily")


class _OpeningSnapshotEndLabeledStockClient(_Client):
    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_min_daily", kwargs))
        morning = pd.date_range(
            "2026-09-07 09:30:00",
            "2026-09-07 11:30:00",
            freq="min",
        )
        afternoon = pd.date_range(
            "2026-09-07 13:01:00",
            "2026-09-07 13:18:00",
            freq="min",
        )
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "time": timestamp,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
                for timestamp in (*morning, *afternoon)
            ]
        )


class _MissingCurrentDayFrequencyClient(_OpeningSnapshotEndLabeledStockClient):
    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        return super().rt_min_daily(**kwargs).drop(columns="freq", errors="ignore")


class _OpeningSnapshotOnlyStockClient(_Client):
    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_min_daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "time": "2026-09-07 09:30:00",
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
            ]
        )


class _OpeningSnapshotEndLabeledStockClientWithGap(_OpeningSnapshotEndLabeledStockClient):
    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        frame = super().rt_min_daily(**kwargs)
        return frame.loc[frame["time"] != pd.Timestamp("2026-09-07 13:07:00")]


class _StockTimestampShapeClient(_Client):
    def __init__(self, timestamps: tuple[str, ...]) -> None:
        super().__init__()
        self.timestamps = timestamps

    def rt_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_min_daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "time": timestamp,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "vol": "100",
                    "amount": "200",
                }
                for timestamp in self.timestamps
            ]
        )


class _WrongIndexFrequencyClient(_Client):
    def rt_idx_min_daily(self, **kwargs: object) -> pd.DataFrame:
        frame = super().rt_idx_min_daily(**kwargs)
        frame["freq"] = "1MIN"
        return frame


class _OpeningSnapshotEndLabeledIndexClient(_Client):
    def rt_idx_min_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("rt_idx_min_daily", kwargs))
        code = str(kwargs["ts_code"])
        columns = (
            "ts_code",
            "freq",
            "time",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
        )
        if code == MarketIndexCode.BSE_50.value:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "freq": "5MIN",
                    "time": f"2026-09-07 {clock_time}:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "vol": "100",
                    "amount": "200",
                }
                for clock_time in (
                    "09:30",
                    "09:35",
                    "11:30",
                    "13:05",
                    "14:45",
                    "14:50",
                )
            ],
            columns=columns,
        )


def test_stock_probe_certifies_all_surfaces_and_end_labeled_minutes(
    tmp_path: Path,
) -> None:
    client = _OpeningSnapshotEndLabeledStockClient()
    controller = _Controller()

    profile = asyncio.run(
        certify_stock(
            client=client,
            request_controller=controller,
            observed_at=STOCK_AFTERNOON_OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.ready
    assert profile.source_time_label is SourceTimeLabel.END
    assert set(profile.capabilities.model_dump(mode="python").values()) == {
        ProviderCapabilityStatus.READY
    }
    assert controller.calls == [
        TushareOperation.TRADING_CALENDAR,
        TushareOperation.DAILY_LIMITS,
        TushareOperation.DAILY_BARS,
        TushareOperation.REALTIME_MINUTES,
        TushareOperation.CURRENT_DAY_MINUTES,
        TushareOperation.CURRENT_DAY_MINUTES,
    ]
    assert (tmp_path / "stock.json").is_file()


def test_stock_probe_accepts_omitted_fixed_current_day_frequency(
    tmp_path: Path,
) -> None:
    profile = asyncio.run(
        certify_stock(
            client=_MissingCurrentDayFrequencyClient(),
            request_controller=_Controller(),
            observed_at=STOCK_AFTERNOON_OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.ready
    assert profile.source_time_label is SourceTimeLabel.END
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.READY


def test_stock_probe_accepts_opening_snapshot_before_complete_end_labeled_minutes(
    tmp_path: Path,
) -> None:
    profile = asyncio.run(
        certify_stock(
            client=_OpeningSnapshotEndLabeledStockClient(),
            request_controller=_Controller(),
            observed_at=STOCK_AFTERNOON_OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.source_time_label is SourceTimeLabel.END
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.READY


def test_stock_probe_accepts_legal_end_labeled_minutes_with_an_intraday_gap(
    tmp_path: Path,
) -> None:
    profile = asyncio.run(
        certify_stock(
            client=_OpeningSnapshotEndLabeledStockClientWithGap(),
            request_controller=_Controller(),
            observed_at=STOCK_AFTERNOON_OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.source_time_label is SourceTimeLabel.END
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.READY


def test_stock_probe_rejects_opening_snapshot_without_session_boundary_evidence(
    tmp_path: Path,
) -> None:
    profile = asyncio.run(
        certify_stock(
            client=_OpeningSnapshotOnlyStockClient(),
            request_controller=_Controller(),
            observed_at=OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.source_time_label is SourceTimeLabel.UNVERIFIED
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.ERROR


@pytest.mark.parametrize(
    "timestamps",
    (
        ("2026-09-07 09:30:00", "2026-09-07 09:32:00"),
        (
            "2026-09-07 09:30:00",
            "2026-09-07 09:31:00",
            "2026-09-07 12:00:00",
        ),
        tuple(
            timestamp.strftime("%Y-%m-%d %H:%M:%S")
            for timestamp in pd.date_range(
                "2026-09-07 09:30:00",
                "2026-09-07 10:15:00",
                freq="min",
            )
        ),
    ),
    ids=("truncated-prefix", "mixed-session", "ambiguous-morning-prefix"),
)
def test_stock_probe_rejects_unproven_opening_snapshot_shapes(
    tmp_path: Path,
    timestamps: tuple[str, ...],
) -> None:
    profile = asyncio.run(
        certify_stock(
            client=_StockTimestampShapeClient(timestamps),
            request_controller=_Controller(),
            observed_at=OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.source_time_label is SourceTimeLabel.UNVERIFIED
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.ERROR


def test_index_probe_keeps_authorization_and_failures_per_index(tmp_path: Path) -> None:
    client = _Client(blocked_index=MarketIndexCode.STAR_50.value)
    controller = _Controller()

    profile = asyncio.run(
        certify_board_indexes(
            client=client,
            request_controller=controller,
            observed_at=OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "index.json",
        )
    )

    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.START
    assert profile.capabilities[MarketIndexCode.STAR_50] is (
        TushareMarketIndexCapabilityStatus.BLOCKED_PERMISSION
    )
    assert profile.capabilities[MarketIndexCode.BSE_50] is (
        TushareMarketIndexCapabilityStatus.DEFERRED
    )
    assert all(
        status is TushareMarketIndexCapabilityStatus.READY
        for code, status in profile.capabilities.items()
        if code not in {MarketIndexCode.STAR_50, MarketIndexCode.BSE_50}
    )
    assert controller.calls[0] is TushareOperation.TRADING_CALENDAR
    assert controller.calls.count(TushareOperation.INDEX_MINUTES) == 2 * (len(MarketIndexCode) - 1)
    assert controller.calls.count(TushareOperation.INDEX_DAILY) == len(MarketIndexCode) - 1
    assert all(
        kwargs.get("ts_code") != MarketIndexCode.BSE_50.value
        for endpoint, kwargs in client.calls
        if endpoint in {"idx_mins", "rt_idx_min_daily", "index_daily"}
    )
    assert (tmp_path / "index.json").is_file()


def test_index_probe_rejects_wrong_returned_realtime_frequency(tmp_path: Path) -> None:
    profile = asyncio.run(
        certify_board_indexes(
            client=_WrongIndexFrequencyClient(),
            request_controller=_Controller(),
            observed_at=OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "index.json",
        )
    )

    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED
    assert set(profile.capabilities.values()) == {
        TushareMarketIndexCapabilityStatus.ERROR,
        TushareMarketIndexCapabilityStatus.DEFERRED,
    }


def test_index_probe_accepts_opening_snapshot_before_end_labeled_bars(
    tmp_path: Path,
) -> None:
    profile = asyncio.run(
        certify_board_indexes(
            client=_OpeningSnapshotEndLabeledIndexClient(),
            request_controller=_Controller(),
            observed_at=AFTERNOON_OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "index.json",
        )
    )

    assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.END
    assert profile.capabilities[MarketIndexCode.BSE_50] is (
        TushareMarketIndexCapabilityStatus.DEFERRED
    )
    assert profile.ready_indexes == frozenset(
        code for code in MarketIndexCode if code is not MarketIndexCode.BSE_50
    )


def test_stock_probe_stops_every_later_call_after_first_rate_limit(tmp_path: Path) -> None:
    client = _RateLimitedStockClient()
    controller = _Controller()

    profile = asyncio.run(
        certify_stock(
            client=client,
            request_controller=controller,
            observed_at=OBSERVED_AT,
            endpoint_url="https://api.quicksync.cn",
            output_path=tmp_path / "stock.json",
        )
    )

    assert profile.capabilities.daily_bars is ProviderCapabilityStatus.RATE_LIMITED
    assert profile.capabilities.realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert profile.capabilities.current_day_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert controller.calls == [
        TushareOperation.TRADING_CALENDAR,
        TushareOperation.DAILY_LIMITS,
        TushareOperation.DAILY_BARS,
    ]
