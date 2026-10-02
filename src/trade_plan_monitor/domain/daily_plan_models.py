"""Closed Schema 4 contracts, independent of the frozen v1–v3 model graphs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from trade_plan_monitor.domain.daily_scope import require_technical_text

Qty = Annotated[int, Field(strict=True, ge=0)]
PositiveQty = Annotated[int, Field(strict=True, gt=0)]
WholeQty = Annotated[int, Field(strict=True, ge=0, multiple_of=100, le=9_007_199_254_740_991)]
PositiveWholeQty = Annotated[
    int, Field(strict=True, gt=0, multiple_of=100, le=9_007_199_254_740_991)
]
Fen = Annotated[int, Field(strict=True, gt=0)]
Offset = Annotated[int, Field(strict=True, ge=0, le=499)]
Number = Annotated[Decimal, Field(allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]
Comparator = Literal["LT", "LTE", "EQ", "GTE", "GT"]
DailyIndicator = Literal[
    "MA20",
    "MA60",
    "MACD_DIF",
    "MACD_DEA",
    "MACD_HIST",
    "RSI14",
    "ATR14",
    "BOLL_LOWER",
    "BOLL_MIDDLE",
    "BOLL_UPPER",
    "BOLL_BANDWIDTH",
]
FactKind = Literal[
    "PRICE_STRUCTURE",
    "VOLUME_OR_CANDLE",
    "TECHNICAL",
    "TRADE_VIABILITY",
    "SIGNAL_INVALIDATION",
    "INDEPENDENT_EVENT",
    "SEVERE_STRUCTURE",
    "SEVERE_DETERIORATION",
    "TRADABILITY",
    "FULL_SESSION_SUSPENSION",
]


class DailyValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    def model_copy(self, *, update=None, deep=False):
        if not update:
            return super().model_copy(deep=deep)
        return type(self).model_validate({**self.model_dump(mode="python"), **update})


class DailyManualActivation(DailyValue):
    mode: Literal["MANUAL"]


class DailyDayActivation(DailyValue):
    mode: Literal["TRADING_DAY"]
    trading_day: date


class DailyRangeActivation(DailyValue):
    mode: Literal["DATE_RANGE"]
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date exceeds end_date")
        return self


DailyActivation = Annotated[
    DailyManualActivation | DailyDayActivation | DailyRangeActivation, Field(discriminator="mode")
]


class DailyMetadata(DailyValue):
    report_at: AwareDatetime | None = None
    reference_price_fen: Fen | None = None


class DailyZone(DailyValue):
    low_fen: Fen
    high_fen: Fen
    include_low: bool = Field(strict=True)
    include_high: bool = Field(strict=True)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.low_fen + (not self.include_low) > self.high_fen - (not self.include_high):
            raise ValueError("range contains no integer-fen tick")
        return self

    def contains(self, price: int | Decimal) -> bool:
        return (price >= self.low_fen if self.include_low else price > self.low_fen) and (
            price <= self.high_fen if self.include_high else price < self.high_fen
        )


class DailyLevels(DailyValue):
    low_buy: DailyZone
    pressure: DailyZone
    risk_line_fen: Fen
    risk_comparison: Literal["LT", "LTE"]

    @model_validator(mode="after")
    def order(self) -> Self:
        if (
            not self.risk_line_fen
            < self.low_buy.low_fen
            <= self.low_buy.high_fen
            < self.pressure.low_fen
            <= self.pressure.high_fen
        ):
            raise ValueError("risk line and nonoverlapping price zones must be ordered")
        return self


class DailyPositionPolicy(DailyValue):
    max_qty: PositiveWholeQty
    core_target_qty: WholeQty
    tactical_target_qty: WholeQty
    allocation_provenance: Literal["EXISTING_CONFIRMED", "PROPOSED"]
    allocation_evidence: Text

    @model_validator(mode="after")
    def total(self) -> Self:
        if self.core_target_qty + self.tactical_target_qty > self.max_qty:
            raise ValueError("proposed allocation exceeds max_qty")
        return self


class DailyTradingRules(DailyValue):
    settlement: Literal["NEXT_EXCHANGE_SESSION"] = "NEXT_EXCHANGE_SESSION"
    tick_size_fen: Literal[1] = 1
    special_state_restrictions: Literal["BLOCK_UNVERIFIED"] = "BLOCK_UNVERIFIED"


class DailyMonitoring(DailyValue):
    timeframe: Literal["DAILY"]
    indicator_formula_version: Literal["daily-ta-v2"]
    price_basis: Literal["QFQ"]
    source_requirement: Literal["ONE_VERIFIED_PROVIDER"]
    comparability_requirement: Literal["CURRENT_QUOTE_BASIS"]
    macd_min_observations: Annotated[int, Field(strict=True, ge=1, le=500)]


class FixedDailyReference(DailyValue):
    mode: Literal["FIXED"]
    value: Number
    unit: Literal["FEN", "INDICATOR"]
    as_of: date
    source: Text


class DynamicDailyReference(DailyValue):
    mode: Literal["DYNAMIC"]
    indicator: DailyIndicator
    formula_version: Literal["daily-ta-v2"]
    parameters: dict[str, int]
    offset: Offset


DailyReference = Annotated[FixedDailyReference | DynamicDailyReference, Field(discriminator="mode")]


class DailyPriceCompare(DailyValue):
    type: Literal["DAILY_PRICE_COMPARE"]
    field: Literal["open", "high", "low", "close"]
    offset: Offset
    comparator: Comparator
    reference: DailyReference


class DailyPriceInRange(DailyValue):
    type: Literal["DAILY_PRICE_IN_RANGE"]
    field: Literal["open", "high", "low", "close"]
    offset: Offset
    range: DailyZone


class DailyVolumeRatio(DailyValue):
    type: Literal["DAILY_VOLUME_RATIO"]
    offset: Offset
    baseline: Literal["PREVIOUS", "MEAN"]
    window: Annotated[int, Field(strict=True, ge=1, le=499)]
    comparator: Comparator
    ratio: Number

    @model_validator(mode="after")
    def window_rule(self) -> Self:
        if self.ratio < 0 or (self.baseline == "PREVIOUS" and self.window != 1):
            raise ValueError("volume ratio/window is invalid")
        return self


class DailyCandleRatio(DailyValue):
    type: Literal["DAILY_CANDLE_RATIO"]
    offset: Offset
    component: Literal["LOWER_WICK", "UPPER_WICK", "BODY"]
    comparator: Comparator
    ratio: Number

    @model_validator(mode="after")
    def ratio_rule(self) -> Self:
        if not 0 <= self.ratio <= 1:
            raise ValueError("candle ratio must be between zero and one")
        return self


class DailyIndicatorCompare(DailyValue):
    type: Literal["DAILY_INDICATOR_COMPARE"]
    indicator: DailyIndicator
    formula_version: Literal["daily-ta-v2"]
    parameters: dict[str, int]
    offset: Offset
    comparator: Comparator
    reference: DailyReference


class DailyCloseSequence(DailyValue):
    type: Literal["DAILY_CLOSE_SEQUENCE"]
    offset: Offset
    sessions: Annotated[int, Field(strict=True, ge=2, le=500)]
    mode: Literal["PAIRWISE_NONDECREASING", "COMPARE_REFERENCE"]
    comparator: Comparator | None
    reference: DailyReference | None

    @model_validator(mode="after")
    def mode_fields(self) -> Self:
        if (self.mode == "COMPARE_REFERENCE") != (
            self.comparator is not None and self.reference is not None
        ):
            raise ValueError("sequence comparison requires explicit reference and comparator")
        if self.mode == "PAIRWISE_NONDECREASING" and (
            self.reference is not None or self.comparator is not None
        ):
            raise ValueError("pairwise sequence forbids reference and comparator")
        return self


class ReviewedDailyFact(DailyValue):
    type: Literal["REVIEWED_FACT"]
    fact_kind: FactKind
    evidence_requirement: Text
    validity_scope: Literal["TRADE_DATE", "SIGNAL"]

    _technical_scope = field_validator("evidence_requirement")(require_technical_text)


class DailyAll(DailyValue):
    type: Literal["ALL"]
    conditions: tuple[DailyCondition, ...] = Field(min_length=1, max_length=50)


class DailyAny(DailyValue):
    type: Literal["ANY"]
    conditions: tuple[DailyCondition, ...] = Field(min_length=1, max_length=50)


DailyCondition = Annotated[
    DailyPriceCompare
    | DailyPriceInRange
    | DailyVolumeRatio
    | DailyCandleRatio
    | DailyIndicatorCompare
    | DailyCloseSequence
    | ReviewedDailyFact
    | DailyAll
    | DailyAny,
    Field(discriminator="type"),
]
DailyAll.model_rebuild()
DailyAny.model_rebuild()


class DailyValidity(DailyRangeActivation):
    mode: Literal["DATE_RANGE"] = "DATE_RANGE"


class DailyIndependentEvent(DailyValue):
    mode: Literal["REVIEWED_INDEPENDENT_EVENT"]
    evidence_requirement: Text

    _technical_scope = field_validator("evidence_requirement")(require_technical_text)


class DailyResetPolicy(DailyValue):
    mode: Literal["LATER_CLOSE_RESET_THEN_CONFIRM"]
    reset_condition: DailyCondition


IndependentSignal = Annotated[DailyIndependentEvent | DailyResetPolicy, Field(discriminator="mode")]


def guarantees_daily_dimension(condition, dimension):
    """Every satisfiable ANY path must prove its group's own independent dimension."""
    if isinstance(condition, DailyAll):
        return any(guarantees_daily_dimension(child, dimension) for child in condition.conditions)
    if isinstance(condition, DailyAny):
        return all(guarantees_daily_dimension(child, dimension) for child in condition.conditions)
    if isinstance(condition, ReviewedDailyFact):
        return (
            condition.fact_kind
            == {
                "price_structure": "PRICE_STRUCTURE",
                "volume_or_candle": "VOLUME_OR_CANDLE",
                "technical": "TECHNICAL",
            }[dimension]
        )
    return isinstance(
        condition,
        {
            "price_structure": (DailyPriceCompare, DailyPriceInRange, DailyCloseSequence),
            "volume_or_candle": (DailyVolumeRatio, DailyCandleRatio),
            "technical": (DailyIndicatorCompare,),
        }[dimension],
    )


