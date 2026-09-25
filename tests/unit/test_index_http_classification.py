"""Fake SDK HTTP status must reach controller state through all index paths."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from requests import Response
from requests.exceptions import HTTPError

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
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

INDEX = MarketIndexCode.SSE_COMPOSITE
ANCHOR = date(2026, 9, 7)
START = datetime(2026, 9, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
TOKEN = "SECRET_FAKE_INDEX_TOKEN"


class Clock:
    def __init__(self) -> None:
        self.current = START

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.current = max(self.current, deadline)


class FailingSDK:
    def __init__(self, status: int) -> None:
        response = Response()
        response.status_code = status
        response._content = f"secret body {TOKEN}".encode()
        self.error = HTTPError(f"opaque {TOKEN}", response=response)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, endpoint: str):
        def request(**kwargs: object):
            self.calls.append((endpoint, kwargs))
            raise self.error

        return request


def _provider(sdk: object, clock: Clock) -> TushareMarketIndexProvider:
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
    return TushareMarketIndexProvider(profile=profile, client=sdk, now=clock.now)


def _controller(clock: Clock) -> TushareRequestController:
    return TushareRequestController(
        clock=clock, executor_workers=1, max_concurrency=1,
        min_interval=timedelta(0), jitter=timedelta(0), in_cycle_retries=0,
    )


def _normal_call(provider: TushareMarketIndexProvider, endpoint: str):
    if endpoint == "idx_mins":
        return lambda: provider._fetch_index_minutes(INDEX, START)
    if endpoint == "rt_idx_min_daily":
        return lambda: provider._fetch_realtime_index_minutes(INDEX)
    return lambda: provider._fetch_index_daily(INDEX, START)


@pytest.mark.parametrize(
    ("endpoint", "operation"),
    (
        ("idx_mins", TushareOperation.INDEX_HISTORICAL_MINUTES),
        ("rt_idx_min_daily", TushareOperation.INDEX_REALTIME_MINUTES),
        ("index_daily", TushareOperation.INDEX_DAILY),
    ),
)
@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (401, RequestControlErrorCode.BLOCKED_PERMISSION),
        (403, RequestControlErrorCode.BLOCKED_PERMISSION),
        (429, RequestControlErrorCode.RATE_LIMITED),
    ),
)
def test_normal_index_http_status_reaches_controller_scope(
    endpoint: str, operation: TushareOperation, status: int,
    expected: RequestControlErrorCode,
) -> None:
    async def scenario() -> None:
        clock = Clock()
        sdk = FailingSDK(status)
        provider = _provider(sdk, clock)
        control = _controller(clock)
        try:
            with pytest.raises(RequestControlError) as caught:
                await control.execute(
                    operation, _normal_call(provider, endpoint), work_key="normal-index",
                )
            assert caught.value.code is expected
            assert TOKEN not in str(caught.value)
            assert len(sdk.calls) == 1
            assert sdk.calls[0][0] == endpoint
            if status in (401, 403):
                assert control.is_permission_blocked(operation)
                assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
                assert control.cooldown_until is None
            else:
                assert not control.is_permission_blocked(operation)
                assert control.cooldown_until is not None
        finally:
            await control.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("endpoint", "operation"),
    (
        ("idx_mins", TushareOperation.INDEX_HISTORICAL_MINUTES),
        ("rt_idx_min_daily", TushareOperation.INDEX_REALTIME_MINUTES),
    ),
)
@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (401, RequestControlErrorCode.BLOCKED_PERMISSION),
        (403, RequestControlErrorCode.BLOCKED_PERMISSION),
        (429, RequestControlErrorCode.RATE_LIMITED),
    ),
)
def test_existing_index_recheck_http_failure_retains_its_scope(
    endpoint: str, operation: TushareOperation, status: int,
    expected: RequestControlErrorCode,
) -> None:
    async def scenario() -> None:
        clock = Clock()
        sdk = FailingSDK(status)
        provider = _provider(sdk, clock)
        control = _controller(clock)

        def initial_block() -> None:
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, endpoint)

        try:
            with pytest.raises(RequestControlError):
                await control.execute(operation, initial_block, work_key="index-recheck")
            assert sdk.calls == []
            clock.current += timedelta(seconds=300)
            def call() -> None:
                if endpoint == "idx_mins":
                    provider.probe_historical_minutes_permission(INDEX, ANCHOR)
                else:
                    provider.probe_realtime_minutes_permission(
                        INDEX, START.date(), clock.now,
                    )
            with pytest.raises(RequestControlError) as caught:
                await control.recheck_permission(operation, call, work_key="index-recheck")
            assert caught.value.code is expected
            assert control.is_permission_blocked(operation)
            assert not control.is_permission_blocked(TushareOperation.DAILY_BARS)
            assert len(sdk.calls) == 1
            assert sdk.calls[0][0] == endpoint
            if status == 429:
                assert control.cooldown_until is not None
            else:
                assert control.cooldown_until is None
        finally:
            await control.aclose()

    asyncio.run(scenario())


def test_index_http_error_drops_raw_context_before_controller() -> None:
    clock = Clock()
    provider = _provider(FailingSDK(403), clock)

    with pytest.raises(TushareProviderError) as caught:
        provider._fetch_index_daily(INDEX, START)

    assert caught.value.code is TushareErrorCode.BLOCKED_PERMISSION
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert TOKEN not in str(caught.value)


def test_index_deferred_start_passes_through_sdk_boundary() -> None:
    sentinel = RequestNotStartedError("deferred")

    class DeferredSDK:
        def idx_mins(self, **_kwargs):
            raise sentinel

    provider = _provider(DeferredSDK(), Clock())

    with pytest.raises(RequestNotStartedError) as caught:
        provider._fetch_index_minutes(INDEX, START)

    assert caught.value is sentinel
