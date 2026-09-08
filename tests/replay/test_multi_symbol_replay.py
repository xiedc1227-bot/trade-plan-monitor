"""Deterministic three-symbol replay through domain, runtime, SQLite, and outbox."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, func, select

from trade_plan_monitor.decision.models import (
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    EpisodeStatus,
    EvaluationContext,
    IntradayEvaluationTarget,
    LowZoneEpisodeSnapshot,
    RiskStateSnapshot,
    RiskStatus,
    SignalType,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.indicators import IndicatorPoint, IndicatorSeries
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close
from trade_plan_monitor.notifications.render import DISCLAIMER
from trade_plan_monitor.runtime.service import (
    IntradayCycleResult,
    IntradayCycleStatus,
    IntradayMarketFacts,
    RuntimeEvaluationService,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEvent, MonitorEventType
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow
from trade_plan_monitor.state.models import (
    DailyBar as DailyBarRow,
)
from trade_plan_monitor.state.models import (
    EvaluationLedger,
    SymbolHealth,
    ZoneEpisode,
)
from trade_plan_monitor.state.models import (
    FiveMinuteBar as FiveMinuteBarRow,
)
from trade_plan_monitor.state.models import (
    MinuteBar as MinuteBarRow,
)
from trade_plan_monitor.state.models import (
    MonitorEvent as MonitorEventRow,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE_ROOT: Final = PROJECT_ROOT / "tests" / "fixtures" / "replay"


def _fixture(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    assert value["schemaVersion"] == 1
    return value


def _plans(payload: dict[str, Any]) -> dict[str, TradePlan]:
    base_path = PROJECT_ROOT / payload["basePlan"]
    base = load_plan_yaml(base_path.read_text(encoding="utf-8"))
    plans: dict[str, TradePlan] = {}
    for item in payload["plans"]:
        raw = base.model_dump(mode="python", round_trip=True)
        raw.update(
            plan_id=item["planId"],
            symbol=item["symbol"],
            name=item["name"],
        )
        plans[item["scenario"]] = TradePlan.model_validate(raw)
    return plans


def _bar_minutes(bar: FiveMinuteBar) -> tuple[MinuteBar, ...]:
    ends = tuple(bar.bar_end - timedelta(minutes=offset) for offset in range(4, -1, -1))
    previous_close = max(bar.low_fen, min(bar.high_fen, bar.close_fen - 1))
    closes = (bar.open_fen, bar.open_fen, bar.open_fen, previous_close, bar.close_fen)
    return tuple(
        MinuteBar(
            symbol=bar.symbol,
            bar_end=bar_end,
            open_fen=bar.open_fen if index == 0 else closes[index - 1],
            high_fen=bar.high_fen if index == 4 else max(closes[index - 1], close),
            low_fen=bar.low_fen if index == 4 else min(closes[index - 1], close),
            close_fen=close,
            volume_shares=bar.volume_shares if index == 4 else 0,
            amount_yuan=bar.amount_yuan if index == 4 else Decimal("0"),
            received_at=bar_end,
        )
        for index, (bar_end, close) in enumerate(zip(ends, closes, strict=True))
    )


def _minutes(
    spec: dict[str, Any],
    *,
    bucket_end: datetime,
    bar_count: int,
) -> tuple[MinuteBar, ...]:
    ends = tuple(
        bucket_end - timedelta(minutes=5 * offset) for offset in range(bar_count - 1, -1, -1)
    )
    bars = tuple(
        FiveMinuteBar(
            symbol=spec["symbol"],
            bar_end=end,
            open_fen=spec["closeFen"],
            high_fen=spec["highFen"],
            low_fen=(spec["latestLowFen"] if index == len(ends) - 1 else spec["baselineLowFen"]),
            close_fen=spec["closeFen"],
            volume_shares=100,
            amount_yuan=Decimal("6400"),
        )
        for index, end in enumerate(ends)
    )
    return tuple(minute for bar in bars for minute in _bar_minutes(bar))


def _indicator_point(
    bar_at: date | datetime,
    *,
    histogram: float,
) -> IndicatorPoint:
    return IndicatorPoint(
        bar_at=bar_at,
        ema10_yuan=64.0,
        ema12_yuan=64.0,
        ema26_yuan=64.0,
        macd_yuan=0.0,
        macd_signal_yuan=0.0,
        macd_histogram_yuan=histogram,
        boll_middle_yuan=64.0,
        boll_upper_yuan=64.5,
        boll_lower_yuan=63.5,
        rsi14=50.0,
        atr14_yuan=0.5,
        ma20_yuan=64.0,
        ma50_yuan=None if isinstance(bar_at, datetime) else 64.0,
        ma200_yuan=None if isinstance(bar_at, datetime) else 64.0,
    )


def _context_builder(
    specs: dict[str, dict[str, Any]],
    *,
    previous_trade_date: date,
) -> Callable[[TradePlan, IntradayMarketFacts], EvaluationContext]:
    def build(plan: TradePlan, facts: IntradayMarketFacts) -> EvaluationContext:
        spec = specs[plan.symbol]
        plan_hash = plan_sha256(plan)
        status = DataHealthStatus(spec["healthStatus"])
        fresh = status is DataHealthStatus.LIVE
        official = DailyBar(
            symbol=plan.symbol,
            trade_date=previous_trade_date,
            open_fen=6400,
            high_fen=6420,
            low_fen=6380,
            close_fen=6400,
            volume_shares=2_000,
            amount_yuan=Decimal("128000"),
            is_official=True,
            received_at=datetime.combine(
                previous_trade_date,
                datetime.min.time(),
                SHANGHAI,
            ).replace(hour=15, minute=30),
        )
        five_minute_indicators = IndicatorSeries(
            symbol=plan.symbol,
            points=tuple(
                _indicator_point(bar.bar_end, histogram=0.0)
                for bar in facts.complete_five_minute_bars
            ),
        )
        daily_indicators = IndicatorSeries(
            symbol=plan.symbol,
            points=(
                _indicator_point(previous_trade_date, histogram=-0.10),
                _indicator_point(facts.bucket_end.date(), histogram=-0.08),
            ),
        )
        reconciliation = reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=facts.bucket_end.date(),
            daily_bars=(facts.provisional_daily_bar,),
        )
        episode = LowZoneEpisodeSnapshot(
            episode_id=spec["episodeId"],
            plan_hash=plan_hash,
            symbol=plan.symbol,
            started_at=facts.bucket_end.replace(hour=9, minute=31),
            episode_low_fen=spec["initialEpisodeLowFen"],
            bars_since_low=spec["initialBarsSinceLow"],
            last_processed_bucket_end=facts.bucket_end - timedelta(minutes=5),
            status=EpisodeStatus.ACTIVE,
            alerted_signal=None,
        )
        return EvaluationContext(
            evaluated_at=facts.evaluated_at,
            target=IntradayEvaluationTarget(bucket_end=facts.bucket_end),
            plan=plan,
            plan_hash=plan_hash,
            plan_active=True,
            activated_at=facts.bucket_end.replace(hour=9, minute=0),
            current_day_minutes=facts.current_day_minutes,
            complete_5m_bars=facts.complete_five_minute_bars,
            official_daily_bars=(official,),
            five_minute_indicators=five_minute_indicators,
            daily_indicator_snapshot=DailyIndicatorSnapshot(
                series=daily_indicators,
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=facts.source_as_of,
                source_bar=facts.provisional_daily_bar,
            ),
            close_reconciliation=reconciliation,
            trading_calendar=(
                TradingDay(
                    exchange=plan.market,
                    cal_date=facts.bucket_end.date(),
                    is_open=True,
                    previous_trade_date=previous_trade_date,
                ),
            ),
            daily_limit=DailyLimit(
                symbol=plan.symbol,
                trade_date=facts.bucket_end.date(),
                up_limit_fen=7200,
                down_limit_fen=6000,
                received_at=facts.bucket_end.replace(hour=9, minute=31),
            ),
            data_health=DataHealthSnapshot(
                symbol=plan.symbol,
                status=status,
                latest_bar_end=facts.bucket_end,
                data_age_seconds=spec["dataAgeSeconds"],
                required_data_complete=True,
                fresh=fresh,
            ),
            positions=(),
            low_zone_episode=episode,
            risk_state=RiskStateSnapshot(
                symbol=plan.symbol,
                plan_hash=plan_hash,
                status=RiskStatus.CLEAR,
                breach_trade_date=None,
                prior_close_fen=6400,
                revision=0,
                updated_at=facts.bucket_end.replace(hour=9, minute=30),
            ),
            manual_event_risk=False,
        )

    return build


def _unit_of_work_factory(
    engine: Engine,
    *,
    now: datetime,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    session_factory = create_session_factory(engine)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock=lambda: now)

    return factory


def _seed_health(
    factory: Callable[[], SqlAlchemyUnitOfWork],
    specs: dict[str, dict[str, Any]],
    *,
    bucket_end: datetime,
) -> None:
    with factory() as work:
        for symbol, spec in specs.items():
            is_live = spec["healthStatus"] == "LIVE"
            work.health.upsert_symbol(
                symbol=symbol,
                status=spec["healthStatus"],
                latest_bar_end=bucket_end,
                data_age_seconds=spec["dataAgeSeconds"],
                gaps={"missingBucketEnds": []},
                error_streak=0 if is_live else 1,
                expected_revision=0,
            )
        work.commit()


def _database_snapshot(engine: Engine) -> dict[str, object]:
    with create_session_factory(engine)() as session:
        alerts = tuple(
            session.execute(
                select(
                    AlertEventRow.id,
                    AlertEventRow.dedup_key,
                    AlertEventRow.message_text,
                ).order_by(AlertEventRow.sequence)
            ).all()
        )
        episodes = tuple(
            session.execute(
                select(
                    ZoneEpisode.symbol,
                    ZoneEpisode.episode_low_fen,
                    ZoneEpisode.bars_since_low,
                    ZoneEpisode.status,
                    ZoneEpisode.alerted_signal,
                    ZoneEpisode.last_processed_bucket_end,
                ).order_by(ZoneEpisode.symbol)
            ).all()
        )
        health = tuple(
            session.execute(
                select(
                    SymbolHealth.symbol,
                    SymbolHealth.status,
                    SymbolHealth.data_age_seconds,
                    SymbolHealth.error_streak,
                    SymbolHealth.revision,
                ).order_by(SymbolHealth.symbol)
            ).all()
        )
        evaluations = tuple(
            session.execute(
                select(
                    EvaluationLedger.symbol,
                    EvaluationLedger.result_hash,
                ).order_by(EvaluationLedger.symbol)
            ).all()
        )
        events = tuple(
            session.execute(
                select(
                    MonitorEventRow.sequence,
                    MonitorEventRow.event_type,
                    MonitorEventRow.aggregate_id,
                ).order_by(MonitorEventRow.sequence)
            ).all()
        )
        counts = {
            "minutes": session.scalar(select(func.count()).select_from(MinuteBarRow)),
            "fiveMinute": session.scalar(select(func.count()).select_from(FiveMinuteBarRow)),
            "daily": session.scalar(select(func.count()).select_from(DailyBarRow)),
        }
    return {
        "alerts": alerts,
        "episodes": episodes,
        "health": health,
        "evaluations": evaluations,
        "events": events,
        "counts": counts,
    }


def test_three_symbol_full_system_replay_is_exactly_once_across_restart(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    plan_payload = _fixture("three_symbol_plans.json")
    market = _fixture("three_symbol_market.json")
    plans = _plans(plan_payload)
    specs = {item["symbol"]: item for item in market["symbols"]}
    scenario_plans = {item["scenario"]: plans[item["scenario"]] for item in market["symbols"]}
    assert set(scenario_plans) == {"VALID_ENTRY", "CONTINUOUS_FALL", "STALE_DATA"}
    assert {plan.symbol for plan in scenario_plans.values()} == set(specs)

    bucket_end = datetime.fromisoformat(market["bucketEnd"]).astimezone(SHANGHAI)
    evaluated_at = datetime.fromisoformat(market["evaluatedAt"]).astimezone(SHANGHAI)
    previous_trade_date = date.fromisoformat(market["previousTradeDate"])
    assert bucket_end.date() == date.fromisoformat(market["tradeDate"])
    all_minutes = {
        symbol: _minutes(
            spec,
            bucket_end=bucket_end,
            bar_count=market["barCount"],
        )
        for symbol, spec in specs.items()
    }
    fetch_modes = {symbol: spec["initialFetch"] for symbol, spec in specs.items()}
    publications: list[MonitorEvent] = []

    async def fetch_minutes(symbol: str, target: datetime) -> tuple[MinuteBar, ...]:
        assert target == bucket_end
        rows = all_minutes[symbol]
        return rows[-1:] if fetch_modes[symbol] == "LATEST_ONLY" else rows

    database_path = tmp_path / "three-symbol-replay.db"
    engine = create_sqlite_engine(database_path)
    request.addfinalizer(engine.dispose)
    upgrade_database(engine)
    factory = _unit_of_work_factory(engine, now=evaluated_at + timedelta(seconds=1))
    _seed_health(factory, specs, bucket_end=bucket_end)

    def service(published: list[MonitorEvent]) -> RuntimeEvaluationService:
        return RuntimeEvaluationService(
            fetch_minutes=fetch_minutes,
            unit_of_work_factory=factory,
            context_builder=_context_builder(
                specs,
                previous_trade_date=previous_trade_date,
            ),
            committed_event_publisher=published.append,
            event_id_factory=lambda: UUID("00000000-0000-0000-0000-000000000054"),
        )

    valid_plan = scenario_plans["VALID_ENTRY"]
    incomplete = asyncio.run(
        service(publications).run_intraday(
            plan=valid_plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )
    assert incomplete.status is IntradayCycleStatus.INCOMPLETE
    assert publications == []

    fetch_modes[valid_plan.symbol] = "FULL"
    first_results: dict[str, IntradayCycleResult] = {}
    for scenario, plan in scenario_plans.items():
        first_results[scenario] = asyncio.run(
            service(publications).run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )

    assert all(result.status is IntradayCycleStatus.COMMITTED for result in first_results.values())
    assert first_results["VALID_ENTRY"].evaluation_result is not None
    assert (
        first_results["VALID_ENTRY"].evaluation_result.snapshot.signal_type
        is SignalType.BUY_CORE_READY
    )
    assert first_results["VALID_ENTRY"].committed_event is not None
    assert first_results["CONTINUOUS_FALL"].evaluation_result is not None
    assert (
        first_results["CONTINUOUS_FALL"].evaluation_result.snapshot.signal_type
        is SignalType.LOW_ZONE_WATCH
    )
    assert first_results["CONTINUOUS_FALL"].committed_event is None
    assert first_results["STALE_DATA"].evaluation_result is not None
    assert (
        first_results["STALE_DATA"].evaluation_result.snapshot.signal_type
        is SignalType.BLOCKED_DATA
    )
    assert first_results["STALE_DATA"].committed_event is None
    assert [event.event_type for event in publications] == [
        MonitorEventType.ALERT_CREATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]

    for plan in scenario_plans.values():
        duplicate = asyncio.run(
            service(publications).run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )
        assert duplicate.status is IntradayCycleStatus.DUPLICATE
        assert duplicate.committed_event is None

    before_restart = _database_snapshot(engine)
    assert before_restart["counts"] == {"minutes": 315, "fiveMinute": 63, "daily": 3}
    assert len(before_restart["alerts"]) == 1
    assert before_restart["alerts"][0].message_text.endswith(DISCLAIMER)
    assert len(before_restart["evaluations"]) == 3
    assert len(before_restart["events"]) == 10
    assert before_restart["health"] == (
        ("000001.SZ", "LIVE", 20, 0, 2),
        ("000002.SZ", "STALE", 20, 2, 2),
        ("003043.SZ", "LIVE", 20, 0, 2),
    )
    assert before_restart["episodes"] == (
        ("000001.SZ", 6380, 0, "ACTIVE", None, market["bucketEnd"]),
        ("003043.SZ", 6380, 2, "ALERTED", "BUY_CORE_READY", market["bucketEnd"]),
    )

    engine.dispose()
    restarted_engine = create_sqlite_engine(database_path)
    request.addfinalizer(restarted_engine.dispose)
    try:
        upgrade_database(restarted_engine)
        factory = _unit_of_work_factory(
            restarted_engine,
            now=evaluated_at + timedelta(seconds=2),
        )
        restarted_publications: list[MonitorEvent] = []
        for plan in scenario_plans.values():
            restarted = asyncio.run(
                service(restarted_publications).run_intraday(
                    plan=plan,
                    bucket_end=bucket_end,
                    evaluated_at=evaluated_at,
                )
            )
            assert restarted.status is IntradayCycleStatus.DUPLICATE
            assert restarted.committed_event is None

        assert restarted_publications == []
        assert _database_snapshot(restarted_engine) == before_restart
    finally:
        restarted_engine.dispose()
