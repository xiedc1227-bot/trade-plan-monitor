"""Source-defined pretrade policies; models confer no execution authority."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, PlainSerializer, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty
from trade_plan_monitor.domain.market_exception_models import (
    MarketExceptionRule,
    MarketExceptionTradePlan,
)
from trade_plan_monitor.domain.market_linkage_models import QuantityPolicy
from trade_plan_monitor.domain.unified_plan_models import UnifiedRule
from trade_plan_monitor.market_index.canonical import canonical_decimal

MAX_SAFE = 9_007_199_254_740_991
SafeFen = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE)]
PositiveFen = Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE)]


def decimal_string(value):
    if not isinstance(value, str | Decimal):
        raise ValueError("decimal input must be a string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("decimal input must be numeric") from exc
    canonical_decimal(result)  # Bound expansion before exact-rational arithmetic.
    return result


ExactDecimal = Annotated[Decimal, BeforeValidator(decimal_string),
                         Field(ge=0, allow_inf_nan=False),
                         PlainSerializer(canonical_decimal, return_type=str, when_used="json")]
Rate = Annotated[ExactDecimal, Field(le=1)]
Label = Annotated[str, Field(min_length=1, max_length=2000)]


class FixedSizing(DailyValue):
    mode: Literal["FIXED_Q0"]


class VolatilityTier(DailyValue):
    lower: ExactDecimal
    upper: ExactDecimal | None
    multiplier: Rate


class TierSizing(DailyValue):
    mode: Literal["ATR_RATIO_TIERS"]
    metric: Literal["ATR14_OVER_CLOSE"]
    base_qty: PositiveWholeQty
    tiers: tuple[VolatilityTier, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def contiguous(self):
        if self.tiers[0].lower != 0 or self.tiers[-1].upper is not None:
            raise ValueError("tiers must cover zero through infinity")
        for i, tier in enumerate(self.tiers):
            if tier.upper is not None and tier.upper <= tier.lower:
                raise ValueError("tier must have positive width")
            if i and (self.tiers[i-1].upper != tier.lower
                      or self.tiers[i-1].multiplier < tier.multiplier):
                raise ValueError("tiers must be contiguous and multipliers nonincreasing")
        return self


class Provenance(DailyValue):
    source: Label
    excerpt: Label
    as_of: date | None
    classification: Literal["ESTIMATE"]


class FeeComponent(DailyValue):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z_]+$")
    side: Literal["BUY", "SELL", "BOTH"]
    kind: Literal["TAX", "TRANSFER", "HANDLING"]
    rate: Rate
    included_in: str | None


class FeeSchedule(DailyValue):
    schedule_id: Label
    version: Label
    currency: Literal["CNY"]
    symbols: tuple[str, ...] = Field(min_length=1, max_length=100)
    effective_from: date
    effective_through: date
    provenance: Provenance
    commission_rate: Rate
    minimum_commission_fen: SafeFen
    components: tuple[FeeComponent, ...] = Field(max_length=20)
    buy_slippage_fen: SafeFen
    sell_slippage_fen: SafeFen

    @model_validator(mode="after")
    def valid_schedule(self):
        import re

        if self.effective_through < self.effective_from:
            raise ValueError("fee validity is reversed")
        if len(set(self.symbols)) != len(self.symbols) or any(
                not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", s) for s in self.symbols):
            raise ValueError("fee symbols must be unique exact securities")
        items = {c.id: c for c in self.components}
        if len(items) != len(self.components) or "COMMISSION" in items:
            raise ValueError("duplicate fee component")
        for component in self.components:
            seen = {component.id}
            parent = component.included_in
            while parent not in {None, "COMMISSION"}:
                if parent in seen or parent not in items:
                    raise ValueError("invalid fee inclusion graph")
                seen.add(parent)
                if items[parent].side not in {"BOTH", component.side}:
                    raise ValueError("included fee sides disagree")
                parent = items[parent].included_in
        return self


class NoEconomics(DailyValue):
    mode: Literal["NONE"]


class EconomicsPreview(DailyValue):
    mode: Literal["PREVIEW_ONLY"]
    entry_price_mode: Literal["CONFIRMED_CLOSE_THEN_EXECUTION_QUOTE"]
    target_price_fen: PositiveFen
    risk_price_fen: PositiveFen
    fee_schedule: FeeSchedule

    @model_validator(mode="after")
    def ordered_levels(self):
        if self.risk_price_fen >= self.target_price_fen:
            raise ValueError("risk must be below target")
        return self


class EconomicsGates(DailyValue):
    min_net_reward_fen: SafeFen | None
    min_reward_risk_ratio: Annotated[ExactDecimal, Field(gt=0)] | None

    @model_validator(mode="after")
    def explicit_threshold(self):
        if self.min_net_reward_fen is None and self.min_reward_risk_ratio is None:
            raise ValueError("required economics needs an explicit gate")
        return self


class RequiredEconomics(EconomicsPreview):
    mode: Literal["REQUIRED"]
    gates: EconomicsGates


class LevelEvidence(DailyValue):
    level: Literal["PRESSURE", "RISK"]
    dimension: Literal["PRICE_STRUCTURE", "TREND", "VOLUME_OR_CANDLE", "VOLATILITY"]
    source: Label
    excerpt: Label
    as_of: date | None
    indicator: str | None

    @model_validator(mode="after")
    def indicator_dimension(self):
        if self.indicator in {"MA20", "BOLL_MIDDLE"} and self.dimension != "TREND":
            raise ValueError("MA20 and Bollinger middle are the same trend dimension")
        return self


class PretradePolicy(DailyValue):
    policy_version: Literal["pretrade-policy-v1"]
    sizing: Annotated[FixedSizing | TierSizing, Field(discriminator="mode")]
    economics: Annotated[NoEconomics | EconomicsPreview | RequiredEconomics,
                         Field(discriminator="mode")]
    level_evidence: tuple[LevelEvidence, ...] = Field(max_length=20)


class DerivedQuantityPolicy(DailyValue):
    mode: Literal["DERIVED_MARKET_FACTOR"]
    normal_factor: Literal["1"]
    weak_factor: Literal["0.5"]
    rounding: Literal["LEGAL_FLOOR"]
    capacity_policy: Literal["BLOCK_FULL"]
    signal_quantity_policy: Literal["FREEZE"]


class P2Rule(MarketExceptionRule):
    quantity_policy: Annotated[QuantityPolicy | DerivedQuantityPolicy, Field(discriminator="mode")]
    pretrade_policy: PretradePolicy

    @model_validator(mode="after")
    def sizing_matches(self):
        if isinstance(self.quantity_policy, DerivedQuantityPolicy) != isinstance(
                self.pretrade_policy.sizing, TierSizing):
            raise ValueError("fixed Q0 and derived Q0 must not be mixed")
        return self


class P2TradePlan(MarketExceptionTradePlan):
    schema_version: Literal[8] = 8
    execution_version: Literal["condition-plan-v4"] = "condition-plan-v4"
    ordinary_rules: tuple[P2Rule | UnifiedRule, ...] = Field(max_length=2)
