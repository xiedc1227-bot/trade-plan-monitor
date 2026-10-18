"""Finite daily condition trees with exact operands and three-valued evidence."""

from datetime import date
from decimal import Decimal
from typing import Literal

from trade_plan_monitor.domain.daily_plan_models import (
    DailyAll,
    DailyAny,
    DailyCandleRatio,
    DailyCloseSequence,
    DailyCondition,
    DailyIndicatorCompare,
    DailyPriceCompare,
    DailyPriceInRange,
    DailyValue,
    DailyVolumeRatio,
    DynamicDailyReference,
    FixedDailyReference,
    ReviewedDailyFact,
)
from trade_plan_monitor.market_data.daily_data import DailySeries
from trade_plan_monitor.market_data.daily_indicators import PARAMETERS, calculate_daily_ta_v2


class DailyConditionEvidence(DailyValue):
    outcome: Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]
    condition: DailyCondition
    bar_ids: tuple[str, ...] = ()
    session_dates: tuple[date, ...] = ()
    basis_id: str | None = None
    operands: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    reason: str | None = None
    children: tuple[DailyConditionEvidence, ...] = ()


def compare(left: Decimal, op: str, right: Decimal) -> bool:
    return {
        "LT": left < right,
        "LTE": left <= right,
        "EQ": left == right,
        "GTE": left >= right,
        "GT": left > right,
    }[op]


