"""UPD-S1 provider-only final admission, with real wrappers and offline SDKs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from inspect import signature
from threading import Barrier, local
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from requests import Response
from requests.exceptions import HTTPError
from sqlalchemy.orm import Session

from trade_plan_monitor.market_data.provider import MarketDataProvider
from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.provider import LiveMarketIndexProvider
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.production import _CertifiedTushareClient
from trade_plan_monitor.runtime.request_control import RequestNotStartedError

CAPTURED = datetime(2026, 9, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
ANCHOR = CAPTURED.date() - timedelta(days=1)
INDEX = MarketIndexCode.SSE_COMPOSITE
OPERATIONS = ("trade_cal", "idx_mins")


def frame_for(operation):
    if operation == "trade_cal":
        return pd.DataFrame([{
            "exchange": "SSE", "cal_date": ANCHOR.strftime("%Y%m%d"), "is_open": 0,
            "pretrade_date": (ANCHOR - timedelta(days=1)).strftime("%Y%m%d"),
        }])
    return pd.DataFrame([{
        "ts_code": INDEX.value,
        "trade_time": (datetime.combine(ANCHOR, datetime.min.time()).replace(
            hour=hour, minute=minute,
        ) + timedelta(minutes=5 * offset)).strftime("%Y-%m-%d %H:%M:%S"),
        "open": "100", "close": "100", "high": "101", "low": "99",
        "vol": "1000", "amount": "10000",
    } for hour, minute in ((9, 35), (13, 5)) for offset in range(24)])


def provider_for(operation, client, now=lambda: CAPTURED):
    if operation == "trade_cal":
        return TushareMarketDataProvider(
            client, now=now,
            is_open_on=lambda _day: pytest.fail("provider proof cannot query calendar storage"),
        )
    return TushareMarketIndexProvider(
        client=client, now=now,
        profile=certified_tushare_market_index_profile(
            capabilities={code: (TushareMarketIndexCapabilityStatus.READY if code is INDEX
                                else TushareMarketIndexCapabilityStatus.DEFERRED)
                          for code in MarketIndexCode},
            source_time_label=TushareMarketIndexSourceTimeLabel.END,
        ),
    )


def invoke(provider, operation, **kwargs):
    if operation == "trade_cal":
        return provider.probe_trading_calendar_permission("SSE", ANCHOR, **kwargs)
    return provider.probe_historical_minutes_permission(INDEX, ANCHOR, **kwargs)


def expected_kwargs(operation):
    if operation == "trade_cal":
        return {
            "fields": "exchange,cal_date,is_open,pretrade_date", "exchange": "SSE",
            "start_date": ANCHOR.strftime("%Y%m%d"), "end_date": ANCHOR.strftime("%Y%m%d"),
        }
    return {
        "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
        "ts_code": INDEX.value, "freq": "5min",
        "start_date": f"{ANCHOR:%Y-%m-%d} 09:30:00",
        "end_date": f"{ANCHOR:%Y-%m-%d} 15:00:00",
    }


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("stage", ["certification", "resolution"])
@pytest.mark.parametrize("elapsed", [2, 15, 15.000001])
@pytest.mark.parametrize("revoked", [False, True])
def test_real_wrapper_and_resolution_finish_before_invocation_guard(
    operation, stage, elapsed, revoked,
):
    trace, calls, clock, authority = [], [], [CAPTURED], [True]
    def finish_stage(name):
        trace.append(name)
        if name == stage:
            clock[0] += timedelta(seconds=elapsed)
            authority[0] = not revoked
    def certification():
        finish_stage("certification")
        return True
    class SDK:
        def __getattr__(self, name):
            assert name == operation, "no dynamic SDK private protocol lookup"
            finish_stage("resolution")
            def endpoint(**kwargs):
                assert trace[-1] == "guard"
                trace.append("sdk")
                calls.append(kwargs)
                return frame_for(operation)
            return endpoint
    provider = provider_for(operation, _CertifiedTushareClient(SDK(), certification),
                            lambda: clock[0])
    sentinel = RequestNotStartedError("offline invocation guard revoked")
    def guard():
        trace.append("guard")
        if not authority[0] or clock[0] > CAPTURED + timedelta(seconds=15):
            raise sentinel
    if revoked or elapsed > 15:
        with pytest.raises(RequestNotStartedError) as caught:
            invoke(provider, operation, _physical_start=guard)
        assert caught.value is sentinel
        assert calls == [] and trace == ["certification", "resolution", "guard"]
    else:
        assert invoke(provider, operation, _physical_start=guard) is None
        assert calls == [expected_kwargs(operation)]
        assert trace == ["certification", "resolution", "guard", "sdk"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("error", [RequestNotStartedError("guard"), RuntimeError("guard"),
                                 ValueError("guard"), asyncio.CancelledError("guard")])
def test_guard_exceptions_preserve_original_identity_outside_classification(operation, error):
    calls = []
    provider = provider_for(operation, SimpleNamespace(**{
        operation: lambda **kwargs: calls.append(kwargs),
    }))
    def guard():
        raise error
    with pytest.raises(type(error)) as caught:
        invoke(provider, operation, _physical_start=guard)
    assert caught.value is error and calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_no_hook_and_opt_in_proofs_have_identical_kwargs_and_no_cache_changes(operation):
    calls, guards = [], []
    def endpoint(**kwargs):
        calls.append(kwargs)
        return frame_for(operation)
    provider = provider_for(operation, _CertifiedTushareClient(
        SimpleNamespace(**{operation: endpoint}), lambda: True,
    ))
    cached = frame_for(operation)
    if operation == "idx_mins":
        provider._historical_minute_cache[(INDEX, ANCHOR)] = cached
        provider._intraday_daily_cache[(INDEX, ANCHOR)] = cached
    assert invoke(provider, operation) is None
    assert invoke(provider, operation, _physical_start=lambda: guards.append(True)) is None
    assert invoke(provider, operation, _physical_start=None) is None
    assert guards == [True] and calls == [expected_kwargs(operation)] * 3
    if operation == "idx_mins":
        assert len(provider._historical_minute_cache) == len(provider._intraday_daily_cache) == 1
        assert provider._historical_minute_cache[(INDEX, ANCHOR)] is cached
        assert provider._intraday_daily_cache[(INDEX, ANCHOR)] is cached
    else:
        rows = provider.trading_calendar_for_exchange("SSE", ANCHOR, ANCHOR)
        assert len(rows) == 1 and rows[0].is_open is False
        assert calls[-1] == expected_kwargs(operation)
    assert "_physical_start" not in signature(MarketDataProvider.trading_calendar).parameters
    assert "_physical_start" not in signature(LiveMarketIndexProvider.acquire_index_data).parameters


@pytest.mark.parametrize("operation", OPERATIONS)
def test_concurrent_invocations_keep_their_guards_and_resolved_calls_private(
    operation, monkeypatch,
):
    state = local()
    barrier = Barrier(2)
    calls, resolutions = [], []
    class SDK:
        def __getattr__(self, name):
            assert name == operation
            invocation = state.invocation
            resolutions.append(invocation)
            def endpoint(**kwargs):
                assert state.invocation == invocation
                calls.append((invocation, kwargs))
                return frame_for(operation)
            return endpoint
    provider = provider_for(operation, _CertifiedTushareClient(SDK(), lambda: True))
    sentinel = RequestNotStartedError("first invocation only")
    def no_worker_access(*args, **kwargs):
        pytest.fail("provider worker accessed SQL or Task")
    monkeypatch.setattr(Session, "execute", no_worker_access)
    monkeypatch.setattr(asyncio, "current_task", no_worker_access)
    def run(invocation):
        state.invocation = invocation
        def guard():
            barrier.wait(timeout=3)
            if invocation == "first":
                raise sentinel
        return invoke(provider, operation, _physical_start=guard)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(run, "first"), pool.submit(run, "second")
        with pytest.raises(RequestNotStartedError) as caught:
            first.result(timeout=5)
        assert caught.value is sentinel and second.result(timeout=5) is None
    assert sorted(resolutions) == ["first", "second"]
    assert calls == [("second", expected_kwargs(operation))]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("status,code", [(403, "BLOCKED_PERMISSION"), (429, "RATE_LIMITED"),
                                      (500, "TRANSIENT")])
@pytest.mark.parametrize("with_hook", [False, True])
def test_actual_sdk_http_classification_is_unchanged(operation, status, code, with_hook):
    response = Response()
    response.status_code = status
    error = HTTPError("untrusted provider response", response=response)
    def endpoint(**kwargs):
        raise error
    provider = provider_for(operation, SimpleNamespace(**{operation: endpoint}))
    with pytest.raises(TushareProviderError) as caught:
        invoke(provider, operation, **({"_physical_start": lambda: None} if with_hook else {}))
    assert caught.value.code.value == code and caught.value.operation == operation
    assert "untrusted" not in str(caught.value)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("with_hook", [False, True])
def test_malformed_actual_response_keeps_existing_parser_failure(operation, with_hook):
    frame = frame_for(operation).iloc[0:0]
    provider = provider_for(operation, SimpleNamespace(**{operation: lambda **kwargs: frame}))
    with pytest.raises(TushareProviderError) as caught:
        invoke(provider, operation, **({"_physical_start": lambda: None} if with_hook else {}))
    assert caught.value.code.value == "INVALID_RESPONSE"


@pytest.mark.parametrize("operation", OPERATIONS)
def test_request_construction_finishes_before_guard_and_bad_identity_cannot_enter(
    operation,
):
    calls = []
    provider = provider_for(operation, SimpleNamespace(**{
        operation: lambda **kw: calls.append(kw),
    }))
    def guard():
        calls.append("guard")
    with pytest.raises((ValueError, TypeError, TushareProviderError)):
        if operation == "trade_cal":
            provider.probe_trading_calendar_permission("wrong", ANCHOR, _physical_start=guard)
        else:
            provider.probe_historical_minutes_permission("wrong", ANCHOR, _physical_start=guard)
    assert calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_real_wrapper_refusal_prevents_guard_and_sdk(operation):
    calls = []
    provider = provider_for(operation, _CertifiedTushareClient(
        SimpleNamespace(**{operation: lambda **kwargs: calls.append("sdk")}), lambda: False,
    ))
    with pytest.raises(RequestNotStartedError):
        invoke(provider, operation, _physical_start=lambda: calls.append("guard"))
    assert calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("error", [RequestNotStartedError("resolver"), RuntimeError("resolver")])
def test_resolution_failure_preserves_original_object_without_guard(operation, error):
    calls = []
    class SDK:
        def __getattr__(self, name):
            assert name == operation
            raise error
    provider = provider_for(operation, _CertifiedTushareClient(SDK(), lambda: True))
    with pytest.raises(type(error)) as caught:
        invoke(provider, operation, _physical_start=lambda: calls.append("guard"))
    assert caught.value is error and calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_each_sequential_invocation_resolves_its_own_endpoint(operation):
    calls = []
    sdk = SimpleNamespace(**{operation: lambda **kwargs: frame_for(operation)})
    provider = provider_for(operation, _CertifiedTushareClient(sdk, lambda: True))
    def endpoint(identity):
        def call(**kwargs):
            calls.append(identity)
            return frame_for(operation)
        return call
    setattr(sdk, operation, endpoint("first"))
    invoke(provider, operation, _physical_start=lambda: None)
    setattr(sdk, operation, endpoint("second"))
    invoke(provider, operation, _physical_start=lambda: None)
    assert calls == ["first", "second"]
