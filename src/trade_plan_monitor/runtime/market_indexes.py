"""Runtime batching for shared board-index snapshots and plan-owned requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexFactRequest,
    MarketIndexHealth,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
)
from trade_plan_monitor.market_index.requirements import (
    plan_index_fact_requests,
    union_fact_requests,
)
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.market_index.turnover import (
    MARKET_TURNOVER_BUCKET_COUNT,
    MARKET_TURNOVER_INDEX_CODES,
    completed_market_turnover_bucket_count,
)

DASHBOARD_INDEX_CODES = (
    MarketIndexCode.SSE_COMPOSITE,
    MarketIndexCode.SHENZHEN_COMPONENT,
    MarketIndexCode.CHINEXT,
    MarketIndexCode.STAR_50,
)
ALWAYS_ON_INDEX_CODES = tuple(
    dict.fromkeys(DASHBOARD_INDEX_CODES + MARKET_TURNOVER_INDEX_CODES)
)
_PUBLICATION_LAG_ISSUES = frozenset(
    {
        MarketIndexIssueCode.MISSING_FIVE_MINUTE_BAR,
        MarketIndexIssueCode.STALE_DATA,
    }
)
_RECOVERY_DELAYS = (timedelta(seconds=30), timedelta(seconds=60), timedelta(seconds=120))
_RECOVERY_WINDOW = timedelta(minutes=5)


def _turnover_minute_bar_count(cutoff: datetime) -> int:
    return MARKET_TURNOVER_BUCKET_COUNT + max(
        1,
        completed_market_turnover_bucket_count(cutoff),
    )


@dataclass(frozen=True, slots=True)
class _Recovery:
    decision_cutoff: datetime
    first_failed_at: datetime
    attempts: int
    due_at: datetime


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
        self._publication_lag_retry_cutoffs: set[datetime] = set()
        self._recoveries: dict[MarketIndexCode, _Recovery] = {}

    def next_recovery_due_at(self, *, now: datetime | None = None) -> datetime | None:
        """Earliest pending retry for the existing serial runtime scheduler."""
        if now is not None:
            self._expire_recoveries(now)
        return min((state.due_at for state in self._recoveries.values()), default=None)

    def _expire_recoveries(self, now: datetime) -> None:
        self._recoveries = {
            code: state
            for code, state in self._recoveries.items()
            if now <= state.first_failed_at + _RECOVERY_WINDOW
        }

    def recovery_records(
        self,
    ) -> tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...]:
        return tuple(
            (code, state.decision_cutoff, state.first_failed_at, state.attempts, state.due_at)
            for code, state in sorted(self._recoveries.items(), key=lambda item: item[0].value)
        )

    def restore_recoveries(
        self,
        *,
        snapshots: Mapping[MarketIndexCode, MarketIndexSnapshot],
        records: tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...],
        now: datetime,
    ) -> None:
        """Resume only unexpired retries whose persisted failed head is still current."""
        self._latest_by_index.update(snapshots)
        for code, cutoff, first_failed_at, attempts, due_at in records:
            snapshot = snapshots.get(code)
            if (
                snapshot is not None
                and snapshot.decision_cutoff == cutoff
                and snapshot.health is MarketIndexHealth.BLOCKED
                and MarketIndexIssueCode.PROVIDER_UNAVAILABLE in snapshot.issues
                and now <= first_failed_at + _RECOVERY_WINDOW
                and due_at <= first_failed_at + _RECOVERY_WINDOW
                and 0 <= attempts < len(_RECOVERY_DELAYS)
            ):
                self._recoveries[code] = _Recovery(cutoff, first_failed_at, attempts, due_at)

    def _track_recoveries(
        self,
        snapshots: Mapping[MarketIndexCode, MarketIndexSnapshot],
        *,
        retry: bool = False,
    ) -> None:
        for code, snapshot in snapshots.items():
            latest = self._latest_by_index.get(code)
            if latest is not snapshot:
                if latest is not None and latest.health is MarketIndexHealth.LIVE:
                    self._recoveries.pop(code, None)
                continue
            current = self._recoveries.get(code)
            if current is not None and current.decision_cutoff > snapshot.decision_cutoff:
                continue
            if snapshot.health is MarketIndexHealth.LIVE or not self._coordinator.failure_for(
                code, snapshot.decision_cutoff
            ):
                self._recoveries.pop(code, None)
                continue
            if current is not None and current.decision_cutoff == snapshot.decision_cutoff:
                if not retry:
                    continue
                attempts = current.attempts + 1
                first_failed_at = current.first_failed_at
            else:
                attempts = 0
                first_failed_at = snapshot.observed_at
            if attempts >= len(_RECOVERY_DELAYS):
                self._recoveries.pop(code, None)
                continue
            due_at = snapshot.observed_at + _RECOVERY_DELAYS[attempts]
            if due_at > first_failed_at + _RECOVERY_WINDOW:
                self._recoveries.pop(code, None)
                continue
            self._recoveries[code] = _Recovery(
                snapshot.decision_cutoff, first_failed_at, attempts, due_at
            )

    async def retry_recoverable(
        self, *, observed_no_later_than: datetime
    ) -> RuntimeMarketIndexBatch | None:
        """Reacquire only due transient failures without rerunning plan evaluations."""
        self._expire_recoveries(observed_no_later_than)
        due = {
            code: state
            for code, state in self._recoveries.items()
            if state.due_at <= observed_no_later_than
            and self._latest_by_index.get(code) is not None
            and self._latest_by_index[code].decision_cutoff == state.decision_cutoff
        }
        if not due:
            return None
        # A new market cutoff supersedes an older recovery. Grouping by cutoff
        # preserves the coordinator's exact snapshot identity.
        cutoff = min(state.decision_cutoff for state in due.values())
        targets = {
            code: self._latest_by_index[code]
            for code, state in due.items()
            if state.decision_cutoff == cutoff
        }
        turnover_minute_count = _turnover_minute_bar_count(cutoff)
        snapshots = await self._coordinator.get_snapshots(
            requirements={code: snapshot.fact_requests for code, snapshot in targets.items()},
            decision_cutoff=cutoff,
            observed_no_later_than=observed_no_later_than,
            minimum_bar_counts={
                code: (turnover_minute_count if code in MARKET_TURNOVER_INDEX_CODES else 1, 2)
                for code in targets
            },
        )
        accepted = {
            code: snapshot
            for code, snapshot in snapshots.items()
            if self._latest_by_index.get(code) is targets[code]
        }
        self._latest_by_index.update(accepted)
        self._track_recoveries(accepted, retry=True)
        return RuntimeMarketIndexBatch(cutoff, MappingProxyType(accepted)) if accepted else None

    def latest_snapshots(self) -> Mapping[MarketIndexCode, MarketIndexSnapshot]:
        """Return an immutable plan-neutral view of the latest shared data."""

        return MappingProxyType(dict(self._latest_by_index))

    def claim_publication_lag_retry(self, decision_cutoff: datetime) -> bool:
        """Claim one bounded retry when the latest bucket appears not yet published."""

        if not isinstance(decision_cutoff, datetime) or decision_cutoff.tzinfo is None:
            raise TypeError("decision_cutoff must be a timezone-aware datetime")
        self._publication_lag_retry_cutoffs = {
            cutoff
            for cutoff in self._publication_lag_retry_cutoffs
            if cutoff.date() == decision_cutoff.date()
        }
        if decision_cutoff in self._publication_lag_retry_cutoffs:
            return False
        if not self._publication_lag_targets(decision_cutoff):
            return False
        self._publication_lag_retry_cutoffs.add(decision_cutoff)
        return True

    def _publication_lag_targets(
        self, decision_cutoff: datetime
    ) -> dict[MarketIndexCode, MarketIndexSnapshot]:
        return {
            index_code: snapshot
            for index_code, snapshot in self._latest_by_index.items()
            if snapshot.decision_cutoff == decision_cutoff
            and snapshot.health is not MarketIndexHealth.LIVE
            and bool(snapshot.issues)
            and set(snapshot.issues).issubset(_PUBLICATION_LAG_ISSUES)
        }

    async def retry_publication_lag(
        self,
        *,
        decision_cutoff: datetime,
        observed_no_later_than: datetime,
    ) -> RuntimeMarketIndexBatch | None:
        """Reacquire only lagging same-cutoff indexes once, preserving their fact needs.

        The returned batch contains only retried indexes so persistence leaves every
        unchanged healthy or independently blocked head untouched.
        """

        if not self.claim_publication_lag_retry(decision_cutoff):
            return None
        targets = self._publication_lag_targets(decision_cutoff)
        turnover_minute_count = _turnover_minute_bar_count(decision_cutoff)
        snapshots = await self._coordinator.get_snapshots(
            requirements={
                index_code: snapshot.fact_requests for index_code, snapshot in targets.items()
            },
            decision_cutoff=decision_cutoff,
            observed_no_later_than=observed_no_later_than,
            minimum_bar_counts={
                index_code: (
                    turnover_minute_count if index_code in MARKET_TURNOVER_INDEX_CODES else 1, 2
                )
                for index_code in targets
            },
        )
        accepted = {
            index_code: snapshot
            for index_code, snapshot in snapshots.items()
            if self._latest_by_index.get(index_code) is targets[index_code]
        }
        if not accepted:
            return None
        self._latest_by_index.update(accepted)
        self._track_recoveries(accepted)
        return RuntimeMarketIndexBatch(
            decision_cutoff=decision_cutoff,
            snapshots_by_index=MappingProxyType(accepted),
        )

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
            index_code: [()] for index_code in ALWAYS_ON_INDEX_CODES
        }
        for plan in plans:
            binding = plan.reference_market
            if plan.schema_version == 1 or binding is None:
                continue
            grouped.setdefault(binding.index_code, []).append(plan_index_fact_requests(plan))
        requirements = {
            index_code: union_fact_requests(*groups) for index_code, groups in grouped.items()
        }
        turnover_minute_count = _turnover_minute_bar_count(decision_cutoff)
        snapshots = await self._coordinator.get_snapshots(
            requirements=requirements,
            decision_cutoff=decision_cutoff,
            observed_no_later_than=observed_no_later_than,
            minimum_bar_counts={
                index_code: (
                    turnover_minute_count if index_code in MARKET_TURNOVER_INDEX_CODES else 1, 2
                )
                for index_code in requirements
            },
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
        self._track_recoveries(snapshots)
        return RuntimeMarketIndexBatch(
            decision_cutoff=decision_cutoff,
            snapshots_by_index=MappingProxyType(dict(snapshots)),
        )


__all__ = [
    "ALWAYS_ON_INDEX_CODES",
    "DASHBOARD_INDEX_CODES",
    "RuntimeMarketIndexBatch",
    "RuntimeMarketIndexService",
]
