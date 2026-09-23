"""Offline, injected legacy delivery policy; no recovery, persistence or sending."""

from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.decision.models import (
    ConditionOutcome,
    EvaluationResult,
    OfficialCloseEvaluationIdentity,
    PositionLotSnapshot,
    RiskStatus,
    Sha256Hex,
    SignalType,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan, activation_is_eligible_on
from trade_plan_monitor.market_data.aggregation import five_minute_bucket_end
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.notifications.models import AlertEvent, build_alert_payload
from trade_plan_monitor.notifications.recovery_eligibility import (
    RecoveryBarrierEvidence,
    RecoveryDeliveryStatus,
)
from trade_plan_monitor.notifications.recovery_provenance import (
    ProvenLegacyAlertOrigin,
    UnknownLegacyAlertOrigin,
)
from trade_plan_monitor.runtime.clock import _canonical_shanghai


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class UnknownLegacyActivePlan(_Value):
    """An unavailable active-identity read, distinct from authoritative absence."""


class ActiveLegacyPlan(_Value):
    plan: TradePlan
    plan_version_id: str = Field(min_length=1, max_length=100)
    activation_revision: int = Field(ge=1)
    activated_at: ShanghaiDatetime
    observed_at: ShanghaiDatetime


class LegacyInventoryEvidence(_Value):
    """Authoritative inventory at target, selected with the existing evaluator.

    The future reader must certify complete inventory and canonical lot preference,
    including settlement_trade_date, the calendar-certified applicable exchange
    session date at now (which can precede now.date() on a closed day).
    selected_target=None proves
    no target; absent wrapper or sellable=None is unknown. This is not a lot lookup
    and cannot be populated from the historical alert or result position summary.
    """

    symbol: AShareSymbol
    plan_hash: Sha256Hex
    activation_revision: int = Field(ge=1)
    target_bucket_end: ShanghaiDatetime
    observed_at: ShanghaiDatetime
    settlement_trade_date: date
    selected_target: PositionLotSnapshot | None
    sellable: bool | None
    opening_quantity: int = Field(default=0, ge=0)
    opening_sellable_quantity: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_opening_quantity(self):
        if self.opening_sellable_quantity > self.opening_quantity:
            raise ValueError("opening sellability exceeds registered quantity")
        return self


class LegacyCurrentEvidence(_Value):
    """One authoritative committed snapshot, not proof of durable reconstruction.

    All results belong to activation_revision. latest is the latest due OFFICIAL
    result, never an intraday replacement. latest_stage is the latest committed risk
    stage through that result, retained across WAIT; None means unavailable history.
    The caller certifies latest_official_trade_date from authoritative calendar and
    activation obligations through target_bucket_end, with no omitted due closes.
    observed_at must equal now, as must active, inventory and barrier observation
    times: one synchronous authoritative read. Recertify the target on every call;
    closed days may retain the prior completed target, but never an old observation.
    origin_plan permits validation even when the current active plan was replaced.
    latest_occurrence needs separate committed origin proof for repeat supersession.
    """

    origin_plan: TradePlan
    origin_result: EvaluationResult
    latest: EvaluationResult
    latest_stage: EvaluationResult | None
    activation_revision: int = Field(ge=1)
    target_bucket_end: ShanghaiDatetime
    latest_official_trade_date: date
    observed_at: ShanghaiDatetime
    inventory: LegacyInventoryEvidence | None
    latest_occurrence: ProvenLegacyAlertOrigin | None = None


class LegacyRecoveryDeliveryReason(StrEnum):
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    FUTURE_EVIDENCE = "FUTURE_EVIDENCE"
    ACTIVE_IDENTITY_INVALID = "ACTIVE_IDENTITY_INVALID"
    ACTIVATION_EXPIRED = "ACTIVATION_EXPIRED"
    BARRIER_INCOMPLETE = "BARRIER_INCOMPLETE"
    RISK_UNKNOWN = "RISK_UNKNOWN"
    RISK_RESOLVED = "RISK_RESOLVED"
    DIFFERENT_EPISODE = "DIFFERENT_EPISODE"
    STAGE_SUPERSEDED = "STAGE_SUPERSEDED"
    TARGET_INAPPLICABLE = "TARGET_INAPPLICABLE"
    NEWER_EXIT_OCCURRENCE = "NEWER_EXIT_OCCURRENCE"
    CURRENT_INSTRUCTION = "CURRENT_INSTRUCTION"
    UNSUPPORTED_SIGNAL = "UNSUPPORTED_SIGNAL"


class LegacyRecoveryDeliveryDecision(_Value):
    status: RecoveryDeliveryStatus
    reason: LegacyRecoveryDeliveryReason


def _decision(status, reason):
    return LegacyRecoveryDeliveryDecision(
        status=RecoveryDeliveryStatus(status), reason=LegacyRecoveryDeliveryReason(reason),
    )


def _origin_matches(origin, result, plan):
    if type(origin) is not ProvenLegacyAlertOrigin or (
        type(origin.activation_revision) is not int or origin.activation_revision < 1
        or type(origin.plan_version_id) is not str or not 1 <= len(origin.plan_version_id) <= 100
        or type(origin.event) is not AlertEvent
        or type(origin.evaluation_identity) is not OfficialCloseEvaluationIdentity
        or origin.evaluation_identity != result.evaluation_identity
        or origin.result_hash != result.result_hash
    ):
        return False
    try:
        rebuilt = build_alert_payload(event_id=origin.event.event_id, plan=plan, result=result)
    except (ValueError, TypeError):
        return False
    return rebuilt.model_dump(mode="python") == origin.event.model_dump(
        mode="python", exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
    )


def _instruction(value):
    return (value.signal_type, value.cause_id, value.target_lot_id, value.bucket, value.quantity)


def classify_legacy_risk_delivery(
    origin: ProvenLegacyAlertOrigin | UnknownLegacyAlertOrigin,
    *,
    active: ActiveLegacyPlan | UnknownLegacyActivePlan | None,
    current: LegacyCurrentEvidence | None,
    barrier: RecoveryBarrierEvidence | None,
    target_bucket_end: datetime,
    runtime_generation: UUID,
    now: datetime,
) -> LegacyRecoveryDeliveryDecision:
    """Classify existing immutable alert; recheck durable facts before any send.

    No injected value grants delivery authority or discovers missing obligations.
    Inactive=None is authoritative; failed reads use UnknownLegacyActivePlan.
    Proven origin alone never establishes current applicability.
    """
    now, target = _canonical_shanghai(now), _canonical_shanghai(target_bucket_end)
    if type(runtime_generation) is not UUID or five_minute_bucket_end(target) != target:
        raise ValueError("validated generation and completed five-minute target required")
    if type(origin) is UnknownLegacyAlertOrigin or type(active) is UnknownLegacyActivePlan:
        return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
    if type(origin) is not ProvenLegacyAlertOrigin:
        raise TypeError("origin must be proven or explicitly unknown")
    if current is None:
        return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
    if (
        current.observed_at != now or current.target_bucket_end != target
        or not _origin_matches(origin, current.origin_result, current.origin_plan)
    ):
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    event = origin.event
    if event.signal_type not in {
        "RISK_BREACH", "RISK_EXIT_READY", "RISK_EXIT_PENDING_SETTLEMENT",
    }:
        return _decision("HOLD", "UNSUPPORTED_SIGNAL")
    cutoff = datetime.combine(event.trading_date, time(15), tzinfo=target.tzinfo)
    if target > now or event.created_at > now or cutoff > target:
        return _decision("HOLD", "FUTURE_EVIDENCE")
    if active is None:
        return _decision("SUPPRESS", "ACTIVE_IDENTITY_INVALID")
    if type(active) is not ActiveLegacyPlan:
        raise TypeError("active must be a validated identity read")
    plan = active.plan
    if active.observed_at > now or active.activated_at > active.observed_at:
        return _decision("HOLD", "FUTURE_EVIDENCE")
    if active.observed_at != now:
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    if (
        active.plan_version_id != origin.plan_version_id
        or active.activation_revision != origin.activation_revision
        or plan.symbol != event.symbol or plan.plan_id != event.plan_id
        or plan.version != event.plan_version or plan_sha256(plan) != event.plan_hash
        or active.activated_at > cutoff or active.activated_at > event.evaluated_at
    ):
        return _decision("SUPPRESS", "ACTIVE_IDENTITY_INVALID")
    historical = activation_is_eligible_on(plan.activation, event.trading_date)
    delayed_breach = event.signal_type == "RISK_BREACH" and (
        event.created_at.date() > event.trading_date and historical
    )
    if not historical or (not delayed_breach and not all(
        activation_is_eligible_on(plan.activation, day) for day in (now.date(), target.date())
    )):
        return _decision("SUPPRESS", "ACTIVATION_EXPIRED")
    if barrier is None or (
        barrier.symbol != event.symbol or barrier.plan_hash != event.plan_hash
        or barrier.activation_revision != origin.activation_revision
        or barrier.runtime_generation != runtime_generation
        or barrier.target_bucket_end != target or barrier.reconciled_through != target
        or barrier.pending_obligations or barrier.observed_at != now
    ):
        return _decision("HOLD", "BARRIER_INCOMPLETE")
    if current.latest_stage is None or current.inventory is None:
        return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
    latest, stage, inventory = current.latest, current.latest_stage, current.inventory
    if (
        current.activation_revision != origin.activation_revision
        or inventory.symbol != event.symbol or inventory.plan_hash != event.plan_hash
        or inventory.activation_revision != origin.activation_revision
        or inventory.target_bucket_end != target or inventory.observed_at != now
        or not target.date() <= inventory.settlement_trade_date <= now.date()
    ):
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    results = (current.origin_result, latest, stage)
    identities = {}
    for result in results:
        identity, snapshot = result.evaluation_identity, result.snapshot
        if (
            type(identity) is not OfficialCloseEvaluationIdentity
            or identity.plan_hash != event.plan_hash or identity.symbol != event.symbol
            or identity.formula_version != plan.monitoring.indicator_formula_version
            or snapshot.plan_id != plan.plan_id or snapshot.plan_version != plan.version
            or snapshot.evaluated_at > current.observed_at
        ):
            return _decision("HOLD", "EVIDENCE_MISMATCH")
        day = identity.official_trade_date
        if day in identities and identities[day] != result.result_hash:
            return _decision("HOLD", "EVIDENCE_MISMATCH")
        identities[day] = result.result_hash
    latest_day = latest.evaluation_identity.official_trade_date
    stage_day = stage.evaluation_identity.official_trade_date
    risk_stages = {
        SignalType.RISK_BREACH, SignalType.RISK_EXIT_READY,
        SignalType.RISK_EXIT_PENDING_SETTLEMENT, SignalType.RISK_RECOVERED,
    }
    if (
        latest_day != current.latest_official_trade_date
        or not event.trading_date <= stage_day <= latest_day
        or datetime.combine(latest_day, time(15), tzinfo=target.tzinfo) > target
        or stage.snapshot.signal_type not in risk_stages
        or (latest.snapshot.signal_type in risk_stages and latest.result_hash != stage.result_hash)
    ):
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    if any(result.blockers or any(
        item.outcome is ConditionOutcome.MISSING_INPUT
        for item in result.snapshot.condition_evidence
    ) for result in (latest, stage)):
        return _decision("HOLD", "RISK_UNKNOWN")
    if latest.snapshot.signal_type not in risk_stages | {SignalType.WAIT}:
        return _decision("HOLD", "RISK_UNKNOWN")
    risk = latest.snapshot.risk
    if risk.status is RiskStatus.CLEAR:
        return _decision("SUPPRESS", "RISK_RESOLVED")
    if risk.breach_trade_date != current.origin_result.snapshot.risk.breach_trade_date:
        return _decision("SUPPRESS", "DIFFERENT_EPISODE")
    if stage.snapshot.risk.breach_trade_date != risk.breach_trade_date:
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    if event.signal_type == "RISK_BREACH":
        if stage_day > event.trading_date and stage.snapshot.signal_type != SignalType.RISK_BREACH:
            return _decision("SUPPRESS", "STAGE_SUPERSEDED")
        return _decision("ELIGIBLE", "CURRENT_INSTRUCTION")
    lot = inventory.selected_target
    if event.target_lot_id is None:
        if lot is not None or event.bucket is not None or (
            inventory.opening_quantity < event.quantity
        ):
            return _decision("SUPPRESS", "TARGET_INAPPLICABLE")
        opening_sellable = inventory.opening_sellable_quantity >= event.quantity
        if inventory.sellable is None:
            return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
        if inventory.sellable != opening_sellable:
            return _decision("HOLD", "EVIDENCE_MISMATCH")
        if opening_sellable != (event.signal_type == "RISK_EXIT_READY"):
            return _decision("SUPPRESS", "TARGET_INAPPLICABLE")
    else:
        if lot is not None and lot.acquired_trade_date > inventory.settlement_trade_date:
            return _decision("HOLD", "FUTURE_EVIDENCE")
        if lot is None or (
            lot.symbol != event.symbol or lot.lot_id != event.target_lot_id
            or lot.bucket != event.bucket or lot.remaining_quantity < event.quantity
            or event.quantity != plan.position.lot_size
        ):
            return _decision("SUPPRESS", "TARGET_INAPPLICABLE")
        if inventory.sellable is None:
            return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
        if inventory.sellable != (lot.acquired_trade_date < inventory.settlement_trade_date):
            return _decision("HOLD", "EVIDENCE_MISMATCH")
        if inventory.sellable != (event.signal_type == "RISK_EXIT_READY"):
            return _decision("SUPPRESS", "TARGET_INAPPLICABLE")
    signal = latest.signal_intent
    if signal is None:
        return _decision("HOLD", "RISK_UNKNOWN")
    if _instruction(signal) != _instruction(event):
        return _decision("SUPPRESS", "STAGE_SUPERSEDED")
    if latest_day > event.trading_date and event.signal_type == "RISK_EXIT_READY":
        newer = current.latest_occurrence
        if (
            not _origin_matches(newer, latest, plan)
            or newer.activation_revision != origin.activation_revision
            or newer.plan_version_id != origin.plan_version_id
            or newer.event.created_at > min(current.observed_at, barrier.observed_at)
            or _instruction(newer.event) != _instruction(event)
        ):
            return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
        return _decision("SUPPRESS", "NEWER_EXIT_OCCURRENCE")
    return _decision("ELIGIBLE", "CURRENT_INSTRUCTION")
