"""Strict immutable values for deterministic textual alerts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from unicodedata import category
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from trade_plan_monitor.decision.explicit_conditions import ExplicitConditionEvidence
from trade_plan_monitor.decision.explicit_rules import (
    ExplicitEvaluationResult,
    ExplicitSignalIntent,
)
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DecisionZone,
    EvaluationEvidence,
    EvaluationResult,
    NextStep,
    NextStepCode,
    PersistedIdentifier,
    Sha256Hex,
    SignalIntent,
    StableIdentifier,
)
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan, PositionBucket, TradePlan
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.notifications.identity import alert_dedup_key, explicit_alert_dedup_key

AlertName = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=100),
]
PositiveVersion = Annotated[int, Field(strict=True, gt=0)]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
PositiveSequence = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
PositiveBoardLot = Annotated[int, Field(strict=True, gt=0, multiple_of=100)]
MessageText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=16_384),
]
_MAX_ALERT_EVIDENCE = 50
_MAX_ALERT_EVIDENCE_NODES = 250
_MAX_ALERT_FACTS = 512
_MAX_DISPLAY_NUMERIC_DIGITS = 256
_MAX_DISPLAY_INTEGER_MAGNITUDE = 10**_MAX_DISPLAY_NUMERIC_DIGITS
_ACTIONABLE_NEXT_STEPS = {
    ActionableSignalType.BUY_CORE_READY: NextStepCode.RECORD_CONFIRMED_FILL,
    ActionableSignalType.BUY_TACTICAL_READY: NextStepCode.RECORD_CONFIRMED_FILL,
    ActionableSignalType.PRESSURE_REDUCE_READY: NextStepCode.RECORD_CONFIRMED_FILL,
    ActionableSignalType.RISK_BREACH: NextStepCode.WAIT_FOR_NEXT_TRADING_DAY,
    ActionableSignalType.RISK_EXIT_READY: NextStepCode.RECORD_CONFIRMED_FILL,
    ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT: NextStepCode.WAIT_FOR_SETTLEMENT,
}


class _NotificationValue(BaseModel):
    """Close, freeze, and revalidate every public notification value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy one value while validating all public updates."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class AlertSeverity(StrEnum):
    """Closed user-facing urgency vocabulary."""

    INFO = "INFO"
    ACTION = "ACTION"
    RISK = "RISK"
    CRITICAL = "CRITICAL"


_SIGNAL_SEVERITY = {
    ActionableSignalType.BUY_CORE_READY: AlertSeverity.ACTION,
    ActionableSignalType.BUY_TACTICAL_READY: AlertSeverity.ACTION,
    ActionableSignalType.PRESSURE_REDUCE_READY: AlertSeverity.RISK,
    ActionableSignalType.RISK_BREACH: AlertSeverity.RISK,
    ActionableSignalType.RISK_EXIT_READY: AlertSeverity.CRITICAL,
    ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT: AlertSeverity.CRITICAL,
}


def _contains_disallowed_text_character(value: str, *, allow_newline: bool = False) -> bool:
    return any(
        not (allow_newline and character == "\n")
        and category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    )


def _walk_evidence(evidence: EvaluationEvidence) -> Iterator[EvaluationEvidence]:
    yield evidence
    if isinstance(evidence, ConditionEvidence):
        for child in evidence.children:
            yield from _walk_evidence(child)


class AlertPriceZone(_NotificationValue):
    """The plan-owned actionable zone relevant to one alert."""

    zone: Literal[DecisionZone.LOW_BUY, DecisionZone.PRESSURE]
    low_fen: PositiveFen
    high_fen: PositiveFen
    include_low: bool = Field(strict=True)
    include_high: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.low_fen > self.high_fen:
            raise ValueError("alert zone lower bound cannot exceed upper bound")
        return self


