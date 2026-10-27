"""A mixed risk table row retains two independent atoms and all unknown text."""

import importlib
from datetime import date
from functools import lru_cache
from pathlib import Path

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_change_composition_attacks import _initial
from tests.unit.test_source_risk_controls import _parent as _risk_parent

from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

_DAY = date(2026, 10, 9)
_ORIGINAL = (Path(__file__).parents[1] / "fixtures/shengxin_sources/04-20261009-091956.txt")
_HEADER = "| 位置 | 价格 | 当前含义 |"
_SEPARATOR = "|---|---:|---|"
_MEANING = "已失守的原核心风险线；现在用于判断旧结构是否被重新收复，而不是给新仓位直接设止损"


def _row(price="25.99"):
    return f"| **结构修复门槛** | **{price}** | {_MEANING} |"


def _table(price="25.99"):
    return "\n".join((_HEADER, _SEPARATOR, _row(price)))


@lru_cache
def _parent(price=2599, *, branch_price=None, second=False, no_global=False, old_scope=None):
    original, _ = _risk_parent()
    raw = original.draft.model_dump(mode="json")
    raw["levels"]["risk_line_fen"] = price
    if branch_price is not None:
        raw["risk_branches"][0].update(risk_line_fen=branch_price, risk_comparison="LT")
    if second:
        other = raw["risk_branches"][0].copy()
        other["rule_id"] = "second-ordinary-exit"
        raw["risk_branches"].append(other)
    if no_global:
        raw["levels"] = None
        raw["ordinary_rules"] = []
    if old_scope is not None:
        raw["risk_branches"][0]["holding_scope"] = {
            "mode": "BEFORE_TRADE_DATE", "trade_date": old_scope}
    draft = UnifiedPlanDraft.model_validate(raw)
    text, mapping = source_mapping(draft)
    base, parent = _initial(draft, text, mapping, source_id="risk-table-parent")
    assert parent.coverage_complete and not base.issues and draft.to_executable() is not None
    return base, parent


def _parse(text, *, day=_DAY, base=None, parent=None):
    if base is None:
        base, parent = _parent()
    module = importlib.import_module("trade_plan_monitor.ai.source_risk_table_controls")
    source = PreparationSource(source_id="risk-table-current", text=text,
                               effective_trade_date=day)
    return source, module.parse_source_risk_table_controls(source, base, parent)


def _assert_owned(source, result):
    spans = [*result.framing, *result.unresolved,
             *(group.scope_control for group in result.groups)]
    owned = set()
    for span in spans:
        assert source.text[span.start:span.end] == span.excerpt
        positions = set(range(span.start, span.end))
        assert not positions & owned
        owned.update(positions)
    assert {index for index, char in enumerate(source.text) if not char.isspace()} <= owned


