"""Read-only daily endpoint proofs must validate the entire fake SDK batch."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from requests import Response
from requests.exceptions import HTTPError

from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
    TushareOperation,
    TushareRequestController,
)

ANCHOR = date(2026, 9, 7)
SYMBOL = "003043.SZ"
INDEX = MarketIndexCode.SSE_COMPOSITE
NOW = datetime(2026, 9, 8, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
LIMIT_FIELDS = "trade_date,ts_code,up_limit,down_limit"
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"


class SDK:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name: str):
        def request(**kwargs):
            self.calls.append((name, kwargs))
            return self.frame

        return request


def _stock(frame: pd.DataFrame) -> tuple[TushareMarketDataProvider, SDK]:
    sdk = SDK(frame)
    return TushareMarketDataProvider(
        sdk, now=lambda: NOW, is_open_on=lambda _day: True,
    ), sdk


def _index(frame: pd.DataFrame) -> tuple[TushareMarketIndexProvider, SDK]:
    sdk = SDK(frame)
    profile = certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.READY
                if code is INDEX else TushareMarketIndexCapabilityStatus.DEFERRED
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    return TushareMarketIndexProvider(profile=profile, client=sdk, now=lambda: NOW), sdk


def _limit_row(symbol: str = SYMBOL, **changes: object) -> dict[str, object]:
    return {
        "trade_date": "20260907", "ts_code": symbol,
        "up_limit": "75", "down_limit": "55",
    } | changes


def _daily_row(symbol: str, **changes: object) -> dict[str, object]:
    return {
        "ts_code": symbol, "trade_date": "20260907",
        "open": "100", "high": "101", "low": "99", "close": "100",
        "vol": "1000", "amount": "10000",
    } | changes


@pytest.mark.parametrize("row_count", (1, 5800))
def test_daily_limits_probe_requests_whole_market_without_plan_symbol(
    row_count: int,
) -> None:
    rows = [_limit_row(f"{index:06d}.SZ") for index in range(row_count)]
    provider, sdk = _stock(pd.DataFrame(rows))

    assert provider.probe_daily_limits_permission(ANCHOR) is None
    assert sdk.calls == [(
        "stk_limit", {"fields": LIMIT_FIELDS, "trade_date": "20260907"},
    )]


@pytest.mark.parametrize("row_count", (0, 5801))
def test_daily_limits_probe_rejects_empty_or_overbound_batch(row_count: int) -> None:
    rows = [_limit_row(f"{index:06d}.SZ") for index in range(row_count)]
    provider, sdk = _stock(pd.DataFrame(rows, columns=LIMIT_FIELDS.split(",")))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    assert len(sdk.calls) == 1


@pytest.mark.parametrize(
    "bad_row",
    (
        _limit_row(trade_date="20260908"),
        _limit_row(ts_code="bad"),
        _limit_row(up_limit="NaN"),
        _limit_row(down_limit="75"),
        _limit_row(down_limit="0"),
    ),
)
def test_daily_limits_probe_rejects_one_bad_row_in_whole_batch(bad_row) -> None:
    provider, _sdk = _stock(pd.DataFrame([_limit_row(), bad_row]))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_daily_limits_probe_rejects_duplicate_identity() -> None:
    provider, _sdk = _stock(pd.DataFrame([_limit_row(), _limit_row()]))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_daily_limits_probe_accepts_unique_extra_column() -> None:
    frame = pd.DataFrame([_limit_row()])
    frame["unexpected"] = "value"
    provider, _sdk = _stock(frame)

    assert provider.probe_daily_limits_permission(ANCHOR) is None


@pytest.mark.parametrize("column", ("up_limit", "unexpected"))
def test_daily_limits_probe_rejects_duplicate_column(column: str) -> None:
    frame = pd.DataFrame([_limit_row()])
    if column == "unexpected":
        frame[column] = "value"
    frame = pd.concat([frame, frame[[column]]], axis=1)
    provider, _sdk = _stock(frame)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_daily_limits_probe_rejects_missing_required_column() -> None:
    frame = pd.DataFrame([_limit_row()]).drop(columns="down_limit")
    provider, _sdk = _stock(frame)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_index_daily_probe_accepts_unique_extra_column() -> None:
    frame = pd.DataFrame([_daily_row(INDEX.value)])
    frame["unexpected"] = "value"
    provider, _sdk = _index(frame)

    assert provider.probe_official_daily_permission(INDEX, ANCHOR) is None


@pytest.mark.parametrize("column", ("close", "unexpected"))
def test_index_daily_probe_rejects_duplicate_column(column: str) -> None:
    frame = pd.DataFrame([_daily_row(INDEX.value)])
    if column == "unexpected":
        frame[column] = "value"
    frame = pd.concat([frame, frame[[column]]], axis=1)
    provider, _sdk = _index(frame)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_official_daily_permission(INDEX, ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_index_daily_probe_rejects_missing_required_column() -> None:
    frame = pd.DataFrame([_daily_row(INDEX.value)]).drop(columns="vol")
    provider, _sdk = _index(frame)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_official_daily_permission(INDEX, ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("upper", "lower"),
    (
        ("1" * 640, "1"),
        ("1e639", "1"),
        ("1", "1e-638"),
        ("1", "123e-638"),
        ("0.001", "0.0001"),
    ),
)
def test_daily_limits_probe_accepts_stock_raw_decimal_bound_and_sub_fen(
    upper: str, lower: str,
) -> None:
    provider, _sdk = _stock(pd.DataFrame([_limit_row(up_limit=upper, down_limit=lower)]))

    assert provider.probe_daily_limits_permission(ANCHOR) is None


@pytest.mark.parametrize(
    "price",
    (
        "1" * 641, "1e640", "1e-639", "123e-639", "0", "-1",
        "NaN", "Inf", True, object(), "bad",
    ),
)
def test_daily_limits_probe_rejects_unsafe_raw_price_in_mixed_batch(price) -> None:
    provider, _sdk = _stock(pd.DataFrame([
        _limit_row("001001.SZ"),
        _limit_row("001002.SZ", up_limit=price),
        _limit_row("001003.SZ"),
    ]))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_limits_permission(ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_daily_limits_probe_rejects_huge_values_before_string_expansion() -> None:
    for price in (10**10000, Decimal("1" * 641), Decimal("1e1000000")):
        with pytest.raises(ValueError):
            TushareMarketDataProvider._probe_limit_price(price)


def test_daily_bars_probe_requests_exact_symbol_day_and_requires_official_row() -> None:
    provider, sdk = _stock(pd.DataFrame([_daily_row(SYMBOL)]))

    assert provider.probe_daily_bars_permission(SYMBOL, ANCHOR) is None
    assert sdk.calls == [(
        "daily",
        {
            "fields": DAILY_FIELDS, "ts_code": SYMBOL,
            "start_date": "20260907", "end_date": "20260907",
        },
    )]


@pytest.mark.parametrize(
    "rows",
    (
        [],
        [_daily_row("600519.SH")],
        [_daily_row(SYMBOL, trade_date="20260908")],
        [_daily_row(SYMBOL), _daily_row(SYMBOL)],
        [_daily_row(SYMBOL), _daily_row("600519.SH")],
        [_daily_row(SYMBOL, close="NaN")],
    ),
)
def test_daily_bars_probe_rejects_empty_wrong_or_mixed_batch(rows) -> None:
    provider, _sdk = _stock(pd.DataFrame(rows, columns=DAILY_FIELDS.split(",")))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_daily_bars_permission(SYMBOL, ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


def test_index_daily_probe_requests_exact_certified_identity_without_cache() -> None:
    provider, sdk = _index(pd.DataFrame([_daily_row(INDEX.value)]))

    assert provider.probe_official_daily_permission(INDEX, ANCHOR) is None
    assert sdk.calls == [(
        "index_daily",
        {
            "fields": DAILY_FIELDS, "ts_code": INDEX.value,
            "start_date": "20260907", "end_date": "20260907",
        },
    )]
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}


@pytest.mark.parametrize(
    "rows",
    (
        [],
        [_daily_row(MarketIndexCode.STAR_50.value)],
        [_daily_row(INDEX.value, trade_date="20260908")],
        [_daily_row(INDEX.value), _daily_row(INDEX.value)],
        [_daily_row(INDEX.value), _daily_row(MarketIndexCode.STAR_50.value)],
        [_daily_row(INDEX.value, vol="NaN")],
    ),
)
def test_index_daily_probe_rejects_empty_wrong_or_mixed_batch(rows) -> None:
    provider, _sdk = _index(pd.DataFrame(rows, columns=DAILY_FIELDS.split(",")))

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_official_daily_permission(INDEX, ANCHOR)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (401, RequestControlErrorCode.BLOCKED_PERMISSION),
        (403, RequestControlErrorCode.BLOCKED_PERMISSION),
        (429, RequestControlErrorCode.RATE_LIMITED),
    ),
)
def test_index_daily_http_status_keeps_controller_permission_classification(
    status: int, expected: RequestControlErrorCode,
) -> None:
    token = "SECRET_FAKE_TOKEN"
    response = Response()
    response.status_code = status

    class FailingSDK:
        def index_daily(self, **_kwargs):
            raise HTTPError(f"opaque {token}", response=response)

    provider, _sdk = _index(pd.DataFrame([_daily_row(INDEX.value)]))
    provider._client = FailingSDK()

    class Clock:
        def now(self) -> datetime:
            return NOW

        async def sleep_until(self, _deadline: datetime) -> None:
            return None

    async def scenario() -> None:
        control = TushareRequestController(
            clock=Clock(), executor_workers=1, max_concurrency=1,
            min_interval=timedelta(0), jitter=timedelta(0), in_cycle_retries=0,
        )
        try:
            with pytest.raises(RequestControlError) as caught:
                await control.execute(
                    TushareOperation.INDEX_DAILY,
                    lambda: provider.probe_official_daily_permission(INDEX, ANCHOR),
                    work_key="index-proof",
                )
            assert caught.value.code is expected
            assert token not in str(caught.value)
            if status in (401, 403):
                assert control.is_permission_blocked(TushareOperation.INDEX_DAILY)
                assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
                assert control.cooldown_until is None
            else:
                assert not control.is_permission_blocked(TushareOperation.INDEX_DAILY)
                assert control.cooldown_until is not None
        finally:
            await control.aclose()

    asyncio.run(scenario())
    with pytest.raises(TushareProviderError) as direct:
        provider.probe_official_daily_permission(INDEX, ANCHOR)
    assert direct.value.__cause__ is None
    assert direct.value.__context__ is None
    assert token not in str(direct.value)


def test_index_daily_not_started_error_passes_through() -> None:
    sentinel = RequestNotStartedError("fake deferred provider start")

    class DeferredSDK:
        def index_daily(self, **_kwargs):
            raise sentinel

    provider, _sdk = _index(pd.DataFrame([_daily_row(INDEX.value)]))
    provider._client = DeferredSDK()

    with pytest.raises(RequestNotStartedError) as caught:
        provider.probe_official_daily_permission(INDEX, ANCHOR)

    assert caught.value is sentinel
