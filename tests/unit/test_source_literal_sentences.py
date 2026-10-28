"""Complete literal sentences prove source semantics independently of AI labels."""

import copy
from time import perf_counter

import pytest
from tests.integration.test_source_treatment_review_api import (
    SOURCE,
    literal_draft,
    literal_mapping,
)
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.daily_review import DailyMapping
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_literal_sentences import literal_sentences
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def _mapping(draft, source):
    raw = literal_mapping(draft).model_dump(mode="json")
    canonical = server_source_clauses(source)
    assert len(canonical) == len(raw["clauses"])
    ids = {}
    for current, actual in zip(raw["clauses"], canonical, strict=True):
        ids[current["clause_id"]] = actual.clause_id
        current.update(actual.model_dump(mode="json", include={
            "clause_id", "start", "end", "excerpt",
        }))
    for binding in raw["bindings"]:
        binding["clause_ids"] = [ids[value] for value in binding["clause_ids"]]
    return DailyMapping.model_validate(raw)


def test_complete_literal_source_has_independently_proven_current_coverage():
    draft = literal_draft(complete=True)
    proof = assess_source_coverage(draft, literal_mapping(draft), SOURCE)
    assert proof.coverage_complete, proof.issues
    assert proof.authority_granted is False
    assert all(row.state in {"MAPPED", "CONTEXT_VERIFIED"} for row in proof.obligations)
    assert all(row.excerpt == SOURCE[row.start:row.end] for row in proof.obligations)


@pytest.mark.parametrize("path,value", [
    (("ordinary_rules", 0, "side"), "SELL"),
    (("ordinary_rules", 0, "quantity"), 200),
    (("ordinary_rules", 0, "condition", "type"), "ANY"),
    (("ordinary_rules", 0, "condition", "conditions", 0, "low_fen"), 970),
    (("ordinary_rules", 0, "condition", "conditions", 0, "include_high"), False),
    (("ordinary_rules", 0, "condition", "conditions", 1, "window_bars"), 6),
    (("ordinary_rules", 0, "condition", "conditions", 1, "minimum_ratio"), "1.6"),
    (("ordinary_rules", 1, "condition", "include_low"), False),
    (("alert_rules", 0, "condition", "price_fen"), 940),
])
def test_literal_source_rejects_internally_consistent_candidate_mutations(path, value):
    raw = literal_draft(complete=True).model_dump(mode="json")
    parent = raw
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value
    draft = UnifiedPlanDraft.model_validate(raw)
    proof = assess_source_coverage(draft, literal_mapping(draft), SOURCE)
    assert not proof.coverage_complete
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" for issue in proof.issues)


@pytest.mark.parametrize("before,after", [
    ("且该根", "或该根"),
    ("不低于前5根", "低于前5根"),
    ("包含两端边界时", "不包含两端边界时"),
    ("提醒买入100股。", "提醒买入100股且等待新的批准。"),
    ("发出风险提醒。", "发出风险提醒并卖出100股。"),
    ("未登记成交时持仓不变。", "未登记成交时持仓增加100股。"),
])
def test_complete_sentence_grammar_never_discards_changed_or_unknown_remainder(before, after):
    draft = literal_draft(complete=True)
    source = SOURCE.replace(before, after)
    proof = assess_source_coverage(draft, _mapping(draft, source), source)
    assert not proof.coverage_complete
    assert any(row.state in {"UNRESOLVED", "CONFLICT"} for row in proof.obligations)


def test_literal_source_does_not_supply_missing_human_activation_or_independent_event():
    draft = literal_draft(complete=False)
    proof = assess_source_coverage(draft, literal_mapping(draft), SOURCE)
    assert not proof.coverage_complete
    assert {issue.path for issue in proof.issues} >= {
        "activation", "ordinary_rules.0.independent_signal", "ordinary_rules.1.independent_signal",
    }


@pytest.mark.parametrize("extra", ["conjunct", "alert"])
def test_registered_supplements_cannot_invent_an_extra_source_rule_or_conjunct(extra):
    raw = literal_draft(complete=True).model_dump(mode="json")
    if extra == "conjunct":
        conditions = raw["ordinary_rules"][0]["condition"]["conditions"]
        conditions.append(copy.deepcopy(conditions[0]))
    else:
        rows = raw[extra + "_rules"]
        new = copy.deepcopy(rows[0])
        new["rule_id"] += "-invented"
        rows.append(new)
    draft = UnifiedPlanDraft.model_validate(raw)
    proof = assess_source_coverage(draft, literal_mapping(draft), SOURCE)
    assert not proof.coverage_complete
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" for issue in proof.issues)


@pytest.mark.parametrize("context", ["", "\n# Trade plan", "\n实际持仓100股。"])
def test_complete_literal_source_cannot_gain_an_additional_supplemented_ordinary_rule(context):
    draft = literal_draft(complete=True)
    source = SOURCE.replace(
        "当已完成5分钟K线收盘价处于10.80至11.00元之间，\n"
        "包含两端边界时，提醒卖出100股。\n", "") + context
    proof = assess_source_coverage(draft, reviewed_mapping(draft, source), source)
    assert not proof.coverage_complete
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" for issue in proof.issues)


@pytest.mark.parametrize("context", ["# Trade plan", "实际持仓100股。"])
def test_registered_context_cannot_cancel_literal_rule_cardinality(context):
    raw = literal_draft(complete=True).model_dump(mode="json")
    extra = copy.deepcopy(raw["alert_rules"][0])
    extra["rule_id"] += "-invented"
    raw["alert_rules"].append(extra)
    draft = UnifiedPlanDraft.model_validate(raw)
    source = SOURCE + "\n" + context
    proof = assess_source_coverage(draft, reviewed_mapping(draft, source), source)
    assert not proof.coverage_complete
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" for issue in proof.issues)


@pytest.mark.parametrize("context", ["# Trade plan", "实际持仓100股。"])
def test_registered_context_itself_remains_permitted_alongside_literal_rules(context):
    draft = literal_draft(complete=True)
    source = SOURCE + "\n" + context
    proof = assess_source_coverage(draft, reviewed_mapping(draft, source), source)
    assert proof.coverage_complete, proof.issues


@pytest.mark.parametrize("context", ["", "\n# Trade plan", "\n实际持仓100股。"])
def test_literal_risk_reminder_cannot_gain_supplemented_liquidation_permission(context):
    raw = literal_draft(complete=True).model_dump(mode="json")
    raw["risk_branches"] = [unified_payload()["risk_branches"][1]]
    raw["risk_branches"][0]["suspension_confirmation_policy"] = None
    draft = UnifiedPlanDraft.model_validate(raw)
    source = SOURCE + context
    proof = assess_source_coverage(draft, reviewed_mapping(draft, source), source)
    assert not proof.coverage_complete
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" for issue in proof.issues)


@pytest.mark.parametrize("terminated", [False, True])
def test_maximum_unrecognized_source_has_linear_scan_and_retains_unknown_text(terminated):
    tail = "；最大计划持仓300股。" if terminated else ""
    source = "未知" * ((150_000 - len(tail)) // 2) + tail
    started = perf_counter()
    rows = literal_sentences(source)
    elapsed = perf_counter() - started
    assert elapsed < 2, elapsed
    if terminated:
        assert len(rows) == 1
        assert source[rows[0].start:rows[0].end] == "最大计划持仓300股。"
        assert rows[0].start > 149_000
        assert rows[0].collection_sizes == ()
    else:
        assert rows == ()