def test_real_fourth_table_keeps_scope_and_recovery_role_separate_and_other_rows_unknown():
    original = _ORIGINAL.read_text(encoding="utf-8")
    start = original.index(_HEADER)
    text = original[start:original.index("\n\n", start)]
    assert _row() in text
    base, parent = _parent()

    source, result = _parse(text)

    group, = result.groups
    control, role = group.scope_control, group.structural_reference
    assert control.excerpt == role.excerpt == _row()
    assert (control.start, control.end) == (role.start, role.end)
    assert control.start == text.index(_row())
    assert control.scope_change == "EXISTING_POSITIONS_ONLY" and control.action == "MODIFY"
    assert control.derived_holding_scope.model_dump(mode="json") == {
        "mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}
    assert control.after.model_dump(mode="json", exclude={"holding_scope"}) == (
        base.draft.risk_branches[0].model_dump(mode="json", exclude={"holding_scope"}))
    assert control.parent_assurance_hash == role.parent_assurance_hash == parent.evidence_hash
    assert role.role == "STRUCTURAL_RECOVERY_REFERENCE" and role.price_fen == 2599
    assert role.unit == "FEN" and role.group_id == group.group_id
    assert role.scope_control_id == control.control_id
    assert role.parent_price_path == "levels.risk_line_fen"
    assert not ({"side", "quantity", "stop", "permission", "condition"} & role.model_dump().keys())
    assert control.authority_granted is role.authority_granted is result.authority_granted is False
    assert not ({"status", "complete", "coverage_complete"} & result.model_dump().keys())
    assert len(result.framing) == 2 and len(result.unresolved) == 2
    assert all(row.scope == "UNKNOWN" for row in result.unresolved)
    _assert_owned(source, result)


@pytest.mark.parametrize("price,fen", [("1", 100), ("25.9", 2590), ("25.99", 2599),
                                      ("0.01", 1), ("1234.56", 123456)])
def test_price_is_a_validated_variable_not_a_security_or_document_allowlist(price, fen):
    base, parent = _parent(fen)
    source, result = _parse(_table(price), base=base, parent=parent)
    assert result.groups[0].structural_reference.price_fen == fen
    assert not result.unresolved
    _assert_owned(source, result)


def test_matching_explicit_branch_price_uses_its_actual_parent_path():
    base, parent = _parent(branch_price=2599, no_global=True)
    _, result = _parse(_table(), base=base, parent=parent)
    assert result.groups[0].structural_reference.parent_price_path == (
        "risk_branches[0].risk_line_fen")


def test_prior_scope_is_intersected_without_resetting_its_original_cutoff():
    base, parent = _parent(old_scope="2026-09-30")
    _, result = _parse(_table(), base=base, parent=parent)
    control = result.groups[0].scope_control
    assert control.after == control.before
    assert control.derived_holding_scope.trade_date == date(2026, 9, 30)


@pytest.mark.parametrize("prefix", [
    "如果明天上涨：\n", "如果明天上涨：\n\n", "仅作示例：\n",
    "条件尚未完成\n", "“\n", '"\n', "```\n", "``历史示例。\n",
    "如果明天上涨：\n## 2. 核心价格位置更新\n\n",
    "如果明天上涨：\n---\n## 2. 核心价格位置更新\n\n",
])
def test_unfinished_antecedents_quotes_fences_and_preambles_cannot_release_a_table(prefix):
    source, result = _parse(prefix + _table())
    assert not result.groups and result.unresolved
    _assert_owned(source, result)


@pytest.mark.parametrize("heading", ["## 2. 核心价格位置更新", "## 17. 核心价格位置更新"])
def test_only_registered_closed_heading_is_framing_and_its_exact_text_stays_recorded(heading):
    source, result = _parse(heading + "\n\n" + _table())
    assert len(result.groups) == 1
    assert result.framing[0].kind == "HEADING" and result.framing[0].excerpt == heading
    _assert_owned(source, result)


@pytest.mark.parametrize("text", [
    _table().replace(_HEADER, "| 位置 | 价格 | 含义 |"),
    _table().replace(_SEPARATOR, "|--|---:|---|"),
    _table().replace(_SEPARATOR, "|---|---:|---|---|"),
    _table().replace(_SEPARATOR, "|**---**|---:|---|"),
    _table().replace(_SEPARATOR, ""),
    _table().replace(_HEADER, _HEADER + "\n"),
    _table().replace("**25.99**", "**26.00**"),
    _table().replace(_row(), _row() + " | 仅当换手率超过3% |"),
    _table().replace(_MEANING, _MEANING + "，且全部风险退出必须等待蓝灯"),
    _table().replace("**结构修复门槛**", "**原核心风险线**"),
    _table().replace(_row(), _row() + "未知说明"),
    _row(),
    "## 如果明天收盘站上25.99\n\n" + _table(),
])
def test_wrong_frame_price_mixed_cell_suffix_and_unregistered_heading_stay_unknown(text):
    source, result = _parse(text)
    assert not result.groups and result.unresolved
    _assert_owned(source, result)


@pytest.mark.parametrize("price", ["0", "-25.99", "25.999", "025.99", "NaN", "Infinity",
                                  "9e3", "90071992547409.92"])
def test_invalid_or_non_exact_safe_fen_prices_do_not_become_reference_atoms(price):
    source, result = _parse(_table(price))
    assert not result.groups and result.unresolved
    _assert_owned(source, result)


@pytest.mark.parametrize("kind", ["duplicate", "branch_disagrees_with_global", "missing_day"])
def test_ambiguous_parent_or_unbound_effective_day_never_selects_a_risk(kind):
    base, parent = _parent(second=kind == "duplicate",
                           branch_price=2600 if kind == "branch_disagrees_with_global" else None)
    source, result = _parse(_table(), base=base, parent=parent,
                            day=None if kind == "missing_day" else _DAY)
    assert not result.groups and result.unresolved
    _assert_owned(source, result)


def test_unknown_prefix_suffix_and_extra_rows_survive_without_receiving_the_scope_meaning():
    text = ("观察🙂。\n" + _table() + "\n| 追加条件 | 未定义 | 先等待蓝灯 |\n\n"
            "所有风险退出必须等待蓝灯。")
    source, result = _parse(text)
    assert len(result.groups) == 1
    unknown = "".join(row.excerpt for row in result.unresolved)
    assert "观察🙂。" in unknown and "追加条件" in unknown and "所有风险退出" in unknown
    _assert_owned(source, result)


@pytest.mark.parametrize("quote", ['"', "“", "```"])
def test_an_unfinished_quote_or_fence_in_an_unknown_prior_row_cannot_release_a_scope_row(quote):
    text = "\n".join((_HEADER, _SEPARATOR, f"| 未知 | {quote} | 未结束引述 |", _row()))
    source, result = _parse(text)
    assert not result.groups and result.unresolved
    _assert_owned(source, result)


def test_wrong_parent_or_blocked_parent_does_not_supply_table_scope_evidence():
    base, parent = _parent()
    different, _ = _parent(price=2600)
    with pytest.raises(ValueError, match="parent"):
        _parse(_table(), base=different, parent=parent)
    values = {name: getattr(parent, name) for name in type(parent).model_fields
              if name not in {"status", "evidence_hash"}}
    blocked = SourceCandidateAssurance.build(**(values | dict(issues=(
        CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", message="Independent unresolved parent"),))))
    source, result = _parse(_table(), base=base, parent=blocked)
    assert not result.groups and result.unresolved and result.issues
    _assert_owned(source, result)


def test_the_full_original_never_loses_its_unregistered_paragraphs_or_claims_complete():
    source, result = _parse(_ORIGINAL.read_text(encoding="utf-8"))
    assert result.unresolved and not hasattr(result, "coverage_complete")
    assert result.authority_granted is False
    _assert_owned(source, result)


def test_duplicate_scope_rows_remain_unknown_instead_of_leaving_a_selected_control():
    source, result = _parse(_table() + "\n" + _row())
    assert not result.groups and result.unresolved and result.issues
    _assert_owned(source, result)


def test_source_date_parent_and_both_atom_hashes_are_bound_without_mutation():
    base, parent = _parent()
    before = (base.model_dump_json(), parent.model_dump_json())
    source, first = _parse(_table())
    _, second = _parse(_table(), day=date(2026, 10, 12))
    assert first == _parse(_table())[1]
    assert first.groups[0].group_id != second.groups[0].group_id
    assert first.groups[0].structural_reference.source_binding_hash == source.binding_hash
    assert first.groups[0].scope_control.source_binding_hash == source.binding_hash
    assert before == (base.model_dump_json(), parent.model_dump_json())
    role = first.groups[0].structural_reference
    with pytest.raises(ValueError):
        type(role).model_validate(role.model_dump(mode="json") | {"atom_id": "a" * 64})
    group = first.groups[0]
    with pytest.raises(ValueError):
        type(group).model_validate(group.model_dump(mode="json") | {"group_id": "b" * 64})
    assert role.atom_id != daily_hash("source-risk-control-v1", role.model_dump(mode="json"))


def test_more_than_64_scope_claims_report_an_explicit_limit_before_duplicate_elimination():
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _parse("\n".join((_HEADER, _SEPARATOR, *(_row() for _ in range(65)))))
