"""P2 draft contract, isolated until the complete execution chain is admitted."""

from typing import Literal

from pydantic import Field, ValidationError

from trade_plan_monitor.domain.market_linkage_validation import MarketExceptionPlanDraft
from trade_plan_monitor.domain.p2_policy_models import P2Rule, P2TradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedDraftRule


class P2PlanDraft(MarketExceptionPlanDraft):
    schema_version: Literal[8] = 8
    execution_version: Literal["condition-plan-v4"] = "condition-plan-v4"
    ordinary_rules: tuple[P2Rule | UnifiedDraftRule, ...] = Field(max_length=2)

    def to_executable(self) -> P2TradePlan | None:
        try:
            return P2TradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None


def p2_draft_issues(draft):
    try:
        P2TradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple({"path": ".".join(str(v) for v in item["loc"]),
                      "code": "P2_PARAMETER_INVALID", "reason": item["msg"]}
                     for item in error.errors(include_url=False, include_context=False))
