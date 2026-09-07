"""Typed alert-center and non-mutating diagnostic HTTP adapters."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    DecisionZone,
    EvaluationEvidence,
    EvaluationResult,
    IntradayEvaluationIdentity,
    OfficialCloseEvaluationIdentity,
)
from trade_plan_monitor.domain.plan_models import PositionBucket
from trade_plan_monitor.market_data.aggregation import expected_five_minute_ends
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.notifications.models import (
    AlertEvent,
    AlertPriceZone,
    AlertSeverity,
)
from trade_plan_monitor.state.models import EvaluationKind
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import (
    AuthoritativeDecisionView,
    DataHealthView,
    DecisionEvidenceView,
    EvidenceFactView,
    EvidenceKind,
    NextStepView,
    PositionSummaryView,
)
from trade_plan_monitor.web.schemas import (
    ApiValue,
    MutationContext,
    MutationContextDependency,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["alerts"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_ROWS = 10_000
_MAX_EVIDENCE = 50
_MAX_EXPECTED_REVISION = 9_223_372_036_854_775_806

OffsetQuery = Annotated[int, Query(ge=0, le=_MAX_ROWS)]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
SymbolFilter = Annotated[AShareSymbol | None, Query()]
SignalTypeFilter = Annotated[ActionableSignalType | None, Query(alias="signalType")]
AcknowledgedFilter = Annotated[bool | None, Query()]
StartAtFilter = Annotated[ShanghaiDatetime | None, Query(alias="startAt")]
EndAtFilter = Annotated[ShanghaiDatetime | None, Query(alias="endAt")]
NonNegativeRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_EXPECTED_REVISION),
]
PositiveBoardLotQuantity = Annotated[
    int,
    Field(strict=True, gt=0, multiple_of=100),
]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
Sha256Hex = Annotated[
    str,
    Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class PositionPrefillAction(StrEnum):
    BUY = "BUY"
    CLOSE = "CLOSE"


class PositionPrefillView(ApiValue):
    """Non-submitting form defaults copied from an alert."""

    action: PositionPrefillAction
    symbol: AShareSymbol
    bucket: PositionBucket
    quantity: PositiveBoardLotQuantity
    target_lot_id: str | None = Field(default=None, min_length=1, max_length=128)
    related_alert_id: UUID = Field(strict=False)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.action is PositionPrefillAction.BUY and self.target_lot_id is not None:
            raise ValueError("a buy prefill cannot target an existing lot")
        if self.action is PositionPrefillAction.CLOSE and self.target_lot_id is None:
            raise ValueError("a closure prefill requires a target lot")
        return self


class AlertPriceZoneView(ApiValue):
    zone: Literal[DecisionZone.LOW_BUY, DecisionZone.PRESSURE]
    low_fen: PositiveFen
    high_fen: PositiveFen
    include_low: bool = Field(strict=True)
    include_high: bool = Field(strict=True)


class AlertRecord(ApiValue):
    """Internal service result retaining the canonical persisted alert event."""

    event: AlertEvent
    revision: NonNegativeRevision
    position_prefill: PositionPrefillView | None = None

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        expected_revision = 0 if self.event.acknowledged_at is None else 1
        if self.revision != expected_revision:
            raise ValueError("alert revision must equal its durable acknowledgement state")
        prefill = self.position_prefill
        if prefill is None:
            return self
        event = self.event
        if (
            prefill.symbol != event.symbol
            or prefill.quantity != event.quantity
            or prefill.bucket != event.bucket
            or prefill.target_lot_id != event.target_lot_id
            or prefill.related_alert_id != event.event_id
        ):
            raise ValueError("position prefill must match the canonical alert")
        buys = {
            ActionableSignalType.BUY_CORE_READY,
            ActionableSignalType.BUY_TACTICAL_READY,
        }
        closures = {
            ActionableSignalType.PRESSURE_REDUCE_READY,
            ActionableSignalType.RISK_EXIT_READY,
        }
        if event.signal_type in buys and prefill.action is not PositionPrefillAction.BUY:
            raise ValueError("buy alert requires a buy prefill")
        if event.signal_type in closures and prefill.action is not PositionPrefillAction.CLOSE:
            raise ValueError("reduction alert requires a closure prefill")
        if event.signal_type not in buys | closures:
            raise ValueError("this alert cannot prefill a position command")
        return self


class AlertRecordPage(ApiValue):
    """Internal bounded page before canonical events are projected for JSON."""

    items: tuple[AlertRecord, ...] = Field(default=(), max_length=_MAX_LIMIT)
    symbol: AShareSymbol | None = None
    signal_type: ActionableSignalType | None = None
    acknowledged: bool | None = Field(default=None, strict=True)
    start_at: ShanghaiDatetime | None = None
    end_at: ShanghaiDatetime | None = None
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit or (
            self.items and self.offset + len(self.items) > self.total
        ):
            raise ValueError("alert page metadata is inconsistent")
        identities = tuple(item.event.event_id for item in self.items)
        sequences = tuple(item.event.sequence for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("alert identities must be unique")
        if len(set(sequences)) != len(sequences):
            raise ValueError("alert sequences must be unique")
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("alert time filters must appear together")
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError("alert time filter is reversed")
        return self


class AlertView(ApiValue):
    """One canonical deterministic reminder projected for the local alert center."""

    event_id: UUID = Field(strict=False)
    sequence: Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]
    dedup_key: Sha256Hex
    plan_id: str = Field(strict=True, min_length=1, max_length=128)
    plan_version: Annotated[int, Field(strict=True, gt=0)]
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    name: str = Field(strict=True, min_length=1, max_length=100)
    signal_type: ActionableSignalType
    severity: AlertSeverity
    trading_date: Annotated[date, Field(strict=True)]
    cause_id: str = Field(strict=True, min_length=1, max_length=128)
    evaluated_at: ShanghaiDatetime
    market_data_at: ShanghaiDatetime | None
    data_age_seconds: Annotated[int, Field(strict=True, ge=0)] | None
    price_fen: PositiveFen | None
    quantity: PositiveBoardLotQuantity | None
    bucket: PositionBucket | None
    target_lot_id: str | None = Field(default=None, min_length=1, max_length=128)
    matched_conditions: tuple[DecisionEvidenceView, ...] = Field(
        min_length=1,
        max_length=_MAX_EVIDENCE,
    )
    satisfied_conditions: tuple[DecisionEvidenceView, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE,
    )
    unmet_conditions: tuple[DecisionEvidenceView, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE,
    )
    blockers: tuple[DecisionEvidenceView, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE,
    )
    zone: DecisionZone
    relevant_zone: AlertPriceZoneView | None
    risk_line_fen: PositiveFen | None
    next_step: NextStepView
    message_text: str = Field(strict=True, min_length=1, max_length=16_384)
    created_at: ShanghaiDatetime
    acknowledged_at: ShanghaiDatetime | None = None
    revision: NonNegativeRevision
    position_prefill: PositionPrefillView | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        expected_revision = 0 if self.acknowledged_at is None else 1
        if self.revision != expected_revision:
            raise ValueError("alert revision must equal its acknowledgement state")
        return self


class AlertPage(ApiValue):
    items: tuple[AlertView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    symbol: AShareSymbol | None = None
    signal_type: ActionableSignalType | None = None
    acknowledged: bool | None = Field(default=None, strict=True)
    start_at: ShanghaiDatetime | None = None
    end_at: ShanghaiDatetime | None = None
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit or (
            self.items and self.offset + len(self.items) > self.total
        ):
            raise ValueError("alert page metadata is inconsistent")
        identities = tuple(item.event_id for item in self.items)
        sequences = tuple(item.sequence for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("alert identities must be unique")
        if len(set(sequences)) != len(sequences):
            raise ValueError("alert sequences must be unique")
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("alert time filters must appear together")
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError("alert time filter is reversed")
        return self


class AlertAcknowledgementCommand(ApiValue):
    alert_id: UUID = Field(strict=False)
    expected_revision: NonNegativeRevision


class DiagnosticEvaluationCommand(ApiValue):
    symbol: AShareSymbol
    evaluation_kind: EvaluationKind = Field(strict=False)
    bucket_end: ShanghaiDatetime | None = Field(default=None, strict=False)
    official_trade_date: date | None = Field(default=None, strict=False)
    expected_revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.evaluation_kind is EvaluationKind.INTRADAY:
            if self.bucket_end is None or self.official_trade_date is not None:
                raise ValueError("intraday diagnostic requires only bucket_end")
            try:
                expected_five_minute_ends(self.bucket_end)
            except ValueError:
                raise ValueError("bucket_end must be a canonical session boundary") from None
        elif self.official_trade_date is None or self.bucket_end is not None:
            raise ValueError("official diagnostic requires only official_trade_date")
        return self


class IntradayDiagnosticIdentityView(ApiValue):
    kind: Literal[EvaluationKind.INTRADAY]
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    bucket_end: ShanghaiDatetime
    formula_version: Literal["ta-v1"]

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        try:
            expected_five_minute_ends(self.bucket_end)
        except ValueError:
            raise ValueError("bucket_end must be a canonical session boundary") from None
        return self


class OfficialCloseDiagnosticIdentityView(ApiValue):
    kind: Literal[EvaluationKind.OFFICIAL_CLOSE]
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    official_trade_date: Annotated[date, Field(strict=True)]
    formula_version: Literal["ta-v1"]


DiagnosticEvaluationIdentityView = Annotated[
    IntradayDiagnosticIdentityView | OfficialCloseDiagnosticIdentityView,
    Field(discriminator="kind"),
]


class DiagnosticEvaluationView(ApiValue):
    decision: AuthoritativeDecisionView
    evaluation_identity: DiagnosticEvaluationIdentityView
    source_revision: NonNegativeRevision
    state_mutation_applied: Literal[False]
    alert_enqueued: Literal[False]
    position_changed: Literal[False]
    audited: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.evaluation_identity.symbol != self.decision.symbol
            or self.evaluation_identity.plan_hash != self.decision.plan_hash
        ):
            raise ValueError("diagnostic identity must match the authoritative decision")
        return self


class DiagnosticEvaluationRecord(ApiValue):
    """Internal service result retaining one self-validating canonical result."""

    result: EvaluationResult
    source_revision: NonNegativeRevision
    state_mutation_applied: Literal[False]
    alert_enqueued: Literal[False]
    position_changed: Literal[False]
    audited: bool = Field(strict=True)


class AlertOperationService(Protocol):
    """Application service owning alert queries, acknowledgement, and pure diagnostics."""

    async def list_alerts(
        self,
        *,
        symbol: str | None,
        signal_type: str | None,
        acknowledged: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> AlertRecordPage: ...

    async def acknowledge_alert(
        self,
        *,
        command: AlertAcknowledgementCommand,
        context: MutationContext,
    ) -> AlertRecord: ...

    async def evaluate_diagnostic(
        self,
        *,
        command: DiagnosticEvaluationCommand,
        context: MutationContext,
    ) -> DiagnosticEvaluationRecord: ...


def get_alert_operation_service(request: Request) -> AlertOperationService:
    service = getattr(request.app.state, "alert_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(AlertOperationService, service)


AlertServiceDependency = Annotated[
    AlertOperationService,
    Depends(get_alert_operation_service),
]


def _evidence_view(evidence: EvaluationEvidence) -> DecisionEvidenceView:
    if isinstance(evidence, ConditionEvidence):
        kind = EvidenceKind.CONDITION
        code = evidence.condition.type
        children = tuple(_evidence_view(child) for child in evidence.children)
    else:
        kind = EvidenceKind.RULE
        code = evidence.code.value
        children = ()
    return DecisionEvidenceView(
        kind=kind,
        code=code,
        outcome=evidence.outcome,
        facts=tuple(
            EvidenceFactView(key=fact.key, value=fact.value, unit=fact.unit)
            for fact in evidence.facts
        ),
        missing_inputs=evidence.missing_inputs,
        children=children,
    )


def _zone_view(zone: AlertPriceZone | None) -> AlertPriceZoneView | None:
    if zone is None:
        return None
    return AlertPriceZoneView(
        zone=zone.zone,
        low_fen=zone.low_fen,
        high_fen=zone.high_fen,
        include_low=zone.include_low,
        include_high=zone.include_high,
    )


def _alert_view(record: AlertRecord) -> AlertView:
    event = record.event
    return AlertView(
        event_id=event.event_id,
        sequence=event.sequence,
        dedup_key=event.dedup_key,
        plan_id=event.plan_id,
        plan_version=event.plan_version,
        plan_hash=event.plan_hash,
        symbol=event.symbol,
        name=event.name,
        signal_type=event.signal_type,
        severity=event.severity,
        trading_date=event.trading_date,
        cause_id=event.cause_id,
        evaluated_at=event.evaluated_at,
        market_data_at=event.market_data_at,
        data_age_seconds=event.data_age_seconds,
        price_fen=event.price_fen,
        quantity=event.quantity,
        bucket=event.bucket,
        target_lot_id=event.target_lot_id,
        matched_conditions=tuple(_evidence_view(item) for item in event.matched_conditions),
        satisfied_conditions=tuple(_evidence_view(item) for item in event.satisfied_conditions),
        unmet_conditions=tuple(_evidence_view(item) for item in event.unmet_conditions),
        blockers=tuple(_evidence_view(item) for item in event.blockers),
        zone=event.zone,
        relevant_zone=_zone_view(event.relevant_zone),
        risk_line_fen=event.risk_line_fen,
        next_step=NextStepView(
            code=event.next_step.code,
            not_before=event.next_step.not_before,
            required_inputs=event.next_step.required_inputs,
        ),
        message_text=event.message_text,
        created_at=event.created_at,
        acknowledged_at=event.acknowledged_at,
        revision=record.revision,
        position_prefill=record.position_prefill,
    )


def _diagnostic_identity_view(
    identity: IntradayEvaluationIdentity | OfficialCloseEvaluationIdentity,
) -> DiagnosticEvaluationIdentityView:
    if isinstance(identity, IntradayEvaluationIdentity):
        return IntradayDiagnosticIdentityView(
            kind=EvaluationKind.INTRADAY,
            plan_hash=identity.plan_hash,
            symbol=identity.symbol,
            bucket_end=identity.bucket_end,
            formula_version=identity.formula_version,
        )
    return OfficialCloseDiagnosticIdentityView(
        kind=EvaluationKind.OFFICIAL_CLOSE,
        plan_hash=identity.plan_hash,
        symbol=identity.symbol,
        official_trade_date=identity.official_trade_date,
        formula_version=identity.formula_version,
    )


def _diagnostic_decision_view(result: EvaluationResult) -> AuthoritativeDecisionView:
    snapshot = result.snapshot
    market_data_age = (
        None
        if snapshot.market_data_at is None
        else int((snapshot.evaluated_at - snapshot.market_data_at).total_seconds())
    )
    episode = snapshot.episode
    risk = snapshot.risk
    health = snapshot.data_health
    return AuthoritativeDecisionView(
        symbol=snapshot.symbol,
        result_hash=result.result_hash,
        plan_id=snapshot.plan_id,
        plan_version=snapshot.plan_version,
        plan_hash=snapshot.plan_hash,
        evaluated_at=snapshot.evaluated_at,
        market_data_at=snapshot.market_data_at,
        data_age_seconds=market_data_age,
        price_fen=snapshot.price_fen,
        zone=snapshot.zone,
        signal_type=snapshot.signal_type,
        position=PositionSummaryView(
            core_quantity=snapshot.position.core_quantity,
            tactical_quantity=snapshot.position.tactical_quantity,
            total_quantity=snapshot.position.total_quantity,
            sellable_core_quantity=snapshot.position.sellable_core_quantity,
            sellable_tactical_quantity=snapshot.position.sellable_tactical_quantity,
        ),
        episode_status=None if episode is None else episode.status,
        episode_low_fen=None if episode is None else episode.episode_low_fen,
        risk_status=risk.status,
        risk_breach_trade_date=risk.breach_trade_date,
        data_health=DataHealthView(
            status=health.status,
            latest_bar_end=health.latest_bar_end,
            data_age_seconds=health.data_age_seconds,
            required_data_complete=health.required_data_complete,
            fresh=health.fresh,
        ),
        evidence=tuple(_evidence_view(item) for item in snapshot.condition_evidence),
        next_step=NextStepView(
            code=snapshot.next_step.code,
            not_before=snapshot.next_step.not_before,
            required_inputs=snapshot.next_step.required_inputs,
        ),
    )


def _diagnostic_view(record: DiagnosticEvaluationRecord) -> DiagnosticEvaluationView:
    return DiagnosticEvaluationView(
        decision=_diagnostic_decision_view(record.result),
        evaluation_identity=_diagnostic_identity_view(record.result.evaluation_identity),
        source_revision=record.source_revision,
        state_mutation_applied=record.state_mutation_applied,
        alert_enqueued=record.alert_enqueued,
        position_changed=record.position_changed,
        audited=record.audited,
    )


@router.get("/alerts", response_model=AlertPage)
async def list_alerts(
    service: AlertServiceDependency,
    symbol: SymbolFilter = None,
    signal_type: SignalTypeFilter = None,
    acknowledged: AcknowledgedFilter = None,
    start_at: StartAtFilter = None,
    end_at: EndAtFilter = None,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> AlertPage:
    if (start_at is None) != (end_at is None):
        raise ApiError(ApiErrorCode.BAD_REQUEST)
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ApiError(ApiErrorCode.BAD_REQUEST)
    page = validate_api_response(
        await service.list_alerts(
            symbol=symbol,
            signal_type=signal_type,
            acknowledged=acknowledged,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        ),
        AlertRecordPage,
    )
    if page.offset != offset or page.limit != limit:
        raise RuntimeError("alert service returned mismatched pagination")
    if (
        page.symbol != symbol
        or page.signal_type != signal_type
        or page.acknowledged != acknowledged
        or page.start_at != start_at
        or page.end_at != end_at
    ):
        raise RuntimeError("alert service returned mismatched filters")
    for record in page.items:
        event = record.event
        if symbol is not None and event.symbol != symbol:
            raise RuntimeError("alert service returned a mismatched symbol")
        if signal_type is not None and event.signal_type != signal_type:
            raise RuntimeError("alert service returned a mismatched signal type")
        if acknowledged is not None and (event.acknowledged_at is not None) != acknowledged:
            raise RuntimeError("alert service returned a mismatched acknowledgement state")
        if (
            start_at is not None
            and end_at is not None
            and not (start_at <= event.created_at <= end_at)
        ):
            raise RuntimeError("alert service returned an item outside the requested range")
    return AlertPage(
        items=tuple(_alert_view(item) for item in page.items),
        symbol=page.symbol,
        signal_type=page.signal_type,
        acknowledged=page.acknowledged,
        start_at=page.start_at,
        end_at=page.end_at,
        offset=page.offset,
        limit=page.limit,
        total=page.total,
    )


@router.post("/alert-acknowledgements", response_model=AlertView)
async def acknowledge_alert(
    command: AlertAcknowledgementCommand,
    context: MutationContextDependency,
    service: AlertServiceDependency,
) -> AlertView:
    if command.expected_revision not in {0, 1}:
        raise ApiError(ApiErrorCode.CONFLICT)
    result = validate_api_response(
        await service.acknowledge_alert(command=command, context=context),
        AlertRecord,
    )
    if result.event.event_id != command.alert_id or result.event.acknowledged_at is None:
        raise RuntimeError("alert service returned a mismatched acknowledgement")
    if result.revision != 1:
        raise RuntimeError("acknowledged alert must retain revision one")
    return _alert_view(result)


@router.post("/diagnostic-evaluations", response_model=DiagnosticEvaluationView)
async def evaluate_diagnostic(
    command: DiagnosticEvaluationCommand,
    context: MutationContextDependency,
    service: AlertServiceDependency,
) -> DiagnosticEvaluationView:
    record = validate_api_response(
        await service.evaluate_diagnostic(command=command, context=context),
        DiagnosticEvaluationRecord,
    )
    identity = record.result.evaluation_identity
    if record.source_revision != command.expected_revision or identity.symbol != command.symbol:
        raise RuntimeError("diagnostic service returned a mismatched source identity")
    if command.evaluation_kind is EvaluationKind.INTRADAY:
        if not isinstance(identity, IntradayEvaluationIdentity) or (
            identity.bucket_end != command.bucket_end
        ):
            raise RuntimeError("diagnostic service returned a mismatched target")
    elif not isinstance(identity, OfficialCloseEvaluationIdentity) or (
        identity.official_trade_date != command.official_trade_date
    ):
        raise RuntimeError("diagnostic service returned a mismatched target")
    return _diagnostic_view(record)


__all__ = [
    "AlertAcknowledgementCommand",
    "AlertOperationService",
    "AlertPage",
    "AlertRecord",
    "AlertRecordPage",
    "AlertView",
    "DiagnosticEvaluationCommand",
    "DiagnosticEvaluationRecord",
    "DiagnosticEvaluationView",
    "PositionPrefillView",
    "router",
]
