"""Full replacement is an exact PLAN control, never complete after-image proof."""

import pytest
from tests.unit.test_source_change_assurance import _parent

from trade_plan_monitor.ai.source_control_models import SourceControl
from trade_plan_monitor.ai.source_controls import parse_source_controls
from trade_plan_monitor.domain.daily_hash import daily_hash


def test_complete_full_replacement_sentence_has_exact_parent_bound_plan_control():
    base, parent = _parent()
    text = "完整替换此前计划。"
    parsed = parse_source_controls(text, base, parent)
    control, = parsed.controls
    assert parsed.unresolved == () and parsed.issues == ()
    assert (control.action, control.target, control.rule_id, control.scope) == (
        "FULL_REPLACEMENT", "plan", None, "PLAN")
    assert (control.start, control.end, control.excerpt) == (0, len(text), text)
    assert control.parent_assurance_hash == parent.evidence_hash
    assert control.before_hash == daily_hash("source-operation-value-v1",
                                             base.draft.model_dump(mode="json"))
    assert parsed.authority_granted is False and control.authority_granted is False


@pytest.mark.parametrize("text", [
    "不是完整替换此前计划。", "假设完整替换此前计划。",
    "如果明天站稳，完整替换此前计划。", "如果明天站稳：\n完整替换此前计划。",
    "“完整替换此前计划。”", "历史记录：\n“完整替换此前计划。”",
    "```\n完整替换此前计划。\n```", "仅替换此前计划的买入数量。",
    "完整替换此前计划但保留原风险。", "完整替换此前计划的部分规则。",
    "Completely replace the previous plan.",
])
def test_qualified_quoted_partial_or_unregistered_forms_cannot_be_full_replacement(text):
    base, parent = _parent()
    parsed = parse_source_controls(text, base, parent)
    assert not parsed.controls and parsed.unresolved


@pytest.mark.parametrize("target,rule_id,scope", [
    ("ordinary_rules", "buy", "BUY"), ("alert_rules", "alert", "ALERT"),
    ("position", None, "PLAN"), ("plan", "invented", "PLAN"), ("plan", None, "SELL"),
])
def test_full_replacement_action_is_closed_to_parent_bound_whole_plan(target, rule_id, scope):
    base, parent = _parent()
    control, = parse_source_controls("完整替换此前计划。", base, parent).controls
    values = control.model_dump(mode="python", exclude={"control_id"}) | {
        "target": target, "rule_id": rule_id, "scope": scope}
    with pytest.raises(ValueError):
        SourceControl.build(**values)


@pytest.mark.parametrize("tail", ["其余规则保留。", "今日没有新增指令。"])
def test_contradictory_plan_retention_controls_are_not_silently_consumed(tail):
    base, parent = _parent()
    source = "完整替换此前计划。\n" + tail
    parsed = parse_source_controls(source, base, parent)
    assert parsed.controls == () and parsed.unresolved
    assert any(row.code == "SOURCE_RELATION_MISMATCH" for row in parsed.issues)


def test_unknown_extra_sentence_survives_recognition_of_the_exact_scope_sentence():
    base, parent = _parent()
    source = "完整替换此前计划。\nOnly buy after the blue lantern turns green."
    parsed = parse_source_controls(source, base, parent)
    control, = parsed.controls
    assert control.action == "FULL_REPLACEMENT"
    assert any("blue lantern" in row.excerpt for row in parsed.unresolved)
    assert parsed.authority_granted is False
