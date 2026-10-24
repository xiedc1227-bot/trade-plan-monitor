"""Opt-in linkage primitives; no activation or inventory authority."""

from math import gcd
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier, PositiveWholeQty
from trade_plan_monitor.domain.unified_plan_models import (
    OfficialDailyConfirmation,
    UnifiedCondition,
    UnifiedIndependentSignal,
    UnifiedRule,
    UnifiedTradePlan,
    UnifiedValidity,
    condition_leaves,
)
from trade_plan_monitor.market_index.identity import ReferenceMarketBinding, resolve_board_reference


class QuantityPolicy(DailyValue):
    """Source-bound sizing policy with no inferred strategy defaults."""

    mode: Literal["MARKET_FACTOR"]
    base_quantity: PositiveWholeQty
    normal_factor: Literal["1"]
    weak_factor: Literal["0.5"]
    rounding: Literal["LEGAL_FLOOR"]
    capacity_policy: Literal["BLOCK_FULL"]
    signal_quantity_policy: Literal["FREEZE"]


class MarketPolicy(DailyValue):
    """Policy identity; source-review bindings must prove its expanded meaning."""

    policy_version: Literal["market-linkage-v1"]
    base_confirmation: Literal["S0"]
    exception_policy: Literal["BLOCK_P1"]


class MarketLinkedRule(DailyValue):
    """Daily tactical entry; deliberately has no fixed quantity attribute."""

    status: Literal["ENABLED"]
    side: Literal["BUY"]
    rule_id: Identifier
    bucket: Literal["TACTICAL"]
    condition: UnifiedCondition
    confirmation: OfficialDailyConfirmation
    execution_window: Literal["NEXT_EXCHANGE_SESSION_ONLY"]
    zone: Literal["LOW_BUY"]
    validity: UnifiedValidity
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"]
    independent_signal: UnifiedIndependentSignal
    market_policy: MarketPolicy
    quantity_policy: QuantityPolicy


class MarketLinkedTradePlan(UnifiedTradePlan):
    """Opt-in linked codec with an explicit boundary from fixed-quantity plans."""

    schema_version: Literal[6] = 6
    execution_version: Literal["condition-plan-v2"] = "condition-plan-v2"
    reference_market: ReferenceMarketBinding
    ordinary_rules: tuple[MarketLinkedRule | UnifiedRule, ...] = Field(max_length=2)

    @model_validator(mode="before")
    @classmethod
    def bounded_expansion(cls, data):
        # S2 adds eight predicates around the complete S0. Count the maximal
        # expanded route once, including the enclosing ALL node.
        if isinstance(data, dict):
            expanded = dict(data)
            rules = []
            for rule in data.get("ordinary_rules", ()):
                if isinstance(rule, dict) and "market_policy" in rule:
                    rule = dict(rule)
                    rule["condition"] = {
                        "type": "ALL",
                        "conditions": [
                            rule.get("condition"),
                            *({"type": "POLICY_PREDICATE"} for _ in range(8)),
                        ],
                    }
                rules.append(rule)
            expanded["ordinary_rules"] = rules
            UnifiedTradePlan.bounded_conditions(expanded)
        return data

    @model_validator(mode="after")
    def linked_contract(self):
        if not any(isinstance(rule, MarketLinkedRule) for rule in self.ordinary_rules):
            raise ValueError("linked format requires a linked ordinary rule")
        if self.monitoring is None:
            raise ValueError("market linkage requires reviewed daily monitoring")
        if self.reference_market != resolve_board_reference(self.symbol).binding:
            raise ValueError("reference index differs from the stock board")
        for rule in self.ordinary_rules:
            if isinstance(rule, MarketLinkedRule) and any(
                leaf.type.startswith("MINUTE_") for leaf in condition_leaves(rule.condition)
            ):
                raise ValueError("linked S0 requires daily conditions")
        return self


def legal_quantity_floor(ceiling: int, *, minimum: int, increment: int) -> int | None:
    """Intersect minimum+n*increment with positive 100-share simulation lots.

    Solve the congruence rather than iterating potentially huge quantities.
    The market rule must be verified by the caller; arithmetic grants no trade.
    """
    if type(ceiling) is not int or ceiling < 0:
        raise ValueError("ceiling must be a nonnegative integer")
    if any(type(value) is not int or value <= 0 for value in (minimum, increment)):
        raise ValueError("market minimum and increment must be positive integers")
    common = gcd(100, increment)
    if minimum % common:
        return None
    modulus = increment // common
    residue = (
        0 if modulus == 1 else ((minimum // common) * pow(100 // common, -1, modulus) % modulus)
    )
    first = 100 * residue
    step = 100 * modulus
    candidate = first + ((ceiling - first) // step) * step
    return candidate if candidate >= minimum else None
