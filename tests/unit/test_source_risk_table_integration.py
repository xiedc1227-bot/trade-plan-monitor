"""A mixed original table row keeps independent scope and structural-reference proofs."""

from datetime import timedelta

import pytest
from tests.unit.test_source_change_assurance import _NOW, _assemble
from tests.unit.test_source_control_changes import _assess
from tests.unit.test_source_risk_table_controls import _parent, _row, _table

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    normalize_daily_exclusions,
    semantic_values,
)
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateOperation,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_risk_table_controls import parse_source_risk_table_controls
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.risk_scope import restrict_scope, risk_identity


def _case(text=None, *, base=None, parent=None, action="MODIFY", other_update=None,
          proposed_scope=None, no_operations=False, extra_operation=None):
    if base is None:
        base, parent = _parent()
    text = _table() if text is None else text
    source = PreparationSource(source_id="mixed-risk-table", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    parsed = parse_source_risk_table_controls(source, base, parent)
    proposed = base.draft.model_copy(update={"version": base.draft.version + 1})
    branches = list(proposed.risk_branches)
    if action == "REVOKE":
        branches.pop(0)
    elif action == "MODIFY":
        holding_scope = proposed_scope or restrict_scope(
            branches[0].holding_scope, "BEFORE_TRADE_DATE", source.effective_trade_date)
        branches[0] = branches[0].model_copy(update={"holding_scope": holding_scope})
        if other_update:
            branches[0] = branches[0].model_copy(update=other_update)
    proposed = proposed.model_copy(update={"risk_branches": tuple(branches)})
    values = semantic_values(proposed)
    paths = tuple(path for path in values if path.startswith("risk_branches[0].holding_scope."))
    if other_update:
        paths += tuple("risk_branches[0]." + name for name in other_update
                       if "risk_branches[0]." + name in values)
    canonical = server_source_clauses(text)
    if parsed.groups:
        start, end = parsed.groups[0].scope_control.start, parsed.groups[0].scope_control.end
    else:
        start = text.find(_row())
        start = 0 if start < 0 else start
        end = start + (len(_row()) if _row() in text else len(canonical[0].excerpt))
    ids = tuple(row.clause_id for row in canonical if row.start < end and row.end > start)
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
        disposition="POLICY" if action == "MODIFY" else "CONTEXT",
        semantic_role="COMMENTARY", paths=paths if action == "MODIFY" else (),
        reason="Complete synthetic source inventory; roles do not release unknown table cells"))
        for row in canonical)
    clauses = normalize_daily_exclusions(clauses, text)
    bindings = tuple(DailyFieldBinding(path=path, value=values[path], origin=(
        "SOURCE_SEMANTIC" if ".holding_scope." in path else "SOURCE"), unit="JSON",
        clause_ids=(ids if ".holding_scope." in path else tuple(
            row.clause_id for row in canonical if path in row.excerpt)),
        supplement_id=None) for path in paths if action == "MODIFY")
    operation = PlanUpdateOperation(target="risk_branches", rule_id=risk_identity(
        base.draft.risk_branches[0]), action=action, clause_ids=ids, intent="ASSERTED",
        rationale="Synthetic proposal narrows the old holding cohort without inventing a stop",
        scope_assessment="PARTIAL_RULE" if action == "MODIFY" else "ENTIRE_RULE",
        scope_change="EXISTING_POSITIONS_ONLY" if action == "MODIFY" else None)
    output = PlanUpdateExtractionOutput(schema_version="monitor-loop-update-extraction-v1",
        draft=proposed, clauses=clauses, bindings=bindings, scope="EXPLICIT_CHANGES",
        scope_clause_ids=ids, retain_unmentioned=True, inheritance_mode="PREDECESSOR_PATCH",
        operations=() if no_operations else (operation,) + (() if extra_operation is None
                                                          else (extra_operation,)))
    context = context_from_review(base, parent.binding.candidate_hash)
    return _assemble(base, parent, source, output, context)


@pytest.mark.parametrize("branch_price", [None, 2599], ids=["global-price", "branch-price"])
def test_actual_wire_mixed_row_preserves_two_distinct_noninterchangeable_meanings(branch_price):
    base, parent = _parent(branch_price=branch_price, no_global=branch_price is not None)
    case = _case(base=base, parent=parent)
    assert case[2].review.issues == () and len(case[3].derivation.stages) == 3
    assert parse_source_risk_table_controls(case[0], base, parent).groups

    result = _assess(case)

    assert result.coverage_complete, result.source_assessment.issues
    assert result.authority_granted is False
    assert result.current_automatic_fidelity_verified is False
    after = case[2].review.draft.risk_branches[0]
    assert after.model_dump(mode="json", exclude={"holding_scope"}) == (
        base.draft.risk_branches[0].model_dump(mode="json", exclude={"holding_scope"}))
    assert case[2].review.draft.risk_branches[0].holding_scope.trade_date == _NOW.date()
    assert case[0].available_at == base.available_at + timedelta(days=1)
