"""Opt-in business acquisition guard at the actual SDK boundary, entirely offline."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from inspect import signature
from threading import Barrier
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from requests import Response
from requests.exceptions import HTTPError

from trade_plan_monitor.market_data.provider import MarketDataProvider
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider, TushareProviderError
from trade_plan_monitor.runtime.production import _CertifiedTushareClient
from trade_plan_monitor.runtime.request_control import RequestNotStartedError

CAPTURED = datetime(2026, 9, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
SYMBOL = "600000.SH"


def _frame():
    return pd.DataFrame([{
        "ts_code": SYMBOL, "freq": "1MIN", "time": "2026-09-25 09:31:00",
        "open": "10", "close": "10", "high": "11", "low": "9",
        "vol": "100", "amount": "1000",
    }])


def _provider(client, now=lambda: CAPTURED):
    return TushareMarketDataProvider(
        client, now=now, is_open_on=lambda _day: True,
        source_time_label=SourceTimeLabel.END,
    )


@pytest.mark.parametrize("elapsed", [14, 15, 16])
@pytest.mark.parametrize("revoked", [False, True])
def test_business_guard_runs_after_real_wrapper_and_inner_resolution(elapsed, revoked):
    trace, calls, clock = [], [], [CAPTURED]

    class Client:
        def __getattr__(self, name):
            assert name == "rt_min_daily"
            trace.append("resolve")
            clock[0] += timedelta(seconds=elapsed)

            def endpoint(**kwargs):
                trace.append("sdk")
                calls.append(kwargs)
                return _frame()

            return endpoint

    def certification():
        trace.append("certification")
        return True

    sentinel = RequestNotStartedError("captured business attempt is no longer valid")

    def guard():
        trace.append("guard")
        if revoked or clock[0] > CAPTURED + timedelta(seconds=15):
            raise sentinel

    provider = _provider(_CertifiedTushareClient(Client(), certification), lambda: clock[0])
    if revoked or elapsed > 15:
        with pytest.raises(RequestNotStartedError) as caught:
            provider.current_day_minutes(SYMBOL, _physical_start=guard)
        assert caught.value is sentinel
        assert calls == []
        assert trace == ["certification", "resolve", "guard"]
    else:
        rows = provider.current_day_minutes(SYMBOL, _physical_start=guard)
        assert len(rows) == 1 and rows[0].symbol == SYMBOL
        assert trace == ["certification", "resolve", "guard", "sdk"]
        assert set(calls[0]) == {"fields", "ts_code", "freq"}
        assert calls[0]["freq"] == "1MIN" and calls[0]["ts_code"] == SYMBOL


@pytest.mark.parametrize("error", [
    RequestNotStartedError("guard"), RuntimeError("guard"), ValueError("guard"),
    asyncio.CancelledError("guard"),
])
def test_business_guard_errors_keep_identity_and_never_enter_sdk(error):
    calls = []
    provider = _provider(SimpleNamespace(rt_min_daily=lambda **kw: calls.append(kw)))

    def guard():
        raise error

    with pytest.raises(type(error)) as caught:
        provider.current_day_minutes(SYMBOL, _physical_start=guard)
    assert caught.value is error
    assert calls == []


def test_opt_in_hook_keeps_ordinary_rows_kwargs_and_generic_protocol_unchanged():
    calls, guards = [], []

    def endpoint(**kwargs):
        calls.append(kwargs)
        return _frame()

    client = _CertifiedTushareClient(SimpleNamespace(rt_min_daily=endpoint), lambda: True)
    provider = _provider(client)
    ordinary = provider.current_day_minutes(SYMBOL)
    explicit_none = provider.current_day_minutes(SYMBOL, _physical_start=None)
    guarded = provider.current_day_minutes(SYMBOL, _physical_start=lambda: guards.append(True))
    assert ordinary == explicit_none == guarded
    assert len(calls) == 3 and calls[0] == calls[1] == calls[2]
    assert guards == [True]
    assert tuple(signature(MarketDataProvider.current_day_minutes).parameters) == ("self", "symbol")


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_sdk_http_classification_matches_no_hook_path(status):
    guard_calls = []

    def endpoint(**_kwargs):
        response = Response()
        response.status_code = status
        raise HTTPError("not-for-display", response=response)

    provider = _provider(SimpleNamespace(rt_min_daily=endpoint))
    with pytest.raises(TushareProviderError) as ordinary:
        provider.current_day_minutes(SYMBOL)
    with pytest.raises(TushareProviderError) as guarded:
        provider.current_day_minutes(SYMBOL, _physical_start=lambda: guard_calls.append(True))
    assert guarded.value.code == ordinary.value.code
    assert guarded.value.failure_kind == ordinary.value.failure_kind
    assert guarded.value.http_status_class == ordinary.value.http_status_class
    assert "not-for-display" not in str(guarded.value)
    assert guard_calls == [True]


def test_two_business_invocations_do_not_share_or_replace_guards():
    calls, rendezvous = [], Barrier(2)
    provider = _provider(SimpleNamespace(rt_min_daily=lambda **kw: calls.append(kw) or _frame()))
    sentinel = RequestNotStartedError("only the first invocation is cancelled")

    def first_guard():
        rendezvous.wait(timeout=5)
        raise sentinel

    def second_guard():
        rendezvous.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(provider.current_day_minutes, SYMBOL, _physical_start=first_guard)
        second = pool.submit(provider.current_day_minutes, SYMBOL, _physical_start=second_guard)
        with pytest.raises(RequestNotStartedError) as caught:
            first.result(timeout=10)
        assert caught.value is sentinel
        assert len(second.result(timeout=10)) == 1
    assert len(calls) == 1


def test_bad_symbol_is_rejected_before_guard_or_sdk():
    calls = []
    provider = _provider(SimpleNamespace(rt_min_daily=lambda **kw: calls.append(kw)))
    with pytest.raises(ValueError):
        provider.current_day_minutes("not-a-symbol", _physical_start=lambda: calls.append("guard"))
    assert calls == []
