"""Exact, priority-ordered research policy over dated index operands."""

from typing import Literal

from pydantic import field_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.market_index.models import LinkedIndexFacts

Truth = Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]
Regime = Literal["BROKEN", "WEAK", "NORMAL_TRANSITION", "UNKNOWN"]


def all_truth(*values: Truth) -> Truth:
    if "UNSATISFIED" in values:
        return "UNSATISFIED"
    return "MISSING_INPUT" if "MISSING_INPUT" in values else "SATISFIED"


def predicate(left, right, *, inclusive=False) -> Truth:
    if left is None or right is None:
        return "MISSING_INPUT"
    result = left <= right if inclusive else left < right
    return "SATISFIED" if result else "UNSATISFIED"


class MarketRegimeEvidence(DailyValue):
    formula_version: Literal["market-linkage-v1"] = "market-linkage-v1"
    facts: LinkedIndexFacts
    regime: Regime
    below_low20: Truth
    below_ma60: Truth
    below_ma20: Truth
    falling_ma20: Truth
    broken: Truth
    weak: Truth

    @field_validator("facts", mode="before")
    @classmethod
    def facts_json(cls, value):
        from trade_plan_monitor.market_index.canonical import canonical_json

        return (
            LinkedIndexFacts.model_validate_json(canonical_json(value))
            if isinstance(value, dict)
            else value
        )


def classify_market_regime(facts: LinkedIndexFacts) -> MarketRegimeEvidence:
    below_low = predicate(facts.close, facts.low20)
    below60 = predicate(facts.close, facts.ma60)
    below20 = predicate(facts.close, facts.ma20)
    falling = predicate(facts.ma20, facts.ma20_5)
    broken, weak = all_truth(below_low, below60), all_truth(below20, falling)
    regime = (
        "BROKEN"
        if broken == "SATISFIED"
        else "UNKNOWN"
        if broken == "MISSING_INPUT"
        else "WEAK"
        if weak == "SATISFIED"
        else "UNKNOWN"
        if weak == "MISSING_INPUT"
        else "NORMAL_TRANSITION"
    )
    return MarketRegimeEvidence(
        facts=facts,
        regime=regime,
        below_low20=below_low,
        below_ma60=below60,
        below_ma20=below20,
        falling_ma20=falling,
        broken=broken,
        weak=weak,
    )
