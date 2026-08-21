"""Pure priority assembly and canonical serialization for decision results."""

from __future__ import annotations

from trade_plan_monitor.decision.conditions import has_complete_current_day_minutes
from trade_plan_monitor.decision.episodes import (
    EpisodeStructuralBlocker,
    EpisodeStructuralBlockerCode,
    LowZoneEpisodeEvaluation,
    evaluate_low_zone_episode,
)
from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    ConditionOutcome,
    DataHealthStatus,
    DecisionZone,
    EpisodeStatus,
    EpisodeTransitionAction,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationEvidence,
    EvaluationResult,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationIdentity,
    IntradayEvaluationTarget,
    MissingInputCode,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationIdentity,
    OfficialCloseEvaluationTarget,
    PositionSummary,
    RuleEvidence,
    RuleEvidenceCode,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
    _canonical_json_text,
)
from trade_plan_monitor.decision.risk import (
    OfficialCloseRiskEvaluation,
    OfficialRiskEvidence,
    PressureReductionEvaluation,
    PressureTouchEvidence,
    evaluate_official_close_risk,
    evaluate_pressure_reduction,
)
from trade_plan_monitor.domain.plan_models import PriceZone

_ENTRY_DATA_CODES = frozenset(
    {
        EpisodeStructuralBlockerCode.DATA_NOT_READY,
        EpisodeStructuralBlockerCode.DAILY_LIMIT_UNKNOWN,
        EpisodeStructuralBlockerCode.EPISODE_HISTORY_GAP,
    }
)
_ENTRY_RISK_CODES = frozenset(
    {
        EpisodeStructuralBlockerCode.BEARISH_VOLUME_EXPANSION,
        EpisodeStructuralBlockerCode.RISK_PENDING,
    }
)


def _fact(key: str, value: object, unit: EvidenceUnit) -> EvidenceFact:
    return EvidenceFact(key=key, value=value, unit=unit)


def _inside_zone(price_fen: int, zone: PriceZone) -> bool:
    above_low = price_fen >= zone.low_fen if zone.include_low else price_fen > zone.low_fen
    below_high = price_fen <= zone.high_fen if zone.include_high else price_fen < zone.high_fen
    return above_low and below_high


def _decision_zone(context: EvaluationContext, price_fen: int | None) -> DecisionZone:
    if price_fen is None:
        return DecisionZone.UNKNOWN
    levels = context.plan.levels
    if price_fen < levels.risk_line_fen:
        return DecisionZone.BELOW_RISK
    if _inside_zone(price_fen, levels.low_buy):
        return DecisionZone.LOW_BUY
    if _inside_zone(price_fen, levels.pressure):
        return DecisionZone.PRESSURE
    if levels.low_buy.high_fen < price_fen < levels.pressure.low_fen:
        return DecisionZone.OBSERVATION
    return DecisionZone.OUTSIDE


def _position_summary(context: EvaluationContext) -> PositionSummary:
    core = sum(lot.remaining_quantity for lot in context.positions if lot.bucket == "CORE")
    tactical = sum(lot.remaining_quantity for lot in context.positions if lot.bucket == "TACTICAL")
    sellable_core = sum(
        lot.remaining_quantity
        for lot in context.positions
        if lot.bucket == "CORE" and lot.acquired_trade_date < context.trade_date
    )
    sellable_tactical = sum(
        lot.remaining_quantity
        for lot in context.positions
        if lot.bucket == "TACTICAL" and lot.acquired_trade_date < context.trade_date
    )
    return PositionSummary(
        core_quantity=core,
        tactical_quantity=tactical,
        total_quantity=core + tactical,
        sellable_core_quantity=sellable_core,
        sellable_tactical_quantity=sellable_tactical,
    )


def _market_facts(
    context: EvaluationContext,
) -> tuple[object | None, int | None]:
    if isinstance(context.target, IntradayEvaluationTarget):
        if not context.current_day_minutes:
            return None, None
        latest = context.current_day_minutes[-1]
        return latest.bar_end, latest.close_fen
    reconciliation = context.close_reconciliation
    if (
        reconciliation is None
        or not reconciliation.advance_close_risk
        or reconciliation.official_bar is None
    ):
        return None, None
    return context.target_cutoff, reconciliation.official_bar.close_fen


