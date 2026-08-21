"""Immutable values and allowlisted conditions for executable trade plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PlanId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
AShareSymbol = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$"),
]
PlanName = Annotated[str, StringConstraints(min_length=1, max_length=100)]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
BoardLotQuantity = Annotated[int, Field(strict=True, ge=0, multiple_of=100)]
PositiveBoardLotQuantity = Annotated[int, Field(strict=True, gt=0, multiple_of=100)]
PositiveVersion = Annotated[int, Field(strict=True, gt=0)]
StrictFlag = Annotated[bool, Field(strict=True)]
Market = Literal["SSE", "SZSE", "BSE"]
ConditionBars = Annotated[int, Field(strict=True, ge=1, le=500)]
ConditionHitCount = Annotated[int, Field(strict=True, ge=0, le=500)]
BoundedRatio = Annotated[
    Decimal,
    Field(gt=Decimal("0"), le=Decimal("10"), allow_inf_nan=False),
]
UnitRatio = Annotated[
    Decimal,
    Field(gt=Decimal("0"), le=Decimal("1"), allow_inf_nan=False),
]
PositiveIndicatorDelta = Annotated[
    Decimal,
    Field(gt=Decimal("0"), le=Decimal("100"), allow_inf_nan=False),
]
PlanZone = Literal["LOW_BUY", "PRESSURE"]
PlanIndicator = Literal["EMA10", "MA20", "MA50", "MA200", "BOLL_MIDDLE"]
PressureLevel = Literal["PRESSURE_REFERENCE"]
RiskLevel = Literal["RISK_LINE"]
PositionBucket = Literal["CORE", "TACTICAL"]
_MAX_CONDITION_DEPTH = 4
_MAX_CONDITION_LEAVES = 50


class _DomainValue(BaseModel):
    """Make all domain values closed and immutable at validation boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class PlanMetadata(_DomainValue):
    """Optional report provenance that never controls plan activation."""

    report_at: AwareDatetime | None = None
    reference_price_fen: PositiveFen | None = None


class ManualActivation(_DomainValue):
    """Activation that ends only through an explicit user command."""

    mode: Literal["MANUAL"] = "MANUAL"


class TradingDayActivation(_DomainValue):
    """Activation for one specified trading day."""

    mode: Literal["TRADING_DAY"] = "TRADING_DAY"
    trading_day: date


class DateRangeActivation(_DomainValue):
    """Activation for an inclusive calendar range interpreted by the runtime."""

    mode: Literal["DATE_RANGE"] = "DATE_RANGE"
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("activation start date cannot be after end date")
        return self


ActivationPolicy = Annotated[
    ManualActivation | TradingDayActivation | DateRangeActivation,
    Field(discriminator="mode"),
]


class PriceZone(_DomainValue):
    """One price interval expressed entirely in integer fen."""

    low_fen: PositiveFen
    high_fen: PositiveFen
    include_low: StrictFlag = True
    include_high: StrictFlag = True

    @model_validator(mode="after")
    def validate_bound_order(self) -> Self:
        if self.low_fen > self.high_fen:
            raise ValueError("price zone lower bound cannot exceed upper bound")
        return self


class PriceLevels(_DomainValue):
    """Named plan levels required by the deterministic decision engine."""

    low_buy: PriceZone
    pressure: PriceZone
    risk_line_fen: PositiveFen
    pressure_reference_fen: PositiveFen


class PositionPolicy(_DomainValue):
    """Planned core and tactical quantities in A-share board lots."""

    lot_size: Literal[100] = 100
    max_qty: PositiveBoardLotQuantity
    core_target_qty: BoardLotQuantity = 0
    tactical_target_qty: BoardLotQuantity = 0


class PriceInZoneCondition(_DomainValue):
    """Require the completed price to be inside one named plan zone."""

    type: Literal["PRICE_IN_ZONE"] = "PRICE_IN_ZONE"
    zone: PlanZone