def required_daily_observations(condition, macd_min_observations):
    """Account for historical offsets before admitting the bounded 500-bar contract."""
    if isinstance(condition, DailyAll | DailyAny):
        return max(
            required_daily_observations(c, macd_min_observations) for c in condition.conditions
        )
    if isinstance(condition, ReviewedDailyFact):
        return 0

    def warmup(indicator):
        if indicator.startswith("MACD"):
            return macd_min_observations
        return {"MA20": 20, "MA60": 60, "RSI14": 15, "ATR14": 14}.get(indicator, 20)

    offset = condition.offset
    needed = offset + 1
    if isinstance(condition, DailyIndicatorCompare):
        needed = offset + warmup(condition.indicator)
    elif isinstance(condition, DailyVolumeRatio):
        needed = offset + condition.window + 1
    elif isinstance(condition, DailyCloseSequence):
        needed = offset + condition.sessions
    reference = getattr(condition, "reference", None)
    if isinstance(reference, DynamicDailyReference):
        earliest_offset = offset + (
            condition.sessions - 1 if isinstance(condition, DailyCloseSequence) else 0
        )
        needed = max(needed, earliest_offset + reference.offset + warmup(reference.indicator))
    return needed


class DailyEnabledRule(DailyValue):
    status: Literal["ENABLED"]
    side: Literal["BUY", "SELL"]
    rule_id: Identifier
    zone: Literal["LOW_BUY", "PRESSURE"]
    quantity: PositiveWholeQty
    bucket: Literal["TACTICAL"]
    price_structure: DailyCondition
    volume_or_candle: DailyCondition
    technical: DailyCondition
    prerequisites: tuple[DailyCondition, ...] = Field(max_length=10)
    validity: DailyValidity
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"]
    independent_signal: IndependentSignal

    @model_validator(mode="after")
    def zone_rule(self) -> Self:
        if self.zone != ("LOW_BUY" if self.side == "BUY" else "PRESSURE"):
            raise ValueError("ordinary side must use its corresponding price zone")
        for dimension in ("price_structure", "volume_or_candle", "technical"):
            if not guarantees_daily_dimension(getattr(self, dimension), dimension):
                raise ValueError(
                    f"{dimension} must prove its own independent evidence dimension "
                    "on every successful path"
                )
        return self


