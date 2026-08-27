"""Content-addressed historical market datasets for deterministic backtests."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import trade_plan_monitor.backtest.market_store as market_store_module
from trade_plan_monitor.backtest.control import (
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "600000.SH"
TRADE_DATE = date(2026, 8, 24)
PREVIOUS_TRADE_DATE = date(2026, 8, 21)
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


def _minute_batch(
    *,
    first_close_fen: int = 1_000,
    symbol: str = SYMBOL,
    trade_date: date = TRADE_DATE,
) -> HistoricalMinuteBatch:
    bars = []
    for index, bar_end in enumerate(expected_minute_ends(trade_date, is_open=True)):
        close_fen = first_close_fen if index == 0 else 1_000
        bars.append(
            MinuteBar(
                symbol=symbol,
                bar_end=bar_end,
                open_fen=1_000,
                high_fen=max(1_001, close_fen),
                low_fen=999,
                close_fen=close_fen,
                volume_shares=1_000 + index,
                amount_yuan=Decimal(10_000 + index),
                received_at=bar_end + timedelta(seconds=12),
            )
        )
    return HistoricalMinuteBatch(
        symbol=symbol,
        trade_date=trade_date,
        contract_version=PROFILE,
        bars=tuple(bars),
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


def _calendar() -> TradingDay:
    return TradingDay(
        exchange="SSE",
        cal_date=TRADE_DATE,
        is_open=True,
        previous_trade_date=PREVIOUS_TRADE_DATE,
    )


def _limit() -> DailyLimit:
    return DailyLimit(
        symbol=SYMBOL,
        trade_date=TRADE_DATE,
        up_limit_fen=1_100,
        down_limit_fen=900,
        received_at=datetime.combine(TRADE_DATE, time(9, 30), SHANGHAI),
    )


def _daily() -> DailyBar:
    return DailyBar(
        symbol=SYMBOL,
        trade_date=TRADE_DATE,
        open_fen=1_000,
        high_fen=1_050,
        low_fen=950,
        close_fen=1_020,
        volume_shares=2_000_000,
        amount_yuan=Decimal("20000000"),
        is_official=True,
        received_at=datetime.combine(TRADE_DATE, time(15, 20), SHANGHAI),
    )


def _seed_complete(store: BacktestMarketStore) -> None:
    store.record_minute_batch(_minute_batch())
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    store.record_daily_bars((_daily(),))


def _scope() -> DatasetScope:
    return DatasetScope(
        symbols=(SYMBOL,),
        start=TRADE_DATE,
        end=TRADE_DATE,
        warmup_start=TRADE_DATE,
        historical_profile=PROFILE,
    )


def test_identical_sync_is_a_noop_and_correction_creates_an_immutable_revision(
    tmp_path,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")

    first = store.record_minute_batch(_minute_batch())
    duplicate = store.record_minute_batch(_minute_batch())

    assert duplicate == first
    assert store.statistics().artifact_count == 1
    assert store.statistics().head_count == 1
    assert store.statistics().minute_artifact_count == 240
    assert store.statistics().minute_head_count == 240

    revised = store.record_minute_batch(_minute_batch(first_close_fen=1_002))

    assert revised != first
    assert store.statistics().artifact_count == 2
    assert store.statistics().head_count == 1
    assert store.statistics().minute_artifact_count == 241
    assert store.statistics().minute_head_count == 240
    assert store.head_revision(f"MINUTE:{SYMBOL}:{TRADE_DATE.isoformat()}") == 2


def test_decimal_scale_only_replay_keeps_artifacts_revisions_and_dataset_hash_stable(
    tmp_path,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    first = store.freeze_dataset(_scope())
    before = store.statistics()
    original_batch = _minute_batch()
    scaled_batch = HistoricalMinuteBatch(
        symbol=original_batch.symbol,
        trade_date=original_batch.trade_date,
        contract_version=original_batch.contract_version,
        bars=tuple(
            bar.model_copy(update={"amount_yuan": Decimal(f"{bar.amount_yuan}.00")})
            for bar in original_batch.bars
        ),
        opening_special=original_batch.opening_special.model_copy(
            update={"amount_yuan": Decimal("5000.000")}
        ),
    )

    store.record_minute_batch(scaled_batch)
    store.record_daily_bars((_daily().model_copy(update={"amount_yuan": Decimal("20000000.000")}),))
    second = store.freeze_dataset(_scope())

    assert second.dataset_hash == first.dataset_hash
    assert store.statistics() == before
    assert store.head_revision(f"MINUTE:{SYMBOL}:{TRADE_DATE.isoformat()}") == 1
    assert store.head_revision(f"DAILY:{SYMBOL}:{TRADE_DATE.isoformat()}") == 1


def test_frozen_dataset_keeps_old_revisions_after_a_provider_correction(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)

    first = store.freeze_dataset(_scope())
    duplicate = store.freeze_dataset(_scope())

    assert first.ready is True
    assert first.blockers == ()
    assert first.dataset_hash is not None
    assert duplicate.dataset_hash == first.dataset_hash
    assert store.statistics().dataset_count == 1

    store.record_minute_batch(_minute_batch(first_close_fen=1_002))
    revised = store.freeze_dataset(_scope())

    assert revised.ready is True
    assert revised.dataset_hash is not None
    assert revised.dataset_hash != first.dataset_hash
    assert store.statistics().dataset_count == 2
    old_bars = store.dataset_minutes(first.dataset_hash, SYMBOL, TRADE_DATE)
    new_bars = store.dataset_minutes(revised.dataset_hash, SYMBOL, TRADE_DATE)
    assert old_bars[0].close_fen == 1_000
    assert new_bars[0].close_fen == 1_002


def test_freeze_fails_closed_when_one_required_market_surface_is_missing(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    store.record_daily_bars((_daily(),))

    result = store.freeze_dataset(_scope())

    assert result.ready is False
    assert result.dataset_hash is None
    assert result.blockers == (f"MISSING_MINUTES:{SYMBOL}:{TRADE_DATE.isoformat()}",)
    assert store.statistics().dataset_count == 0


def test_freeze_fails_closed_when_a_price_exceeds_the_daily_limit(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    store.record_minute_batch(_minute_batch(first_close_fen=1_200))
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    store.record_daily_bars((_daily(),))

    result = store.freeze_dataset(_scope())

    assert result.ready is False
    assert result.dataset_hash is None
    assert result.blockers == (f"PRICE_OUTSIDE_DAILY_LIMIT:{SYMBOL}:{TRADE_DATE.isoformat()}",)
    assert store.statistics().dataset_count == 0


def test_market_store_reopens_with_stable_dataset_content(tmp_path) -> None:
    path = tmp_path / "market.sqlite3"
    first_store = BacktestMarketStore(path)
    _seed_complete(first_store)
    frozen = first_store.freeze_dataset(_scope())
    assert frozen.dataset_hash is not None

    reopened = BacktestMarketStore(path)

    assert reopened.statistics().dataset_count == 1
    assert reopened.dataset_manifest(frozen.dataset_hash).dataset_hash == frozen.dataset_hash
    assert len(reopened.dataset_minutes(frozen.dataset_hash, SYMBOL, TRADE_DATE)) == 240
    assert reopened.dataset_daily_limit(frozen.dataset_hash, SYMBOL, TRADE_DATE) == _limit()
    assert reopened.dataset_daily_bar(frozen.dataset_hash, SYMBOL, TRADE_DATE) == _daily()


def test_market_store_rejects_wall_clock_receipts_from_historical_reference_facts(
    tmp_path,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")

    with pytest.raises(ValueError, match="deterministic 09:30"):
        store.record_daily_limits(
            (
                _limit().model_copy(
                    update={"received_at": _limit().received_at + timedelta(hours=1)}
                ),
            )
        )
    with pytest.raises(ValueError, match="deterministic 15:20"):
        store.record_daily_bars(
            (
                _daily().model_copy(
                    update={"received_at": _daily().received_at + timedelta(minutes=1)}
                ),
            )
        )


def test_two_symbol_two_day_dataset_reuses_indexed_minute_artifacts(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    first_date = date(2026, 8, 21)
    second_symbol = "000001.SZ"
    calendar: list[TradingDay] = []
    for exchange in ("SSE", "SZSE"):
        calendar.extend(
            (
                TradingDay(
                    exchange=exchange,
                    cal_date=first_date,
                    is_open=True,
                    previous_trade_date=date(2026, 8, 20),
                ),
                TradingDay(
                    exchange=exchange,
                    cal_date=date(2026, 8, 22),
                    is_open=False,
                    previous_trade_date=first_date,
                ),
                TradingDay(
                    exchange=exchange,
                    cal_date=date(2026, 8, 23),
                    is_open=False,
                    previous_trade_date=first_date,
                ),
                TradingDay(
                    exchange=exchange,
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=first_date,
                ),
            )
        )
    store.record_trading_days(tuple(calendar))
    daily: list[DailyBar] = []
    limits: list[DailyLimit] = []
    for symbol in (SYMBOL, second_symbol):
        for trade_date in (first_date, TRADE_DATE):
            store.record_minute_batch(_minute_batch(symbol=symbol, trade_date=trade_date))
            daily.append(
                _daily().model_copy(
                    update={
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "received_at": datetime.combine(trade_date, time(15, 20), SHANGHAI),
                    }
                )
            )
            limits.append(
                _limit().model_copy(
                    update={
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "received_at": datetime.combine(trade_date, time(9, 30), SHANGHAI),
                    }
                )
            )
    store.record_daily_bars(tuple(daily))
    store.record_daily_limits(tuple(limits))

    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=(second_symbol, SYMBOL),
            start=first_date,
            end=TRADE_DATE,
            warmup_start=first_date,
            historical_profile=PROFILE,
        )
    )

    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    assert store.statistics().minute_artifact_count == 960
    assert len(store.dataset_minutes(frozen.dataset_hash, second_symbol, first_date)) == 240


def test_verify_and_frozen_reads_reject_tampered_minute_content(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    frozen = store.freeze_dataset(_scope())
    assert frozen.dataset_hash is not None

    with closing(sqlite3.connect(store.database_path)) as connection:
        row = connection.execute(
            """
            SELECT artifact_hash, content_json
            FROM market_minute_artifact
            ORDER BY bar_end
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        content = json.loads(str(row[1]))
        content["close_fen"] = content["high_fen"]
        connection.execute(
            "UPDATE market_minute_artifact SET content_json = ? WHERE artifact_hash = ?",
            (json.dumps(content, sort_keys=True, separators=(",", ":")), str(row[0])),
        )
        connection.commit()

    verified = store.freeze_dataset(_scope())
    assert verified.ready is False
    assert verified.blockers == (f"INVALID_MINUTE:{SYMBOL}:{TRADE_DATE.isoformat()}",)
    with pytest.raises(RuntimeError, match="frozen minute day manifest"):
        store.dataset_minutes(frozen.dataset_hash, SYMBOL, TRADE_DATE)