class NoNewLowForBarsCondition(_DomainValue):
    """Require no new episode low for a bounded number of completed bars."""

    type: Literal["NO_NEW_LOW_FOR_BARS"] = "NO_NEW_LOW_FOR_BARS"
    bars: ConditionBars


class NonDecreasingCloseCondition(_DomainValue):
    """Require the latest completed close not to decline."""

    type: Literal["NON_DECREASING_CLOSE"] = "NON_DECREASING_CLOSE"


class VolumeToPreviousLteCondition(_DomainValue):
    """Bound latest completed-bar volume relative to the previous bar."""

    type: Literal["VOLUME_TO_PREVIOUS_LTE"] = "VOLUME_TO_PREVIOUS_LTE"
    max_ratio: BoundedRatio


class VolumeToMedianLteCondition(_DomainValue):
    """Bound latest volume relative to a bounded rolling median window."""

    type: Literal["VOLUME_TO_MEDIAN_LTE"] = "VOLUME_TO_MEDIAN_LTE"
    max_ratio: BoundedRatio
    window_bars: ConditionBars


class MacdHistImprovementGteCondition(_DomainValue):
    """Require a positive minimum MACD histogram improvement."""

    type: Literal["MACD_HIST_IMPROVEMENT_GTE"] = "MACD_HIST_IMPROVEMENT_GTE"
    minimum_improvement: PositiveIndicatorDelta


class PriceReclaimsIndicatorCondition(_DomainValue):
    """Require price to reclaim one named allowlisted indicator."""

    type: Literal["PRICE_RECLAIMS_INDICATOR"] = "PRICE_RECLAIMS_INDICATOR"
    indicator: PlanIndicator


class UpperWickRatioGteCondition(_DomainValue):
    """Require an upper-wick ratio at or above a unit-interval threshold."""

    type: Literal["UPPER_WICK_RATIO_GTE"] = "UPPER_WICK_RATIO_GTE"
    minimum_ratio: UnitRatio


class RetreatFromSessionHighGteCondition(_DomainValue):
    """Require retreat from the session high by a bounded ratio."""

    type: Literal["RETREAT_FROM_SESSION_HIGH_GTE"] = "RETREAT_FROM_SESSION_HIGH_GTE"
    minimum_ratio: UnitRatio


class CloseInBarLowerHalfCondition(_DomainValue):
    """Require the completed close to be in the lower half of its bar."""

    type: Literal["CLOSE_IN_BAR_LOWER_HALF"] = "CLOSE_IN_BAR_LOWER_HALF"


class ConsecutiveClosesBelowLevelCondition(_DomainValue):
    """Require bounded consecutive closes below the pressure reference."""

    type: Literal["CONSECUTIVE_CLOSES_BELOW_LEVEL"] = "CONSECUTIVE_CLOSES_BELOW_LEVEL"
    level: PressureLevel
    bars: ConditionBars


class OfficialCloseBelowLevelCondition(_DomainValue):
    """Require the official daily close below the named risk level."""

    type: Literal["OFFICIAL_CLOSE_BELOW_LEVEL"] = "OFFICIAL_CLOSE_BELOW_LEVEL"
    level: RiskLevel


class NextTradingDayRecoveryCondition(_DomainValue):
    """Require next-trading-day recovery of the named risk level."""

    type: Literal["NEXT_TRADING_DAY_RECOVERY"] = "NEXT_TRADING_DAY_RECOVERY"
    level: RiskLevel


class PositionBucketAvailableCondition(_DomainValue):
    """Require capacity in one named planned position bucket."""

    type: Literal["POSITION_BUCKET_AVAILABLE"] = "POSITION_BUCKET_AVAILABLE"
    bucket: PositionBucket


class SellableQuantityGteCondition(_DomainValue):
    """Require a minimum sellable A-share board-lot quantity."""

    type: Literal["SELLABLE_QUANTITY_GTE"] = "SELLABLE_QUANTITY_GTE"
    quantity: PositiveBoardLotQuantity


