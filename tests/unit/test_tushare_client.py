import pytest

from trade_plan_monitor.config import TushareConfiguration
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
