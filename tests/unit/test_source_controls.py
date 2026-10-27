"""Source controls are complete original statements, independent of AI proposals."""

import importlib
import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_change_assurance import _NOW
from tests.unit.test_source_change_attacks import _two_rule_parent
from tests.unit.test_source_change_composition_attacks import _initial
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def _parse(text, base=None, parent=None):
    if base is None:
        base, parent = _two_rule_parent()
    module = importlib.import_module("trade_plan_monitor.ai.source_controls")
    return module.parse_source_controls(text, base, parent)


def test_exact_three_key_json_resolves_the_stated_prior_rule_without_a_model_operation():
    base, parent = _two_rule_parent()
    text = 'operations[7] = {"target":"ordinary_rules","rule_id":"low-buy","action":"REVOKE"}'

    result = _parse(text, base, parent)

    assert result.source_hash == scope_hash(text)
    assert result.parent_assurance_hash == parent.evidence_hash
    assert result.base_review_hash == base.evidence_hash
    assert result.unresolved == () and result.issues == ()
    control, = result.controls
    assert (control.action, control.target, control.rule_id, control.scope) == (
        "REVOKE", "ordinary_rules", "low-buy", "BUY")
    assert (control.start, control.end, control.excerpt) == (0, len(text), text)
    assert control.source_hash == scope_hash(text)
    assert control.parent_assurance_hash == parent.evidence_hash
    assert control.before_hash == daily_hash("source-operation-value-v1",
        base.draft.ordinary_rules[0].model_dump(mode="json"))
    assert control.control_id and result.evidence_hash
    assert result.authority_granted is False
    assert "draft" not in json.loads(text.split(" = ", 1)[1])


def _variant(kind):
    base, _ = _two_rule_parent()
    raw = base.draft.model_dump(mode="json")
    if kind in {"zone", "display_zone"}:
        raw["levels"] = dict(low_buy=dict(low_fen=2640, high_fen=2670,
            include_low=True, include_high=True), pressure=None,
            risk_line_fen=None, risk_comparison=None)
        raw["ordinary_rules"][0]["zone"] = "LOW_BUY" if kind == "zone" else None
    elif kind == "two_buys":
        first, second = raw["ordinary_rules"]
        first["independent_signal"] = {"mode": "ONCE_PER_RULE"}
        second.update(side="BUY", independent_signal={"mode": "AFTER_RULE_COMPLETED",
            "prior_rule_id": first["rule_id"]})
    elif kind == "alert":
        raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="old-alert",
            condition=dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=4000),
            confirmation=dict(kind="COMPLETED_BAR_CLOSE", timeframe_minutes=5))]
    elif kind == "risk":
        raw = UnifiedTradePlan.model_validate(unified_payload()).model_dump(mode="json")
    else:
        raise AssertionError("unknown predecessor fixture")
    draft = UnifiedPlanDraft.model_validate(raw)
    text, mapping = source_mapping(draft)
    base, parent = _initial(draft, text, mapping, source_id=f"control-parent-{kind}")
    assert base.draft.to_executable() is not None
    return base, parent


@pytest.mark.parametrize("text,action,side", [
    ("取消原来的买入规则。", "REVOKE", "BUY"),
    ("取消原买入指令。", "REVOKE", "BUY"),
    ("撤下原来的入场指令。", "REVOKE", "BUY"),
    ("此前那笔买单就此作废。", "REVOKE", "BUY"),
    ("上一版的买入安排就此作废。", "REVOKE", "BUY"),
    ("取消原来的卖出规则。", "REVOKE", "SELL"),
    ("不要撤销原买入指令。", "RETAIN", "BUY"),
    ("旧入场安排照常有效。", "RETAIN", "BUY"),
    ("Revoke rule low-buy.", "REVOKE", "BUY"),
    ("Do not revoke rule low-buy.", "RETAIN", "BUY"),
    ("保留规则remaining-sell。", "RETAIN", "SELL"),
])
def test_registered_complete_business_and_identity_controls_are_independent_of_ai_labels(
    text, action, side,
):
    result = _parse(text)
    control, = result.controls
    assert (control.action, control.scope) == (action, side)
    assert control.target == "ordinary_rules"
    assert result.unresolved == () and result.issues == ()


