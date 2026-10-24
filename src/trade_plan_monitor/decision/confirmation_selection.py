"""One entry route per rule; exception eligibility never grants P0 authority."""

from typing import Literal

from pydantic import TypeAdapter

from trade_plan_monitor.decision.market_regime import all_truth
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition


class ConfirmationSelection(DailyValue):
    group: Literal["S0", "S1", "S2"] | None
    blocker: str | None
    needs_strength: bool


def select_confirmation(*, regime, ordinary_quantity_available, strength="UNKNOWN"):
    if regime == "NORMAL_TRANSITION":
        return ConfirmationSelection(group="S0", blocker=None, needs_strength=False)
    if regime == "WEAK" and ordinary_quantity_available is True:
        return ConfirmationSelection(group="S1", blocker=None, needs_strength=False)
    if regime == "WEAK" and ordinary_quantity_available is False:
        return ConfirmationSelection(
            group=None if strength == "UNKNOWN" else "S1",
            blocker="MARKET_INPUT_UNKNOWN" if strength == "UNKNOWN" else "P1_EXCEPTION_REQUIRED",
            needs_strength=True,
        )
    if regime == "BROKEN" and strength == "NOT_STRONG":
        return ConfirmationSelection(group=None, blocker="MARKET_BROKEN", needs_strength=True)
    if regime == "BROKEN" and strength == "STRONG":
        return ConfirmationSelection(
            group="S2", blocker="P1_EXCEPTION_REQUIRED", needs_strength=True
        )
    return ConfirmationSelection(
        group=None, blocker="MARKET_INPUT_UNKNOWN", needs_strength=regime == "BROKEN"
    )


def confirmation_components(plan, rule, group):
    """Use the existing daily evaluator, retaining each leaf's inspectable proof."""
    if group == "S0":
        return (rule.condition,)
    zone = plan.levels.low_buy.model_dump(mode="json")
    raw = [rule.condition.model_dump(mode="json")]
    raw.extend(
        {"type": "DAILY_PRICE_IN_RANGE", "field": "close", "offset": offset, "range": zone}
        for offset in (1, 0)
    )
    raw.extend(
        [
            {
                "type": "DAILY_CLOSE_SEQUENCE",
                "offset": 0,
                "sessions": 2,
                "mode": "PAIRWISE_NONDECREASING",
                "comparator": None,
                "reference": None,
            },
            {
                "type": "DAILY_VOLUME_RATIO",
                "offset": 0,
                "baseline": "MEAN",
                "window": 20,
                "comparator": "LTE",
                "ratio": "1",
            },
            {
                "type": "DAILY_INDICATOR_COMPARE",
                "indicator": "RSI14",
                "offset": 0,
                "formula_version": "daily-ta-v2",
                "parameters": {"period": 14},
                "comparator": "GT",
                "reference": {
                    "mode": "DYNAMIC",
                    "indicator": "RSI14",
                    "offset": 1,
                    "formula_version": "daily-ta-v2",
                    "parameters": {"period": 14},
                },
            },
        ]
    )
    if group == "S2":
        raw.extend(
            {
                "type": "DAILY_PRICE_COMPARE",
                "field": "close",
                "offset": offset,
                "comparator": "GTE",
                "reference": {
                    "mode": "DYNAMIC",
                    "indicator": "MA20",
                    "offset": 0,
                    "formula_version": "daily-ta-v2",
                    "parameters": {"period": 20},
                },
            }
            for offset in (1, 0)
        )
    elif group != "S1":
        raise ValueError("unsupported confirmation group")
    adapter = TypeAdapter(UnifiedCondition)
    return tuple(adapter.validate_python(value) for value in raw)


def evaluate_confirmation(plan, rule, group, *, series, facts, decision_session, risk):
    if group is None or series is None or series.bars[-1].trade_date != decision_session:
        return "MISSING_INPUT", ()
    if group != "S0":
        days = tuple(d for d in series.session_dates if d <= decision_session)
        # Strict calendar adjacency, including the volume and RSI warm-up.
        wanted = days[-21:]
        if len(wanted) != 21 or tuple(b.trade_date for b in series.bars[-21:]) != wanted:
            return "MISSING_INPUT", ()
    proofs = tuple(
        evaluate_unified_condition(
            c, series, facts=facts, macd_min_observations=plan.monitoring.macd_min_observations
        )
        for c in confirmation_components(plan, rule, group)
    )
    no_risk = {
        "SATISFIED": "UNSATISFIED",
        "UNSATISFIED": "SATISFIED",
        "MISSING_INPUT": "MISSING_INPUT",
    }[risk]
    return all_truth(*(p.outcome for p in proofs), no_risk), proofs
