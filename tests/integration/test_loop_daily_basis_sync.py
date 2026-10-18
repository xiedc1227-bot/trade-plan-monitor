"""Factors backfill independently of already-cached raw bars and freeze fail closed."""

import asyncio
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from tests.integration.test_backtest_sync import (
    SHANGHAI,
    SYMBOL,
    TRADE_DATE,
    _Controller,
    _Provider,
    _scope,
)

from trade_plan_monitor.backtest.daily_basis import DailyBasisStore, HistoricalAdjustmentFactor
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.sync import BacktestSyncService


class FactorProvider(_Provider):
    def historical_adjustment_factors(self, symbol, start, end):
        self.calls.append(("adj_factor", (symbol, start, end)))
        return (
            HistoricalAdjustmentFactor(
                symbol=symbol,
                trade_date=TRADE_DATE,
                factor=Decimal("1.5"),
                available_at=datetime.combine(TRADE_DATE, time(9, 30), SHANGHAI),
                collected_at=datetime.combine(TRADE_DATE, time(16), SHANGHAI),
            ),
        )


def test_sync_backfills_factors_without_refetching_cached_prices(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")

    def service(provider):
        return BacktestSyncService(
            provider=provider,
            store=store,
            request_controller=_Controller(),
            today=lambda: date(2026, 8, 25),
        )

    asyncio.run(service(_Provider()).sync(_scope()))
    provider = FactorProvider()
    first = asyncio.run(service(provider).sync(_scope()))
    assert first.network_calls == 1
    assert [c[0] for c in provider.calls] == ["adj_factor"]
    values = DailyBasisStore(store.database_path).read(SYMBOL, TRADE_DATE, TRADE_DATE)
    assert len(values) == 1 and values[0].factor == Decimal("1.5")
    assert asyncio.run(service(provider).sync(_scope())).network_calls == 0
    assert len(provider.calls) == 1


def test_sync_rejects_incomplete_factor_coverage(tmp_path):
    provider = FactorProvider()
    provider.historical_adjustment_factors = lambda *args: ()
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    service = BacktestSyncService(
        provider=provider,
        store=store,
        request_controller=_Controller(),
        today=lambda: date(2026, 8, 25),
    )
    with pytest.raises(Exception, match="adj_factor"):
        asyncio.run(service.sync(_scope()))
    assert DailyBasisStore(store.database_path).read(SYMBOL, TRADE_DATE, TRADE_DATE) == ()
