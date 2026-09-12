"""Pure BUY-only rule evaluation for the explicit-rules-v1 execution mode."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trade_plan_monitor.decision.explicit_conditions import (
    ExplicitConditionEvidence,
    evaluate_explicit_condition,
)
from trade_plan_monitor.decision.models import ConditionOutcome, _canonical_json_text
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    DateRangeActivation,
    ExplicitAction,
    ExplicitBuyAction,
    ExplicitRule,
    ExplicitTradePlan,
    TradingDayActivation,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime, TradingDay

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StableIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
NonNegativeRevision = Annotated[int, Field(strict=True, ge=0)]
_RESULT_HASH_DOMAIN = b"decision-result-v2\0"


class ExplicitExecutionCapabilityError(RuntimeError):
    """The bounded R09 evaluator was asked to reinterpret an unsupported action."""

    code = "EXECUTION_CAPABILITY_UNAVAILABLE"


class _ExplicitValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        payload = self.model_dump(mode="python", round_trip=True)
        payload.update(update)
        return type(self).model_validate(payload)


class ExplicitInventorySnapshot(_ExplicitValue):
    """Minimal authoritative inventory fact consumed by a pure BUY decision."""

    status: Literal["KNOWN", "UNKNOWN"]
    total_qty: int | None = Field(ge=0, multiple_of=100)
    inventory_revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_known_shape(self) -> Self:
        if (self.status == "KNOWN") != (self.total_qty is not None):
            raise ValueError("known inventory requires total_qty and unknown inventory forbids it")
        return self


class ExplicitRuleStateSnapshot(_ExplicitValue):
    """Durable occurrence state read before pure repeat-policy evaluation."""

    rule_id: StableIdentifier
    activation_revision: NonNegativeRevision
    revision: NonNegativeRevision
    has_emitted: bool
    last_emitted_bucket_end: ShanghaiDatetime | None

    @model_validator(mode="after")
    def validate_emission_shape(self) -> Self:
        if self.has_emitted != (self.last_emitted_bucket_end is not None):
            raise ValueError("emitted state requires exactly one last emitted target")
        return self


class ExplicitRuleStateTransition(_ExplicitValue):
    """Optimistic transition proposal; persistence decides whether it may commit."""

    rule_id: StableIdentifier
    activation_revision: NonNegativeRevision
    expected_revision: NonNegativeRevision
    next_revision: Annotated[int, Field(strict=True, gt=0)]
    last_emitted_bucket_end: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_revision_step(self) -> Self:
        if self.next_revision != self.expected_revision + 1:
            raise ValueError("rule state transition must advance exactly one revision")
        return self


class ExplicitSignalIntent(_ExplicitValue):
    """Reminder-only explicit BUY request; it never represents a fill or reservation."""

    payload_schema_version: Literal["explicit-rule-alert-v1"] = "explicit-rule-alert-v1"
    plan_hash: Sha256Hex
    activation_revision: NonNegativeRevision
    symbol: AShareSymbol
    rule_id: StableIdentifier
    target_bucket_end: ShanghaiDatetime
    action: ExplicitBuyAction
    condition_evidence: ExplicitConditionEvidence
    safety_evidence: ExplicitConditionEvidence | None
    next_step: Literal["REVIEW_BUY_REMINDER"] = "REVIEW_BUY_REMINDER"


class ExplicitRuleResult(_ExplicitValue):
    """One rule's evidence, blockers, suppression, action and transition proposal."""

    rule_id: StableIdentifier
    action: ExplicitAction
    condition_evidence: ExplicitConditionEvidence
    safety_evidence: ExplicitConditionEvidence | None
    blockers: tuple[str, ...] = Field(default=(), max_length=8)
    suppression_reason: Literal[
        "ONCE_ALREADY_EMITTED", "TARGET_ALREADY_EMITTED"
    ] | None = None
    state_transition: ExplicitRuleStateTransition | None


