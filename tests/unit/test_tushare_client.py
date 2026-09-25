import asyncio
import json
import ssl
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import requests
import urllib3
from pydantic import ValidationError

from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareFailureKind,
    TushareHTTPStatusClass,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.market_data.tushare_client import (
    TushareClientConfigurationError,
    create_tushare_client,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    create_live_tushare_request_controller,
)

TOKEN_SENTINEL = "quick-sync-test-token-must-not-leak"


@pytest.mark.parametrize("status", (401, 403, 408, 429, 500))
@pytest.mark.parametrize("connect_ip", (None, "192.0.2.1"))
def test_non_2xx_http_status_keeps_permission_or_cooldown_through_official_client(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    connect_ip: str | None,
) -> None:
    """RED: the default SDK route must retain the same structured HTTP outcome."""

    called: list[str] = []

    def fake_post(url: str, **kwargs: object) -> requests.Response:
        called.append("default")
        assert url == "https://api.quicksync.cn/trade_cal"
        assert kwargs["json"]["api_name"] == "trade_cal"
        response = requests.Response()
        response.status_code = status
        response._content = TOKEN_SENTINEL.encode()
        return response

    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> urllib3.HTTPResponse:
            called.append("direct")
            return urllib3.HTTPResponse(body=TOKEN_SENTINEL.encode(), status=status)

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip=connect_ip))
    now = datetime(2026, 9, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    class Clock:
        def now(self) -> datetime:
            return now

        async def sleep_until(self, _deadline: datetime) -> None:
            return None

    async def scenario() -> RequestControlError:
        controller = create_live_tushare_request_controller(clock=Clock())
        provider = TushareMarketDataProvider(
            client, now=lambda: now, is_open_on=lambda _day: True,
        )
        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.TRADING_CALENDAR,
                    lambda: provider.trading_calendar_for_exchange(
                        "SSE", date(2026, 9, 8), date(2026, 9, 8),
                    ),
                    work_key="http-status:calendar",
                )
            expected = (
                RequestControlErrorCode.RATE_LIMITED
                if status == 429 else RequestControlErrorCode.BLOCKED_PERMISSION
                if status in (401, 403) else RequestControlErrorCode.TRANSIENT
            )
            if status == 429:
                assert (captured.value.code, controller.cooldown_until is not None) == (
                    expected, True,
                )
            elif status in (401, 403):
                assert (
                    captured.value.code,
                    controller.is_permission_blocked(TushareOperation.TRADING_CALENDAR),
                ) == (expected, True)
            else:
                assert (captured.value.code, controller.backoff_until("http-status:calendar")) == (
                    expected, now.replace(second=30),
                )
            return captured.value
        finally:
            await controller.aclose()

    error = asyncio.run(scenario())
    assert called == ["direct" if connect_ip else "default"]
    assert TOKEN_SENTINEL not in str(error)


def test_default_url_keeps_one_valid_2xx_dataframe_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> requests.Response:
        calls.append(url)
        assert set(kwargs) == {"json", "timeout"}
        assert kwargs["json"]["api_name"] == "trade_cal"
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "code": 0,
            "data": {
                "fields": ["exchange", "cal_date", "is_open", "pretrade_date"],
                "items": [["SSE", "20260908", 1, "20260907"]],
            },
        }).encode()
        return response

    def unexpected_direct(*_args: object, **_kwargs: object) -> None:
        pytest.fail("default URL must not use the direct-IP transport")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", unexpected_direct)
    client = create_tushare_client(_configuration())

    frame = client.trade_cal(
        fields="exchange,cal_date,is_open,pretrade_date",
        exchange="SSE", start_date="20260908", end_date="20260908",
    )

    assert frame.to_dict(orient="records") == [{
        "exchange": "SSE", "cal_date": "20260908", "is_open": 1,
        "pretrade_date": "20260907",
    }]
    assert calls == ["https://api.quicksync.cn/trade_cal"]
    assert TOKEN_SENTINEL not in repr(frame)


def test_default_url_accepts_one_valid_empty_2xx_dataframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "code": 0,
            "data": {"fields": ["cal_date"], "items": []},
        }).encode()
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    frame = create_tushare_client(_configuration()).trade_cal()

    assert frame.empty
    assert list(frame.columns) == ["cal_date"]
    assert calls == ["https://api.quicksync.cn/trade_cal"]


