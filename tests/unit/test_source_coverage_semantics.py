"""Independent source mutations keep spans/refs valid while changing obligations."""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.ai.daily_review import DailyClause, DailyMapping, semantic_values
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.p3_validation import P3PlanDraft

_PRICE = "alert_rules[0].condition.conditions[0]"
_TREND = "alert_rules[0].condition.conditions[1]"
_FEES = "position.limit.capital_policy.buy_cost_schedule"
_BUY = "ordinary_rules[0]"

_MUTATIONS = [
    (f"{_PRICE}.comparator", "GTE"),
    (f"{_BUY}.pretrade_policy.sizing.base_qty", 1100),
    ("position.limit.max_qty", 900),
    (f"{_FEES}.minimum_commission_fen", 5),
    (f"{_FEES}.currency", "USD"),
    (f"{_PRICE}.reference.unit", "INDICATOR"),
    (f"{_PRICE}.offset", 1),
    (f"{_TREND}.reference.indicator", "MA60"),
    (f"{_TREND}.reference.offset", 2),
    (f"{_BUY}.market_policy.exception_routes.weak_minimum", "DISABLED"),
    (f"{_BUY}.market_policy.exception_routes.broken_strong", "DISABLED"),
    (f"{_BUY}.validity.start_date", "2026-09-02"),
    (f"{_BUY}.validity.end_date", "2026-12-30"),
]


def _native_baseline():
    raw = p3_payload("OPEN_COST_CAP", combined=True)
    raw["alert_rules"] = [{
        "kind": "RISK_ALERT",
        "rule_id": "semantic-comparison-alert",
        "condition": {"type": "ALL", "conditions": [
            {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
             "comparator": "GT", "reference": {"mode": "FIXED", "value": "1000",
                "unit": "FEN", "as_of": None, "source": "Exact synthetic fixed threshold"}},
            {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
             "comparator": "GT", "reference": {"mode": "DYNAMIC", "indicator": "MA20",
                "formula_version": "daily-ta-v2", "parameters": {"period": 20}, "offset": 0}},
        ]},
        "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
    }]
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    return draft, source, mapping


def _rebuilt_source(draft, mapping, *, replacements=None, suffixes=None):
    """Rebind every source reference; no stale span/hash is used as the oracle."""
    values = semantic_values(draft)
    replacements, suffixes = replacements or {}, suffixes or {}
    assert set(replacements) | set(suffixes) <= values.keys()
    lines = [
        f"{path} = {json.dumps(replacements.get(path, value), ensure_ascii=False)}"
        + suffixes.get(path, "")
        for path, value in values.items()
    ]
    source = "\n".join(lines)
    canonical = server_source_clauses(source)
    by_path, ranges, cursor = {}, {}, 0
    clauses = []
    for path, line in zip(values, lines, strict=True):
        group = tuple(clause for clause in canonical if cursor <= clause.start < cursor + len(line))
        assert group
        by_path[path] = group
        ranges[path] = (cursor, cursor + len(line))
        for clause in group:
            raw = clause.model_dump()
            raw.update(disposition="POLICY", paths=(path,), reason="Exact source declaration")
            clauses.append(DailyClause.model_validate(raw))
        cursor += len(line) + 1
    changed = DailyMapping.model_validate({
        **mapping.model_dump(mode="python"),
        "clauses": tuple(clauses),
        "bindings": tuple(binding.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in by_path[binding.path]),
        }) for binding in mapping.bindings),
    })
    _assert_exact_source_structure(draft, mapping, source, changed)
    return source, changed, ranges


def _assert_exact_source_structure(draft, original, source, changed):
    canonical = server_source_clauses(source)

    def identity(clause):
        return clause.clause_id, clause.start, clause.end, clause.excerpt

    assert tuple(map(identity, changed.clauses)) == tuple(map(identity, canonical))
    assert changed.candidate_content_hash == daily_draft_content_sha256(draft)
    assert changed.candidate_content_hash == original.candidate_content_hash
    assert len(changed.bindings) == len(original.bindings)
    assert [(b.path, b.value) for b in changed.bindings] == [
        (b.path, b.value) for b in original.bindings
    ]
    clauses = {clause.clause_id: clause for clause in changed.clauses}
    for binding in changed.bindings:
        assert binding.clause_ids
        assert all(binding.path in clauses[key].paths for key in binding.clause_ids)
    assert draft.to_executable() is not None


