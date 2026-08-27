"""Incremental, resumable historical-data synchronization."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from threading import Thread
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.backtest.control import (
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.sync import BacktestSyncService
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider
from trade_plan_monitor.runtime.request_control import RequestPriority

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "600000.SH"
TRADE_DATE = date(2026, 8, 24)
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def trading_calendar(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[TradingDay, ...]:
        self.calls.append(("calendar", (exchange, start, end)))
        assert exchange == "SSE"
        return (
            TradingDay(
                exchange="SSE",
                cal_date=TRADE_DATE,
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        )

    def historical_minute_batch(self, symbol: str, trade_date: date) -> HistoricalMinuteBatch:
        self.calls.append(("minutes", (symbol, trade_date)))
        bars = tuple(
            MinuteBar(
                symbol=symbol,
                bar_end=bar_end,
                open_fen=1_000,
                high_fen=1_001,
                low_fen=999,
                close_fen=1_000,
                volume_shares=1_000,
                amount_yuan=Decimal("10000"),
                received_at=bar_end + timedelta(seconds=12),
            )
            for bar_end in expected_minute_ends(trade_date, is_open=True)
        )
        return HistoricalMinuteBatch(
            symbol=symbol,
            trade_date=trade_date,
            contract_version=PROFILE,
            bars=bars,
            opening_special=HistoricalOpeningSpecial(
                symbol=symbol,
                source_time=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                open_fen=1_000,
                high_fen=1_001,
                low_fen=999,
                close_fen=1_000,
                volume_shares=500,
                amount_yuan=Decimal("5000"),
            ),
        )

    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]:
        self.calls.append(("limits", trade_date))
        return (
            DailyLimit(
                symbol=SYMBOL,
                trade_date=trade_date,
                up_limit_fen=1_100,
                down_limit_fen=900,
                received_at=datetime.combine(trade_date, time(9, 30), SHANGHAI),
            ),
        )

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]:
        self.calls.append(("daily", (symbol, start, end)))
        return (
            DailyBar(
                symbol=symbol,
                trade_date=TRADE_DATE,
                open_fen=1_000,
                high_fen=1_050,
                low_fen=950,
                close_fen=1_020,
                volume_shares=2_000_000,
                amount_yuan=Decimal("20000000"),
                is_official=True,
                received_at=datetime.combine(TRADE_DATE, time(15, 20), SHANGHAI),
            ),
        )


class _Controller:
    def __init__(self) -> None:
        self.priorities: list[RequestPriority] = []

    async def execute(self, _operation, call, *, work_key, priority):
        assert work_key.startswith("backtest:")
        self.priorities.append(priority)
        return call()


def _scope() -> DatasetScope:
    return DatasetScope(
        symbols=(SYMBOL,),
        start=TRADE_DATE,
        end=TRADE_DATE,
        warmup_start=TRADE_DATE,
        historical_profile=PROFILE,
    )


def test_sync_fetches_missing_surfaces_then_repeats_without_network(tmp_path) -> None:
    provider = _Provider()
    controller = _Controller()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=controller,
        today=lambda: date(2026, 8, 25),
    )

    first = asyncio.run(service.sync(_scope()))
    first_calls = tuple(provider.calls)
    second = asyncio.run(service.sync(_scope()))

    assert first.calendar_rows == 1
    assert first.minute_days == 1
    assert first.daily_limit_rows == 1
    assert first.daily_bar_rows == 1
    assert first.network_calls == 4
    assert second.network_calls == 0
    assert tuple(provider.calls) == first_calls
    assert set(controller.priorities) == {RequestPriority.BACKGROUND}
    assert store.freeze_dataset(_scope()).ready is True


def test_cancellation_token_is_cross_thread_safe() -> None:
    token = CancellationToken()
    worker = Thread(target=token.cancel)

    worker.start()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert token.cancelled is True
    with pytest.raises(
        BacktestOperationCancelled,
        match="BACKTEST_OPERATION_CANCELLED:SYNC_CALENDAR",
    ):
        token.raise_if_cancelled("SYNC_CALENDAR")


def test_sync_cancel_before_first_surface_starts_no_provider_call(tmp_path) -> None:
    token = CancellationToken()
    token.cancel()
    provider = _Provider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )

    with pytest.raises(
        BacktestOperationCancelled,
        match="BACKTEST_OPERATION_CANCELLED:SYNC_CALENDAR",
    ):
        asyncio.run(service.sync(_scope(), cancellation_token=token))

    assert provider.calls == []
    assert store.statistics().artifact_count == 0


def test_sync_cancel_while_queued_starts_no_provider_call(tmp_path) -> None:
    token = CancellationToken()

    class CancellingAdmissionController:
        async def execute(self, _operation, call, *, work_key, priority):
            assert work_key.startswith("backtest:")
            assert priority is RequestPriority.BACKGROUND
            token.cancel()
            return call()

    provider = _Provider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=CancellingAdmissionController(),
        today=lambda: date(2026, 8, 25),
    )

    with pytest.raises(
        BacktestOperationCancelled,
        match="BACKTEST_OPERATION_CANCELLED:SYNC_CALENDAR",
    ):
        asyncio.run(service.sync(_scope(), cancellation_token=token))

    assert provider.calls == []
    assert store.statistics().artifact_count == 0


def test_sync_cancel_after_inflight_surface_commits_and_resubmit_reuses_fact(
    tmp_path,
) -> None:
    token = CancellationToken()

    class CancellingProvider(_Provider):
        def trading_calendar(
            self,
            exchange: str,
            start: date,
            end: date,
        ) -> tuple[TradingDay, ...]:
            values = super().trading_calendar(exchange, start, end)
            token.cancel()
            return values

    provider = CancellingProvider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )
    progress: list[BacktestProgress] = []

    with pytest.raises(
        BacktestOperationCancelled,
        match="BACKTEST_OPERATION_CANCELLED:SYNC_CALENDAR",
    ):
        asyncio.run(
            service.sync(
                _scope(),
                cancellation_token=token,
                progress_callback=progress.append,
            )
        )

    assert tuple(name for name, _ in provider.calls) == ("calendar",)
    assert store.has_head(f"CALENDAR:SSE:{TRADE_DATE.isoformat()}") is True
    assert store.has_head(f"DAILY:{SYMBOL}:{TRADE_DATE.isoformat()}") is False
    assert [(item.phase, item.completed_units, item.total_units) for item in progress] == [
        ("SYNC_CALENDAR", 1, 1)
    ]

    resumed = asyncio.run(service.sync(_scope()))
    frozen = store.freeze_dataset(_scope())
    completed_statistics = store.statistics()
    repeated = asyncio.run(service.sync(_scope()))
    refrozen = store.freeze_dataset(_scope())

    assert resumed.network_calls == 3
    assert repeated.network_calls == 0
    assert frozen.ready is True
    assert refrozen.dataset_hash == frozen.dataset_hash
    assert store.statistics() == completed_statistics


def test_sync_progress_is_bounded_and_excluded_from_dataset_identity(tmp_path) -> None:
    progress: list[BacktestProgress] = []
    first_store = BacktestMarketStore(tmp_path / "first.sqlite3")
    second_store = BacktestMarketStore(tmp_path / "second.sqlite3")
    first = BacktestSyncService(
        provider=_Provider(),
        store=first_store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )
    second = BacktestSyncService(
        provider=_Provider(),
        store=second_store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )

    asyncio.run(first.sync(_scope(), progress_callback=progress.append))
    asyncio.run(second.sync(_scope()))
    first_frozen = first_store.freeze_dataset(_scope())
    second_frozen = second_store.freeze_dataset(_scope())

    assert [item.phase for item in progress] == [
        "SYNC_CALENDAR",
        "SYNC_DAILY",
        "SYNC_MINUTE",
        "SYNC_LIMIT",
    ]
    assert all(
        item.completed_units == item.total_units == 1
        and set(item.model_dump()) == {"phase", "completed_units", "total_units"}
        for item in progress
    )
    assert first_frozen.dataset_hash == second_frozen.dataset_hash


def test_refresh_rechecks_content_without_duplicate_artifacts(tmp_path) -> None:
    provider = _Provider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )
    asyncio.run(service.sync(_scope()))
    before = store.statistics()

    refreshed = asyncio.run(service.sync(_scope(), refresh=True))

    assert refreshed.network_calls == 4
    assert store.statistics() == before


def test_sync_rejects_duplicate_raw_calendar_rows_from_the_real_adapter(tmp_path) -> None:
    row = {
        "exchange": "SSE",
        "cal_date": "20260824",
        "is_open": "1",
        "pretrade_date": "20260821",
    }

    class RawCalendarClient:
        def trade_cal(self, **_kwargs):
            return pd.DataFrame((row, dict(row)))

    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    provider = TushareHistoricalMinuteProvider(
        RawCalendarClient(),
        now=lambda: datetime(2026, 8, 25, 20, tzinfo=SHANGHAI),
        profile=PROFILE,
    )
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )

    with pytest.raises(TushareProviderError) as captured:
        asyncio.run(service.sync(_scope()))

    assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert store.statistics().artifact_count == 0


@pytest.mark.parametrize(
    ("surface", "error_surface"),
    (("calendar", "trade_cal"), ("daily", "daily"), ("limits", "stk_limit")),
)
def test_refresh_rejects_partial_reference_surfaces_before_persisting(
    tmp_path,
    surface: str,
    error_surface: str,
) -> None:
    class PartialRefreshProvider(_Provider):
        omitted: str | None = None

        def trading_calendar(
            self,
            exchange: str,
            start: date,
            end: date,
        ) -> tuple[TradingDay, ...]:
            values = super().trading_calendar(exchange, start, end)
            return () if self.omitted == "calendar" else values

        def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]:
            values = super().daily_bars(symbol, start, end)
            return () if self.omitted == "daily" else values

        def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]:
            values = super().daily_limits(trade_date)
            return () if self.omitted == "limits" else values

    provider = PartialRefreshProvider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )
    asyncio.run(service.sync(_scope()))
    before = store.statistics()
    provider.omitted = surface

    with pytest.raises(ValueError, match=f"INVALID_RESPONSE:{error_surface}"):
        asyncio.run(service.sync(_scope(), refresh=True))

    assert store.statistics() == before


def test_sync_rejects_current_or_future_dates_before_network(tmp_path) -> None:
    provider = _Provider()
    service = BacktestSyncService(
        provider=provider,
        store=BacktestMarketStore(tmp_path / "market.sqlite3"),
        request_controller=_Controller(),
        today=lambda: TRADE_DATE,
    )

    with pytest.raises(ValueError, match="closed historical dates"):
        asyncio.run(service.sync(_scope()))

    assert provider.calls == []


def test_sync_requests_sse_and_szse_calendars_separately(tmp_path) -> None:
    second_symbol = "000001.SZ"

    class MultiExchangeProvider(_Provider):
        def trading_calendar(
            self,
            exchange: str,
            start: date,
            end: date,
        ) -> tuple[TradingDay, ...]:
            self.calls.append(("calendar", (exchange, start, end)))
            return (
                TradingDay(
                    exchange=exchange,
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=date(2026, 8, 21),
                ),
            )

        def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]:
            self.calls.append(("limits", trade_date))
            return tuple(
                DailyLimit(
                    symbol=symbol,
                    trade_date=trade_date,
                    up_limit_fen=1_100,
                    down_limit_fen=900,
                    received_at=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                )
                for symbol in (SYMBOL, second_symbol)
            )

    scope = DatasetScope(
        symbols=(SYMBOL, second_symbol),
        start=TRADE_DATE,
        end=TRADE_DATE,
        warmup_start=TRADE_DATE,
        historical_profile=PROFILE,
    )
    provider = MultiExchangeProvider()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )

    result = asyncio.run(service.sync(scope))

    assert result.calendar_rows == 2
    assert result.network_calls == 7
    assert {arguments[0] for operation, arguments in provider.calls if operation == "calendar"} == {
        "SSE",
        "SZSE",
    }
    assert store.freeze_dataset(scope).ready is True


def test_dataset_scope_rejects_bse_before_store_or_provider_access(tmp_path) -> None:
    database_path = tmp_path / "market.sqlite3"
    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORICAL_CALENDAR:BSE"):
        DatasetScope(
            symbols=("920000.BJ",),
            start=TRADE_DATE,
            end=TRADE_DATE,
            warmup_start=TRADE_DATE,
            historical_profile=PROFILE,
        )

    assert not database_path.exists()


def test_dataset_scope_rejects_more_than_five_calendar_years() -> None:
    with pytest.raises(ValueError, match="cannot exceed 5 calendar years"):
        DatasetScope(
            symbols=(SYMBOL,),
            start=date(2021, 8, 24),
            end=date(2026, 8, 25),
            warmup_start=date(2020, 8, 24),
            historical_profile=PROFILE,
        )

    boundary = DatasetScope(
        symbols=(SYMBOL,),
        start=date(2021, 8, 24),
        end=date(2026, 8, 24),
        warmup_start=date(2020, 8, 24),
        historical_profile=PROFILE,
    )
    assert boundary.end == date(2026, 8, 24)

    with pytest.raises(ValueError, match="warmup range cannot exceed 2 calendar years"):
        DatasetScope(
            symbols=(SYMBOL,),
            start=TRADE_DATE,
            end=TRADE_DATE,
            warmup_start=date(1900, 1, 1),
            historical_profile=PROFILE,
        )
