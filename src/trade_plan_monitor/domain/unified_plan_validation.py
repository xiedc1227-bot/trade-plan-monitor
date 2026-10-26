"""Incomplete current candidates use the same trusted source-review workflow."""

from typing import Literal

from pydantic import Field, ValidationError

from trade_plan_monitor.domain.daily_plan_models import (
    DailyActivation,
    DailyValue,
    Identifier,
    PositiveWholeQty,
)
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyDraftLevels,
    DailyDraftRisk,
    DailyDraftZone,
    DailyPlanDraft,
)
from trade_plan_monitor.domain.risk_scope import RiskHoldingScope
from trade_plan_monitor.domain.unified_plan_models import (
    UnifiedCondition,
    UnifiedConfirmation,
    UnifiedExecutionPolicy,
    UnifiedIndependentSignal,
    UnifiedMonitoring,
    UnifiedPositionPolicy,
    UnifiedTradePlan,
    UnifiedValidity,
)


class UnifiedDraftRule(DailyValue):
    status: Literal["ENABLED"] | None
    side: Literal["BUY", "SELL"]
    rule_id: Identifier | None
    quantity: PositiveWholeQty | None
    bucket: Literal["TACTICAL"] | None
    condition: UnifiedCondition | None
    confirmation: UnifiedConfirmation | None
    execution_window: Literal["NEXT_EXCHANGE_SESSION_ONLY", "CURRENT_SESSION"] | None
    zone: Literal["LOW_BUY", "PRESSURE"] | None
    validity: UnifiedValidity | None
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"] | None
    independent_signal: UnifiedIndependentSignal | None


class UnifiedDraftRisk(DailyDraftRisk):
    condition: UnifiedCondition | None
    rule_id: Identifier | None = Field(default=None, exclude_if=lambda v: v is None)
    holding_scope: RiskHoldingScope | None = Field(default=None, exclude_if=lambda v: v is None)
    risk_line_fen: int | None = Field(default=None, strict=True, gt=0,
                                      exclude_if=lambda v: v is None)
    risk_comparison: Literal["LT", "LTE"] | None = Field(
        default=None, exclude_if=lambda v: v is None)


class UnifiedDraftAlertRule(DailyValue):
    kind: Literal["RISK_ALERT"] | None
    rule_id: Identifier | None
    condition: UnifiedCondition | None
    confirmation: UnifiedConfirmation | None


class UnifiedDraftPosition(UnifiedPositionPolicy):
    max_qty: PositiveWholeQty | None

    def bounded_allocation(self):
        if self.max_qty is not None:
            return super().bounded_allocation()
        return self


class UnifiedDraftLevels(DailyDraftLevels):
    low_buy: DailyDraftZone | None
    pressure: DailyDraftZone | None


class UnifiedPlanDraft(DailyPlanDraft):
    schema_version: Literal[5] = 5
    execution_mode: Literal["CONDITION_PLAN"] = "CONDITION_PLAN"
    execution_version: Literal["condition-plan-v1"] = "condition-plan-v1"
    activation: DailyActivation | None
    levels: UnifiedDraftLevels | None
    position: UnifiedDraftPosition
    monitoring: UnifiedMonitoring | None
    ordinary_rules: tuple[UnifiedDraftRule, ...] = Field(max_length=2)
    alert_rules: tuple[UnifiedDraftAlertRule, ...] = Field(default=(), max_length=10)
    risk_branches: tuple[UnifiedDraftRisk, ...] = Field(max_length=64)
    execution_policy: UnifiedExecutionPolicy | None

    def executable_payload(self):
        return self.model_dump(mode="json")

    def to_executable(self) -> UnifiedTradePlan | None:
        try:
            return UnifiedTradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None

    @classmethod
    def from_executable(cls, plan):
        if cls is UnifiedPlanDraft and plan.schema_version == 8:
            from trade_plan_monitor.domain.market_linkage_validation import P2PlanDraft
            return P2PlanDraft.from_executable(plan)
        if cls is UnifiedPlanDraft and plan.schema_version == 7:
            from trade_plan_monitor.domain.market_linkage_validation import MarketExceptionPlanDraft
            return MarketExceptionPlanDraft.from_executable(plan)
        if cls is UnifiedPlanDraft and plan.schema_version == 6:
            from trade_plan_monitor.domain.market_linkage_validation import MarketLinkedPlanDraft
            return MarketLinkedPlanDraft.from_executable(plan)
        return cls.model_validate(plan.model_dump(mode="json"))


def unified_plan_issues(draft):
    try:
        if draft.schema_version == 7:
            from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
            MarketExceptionTradePlan.model_validate(draft.executable_payload())
        elif draft.schema_version == 6:
            from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
            MarketLinkedTradePlan.model_validate(draft.executable_payload())
        else:
            UnifiedTradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        errors = []
        for item in error.errors(include_url=False, include_context=False, include_input=True):
            location = list(item["loc"])
            if (len(location) == 2 and location[0] == "risk_branches"
                    and "ordinary risk needs an explicit suspension policy" in item["msg"]):
                location.append("suspension_confirmation_policy")
                item = {**item, "input": None}
            if "validity" in location and "ordinary_rules" in location:
                index = location.index("validity")
                branch = location[index + 1] if len(location) > index + 1 else None
                if branch in {"PlanActiveValidity", "function-after[order(), DailyValidity]"}:
                    validity = draft.ordinary_rules[location[1]].validity
                    persistent = validity is not None and validity.mode == "PLAN_ACTIVE"
                    if (branch == "PlanActiveValidity") != persistent:
                        continue
                    location.pop(index + 1)
            errors.append({**item, "loc": location})
        return tuple(
            {
                "path": ".".join(str(x) for x in e["loc"]) or "plan",
                "code": "PLAN_PARAMETER_REQUIRED"
                if e["input"] is None
                else "PLAN_PARAMETER_INVALID",
                "reason": "Supply the reviewed parameter and its source or human evidence.",
            }
            for e in errors
        )
