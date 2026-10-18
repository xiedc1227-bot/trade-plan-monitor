"""Evaluate period-explicit conditions against exact completed market evidence."""

from typing import Literal

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.plan_models import (
    CompletedCloseBelowCondition,
    CompletedCloseInRangeCondition,
    VolumeToMeanGteCondition,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition


class UnifiedConditionEvidence(DailyValue):
    outcome: Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]
    condition: UnifiedCondition
    bar_ids: tuple[str, ...] = ()
    session_dates: tuple = ()
    basis_id: str | None = None
    operands: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    reason: str | None = None
    children: tuple[UnifiedConditionEvidence, ...] = ()


def evaluate_unified_condition(
    condition,
    series,
    *,
    facts=(),
    signal_id=None,
    macd_min_observations=500,
    bars=(),
    target=None,
    trading_calendar=(),
):
    raw = condition.model_dump(mode="json")
    tag = raw["type"]
    if tag in {"ALL", "ANY"}:
        children = tuple(
            evaluate_unified_condition(
                c,
                series,
                facts=facts,
                signal_id=signal_id,
                macd_min_observations=macd_min_observations,
                bars=bars,
                target=target,
                trading_calendar=trading_calendar,
            )
            for c in condition.conditions
        )
        statuses = {c.outcome for c in children}
        decisive, otherwise = (
            ("UNSATISFIED", "SATISFIED") if tag == "ALL" else ("SATISFIED", "UNSATISFIED")
        )
        outcome = (
            decisive
            if decisive in statuses
            else ("MISSING_INPUT" if "MISSING_INPUT" in statuses else otherwise)
        )
        return UnifiedConditionEvidence(outcome=outcome, condition=condition, children=children)
    if tag == "REVIEWED_FACT":
        day = target.date() if target is not None else (
            None if series is None else series.bars[-1].trade_date)
        matching = tuple(f for f in facts if f.get("kind") == condition.fact_kind
            and f.get("verified") is True and (
                condition.validity_scope == "TRADE_DATE" and day is not None
                and f.get("trade_date") == str(day)
                or condition.validity_scope == "SIGNAL" and signal_id is not None
                and f.get("signal_id") == signal_id))
        latest_at = max((f.get("available_at", ""), f.get("verified_at", ""))
            for f in matching) if matching else None
        current = tuple(f for f in matching if (
            f.get("available_at", ""), f.get("verified_at", "")) == latest_at)
        outcomes = {f.get("satisfied", True) for f in current}
        outcome = ("MISSING_INPUT" if len(outcomes) != 1 else
            "SATISFIED" if outcomes == {True} else
            "UNSATISFIED" if outcomes == {False} else "MISSING_INPUT")
        return UnifiedConditionEvidence(condition=condition,
            outcome=outcome,
            fact_ids=tuple(f["id"] for f in current),
            reason=("REVIEWED_FACT_REQUIRED" if not matching else
                "CONFLICTING_REVIEWED_FACT" if len(outcomes) != 1 else None))
    if tag == "DAILY_PRIOR_CLOSE":
        return _prior_close(condition, series)
    if not tag.startswith("MINUTE_"):
        evidence = evaluate_daily_condition(
            condition,
            series,
            facts=facts,
            signal_id=signal_id,
            macd_min_observations=macd_min_observations,
            evidence_model=UnifiedConditionEvidence,
        )
        return UnifiedConditionEvidence.model_validate(evidence.model_dump())
    if target is None or not bars:
        return UnifiedConditionEvidence(
            outcome="MISSING_INPUT", condition=condition, reason="COMPLETE_5M_BAR_WINDOW"
        )
    parameters = {k: v for k, v in raw.items() if k not in {"type", "timeframe_minutes"}}
    model, original_tag = {
        "MINUTE_CLOSE_IN_RANGE": (CompletedCloseInRangeCondition, "COMPLETED_CLOSE_IN_RANGE"),
        "MINUTE_CLOSE_BELOW": (CompletedCloseBelowCondition, "COMPLETED_CLOSE_BELOW"),
        "MINUTE_VOLUME_TO_MEAN_GTE": (VolumeToMeanGteCondition, "VOLUME_TO_MEAN_GTE"),
    }[tag]
    original = model.model_validate({"type": original_tag, **parameters})
    result = evaluate_explicit_condition(
        original,
        bars=bars,
        target_bucket_end=target,
        trading_calendar=trading_calendar,
        plan_path="condition",
    )
    return UnifiedConditionEvidence(
        outcome=result.outcome.value,
        condition=condition,
        bar_ids=tuple(end.isoformat() for end in result.bar_ends),
        operands=tuple(str(f.value) for f in result.facts),
        reason=",".join(c.value for c in result.missing_inputs) or None,
    )


def requires_daily(root):
    if root.type in {"ALL", "ANY"}:
        return any(requires_daily(c) for c in root.conditions)
    return root.type != "REVIEWED_FACT" and not root.type.startswith("MINUTE_")


def _prior_close(condition, series):
    """Certify a prior stage without treating a current close as a later retest."""
    from decimal import Decimal

    from trade_plan_monitor.decision.daily_conditions import compare

    base = dict(condition=condition, basis_id=None if series is None else series.basis_id)
    if series is None:
        return UnifiedConditionEvidence(**base, outcome="MISSING_INPUT",
                                        reason="PRICE_BASIS_UNVERIFIED")
    # A truncated history cannot establish absence of a previous recovery.
    if series.bars[0].trade_date > condition.since_date:
        return UnifiedConditionEvidence(**base, outcome="MISSING_INPUT",
                                        reason="PRIOR_CLOSE_HISTORY_REQUIRED")
    earlier = tuple(b for b in series.bars
                    if condition.since_date <= b.trade_date < series.bars[-1].trade_date)
    matched = tuple(b for b in earlier
                    if compare(b.close, condition.comparator, Decimal(condition.price_fen)))
    evidence = matched[:1] or earlier
    return UnifiedConditionEvidence(
        **base, outcome="SATISFIED" if matched else "UNSATISFIED",
        reason=None if matched else "PRIOR_CLOSE_NOT_SATISFIED",
        bar_ids=tuple(b.bar_id for b in evidence),
        session_dates=tuple(b.trade_date for b in evidence),
        operands=tuple(str(b.close) for b in evidence) + (str(condition.price_fen),),
    )


def requires_minutes(root):
    if root.type in {"ALL", "ANY"}:
        return any(requires_minutes(c) for c in root.conditions)
    return root.type.startswith("MINUTE_")
