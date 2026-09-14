"""Runtime batching contracts for shared board-index snapshots."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.snapshots import (
    MarketIndexSnapshotCoordinator,
    build_market_index_snapshot,
)
from trade_plan_monitor.market_index.turnover import MARKET_TURNOVER_INDEX_CODES
from trade_plan_monitor.market_index.tushare import TushareMarketIndexProviderError
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.request_control import RequestControlErrorCode
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.events import MonitorEventType
from trade_plan_monitor.state.models import Base, MonitorSequence
from trade_plan_monitor.state.projections import ProjectionRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.persistent_monitor_read_service import _dashboard_market_indexes


@pytest.mark.parametrize("include_prior", [True, False])
def test_close_dashboard_uses_previous_session_instead_of_today_daily_close(
    include_prior: bool,
) -> None:
    cutoff = CUTOFF.replace(hour=15, minute=0)
    observed = cutoff + timedelta(minutes=20)
    today = _bar(interval=MarketIndexInterval.OFFICIAL_DAILY, bar_at=cutoff, close="110")
    prior = _bar(
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        bar_at=cutoff - timedelta(days=1), close="100",
    )
    latest = today.model_copy(update={
        "interval": MarketIndexInterval.FIVE_MINUTE,
        "source_kind": MarketIndexSourceKind.PROVISIONAL,
        "observed_at": observed,
    })
    daily = (prior, today) if include_prior else (today,)
    snapshot = build_market_index_snapshot(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT, decision_cutoff=cutoff,
        requests=(), five_minute_bars=(latest,), official_daily_bars=daily,
        content_revision=3, observed_at=observed, observed_no_later_than=observed,
        minimum_official_daily_bar_count=len(daily),
    )
    view = _dashboard_market_indexes((), display_snapshots=(snapshot,))[0]
    if include_prior:
        assert view.prior_close_points == Decimal("100")
        assert view.session_change_ratio == Decimal("0.1")
    else:
        assert view.health is MarketIndexHealth.BLOCKED
        assert view.session_change_ratio is None


def test_transient_index_recovery_targets_one_index_and_stops_after_success() -> None:
    class OnceFailingProvider(_DashboardProvider):
        failed = False

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            if kwargs["index_code"] is MarketIndexCode.SSE_COMPOSITE and not self.failed:
                self.failed = True
                self.calls.append(MarketIndexCode.SSE_COMPOSITE)
                raise TushareMarketIndexProviderError(
                    stage="REALTIME_MINUTES", reason=RequestControlErrorCode.TIMEOUT
                )
            return await super().acquire_index_data(**kwargs)

    provider = OnceFailingProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert (
        initial.snapshots_by_index[MarketIndexCode.SSE_COMPOSITE].health
        is MarketIndexHealth.BLOCKED
    )
    assert service.next_recovery_due_at() == OBSERVED_AT + timedelta(seconds=30)
    failed_view = _dashboard_market_indexes(
        (),
        display_snapshots=(initial.snapshots_by_index[MarketIndexCode.SSE_COMPOSITE],),
        recoveries={
            MarketIndexCode.SSE_COMPOSITE: (
                CUTOFF,
                0,
                OBSERVED_AT + timedelta(seconds=30),
            )
        },
    )[0]
    assert failed_view.recovery_attempts == 0
    assert failed_view.next_retry_at == OBSERVED_AT + timedelta(seconds=30)
    assert asyncio.run(service.retry_recoverable(observed_no_later_than=OBSERVED_AT)) is None

    retry = asyncio.run(
        service.retry_recoverable(observed_no_later_than=OBSERVED_AT + timedelta(seconds=30))
    )
    assert retry is not None
    assert set(retry.snapshots_by_index) == {MarketIndexCode.SSE_COMPOSITE}
    assert retry.snapshots_by_index[MarketIndexCode.SSE_COMPOSITE].health is MarketIndexHealth.LIVE
    assert service.next_recovery_due_at() is None


def test_processing_failure_is_not_retried() -> None:
    provider = _Provider(TushareMarketIndexProviderError(stage="PROCESSING"))
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert service.next_recovery_due_at() is None


def test_later_failed_fetch_does_not_schedule_recovery_over_a_live_same_cutoff() -> None:
    class LaterFailingProvider(_DashboardProvider):
        fail = False

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            if self.fail and kwargs["index_code"] is MarketIndexCode.SSE_COMPOSITE:
                raise TushareMarketIndexProviderError(
                    stage="REALTIME_MINUTES", reason=RequestControlErrorCode.TIMEOUT
                )
            return await super().acquire_index_data(**kwargs)

    provider = LaterFailingProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    provider.fail = True
    asyncio.run(
        service.prepare(
            plans=(),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT + timedelta(seconds=30),
        )
    )
    assert (
        service.latest_snapshots()[MarketIndexCode.SSE_COMPOSITE].health
        is MarketIndexHealth.LIVE
    )
    assert service.next_recovery_due_at() is None


def test_transient_recovery_budget_survives_restart_and_expires() -> None:
    class FailingProvider(_DashboardProvider):
        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            if kwargs["index_code"] is MarketIndexCode.SSE_COMPOSITE:
                self.calls.append(MarketIndexCode.SSE_COMPOSITE)
                raise TushareMarketIndexProviderError(
                    stage="HISTORICAL_MINUTES", reason=RequestControlErrorCode.TRANSIENT
                )
            return await super().acquire_index_data(**kwargs)

    provider = FailingProvider()
    original = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    asyncio.run(
        original.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    first_retry_at = OBSERVED_AT + timedelta(seconds=30)
    asyncio.run(original.retry_recoverable(observed_no_later_than=first_retry_at))
    records = original.recovery_records()
    assert len(records) == 1
    assert records[0][3] == 1

    expired = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    expired.restore_recoveries(
        snapshots=original.latest_snapshots(),
        records=records,
        now=OBSERVED_AT + timedelta(minutes=6),
    )
    assert expired.next_recovery_due_at() is None

    resumed = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    resumed.restore_recoveries(
        snapshots=original.latest_snapshots(),
        records=records,
        now=first_retry_at + timedelta(seconds=1),
    )
    assert resumed.next_recovery_due_at() == first_retry_at + timedelta(seconds=60)
    asyncio.run(
        resumed.retry_recoverable(
            observed_no_later_than=first_retry_at + timedelta(seconds=60)
        )
    )
    asyncio.run(
        resumed.retry_recoverable(
            observed_no_later_than=first_retry_at + timedelta(seconds=180)
        )
    )
    assert resumed.next_recovery_due_at() is None
    assert provider.calls.count(MarketIndexCode.SSE_COMPOSITE) == 4


def test_recovery_budget_is_saved_and_removed_with_projection_transaction() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    record = (
        MarketIndexCode.SSE_COMPOSITE,
        CUTOFF,
        OBSERVED_AT,
        1,
        OBSERVED_AT + timedelta(seconds=90),
    )
    with Session(engine) as session:
        ProjectionRepository(session).replace_market_index_recoveries((record,))
        session.commit()
    with Session(engine) as session:
        repository = ProjectionRepository(session)
        assert repository.list_market_index_recoveries() == (record,)
        repository.replace_market_index_recoveries(())
        session.commit()
    with Session(engine) as session:
        assert ProjectionRepository(session).list_market_index_recoveries() == ()
    engine.dispose()


def test_failed_recovery_updates_retry_status_without_replacing_blocked_head() -> None:
    class FailingProvider(_DashboardProvider):
        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            if kwargs["index_code"] is MarketIndexCode.SSE_COMPOSITE:
                raise TushareMarketIndexProviderError(
                    stage="REALTIME_MINUTES", reason=RequestControlErrorCode.TIMEOUT
                )
            return await super().acquire_index_data(**kwargs)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(MonitorSequence(singleton_id=1, last_sequence=0))
        session.commit()
    index_service = RuntimeMarketIndexService(
        MarketIndexSnapshotCoordinator(FailingProvider())
    )
    session_factory = create_session_factory(engine)
    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: (),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(
            session_factory, clock=lambda: OBSERVED_AT + timedelta(minutes=5)
        ),
        context_builder=lambda *_args: None,
        committed_event_publisher=lambda _event: None,
        market_index_service=index_service,
    )
    initial = asyncio.run(
        index_service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    first, first_events = service._persist_market_index_batch(initial)
    first_head = first.snapshots_by_index[MarketIndexCode.SSE_COMPOSITE]
    assert any(
        event.event_type is MonitorEventType.MARKET_INDEX_UPDATED
        and event.aggregate_id == MarketIndexCode.SSE_COMPOSITE.value
        for event in first_events
    )

    failed_retry = asyncio.run(
        index_service.retry_recoverable(observed_no_later_than=OBSERVED_AT + timedelta(seconds=30))
    )
    assert failed_retry is not None
    second, retry_events = service._persist_market_index_batch(failed_retry)
    assert second.snapshots_by_index[MarketIndexCode.SSE_COMPOSITE] == first_head
    assert len(retry_events) == 1
    assert retry_events[0].aggregate_id == MarketIndexCode.SSE_COMPOSITE.value
    assert retry_events[0].event_type is MonitorEventType.MARKET_INDEX_UPDATED
    with Session(engine) as session:
        repository = ProjectionRepository(session)
        assert repository.list_market_index_recoveries()[0][3] == 1
        assert (
            repository.get_market_index_head(
                mapping_version=first_head.mapping_version,
                index_code=first_head.index_code,
                decision_cutoff=first_head.decision_cutoff,
                request_set_hash=first_head.request_set_hash,
            ).snapshot
            == first_head
        )
    engine.dispose()

SHANGHAI = ZoneInfo("Asia/Shanghai")
CUTOFF = datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI)
OBSERVED_AT = CUTOFF + timedelta(seconds=2)


def _plan(index: int, condition: dict[str, object], *, schema_version: int = 2) -> TradePlan:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "plan_id": f"runtime-index-{index}",
        "version": 2 if schema_version == 2 else 1,
        "symbol": "000001.SZ",
        "name": f"Runtime {index}",
        "market": "SZSE",
        "metadata": {},
        "activation": {"mode": "MANUAL"},
        "position": {"max_qty": 100, "core_target_qty": 100},
        "levels": {
            "low_buy": {"low_fen": 1000, "high_fen": 1100},
            "pressure": {"low_fen": 1200, "high_fen": 1300},
            "risk_line_fen": 900,
            "pressure_reference_fen": 1250,
        },
        "entry": {"condition": condition},
        "reduction": {"condition": {"type": "CLOSE_IN_BAR_LOWER_HALF"}},
        "risk": {
            "condition": {
                "type": "OFFICIAL_CLOSE_BELOW_LEVEL",
                "level": "RISK_LINE",
            }
        },
        "blockers": {"condition": {"type": "MANUAL_EVENT_RISK_CLEAR"}},
        "monitoring": {},
    }
    if schema_version == 2:
        payload["reference_market"] = {
            "selection": "AUTO_BOARD",
            "mapping_version": "board-index-map-v1",
            "index_code": "399001.SZ",
        }
    return TradePlan.model_validate(payload)


def _bar(
    *,
    interval: MarketIndexInterval,
    bar_at: datetime,
    close: str,
) -> MarketIndexBar:
    value = Decimal(close)
    return MarketIndexBar(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        interval=interval,
        bar_at=bar_at,
        open_points=value,
        high_points=value,
        low_points=value,
        close_points=value,
        observed_at=(
            OBSERVED_AT
            if interval is MarketIndexInterval.FIVE_MINUTE
            else bar_at + timedelta(minutes=1)
        ),
        source_kind=(
            MarketIndexSourceKind.PROVISIONAL
            if interval is MarketIndexInterval.FIVE_MINUTE
            else MarketIndexSourceKind.OFFICIAL
        ),
        provider_revision=3,
    )


def _batch() -> MarketIndexProviderBatch:
    return MarketIndexProviderBatch(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        five_minute_bars=tuple(
            _bar(
                interval=MarketIndexInterval.FIVE_MINUTE,
                bar_at=CUTOFF - timedelta(minutes=offset),
                close=str(100 - offset),
            )
            for offset in (10, 5, 0)
        ),
        official_daily_bars=tuple(
            _bar(
                interval=MarketIndexInterval.OFFICIAL_DAILY,
                bar_at=datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
                close=str(100 + day),
            )
            for day in range(20, 25)
        ),
        content_revision=3,
        observed_at=OBSERVED_AT,
    )


class _Provider:
    def __init__(self, result: MarketIndexProviderBatch | Exception) -> None:
        self.result = result
        self.calls: list[tuple[int, int]] = []
        self.requests: list[tuple[MarketIndexCode, datetime, int, int]] = []

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        self.requests.append(
            (
                index_code,
                decision_cutoff,
                five_minute_bar_count,
                official_daily_bar_count,
            )
        )
        if index_code is MarketIndexCode.SHENZHEN_COMPONENT:
            self.calls.append((five_minute_bar_count, official_daily_bar_count))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result.model_copy(
            update={
                "index_code": index_code,
                "five_minute_bars": tuple(
                    bar.model_copy(update={"index_code": index_code})
                    for bar in self.result.five_minute_bars
                ),
                "official_daily_bars": tuple(
                    bar.model_copy(update={"index_code": index_code})
                    for bar in self.result.official_daily_bars
                ),
            }
        )


class _DashboardProvider:
    def __init__(self) -> None:
        self.calls: list[MarketIndexCode] = []
        self.requests: list[tuple[MarketIndexCode, datetime, int, int]] = []

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        self.calls.append(index_code)
        self.requests.append(
            (
                index_code,
                decision_cutoff,
                five_minute_bar_count,
                official_daily_bar_count,
            )
        )
        original = _batch()
        return MarketIndexProviderBatch(
            index_code=index_code,
            five_minute_bars=tuple(
                _bar(
                    interval=MarketIndexInterval.FIVE_MINUTE,
                    bar_at=CUTOFF - timedelta(minutes=5 * offset),
                    close=str(100 - offset),
                ).model_copy(update={"index_code": index_code})
                for offset in reversed(range(five_minute_bar_count))
            ),
            official_daily_bars=tuple(
                bar.model_copy(update={"index_code": index_code})
                for bar in original.official_daily_bars[-official_daily_bar_count:]
            ),
            content_revision=original.content_revision,
            observed_at=original.observed_at,
        )


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.sleep_calls: list[datetime] = []

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_calls.append(deadline)
        self.current = max(self.current, deadline)


def test_ten_plans_union_requirements_and_share_one_snapshot_instance() -> None:
    plans = tuple(
        _plan(
            index,
            (
                {
                    "type": "INDEX_CLOSE_GTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 5,
                }
                if index % 2 == 0
                else {
                    "type": "INDEX_RETURN_GTE",
                    "index_role": "BOARD_REFERENCE",
                    "window": "FIVE_MINUTE_BUCKETS",
                    "window_size": 2,
                    "threshold_ratio": Decimal("-1"),
                }
            ),
        )
        for index in range(10)
    )
    provider = _Provider(_batch())
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))

    prepared = asyncio.run(
        service.prepare(
            plans=plans,
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )

    snapshots = tuple(prepared.snapshot_for_plan(plan) for plan in plans)
    assert provider.calls == [(3, 5)]
    assert {request[0] for request in provider.requests} == set(ALWAYS_ON_INDEX_CODES)
    assert all(request[1] == CUTOFF for request in provider.requests)
    assert {
        request[0]: request[2:] for request in provider.requests
    } == {
        index_code: (
            (3, 5)
            if index_code is MarketIndexCode.SHENZHEN_COMPONENT
            else (13, 2)
            if index_code in MARKET_TURNOVER_INDEX_CODES
            else (1, 2)
        )
        for index_code in ALWAYS_ON_INDEX_CODES
    }
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert snapshots[0] is not None
    assert snapshots[0].health is MarketIndexHealth.LIVE
    assert len(snapshots[0].fact_requests) == 2
    latest = service.latest_snapshots()
    assert latest[MarketIndexCode.SHENZHEN_COMPONENT] is snapshots[0]
    assert "plan" not in snapshots[0].model_dump_json().lower()


def test_dashboard_indexes_are_acquired_without_active_plans() -> None:
    provider = _DashboardProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))

    prepared = asyncio.run(
        service.prepare(
            plans=(),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )

    assert set(provider.calls) == set(ALWAYS_ON_INDEX_CODES)
    assert all(
        decision_cutoff == CUTOFF
        and (five_minute_count, official_daily_count)
        == ((13, 2) if _index_code in MARKET_TURNOVER_INDEX_CODES else (1, 2))
        for (
            _index_code,
            decision_cutoff,
            five_minute_count,
            official_daily_count,
        ) in provider.requests
    )
    assert set(prepared.snapshots_by_index) == set(ALWAYS_ON_INDEX_CODES)
    assert all(
        snapshot.health is MarketIndexHealth.LIVE and snapshot.fact_requests == ()
        for snapshot in prepared.snapshots_by_index.values()
    )
    assert (
        asyncio.run(
            service.retry_publication_lag(
                decision_cutoff=CUTOFF,
                observed_no_later_than=OBSERVED_AT + timedelta(minutes=1),
            )
        )
        is None
    )
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES)


def test_normal_prepare_refetches_new_requirements_revision_cutoff_and_day() -> None:
    class RevisingProvider(_DashboardProvider):
        revision = 3

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            batch = await super().acquire_index_data(**kwargs)
            cutoff = kwargs["decision_cutoff"]
            assert isinstance(cutoff, datetime)
            return batch.model_copy(
                update={
                    "content_revision": self.revision,
                    "observed_at": cutoff + timedelta(seconds=2),
                    "five_minute_bars": tuple(
                        bar.model_copy(
                            update={
                                "bar_at": cutoff - (CUTOFF - bar.bar_at),
                                "observed_at": cutoff + timedelta(seconds=2),
                            }
                        )
                        for bar in batch.five_minute_bars
                    ),
                }
            )

    provider = RevisingProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert len(provider.calls) == 5
    plan = _plan(
        22,
        {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 5},
    )
    richer = asyncio.run(
        service.prepare(plans=(plan,), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert len(provider.calls) == 10
    requested = richer.snapshot_for_plan(plan)
    assert requested is not None and requested.health is MarketIndexHealth.LIVE
    assert len(requested.fact_requests) == 1
    assert requested is not initial.snapshot_for_plan(plan)
    assert (MarketIndexCode.SHENZHEN_COMPONENT, CUTOFF, 1, 5) in provider.requests

    provider.revision = 4
    revised = asyncio.run(
        service.prepare(plans=(plan,), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert len(provider.calls) == 15
    assert revised.snapshot_for_plan(plan).revision == 4
    assert revised.snapshot_for_plan(plan).snapshot_hash != requested.snapshot_hash

    for cutoff in (CUTOFF + timedelta(minutes=5), CUTOFF + timedelta(days=1)):
        next_batch = asyncio.run(
            service.prepare(
                plans=(plan,),
                decision_cutoff=cutoff,
                observed_no_later_than=cutoff + timedelta(seconds=2),
            )
        )
        assert next_batch.decision_cutoff == cutoff
        assert len(provider.calls) == (20 if cutoff.date() == CUTOFF.date() else 25)
        assert {request[0] for request in provider.requests[-5:]} == set(ALWAYS_ON_INDEX_CODES)
        assert all(request[1] == cutoff for request in provider.requests[-5:])


def test_publication_lag_retry_is_not_claimed_for_provider_unavailability() -> None:
    service = RuntimeMarketIndexService(
        MarketIndexSnapshotCoordinator(_Provider(RuntimeError("provider unavailable")))
    )

    prepared = asyncio.run(
        service.prepare(
            plans=(),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )

    assert all(
        snapshot.health is MarketIndexHealth.BLOCKED
        for snapshot in prepared.snapshots_by_index.values()
    )
    assert service.claim_publication_lag_retry(CUTOFF) is False

    provider_failure = next(iter(prepared.snapshots_by_index.values()))
    service._latest_by_index = {
        provider_failure.index_code: provider_failure.model_copy(
            update={
                "health": MarketIndexHealth.STALE,
                "issues": (
                    MarketIndexIssueCode.STALE_DATA,
                    MarketIndexIssueCode.PROVIDER_UNAVAILABLE,
                ),
            }
        )
    }

    assert service.claim_publication_lag_retry(CUTOFF) is False


def test_publication_lag_retry_only_acquires_stale_index_and_preserves_live_snapshots() -> None:
    class DelayedProvider(_DashboardProvider):
        lag = True

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            batch = await super().acquire_index_data(**kwargs)
            if self.lag and kwargs["index_code"] is MarketIndexCode.STAR_50:
                return batch.model_copy(
                    update={
                        "five_minute_bars": tuple(
                            bar.model_copy(update={"bar_at": bar.bar_at - timedelta(minutes=5)})
                            for bar in batch.five_minute_bars
                        )
                    }
                )
            return batch

    provider = DelayedProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert (
        sum(
            snapshot.health is MarketIndexHealth.LIVE
            for snapshot in initial.snapshots_by_index.values()
        )
        == 4
    )
    assert initial.snapshots_by_index[MarketIndexCode.STAR_50].health is MarketIndexHealth.STALE

    provider.lag = False
    retry = asyncio.run(
        service.retry_publication_lag(
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT + timedelta(minutes=1),
        )
    )
    assert retry is not None
    assert set(retry.snapshots_by_index) == {MarketIndexCode.STAR_50}
    assert provider.calls[5:] == [MarketIndexCode.STAR_50]
    assert service.latest_snapshots()[MarketIndexCode.STAR_50].health is MarketIndexHealth.LIVE
    for index_code in set(ALWAYS_ON_INDEX_CODES) - {MarketIndexCode.STAR_50}:
        assert service.latest_snapshots()[index_code] is initial.snapshots_by_index[index_code]
    assert (
        asyncio.run(
            service.retry_publication_lag(
                decision_cutoff=CUTOFF,
                observed_no_later_than=OBSERVED_AT + timedelta(minutes=2),
            )
        )
        is None
    )
    assert len(provider.calls) == 6


def test_publication_lag_retry_ignores_provider_failure_and_keeps_failed_retry_blocked() -> None:
    class MixedProvider(_DashboardProvider):
        retry = False

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            index_code = kwargs["index_code"]
            if index_code is MarketIndexCode.CHINEXT or (
                self.retry and index_code is MarketIndexCode.STAR_50
            ):
                self.calls.append(index_code)
                raise RuntimeError("SIMULATED provider unavailable")
            batch = await super().acquire_index_data(**kwargs)
            if index_code is MarketIndexCode.STAR_50:
                return batch.model_copy(
                    update={
                        "five_minute_bars": tuple(
                            bar.model_copy(update={"bar_at": bar.bar_at - timedelta(minutes=5)})
                            for bar in batch.five_minute_bars
                        )
                    }
                )
            return batch

    provider = MixedProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    assert initial.snapshots_by_index[MarketIndexCode.CHINEXT].health is MarketIndexHealth.BLOCKED
    assert initial.snapshots_by_index[MarketIndexCode.STAR_50].health is MarketIndexHealth.STALE
    provider.retry = True
    retry = asyncio.run(
        service.retry_publication_lag(
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT + timedelta(minutes=1),
        )
    )
    assert retry is not None
    assert provider.calls[5:] == [MarketIndexCode.STAR_50]
    assert retry.snapshots_by_index[MarketIndexCode.STAR_50].health is MarketIndexHealth.BLOCKED
    assert service.latest_snapshots()[MarketIndexCode.STAR_50].health is MarketIndexHealth.BLOCKED
    assert (
        service.latest_snapshots()[MarketIndexCode.CHINEXT]
        is initial.snapshots_by_index[MarketIndexCode.CHINEXT]
    )


def test_delayed_retry_cannot_replace_new_same_cutoff_fact_requirements() -> None:
    class InterleavedProvider(_DashboardProvider):
        def __init__(self) -> None:
            super().__init__()
            self.serve_stale = True
            self.hold_retry = False
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            batch = await super().acquire_index_data(**kwargs)
            if kwargs["index_code"] is not MarketIndexCode.SHENZHEN_COMPONENT:
                return batch
            if self.hold_retry:
                self.hold_retry = False
                self.started.set()
                await self.release.wait()
                return batch
            if self.serve_stale:
                return batch.model_copy(
                    update={
                        "five_minute_bars": tuple(
                            bar.model_copy(update={"bar_at": bar.bar_at - timedelta(minutes=5)})
                            for bar in batch.five_minute_bars
                        )
                    }
                )
            return batch.model_copy(update={"content_revision": 4})

    async def scenario() -> None:
        provider = InterleavedProvider()
        service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
        initial = await service.prepare(
            plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT
        )
        assert (
            initial.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT].health
            is MarketIndexHealth.STALE
        )
        provider.serve_stale = False
        provider.hold_retry = True
        retry_task = asyncio.create_task(
            service.retry_publication_lag(
                decision_cutoff=CUTOFF,
                observed_no_later_than=OBSERVED_AT + timedelta(minutes=1),
            )
        )
        await provider.started.wait()
        plan = _plan(
            21,
            {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 5},
        )
        current = await service.prepare(
            plans=(plan,),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT + timedelta(seconds=30),
        )
        richer = current.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT]
        assert richer.health is MarketIndexHealth.LIVE
        assert len(richer.fact_requests) == 1
        provider.release.set()
        assert await retry_task is None
        assert service.latest_snapshots()[MarketIndexCode.SHENZHEN_COMPONENT] is richer

    asyncio.run(scenario())


def test_index_snapshot_uses_post_fetch_whole_second_as_future_data_fence() -> None:
    requested_at = CUTOFF + timedelta(seconds=2)
    provider_observed_at = requested_at + timedelta(microseconds=250_000)
    expected_observed_at = CUTOFF + timedelta(seconds=3)
    clock = _Clock(requested_at)
    batch = _batch().model_copy(
        update={
            "observed_at": provider_observed_at,
            "five_minute_bars": tuple(
                bar.model_copy(update={"observed_at": provider_observed_at})
                for bar in _batch().five_minute_bars
            ),
        }
    )

    class DelayedProvider(_Provider):
        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            clock.current = provider_observed_at
            return await super().acquire_index_data(**kwargs)  # type: ignore[arg-type]

    provider = DelayedProvider(batch)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider, clock=clock))

    prepared = asyncio.run(
        service.prepare(
            plans=(_plan(1, {"type": "NON_DECREASING_CLOSE"}),),
            decision_cutoff=CUTOFF,
            observed_no_later_than=requested_at,
        )
    )
    snapshot = prepared.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT]

    assert snapshot.health is MarketIndexHealth.LIVE
    assert snapshot.observed_at == provider_observed_at
    assert clock.sleep_calls == [expected_observed_at] * len(ALWAYS_ON_INDEX_CODES)
    assert snapshot.observed_at <= clock.now()


def test_blocked_index_snapshot_is_not_returned_before_observation_boundary() -> None:
    requested_at = CUTOFF + timedelta(seconds=2)
    provider_finished_at = requested_at + timedelta(microseconds=250_000)
    expected_observed_at = CUTOFF + timedelta(seconds=3)
    clock = _Clock(requested_at)

    class DelayedFailingProvider(_Provider):
        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            clock.current = provider_finished_at
            raise RuntimeError("provider unavailable")

    service = RuntimeMarketIndexService(
        MarketIndexSnapshotCoordinator(
            DelayedFailingProvider(RuntimeError("unused")),
            clock=clock,
        )
    )

    prepared = asyncio.run(
        service.prepare(
            plans=(_plan(1, {"type": "NON_DECREASING_CLOSE"}),),
            decision_cutoff=CUTOFF,
            observed_no_later_than=requested_at,
        )
    )
    snapshot = prepared.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT]

    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.observed_at == expected_observed_at
    assert clock.sleep_calls == [expected_observed_at] * len(ALWAYS_ON_INDEX_CODES)
    assert snapshot.observed_at <= clock.now()


def test_evaluation_rejects_index_snapshot_observed_after_its_evaluation_time() -> None:
    requested_at = CUTOFF + timedelta(seconds=2)
    provider_observed_at = requested_at + timedelta(seconds=1)
    clock = _Clock(provider_observed_at)
    batch = _batch().model_copy(
        update={
            "observed_at": provider_observed_at,
            "five_minute_bars": tuple(
                bar.model_copy(update={"observed_at": provider_observed_at})
                for bar in _batch().five_minute_bars
            ),
        }
    )
    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: (),  # type: ignore[arg-type]
        unit_of_work_factory=lambda: None,
        context_builder=lambda *_args: None,
        committed_event_publisher=lambda _event: None,
        market_index_service=RuntimeMarketIndexService(
            MarketIndexSnapshotCoordinator(_Provider(batch), clock=clock)
        ),
    )
    service._persist_market_index_batch = lambda prepared: (prepared, ())

    with pytest.raises(ValueError, match="index snapshot observation"):
        asyncio.run(
            service.run_intraday_batch_from_minutes(
                plans=(_plan(1, {"type": "NON_DECREASING_CLOSE"}),),
                bucket_end=CUTOFF,
                evaluated_at=requested_at,
                minutes_by_symbol={"000001.SZ": ()},
            )
        )


def test_v2_no_condition_plan_gets_informational_failure_without_a_requirement() -> None:
    provider = _Provider(RuntimeError("secret provider failure"))
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    plan = _plan(1, {"type": "NON_DECREASING_CLOSE"})

    prepared = asyncio.run(
        service.prepare(
            plans=(plan,),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )
    snapshot = prepared.snapshot_for_plan(plan)

    assert provider.calls == [(1, 2)]
    assert {request[0] for request in provider.requests} == set(ALWAYS_ON_INDEX_CODES)
    assert all(request[1] == CUTOFF for request in provider.requests)
    assert snapshot is not None
    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.fact_requests == ()


def test_schema_v1_plans_do_not_add_plan_owned_index_requirements() -> None:
    provider = _DashboardProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    plan = _plan(1, {"type": "NON_DECREASING_CLOSE"}, schema_version=1)

    prepared = asyncio.run(
        service.prepare(
            plans=(plan,),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )

    assert set(provider.calls) == set(ALWAYS_ON_INDEX_CODES)
    assert prepared.snapshot_for_plan(plan) is None


def test_official_close_batch_unions_requirements_and_shares_one_snapshot() -> None:
    trade_date = date(2026, 9, 2)
    cutoff = datetime.combine(trade_date, time(15, 0), SHANGHAI)
    evaluated_at = cutoff + timedelta(minutes=1)
    plans = (
        _plan(
            1,
            {
                "type": "INDEX_CLOSE_GTE_MA",
                "index_role": "BOARD_REFERENCE",
                "period": 2,
            },
        ),
        _plan(
            2,
            {
                "type": "INDEX_CLOSE_LTE_MA",
                "index_role": "BOARD_REFERENCE",
                "period": 3,
            },
        ),
    )

    def official_bar(interval: MarketIndexInterval, bar_at: datetime) -> MarketIndexBar:
        return MarketIndexBar(
            index_code=MarketIndexCode.SHENZHEN_COMPONENT,
            interval=interval,
            bar_at=bar_at,
            open_points=Decimal("100"),
            high_points=Decimal("100"),
            low_points=Decimal("100"),
            close_points=Decimal("100"),
            observed_at=evaluated_at,
            source_kind=(
                MarketIndexSourceKind.PROVISIONAL
                if interval is MarketIndexInterval.FIVE_MINUTE
                else MarketIndexSourceKind.OFFICIAL
            ),
            provider_revision=4,
        )

    class OfficialProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def acquire_index_data(
            self,
            *,
            index_code: MarketIndexCode,
            decision_cutoff: datetime,
            five_minute_bar_count: int,
            official_daily_bar_count: int,
        ) -> MarketIndexProviderBatch:
            assert index_code is MarketIndexCode.SHENZHEN_COMPONENT
            assert decision_cutoff == cutoff
            self.calls.append((five_minute_bar_count, official_daily_bar_count))
            return MarketIndexProviderBatch(
                index_code=index_code,
                five_minute_bars=(official_bar(MarketIndexInterval.FIVE_MINUTE, cutoff),),
                official_daily_bars=tuple(
                    official_bar(
                        MarketIndexInterval.OFFICIAL_DAILY,
                        datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
                    )
                    for day in (21, 22, 23)
                ),
                content_revision=4,
                observed_at=evaluated_at,
            )

    provider = OfficialProvider()
    captured: list[object] = []
    persisted: list[object] = []
    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args, **_kwargs: [],
        fetch_official_daily=lambda *_args, **_kwargs: [],
        unit_of_work_factory=lambda: None,
        context_builder=lambda *_args, **_kwargs: None,
        official_context_builder=lambda *_args, **_kwargs: None,
        committed_event_publisher=lambda _event: None,
        market_index_service=RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider)),
    )
    def persist(prepared: object):
        persisted.append(prepared)
        return prepared, ()

    service._persist_market_index_batch = persist

    async def capture_official_close(**kwargs: object) -> str:
        captured.append(kwargs["reference_market_snapshot"])
        plan = kwargs["plan"]
        assert isinstance(plan, TradePlan)
        return plan.plan_id

    service._run_official_close_unlocked = capture_official_close
    results = asyncio.run(
        service.run_official_close_batch(
            plans=plans,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            close_attempt=1,
        )
    )

    assert results == tuple(plan.plan_id for plan in plans)
    assert provider.calls == [(1, 3)]
    assert len(persisted) == 1
    assert len(captured) == 2
    assert captured[0] is captured[1]