class DailyDisabledRule(DailyValue):
    status: Literal["DISABLED"]
    side: Literal["BUY", "SELL"]
    reason: Text


DailyOrdinaryRule = Annotated[DailyEnabledRule | DailyDisabledRule, Field(discriminator="status")]
RiskKind = Literal["ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"]


class DailyRiskBranch(DailyValue):
    kind: RiskKind
    involves_core: bool = Field(strict=True)
    scope_evidence: Text
    target_core_qty: WholeQty
    target_tactical_qty: WholeQty
    priority: Annotated[int, Field(strict=True, ge=1, le=3)]
    evidence_mode: Literal["TWO_OFFICIAL_CLOSES", "STRUCTURE_AND_DETERIORATION"]
    suspension_confirmation_policy: (
        Literal["RESUME_FIRST_CLOSE", "RESTART_ADJACENT_PAIR"] | None
    ) = None

    @model_validator(mode="after")
    def branch_contract(self) -> Self:
        require_technical_text(self.scope_evidence)
        expected = {
            "ORDINARY_TECHNICAL": (3, "TWO_OFFICIAL_CLOSES"),
            "SEVERE_TECHNICAL": (2, "STRUCTURE_AND_DETERIORATION"),
        }
        if (self.priority, self.evidence_mode) != expected[self.kind]:
            raise ValueError("risk priority/evidence mode differs from branch contract")
        if (self.kind == "ORDINARY_TECHNICAL") != (self.suspension_confirmation_policy is not None):
            raise ValueError(
                "ordinary risk needs an explicit suspension policy; other branches forbid it"
            )
        return self


