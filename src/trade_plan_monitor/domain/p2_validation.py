"""P2 draft contract, isolated until the complete execution chain is admitted."""

from pydantic import ValidationError

from trade_plan_monitor.domain.market_linkage_validation import P2PlanDraft as P2PlanDraft
from trade_plan_monitor.domain.p2_policy_models import P2TradePlan


def p2_draft_issues(draft):
    try:
        P2TradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple({"path": ".".join(str(v) for v in item["loc"]),
                      "code": "P2_PARAMETER_INVALID", "reason": item["msg"]}
                     for item in error.errors(include_url=False, include_context=False))
