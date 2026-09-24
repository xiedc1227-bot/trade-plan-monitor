"""A permission probe is one validated read-only calendar request."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)

ANCHOR = date(2026, 9, 23)


class CalendarClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def trade_cal(self, **kwargs):
        self.calls.append(kwargs)
        return pd.DataFrame(self.rows, columns=(
            "exchange", "cal_date", "is_open", "pretrade_date",
        ))


def _provider(client):
    return TushareMarketDataProvider(
        client,
        now=lambda: datetime(2026, 9, 24, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        is_open_on=lambda _: None,
    )


def _row(**changes):
    return {
        "exchange": "SSE", "cal_date": "20260923", "is_open": 1,
        "pretrade_date": "20260922",
    } | changes


def test_calendar_permission_probe_is_one_day_read_only_request():
    client = CalendarClient([_row()])
    assert _provider(client).probe_trading_calendar_permission("SSE", ANCHOR) is None
    assert client.calls == [{
        "fields": "exchange,cal_date,is_open,pretrade_date",
        "exchange": "SSE", "start_date": "20260923", "end_date": "20260923",
    }]


@pytest.mark.parametrize("rows", (
    [],
    [_row(cal_date="20260922")],
    [_row(exchange="SZSE")],
    [_row(), _row()],
    [_row(), _row(cal_date="20260922")],
    [_row(is_open="invalid")],
))
def test_calendar_permission_probe_rejects_empty_or_mixed_response(rows):
    with pytest.raises(TushareProviderError) as caught:
        _provider(CalendarClient(rows)).probe_trading_calendar_permission("SSE", ANCHOR)
    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