class ManualEventRiskClearCondition(_DomainValue):
    """Require the user-controlled material event-risk flag to be clear."""

    type: Literal["MANUAL_EVENT_RISK_CLEAR"] = "MANUAL_EVENT_RISK_CLEAR"


class DistanceFromLimitDownGteCondition(_DomainValue):
    """Require a minimum unit-ratio distance from the daily limit-down price."""

    type: Literal["DISTANCE_FROM_LIMIT_DOWN_GTE"] = "DISTANCE_FROM_LIMIT_DOWN_GTE"
    minimum_ratio: UnitRatio


class LowerBandHitsLteCondition(_DomainValue):
    """Bound lower-Bollinger-band hits inside a bounded rolling window."""

    type: Literal["LOWER_BAND_HITS_LTE"] = "LOWER_BAND_HITS_LTE"
    max_hits: ConditionHitCount
    window_bars: ConditionBars

    @model_validator(mode="after")
    def validate_hit_window(self) -> Self:
        if self.max_hits > self.window_bars:
            raise ValueError("lower-band hit count cannot exceed its window")
        return self


class AllCondition(_DomainValue):
    """Require every child condition to be true."""

    type: Literal["ALL"] = "ALL"
    conditions: tuple[ConditionNode, ...] = Field(
        min_length=1,
        max_length=_MAX_CONDITION_LEAVES,
    )


class AnyCondition(_DomainValue):
    """Require at least one child condition to be true."""

    type: Literal["ANY"] = "ANY"
    conditions: tuple[ConditionNode, ...] = Field(
        min_length=1,
        max_length=_MAX_CONDITION_LEAVES,
    )


ConditionNode = Annotated[
    PriceInZoneCondition
    | NoNewLowForBarsCondition
    | NonDecreasingCloseCondition
    | VolumeToPreviousLteCondition
    | VolumeToMedianLteCondition
    | MacdHistImprovementGteCondition
    | PriceReclaimsIndicatorCondition
    | UpperWickRatioGteCondition
    | RetreatFromSessionHighGteCondition
    | CloseInBarLowerHalfCondition
    | ConsecutiveClosesBelowLevelCondition
    | OfficialCloseBelowLevelCondition
    | NextTradingDayRecoveryCondition
    | PositionBucketAvailableCondition
    | SellableQuantityGteCondition
    | ManualEventRiskClearCondition
    | DistanceFromLimitDownGteCondition
    | LowerBandHitsLteCondition
    | AllCondition
    | AnyCondition,
    Field(discriminator="type"),
]

AllCondition.model_rebuild()
AnyCondition.model_rebuild()


def _condition_tag_and_children(node: object) -> tuple[object, object]:
    if isinstance(node, Mapping):
        return node.get("type"), node.get("conditions")
    return getattr(node, "type", None), getattr(node, "conditions", None)


def _count_condition_leaves(root: object) -> int:
    """Count leaves while failing closed on unsafe raw or validated structure."""

    stack = [(root, 1)]
    seen_composites: set[int] = set()
    leaf_count = 0

    while stack:
        node, depth = stack.pop()
        if depth > _MAX_CONDITION_DEPTH:
            raise ValueError(
                f"condition nesting depth cannot exceed {_MAX_CONDITION_DEPTH}"
            )

        tag, children = _condition_tag_and_children(node)
        if tag not in {"ALL", "ANY"}:
            leaf_count += 1
            if leaf_count > _MAX_CONDITION_LEAVES:
                raise ValueError(
                    f"condition leaf count cannot exceed {_MAX_CONDITION_LEAVES} per plan"
                )
            continue

        identity = id(node)
        if identity in seen_composites:
            raise ValueError("condition tree cannot contain repeated or cyclic composites")
        seen_composites.add(identity)

        if not isinstance(children, Sequence) or isinstance(children, (str, bytes)):
            continue
        if len(children) > _MAX_CONDITION_LEAVES:
            raise ValueError(
                "logical condition cannot contain more than "
                f"{_MAX_CONDITION_LEAVES} children"
            )
        stack.extend((child, depth + 1) for child in children)

    return leaf_count


