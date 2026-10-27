"""Independent reverse-provenance attacks never authorize or edit a saved plan."""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    build_daily_review,
    semantic_values,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.p3_validation import P3PlanDraft


def _native_candidate(join):
    raw = p3_payload()
    raw["ordinary_rules"][0]["condition"] = {
        "type": join,
        "conditions": [
            {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
             "comparator": "GT", "reference": {"mode": "FIXED", "value": "1000",
                 "unit": "FEN", "as_of": None, "source": "Exact synthetic threshold"}},
            {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
             "comparator": "GT", "reference": {"mode": "DYNAMIC", "indicator": "MA20",
                 "formula_version": "daily-ta-v2", "parameters": {}, "offset": 0}},
        ],
    }
    return P3PlanDraft.model_validate(raw)


def _assert_legacy_passes_but_current_blocks(draft, mapping, source):
    # Exact source/candidate integrity and the historical blind spot are retained.
    assert not build_daily_review(draft, mapping, source).issues
    assert draft.to_executable() is not None
    result = assess_source_coverage(draft, mapping, source)
    assert result.coverage_complete is False
    assert result.status == "BLOCKED"
    assert result.issues
    assert result.authority_granted is False


@pytest.mark.parametrize("join", ["ANY", "ALL"])
def test_candidate_cannot_add_an_unsourced_fact_by_citing_the_scalar_group_label(join):
    before = _native_candidate(join)
    source, mapping = source_mapping(before)
    assert assess_source_coverage(before, mapping, source).coverage_complete
    raw = before.model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["conditions"].append({
        "type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
        "evidence_requirement": "Additional unrequested candle pattern",
        "validity_scope": "TRADE_DATE",
    })
    after = P3PlanDraft.model_validate(raw)
    values = semantic_values(after)
    invented = sorted(values.keys() - semantic_values(before).keys())
    assert len(invented) == 4
    victim = next(c for c in mapping.clauses
                  if c.paths == ("ordinary_rules[0].condition.type",))
    clauses = tuple(c.model_copy(update={"paths": (*c.paths, *invented)})
                    if c.clause_id == victim.clause_id else c for c in mapping.clauses)
    extra = tuple(DailyFieldBinding(path=path, value=values[path], origin="SOURCE_SEMANTIC",
        unit="JSON", clause_ids=(victim.clause_id,), supplement_id=None) for path in invented)
    changed = DailyMapping.model_validate(mapping.model_dump(mode="python") | dict(
        candidate_content_hash=daily_draft_content_sha256(after),
        clauses=clauses, bindings=(*mapping.bindings, *extra),
    ))

    _assert_legacy_passes_but_current_blocks(after, changed, source)


@pytest.mark.parametrize("omitted", [
    "ordinary_rules[0].condition.conditions[0].comparator",
    "ordinary_rules[0].condition.conditions[0].type",
])
def test_a_scalar_all_label_cannot_prove_an_unstated_descendant_enum(omitted):
    draft = _native_candidate("ALL")
    _, original = source_mapping(draft)
    values = semantic_values(draft)
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}")
            for path, value in values.items() if path != omitted]
    source = "\n".join(line for _, line in rows)
    canonical = server_source_clauses(source)
    groups, cursor = {}, 0
    for path, line in rows:
        groups[path] = tuple(c for c in canonical if cursor <= c.start < cursor + len(line))
        cursor += len(line) + 1
    group_path = "ordinary_rules[0].condition"
    victim_ids = {c.clause_id for c in groups[group_path]}
    clauses = tuple(DailyClause.model_validate(c.model_dump() | dict(
        disposition="POLICY", paths=(path, omitted) if c.clause_id in victim_ids else (path,),
        reason="Exact synthetic declaration",
    )) for path, _ in rows for c in groups[path])
    bindings = tuple(binding.model_copy(update={
        "clause_ids": tuple(c.clause_id for c in groups[
            group_path if binding.path == omitted else binding.path]),
        **({"origin": "SOURCE_SEMANTIC", "unit": "JSON"} if binding.path == omitted else {}),
    }) for binding in original.bindings)
    mapping = DailyMapping.model_validate(original.model_dump(mode="python") | dict(
        clauses=clauses, bindings=bindings,
    ))

    _assert_legacy_passes_but_current_blocks(draft, mapping, source)


def test_equal_values_do_not_allow_source_bindings_to_exchange_different_scopes():
    draft = P3PlanDraft.model_validate(p3_payload())
    source, mapping = source_mapping(draft)
    left, right = "position.tactical_target_qty", "risk_branches[0].target_core_qty"
    values = semantic_values(draft)
    assert values[left] == values[right] == 0
    old = {binding.path: binding for binding in mapping.bindings}
    left_ids, right_ids = old[left].clause_ids, old[right].clause_ids
    clauses = tuple(c.model_copy(update={"paths": (right,)}) if c.clause_id in left_ids
                    else c.model_copy(update={"paths": (left,)}) if c.clause_id in right_ids
                    else c for c in mapping.clauses)
    swaps = {left: right_ids, right: left_ids}
    bindings = tuple(binding.model_copy(update={"clause_ids": swaps[binding.path]})
                     if binding.path in swaps else binding for binding in mapping.bindings)
    changed = DailyMapping.model_validate(mapping.model_dump(mode="python") | dict(
        clauses=clauses, bindings=bindings,
    ))

    _assert_legacy_passes_but_current_blocks(draft, changed, source)


@pytest.mark.parametrize("padding", [0, 520], ids=["one-chunk", "across-512-chunk"])
def test_display_name_cannot_swallow_an_additional_mandatory_instruction(padding):
    raw = p3_payload()
    raw["name"] = "Observation. Only buy when turnover exceeds 3 percent."
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    source += "\nname = " + " " * padding + json.dumps(draft.name, ensure_ascii=False)
    extra = server_source_clauses(source)[len(mapping.clauses):]
    assert len(extra) == (1 if not padding else 2)
    changed = DailyMapping.model_validate(mapping.model_dump(mode="python") | dict(
        clauses=(*mapping.clauses, *(DailyClause.model_validate(c.model_dump() | dict(
            disposition="CONTEXT", semantic_role="COMMENTARY", paths=(),
            reason="Display name is claimed to be context",
        )) for c in extra)),
    ))

    _assert_legacy_passes_but_current_blocks(draft, changed, source)