@pytest.mark.parametrize("text", [
    "今日没有新增指令。", "今日休市，没有新增指令。", "No new instructions today.",
])
def test_no_new_instructions_is_a_plan_control_not_calendar_or_trading_authority(text):
    result = _parse(text)
    control, = result.controls
    assert (control.action, control.target, control.rule_id, control.scope) == (
        "NO_NEW_INSTRUCTIONS", "plan", None, "PLAN")
    assert result.unresolved == () and result.authority_granted is False


@pytest.mark.parametrize("text", [
    "如果收盘跌破25.99，取消原来的买入规则。",
    "假设取消原来的买入规则。",
    "只取消原买入规则的数量部分。",
    "不要取消原来的卖出规则。",
    "取消原来的买入规则但跌破30元必须卖出200股。",
    "取消原来的买入规则，新的条件以后再说。",
    '历史记录：“取消原来的买入规则。”',
    "取消其中一条规则。",
    "最后100股继续保留。",
    "不把低吸区继续往下移动。",
    "取消风控对新仓的适用，不影响老仓。",
    "如果收盘跌破25.99，" + "甲" * 520 + "取消原来的买入规则。",
    '历史记录：“昨天没有决定。取消原来的买入规则。”',
    "如果明天收盘跌破25.99：\n取消原来的买入规则。",
    '仅作示例：\noperations[0] = {"target":"ordinary_rules",'
    '"rule_id":"low-buy","action":"REVOKE"}',
    "``历史示例。取消原来的买入规则。``",
    "```\n取消原来的买入规则。\n```",
])
def test_conditional_partial_quoted_or_extra_meanings_never_become_whole_rule_cancellation(text):
    result = _parse(text)
    assert result.controls == () and result.unresolved
    assert all(span.scope == "UNKNOWN" and len(span.excerpt) <= 512 for span in result.unresolved)
    assert all(text[span.start:span.end] == span.excerpt for span in result.unresolved)


@pytest.mark.parametrize("change", [
    {"side": "SELL"}, {"scope_assessment": "ENTIRE_RULE"},
    {"action": "MODIFY"}, {"rule_id": "absent"}, {"target": "missing"},
    {"action": []}, {"target": {}}, {"rule_id": []},
])
def test_json_control_requires_exact_three_keys_and_supported_existing_identity(change):
    raw = dict(target="ordinary_rules", rule_id="low-buy", action="REVOKE") | change
    text = "operations[0] = " + json.dumps(raw)
    result = _parse(text)
    assert not result.controls and result.unresolved


@pytest.mark.parametrize("text", [
    'operations[0] = {"target":"ordinary_rules","rule_id":"low-buy","action":"REVOKE",'
    '"action":"RETAIN"}',
    'operations[0] = {"target":"ordinary_rules","rule_id":"low-buy","action":"REVOKE"} extra',
    'operations[0].action = "REVOKE"',
    'operations[64] = {"target":"ordinary_rules","rule_id":"low-buy","action":"REVOKE"}',
])
def test_duplicate_keys_trailing_text_partial_fields_and_unbounded_ordinals_stay_unknown(text):
    result = _parse(text)
    assert not result.controls and result.unresolved


def test_exact_source_zone_can_identify_only_an_actual_unique_low_buy_rule():
    base, parent = _variant("zone")
    result = _parse("原26.40—26.70低吸计划正式取消。", base, parent)
    control, = result.controls
    assert control.rule_id == "low-buy" and control.scope == "BUY"
    assert control.before_hash == daily_hash("source-operation-value-v1",
        base.draft.ordinary_rules[0].model_dump(mode="json"))


