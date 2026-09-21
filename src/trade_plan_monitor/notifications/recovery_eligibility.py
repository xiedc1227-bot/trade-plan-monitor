"""Pure, opt-in delivery policy for previously committed explicit risk alerts.

No intent, hash, evaluator state or delivery record is changed here. Callers must
read committed facts and recheck them immediately before eventual send admission.
These injected barrier values do not themselves reconstruct recovery completion.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult
from trade_plan_monitor.decision.models import ConditionOutcome, Sha256Hex
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan, activation_is_eligible_on
from trade_plan_monitor.market_data.aggregation import five_minute_bucket_end
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.notifications.models import ExplicitAlertEvent
from trade_plan_monitor.runtime.clock import _canonical_shanghai


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ActiveExplicitPlan(_Value):
    """Authoritative active-plan read, not a fallback for an unavailable read."""

    plan: ExplicitTradePlan
    activation_revision: int = Field(ge=1)
    activated_at: ShanghaiDatetime
    observed_at: ShanghaiDatetime


class RecoveryBarrierEvidence(_Value):
    """Captured per-plan progress through an exact requested target/generation."""

    symbol: AShareSymbol
    plan_hash: Sha256Hex
    activation_revision: int = Field(ge=1)
    runtime_generation: UUID
    target_bucket_end: ShanghaiDatetime
    reconciled_through: ShanghaiDatetime | None
    pending_obligations: int = Field(ge=0)
    observed_at: ShanghaiDatetime


class RecoveryDeliveryStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    HOLD = "HOLD"
    SUPPRESS = "SUPPRESS"


class RecoveryDeliveryReason(StrEnum):
    ACTIVE_IDENTITY_INVALID = "ACTIVE_IDENTITY_INVALID"
    ACTIVATION_EXPIRED = "ACTIVATION_EXPIRED"
    BARRIER_INCOMPLETE = "BARRIER_INCOMPLETE"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    FUTURE_EVIDENCE = "FUTURE_EVIDENCE"
    RULE_BLOCKED = "RULE_BLOCKED"
    RISK_UNKNOWN = "RISK_UNKNOWN"
    RISK_FALSE = "RISK_FALSE"
    RISK_TRUE = "RISK_TRUE"
    UNSUPPORTED_SIGNAL = "UNSUPPORTED_SIGNAL"


class RecoveryDeliveryDecision(_Value):
    """Classification for the caller to persist; HOLD is never suppression."""

    status: RecoveryDeliveryStatus
    reason: RecoveryDeliveryReason


def _decision(status: str, reason: str) -> RecoveryDeliveryDecision:
    return RecoveryDeliveryDecision(
        status=RecoveryDeliveryStatus(status), reason=RecoveryDeliveryReason(reason),
    )


def classify_explicit_risk_delivery(
    event: ExplicitAlertEvent,
    *,
    active: ActiveExplicitPlan | None,
    latest: ExplicitEvaluationResult | None,
    barrier: RecoveryBarrierEvidence | None,
    target_bucket_end: datetime,
    runtime_generation: UUID,
    now: datetime,
) -> RecoveryDeliveryDecision:
    """Classify one old risk event using the current committed rule evidence.

    ``active=None`` means authoritatively inactive, never a failed database read.
    The caller derives the requested target from its exchange calendar. Missing
    barriers/results, obsolete generations, unknown facts and unexpected blockers
    HOLD. An invalid active identity or fully known false risk SUPPRESS. Repeat
    suppression and empty signal intents do not mean risk has resolved.
    """

    if type(event) is not ExplicitAlertEvent or type(runtime_generation) is not UUID:
        raise TypeError("explicit event and runtime generation must be validated values")
    if active is not None and type(active) is not ActiveExplicitPlan:
        raise TypeError("active must be a validated active-plan read or authoritative absence")
    if latest is not None and type(latest) is not ExplicitEvaluationResult:
        raise TypeError("latest must be a validated explicit evaluation")
    if barrier is not None and type(barrier) is not RecoveryBarrierEvidence:
        raise TypeError("barrier must be validated recovery evidence")
    now = _canonical_shanghai(now)
    target = _canonical_shanghai(target_bucket_end)
    if five_minute_bucket_end(target) != target:
        raise ValueError("delivery target must be a completed five-minute cutoff")
    if event.signal_type != "RISK_ALERT":
        return _decision("HOLD", "UNSUPPORTED_SIGNAL")
    if target > now or event.created_at > now or event.target_bucket_end > target:
        return _decision("HOLD", "FUTURE_EVIDENCE")
    if active is None:
        return _decision("SUPPRESS", "ACTIVE_IDENTITY_INVALID")
    if active.observed_at > now or active.activated_at > active.observed_at:
        return _decision("HOLD", "FUTURE_EVIDENCE")
    plan = active.plan
    if (
        plan.symbol != event.symbol or plan.plan_id != event.plan_id
        or plan.version != event.plan_version or plan_sha256(plan) != event.plan_hash
        or active.activation_revision != event.activation_revision
        or active.activated_at > event.target_bucket_end
    ):
        return _decision("SUPPRESS", "ACTIVE_IDENTITY_INVALID")
    rule = next((item for item in plan.rules if item.rule_id == event.rule_id), None)
    if rule is None or rule.action.type != "RISK_ALERT":
        return _decision("SUPPRESS", "ACTIVE_IDENTITY_INVALID")
    if not all(
        activation_is_eligible_on(plan.activation, day)
        for day in (now.date(), target.date(), event.trading_date)
    ):
        return _decision("SUPPRESS", "ACTIVATION_EXPIRED")
    if barrier is None or (
        barrier.symbol != event.symbol or barrier.plan_hash != event.plan_hash
        or barrier.activation_revision != active.activation_revision
        or barrier.runtime_generation != runtime_generation
        or barrier.target_bucket_end != target or barrier.reconciled_through != target
        or barrier.pending_obligations != 0 or barrier.observed_at > now
        or barrier.observed_at < target
    ):
        return _decision("HOLD", "BARRIER_INCOMPLETE")
    if latest is None:
        return _decision("HOLD", "EVIDENCE_UNAVAILABLE")
    if (
        latest.symbol != event.symbol or latest.plan_hash != event.plan_hash
        or latest.activation_revision != active.activation_revision
        or latest.target_bucket_end != target
    ):
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    if latest.evaluated_at > now or latest.evaluated_at > barrier.observed_at:
        return _decision("HOLD", "FUTURE_EVIDENCE")
    result = next((item for item in latest.rule_results if item.rule_id == event.rule_id), None)
    if result is None or (
        result.action != rule.action
        or result.condition_evidence.condition != rule.condition
        or (result.safety_evidence is None) != (rule.safety_conditions is None)
        or (
            result.safety_evidence is not None
            and result.safety_evidence.condition != rule.safety_conditions
        )
    ):
        return _decision("HOLD", "EVIDENCE_MISMATCH")
    evidence = [result.condition_evidence]
    if result.safety_evidence is not None:
        evidence.append(result.safety_evidence)
    pending = list(evidence)
    while pending:
        item = pending.pop()
        if any(end > target for end in item.bar_ends):
            return _decision("HOLD", "FUTURE_EVIDENCE")
        pending.extend(item.children)
    expected_blockers = set()
    for prefix, item in zip(("CONDITION", "SAFETY"), evidence, strict=False):
        if item.outcome is ConditionOutcome.UNSATISFIED:
            expected_blockers.add(f"{prefix}_UNSATISFIED")
        elif item.outcome is ConditionOutcome.MISSING_INPUT:
            expected_blockers.add(f"{prefix}_INPUT_MISSING")
    if set(result.blockers) != expected_blockers:
        return _decision("HOLD", "RULE_BLOCKED")
    if any(item.outcome is ConditionOutcome.MISSING_INPUT for item in evidence):
        return _decision("HOLD", "RISK_UNKNOWN")
    if any(item.outcome is ConditionOutcome.UNSATISFIED for item in evidence):
        return _decision("SUPPRESS", "RISK_FALSE")
    return _decision("ELIGIBLE", "RISK_TRUE")
