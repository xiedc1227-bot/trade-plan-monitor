"""Shared cutoff coordination for immutable plan-neutral index snapshots."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from types import MappingProxyType

from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
    market_index_bar_set_hash,
    market_index_request_set_hash,
    market_index_snapshot_hash,
)
from trade_plan_monitor.market_index.formulas import calculate_requested_facts
from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    MarketIndexCode,
    identity_for_index_code,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactRequest,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
)
from trade_plan_monitor.market_index.provider import (
    LiveMarketIndexProvider,
    MarketIndexProviderBatch,
)
from trade_plan_monitor.market_index.requirements import (
    required_bar_counts,
    union_fact_requests,
)
from trade_plan_monitor.runtime.clock import Clock, _canonical_shanghai

_PrefetchKey = tuple[str, MarketIndexCode, datetime, str, int, int, datetime]
_SnapshotKey = tuple[str, MarketIndexCode, datetime, str, int, int, int]
_MAX_SNAPSHOT_CACHE_ENTRIES = 512
_MORNING_CLOSE = time(11, 30)
_AFTERNOON_OPEN = time(13, 5)
_SESSION_CLOSE = time(15, 0)
_SESSION_OPEN = time(9, 35)
# One immutable index snapshot may require historical minutes, realtime minutes
# and official daily data. Each controller call permits at most three attempts,
# each with 15 seconds admission plus 15 seconds physical wait, followed by
# one bounded local validation. This is per snapshot, never a batch allowance.
_INDEX_SNAPSHOT_PROGRESS_BUDGET_SECONDS = 3 * 3 * (15 + 15) + 30


def _ceil_to_whole_second(value: datetime) -> datetime:
    canonical = _canonical_shanghai(value)
    if canonical.microsecond:
        canonical += timedelta(seconds=1)
    return canonical.replace(microsecond=0)


def _validate_shanghai_timestamp(value: datetime, *, field_name: str) -> None:
    if value.utcoffset() != timedelta(hours=8):
        raise ValueError(f"{field_name} must use the Asia/Shanghai offset")


def _snapshot_payload(
    *,
    index_code: MarketIndexCode,
    decision_cutoff: datetime,
    requests: tuple[MarketIndexFactRequest, ...],
    batch: MarketIndexProviderBatch | None,
    health: MarketIndexHealth,
    issues: tuple[MarketIndexIssueCode, ...],
    observed_at: datetime,
) -> dict[str, object]:
    board, display_name = identity_for_index_code(index_code)
    bars = () if batch is None else batch.five_minute_bars + batch.official_daily_bars
    request_set_hash = market_index_request_set_hash(requests)
    bar_set_hash = market_index_bar_set_hash(bars)
    revision = 1 if batch is None else batch.content_revision
    five_minute_bars = () if batch is None else batch.five_minute_bars
    official_daily_bars = () if batch is None else batch.official_daily_bars
    latest = five_minute_bars[-1] if five_minute_bars else None
    prior_close = official_daily_bars[-1].close_points if official_daily_bars else None
    facts = (
        ()
        if batch is None or health is not MarketIndexHealth.LIVE
        else calculate_requested_facts(
            index_code=index_code,
            five_minute_bars=five_minute_bars,
            official_daily_bars=official_daily_bars,
            requests=requests,
            input_cutoff=decision_cutoff,
        )
    )
    return {
        "index_code": index_code,
        "display_name": display_name,
        "board": board,
        "decision_cutoff": decision_cutoff,
        "latest_completed_five_minute": latest,
        "five_minute_bars": five_minute_bars,
        "official_daily_bars": official_daily_bars,
        "prior_official_close_points": prior_close,
        "fact_requests": requests,
        "indicator_facts": facts,
        "health": health,
        "issues": issues,
        "completed_bucket_at": None if latest is None else latest.bar_at,
        "observed_at": observed_at,
        "mapping_version": MAPPING_VERSION,
        "revision": revision,
        "bar_set_hash": bar_set_hash,
        "request_set_hash": request_set_hash,
        "formula_definition_hash": FORMULA_DEFINITION_HASH,
    }


def _finish_snapshot(payload: dict[str, object]) -> MarketIndexSnapshot:
    return MarketIndexSnapshot(
        **payload,
        snapshot_hash=market_index_snapshot_hash(payload),
    )


def _blocked_snapshot(
    *,
    index_code: MarketIndexCode,
    decision_cutoff: datetime,
    requests: tuple[MarketIndexFactRequest, ...],
    issue: MarketIndexIssueCode,
    observed_at: datetime,
    batch: MarketIndexProviderBatch | None = None,
    health: MarketIndexHealth = MarketIndexHealth.BLOCKED,
) -> MarketIndexSnapshot:
    if health is MarketIndexHealth.LIVE:
        raise ValueError("an unusable snapshot cannot have LIVE health")
    return _finish_snapshot(
        _snapshot_payload(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=requests,
            batch=batch,
            health=health,
            issues=(issue,),
            observed_at=observed_at,
        )
    )


def _has_five_minute_gap(bars: tuple[MarketIndexBar, ...]) -> bool:
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.bar_at.date() == current.bar_at.date():
            previous_time = previous.bar_at.timetz().replace(tzinfo=None)
            current_time = current.bar_at.timetz().replace(tzinfo=None)
            if previous_time == _MORNING_CLOSE:
                if current_time != _AFTERNOON_OPEN:
                    return True
            elif current.bar_at - previous.bar_at != timedelta(minutes=5):
                return True
        else:
            previous_time = previous.bar_at.timetz().replace(tzinfo=None)
            current_time = current.bar_at.timetz().replace(tzinfo=None)
            if previous_time != _SESSION_CLOSE or current_time != _SESSION_OPEN:
                return True
    return False


def build_market_index_snapshot(
    *,
    index_code: MarketIndexCode,
    decision_cutoff: datetime,
    requests: tuple[MarketIndexFactRequest, ...],
    five_minute_bars: tuple[MarketIndexBar, ...],
    official_daily_bars: tuple[MarketIndexBar, ...],
    content_revision: int,
    observed_at: datetime,
    observed_no_later_than: datetime,
    minimum_five_minute_bar_count: int = 1,
    minimum_official_daily_bar_count: int = 1,
) -> MarketIndexSnapshot:
    """Build the shared validated snapshot used by live and offline replay paths."""

    _validate_shanghai_timestamp(decision_cutoff, field_name="decision_cutoff")
    _validate_shanghai_timestamp(observed_at, field_name="observed_at")
    _validate_shanghai_timestamp(
        observed_no_later_than,
        field_name="observed_no_later_than",
    )
    normalized_requests = union_fact_requests(requests)
    for name, value in (
        ("minimum_five_minute_bar_count", minimum_five_minute_bar_count),
        ("minimum_official_daily_bar_count", minimum_official_daily_bar_count),
    ):
        if type(value) is not int or not 1 <= value <= 8_000:
            raise ValueError(f"{name} must be between 1 and 8000")
    if (
        not isinstance(index_code, MarketIndexCode)
        or type(five_minute_bars) is not tuple
        or type(official_daily_bars) is not tuple
        or any(type(bar) is not MarketIndexBar for bar in five_minute_bars + official_daily_bars)
        or type(content_revision) is not int
        or not 1 <= content_revision <= 2_147_483_647
    ):
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,
            observed_at=observed_no_later_than,
        )
    batch = MarketIndexProviderBatch.model_construct(
        index_code=index_code,
        five_minute_bars=tuple(sorted(five_minute_bars, key=lambda bar: bar.bar_at)),
        official_daily_bars=tuple(sorted(official_daily_bars, key=lambda bar: bar.bar_at)),
        content_revision=content_revision,
        observed_at=observed_at,
    )
    bars = batch.five_minute_bars + batch.official_daily_bars
    if (
        any(bar.index_code is not index_code for bar in bars)
        or any(
            bar.interval is not MarketIndexInterval.FIVE_MINUTE for bar in batch.five_minute_bars
        )
        or any(
            bar.interval is not MarketIndexInterval.OFFICIAL_DAILY
            for bar in batch.official_daily_bars
        )
    ):
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,
            observed_at=observed_no_later_than,
        )
    identities = tuple((bar.interval, bar.bar_at) for bar in bars)
    if len(set(identities)) != len(identities):
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.DUPLICATE_IDENTITY,
            observed_at=batch.observed_at,
            batch=batch,
        )
    if batch.observed_at > observed_no_later_than or any(
        bar.observed_at > observed_no_later_than or bar.bar_at > decision_cutoff for bar in bars
    ):
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.FUTURE_DATA,
            observed_at=observed_no_later_than,
        )
    requested_five_minute_count, requested_official_daily_count = required_bar_counts(
        normalized_requests
    )
    five_minute_count = max(
        requested_five_minute_count,
        minimum_five_minute_bar_count,
    )
    official_daily_count = max(
        requested_official_daily_count,
        minimum_official_daily_bar_count,
    )
    if len(batch.five_minute_bars) < five_minute_count:
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.MISSING_FIVE_MINUTE_BAR,
            observed_at=batch.observed_at,
            batch=batch,
        )
    if len(batch.official_daily_bars) < official_daily_count:
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.INSUFFICIENT_HISTORY,
            observed_at=batch.observed_at,
            batch=batch,
        )
    required_five_minute_bars = batch.five_minute_bars[-five_minute_count:]
    batch = MarketIndexProviderBatch.model_construct(
        index_code=index_code,
        five_minute_bars=batch.five_minute_bars,
        official_daily_bars=batch.official_daily_bars[-official_daily_count:],
        content_revision=content_revision,
        observed_at=observed_at,
    )
    if batch.five_minute_bars[-1].bar_at != decision_cutoff:
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.STALE_DATA,
            observed_at=batch.observed_at,
            batch=batch,
            health=MarketIndexHealth.STALE,
        )
    if _has_five_minute_gap(required_five_minute_bars):
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=MarketIndexIssueCode.GAPPED_SERIES,
            observed_at=batch.observed_at,
            batch=batch,
            health=MarketIndexHealth.GAPPED,
        )
    try:
        return _finish_snapshot(
            _snapshot_payload(
                index_code=index_code,
                decision_cutoff=decision_cutoff,
                requests=normalized_requests,
                batch=batch,
                health=MarketIndexHealth.LIVE,
                issues=(),
                observed_at=batch.observed_at,
            )
        )
    except ValueError as error:
        issue = (
            MarketIndexIssueCode.DUPLICATE_IDENTITY
            if str(error) == MarketIndexIssueCode.DUPLICATE_IDENTITY
            else MarketIndexIssueCode.FORMULA_MISMATCH
        )
        return _blocked_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            issue=issue,
            observed_at=batch.observed_at,
            batch=batch,
        )


class MarketIndexSnapshotCoordinator:
    """Acquire and publish at most one snapshot for each exact prefetch key."""

    def __init__(
        self,
        provider: LiveMarketIndexProvider,
        *,
        clock: Clock | None = None,
        progress_owner=None,
    ) -> None:
        if clock is not None and not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        self._provider = provider
        self._clock = clock
        self._progress_owner = progress_owner
        self._lock = asyncio.Lock()
        self._inflight: dict[_PrefetchKey, asyncio.Task[MarketIndexSnapshot]] = {}
        self._snapshots: OrderedDict[_SnapshotKey, MarketIndexSnapshot] = OrderedDict()
        self._failures: dict[tuple[MarketIndexCode, datetime], bool] = {}
        self._request_started: dict[tuple[MarketIndexCode, datetime], bool] = {}

    def request_started_for(self, index_code: MarketIndexCode, decision_cutoff: datetime) -> bool:
        return self._request_started.get((index_code, decision_cutoff), True)

    def failure_for(
        self, index_code: MarketIndexCode, decision_cutoff: datetime
    ) -> bool:
        """Whether the latest failure was explicitly classified as transient."""
        return self._failures.get((index_code, decision_cutoff), False)

    async def get_snapshot(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        requests: tuple[MarketIndexFactRequest, ...],
        observed_no_later_than: datetime,
        minimum_five_minute_bar_count: int = 1,
        minimum_official_daily_bar_count: int = 1,
    ) -> MarketIndexSnapshot:
        _validate_shanghai_timestamp(decision_cutoff, field_name="decision_cutoff")
        _validate_shanghai_timestamp(
            observed_no_later_than,
            field_name="observed_no_later_than",
        )
        normalized_requests = union_fact_requests(requests)
        for name, value in (
            ("minimum_five_minute_bar_count", minimum_five_minute_bar_count),
            ("minimum_official_daily_bar_count", minimum_official_daily_bar_count),
        ):
            if type(value) is not int or not 1 <= value <= 8_000:
                raise ValueError(f"{name} must be between 1 and 8000")
        request_hash = market_index_request_set_hash(normalized_requests)
        prefetch_key = (
            MAPPING_VERSION,
            index_code,
            decision_cutoff,
            request_hash,
            minimum_five_minute_bar_count,
            minimum_official_daily_bar_count,
            observed_no_later_than,
        )
        async with self._lock:
            task = self._inflight.get(prefetch_key)
            if task is None:
                task = asyncio.create_task(
                    self._acquire(
                        index_code=index_code,
                        decision_cutoff=decision_cutoff,
                        requests=normalized_requests,
                        observed_no_later_than=observed_no_later_than,
                        minimum_five_minute_bar_count=minimum_five_minute_bar_count,
                        minimum_official_daily_bar_count=minimum_official_daily_bar_count,
                    )
                )
                self._inflight[prefetch_key] = task

                def discard_finished(completed: asyncio.Task[MarketIndexSnapshot]) -> None:
                    if self._inflight.get(prefetch_key) is completed:
                        self._inflight.pop(prefetch_key, None)

                task.add_done_callback(discard_finished)
        snapshot = await asyncio.shield(task)
        if snapshot.health is not MarketIndexHealth.LIVE:
            return snapshot
        snapshot_key = (
            MAPPING_VERSION,
            index_code,
            decision_cutoff,
            request_hash,
            snapshot.revision,
            minimum_five_minute_bar_count,
            minimum_official_daily_bar_count,
        )
        async with self._lock:
            cached = self._snapshots.get(snapshot_key)
            if cached is not None:
                self._snapshots.move_to_end(snapshot_key)
                return cached
            self._snapshots[snapshot_key] = snapshot
            if len(self._snapshots) > _MAX_SNAPSHOT_CACHE_ENTRIES:
                self._snapshots.popitem(last=False)
        return snapshot

    async def get_snapshots(
        self,
        *,
        requirements: Mapping[MarketIndexCode, tuple[MarketIndexFactRequest, ...]],
        decision_cutoff: datetime,
        observed_no_later_than: datetime,
        minimum_bar_counts: Mapping[MarketIndexCode, tuple[int, int]] | None = None,
    ) -> Mapping[MarketIndexCode, MarketIndexSnapshot]:
        codes = tuple(sorted(requirements, key=lambda item: item.value))
        selected_minimums = {} if minimum_bar_counts is None else dict(minimum_bar_counts)
        if not set(selected_minimums).issubset(requirements):
            raise ValueError("minimum bar counts must name requested indexes")
        requests = tuple(
                self.get_snapshot(
                    index_code=index_code,
                    decision_cutoff=decision_cutoff,
                    requests=requirements[index_code],
                    observed_no_later_than=observed_no_later_than,
                    minimum_five_minute_bar_count=selected_minimums.get(index_code, (1, 1))[0],
                    minimum_official_daily_bar_count=selected_minimums.get(index_code, (1, 1))[1],
                )
                for index_code in codes
        )
        if self._progress_owner is None or not requests:
            snapshots = await asyncio.gather(*requests)
        else:
            snapshots = await self._collect_owned_snapshots(codes, requests)
        return MappingProxyType(dict(zip(codes, snapshots, strict=True)))

    async def _collect_owned_snapshots(self, codes, requests):
        """Only the awaiting owner records validated completions, retaining original due times."""
        owner = self._progress_owner
        # Freeze each snapshot's actual maximum three-stage controller budget.
        # A peer completion cannot refresh another snapshot's original due time.
        try:
            due = owner.progress_monotonic_now() + _INDEX_SNAPSHOT_PROGRESS_BUDGET_SECONDS
            token = owner.begin_progress_step_at(deadline=due)
        except BaseException:
            # Rejected ownership cannot begin an otherwise unowned provider task.
            for request in requests:
                request.close()
            raise
        pending = {asyncio.create_task(request): (code, due)
                   for code, request in zip(codes, requests, strict=True)}
        completed = {}
        try:
            while pending:
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(done, key=lambda task: pending[task][0].value):
                    code, _deadline = pending[task]
                    snapshot = task.result()
                    # get_snapshot already validated and installed the immutable snapshot.
                    completed[code] = snapshot
                    del pending[task]
                    accepted = owner.complete_progress_step(
                        token, next_wake_at=self._clock.now() + timedelta(seconds=30),
                    )
                    if accepted and pending:
                        token = owner.begin_progress_step_at(
                            deadline=min(item[1] for item in pending.values()),
                        )
            return tuple(completed[code] for code in codes)
        finally:
            # Cancelling wrappers preserves get_snapshot's physically shielded
            # provider work. Its lifecycle controller owns that physical drain.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _acquire(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        requests: tuple[MarketIndexFactRequest, ...],
        observed_no_later_than: datetime,
        minimum_five_minute_bar_count: int,
        minimum_official_daily_bar_count: int,
    ) -> MarketIndexSnapshot:
        requested_five_minute_count, requested_official_daily_count = required_bar_counts(requests)
        five_minute_count = max(
            requested_five_minute_count,
            minimum_five_minute_bar_count,
        )
        official_daily_count = max(
            requested_official_daily_count,
            minimum_official_daily_bar_count,
        )
        try:
            batch = await self._provider.acquire_index_data(
                index_code=index_code,
                decision_cutoff=decision_cutoff,
                five_minute_bar_count=five_minute_count,
                official_daily_bar_count=official_daily_count,
            )
        except Exception as error:
            self._request_started[(index_code, decision_cutoff)] = getattr(
                error, "request_started", True
            )
            if len(self._request_started) > 512:
                self._request_started.pop(next(iter(self._request_started)))
            self._failures[(index_code, decision_cutoff)] = (
                getattr(error, "retryable", False) is True
            )
            if len(self._failures) > 512:
                self._failures.pop(next(iter(self._failures)))
            observed_no_later_than = await self._post_fetch_observed_at(observed_no_later_than)
            return _blocked_snapshot(
                index_code=index_code,
                decision_cutoff=decision_cutoff,
                requests=requests,
                issue=MarketIndexIssueCode.PROVIDER_UNAVAILABLE,
                observed_at=observed_no_later_than,
            )
        observed_no_later_than = await self._post_fetch_observed_at(observed_no_later_than)
        self._failures.pop((index_code, decision_cutoff), None)
        self._request_started.pop((index_code, decision_cutoff), None)
        if type(batch) is not MarketIndexProviderBatch or batch.index_code is not index_code:
            return _blocked_snapshot(
                index_code=index_code,
                decision_cutoff=decision_cutoff,
                requests=requests,
                issue=MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,
                observed_at=observed_no_later_than,
            )
        return build_market_index_snapshot(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            requests=requests,
            five_minute_bars=batch.five_minute_bars,
            official_daily_bars=batch.official_daily_bars,
            content_revision=batch.content_revision,
            observed_at=batch.observed_at,
            observed_no_later_than=observed_no_later_than,
            minimum_five_minute_bar_count=minimum_five_minute_bar_count,
            minimum_official_daily_bar_count=minimum_official_daily_bar_count,
        )

    async def _post_fetch_observed_at(self, requested_at: datetime) -> datetime:
        observed_at = _ceil_to_whole_second(requested_at)
        if self._clock is None:
            return observed_at
        now = _canonical_shanghai(self._clock.now())
        observed_at = max(observed_at, _ceil_to_whole_second(now))
        if now < observed_at:
            await self._clock.sleep_until(observed_at)
            if _canonical_shanghai(self._clock.now()) < observed_at:
                raise RuntimeError("clock returned before the market-index observation boundary")
        return observed_at


__all__ = ["MarketIndexSnapshotCoordinator", "build_market_index_snapshot"]
