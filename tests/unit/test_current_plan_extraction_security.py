"""Trust-boundary checks use the sole current extraction schema and real parser."""

import asyncio
import json
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

SOURCE = "Synthetic reviewed source with technical choices still awaiting explicit review."


def current_output():
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(unified_payload()))
    return {
        "draft": draft.model_dump(mode="json"),
        "bindings": [],
        "clauses": [
            {
                **c.model_dump(mode="json"),
                "disposition": "UNRESOLVED",
                "paths": [],
                "reason": "Bind exact source policy before activation.",
            }
            for c in server_source_clauses(SOURCE)
        ],
    }


def extract(output, *, finish_reason="stop"):
    identity = uuid4()
    config = _config()  # Retired config label cannot select a retired extraction workflow.

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "plan-extract-v11"
            return RawAIResponse(
                request_id=identity,
                provider_id=config.provider_id,
                model=config.model,
                content=output if isinstance(output, str) else json.dumps(output),
                finish_reason=finish_reason,
                attempts=1,
                usage=None,
            )

    return asyncio.run(
        extract_plan(request_id=identity, source_text=SOURCE, config=config, provider=Provider())
    )


@pytest.mark.parametrize(
    "attack",
    [
        "extra_root",
        "extra_plan_field",
        "missing_clause",
        "changed_source_span",
        "forged_human",
        "forged_contract",
        "wrong_bound_value",
        "fundamental_condition",
    ],
)
def test_current_ai_cannot_forge_review_or_hide_source(attack):
    output = current_output()
    if attack == "extra_root":
        output["SECRET_untrusted"] = "execute arbitrary code"
    elif attack == "extra_plan_field":
        output["draft"]["execute_python"] = "SECRET_untrusted"
    elif attack == "missing_clause":
        output["clauses"] = []
    elif attack == "changed_source_span":
        output["clauses"][0]["excerpt"] = "SECRET_untrusted"
    elif attack == "fundamental_condition":
        output["draft"]["ordinary_rules"][0]["condition"] = {
            "type": "REVIEWED_FACT",
            "fact_kind": "PRICE_STRUCTURE",
            "evidence_requirement": "Fundamental announcement verification",
            "validity_scope": "TRADE_DATE",
        }
    else:
        output["bindings"] = [
            {
                "path": "position.max_qty" if attack == "forged_contract" else "schema_version",
                "value": 300 if attack == "forged_contract" else 4,
                "origin": "HUMAN_SUPPLEMENT" if attack == "forged_human" else "PRODUCT_CONTRACT",
                "unit": "JSON",
                "clause_ids": [],
                "supplement_id": "SECRET_untrusted" if attack == "forged_human" else None,
            }
        ]
    result = extract(output)
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert "SECRET_untrusted" not in result.model_dump_json()
    assert result.diagnostic is not None


@pytest.mark.parametrize(
    "content",
    [
        '{"draft":null,"draft":null}',
        '{"draft": NaN}',
        "[1,2,3]",
        '{"SECRET_untrusted":',
    ],
)
def test_current_json_boundary_rejects_ambiguous_or_malformed_output(content):
    result = extract(content)
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert "SECRET_untrusted" not in result.model_dump_json()


def test_current_truncated_valid_output_never_creates_a_draft():
    result = extract(current_output(), finish_reason="length")
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_OUTPUT_TRUNCATED"


def test_current_missing_parameters_remain_a_reviewable_blocked_candidate():
    output = current_output()
    output["draft"]["ordinary_rules"][0]["quantity"] = None
    result = extract(output)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft.to_executable() is None
    assert any(i.code == "PLAN_PARAMETER_REQUIRED" for i in result.validation_issues)
    assert any(i.code == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in result.validation_issues)


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "INVALID_OUTPUT", "PROVIDER_ERROR"])
def test_non_success_http_extraction_never_exposes_current_source_mapping(status):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from pydantic import ValidationError

    from trade_plan_monitor.web.routers.plans import (
        PlanExtractionOperationStatus,
        PlanExtractionView,
    )

    result = extract(current_output())
    instant = datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    payload = {
        "id": uuid4(),
        "provider_id": uuid4(),
        "status": PlanExtractionOperationStatus(status),
        "submitted_at": instant,
        "started_at": None if status == "QUEUED" else instant,
        "completed_at": instant if status in {"INVALID_OUTPUT", "PROVIDER_ERROR"} else None,
        "daily_mapping": result.daily_mapping,
    }
    with pytest.raises(ValidationError, match="cannot expose"):
        PlanExtractionView.model_validate(payload)
