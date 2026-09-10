"""Typed dashboard read contract over an injected application service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self, cast

from fastapi import APIRouter, Depends, Request
from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator
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
    IndexConditionType,
    IndexPlanPath,
    MissingInputCode,
    NextStepCode,
    RiskStatus,
    SignalType,
)
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.market_index.identity import (
    Board,
    MarketIndexCode,
    identity_for_index_code,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexFactUnit,
    MarketIndexHealth,
    MarketIndexIssueCode,
    ReturnWindow,
)
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

if TYPE_CHECKING:
    from trade_plan_monitor.web.routers.health import (
        RuntimeHealthResponse,
        SymbolHealthResponse,
    )
    from trade_plan_monitor.web.routers.symbols import (
        BarInterval,
        BarPage,
        SymbolCollectionResponse,
        SymbolDetailProjectionResponse,
        SymbolEventPage,
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
SafeMonitorSequence = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
FiniteDecimal = Annotated[Decimal, Field(strict=True, allow_inf_nan=False)]


class SmaIndicatorFactView(ReadModel):
    formula_id: Literal["SMA"]
    period: Annotated[int, Field(strict=True, ge=2, le=250)]
    value: FiniteDecimal
    unit: Literal[MarketIndexFactUnit.POINTS]
    source_bar_hash: Sha256Hex
    formula_definition_hash: Sha256Hex


class SmaLookbackIndicatorFactView(ReadModel):
    formula_id: Literal["SMA_LOOKBACK"]
    period: Annotated[int, Field(strict=True, ge=2, le=250)]
    lookback: Annotated[int, Field(strict=True, ge=1, le=60)]
    value: FiniteDecimal
    comparison_value: FiniteDecimal
    unit: Literal[MarketIndexFactUnit.POINTS]
    source_bar_hash: Sha256Hex
    formula_definition_hash: Sha256Hex


class ReturnIndicatorFactView(ReadModel):
    formula_id: Literal["RETURN"]
    window: ReturnWindow
    window_size: Annotated[int, Field(strict=True, ge=1, le=250)]
    value: FiniteDecimal
    unit: Literal[MarketIndexFactUnit.RATIO]
    source_bar_hash: Sha256Hex
    formula_definition_hash: Sha256Hex


MarketIndexIndicatorFactView = Annotated[
    SmaIndicatorFactView | SmaLookbackIndicatorFactView | ReturnIndicatorFactView,
    Field(discriminator="formula_id"),
]


class MarketIndexSnapshotView(ReadModel):
    """Plan-neutral projection of one shared board-index snapshot."""

    index_code: MarketIndexCode
    display_name: Annotated[str, Field(strict=True, min_length=1, max_length=32)]
    board: Board
    close_points: FiniteDecimal | None
    prior_close_points: FiniteDecimal | None
    session_change_ratio: FiniteDecimal | None
    completed_bucket_at: ShanghaiDatetime | None
    observed_at: ShanghaiDatetime
    health: MarketIndexHealth
    issues: tuple[MarketIndexIssueCode, ...] = Field(max_length=16)
    indicator_facts: tuple[MarketIndexIndicatorFactView, ...] = Field(
        max_length=50,
    )
    mapped_symbol_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_SYMBOLS)]
    mapping_version: Literal["board-index-map-v1"]
    revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
    snapshot_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_snapshot_projection(self) -> Self:
        expected_board, expected_name = identity_for_index_code(self.index_code)
        if self.board is not expected_board or self.display_name != expected_name:
            raise ValueError("market-index projection identity is inconsistent")
        values = (
            self.close_points,
            self.prior_close_points,
            self.session_change_ratio,
            self.completed_bucket_at,
        )
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("market-index headline facts must appear together")
        if self.health is MarketIndexHealth.LIVE and any(value is None for value in values):
            raise ValueError("LIVE market-index projection requires headline facts")
        if self.completed_bucket_at is not None and self.observed_at < self.completed_bucket_at:
            raise ValueError("market-index observation cannot precede its completed bucket")
        if tuple(dict.fromkeys(self.issues)) != self.issues:
            raise ValueError("market-index issues must be unique")
        identities = tuple(
            fact.model_dump(mode="json", exclude={"value", "comparison_value"})
            for fact in self.indicator_facts
        )
        if len({repr(identity) for identity in identities}) != len(identities):
            raise ValueError("market-index indicator facts must be unique")
        return self


class IndexConditionProgressView(ReadModel):
    satisfied: NonNegativeInteger
    unsatisfied: NonNegativeInteger
    missing: NonNegativeInteger
    total: NonNegativeInteger

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.satisfied + self.unsatisfied + self.missing != self.total:
            raise ValueError("condition progress counts must sum to total")
        return self


class SymbolReferenceMarketView(ReadModel):
    """Plan-specific reference to shared data and server-authored progress only."""

    index_code: MarketIndexCode
    display_name: Annotated[str, Field(strict=True, min_length=1, max_length=32)]
    board: Board
    mapping_version: Literal["board-index-map-v1"]
    snapshot_hash: Sha256Hex | None
    data_at: ShanghaiDatetime | None
    health: MarketIndexHealth
    issues: tuple[MarketIndexIssueCode, ...] = Field(max_length=16)
    condition_progress: IndexConditionProgressView

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        expected_board, expected_name = identity_for_index_code(self.index_code)
        if self.board is not expected_board or self.display_name != expected_name:
            raise ValueError("reference-market projection identity is inconsistent")
        if (self.snapshot_hash is None) != (self.data_at is None):
            raise ValueError("reference-market snapshot hash and cutoff must appear together")
        if tuple(dict.fromkeys(self.issues)) != self.issues:
            raise ValueError("reference-market issues must be unique")
        return self


class IndexConditionEvidenceView(ReadModel):
    """Exact server projection of one plan path's index interpretation."""

    plan_path: IndexPlanPath
    condition_type: IndexConditionType
    index_code: MarketIndexCode
    mapping_version: Literal["board-index-map-v1"]
    snapshot_hash: Sha256Hex | None
    decision_cutoff: ShanghaiDatetime
    data_cutoff: ShanghaiDatetime | None
    formula_id: Literal["SMA", "SMA_LOOKBACK", "RETURN"]
    formula_definition_hash: Sha256Hex | None
    parameters: tuple[EvidenceFactView, ...] = Field(default=(), max_length=8)
    actual_value: FiniteDecimal | None
    comparison_value: FiniteDecimal | None
    unit: MarketIndexFactUnit
    outcome: ConditionOutcome
    missing_inputs: tuple[MissingInputCode, ...] = Field(default=(), max_length=7)

    @model_validator(mode="after")
    def validate_index_evidence(self) -> Self:
        if len({parameter.key for parameter in self.parameters}) != len(self.parameters):
            raise ValueError("index evidence parameters must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("index evidence missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs:
                raise ValueError("missing index evidence requires missing inputs")
            if self.actual_value is not None or self.comparison_value is not None:
                raise ValueError("missing index evidence cannot contain comparison values")
        else:
            if self.missing_inputs:
                raise ValueError("known index evidence cannot contain missing inputs")
            if any(
                value is None
                for value in (
                    self.snapshot_hash,
                    self.data_cutoff,
                    self.formula_definition_hash,
                    self.actual_value,
                    self.comparison_value,
                )
            ):
                raise ValueError("known index evidence requires complete identity and values")
        return self


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

    def _is_certified_official_close_risk_breach(self) -> bool:
        market_data_at = self.market_data_at
        breach_date = self.risk_breach_trade_date
        health = self.data_health
        if (
            self.signal_type is not SignalType.RISK_BREACH
            or self.zone is not DecisionZone.BELOW_RISK
            or self.risk_status is not RiskStatus.BREACHED_PENDING_CONFIRMATION
            or market_data_at is None
            or breach_date is None
            or breach_date != market_data_at.date()
            or (
                market_data_at.hour,
                market_data_at.minute,
                market_data_at.second,
                market_data_at.microsecond,
            )
            != (15, 0, 0, 0)
            or health.status is not DataHealthStatus.STALE
            or not health.required_data_complete
            or health.fresh
            or self.next_step.code is not NextStepCode.WAIT_FOR_NEXT_TRADING_DAY
        ):
            return False
        for evidence in self.evidence:
            if (
                evidence.kind is not EvidenceKind.CONDITION
                or evidence.code != "OFFICIAL_CLOSE_BELOW_LEVEL"
                or evidence.outcome is not ConditionOutcome.SATISFIED
                or evidence.children
                or evidence.missing_inputs
            ):
                continue
            facts = {fact.key: fact for fact in evidence.facts}
            official_close = facts.get("official_close_fen")
            risk_line = facts.get("risk_line_fen")
            official_date = facts.get("official_trade_date")
            if (
                official_close is not None
                and official_close.unit is EvidenceUnit.FEN
                and type(official_close.value) is int
                and official_close.value == self.price_fen
                and risk_line is not None
                and risk_line.unit is EvidenceUnit.FEN
                and type(risk_line.value) is int
                and official_close.value < risk_line.value
                and official_date is not None
                and official_date.unit is EvidenceUnit.DATE
                and type(official_date.value) is date
                and official_date.value == breach_date
            ):
                return True
        return False

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
            and not self._is_certified_official_close_risk_breach()
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
    reference_market: SymbolReferenceMarketView | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.satisfied_condition_count > self.total_condition_count:
            raise ValueError("satisfied conditions cannot exceed total conditions")
        if self.observed_at < self.decision.evaluated_at:
            raise ValueError("summary observation cannot precede its decision")
        if self.decision.symbol != self.symbol:
            raise ValueError("summary and decision symbols must match")
        # `decision.data_health` is immutable evidence at evaluation time;
        # `connected` is the current persisted-symbol plus lifecycle liveness.
        # They intentionally may diverge after a disconnect or restart.
        return self


class DashboardCounts(ReadModel):
    actionable: NonNegativeInteger
    low_zone_watch: NonNegativeInteger
    blocked: NonNegativeInteger
    risk: NonNegativeInteger
    stale: NonNegativeInteger
    normal: NonNegativeInteger


class ProjectionUnavailableReason(StrEnum):
    """Stable, non-sensitive reasons that a read projection does not exist yet."""

    EMPTY_DATABASE = "EMPTY_DATABASE"
    NO_ACTIVE_PLANS = "NO_ACTIVE_PLANS"
    NO_ACTIVE_PLAN = "NO_ACTIVE_PLAN"
    AWAITING_FIRST_EVALUATION = "AWAITING_FIRST_EVALUATION"


class ProjectionUnavailableResponse(ReadModel):
    """An honest successful response when no authoritative dashboard exists."""

    availability: Literal["UNAVAILABLE"]
    observed_at: ShanghaiDatetime
    reason: ProjectionUnavailableReason
    sequence: SafeMonitorSequence
    symbol: AShareSymbol | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.symbol is None and self.reason is ProjectionUnavailableReason.NO_ACTIVE_PLAN:
            raise ValueError("aggregate unavailability cannot use NO_ACTIVE_PLAN")
        if self.symbol is not None and self.reason in {
            ProjectionUnavailableReason.EMPTY_DATABASE,
            ProjectionUnavailableReason.NO_ACTIVE_PLANS,
        }:
            raise ValueError("symbol unavailability cannot use an aggregate reason")
        return self


class DashboardProjectionUnavailableResponse(ReadModel):
    availability: Literal["UNAVAILABLE"]
    observed_at: ShanghaiDatetime
    reason: Literal[
        ProjectionUnavailableReason.EMPTY_DATABASE,
        ProjectionUnavailableReason.NO_ACTIVE_PLANS,
        ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
    ]
    sequence: SafeMonitorSequence


class DashboardResponse(ReadModel):
    sequence: SafeMonitorSequence
    observed_at: ShanghaiDatetime
    runtime_generation: UUID4 | None
    connection_status: ConnectionStatus
    data_age_seconds: NonNegativeInteger | None
    counts: DashboardCounts
    symbols: tuple[SymbolSummaryView, ...] = Field(default=(), max_length=_MAX_SYMBOLS)
    market_indexes: tuple[MarketIndexSnapshotView, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_dashboard(self) -> Self:
        identities = tuple(symbol.symbol for symbol in self.symbols)
        if len(set(identities)) != len(identities):
            raise ValueError("dashboard symbols must be unique")
        if any(symbol.observed_at > self.observed_at for symbol in self.symbols):
            raise ValueError("symbol observation cannot follow dashboard observation")
        connected_count = sum(symbol.connected for symbol in self.symbols)
        if self.connection_status is ConnectionStatus.CONNECTED and connected_count != len(
            self.symbols
        ):
            raise ValueError("connected dashboard requires every current symbol connection")
        if self.connection_status is ConnectionStatus.DISCONNECTED and connected_count != 0:
            raise ValueError("disconnected dashboard cannot contain a current connection")
        index_codes = tuple(item.index_code for item in self.market_indexes)
        if len(set(index_codes)) != len(index_codes):
            raise ValueError("dashboard market-index identities must be unique")
        if index_codes != tuple(sorted(index_codes, key=str)):
            raise ValueError("dashboard market indexes must be sorted by indexCode")
        if any(item.observed_at > self.observed_at for item in self.market_indexes):
            raise ValueError("market-index observation cannot follow dashboard observation")
        return self


DashboardProjectionResponse = DashboardResponse | DashboardProjectionUnavailableResponse


def validate_dashboard_projection(value: object) -> DashboardProjectionResponse:
    """Revalidate either a complete snapshot or the explicit unavailable state."""

    if isinstance(value, ReadModel):
        value = value.model_dump(mode="python", round_trip=True)
    if isinstance(value, Mapping) and value.get("availability") == "UNAVAILABLE":
        return DashboardProjectionUnavailableResponse.model_validate_json(to_json(value))
    return validate_read_response(value, DashboardResponse)


class MonitorReadService(Protocol):
    """Application-service surface consumed by the T036 read adapters."""

    async def get_dashboard(self) -> DashboardProjectionResponse: ...

    async def list_symbols(self, *, offset: int, limit: int) -> SymbolCollectionResponse: ...

    async def get_symbol(
        self,
        *,
        symbol: str,
    ) -> SymbolDetailProjectionResponse | None: ...

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


@router.get(
    "/dashboard",
    response_model=DashboardProjectionResponse,
)
async def get_dashboard(
    service: ReadServiceDependency,
) -> DashboardProjectionResponse:
    return validate_dashboard_projection(await service.get_dashboard())


__all__ = [
    "AuthoritativeDecisionView",
    "DashboardProjectionResponse",
    "DashboardProjectionUnavailableResponse",
    "DashboardResponse",
    "ProjectionUnavailableResponse",
    "IndexConditionEvidenceView",
    "IndexConditionProgressView",
    "MarketIndexSnapshotView",
    "MonitorReadService",
    "ReadModel",
    "ReadServiceDependency",
    "SymbolReferenceMarketView",
    "SymbolSummaryView",
    "get_monitor_read_service",
    "router",
    "validate_dashboard_projection",
    "validate_read_response",
]