class AlertPayload(_NotificationValue):
    """Validated semantic data used to render one actionable reminder."""

    event_id: UUID
    dedup_key: Sha256Hex
    plan_id: StableIdentifier
    plan_version: PositiveVersion
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    name: AlertName
    signal_type: ActionableSignalType
    severity: AlertSeverity
    trading_date: Annotated[date, Field(strict=True)]
    cause_id: StableIdentifier
    evaluated_at: ShanghaiDatetime
    market_data_at: ShanghaiDatetime | None
    data_age_seconds: NonNegativeInteger | None
    price_fen: PositiveFen | None
    quantity: PositiveBoardLot | None
    bucket: PositionBucket | None
    target_lot_id: PersistedIdentifier | None
    matched_conditions: tuple[ConditionEvidence, ...] = Field(
        min_length=1,
        max_length=_MAX_ALERT_EVIDENCE,
    )
    satisfied_conditions: tuple[EvaluationEvidence, ...] = Field(
        max_length=_MAX_ALERT_EVIDENCE,
    )
    unmet_conditions: tuple[EvaluationEvidence, ...] = Field(
        max_length=_MAX_ALERT_EVIDENCE,
    )
    blockers: tuple[EvaluationEvidence, ...] = Field(
        max_length=_MAX_ALERT_EVIDENCE,
    )
    zone: DecisionZone
    relevant_zone: AlertPriceZone | None
    risk_line_fen: PositiveFen | None
    next_step: NextStep

    @field_validator("name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if _contains_disallowed_text_character(value):
            raise ValueError("alert name cannot contain control characters")
        return value

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        signal = SignalIntent(
            signal_type=self.signal_type,
            plan_hash=self.plan_hash,
            symbol=self.symbol,
            trading_date=self.trading_date,
            cause_id=self.cause_id,
            quantity=self.quantity,
            bucket=self.bucket,
            target_lot_id=self.target_lot_id,
            matched_conditions=self.matched_conditions,
            blockers=(),
            next_step=self.next_step,
        )
        if self.dedup_key != alert_dedup_key(signal):
            raise ValueError("dedup_key must match the canonical alert identity")
        if self.severity is not _SIGNAL_SEVERITY[self.signal_type]:
            raise ValueError("severity must match signal type")
        if self.next_step.code is not _ACTIONABLE_NEXT_STEPS[self.signal_type]:
            raise ValueError("next step must match signal type")

        rendered_integers = (
            self.plan_version,
            self.data_age_seconds,
            self.price_fen,
            self.quantity,
            self.risk_line_fen,
            self.relevant_zone.low_fen if self.relevant_zone is not None else None,
            self.relevant_zone.high_fen if self.relevant_zone is not None else None,
        )
        if any(
            value is not None and abs(value) >= _MAX_DISPLAY_INTEGER_MAGNITUDE
            for value in rendered_integers
        ):
            raise ValueError("numeric display exceeds the alert limit")

        market_values = (
            self.market_data_at,
            self.data_age_seconds,
            self.price_fen,
        )
        if any(value is None for value in market_values) and any(
            value is not None for value in market_values
        ):
            raise ValueError("market time, data age, and price must appear together")
        if self.market_data_at is not None:
            if self.market_data_at > self.evaluated_at:
                raise ValueError("market data cannot follow evaluation time")
            expected_age = timedelta(seconds=self.data_age_seconds)
            if self.evaluated_at - self.market_data_at != expected_age:
                raise ValueError("data age must match market and evaluation times")

        if any(
            evidence.outcome is not ConditionOutcome.SATISFIED
            for evidence in self.satisfied_conditions
        ):
            raise ValueError("satisfied conditions must contain only satisfied evidence")
        if any(
            evidence.outcome is ConditionOutcome.SATISFIED for evidence in self.unmet_conditions
        ):
            raise ValueError("unmet conditions cannot contain satisfied evidence")
        if any(evidence.outcome is ConditionOutcome.SATISFIED for evidence in self.blockers):
            raise ValueError("alert blockers cannot be satisfied evidence")
        if any(evidence not in self.satisfied_conditions for evidence in self.matched_conditions):
            raise ValueError("signal evidence must be retained in satisfied conditions")

        evidence_node_count = 0
        fact_count = 0
        result_evidence = self.satisfied_conditions + self.unmet_conditions + self.blockers
        for result_item in result_evidence:
            for evidence in _walk_evidence(result_item):
                evidence_node_count += 1
                fact_count += len(evidence.facts)
                if evidence_node_count > _MAX_ALERT_EVIDENCE_NODES or fact_count > _MAX_ALERT_FACTS:
                    raise ValueError("alert evidence budget exceeded")
                condition = evidence.condition if isinstance(evidence, ConditionEvidence) else None
                for field_name in ("max_ratio", "minimum_ratio", "minimum_improvement"):
                    condition_value = getattr(condition, field_name, None)
                    if (
                        isinstance(condition_value, Decimal)
                        and len(condition_value.as_tuple().digits) > _MAX_DISPLAY_NUMERIC_DIGITS
                    ):
                        raise ValueError("numeric display exceeds the alert limit")
                for fact in evidence.facts:
                    value = fact.value
                    if type(value) is int and abs(value) >= _MAX_DISPLAY_INTEGER_MAGNITUDE:
                        raise ValueError("numeric display exceeds the alert limit")
                    if isinstance(value, Decimal) and len(value.as_tuple().digits) > (
                        _MAX_DISPLAY_NUMERIC_DIGITS
                    ):
                        raise ValueError("numeric display exceeds the alert limit")

        if self.signal_type in {
            ActionableSignalType.BUY_CORE_READY,
            ActionableSignalType.BUY_TACTICAL_READY,
        }:
            if self.zone is not DecisionZone.LOW_BUY:
                raise ValueError("buy alerts must identify the low-buy zone")
            if self.relevant_zone is None or self.relevant_zone.zone is not DecisionZone.LOW_BUY:
                raise ValueError("buy alerts require the low-buy plan zone")
        elif self.signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
            if self.zone is not DecisionZone.PRESSURE:
                raise ValueError("pressure alerts must identify the pressure zone")
            if self.relevant_zone is None or self.relevant_zone.zone is not DecisionZone.PRESSURE:
                raise ValueError("pressure alerts require the pressure plan zone")
        elif self.relevant_zone is not None:
            raise ValueError("risk alerts cannot invent an actionable price zone")
        return self


class AlertEvent(AlertPayload):
    """One sequenced event value ready for later outbox persistence."""

    sequence: PositiveSequence
    message_text: MessageText
    created_at: ShanghaiDatetime
    acknowledged_at: ShanghaiDatetime | None = None

    @field_validator("message_text")
    @classmethod
    def validate_message_text(cls, value: str) -> str:
        if _contains_disallowed_text_character(value, allow_newline=True):
            raise ValueError("message text cannot contain control characters")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.created_at < self.evaluated_at:
            raise ValueError("event cannot be created before evaluation")
        if self.acknowledged_at is not None and self.acknowledged_at < self.created_at:
            raise ValueError("acknowledgement cannot precede event creation")
        payload = AlertPayload.model_validate(
            self.model_dump(
                mode="python",
                round_trip=True,
                exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
            )
        )
        from trade_plan_monitor.notifications.render import render_alert

        if self.message_text != render_alert(payload):
            raise ValueError("message_text must match deterministic rendering")
        return self


class ExplicitAlertPayload(_NotificationValue):
    """Versioned reminder payload for one explicit BUY occurrence."""

    payload_schema_version: Literal["explicit-rule-alert-v1"] = "explicit-rule-alert-v1"
    event_id: UUID
    dedup_key: Sha256Hex
    plan_id: StableIdentifier
    plan_version: PositiveVersion
    plan_hash: Sha256Hex
    activation_revision: NonNegativeInteger
    symbol: AShareSymbol
    name: AlertName
    signal_type: Literal["BUY"] = "BUY"
    severity: Literal[AlertSeverity.ACTION] = AlertSeverity.ACTION
    trading_date: Annotated[date, Field(strict=True)]
    cause_id: StableIdentifier
    rule_id: StableIdentifier
    target_bucket_end: ShanghaiDatetime
    evaluated_at: ShanghaiDatetime
    quantity: PositiveBoardLot
    condition_evidence: ExplicitConditionEvidence
    safety_evidence: ExplicitConditionEvidence | None
    next_step: Literal["REVIEW_BUY_REMINDER"] = "REVIEW_BUY_REMINDER"

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        signal = ExplicitSignalIntent(
            plan_hash=self.plan_hash,
            activation_revision=self.activation_revision,
            symbol=self.symbol,
            rule_id=self.rule_id,
            target_bucket_end=self.target_bucket_end,
            action={"type": "BUY", "quantity": self.quantity},
            condition_evidence=self.condition_evidence,
            safety_evidence=self.safety_evidence,
        )
        if self.dedup_key != explicit_alert_dedup_key(signal):
            raise ValueError("dedup_key must match the explicit alert identity")
        if self.cause_id != self.rule_id:
            raise ValueError("explicit alert cause_id must equal rule_id")
        if self.trading_date != self.target_bucket_end.date():
            raise ValueError("explicit alert trading date must match its target")
        if self.target_bucket_end > self.evaluated_at:
            raise ValueError("explicit alert target cannot follow evaluation")
        return self


class ExplicitAlertEvent(ExplicitAlertPayload):
    """Sequenced durable explicit alert event."""

    sequence: PositiveSequence
    message_text: MessageText
    created_at: ShanghaiDatetime
    acknowledged_at: ShanghaiDatetime | None = None

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.created_at < self.evaluated_at:
            raise ValueError("event cannot be created before evaluation")
        if self.acknowledged_at is not None and self.acknowledged_at < self.created_at:
            raise ValueError("acknowledgement cannot precede event creation")
        payload = ExplicitAlertPayload.model_validate(
            self.model_dump(
                mode="python",
                round_trip=True,
                exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
            )
        )
        from trade_plan_monitor.notifications.render import render_explicit_alert

        if self.message_text != render_explicit_alert(payload):
            raise ValueError("message_text must match deterministic explicit rendering")
        return self


def build_alert_payload(
    *,
    event_id: UUID,
    plan: TradePlan,
    result: EvaluationResult,
) -> AlertPayload:
    """Build render input strictly from one validated plan and decision result."""

    if not isinstance(plan, TradePlan):
        raise TypeError("plan must be a TradePlan")
    if not isinstance(result, EvaluationResult):
        raise TypeError("result must be an EvaluationResult")
    signal = result.signal_intent
    if signal is None:
        raise ValueError("an actionable decision result is required")
    if (
        signal.plan_hash != result.snapshot.plan_hash
        or signal.plan_hash != result.evaluation_identity.plan_hash
    ):
        raise ValueError("decision plan identity is inconsistent")
    from trade_plan_monitor.domain.plan_hash import plan_sha256

    if plan_sha256(plan) != signal.plan_hash:
        raise ValueError("plan hash must match the actionable decision")
    if (
        result.snapshot.plan_id != plan.plan_id
        or result.snapshot.plan_version != plan.version
        or result.snapshot.symbol != plan.symbol
    ):
        raise ValueError("plan metadata must match the actionable decision")

    relevant_zone = None
    if signal.signal_type in {
        ActionableSignalType.BUY_CORE_READY,
        ActionableSignalType.BUY_TACTICAL_READY,
    }:
        plan_zone = plan.levels.low_buy
        relevant_zone = AlertPriceZone(
            zone=DecisionZone.LOW_BUY,
            low_fen=plan_zone.low_fen,
            high_fen=plan_zone.high_fen,
            include_low=plan_zone.include_low,
            include_high=plan_zone.include_high,
        )
    elif signal.signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
        plan_zone = plan.levels.pressure
        relevant_zone = AlertPriceZone(
            zone=DecisionZone.PRESSURE,
            low_fen=plan_zone.low_fen,
            high_fen=plan_zone.high_fen,
            include_low=plan_zone.include_low,
            include_high=plan_zone.include_high,
        )

    snapshot = result.snapshot
    data_age_seconds = None
    if snapshot.market_data_at is not None:
        market_data_age = snapshot.evaluated_at - snapshot.market_data_at
        if market_data_age.microseconds:
            raise ValueError("market data age must be a whole number of seconds")
        data_age_seconds = market_data_age.days * 86_400 + market_data_age.seconds

    return AlertPayload(
        event_id=event_id,
        dedup_key=alert_dedup_key(signal),
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=signal.plan_hash,
        symbol=signal.symbol,
        name=plan.name,
        signal_type=signal.signal_type,
        severity=_SIGNAL_SEVERITY[signal.signal_type],
        trading_date=signal.trading_date,
        cause_id=signal.cause_id,
        evaluated_at=snapshot.evaluated_at,
        market_data_at=snapshot.market_data_at,
        data_age_seconds=data_age_seconds,
        price_fen=snapshot.price_fen,
        quantity=signal.quantity,
        bucket=signal.bucket,
        target_lot_id=signal.target_lot_id,
        matched_conditions=signal.matched_conditions,
        satisfied_conditions=result.satisfied_conditions,
        unmet_conditions=result.unmet_conditions,
        blockers=result.blockers,
        zone=snapshot.zone,
        relevant_zone=relevant_zone,
        risk_line_fen=plan.levels.risk_line_fen,
        next_step=signal.next_step,
    )


def build_explicit_alert_payload(
    *,
    event_id: UUID,
    plan: ExplicitTradePlan,
    result: ExplicitEvaluationResult,
    signal: ExplicitSignalIntent,
) -> ExplicitAlertPayload:
    """Build one explicit alert strictly from matching validated plan/result facts."""

    from trade_plan_monitor.domain.plan_hash import plan_sha256

    if type(plan) is not ExplicitTradePlan:
        raise TypeError("plan must be an ExplicitTradePlan")
    if type(result) is not ExplicitEvaluationResult:
        raise TypeError("result must be an ExplicitEvaluationResult")
    if type(signal) is not ExplicitSignalIntent or signal not in result.signal_intents:
        raise ValueError("signal must belong to the explicit evaluation result")
    if plan_sha256(plan) != result.plan_hash or signal.plan_hash != result.plan_hash:
        raise ValueError("explicit alert plan identity is inconsistent")
    if plan.symbol != result.symbol or signal.symbol != result.symbol:
        raise ValueError("explicit alert symbol identity is inconsistent")
    return ExplicitAlertPayload(
        event_id=event_id,
        dedup_key=explicit_alert_dedup_key(signal),
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=result.plan_hash,
        activation_revision=result.activation_revision,
        symbol=result.symbol,
        name=plan.name,
        trading_date=result.target_bucket_end.date(),
        cause_id=signal.rule_id,
        rule_id=signal.rule_id,
        target_bucket_end=result.target_bucket_end,
        evaluated_at=result.evaluated_at,
        quantity=signal.action.quantity,
        condition_evidence=signal.condition_evidence,
        safety_evidence=signal.safety_evidence,
    )


__all__ = [
    "AlertEvent",
    "AlertPayload",
    "AlertPriceZone",
    "AlertSeverity",
    "ExplicitAlertEvent",
    "ExplicitAlertPayload",
    "build_alert_payload",
    "build_explicit_alert_payload",
]
