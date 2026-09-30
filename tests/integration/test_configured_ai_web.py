from __future__ import annotations

import asyncio
import json
from importlib import resources
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.ai import AIProviderSecretCommand, ConfiguredAIRuntimeView
from trade_plan_monitor.web.routers.plans import PlanExtractionCommand
from trade_plan_monitor.web.schemas import MutationContext, OperationKind


def test_configured_ai_web_lifecycle_uses_direct_application_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek Web
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: direct-web-key
  timeout_seconds: 10
  max_retries: 0
  max_input_chars: 50000
  max_output_tokens: 2048
  temperature: 0.0
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "wrong-process-environment-key")
    authorization_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-web-config",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 10,
                },
            },
        )

    async def scenario() -> None:
        lifecycle = ConfiguredAIWebLifecycle(
            config_path=config_path,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                trust_env=False,
            ),
        )
        await lifecycle.start()
        try:
            assert lifecycle.ai_operation_service is lifecycle
            assert lifecycle.plan_extraction_service is lifecycle

            page = await lifecycle.list_ai_providers(offset=0, limit=20)
            assert page.total == 1
            provider = page.items[0]
            assert provider.config.display_name == "DeepSeek Web"
            assert provider.config.model == "deepseek-v4-flash"
            assert str(provider.config.base_url) == "https://api.deepseek.com/"
            assert provider.revision == 0
            assert provider.secret_status.configured is True
            assert provider.secret_status.masked_value == "********"

            with pytest.raises(ApiError) as blocked_write:
                await lifecycle.replace_ai_provider_secret(
                    command=AIProviderSecretCommand(
                        provider_id=provider.config.provider_id,
                        secret={"value": "must-not-be-written-from-web"},
                        expected_revision=0,
                    ),
                    context=MutationContext(
                        idempotency_key="replace-secret-is-disabled",
                        request_id="a" * 32,
                    ),
                )
            assert blocked_write.value.code is ApiErrorCode.METHOD_NOT_ALLOWED

            receipt = await lifecycle.submit_plan_extraction(
                command=PlanExtractionCommand(
                    provider_id=provider.config.provider_id,
                    source_text="华亚智能：回踩 20.10 至 20.50 分批关注。",
                    expected_revision=0,
                ),
                context=MutationContext(
                    idempotency_key="extract-from-web-config",
                    request_id="b" * 32,
                ),
            )
            assert receipt.kind is OperationKind.PLAN_EXTRACTION
            assert receipt.status == "QUEUED"

            extraction = None
            for _attempt in range(100):
                extraction = await lifecycle.get_plan_extraction(
                    operation_id=str(receipt.operation_id)
                )
                if extraction is not None and extraction.status.value not in {
                    "QUEUED",
                    "RUNNING",
                }:
                    break
                await asyncio.sleep(0)

            assert extraction is not None
            assert extraction.status.value == "INVALID_OUTPUT"
            assert extraction.draft_plan_json is None
            assert authorization_headers == ["Bearer direct-web-key"]
        finally:
            await lifecycle.stop()

    asyncio.run(scenario())


