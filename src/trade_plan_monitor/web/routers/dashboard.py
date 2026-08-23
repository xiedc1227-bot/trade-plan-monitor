"""Typed dashboard read contract over an injected application service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Protocol, Self, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_json

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionOutcome,
    DataHealthStatus,
    DecisionZone,
    EpisodeStatus,
    EvidenceKey,
    EvidenceScalar,
    EvidenceUnit,
    MissingInputCode,
    NextStepCode,
    RiskStatus,
    SignalType,
)
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

if TYPE_CHECKING:
    from trade_plan_monitor.web.routers.health import (
        RuntimeHealthResponse,
        SymbolHealthResponse,
    )
    from trade_plan_monitor.web.routers.symbols import (
        BarInterval,
        BarPage,
        SymbolDetailResponse,
        SymbolEventPage,
        SymbolPage,
    )

router = APIRouter(prefix="/api/v1", tags=["monitor"])

_MAX_SYMBOLS = 10
_MAX_EVIDENCE = 50
_MAX_FACTS = 512
_MAX_MISSING_INPUTS = 16


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ReadModel(BaseModel):
    """Keep public read values closed, immutable, strict, and camelCase-ready."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


def validate_read_response[ReadModelT: ReadModel](
    value: object,
    model_type: type[ReadModelT],
) -> ReadModelT:
    """Revalidate application-service output before it crosses the API boundary."""

    if isinstance(value, model_type):
        value = value.model_dump(mode="python", round_trip=True)
    return model_type.model_validate_json(to_json(value))


class ConnectionStatus(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class EvidenceKind(StrEnum):
    CONDITION = "CONDITION"
    RULE = "RULE"


StableCode = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
Sha256Hex = Annotated[
    str,
    Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]


class EvidenceFactView(ReadModel):
    key: EvidenceKey
    value: EvidenceScalar
    unit: EvidenceUnit


class DecisionEvidenceView(ReadModel):
    kind: EvidenceKind
    code: StableCode
    outcome: ConditionOutcome
    facts: tuple[EvidenceFactView, ...] = Field(default=(), max_length=_MAX_FACTS)
    missing_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=_MAX_MISSING_INPUTS,
    )
    children: tuple[DecisionEvidenceView, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE,
    )

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("evidence fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            child_missing = any(
                child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children
            )
            if not self.missing_inputs and not child_missing:
                raise ValueError("missing evidence must identify unavailable input")
        elif self.missing_inputs:
            raise ValueError("non-missing evidence cannot contain missing inputs")
        return self


class PositionSummaryView(ReadModel):
    core_quantity: NonNegativeInteger
    tactical_quantity: NonNegativeInteger
    total_quantity: NonNegativeInteger
    sellable_core_quantity: NonNegativeInteger
    sellable_tactical_quantity: NonNegativeInteger

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if self.total_quantity != self.core_quantity + self.tactical_quantity:
            raise ValueError("total quantity must equal core plus tactical quantity")
        if self.sellable_core_quantity > self.core_quantity:
            raise ValueError("sellable core quantity cannot exceed core quantity")
        if self.sellable_tactical_quantity > self.tactical_quantity:
            raise ValueError("sellable tactical quantity cannot exceed tactical quantity")
        return self


class DataHealthView(ReadModel):
    status: DataHealthStatus
    latest_bar_end: ShanghaiDatetime | None
    data_age_seconds: NonNegativeInteger | None
    required_data_complete: bool = Field(strict=True)
    fresh: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_health(self) -> Self:
        if (self.latest_bar_end is None) != (self.data_age_seconds is None):
            raise ValueError("latest bar and data age must appear together")
        if self.fresh and self.latest_bar_end is None:
            raise ValueError("fresh health requires a latest bar")
        if self.status is DataHealthStatus.LIVE and (
            not self.fresh or not self.required_data_complete or self.latest_bar_end is None
        ):
            raise ValueError("LIVE health requires fresh complete data")
        if self.status is DataHealthStatus.STALE and self.fresh:
            raise ValueError("STALE health cannot be fresh")
        if self.status in {DataHealthStatus.GAPPED, DataHealthStatus.BLOCKED} and (
            self.required_data_complete
        ):
            raise ValueError("gapped or blocked health cannot be complete")
        return self


class NextStepView(ReadModel):
    code: NextStepCode
    not_before: ShanghaiDatetime | Annotated[date, Field(strict=True)] | None = None
    required_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=_MAX_MISSING_INPUTS,
    )

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError("next-step inputs must be unique")
        return self