class DailyExecutionPolicy(DailyValue):
    confirmation: Literal["OFFICIAL_DAILY_CLOSE"]
    ordinary_window: Literal["NEXT_EXCHANGE_SESSION_ONLY"]
    same_signal: Literal["ONE_PLANNED_QUANTITY"]
    risk_priority: Literal["SEVERE_THEN_ORDINARY"]
    ordinary_conflict: Literal["BLOCK_BOTH"]


class DailyTradePlan(DailyValue):
    schema_version: Literal[4] = 4
    execution_mode: Literal["DAILY_CLOSE_PLAN"] = "DAILY_CLOSE_PLAN"
    execution_version: Literal["daily-close-v1"] = "daily-close-v1"
    plan_id: Identifier
    version: PositiveQty
    symbol: Annotated[str, Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: DailyMetadata
    activation: DailyActivation
    levels: DailyLevels
    position: DailyPositionPolicy
    trading_rules: DailyTradingRules
    monitoring: DailyMonitoring
    ordinary_rules: tuple[DailyOrdinaryRule, ...] = Field(min_length=2, max_length=2)
    risk_branches: tuple[DailyRiskBranch, ...] = Field(min_length=2, max_length=2)
    execution_policy: DailyExecutionPolicy

    @model_validator(mode="before")
    @classmethod
    def bounded_conditions(cls, raw: object) -> object:
        count = 0

        def walk(value: object, depth: int = 1) -> None:
            nonlocal count
            if isinstance(value, dict):
                tag = value.get("type")
                if tag in {"ALL", "ANY"}:
                    if depth >= 4:
                        raise ValueError("daily condition depth exceeds four")
                    for child in value.get("conditions", []):
                        walk(child, depth + 1)
                elif tag and (str(tag).startswith("DAILY_") or tag == "REVIEWED_FACT"):
                    count += 1
                else:
                    for child in value.values():
                        walk(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    walk(child, depth)
            if count > 50:
                raise ValueError("daily condition leaves exceed fifty")

        walk(raw)
        return raw

    @model_validator(mode="after")
    def semantic_contract(self) -> Self:
        if self.market != {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[self.symbol[-2:]]:
            raise ValueError("symbol/market mismatch")
        if {r.side for r in self.ordinary_rules} != {"BUY", "SELL"}:
            raise ValueError("exactly one explicit status per ordinary side is required")
        ids = [r.rule_id for r in self.ordinary_rules if isinstance(r, DailyEnabledRule)]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate rule identity")
        if {b.kind for b in self.risk_branches} != {
            "ORDINARY_TECHNICAL",
            "SEVERE_TECHNICAL",
        }:
            raise ValueError("exactly two distinct technical risk branches required")
        for branch in self.risk_branches:
            if not branch.involves_core and branch.target_core_qty != self.position.core_target_qty:
                raise ValueError("protected CORE target must be retained")
        for rule in self.ordinary_rules:
            if isinstance(rule, DailyEnabledRule):
                conditions = (
                    rule.price_structure,
                    rule.volume_or_candle,
                    rule.technical,
                    *rule.prerequisites,
                )
                if isinstance(rule.independent_signal, DailyResetPolicy):
                    conditions += (rule.independent_signal.reset_condition,)
                if any(
                    required_daily_observations(c, self.monitoring.macd_min_observations) > 500
                    for c in conditions
                ):
                    raise ValueError(
                        "daily condition warmup plus offsets exceeds the 500-bar history contract"
                    )
        tick = self.trading_rules.tick_size_fen
        for zone in (self.levels.low_buy, self.levels.pressure):
            first = ((zone.low_fen + tick - 1) // tick) * tick
            if first == zone.low_fen and not zone.include_low:
                first += tick
            if not zone.contains(first):
                raise ValueError("zone contains no reviewed valid tick")
        return self