@pytest.mark.parametrize("kind,text", [
    ("zone", "原26.50—26.70低吸计划正式取消。"),
    ("zone", "原126.40—26.70低吸计划正式取消。"),
    ("zone", "原26.401—26.70低吸计划正式取消。"),
    ("display_zone", "原26.40—26.70低吸计划正式取消。"),
    ("two_buys", "取消原来的买入规则。"),
])
def test_display_only_wrong_zone_and_multiple_buy_tranches_do_not_identify_a_whole_rule(kind, text):
    base, parent = _variant(kind)
    result = _parse(text, base, parent)
    assert result.controls == () and result.unresolved


def test_risk_scope_is_not_invented_from_a_three_key_json_or_business_label():
    base, parent = _variant("risk")
    kind = base.draft.risk_branches[0].kind
    for text in [f'operations[0] = {{"target":"risk_branches","rule_id":"{kind}",'
                 '"action":"REVOKE"}', f"撤销规则{kind}。"]:
        result = _parse(text, base, parent)
        assert not result.controls and result.unresolved


def test_named_alert_and_scalar_retention_use_their_actual_prior_scope_and_value():
    base, parent = _variant("alert")
    result = _parse('operations[0] = {"target":"alert_rules","rule_id":"old-alert",'
                    '"action":"REVOKE"}', base, parent)
    control, = result.controls
    assert control.scope == "ALERT" and control.target == "alert_rules"
    retained = _parse('operations[1] = {"target":"position","rule_id":null,"action":"RETAIN"}')
    assert retained.controls[0].scope == "PLAN"
    assert not _parse('operations[1] = {"target":"position","rule_id":null,'
                     '"action":"REVOKE"}').controls


def test_duplicate_or_contradictory_complete_statements_do_not_leave_an_actionable_control():
    for text in ["取消原来的买入规则。不要撤销原买入指令。",
                 "取消原来的买入规则。取消原来的买入规则。",
                 "今日没有新增指令。取消原来的买入规则。"]:
        result = _parse(text)
        assert result.controls == () and result.unresolved and result.issues


def test_a_repeated_source_ordinal_cannot_declare_two_different_control_objects():
    text = ('operations[0] = {"target":"ordinary_rules","rule_id":"low-buy",'
            '"action":"REVOKE"}\noperations[0] = {"target":"ordinary_rules",'
            '"rule_id":"remaining-sell","action":"RETAIN"}')
    result = _parse(text)
    assert result.controls == () and len(result.unresolved) == 2 and result.issues


def test_reversible_whole_statement_formatting_preserves_exact_unicode_codepoint_spans():
    text = "观察🙂。\n  **取消原来的买入规则。**"
    result = _parse(text)
    control, = result.controls
    assert control.start == text.index("**")
    assert control.excerpt == "**取消原来的买入规则。**"
    assert text[control.start:control.end] == control.excerpt
    assert result.unresolved[0].excerpt == "观察🙂。"


def test_metadata_changes_cannot_rewrite_original_text_identity_or_grant_authority():
    text = "不要撤销原买入指令。"
    base, parent = _two_rule_parent()
    source = PreparationSource(source_id="control-source", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    result = _parse(source, base, parent)
    assert result == _parse(text, base, parent)
    before = (base.model_dump_json(), parent.model_dump_json())
    assert _parse(source, base, parent) == result
    assert (base.model_dump_json(), parent.model_dump_json()) == before


def test_wrong_parent_and_tampered_control_or_analysis_hash_are_rejected():
    base, parent = _two_rule_parent()
    _, different = _variant("zone")
    with pytest.raises(ValueError):
        _parse("取消原来的买入规则。", base, different)
    result = _parse("取消原来的买入规则。", base, parent)
    with pytest.raises(ValueError):
        type(result).model_validate(result.model_dump(mode="json") | {"evidence_hash": "b" * 64})
    control = result.controls[0]
    with pytest.raises(ValueError):
        type(control).model_validate(control.model_dump(mode="json") | {"before_hash": "c" * 64})
