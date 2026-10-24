"""Unmodified live responses exercise the real parser and complete source review."""

import json
from pathlib import Path

import pytest
from tests.unit.test_current_review_contract import extract_response

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import build_current_plan_prompt
from trade_plan_monitor.ai.review import server_source_clauses

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai" / "empty-array-contract"


@pytest.mark.parametrize(
    "case,symbol,market,cap,prices",
    [
        ("sse-one-alert", "600010.SH", "SSE", 500, [("LT", "1207")]),
        ("szse-two-alerts", "000858.SZ", "SZSE", 800, [("LT", "7432"), ("GT", "8567")]),
    ],
)
def test_real_cross_symbol_responses_pass_without_repairs(case, symbol, market, cap, prices):
    record = json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    result = extract_response(record["response"], record["source"])
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.validation_issues == result.assumptions == result.warnings == ()
    draft = result.draft
    assert draft.to_executable() is not None
    assert (draft.symbol, draft.market, draft.position.max_qty) == (symbol, market, cap)
    assert draft.ordinary_rules == draft.risk_branches == ()
    assert [
        (r.condition.comparator, str(r.condition.reference.value)) for r in draft.alert_rules
    ] == prices
    for alert in draft.alert_rules:
        assert alert.kind == "RISK_ALERT"
        assert alert.condition.field == "close" and alert.condition.offset == 0
        assert alert.condition.reference.unit == "FEN"
        assert alert.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
    values = semantic_values(draft)
    assert {b.path for b in result.daily_mapping.bindings} == values.keys()
    for binding in result.daily_mapping.bindings:
        assert type(binding.value) is type(values[binding.path])
        assert binding.value == values[binding.path]
    prompt = build_current_plan_prompt(record["source"])
    assert len(prompt) <= 50_000
    clauses = json.JSONDecoder().raw_decode(prompt.split("Canonical source clauses:\n")[1])[0]
    expected = server_source_clauses(record["source"])
    # Compact prompts omit only empty output placeholders, never source evidence.
    assert all(c.disposition.value == "UNRESOLVED" and c.paths == () for c in expected)
    assert clauses == [c.model_dump(mode="json", exclude={"disposition", "paths"})
                       for c in expected]
    assert all(set(c) == {"clause_id", "start", "end", "excerpt"} for c in clauses)


@pytest.mark.parametrize("case", ["sse-one-alert", "szse-two-alerts"])
def test_original_empty_array_string_responses_remain_rejected(case):
    record = json.loads((FIXTURES / f"{case}-before.json").read_text(encoding="utf-8"))
    raw = json.loads(record["response"])
    assert any(b["value"] == "[]" for b in raw["bindings"])
    result = extract_response(record["response"], record["source"])
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_FIELD_EVIDENCE_INVALID"