class AuthoritativeDecisionView(ReadModel):
    """Display facts copied from one persisted deterministic decision result."""

    symbol: AShareSymbol
    result_hash: Sha256Hex
    plan_id: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    plan_version: Annotated[int, Field(strict=True, gt=0)]
    plan_hash: Sha256Hex
    evaluated_at: ShanghaiDatetime
    market_data_at: ShanghaiDatetime | None
    data_age_seconds: NonNegativeInteger | None
    price_fen: PositiveFen | None
    zone: DecisionZone
    signal_type: SignalType
    position: PositionSummaryView
    episode_status: EpisodeStatus | None
    episode_low_fen: PositiveFen | None
    risk_status: RiskStatus
    risk_breach_trade_date: Annotated[date, Field(strict=True)] | None
    data_health: DataHealthView
    evidence: tuple[DecisionEvidenceView, ...] = Field(default=(), max_length=_MAX_EVIDENCE)
    next_step: NextStepView

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        market_values = (self.market_data_at, self.data_age_seconds, self.price_fen)
        if any(value is None for value in market_values) and any(
            value is not None for value in market_values
        ):
            raise ValueError("market time, data age, and price must appear together")
        if self.market_data_at is not None:
            age = self.evaluated_at - self.market_data_at
            if age < timedelta(0) or int(age.total_seconds()) != self.data_age_seconds:
                raise ValueError("decision data age must match its timestamps")
        if self.data_health.latest_bar_end is not None:
            health_age = self.evaluated_at - self.data_health.latest_bar_end
            if health_age < timedelta(0) or int(health_age.total_seconds()) != (
                self.data_health.data_age_seconds
            ):
                raise ValueError("health data age must match evaluation time")
        if (self.episode_status is None) != (self.episode_low_fen is None):
            raise ValueError("episode status and low must appear together")
        if self.risk_status is RiskStatus.CLEAR:
            if self.risk_breach_trade_date is not None:
                raise ValueError("clear risk cannot retain a breach date")
        elif self.risk_breach_trade_date is None:
            raise ValueError("active risk requires a breach date")
        if (
            self.risk_breach_trade_date is not None
            and self.risk_breach_trade_date > self.evaluated_at.date()
        ):
            raise ValueError("risk breach cannot follow evaluation")
        actionable = {signal.value for signal in ActionableSignalType}
        if (
            self.signal_type.value in actionable
            and self.data_health.status is not DataHealthStatus.LIVE
        ):
            raise ValueError("actionable decisions require LIVE data")
        return self


class SymbolSummaryView(ReadModel):
    symbol: AShareSymbol
    name: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    observed_at: ShanghaiDatetime
    connected: bool = Field(strict=True)
    risk_distance_fen: Annotated[int, Field(strict=True)] | None
    satisfied_condition_count: NonNegativeInteger
    total_condition_count: NonNegativeInteger
    decision: AuthoritativeDecisionView

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.satisfied_condition_count > self.total_condition_count:
            raise ValueError("satisfied conditions cannot exceed total conditions")
        if self.observed_at < self.decision.evaluated_at:
            raise ValueError("summary observation cannot precede its decision")
        if self.decision.symbol != self.symbol:
            raise ValueError("summary and decision symbols must match")
        if not self.connected and self.decision.data_health.status is DataHealthStatus.LIVE:
            raise ValueError("disconnected data cannot be labelled LIVE")
        if self.decision.data_health.status is DataHealthStatus.LIVE and not self.connected:
            raise ValueError("LIVE data requires a connected source")
        return self


class DashboardCounts(ReadModel):
    actionable: NonNegativeInteger
    low_zone_watch: NonNegativeInteger
    blocked: NonNegativeInteger
    risk: NonNegativeInteger
    stale: NonNegativeInteger
    normal: NonNegativeInteger


class DashboardResponse(ReadModel):
    sequence: NonNegativeInteger
    observed_at: ShanghaiDatetime
    connection_status: ConnectionStatus
    data_age_seconds: NonNegativeInteger | None
    counts: DashboardCounts
    symbols: tuple[SymbolSummaryView, ...] = Field(default=(), max_length=_MAX_SYMBOLS)

    @model_validator(mode="after")
    def validate_dashboard(self) -> Self:
        identities = tuple(symbol.symbol for symbol in self.symbols)
        if len(set(identities)) != len(identities):
            raise ValueError("dashboard symbols must be unique")
        if any(symbol.observed_at > self.observed_at for symbol in self.symbols):
            raise ValueError("symbol observation cannot follow dashboard observation")
        if self.connection_status is ConnectionStatus.DISCONNECTED and any(
            symbol.decision.data_health.status is DataHealthStatus.LIVE for symbol in self.symbols
        ):
            raise ValueError("disconnected dashboard cannot contain LIVE symbols")
        return self


class MonitorReadService(Protocol):
    """Application-service surface consumed by the T036 read adapters."""

    async def get_dashboard(self) -> DashboardResponse: ...

    async def list_symbols(self, *, offset: int, limit: int) -> SymbolPage: ...

    async def get_symbol(self, *, symbol: str) -> SymbolDetailResponse | None: ...

    async def list_symbol_bars(
        self,
        *,
        symbol: str,
        interval: BarInterval,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> BarPage | None: ...

    async def list_symbol_events(
        self,
        *,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> SymbolEventPage | None: ...

    async def get_health(self) -> RuntimeHealthResponse: ...

    async def get_symbol_health(self, *, symbol: str) -> SymbolHealthResponse | None: ...


def get_monitor_read_service(request: Request) -> MonitorReadService:
    service = getattr(request.app.state, "monitor_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(MonitorReadService, service)


ReadServiceDependency = Annotated[
    MonitorReadService,
    Depends(get_monitor_read_service),
]


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    service: ReadServiceDependency,
) -> DashboardResponse:
    return validate_read_response(await service.get_dashboard(), DashboardResponse)


__all__ = [
    "AuthoritativeDecisionView",
    "DashboardResponse",
    "MonitorReadService",
    "ReadModel",
    "ReadServiceDependency",
    "SymbolSummaryView",
    "get_monitor_read_service",
    "router",
    "validate_read_response",
]
