"""Registered whole-source controls must match the actual stable-rule operation."""

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import _NOW, _assemble
from tests.unit.test_source_change_attacks import _two_rule_parent

from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_change_composition import assess_change_current
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource


def _case(text, *, action="REVOKE", rule_id="low-buy", no_operations=False):
    base, parent = _two_rule_parent()
    _, patch = delta(text, target="ordinary_rules", rule_id=rule_id, action=action)
    patch = patch.model_copy(update={"clauses": tuple(row.model_copy(update={
        "meaning": "COMMENTARY", "disposition": "BACKGROUND", "paths": (),
    }) for row in patch.clauses), "operations": () if no_operations else patch.operations})
    source = PreparationSource(source_id="source-control-change", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    context = context_from_review(base, parent.binding.candidate_hash)
    case = _assemble(base, parent, source, patch, context)
    assert case[2].review.issues == ()
    return case


def _assess(case):
    source, output, materialized, inputs, context, base, parent, binding = case
    return assess_change_current(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding, prefix=(
            PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash),))


@pytest.mark.parametrize("text", [
    "取消原来的买入规则。",
    'operations[7] = {"target":"ordinary_rules","rule_id":"low-buy","action":"REVOKE"}',
])
def test_complete_registered_cancellation_proves_only_the_exact_removed_rule(text):
    case = _case(text)
    result = _assess(case)
    assert result.coverage_complete is True and result.authority_granted is False
    operation = next(row for row in result.source_assessment.operations if row.action == "REVOKE")
    assert operation.rule_id == "low-buy" and operation.obligation_ids
    assert operation.changed_paths
    assert all(row.source_id == case[6].binding.source_id for row in result.owners)
    assert {row.path for row in result.owners if row.path.startswith("ordinary_rules[")} == {
        row.path for row in result.owners if row.path.startswith("ordinary_rules[0].")}


@pytest.mark.parametrize("action,rule_id", [("RETAIN", "low-buy"), ("REVOKE", "remaining-sell")])
def test_recognized_source_cancellation_cannot_be_ignored_or_redirected(action, rule_id):
    result = _assess(_case("取消原来的买入规则。", action=action, rule_id=rule_id))
    assert result.status == "BLOCKED" and result.source_assessment.issues


@pytest.mark.parametrize("text", [
    "如果明天跌破才取消原来的买入规则。",
    "仅对新仓取消原来的买入规则。",
    "示例：取消原来的买入规则。",
])
def test_qualified_or_example_cancellation_never_authorizes_unconditional_removal(text):
    result = _assess(_case(text))
    assert result.status == "BLOCKED"
    assert any(row.scope == "UNKNOWN" for row in result.source_assessment.obligations)


@pytest.mark.parametrize("text,no_operations", [
    ("不要撤销原买入指令。", False), ("今日没有新增指令。", True),
])
def test_registered_retention_and_no_new_instruction_preserve_complete_parent(text, no_operations):
    case = _case(text, action="RETAIN", no_operations=no_operations)
    result = _assess(case)
    assert result.coverage_complete is True
    assert all(row.action == "RETAIN" and not row.changed_paths
               for row in result.source_assessment.operations)
    assert {row.source_id for row in result.owners} == {case[6].binding.source_id}
    assert result.current_automatic_fidelity_verified is False
