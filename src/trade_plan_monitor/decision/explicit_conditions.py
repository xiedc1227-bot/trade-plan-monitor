"""Pure condition evaluation for the versioned explicit-rules-v1 mode."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trade_plan_monitor.decision.models import (
    ConditionOutcome,
    EvidenceFact,
    EvidenceUnit,
    MissingInputCode,
)
from trade_plan_monitor.domain.plan_models import (
    CompletedCloseBelowCondition,
    CompletedCloseInRangeCondition,
    ExplicitAllCondition,
    ExplicitAnyCondition,
    ExplicitConditionNode,
    ManualEventRiskClearCondition,
    VolumeToMeanGteCondition,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import ShanghaiDatetime, TradingDay

PlanPath = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class ExplicitConditionEvidence(BaseModel):
    """Path-addressed evidence that does not widen the legacy result contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    plan_path: PlanPath
    condition: ExplicitConditionNode
    outcome: ConditionOutcome
    facts: tuple[EvidenceFact, ...] = Field(default=(), max_length=16)
    missing_inputs: tuple[MissingInputCode, ...] = Field(default=(), max_length=4)
    children: tuple[ExplicitConditionEvidence, ...] = Field(default=(), max_length=50)
    bar_ends: tuple[ShanghaiDatetime, ...] = Field(default=(), max_length=501)

    @model_validator(mode="after")
    def validate_shape(self) -> ExplicitConditionEvidence:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("explicit evidence fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("explicit evidence missing inputs must be unique")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs and not any(
                child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children
            ):
                raise ValueError("missing explicit evidence requires one missing input")
        elif self.missing_inputs:
            raise ValueError("known explicit evidence cannot retain missing inputs")
        return self


def _fact(key: str, value: object, unit: EvidenceUnit) -> EvidenceFact:
    return EvidenceFact(key=key, value=value, unit=unit)


def _missing(
    condition: ExplicitConditionNode,
    plan_path: str,
    code: MissingInputCode,
) -> ExplicitConditionEvidence:
    return ExplicitConditionEvidence(
        plan_path=plan_path,
        condition=condition,
        outcome=ConditionOutcome.MISSING_INPUT,
        missing_inputs=(code,),
    )


def _current_bar(
    condition: ExplicitConditionNode,
    *,
    bars: tuple[FiveMinuteBar, ...],
    target_bucket_end: datetime,
    plan_path: str,
) -> FiveMinuteBar | ExplicitConditionEvidence:
    if not bars or bars[-1].bar_end != target_bucket_end:
        return _missing(condition, plan_path, MissingInputCode.COMPLETE_5M_BAR)
    ends = tuple(bar.bar_end for bar in bars)
    if any(current <= previous for previous, current in pairwise(ends)):
        return _missing(condition, plan_path, MissingInputCode.COMPLETE_5M_BAR_WINDOW)
    symbols = {bar.symbol for bar in bars}
    formulas = {bar.formula_version for bar in bars}
    if len(symbols) != 1 or formulas != {"ta-v1"}:
        return _missing(condition, plan_path, MissingInputCode.COMPLETE_5M_BAR_WINDOW)
    return bars[-1]


