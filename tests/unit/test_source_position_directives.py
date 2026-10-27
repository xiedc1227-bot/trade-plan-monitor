"""Closed position directives prove only the cap and preserve the retention tail."""

import importlib

import pytest
from tests.unit.test_source_change_assurance import _parent

from trade_plan_monitor.ai.source_controls import parse_source_controls
from trade_plan_monitor.ai.source_obligations import declarations


def _parse(source):
    module = importlib.import_module("trade_plan_monitor.ai.source_position_directives")
    return module.parse_position_directive(source)


def test_complete_position_directive_keeps_exact_cap_and_retention_codepoint_spans():
    source = " \t调整最大仓位为300股，其余规则保留。\t "
    row = _parse(source)
    assert row is not None and row.value == 300
    assert source[row.start:row.cap_end] == "调整最大仓位为300股，"
    assert source[row.tail_start:row.end] == "其余规则保留。"
    assert row.cap_end == row.tail_start


@pytest.mark.parametrize("cap", ["调整最大仓位为", "仅修改最大仓位", "仅修改最大仓位为"])
@pytest.mark.parametrize("tail", ["其余规则保留。", "其余规则不变。"])
@pytest.mark.parametrize("quantity", [0, 100, 300, 1200, 9_007_199_254_740_991])
def test_only_registered_whole_productions_recognize_the_exact_quantity(cap, tail, quantity):
    source = f"\r\n \t{cap}{quantity}股，{tail}\t\r\n"
    row = _parse(source)
    assert row is not None and type(row.value) is int and row.value == quantity
    declaration, = declarations(source)
    assert (declaration.path, declaration.value) == ("position.max_qty", quantity)
    assert (declaration.start, declaration.end) == (row.start, row.cap_end)
    assert source[declaration.start:declaration.end] == f"{cap}{quantity}股，"
    assert tail not in source[declaration.start:declaration.end]
    # This is source recognition, including zero; native quantity/position
    # validation independently determines whether any candidate is executable.


@pytest.mark.parametrize("text", [
    "如果明天站稳，调整最大仓位为300股，其余规则保留。",
    "如果明天站稳：\n调整最大仓位为300股，其余规则保留。",
    "只在收盘后\n仅修改最大仓位300股，其余规则不变。",
    "不调整最大仓位为300股，其余规则保留。",
    "仅不修改最大仓位300股，其余规则不变。",
    "不是仅修改最大仓位300股，其余规则不变。",
    "示例：调整最大仓位为300股，其余规则保留。",
    "“调整最大仓位为300股，其余规则保留。”",
    "历史记录：‘调整最大仓位为300股，其余规则保留。’",
    "历史记录：\n“调整最大仓位为300股，其余规则保留。”",
    "**调整最大仓位为300股，其余规则保留。**",
    "```\n调整最大仓位为300股，其余规则保留。\n```",
    "调整最大仓位为300股，其余规则保留。新增买入100股。",
    "调整最大仓位为300股，其余规则保留。\n只有蓝灯亮才可以买入。",
    "调整最大仓位为300股，并撤销卖出规则，其余规则保留。",
    "调整最大仓位为300股，其余规则暂不变。",
    "调整最大仓位为300股，其余规则不变但需要额外确认。",
    "调整最大仓位为300股，\n其余规则保留。",
    "调整最大仓位为300股。其余规则保留。",
    "调整最大仓位为300股,其余规则保留。",
    "调整最大仓位为300股，其余规则保留",
    "调整最大仓位为300股。",
    "最大仓位调整为300股，其余规则保留。",
    "调整最大仓位为 300股，其余规则保留。",
])
def test_qualifications_quotes_extra_meaning_and_unregistered_forms_never_prove_cap(text):
    assert _parse(text) is None
    assert declarations(text) == ()


@pytest.mark.parametrize("number", ["0300", "+300", "-300", "300.0", "3e2", "三百",
                                    "300%", "9007199254740992", "1" * 600])
def test_quantity_has_no_rounding_sign_coercion_or_unsafe_integer(number):
    source = f"调整最大仓位为{number}股，其余规则保留。"
    assert _parse(source) is None and declarations(source) == ()


def test_complete_sentence_yields_cap_unknown_and_original_registered_tail_control_separately():
    base, parent = _parent()
    source = " \t仅修改最大仓位300股，其余规则不变。\t "
    row = _parse(source)
    result = parse_source_controls(source, base, parent)
    control, = result.controls
    unresolved, = result.unresolved
    assert (control.start, control.end, control.excerpt) == (
        row.tail_start, row.end, "其余规则不变。")
    assert control.grammar_id == "EXACT_PLAN_CONTROL_V1"
    assert control.action == "RETAIN_UNMENTIONED" and control.parent_assurance_hash == (
        parent.evidence_hash)
    assert (unresolved.start, unresolved.end, unresolved.excerpt) == (
        row.start, row.cap_end, "仅修改最大仓位300股，")
    assert result.authority_granted is False


@pytest.mark.parametrize("source", [
    "如果明天站稳：\n调整最大仓位为300股，其余规则保留。",
    "历史记录：\n“调整最大仓位为300股，其余规则保留。”",
    "```\n调整最大仓位为300股，其余规则保留。\n```",
    "调整最大仓位为300股，其余规则不变但撤销买入。",
])
def test_controls_do_not_split_a_cap_tail_from_pending_quoted_or_unclosed_text(source):
    base, parent = _parent()
    result = parse_source_controls(source, base, parent)
    assert result.controls == () and result.unresolved
    assert all(source[row.start:row.end] == row.excerpt for row in result.unresolved)


def test_unknown_remainder_is_retained_even_when_an_earlier_complete_tail_is_recognized():
    base, parent = _parent()
    source = "调整最大仓位为300股，其余规则保留。\nOnly buy after the blue lantern turns green."
    result = parse_source_controls(source, base, parent)
    assert len(result.controls) == 1 and result.controls[0].excerpt == "其余规则保留。"
    assert any("blue lantern" in row.excerpt for row in result.unresolved)
    assert declarations(source) == ()


def test_existing_scalar_json_source_still_proves_only_its_own_line():
    source = "position.max_qty = 300\n其余规则保留。"
    declaration, = declarations(source)
    assert declaration.path == "position.max_qty" and declaration.value == 300
    assert source[declaration.start:declaration.end] == "position.max_qty = 300"
    assert _parse(source) is None
