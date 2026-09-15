import json
import ssl

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
)
from trade_plan_monitor.market_data.tushare_client import (
    TushareClientConfigurationError,
    create_tushare_client,
)

TOKEN_SENTINEL = "quick-sync-test-token-must-not-leak"


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
