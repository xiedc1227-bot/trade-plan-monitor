"""Opt-in exception permission; plan models never contain occurrence approval."""

from typing import Literal

from pydantic import Field

from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.market_linkage_models import (
    MarketLinkedRule,
    MarketLinkedTradePlan,
    MarketPolicy,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedRule

ExceptionRoute = Literal["WEAK_MINIMUM", "BROKEN_STRONG"]
ExceptionPermission = Literal["DISABLED", "PER_OCCURRENCE"]


class ExceptionRoutes(DailyValue):
    weak_minimum: ExceptionPermission
    broken_strong: ExceptionPermission


class MarketExceptionPolicy(MarketPolicy):
    policy_version: Literal["market-linkage-v2"]
    exception_policy: Literal["REVIEW_PER_OCCURRENCE"]
    exception_routes: ExceptionRoutes


class MarketExceptionRule(MarketLinkedRule):
    market_policy: MarketExceptionPolicy


class MarketExceptionTradePlan(MarketLinkedTradePlan):
    schema_version: Literal[7] = 7
    execution_version: Literal["condition-plan-v3"] = "condition-plan-v3"
    ordinary_rules: tuple[MarketExceptionRule | UnifiedRule, ...] = Field(max_length=2)
