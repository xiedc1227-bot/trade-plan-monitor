"""Offline regression coverage for safe field-binding schema diagnostics."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_core import PydanticCustomError
from tests.unit.test_ai_plan_extraction_v4 import (
    _valid_output,
)

from trade_plan_monitor.ai.extraction import _safe_schema_error_type

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
