"""Synthetic historical provider for real-worker/browser preparation checks."""

from datetime import timedelta
from types import SimpleNamespace

from tests.integration.test_backtest_market_store import _daily, _minute_batch
from tests.integration.test_monitor_loop_cycle import frames
from tests.unit.test_monitor_loop_schedule import at


def bind_provider(monkeypatch, market):
    import trade_plan_monitor.backtest.application as application

    source = tuple(frames())
    literal = {frame.minute.bar_end: frame.minute for frame in source}
    calls = []

    class Provider:
        def trading_calendar(self, exchange, start, end):
            from trade_plan_monitor.market_data.models import TradingDay

            calls.append("calendar")
            rows = []
            day = start
            while day <= end:
                existing = market.current_trading_day(exchange, day)
                previous = day - timedelta(days=1)
                while previous.weekday() >= 5:
                    previous -= timedelta(days=1)
                rows.append(existing or TradingDay(exchange=exchange, cal_date=day,
                    is_open=day.weekday() < 5, previous_trade_date=previous))
                day += timedelta(days=1)
            return tuple(rows)

        def historical_minute_batch(self, symbol, day):
            calls.append("minutes")
            batch = _minute_batch(symbol=symbol, trade_date=day)
            last = source[-1].minute
            bars = tuple(literal.get(bar.bar_end, bar.model_copy(update={
                "open_fen": last.close_fen, "high_fen": last.close_fen,
                "low_fen": last.close_fen, "close_fen": last.close_fen,
            })).model_copy(update={"symbol": symbol}) for bar in batch.bars)
            return batch.model_copy(update={"bars": bars})

        def daily_limits(self, day):
            calls.append("limits")
            return (source[0].daily_limit.model_copy(update={
                "symbol": "002240.SZ", "trade_date": day,
                "received_at": at(day.day, 9, 30),
            }),)

        def daily_bars(self, symbol, start, end):
            calls.append("daily")
            return tuple(_daily().model_copy(update={
                "symbol": symbol, "trade_date": start + timedelta(days=index),
                "open_fen": 4000, "high_fen": 4100, "low_fen": 3900, "close_fen": 4020,
                "received_at": at((start + timedelta(days=index)).day, 15, 20),
            }) for index in range((end - start).days + 1)
                if (start + timedelta(days=index)).weekday() < 5)

    monkeypatch.setattr(application, "load_application_config", lambda _path: SimpleNamespace(
        tushare=SimpleNamespace(timeout_seconds=2, model_copy=lambda **_kwargs: None),
    ))
    monkeypatch.setattr(application, "create_tushare_client", lambda _config: None)
    monkeypatch.setattr(application, "TushareHistoricalMinuteProvider",
                        lambda *_args, **_kwargs: Provider())
    return calls