@pytest.mark.parametrize("close_fails", (False, True))
@pytest.mark.parametrize("outcome", ("valid", "malformed", "rate_limited"))
def test_default_url_closes_response_without_overriding_classification(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    close_fails: bool,
) -> None:
    calls: list[str] = []
    closed: list[bool] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = 429 if outcome == "rate_limited" else 200
        response._content = (
            b"not-json"
            if outcome == "malformed"
            else json.dumps({
                "code": 0,
                "data": {"fields": ["cal_date"], "items": [["20260908"]]},
            }).encode()
        )

        def close() -> None:
            closed.append(True)
            if close_fails:
                raise RuntimeError(f"close token={TOKEN_SENTINEL}")

        response.close = close
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    client = create_tushare_client(_configuration())
    if outcome == "valid":
        assert client.trade_cal().iloc[0]["cal_date"] == "20260908"
    else:
        expected = requests.HTTPError if outcome == "rate_limited" else TushareProviderError
        with pytest.raises(expected) as captured:
            client.trade_cal()
        assert TOKEN_SENTINEL not in repr(captured.value)
        assert captured.value.__context__ is None
        if outcome == "rate_limited":
            assert captured.value.response.status_code == 429
        else:
            assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert calls == ["https://api.quicksync.cn/trade_cal"]
    assert closed == [True]


def test_injected_data_api_factory_keeps_its_query_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedDataApi:
        def __init__(self, token: str, timeout: int) -> None:
            self.token = token
            self.timeout = timeout
            self.calls = 0

        def query(self, operation: str, fields: str = "") -> tuple[str, str]:
            self.calls += 1
            return operation, fields

    def unexpected_post(*_args: object, **_kwargs: object) -> None:
        pytest.fail("injected SDK query must remain in control")

    monkeypatch.setattr(requests, "post", unexpected_post)
    client = create_tushare_client(_configuration(), data_api_factory=InjectedDataApi)

    assert client.query("trade_cal", "cal_date") == ("trade_cal", "cal_date")
    assert client.calls == 1
    assert client.token == TOKEN_SENTINEL
    assert client.timeout == 20
    assert client._DataApi__http_url == "https://api.quicksync.cn"


@pytest.mark.parametrize(
    "payload",
    (
        f"<html>{TOKEN_SENTINEL}</html>".encode(),
        json.dumps({"code": 0, "data": {"fields": ["cal_date"], "items": [[TOKEN_SENTINEL]]}})
        .encode(),
    ),
)
@pytest.mark.parametrize("status", (401, 429))
def test_default_url_non_2xx_ignores_poison_body_and_exposes_status_only(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: bytes,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = status
        response._content = payload
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    client = create_tushare_client(_configuration())

    with pytest.raises(requests.HTTPError) as captured:
        client.trade_cal()

    assert calls == ["https://api.quicksync.cn/trade_cal"]
    assert captured.value.response.status_code == status
    assert captured.value.response.content is None
    assert captured.value.response.request is None
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in repr(captured.value)


def test_default_url_clients_keep_instance_endpoint_and_token_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tushare.pro.client import DataApi

    calls: list[tuple[str, str, int]] = []
    original_query = DataApi.query

    def fake_post(url: str, **kwargs: object) -> requests.Response:
        calls.append((url, kwargs["json"]["token"], kwargs["timeout"]))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "code": 0,
            "data": {"fields": ["cal_date"], "items": [["20260908"]]},
        }).encode()
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    first = create_tushare_client(_configuration())
    second_token = "second-offline-token"
    second = create_tushare_client(_configuration(
        api_url="https://second.example.test/dataapi", token=second_token,
        timeout_seconds=7,
    ))

    assert first.trade_cal().iloc[0]["cal_date"] == "20260908"
    assert second.trade_cal().iloc[0]["cal_date"] == "20260908"
    assert first.trade_cal().iloc[0]["cal_date"] == "20260908"
    assert calls == [
        ("https://api.quicksync.cn/trade_cal", TOKEN_SENTINEL, 20),
        ("https://second.example.test/dataapi/trade_cal", second_token, 7),
        ("https://api.quicksync.cn/trade_cal", TOKEN_SENTINEL, 20),
    ]
    assert DataApi.query is original_query


