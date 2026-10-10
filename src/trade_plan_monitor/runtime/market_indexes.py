"""Runtime batching for shared board-index snapshots and plan-owned requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
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
from trade_plan_monitor.market_index.selection import snapshot_rank
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
_FINAL_DELAYS = (72, 132, 252)


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
    kind: str = "TRANSIENT"


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
        self._recovery_deferrals: dict[MarketIndexCode, datetime] = {}
        self._recovery_inflight: set[MarketIndexCode] = set()

    def next_recovery_due_at(self, *, now: datetime | None = None) -> datetime | None:
        """Earliest pending retry for the existing serial runtime scheduler."""
        if now is not None:
            self._expire_recoveries(now)
        return min(
            (
                max(state.due_at, self._recovery_deferrals.get(code, state.due_at))
                for code, state in self._recoveries.items()
                if state.attempts < 3 and code not in self._recovery_inflight
            ),
            default=None,
        )

    def defer_due_recoveries(
        self, *, now: datetime, until: datetime, index_codes: frozenset[MarketIndexCode]
    ) -> None:
        """Delay only targets unable to start a physical request; retain retry budget."""
        self._expire_recoveries(now)
        if until <= now:
            raise ValueError("recovery deferral must be in the future")
        for code in index_codes:
            state = self._recoveries.get(code)
            if state is not None and state.due_at <= now:
                self._recovery_deferrals[code] = max(
                    until, self._recovery_deferrals.get(code, until)
                )

    def _expire_recoveries(self, now: datetime) -> None:
        self._recoveries = {
            code: state
            for code, state in self._recoveries.items()
            if (now < state.decision_cutoff + _RECOVERY_WINDOW
                if state.decision_cutoff.time() in (time(11, 30), time(15))
                else now <= state.first_failed_at + _RECOVERY_WINDOW)
        }
        self._recovery_deferrals = {
            code: due for code, due in self._recovery_deferrals.items()
            if code in self._recoveries and due > now
        }

    def recovery_records(
        self,
        *, include_exhausted: bool = False,
    ) -> tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...]:
        return tuple(
            (code, state.decision_cutoff, state.first_failed_at, state.attempts, state.due_at)
            for code, state in sorted(self._recoveries.items(), key=lambda item: item[0].value)
            if include_exhausted or state.attempts < 3
        )

    def recovery_kinds(self) -> dict[MarketIndexCode, str]:
        return {code: state.kind for code, state in self._recoveries.items()}

    def restore_recoveries(
        self,
        *,
        snapshots: Mapping[MarketIndexCode, MarketIndexSnapshot],
        records: tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...],
        now: datetime,
        kinds: Mapping[MarketIndexCode, str] | None = None,
    ) -> None:
        """Resume only unexpired retries whose persisted failed head is still current."""
        self._latest_by_index.update(snapshots)
        for code, cutoff, first_failed_at, attempts, due_at in records:
            snapshot = snapshots.get(code)
            kind = (kinds or {}).get(code, "TRANSIENT")
            final = kind == "FINAL_BUCKET"
            final_budget = cutoff.time() in (time(11, 30), time(15))
            if (
                snapshot is not None
                and snapshot.decision_cutoff == cutoff
                and (snapshot.health is not MarketIndexHealth.LIVE if final or attempts == 3 else
                    snapshot.health is MarketIndexHealth.BLOCKED
                    and MarketIndexIssueCode.PROVIDER_UNAVAILABLE in snapshot.issues)
                and (now < cutoff + _RECOVERY_WINDOW if final_budget else
                    now <= first_failed_at + _RECOVERY_WINDOW)
                and now >= first_failed_at
                and due_at <= first_failed_at + _RECOVERY_WINDOW
                and (0 <= attempts <= 3 if final_budget else 0 <= attempts < 3)
            ):
                self._recoveries[code] = _Recovery(cutoff, first_failed_at, attempts, due_at, kind)

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
                    self._recovery_deferrals.pop(code, None)
                continue
            current = self._recoveries.get(code)
            if current is not None and current.decision_cutoff > snapshot.decision_cutoff:
                continue
            final_target = snapshot.decision_cutoff.time() in (time(11, 30), time(15))
            lag = bool(snapshot.issues) and set(snapshot.issues).issubset(_PUBLICATION_LAG_ISSUES)
            final = final_target and (lag or current is not None and current.kind == "FINAL_BUCKET")
            if final:
                expiry = snapshot.decision_cutoff + _RECOVERY_WINDOW
                if snapshot.health is MarketIndexHealth.LIVE or snapshot.observed_at >= expiry:
                    self._recoveries.pop(code, None)
                    self._recovery_deferrals.pop(code, None)
                    continue
                same = current is not None and current.decision_cutoff == snapshot.decision_cutoff
                attempts = (current.attempts if same else 0) + int(retry)
                if same and not retry:
                    continue
                if retry and not self._coordinator.request_started_for(
                    code, snapshot.decision_cutoff
                ):
                    attempts -= 1
                permitted = lag or self._coordinator.failure_for(code, snapshot.decision_cutoff)
                due = expiry if attempts >= 3 or not permitted else max(
                    snapshot.decision_cutoff + timedelta(seconds=_FINAL_DELAYS[attempts]),
                    snapshot.observed_at + timedelta(seconds=60)
                    if retry else snapshot.decision_cutoff,
                )
                self._recoveries[code] = _Recovery(snapshot.decision_cutoff,
                    snapshot.decision_cutoff, attempts, min(due, expiry), "FINAL_BUCKET")
                self._recovery_deferrals.pop(code, None)
                continue
            if snapshot.health is MarketIndexHealth.LIVE or not self._coordinator.failure_for(
                code, snapshot.decision_cutoff
            ):
                if (
                    final_target and current is not None
                    and snapshot.health is not MarketIndexHealth.LIVE
                ):
                    attempts = current.attempts + int(
                        retry and self._coordinator.request_started_for(
                            code, snapshot.decision_cutoff
                        )
                    )
                    self._recoveries[code] = _Recovery(snapshot.decision_cutoff,
                        current.first_failed_at, min(3, attempts),
                        snapshot.decision_cutoff + _RECOVERY_WINDOW)
                else:
                    self._recoveries.pop(code, None)
                self._recovery_deferrals.pop(code, None)
                continue
            if current is not None and current.decision_cutoff == snapshot.decision_cutoff:
                if not retry:
                    continue
                attempts = current.attempts + int(
                    self._coordinator.request_started_for(code, snapshot.decision_cutoff)
                )
                first_failed_at = current.first_failed_at
            else:
                attempts = 0
                first_failed_at = snapshot.observed_at
            if attempts >= len(_RECOVERY_DELAYS):
                if (
                    final_target
                    and snapshot.observed_at < snapshot.decision_cutoff + _RECOVERY_WINDOW
                ):
                    self._recoveries[code] = _Recovery(snapshot.decision_cutoff, first_failed_at,
                        3, snapshot.decision_cutoff + _RECOVERY_WINDOW)
                else:
                    self._recoveries.pop(code, None)
                self._recovery_deferrals.pop(code, None)
                continue
            due_at = snapshot.observed_at + _RECOVERY_DELAYS[attempts]
            if due_at > first_failed_at + _RECOVERY_WINDOW:
                self._recoveries.pop(code, None)
                self._recovery_deferrals.pop(code, None)
                continue
            self._recoveries[code] = _Recovery(
                snapshot.decision_cutoff, first_failed_at, attempts, due_at
            )
            self._recovery_deferrals.pop(code, None)

    async def retry_recoverable(
        self, *, observed_no_later_than: datetime
    ) -> RuntimeMarketIndexBatch | None:
        """Reacquire only due transient failures without rerunning plan evaluations."""
        self._expire_recoveries(observed_no_later_than)
        due = {
            code: state
            for code, state in self._recoveries.items()
            if max(
                state.due_at,
                self._recovery_deferrals.get(code, state.due_at),
            ) <= observed_no_later_than
            and state.attempts < 3 and code not in self._recovery_inflight
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
        self._recovery_inflight.update(targets)
        try:
            snapshots = await self._coordinator.get_snapshots(
                requirements={code: snapshot.fact_requests for code, snapshot in targets.items()},
                decision_cutoff=cutoff,
                observed_no_later_than=observed_no_later_than,
                minimum_bar_counts={
                    code: (turnover_minute_count if code in MARKET_TURNOVER_INDEX_CODES else 1, 2)
                    for code in targets
                },
            )
        finally:
            self._recovery_inflight.difference_update(targets)
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

        if decision_cutoff.time() in (time(11, 30), time(15)):
            return await self.retry_recoverable(observed_no_later_than=observed_no_later_than)
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
            if current is None or snapshot_rank(snapshot) > snapshot_rank(current):
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