def test_configured_ai_web_lifecycle_lists_and_executes_an_additional_model(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: direct-web-key
  max_retries: 0
  additional_models:
    - display_name: DeepSeek Pro
      model: deepseek-v4-pro
""",
        encoding="utf-8",
    )
    requested_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_models.append(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-web-pro",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async def scenario() -> None:
        lifecycle = ConfiguredAIWebLifecycle(
            config_path=config_path,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                trust_env=False,
            ),
        )
        start_result = await lifecycle.start()
        try:
            assert start_result["providerCount"] == 2
            page = await lifecycle.list_ai_providers(offset=0, limit=20)
            assert page.total == 2
            pro_provider = next(
                provider for provider in page.items if provider.config.model == "deepseek-v4-pro"
            )

            runtime = await lifecycle.get_configured_ai()
            assert runtime.alternative_providers is not None
            assert [provider.model for provider in runtime.alternative_providers] == [
                "deepseek-v4-pro"
            ]

            receipt = await lifecycle.submit_plan_extraction(
                command=PlanExtractionCommand(
                    provider_id=pro_provider.config.provider_id,
                    source_text="华亚智能：回踩 20.10 至 20.50 分批关注。",
                    expected_revision=0,
                ),
                context=MutationContext(
                    idempotency_key="extract-with-deepseek-pro",
                    request_id="c" * 32,
                ),
            )
            for _attempt in range(100):
                extraction = await lifecycle.get_plan_extraction(
                    operation_id=str(receipt.operation_id)
                )
                if extraction is not None and extraction.status.value not in {
                    "QUEUED",
                    "RUNNING",
                }:
                    break
                await asyncio.sleep(0)
            assert requested_models == ["deepseek-v4-pro"]
        finally:
            await lifecycle.stop()

    asyncio.run(scenario())


def test_configured_ai_runtime_rejects_duplicate_provider_identities() -> None:
    provider = {
        "provider_id": "00000000-0000-4000-8000-0000000000d5",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "configured": True,
        "enabled": True,
        "max_input_chars": 50_000,
        "max_output_tokens": 4_096,
        "revision": 0,
    }

    with pytest.raises(ValueError, match="identities must be unique"):
        ConfiguredAIRuntimeView(
            **provider,
            alternative_providers=(
                {
                    **provider,
                    "display_name": "DeepSeek Pro",
                    "model": "deepseek-v4-pro",
                },
            ),
        )


def test_fastapi_lifespan_exposes_directly_configured_ai_services(tmp_path: Path) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: direct-web-lifespan-key
  max_retries: 0
""",
        encoding="utf-8",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-web-lifespan",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider_clients: list[httpx.AsyncClient] = []

    def create_client() -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
        provider_clients.append(client)
        return client

    lifecycle = ConfiguredAIWebLifecycle(
        config_path=config_path,
        client_factory=create_client,
    )

    class Runtime:
        async def start(self) -> dict[str, object]:
            return {"status": "READY"}

        async def stop(self) -> None:
            return None

    app = create_app(
        runtime_factory=Runtime,
        ai_lifecycle_factory=lambda: lifecycle,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        runtime = client.get("/api/v1/ai-runtime")
        assert runtime.status_code == 200
        assert runtime.json() == {
            "baseUrl": "https://api.deepseek.com/",
            "configured": True,
            "displayName": "DeepSeek",
            "enabled": True,
            "maxInputChars": 50000,
            "maxOutputTokens": 8192,
            "model": "deepseek-v4-flash",
            "providerId": "00000000-0000-4000-8000-0000000000d5",
            "revision": 0,
        }
        assert all("secret" not in key.casefold() for key in runtime.json())
        provider_id = runtime.json()["providerId"]

        accepted = client.post(
            "/api/v1/plan-extractions",
            headers={"Idempotency-Key": "web-lifespan-extraction"},
            json={
                "providerId": provider_id,
                "sourceText": "华亚智能交易计划",
                "expectedRevision": 0,
            },
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operationId"]

        extraction = None
        for _attempt in range(100):
            extraction = client.get(f"/api/v1/plan-extractions/{operation_id}")
            if extraction.json()["status"] not in {"QUEUED", "RUNNING"}:
                break
        assert extraction is not None
        assert extraction.status_code == 200
        assert extraction.json()["status"] == "INVALID_OUTPUT"

    assert len(provider_clients) == 1
    assert provider_clients[0].is_closed


def test_production_app_defaults_to_direct_ai_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = tmp_path / "dist"
    (distribution / "assets").mkdir(parents=True)
    (distribution / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (distribution / "assets/app.js").write_text("export {};", encoding="utf-8")
    (distribution / "monitor-contract.json").write_text(
        '{"monitorContractVersion":1}', encoding="utf-8",
    )
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek Production
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: direct-production-key
""",
        encoding="utf-8",
    )

    class Runtime:
        async def start(self) -> dict[str, object]:
            return {"status": "DEGRADED"}

        async def stop(self) -> None:
            return None

    class BacktestLifecycle:
        read_service = object()
        operation_service = object()

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    with create_production_app(monitor_contract_version=1,
        config_path=config_path,
        database_path=tmp_path / "monitor.sqlite3",
        runtime_factory=Runtime,
        backtest_lifecycle_factory=BacktestLifecycle,
    ) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.get("/api/v1/ai-runtime")

    assert response.status_code == 200
    assert response.json()["displayName"] == "DeepSeek Production"
    assert response.json()["configured"] is True
    assert not any("secret" in key.casefold() for key in response.json())
