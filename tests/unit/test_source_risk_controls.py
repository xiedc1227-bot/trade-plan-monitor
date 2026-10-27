"""Independent risk controls do not grant coverage or discard unknown meanings."""

import importlib
import json
from datetime import date
from functools import lru_cache

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_change_composition_attacks import _initial
from tests.unit.test_source_controls import _variant

from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

_DAY = date(2026, 10, 9)
_ID = "ORDINARY_TECHNICAL"


@lru_cache
def _parent(scope=None, *, explicit_id=None):
    base, parent = _variant("risk")
    if scope is not None or explicit_id is not None:
        raw = base.draft.model_dump(mode="json")
        if scope is not None:
            raw["risk_branches"][0]["holding_scope"] = json.loads(scope)
        if explicit_id is not None:
            raw["risk_branches"][0]["rule_id"] = explicit_id
        draft = UnifiedPlanDraft.model_validate(raw)
        text, mapping = source_mapping(draft)
        base, parent = _initial(draft, text, mapping, source_id="risk-control-parent")
    assert parent.coverage_complete and not base.issues
    return base, parent


def _json(action="MODIFY", *, rule_id=_ID, direction="EXISTING_POSITIONS_ONLY", ordinal=0):
    value = dict(target="risk_branches", rule_id=rule_id, action=action,
                 scope_assessment="PARTIAL_RULE" if action == "MODIFY" else "ENTIRE_RULE")
    if action == "MODIFY":
        value["scope_change"] = direction
    return f"operations[{ordinal}] = " + json.dumps(value, ensure_ascii=False)


def _source(text, *, day=_DAY):
    return PreparationSource(source_id="risk-control-current", text=text,
                             effective_trade_date=day)


def _parse(text, *, base=None, parent=None, day=_DAY):
    if base is None:
        base, parent = _parent()
    module = importlib.import_module("trade_plan_monitor.ai.source_risk_controls")
    source = text if isinstance(text, PreparationSource) else _source(text, day=day)
    return module.parse_source_risk_controls(source, base, parent)


def test_risk_fixture_is_complete_before_the_new_recognizer_runs():
    base, parent = _parent()
    assert len(base.draft.risk_branches) == 2 and parent.coverage_complete
    assert base.draft.risk_branches[0].suspension_confirmation_policy == "RESUME_FIRST_CLOSE"


