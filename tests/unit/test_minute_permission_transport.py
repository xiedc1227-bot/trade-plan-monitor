"""Offline full-chain transport boundaries for strict minute permission probes."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests
import urllib3

from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareFailureKind,
    TushareHTTPStatusClass,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.runtime.request_control import RequestNotStartedError

SECRET = "minute-transport-token-and-raw-payload-must-not-leak"
SYMBOL = "600000.SH"
DAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
OPERATIONS = ("rt_min_daily", "rt_min")
METHODS = {
    "rt_min_daily": "probe_current_day_minutes_permission",
    "rt_min": "probe_realtime_minutes_permission",
}
FIELDS = ["ts_code", "time", "open", "close", "high", "low", "vol", "amount"]
ROW = [SYMBOL, "2026-09-25 09:31:00", "10", "10", "11", "9", "100", "1000"]


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("minute permission transport tests must not contact a real service")

    monkeypatch.setattr(requests, "post", unexpected)
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", unexpected)


def _provider(client: object, *, received_at: datetime = NOW) -> TushareMarketDataProvider:
    def no_calendar(_day: date) -> bool:
        pytest.fail("pure provider permission proof must not access a calendar")

    return TushareMarketDataProvider(
        client, now=lambda: received_at, is_open_on=no_calendar,
        source_time_label=SourceTimeLabel.END,
    )


def _invoke(provider: TushareMarketDataProvider, operation: str, *, guard=None):
    method = getattr(provider, METHODS[operation])
    return method(SYMBOL, DAY, physical_start=guard or (lambda: NOW))


def _safe(error: TushareProviderError, operation: str) -> None:
    assert str(error) == f"Tushare {operation} failed ({error.code.value})"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert SECRET not in repr(error)
    assert SECRET not in repr(vars(error))
    assert SECRET not in repr(error.args)


class _FakeSDK:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def __getattr__(self, operation: str):
        assert operation in OPERATIONS

        def call(**_kwargs: object):
            self.calls.append(operation)
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            return self.outcome

        return call


def _installed(
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    *,
    error: Exception | None = None,
    status: int = 200,
    body: bytes | None = None,
    timeout: int = 30,
) -> tuple[object, list[str]]:
    calls: list[str] = []
    payload = body if body is not None else json.dumps({
        "code": 0, "data": {"fields": FIELDS, "items": [ROW]},
    }).encode()

    def outcome(operation: str) -> None:
        calls.append(operation)
        if error is not None:
            raise error

    def fake_post(url: str, **kwargs: object) -> requests.Response:
        operation = kwargs["json"]["api_name"]
        assert url == f"https://minute-proof.example/{operation}"
        assert kwargs["timeout"] == timeout
        outcome(operation)
        response = requests.Response()
        response.status_code = status
        response._content = payload
        return response

    class Pool:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["retries"] is False
            assert kwargs["server_hostname"] == "minute-proof.example"
            assert kwargs["timeout"].total == timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, method: str, path: str, **kwargs: object):
            assert method == "POST"
            assert kwargs["retries"] is False
            assert kwargs["redirect"] is False
            operation = json.loads(kwargs["body"])["api_name"]
            assert path == f"/{operation}"
            outcome(operation)
            return urllib3.HTTPResponse(body=payload, status=status)

    if route == "default":
        monkeypatch.setattr(requests, "post", fake_post)
    else:
        assert route == "direct"
        monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    configuration = TushareConfiguration.model_validate({
        "api_url": "https://minute-proof.example",
        "token": SECRET,
        "timeout_seconds": timeout,
        "connect_ip": "192.0.2.1" if route == "direct" else None,
    })
    return create_tushare_client(configuration), calls


class _ConnectionHTTPError(requests.ConnectionError, requests.HTTPError):
    """Structured status must win even when ConnectionError precedes HTTPError."""


def _http_error(status: int, *, connection_first: bool = False) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response._content = SECRET.encode()
    response.url = f"https://minute-proof.example/{SECRET}"
    kind = _ConnectionHTTPError if connection_first else requests.HTTPError
    return kind(SECRET, response=response)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("fake", "default", "direct"))
@pytest.mark.parametrize("boundary", ("client", "fetch", "permission"))
def test_original_request_not_started_survives_all_layers(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str, boundary: str,
) -> None:
    sentinel = RequestNotStartedError("provider request revoked before physical I/O")
    if route == "fake":
        client = _FakeSDK(sentinel)
        calls = client.calls
    else:
        client, calls = _installed(monkeypatch, route, error=sentinel)
    provider = _provider(client)

    with pytest.raises(RequestNotStartedError) as captured:
        if boundary == "client":
            getattr(client, operation)(fields=",".join(FIELDS), ts_code=SYMBOL, freq="1MIN")
        elif boundary == "fetch":
            provider._fetch_frame(operation, fields=",".join(FIELDS), ts_code=SYMBOL, freq="1MIN")
        else:
            _invoke(provider, operation)

    assert captured.value is sentinel
    assert str(captured.value) == "provider request revoked before physical I/O"
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_physical_start_revocation_makes_zero_sdk_calls(operation: str) -> None:
    client = _FakeSDK(pd.DataFrame([ROW], columns=FIELDS))
    sentinel = RequestNotStartedError("provider request revoked before physical I/O")

    def guard() -> datetime:
        raise sentinel

    with pytest.raises(RequestNotStartedError) as captured:
        _invoke(_provider(client), operation, guard=guard)
    assert captured.value is sentinel
    assert client.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("fake", "default", "direct"))
@pytest.mark.parametrize("status", (401, 403, 429))
@pytest.mark.parametrize("connection_first", (False, True))
def test_raised_structured_http_status_precedes_connection_error(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str,
    status: int, connection_first: bool,
) -> None:
    raw = _http_error(status, connection_first=connection_first)
    if route == "fake":
        client = _FakeSDK(raw)
        calls = client.calls
    else:
        client, calls = _installed(monkeypatch, route, error=raw)

    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)
    error = captured.value
    assert error.code is (
        TushareErrorCode.RATE_LIMITED if status == 429 else TushareErrorCode.BLOCKED_PERMISSION
    )
    assert error.failure_kind is TushareFailureKind.HTTP_STATUS
    assert error.http_status_class is TushareHTTPStatusClass.CLIENT_ERROR
    _safe(error, operation)
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("default", "direct"))
@pytest.mark.parametrize("status", (401, 403, 429))
def test_returned_http_status_remains_structured_and_sanitized(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str, status: int,
) -> None:
    client, calls = _installed(monkeypatch, route, status=status, body=SECRET.encode())
    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)
    error = captured.value
    assert error.code is (
        TushareErrorCode.RATE_LIMITED if status == 429 else TushareErrorCode.BLOCKED_PERMISSION
    )
    assert error.failure_kind is TushareFailureKind.HTTP_STATUS
    _safe(error, operation)
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("fake", "default", "direct"))
@pytest.mark.parametrize("failure", ("timeout", "tls", "connection"))
def test_transport_failure_keeps_typed_classification_without_payload(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str, failure: str,
) -> None:
    exception_types = (
        {"timeout": urllib3.exceptions.TimeoutError, "tls": urllib3.exceptions.SSLError,
         "connection": urllib3.exceptions.HTTPError}
        if route == "direct" else
        {"timeout": requests.Timeout, "tls": requests.exceptions.SSLError,
         "connection": requests.ConnectionError}
    )
    raw = exception_types[failure](SECRET)
    if route == "fake":
        client = _FakeSDK(raw)
        calls = client.calls
    else:
        client, calls = _installed(monkeypatch, route, error=raw)
    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)
    error = captured.value
    assert error.code is (
        TushareErrorCode.TIMEOUT if failure == "timeout" else TushareErrorCode.TRANSIENT
    )
    assert error.failure_kind is {
        "timeout": TushareFailureKind.TRANSPORT_TIMEOUT,
        "tls": TushareFailureKind.TRANSPORT_TLS,
        "connection": TushareFailureKind.TRANSPORT_CONNECTION,
    }[failure]
    _safe(error, operation)
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("default", "direct"))
@pytest.mark.parametrize("failure", ("decode", "schema", "permission", "rate_limit", "unknown"))
def test_installed_wrapper_payload_failure_is_safe_and_single_attempt(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str, failure: str,
) -> None:
    bodies = {
        "decode": SECRET.encode(),
        "schema": json.dumps({"code": 0, "data": {"secret": SECRET}}).encode(),
        "permission": json.dumps({"code": 1, "msg": f"permission denied {SECRET}"}).encode(),
        "rate_limit": json.dumps({"code": 1, "msg": f"rate limit {SECRET}"}).encode(),
        "unknown": json.dumps({"code": 1, "msg": SECRET}).encode(),
    }
    client, calls = _installed(monkeypatch, route, body=bodies[failure])
    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)
    error = captured.value
    assert error.code is {
        "decode": TushareErrorCode.INVALID_RESPONSE,
        "schema": TushareErrorCode.INVALID_RESPONSE,
        "permission": TushareErrorCode.BLOCKED_PERMISSION,
        "rate_limit": TushareErrorCode.RATE_LIMITED,
        "unknown": TushareErrorCode.ERROR,
    }[failure]
    assert error.failure_kind is {
        "decode": TushareFailureKind.RESPONSE_DECODE,
        "schema": TushareFailureKind.RESPONSE_SCHEMA,
    }.get(failure, TushareFailureKind.PROVIDER_STATUS)
    _safe(error, operation)
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("failure", ("permission", "rate_limit", "unknown", "nonframe"))
def test_fake_sdk_provider_or_shape_failure_is_sanitized(operation: str, failure: str) -> None:
    outcomes = {
        "permission": RuntimeError(f"permission denied {SECRET}"),
        "rate_limit": RuntimeError(f"rate limit {SECRET}"),
        "unknown": RuntimeError(SECRET),
        "nonframe": {"secret": SECRET},
    }
    client = _FakeSDK(outcomes[failure])
    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)
    error = captured.value
    assert error.code is {
        "permission": TushareErrorCode.BLOCKED_PERMISSION,
        "rate_limit": TushareErrorCode.RATE_LIMITED,
        "unknown": TushareErrorCode.ERROR,
        "nonframe": TushareErrorCode.INVALID_RESPONSE,
    }[failure]
    _safe(error, operation)
    assert client.calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("default", "direct"))
def test_installed_wrapper_success_reaches_strict_parser_once(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str,
) -> None:
    client, calls = _installed(monkeypatch, route)
    evidence = _invoke(_provider(client), operation)
    assert evidence.operation == operation
    assert evidence.completed_count == 1
    assert evidence.opening_count == evidence.incomplete_count == 0
    assert evidence.source_dates == (DAY,)
    assert calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_existing_typed_sdk_error_is_rebuilt_without_raw_exception_state(operation: str) -> None:
    raw = TushareProviderError(
        TushareErrorCode.BLOCKED_PERMISSION,
        SECRET,
        failure_kind=TushareFailureKind.HTTP_STATUS,
        http_status_class=TushareHTTPStatusClass.CLIENT_ERROR,
    )
    raw.__cause__ = RuntimeError(f"cause {SECRET}")
    raw.__context__ = ValueError(f"context {SECRET}")
    raw.raw_payload = {"token": SECRET}
    raw.add_note(f"raw SDK note {SECRET}")
    client = _FakeSDK(raw)

    with pytest.raises(TushareProviderError) as captured:
        _invoke(_provider(client), operation)

    error = captured.value
    assert error is not raw
    assert type(error) is TushareProviderError
    assert error.code is TushareErrorCode.BLOCKED_PERMISSION
    assert error.operation == operation
    assert error.failure_kind is TushareFailureKind.HTTP_STATUS
    assert error.http_status_class is TushareHTTPStatusClass.CLIENT_ERROR
    assert set(vars(error)) == {"code", "operation", "failure_kind", "http_status_class"}
    _safe(error, operation)
    assert client.calls == [operation]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("route", ("default", "direct"))
@pytest.mark.parametrize("timeout", (30, 120))
@pytest.mark.parametrize("overrun", (False, True))
def test_evidence_interval_is_independent_of_installed_transport_timeout(
    monkeypatch: pytest.MonkeyPatch, operation: str, route: str, timeout: int, overrun: bool,
) -> None:
    """SDK has returned normally: the fixed evidence window accepts or rejects its result."""
    client, calls = _installed(monkeypatch, route, timeout=timeout)
    received_at = NOW + timedelta(seconds=15, microseconds=int(overrun))
    provider = _provider(client, received_at=received_at)

    if overrun:
        with pytest.raises(TushareProviderError) as captured:
            _invoke(provider, operation)
        assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
        _safe(captured.value, operation)
    else:
        evidence = _invoke(provider, operation)
        assert evidence.started_at == NOW
        assert evidence.received_at == received_at
        assert evidence.completed_count == 1
        assert evidence.source_dates == (DAY,)

    assert calls == [operation]
