"""Bounded frozen evidence and explicit actions for isolated current-plan research."""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from trade_plan_monitor.backtest.canonical import canonical_decimal
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.time import parse_shanghai_datetime
from trade_plan_monitor.domain.daily_plan_models import FactKind, PositiveWholeQty, Text
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.daily_state_models import DailyOfficialProof


class ResearchValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(self, *, update=None, deep=False):
        if not update:
            return super().model_copy(deep=deep)
        return type(self).model_validate({**self.model_dump(mode="python"), **update})


def _shanghai(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(hours=8):
        raise ValueError("research timestamps require explicit +08:00")
    return value


ResearchTimestamp = Annotated[
    datetime,
    BeforeValidator(
        lambda value: parse_shanghai_datetime(value) if isinstance(value, str) else value
    ),
]


def _exact_decimal(value):
    if type(value) is str:
        if len(value) > 10000:
            raise ValueError("research decimal exceeds bounded canonical grammar")
        try:
            value = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("research decimal is invalid") from error
    if type(value) is not Decimal:
        raise ValueError("research decimal must be an exact decimal string")
    canonical_decimal(value)
    return value


def _confirmed(value):
    if type(value) is not bool or value is not True:
        raise ValueError("review requires explicit confirmed true")
    return value


ExactDecimal = Annotated[Decimal, BeforeValidator(_exact_decimal)]


class ResearchReview(ResearchValue):
    """Frozen research submission declaration; not a historical review timestamp."""

    content_hash: Sha256Hex
    reviewed_at: ResearchTimestamp
    confirmed: Annotated[Literal[True], BeforeValidator(_confirmed)]
    evidence: Text

    _offset = field_validator("reviewed_at")(_shanghai)


class ResearchFactor(ResearchValue):
    trade_date: date
    factor: ExactDecimal = Field(gt=0, allow_inf_nan=False)


class ResearchAdjustmentProof(ResearchValue):
    proof_id: StableIdentifier
    dataset_hash: Sha256Hex
    symbol: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
    provider: Literal["TUSHARE"]
    available_at: ResearchTimestamp
    received_at: ResearchTimestamp
    adjustment_as_of: date
    quote_basis_factor: ExactDecimal = Field(gt=0, allow_inf_nan=False)
    factors: tuple[ResearchFactor, ...] = Field(min_length=1, max_length=1500)
    evidence: Text

    _offset = field_validator("available_at", "received_at")(_shanghai)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.received_at < self.available_at:
            raise ValueError("adjustment receipt precedes availability")
        if self.adjustment_as_of > self.available_at.date():
            raise ValueError("future adjustment anchor is unavailable")
        dates = tuple(f.trade_date for f in self.factors)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("adjustment factor dates must increase strictly")
        if any(day > self.adjustment_as_of for day in dates):
            raise ValueError("factor date follows adjustment anchor")
        return self


class ResearchOperation(ResearchValue):
    operation_id: StableIdentifier
    at: ResearchTimestamp
    order: int = Field(ge=0, le=10000)

    _offset = field_validator("at")(_shanghai)


class ResearchFact(ResearchOperation):
    kind: Literal["FACT"]
    fact_id: StableIdentifier
    fact_kind: FactKind
    trade_date: date
    satisfied: bool
    evidence: Text
    rule_id: StableIdentifier | None = None
    occurrence: int | None = Field(default=None, ge=1, le=10000)
    official_evidence: DailyOfficialProof | None = None

    @model_validator(mode="after")
    def scope(self) -> Self:
        if self.trade_date > self.at.date():
            raise ValueError("future fact date is unavailable")
        if (self.rule_id is None) != (self.occurrence is None):
            raise ValueError("fact signal scope requires rule and occurrence")
        if not self.satisfied and self.fact_kind in {
            "TRADABILITY",
            "FULL_SESSION_SUSPENSION",
            "INDEPENDENT_EVENT",
            "SIGNAL_INVALIDATION",
        }:
            raise ValueError("negative assertions apply only to technical condition facts")
        if self.fact_kind in {"INDEPENDENT_EVENT", "SIGNAL_INVALIDATION"}:
            if not self.satisfied or self.rule_id is None:
                raise ValueError("control facts require positive exact signal scope")
        return self


class ResearchDeactivate(ResearchOperation):
    kind: Literal["DEACTIVATE"]


class ResearchReplace(ResearchOperation):
    kind: Literal["REPLACE"]
    replacement_plan_hash: Sha256Hex
    replacement_version_id: StableIdentifier
    replacement_review: ResearchReview


class ResearchSimulation(ResearchOperation):
    kind: Literal["SIMULATE"]
    rule_id: StableIdentifier | None = None
    occurrence: int | None = Field(default=None, ge=1, le=10000)
    risk_kind: Literal["ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"] | None = None
    quantity: PositiveWholeQty

    @model_validator(mode="after")
    def exact_cause(self) -> Self:
        ordinary = self.rule_id is not None and self.occurrence is not None
        if ordinary == (self.risk_kind is not None):
            raise ValueError("simulation requires exactly one rule occurrence or risk kind")
        if (self.rule_id is None) != (self.occurrence is None):
            raise ValueError("simulation requires exact rule occurrence")
        return self


class ResearchReassessment(ResearchOperation):
    kind: Literal["REASSESS"]
    risk_kind: Literal["ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"]
    removal_evidence: Text


ScriptOperation = Annotated[
    ResearchFact | ResearchDeactivate | ResearchReplace | ResearchSimulation | ResearchReassessment,
    Field(discriminator="kind"),
]


class UnifiedResearchInput(ResearchValue):
    schema_version: Literal["unified-research-input-v1"] = "unified-research-input-v1"
    started_at: ResearchTimestamp
    inventory_known: bool
    review: ResearchReview
    adjustment_proofs: tuple[ResearchAdjustmentProof, ...] = Field(default=(), max_length=1500)
    calendar_extension: tuple[TradingDay, ...] = Field(default=(), max_length=32)
    operations: tuple[ScriptOperation, ...] = Field(default=(), max_length=10000)

    _offset = field_validator("started_at")(_shanghai)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        keys = tuple((o.at, o.order) for o in self.operations)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("operations require unique increasing time/order")
        if len({o.operation_id for o in self.operations}) != len(self.operations):
            raise ValueError("operation IDs must be unique")
        if any(o.at < self.started_at for o in self.operations):
            raise ValueError("operation precedes research start")
        if len({p.proof_id for p in self.adjustment_proofs}) != len(self.adjustment_proofs):
            raise ValueError("adjustment proof IDs must be unique")
        return self
