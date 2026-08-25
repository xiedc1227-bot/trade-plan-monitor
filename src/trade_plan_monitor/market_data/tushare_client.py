"""Secure construction of one instance-scoped official Tushare SDK client."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from trade_plan_monitor.config import TushareConfiguration

_MAX_TOKEN_LENGTH = 8_192


class TushareClientConfigurationError(RuntimeError):
    """Stable, secret-free failure raised before any provider operation."""


def create_tushare_client[ClientT](
    configuration: TushareConfiguration,
    *,
    environment: Mapping[str, str] | None = None,
    data_api_factory: Callable[[str, int], ClientT] | None = None,
) -> ClientT | object:
    """Build one official SDK client without changing its process-global endpoint."""

    if not isinstance(configuration, TushareConfiguration):
        raise TypeError("configuration must be a TushareConfiguration")
    if configuration.api_url is None:
        raise TushareClientConfigurationError("Tushare API URL is not configured")

    values = os.environ if environment is None else environment
    token = values.get(configuration.token_ref.environment_variable)
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
        client._DataApi__http_url = endpoint  # type: ignore[attr-defined]
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
