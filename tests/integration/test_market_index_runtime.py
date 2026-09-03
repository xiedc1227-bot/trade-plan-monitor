"""Runtime batching contracts for shared board-index snapshots."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

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
from trade_plan_monitor.runtime.market_indexes import RuntimeMarketIndexService
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


def test_schema_v1_plans_do_not_trigger_index_acquisition() -> None:
    provider = _Provider(_batch())
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    plan = _plan(1, {"type": "NON_DECREASING_CLOSE"}, schema_version=1)

    prepared = asyncio.run(
        service.prepare(
            plans=(plan,),
            decision_cutoff=CUTOFF,
            observed_no_later_than=OBSERVED_AT,
        )
    )

    assert provider.calls == []
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
    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args, **_kwargs: [],
        fetch_official_daily=lambda *_args, **_kwargs: [],
        unit_of_work_factory=lambda: None,
        context_builder=lambda *_args, **_kwargs: None,
        official_context_builder=lambda *_args, **_kwargs: None,
        committed_event_publisher=lambda _event: None,
        market_index_service=RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider)),
    )

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
    assert len(captured) == 2
    assert captured[0] is captured[1]
