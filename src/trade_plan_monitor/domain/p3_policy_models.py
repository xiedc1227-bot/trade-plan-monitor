"""Explicit monetary position limits, isolated from historical share contracts."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty, Text, WholeQty
from trade_plan_monitor.domain.p2_policy_models import FeeSchedule, P2Rule, P2TradePlan, PositiveFen


class CapitalPolicy(DailyValue):
    policy_version: Literal["capital-policy-v1"]
    currency: Literal["CNY"]
    scope: Literal["SYMBOL_CORE_AND_TACTICAL"]
    account_scope: Literal["SIMULATION"]
    cap_fen: PositiveFen


class OpenCostCap(CapitalPolicy):
    mode: Literal["OPEN_COST_CAP"]
    buy_cost_schedule: FeeSchedule


class MarketValueCap(CapitalPolicy):
    mode: Literal["MARKET_VALUE_CAP"]
    valuation: Literal["CURRENT_ADMITTED_QUOTE"]


MonetaryPolicy = Annotated[OpenCostCap | MarketValueCap, Field(discriminator="mode")]


class CapitalOnlyLimit(DailyValue):
    mode: Literal["CAPITAL_ONLY"]
    capital_policy: MonetaryPolicy


class CombinedCapitalLimit(DailyValue):
    mode: Literal["QUANTITY_AND_CAPITAL"]
    max_qty: PositiveWholeQty
    capital_policy: MonetaryPolicy


class P3Position(DailyValue):
    limit: Annotated[CapitalOnlyLimit | CombinedCapitalLimit, Field(discriminator="mode")]
    core_target_qty: WholeQty | None = None
    tactical_target_qty: WholeQty | None = None
    allocation_provenance: Literal["EXISTING_CONFIRMED", "PROPOSED"] | None = None
    allocation_evidence: Text | None = None

    @model_validator(mode="after")
    def bounded_allocation(self):
        if isinstance(self.limit, CombinedCapitalLimit) and sum(
                q or 0 for q in (self.core_target_qty, self.tactical_target_qty)
        ) > self.limit.max_qty:
            raise ValueError("source-defined allocation exceeds max_qty")
        return self


class P3TradePlan(P2TradePlan):
    schema_version: Literal[9] = 9
    execution_version: Literal["condition-plan-v5"] = "condition-plan-v5"
    position: P3Position

    @model_validator(mode="after")
    def capital_contract(self):
        if any(r.side == "BUY" and not isinstance(r, P2Rule) for r in self.ordinary_rules):
            raise ValueError("capital BUY requires the complete daily linked P2 rule")
        policy = self.position.limit.capital_policy
        if isinstance(policy, OpenCostCap):
            if self.symbol not in policy.buy_cost_schedule.symbols:
                raise ValueError("budget fee schedule must cover this security")
            for rule in self.ordinary_rules:
                economics = getattr(getattr(rule, "pretrade_policy", None), "economics", None)
                schedule = getattr(economics, "fee_schedule", None)
                if schedule is not None and schedule != policy.buy_cost_schedule:
                    raise ValueError("P2 and capital fee schedule content must match")
        return self
