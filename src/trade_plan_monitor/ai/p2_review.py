"""P2 evidence completeness supplements, never replaces human source review."""

from pydantic import ValidationError

from trade_plan_monitor.domain.daily_plan_models import DailyZone
from trade_plan_monitor.domain.p2_policy_models import NoEconomics, PretradePolicy


def p2_review_issues(draft):
    issues = []
    for i, rule in enumerate(draft.ordinary_rules):
        if not hasattr(rule, "pretrade_policy"):
            continue
        try:
            policy = PretradePolicy.model_validate(rule.pretrade_policy.model_dump(mode="json"))
        except (ValidationError, AttributeError):
            continue  # Strict draft issues already block incomplete policies.
        if isinstance(policy.economics, NoEconomics):
            continue
        path = f"ordinary_rules[{i}].pretrade_policy"
        for level in ("PRESSURE", "RISK"):
            dimensions = {e.dimension for e in policy.level_evidence if e.level == level}
            if "PRICE_STRUCTURE" not in dimensions or len(dimensions) < 2:
                issues.append(dict(path=path+".level_evidence", code="P2_LEVEL_EVIDENCE_REQUIRED",
                    reason=f"{level} needs structural and independent supporting evidence."))
        levels = draft.levels
        try:
            pressure = DailyZone.model_validate(levels.pressure.model_dump(mode="json"))
        except (AttributeError, ValidationError):
            pressure = None
        if (levels is None or pressure is None
                or not pressure.contains(policy.economics.target_price_fen)
                or policy.economics.risk_price_fen != levels.risk_line_fen):
            issues.append(dict(path=path+".economics", code="P2_LEVEL_REFERENCE_MISMATCH",
                reason="Bind the explicit target to the reviewed pressure range and risk line."))
        if draft.symbol not in policy.economics.fee_schedule.symbols:
            issues.append(dict(path=path+".economics.fee_schedule.symbols",
                code="P2_FEE_SYMBOL_MISMATCH", reason="Fee schedule must cover this security."))
    return tuple(issues)