def _identity(
    context: EvaluationContext,
) -> IntradayEvaluationIdentity | OfficialCloseEvaluationIdentity:
    common = {
        "plan_hash": context.plan_hash,
        "symbol": context.plan.symbol,
        "formula_version": context.plan.monitoring.indicator_formula_version,
    }
    if isinstance(context.target, IntradayEvaluationTarget):
        return IntradayEvaluationIdentity(
            **common,
            bucket_end=context.target.bucket_end,
        )
    return OfficialCloseEvaluationIdentity(
        **common,
        official_trade_date=context.target.trade_date,
    )


def _map_structural(blocker: EpisodeStructuralBlocker) -> RuleEvidence:
    return RuleEvidence(
        code=RuleEvidenceCode(blocker.code.value),
        outcome=blocker.outcome,
        facts=blocker.facts,
        missing_inputs=blocker.missing_inputs,
    )


def _map_pressure_touch(evidence: PressureTouchEvidence) -> RuleEvidence:
    return RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=evidence.outcome,
        facts=evidence.facts,
        missing_inputs=evidence.missing_inputs,
    )


def _map_official_rule(
    code: RuleEvidenceCode,
    evidence: OfficialRiskEvidence,
) -> RuleEvidence:
    return RuleEvidence(
        code=code,
        outcome=evidence.outcome,
        facts=evidence.facts,
        missing_inputs=evidence.missing_inputs,
    )


def _intraday_data_readiness(
    context: EvaluationContext,
) -> tuple[bool, RuleEvidence]:
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
    missing: list[MissingInputCode] = []
    if trading_day is None or not trading_day.is_open:
        missing.append(MissingInputCode.TRADING_CALENDAR)
    if not minute_history_complete:
        missing.append(MissingInputCode.COMPLETE_MINUTE_BAR)
    if not target_bar_present:
        missing.append(MissingInputCode.COMPLETE_5M_BAR)
    return ready, RuleEvidence(
        code=RuleEvidenceCode.DATA_NOT_READY,
        outcome=(ConditionOutcome.MISSING_INPUT if missing else ConditionOutcome.UNSATISFIED),
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
            _fact("target_bar_present", target_bar_present, EvidenceUnit.BOOLEAN),
        ),
        missing_inputs=tuple(missing),
    )


def _official_data_readiness(
    context: EvaluationContext,
) -> tuple[bool, RuleEvidence]:
    trading_day = context.trading_day
    reconciliation = context.close_reconciliation
    official_ready = bool(
        reconciliation is not None
        and reconciliation.advance_close_risk
        and reconciliation.official_bar is not None
    )
    missing: list[MissingInputCode] = []
    if trading_day is None or not trading_day.is_open:
        missing.append(MissingInputCode.TRADING_CALENDAR)
    if not official_ready:
        missing.append(MissingInputCode.OFFICIAL_DAILY_CLOSE)
    return not missing, RuleEvidence(
        code=RuleEvidenceCode.DATA_NOT_READY,
        outcome=(ConditionOutcome.MISSING_INPUT if missing else ConditionOutcome.UNSATISFIED),
        facts=(
            _fact("target_kind", "OFFICIAL_CLOSE", EvidenceUnit.CODE),
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
            _fact("official_close_ready", official_ready, EvidenceUnit.BOOLEAN),
        ),
        missing_inputs=tuple(missing),
    )


def _append_evidence(
    evidence: EvaluationEvidence,
    *,
    satisfied: list[EvaluationEvidence],
    unmet: list[EvaluationEvidence],
    blockers: list[EvaluationEvidence],
    active_blocker: bool = False,
) -> None:
    if active_blocker:
        blockers.append(evidence)
    elif evidence.outcome is ConditionOutcome.SATISFIED:
        satisfied.append(evidence)
    else:
        unmet.append(evidence)


def _missing_inputs(evidence: EvaluationEvidence) -> tuple[MissingInputCode, ...]:
    values = list(evidence.missing_inputs)
    if isinstance(evidence, ConditionEvidence):
        for child in evidence.children:
            values.extend(_missing_inputs(child))
    return tuple(values)


