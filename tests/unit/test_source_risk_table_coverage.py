"""A structural price relationship cannot become current stop, BUY or blanket row authority."""

import json
from datetime import timedelta

import pytest
from tests.unit.test_source_change_composition_attacks import _next
from tests.unit.test_source_change_scopes import _replace_parent
from tests.unit.test_source_control_changes import _assess
from tests.unit.test_source_risk_table_controls import _ORIGINAL, _parent, _row, _table
from tests.unit.test_source_risk_table_integration import _case

from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_risk_controls import parse_source_risk_controls
from trade_plan_monitor.ai.source_risk_table_controls import parse_source_risk_table_controls
from trade_plan_monitor.ai.source_risk_table_coverage import (
    build_risk_table_coverage,
    validate_risk_table_coverage,
)


def _coverage(case):
    source, output, _, _, _, base, parent, _ = case
    evidence = build_risk_table_coverage(source, base, parent)
    analysis = analyze_source(output.draft, output.review(source.text).mapping, source.text,
                              risk_tables=evidence)
    return evidence, analysis


def test_scope_and_structural_reference_are_two_complete_independent_obligations():
    case = _case()
    evidence, result = _coverage(case)
    group, = evidence.analysis.groups
    dependency, = evidence.references
    assert result.issues == () and evidence.issues == ()
    assert dependency.price_owner == next(row for row in case[6].owners
                                         if row.path == "levels.risk_line_fen")
    assert dependency.price_binding == next(row for row in case[5].bindings
                                           if row.path == "levels.risk_line_fen")
    assert dependency.parent_binding == case[6].binding
    assert set(result.proven_paths) == {
        "risk_branches[0].holding_scope.mode", "risk_branches[0].holding_scope.trade_date"}
    relations, scopes = [], []
    for row in result.obligations:
        meaning = json.loads(row.semantics_json)
        if meaning["treatment"] == "REGISTERED_STRUCTURAL_RECOVERY_REFERENCE":
            relations.append(row)
            assert row.kind == "RELATION" and row.scope == "RISK" and row.state == "MAPPED"
            assert row.paths == () and row.group_id == group.group_id
            assert row.relation_ids == (group.scope_control.control_id,)
            assert meaning["structural_reference"] == (
                group.structural_reference.model_dump(mode="json"))
            assert meaning["price_dependency"] == dependency.model_dump(mode="json")
            assert not ({"side", "quantity", "stop", "condition"} & meaning.keys())
        elif meaning["treatment"] == "REGISTERED_SOURCE_RISK_CONTROL":
            scopes.append(row)
    assert relations and len(relations) == len(scopes)
    assert {(row.start, row.end, row.excerpt) for row in relations} == {
        (row.start, row.end, row.excerpt) for row in scopes}
    current = _assess(case)
    assert current.coverage_complete
    assert {row.obligation_id for row in relations} <= {
        row.obligation_id for row in current.global_obligations}
    price_owner = next(row for row in current.owners if row.path == "levels.risk_line_fen")
    assert price_owner.origin == "BASE"
    assert price_owner.proof_hash == dependency.price_owner.proof_hash
    assert not any(row.source_id == case[0].source_id and "risk_line_fen" in row.path
                   for row in current.owners)


@pytest.mark.parametrize("problem", ["missing-owner", "wrong-original-path", "wrong-obligation",
                                      "product-owner"])
def test_complete_parent_still_needs_the_exact_original_price_owner(problem):
    base, parent = _parent()
    unrelated = next(row for row in parent.source_assessment.obligations
                     if row.paths == ("position.max_qty",))
    owners = []
    for owner in parent.owners:
        if owner.path == "levels.risk_line_fen":
            if problem == "missing-owner":
                continue
            change = ({"original_path": "position.max_qty"} if problem == "wrong-original-path"
                      else {"obligation_ids": (unrelated.obligation_id,)}
                      if problem == "wrong-obligation" else {"origin": "PRODUCT_CONTRACT"})
            owner = owner.model_copy(update=change)
        owners.append(owner)
    parent = _replace_parent(parent, owners=tuple(owners))
    assert parent.coverage_complete
    case = _case(base=base, parent=parent)
    assert case[2].review.issues == ()
    evidence, result = _coverage(case)

    assert evidence.analysis.groups and evidence.references == () and evidence.framing == ()
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in evidence.issues)
    assert any(row.kind == "RELATION" and row.state == "UNRESOLVED" for row in result.obligations)
    assert not _assess(case).coverage_complete


def test_relationship_cannot_disappear_while_the_scope_control_is_kept_mapped():
    case = _case()
    evidence, _ = _coverage(case)
    with pytest.raises(ValueError, match="relationship"):
        evidence.model_copy(update={"references": ()})
    missing = evidence.model_copy(update=dict(references=(), framing=(), issues=(CoverageIssue(
        code="SOURCE_COVERAGE_REQUIRED", message="The original structural meaning is unproven"),)))

    result = analyze_source(case[1].draft, case[1].review(case[0].text).mapping, case[0].text,
                            risk_tables=missing)

    assert any(row.kind == "PREDICATE" and row.scope == "RISK" and row.state == "MAPPED"
               for row in result.obligations)
    assert any(row.kind == "RELATION" and row.state == "UNRESOLVED" for row in result.obligations)
    assert result.issues


