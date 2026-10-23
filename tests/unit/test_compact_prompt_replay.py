"""Replay unmodified compact-source responses through the strict production boundary."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_current_review_contract import extract_response

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import build_current_plan_prompt
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai" / "compact-prompt"


def record(case):
    return json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case,symbol,market,cap,prices",
    [
        ("sse-one-alert", "600010.SH", "SSE", 500, [("LT", "1207")]),
        ("szse-two-alerts", "000858.SZ", "SZSE", 800, [("LT", "7432"), ("GT", "8567")]),
    ],
)
def test_live_compact_sources_preserve_all_rules_and_evidence(case, symbol, market, cap, prices):
    frozen = record(case)
    result = extract_response(frozen["response"], frozen["source"])
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.validation_issues == result.assumptions == result.warnings == ()
    draft = result.draft
    assert draft.to_executable() is not None
    assert (draft.symbol, draft.market, draft.position.max_qty) == (symbol, market, cap)
    assert draft.ordinary_rules == draft.risk_branches == ()
    assert draft.metadata.report_at is None
    observed_prices = [
        (r.condition.comparator, str(r.condition.reference.value)) for r in draft.alert_rules
    ]
    assert observed_prices == prices
    for alert in draft.alert_rules:
        assert alert.kind == "RISK_ALERT"
        assert alert.condition.type == "DAILY_PRICE_COMPARE"
        assert alert.condition.field == "close" and alert.condition.offset == 0
        assert alert.condition.reference.unit == "FEN"
        assert alert.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
    values = semantic_values(draft)
    assert len(result.daily_mapping.bindings) == len(values)
    assert {binding.path for binding in result.daily_mapping.bindings} == values.keys()
    for binding in result.daily_mapping.bindings:
        assert type(binding.value) is type(values[binding.path])
        assert binding.value == values[binding.path]
        if binding.origin == "PRODUCT_CONTRACT":
            assert binding.clause_ids == ()
    canonical = server_source_clauses(frozen["source"])
    observed = result.daily_mapping.clauses
    assert [(c.clause_id, c.start, c.end, c.excerpt) for c in observed] == [
        (c.clause_id, c.start, c.end, c.excerpt) for c in canonical
    ]
    assert len(build_current_plan_prompt(frozen["source"])) <= 50_000
    assert frozen["finish_reason"] == "stop"
    assert frozen["completion_tokens"] < 4096


@pytest.mark.parametrize("violation", ["missing_limit", "unsupported_index", "missing_binding"])
def test_compact_notation_does_not_bypass_required_parameters_or_review(violation):
    frozen = record("szse-two-alerts")
    output = json.loads(frozen["response"])
    if violation == "missing_limit":
        del output["draft"]["position"]["max_qty"]
    elif violation == "unsupported_index":
        output["draft"]["alert_rules"][0]["condition"]["type"] = "INDEX_STATE"
    else:
        output["bindings"] = [
            b for b in output["bindings"] if b["path"] != "alert_rules[1].condition.reference.value"
        ]
    # Deliberately corrupt a test copy; live provider responses are never repaired.
    result = extract_response(json.dumps(output, ensure_ascii=False), frozen["source"])
    if violation == "missing_binding":
        # Parsing succeeds, but complete source review must block activation.
        assert result.status is PlanExtractionStatus.SUCCEEDED
        assert len(result.validation_issues) == 1
        issue = result.validation_issues[0]
        assert issue.code == "DAILY_SOURCE_BINDING_REQUIRED"
        assert issue.path == "alert_rules[1].condition.reference.value"
        assert issue.activation_blocking is True
    else:
        assert result.status is PlanExtractionStatus.INVALID_OUTPUT
        assert result.draft is None
        assert result.validation_issues


def test_original_live_truncation_still_fails_closed():
    frozen = record("szse-two-alerts-truncated")

    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=frozen["response"],
                finish_reason=frozen["finish_reason"],
                attempts=1,
                usage=None,
            )

    result = asyncio.run(
        extract_plan(
            request_id=uuid4(), source_text=frozen["source"], config=_config(), provider=Provider()
        )
    )
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_OUTPUT_TRUNCATED"