def _required_inputs(
    blockers: tuple[EvaluationEvidence, ...],
) -> tuple[MissingInputCode, ...]:
    ordered: list[MissingInputCode] = []
    for evidence in blockers:
        for item in _missing_inputs(evidence):
            if item not in ordered:
                ordered.append(item)
    return tuple(ordered)


def _downgrade_suppressed_buy(
    decision: LowZoneEpisodeEvaluation,
) -> tuple[object | None, EpisodeTransitionIntent | None]:
    episode = decision.episode
    if (
        decision.signal_intent is None
        or episode is None
        or episode.status is not EpisodeStatus.ALERTED
    ):
        return episode, decision.transition
    active = episode.model_copy(update={"status": EpisodeStatus.ACTIVE, "alerted_signal": None})
    return active, EpisodeTransitionIntent(
        action=EpisodeTransitionAction.UPSERT,
        episode=active,
    )


def _inactive_result(context: EvaluationContext) -> EvaluationResult:
    evidence = RuleEvidence(
        code=RuleEvidenceCode.PLAN_INACTIVE,
        outcome=ConditionOutcome.UNSATISFIED,
        facts=(_fact("plan_active", False, EvidenceUnit.BOOLEAN),),
    )
    next_step = NextStep(code=NextStepCode.REVIEW_BLOCKER)
    market_data_at, price_fen = _market_facts(context)
    snapshot = SymbolDecisionSnapshot(
        symbol=context.plan.symbol,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=market_data_at,
        price_fen=price_fen,
        zone=_decision_zone(context, price_fen),
        signal_type=SignalType.WAIT,
        position=_position_summary(context),
        episode=context.low_zone_episode,
        risk=context.risk_state,
        data_health=context.data_health,
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=None,
        satisfied_conditions=(),
        unmet_conditions=(),
        blockers=(evidence,),
        next_step=next_step,
        evaluation_identity=_identity(context),
    )


def _official_result(context: EvaluationContext) -> EvaluationResult:
    decision: OfficialCloseRiskEvaluation = evaluate_official_close_risk(context)
    ready, readiness_evidence = _official_data_readiness(context)
    satisfied: list[EvaluationEvidence] = []
    unmet: list[EvaluationEvidence] = []
    blockers: list[EvaluationEvidence] = []
    if not ready:
        _append_evidence(
            readiness_evidence,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=True,
        )
    _append_evidence(
        decision.risk_evidence,
        satisfied=satisfied,
        unmet=unmet,
        blockers=blockers,
        active_blocker=(decision.risk_evidence.outcome is ConditionOutcome.MISSING_INPUT),
    )
    if decision.recovery_evidence is not None:
        recovery = _map_official_rule(
            RuleEvidenceCode.RISK_RECOVERY,
            decision.recovery_evidence,
        )
        _append_evidence(
            recovery,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=(recovery.outcome is ConditionOutcome.MISSING_INPUT),
        )
    if decision.deterioration_evidence is not None:
        deterioration = _map_official_rule(
            RuleEvidenceCode.RISK_DETERIORATION,
            decision.deterioration_evidence,
        )
        _append_evidence(
            deterioration,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=(deterioration.outcome is ConditionOutcome.MISSING_INPUT),
        )

    if not ready or blockers:
        signal_type = SignalType.BLOCKED_DATA
        signal_intent = None
        transitions = ()
        required = _required_inputs(tuple(blockers))
        next_step = NextStep(
            code=(
                NextStepCode.WAIT_FOR_OFFICIAL_CLOSE
                if MissingInputCode.OFFICIAL_DAILY_CLOSE in required
                else NextStepCode.WAIT_FOR_REQUIRED_DATA
            ),
            required_inputs=required,
        )
        risk = context.risk_state
    elif decision.signal_type is not None:
        signal_type = decision.signal_type
        signal_intent = decision.signal_intent
        transitions = () if decision.transition is None else (decision.transition,)
        next_step = (
            signal_intent.next_step
            if signal_intent is not None
            else NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
        )
        risk = decision.risk
    else:
        signal_type = SignalType.WAIT
        signal_intent = None
        transitions = ()
        next_step = NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
        risk = decision.risk

    market_data_at, price_fen = _market_facts(context)
    evidence = tuple(satisfied + unmet + blockers)
    snapshot = SymbolDecisionSnapshot(
        symbol=context.plan.symbol,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=market_data_at,
        price_fen=price_fen,
        zone=_decision_zone(context, price_fen),
        signal_type=signal_type,
        position=_position_summary(context),
        episode=context.low_zone_episode,
        risk=risk,
        data_health=context.data_health,
        condition_evidence=evidence,
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=transitions,
        signal_intent=signal_intent,
        satisfied_conditions=tuple(satisfied),
        unmet_conditions=tuple(unmet),
        blockers=tuple(blockers),
        next_step=next_step,
        evaluation_identity=_identity(context),
    )


