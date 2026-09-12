"""Pure rule evaluation for the explicit-rules-v1 execution mode."""

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
    """Authoritative inventory facts consumed only by eligible trade rules."""

    status: Literal["KNOWN", "UNKNOWN"]
    total_qty: int | None = Field(ge=0, multiple_of=100)
    sellable_qty: int | None = Field(default=None, ge=0, multiple_of=100)
    inventory_revision: NonNegativeRevision
    missing_reasons: tuple[Literal["POSITION_UNKNOWN", "SELLABLE_QUANTITY_UNKNOWN"], ...] = Field(
        default=(), max_length=2
    )

    @model_validator(mode="before")
    @classmethod
    def fill_legacy_buy_only_shape(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if normalized.get("status") == "UNKNOWN" and "missing_reasons" not in normalized:
            normalized["missing_reasons"] = ("POSITION_UNKNOWN",)
        elif normalized.get("status") == "KNOWN" and "sellable_qty" not in normalized:
            normalized["sellable_qty"] = normalized.get("total_qty")
        return normalized

    @model_validator(mode="after")
    def validate_known_shape(self) -> Self:
        if self.status == "UNKNOWN":
            if self.total_qty is not None or self.sellable_qty is not None:
                raise ValueError("unknown inventory forbids numeric quantities")
            if self.missing_reasons != ("POSITION_UNKNOWN",):
                raise ValueError("unknown inventory requires POSITION_UNKNOWN")
            return self
        if self.total_qty is None:
            raise ValueError("known inventory requires total_qty")
        if self.sellable_qty is None:
            if self.missing_reasons != ("SELLABLE_QUANTITY_UNKNOWN",):
                raise ValueError("unknown sellability requires its missing reason")
        elif self.sellable_qty > self.total_qty or self.missing_reasons:
            raise ValueError("known sellable quantity is inconsistent")
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
    """Reminder-only explicit action; it never represents a fill or reservation."""

    payload_schema_version: Literal["explicit-rule-alert-v1"] = "explicit-rule-alert-v1"
    plan_hash: Sha256Hex
    activation_revision: NonNegativeRevision
    symbol: AShareSymbol
    rule_id: StableIdentifier
    target_bucket_end: ShanghaiDatetime
    action: ExplicitAction
    condition_evidence: ExplicitConditionEvidence
    safety_evidence: ExplicitConditionEvidence | None
    next_step: Literal[
        "REVIEW_BUY_REMINDER",
        "REVIEW_SELL_REMINDER",
        "REVIEW_RISK_REMINDER",
    ] = "REVIEW_BUY_REMINDER"

    @model_validator(mode="after")
    def validate_next_step(self) -> Self:
        expected = {
            "BUY": "REVIEW_BUY_REMINDER",
            "SELL": "REVIEW_SELL_REMINDER",
            "RISK_ALERT": "REVIEW_RISK_REMINDER",
        }[self.action.type]
        if self.next_step != expected:
            raise ValueError("next_step must match the explicit action")
        return self


class ExplicitRuleResult(_ExplicitValue):
    """One rule's evidence, blockers, suppression, action and transition proposal."""

    rule_id: StableIdentifier
    action: ExplicitAction
    condition_evidence: ExplicitConditionEvidence
    safety_evidence: ExplicitConditionEvidence | None
    blockers: tuple[str, ...] = Field(default=(), max_length=8)
    suppression_reason: Literal["ONCE_ALREADY_EMITTED", "TARGET_ALREADY_EMITTED"] | None = None
    state_transition: ExplicitRuleStateTransition | None


class _ExplicitEvaluationPayload(_ExplicitValue):
    result_schema_version: Literal["decision-result-v2"] = "decision-result-v2"
    execution_version: Literal["explicit-rules-v1"] = "explicit-rules-v1"
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    target_bucket_end: ShanghaiDatetime
    evaluated_at: ShanghaiDatetime
    activation_revision: NonNegativeRevision
    inventory_revision: NonNegativeRevision | None
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
        results = {item.rule_id: item for item in self.rule_results}
        if len(results) != len(self.rule_results):
            raise ValueError("explicit result rule IDs must be unique")
        for intent in self.signal_intents:
            item = results.get(intent.rule_id)
            if item is None or item.action != intent.action:
                raise ValueError("signal action must match its rule result")
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
    """Evaluate explicit actions without legacy episodes, buckets, or risk state."""

    states = {state.rule_id: state for state in rule_states}
    if len(states) != len(tuple(rule_states)):
        raise ValueError("rule state snapshots must have unique rule IDs")
    digest = plan_sha256(plan)
    active = _plan_is_active(plan, target_bucket_end.date())
    evaluated_rules: list[
        tuple[ExplicitRule, ExplicitConditionEvidence, ExplicitConditionEvidence | None, list[str]]
    ] = []
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
        evaluated_rules.append((rule, condition, safety, blockers))

    root_states = [_root_state(condition, safety) for _, condition, safety, _ in evaluated_rules]
    action_indexes = {
        rule.action.type: index for index, (rule, _, _, _) in enumerate(evaluated_rules)
    }
    _apply_conflicts(
        plan=plan,
        evaluated_rules=evaluated_rules,
        root_states=root_states,
        action_indexes=action_indexes,
    )

    result_items: list[ExplicitRuleResult] = []
    intents: list[ExplicitSignalIntent] = []
    consumed_inventory = False
    for rule, condition, safety, blockers in evaluated_rules:
        state = _state_for(rule, activation_revision, states)
        suppression: Literal["ONCE_ALREADY_EMITTED", "TARGET_ALREADY_EMITTED"] | None = None
        if state is not None and state.has_emitted:
            if rule.repeat_policy.mode == "ONCE_PER_ACTIVATION":
                suppression = "ONCE_ALREADY_EMITTED"
            elif state.last_emitted_bucket_end == target_bucket_end:
                suppression = "TARGET_ALREADY_EMITTED"

        if not blockers and suppression is None and rule.action.type in {"BUY", "SELL"}:
            consumed_inventory = True
            if inventory.status == "UNKNOWN" or inventory.total_qty is None:
                blockers.append("POSITION_UNKNOWN")
            elif rule.action.type == "BUY":
                if inventory.total_qty + rule.action.quantity > plan.position.max_qty:
                    blockers.append("MAX_POSITION_EXCEEDED")
            elif inventory.sellable_qty is None:
                blockers.append("SELLABLE_QUANTITY_UNKNOWN")
            elif inventory.sellable_qty < rule.action.quantity:
                blockers.append("INSUFFICIENT_SELLABLE_QUANTITY")

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
                next_step={
                    "BUY": "REVIEW_BUY_REMINDER",
                    "SELL": "REVIEW_SELL_REMINDER",
                    "RISK_ALERT": "REVIEW_RISK_REMINDER",
                }[rule.action.type],
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
        inventory_revision=inventory.inventory_revision if consumed_inventory else None,
        manual_event_risk_revision=manual_event_risk_revision,
        rule_results=tuple(result_items),
        signal_intents=tuple(intents),
    )