def test_dedicated_json_partial_control_proves_only_an_exact_intersection():
    base, parent = _parent()
    source = _source(_json())
    result = _parse(source)
    control, = result.controls
    assert not result.unresolved and not result.issues
    assert (control.target, control.rule_id, control.scope, control.action) == (
        "risk_branches", _ID, "RISK", "MODIFY")
    assert control.scope_assessment == "PARTIAL_RULE"
    assert control.scope_change == "EXISTING_POSITIONS_ONLY"
    assert control.derived_holding_scope.model_dump(mode="json") == {
        "mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}
    before = base.draft.risk_branches[0].model_dump(mode="json")
    after = before | {"holding_scope": control.derived_holding_scope.model_dump(mode="json")}
    assert control.before.model_dump(mode="json") == before
    assert control.after.model_dump(mode="json") == after
    assert control.before_hash == daily_hash("source-operation-value-v1", before)
    assert control.after_hash == daily_hash("source-operation-value-v1", after)
    assert control.parent_assurance_hash == parent.evidence_hash
    assert control.base_review_hash == base.evidence_hash
    assert control.source_binding_hash == source.binding_hash
    assert control.source_hash == source.source_hash
    assert control.effective_trade_date == _DAY
    assert source.text[control.start:control.end] == control.excerpt == source.text
    assert control.authority_granted is result.authority_granted is False
    assert not ({"status", "complete", "coverage_complete"} & result.model_dump().keys())


@pytest.mark.parametrize("text,direction", [
    (f"旧持仓继续执行风险规则{_ID}，新开仓位不适用该规则。", "EXISTING_POSITIONS_ONLY"),
    (f"风险规则{_ID}仅适用于旧持仓，不适用于新开仓位。", "EXISTING_POSITIONS_ONLY"),
    (f"Risk rule {_ID} continues for existing lots; exclude new holdings.",
     "EXISTING_POSITIONS_ONLY"),
    (f"新开仓位继续执行风险规则{_ID}，旧持仓不适用该规则。", "NEW_POSITIONS_ONLY"),
    (f"Risk rule {_ID} continues for new holdings; exclude existing lots.",
     "NEW_POSITIONS_ONLY"),
])
def test_explicit_identity_natural_controls_preserve_the_complete_risk(text, direction):
    base, _ = _parent()
    control, = _parse(text).controls
    assert control.action == "MODIFY" and control.scope_change == direction
    assert control.after.model_dump(mode="json", exclude={"holding_scope"}) == (
        base.draft.risk_branches[0].model_dump(mode="json", exclude={"holding_scope"}))
    assert control.derived_holding_scope.mode == (
        "BEFORE_TRADE_DATE" if direction == "EXISTING_POSITIONS_ONLY" else "FROM_TRADE_DATE")


@pytest.mark.parametrize("text,action", [
    (_json("REVOKE"), "REVOKE"), (_json("RETAIN"), "RETAIN"),
    (f"对全部新旧持仓一并废止风险规则{_ID}，今后不再执行该规则。", "REVOKE"),
    (f"Revoke risk rule {_ID} for all existing and future holdings.", "REVOKE"),
    (f"保留风险规则{_ID}，新旧持仓均按原规则执行。", "RETAIN"),
    (f"Retain risk rule {_ID} for all existing and future holdings.", "RETAIN"),
    (f"Do not revoke risk rule {_ID} for all existing and future holdings.", "RETAIN"),
])
def test_only_explicit_complete_cohort_control_can_cancel_or_retain(text, action):
    control, = _parse(text, day=None).controls
    assert control.action == action and control.scope_assessment == "ENTIRE_RULE"
    assert control.scope_change is control.derived_holding_scope is None
    if action == "REVOKE":
        assert control.after is None
        assert control.after_hash == daily_hash("source-operation-value-v1", None)
    else:
        assert control.before == control.after and control.before_hash == control.after_hash


@pytest.mark.parametrize("old,direction,expected", [
    ({"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-09-30"},
     "EXISTING_POSITIONS_ONLY", {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-09-30"}),
    ({"mode": "FROM_TRADE_DATE", "trade_date": "2026-09-30"},
     "EXISTING_POSITIONS_ONLY", {"mode": "FROM_TRADE_DATE", "trade_date": "2026-09-30",
                                 "end_trade_date": "2026-10-09"}),
    ({"mode": "FROM_TRADE_DATE", "trade_date": "2026-09-30", "end_trade_date": "2026-10-15"},
     "NEW_POSITIONS_ONLY", {"mode": "FROM_TRADE_DATE", "trade_date": "2026-10-09",
                            "end_trade_date": "2026-10-15"}),
])
def test_intersection_never_broadens_resets_or_discards_an_existing_window(
    old, direction, expected,
):
    base, parent = _parent(json.dumps(old))
    control, = _parse(_json(direction=direction), base=base, parent=parent).controls
    assert control.derived_holding_scope.model_dump(mode="json") == expected
    assert control.action == "MODIFY"  # source intent; actual no-op classification is downstream
    if old == expected:
        assert control.before == control.after and control.before_hash == control.after_hash


def test_empty_intersection_stays_unresolved_and_never_becomes_revocation():
    base, parent = _parent('{"mode":"BEFORE_TRADE_DATE","trade_date":"2026-09-30"}')
    result = _parse(_json(direction="NEW_POSITIONS_ONLY"), base=base, parent=parent)
    assert not result.controls and result.unresolved and result.issues
    assert all(row.scope == "UNKNOWN" for row in result.unresolved)


@pytest.mark.parametrize("text", [
    f"撤销规则{_ID}。", f"Revoke risk rule {_ID}.",
    f"如果明天上涨，Revoke risk rule {_ID} for all existing and future holdings.",
    f"如果明天上涨：\n{_json('REVOKE')}",
    f"仅作示例：\n{_json('REVOKE')}",
    f"历史记录：“Revoke risk rule {_ID} for all existing and future holdings.”",
    f"```\n{_json('REVOKE')}\n```",
    f"只取消风险规则{_ID}对新仓的适用。",
    "旧仓止损保留，新仓排除。", "当前没有持仓，不用卖出。",
    "原风险线25.99现在转为压力。",
    ("| **结构修复门槛** | **25.99** | 已失守的原核心风险线；"
     "现在用于判断旧结构是否被重新收复，而不是给新仓位直接设止损 |"),
    f"风险规则{_ID}仅适用于旧持仓，但也必须等蓝灯。",
    f"旧持仓继续执行风险规则{_ID}，新开仓位不适用该规则且换手率必须超过3%。",
    f'operations[0] = {{"target":"risk_branches","rule_id":"{_ID}","action":"REVOKE"}}',
    _json().replace('"MODIFY"', '"REVOKE"'),
    _json().replace('"EXISTING_POSITIONS_ONLY"', '"ALL"'),
    _json().replace('"rule_id": "ORDINARY_TECHNICAL"', '"rule_id": "absent"'),
    _json().replace('operations[0]', 'operations[64]'),
    _json().replace('operations[0]', 'operations[00]'),
    _json() + " extra", _json()[:-1] + ', "extra": null}',
    _json()[:-1] + ', "action": "MODIFY"}',
    _json().replace('"rule_id": "ORDINARY_TECHNICAL"', '"rule_id": true'),
])
def test_unknown_qualified_quoted_partial_and_wrong_shape_controls_keep_exact_unknown_spans(text):
    result = _parse(text)
    assert not result.controls and result.unresolved
    for row in result.unresolved:
        assert row.scope == "UNKNOWN" and text[row.start:row.end] == row.excerpt
        assert len(row.excerpt) <= 512


def test_unknown_suffix_remains_blocking_even_after_a_recognized_complete_control():
    text = _json() + "\n所有风险退出必须先等待蓝灯。"
    result = _parse(text)
    assert len(result.controls) == len(result.unresolved) == 1
    assert result.unresolved[0].excerpt == "所有风险退出必须先等待蓝灯。"
    assert result.unresolved[0].scope == "UNKNOWN"


@pytest.mark.parametrize("text", [
    _json() + "\n" + _json("REVOKE", ordinal=1),
    _json() + "\n" + _json(ordinal=1),
    _json() + "\n" + _json(direction="NEW_POSITIONS_ONLY", ordinal=1),
    _json() + "\n" + _json("RETAIN", rule_id="SEVERE_TECHNICAL"),
])
def test_duplicate_targets_or_ordinals_leave_no_actionable_control(text):
    result = _parse(text)
    assert not result.controls and len(result.unresolved) == 2 and result.issues
    assert result.issues[0].code == "SOURCE_RELATION_MISMATCH"


def test_source_binding_and_effective_day_are_exact_dependencies_and_inputs_are_unchanged():
    base, parent = _parent()
    source = _source(_json())
    before = (source.model_dump_json(), base.model_dump_json(), parent.model_dump_json())
    first = _parse(source)
    assert first == _parse(source)
    later = _parse(source.model_copy(update={"effective_trade_date": date(2026, 10, 12)}))
    assert first.controls[0].source_binding_hash != later.controls[0].source_binding_hash
    assert first.controls[0].control_id != later.controls[0].control_id
    assert later.controls[0].derived_holding_scope.trade_date == date(2026, 10, 12)
    assert before == (source.model_dump_json(), base.model_dump_json(), parent.model_dump_json())


def test_missing_partial_effective_day_is_unknown_not_a_guessed_cutoff():
    result = _parse(_json(), day=None)
    assert not result.controls and result.unresolved and result.issues


def test_explicit_stable_identity_does_not_fall_back_to_the_kind_label():
    base, parent = _parent(explicit_id="old-exit.v2")
    result = _parse(_json(rule_id="old-exit.v2"), base=base, parent=parent)
    assert result.controls[0].rule_id == "old-exit.v2"
    assert not _parse(_json(), base=base, parent=parent).controls


def test_wrong_parent_binding_is_rejected_and_blocked_parent_cannot_supply_control_authority():
    base, parent = _parent()
    other, _ = _parent(explicit_id="another-exit")
    with pytest.raises(ValueError, match="parent"):
        _parse(_json(), base=other, parent=parent)
    module = importlib.import_module("trade_plan_monitor.ai.source_candidate_models")
    blocked = module.SourceCandidateAssurance.build(**{
        **{name: getattr(parent, name) for name in type(parent).model_fields
           if name not in {"status", "evidence_hash"}},
        "issues": (CoverageIssue(code="SOURCE_COVERAGE_REQUIRED", message="Unproven parent"),),
    })
    result = _parse(_json(), base=base, parent=blocked)
    assert not result.controls and result.unresolved and result.issues


def test_typed_controls_reject_self_hash_tampering_and_any_non_scope_partial_write():
    result = _parse(_json())
    control, = result.controls
    with pytest.raises(ValueError):
        type(result).model_validate(result.model_dump(mode="json") | {"evidence_hash": "a" * 64})
    with pytest.raises(ValueError):
        type(control).model_validate(control.model_dump(mode="json") | {"before_hash": "b" * 64})
    values = {name: getattr(control, name) for name in type(control).model_fields
              if name != "control_id"}
    after = control.after.model_copy(update={"target_tactical_qty": 100})
    with pytest.raises(ValueError):
        type(control).build(**(values | {"after": after,
            "after_hash": daily_hash("source-operation-value-v1", after.model_dump(mode="json"))}))
    with pytest.raises(ValueError):
        type(control).build(**(values | {"authority_granted": True}))


def test_unicode_positions_and_long_unknowns_are_never_truncated():
    text = "观察🙂。\n  " + _json() + "\n" + "甲" * 1200
    result = _parse(text)
    control, = result.controls
    assert control.start == text.index("operations[")
    assert text[control.start:control.end] == control.excerpt
    assert "".join(row.excerpt for row in result.unresolved) == "观察🙂。" + "甲" * 1200
    assert all(len(row.excerpt) <= 512 for row in result.unresolved)


def test_too_many_recognized_control_claims_fail_explicitly_before_conflict_elimination():
    text = "\n".join(_json(ordinal=n % 64) for n in range(65))
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _parse(text)


def test_too_many_unknown_units_fail_explicitly_without_truncation():
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _parse("?" * 4097)


def test_a_derivation_proof_size_limit_is_not_reclassified_as_an_unknown_scope(monkeypatch):
    module = importlib.import_module("trade_plan_monitor.ai.source_risk_control_models")
    original = module.SourceRiskControl.build.__func__

    def limited_build(cls, **values):
        with monkeypatch.context() as limited:
            limited.setattr(module, "MAX_PROOF_BYTES", 32)
            return original(cls, **values)

    monkeypatch.setattr(module.SourceRiskControl, "build", classmethod(limited_build))
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _parse(_json())