def _intraday_result(context: EvaluationContext) -> EvaluationResult:
    pressure: PressureReductionEvaluation = evaluate_pressure_reduction(context)
    episode: LowZoneEpisodeEvaluation = evaluate_low_zone_episode(context)
    ready, readiness_evidence = _intraday_data_readiness(context)
    structural = [_map_structural(item) for item in episode.structural_blockers]
    if not ready and not any(item.code is RuleEvidenceCode.DATA_NOT_READY for item in structural):
        structural.insert(0, readiness_evidence)

    satisfied: list[EvaluationEvidence] = []
    unmet: list[EvaluationEvidence] = []
    blockers: list[EvaluationEvidence] = []
    pressure_touch = _map_pressure_touch(pressure.touch_evidence)
    _append_evidence(
        pressure_touch,
        satisfied=satisfied,
        unmet=unmet,
        blockers=blockers,
        active_blocker=(pressure_touch.outcome is ConditionOutcome.MISSING_INPUT),
    )
    if pressure.reduction_evidence is not None:
        pressure_missing = (
            pressure.touch_evidence.outcome is ConditionOutcome.SATISFIED
            and pressure.reduction_evidence.outcome is ConditionOutcome.MISSING_INPUT
        )
        _append_evidence(
            pressure.reduction_evidence,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=pressure_missing,
        )
    if episode.entry_evidence is not None:
        _append_evidence(
            episode.entry_evidence,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=(episode.entry_evidence.outcome is ConditionOutcome.MISSING_INPUT),
        )
    if episode.blocker_evidence is not None:
        _append_evidence(
            episode.blocker_evidence,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=(episode.blocker_evidence.outcome is not ConditionOutcome.SATISFIED),
        )
    if episode.availability_evidence is not None:
        _append_evidence(
            episode.availability_evidence,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=(
                episode.availability_evidence.outcome is not ConditionOutcome.SATISFIED
            ),
        )
    for item in structural:
        _append_evidence(
            item,
            satisfied=satisfied,
            unmet=unmet,
            blockers=blockers,
            active_blocker=True,
        )

    structural_codes = {item.code for item in structural}
    pressure_data_blocked = bool(
        pressure.touch_evidence.outcome is ConditionOutcome.SATISFIED
        and pressure.reduction_evidence is not None
        and pressure.reduction_evidence.outcome is ConditionOutcome.MISSING_INPUT
    )
    entry_data_blocked = bool(
        structural_codes.intersection(RuleEvidenceCode(item.value) for item in _ENTRY_DATA_CODES)
        or (
            episode.entry_evidence is not None
            and episode.entry_evidence.outcome is ConditionOutcome.MISSING_INPUT
        )
        or (
            episode.blocker_evidence is not None
            and (
                episode.blocker_evidence.outcome is ConditionOutcome.MISSING_INPUT
                or (
                    episode.blocker_evidence.outcome is ConditionOutcome.UNSATISFIED
                    and _missing_inputs(episode.blocker_evidence)
                )
            )
        )
        or (
            episode.availability_evidence is not None
            and episode.availability_evidence.outcome is ConditionOutcome.MISSING_INPUT
        )
    )
    entry_risk_blocked = bool(
        structural_codes.intersection(RuleEvidenceCode(item.value) for item in _ENTRY_RISK_CODES)
        or (
            episode.blocker_evidence is not None
            and episode.blocker_evidence.outcome is ConditionOutcome.UNSATISFIED
        )
        or (
            episode.availability_evidence is not None
            and episode.availability_evidence.outcome is ConditionOutcome.UNSATISFIED
        )
    )

    market_data_at, price_fen = _market_facts(context)
    current_zone = _decision_zone(context, price_fen)
    selected_episode = episode.episode
    episode_transition = episode.transition
    if not ready:
        signal_type = SignalType.BLOCKED_DATA
        signal_intent: SignalIntent | None = None
        selected_episode = context.low_zone_episode
        episode_transition = None
        required = _required_inputs(tuple(blockers))
        next_step = NextStep(
            code=NextStepCode.WAIT_FOR_REQUIRED_DATA,
            required_inputs=required,
        )
    elif pressure.signal_intent is not None:
        signal_type = SignalType.PRESSURE_REDUCE_READY
        signal_intent = pressure.signal_intent
        next_step = signal_intent.next_step
        selected_episode, episode_transition = _downgrade_suppressed_buy(episode)
    elif pressure_data_blocked:
        signal_type = SignalType.BLOCKED_DATA
        signal_intent = None
        next_step = NextStep(
            code=NextStepCode.WAIT_FOR_REQUIRED_DATA,
            required_inputs=_required_inputs(tuple(blockers)),
        )
        selected_episode, episode_transition = _downgrade_suppressed_buy(episode)
    elif entry_data_blocked:
        signal_type = SignalType.BLOCKED_DATA
        signal_intent = None
        next_step = NextStep(
            code=NextStepCode.WAIT_FOR_REQUIRED_DATA,
            required_inputs=_required_inputs(tuple(blockers)),
        )
    elif entry_risk_blocked:
        signal_type = SignalType.BLOCKED_RISK
        signal_intent = None
        next_step = NextStep(code=NextStepCode.REVIEW_BLOCKER)
    elif episode.signal_intent is not None:
        signal_type = SignalType(episode.signal_intent.signal_type.value)
        signal_intent = episode.signal_intent
        next_step = signal_intent.next_step
    elif current_zone is DecisionZone.PRESSURE:
        signal_type = SignalType.WAIT
        signal_intent = None
        next_step = NextStep(code=NextStepCode.WATCH_PRESSURE)
    elif selected_episode is not None and selected_episode.status is not EpisodeStatus.CLOSED:
        signal_type = SignalType.LOW_ZONE_WATCH
        signal_intent = None
        next_step = NextStep(code=NextStepCode.WATCH_LOW_ZONE)
    else:
        signal_type = SignalType.WAIT
        signal_intent = None
        if (
            context.target.bucket_end.hour,
            context.target.bucket_end.minute,
        ) == (15, 0):
            next_step = NextStep(code=NextStepCode.WAIT_FOR_OFFICIAL_CLOSE)
        else:
            next_step = NextStep(code=NextStepCode.WAIT_FOR_COMPLETE_BAR)

    transitions = () if episode_transition is None else (episode_transition,)
    evidence = tuple(satisfied + unmet + blockers)
    snapshot = SymbolDecisionSnapshot(
        symbol=context.plan.symbol,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=market_data_at,
        price_fen=price_fen,
        zone=current_zone,
        signal_type=signal_type,
        position=_position_summary(context),
        episode=selected_episode,
        risk=context.risk_state,
        data_health=context.data_health,
        condition_evidence=evidence,
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=transitions,
        signal_intent=signal_intent,
        satisfied_conditions=tuple(satisfied),
        unmet_conditions=tuple(unmet),
        blockers=tuple(blockers),
        next_step=next_step,
        evaluation_identity=_identity(context),
    )


def evaluate(context: EvaluationContext) -> EvaluationResult:
    """Pure deterministic evaluation with no I/O, clock, or mutation."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")
    if not context.plan_active:
        return _inactive_result(context)
    if isinstance(context.target, OfficialCloseEvaluationTarget):
        return _official_result(context)
    return _intraday_result(context)


def canonical_result_json(result: EvaluationResult) -> str:
    """Return canonical compact JSON for one already validated result."""

    if type(result) is not EvaluationResult:
        raise TypeError("result must be an EvaluationResult")
    return _canonical_json_text(result)


__all__ = ["canonical_result_json", "evaluate"]
