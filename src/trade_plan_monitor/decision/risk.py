"""Pure pressure-reduction and official-close risk orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.decision.conditions import (
    evaluate_condition,
    has_complete_current_day_minutes,
)
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DailyIndicatorProvenance,
    EvaluationContext,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationTarget,
    MissingInputCode,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    SignalIntent,
    SignalType,
)
from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    ConditionNode,
    ConsecutiveClosesBelowLevelCondition,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import DailyBar, ShanghaiDatetime

_PRESSURE_CAUSE_DOMAIN = "pressure-reduction-v1"
_RISK_CAUSE_DOMAIN = "official-close-risk-v1"


class _OrchestrationValue(BaseModel):
    """Close, freeze, and revalidate public orchestration decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

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


class PressureTouchEvidence(_OrchestrationValue):
    """Transient provenance for the first certified pressure-zone minute close."""

    outcome: ConditionOutcome
    touch_at: ShanghaiDatetime | None
    facts: tuple[EvidenceFact, ...] = Field(default=(), max_length=8)
    missing_inputs: tuple[MissingInputCode, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("pressure-touch fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("pressure-touch missing inputs must be unique")
        if self.outcome is ConditionOutcome.SATISFIED:
            if self.touch_at is None or self.missing_inputs:
                raise ValueError("satisfied pressure touch requires one timestamp")
        elif self.touch_at is not None:
            raise ValueError("non-satisfied pressure touch cannot retain a timestamp")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs:
                raise ValueError("missing pressure touch requires a missing input code")
        elif self.missing_inputs:
            raise ValueError("known pressure touch evidence cannot retain missing inputs")
        return self


class PressureReductionEvaluation(_OrchestrationValue):
    """One bounded pressure result for later T024 result assembly."""

    touch_evidence: PressureTouchEvidence
    reduction_evidence: ConditionEvidence | None
    signal_intent: SignalIntent | None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        signal = self.signal_intent
        if signal is None:
            return self
        if self.touch_evidence.outcome is not ConditionOutcome.SATISFIED:
            raise ValueError("pressure intent requires a certified touch")
        if (
            self.reduction_evidence is None
            or self.reduction_evidence.outcome is not ConditionOutcome.SATISFIED
        ):
            raise ValueError("pressure intent requires satisfied reduction evidence")
        if signal.signal_type is not ActionableSignalType.PRESSURE_REDUCE_READY:
            raise ValueError("pressure evaluation can emit only pressure reduction")
        if signal.matched_conditions != (self.reduction_evidence,):
            raise ValueError("pressure intent must retain the complete reduction evidence")
        return self


class OfficialRiskEvidence(_OrchestrationValue):
    """Bounded facts for recovery or continued deterioration."""

    outcome: ConditionOutcome
    facts: tuple[EvidenceFact, ...] = Field(default=(), max_length=16)
    missing_inputs: tuple[MissingInputCode, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("official-risk fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("official-risk missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs:
                raise ValueError("missing official-risk evidence requires a reason")
        elif self.missing_inputs:
            raise ValueError("known official-risk evidence cannot retain missing inputs")
        return self


class OfficialCloseRiskEvaluation(_OrchestrationValue):
    """One bounded official-close result for later T024 result assembly."""

    risk: RiskStateSnapshot
    transition: RiskTransitionIntent | None
    signal_type: SignalType | None
    signal_intent: SignalIntent | None
    risk_evidence: ConditionEvidence
    recovery_evidence: OfficialRiskEvidence | None = None
    deterioration_evidence: OfficialRiskEvidence | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        transition = self.transition
        display = self.signal_type
        signal = self.signal_intent
        if transition is not None and transition.risk != self.risk:
            raise ValueError("official-risk transition must carry the returned state")
        if display not in {
            None,
            SignalType.RISK_BREACH,
            SignalType.RISK_RECOVERED,
            SignalType.RISK_EXIT_READY,
            SignalType.RISK_EXIT_PENDING_SETTLEMENT,
        }:
            raise ValueError("official-risk result has an unsupported display signal")
        if signal is not None:
            if display is None:
                raise ValueError("official-risk intent requires a display signal")
            if signal.signal_type.value != display.value:
                raise ValueError("official-risk intent and display signal must agree")
        elif display not in {None, SignalType.RISK_RECOVERED}:
            raise ValueError("actionable official-risk display requires an intent")

        if display is None:
            if transition is not None:
                raise ValueError("official-risk transition requires a display signal")
            if (
                self.recovery_evidence is not None
                and self.recovery_evidence.outcome is ConditionOutcome.SATISFIED
            ):
                raise ValueError("satisfied recovery evidence requires a recovered transition")
            return self

        if display is SignalType.RISK_RECOVERED:
            if transition is None or self.risk.status is not RiskStatus.CLEAR:
                raise ValueError("recovered display requires a CLEAR risk transition")
            if signal is not None:
                raise ValueError("recovery is not an actionable signal")
            if (
                self.recovery_evidence is None
                or self.recovery_evidence.outcome is not ConditionOutcome.SATISFIED
            ):
                raise ValueError("recovered display requires satisfied recovery evidence")
            if self.risk_evidence.outcome is not ConditionOutcome.UNSATISFIED:
                raise ValueError("recovered display requires a close at or above the risk line")
            return self

        if signal is None or self.risk_evidence.outcome is not ConditionOutcome.SATISFIED:
            raise ValueError("actionable official-risk result requires satisfied risk evidence")
        if display is SignalType.RISK_BREACH:
            if (
                transition is None
                or self.risk.status is not RiskStatus.BREACHED_PENDING_CONFIRMATION
            ):
                raise ValueError("risk breach requires a BREACHED transition")
            if self.recovery_evidence is not None or self.deterioration_evidence is not None:
                raise ValueError("first risk breach cannot carry follow-up evidence")
        elif display is SignalType.RISK_EXIT_PENDING_SETTLEMENT:
            if transition is None or self.risk.status is not RiskStatus.EXIT_PENDING_SETTLEMENT:
                raise ValueError("pending exit requires an EXIT_PENDING_SETTLEMENT transition")
            if (
                self.recovery_evidence is None
                or self.recovery_evidence.outcome is not ConditionOutcome.UNSATISFIED
            ):
                raise ValueError("pending exit requires known non-recovery evidence")
            if (
                self.deterioration_evidence is None
                or self.deterioration_evidence.outcome is not ConditionOutcome.SATISFIED
            ):
                raise ValueError("pending exit requires satisfied deterioration evidence")
        else:
            if transition is not None or self.risk.status is RiskStatus.CLEAR:
                raise ValueError("ready exit requires unchanged active risk")
            if (
                self.recovery_evidence is None
                or self.recovery_evidence.outcome is not ConditionOutcome.UNSATISFIED
            ):
                raise ValueError("ready exit requires known non-recovery evidence")
            if self.risk.status is RiskStatus.BREACHED_PENDING_CONFIRMATION and (
                self.deterioration_evidence is None
                or self.deterioration_evidence.outcome is not ConditionOutcome.SATISFIED
            ):
                raise ValueError("first ready exit requires satisfied deterioration evidence")
        return self


def _fact(key: str, value: object, unit: EvidenceUnit) -> EvidenceFact:
    return EvidenceFact(key=key, value=value, unit=unit)


def _inside_pressure_zone(price_fen: int, context: EvaluationContext) -> bool:
    zone = context.plan.levels.pressure
    above_low = price_fen >= zone.low_fen if zone.include_low else price_fen > zone.low_fen
    below_high = price_fen <= zone.high_fen if zone.include_high else price_fen < zone.high_fen
    return above_low and below_high


def _pressure_touch_evidence(context: EvaluationContext) -> PressureTouchEvidence:
    zone = context.plan.levels.pressure
    common_facts = (
        _fact("pressure_low_fen", zone.low_fen, EvidenceUnit.FEN),
        _fact("pressure_high_fen", zone.high_fen, EvidenceUnit.FEN),
    )
    if not context.plan_active or context.activated_at is None:
        return PressureTouchEvidence(
            outcome=ConditionOutcome.UNSATISFIED,
            touch_at=None,
            facts=common_facts,
        )
    if not has_complete_current_day_minutes(context):
        return PressureTouchEvidence(
            outcome=ConditionOutcome.MISSING_INPUT,
            touch_at=None,
            facts=common_facts,
            missing_inputs=(MissingInputCode.COMPLETE_MINUTE_BAR,),
        )
    touch = next(
        (
            minute
            for minute in context.current_day_minutes
            if minute.bar_end >= context.activated_at
            and _inside_pressure_zone(minute.close_fen, context)
        ),
        None,
    )
    if touch is None:
        return PressureTouchEvidence(
            outcome=ConditionOutcome.UNSATISFIED,
            touch_at=None,
            facts=common_facts,
        )
    return PressureTouchEvidence(
        outcome=ConditionOutcome.SATISFIED,
        touch_at=touch.bar_end,
        facts=(
            *common_facts,
            _fact("pressure_touch_at", touch.bar_end, EvidenceUnit.DATETIME),
            _fact("pressure_touch_close_fen", touch.close_fen, EvidenceUnit.FEN),
        ),
    )


def _bars_are_adjacent(previous: FiveMinuteBar, current: FiveMinuteBar) -> bool:
    if previous.bar_end.date() != current.bar_end.date():
        return False
    if (
        previous.bar_end.hour,
        previous.bar_end.minute,
        current.bar_end.hour,
        current.bar_end.minute,
    ) == (11, 30, 13, 5):
        return True
    return current.bar_end - previous.bar_end == timedelta(minutes=5)


def _missing_consecutive_evidence(
    condition: ConsecutiveClosesBelowLevelCondition,
    context: EvaluationContext,
    touch_at: ShanghaiDatetime | None,
    bars: tuple[FiveMinuteBar, ...] = (),
) -> ConditionEvidence:
    facts = [
        _fact(
            "pressure_reference_fen",
            context.plan.levels.pressure_reference_fen,
            EvidenceUnit.FEN,
        ),
        _fact("required_bars", condition.bars, EvidenceUnit.BARS),
    ]
    if touch_at is not None:
        facts.append(_fact("pressure_touch_at", touch_at, EvidenceUnit.DATETIME))
    facts.extend(
        fact
        for index, bar in enumerate(bars, start=1)
        for fact in (
            _fact(f"bar_{index}_end", bar.bar_end, EvidenceUnit.DATETIME),
            _fact(f"close_{index}_fen", bar.close_fen, EvidenceUnit.FEN),
        )
    )
    return ConditionEvidence(
        condition=condition,
        outcome=ConditionOutcome.MISSING_INPUT,
        facts=tuple(facts),
        missing_inputs=(MissingInputCode.COMPLETE_5M_BAR_WINDOW,),
    )


def _evaluate_after_touch_consecutive(
    condition: ConsecutiveClosesBelowLevelCondition,
    context: EvaluationContext,
    touch_evidence: PressureTouchEvidence,
) -> ConditionEvidence:
    if touch_evidence.outcome is ConditionOutcome.MISSING_INPUT:
        return _missing_consecutive_evidence(condition, context, None)
    if touch_evidence.outcome is ConditionOutcome.UNSATISFIED:
        return ConditionEvidence(
            condition=condition,
            outcome=ConditionOutcome.UNSATISFIED,
            facts=(
                _fact(
                    "pressure_reference_fen",
                    context.plan.levels.pressure_reference_fen,
                    EvidenceUnit.FEN,
                ),
                _fact("consecutive_bars", 0, EvidenceUnit.BARS),
                _fact("required_bars", condition.bars, EvidenceUnit.BARS),
            ),
        )

    touch_at = touch_evidence.touch_at
    if touch_at is None:
        raise ValueError("satisfied pressure touch must include touch_at")
    eligible = tuple(
        bar
        for bar in context.complete_5m_bars
        if bar.bar_end.date() == context.trade_date and bar.bar_end > touch_at
    )
    selected = eligible[-condition.bars :]
    reference = context.plan.levels.pressure_reference_fen
    below_count = sum(bar.close_fen < reference for bar in selected)
    facts = (
        _fact("pressure_reference_fen", reference, EvidenceUnit.FEN),
        _fact("pressure_touch_at", touch_at, EvidenceUnit.DATETIME),
        _fact("consecutive_bars", below_count, EvidenceUnit.BARS),
        _fact("required_bars", condition.bars, EvidenceUnit.BARS),
        *(
            fact
            for index, bar in enumerate(selected, start=1)
            for fact in (
                _fact(f"bar_{index}_end", bar.bar_end, EvidenceUnit.DATETIME),
                _fact(f"close_{index}_fen", bar.close_fen, EvidenceUnit.FEN),
            )
        ),
    )
    if len(selected) < condition.bars:
        return _missing_consecutive_evidence(
            condition,
            context,
            touch_at,
            selected,
        )
    if any(not _bars_are_adjacent(previous, current) for previous, current in pairwise(selected)):
        return _missing_consecutive_evidence(
            condition,
            context,
            touch_at,
            selected,
        )
    return ConditionEvidence(
        condition=condition,
        outcome=(
            ConditionOutcome.SATISFIED
            if below_count == condition.bars
            else ConditionOutcome.UNSATISFIED
        ),
        facts=facts,
    )


def _logical_evidence(
    condition: AllCondition | AnyCondition,
    children: tuple[ConditionEvidence, ...],
) -> ConditionEvidence:
    if isinstance(condition, AllCondition):
        if any(child.outcome is ConditionOutcome.UNSATISFIED for child in children):
            outcome = ConditionOutcome.UNSATISFIED
        elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
            outcome = ConditionOutcome.MISSING_INPUT
        else:
            outcome = ConditionOutcome.SATISFIED
    elif any(child.outcome is ConditionOutcome.SATISFIED for child in children):
        outcome = ConditionOutcome.SATISFIED
    elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
        outcome = ConditionOutcome.MISSING_INPUT
    else:
        outcome = ConditionOutcome.UNSATISFIED
    return ConditionEvidence(
        condition=condition,
        outcome=outcome,
        facts=(
            _fact(
                "satisfied_children",
                sum(child.outcome is ConditionOutcome.SATISFIED for child in children),
                EvidenceUnit.COUNT,
            ),
            _fact(
                "unsatisfied_children",
                sum(child.outcome is ConditionOutcome.UNSATISFIED for child in children),
                EvidenceUnit.COUNT,
            ),
            _fact(
                "missing_children",
                sum(child.outcome is ConditionOutcome.MISSING_INPUT for child in children),
                EvidenceUnit.COUNT,
            ),
        ),
        children=children,
    )


def _evaluate_reduction_node(
    condition: ConditionNode,
    context: EvaluationContext,
    touch_evidence: PressureTouchEvidence,
) -> ConditionEvidence:
    if isinstance(condition, ConsecutiveClosesBelowLevelCondition):
        return _evaluate_after_touch_consecutive(condition, context, touch_evidence)
    if isinstance(condition, (AllCondition, AnyCondition)):
        children = tuple(
            _evaluate_reduction_node(child, context, touch_evidence)
            for child in condition.conditions
        )
        return _logical_evidence(condition, children)
    return evaluate_condition(condition, context)


def _target_tactical_lot(context: EvaluationContext) -> PositionLotSnapshot | None:
    candidates = tuple(
        lot
        for lot in context.positions
        if lot.bucket == "TACTICAL"
        and lot.acquired_trade_date < context.trade_date
        and lot.remaining_quantity >= context.plan.position.lot_size
    )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda lot: (-lot.acquired_trade_date.toordinal(), lot.lot_id),
    )[0]


def _pressure_cause_id(context: EvaluationContext, touch_at: ShanghaiDatetime) -> str:
    preimage = "\0".join(
        (
            _PRESSURE_CAUSE_DOMAIN,
            context.plan_hash,
            context.plan.symbol,
            touch_at.isoformat(),
        )
    )
    return f"pressure-{sha256(preimage.encode('utf-8')).hexdigest()[:32]}"


def _official_bar(context: EvaluationContext) -> DailyBar | None:
    reconciliation = context.close_reconciliation
    if (
        not isinstance(context.target, OfficialCloseEvaluationTarget)
        or reconciliation is None
        or not reconciliation.advance_close_risk
        or reconciliation.official_bar is None
        or reconciliation.symbol != context.plan.symbol
        or reconciliation.trade_date != context.trade_date
    ):
        return None
    bar = reconciliation.official_bar
    if (
        not bar.is_official
        or bar.symbol != context.plan.symbol
        or bar.trade_date != context.trade_date
    ):
        return None
    return bar


def _open_target_is_certified(context: EvaluationContext) -> bool:
    trading_day = context.trading_day
    return trading_day is not None and trading_day.is_open


def _official_risk_evidence(
    outcome: ConditionOutcome,
    *facts: EvidenceFact,
    missing_inputs: tuple[MissingInputCode, ...] = (),
) -> OfficialRiskEvidence:
    return OfficialRiskEvidence(
        outcome=outcome,
        facts=facts,
        missing_inputs=missing_inputs,
    )


def _recovery_evidence(
    context: EvaluationContext,
    bar: DailyBar,
) -> OfficialRiskEvidence:
    risk = context.risk_state
    breach_trade_date = risk.breach_trade_date
    facts = (
        _fact("risk_line_fen", context.plan.levels.risk_line_fen, EvidenceUnit.FEN),
        _fact("current_close_fen", bar.close_fen, EvidenceUnit.FEN),
        _fact("current_trade_date", context.trade_date, EvidenceUnit.DATE),
        *(
            (_fact("breach_trade_date", breach_trade_date, EvidenceUnit.DATE),)
            if breach_trade_date is not None
            else ()
        ),
    )
    if not _open_target_is_certified(context):
        return _official_risk_evidence(
            ConditionOutcome.MISSING_INPUT,
            *facts,
            missing_inputs=(MissingInputCode.TRADING_CALENDAR,),
        )
    recovered = (
        breach_trade_date is not None
        and context.trade_date > risk.updated_at.date()
        and bar.close_fen >= context.plan.levels.risk_line_fen
    )
    return _official_risk_evidence(
        ConditionOutcome.SATISFIED if recovered else ConditionOutcome.UNSATISFIED,
        *facts,
    )


def _breach_day_bar(
    context: EvaluationContext,
    breach_trade_date: date,
) -> DailyBar | None:
    return next(
        (
            bar
            for bar in context.official_daily_bars
            if bar.trade_date == breach_trade_date
            and bar.symbol == context.plan.symbol
            and bar.is_official
        ),
        None,
    )


def _macd_histogram(
    context: EvaluationContext,
    trade_date: date,
) -> Decimal | None:
    snapshot = context.daily_indicator_snapshot
    if snapshot is None or snapshot.provenance is not DailyIndicatorProvenance.OFFICIAL:
        return None
    point = next(
        (
            point
            for point in snapshot.series.points
            if type(point.bar_at) is date and point.bar_at == trade_date
        ),
        None,
    )
    if point is None:
        return None
    return Decimal(str(point.macd_histogram_yuan))


def _deterioration_evidence(
    context: EvaluationContext,
    current_bar: DailyBar,
) -> OfficialRiskEvidence:
    risk = context.risk_state
    breach_trade_date = risk.breach_trade_date
    if breach_trade_date is None:
        return _official_risk_evidence(
            ConditionOutcome.MISSING_INPUT,
            missing_inputs=(MissingInputCode.OFFICIAL_DAILY_CLOSE,),
        )

    breach_bar = _breach_day_bar(context, breach_trade_date)
    if (
        breach_bar is None
        or breach_bar.close_fen != risk.prior_close_fen
        or breach_bar.close_fen >= context.plan.levels.risk_line_fen
    ):
        return _official_risk_evidence(
            ConditionOutcome.MISSING_INPUT,
            _fact("breach_trade_date", breach_trade_date, EvidenceUnit.DATE),
            _fact("current_trade_date", context.trade_date, EvidenceUnit.DATE),
            missing_inputs=(MissingInputCode.OFFICIAL_DAILY_CLOSE,),
        )

    close_not_higher = current_bar.close_fen <= breach_bar.close_fen
    volume_not_lower = current_bar.volume_shares >= breach_bar.volume_shares
    common_facts = (
        _fact("breach_trade_date", breach_trade_date, EvidenceUnit.DATE),
        _fact("current_trade_date", context.trade_date, EvidenceUnit.DATE),
        _fact("breach_close_fen", breach_bar.close_fen, EvidenceUnit.FEN),
        _fact("current_close_fen", current_bar.close_fen, EvidenceUnit.FEN),
        _fact(
            "breach_volume_shares",
            breach_bar.volume_shares,
            EvidenceUnit.SHARES,
        ),
        _fact(
            "current_volume_shares",
            current_bar.volume_shares,
            EvidenceUnit.SHARES,
        ),
        _fact("close_not_higher", close_not_higher, EvidenceUnit.BOOLEAN),
        _fact("volume_not_lower", volume_not_lower, EvidenceUnit.BOOLEAN),
    )
    if context.trade_date <= breach_trade_date or not close_not_higher:
        return _official_risk_evidence(
            ConditionOutcome.UNSATISFIED,
            *common_facts,
        )
    if volume_not_lower:
        return _official_risk_evidence(
            ConditionOutcome.SATISFIED,
            *common_facts,
        )

    breach_macd = _macd_histogram(context, breach_trade_date)
    current_macd = _macd_histogram(context, context.trade_date)
    if breach_macd is None or current_macd is None:
        return _official_risk_evidence(
            ConditionOutcome.MISSING_INPUT,
            *common_facts,
            missing_inputs=(MissingInputCode.DAILY_INDICATORS,),
        )
    macd_not_improving = current_macd <= breach_macd
    return _official_risk_evidence(
        (ConditionOutcome.SATISFIED if macd_not_improving else ConditionOutcome.UNSATISFIED),
        *common_facts,
        _fact("breach_macd_histogram_yuan", breach_macd, EvidenceUnit.YUAN),
        _fact("current_macd_histogram_yuan", current_macd, EvidenceUnit.YUAN),
        _fact("macd_not_improving", macd_not_improving, EvidenceUnit.BOOLEAN),
    )


def _risk_exit_target(context: EvaluationContext) -> PositionLotSnapshot | None:
    eligible = tuple(
        lot for lot in context.positions if lot.remaining_quantity >= context.plan.position.lot_size
    )
    tactical = tuple(lot for lot in eligible if lot.bucket == "TACTICAL")
    candidates = tactical or tuple(lot for lot in eligible if lot.bucket == "CORE")
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda lot: (-lot.acquired_trade_date.toordinal(), lot.lot_id),
    )[0]


def _risk_cause_id(context: EvaluationContext, breach_trade_date: date) -> str:
    preimage = "\0".join(
        (
            _RISK_CAUSE_DOMAIN,
            context.plan_hash,
            context.plan.symbol,
            breach_trade_date.isoformat(),
        )
    )
    return f"risk-{sha256(preimage.encode('utf-8')).hexdigest()[:32]}"


def _risk_transition(
    context: EvaluationContext,
    *,
    status: RiskStatus,
    breach_trade_date: date | None,
    prior_close_fen: int,
) -> tuple[RiskStateSnapshot, RiskTransitionIntent]:
    risk = RiskStateSnapshot(
        symbol=context.plan.symbol,
        plan_hash=context.plan_hash,
        status=status,
        breach_trade_date=breach_trade_date,
        prior_close_fen=prior_close_fen,
        revision=context.risk_state.revision + 1,
        updated_at=context.evaluated_at,
    )
    return risk, RiskTransitionIntent(
        risk=risk,
        expected_revision=context.risk_state.revision,
    )


def _risk_signal(
    context: EvaluationContext,
    *,
    signal_type: ActionableSignalType,
    breach_trade_date: date,
    matched_condition: ConditionEvidence,
    target_lot: PositionLotSnapshot | None = None,
) -> SignalIntent:
    if signal_type is ActionableSignalType.RISK_BREACH:
        quantity = None
        bucket = None
        target_lot_id = None
        next_step = NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
    else:
        if target_lot is None:
            raise ValueError("risk exit signal requires a target lot")
        quantity = context.plan.position.lot_size
        bucket = target_lot.bucket
        target_lot_id = target_lot.lot_id
        next_step = NextStep(
            code=(
                NextStepCode.WAIT_FOR_SETTLEMENT
                if signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT
                else NextStepCode.RECORD_CONFIRMED_FILL
            )
        )
    return SignalIntent(
        signal_type=signal_type,
        plan_hash=context.plan_hash,
        symbol=context.plan.symbol,
        trading_date=context.trade_date,
        cause_id=_risk_cause_id(context, breach_trade_date),
        quantity=quantity,
        bucket=bucket,
        target_lot_id=target_lot_id,
        matched_conditions=(matched_condition,),
        blockers=(),
        next_step=next_step,
    )


def _unchanged_official_risk(
    context: EvaluationContext,
    risk_evidence: ConditionEvidence,
    *,
    recovery_evidence: OfficialRiskEvidence | None = None,
    deterioration_evidence: OfficialRiskEvidence | None = None,
) -> OfficialCloseRiskEvaluation:
    return OfficialCloseRiskEvaluation(
        risk=context.risk_state,
        transition=None,
        signal_type=None,
        signal_intent=None,
        risk_evidence=risk_evidence,
        recovery_evidence=recovery_evidence,
        deterioration_evidence=deterioration_evidence,
    )


def evaluate_official_close_risk(
    context: EvaluationContext,
) -> OfficialCloseRiskEvaluation:
    """Evaluate one strict, deterministic official-close risk transition."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")

    risk_evidence = evaluate_condition(context.plan.risk.condition, context)
    if not context.plan_active:
        return _unchanged_official_risk(context, risk_evidence)
    official_bar = _official_bar(context)
    if official_bar is None or risk_evidence.outcome is ConditionOutcome.MISSING_INPUT:
        return _unchanged_official_risk(context, risk_evidence)

    current_risk = context.risk_state
    if current_risk.status is RiskStatus.CLEAR:
        if not _open_target_is_certified(context):
            return _unchanged_official_risk(context, risk_evidence)
        if risk_evidence.outcome is not ConditionOutcome.SATISFIED:
            return _unchanged_official_risk(context, risk_evidence)
        risk, transition = _risk_transition(
            context,
            status=RiskStatus.BREACHED_PENDING_CONFIRMATION,
            breach_trade_date=context.trade_date,
            prior_close_fen=official_bar.close_fen,
        )
        signal = _risk_signal(
            context,
            signal_type=ActionableSignalType.RISK_BREACH,
            breach_trade_date=context.trade_date,
            matched_condition=risk_evidence,
        )
        return OfficialCloseRiskEvaluation(
            risk=risk,
            transition=transition,
            signal_type=SignalType.RISK_BREACH,
            signal_intent=signal,
            risk_evidence=risk_evidence,
        )

    recovery_evidence = _recovery_evidence(context, official_bar)
    if recovery_evidence.outcome is ConditionOutcome.SATISFIED:
        risk, transition = _risk_transition(
            context,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=official_bar.close_fen,
        )
        return OfficialCloseRiskEvaluation(
            risk=risk,
            transition=transition,
            signal_type=SignalType.RISK_RECOVERED,
            signal_intent=None,
            risk_evidence=risk_evidence,
            recovery_evidence=recovery_evidence,
        )
    if recovery_evidence.outcome is ConditionOutcome.MISSING_INPUT:
        return _unchanged_official_risk(
            context,
            risk_evidence,
            recovery_evidence=recovery_evidence,
        )

    deterioration_evidence = _deterioration_evidence(context, official_bar)
    pending_lifecycle = current_risk.status is RiskStatus.EXIT_PENDING_SETTLEMENT
    should_resolve_pending = (
        pending_lifecycle and context.trade_date > current_risk.updated_at.date()
    )
    if pending_lifecycle and not should_resolve_pending:
        return _unchanged_official_risk(
            context,
            risk_evidence,
            recovery_evidence=recovery_evidence,
            deterioration_evidence=deterioration_evidence,
        )
    if (
        not should_resolve_pending
        and deterioration_evidence.outcome is not ConditionOutcome.SATISFIED
    ):
        return _unchanged_official_risk(
            context,
            risk_evidence,
            recovery_evidence=recovery_evidence,
            deterioration_evidence=deterioration_evidence,
        )

    target_lot = _risk_exit_target(context)
    breach_trade_date = current_risk.breach_trade_date
    if target_lot is None or breach_trade_date is None:
        return _unchanged_official_risk(
            context,
            risk_evidence,
            recovery_evidence=recovery_evidence,
            deterioration_evidence=deterioration_evidence,
        )

    sellable = target_lot.acquired_trade_date < context.trade_date
    if sellable:
        signal = _risk_signal(
            context,
            signal_type=ActionableSignalType.RISK_EXIT_READY,
            breach_trade_date=breach_trade_date,
            matched_condition=risk_evidence,
            target_lot=target_lot,
        )
        return OfficialCloseRiskEvaluation(
            risk=current_risk,
            transition=None,
            signal_type=SignalType.RISK_EXIT_READY,
            signal_intent=signal,
            risk_evidence=risk_evidence,
            recovery_evidence=recovery_evidence,
            deterioration_evidence=deterioration_evidence,
        )

    if current_risk.status is RiskStatus.EXIT_PENDING_SETTLEMENT:
        return _unchanged_official_risk(
            context,
            risk_evidence,
            recovery_evidence=recovery_evidence,
            deterioration_evidence=deterioration_evidence,
        )

    risk, transition = _risk_transition(
        context,
        status=RiskStatus.EXIT_PENDING_SETTLEMENT,
        breach_trade_date=breach_trade_date,
        prior_close_fen=current_risk.prior_close_fen,
    )
    signal = _risk_signal(
        context,
        signal_type=ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
        breach_trade_date=breach_trade_date,
        matched_condition=risk_evidence,
        target_lot=target_lot,
    )
    return OfficialCloseRiskEvaluation(
        risk=risk,
        transition=transition,
        signal_type=SignalType.RISK_EXIT_PENDING_SETTLEMENT,
        signal_intent=signal,
        risk_evidence=risk_evidence,
        recovery_evidence=recovery_evidence,
        deterioration_evidence=deterioration_evidence,
    )


def evaluate_pressure_reduction(context: EvaluationContext) -> PressureReductionEvaluation:
    """Evaluate one deterministic intraday pressure-reduction opportunity."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")
    if not isinstance(context.target, IntradayEvaluationTarget):
        return PressureReductionEvaluation(
            touch_evidence=PressureTouchEvidence(
                outcome=ConditionOutcome.UNSATISFIED,
                touch_at=None,
            ),
            reduction_evidence=None,
            signal_intent=None,
        )

    touch_evidence = _pressure_touch_evidence(context)
    reduction_evidence = _evaluate_reduction_node(
        context.plan.reduction.condition,
        context,
        touch_evidence,
    )
    if (
        touch_evidence.outcome is not ConditionOutcome.SATISFIED
        or reduction_evidence.outcome is not ConditionOutcome.SATISFIED
    ):
        return PressureReductionEvaluation(
            touch_evidence=touch_evidence,
            reduction_evidence=reduction_evidence,
            signal_intent=None,
        )

    target_lot = _target_tactical_lot(context)
    if target_lot is None or touch_evidence.touch_at is None:
        return PressureReductionEvaluation(
            touch_evidence=touch_evidence,
            reduction_evidence=reduction_evidence,
            signal_intent=None,
        )
    signal = SignalIntent(
        signal_type=ActionableSignalType.PRESSURE_REDUCE_READY,
        plan_hash=context.plan_hash,
        symbol=context.plan.symbol,
        trading_date=context.trade_date,
        cause_id=_pressure_cause_id(context, touch_evidence.touch_at),
        quantity=context.plan.position.lot_size,
        bucket="TACTICAL",
        target_lot_id=target_lot.lot_id,
        matched_conditions=(reduction_evidence,),
        blockers=(),
        next_step=NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL),
    )
    return PressureReductionEvaluation(
        touch_evidence=touch_evidence,
        reduction_evidence=reduction_evidence,
        signal_intent=signal,
    )


__all__ = [
    "OfficialCloseRiskEvaluation",
    "OfficialRiskEvidence",
    "PressureReductionEvaluation",
    "PressureTouchEvidence",
    "evaluate_official_close_risk",
    "evaluate_pressure_reduction",
]
