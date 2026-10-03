"""Offline regression coverage for the R25 AI timeout diagnostic gap."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import AIProviderConfig, ExtractionDiagnostic, SecretReference
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderTimeoutKind,
)
from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.web.ai_diagnostics import append_extraction_diagnostic

_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000026")
_REQUEST_ID = UUID("00000000-0000-4000-8000-000000000126")
_SECRET = "offline-r26-secret"


def _config(*, timeout_seconds: int = 5) -> AIProviderConfig:
    return AIProviderConfig(
        provider_id=_PROVIDER_ID,
        display_name="Offline R26 provider",
        base_url="http://127.0.0.1:18080/v1",
        model="offline-model",
        secret_ref=SecretReference(key="ai/provider/r26-offline"),
        timeout_seconds=timeout_seconds,
        max_retries=0,
        max_input_chars=75_000,
        max_output_tokens=128,
        temperature=0,
        prompt_version="plan-extract-v9",
    )


def _secret_store(config: AIProviderConfig) -> InMemorySecretStore:
    store = InMemorySecretStore()
    store.replace(config.secret_ref, SecretWrite(value=_SECRET))
    return store


@pytest.mark.parametrize(
    ("exception_type", "expected_kind"),
    [
        (httpx.ConnectTimeout, AIProviderTimeoutKind.CONNECT),
        (httpx.ReadTimeout, AIProviderTimeoutKind.READ),
        (httpx.WriteTimeout, AIProviderTimeoutKind.WRITE),
        (httpx.PoolTimeout, AIProviderTimeoutKind.POOL),
    ],
)
def test_httpx_timeout_subtype_is_preserved_without_exception_text(
    exception_type: type[httpx.TimeoutException],
    expected_kind: AIProviderTimeoutKind,
) -> None:
    config = _config()

    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("SECRET-provider-timeout-detail", request=request)

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.TIMEOUT
    assert error.timeout_kind is expected_kind
    assert error.timeout_elapsed_ms is not None
    assert 0 <= error.timeout_elapsed_ms <= config.timeout_seconds * 1_000
    assert "SECRET" not in f"{error!r} {error} {vars(error)!r}"


def test_local_deadline_is_distinct_from_httpx_timeout_subtypes() -> None:
    config = _config(timeout_seconds=1)

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await asyncio.wait_for(provider.test_connection(config), timeout=2.0)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.TIMEOUT
    assert error.timeout_kind is AIProviderTimeoutKind.OVERALL_DEADLINE
    assert error.timeout_elapsed_ms is not None
    assert 900 <= error.timeout_elapsed_ms <= 1_500


def test_timeout_diagnostic_persists_only_closed_kind_and_elapsed_ms(tmp_path: Path) -> None:
    config = _config()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SECRET-provider-timeout-detail", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            return await extract_plan(
                request_id=_REQUEST_ID,
                source_text="离线超时诊断测试",
                config=config,
                provider=provider,
            )

    result = asyncio.run(scenario())
    assert result.diagnostic is not None
    assert result.diagnostic.timeout_kind == "READ"
    assert result.diagnostic.timeout_elapsed_ms is not None

    sidecar = tmp_path / "monitor.ai-extraction-diagnostics.jsonl"
    append_extraction_diagnostic(
        sidecar,
        result=result,
        configured_model=config.model,
        completed_at=datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    record = json.loads(sidecar.read_text("utf-8"))

    assert record["version"] == 3
    assert record["timeoutKind"] == "READ"
    assert record["timeoutElapsedMs"] == result.diagnostic.timeout_elapsed_ms
    assert record["transientKind"] is None
    assert "SECRET" not in sidecar.read_text("utf-8")


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_error_code": "TRANSIENT", "timeout_kind": "READ", "timeout_elapsed_ms": 1},
        {"provider_error_code": "TIMEOUT", "timeout_kind": "READ"},
        {"provider_error_code": "TIMEOUT", "timeout_elapsed_ms": 1},
    ],
)
def test_timeout_diagnostic_metadata_is_consistent(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="timeout metadata"):
        ExtractionDiagnostic(
            stage="provider",
            reason="PROVIDER_ERROR",
            **changes,
        )


def test_transient_diagnostic_metadata_is_consistent() -> None:
    with pytest.raises(ValidationError, match="transient_kind"):
        ExtractionDiagnostic(
            stage="provider",
            reason="PROVIDER_ERROR",
            provider_error_code="AUTHENTICATION",
            transient_kind="UNKNOWN",
        )


def test_legacy_transient_diagnostic_defaults_to_unknown_category() -> None:
    diagnostic = ExtractionDiagnostic(
        stage="provider",
        reason="PROVIDER_ERROR",
        provider_error_code="TRANSIENT",
    )

    assert diagnostic.transient_kind == "UNKNOWN"
