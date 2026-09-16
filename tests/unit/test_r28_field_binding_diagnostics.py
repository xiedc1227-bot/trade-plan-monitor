"""Offline regression coverage for safe field-binding schema diagnostics."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_core import PydanticCustomError
from tests.unit.test_ai_plan_extraction_v4 import (
    _REQUEST_ID,
    _SOURCE,
    _config,
    _extract,
    _StaticProvider,
    _valid_output,
)

from trade_plan_monitor.ai.extraction import _safe_schema_error_type, extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.prompts import (
    PLAN_EXTRACTION_PROMPT_VERSION,
    build_plan_extraction_prompt,
)
from trade_plan_monitor.config import AIConfiguration
from trade_plan_monitor.web.ai_diagnostics import append_extraction_diagnostic

_SAFE_CASES = (
    (
        "field_binding_clause_ids_not_unique",
        {
            "path": "symbol",
            "value": "003043.SZ",
            "unit": "NONE",
            "origin": "SOURCE",
            "binding_kind": "VALUE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": None,
        },
        "duplicate",
    ),
    (
        "field_binding_source_reference_invalid",
        {
            "path": "symbol",
            "value": "003043.SZ",
            "unit": "NONE",
            "origin": "SOURCE",
            "binding_kind": "VALUE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": None,
        },
        "source",
    ),
    (
        "field_binding_user_supplement_reference_invalid",
        {
            "path": "symbol",
            "value": "003043.SZ",
            "unit": "NONE",
            "origin": "USER_SUPPLEMENT",
            "binding_kind": "VALUE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": None,
        },
        "user_supplement",
    ),
    (
        "field_binding_contract_reference_invalid",
        {
            "path": "schema_version",
            "value": 3,
            "unit": "NONE",
            "origin": "CONTRACT",
            "binding_kind": "VALUE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": None,
        },
        "contract_reference",
    ),
    (
        "field_binding_contract_path_forbidden",
        {
            "path": "metadata",
            "value": None,
            "unit": "NONE",
            "origin": "CONTRACT",
            "binding_kind": "VALUE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": "schema-literal-v1",
        },
        "contract_path",
    ),
    (
        "field_binding_structure_value_invalid",
        {
            "path": "rules[0].condition",
            "value": "SECRET-structure-value",
            "unit": "NONE",
            "origin": "SOURCE",
            "binding_kind": "STRUCTURE",
            "clause_ids": (),
            "supplement_id": None,
            "contract_id": None,
        },
        "structure",
    ),
)


def _invalid_output(case: str, binding: dict[str, object]) -> dict[str, object]:
    payload = _valid_output()
    clause_id = payload["source_clauses"][0]["clause_id"]
    item = dict(binding)
    if case == "duplicate":
        item["clause_ids"] = [clause_id, clause_id]
    elif case in {"source", "structure"}:
        item["clause_ids"] = [clause_id]
        if case == "source":
            item["supplement_id"] = "SECRET-supplement"
    payload["field_bindings"] = [item]
    return payload


@pytest.mark.parametrize(("expected_code", "binding", "case"), _SAFE_CASES)
def test_field_binding_validator_failures_have_fixed_content_free_codes(
    tmp_path: Path,
    expected_code: str,
    binding: dict[str, object],
    case: str,
) -> None:
    result = _extract(_invalid_output(case, binding))

    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.diagnostic is not None
    assert result.diagnostic.stage == "schema"
    assert result.diagnostic.reason == "SCHEMA"
    assert result.diagnostic.path == "field_bindings[0]"
    assert result.diagnostic.schema_error_type == expected_code
    assert "SECRET" not in result.model_dump_json()

    sidecar = tmp_path / "monitor.ai-extraction-diagnostics.jsonl"
    append_extraction_diagnostic(
        sidecar,
        result=result,
        configured_model="offline-v4",
        completed_at=datetime(2026, 9, 16, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    record = json.loads(sidecar.read_text("utf-8"))
    assert record["version"] == 2
    assert record["schemaErrorType"] == expected_code
    assert "SECRET" not in sidecar.read_text("utf-8")


def test_valid_field_binding_acceptance_is_unchanged() -> None:
    payload = _valid_output()
    payload["field_bindings"] = [
        {
            "path": "schema_version",
            "value": 3,
            "unit": "NONE",
            "origin": "CONTRACT",
            "binding_kind": "VALUE",
            "clause_ids": [],
            "supplement_id": None,
            "contract_id": "schema-literal-v1",
        }
    ]

    result = _extract(payload)

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.mapping is not None
    assert result.mapping.field_bindings[0].path == "schema_version"


def test_unrecognized_custom_validator_code_falls_back_without_error_text() -> None:
    class UnknownValidator(BaseModel):
        value: str

        @model_validator(mode="after")
        def reject_value(self):
            raise PydanticCustomError(
                "SECRET_dynamic_validator_code",
                "SECRET dynamic validator message",
            )

    with pytest.raises(ValidationError) as captured:
        UnknownValidator(value="SECRET-input")

    safe_code = _safe_schema_error_type(captured.value)

    assert safe_code == "other"
    assert "SECRET" not in safe_code


def test_v6_candidate_states_cross_field_binding_contract_without_changing_default() -> None:
    prompt = build_plan_extraction_prompt(
        "OFFLINE SYNTHETIC SOURCE",
        prompt_version="plan-extract-v6",
    )

    assert PLAN_EXTRACTION_PROMPT_VERSION == "plan-extract-v5"
    assert prompt.startswith("Prompt version: plan-extract-v6")
    assert "clause_ids must be unique" in prompt
    assert "SOURCE requires non-empty clause_ids" in prompt
    assert "Do not emit USER_SUPPLEMENT bindings" in prompt
    assert "CONTRACT requires empty clause_ids" in prompt
    assert "Each (binding_kind, path) identity must be unique" in prompt
    assert "STRUCTURE value must be exactly ALL or ANY" in prompt
    assert "VALUE must address a scalar current draft field" in prompt
    assert "*_fen uses FEN" in prompt
    assert "minimum_ratio uses RATIO" in prompt
    assert AIConfiguration(prompt_version="plan-extract-v6").prompt_version == "plan-extract-v6"


def test_v6_candidate_has_frozen_prompt_bytes_and_uses_mapping_parser() -> None:
    prompt = build_plan_extraction_prompt(
        "GOLDEN_PLAN_SOURCE",
        prompt_version="plan-extract-v6",
    )
    config = _config().model_copy(update={"prompt_version": "plan-extract-v6"})
    result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=_SOURCE,
            config=config,
            provider=_StaticProvider(json.dumps(_valid_output(), ensure_ascii=False)),
        )
    )

    assert sha256(prompt.encode()).hexdigest() == (
        "bb7103099469ff8f159975d2401992f0fe6d254713e627b196eabcff068e3de3"
    )
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.prompt_version == "plan-extract-v6"
    assert result.mapping is not None
