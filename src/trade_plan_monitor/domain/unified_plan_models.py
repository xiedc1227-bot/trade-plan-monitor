"""Current condition-driven plan contract; historical schemas retain their exact codecs."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import (
    DailyActivation,
    DailyCandleRatio,
    DailyCloseSequence,
    DailyIndependentEvent,
    DailyIndicatorCompare,
    DailyLevels,
    DailyMetadata,
    DailyPriceCompare,
    DailyPriceInRange,
    DailyRiskBranch,
    DailyTradePlan,
    DailyTradingRules,
    DailyValidity,
    DailyValue,
    DailyVolumeRatio,
    Fen,
    Identifier,
    PositiveQty,
    PositiveWholeQty,
    ReviewedDailyFact,
    Text,
    WholeQty,
    required_daily_observations,
)


class MinuteCloseInRange(DailyValue):
    type: Literal["MINUTE_CLOSE_IN_RANGE"]
    timeframe_minutes: Literal[5]
    low_fen: Fen
    high_fen: Fen
    include_low: bool = Field(strict=True)
    include_high: bool = Field(strict=True)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.low_fen + (not self.include_low) > self.high_fen - (not self.include_high):
            raise ValueError("range contains no integer-fen tick")
        return self


class MinuteCloseBelow(DailyValue):
    type: Literal["MINUTE_CLOSE_BELOW"]
    timeframe_minutes: Literal[5]
    price_fen: Fen


class MinuteVolumeToMeanGte(DailyValue):
    type: Literal["MINUTE_VOLUME_TO_MEAN_GTE"]
    timeframe_minutes: Literal[5]
    window_bars: int = Field(strict=True, ge=1, le=500)
    minimum_ratio: Decimal = Field(gt=0, le=10, allow_inf_nan=False)
    history_scope: Literal["CONTIGUOUS_TRADING_BARS"]


class UnifiedAll(DailyValue):
    type: Literal["ALL"]
    conditions: tuple[UnifiedCondition, ...] = Field(min_length=1, max_length=50)


class UnifiedAny(DailyValue):
    type: Literal["ANY"]
    conditions: tuple[UnifiedCondition, ...] = Field(min_length=1, max_length=50)


UnifiedCondition = Annotated[
    DailyPriceCompare
    | DailyPriceInRange
    | DailyVolumeRatio
    | DailyCandleRatio
    | DailyIndicatorCompare
    | DailyCloseSequence
    | ReviewedDailyFact
    | MinuteCloseInRange
    | MinuteCloseBelow
    | MinuteVolumeToMeanGte
    | UnifiedAll
    | UnifiedAny,
    Field(discriminator="type"),
]
UnifiedAll.model_rebuild()
UnifiedAny.model_rebuild()


def condition_leaves(condition):
    if isinstance(condition, UnifiedAll | UnifiedAny):
        return tuple(leaf for child in condition.conditions for leaf in condition_leaves(child))
    return (condition,)


class OfficialDailyConfirmation(DailyValue):
    kind: Literal["OFFICIAL_DAILY_CLOSE"]


class CompletedMinuteConfirmation(DailyValue):
    kind: Literal["COMPLETED_BAR_CLOSE"]
    timeframe_minutes: Literal[5]


UnifiedConfirmation = Annotated[
    OfficialDailyConfirmation | CompletedMinuteConfirmation, Field(discriminator="kind")
]


class UnifiedResetPolicy(DailyValue):
    mode: Literal["LATER_CLOSE_RESET_THEN_CONFIRM"]
    reset_condition: UnifiedCondition


UnifiedIndependentSignal = Annotated[
    DailyIndependentEvent | UnifiedResetPolicy, Field(discriminator="mode")
]


class UnifiedMonitoring(DailyValue):
    indicator_formula_version: Literal["daily-ta-v2"]
    price_basis: Literal["QFQ"]
    source_requirement: Literal["ONE_VERIFIED_PROVIDER"]
    comparability_requirement: Literal["CURRENT_QUOTE_BASIS"]
    macd_min_observations: int = Field(strict=True, ge=1, le=500)


class UnifiedRule(DailyValue):
    status: Literal["ENABLED"]
    side: Literal["BUY", "SELL"]
    rule_id: Identifier
    quantity: PositiveWholeQty
    bucket: Literal["TACTICAL"]
    condition: UnifiedCondition
    confirmation: UnifiedConfirmation
    execution_window: Literal["NEXT_EXCHANGE_SESSION_ONLY", "CURRENT_SESSION"]
    zone: Literal["LOW_BUY", "PRESSURE"] | None
    validity: DailyValidity
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"]
    independent_signal: UnifiedIndependentSignal

    @model_validator(mode="after")
    def temporal_contract(self) -> Self:
        daily = self.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
        if daily != (self.execution_window == "NEXT_EXCHANGE_SESSION_ONLY"):
            raise ValueError("confirmation and execution window disagree")
        if self.zone is not None and self.zone != ("LOW_BUY" if self.side == "BUY" else "PRESSURE"):
            raise ValueError("side and optional price zone disagree")
        return self


class UnifiedAlertRule(DailyValue):
    """Source-defined reminder authority, without simulated liquidation authority."""

    kind: Literal["RISK_ALERT"]
    rule_id: Identifier
    condition: UnifiedCondition
    confirmation: UnifiedConfirmation


class UnifiedExecutionPolicy(DailyValue):
    same_signal: Literal["ONE_PLANNED_QUANTITY"]
    risk_priority: Literal["SEVERE_THEN_ORDINARY"]
    ordinary_conflict: Literal["BLOCK_BOTH"]


class UnifiedPositionPolicy(DailyValue):
    """Maximum position is required; source-defined allocation remains optional policy."""

    max_qty: PositiveWholeQty
    core_target_qty: WholeQty | None = None
    tactical_target_qty: WholeQty | None = None
    allocation_provenance: Literal["EXISTING_CONFIRMED", "PROPOSED"] | None = None
    allocation_evidence: Text | None = None

    @model_validator(mode="after")
    def bounded_allocation(self) -> Self:
        targets = (self.core_target_qty, self.tactical_target_qty)
        if sum(target for target in targets if target is not None) > self.max_qty:
            raise ValueError("source-defined allocation exceeds max_qty")
        return self


class UnifiedRiskBranch(DailyRiskBranch):
    condition: UnifiedCondition | None

    @model_validator(mode="after")
    def explicit_severe_condition(self) -> Self:
        if (self.kind == "SEVERE_TECHNICAL") != (self.condition is not None):
            raise ValueError("severe risk requires its explicit reviewed condition")
        return self


class UnifiedTradePlan(DailyTradePlan):
    schema_version: Literal[5] = 5
    execution_mode: Literal["CONDITION_PLAN"] = "CONDITION_PLAN"
    execution_version: Literal["condition-plan-v1"] = "condition-plan-v1"
    plan_id: Identifier
    version: PositiveQty
    symbol: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
    name: str = Field(min_length=1, max_length=100)
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: DailyMetadata
    activation: DailyActivation
    levels: DailyLevels | None
    position: UnifiedPositionPolicy
    trading_rules: DailyTradingRules
    monitoring: UnifiedMonitoring | None
    ordinary_rules: tuple[UnifiedRule, ...] = Field(max_length=2)
    alert_rules: tuple[UnifiedAlertRule, ...] = Field(default=(), max_length=10)
    risk_branches: tuple[UnifiedRiskBranch, ...] = Field(max_length=2)
    execution_policy: UnifiedExecutionPolicy

    @model_validator(mode="before")
    @classmethod
    def bounded_conditions(cls, data):
        count = 0

        def walk(value, depth=1):
            nonlocal count
            if isinstance(value, dict):
                if value.get("type") in {"ALL", "ANY"}:
                    if depth >= 4:
                        raise ValueError("condition depth exceeds four")
                    for child in value.get("conditions", ()):
                        walk(child, depth + 1)
                elif "type" in value:
                    count += 1
                else:
                    for child in value.values():
                        walk(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    walk(child, depth)
            if count > 50:
                raise ValueError("condition leaves exceed fifty")

        walk(data)
        return data

    @model_validator(mode="after")
    def semantic_contract(self) -> Self:
        if self.market != {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[self.symbol[-2:]]:
            raise ValueError("symbol/market mismatch")
        if not self.ordinary_rules and not self.risk_branches and not self.alert_rules:
            raise ValueError("plan requires an explicit condition or risk branch")
        if len({r.side for r in self.ordinary_rules}) != len(self.ordinary_rules):
            raise ValueError("duplicate ordinary side")
        identified_rules = (*self.ordinary_rules, *self.alert_rules)
        if len({r.rule_id for r in identified_rules}) != len(identified_rules):
            raise ValueError("duplicate rule identity")
        if len({r.kind for r in self.risk_branches}) != len(self.risk_branches):
            raise ValueError("duplicate risk branch")
        if self.levels is None and (
            any(r.zone for r in self.ordinary_rules)
            or any(r.kind == "ORDINARY_TECHNICAL" for r in self.risk_branches)
        ):
            raise ValueError("referenced price zones/risk line require explicit levels")
        for branch in self.risk_branches:
            if (
                not branch.involves_core
                and self.position.core_target_qty is not None
                and branch.target_core_qty != self.position.core_target_qty
            ):
                raise ValueError("protected CORE target must be retained")
        roots = [branch.condition for branch in self.risk_branches if branch.condition is not None]
        roots.extend(rule.condition for rule in self.alert_rules)
        for rule in self.ordinary_rules:
            roots.append(rule.condition)
            if isinstance(rule.independent_signal, UnifiedResetPolicy):
                roots.append(rule.independent_signal.reset_condition)
        for root in roots:
            for leaf in condition_leaves(root):
                if leaf.type.startswith("DAILY_"):
                    if self.monitoring is None:
                        raise ValueError("daily conditions require reviewed data settings")
                    if (
                        required_daily_observations(leaf, self.monitoring.macd_min_observations)
                        > 500
                    ):
                        raise ValueError("daily condition history exceeds 500 observations")
        return self