@pytest.mark.parametrize(
    "payload",
    (
        f"not-json {TOKEN_SENTINEL}".encode(),
        json.dumps({"code": 0, "data": {"fields": ["cal_date"]}}).encode(),
    ),
)
def test_default_url_2xx_malformed_response_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = payload
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    client = create_tushare_client(_configuration())

    with pytest.raises(TushareProviderError) as captured:
        client.trade_cal()

    assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in repr(captured.value)
    assert calls == ["https://api.quicksync.cn/trade_cal"]


def test_default_url_timeout_is_sanitized_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        raise requests.Timeout(f"provider timeout token={TOKEN_SENTINEL}")

    monkeypatch.setattr(requests, "post", fake_post)
    client = create_tushare_client(_configuration())

    with pytest.raises(requests.Timeout) as captured:
        client.trade_cal()

    assert calls == ["https://api.quicksync.cn/trade_cal"]
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in repr(captured.value)


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        (f"permission denied token={TOKEN_SENTINEL}", RequestControlErrorCode.BLOCKED_PERMISSION),
        (f"每分钟最多访问 token={TOKEN_SENTINEL}", RequestControlErrorCode.RATE_LIMITED),
    ),
)
def test_default_url_2xx_provider_error_is_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected: RequestControlErrorCode,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **_kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"code": -1, "msg": message}).encode()
        return response

    def unexpected_direct(*_args: object, **_kwargs: object) -> None:
        pytest.fail("default URL must not use the direct-IP transport")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", unexpected_direct)
    client = create_tushare_client(_configuration())
    now = datetime(2026, 9, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    class Clock:
        def now(self) -> datetime:
            return now

        async def sleep_until(self, _deadline: datetime) -> None:
            return None

    async def scenario() -> RequestControlError:
        controller = create_live_tushare_request_controller(clock=Clock())
        provider = TushareMarketDataProvider(
            client, now=lambda: now, is_open_on=lambda _day: True,
        )
        try:
            with pytest.raises(RequestControlError) as captured:
                await controller.execute(
                    TushareOperation.TRADING_CALENDAR,
                    lambda: provider.trading_calendar_for_exchange(
                        "SSE", date(2026, 9, 8), date(2026, 9, 8),
                    ),
                    work_key="provider-status:calendar",
                )
            assert captured.value.code is expected
            if expected is RequestControlErrorCode.BLOCKED_PERMISSION:
                assert controller.is_permission_blocked(TushareOperation.TRADING_CALENDAR)
            else:
                assert controller.cooldown_until is not None
            return captured.value
        finally:
            await controller.aclose()

    error = asyncio.run(scenario())
    assert calls == ["https://api.quicksync.cn/trade_cal"]
    assert TOKEN_SENTINEL not in str(error)
    assert TOKEN_SENTINEL not in repr(error)
    assert TOKEN_SENTINEL not in repr(error.__context__)


class StubDataApi:
    def __init__(self, token: str, timeout: int) -> None:
        self.received_token = token
        self.timeout = timeout


def _configuration(**overrides: object) -> TushareConfiguration:
    values: dict[str, object] = {
        "api_url": "https://api.quicksync.cn",
        "timeout_seconds": 20,
        "token": TOKEN_SENTINEL,
    }
    return TushareConfiguration.model_validate(values | overrides)


def test_client_factory_configures_one_official_sdk_instance_without_global_mutation() -> None:
    client = create_tushare_client(
        _configuration(),
        data_api_factory=StubDataApi,
    )

    assert isinstance(client, StubDataApi)
    assert client.received_token == TOKEN_SENTINEL
    assert client.timeout == 20
    assert client._DataApi__http_url == "https://api.quicksync.cn"  # type: ignore[attr-defined]


def test_client_factory_fails_closed_without_an_explicit_https_endpoint() -> None:
    called = False

    def factory(_token: str, _timeout: int) -> object:
        nonlocal called
        called = True
        return object()

    with pytest.raises(TushareClientConfigurationError, match="API URL"):
        create_tushare_client(
            TushareConfiguration(),
            data_api_factory=factory,
        )

    assert called is False


def test_client_factory_fails_closed_when_token_is_missing() -> None:
    with pytest.raises(TushareClientConfigurationError, match="not configured"):
        create_tushare_client(
            _configuration(token=None),
            data_api_factory=StubDataApi,
        )


def test_client_factory_rejects_control_characters_without_exposing_token() -> None:
    unsafe_token = f"{TOKEN_SENTINEL}\nsecond-line"

    with pytest.raises(TushareClientConfigurationError) as captured:
        create_tushare_client(
            _configuration(token=unsafe_token),
            data_api_factory=StubDataApi,
        )

    assert unsafe_token not in str(captured.value)
    assert unsafe_token not in repr(captured.value)


def test_client_factory_sanitizes_sdk_initialization_errors() -> None:
    def failing_factory(token: str, _timeout: int) -> object:
        raise RuntimeError(f"provider rejected token={token}")

    with pytest.raises(TushareClientConfigurationError) as captured:
        create_tushare_client(
            _configuration(),
            data_api_factory=failing_factory,
        )

    surfaces = (str(captured.value), repr(captured.value), repr(captured.value.__context__))
    assert all(TOKEN_SENTINEL not in surface for surface in surfaces)


@pytest.mark.parametrize(
    "connect_ip",
    [
        "api.example.com",
        "https://192.0.2.1",
        "192.0.2.1:443",
        "192.0.2.0/24",
        "fe80::1%3",
        TOKEN_SENTINEL,
    ],
)
def test_direct_connection_rejects_non_literal_addresses_without_leaking_token(
    connect_ip: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        _configuration(connect_ip=connect_ip)

    assert TOKEN_SENTINEL not in str(captured.value)
    assert TOKEN_SENTINEL not in repr(captured.value.errors())


def test_direct_connection_requires_the_original_https_endpoint() -> None:
    with pytest.raises(ValidationError):
        _configuration(connect_ip="192.0.2.1", api_url=None)


def test_direct_connection_is_opt_in_and_accepts_canonical_ipv6() -> None:
    assert _configuration().connect_ip is None
    assert _configuration(connect_ip="2001:0db8::1").connect_ip == "2001:db8::1"


def test_direct_connection_preserves_tls_identity_and_sends_once_without_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool_settings: list[dict[str, object]] = []
    sent: list[tuple[str, str, dict[str, object]]] = []
    closed: list[bool] = []

    class Pool:
        def __init__(self, **kwargs: object) -> None:
            pool_settings.append(kwargs)

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            closed.append(True)

        def request(self, method: str, url: str, **kwargs: object) -> urllib3.HTTPResponse:
            sent.append((method, url, kwargs))
            return urllib3.HTTPResponse(
                body=json.dumps(
                    {"code": 0, "data": {"fields": ["cal_date"], "items": [["20260908"]]}}
                ).encode(),
                status=200,
            )

    def unexpected_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("direct connection must not use process requests/proxy routing")

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:7897")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "invalid-environment-ca-bundle")
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    monkeypatch.setattr(requests, "post", unexpected_network)
    settings = _configuration(
        connect_ip="192.0.2.1", api_url="https://api.example.com:8443/dataapi"
    )
    client = create_tushare_client(settings)

    frame = client.trade_cal(fields="cal_date", exchange="SSE")

    assert frame.to_dict(orient="records") == [{"cal_date": "20260908"}]
    assert len(sent) == len(pool_settings) == 1
    assert closed == [True]
    pool = pool_settings[0]
    assert pool["host"] == "192.0.2.1"
    assert pool["port"] == 8443
    assert pool["server_hostname"] == pool["assert_hostname"] == "api.example.com"
    assert pool["cert_reqs"] == ssl.CERT_REQUIRED
    assert pool["ca_certs"] == requests.certs.where()
    assert pool["retries"] is False
    assert "_proxy" not in pool
    method, path, options = sent[0]
    assert method == "POST"
    assert path == "/dataapi/trade_cal"
    assert options["headers"]["Host"] == "api.example.com:8443"
    assert options["retries"] is False
    assert options["redirect"] is False
    payload = json.loads(options["body"])
    assert payload == {
        "api_name": "trade_cal",
        "token": TOKEN_SENTINEL,
        "fields": "cal_date",
        "params": {"exchange": "SSE", "ts_type_name": "https://api.example.com:8443/dataapi"},
    }


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_direct_connection_keeps_http_failures_structured_without_retry_or_secret(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    sent: list[bool] = []

    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **kwargs: object) -> urllib3.HTTPResponse:
            sent.append(True)
            assert kwargs["retries"] is False
            assert kwargs["redirect"] is False
            return urllib3.HTTPResponse(body=TOKEN_SENTINEL.encode(), status=status)

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip="192.0.2.1"))

    with pytest.raises(requests.HTTPError) as captured:
        client.trade_cal()

    assert sent == [True]
    assert captured.value.response.status_code == status
    assert captured.value.response.request is None
    assert captured.value.response.content is None
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in str(captured.value)
    classified = TushareMarketDataProvider._safe_provider_error("trade_cal", captured.value)
    assert classified.failure_kind is TushareFailureKind.HTTP_STATUS
    assert classified.http_status_class is {
        302: TushareHTTPStatusClass.REDIRECTION,
        401: TushareHTTPStatusClass.CLIENT_ERROR,
        403: TushareHTTPStatusClass.CLIENT_ERROR,
        429: TushareHTTPStatusClass.CLIENT_ERROR,
        500: TushareHTTPStatusClass.SERVER_ERROR,
    }[status]


