"""Incomplete linked candidates preserve missing strategy parameters explicitly."""

from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier, PositiveWholeQty
from trade_plan_monitor.domain.market_exception_models import (
    ExceptionPermission,
    MarketExceptionTradePlan,
)
from trade_plan_monitor.domain.market_linkage_models import (
    MarketLinkedTradePlan,
    MarketPolicy,
    QuantityPolicy,
)
from trade_plan_monitor.domain.unified_plan_models import (
    UnifiedCondition,
    UnifiedConfirmation,
    UnifiedIndependentSignal,
    UnifiedValidity,
)
from trade_plan_monitor.domain.unified_plan_validation import (
    UnifiedDraftRisk,
    UnifiedDraftRule,
    UnifiedPlanDraft,
)
from trade_plan_monitor.market_index.identity import ReferenceMarketBinding


class DraftQuantityPolicy(QuantityPolicy):
    base_quantity: PositiveWholeQty | None
    mode: Literal["MARKET_FACTOR"] | None
    normal_factor: Literal["1"] | None
    weak_factor: Literal["0.5"] | None
    rounding: Literal["LEGAL_FLOOR"] | None
    capacity_policy: Literal["BLOCK_FULL"] | None
    signal_quantity_policy: Literal["FREEZE"] | None


class DraftMarketPolicy(MarketPolicy):
    policy_version: Literal["market-linkage-v1"] | None
    base_confirmation: Literal["S0"] | None
    exception_policy: Literal["BLOCK_P1"] | None


class MarketLinkedDraftRule(DailyValue):
    status: Literal["ENABLED"] | None
    side: Literal["BUY"] | None
    rule_id: Identifier | None
    bucket: Literal["TACTICAL"] | None
    condition: UnifiedCondition | None
    confirmation: UnifiedConfirmation | None
    execution_window: Literal["NEXT_EXCHANGE_SESSION_ONLY"] | None
    zone: Literal["LOW_BUY"] | None
    validity: UnifiedValidity | None
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"] | None
    independent_signal: UnifiedIndependentSignal | None
    market_policy: DraftMarketPolicy | None
    quantity_policy: DraftQuantityPolicy | None

    @model_validator(mode="before")
    @classmethod
    def reject_fixed_quantity(cls, value):
        if isinstance(value, dict) and "quantity" in value:
            raise ValueError("linked rule forbids fixed quantity, including null")
        return value


class LinkedDraftRisk(UnifiedDraftRisk):
    suspension_confirmation_policy: (
        Literal["RESUME_FIRST_CLOSE", "RESTART_ADJACENT_PAIR"] | None
    ) = None


class MarketLinkedPlanDraft(UnifiedPlanDraft):
    schema_version: Literal[6] = 6
    execution_version: Literal["condition-plan-v2"] = "condition-plan-v2"
    reference_market: ReferenceMarketBinding | None
    ordinary_rules: tuple[MarketLinkedDraftRule | UnifiedDraftRule, ...] = Field(max_length=2)
    risk_branches: tuple[LinkedDraftRisk, ...] = Field(max_length=64)

    def to_executable(self) -> MarketLinkedTradePlan | None:
        try:
            return MarketLinkedTradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None


class DraftExceptionRoutes(DailyValue):
    weak_minimum: ExceptionPermission | None
    broken_strong: ExceptionPermission | None


class DraftExceptionPolicy(DailyValue):
    policy_version: Literal["market-linkage-v2"] | None
    base_confirmation: Literal["S0"] | None
    exception_policy: Literal["REVIEW_PER_OCCURRENCE"] | None
    exception_routes: DraftExceptionRoutes | None


class MarketExceptionDraftRule(MarketLinkedDraftRule):
    market_policy: DraftExceptionPolicy | None


class MarketExceptionPlanDraft(MarketLinkedPlanDraft):
    schema_version: Literal[7] = 7
    execution_version: Literal["condition-plan-v3"] = "condition-plan-v3"
    ordinary_rules: tuple[MarketExceptionDraftRule | UnifiedDraftRule, ...] = Field(max_length=2)

    def to_executable(self) -> MarketExceptionTradePlan | None:
        try:
            return MarketExceptionTradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None


CurrentPlanDraft = Annotated[
    MarketExceptionPlanDraft | MarketLinkedPlanDraft | UnifiedPlanDraft,
    Field(discriminator="schema_version"),
]


def parse_current_draft(data):
    from pydantic import TypeAdapter

    return TypeAdapter(CurrentPlanDraft).validate_python(data)
