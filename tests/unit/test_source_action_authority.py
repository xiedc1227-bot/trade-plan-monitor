"""Risk policy comparison is exact and cannot itself establish a stored grant."""

import importlib
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from tests.unit.test_source_risk_controls import _parent

from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.state.daily_state_models import DailyRiskState
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError


def _severe_evidence(branch):
    facts = [dict(id="actual-" + child.fact_kind, kind=child.fact_kind, verified=True,
        trade_date="2026-10-26", available_at="2026-10-26T15:00:00+08:00",
        verified_at="2026-10-26T15:00:00+08:00", satisfied=True)
        for child in branch.condition.conditions]
    evidence = evaluate_unified_condition(branch.condition, None, facts=facts,
        target=datetime(2026, 10, 26, 15, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert evidence.outcome == "SATISFIED" and len(evidence.children) == 2
    return evidence.model_dump(mode="json")


def _severe_policy():
    plan, _, _ = _policy()
    branch = plan.risk_branches[1]
    payload = dict(kind=branch.kind, priority=branch.priority, involves_core=branch.involves_core,
        target_core_qty=branch.target_core_qty, target_tactical_qty=branch.target_tactical_qty,
        scope_evidence=branch.scope_evidence, status="CONFIRMED")
    return plan, branch, payload


def _policy():
    base, _ = _parent()
    plan = base.draft.to_executable()
    branch = plan.risk_branches[0]
    payload = dict(kind=branch.kind, priority=branch.priority,
        target_core_qty=branch.target_core_qty, target_tactical_qty=branch.target_tactical_qty,
        involves_core=branch.involves_core, scope_evidence=branch.scope_evidence,
        risk_line_fen=plan.levels.risk_line_fen, risk_comparison=plan.levels.risk_comparison,
        suspension_confirmation_policy=branch.suspension_confirmation_policy,
        status="CONFIRMED", confirmed_trade_date="2026-10-26")
    return plan, branch, payload


def _matches(plan, branch, payload):
    module = importlib.import_module("trade_plan_monitor.state.source_action_authority")
    return module._risk_policy_matches(plan, branch, payload)


def test_complete_exact_ordinary_risk_policy_matches_without_granting_an_action():
    plan, branch, payload = _policy()
    assert _matches(plan, branch, payload) is True


@pytest.mark.parametrize("change", [
    {"kind": "SEVERE_TECHNICAL"}, {"rule_id": "another-risk"}, {"priority": 2},
    {"target_core_qty": 100}, {"target_tactical_qty": 100}, {"involves_core": False},
    {"scope_evidence": "A different original policy"}, {"risk_line_fen": 2599},
    {"risk_comparison": "LTE"}, {"suspension_confirmation_policy": "RESTART_ADJACENT_PAIR"},
    {"holding_scope": {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}},
])
def test_same_kind_or_confirmation_status_cannot_hide_a_changed_policy(change):
    plan, branch, payload = _policy()
    assert _matches(plan, branch, payload | change) is False


@pytest.mark.parametrize("field", ["risk_line_fen", "risk_comparison",
                                   "suspension_confirmation_policy", "target_core_qty"])
def test_missing_policy_fields_are_uncertain_not_inferred_from_confirmed_status(field):
    plan, branch, payload = _policy()
    del payload[field]
    assert _matches(plan, branch, payload) is False


def test_narrow_scope_and_explicit_branch_price_must_be_preserved_exactly():
    plan, branch, payload = _policy()
    scope = {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}
    branch = branch.model_copy(update=dict(rule_id="old-only", holding_scope=scope,
                                          risk_line_fen=2599, risk_comparison="LT"))
    payload = payload | dict(rule_id="old-only", holding_scope=scope,
                              risk_line_fen=2599, risk_comparison="LT")
    assert _matches(plan, branch, payload)
    assert not _matches(plan, branch, payload | {"holding_scope": None})


def test_present_severe_condition_evidence_cannot_prove_another_branch_expression():
    plan, branch, payload = _severe_policy()
    payload["technical_evidence"] = [_severe_evidence(branch)]
    assert _matches(plan, branch, payload)
    changed = deepcopy(payload)
    changed["technical_evidence"][0]["condition"]["type"] = "ANY"
    assert not _matches(plan, branch, changed)


@pytest.mark.parametrize("evidence", [None, [], ()])
def test_severe_missing_evidence_cannot_be_confirmed_by_an_empty_all(evidence):
    plan, branch, payload = _severe_policy()
    if evidence is not None:
        payload["technical_evidence"] = evidence
    assert not _matches(plan, branch, payload)


def test_severe_root_sat_marker_without_complete_children_is_not_condition_evidence():
    plan, branch, payload = _severe_policy()
    payload["technical_evidence"] = [dict(outcome="SATISFIED",
                                        condition=branch.condition.model_dump(mode="json"))]
    assert not _matches(plan, branch, payload)


@pytest.mark.parametrize("mutation", ["missing", "condition", "outcome"])
def test_severe_inconsistent_children_cannot_donate_a_complete_sat_marker(mutation):
    plan, branch, payload = _severe_policy()
    proof = _severe_evidence(branch)
    if mutation == "missing":
        proof["children"].pop()
    elif mutation == "condition":
        proof["children"][0]["condition"] = proof["children"][1]["condition"]
    else:
        proof["children"][0]["outcome"] = "UNSATISFIED"
    payload["technical_evidence"] = [proof]
    assert not _matches(plan, branch, payload)


def test_complete_severe_any_tree_may_have_a_decisive_sat_child_and_a_missing_child():
    plan, branch, payload = _severe_policy()
    condition = branch.condition.model_dump(mode="json") | {"type": "ANY"}
    branch = branch.model_copy(update={"condition": condition})
    fact = dict(id="actual-structure", kind=branch.condition.conditions[0].fact_kind,
        verified=True, trade_date="2026-10-26", available_at="2026-10-26T15:00:00+08:00",
        verified_at="2026-10-26T15:00:00+08:00", satisfied=True)
    evidence = evaluate_unified_condition(branch.condition, None, facts=[fact],
        target=datetime(2026, 10, 26, 15, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert evidence.outcome == "SATISFIED"
    assert [row.outcome for row in evidence.children] == ["SATISFIED", "MISSING_INPUT"]
    payload["technical_evidence"] = [evidence.model_dump(mode="json")]
    assert _matches(plan, branch, payload)


def test_explicit_coverage_resource_limit_is_preserved_in_the_historical_risk_diagnostic(
    monkeypatch,
):
    _, parent = _parent()
    proof = parent.source_assessment
    values = proof.model_dump(mode="python", exclude={"evidence_hash", "status"})
    values["obligations"] = proof.obligations
    values["issues"] = (*proof.issues, CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED",
        path="source", message="The independent source proof exceeds its declared limit."))
    limited = CoverageAssessment.build(**values)
    assert not limited.coverage_complete
    module = importlib.import_module("trade_plan_monitor.state.source_action_authority")
    # This only injects a negative reader result for diagnostic classification.
    monkeypatch.setattr(module, "read_version_coverage", lambda *_: SimpleNamespace(
        assessment=limited))
    with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        module._risk_meaning_known(None, None)


def test_restart_adjacent_pair_requires_its_second_session_to_be_the_actual_confirmation():
    _, _, raw = _policy()
    raw.update(evidence_ids=[], earliest_execution_date="2026-10-27", blockers=[],
        breach_trade_date="2026-10-22", second_close_date="2026-10-26",
        suspension_confirmation_policy="RESTART_ADJACENT_PAIR")
    state = DailyRiskState.model_validate(raw)
    instant = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    module = importlib.import_module("trade_plan_monitor.state.source_action_authority")
    assert module._risk_dates_match(state, instant)
    earlier_second = DailyRiskState.model_validate(raw | dict(second_close_date="2026-10-23"))
    assert not module._risk_dates_match(earlier_second, instant)
