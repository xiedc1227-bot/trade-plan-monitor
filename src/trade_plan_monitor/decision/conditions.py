"""Pure, closed evaluators for every allowlisted plan condition."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise
from types import MappingProxyType
from typing import cast

from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    ConditionOutcome,
    EvaluationContext,
    EvidenceFact,
    EvidenceUnit,
    IndexConditionEvidence,
    IntradayEvaluationTarget,
    MissingInputCode,
    OfficialCloseEvaluationTarget,
    RiskStatus,
)
from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    CloseInBarLowerHalfCondition,
    ConditionNode,
    ConsecutiveClosesBelowLevelCondition,
    DistanceFromLimitDownGteCondition,
    IndexCloseGteMaCondition,
    IndexCloseLteMaCondition,
    IndexMaNonDecreasingCondition,
    IndexMaNonIncreasingCondition,
    IndexReturnGteCondition,
    IndexReturnLteCondition,
    LowerBandHitsLteCondition,
    MacdHistImprovementGteCondition,
    ManualEventRiskClearCondition,
    NextTradingDayRecoveryCondition,
    NonDecreasingCloseCondition,
    NoNewLowForBarsCondition,
    OfficialCloseBelowLevelCondition,
    PositionBucketAvailableCondition,
    PriceInZoneCondition,
    PriceReclaimsIndicatorCondition,
    RetreatFromSessionHighGteCondition,
    SellableQuantityGteCondition,
    UpperWickRatioGteCondition,
    VolumeToMedianGteCondition,
    VolumeToMedianLteCondition,
    VolumeToPreviousLteCondition,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.indicators import IndicatorPoint
from trade_plan_monitor.market_data.models import DailyBar, MinuteBar
from trade_plan_monitor.market_index.models import (
    MarketIndexFactRequest,
    MarketIndexFactUnit,
    MarketIndexHealth,
    MarketIndexIssueCode,
    ReturnFactRequest,
    SmaFactRequest,
    SmaLookbackFactRequest,
)

_MAX_CONDITION_DEPTH = 4
_MAX_CONDITION_LEAVES = 50
ConditionEvaluator = Callable[[ConditionNode, EvaluationContext], ConditionEvidence]


def _fact(key: str, value: object, unit: EvidenceUnit) -> EvidenceFact:
    return EvidenceFact(key=key, value=value, unit=unit)


def _result(
    condition: ConditionNode,
    outcome: ConditionOutcome,
    *facts: EvidenceFact,
    missing_inputs: tuple[MissingInputCode, ...] = (),
    children: tuple[ConditionEvidence, ...] = (),
    index_evidence: IndexConditionEvidence | None = None,
) -> ConditionEvidence:
    return ConditionEvidence(
        condition=condition,
        outcome=outcome,
        facts=facts,
        missing_inputs=missing_inputs,
        children=children,
        index_evidence=index_evidence,
    )


def _missing(
    condition: ConditionNode,
    code: MissingInputCode,
    *facts: EvidenceFact,
) -> ConditionEvidence:
    return _result(
        condition,
        ConditionOutcome.MISSING_INPUT,
        *facts,
        missing_inputs=(code,),
    )


def _outcome(value: bool) -> ConditionOutcome:
    return ConditionOutcome.SATISFIED if value else ConditionOutcome.UNSATISFIED


IndexCondition = (
    IndexCloseGteMaCondition
    | IndexCloseLteMaCondition
    | IndexMaNonDecreasingCondition
    | IndexMaNonIncreasingCondition
    | IndexReturnGteCondition
    | IndexReturnLteCondition
)
_INDEX_CONDITION_CLASSES = (
    IndexCloseGteMaCondition,
    IndexCloseLteMaCondition,
    IndexMaNonDecreasingCondition,
    IndexMaNonIncreasingCondition,
    IndexReturnGteCondition,
    IndexReturnLteCondition,
)
_INDEX_HISTORY_ISSUES = frozenset(
    {
        MarketIndexIssueCode.MISSING_FIVE_MINUTE_BAR,
        MarketIndexIssueCode.MISSING_OFFICIAL_DAILY_BAR,
        MarketIndexIssueCode.INSUFFICIENT_HISTORY,
        MarketIndexIssueCode.GAPPED_SERIES,
    }
)


def _index_request(condition: IndexCondition) -> MarketIndexFactRequest:
    if isinstance(condition, (IndexCloseGteMaCondition, IndexCloseLteMaCondition)):
        return SmaFactRequest(period=condition.period)
    if isinstance(
        condition,
        (IndexMaNonDecreasingCondition, IndexMaNonIncreasingCondition),
    ):
        return SmaLookbackFactRequest(
            period=condition.period,
            lookback=condition.lookback,
        )
    return ReturnFactRequest(
        window=condition.window,
        window_size=condition.window_size,
    )


def _index_parameters(condition: IndexCondition) -> tuple[EvidenceFact, ...]:
    parameters = [
        _fact("index_role", condition.index_role, EvidenceUnit.CODE),
    ]
    if isinstance(
        condition,
        (
            IndexCloseGteMaCondition,
            IndexCloseLteMaCondition,
            IndexMaNonDecreasingCondition,
            IndexMaNonIncreasingCondition,
        ),
    ):
        parameters.append(_fact("period", condition.period, EvidenceUnit.BARS))
    if isinstance(condition, (IndexMaNonDecreasingCondition, IndexMaNonIncreasingCondition)):
        parameters.append(_fact("lookback", condition.lookback, EvidenceUnit.BARS))
    if isinstance(condition, (IndexReturnGteCondition, IndexReturnLteCondition)):
        parameters.extend(
            (
                _fact("window", condition.window.value, EvidenceUnit.CODE),
                _fact("window_size", condition.window_size, EvidenceUnit.BARS),
                _fact(
                    "threshold_ratio",
                    condition.threshold_ratio,
                    EvidenceUnit.RATIO,
                ),
            )
        )
    return tuple(parameters)


def _index_unit(condition: IndexCondition) -> MarketIndexFactUnit:
    if isinstance(condition, (IndexReturnGteCondition, IndexReturnLteCondition)):
        return MarketIndexFactUnit.RATIO
    return MarketIndexFactUnit.POINTS


def _missing_index(
    condition: IndexCondition,
    context: EvaluationContext,
    plan_path: str,
    missing_inputs: tuple[MissingInputCode, ...],
) -> ConditionEvidence:
    binding = context.plan.reference_market
    if binding is None:  # pragma: no cover - Schema v1 rejects index leaves
        raise ValueError("index condition requires a Schema v2 reference binding")
    snapshot = context.reference_market_snapshot
    request = _index_request(condition)
    index_evidence = IndexConditionEvidence(
        plan_path=plan_path,
        condition_type=condition.type,
        index_code=binding.index_code,
        snapshot_hash=None if snapshot is None else snapshot.snapshot_hash,
        decision_cutoff=context.target_cutoff,
        data_cutoff=None if snapshot is None else snapshot.completed_bucket_at,
        formula_id=request.formula_id,
        formula_definition_hash=(None if snapshot is None else snapshot.formula_definition_hash),
        parameters=_index_parameters(condition),
        actual_value=None,
        comparison_value=None,
        unit=_index_unit(condition),
        outcome=ConditionOutcome.MISSING_INPUT,
        missing_inputs=missing_inputs,
    )
    return _result(
        condition,
        ConditionOutcome.MISSING_INPUT,
        missing_inputs=missing_inputs,
        index_evidence=index_evidence,
    )


def _evaluate_index(
    condition: IndexCondition,
    context: EvaluationContext,
    plan_path: str,
) -> ConditionEvidence:
    binding = context.plan.reference_market
    if binding is None:
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_IDENTITY,),
        )
    snapshot = context.reference_market_snapshot
    if snapshot is None:
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_SNAPSHOT,),
        )
    if (
        snapshot.index_code is not binding.index_code
        or snapshot.mapping_version != binding.mapping_version
    ):
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_IDENTITY,),
        )
    if (
        snapshot.decision_cutoff != context.target_cutoff
        or snapshot.completed_bucket_at is None
        or snapshot.completed_bucket_at > context.target_cutoff
        or snapshot.observed_at > context.evaluated_at
    ):
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_CUTOFF,),
        )
    if snapshot.health is not MarketIndexHealth.LIVE:
        missing = [MissingInputCode.INDEX_HEALTH]
        if any(issue in _INDEX_HISTORY_ISSUES for issue in snapshot.issues):
            missing.append(MissingInputCode.INDEX_HISTORY)
        if MarketIndexIssueCode.FORMULA_MISMATCH in snapshot.issues:
            missing.append(MissingInputCode.INDEX_FORMULA)
        return _missing_index(condition, context, plan_path, tuple(missing))

    request = _index_request(condition)
    matches = tuple(fact for fact in snapshot.indicator_facts if fact.request == request)
    if request not in snapshot.fact_requests or len(matches) != 1:
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_FACT,),
        )
    fact = matches[0]
    if (
        fact.formula_definition_hash != snapshot.formula_definition_hash
        or fact.input_cutoff != snapshot.decision_cutoff
        or fact.health is not MarketIndexHealth.LIVE
    ):
        return _missing_index(
            condition,
            context,
            plan_path,
            (MissingInputCode.INDEX_FORMULA,),
        )

    if isinstance(condition, (IndexCloseGteMaCondition, IndexCloseLteMaCondition)):
        latest = snapshot.latest_completed_five_minute
        if latest is None:  # pragma: no cover - LIVE snapshot invariant
            return _missing_index(
                condition,
                context,
                plan_path,
                (MissingInputCode.INDEX_FACT,),
            )
        actual_value = latest.close_points
        comparison_value = fact.value
        satisfied = (
            actual_value >= comparison_value
            if isinstance(condition, IndexCloseGteMaCondition)
            else actual_value <= comparison_value
        )
    elif isinstance(
        condition,
        (IndexMaNonDecreasingCondition, IndexMaNonIncreasingCondition),
    ):
        if fact.comparison_value is None:  # pragma: no cover - fact model invariant
            return _missing_index(
                condition,
                context,
                plan_path,
                (MissingInputCode.INDEX_FACT,),
            )
        actual_value = fact.value
        comparison_value = fact.comparison_value
        satisfied = (
            actual_value >= comparison_value
            if isinstance(condition, IndexMaNonDecreasingCondition)
            else actual_value <= comparison_value
        )
    else:
        actual_value = fact.value
        comparison_value = condition.threshold_ratio
        satisfied = (
            actual_value >= comparison_value
            if isinstance(condition, IndexReturnGteCondition)
            else actual_value <= comparison_value
        )

    outcome = _outcome(satisfied)
    unit = _index_unit(condition)
    evidence_unit = EvidenceUnit.RATIO if unit is MarketIndexFactUnit.RATIO else EvidenceUnit.POINTS
    index_evidence = IndexConditionEvidence(
        plan_path=plan_path,
        condition_type=condition.type,
        index_code=binding.index_code,
        snapshot_hash=snapshot.snapshot_hash,
        decision_cutoff=context.target_cutoff,
        data_cutoff=snapshot.completed_bucket_at,
        formula_id=request.formula_id,
        formula_definition_hash=snapshot.formula_definition_hash,
        parameters=_index_parameters(condition),
        actual_value=actual_value,
        comparison_value=comparison_value,
        unit=unit,
        outcome=outcome,
    )
    return _result(
        condition,
        outcome,
        _fact("actual_value", actual_value, evidence_unit),
        _fact("comparison_value", comparison_value, evidence_unit),
        index_evidence=index_evidence,
    )


def _latest_bar(context: EvaluationContext) -> FiveMinuteBar | None:
    if not context.complete_5m_bars:
        return None
    latest = context.complete_5m_bars[-1]
    if isinstance(context.target, IntradayEvaluationTarget):
        if latest.bar_end != context.target.bucket_end:
            return None
    elif latest.bar_end.date() != context.trade_date:
        return None
    return latest


def _latest_minute(context: EvaluationContext) -> MinuteBar | None:
    if not context.current_bucket_minutes:
        return None
    latest = context.current_bucket_minutes[-1]
    if isinstance(context.target, IntradayEvaluationTarget):
        if latest.bar_end != context.target.bucket_end:
            return None
    elif latest.bar_end.date() != context.trade_date:
        return None
    return latest


def _bar_ends_are_adjacent(
    context: EvaluationContext,
    previous: FiveMinuteBar,
    current: FiveMinuteBar,
) -> bool | None:
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
    calendar_day = next(
        (item for item in context.trading_calendar if item.cal_date == current.bar_end.date()),
        None,
    )
    if calendar_day is None:
        return None
    return calendar_day.is_open and calendar_day.previous_trade_date == previous.bar_end.date()


def _recent_bars(
    context: EvaluationContext,
    count: int,
) -> tuple[tuple[FiveMinuteBar, ...] | None, MissingInputCode | None]:
    if _latest_bar(context) is None or len(context.complete_5m_bars) < count:
        return None, None
    bars = context.complete_5m_bars[-count:]
    for previous, current in pairwise(bars):
        adjacency = _bar_ends_are_adjacent(context, previous, current)
        if adjacency is None:
            return None, MissingInputCode.TRADING_CALENDAR
        if not adjacency:
            return None, None
    return bars, None


def has_complete_current_day_minutes(context: EvaluationContext) -> bool:
    """Return whether explicit health certifies the exact intraday minute slice."""

    trading_day = context.trading_day
    return (
        isinstance(context.target, IntradayEvaluationTarget)
        and context.data_health.required_data_complete
        and trading_day is not None
        and trading_day.is_open
        and bool(context.current_day_minutes)
        and context.current_day_minutes[-1].bar_end == context.target.bucket_end
    )


def _recent_minutes(
    context: EvaluationContext,
    count: int,
) -> tuple[MinuteBar, ...] | None:
    if _latest_minute(context) is None or len(context.current_bucket_minutes) < count:
        return None
    minutes = context.current_bucket_minutes[-count:]
    if any(
        current.bar_end - previous.bar_end != timedelta(minutes=1)
        for previous, current in pairwise(minutes)
    ):
        return None
    return minutes


def _daily_point(context: EvaluationContext) -> IndicatorPoint | None:
    series = context.daily_indicators
    if series is None or not series.points:
        return None
    latest = series.points[-1]
    if type(latest.bar_at) is not date or latest.bar_at != context.trade_date:
        return None
    return latest


def _official_bar(context: EvaluationContext) -> DailyBar | None:
    reconciliation = context.close_reconciliation
    if (
        not isinstance(context.target, OfficialCloseEvaluationTarget)
        or reconciliation is None
        or not reconciliation.advance_close_risk
        or reconciliation.official_bar is None
        or reconciliation.trade_date != context.trade_date
    ):
        return None
    return reconciliation.official_bar


def _decimal_float(value: float) -> Decimal:
    return Decimal(str(value))


def _fixed_context() -> Context:
    return Context(prec=50, rounding=ROUND_HALF_EVEN)


def _fixed_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(_fixed_context()):
        return numerator / denominator


def _decimal_parts(value: Decimal) -> tuple[int, int]:
    decimal_tuple = value.as_tuple()
    coefficient = 0
    for digit in decimal_tuple.digits:
        coefficient = coefficient * 10 + digit
    if decimal_tuple.sign:
        coefficient = -coefficient
    return coefficient, int(decimal_tuple.exponent)


def _decimal_from_parts(coefficient: int, exponent: int) -> Decimal:
    sign = int(coefficient < 0)
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    return Decimal((sign, digits, exponent))


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    left_coefficient, left_exponent = _decimal_parts(left)
    right_coefficient, right_exponent = _decimal_parts(right)
    return _decimal_from_parts(
        left_coefficient * right_coefficient,
        left_exponent + right_exponent,
    )


def _exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    left_coefficient, left_exponent = _decimal_parts(left)
    right_coefficient, right_exponent = _decimal_parts(right)
    result_exponent = min(left_exponent, right_exponent)
    result_coefficient = left_coefficient * 10 ** (left_exponent - result_exponent)
    result_coefficient -= right_coefficient * 10 ** (right_exponent - result_exponent)
    return _decimal_from_parts(result_coefficient, result_exponent)


def _scaled_integer(value: int, *, decimal_places: int) -> Decimal:
    return _decimal_from_parts(value, -decimal_places)


def _fen_to_yuan_exact(value: int) -> Decimal:
    return _scaled_integer(value, decimal_places=2)


def _lte_product(value: Decimal, base: Decimal, ratio: Decimal) -> bool:
    return value <= _exact_multiply(base, ratio)


def _gte_product(value: Decimal, base: Decimal, ratio: Decimal) -> bool:
    return value >= _exact_multiply(base, ratio)


def _rolling_median(values: tuple[int, ...]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[midpoint])
    total = ordered[midpoint - 1] + ordered[midpoint]
    if total % 2 == 0:
        return Decimal(total // 2)
    return _scaled_integer(total * 5, decimal_places=1)


def _evaluate_price_in_zone(
    condition: PriceInZoneCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    minute = _latest_minute(context)
    if minute is None:
        return _missing(condition, MissingInputCode.COMPLETE_MINUTE_BAR)
    zone = (
        context.plan.levels.low_buy if condition.zone == "LOW_BUY" else context.plan.levels.pressure
    )
    above_low = (
        minute.close_fen >= zone.low_fen if zone.include_low else minute.close_fen > zone.low_fen
    )
    below_high = (
        minute.close_fen <= zone.high_fen if zone.include_high else minute.close_fen < zone.high_fen
    )
    return _result(
        condition,
        _outcome(above_low and below_high),
        _fact("price_fen", minute.close_fen, EvidenceUnit.FEN),
        _fact("price_at", minute.bar_end, EvidenceUnit.DATETIME),
        _fact("zone_low_fen", zone.low_fen, EvidenceUnit.FEN),
        _fact("zone_high_fen", zone.high_fen, EvidenceUnit.FEN),
        _fact("include_low", zone.include_low, EvidenceUnit.BOOLEAN),
        _fact("include_high", zone.include_high, EvidenceUnit.BOOLEAN),
    )


def _evaluate_no_new_low(
    condition: NoNewLowForBarsCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    episode = context.low_zone_episode
    if episode is None:
        return _result(condition, ConditionOutcome.UNSATISFIED)
    active = episode.status.value in {"ACTIVE", "ALERTED"}
    return _result(
        condition,
        _outcome(active and episode.bars_since_low >= condition.bars),
        _fact("episode_low_fen", episode.episode_low_fen, EvidenceUnit.FEN),
        _fact("bars_since_low", episode.bars_since_low, EvidenceUnit.BARS),
        _fact("required_bars", condition.bars, EvidenceUnit.BARS),
    )


def _evaluate_non_decreasing_close(
    condition: NonDecreasingCloseCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bars, missing_code = _recent_bars(context, 2)
    if bars is None:
        return _missing(
            condition,
            missing_code or MissingInputCode.PREVIOUS_5M_BAR,
        )
    previous, latest = bars
    delta = latest.close_fen - previous.close_fen
    return _result(
        condition,
        _outcome(delta >= 0),
        _fact("previous_close_fen", previous.close_fen, EvidenceUnit.FEN),
        _fact("latest_close_fen", latest.close_fen, EvidenceUnit.FEN),
        _fact("close_delta_fen", delta, EvidenceUnit.FEN),
    )


def _evaluate_volume_to_previous_lte(
    condition: VolumeToPreviousLteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bars, missing_code = _recent_bars(context, 2)
    if bars is None:
        return _missing(
            condition,
            missing_code or MissingInputCode.PREVIOUS_5M_BAR,
        )
    previous, latest = bars
    previous_volume = Decimal(previous.volume_shares)
    latest_volume = Decimal(latest.volume_shares)
    threshold = _exact_multiply(previous_volume, condition.max_ratio)
    facts = [
        _fact("previous_volume_shares", previous.volume_shares, EvidenceUnit.SHARES),
        _fact("latest_volume_shares", latest.volume_shares, EvidenceUnit.SHARES),
        _fact("maximum_ratio", condition.max_ratio, EvidenceUnit.RATIO),
        _fact("threshold_volume_shares", threshold, EvidenceUnit.SHARES),
    ]
    if previous.volume_shares > 0:
        facts.append(
            _fact(
                "observed_ratio",
                _fixed_ratio(latest_volume, previous_volume),
                EvidenceUnit.RATIO,
            )
        )
    return _result(
        condition,
        _outcome(_lte_product(latest_volume, previous_volume, condition.max_ratio)),
        *facts,
    )


def _median_volume_facts(
    condition: VolumeToMedianLteCondition | VolumeToMedianGteCondition,
    context: EvaluationContext,
) -> tuple[FiveMinuteBar, Decimal, Decimal, tuple[EvidenceFact, ...]] | MissingInputCode | None:
    bars, missing_code = _recent_bars(context, condition.window_bars + 1)
    if bars is None:
        return missing_code
    prior = bars[:-1]
    latest = bars[-1]
    median = _rolling_median(tuple(bar.volume_shares for bar in prior))
    ratio = (
        condition.max_ratio
        if isinstance(condition, VolumeToMedianLteCondition)
        else condition.minimum_ratio
    )
    threshold = _exact_multiply(median, ratio)
    facts = [
        _fact("latest_volume_shares", latest.volume_shares, EvidenceUnit.SHARES),
        _fact("median_volume_shares", median, EvidenceUnit.SHARES),
        _fact("window_bars", condition.window_bars, EvidenceUnit.BARS),
        _fact("threshold_volume_shares", threshold, EvidenceUnit.SHARES),
    ]
    facts.append(
        _fact(
            "maximum_ratio"
            if isinstance(condition, VolumeToMedianLteCondition)
            else "minimum_ratio",
            ratio,
            EvidenceUnit.RATIO,
        )
    )
    if median > 0:
        facts.append(
            _fact(
                "observed_ratio",
                _fixed_ratio(Decimal(latest.volume_shares), median),
                EvidenceUnit.RATIO,
            )
        )
    return latest, median, threshold, tuple(facts)


def _evaluate_volume_to_median_lte(
    condition: VolumeToMedianLteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    evidence = _median_volume_facts(condition, context)
    if isinstance(evidence, MissingInputCode):
        return _missing(condition, evidence)
    if evidence is None:
        return _missing(condition, MissingInputCode.ROLLING_VOLUME_WINDOW)
    latest, median, _threshold, facts = evidence
    return _result(
        condition,
        _outcome(
            _lte_product(
                Decimal(latest.volume_shares),
                median,
                condition.max_ratio,
            )
        ),
        *facts,
    )


def _evaluate_volume_to_median_gte(
    condition: VolumeToMedianGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    evidence = _median_volume_facts(condition, context)
    if isinstance(evidence, MissingInputCode):
        return _missing(condition, evidence)
    if evidence is None:
        return _missing(condition, MissingInputCode.ROLLING_VOLUME_WINDOW)
    latest, median, _threshold, facts = evidence
    if median == 0:
        return _missing(
            condition,
            MissingInputCode.ROLLING_VOLUME_WINDOW,
            *facts,
        )
    return _result(
        condition,
        _outcome(
            _gte_product(
                Decimal(latest.volume_shares),
                median,
                condition.minimum_ratio,
            )
        ),
        *facts,
    )


def _evaluate_macd_improvement(
    condition: MacdHistImprovementGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    indicator_snapshot = context.daily_indicator_snapshot
    if indicator_snapshot is None or len(indicator_snapshot.series.points) < 2:
        return _missing(condition, MissingInputCode.DAILY_INDICATORS)
    series = indicator_snapshot.series
    if context.trading_day is None:
        return _missing(condition, MissingInputCode.TRADING_CALENDAR)
    previous, current = series.points[-2:]
    if (
        type(previous.bar_at) is not date
        or previous.bar_at != context.trading_day.previous_trade_date
        or type(current.bar_at) is not date
        or current.bar_at != context.trade_date
    ):
        return _missing(condition, MissingInputCode.DAILY_INDICATORS)
    previous_value = _decimal_float(previous.macd_histogram_yuan)
    current_value = _decimal_float(current.macd_histogram_yuan)
    improvement = _exact_subtract(current_value, previous_value)
    return _result(
        condition,
        _outcome(improvement >= condition.minimum_improvement),
        _fact("previous_macd_histogram_yuan", previous_value, EvidenceUnit.YUAN),
        _fact("current_macd_histogram_yuan", current_value, EvidenceUnit.YUAN),
        _fact("macd_histogram_improvement_yuan", improvement, EvidenceUnit.YUAN),
        _fact(
            "minimum_improvement_yuan",
            condition.minimum_improvement,
            EvidenceUnit.YUAN,
        ),
        _fact("previous_indicator_date", previous.bar_at, EvidenceUnit.DATE),
        _fact("current_indicator_date", current.bar_at, EvidenceUnit.DATE),
        _fact(
            "indicator_provenance",
            indicator_snapshot.provenance.value,
            EvidenceUnit.CODE,
        ),
        _fact(
            "indicator_source_as_of",
            indicator_snapshot.source_as_of,
            EvidenceUnit.DATETIME,
        ),
    )


_INDICATOR_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "EMA10": "ema10_yuan",
        "MA20": "ma20_yuan",
        "MA50": "ma50_yuan",
        "MA200": "ma200_yuan",
        "BOLL_MIDDLE": "boll_middle_yuan",
    }
)


def _evaluate_price_reclaims_indicator(
    condition: PriceReclaimsIndicatorCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    minutes = _recent_minutes(context, 5)
    if minutes is None:
        return _missing(condition, MissingInputCode.COMPLETE_MINUTE_BAR)
    point = _daily_point(context)
    if point is None:
        return _missing(condition, MissingInputCode.DAILY_INDICATORS)
    raw_value = getattr(point, _INDICATOR_FIELDS[condition.indicator])
    if raw_value is None:
        return _missing(
            condition,
            MissingInputCode.INDICATOR_VALUE,
            _fact("previous_price_fen", minutes[-2].close_fen, EvidenceUnit.FEN),
            _fact("price_fen", minutes[-1].close_fen, EvidenceUnit.FEN),
        )
    indicator_value = _decimal_float(raw_value)
    crossing: tuple[MinuteBar, MinuteBar] | None = None
    for previous_minute, current_minute in pairwise(minutes):
        previous_price_yuan = _fen_to_yuan_exact(previous_minute.close_fen)
        current_price_yuan = _fen_to_yuan_exact(current_minute.close_fen)
        if previous_price_yuan < indicator_value <= current_price_yuan:
            crossing = (previous_minute, current_minute)
            break

    evidence_previous, evidence_current = crossing or (minutes[-2], minutes[-1])
    previous_price_yuan = _fen_to_yuan_exact(evidence_previous.close_fen)
    price_yuan = _fen_to_yuan_exact(evidence_current.close_fen)
    bucket_end_price_yuan = _fen_to_yuan_exact(minutes[-1].close_fen)
    indicator_snapshot = context.daily_indicator_snapshot
    if indicator_snapshot is None:
        return _missing(condition, MissingInputCode.DAILY_INDICATORS)
    return _result(
        condition,
        _outcome(crossing is not None and bucket_end_price_yuan >= indicator_value),
        _fact("previous_price_fen", evidence_previous.close_fen, EvidenceUnit.FEN),
        _fact("price_fen", evidence_current.close_fen, EvidenceUnit.FEN),
        _fact("previous_price_yuan", previous_price_yuan, EvidenceUnit.YUAN),
        _fact("price_yuan", price_yuan, EvidenceUnit.YUAN),
        _fact("bucket_end_price_fen", minutes[-1].close_fen, EvidenceUnit.FEN),
        _fact("bucket_end_price_yuan", bucket_end_price_yuan, EvidenceUnit.YUAN),
        _fact("indicator_yuan", indicator_value, EvidenceUnit.YUAN),
        _fact("indicator", condition.indicator, EvidenceUnit.CODE),
        _fact(
            "indicator_provenance",
            indicator_snapshot.provenance.value,
            EvidenceUnit.CODE,
        ),
        _fact(
            "indicator_source_as_of",
            indicator_snapshot.source_as_of,
            EvidenceUnit.DATETIME,
        ),
        *(
            (
                _fact(
                    "crossing_from_price_fen",
                    crossing[0].close_fen,
                    EvidenceUnit.FEN,
                ),
                _fact(
                    "crossing_to_price_fen",
                    crossing[1].close_fen,
                    EvidenceUnit.FEN,
                ),
                _fact("crossing_at", crossing[1].bar_end, EvidenceUnit.DATETIME),
            )
            if crossing is not None
            else ()
        ),
    )


def _evaluate_upper_wick(
    condition: UpperWickRatioGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bar = _latest_bar(context)
    if bar is None:
        return _missing(condition, MissingInputCode.COMPLETE_5M_BAR)
    bar_range = bar.high_fen - bar.low_fen
    upper_wick = bar.high_fen - max(bar.open_fen, bar.close_fen)
    ratio = Decimal(0) if bar_range == 0 else _fixed_ratio(Decimal(upper_wick), Decimal(bar_range))
    return _result(
        condition,
        _outcome(
            bar_range > 0
            and _gte_product(
                Decimal(upper_wick),
                Decimal(bar_range),
                condition.minimum_ratio,
            )
        ),
        _fact("upper_wick_fen", upper_wick, EvidenceUnit.FEN),
        _fact("bar_range_fen", bar_range, EvidenceUnit.FEN),
        _fact("upper_wick_ratio", ratio, EvidenceUnit.RATIO),
        _fact("minimum_ratio", condition.minimum_ratio, EvidenceUnit.RATIO),
    )


def _evaluate_retreat_from_session_high(
    condition: RetreatFromSessionHighGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    if not has_complete_current_day_minutes(context):
        return _missing(condition, MissingInputCode.SESSION_BARS)
    minute = _latest_minute(context)
    session_bars = tuple(
        value for value in context.complete_5m_bars if value.bar_end.date() == context.trade_date
    )
    if minute is None or not session_bars:
        return _missing(condition, MissingInputCode.SESSION_BARS)
    session_high = max(
        *(value.high_fen for value in session_bars),
        *(value.high_fen for value in context.current_bucket_minutes),
    )
    retreat_fen = session_high - minute.close_fen
    ratio = _fixed_ratio(Decimal(retreat_fen), Decimal(session_high))
    return _result(
        condition,
        _outcome(
            retreat_fen >= 0
            and _gte_product(
                Decimal(retreat_fen),
                Decimal(session_high),
                condition.minimum_ratio,
            )
        ),
        _fact("session_high_fen", session_high, EvidenceUnit.FEN),
        _fact("latest_price_fen", minute.close_fen, EvidenceUnit.FEN),
        _fact("retreat_fen", retreat_fen, EvidenceUnit.FEN),
        _fact("retreat_ratio", ratio, EvidenceUnit.RATIO),
        _fact("minimum_ratio", condition.minimum_ratio, EvidenceUnit.RATIO),
    )


def _evaluate_close_in_lower_half(
    condition: CloseInBarLowerHalfCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bar = _latest_bar(context)
    if bar is None:
        return _missing(condition, MissingInputCode.COMPLETE_5M_BAR)
    bar_range = bar.high_fen - bar.low_fen
    close_twice = 2 * bar.close_fen
    midpoint_twice = bar.high_fen + bar.low_fen
    return _result(
        condition,
        _outcome(bar_range > 0 and close_twice <= midpoint_twice),
        _fact("close_twice_fen", close_twice, EvidenceUnit.FEN),
        _fact("bar_midpoint_twice_fen", midpoint_twice, EvidenceUnit.FEN),
        _fact("bar_range_fen", bar_range, EvidenceUnit.FEN),
    )


def _evaluate_consecutive_closes_below(
    condition: ConsecutiveClosesBelowLevelCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bars, missing_code = _recent_bars(context, condition.bars)
    if bars is None:
        return _missing(
            condition,
            missing_code or MissingInputCode.COMPLETE_5M_BAR_WINDOW,
        )
    reference = context.plan.levels.pressure_reference_fen
    count = sum(bar.close_fen < reference for bar in bars)
    return _result(
        condition,
        _outcome(count == condition.bars),
        _fact("pressure_reference_fen", reference, EvidenceUnit.FEN),
        _fact("consecutive_bars", count, EvidenceUnit.BARS),
        _fact("required_bars", condition.bars, EvidenceUnit.BARS),
        *(
            _fact(f"close_{index}_fen", bar.close_fen, EvidenceUnit.FEN)
            for index, bar in enumerate(bars, start=1)
        ),
    )


def _evaluate_official_close_below(
    condition: OfficialCloseBelowLevelCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bar = _official_bar(context)
    if bar is None:
        return _missing(condition, MissingInputCode.OFFICIAL_DAILY_CLOSE)
    risk_line = context.plan.levels.risk_line_fen
    return _result(
        condition,
        _outcome(bar.close_fen < risk_line),
        _fact("official_close_fen", bar.close_fen, EvidenceUnit.FEN),
        _fact("risk_line_fen", risk_line, EvidenceUnit.FEN),
        _fact("official_trade_date", bar.trade_date, EvidenceUnit.DATE),
    )


def _evaluate_next_trading_day_recovery(
    condition: NextTradingDayRecoveryCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    risk = context.risk_state
    if risk.status is RiskStatus.CLEAR or risk.breach_trade_date is None:
        return _result(
            condition,
            ConditionOutcome.UNSATISFIED,
            _fact("risk_status", risk.status.value, EvidenceUnit.CODE),
        )
    if context.trading_day is None:
        return _missing(
            condition,
            MissingInputCode.TRADING_CALENDAR,
            _fact("breach_trade_date", risk.breach_trade_date, EvidenceUnit.DATE),
        )
    bar = _official_bar(context)
    if bar is None:
        return _missing(
            condition,
            MissingInputCode.OFFICIAL_DAILY_CLOSE,
            _fact("breach_trade_date", risk.breach_trade_date, EvidenceUnit.DATE),
        )
    is_next_day = (
        context.trading_day.is_open
        and context.trading_day.previous_trade_date == risk.breach_trade_date
    )
    risk_line = context.plan.levels.risk_line_fen
    return _result(
        condition,
        _outcome(is_next_day and bar.close_fen >= risk_line),
        _fact("breach_trade_date", risk.breach_trade_date, EvidenceUnit.DATE),
        _fact(
            "previous_trade_date",
            context.trading_day.previous_trade_date,
            EvidenceUnit.DATE,
        ),
        _fact("official_close_fen", bar.close_fen, EvidenceUnit.FEN),
        _fact("risk_line_fen", risk_line, EvidenceUnit.FEN),
        _fact("calendar_is_open", context.trading_day.is_open, EvidenceUnit.BOOLEAN),
    )


def _evaluate_position_bucket_available(
    condition: PositionBucketAvailableCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    current = sum(
        lot.remaining_quantity for lot in context.positions if lot.bucket == condition.bucket
    )
    total = sum(lot.remaining_quantity for lot in context.positions)
    target = (
        context.plan.position.core_target_qty
        if condition.bucket == "CORE"
        else context.plan.position.tactical_target_qty
    )
    available = max(
        0,
        min(target - current, context.plan.position.max_qty - total),
    )
    return _result(
        condition,
        _outcome(available >= context.plan.position.lot_size),
        _fact("bucket_quantity", current, EvidenceUnit.SHARES),
        _fact("bucket_target_quantity", target, EvidenceUnit.SHARES),
        _fact("total_quantity", total, EvidenceUnit.SHARES),
        _fact("maximum_quantity", context.plan.position.max_qty, EvidenceUnit.SHARES),
        _fact("available_quantity", available, EvidenceUnit.SHARES),
        _fact("lot_size", context.plan.position.lot_size, EvidenceUnit.SHARES),
    )


def _evaluate_sellable_quantity(
    condition: SellableQuantityGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    if context.trading_day is None:
        return _missing(condition, MissingInputCode.TRADING_CALENDAR)
    if not context.trading_day.is_open:
        return _result(
            condition,
            ConditionOutcome.UNSATISFIED,
            _fact("calendar_is_open", False, EvidenceUnit.BOOLEAN),
        )
    sellable = sum(
        lot.remaining_quantity
        for lot in context.positions
        if lot.bucket == condition.bucket and lot.acquired_trade_date < context.trade_date
    )
    return _result(
        condition,
        _outcome(sellable >= condition.quantity),
        _fact("sellable_quantity", sellable, EvidenceUnit.SHARES),
        _fact("required_quantity", condition.quantity, EvidenceUnit.SHARES),
        _fact("position_bucket", condition.bucket, EvidenceUnit.CODE),
        _fact("current_trade_date", context.trade_date, EvidenceUnit.DATE),
    )


def _evaluate_manual_event_risk_clear(
    condition: ManualEventRiskClearCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    if context.manual_event_risk is None:
        return _missing(condition, MissingInputCode.MANUAL_EVENT_RISK)
    return _result(
        condition,
        _outcome(not context.manual_event_risk),
        _fact(
            "manual_event_risk",
            context.manual_event_risk,
            EvidenceUnit.BOOLEAN,
        ),
    )


def _evaluate_distance_from_limit_down(
    condition: DistanceFromLimitDownGteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    minute = _latest_minute(context)
    if minute is None:
        return _missing(condition, MissingInputCode.COMPLETE_MINUTE_BAR)
    daily_limit = context.daily_limit
    if daily_limit is None:
        return _missing(
            condition,
            MissingInputCode.DAILY_LIMIT,
            _fact("price_fen", minute.close_fen, EvidenceUnit.FEN),
        )
    distance = minute.close_fen - daily_limit.down_limit_fen
    ratio = _fixed_ratio(Decimal(distance), Decimal(daily_limit.down_limit_fen))
    return _result(
        condition,
        _outcome(
            distance >= 0
            and _gte_product(
                Decimal(distance),
                Decimal(daily_limit.down_limit_fen),
                condition.minimum_ratio,
            )
        ),
        _fact("price_fen", minute.close_fen, EvidenceUnit.FEN),
        _fact("down_limit_fen", daily_limit.down_limit_fen, EvidenceUnit.FEN),
        _fact("distance_from_limit_down_fen", distance, EvidenceUnit.FEN),
        _fact("distance_from_limit_down_ratio", ratio, EvidenceUnit.RATIO),
        _fact("minimum_ratio", condition.minimum_ratio, EvidenceUnit.RATIO),
    )


def _evaluate_lower_band_hits(
    condition: LowerBandHitsLteCondition,
    context: EvaluationContext,
) -> ConditionEvidence:
    bars, missing_code = _recent_bars(context, condition.window_bars)
    if bars is None:
        return _missing(
            condition,
            missing_code or MissingInputCode.COMPLETE_5M_BAR_WINDOW,
        )
    series = context.five_minute_indicators
    if series is None or len(series.points) < condition.window_bars:
        return _missing(condition, MissingInputCode.FIVE_MINUTE_INDICATORS)
    points = series.points[-condition.window_bars :]
    if tuple(point.bar_at for point in points) != tuple(bar.bar_end for bar in bars):
        return _missing(condition, MissingInputCode.FIVE_MINUTE_INDICATORS)
    if any(point.boll_lower_yuan is None for point in points):
        return _missing(condition, MissingInputCode.INDICATOR_VALUE)
    lower_bands = tuple(_decimal_float(cast(float, point.boll_lower_yuan)) for point in points)
    hit_count = sum(
        _fen_to_yuan_exact(bar.close_fen) <= lower_band
        for bar, lower_band in zip(bars, lower_bands, strict=True)
    )
    close_minus_lower = tuple(
        _exact_subtract(
            _fen_to_yuan_exact(bar.close_fen),
            lower_band,
        )
        for bar, lower_band in zip(bars, lower_bands, strict=True)
    )
    return _result(
        condition,
        _outcome(hit_count <= condition.max_hits),
        _fact("latest_boll_lower_yuan", lower_bands[-1], EvidenceUnit.YUAN),
        _fact("lower_band_hit_count", hit_count, EvidenceUnit.COUNT),
        _fact("maximum_hits", condition.max_hits, EvidenceUnit.COUNT),
        _fact("window_bars", condition.window_bars, EvidenceUnit.BARS),
        *(
            _fact(
                f"close_minus_lower_{index}_yuan",
                delta,
                EvidenceUnit.YUAN,
            )
            for index, delta in enumerate(close_minus_lower, start=1)
        ),
    )


def _evaluate_all(
    condition: AllCondition,
    context: EvaluationContext,
    plan_path: str | None = None,
) -> ConditionEvidence:
    children = tuple(
        _evaluate(
            child,
            context,
            None if plan_path is None else f"{plan_path}.conditions[{index}]",
        )
        for index, child in enumerate(condition.conditions)
    )
    if any(child.outcome is ConditionOutcome.UNSATISFIED for child in children):
        outcome = ConditionOutcome.UNSATISFIED
    elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
        outcome = ConditionOutcome.MISSING_INPUT
    else:
        outcome = ConditionOutcome.SATISFIED
    return _logical_result(condition, outcome, children)


def _evaluate_any(
    condition: AnyCondition,
    context: EvaluationContext,
    plan_path: str | None = None,
) -> ConditionEvidence:
    children = tuple(
        _evaluate(
            child,
            context,
            None if plan_path is None else f"{plan_path}.conditions[{index}]",
        )
        for index, child in enumerate(condition.conditions)
    )
    if any(child.outcome is ConditionOutcome.SATISFIED for child in children):
        outcome = ConditionOutcome.SATISFIED
    elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
        outcome = ConditionOutcome.MISSING_INPUT
    else:
        outcome = ConditionOutcome.UNSATISFIED
    return _logical_result(condition, outcome, children)


def _logical_result(
    condition: AllCondition | AnyCondition,
    outcome: ConditionOutcome,
    children: tuple[ConditionEvidence, ...],
) -> ConditionEvidence:
    return _result(
        condition,
        outcome,
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
        children=children,
    )


_MUTABLE_EVALUATORS: dict[type[object], ConditionEvaluator] = {
    PriceInZoneCondition: cast(ConditionEvaluator, _evaluate_price_in_zone),
    NoNewLowForBarsCondition: cast(ConditionEvaluator, _evaluate_no_new_low),
    NonDecreasingCloseCondition: cast(ConditionEvaluator, _evaluate_non_decreasing_close),
    VolumeToPreviousLteCondition: cast(
        ConditionEvaluator,
        _evaluate_volume_to_previous_lte,
    ),
    VolumeToMedianLteCondition: cast(
        ConditionEvaluator,
        _evaluate_volume_to_median_lte,
    ),
    VolumeToMedianGteCondition: cast(
        ConditionEvaluator,
        _evaluate_volume_to_median_gte,
    ),
    MacdHistImprovementGteCondition: cast(
        ConditionEvaluator,
        _evaluate_macd_improvement,
    ),
    PriceReclaimsIndicatorCondition: cast(
        ConditionEvaluator,
        _evaluate_price_reclaims_indicator,
    ),
    UpperWickRatioGteCondition: cast(ConditionEvaluator, _evaluate_upper_wick),
    RetreatFromSessionHighGteCondition: cast(
        ConditionEvaluator,
        _evaluate_retreat_from_session_high,
    ),
    CloseInBarLowerHalfCondition: cast(
        ConditionEvaluator,
        _evaluate_close_in_lower_half,
    ),
    ConsecutiveClosesBelowLevelCondition: cast(
        ConditionEvaluator,
        _evaluate_consecutive_closes_below,
    ),
    OfficialCloseBelowLevelCondition: cast(
        ConditionEvaluator,
        _evaluate_official_close_below,
    ),
    NextTradingDayRecoveryCondition: cast(
        ConditionEvaluator,
        _evaluate_next_trading_day_recovery,
    ),
    PositionBucketAvailableCondition: cast(
        ConditionEvaluator,
        _evaluate_position_bucket_available,
    ),
    SellableQuantityGteCondition: cast(
        ConditionEvaluator,
        _evaluate_sellable_quantity,
    ),
    ManualEventRiskClearCondition: cast(
        ConditionEvaluator,
        _evaluate_manual_event_risk_clear,
    ),
    DistanceFromLimitDownGteCondition: cast(
        ConditionEvaluator,
        _evaluate_distance_from_limit_down,
    ),
    LowerBandHitsLteCondition: cast(
        ConditionEvaluator,
        _evaluate_lower_band_hits,
    ),
    IndexCloseGteMaCondition: cast(ConditionEvaluator, _evaluate_index),
    IndexCloseLteMaCondition: cast(ConditionEvaluator, _evaluate_index),
    IndexMaNonDecreasingCondition: cast(ConditionEvaluator, _evaluate_index),
    IndexMaNonIncreasingCondition: cast(ConditionEvaluator, _evaluate_index),
    IndexReturnGteCondition: cast(ConditionEvaluator, _evaluate_index),
    IndexReturnLteCondition: cast(ConditionEvaluator, _evaluate_index),
    AllCondition: cast(ConditionEvaluator, _evaluate_all),
    AnyCondition: cast(ConditionEvaluator, _evaluate_any),
}
CONDITION_EVALUATORS: Mapping[type[object], ConditionEvaluator] = MappingProxyType(
    _MUTABLE_EVALUATORS.copy()
)
del _MUTABLE_EVALUATORS


def _validate_condition_tree(condition: ConditionNode) -> None:
    stack: list[tuple[ConditionNode, int]] = [(condition, 1)]
    leaf_count = 0
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_CONDITION_DEPTH:
            raise ValueError(f"condition nesting depth cannot exceed {_MAX_CONDITION_DEPTH}")
        if type(node) not in CONDITION_EVALUATORS:
            raise TypeError(f"unsupported condition class: {type(node).__name__}")
        if type(node) in {AllCondition, AnyCondition}:
            composite = cast(AllCondition | AnyCondition, node)
            stack.extend((child, depth + 1) for child in reversed(composite.conditions))
        else:
            leaf_count += 1
            if leaf_count > _MAX_CONDITION_LEAVES:
                raise ValueError(f"condition leaf count cannot exceed {_MAX_CONDITION_LEAVES}")


def _evaluate(
    condition: ConditionNode,
    context: EvaluationContext,
    plan_path: str | None,
) -> ConditionEvidence:
    if isinstance(condition, AllCondition):
        return _evaluate_all(condition, context, plan_path)
    if isinstance(condition, AnyCondition):
        return _evaluate_any(condition, context, plan_path)
    if isinstance(condition, _INDEX_CONDITION_CLASSES):
        if plan_path is None:
            raise ValueError("index condition evaluation requires its exact plan path")
        return _evaluate_index(condition, context, plan_path)
    evaluator = CONDITION_EVALUATORS.get(type(condition))
    if evaluator is None:
        raise TypeError(f"unsupported condition class: {type(condition).__name__}")
    return evaluator(condition, context)


def _tree_contains_index(condition: ConditionNode) -> bool:
    stack = [condition]
    while stack:
        node = stack.pop()
        if isinstance(node, _INDEX_CONDITION_CLASSES):
            return True
        if isinstance(node, (AllCondition, AnyCondition)):
            stack.extend(node.conditions)
    return False


def _condition_at_path(context: EvaluationContext, plan_path: str) -> ConditionNode:
    match = re.fullmatch(
        r"(entry|reduction|risk|blockers)\.condition((?:\.conditions\[[0-9]+\])*)",
        plan_path,
    )
    if match is None:
        raise ValueError("index condition plan path is invalid")
    node = getattr(context.plan, match.group(1)).condition
    for child_match in re.finditer(r"\.conditions\[([0-9]+)\]", match.group(2)):
        if not isinstance(node, (AllCondition, AnyCondition)):
            raise ValueError("index condition plan path crosses a leaf")
        index = int(child_match.group(1))
        if index >= len(node.conditions):
            raise ValueError("index condition plan path is out of bounds")
        node = node.conditions[index]
    return node


def _evaluate_validated_condition(
    condition: ConditionNode,
    context: EvaluationContext,
    *,
    plan_path: str | None = None,
) -> ConditionEvidence:
    """Evaluate trusted immutable decision values without repeat serialization."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")
    if type(condition) not in CONDITION_EVALUATORS:
        raise TypeError("condition must be one exact allowlisted condition class")
    _validate_condition_tree(condition)
    if _tree_contains_index(condition):
        if plan_path is None:
            raise ValueError("index condition tree requires its exact plan path")
        if _condition_at_path(context, plan_path) != condition:
            raise ValueError("index condition plan path does not identify the evaluated tree")
    return _evaluate(condition, context, plan_path)


def evaluate_condition(
    condition: ConditionNode,
    context: EvaluationContext,
    *,
    plan_path: str | None = None,
) -> ConditionEvidence:
    """Evaluate one validated condition tree without I/O or state mutation."""

    if type(context) is not EvaluationContext:
        raise TypeError("context must be an EvaluationContext")
    if type(condition) not in CONDITION_EVALUATORS:
        raise TypeError("condition must be one exact allowlisted condition class")

    validated_context = EvaluationContext.model_validate(
        context.model_dump(mode="python", round_trip=True)
    )
    condition_type = type(condition)
    validated_condition = condition_type.model_validate(
        condition.model_dump(mode="python", round_trip=True)
    )
    return _evaluate_validated_condition(
        validated_condition,
        validated_context,
        plan_path=plan_path,
    )


__all__ = [
    "CONDITION_EVALUATORS",
    "evaluate_condition",
    "has_complete_current_day_minutes",
]