class _ConditionPolicy(_DomainValue):
    """Validate one policy condition tree before recursive model construction."""

    condition: ConditionNode

    @field_validator("condition", mode="before")
    @classmethod
    def validate_condition_structure(cls, value: object) -> object:
        _count_condition_leaves(value)
        return value


class EntryPolicy(_ConditionPolicy):
    """Typed condition tree that gates entry reminders."""


class ReductionPolicy(_ConditionPolicy):
    """Typed condition tree that gates pressure reduction reminders."""


class RiskPolicy(_ConditionPolicy):
    """Typed condition tree that gates close-risk reminders."""


class BlockerPolicy(_ConditionPolicy):
    """Typed condition tree that must clear before an action is eligible."""


class MonitoringPolicy(_DomainValue):
    """Allowlisted evidence timeframe and indicator formula contract."""

    timeframe_minutes: Literal[5] = 5
    indicator_formula_version: Literal["ta-v1"] = "ta-v1"


class TradePlan(_DomainValue):
    """One immutable, validated version of an executable trade plan."""

    schema_version: Literal[1] = 1
    plan_id: PlanId
    version: PositiveVersion
    symbol: AShareSymbol
    name: PlanName
    market: Market
    metadata: PlanMetadata
    activation: ActivationPolicy
    position: PositionPolicy
    levels: PriceLevels
    entry: EntryPolicy
    reduction: ReductionPolicy
    risk: RiskPolicy
    blockers: BlockerPolicy
    monitoring: MonitoringPolicy

    @model_validator(mode="before")
    @classmethod
    def validate_plan_condition_limits(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data

        leaf_count = 0
        for policy_name in ("entry", "reduction", "risk", "blockers"):
            policy = data.get(policy_name)
            if isinstance(policy, Mapping):
                condition = policy.get("condition")
            else:
                condition = getattr(policy, "condition", None)
            if condition is None:
                continue
            leaf_count += _count_condition_leaves(condition)
            if leaf_count > _MAX_CONDITION_LEAVES:
                raise ValueError(
                    f"condition leaf count cannot exceed {_MAX_CONDITION_LEAVES} per plan"
                )
        return data


__all__ = [
    "AShareSymbol",
    "ActivationPolicy",
    "AllCondition",
    "AnyCondition",
    "BlockerPolicy",
    "BoardLotQuantity",
    "CloseInBarLowerHalfCondition",
    "ConditionNode",
    "ConsecutiveClosesBelowLevelCondition",
    "DateRangeActivation",
    "DistanceFromLimitDownGteCondition",
    "EntryPolicy",
    "LowerBandHitsLteCondition",
    "MacdHistImprovementGteCondition",
    "ManualActivation",
    "ManualEventRiskClearCondition",
    "Market",
    "MonitoringPolicy",
    "NextTradingDayRecoveryCondition",
    "NoNewLowForBarsCondition",
    "NonDecreasingCloseCondition",
    "OfficialCloseBelowLevelCondition",
    "PlanMetadata",
    "PositionBucketAvailableCondition",
    "PositionPolicy",
    "PositiveFen",
    "PriceInZoneCondition",
    "PriceLevels",
    "PriceReclaimsIndicatorCondition",
    "PriceZone",
    "ReductionPolicy",
    "RetreatFromSessionHighGteCondition",
    "RiskPolicy",
    "SellableQuantityGteCondition",
    "TradePlan",
    "TradingDayActivation",
    "UpperWickRatioGteCondition",
    "VolumeToMedianLteCondition",
    "VolumeToPreviousLteCondition",
]
