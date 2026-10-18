"""Historical display cannot become current inheritance authority."""

from types import SimpleNamespace

from trade_plan_monitor.ai.daily_review import DailyClause
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateOperation
from trade_plan_monitor.ai.update_review import _scope_issues


def test_legacy_frozen_risk_diagnosis_remains_readable_but_not_reusable():
    operation = PlanUpdateOperation(
        target="risk_branches", rule_id="ORDINARY_TECHNICAL", action="REVOKE",
        clause_ids=("risk-clause",),
    )
    text = "旧价位只是观察参照，不对之后建立的仓位设止损。"
    clause = DailyClause(clause_id="risk-clause", excerpt=text, start=0, end=len(text),
        disposition="POLICY", paths=("risk_branches",), reason="Legacy reviewed interpretation.")
    output = SimpleNamespace(
        inheritance_mode=None, scope="EXPLICIT_CHANGES", retain_unmentioned=False,
        clauses=(clause,), operations=(operation,), scope_clause_ids=(),
    )
    assert _scope_issues(output, historical=True) == []
    assert ("UPDATE_WITHDRAWAL_SCOPE_REQUIRED: risk_branches.ORDINARY_TECHNICAL"
            in _scope_issues(output))
