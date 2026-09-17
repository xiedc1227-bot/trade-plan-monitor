"""Offline tests for independently bounded AI transport and overall deadlines."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai import openai_compatible
from trade_plan_monitor.ai.models import AIProviderConfig, SecretReference
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderTimeoutKind,
)
from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite

_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000030")
_SECRET = "offline-r30-secret"


def _config(**changes: object) -> AIProviderConfig:
    values: dict[str, object] = {
        "provider_id": _PROVIDER_ID,
        "display_name": "Offline R30 provider",
        "base_url": "http://127.0.0.1:18080/v1",
        "model": "offline-model",
        "secret_ref": SecretReference(key="ai/provider/r30-offline"),
        "timeout_seconds": 65,
        "transport_timeout_seconds": 30,
        "read_timeout_seconds": 60,
        "max_retries": 0,
        "max_input_chars": 19_359,
        "max_output_tokens": 8_192,
        "temperature": 0,
        "prompt_version": "plan-extract-v6",
    }
    values.update(changes)
    return AIProviderConfig.model_validate(values)


def _secret_store(config: AIProviderConfig) -> InMemorySecretStore:
    store = InMemorySecretStore()
    store.replace(config.secret_ref, SecretWrite(value=_SECRET))
    return store


def test_r30_timeout_shape_keeps_connect_write_pool_at_30_and_read_at_60() -> None:
    observed_timeout: dict[str, float] = {}
    config = _config()

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeout.update(request.extensions["timeout"])
        return httpx.Response(
            200,
            json={
                "model": config.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(client=client, secret_store=_secret_store(config))
            result = await provider.test_connection(config)
            assert result.connected is True

    asyncio.run(scenario())

    assert observed_timeout == {
        "connect": 30.0,
        "read": 60.0,
        "write": 30.0,
        "pool": 30.0,
    }


def test_r30_scaled_overall_deadline_cancels_once_and_redacts_details(monkeypatch) -> None:
    config = _config()
    starts = 0
    cancelled = False
    real_timeout = asyncio.timeout

    monkeypatch.setattr(
        openai_compatible.asyncio,
        "timeout",
        lambda seconds: real_timeout(float(seconds) / 1_000),
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts, cancelled
        starts += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("unreachable")

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(client=client, secret_store=_secret_store(config))
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert starts == 1
    assert cancelled is True
    assert error.code is AIProviderErrorCode.TIMEOUT
    assert error.timeout_kind is AIProviderTimeoutKind.OVERALL_DEADLINE
    assert error.timeout_elapsed_ms is not None
    assert _SECRET not in f"{error!r} {error} {vars(error)!r}"


def test_existing_provider_timeout_defaults_remain_coupled_at_30_seconds() -> None:
    config = _config(
        timeout_seconds=30,
        transport_timeout_seconds=None,
        read_timeout_seconds=None,
    )

    assert config.timeout_seconds == 30
    assert config.transport_timeout_seconds is None
    assert config.read_timeout_seconds is None


@pytest.mark.parametrize(
    "changes",
    [
        {"transport_timeout_seconds": 66},
        {"read_timeout_seconds": 66},
    ],
)
def test_transport_phase_timeout_cannot_exceed_overall_deadline(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="transport timeouts must not exceed"):
        _config(**changes)
