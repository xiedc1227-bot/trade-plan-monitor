"""Secure construction of one instance-scoped official Tushare SDK client."""

from __future__ import annotations

import json
import re
import ssl
from collections.abc import Callable
from typing import Protocol, cast
from urllib.parse import urlsplit

import pandas as pd
import requests
import urllib3

from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareFailureKind,
    TushareMarketDataProvider,
    TushareProviderError,
)

_MAX_TOKEN_LENGTH = 8_192
_ENDPOINT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class TushareClientConfigurationError(RuntimeError):
    """Stable, secret-free failure raised before any provider operation."""


class _ConfigurableDataApi(Protocol):
    _DataApi__http_url: str
    query: Callable[..., pd.DataFrame]


class _DirectTushareQuery:
    """One SDK instance's explicit address route with the original TLS identity.

    urllib3 documents separate connection, SNI, certificate, and Host identities:
    https://urllib3.readthedocs.io/en/stable/advanced-usage.html#custom-sni-hostname
    Each call owns its pool so shutdown never leaves an unmanaged persistent socket.
    """

    def __init__(self, configuration: TushareConfiguration, token: str) -> None:
        self._endpoint = str(configuration.api_url).rstrip("/")
        self._address = configuration.connect_ip
        self._timeout = configuration.timeout_seconds
        self._token = token

    def __call__(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        if not isinstance(api_name, str) or _ENDPOINT_NAME.fullmatch(api_name) is None:
            raise ValueError("Tushare operation name is invalid")
        endpoint = urlsplit(self._endpoint)
        kwargs.setdefault("ts_type_name", self._endpoint)
        body = json.dumps(
            {"api_name": api_name, "token": self._token, "params": kwargs, "fields": fields}
        ).encode("utf-8")
        failure: Exception | None = None
        frame: pd.DataFrame | None = None
        try:
            with urllib3.HTTPSConnectionPool(
                host=self._address,
                port=endpoint.port or 443,
                server_hostname=endpoint.hostname,
                assert_hostname=endpoint.hostname,
                cert_reqs=ssl.CERT_REQUIRED,
                ca_certs=requests.certs.where(),
                timeout=urllib3.Timeout(total=self._timeout),
                retries=False,
            ) as pool:
                response = pool.request(
                    "POST",
                    f"{endpoint.path}/{api_name}",
                    body=body,
                    headers={"Host": endpoint.netloc, "Content-Type": "application/json"},
                    retries=False,
                    redirect=False,
                    assert_same_host=False,
                )
            if not 200 <= response.status < 300:
                safe_response = requests.Response()
                safe_response.status_code = response.status
                failure = requests.HTTPError("Tushare HTTP request failed", response=safe_response)
            else:
                try:
                    result = json.loads(response.data)
                except (TypeError, UnicodeError, ValueError):
                    failure = TushareProviderError(
                        TushareErrorCode.INVALID_RESPONSE,
                        api_name,
                        failure_kind=TushareFailureKind.RESPONSE_DECODE,
                    )
                else:
                    try:
                        provider_code = result["code"]
                    except (KeyError, TypeError):
                        failure = TushareProviderError(
                            TushareErrorCode.INVALID_RESPONSE,
                            api_name,
                            failure_kind=TushareFailureKind.RESPONSE_SCHEMA,
                        )
                    else:
                        if provider_code != 0:
                            failure = _safe_application_failure(api_name, result.get("msg", ""))
                        else:
                            try:
                                data = result["data"]
                                frame = pd.DataFrame(data["items"], columns=data["fields"])
                            except (KeyError, TypeError, ValueError):
                                failure = TushareProviderError(
                                    TushareErrorCode.INVALID_RESPONSE,
                                    api_name,
                                    failure_kind=TushareFailureKind.RESPONSE_SCHEMA,
                                )
        except urllib3.exceptions.TimeoutError:
            failure = requests.Timeout("Tushare request timed out")
            failure._tushare_failure_kind = TushareFailureKind.TRANSPORT_TIMEOUT
        except urllib3.exceptions.SSLError:
            failure = requests.ConnectionError("Tushare TLS connection failed")
            failure._tushare_failure_kind = TushareFailureKind.TRANSPORT_TLS
        except urllib3.exceptions.HTTPError:
            failure = requests.ConnectionError("Tushare connection failed")
            failure._tushare_failure_kind = TushareFailureKind.TRANSPORT_CONNECTION
        except Exception:
            failure = TushareProviderError(
                TushareErrorCode.INVALID_RESPONSE,
                api_name,
                failure_kind=TushareFailureKind.RESPONSE_SCHEMA,
            )
        if failure is not None:
            # Raise outside the handler: raw provider errors/bodies cannot become __context__.
            raise failure
        if frame is None:
            raise RuntimeError("Tushare response is invalid")
        return frame


def _safe_application_failure(operation: str, message: object) -> Exception:
    classified = TushareMarketDataProvider._safe_provider_error(
        operation, RuntimeError(message if isinstance(message, str) else "")
    )
    return TushareProviderError(
        classified.code,
        operation,
        failure_kind=TushareFailureKind.PROVIDER_STATUS,
    )


def create_tushare_client[ClientT](
    configuration: TushareConfiguration,
    *,
    data_api_factory: Callable[[str, int], ClientT] | None = None,
) -> ClientT | object:
    """Build one official SDK client without changing its process-global endpoint."""

    if not isinstance(configuration, TushareConfiguration):
        raise TypeError("configuration must be a TushareConfiguration")
    if configuration.api_url is None:
        raise TushareClientConfigurationError("Tushare API URL is not configured")

    token = configuration.token
    if token is None or not token.strip():
        raise TushareClientConfigurationError("Tushare token is not configured")
    if len(token) > _MAX_TOKEN_LENGTH or any(
        not 0x21 <= ord(character) <= 0x7E for character in token
    ):
        raise TushareClientConfigurationError("Tushare token is invalid")

    if data_api_factory is None:
        from tushare.pro.client import DataApi

        factory: Callable[[str, int], object] = DataApi
    else:
        factory = data_api_factory

    endpoint = str(configuration.api_url).rstrip("/")
    client: object | ClientT | None = None
    initialization_failed = False
    try:
        client = factory(token, configuration.timeout_seconds)
        configured_client = cast(_ConfigurableDataApi, client)
        configured_client._DataApi__http_url = endpoint
        if configuration.connect_ip is not None:
            configured_client.query = _DirectTushareQuery(configuration, token)
    except Exception:
        initialization_failed = True
    finally:
        token = None
    if initialization_failed or client is None:
        raise TushareClientConfigurationError("Tushare client initialization failed")
    return client


__all__ = [
    "TushareClientConfigurationError",
    "create_tushare_client",
]