def evaluate_daily_condition(
    condition: DailyCondition,
    series: DailySeries | None,
    *,
    facts: tuple[dict, ...] = (),
    signal_id: str | None = None,
    macd_min_observations: int = 500,
    evidence_model=DailyConditionEvidence,
) -> DailyConditionEvidence:
    """Evaluate all children; missing branches remain visible even on a decisive root."""
    raw = condition.model_dump(mode="json")
    if isinstance(condition, DailyAll | DailyAny):
        children = tuple(
            evaluate_daily_condition(
                c,
                series,
                facts=facts,
                signal_id=signal_id,
                macd_min_observations=macd_min_observations,
                evidence_model=evidence_model,
            )
            for c in condition.conditions
        )
        statuses = {c.outcome for c in children}
        decisive, otherwise = (
            ("UNSATISFIED", "SATISFIED")
            if isinstance(condition, DailyAll)
            else ("SATISFIED", "UNSATISFIED")
        )
        outcome = (
            decisive
            if decisive in statuses
            else "MISSING_INPUT"
            if "MISSING_INPUT" in statuses
            else otherwise
        )
        return evidence_model(outcome=outcome, condition=raw, children=children)
    base = {"condition": raw, "basis_id": None if series is None else series.basis_id}

    def missing(reason):
        return evidence_model(outcome="MISSING_INPUT", reason=reason, **base)

    if series is None:
        return missing("PRICE_BASIS_UNVERIFIED")
    if isinstance(condition, ReviewedDailyFact):
        matching = [
            f
            for f in facts
            if f.get("kind") == condition.fact_kind
            and f.get("verified") is True
            and (
                (
                    condition.validity_scope == "TRADE_DATE"
                    and f.get("trade_date") == str(series.bars[-1].trade_date)
                )
                or (
                    condition.validity_scope == "SIGNAL"
                    and signal_id is not None
                    and f.get("signal_id") == signal_id
                )
            )
        ]
        if not matching:
            return missing("REVIEWED_FACT_REQUIRED")
        return evidence_model(
            outcome="SATISFIED",
            fact_ids=tuple(f["id"] for f in matching),
            bar_ids=(series.bars[-1].bar_id,),
            **base,
        )
    offset = condition.offset
    if offset >= len(series.bars):
        return missing("DAILY_HISTORY_MISSING")
    index = len(series.bars) - 1 - offset
    bar = series.bars[index]
    used = [bar]
    indicators = None

    def indicator(name, parameters, point_index):
        nonlocal indicators
        if point_index < 0 or parameters != PARAMETERS[name]:
            return None
        if name.startswith("MACD") and point_index + 1 < macd_min_observations:
            return None
        if indicators is None:
            indicators = calculate_daily_ta_v2(series)
        return indicators[point_index][name]

    def reference(ref, at_index):
        if isinstance(ref, FixedDailyReference):
            return ref.value
        if isinstance(ref, DynamicDailyReference):
            point_index = at_index - ref.offset
            value = indicator(ref.indicator, ref.parameters, point_index)
            if point_index >= 0:
                used.append(series.bars[point_index])
            return value
        return None

    operands = []
    if isinstance(condition, DailyPriceInRange):
        left = getattr(bar, condition.field)
        operands = [left, condition.range.low_fen, condition.range.high_fen]
        satisfied = condition.range.contains(left)
    elif isinstance(condition, DailyPriceCompare | DailyIndicatorCompare):
        left = (
            getattr(bar, condition.field)
            if isinstance(condition, DailyPriceCompare)
            else indicator(condition.indicator, condition.parameters, index)
        )
        right = reference(condition.reference, index)
        if (
            isinstance(condition, DailyPriceCompare)
            and isinstance(condition.reference, DynamicDailyReference)
            and right is not None
        ):
            if condition.reference.indicator in {"RSI14", "BOLL_BANDWIDTH"}:
                return missing("REFERENCE_UNIT_MISMATCH")
            right *= 100
        if isinstance(condition.reference, FixedDailyReference):
            expected = "FEN" if isinstance(condition, DailyPriceCompare) else "INDICATOR"
            if condition.reference.unit != expected:
                return missing("REFERENCE_UNIT_MISMATCH")
        if left is None or right is None:
            return missing("INDICATOR_HISTORY_OR_PARAMETERS_UNVERIFIED")
        operands = [left, right]
        satisfied = compare(left, condition.comparator, right)
    elif isinstance(condition, DailyVolumeRatio):
        prior = series.bars[max(0, index - condition.window) : index]
        if len(prior) != condition.window:
            return missing("DAILY_HISTORY_MISSING")
        used.extend(prior)
        denominator = sum(Decimal(b.volume_shares) for b in prior) / len(prior)
        if denominator == 0:
            return missing("ZERO_VOLUME_BASELINE")
        ratio = Decimal(bar.volume_shares) / denominator
        operands = [bar.volume_shares, denominator, ratio, condition.ratio]
        satisfied = compare(ratio, condition.comparator, condition.ratio)
    elif isinstance(condition, DailyCandleRatio):
        denominator = bar.high - bar.low
        if not denominator:
            return missing("ZERO_CANDLE_RANGE")
        numerator = {
            "LOWER_WICK": min(bar.open, bar.close) - bar.low,
            "UPPER_WICK": bar.high - max(bar.open, bar.close),
            "BODY": abs(bar.close - bar.open),
        }[condition.component]
        ratio = numerator / denominator
        operands = [numerator, denominator, ratio, condition.ratio]
        satisfied = compare(ratio, condition.comparator, condition.ratio)
    elif isinstance(condition, DailyCloseSequence):
        window = series.bars[max(0, index - condition.sessions + 1) : index + 1]
        if len(window) != condition.sessions:
            return missing("DAILY_HISTORY_MISSING")
        used.extend(window)
        operands = [b.close for b in window]
        if condition.mode == "PAIRWISE_NONDECREASING":
            satisfied = all(
                a.close <= b.close for a, b in zip(window[:-1], window[1:], strict=True)
            )
        else:
            refs = [
                reference(condition.reference, index - condition.sessions + 1 + i)
                for i in range(len(window))
            ]
            if any(r is None for r in refs):
                return missing("INDICATOR_HISTORY_OR_PARAMETERS_UNVERIFIED")
            if isinstance(condition.reference, DynamicDailyReference):
                refs = [r * 100 for r in refs]
            satisfied = all(
                compare(b.close, condition.comparator, r) for b, r in zip(window, refs, strict=True)
            )
            operands.extend(refs)
    else:
        return missing("UNSUPPORTED_DAILY_CONDITION")
    unique = {b.bar_id: b for b in used}
    return evidence_model(
        outcome="SATISFIED" if satisfied else "UNSATISFIED",
        operands=tuple(str(v) for v in operands),
        bar_ids=tuple(unique),
        session_dates=tuple(b.trade_date for b in unique.values()),
        **base,
    )
