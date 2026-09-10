"""Runtime batching contracts for shared board-index snapshots."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.runtime.market_indexes import (
    DASHBOARD_INDEX_CODES,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.service import RuntimeEvaluationService

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

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        assert index_code is MarketIndexCode.SHENZHEN_COMPONENT
        assert decision_cutoff == CUTOFF
        self.calls.append((five_minute_bar_count, official_daily_bar_count))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _DashboardProvider:
    def __init__(self) -> None:
        self.calls: list[MarketIndexCode] = []

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        assert decision_cutoff == CUTOFF
        assert (five_minute_bar_count, official_daily_bar_count) == (1, 1)
        self.calls.append(index_code)
        original = _batch()
        return MarketIndexProviderBatch(
            index_code=index_code,
            five_minute_bars=tuple(
                bar.model_copy(update={"index_code": index_code})
                for bar in original.five_minute_bars
            ),
            official_daily_bars=tuple(
                bar.model_copy(update={"index_code": index_code})
                for bar in original.official_daily_bars
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

    assert set(provider.calls) == set(DASHBOARD_INDEX_CODES)
    assert set(prepared.snapshots_by_index) == set(DASHBOARD_INDEX_CODES)
    assert all(
        snapshot.health is MarketIndexHealth.LIVE
        and snapshot.fact_requests == ()
        for snapshot in prepared.snapshots_by_index.values()
    )


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
    assert clock.sleep_calls == [expected_observed_at] * len(DASHBOARD_INDEX_CODES)
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
    assert clock.sleep_calls == [expected_observed_at] * len(DASHBOARD_INDEX_CODES)
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
    service._persist_market_index_batch = lambda _prepared: None

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

    assert provider.calls == [(1, 1)]
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

    assert set(provider.calls) == set(DASHBOARD_INDEX_CODES)
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
    service._persist_market_index_batch = persisted.append

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