def test_table_evidence_cannot_be_reused_for_different_source_or_role():
    case = _case()
    evidence, _ = _coverage(case)
    with pytest.raises(ValueError, match="source"):
        validate_risk_table_coverage(evidence, case[0].text.replace("25.99", "26.00"))
    dependency = evidence.references[0]
    with pytest.raises(ValueError):
        dependency.reference.model_copy(update={"role": "NEW_POSITION_STOP"})


@pytest.mark.parametrize("text", [
    _table() + "\n| 追加条件 | 未定义 | 风险退出先等待蓝灯 |",
    "如果明天上涨：\n" + _table(),
    "条件尚未完成\n## 2. 核心价格位置更新\n\n" + _table(),
    "```\n" + _table(),
    "B. Background\n" + _table(),
    _table().replace("**25.99**", "**26.00**"),
    _table().replace("而不是给新仓位直接设止损", "直接给新仓位设止损"),
    _table() + "\n" + _row(),
], ids=["unknown-row", "antecedent", "unfinished-heading", "fence", "background",
        "wrong-price", "wrong-role", "duplicate-target"])
def test_unrecognized_rows_antecedents_price_role_changes_and_duplicates_keep_blocking(text):
    case = _case(text)
    assert case[2].review.issues == ()
    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.scope == "UNKNOWN" or row.state not in {"MAPPED", "CONTEXT_VERIFIED"}
               for row in result.source_assessment.obligations)
    if not parse_source_risk_table_controls(case[0], case[5], case[6]).groups:
        assert not any(json.loads(row.semantics_json or "{}").get("treatment") == (
            "REGISTERED_RISK_TABLE_SYNTAX") for row in result.source_assessment.obligations)


@pytest.mark.parametrize("problem", ["revoke", "unused", "non-scope-change"])
def test_mixed_row_scope_and_price_role_cannot_authorize_other_actual_changes(problem):
    text, options = _table(), {}
    if problem == "revoke":
        options["action"] = "REVOKE"
    elif problem == "unused":
        options["no_operations"] = True
    else:
        text += '\nrisk_branches[0].risk_line_fen = 1234\nrisk_branches[0].risk_comparison = "LT"'
        options["other_update"] = {"risk_line_fen": 1234, "risk_comparison": "LT"}
    case = _case(text, **options)
    assert case[2].review.issues == ()

    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.code == "SOURCE_RELATION_MISMATCH" for row in result.source_assessment.issues)


def test_dedicated_and_table_controls_cannot_repeat_the_same_risk_target():
    text = "旧持仓继续执行风险规则ORDINARY_TECHNICAL，新开仓位不适用该规则。\n" + _table()
    case = _case(text)
    assert case[2].review.issues == ()
    assert parse_source_risk_controls(case[0], case[5], case[6]).controls
    assert parse_source_risk_table_controls(case[0], case[5], case[6]).groups

    result = _assess(case)

    assert not result.coverage_complete
    assert all(row.state == "CONFLICT" for row in result.source_assessment.obligations
               if row.scope == "RISK")


def test_inherited_parent_price_binding_is_preserved_without_reassigning_original_ownership():
    base, parent = _parent()
    middle_case = _next(base, parent)
    middle = _assess(middle_case)
    assert middle.coverage_complete
    source = middle_case[0].model_copy(update=dict(source_id="next-risk-table", text=_table(),
        available_at=middle_case[0].available_at + timedelta(days=1),
        effective_trade_date=(middle_case[0].available_at + timedelta(days=1)).date()))
    before = (middle.model_dump_json(), middle_case[2].review.model_dump_json())

    evidence = build_risk_table_coverage(source, middle_case[2].review, middle)

    assert evidence.issues == () and len(evidence.references) == 1
    dependency = evidence.references[0]
    assert dependency.price_owner.origin == "BASE"
    original = next(row for row in parent.owners if row.path == "levels.risk_line_fen")
    assert dependency.price_owner.proof_hash == original.proof_hash
    assert dependency.price_owner.source_binding_hash == original.source_binding_hash
    assert dependency.price_owner.human_receipt_hash == original.human_receipt_hash
    assert before == (middle.model_dump_json(), middle_case[2].review.model_dump_json())


def test_full_unedited_original04_remains_blocked_until_its_other_real_meanings_are_supported():
    original = _ORIGINAL.read_text(encoding="utf-8")
    case = _case(original)
    assert case[0].text == original
    assert len(case[3].derivation.stages) == 3

    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.scope == "UNKNOWN" and row.state == "UNRESOLVED"
               for row in result.source_assessment.obligations)
    assert case[0].text == _ORIGINAL.read_text(encoding="utf-8")
