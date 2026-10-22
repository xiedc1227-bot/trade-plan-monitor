"""The AI receives the same evidence rules enforced by the current source reviewer."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.daily_review import daily_contract_bindings, semantic_values
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import (
    CurrentPlanExtractionOutput,
    build_current_plan_prompt,
)
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai" / "current-review-contract"
SOURCE = (FIXTURES / "source.txt").read_text(encoding="utf-8")
CONTRACT_MARKER = "Source review contract (trusted):\n"


def review_contract():
    prompt = build_current_plan_prompt(SOURCE)
    assert CONTRACT_MARKER in prompt, "The model is missing the reviewer's binding contract"
    return json.JSONDecoder().raw_decode(prompt.split(CONTRACT_MARKER, 1)[1])[0]


def extract_response(content):
    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=content,
                finish_reason="stop",
                attempts=1,
                usage=None,
            )

    return asyncio.run(
        extract_plan(request_id=uuid4(), source_text=SOURCE, config=_config(), provider=Provider())
    )


def test_prompt_contract_matches_registered_semantic_paths_and_null_exceptions():
    contract = review_contract()
    output = CurrentPlanExtractionOutput.model_validate_json(
        (FIXTURES / "deepseek-before.json").read_text(encoding="utf-8")
    )
    values = semantic_values(output.draft)
    assert contract["path_root"] == "plan"
    assert contract["forbidden_prefixes"] == ["draft."]
    assert contract["excluded_roots"] == ["plan_id", "version", "name", "metadata"]
    assert all(path.split(".", 1)[0] not in contract["excluded_roots"] for path in values)
    assert "position.max_qty" in values
    assert set(contract["required_scope_paths"]) == {"symbol", "market"}
    assert set(contract["mixed_identity_clause_treatment"]["paths"]) == {"symbol", "market"}
    assert "alert_rules[0].condition.reference.value" in values
    assert "levels" not in values
    assert not set(contract["forbidden_paths"]) & values.keys()
    assert contract["metadata_clause_treatment"]["disposition"] == "CONTEXT"
    assert contract["metadata_clause_treatment"]["paths"] == []
    assert set(contract["mixed_clause_example"]["paths"]) <= values.keys()
    prompt = build_current_plan_prompt(SOURCE)
    assert prompt.index(CONTRACT_MARKER) > prompt.index("\nJSON schema:\n")
    assert values["alert_rules[0].condition.reference.value"] == "2659"
    payload = output.draft.model_dump(mode="json")
    payload["levels"] = dict(low_buy=None, pressure=None, risk_line_fen=None, risk_comparison=None)
    null_values = semantic_values(UnifiedPlanDraft.model_validate(payload))
    assert {path for path, value in null_values.items() if value is None} == set(
        contract["registered_null_paths"]
    )


def test_prompt_product_example_is_accepted_by_the_existing_product_contract():
    contract = review_contract()
    output = CurrentPlanExtractionOutput.model_validate_json(
        (FIXTURES / "deepseek-before.json").read_text(encoding="utf-8")
    )
    example = contract["product_binding_example"]
    actual = {binding.path: binding for binding in daily_contract_bindings(output.draft)}
    assert example == actual[example["path"]].model_dump(mode="json")
    assert contract["product_clause_ids"] == []
    assert contract["supplement_id"] is None
    assert contract["bind_empty_arrays"] is True
    assert contract["group_binding_value"] == "type string"


def test_original_complete_deepseek_failure_is_still_rejected_without_repair():
    content = (FIXTURES / "deepseek-before.json").read_text(encoding="utf-8")
    result = extract_response(content)
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_FIELD_EVIDENCE_INVALID"
    assert result.diagnostic.stage == "mapping"


def test_unmodified_real_response_passes_complete_review_with_one_alert_and_no_trades():
    content = (FIXTURES / "deepseek-after.json").read_text(encoding="utf-8")
    result = extract_response(content)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.validation_issues == ()
    assert result.assumptions == ()
    assert result.warnings == ()
    assert result.draft.to_executable() is not None
    assert result.draft.ordinary_rules == ()
    assert result.draft.risk_branches == ()
    (alert,) = result.draft.alert_rules
    assert alert.kind == "RISK_ALERT"
    assert alert.rule_id == "RISK-ALERT-01"
    assert alert.condition.type == "DAILY_PRICE_COMPARE"
    assert alert.condition.field == "close"
    assert alert.condition.offset == 0
    assert alert.condition.comparator == "LT"
    assert str(alert.condition.reference.value) == "2659"
    assert alert.condition.reference.unit == "FEN"
    assert alert.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
    assert result.draft.metadata.report_at is None
    assert result.draft.position.core_target_qty is None
    assert result.draft.position.tactical_target_qty is None
    assert {b.path for b in result.daily_mapping.bindings} == semantic_values(result.draft).keys()


@pytest.mark.parametrize(
    "defect",
    [
        "draft_prefix",
        "clause_draft_prefix",
        "metadata_binding",
        "null_binding",
        "product_source_ids",
        "decimal_binding_type",
        "missing_clause",
    ],
)
def test_contract_fix_does_not_accept_invalid_evidence_or_repair_model_output(defect):
    output = json.loads((FIXTURES / "deepseek-after.json").read_text(encoding="utf-8"))
    if defect == "draft_prefix":
        output["bindings"][0]["path"] = "draft." + output["bindings"][0]["path"]
    elif defect == "clause_draft_prefix":
        clause = next(c for c in output["clauses"] if c["paths"])
        clause["paths"][0] = "draft." + clause["paths"][0]
    elif defect in {"metadata_binding", "null_binding"}:
        output["bindings"].append(
            {
                "path": "metadata.reference_price_fen"
                if defect == "metadata_binding"
                else "levels",
                "value": 3030 if defect == "metadata_binding" else None,
                "origin": "SOURCE",
                "unit": "JSON",
                "clause_ids": [output["clauses"][0]["clause_id"]],
                "supplement_id": None,
            }
        )
    elif defect == "product_source_ids":
        binding = next(b for b in output["bindings"] if b["origin"] == "PRODUCT_CONTRACT")
        binding["clause_ids"] = [output["clauses"][0]["clause_id"]]
    elif defect == "decimal_binding_type":
        binding = next(
            b for b in output["bindings"] if b["path"].endswith("condition.reference.value")
        )
        binding["value"] = 2659
    elif defect == "missing_clause":
        output["clauses"].pop()
    result = extract_response(json.dumps(output, ensure_ascii=False))
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_FIELD_EVIDENCE_INVALID"


def test_missing_required_quantity_remains_null_and_blocks_review():
    output = json.loads((FIXTURES / "deepseek-after.json").read_text(encoding="utf-8"))
    output["draft"]["position"]["max_qty"] = None
    output["bindings"] = [b for b in output["bindings"] if b["path"] != "position.max_qty"]
    for clause in output["clauses"]:
        clause["paths"] = [p for p in clause["paths"] if p != "position.max_qty"]
    result = extract_response(json.dumps(output, ensure_ascii=False))
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft.position.max_qty is None
    assert result.draft.to_executable() is None
    assert any(i.code == "PLAN_PARAMETER_REQUIRED" for i in result.validation_issues)
