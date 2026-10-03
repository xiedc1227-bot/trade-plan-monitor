from __future__ import annotations

import asyncio
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderType,
    ExtractionDiagnostic,
    PlanExtractionStatus,
    SecretReference,
)
from trade_plan_monitor.ai.prompts import (
    PLAN_EXTRACTION_PROMPT_V1,
    PLAN_EXTRACTION_PROMPT_V2,
    PLAN_EXTRACTION_PROMPT_V3,
    PLAN_EXTRACTION_PROMPT_V4,
)
from trade_plan_monitor.ai.provider import PlanExtractionRequest, RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses

_PROVIDER_ID = UUID("c738345b-8265-497c-9a8e-6da9154e233c")
_REQUEST_ID = UUID("51e37676-d62d-4bbc-873a-2b389f8d4611")
_SOURCE = "003043.SZ五分钟收盘在9.80至10.00元且放量时买入100股。"
_OLD_PROMPT_HASHES = {
    PLAN_EXTRACTION_PROMPT_V1: "420e06c0a8ab136a1b95c8218474fccd7f134d1bc5c9e1365e0c6a4a099e3d8d",
    PLAN_EXTRACTION_PROMPT_V2: "6d9ba53055700e508251fc62ce3a10c2c719b68874ac78aee9f27cbd40127daf",
    PLAN_EXTRACTION_PROMPT_V3: "df606ede45e58263b669f092cfaeb575becf1ea314076823b23f275a1768ae5d",
}


def _config() -> AIProviderConfig:
    return AIProviderConfig(
        provider_id=_PROVIDER_ID,
        display_name="Offline v4 provider",
        provider_type=AIProviderType.OPENAI_COMPATIBLE,
        base_url="https://ai.example.test/v1",
        model="offline-v4",
        secret_ref=SecretReference(key="ai/provider/offline-v4"),
        prompt_version=PLAN_EXTRACTION_PROMPT_V4,
        max_retries=0,
    )


def test_provider_default_selects_v5_without_changing_the_configured_model() -> None:
    values = _config().model_dump(mode="python")
    values.pop("prompt_version")

    config = AIProviderConfig.model_validate(values)

    assert config.prompt_version == "plan-extract-v9"
    assert config.model == "offline-v4"


def _partial_draft() -> dict[str, object]:
    return {
        "schema_version": 3,
        "execution_mode": "EXPLICIT_RULES",
        "execution_version": "explicit-rules-v1",
        "plan_id": "synthetic-v4",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "SYNTHETIC V4",
        "market": "SZSE",
        "metadata": {},
        "activation": None,
        "position": {
            "inventory_scope": "ALL_REGISTERED",
            "lot_size": 100,
            "max_qty": None,
        },
        "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
        "rules": [
            {
                "rule_id": "buy-100",
                "condition": {
                    "type": "ALL",
                    "conditions": [
                        {
                            "type": "COMPLETED_CLOSE_IN_RANGE",
                            "low_fen": 980,
                            "high_fen": 1000,
                            "include_low": None,
                            "include_high": None,
                        },
                        {
                            "type": "VOLUME_TO_MEAN_GTE",
                            "window_bars": None,
                            "minimum_ratio": None,
                            "history_scope": None,
                        },
                    ],
                },
                "action": {"type": "BUY", "quantity": 100},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": None,
                "safety_conditions": None,
            }
        ],
        "conflict_policy": None,
    }


def _valid_output() -> dict[str, object]:
    return {
        "draft": _partial_draft(),
        "mapping_version": "plan-mapping-v1",
        "source_clauses": [
            clause.model_dump(mode="json") for clause in server_source_clauses(_SOURCE)
        ],
        "field_bindings": [],
        "assumptions": [],
        "warnings": [],
    }


class _StaticProvider:
    def __init__(self, content: str, *, finish_reason: str = "stop") -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.request: PlanExtractionRequest | None = None

    async def test_connection(self, config: AIProviderConfig) -> None:
        raise AssertionError("not used")

    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse:
        self.request = request
        return RawAIResponse(
            request_id=request.request_id,
            provider_id=request.config.provider_id,
            model=request.config.model,
            content=self.content,
            finish_reason=self.finish_reason,
            usage=None,
            attempts=1,
        )


def _extract(payload: object, *, finish_reason: str = "stop"):
    return asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=_SOURCE,
            config=_config(),
            provider=_StaticProvider(
                json.dumps(payload, ensure_ascii=False),
                finish_reason=finish_reason,
            ),
        )
    )


def test_simulated_nonfinite_json_has_closed_diagnostic_reason() -> None:
    payload = _valid_output()
    payload["draft"]["rules"][0]["action"]["quantity"] = float("nan")
    result = _extract(payload)
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.diagnostic is not None
    assert result.diagnostic.reason == "JSON_NON_FINITE"
    assert result.diagnostic.stage == "json"


def test_diagnostic_model_rejects_untrusted_path_segments() -> None:
    with pytest.raises(ValidationError):
        ExtractionDiagnostic(
            stage="schema",
            reason="SCHEMA",
            path="draft.rules[0].SECRET-private-input",
        )


def test_v4_rejects_a_missing_server_clause_even_when_json_is_well_typed() -> None:
    output = _valid_output()
    output["source_clauses"] = []

    result = _extract(output)

    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None


def test_v4_rejects_unknown_keys_duplicate_keys_and_truncation() -> None:
    unknown = _valid_output() | {"clientIssues": []}
    duplicate = '{"draft":null,"draft":null}'

    unknown_result = _extract(unknown)
    duplicate_result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=_SOURCE,
            config=_config(),
            provider=_StaticProvider(duplicate),
        )
    )
    truncated = _extract(_valid_output(), finish_reason="length")

    assert unknown_result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert duplicate_result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert truncated.status is PlanExtractionStatus.INVALID_OUTPUT
