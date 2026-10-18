"""Regression against the user's exact four TXT originals, without companion JSON."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_monitor_loop_extraction import update_context

from trade_plan_monitor.ai.loop_plan_extraction import build_loop_plan_prompt
from trade_plan_monitor.ai.plan_update_extraction import build_plan_update_prompt
from trade_plan_monitor.ai.provider import PlanExtractionRequest
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.backtest.preparation_dates import infer_effective_trade_date

SOURCES = sorted((Path(__file__).parents[1] / "fixtures/shengxin_sources").glob("*.txt"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_actual_originals_fit_default_budget_without_losing_source_evidence(path):
    source = path.read_text(encoding="utf-8-sig")
    prompt = build_loop_plan_prompt(source)
    request = PlanExtractionRequest(request_id=uuid4(),
        config=_config().model_copy(update={"max_input_chars": 50_000}), prompt=prompt)
    assert len(request.prompt) <= 50_000
    payload = json.loads(prompt.split("UNTRUSTED_PLAN_DATA_START\n")[1].split(
        "\nUNTRUSTED_PLAN_DATA_END")[0])
    assert payload["source_text"] == source
    for actual, expected in zip(payload["clauses"], server_source_clauses(source), strict=True):
        assert {key: actual[key] for key in ("clause_id", "start", "end", "excerpt")} == {
            key: getattr(expected, key) for key in ("clause_id", "start", "end", "excerpt")}
    assert infer_effective_trade_date(source) is None


@pytest.mark.parametrize("path", SOURCES[1:], ids=lambda path: path.name)
def test_actual_followups_fit_with_validated_past_context(path):
    source = path.read_text(encoding="utf-8-sig")
    context = update_context()
    prompt = build_plan_update_prompt(source, context)
    PlanExtractionRequest(request_id=uuid4(),
        config=_config().model_copy(update={"max_input_chars": 50_000}), prompt=prompt)
    payload = json.loads(prompt.split("UNTRUSTED_PLAN_DATA_START\n")[1].split(
        "\nUNTRUSTED_PLAN_DATA_END")[0])
    assert payload["source_text"] == source
    assert payload["past_context"] == context.model_dump(mode="json")


def test_compact_schema_keeps_titles_inside_literal_values_and_properties():
    from trade_plan_monitor.ai.prompt_encoding import compact_schema

    schema = {"title": "Display", "type": "object", "properties": {
        "title": {"title": "Field", "type": "string", "default": "name"}},
        "default": {"title": "literal"}, "required": ["title"]}
    result = json.loads(compact_schema(schema))
    assert result["default"] == {"title": "literal"}
    assert result["properties"]["title"] == {"type": "string", "default": "name"}
    assert result["required"] == ["title"]


def test_compact_schema_omits_redundant_discriminator_but_keeps_union_constraints():
    from trade_plan_monitor.ai.prompt_encoding import compact_schema

    schema = {"discriminator": {"propertyName": "type", "mapping": {"A": "#/$defs/A"}},
              "oneOf": [{"$ref": "#/$defs/A"}],
              "$defs": {"A": {"type": "object", "properties": {
                  "type": {"const": "A"}, "discriminator": {"type": "string"}},
                  "required": ["type"], "additionalProperties": False}},
              "default": {"discriminator": "literal"}}
    result = json.loads(compact_schema(schema))
    assert "discriminator" not in result
    assert result["oneOf"] == schema["oneOf"]
    assert result["$defs"] == schema["$defs"]
    assert result["default"] == schema["default"]