def _bars_are_adjacent(
    previous: FiveMinuteBar,
    current: FiveMinuteBar,
    trading_calendar: tuple[TradingDay, ...],
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
    current_day = next(
        (row for row in trading_calendar if row.cal_date == current.bar_end.date()),
        None,
    )
    if current_day is None:
        return None
    return current_day.is_open and current_day.previous_trade_date == previous.bar_end.date()


def _evaluate_range(
    condition: CompletedCloseInRangeCondition,
    *,
    bars: tuple[FiveMinuteBar, ...],
    target_bucket_end: datetime,
    plan_path: str,
) -> ExplicitConditionEvidence:
    current = _current_bar(
        condition,
        bars=bars,
        target_bucket_end=target_bucket_end,
        plan_path=plan_path,
    )
    if isinstance(current, ExplicitConditionEvidence):
        return current
    low_ok = current.close_fen > condition.low_fen or (
        condition.include_low and current.close_fen == condition.low_fen
    )
    high_ok = current.close_fen < condition.high_fen or (
        condition.include_high and current.close_fen == condition.high_fen
    )
    return ExplicitConditionEvidence(
        plan_path=plan_path,
        condition=condition,
        outcome=(
            ConditionOutcome.SATISFIED
            if low_ok and high_ok
            else ConditionOutcome.UNSATISFIED
        ),
        facts=(
            _fact("close_fen", current.close_fen, EvidenceUnit.FEN),
            _fact("low_fen", condition.low_fen, EvidenceUnit.FEN),
            _fact("high_fen", condition.high_fen, EvidenceUnit.FEN),
            _fact("include_low", condition.include_low, EvidenceUnit.BOOLEAN),
            _fact("include_high", condition.include_high, EvidenceUnit.BOOLEAN),
        ),
        bar_ends=(current.bar_end,),
    )


def _evaluate_below(
    condition: CompletedCloseBelowCondition,
    *,
    bars: tuple[FiveMinuteBar, ...],
    target_bucket_end: datetime,
    plan_path: str,
) -> ExplicitConditionEvidence:
    current = _current_bar(
        condition,
        bars=bars,
        target_bucket_end=target_bucket_end,
        plan_path=plan_path,
    )
    if isinstance(current, ExplicitConditionEvidence):
        return current
    return ExplicitConditionEvidence(
        plan_path=plan_path,
        condition=condition,
        outcome=(
            ConditionOutcome.SATISFIED
            if current.close_fen < condition.price_fen
            else ConditionOutcome.UNSATISFIED
        ),
        facts=(
            _fact("close_fen", current.close_fen, EvidenceUnit.FEN),
            _fact("price_fen", condition.price_fen, EvidenceUnit.FEN),
        ),
        bar_ends=(current.bar_end,),
    )


def _evaluate_volume_mean(
    condition: VolumeToMeanGteCondition,
    *,
    bars: tuple[FiveMinuteBar, ...],
    target_bucket_end: datetime,
    trading_calendar: tuple[TradingDay, ...],
    plan_path: str,
) -> ExplicitConditionEvidence:
    current = _current_bar(
        condition,
        bars=bars,
        target_bucket_end=target_bucket_end,
        plan_path=plan_path,
    )
    if isinstance(current, ExplicitConditionEvidence):
        return current
    required_count = condition.window_bars + 1
    if len(bars) < required_count:
        return _missing(condition, plan_path, MissingInputCode.ROLLING_VOLUME_WINDOW)
    window = bars[-required_count:]
    for previous, following in pairwise(window):
        adjacent = _bars_are_adjacent(previous, following, trading_calendar)
        if adjacent is None:
            return _missing(condition, plan_path, MissingInputCode.TRADING_CALENDAR)
        if not adjacent:
            return _missing(condition, plan_path, MissingInputCode.ROLLING_VOLUME_WINDOW)
    prior = window[:-1]
    sum_volume = sum(bar.volume_shares for bar in prior)
    ratio_numerator, ratio_denominator = condition.minimum_ratio.as_integer_ratio()
    satisfied = (
        current.volume_shares * condition.window_bars * ratio_denominator
        >= sum_volume * ratio_numerator
    )
    precision = max(28, len(str(sum_volume)) + len(str(ratio_numerator)) + 10)
    with localcontext() as context:
        context.prec = precision
        mean_volume = Decimal(sum_volume) / Decimal(condition.window_bars)
        threshold_volume = (
            condition.minimum_ratio * Decimal(sum_volume) / Decimal(condition.window_bars)
        )
    return ExplicitConditionEvidence(
        plan_path=plan_path,
        condition=condition,
        outcome=(
            ConditionOutcome.SATISFIED if satisfied else ConditionOutcome.UNSATISFIED
        ),
        facts=(
            _fact("current_volume_shares", current.volume_shares, EvidenceUnit.SHARES),
            _fact("sum_volume_shares", sum_volume, EvidenceUnit.SHARES),
            _fact("window_bars", condition.window_bars, EvidenceUnit.BARS),
            _fact("mean_volume_shares", mean_volume, EvidenceUnit.SHARES),
            _fact("minimum_ratio", condition.minimum_ratio, EvidenceUnit.RATIO),
            _fact("threshold_volume_shares", threshold_volume, EvidenceUnit.SHARES),
            _fact("history_scope", condition.history_scope, EvidenceUnit.CODE),
        ),
        bar_ends=tuple(bar.bar_end for bar in window),
    )


def _logical_outcome(
    condition: ExplicitAllCondition | ExplicitAnyCondition,
    children: tuple[ExplicitConditionEvidence, ...],
) -> ConditionOutcome:
    if isinstance(condition, ExplicitAllCondition):
        if any(child.outcome is ConditionOutcome.UNSATISFIED for child in children):
            return ConditionOutcome.UNSATISFIED
        if any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
            return ConditionOutcome.MISSING_INPUT
        return ConditionOutcome.SATISFIED
    if any(child.outcome is ConditionOutcome.SATISFIED for child in children):
        return ConditionOutcome.SATISFIED
    if any(child.outcome is ConditionOutcome.MISSING_INPUT for child in children):
        return ConditionOutcome.MISSING_INPUT
    return ConditionOutcome.UNSATISFIED


def evaluate_explicit_condition(
    condition: ExplicitConditionNode,
    *,
    bars: Sequence[FiveMinuteBar],
    target_bucket_end: datetime,
    trading_calendar: Sequence[TradingDay],
    plan_path: str,
    manual_event_risk: bool | None = None,
) -> ExplicitConditionEvidence:
    """Evaluate one v3 tree from only the facts declared by that tree."""

    bar_values = tuple(bars)
    calendar_values = tuple(trading_calendar)
    if isinstance(condition, CompletedCloseInRangeCondition):
        return _evaluate_range(
            condition,
            bars=bar_values,
            target_bucket_end=target_bucket_end,
            plan_path=plan_path,
        )
    if isinstance(condition, CompletedCloseBelowCondition):
        return _evaluate_below(
            condition,
            bars=bar_values,
            target_bucket_end=target_bucket_end,
            plan_path=plan_path,
        )
    if isinstance(condition, VolumeToMeanGteCondition):
        return _evaluate_volume_mean(
            condition,
            bars=bar_values,
            target_bucket_end=target_bucket_end,
            trading_calendar=calendar_values,
            plan_path=plan_path,
        )
    if isinstance(condition, ManualEventRiskClearCondition):
        if manual_event_risk is None:
            return _missing(condition, plan_path, MissingInputCode.MANUAL_EVENT_RISK)
        return ExplicitConditionEvidence(
            plan_path=plan_path,
            condition=condition,
            outcome=(
                ConditionOutcome.SATISFIED
                if not manual_event_risk
                else ConditionOutcome.UNSATISFIED
            ),
            facts=(
                _fact("manual_event_risk", manual_event_risk, EvidenceUnit.BOOLEAN),
            ),
        )
    if isinstance(condition, ExplicitAllCondition | ExplicitAnyCondition):
        children = tuple(
            evaluate_explicit_condition(
                child,
                bars=bar_values,
                target_bucket_end=target_bucket_end,
                trading_calendar=calendar_values,
                plan_path=f"{plan_path}.conditions[{index}]",
                manual_event_risk=manual_event_risk,
            )
            for index, child in enumerate(condition.conditions)
        )
        return ExplicitConditionEvidence(
            plan_path=plan_path,
            condition=condition,
            outcome=_logical_outcome(condition, children),
            children=children,
        )
    raise TypeError(f"unsupported explicit condition {type(condition).__name__}")


__all__ = ["ExplicitConditionEvidence", "evaluate_explicit_condition"]
