"""Shared board-index acquisition and snapshot coordination contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSourceKind,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.requirements import (
    required_bar_counts,
    union_fact_requests,
)
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator

SHANGHAI = timezone(timedelta(hours=8))
CUTOFF = datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI)
EVALUATED_AT = datetime(2026, 9, 2, 10, 36, tzinfo=SHANGHAI)


def _bar(
    *,
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    bar_at: datetime,
    close: str,
    revision: int = 7,
) -> MarketIndexBar:
    close_points = Decimal(close)
    return MarketIndexBar(
        index_code=index_code,
        interval=interval,
        bar_at=bar_at,
        open_points=close_points,
        high_points=close_points,
        low_points=close_points,
        close_points=close_points,
        observed_at=(
            EVALUATED_AT
            if interval is MarketIndexInterval.FIVE_MINUTE
            else bar_at + timedelta(minutes=5)
        ),
        source_kind=(
            MarketIndexSourceKind.PROVISIONAL
            if interval is MarketIndexInterval.FIVE_MINUTE
            else MarketIndexSourceKind.OFFICIAL
        ),
        provider_revision=revision,
    )


def _batch(index_code: MarketIndexCode, *, revision: int = 7) -> MarketIndexProviderBatch:
    five_minute_bars = tuple(
        _bar(
            index_code=index_code,
            interval=MarketIndexInterval.FIVE_MINUTE,
            bar_at=CUTOFF - timedelta(minutes=5 * offset),
            close=str(100 + (2 - offset)),
            revision=revision,
        )
        for offset in reversed(range(3))
    )
    official_daily_bars = tuple(
        _bar(
            index_code=index_code,
            interval=MarketIndexInterval.OFFICIAL_DAILY,
            bar_at=datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
            close=str(90 + day),
            revision=revision,
        )
        for day in range(20, 29)
    )
    return MarketIndexProviderBatch(
        index_code=index_code,
        five_minute_bars=five_minute_bars,
        official_daily_bars=official_daily_bars,
        content_revision=revision,
        observed_at=EVALUATED_AT,
    )


class _FakeProvider:
    def __init__(self, batches: Mapping[MarketIndexCode, MarketIndexProviderBatch | Exception]):
        self._batches = batches
        self.calls: list[tuple[MarketIndexCode, datetime, int, int]] = []

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        self.calls.append(
            (
                index_code,
                decision_cutoff,
                five_minute_bar_count,
                official_daily_bar_count,
            )
        )
        await asyncio.sleep(0)
        result = self._batches[index_code]
        if isinstance(result, Exception):
            raise result
        return result


def test_requirement_union_is_order_independent_and_uses_maximum_history() -> None:
    sma = SmaFactRequest(period=5)
    trend = SmaLookbackFactRequest(period=5, lookback=3)
    intraday_return = ReturnFactRequest(
        window=ReturnWindow.FIVE_MINUTE_BUCKETS,
        window_size=2,
    )
    daily_return = ReturnFactRequest(
        window=ReturnWindow.OFFICIAL_OPEN_DAYS,
        window_size=6,
    )

    forward = union_fact_requests((sma, trend), (intraday_return, sma), (daily_return,))
    reverse = union_fact_requests((daily_return,), (sma, intraday_return), (trend, sma))

    assert forward == reverse
    assert len(forward) == 4
    assert required_bar_counts(forward) == (3, 8)


def test_equal_concurrent_keys_share_one_immutable_snapshot_and_one_fetch() -> None:
    provider = _FakeProvider({MarketIndexCode.CHINEXT: _batch(MarketIndexCode.CHINEXT)})
    coordinator = MarketIndexSnapshotCoordinator(provider)
    requests = union_fact_requests(
        (SmaFactRequest(period=3),),
        (
            ReturnFactRequest(
                window=ReturnWindow.FIVE_MINUTE_BUCKETS,
                window_size=2,
            ),
        ),
    )

    async def scenario() -> tuple[object, ...]:
        return tuple(
            await asyncio.gather(
                *(
                    coordinator.get_snapshot(
                        index_code=MarketIndexCode.CHINEXT,
                        decision_cutoff=CUTOFF,
                        requests=requests,
                        observed_no_later_than=EVALUATED_AT,
                    )
                    for _ in range(10)
                )
            )
        )

    snapshots = asyncio.run(scenario())

    assert len(provider.calls) == 1
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    snapshot = snapshots[0]
    assert snapshot.health is MarketIndexHealth.LIVE
    assert snapshot.snapshot_hash
    assert snapshot.latest_completed_five_minute.close_points == Decimal("102")
    assert len(snapshot.indicator_facts) == 2
    assert snapshot.cache_key.provider_content_revision == 7


def test_completed_cache_tracks_revisions_and_does_not_reuse_blocked_snapshots() -> None:
    batches: dict[MarketIndexCode, MarketIndexProviderBatch | Exception] = {
        MarketIndexCode.CHINEXT: _batch(MarketIndexCode.CHINEXT, revision=7)
    }
    provider = _FakeProvider(batches)
    coordinator = MarketIndexSnapshotCoordinator(provider)

    async def scenario() -> tuple[object, object, object, object]:
        first = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
        batches[MarketIndexCode.CHINEXT] = _batch(MarketIndexCode.CHINEXT, revision=8)
        second = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
        batches[MarketIndexCode.CHINEXT] = RuntimeError("provider unavailable")
        first_failure_fence = EVALUATED_AT + timedelta(minutes=1)
        first_failure = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=first_failure_fence,
        )
        second_failure_fence = EVALUATED_AT + timedelta(minutes=2)
        second_failure = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=second_failure_fence,
        )
        return first, second, first_failure, second_failure

    first, second, first_failure, second_failure = asyncio.run(scenario())

    assert len(provider.calls) == 4
    assert first.cache_key.provider_content_revision == 7
    assert second.cache_key.provider_content_revision == 8
    assert first.snapshot_hash != second.snapshot_hash
    assert first_failure.health is MarketIndexHealth.BLOCKED
    assert second_failure.health is MarketIndexHealth.BLOCKED
    assert first_failure.observed_at == EVALUATED_AT + timedelta(minutes=1)
    assert second_failure.observed_at == EVALUATED_AT + timedelta(minutes=2)
    assert first_failure is not second_failure


def test_request_union_changes_cache_identity_and_fetch_shape() -> None:
    provider = _FakeProvider({MarketIndexCode.CHINEXT: _batch(MarketIndexCode.CHINEXT)})
    coordinator = MarketIndexSnapshotCoordinator(provider)

    async def scenario() -> tuple[object, object]:
        first = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
        second = await coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=4),),
            observed_no_later_than=EVALUATED_AT,
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert len(provider.calls) == 2
    assert first.request_set_hash != second.request_set_hash
    assert first.snapshot_hash != second.snapshot_hash


def test_provider_response_order_does_not_change_snapshot_content() -> None:
    ordered = _batch(MarketIndexCode.CHINEXT)
    reversed_batch = ordered.model_copy(
        update={
            "five_minute_bars": tuple(reversed(ordered.five_minute_bars)),
            "official_daily_bars": tuple(reversed(ordered.official_daily_bars)),
        }
    )

    async def acquire(batch: MarketIndexProviderBatch) -> object:
        return await MarketIndexSnapshotCoordinator(
            _FakeProvider({MarketIndexCode.CHINEXT: batch})
        ).get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )

    first = asyncio.run(acquire(ordered))
    second = asyncio.run(acquire(reversed_batch))

    assert first.snapshot_hash == second.snapshot_hash
    assert first.latest_completed_five_minute == second.latest_completed_five_minute
    assert first.five_minute_bars == second.five_minute_bars
    assert first.official_daily_bars == second.official_daily_bars


def test_snapshot_retains_only_the_exact_unioned_history_window() -> None:
    provider = _FakeProvider({MarketIndexCode.CHINEXT: _batch(MarketIndexCode.CHINEXT)})
    coordinator = MarketIndexSnapshotCoordinator(provider)

    snapshot = asyncio.run(
        coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.LIVE
    assert snapshot.five_minute_bars == (_batch(MarketIndexCode.CHINEXT).five_minute_bars[-1],)
    assert snapshot.official_daily_bars == _batch(MarketIndexCode.CHINEXT).official_daily_bars[-3:]


def test_latest_completed_bucket_before_cutoff_is_stale_not_live() -> None:
    complete = _batch(MarketIndexCode.CHINEXT)
    stale = complete.model_copy(update={"five_minute_bars": complete.five_minute_bars[:-1]})
    provider = _FakeProvider({MarketIndexCode.CHINEXT: stale})

    snapshot = asyncio.run(
        MarketIndexSnapshotCoordinator(provider).get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.STALE
    assert snapshot.issues == (MarketIndexIssueCode.STALE_DATA,)
    assert snapshot.indicator_facts == ()


def test_gap_inside_required_five_minute_window_is_not_live() -> None:
    complete = _batch(MarketIndexCode.CHINEXT)
    earlier = _bar(
        index_code=MarketIndexCode.CHINEXT,
        interval=MarketIndexInterval.FIVE_MINUTE,
        bar_at=CUTOFF - timedelta(minutes=15),
        close="99",
    )
    gapped = complete.model_copy(
        update={
            "five_minute_bars": (
                earlier,
                complete.five_minute_bars[0],
                complete.five_minute_bars[-1],
            )
        }
    )
    provider = _FakeProvider({MarketIndexCode.CHINEXT: gapped})

    snapshot = asyncio.run(
        MarketIndexSnapshotCoordinator(provider).get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(
                ReturnFactRequest(
                    window=ReturnWindow.FIVE_MINUTE_BUCKETS,
                    window_size=2,
                ),
            ),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.GAPPED
    assert snapshot.issues == (MarketIndexIssueCode.GAPPED_SERIES,)
    assert snapshot.indicator_facts == ()


def test_provider_failure_is_sanitized_and_isolated_by_index() -> None:
    secret = "never-return-this-provider-token"
    provider = _FakeProvider(
        {
            MarketIndexCode.CHINEXT: RuntimeError(f"permission denied: {secret}"),
            MarketIndexCode.STAR_50: _batch(MarketIndexCode.STAR_50),
        }
    )
    coordinator = MarketIndexSnapshotCoordinator(provider)

    snapshots = asyncio.run(
        coordinator.get_snapshots(
            requirements={
                MarketIndexCode.CHINEXT: (SmaFactRequest(period=3),),
                MarketIndexCode.STAR_50: (SmaFactRequest(period=3),),
            },
            decision_cutoff=CUTOFF,
            observed_no_later_than=EVALUATED_AT,
        )
    )

    failed = snapshots[MarketIndexCode.CHINEXT]
    healthy = snapshots[MarketIndexCode.STAR_50]
    assert failed.health is MarketIndexHealth.BLOCKED
    assert failed.issues == (MarketIndexIssueCode.PROVIDER_UNAVAILABLE,)
    assert healthy.health is MarketIndexHealth.LIVE
    assert secret not in failed.model_dump_json()


def test_mismatched_provider_identity_fails_closed_without_raw_exception() -> None:
    wrong = _batch(MarketIndexCode.STAR_50).model_copy(
        update={"index_code": MarketIndexCode.CHINEXT}
    )
    provider = _FakeProvider({MarketIndexCode.STAR_50: wrong})
    coordinator = MarketIndexSnapshotCoordinator(provider)

    snapshot = asyncio.run(
        coordinator.get_snapshot(
            index_code=MarketIndexCode.STAR_50,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.issues == (MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,)


def test_mismatched_provider_interval_fails_closed_as_identity_error() -> None:
    valid = _batch(MarketIndexCode.CHINEXT)
    wrong = valid.model_copy(update={"five_minute_bars": (valid.official_daily_bars[-1],)})

    snapshot = asyncio.run(
        MarketIndexSnapshotCoordinator(
            _FakeProvider({MarketIndexCode.CHINEXT: wrong})
        ).get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(SmaFactRequest(period=3),),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.issues == (MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,)


def test_provider_observation_after_evaluation_fails_closed_as_future_data() -> None:
    future_batch = _batch(MarketIndexCode.CHINEXT).model_copy(
        update={"observed_at": EVALUATED_AT + timedelta(seconds=1)}
    )
    provider = _FakeProvider({MarketIndexCode.CHINEXT: future_batch})
    coordinator = MarketIndexSnapshotCoordinator(provider)

    snapshot = asyncio.run(
        coordinator.get_snapshot(
            index_code=MarketIndexCode.CHINEXT,
            decision_cutoff=CUTOFF,
            requests=(),
            observed_no_later_than=EVALUATED_AT,
        )
    )

    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.issues == (MarketIndexIssueCode.FUTURE_DATA,)
