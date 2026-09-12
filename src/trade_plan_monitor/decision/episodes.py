"""Pure low-zone episode transitions and one-alert buy intents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.decision.conditions import (
    _evaluate_validated_condition,
    has_complete_current_day_minutes,
)
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DataHealthStatus,
    EpisodeStatus,
    EpisodeTransitionAction,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationTarget,
    LowZoneEpisodeSnapshot,
    MissingInputCode,
    NextStep,
    NextStepCode,
    RiskStatus,
    SignalIntent,
)
from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    NoNewLowForBarsCondition,
    PositionBucket,
    PositionBucketAvailableCondition,
    VolumeToMedianLteCondition,
)
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.models import MinuteBar, ShanghaiDatetime

_DEFAULT_CONFIRMATION_BARS = 2
_EPISODE_ID_DOMAIN = "low-zone-episode-v1"


class _EpisodeValue(BaseModel):
    """Close, freeze, and revalidate public episode decisions."""

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


class EpisodeStructuralBlockerCode(StrEnum):
    """Non-DSL reasons why T022 must suppress a low-zone buy intent."""

    DATA_NOT_READY = "DATA_NOT_READY"
    DAILY_LIMIT_UNKNOWN = "DAILY_LIMIT_UNKNOWN"
    EPISODE_HISTORY_GAP = "EPISODE_HISTORY_GAP"
    BEARISH_VOLUME_EXPANSION = "BEARISH_VOLUME_EXPANSION"
    RISK_PENDING = "RISK_PENDING"


class EpisodeStructuralBlocker(_EpisodeValue):
    """Bounded structural evidence retained for T024 result assembly."""

    code: EpisodeStructuralBlockerCode
    outcome: ConditionOutcome
    facts: tuple[EvidenceFact, ...] = Field(default=(), max_length=16)
    missing_inputs: tuple[MissingInputCode, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def validate_blocker_shape(self) -> Self:
        if self.outcome is ConditionOutcome.SATISFIED:
            raise ValueError("structural blocker cannot be satisfied")
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("structural blocker fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("structural blocker missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT and not self.missing_inputs:
            raise ValueError("missing structural blocker requires a missing input code")
        if self.outcome is ConditionOutcome.UNSATISFIED and self.missing_inputs:
            raise ValueError("known structural blocker cannot retain missing inputs")
        return self


class LowZoneEpisodeEvaluation(_EpisodeValue):
    """One bounded T022 result for later T024 result assembly."""

    episode: LowZoneEpisodeSnapshot | None
    transition: EpisodeTransitionIntent | None
    signal_intent: SignalIntent | None
    entry_evidence: ConditionEvidence | None
    blocker_evidence: ConditionEvidence | None
    availability_evidence: ConditionEvidence | None
    structural_blockers: tuple[EpisodeStructuralBlocker, ...] = Field(
        default=(),
        max_length=3,
    )
    touch_at: ShanghaiDatetime | None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if (self.episode is None) != (self.touch_at is None):
            raise ValueError("episode and touch_at must appear together")
        if self.episode is not None and self.touch_at != self.episode.started_at:
            raise ValueError("touch_at must identify the returned episode start")
        if self.transition is not None and self.transition.episode != self.episode:
            raise ValueError("episode transition must match the returned episode")
        if self.signal_intent is None:
            return self
        if self.structural_blockers:
            raise ValueError("buy intent cannot retain structural blockers")
        if self.episode is None or self.episode.status is not EpisodeStatus.ALERTED:
            raise ValueError("buy intent requires an alerted episode")
        if self.signal_intent.cause_id != self.episode.episode_id:
            raise ValueError("buy intent cause must match the episode identity")
        evidence = (
            self.entry_evidence,
            self.blocker_evidence,
            self.availability_evidence,
        )
        if any(item is None for item in evidence):
            raise ValueError("buy intent requires entry, blocker, and availability evidence")
        if self.signal_intent.matched_conditions != evidence:
            raise ValueError("buy intent must retain all satisfied episode evidence")
        return self


def _decision(
    episode: LowZoneEpisodeSnapshot | None,
    *,
    transition: EpisodeTransitionIntent | None = None,
    signal_intent: SignalIntent | None = None,
    entry_evidence: ConditionEvidence | None = None,
    blocker_evidence: ConditionEvidence | None = None,
    availability_evidence: ConditionEvidence | None = None,
    structural_blockers: tuple[EpisodeStructuralBlocker, ...] = (),
) -> LowZoneEpisodeEvaluation:
    return LowZoneEpisodeEvaluation(
        episode=episode,
        transition=transition,
        signal_intent=signal_intent,
        entry_evidence=entry_evidence,
        blocker_evidence=blocker_evidence,
        availability_evidence=availability_evidence,
        structural_blockers=structural_blockers,
        touch_at=None if episode is None else episode.started_at,
    )


def _inside_low_zone(price_fen: int, context: EvaluationContext) -> bool:
    zone = context.plan.levels.low_buy
    above_low = price_fen >= zone.low_fen if zone.include_low else price_fen > zone.low_fen
    below_high = price_fen <= zone.high_fen if zone.include_high else price_fen < zone.high_fen
    return above_low and below_high


def _bars_are_adjacent(
    previous: FiveMinuteBar,
    current: FiveMinuteBar,
    context: EvaluationContext,
) -> bool:
    if previous.bar_end.date() == current.bar_end.date():
        if (
            previous.bar_end.hour,
            previous.bar_end.minute,
            current.bar_end.hour,
            current.bar_end.minute,
        ) == (11, 30, 13, 5):
            return True
        return current.bar_end - previous.bar_end == timedelta(minutes=5)
    if (previous.bar_end.hour, previous.bar_end.minute) != (15, 0) or (
        current.bar_end.hour,
        current.bar_end.minute,
    ) != (9, 35):
        return False
    trading_day = next(
        (item for item in context.trading_calendar if item.cal_date == current.bar_end.date()),
        None,
    )
    return bool(
        trading_day is not None
        and trading_day.is_open
        and trading_day.previous_trade_date == previous.bar_end.date()
    )


def _fact(key: str, value: object, unit: EvidenceUnit) -> EvidenceFact:
    return EvidenceFact(key=key, value=value, unit=unit)


def _data_readiness_blockers(
    context: EvaluationContext,
) -> tuple[EpisodeStructuralBlocker, ...]:
    trading_day = context.trading_day
    minute_history_complete = has_complete_current_day_minutes(context)
    target_bar_present = bool(
        context.complete_5m_bars
        and isinstance(context.target, IntradayEvaluationTarget)
        and context.complete_5m_bars[-1].bar_end == context.target.bucket_end
    )
    ready = (
        context.data_health.status is DataHealthStatus.LIVE
        and context.data_health.fresh
        and context.data_health.required_data_complete
        and trading_day is not None
        and trading_day.is_open
        and minute_history_complete
        and target_bar_present
    )
    if ready:
        return ()

    missing: list[MissingInputCode] = []
    if trading_day is None or not trading_day.is_open:
        missing.append(MissingInputCode.TRADING_CALENDAR)
    if not minute_history_complete:
        missing.append(MissingInputCode.COMPLETE_MINUTE_BAR)
    if not target_bar_present:
        missing.append(MissingInputCode.COMPLETE_5M_BAR)
    outcome = ConditionOutcome.MISSING_INPUT if missing else ConditionOutcome.UNSATISFIED
    return (
        EpisodeStructuralBlocker(
            code=EpisodeStructuralBlockerCode.DATA_NOT_READY,
            outcome=outcome,
            facts=(
                _fact(
                    "data_health_status",
                    context.data_health.status.value,
                    EvidenceUnit.CODE,
                ),
                _fact(
                    "required_data_complete",
                    context.data_health.required_data_complete,
                    EvidenceUnit.BOOLEAN,
                ),
                _fact("fresh", context.data_health.fresh, EvidenceUnit.BOOLEAN),
                _fact(
                    "trading_day_present",
                    trading_day is not None,
                    EvidenceUnit.BOOLEAN,
                ),
                _fact(
                    "trading_day_open",
                    bool(trading_day is not None and trading_day.is_open),
                    EvidenceUnit.BOOLEAN,
                ),
                _fact(
                    "minute_history_complete",
                    minute_history_complete,
                    EvidenceUnit.BOOLEAN,
                ),
                _fact(
                    "target_bar_present",
                    target_bar_present,
                    EvidenceUnit.BOOLEAN,
                ),
            ),
            missing_inputs=tuple(missing),
        ),
    )


def _buy_structural_blockers(
    context: EvaluationContext,
) -> tuple[EpisodeStructuralBlocker, ...]:
    blockers: list[EpisodeStructuralBlocker] = []
    if context.daily_limit is None:
        blockers.append(
            EpisodeStructuralBlocker(
                code=EpisodeStructuralBlockerCode.DAILY_LIMIT_UNKNOWN,
                outcome=ConditionOutcome.MISSING_INPUT,
                facts=(_fact("daily_limit_present", False, EvidenceUnit.BOOLEAN),),
                missing_inputs=(MissingInputCode.DAILY_LIMIT,),
            )
        )
    bearish_volume = _bearish_volume_blocker(context)
    if bearish_volume is not None:
        blockers.append(bearish_volume)
    if context.risk_state.status is not RiskStatus.CLEAR:
        risk_facts = [
            _fact("risk_status", context.risk_state.status.value, EvidenceUnit.CODE),
        ]
        if context.risk_state.breach_trade_date is not None:
            risk_facts.append(
                _fact(
                    "risk_breach_trade_date",
                    context.risk_state.breach_trade_date,
                    EvidenceUnit.DATE,
                )
            )
        blockers.append(
            EpisodeStructuralBlocker(
                code=EpisodeStructuralBlockerCode.RISK_PENDING,
                outcome=ConditionOutcome.UNSATISFIED,
                facts=tuple(risk_facts),
            )
        )
    return tuple(blockers)


def _mandatory_entry_volume_caps(
    context: EvaluationContext,
) -> tuple[VolumeToMedianLteCondition, ...]:
    """Return volume caps on explicitly conjunctive entry paths only."""

    stack = [context.plan.entry.condition]
    caps: list[VolumeToMedianLteCondition] = []
    while stack:
        condition = stack.pop()
        if isinstance(condition, VolumeToMedianLteCondition):
            caps.append(condition)
        elif isinstance(condition, AllCondition):
            stack.extend(reversed(condition.conditions))
        # A condition beneath ANY is an alternative, never an inferred global blocker.
    return tuple(caps)


def _bearish_volume_blocker(
    context: EvaluationContext,
) -> EpisodeStructuralBlocker | None:
    latest = context.complete_5m_bars[-1]
    if latest.close_fen >= latest.open_fen:
        return None
    for condition in _mandatory_entry_volume_caps(context):
        evidence = _evaluate_validated_condition(condition, context)
        if evidence.outcome is not ConditionOutcome.UNSATISFIED:
            continue
        return EpisodeStructuralBlocker(
            code=EpisodeStructuralBlockerCode.BEARISH_VOLUME_EXPANSION,
            outcome=ConditionOutcome.UNSATISFIED,
            facts=(
                _fact("latest_open_fen", latest.open_fen, EvidenceUnit.FEN),
                _fact("latest_close_fen", latest.close_fen, EvidenceUnit.FEN),
                _fact("bearish", True, EvidenceUnit.BOOLEAN),
                *evidence.facts,
            ),
        )
    return None


def _first_touch(
    context: EvaluationContext,
    *,
    after: datetime | None = None,
) -> MinuteBar | None:
    activated_at = context.activated_at
    if activated_at is None:
        return None
    for minute in context.current_day_minutes:
        if minute.bar_end < activated_at:
            continue
        if after is not None and minute.bar_end <= after:
            continue
        if _inside_low_zone(minute.close_fen, context):
            return minute
    return None


def _episode_id(context: EvaluationContext, touch_at: datetime) -> str:
    preimage = "\0".join(
        (
            _EPISODE_ID_DOMAIN,
            context.plan_hash,
            context.plan.symbol,
            touch_at.isoformat(),
        )
    )
    return f"ep-{sha256(preimage.encode('utf-8')).hexdigest()[:32]}"


def _initial_episode_low(context: EvaluationContext, touch: MinuteBar) -> int:
    touch_bucket_end = five_minute_bucket_end(touch.bar_end)
    post_touch_lows = tuple(
        minute.low_fen
        for minute in context.current_day_minutes
        if touch.bar_end < minute.bar_end <= touch_bucket_end
    )
    return min((touch.close_fen, *post_touch_lows))


def _start_episode(
    context: EvaluationContext,
    touch: MinuteBar,
) -> LowZoneEpisodeEvaluation:
    episode = LowZoneEpisodeSnapshot(
        episode_id=_episode_id(context, touch.bar_end),
        plan_hash=context.plan_hash,
        symbol=context.plan.symbol,
        started_at=touch.bar_end,
        episode_low_fen=_initial_episode_low(context, touch),
        bars_since_low=0,
        last_processed_bucket_end=five_minute_bucket_end(touch.bar_end),
        status=EpisodeStatus.ACTIVE,
        alerted_signal=None,
    )
    transition = EpisodeTransitionIntent(
        action=EpisodeTransitionAction.UPSERT,
        episode=episode,
    )
    return _decision(episode, transition=transition)


def _start_and_catch_up_episode(
    context: EvaluationContext,
    touch: MinuteBar,
) -> LowZoneEpisodeEvaluation:
    started = _start_episode(context, touch)
    episode = started.episode
    if episode is None or context.target_cutoff <= episode.last_processed_bucket_end:
        return started
    history_blockers = _episode_history_blockers(context, episode)
    if history_blockers:
        return _decision(
            episode,
            transition=started.transition,
            structural_blockers=history_blockers,
        )
    return _evaluate_active_episode(context, episode)


def _closure_boundary(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
) -> datetime | None:
    unseen = _episode_bars_through(context, episode, context.target_cutoff)
    if not unseen:
        return None
    anchor = next(
        (
            bar
            for bar in context.complete_5m_bars
            if bar.bar_end == episode.last_processed_bucket_end
        ),
        None,
    )
    if anchor is None:
        return None
    eligible = (anchor, *unseen)
    for previous, current in pairwise(eligible):
        if (
            _bars_are_adjacent(previous, current, context)
            and not _inside_low_zone(previous.close_fen, context)
            and not _inside_low_zone(current.close_fen, context)
        ):
            return current.bar_end
    return None


def _close_episode(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
    *,
    closure_at: datetime,
) -> LowZoneEpisodeEvaluation:
    current = _derive_episode_state(context, episode, through=closure_at)
    closed = current.model_copy(update={"status": EpisodeStatus.CLOSED})
    transition = EpisodeTransitionIntent(
        action=EpisodeTransitionAction.CLOSE,
        episode=closed,
    )
    return _decision(closed, transition=transition)


def _required_confirmation_bars(context: EvaluationContext) -> int:
    required = _DEFAULT_CONFIRMATION_BARS
    stack = [context.plan.entry.condition]
    while stack:
        condition = stack.pop()
        if isinstance(condition, NoNewLowForBarsCondition):
            required = max(required, condition.bars)
        elif isinstance(condition, (AllCondition, AnyCondition)):
            stack.extend(condition.conditions)
    return required


def _episode_bars_through(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
    through: datetime,
) -> tuple[FiveMinuteBar, ...] | None:
    cursor = episode.last_processed_bucket_end
    if through <= cursor:
        return ()
    bars = tuple(bar for bar in context.complete_5m_bars if cursor < bar.bar_end <= through)
    anchor = next(
        (bar for bar in context.complete_5m_bars if bar.bar_end == cursor),
        None,
    )
    if anchor is None:
        return None
    adjacency_values = (anchor, *bars)
    if any(
        not _bars_are_adjacent(previous, current, context)
        for previous, current in pairwise(adjacency_values)
    ):
        return None
    return bars


def _episode_history_blockers(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
) -> tuple[EpisodeStructuralBlocker, ...]:
    if context.target_cutoff <= episode.last_processed_bucket_end:
        return ()
    if _episode_bars_through(context, episode, context.target_cutoff) is not None:
        return ()
    return (
        EpisodeStructuralBlocker(
            code=EpisodeStructuralBlockerCode.EPISODE_HISTORY_GAP,
            outcome=ConditionOutcome.MISSING_INPUT,
            facts=(
                _fact(
                    "last_processed_bucket_end",
                    episode.last_processed_bucket_end,
                    EvidenceUnit.DATETIME,
                ),
                _fact(
                    "evaluation_target",
                    context.target_cutoff,
                    EvidenceUnit.DATETIME,
                ),
            ),
            missing_inputs=(MissingInputCode.COMPLETE_5M_BAR_WINDOW,),
        ),
    )


def _derive_episode_state(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
    *,
    through: datetime | None = None,
) -> LowZoneEpisodeSnapshot:
    cutoff = context.target.bucket_end if through is None else through
    bars = _episode_bars_through(context, episode, cutoff)
    if not bars:
        return episode
    required = _required_confirmation_bars(context)
    episode_low = episode.episode_low_fen
    bars_since_low = episode.bars_since_low
    for bar in bars:
        if bar.low_fen < episode_low:
            episode_low = bar.low_fen
            bars_since_low = 0
        else:
            bars_since_low = min(required, bars_since_low + 1)
    return episode.model_copy(
        update={
            "episode_low_fen": episode_low,
            "bars_since_low": bars_since_low,
            "last_processed_bucket_end": bars[-1].bar_end,
        }
    )


def _candidate_bucket(context: EvaluationContext) -> PositionBucket:
    core_quantity = sum(lot.remaining_quantity for lot in context.positions if lot.bucket == "CORE")
    return "CORE" if core_quantity == 0 else "TACTICAL"


def _evaluate_active_episode(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
) -> LowZoneEpisodeEvaluation:
    history_blockers = _episode_history_blockers(context, episode)
    if history_blockers:
        return _decision(episode, structural_blockers=history_blockers)
    closure_at = _closure_boundary(context, episode)
    if closure_at is not None:
        return _close_episode(context, episode, closure_at=closure_at)
    advanced = _derive_episode_state(context, episode)
    derived_context = context.model_copy(update={"low_zone_episode": advanced})
    entry_evidence = _evaluate_validated_condition(
        derived_context.plan.entry.condition,
        derived_context,
        plan_path="entry.condition",
    )
    blocker_evidence = _evaluate_validated_condition(
        derived_context.plan.blockers.condition,
        derived_context,
        plan_path="blockers.condition",
    )
    bucket = _candidate_bucket(derived_context)
    availability_evidence = _evaluate_validated_condition(
        PositionBucketAvailableCondition(bucket=bucket),
        derived_context,
    )
    structural_blockers = _buy_structural_blockers(derived_context)
    changed = advanced != episode
    transition = (
        EpisodeTransitionIntent(
            action=EpisodeTransitionAction.UPSERT,
            episode=advanced,
        )
        if changed
        else None
    )
    if not (
        not structural_blockers
        and entry_evidence.outcome is ConditionOutcome.SATISFIED
        and blocker_evidence.outcome is ConditionOutcome.SATISFIED
        and availability_evidence.outcome is ConditionOutcome.SATISFIED
    ):
        return _decision(
            advanced,
            transition=transition,
            entry_evidence=entry_evidence,
            blocker_evidence=blocker_evidence,
            availability_evidence=availability_evidence,
            structural_blockers=structural_blockers,
        )

    signal_type = (
        ActionableSignalType.BUY_CORE_READY
        if bucket == "CORE"
        else ActionableSignalType.BUY_TACTICAL_READY
    )
    alerted = advanced.model_copy(
        update={
            "status": EpisodeStatus.ALERTED,
            "alerted_signal": signal_type.value,
        }
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    matched_conditions = (
        entry_evidence,
        blocker_evidence,
        availability_evidence,
    )
    signal_intent = SignalIntent(
        signal_type=signal_type,
        plan_hash=derived_context.plan_hash,
        symbol=derived_context.plan.symbol,
        trading_date=derived_context.trade_date,
        cause_id=alerted.episode_id,
        quantity=derived_context.plan.position.lot_size,
        bucket=bucket,
        target_lot_id=None,
        matched_conditions=matched_conditions,
        blockers=(),
        next_step=next_step,
    )
    return _decision(
        alerted,
        transition=EpisodeTransitionIntent(
            action=EpisodeTransitionAction.UPSERT,
            episode=alerted,
        ),
        signal_intent=signal_intent,
        entry_evidence=entry_evidence,
        blocker_evidence=blocker_evidence,
        availability_evidence=availability_evidence,
    )


def _evaluate_alerted_episode(
    context: EvaluationContext,
    episode: LowZoneEpisodeSnapshot,
) -> LowZoneEpisodeEvaluation:
    history_blockers = _episode_history_blockers(context, episode)
    if history_blockers:
        return _decision(episode, structural_blockers=history_blockers)
    closure_at = _closure_boundary(context, episode)
    if closure_at is not None:
        return _close_episode(context, episode, closure_at=closure_at)
    advanced = _derive_episode_state(context, episode)
    if advanced == episode:
        return _decision(episode)
    return _decision(
        advanced,
        transition=EpisodeTransitionIntent(
            action=EpisodeTransitionAction.UPSERT,
            episode=advanced,
        ),
    )


def evaluate_low_zone_episode(context: EvaluationContext) -> LowZoneEpisodeEvaluation:
    """Evaluate one deterministic intraday low-zone episode step without I/O."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")
    if not isinstance(context.target, IntradayEvaluationTarget):
        return _decision(context.low_zone_episode)
    episode = context.low_zone_episode
    if episode is not None and context.target_cutoff == episode.last_processed_bucket_end:
        return _decision(episode)
    if not context.plan_active or context.activated_at is None:
        return _decision(context.low_zone_episode)
    data_blockers = _data_readiness_blockers(context)
    if data_blockers:
        return _decision(
            context.low_zone_episode,
            structural_blockers=data_blockers,
        )

    if episode is None:
        touch = _first_touch(context)
        return _decision(None) if touch is None else _start_and_catch_up_episode(context, touch)
    if context.activated_at is None or episode.started_at < context.activated_at:
        return _decision(episode)
    if episode.status is EpisodeStatus.CLOSED:
        touch = _first_touch(context, after=episode.last_processed_bucket_end)
        return _decision(episode) if touch is None else _start_and_catch_up_episode(context, touch)
    if episode.status is EpisodeStatus.ALERTED:
        return _evaluate_alerted_episode(context, episode)
    return _evaluate_active_episode(context, episode)


__all__ = [
    "EpisodeStructuralBlocker",
    "EpisodeStructuralBlockerCode",
    "LowZoneEpisodeEvaluation",
    "evaluate_low_zone_episode",
]
