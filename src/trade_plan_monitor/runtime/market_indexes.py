"""Runtime batching for shared board-index snapshots and plan-owned requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexFactRequest,
    MarketIndexHealth,
    MarketIndexSnapshot,
)
from trade_plan_monitor.market_index.requirements import (
    plan_index_fact_requests,
    union_fact_requests,
)
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator


DASHBOARD_INDEX_CODES = (
    MarketIndexCode.SSE_COMPOSITE,
    MarketIndexCode.SHENZHEN_COMPONENT,
    MarketIndexCode.CHINEXT,
    MarketIndexCode.STAR_50,
)


@dataclass(frozen=True, slots=True)
class RuntimeMarketIndexBatch:
    """One immutable set of shared snapshots prepared for a runtime cutoff."""

    decision_cutoff: datetime
    snapshots_by_index: Mapping[MarketIndexCode, MarketIndexSnapshot]

    def snapshot_for_plan(self, plan: TradePlan) -> MarketIndexSnapshot | None:
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        binding = plan.reference_market
        if plan.schema_version == 1 or binding is None:
            return None
        return self.snapshots_by_index.get(binding.index_code)


class RuntimeMarketIndexService:
    """Acquire fixed dashboard indexes and union any plan-owned requirements once."""

    def __init__(self, coordinator: MarketIndexSnapshotCoordinator) -> None:
        if not isinstance(coordinator, MarketIndexSnapshotCoordinator):
            raise TypeError("coordinator must be a MarketIndexSnapshotCoordinator")
        self._coordinator = coordinator
        self._latest_by_index: dict[MarketIndexCode, MarketIndexSnapshot] = {}

    def latest_snapshots(self) -> Mapping[MarketIndexCode, MarketIndexSnapshot]:
        """Return an immutable plan-neutral view of the latest shared data."""

        return MappingProxyType(dict(self._latest_by_index))

    async def prepare(
        self,
        *,
        plans: tuple[TradePlan, ...],
        decision_cutoff: datetime,
        observed_no_later_than: datetime,
    ) -> RuntimeMarketIndexBatch:
        if type(plans) is not tuple or any(not isinstance(plan, TradePlan) for plan in plans):
            raise TypeError("plans must be a tuple of TradePlan values")
        if len(plans) > 10:
            raise ValueError("runtime supports at most 10 active plans")
        grouped: dict[MarketIndexCode, list[tuple[MarketIndexFactRequest, ...]]] = {
            index_code: [()] for index_code in DASHBOARD_INDEX_CODES
        }
        for plan in plans:
            binding = plan.reference_market
            if plan.schema_version == 1 or binding is None:
                continue
            grouped.setdefault(binding.index_code, []).append(plan_index_fact_requests(plan))
        requirements = {
            index_code: union_fact_requests(*groups) for index_code, groups in grouped.items()
        }
        snapshots = await self._coordinator.get_snapshots(
            requirements=requirements,
            decision_cutoff=decision_cutoff,
            observed_no_later_than=observed_no_later_than,
        )
        for index_code, snapshot in snapshots.items():
            current = self._latest_by_index.get(index_code)
            snapshot_rank = (
                snapshot.decision_cutoff,
                snapshot.health is MarketIndexHealth.LIVE,
                len(snapshot.fact_requests),
                snapshot.revision,
                snapshot.snapshot_hash,
            )
            current_rank = (
                None
                if current is None
                else (
                    current.decision_cutoff,
                    current.health is MarketIndexHealth.LIVE,
                    len(current.fact_requests),
                    current.revision,
                    current.snapshot_hash,
                )
            )
            if current_rank is None or snapshot_rank > current_rank:
                self._latest_by_index[index_code] = snapshot
        return RuntimeMarketIndexBatch(
            decision_cutoff=decision_cutoff,
            snapshots_by_index=MappingProxyType(dict(snapshots)),
        )


__all__ = [
    "DASHBOARD_INDEX_CODES",
    "RuntimeMarketIndexBatch",
    "RuntimeMarketIndexService",
]
