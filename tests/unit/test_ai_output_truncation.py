from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import httpx
from tests.integration.test_source_treatment_review_api import (
    SOURCE as LITERAL_SOURCE,
)
from tests.integration.test_source_treatment_review_api import _literal_mapping
from tests.unit.test_ai_plan_extraction_v4 import _SOURCE, _partial_draft, _valid_output

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    PlanExtractionOutputV4,
    PlanExtractionStatus,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.prompts import (
    PLAN_EXTRACTION_PROMPT_V4,
    PLAN_EXTRACTION_PROMPT_V5,
    PLAN_EXTRACTION_PROMPT_VERSION,
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
    assert settings.prompt_version == PLAN_EXTRACTION_PROMPT_V5
    assert config.max_output_tokens == 8_192
    assert config.prompt_version == PLAN_EXTRACTION_PROMPT_V5
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


def test_plan_extract_v5_is_compact_and_keeps_v4_immutable() -> None:
    v4 = build_plan_extraction_prompt(
        "GOLDEN_PLAN_SOURCE", prompt_version=PLAN_EXTRACTION_PROMPT_V4
    )
    v5 = build_plan_extraction_prompt(
        "GOLDEN_PLAN_SOURCE", prompt_version=PLAN_EXTRACTION_PROMPT_V5
    )

    assert PLAN_EXTRACTION_PROMPT_VERSION == PLAN_EXTRACTION_PROMPT_V5
    assert "Return minified JSON" in v5
    assert "omit top-level assumptions or warnings only when that list is empty" in v5
    assert "Keep every discriminator field" in v5
    assert sha256(v4.encode()).hexdigest() == (
        "e91f6b32a69a60b1f35da3e5deee5acd17d326cecd0efcadd2aa99bdb36b4eb7"
    )
    assert v5 != v4


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


def test_v5_accepts_the_existing_closed_mapping_shape(tmp_path: Path) -> None:
    result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=_SOURCE,
            config=_v5_config(tmp_path),
            provider=_StaticV5Provider(finish_reason="stop"),
        )
    )

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.mapping is not None
    assert result.draft is not None
    assert result.draft.to_executable() is None
    assert all(issue.activation_blocking for issue in result.validation_issues)


def test_v5_compact_empty_list_omission_round_trips_without_semantic_loss(
    tmp_path: Path,
) -> None:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_partial_draft(), ensure_ascii=False))
    mapping = _literal_mapping(draft)
    output = PlanExtractionOutputV4(
        draft=draft,
        mapping_version=mapping.mapping_version,
        source_clauses=mapping.source_clauses,
        field_bindings=mapping.field_bindings,
        assumptions=(),
        warnings=(),
    )
    full_payload = output.model_dump(mode="json")
    full_json = json.dumps(full_payload, ensure_ascii=False, separators=(",", ":"))
    parsed = PlanExtractionOutputV4.model_validate_json(full_json)
    compact_payload = dict(full_payload)
    for field in ("assumptions", "warnings"):
        if not compact_payload[field]:
            del compact_payload[field]
    compact_json = json.dumps(
        compact_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=LITERAL_SOURCE,
            config=_v5_config(tmp_path),
            provider=_StaticV5Provider(finish_reason="stop", content=compact_json),
        )
    )

    assert len(compact_json.encode("utf-8")) < len(full_json.encode("utf-8"))
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft == parsed.draft
    assert result.mapping == parsed.to_mapping()
    assert len(result.mapping.source_clauses) == 15
    assert len(result.mapping.field_bindings) == 23


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