def _root_state(
    condition: ExplicitConditionEvidence,
    safety: ExplicitConditionEvidence | None,
) -> Literal["TRUE", "FALSE", "UNKNOWN"]:
    outcomes = [condition.outcome]
    if safety is not None:
        outcomes.append(safety.outcome)
    if ConditionOutcome.UNSATISFIED in outcomes:
        return "FALSE"
    if ConditionOutcome.MISSING_INPUT in outcomes:
        return "UNKNOWN"
    return "TRUE"


def _apply_conflicts(
    *,
    plan: ExplicitTradePlan,
    evaluated_rules: list[
        tuple[ExplicitRule, ExplicitConditionEvidence, ExplicitConditionEvidence | None, list[str]]
    ],
    root_states: list[Literal["TRUE", "FALSE", "UNKNOWN"]],
    action_indexes: Mapping[str, int],
) -> None:
    buy_index = action_indexes.get("BUY")
    sell_index = action_indexes.get("SELL")
    risk_index = action_indexes.get("RISK_ALERT")
    if buy_index is not None and sell_index is not None:
        buy_state = root_states[buy_index]
        sell_state = root_states[sell_index]
        if buy_state == sell_state == "TRUE":
            evaluated_rules[buy_index][3].append("TRADE_RULE_CONFLICT")
            evaluated_rules[sell_index][3].append("TRADE_RULE_CONFLICT")
        elif buy_state == "TRUE" and sell_state == "UNKNOWN":
            evaluated_rules[buy_index][3].append("CONFLICT_INPUT_UNKNOWN")
        elif sell_state == "TRUE" and buy_state == "UNKNOWN":
            evaluated_rules[sell_index][3].append("CONFLICT_INPUT_UNKNOWN")

    if risk_index is None:
        return
    risk_state = root_states[risk_index]
    affected = [buy_index]
    if plan.conflict_policy.risk_conflict == "RISK_ONLY":
        affected.append(sell_index)
    for index in affected:
        if index is None or root_states[index] == "FALSE":
            continue
        if risk_state == "TRUE":
            evaluated_rules[index][3].append("RISK_RULE_CONFLICT")
        elif risk_state == "UNKNOWN" and root_states[index] == "TRUE":
            evaluated_rules[index][3].append("CONFLICT_INPUT_UNKNOWN")


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
