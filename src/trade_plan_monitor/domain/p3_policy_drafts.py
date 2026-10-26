"""Reviewable monetary omissions retain strict scalar/collection bounds."""

from trade_plan_monitor.domain.p2_policy_drafts import DraftFeeSchedule, _nullable
from trade_plan_monitor.domain.p3_policy_models import (
    CapitalOnlyLimit,
    CombinedCapitalLimit,
    MarketValueCap,
    OpenCostCap,
    P3Position,
)

DraftOpenCostCap = _nullable(OpenCostCap, buy_cost_schedule=DraftFeeSchedule)
DraftMarketValueCap = _nullable(MarketValueCap)
DraftCapitalOnlyLimit = _nullable(CapitalOnlyLimit,
    capital_policy=DraftOpenCostCap | DraftMarketValueCap)
DraftCombinedCapitalLimit = _nullable(CombinedCapitalLimit,
    capital_policy=DraftOpenCostCap | DraftMarketValueCap)
DraftP3Position = _nullable(P3Position, limit=DraftCapitalOnlyLimit | DraftCombinedCapitalLimit)