class _ExplicitEvaluationPayload(_ExplicitValue):
    result_schema_version: Literal["decision-result-v2"] = "decision-result-v2"
    execution_version: Literal["explicit-rules-v1"] = "explicit-rules-v1"
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    target_bucket_end: ShanghaiDatetime
    evaluated_at: ShanghaiDatetime
    activation_revision: NonNegativeRevision
    inventory_revision: NonNegativeRevision
    manual_event_risk_revision: NonNegativeRevision | None
    rule_results: tuple[ExplicitRuleResult, ...] = Field(min_length=1, max_length=3)
    signal_intents: tuple[ExplicitSignalIntent, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.target_bucket_end > self.evaluated_at:
            raise ValueError("evaluation cannot precede its completed target")
        if any(intent.plan_hash != self.plan_hash for intent in self.signal_intents):
            raise ValueError("signal plan hash must match its result")
        if any(intent.symbol != self.symbol for intent in self.signal_intents):
            raise ValueError("signal symbol must match its result")
        if any(
            intent.activation_revision != self.activation_revision
            or intent.target_bucket_end != self.target_bucket_end
            for intent in self.signal_intents
        ):
            raise ValueError("signal occurrence identity must match its result")
        emitted_ids = {intent.rule_id for intent in self.signal_intents}
        transitioned_ids = {
            item.rule_id for item in self.rule_results if item.state_transition is not None
        }
        if emitted_ids != transitioned_ids:
            raise ValueError("every emitted signal requires exactly one state transition")
        return self


class ExplicitEvaluationResult(_ExplicitEvaluationPayload):
    """Deterministic v3 result under a new domain-separated hash contract."""

    result_hash: Sha256Hex

    @classmethod
    def build(cls, **payload: object) -> Self:
        if "result_hash" in payload:
            raise TypeError("build computes result_hash")
        normalized = _ExplicitEvaluationPayload.model_validate(payload)
        values = normalized.model_dump(mode="python", round_trip=True)
        digest = _result_digest(values)
        return cls.model_construct(
            **{name: getattr(normalized, name) for name in _ExplicitEvaluationPayload.model_fields},
            result_hash=digest,
        )

    @model_validator(mode="after")
    def validate_result_hash(self) -> Self:
        expected = _result_digest(
            self.model_dump(mode="python", round_trip=True, exclude={"result_hash"})
        )
        if self.result_hash != expected:
            raise ValueError("result_hash must match the canonical explicit result payload")
        return self


def _result_digest(payload: Mapping[str, object]) -> str:
    canonical = _canonical_json_text(payload).encode("utf-8")
    return sha256(_RESULT_HASH_DOMAIN + canonical).hexdigest()


def _plan_is_active(plan: ExplicitTradePlan, target_date: date) -> bool:
    activation = plan.activation
    if isinstance(activation, TradingDayActivation):
        return activation.trading_day == target_date
    if isinstance(activation, DateRangeActivation):
        return activation.start_date <= target_date <= activation.end_date
    return True


def _state_for(
    rule: ExplicitRule,
    activation_revision: int,
    states: Mapping[str, ExplicitRuleStateSnapshot],
) -> ExplicitRuleStateSnapshot | None:
    state = states.get(rule.rule_id)
    if state is None or state.activation_revision != activation_revision:
        return None
    return state


def evaluate_explicit_rules(
    *,
    plan: ExplicitTradePlan,
    bars: Sequence[FiveMinuteBar],
    trading_calendar: Sequence[TradingDay],
    target_bucket_end: datetime,
    evaluated_at: datetime,
    activation_revision: int,
    inventory: ExplicitInventorySnapshot,
    rule_states: Sequence[ExplicitRuleStateSnapshot],
    manual_event_risk: bool | None = None,
    manual_event_risk_revision: int | None = None,
) -> ExplicitEvaluationResult:
    """Evaluate the bounded R09 BUY subset without legacy episodes or indicators."""

    unsupported = sorted({rule.action.type for rule in plan.rules if rule.action.type != "BUY"})
    if unsupported:
        raise ExplicitExecutionCapabilityError(
            "R09 BUY consumer does not support actions: " + ", ".join(unsupported)
        )
    states = {state.rule_id: state for state in rule_states}
    if len(states) != len(tuple(rule_states)):
        raise ValueError("rule state snapshots must have unique rule IDs")
    result_items: list[ExplicitRuleResult] = []
    intents: list[ExplicitSignalIntent] = []
    digest = plan_sha256(plan)
    active = _plan_is_active(plan, target_bucket_end.date())

    for index, rule in enumerate(plan.rules):
        condition = evaluate_explicit_condition(
            rule.condition,
            bars=bars,
            target_bucket_end=target_bucket_end,
            trading_calendar=trading_calendar,
            plan_path=f"rules[{index}].condition",
            manual_event_risk=manual_event_risk,
        )
        safety = (
            evaluate_explicit_condition(
                rule.safety_conditions,
                bars=bars,
                target_bucket_end=target_bucket_end,
                trading_calendar=trading_calendar,
                plan_path=f"rules[{index}].safety_conditions",
                manual_event_risk=manual_event_risk,
            )
            if rule.safety_conditions is not None
            else None
        )
        blockers: list[str] = []
        if not active:
            blockers.append("PLAN_INACTIVE")
        if condition.outcome is ConditionOutcome.UNSATISFIED:
            blockers.append("CONDITION_UNSATISFIED")
        elif condition.outcome is ConditionOutcome.MISSING_INPUT:
            blockers.append("CONDITION_INPUT_MISSING")
        if safety is not None:
            if safety.outcome is ConditionOutcome.UNSATISFIED:
                blockers.append("SAFETY_UNSATISFIED")
            elif safety.outcome is ConditionOutcome.MISSING_INPUT:
                blockers.append("SAFETY_INPUT_MISSING")
        if inventory.status == "UNKNOWN":
            blockers.append("POSITION_UNKNOWN")
        elif inventory.total_qty + rule.action.quantity > plan.position.max_qty:
            blockers.append("MAX_POSITION_EXCEEDED")

        state = _state_for(rule, activation_revision, states)
        suppression: Literal["ONCE_ALREADY_EMITTED", "TARGET_ALREADY_EMITTED"] | None = None
        if state is not None and state.has_emitted:
            if rule.repeat_policy.mode == "ONCE_PER_ACTIVATION":
                suppression = "ONCE_ALREADY_EMITTED"
            elif state.last_emitted_bucket_end == target_bucket_end:
                suppression = "TARGET_ALREADY_EMITTED"

        transition = None
        if not blockers and suppression is None:
            expected_revision = state.revision if state is not None else 0
            transition = ExplicitRuleStateTransition(
                rule_id=rule.rule_id,
                activation_revision=activation_revision,
                expected_revision=expected_revision,
                next_revision=expected_revision + 1,
                last_emitted_bucket_end=target_bucket_end,
            )
            intent = ExplicitSignalIntent(
                plan_hash=digest,
                activation_revision=activation_revision,
                symbol=plan.symbol,
                rule_id=rule.rule_id,
                target_bucket_end=target_bucket_end,
                action=rule.action,
                condition_evidence=condition,
                safety_evidence=safety,
            )
            intents.append(intent)
        result_items.append(
            ExplicitRuleResult(
                rule_id=rule.rule_id,
                action=rule.action,
                condition_evidence=condition,
                safety_evidence=safety,
                blockers=tuple(blockers),
                suppression_reason=suppression,
                state_transition=transition,
            )
        )

    return ExplicitEvaluationResult.build(
        plan_hash=digest,
        symbol=plan.symbol,
        target_bucket_end=target_bucket_end,
        evaluated_at=evaluated_at,
        activation_revision=activation_revision,
        inventory_revision=inventory.inventory_revision,
        manual_event_risk_revision=manual_event_risk_revision,
        rule_results=tuple(result_items),
        signal_intents=tuple(intents),
    )


__all__ = [
    "ExplicitEvaluationResult",
    "ExplicitExecutionCapabilityError",
    "ExplicitInventorySnapshot",
    "ExplicitRuleResult",
    "ExplicitRuleStateSnapshot",
    "ExplicitRuleStateTransition",
    "ExplicitSignalIntent",
    "evaluate_explicit_rules",
]