def _assess(draft, mapping, source):
    from trade_plan_monitor.ai.source_coverage import assess_source_coverage

    return assess_source_coverage(draft, mapping, source)


def _assert_semantic_blocked(assessment, source, spans):
    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    related = [issue for issue in assessment.issues if isinstance(issue.start, int)
               and isinstance(issue.end, int) and any(
        issue.start < end and issue.end > start for start, end in spans
    )]
    assert related
    for issue in related:
        assert issue.code.startswith("SOURCE_")
        assert 0 <= issue.start < issue.end <= len(source)
        assert issue.path


def test_native_price_trend_and_complete_p3_declarations_are_a_positive_baseline():
    draft, source, mapping = _native_baseline()
    assessment = _assess(draft, mapping, source)
    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False


def test_all_value_mutations_have_rebuilt_valid_spans_and_unchanged_candidate():
    draft, _, mapping = _native_baseline()
    values = semantic_values(draft)
    original = draft.model_dump_json()
    for path, value in _MUTATIONS:
        assert value != values[path]
        source, changed, ranges = _rebuilt_source(draft, mapping, replacements={path: value})
        start, end = ranges[path]
        assert source[start:end] == f"{path} = {json.dumps(value, ensure_ascii=False)}"
        assert draft.model_dump_json() == original
        assert changed.candidate_content_hash == mapping.candidate_content_hash


@pytest.mark.parametrize("path,value", _MUTATIONS, ids=[path for path, _ in _MUTATIONS])
def test_changed_source_semantics_cannot_pass_with_the_unchanged_candidate(path, value):
    draft, _, mapping = _native_baseline()
    original = draft.model_dump_json()
    source, changed, ranges = _rebuilt_source(draft, mapping, replacements={path: value})

    assessment = _assess(draft, changed, source)

    _assert_semantic_blocked(assessment, source, [ranges[path]])
    assert draft.model_dump_json() == original


@pytest.mark.parametrize("tail", [
    " AND turnover must exceed 3 percent.",
    "且换手率必须超过3%才允许买入。",
])
def test_one_price_binding_cannot_discharge_an_extra_same_clause_turnover_condition(tail):
    draft, _, mapping = _native_baseline()
    path = f"{_PRICE}.reference.value"
    source, changed, ranges = _rebuilt_source(draft, mapping, suffixes={path: tail})
    bound = next(binding for binding in changed.bindings if binding.path == path)
    assert len(bound.clause_ids) == 1
    clause = next(clause for clause in changed.clauses if clause.clause_id == bound.clause_ids[0])
    assert clause.paths == (path,)
    assert tail in clause.excerpt

    assessment = _assess(draft, changed, source)

    _assert_semantic_blocked(assessment, source, [ranges[path]])


def test_both_price_leaves_present_does_not_cover_a_changed_and_or_relationship():
    draft, _, mapping = _native_baseline()
    root = "alert_rules[0].condition"
    source, changed, ranges = _rebuilt_source(
        draft, mapping, replacements={root: "ANY", root + ".type": "ANY"},
    )
    values = semantic_values(draft)
    leaf_paths = {path for path in values if path.startswith(root + ".conditions[")}
    assert leaf_paths
    bound_leaves = {binding.path for binding in changed.bindings if binding.path in leaf_paths}
    assert bound_leaves == leaf_paths
    for path in leaf_paths:
        start, end = ranges[path]
        assert source[start:end] == f"{path} = {json.dumps(values[path], ensure_ascii=False)}"

    assessment = _assess(draft, changed, source)

    _assert_semantic_blocked(assessment, source, [ranges[root], ranges[root + ".type"]])