def test_dataset_manifest_rejects_membership_tampering(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    frozen = store.freeze_dataset(_scope())
    assert frozen.dataset_hash is not None

    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute(
            """
            UPDATE market_dataset_item
            SET symbol = '000001.SZ'
            WHERE dataset_hash = ? AND kind = 'MINUTE'
            """,
            (frozen.dataset_hash,),
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="membership"):
        store.dataset_manifest(frozen.dataset_hash)


def test_freeze_rejects_a_head_correction_between_validation_and_publication(
    tmp_path,
    monkeypatch,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    original_identity = market_store_module._dataset_identity
    corrected = False

    def correct_head_after_read(scope, items):
        nonlocal corrected
        if not corrected:
            corrected = True
            store.record_minute_batch(_minute_batch(first_close_fen=1_002))
        return original_identity(scope, items)

    monkeypatch.setattr(
        market_store_module,
        "_dataset_identity",
        correct_head_after_read,
    )

    with pytest.raises(RuntimeError, match="heads changed"):
        store.freeze_dataset(_scope())

    assert corrected is True
    assert store.statistics().dataset_count == 0


def test_freeze_cancel_during_publication_rolls_back_and_resubmit_is_complete(
    tmp_path,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    token = CancellationToken()
    progress: list[BacktestProgress] = []

    def cancel_publication(value: BacktestProgress) -> None:
        progress.append(value)
        if value.phase == "FREEZE_PUBLISH":
            token.cancel()

    with pytest.raises(
        BacktestOperationCancelled,
        match="BACKTEST_OPERATION_CANCELLED:FREEZE_PUBLISH",
    ):
        store.freeze_dataset(
            _scope(),
            cancellation_token=token,
            progress_callback=cancel_publication,
        )

    assert [item.phase for item in progress] == ["FREEZE_VERIFY", "FREEZE_PUBLISH"]
    assert store.statistics().dataset_count == 0
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_dataset_item").fetchone() == (0,)

    frozen = store.freeze_dataset(_scope())
    completed_statistics = store.statistics()
    refrozen = store.freeze_dataset(_scope())

    assert frozen.ready is True
    assert refrozen.dataset_hash == frozen.dataset_hash
    assert store.statistics() == completed_statistics
