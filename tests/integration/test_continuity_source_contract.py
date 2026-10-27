"""Current synthetic workflow sources preserve the complete original snapshot."""

import json

import pytest
from tests.integration.test_monitor_loop_production_composition import (
    CONTINUITY,
    continuity_output,
    continuity_sources,
)

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionOutput
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.source_obligations import declarations
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


@pytest.mark.parametrize("index", range(4))
def test_current_synthetic_source_declares_every_exact_policy_value(index):
    original = CONTINUITY["sources"][index]
    source = continuity_sources()[index]
    draft = UnifiedPlanDraft.model_validate_json(json.dumps(original["snapshot"]))
    values = semantic_values(draft)
    parsed = {row.path: row for row in declarations(source["text"])}
    assert set(values) <= parsed.keys()
    for path, value in values.items():
        assert type(parsed[path].value) is type(value) and parsed[path].value == value, path
    assert all(source[key] == original[key] for key in (
        "source_id", "authored_at", "available_at", "effective_trade_date"))
    assert source["text"].count("完整替换此前计划。") == (1 if index else 0)


@pytest.mark.parametrize("index", range(4))
def test_synthetic_output_maps_actual_current_declarations_without_changing_snapshot(index):
    source = continuity_sources()[index]
    model = PlanUpdateExtractionOutput if index else LoopPlanExtractionOutput
    output = model.model_validate_json(json.dumps(continuity_output(index, source["text"])))
    assert output.draft.model_dump(mode="json") == CONTINUITY["sources"][index]["snapshot"]
    policy = {path: value for path, value in semantic_values(output.draft).items()}
    source_bindings = {row.path: row for row in output.bindings if row.clause_ids}
    assert set(policy) <= source_bindings.keys()
    for path, value in policy.items():
        bound = source_bindings[path]
        assert type(bound.value) is type(value) and bound.value == value
        if type(value) is bool or value is None:
            assert bound.origin == "SOURCE_SEMANTIC"
    assert all(row.paths or row.excerpt == "完整替换此前计划。"
               or row.semantic_role in {"ACCOUNT", "COMMENTARY"} for row in output.clauses)
