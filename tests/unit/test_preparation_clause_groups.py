"""Grouped model classifications retain every canonical clause independently."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.plan_delta_wire import CompactDeltaOutput
from trade_plan_monitor.backtest.preparation_repairs import correction_context


def parse(value):
    return CompactDeltaOutput.model_validate_json(json.dumps(value))


def test_grouped_classifications_expand_without_dropping_individual_decisions():
    output = parse(
        {
            "schema_version": "monitor-loop-delta-wire-v1",
            "operations": [],
            "clauses": [
                {
                    "clause_id": "c1",
                    "meaning": "DIRECTIVE",
                    "disposition": "POLICY",
                    "reason": "Unchanged rule",
                }
            ],
            "clause_groups": [
                {
                    "clause_ids": ["c2", "c3"],
                    "meaning": "HISTORICAL",
                    "disposition": "BACKGROUND",
                    "reason": "Past session observations",
                }
            ],
        }
    )
    assert [c.clause_id for c in output.clauses] == ["c1", "c2", "c3"]
    assert [c.meaning for c in output.clauses] == ["DIRECTIVE", "HISTORICAL", "HISTORICAL"]


def test_duplicate_group_classifications_are_rejected():
    with pytest.raises(ValidationError):
        parse(
            {
                "schema_version": "monitor-loop-delta-wire-v1",
                "operations": [],
                "clause_groups": [
                    {
                        "clause_ids": ["c1", "c1"],
                        "meaning": "HISTORICAL",
                        "disposition": "BACKGROUND",
                        "reason": "Past",
                    }
                ],
            }
        )


def test_group_does_not_classify_unlisted_source_ids():
    output = parse(
        {
            "schema_version": "monitor-loop-delta-wire-v1",
            "operations": [],
            "clause_groups": [
                {
                    "clause_ids": ["c1"],
                    "meaning": "COMMENTARY",
                    "disposition": "BACKGROUND",
                    "reason": "Heading",
                }
            ],
        }
    )
    assert [c.clause_id for c in output.clauses] == ["c1"]


def test_correction_context_keeps_prior_classification_with_its_reason():
    draft = SimpleNamespace(model_dump=lambda **kwargs: {"ordinary_rules": []})
    clauses = tuple(
        SimpleNamespace(
            clause_id=i,
            semantic_role="HISTORICAL",
            disposition="CONTEXT",
            reason="Prior session result",
        )
        for i in ("c1", "c2")
    )
    result = SimpleNamespace(draft=draft, daily_mapping=SimpleNamespace(clauses=clauses))
    context = json.loads(correction_context(result))
    assert context["clause_groups"] == [
        {
            "clause_ids": ["c1", "c2"],
            "meaning": "HISTORICAL",
            "disposition": "BACKGROUND",
            "reason": "Prior session result",
        }
    ]


def test_individual_classification_overrides_group_as_explicit_exception():
    output = parse(
        {
            "schema_version": "monitor-loop-delta-wire-v1",
            "operations": [],
            "clauses": [
                {
                    "clause_id": "c1",
                    "disposition": "POLICY",
                    "meaning": "DIRECTIVE",
                    "reason": "Current instruction",
                }
            ],
            "clause_groups": [
                {
                    "clause_ids": ["c1", "c2"],
                    "meaning": "HISTORICAL",
                    "disposition": "BACKGROUND",
                    "reason": "Past observations",
                }
            ],
        }
    )
    assert {c.clause_id: c.meaning for c in output.clauses} == {
        "c1": "DIRECTIVE",
        "c2": "HISTORICAL",
    }


def test_historical_disposition_alias_requires_matching_semantic_meaning():
    value = {
        "schema_version": "monitor-loop-delta-wire-v1",
        "operations": [],
        "clauses": [
            {
                "clause_id": "c1",
                "disposition": "HISTORICAL",
                "meaning": "HISTORICAL",
                "reason": "Past",
            }
        ],
    }
    assert parse(value).clauses[0].disposition == "BACKGROUND"
    value["clauses"][0]["meaning"] = "DIRECTIVE"
    with pytest.raises(ValidationError):
        parse(value)


def test_group_preserves_explicit_policy_field_associations():
    output = parse(
        {
            "schema_version": "monitor-loop-delta-wire-v1",
            "operations": [],
            "clause_groups": [
                {
                    "clause_ids": ["c1", "c2"],
                    "meaning": "DIRECTIVE",
                    "disposition": "POLICY",
                    "reason": "Pressure band and no-chase context",
                    "paths": ["levels.pressure"],
                }
            ],
        }
    )
    assert all(c.paths == ("levels.pressure",) for c in output.clauses)
    assert CompactDeltaOutput.model_validate_json(output.model_dump_json()) == output


def test_new_execution_authority_must_be_explicit_in_v2():
    value = {
        "schema_version": "monitor-loop-delta-wire-v2",
        "operations": [
            {
                "target": "ordinary_rules",
                "action": "ADD",
                "rule_id": "new-entry",
                "clause_ids": ["c1"],
                "intent": "ASSERTED",
                "rationale": "Conditional entry",
                "values": {"quantity": 100},
            }
        ],
    }
    with pytest.raises(ValidationError):
        parse(value)
    value["operations"][0]["authority"] = "EXECUTE_WHEN_CONDITION_MET"
    assert parse(value).operations[0].authority == "EXECUTE_WHEN_CONDITION_MET"


def test_omitted_collection_index_resolves_only_a_unique_member():
    from trade_plan_monitor.ai.preparation_wire import resolve_singleton_path

    data = {"rules": [{"condition": {"type": "X"}}]}
    assert resolve_singleton_path("rules.condition.type", data) == "rules[0].condition.type"
    data["rules"].append(data["rules"][0])
    with pytest.raises(ValueError):
        resolve_singleton_path("rules.condition.type", data)


def test_earlier_session_intent_cannot_be_encoded_as_same_session_price():
    value = {
        "schema_version": "monitor-loop-delta-wire-v3",
        "operations": [
            {
                "target": "ordinary_rules",
                "action": "ADD",
                "rule_id": "new-entry",
                "clause_ids": ["c1"],
                "intent": "ASSERTED",
                "rationale": "Reclaim then later retest",
                "authority": "EXECUTE_WHEN_CONDITION_MET",
                "temporal_order": "EARLIER_SESSION_THEN_RETEST",
                "values": {"condition": {"type": "DAILY_PRICE_COMPARE"}},
            }
        ],
    }
    with pytest.raises(ValidationError):
        parse(value)
    value["operations"][0]["values"]["condition"] = {
        "type": "ALL",
        "conditions": [
            {
                "type": "DAILY_PRIOR_CLOSE",
                "since_date": "2026-10-12",
                "price_fen": 2100,
                "comparator": "GTE",
            },
            {"type": "REVIEWED_FACT", "evidence_requirement": "later retest"},
        ],
    }
    assert parse(value).operations[0].temporal_order == "EARLIER_SESSION_THEN_RETEST"


def test_null_prior_trade_dependency_is_a_validation_error():
    value = {
        "schema_version": "monitor-loop-delta-wire-v3",
        "operations": [
            {
                "target": "ordinary_rules",
                "action": "ADD",
                "rule_id": "later-entry",
                "clause_ids": ["c1"],
                "intent": "ASSERTED",
                "rationale": "After first trade",
                "authority": "EXECUTE_WHEN_CONDITION_MET",
                "temporal_order": "AFTER_PRIOR_TRADE",
                "values": {"independent_signal": None},
            }
        ],
    }
    with pytest.raises(ValidationError):
        parse(value)
