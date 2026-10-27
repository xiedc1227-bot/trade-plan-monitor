"""Actual raw update replay must apply independently recognized risk controls exactly."""

import json

import pytest
from tests.unit.test_source_change_assurance import _NOW, _assemble
from tests.unit.test_source_control_changes import _assess
from tests.unit.test_source_risk_controls import _json, _parent

from trade_plan_monitor.ai.daily_review import DailyClause, DailyFieldBinding, semantic_values
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateOperation,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_risk_controls import parse_source_risk_controls
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.risk_scope import restrict_scope, risk_identity

_UNSET = object()


def _case(text=None, *, action="MODIFY", direction="EXISTING_POSITIONS_ONLY", scope=None,
          proposed_scope=_UNSET, other_update=None, no_operations=False, operation_id=None,
          source_day=None, extra_operation=None, direction_claim=True):
    base, parent = _parent(None if scope is None else json.dumps(scope))
    text = text or _json(action, direction=direction)
    source = PreparationSource(source_id="risk-control-current", text=text, available_at=_NOW,
        effective_trade_date=source_day or _NOW.date())
    controls = parse_source_risk_controls(source, base, parent)
    control = next((row for row in controls.controls if row.rule_id == "ORDINARY_TECHNICAL"), None)
    proposed = base.draft.model_copy(update={"version": base.draft.version + 1})
    branches = list(proposed.risk_branches)
    if action == "REVOKE":
        branches.pop(0)
    elif action == "MODIFY":
        if control is not None and control.after is not None:
            branches[0] = type(branches[0]).model_validate(control.after.model_dump(mode="json"))
        else:
            branches[0] = branches[0].model_copy(update={"holding_scope": restrict_scope(
                branches[0].holding_scope, "BEFORE_TRADE_DATE" if direction ==
                "EXISTING_POSITIONS_ONLY" else "FROM_TRADE_DATE", source.effective_trade_date)})
        if proposed_scope is not _UNSET:
            branches[0] = branches[0].model_copy(update={"holding_scope": proposed_scope})
        if other_update:
            branches[0] = branches[0].model_copy(update=other_update)
    proposed = proposed.model_copy(update={"risk_branches": tuple(branches)})
    values = semantic_values(proposed)
    paths = tuple(path for path in values if path.startswith("risk_branches[0].holding_scope."))
    if other_update:
        paths += tuple("risk_branches[0]." + name for name in other_update
                       if "risk_branches[0]." + name in values)
    canonical = server_source_clauses(text)
    ids = tuple(row.clause_id for row in canonical if control is None or (
        row.start < control.end and row.end > control.start))
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
        disposition="POLICY" if action == "MODIFY" else "CONTEXT",
        semantic_role="COMMENTARY", paths=paths if action == "MODIFY" else (),
        reason="Exact synthetic original risk control; role does not establish meaning"))
        for row in canonical)
    bindings = tuple(DailyFieldBinding(path=path, value=values[path], origin=(
        "SOURCE_SEMANTIC" if ".holding_scope." in path else "SOURCE"),
        unit="JSON", clause_ids=(ids if ".holding_scope." in path else tuple(
            row.clause_id for row in canonical if path in row.excerpt)),
        supplement_id=None) for path in paths
        if action == "MODIFY")
    operation = PlanUpdateOperation(target="risk_branches", action=action,
        rule_id=operation_id or risk_identity(base.draft.risk_branches[0]), clause_ids=ids,
        intent="ASSERTED", rationale="Synthetic proposal cites the exact complete source control",
        scope_assessment=("PARTIAL_RULE" if action == "MODIFY" and direction_claim
                          else "ENTIRE_RULE"),
        scope_change=direction if action == "MODIFY" and direction_claim else None)
    output = PlanUpdateExtractionOutput(schema_version="monitor-loop-update-extraction-v1",
        draft=proposed, clauses=clauses, bindings=bindings, scope="EXPLICIT_CHANGES",
        scope_clause_ids=ids, retain_unmentioned=True, inheritance_mode="PREDECESSOR_PATCH",
        operations=() if no_operations else (operation,) + (() if extra_operation is None
                                                          else (extra_operation,)))
    context = context_from_review(base, parent.binding.candidate_hash)
    return _assemble(base, parent, source, output, context)


@pytest.mark.parametrize("action", ["MODIFY", "REVOKE", "RETAIN"])
def test_actual_full_wire_registered_risk_control_has_complete_current_coverage(action):
    case = _case(action=action)
    assert case[2].review.issues == ()
    assert len(case[3].derivation.stages) == 3

    result = _assess(case)

    assert result.coverage_complete, result.source_assessment.issues
    assert result.authority_granted is False
    controls = [row for row in result.source_assessment.obligations
                if row.scope == "RISK" and row.state == "MAPPED"]
    assert controls and all(json.loads(row.semantics_json)["treatment"] == (
        "REGISTERED_SOURCE_RISK_CONTROL") for row in controls)
    operation = next(row for row in result.source_assessment.operations
                     if row.target == "risk_branches" and row.rule_id == "ORDINARY_TECHNICAL")
    assert operation.action == action and operation.obligation_ids
