from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
from tests.unit.test_ai_plan_extraction_v4 import _SOURCE, _valid_output

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    PlanExtractionStatus,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.prompts import (
    build_plan_extraction_prompt,
)
from trade_plan_monitor.ai.provider import PlanExtractionRequest, RawAIResponse
from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.config import load_application_config

_REQUEST_ID = UUID("4518b1e8-d450-4109-af50-fb86d868dd0e")


def test_new_configuration_default_reaches_deepseek_request_with_bounded_8192_tokens(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  base_url: https://api.deepseek.com
  model: deepseek-v4-pro
  api_key: offline-test-key
  max_retries: 0
""",
        encoding="utf-8",
    )
    settings = load_application_config(config_path).ai
    config = settings.to_provider_config()
    assert config is not None
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
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

    secrets = InMemorySecretStore()
    secrets.replace(config.secret_ref, SecretWrite(value="offline-test-key"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        client=client,
        secret_store=secrets,
        profile=settings.profile,
    )

    async def scenario() -> None:
        try:
            await provider.extract_plan(
                PlanExtractionRequest(
                    request_id=_REQUEST_ID,
                    config=config,
                    prompt=build_plan_extraction_prompt(_SOURCE),
                )
            )
        finally:
            await client.aclose()

    asyncio.run(scenario())

    assert settings.max_output_tokens == 8_192
    assert settings.prompt_version == "plan-extract-v8"
    assert config.max_output_tokens == 8_192
    assert config.prompt_version == "plan-extract-v8"
    assert captured == [
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": build_plan_extraction_prompt(_SOURCE)}],
            "temperature": 0.0,
            "stream": False,
            "max_tokens": 8_192,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
    ]


class _StaticV5Provider:
    def __init__(self, *, finish_reason: str, content: str | None = None) -> None:
        self.finish_reason = finish_reason
        self.content = content or json.dumps(
            _valid_output(), ensure_ascii=False, separators=(",", ":")
        )

    async def test_connection(self, config: object) -> None:
        raise AssertionError("not used")

    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse:
        return RawAIResponse(
            request_id=request.request_id,
            provider_id=request.config.provider_id,
            model=request.config.model,
            content=self.content,
            finish_reason=self.finish_reason,
            usage=None,
            attempts=1,
        )


def _v5_config(tmp_path: Path):
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  base_url: https://api.deepseek.com
  model: deepseek-v4-pro
  api_key: offline-test-key
  max_retries: 0
""",
        encoding="utf-8",
    )
    config = load_application_config(config_path).ai.to_provider_config()
    assert config is not None
    return config


def test_length_finish_reason_is_user_visible_and_never_returns_a_draft(tmp_path: Path) -> None:
    result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=_SOURCE,
            config=_v5_config(tmp_path),
            provider=_StaticV5Provider(finish_reason="length"),
        )
    )

    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert result.mapping is None
    assert result.validation_issues[0].code == "AI_OUTPUT_TRUNCATED"
    assert result.validation_issues[0].message == (
        "AI output was truncated before completion; no draft was created."
    )
    assert result.diagnostic is not None
    assert result.diagnostic.reason == "FINISH_REASON"
    assert result.diagnostic.finish_reason == "length"
