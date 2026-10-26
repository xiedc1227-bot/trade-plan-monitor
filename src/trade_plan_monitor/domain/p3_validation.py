"""Private Schema9 draft preparation; public admission waits for workflow guards."""

from pydantic import ValidationError

from trade_plan_monitor.domain.market_linkage_validation import P3PlanDraft as P3PlanDraft
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan


def p3_draft_issues(draft):
    try:
        P3TradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple({"path": ".".join(str(v) for v in item["loc"]),
                      "code": "P3_PARAMETER_INVALID", "reason": item["msg"]}
                     for item in error.errors(include_url=False, include_context=False))