@pytest.mark.parametrize(
    "message, expected_code",
    [
        (f"permission denied {TOKEN_SENTINEL}", "BLOCKED_PERMISSION"),
        (f"每分钟最多访问 {TOKEN_SENTINEL}", "RATE_LIMITED"),
        (f"connection failed {TOKEN_SENTINEL}", "TRANSIENT"),
        (f"unexpected {TOKEN_SENTINEL}", "ERROR"),
    ],
)
def test_direct_connection_preserves_safe_provider_failure_classification(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_code: str,
) -> None:
    from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider

    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> urllib3.HTTPResponse:
            return urllib3.HTTPResponse(
                body=json.dumps({"code": -1, "msg": message}).encode(), status=200
            )

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip="192.0.2.1"))

    with pytest.raises(Exception) as captured:
        client.trade_cal()

    classified = TushareMarketDataProvider._safe_provider_error("trade_cal", captured.value)
    assert classified.code.value == expected_code
    assert classified.failure_kind is TushareFailureKind.PROVIDER_STATUS
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in str(captured.value)


@pytest.mark.parametrize(
    ("body", "expected_kind"),
    [
        (b"not-json SECRET", TushareFailureKind.RESPONSE_DECODE),
        (json.dumps({"code": 0, "data": {}}).encode(), TushareFailureKind.RESPONSE_SCHEMA),
    ],
)
def test_direct_connection_classifies_invalid_responses_without_retaining_body(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    expected_kind: TushareFailureKind,
) -> None:
    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> urllib3.HTTPResponse:
            return urllib3.HTTPResponse(body=body, status=200)

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip="192.0.2.1"))

    with pytest.raises(Exception) as captured:
        client.trade_cal()

    classified = TushareMarketDataProvider._safe_provider_error("trade_cal", captured.value)
    assert classified.code is TushareErrorCode.INVALID_RESPONSE
    assert classified.failure_kind is expected_kind
    assert "SECRET" not in str(captured.value)
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "failure, expected",
    [
        (urllib3.exceptions.SSLError(TOKEN_SENTINEL), requests.ConnectionError),
        (urllib3.exceptions.ReadTimeoutError(None, None, TOKEN_SENTINEL), requests.Timeout),
    ],
)
def test_direct_connection_sanitizes_tls_and_timeout_failures_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: type[Exception],
) -> None:
    sent: list[bool] = []

    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **kwargs: object) -> urllib3.HTTPResponse:
            sent.append(True)
            assert kwargs["retries"] is False
            raise failure

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip="192.0.2.1"))

    with pytest.raises(expected) as captured:
        client.trade_cal()

    assert sent == [True]
    assert captured.value.__context__ is None
    assert TOKEN_SENTINEL not in str(captured.value)


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_kind"),
    [
        (
            urllib3.exceptions.ReadTimeoutError(None, None, TOKEN_SENTINEL),
            TushareErrorCode.TIMEOUT,
            TushareFailureKind.TRANSPORT_TIMEOUT,
        ),
        (
            urllib3.exceptions.SSLError(TOKEN_SENTINEL),
            TushareErrorCode.TRANSIENT,
            TushareFailureKind.TRANSPORT_TLS,
        ),
    ],
)
def test_direct_connection_retains_bounded_transport_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: TushareErrorCode,
    expected_kind: TushareFailureKind,
) -> None:
    class Pool:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Pool:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> urllib3.HTTPResponse:
            raise failure

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    client = create_tushare_client(_configuration(connect_ip="192.0.2.1"))

    with pytest.raises(Exception) as captured:
        client.trade_cal()

    classified = TushareMarketDataProvider._safe_provider_error("trade_cal", captured.value)
    assert classified.code is expected_code
    assert classified.failure_kind is expected_kind
    assert TOKEN_SENTINEL not in str(captured.value)
