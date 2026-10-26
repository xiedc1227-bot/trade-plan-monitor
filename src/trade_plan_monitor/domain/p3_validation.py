"""Private Schema9 draft preparation; public admission waits for workflow guards."""

from typing import Literal

from pydantic import ValidationError

from trade_plan_monitor.domain.market_linkage_validation import P2PlanDraft
from trade_plan_monitor.domain.p3_policy_drafts import DraftP3Position
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan


class P3PlanDraft(P2PlanDraft):
    schema_version: Literal[9] = 9
    execution_version: Literal["condition-plan-v5"] = "condition-plan-v5"
    position: DraftP3Position

    def to_executable(self):
        try:
            return P3TradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None


def p3_draft_issues(draft):
    try:
        P3TradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple({"path": ".".join(str(v) for v in item["loc"]),
                      "code": "P3_PARAMETER_INVALID", "reason": item["msg"]}
                     for item in error.errors(include_url=False, include_context=False))
