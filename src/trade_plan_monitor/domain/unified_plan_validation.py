"""Incomplete current candidates use the same trusted source-review workflow."""

from typing import Literal

from pydantic import Field, ValidationError

from trade_plan_monitor.domain.daily_plan_models import (
    DailyActivation,
    DailyValidity,
    DailyValue,
    Identifier,
    PositiveWholeQty,
)
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyDraftLevels,
    DailyDraftRisk,
    DailyPlanDraft,
)
from trade_plan_monitor.domain.unified_plan_models import (
    UnifiedCondition,
    UnifiedConfirmation,
    UnifiedExecutionPolicy,
    UnifiedIndependentSignal,
    UnifiedMonitoring,
    UnifiedPositionPolicy,
    UnifiedTradePlan,
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
    validity: DailyValidity | None
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"] | None
    independent_signal: UnifiedIndependentSignal | None


class UnifiedDraftRisk(DailyDraftRisk):
    condition: UnifiedCondition | None


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


class UnifiedPlanDraft(DailyPlanDraft):
    schema_version: Literal[5] = 5
    execution_mode: Literal["CONDITION_PLAN"] = "CONDITION_PLAN"
    execution_version: Literal["condition-plan-v1"] = "condition-plan-v1"
    activation: DailyActivation | None
    levels: DailyDraftLevels | None
    position: UnifiedDraftPosition
    monitoring: UnifiedMonitoring | None
    ordinary_rules: tuple[UnifiedDraftRule, ...] = Field(max_length=2)
    alert_rules: tuple[UnifiedDraftAlertRule, ...] = Field(default=(), max_length=10)
    risk_branches: tuple[UnifiedDraftRisk, ...] = Field(max_length=2)
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
        return cls.model_validate(plan.model_dump(mode="json"))


def unified_plan_issues(draft):
    try:
        UnifiedTradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple(
            {
                "path": ".".join(str(x) for x in e["loc"]),
                "code": "PLAN_PARAMETER_REQUIRED"
                if e["input"] is None
                else "PLAN_PARAMETER_INVALID",
                "reason": "Supply the reviewed parameter and its source or human evidence.",
            }
            for e in error.errors(include_url=False, include_context=False, include_input=True)
        )
