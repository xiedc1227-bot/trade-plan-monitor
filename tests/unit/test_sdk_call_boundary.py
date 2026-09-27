"""Final SDK admission through real certification wrappers, entirely offline."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, local
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from test_minute_permission_transport import _installed

from trade_plan_monitor.market_data.sessions import SourceTimeLabel
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
from trade_plan_monitor.runtime.production import _CertifiedTushareClient
from trade_plan_monitor.runtime.request_control import RequestNotStartedError

CAPTURED = datetime(2026, 9, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
SYMBOL = "600000.SH"
MINUTE_METHODS = {
    "rt_min_daily": "probe_current_day_minutes_permission",
    "rt_min": "probe_realtime_minutes_permission",
}
OPERATIONS = (*MINUTE_METHODS, "daily", "stk_limit", "index_daily", "rt_idx_min_daily")
INDEX = MarketIndexCode.SSE_COMPOSITE
ANCHOR = CAPTURED.date() - timedelta(days=1)


def minute_frame():
    return pd.DataFrame([{
        "ts_code": SYMBOL, "time": "2026-09-25 09:31:00",
        "open": "10", "close": "10", "high": "11", "low": "9",
        "vol": "100", "amount": "1000",
    }])


@pytest.mark.parametrize("operation", MINUTE_METHODS)
def test_pb01_real_wrapper_cannot_enter_at_16_seconds_after_guard_at_14(operation):
    clock = [CAPTURED + timedelta(seconds=14)]
    calls = []
    def certification():
        clock[0] += timedelta(seconds=2)
        return True
    def endpoint(**kwargs):
        calls.append((clock[0], kwargs))
        return minute_frame()
    client = _CertifiedTushareClient(SimpleNamespace(**{operation: endpoint}), certification)
    provider = TushareMarketDataProvider(
        client, now=lambda: clock[0], is_open_on=lambda _day: True,
        source_time_label=SourceTimeLabel.END,
    )
    sentinel = RequestNotStartedError("final SDK admission expired")
    def start():
        at = clock[0]
        if not CAPTURED <= at <= CAPTURED + timedelta(seconds=15):
            raise sentinel
        return at
    with pytest.raises(RequestNotStartedError) as caught:
        getattr(provider, MINUTE_METHODS[operation])(
            SYMBOL, CAPTURED.date(), physical_start=start,
        )
    assert caught.value is sentinel
    assert calls == []


def response_for(operation):
    if operation in MINUTE_METHODS:
        return minute_frame()
    if operation == "stk_limit":
        return pd.DataFrame([{
            "trade_date": ANCHOR.strftime("%Y%m%d"), "ts_code": SYMBOL,
            "up_limit": "11", "down_limit": "9",
        }])
    row = {
        "ts_code": SYMBOL if operation == "daily" else INDEX.value,
        "open": "10", "close": "10", "high": "11", "low": "9",
        "vol": "100", "amount": "1000",
    }
    if operation == "rt_idx_min_daily":
        row.update(time="2026-09-25 09:35:00", freq="5MIN")
    else:
        row["trade_date"] = ANCHOR.strftime("%Y%m%d")
    return pd.DataFrame([row])


def provider_for(operation, client, clock):
    if operation not in {"index_daily", "rt_idx_min_daily"}:
        return TushareMarketDataProvider(
            client, now=lambda: clock[0], source_time_label=SourceTimeLabel.END,
            is_open_on=lambda _day: pytest.fail("permission worker queried calendar"),
        )
    profile = certified_tushare_market_index_profile(
        capabilities={code: (TushareMarketIndexCapabilityStatus.READY if code is INDEX
                             else TushareMarketIndexCapabilityStatus.DEFERRED)
                      for code in MarketIndexCode},
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    return TushareMarketIndexProvider(profile=profile, client=client, now=lambda: clock[0])


def invoke(provider, operation, guard):
    if operation in MINUTE_METHODS:
        return getattr(provider, MINUTE_METHODS[operation])(
            SYMBOL, CAPTURED.date(), physical_start=guard,
        )
    if operation == "daily":
        return provider.probe_daily_bars_permission(SYMBOL, ANCHOR, _physical_start=guard)
    if operation == "stk_limit":
        return provider.probe_daily_limits_permission(ANCHOR, _physical_start=guard)
    if operation == "index_daily":
        return provider.probe_official_daily_permission(INDEX, ANCHOR, _physical_start=guard)
    return provider.probe_realtime_minutes_permission(INDEX, CAPTURED.date(), guard)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("stage", ["certification", "resolution"])
@pytest.mark.parametrize("delay", [2, 16])
def test_all_proofs_resolve_and_certify_before_final_guard(operation, stage, delay):
    clock = [CAPTURED]
    trace = []
    def current():
        trace.append("certification")
        if stage == "certification":
            clock[0] += timedelta(seconds=delay)
        return True
    class DynamicSDK:
        def __getattr__(self, name):
            assert name == operation, "never probe an optional private protocol on a dynamic SDK"
            trace.append("resolution")
            if stage == "resolution":
                clock[0] += timedelta(seconds=delay)
            def endpoint(**kwargs):
                assert trace[-1] == "guard", "no authority IO or dynamic lookup after S"
                assert all(not key.startswith("_") for key in kwargs)
                trace.append("sdk")
                return response_for(operation)
            return endpoint
    provider = provider_for(operation, _CertifiedTushareClient(DynamicSDK(), current), clock)
    starts = []
    sentinel = RequestNotStartedError("clock advanced during preparation")
    def guard():
        trace.append("guard")
        starts.append(clock[0])
        if clock[0] > CAPTURED + timedelta(seconds=15):
            raise sentinel
        return clock[0]
    if delay > 15:
        with pytest.raises(RequestNotStartedError) as caught:
            invoke(provider, operation, guard)
        assert caught.value is sentinel
        assert trace == ["certification", "resolution", "guard"]
    else:
        evidence = invoke(provider, operation, guard)
        assert trace == ["certification", "resolution", "guard", "sdk"]
        if operation in MINUTE_METHODS:
            assert evidence.started_at == starts[0]
    assert starts == [CAPTURED + timedelta(seconds=delay)]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("stage", ["certification", "resolution", "guard", "sdk"])
def test_trusted_sentinel_keeps_identity_at_each_layer(operation, stage):
    sentinel = RequestNotStartedError("trusted local rejection")
    def current():
        if stage == "certification":
            raise sentinel
        return True
    class SDK:
        def __getattr__(self, name):
            assert name == operation
            if stage == "resolution":
                raise sentinel
            def call(**kwargs):
                if stage == "sdk":
                    raise sentinel
                pytest.fail("a rejected guard must not call SDK")
            return call
    def guard():
        if stage == "guard":
            raise sentinel
        return CAPTURED
    provider = provider_for(operation, _CertifiedTushareClient(SDK(), current), [CAPTURED])
    with pytest.raises(RequestNotStartedError) as caught:
        invoke(provider, operation, guard)
    assert caught.value is sentinel


@pytest.mark.parametrize("operation", OPERATIONS)
def test_false_certification_rejects_before_resolution_and_guard(operation):
    class SDK:
        def __getattr__(self, name):
            pytest.fail("certification rejected before endpoint resolution")
    provider = provider_for(operation, _CertifiedTushareClient(SDK(), lambda: False), [CAPTURED])
    with pytest.raises(RequestNotStartedError):
        invoke(provider, operation, lambda: pytest.fail("certification rejected before guard"))


@pytest.mark.parametrize("operation", MINUTE_METHODS)
@pytest.mark.parametrize("start_offset,duration", [(15, 15), (16, 0), (15, 15.000001)])
def test_minute_start_and_response_boundaries_use_resolved_s(operation, start_offset, duration):
    clock = [CAPTURED]
    calls = []
    def current():
        clock[0] = CAPTURED + timedelta(seconds=start_offset)
        return True
    def endpoint(**kwargs):
        calls.append(kwargs)
        clock[0] += timedelta(seconds=duration)
        return minute_frame()
    provider = provider_for(operation, _CertifiedTushareClient(
        SimpleNamespace(**{operation: endpoint}), current,
    ), clock)
    def guard():
        at = clock[0]
        if at > CAPTURED + timedelta(seconds=15):
            raise RequestNotStartedError("expired")
        return at
    if start_offset > 15:
        with pytest.raises(RequestNotStartedError):
            invoke(provider, operation, guard)
        assert not calls
    elif duration > 15:
        with pytest.raises(TushareProviderError) as caught:
            invoke(provider, operation, guard)
        assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    else:
        evidence = invoke(provider, operation, guard)
        assert evidence.started_at == CAPTURED + timedelta(seconds=15)
        assert evidence.received_at - evidence.started_at == timedelta(seconds=15)
        assert len(calls) == 1


@pytest.mark.parametrize("operation", MINUTE_METHODS)
@pytest.mark.parametrize("route", ["default", "direct"])
def test_installed_transport_with_real_certification_wrapper(monkeypatch, operation, route):
    from tushare.pro.client import DataApi

    original_getattr = DataApi.__getattr__
    resolved = []
    def lookup(client, name):
        assert name == operation, "installed dynamic SDK must not receive private protocol probes"
        resolved.append(name)
        call = original_getattr(client, name)
        def endpoint(**kwargs):
            assert set(kwargs) == {"fields", "ts_code", "freq"}
            return call(**kwargs)
        return endpoint
    monkeypatch.setattr(DataApi, "__getattr__", lookup)
    client, calls = _installed(monkeypatch, route)
    trace = []
    def current():
        trace.append("certification")
        return True
    def guard():
        assert trace == ["certification"]
        trace.append("guard")
        return CAPTURED
    provider = provider_for(operation, _CertifiedTushareClient(client, current), [CAPTURED])
    assert invoke(provider, operation, guard).completed_count == 1
    assert calls == [operation] and trace == ["certification", "guard"]
    assert resolved == [operation]


def test_concurrent_calls_keep_their_own_guard_and_s():
    gate = Barrier(2)
    worker = local()
    def current():
        gate.wait(timeout=3)
        return True
    def endpoint(**kwargs):
        assert worker.guarded
        return minute_frame()
    provider = TushareMarketDataProvider(
        _CertifiedTushareClient(SimpleNamespace(rt_min=endpoint), current),
        now=lambda: worker.at, source_time_label=SourceTimeLabel.END,
        is_open_on=lambda _day: pytest.fail("permission worker queried calendar"),
    )
    def attempt(offset):
        worker.at = CAPTURED + timedelta(seconds=offset)
        worker.guarded = False
        def guard():
            worker.guarded = True
            return worker.at
        return invoke(provider, "rt_min", guard).started_at
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert results == [CAPTURED + timedelta(seconds=offset) for offset in [1, 2]]


def test_nested_calls_do_not_replace_outer_hook_or_preparation():
    trace = []
    def endpoint(**kwargs):
        trace.append("sdk")
        return minute_frame()
    def current():
        trace.append("certification")
        return True
    provider = provider_for("rt_min", _CertifiedTushareClient(
        SimpleNamespace(rt_min=endpoint), current,
    ), [CAPTURED + timedelta(seconds=2)])
    def inner_guard():
        trace.append("inner")
        return CAPTURED + timedelta(seconds=1)
    def outer_guard():
        inner = invoke(provider, "rt_min", inner_guard)
        assert inner.started_at == CAPTURED + timedelta(seconds=1)
        trace.append("outer")
        return CAPTURED + timedelta(seconds=2)
    outer = invoke(provider, "rt_min", outer_guard)
    assert outer.started_at == CAPTURED + timedelta(seconds=2)
    assert trace == ["certification", "certification", "inner", "sdk", "outer", "sdk"]


@pytest.mark.parametrize("method", ["daily_bars", "historical_daily_bars"])
def test_ordinary_daily_calls_keep_wrapper_and_kwargs(method):
    trace = []
    calls = []
    def current():
        trace.append("certification")
        return True
    def endpoint(**kwargs):
        calls.append(kwargs)
        return response_for("daily")
    provider = provider_for("daily", _CertifiedTushareClient(
        SimpleNamespace(daily=endpoint), current,
    ), [CAPTURED])
    provider._is_open_on = lambda _day: True
    assert getattr(provider, method)(SYMBOL, ANCHOR, ANCHOR)[0].is_official
    assert trace == ["certification"]
    assert calls == [{
        "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
        "ts_code": SYMBOL, "start_date": "20260924", "end_date": "20260924",
    }]


def test_ordinary_wrapper_rejection_keeps_original_error():
    client = _CertifiedTushareClient(SimpleNamespace(), lambda: False)
    with pytest.raises(RuntimeError) as caught:
        client.daily(fields="ts_code")
    assert type(caught.value) is RuntimeError
    assert str(caught.value) == "provider certification is not current"


def test_nested_nominal_wrappers_finish_all_checks_before_guard():
    trace = []
    def current(label):
        trace.append(label)
        return True
    def endpoint(**kwargs):
        assert trace == ["outer", "inner", "guard"]
        return minute_frame()
    client = _CertifiedTushareClient(
        _CertifiedTushareClient(SimpleNamespace(rt_min=endpoint), lambda: current("inner")),
        lambda: current("outer"),
    )
    provider = provider_for("rt_min", client, [CAPTURED])
    def guard():
        trace.append("guard")
        return CAPTURED
    assert invoke(provider, "rt_min", guard).completed_count == 1


def test_noncallable_endpoint_is_local_preparation_error_before_guard():
    provider = provider_for("rt_min", _CertifiedTushareClient(
        SimpleNamespace(rt_min=None), lambda: True,
    ), [CAPTURED])
    with pytest.raises(TypeError, match="endpoint must be callable"):
        invoke(provider, "rt_min", lambda: pytest.fail("resolution precedes guard"))
