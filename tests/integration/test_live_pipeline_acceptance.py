"""Offline acceptance tests for the certified live production pipeline."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from tests.integration.current_activation_fixture import current_sample_plan, seed_current

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    ConditionOutcome,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.live_profiles import (
    create_index_certification,
    create_stock_certification,
    write_live_certification,
)
from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode, resolve_board_reference
from trade_plan_monitor.market_index.models import MarketIndexHealth, MarketIndexIssueCode
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import RuntimeResourceStatus, RuntimeServiceStatus
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    DASHBOARD_INDEX_CODES,
    RuntimeMarketIndexBatch,
)
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import (
    IntradayCycleStatus,
    OfficialCloseCycleStatus,
    RuntimeEvaluationService,
    RuntimeLifecycleService,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEvent, MonitorEventType
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.monitor_composition import create_monitor_composition

NOW = datetime(2026, 9, 8, 10, 0, 15, tzinfo=SHANGHAI)
INDEX_CUTOFF = datetime(2026, 9, 8, 10, 35, tzinfo=SHANGHAI)
ENDPOINT = "https://example.test"


class ControlledClock:
    """Advance a bounded number of scheduler sleeps, then wait for cancellation."""

    def __init__(self, current: datetime, *, released_sleeps: int = 0) -> None:
        self.current = current
        self.released_sleeps = released_sleeps
        self.sleep_calls: list[datetime] = []

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_calls.append(deadline)
        if len(self.sleep_calls) <= self.released_sleeps:
            self.current = max(self.current, deadline)
            await asyncio.sleep(0)
            return
        await asyncio.Event().wait()


class VirtualPace:
    """Honor production pacing in virtual monotonic time."""

    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += seconds
        await asyncio.sleep(0)


class OfflineSDK:
    """Replace only the remote SDK boundary with deterministic DataFrames."""

    def __init__(
        self,
        clock: ControlledClock,
        stock_symbols: tuple[str, ...],
        *,
        official_closes: dict[date, str] | None = None,
    ) -> None:
        self.clock = clock
        self.stock_symbols = stock_symbols
        self.official_closes = official_closes or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name: str):
        def request(**kwargs: object) -> pd.DataFrame:
            self.calls.append((name, dict(kwargs)))
            if name == "trade_cal":
                return self._calendar(kwargs)
            if name == "stk_limit":
                return self._limits(kwargs)
            if name == "daily":
                return self._stock_daily(kwargs)
            if name in {"rt_min", "rt_min_daily"}:
                return self._stock_minutes(name, kwargs)
            if name == "idx_mins":
                return self._historical_index_minutes(kwargs)
            if name == "rt_idx_min_daily":
                return self._index_minutes(kwargs)
            if name == "index_daily":
                return self._index_daily(kwargs)
            raise AssertionError(f"unexpected offline SDK endpoint: {name}")

        return request

    @staticmethod
    def _calendar(kwargs: dict[str, object]) -> pd.DataFrame:
        start = date.fromisoformat(str(kwargs["start_date"]))
        end = date.fromisoformat(str(kwargs["end_date"]))
        exchange = str(kwargs["exchange"])
        rows: list[dict[str, object]] = []
        previous = start - timedelta(days=1)
        while previous.weekday() > 4:
            previous -= timedelta(days=1)
        current = start
        while current <= end:
            rows.append(
                {
                    "exchange": exchange,
                    "cal_date": current.strftime("%Y%m%d"),
                    "is_open": int(current.weekday() < 5),
                    "pretrade_date": previous.strftime("%Y%m%d"),
                }
            )
            if current.weekday() < 5:
                previous = current
            current += timedelta(days=1)
        return pd.DataFrame(rows)

    def _limits(self, kwargs: dict[str, object]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "trade_date": str(kwargs["trade_date"]),
                    "up_limit": "75",
                    "down_limit": "55",
                }
                for symbol in self.stock_symbols
            ]
        )

    def _stock_daily(self, kwargs: dict[str, object]) -> pd.DataFrame:
        start = date.fromisoformat(str(kwargs["start_date"]))
        end = date.fromisoformat(str(kwargs["end_date"]))
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": current.strftime("%Y%m%d"),
                    "open": self.official_closes.get(current, "64.00"),
                    "high": self.official_closes.get(current, "64.10"),
                    "low": self.official_closes.get(current, "63.90"),
                    "close": self.official_closes.get(current, "64.05"),
                    "vol": "1000",
                    "amount": "64000",
                }
                for offset in range((end - start).days + 1)
                if (current := start + timedelta(days=offset)).weekday() < 5
            ]
        )

    def _stock_minutes(self, name: str, kwargs: dict[str, object]) -> pd.DataFrame:
        cutoff = self.clock.now().replace(second=0, microsecond=0)
        start = cutoff.replace(hour=9, minute=30)
        if name == "rt_min":
            source_minutes = (cutoff - timedelta(minutes=1),)
            symbols = tuple(str(kwargs["ts_code"]).split(","))
        else:
            source_minutes = tuple(
                start + timedelta(minutes=offset)
                for offset in range(int((cutoff - start).total_seconds() // 60))
            )
            symbols = (str(kwargs["ts_code"]),)
        return pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "freq": "1MIN",
                    "time": minute.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": "64.00",
                    "high": "64.10",
                    "low": "63.90",
                    "close": "64.05",
                    "vol": "1000",
                    "amount": "64000",
                }
                for symbol in symbols
                for minute in source_minutes
            ]
        )

    def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
        cutoff = self.clock.now().replace(second=0, microsecond=0)
        rows = []
        current = cutoff.replace(hour=9, minute=35)
        while current <= cutoff:
            rows.append(
                {
                    "ts_code": kwargs["ts_code"],
                    "freq": "5MIN",
                    "time": current.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                    "vol": "1000",
                    "amount": "10000",
                }
            )
            current += timedelta(minutes=5)
        return pd.DataFrame(rows)

    def _historical_index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
        cutoff_date = datetime.fromisoformat(str(kwargs["end_date"])).date()
        trade_day = cutoff_date - timedelta(days=1)
        while trade_day.weekday() > 4:
            trade_day -= timedelta(days=1)
        bucket_ends = tuple(
            datetime.combine(trade_day, datetime.min.time(), SHANGHAI).replace(hour=9, minute=35)
            + timedelta(minutes=5 * index)
            for index in range(24)
        ) + tuple(
            datetime.combine(trade_day, datetime.min.time(), SHANGHAI).replace(hour=13, minute=5)
            + timedelta(minutes=5 * index)
            for index in range(24)
        )
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_time": bar_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                    "vol": "1000",
                    "amount": "10000",
                }
                for bar_at in bucket_ends
            ]
        )

    def _index_daily(self, kwargs: dict[str, object]) -> pd.DataFrame:
        cutoff = self.clock.now().date()
        days = []
        current = cutoff - timedelta(days=1)
        while len(days) < 260:
            if current.weekday() < 5:
                days.append(current)
            current -= timedelta(days=1)
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": trade_date.strftime("%Y%m%d"),
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                    "vol": "1000",
                    "amount": "10000",
                }
                for trade_date in reversed(days)
            ]
        )


class DelayedIndexSDK(OfflineSDK):
    """Expose a just-completed index bar from the following minute onward."""

    def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
        frame = super()._index_minutes(kwargs)
        cutoff = self.clock.now().replace(second=0, microsecond=0)
        if cutoff.minute % 5:
            return frame
        return frame.loc[frame["time"] < cutoff.strftime("%Y-%m-%d %H:%M:%S")]


def _ready_stock_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
    )


def _write_configuration_and_evidence(
    root: Path,
    *,
    observed_at: datetime,
    include_index: bool,
) -> Path:
    config = root / "config" / "app.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f"tushare:\n  api_url: {ENDPOINT}\n  token: offline-test-token\n",
        encoding="utf-8",
    )
    certifications = root / "data" / "live-certification"
    write_live_certification(
        certifications / "tushare-stock-live.json",
        create_stock_certification(
            observed_at=observed_at,
            endpoint_url=ENDPOINT,
            capabilities=_ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START,
        ),
    )
    if include_index:
        capabilities = {
            code: (
                TushareMarketIndexCapabilityStatus.ERROR
                if code is MarketIndexCode.BSE_50
                else TushareMarketIndexCapabilityStatus.READY
            )
            for code in MarketIndexCode
        }
        write_live_certification(
            certifications / "tushare-board-index-live.json",
            create_index_certification(
                observed_at=observed_at,
                endpoint_url=ENDPOINT,
                capabilities=capabilities,
                source_time_label=TushareMarketIndexSourceTimeLabel.END,
            ),
        )
    return config


def _activate_plans(database_path: Path, clock: ControlledClock, plans: tuple[TradePlan, ...]):
    engine = create_sqlite_engine(database_path)
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    try:
        with SqlAlchemyUnitOfWork(sessions, clock=clock.now) as work:
            for plan in plans:
                work.plans.save_draft(plan, source_text="offline production acceptance")
                work.plans.activate(
                    plan,
                    expected_revision=0,
                    validation=validate_trade_plan(
                        plan,
                        available_market_evidence=ALL_MARKET_EVIDENCE,
                    ),
                )
            work.commit()
    finally:
        engine.dispose()


def _sample_plan() -> TradePlan:
    sample = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
    return load_plan_yaml(sample.read_text(encoding="utf-8"))


def _plan(
    *,
    plan_id: str,
    symbol: str,
    market: str,
    condition: dict[str, object],
    schema_version: int = 2,
) -> TradePlan:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "plan_id": plan_id,
        "version": schema_version,
        "symbol": symbol,
        "name": plan_id,
        "market": market,
        "metadata": {},
        "activation": {"mode": "MANUAL"},
        "position": {"max_qty": 100, "core_target_qty": 100},
        "levels": {
            "low_buy": {"low_fen": 6000, "high_fen": 6500},
            "pressure": {"low_fen": 6800, "high_fen": 7000},
            "risk_line_fen": 5800,
            "pressure_reference_fen": 6900,
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
        payload["reference_market"] = resolve_board_reference(symbol).binding.model_dump(
            mode="python"
        )
    return TradePlan.model_validate(payload)


def _work_factory(database_path: Path, clock: ControlledClock):
    engine = create_sqlite_engine(database_path)
    sessions = create_session_factory(engine)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

    return engine, factory


async def _wait_for_decision_head(database_path: Path, symbol: str, clock: ControlledClock):
    engine, work_factory = _work_factory(database_path, clock)
    try:
        for _ in range(300):
            with work_factory() as work:
                head = work.projections.get_decision_head(symbol)
            if head is not None:
                return head
            await asyncio.sleep(0.01)
    finally:
        engine.dispose()
    raise AssertionError("scheduled runtime did not persist a decision head")


def _index_condition_evidence(evidence: object):
    index_evidence = getattr(evidence, "index_evidence", None)
    if index_evidence is not None:
        yield index_evidence
    for child in getattr(evidence, "children", ()):
        yield from _index_condition_evidence(child)


@pytest.mark.parametrize(
    "malicious",
    (
        '{"threshold_ratio":"1e-999999999"}',
        '{ "threshold_ratio" : "1e-999999999" }',
    ),
)
def test_projection_validation_rejects_unbounded_canonical_decimal_expansion(
    malicious: str,
) -> None:
    from trade_plan_monitor.state.projections import _result_validation_json

    with pytest.raises(ValueError, match="outside its domain|expansion is too large"):
        _result_validation_json(malicious)
    assert _result_validation_json('{"threshold_ratio":1}') == '{"threshold_ratio":1}'


def test_market_index_persistence_reuses_an_older_canonical_content_revision(
    tmp_path: Path,
) -> None:
    engine, work_factory = _work_factory(tmp_path / "monitor.sqlite3", ControlledClock(NOW))
    upgrade_database(engine)
    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: (),
        unit_of_work_factory=work_factory,
        context_builder=lambda *_args: None,
        committed_event_publisher=lambda _event: None,
    )

    def batch(revision: int, observed_at: datetime) -> RuntimeMarketIndexBatch:
        snapshot = build_market_index_snapshot(
            index_code=MarketIndexCode.SHENZHEN_COMPONENT,
            decision_cutoff=INDEX_CUTOFF,
            requests=(),
            five_minute_bars=(),
            official_daily_bars=(),
            content_revision=revision,
            observed_at=observed_at,
            observed_no_later_than=observed_at,
        )
        return RuntimeMarketIndexBatch(
            decision_cutoff=INDEX_CUTOFF,
            snapshots_by_index={snapshot.index_code: snapshot},
        )

    try:
        first, first_events = service._persist_market_index_batch(
            batch(17, INDEX_CUTOFF + timedelta(minutes=1))
        )
        _, second_events = service._persist_market_index_batch(
            batch(18, INDEX_CUTOFF + timedelta(minutes=2))
        )
        reused, reused_events = service._persist_market_index_batch(
            batch(17, INDEX_CUTOFF + timedelta(minutes=3))
        )
        _, duplicate_events = service._persist_market_index_batch(
            batch(17, INDEX_CUTOFF + timedelta(minutes=3))
        )
        first_snapshot = first.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT]
        reused_snapshot = reused.snapshots_by_index[MarketIndexCode.SHENZHEN_COMPONENT]

        assert reused_snapshot.snapshot_hash == first_snapshot.snapshot_hash
        assert reused_snapshot.observed_at == first_snapshot.observed_at
        with work_factory() as work:
            head = work.projections.get_market_index_head(
                mapping_version=first_snapshot.mapping_version,
                index_code=first_snapshot.index_code,
                decision_cutoff=first_snapshot.decision_cutoff,
                request_set_hash=first_snapshot.request_set_hash,
            )
            events = work.events.replay_page_after(0).events
        assert head is not None
        assert head.snapshot.snapshot_hash == first_snapshot.snapshot_hash
        assert head.updated_at == INDEX_CUTOFF + timedelta(minutes=3)
        assert tuple(map(len, (first_events, second_events, reused_events))) == (1, 1, 1)
        assert duplicate_events == ()
        assert tuple(event.sequence for event in events) == (1, 2, 3)
    finally:
        engine.dispose()


@pytest.mark.parametrize("close_attempt", [None, 2, 3])
def test_production_pipeline_collects_dashboard_indexes_without_active_plans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    close_attempt: int | None,
) -> None:
    import trade_plan_monitor.runtime.production as production

    async def scenario() -> None:
        clock = ControlledClock(INDEX_CUTOFF + timedelta(seconds=12))
        database = tmp_path / "monitor.sqlite3"
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=True,
        )
        sdk = OfflineSDK(clock, ())
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine, work_factory = _work_factory(database, clock)
        upgrade_database(engine)
        published: list[MonitorEvent] = []
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data" / "live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=uuid4(),
            publisher=published.append,
        )
        try:
            after_sequence = 0
            if close_attempt is not None:
                clock.current = INDEX_CUTOFF.replace(hour=15, minute=20, second=12)
                original_minutes = sdk._index_minutes

                def unavailable_minutes(kwargs: dict[str, object]) -> pd.DataFrame:
                    if kwargs["ts_code"] == MarketIndexCode.SSE_COMPOSITE.value:
                        raise RuntimeError("index response unavailable")
                    return original_minutes(kwargs)

                with monkeypatch.context() as patch:
                    patch.setattr(sdk, "_index_minutes", unavailable_minutes)
                    await pipeline.run_deadline(
                        MarketDeadline(
                            kind=DeadlineKind.OFFICIAL_CLOSE,
                            trade_date=INDEX_CUTOFF.date(),
                            due_at=clock.now(),
                            close_attempt=1,
                        )
                    )
                assert (
                    pipeline.index_service.latest_snapshots()[MarketIndexCode.SSE_COMPOSITE].health
                    is MarketIndexHealth.BLOCKED
                )
                after_sequence = published[-1].sequence
                published.clear()
                clock.current = clock.current.replace(hour=14 + close_attempt, minute=0)
            result = await pipeline.run_deadline(
                MarketDeadline(
                    kind=(
                        DeadlineKind.REALTIME_MINUTE
                        if close_attempt is None
                        else DeadlineKind.OFFICIAL_CLOSE
                    ),
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF if close_attempt is None else None,
                    close_attempt=close_attempt,
                )
            )

            assert result == ()
            assert set(pipeline.index_service.latest_snapshots()) == set(ALWAYS_ON_INDEX_CODES)
            with work_factory() as work:
                snapshots = work.projections.list_latest_market_index_snapshots(
                    mapping_version="board-index-map-v1",
                    index_codes=DASHBOARD_INDEX_CODES,
                )
                events = work.events.replay_page_after(after_sequence).events
            if close_attempt is not None:
                recovered = next(
                    item.snapshot
                    for item in snapshots
                    if item.snapshot.index_code is MarketIndexCode.SSE_COMPOSITE
                )
                assert recovered.health is MarketIndexHealth.LIVE
                assert recovered.completed_bucket_at == INDEX_CUTOFF.replace(hour=15, minute=0)
            assert (
                tuple(snapshot.snapshot.index_code for snapshot in snapshots)
                == DASHBOARD_INDEX_CODES
            )
            assert tuple(event.event_type for event in events) == (
                MonitorEventType.MARKET_INDEX_UPDATED,
            ) * len(ALWAYS_ON_INDEX_CODES)
            assert {event.aggregate_id for event in events} == {
                code.value for code in ALWAYS_ON_INDEX_CODES
            }
            assert published == list(events)
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_production_pipeline_retries_a_late_index_bucket_once_on_the_next_minute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trade_plan_monitor.runtime.production as production

    async def scenario() -> None:
        clock = ControlledClock(INDEX_CUTOFF + timedelta(seconds=12))
        database = tmp_path / "monitor.sqlite3"
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=True,
        )
        sdk = DelayedIndexSDK(clock, ())
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine, work_factory = _work_factory(database, clock)
        upgrade_database(engine)
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data" / "live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=uuid4(),
            publisher=lambda _event: None,
        )
        try:
            await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF,
                )
            )
            assert (
                pipeline.index_service.latest_snapshots()[MarketIndexCode.STAR_50].health
                is MarketIndexHealth.STALE
            )
            calls_after_initial_attempt = len(sdk.calls)

            clock.current = INDEX_CUTOFF + timedelta(minutes=1, seconds=12)
            await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF + timedelta(minutes=1),
                )
            )
            assert len(sdk.calls) > calls_after_initial_attempt
            assert (
                pipeline.index_service.latest_snapshots()[MarketIndexCode.STAR_50].health
                is MarketIndexHealth.LIVE
            )

            calls_after_retry = len(sdk.calls)
            clock.current = INDEX_CUTOFF + timedelta(minutes=2, seconds=12)
            await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF + timedelta(minutes=2),
                )
            )
            assert len(sdk.calls) == calls_after_retry
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_optional_index_failure_does_not_change_stock_only_plan_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Schema v2 plan without index leaves keeps its stock decision when display data fails."""
    import trade_plan_monitor.runtime.production as production

    async def run_case(fail_index: bool) -> tuple[object, MarketIndexHealth]:
        case_root = tmp_path / ("index-failed" if fail_index else "index-live")
        case_root.mkdir()
        clock = ControlledClock(INDEX_CUTOFF.replace(hour=9, minute=0))
        raw = current_sample_plan().model_dump(mode="json")
        raw.update(plan_id="stock-only-current", symbol="300001.SZ")
        plan = UnifiedTradePlan.model_validate(raw)
        database = case_root / "monitor.sqlite3"
        seed_current(case_root, plan=plan, clock=clock)
        clock.current = INDEX_CUTOFF + timedelta(seconds=12)
        config = _write_configuration_and_evidence(
            case_root, observed_at=clock.now(), include_index=True
        )

        class OptionalIndexSDK(OfflineSDK):
            def __getattr__(self, name: str):
                request = super().__getattr__(name)

                def checked(**kwargs: object) -> pd.DataFrame:
                    if (
                        fail_index
                        and name == "rt_idx_min_daily"
                        and kwargs.get("ts_code") == MarketIndexCode.CHINEXT.value
                    ):
                        self.calls.append((name, dict(kwargs)))
                        raise RuntimeError("SIMULATED optional index failure")
                    return request(**kwargs)

                return checked

        sdk = OptionalIndexSDK(clock, (plan.symbol,))
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
        )
        engine, work_factory = _work_factory(database, clock)
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=case_root / "data/live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=uuid4(),
            publisher=lambda _event: None,
        )
        try:
            await pipeline.refresh_references(INDEX_CUTOFF.date())
            await pipeline.recover_startup(INDEX_CUTOFF.date())
            results = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF,
                )
            )
            assert len(results) == 1 and not results[0].duplicate
            decision = results[0].snapshot
            assert decision["plan_hash"] == plan_sha256(plan)
            assert decision["minute_target"] == INDEX_CUTOFF.isoformat()
            assert decision["data_blockers"] == []
            assert decision["signals"] == decision["risks"] == []
            return decision, pipeline.index_service.latest_snapshots()[
                MarketIndexCode.CHINEXT
            ].health
        finally:
            await controller.aclose()
            engine.dispose()

    async def scenario() -> None:
        healthy, healthy_index = await run_case(False)
        failed, failed_index = await run_case(True)
        assert healthy_index is MarketIndexHealth.LIVE
        assert failed_index is MarketIndexHealth.BLOCKED
        for field in (
            "plan_hash",
            "signals",
            "risks",
            "risk_action",
            "next_action",
            "minute_target",
            "minute_prefix",
            "five_minute_bars",
            "quote",
        ):
            assert failed[field] == healthy[field]

    asyncio.run(scenario())


def test_real_composition_starts_runs_a_timer_and_restores_its_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import func, select

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition
    from trade_plan_monitor.state.models import EvaluationResult, SymbolDecisionHead

    async def scenario() -> None:
        database = tmp_path / "monitor.sqlite3"
        parked = asyncio.Event()

        class TimerClock(ControlledClock):
            async def sleep_until(self, deadline):
                self.sleep_calls.append(deadline)
                if deadline <= NOW.replace(minute=5, second=12):
                    assert len(self.sleep_calls) <= 12, "scheduler did not reach 10:05 target"
                    self.current = max(self.current, deadline)
                    await asyncio.sleep(0)
                    return
                parked.set()
                await asyncio.Event().wait()

        clock = TimerClock(NOW.replace(hour=9, minute=0))
        plan = current_sample_plan()
        seed_current(tmp_path, plan=plan, clock=clock)
        # This fixture represents a restart of an already-running monitor.
        seeded_engine = create_sqlite_engine(database)
        try:
            with create_session_factory(seeded_engine).begin() as session:
                session.add(
                    RuntimeLiveness(
                        id=1,
                        schema_version=1,
                        revision=0,
                        last_alive_at=clock.now().isoformat(),
                    )
                )
        finally:
            seeded_engine.dispose()
        clock.current = NOW
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=NOW,
            include_index=False,
        )
        sdk = OfflineSDK(clock, (plan.symbol,))
        controllers = []

        def controller_factory(*, clock: ControlledClock, require_repository_binding=False):
            pace = VirtualPace()
            controller = create_live_tushare_request_controller(
                clock=clock,
                monotonic=pace.monotonic,
                pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )
            controllers.append(controller)
            return controller

        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
        monkeypatch.setattr(
            monitor_composition,
            "create_live_tushare_request_controller",
            controller_factory,
        )
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)

        first = create_monitor_composition(config_path=config, database_path=database)
        assert isinstance(first._runtime, RuntimeLifecycleService)
        observed = []
        original_run = first._runtime._run_deadline

        async def capture(deadline):
            observed.append(
                (deadline, first._runtime.runtime_generation, first._runtime._schedule_owner)
            )
            return await original_run(deadline)

        first._runtime._run_deadline = capture
        started = await first.start()
        assert started.status is RuntimeServiceStatus.RUNNING
        assert started.read_only is False
        assert started.delivery.status is RuntimeResourceStatus.READY

        try:
            before = await _wait_for_current_head(database, plan.symbol, clock)
            await asyncio.wait_for(parked.wait(), timeout=5)
        except AssertionError as error:
            raise AssertionError(f"runtime={first.health()} calls={sdk.calls!r}") from error
        assert clock.sleep_calls
        assert [
            deadline.due_at
            for deadline, _, _ in observed
            if deadline.kind is DeadlineKind.REALTIME_MINUTE
        ] == [NOW.replace(minute=minute, second=12) for minute in range(1, 6)]
        assert all(
            generation == started.runtime_generation and owner is first._runner_task
            for _, generation, owner in observed
        )
        assert first.health().status is RuntimeServiceStatus.RUNNING
        assert not first._runner_task.done()
        assert Counter(name for name, _ in sdk.calls)["rt_min"] == 5
        snapshot = json.loads(before)
        assert snapshot["minute_target"] == NOW.replace(minute=5, second=0).isoformat()
        assert snapshot["evaluated_at"] == NOW.replace(minute=5, second=12).isoformat()
        assert snapshot["plan_hash"] == plan_sha256(plan)
        assert snapshot["activation_revision"] == 1
        engine, work_factory = _work_factory(database, clock)
        try:
            with work_factory() as work:
                records = tuple(
                    work._session.scalars(
                        select(DailyRecord).where(DailyRecord.kind == "EVALUATION")
                    )
                )
                assert len(records) == 2
                assert {record.payload_json for record in records} == {before}
                for model in (EvaluationResult, SymbolDecisionHead):
                    assert work._session.scalar(select(func.count()).select_from(model)) == 0
        finally:
            engine.dispose()
        await first.stop()
        assert first.health().status is RuntimeServiceStatus.STOPPED

        restarted_clock = ControlledClock(clock.now(), released_sleeps=0)
        clock = restarted_clock
        second = create_monitor_composition(config_path=config, database_path=database)
        assert isinstance(second._runtime, RuntimeLifecycleService)
        restarted = await second.start()
        assert restarted.status is RuntimeServiceStatus.RUNNING
        assert restarted.delivery.status is RuntimeResourceStatus.READY
        after = await _wait_for_current_head(database, plan.symbol, restarted_clock)
        assert after == before
        for _ in range(20):
            if restarted_clock.sleep_calls:
                break
            await asyncio.sleep(0)
        assert restarted_clock.sleep_calls
        await second.stop()
        assert len(controllers) == 2

    asyncio.run(scenario())


def test_cross_day_official_risk_breach_restores_from_sqlite_dashboard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trade_plan_monitor.runtime.production as production

    async def scenario() -> None:
        target_date = NOW.date()
        clock = ControlledClock(NOW.replace(hour=9, minute=0))
        raw = current_sample_plan().model_dump(mode="json")
        from tests.unit.test_unified_plan_domain import unified_payload

        raw["monitoring"] = unified_payload()["monitoring"]
        raw["ordinary_rules"] = []
        raw["alert_rules"] = [
            {
                "kind": "RISK_ALERT",
                "rule_id": "official-close-risk",
                "condition": {
                    "type": "DAILY_PRICE_COMPARE",
                    "field": "close",
                    "offset": 0,
                    "comparator": "LT",
                    "reference": {
                        "mode": "FIXED",
                        "value": "6200",
                        "unit": "FEN",
                        "as_of": str(target_date),
                        "source": "Synthetic reviewed official close threshold",
                    },
                },
                "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
            }
        ]
        plan = UnifiedTradePlan.model_validate(raw)
        database = tmp_path / "monitor.sqlite3"
        seed_current(tmp_path, plan=plan, clock=clock)
        clock.current = NOW + timedelta(days=1)
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=False,
        )
        from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK

        sdk = CurrentCloseSDK(
            clock,
            (plan.symbol,),
            official_closes={target_date: "55.00"},
        )
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine, work_factory = _work_factory(database, clock)
        generation = uuid4()
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data" / "live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=generation,
            publisher=lambda _event: None,
        )
        try:
            await pipeline.refresh_references(target_date)
            result = await pipeline.daily_evaluations.run_target(
                plan=plan, official_trade_date=target_date, evaluated_at=clock.now()
            )
            assert not result.duplicate
            snapshot = result.snapshot
            assert snapshot["official_trade_date"] == str(target_date)
            assert snapshot["evaluated_at"] == clock.now().isoformat()
            assert snapshot["daily_evidence"]["bars"][-1]["close"] == "5500"
            assert snapshot["alerts"][0]["outcome"] == "SATISFIED"
            assert snapshot["signals"] == snapshot["risks"] == []
            assert len(result.event_ids) == 1
            # Read through a fresh lifecycle/database connection after the source owner closes.
            from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

            reader = PersistentPlanWebLifecycle(database_path=database, clock=clock.now)
            await reader.start()
            try:
                view = await reader.read_daily(symbol=plan.symbol, trade_date=None)
            finally:
                await reader.stop()
            assert view.status == "CURRENT"
            assert view.snapshot.plan_hash == plan_sha256(plan)
            assert view.snapshot.official_trade_date == target_date
            assert view.snapshot.alerts[0].outcome == "SATISFIED"
            with work_factory() as work:
                from trade_plan_monitor.state.models import AlertEvent

                event = work._session.get(AlertEvent, result.event_ids[0])
                payload = json.loads(event.payload_json)
                assert payload["signal_type"] == "REMINDER"
                assert payload["alert_kind"] == "RISK_ALERT"
                assert payload["quantity"] is None
                assert payload["simulated_qty"] == 0
                assert payload["confirmed_trade_date"] == str(target_date)
                assert payload["trading_date"] == str(clock.now().date())
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "activation",
    (
        {
            "mode": "DATE_RANGE",
            "start_date": NOW.date() + timedelta(days=1),
            "end_date": NOW.date() + timedelta(days=2),
        },
        {
            "mode": "DATE_RANGE",
            "start_date": NOW.date() - timedelta(days=8),
            "end_date": NOW.date() - timedelta(days=7),
        },
        {
            "mode": "TRADING_DAY",
            "trading_day": NOW.date() - timedelta(days=7),
        },
    ),
    ids=("before-start", "after-end", "trading-day-mismatch"),
)
def test_production_pipeline_never_evaluates_or_alerts_outside_plan_validity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    activation: dict[str, object],
) -> None:
    import trade_plan_monitor.runtime.production as production

    async def scenario() -> None:
        clock = ControlledClock(NOW)
        database = tmp_path / "monitor.sqlite3"
        payload = current_sample_plan().model_dump(mode="python")
        payload["activation"] = activation
        payload["ordinary_rules"][0]["condition"]["price_fen"] = 6500
        plan = UnifiedTradePlan.model_validate(payload)
        runtime_time = clock.current
        if activation["mode"] == "TRADING_DAY":
            activation_date = activation["trading_day"]
        elif activation["start_date"] < NOW.date():
            activation_date = activation["end_date"]
        else:
            activation_date = NOW.date()
        assert isinstance(activation_date, date)
        clock.current = datetime.combine(activation_date, runtime_time.timetz())
        seed_current(tmp_path, plan=plan, clock=clock)
        clock.current = runtime_time
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=False,
        )
        sdk = OfflineSDK(clock, (plan.symbol,))
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine, work_factory = _work_factory(database, clock)
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data" / "live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=uuid4(),
            publisher=lambda _event: None,
        )
        try:
            assert pipeline.active_plans() == ()
            await pipeline.refresh_references(NOW.date())
            await pipeline.recover_startup(NOW.date())
            results = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0, microsecond=0),
                )
            )
            assert results == ()
            clock.current = NOW.replace(hour=17, minute=0)
            official_results = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.OFFICIAL_CLOSE,
                    trade_date=NOW.date(),
                    due_at=NOW.replace(hour=17, minute=0),
                    close_attempt=2,
                )
            )
            assert official_results == ()
            assert Counter(name for name, _ in sdk.calls)["rt_min"] == 0
            assert Counter(name for name, _ in sdk.calls)["daily"] == 0
            with work_factory() as work:
                assert work.plans.get_active(plan.symbol) is not None
                assert work.projections.get_decision_head(plan.symbol) is None
                assert work.daily.get("evaluation-head-" + plan.symbol) is None
                assert work.daily.list(symbol=plan.symbol, kind="EVALUATION") == ()
                alerts, total = work.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=None,
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=100,
                )
            assert alerts == ()
            assert total == 0
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "recovery_mode",
    ("success", "official_missing", "index_error", "revision_conflict"),
)
def test_frozen_service_batches_persisted_pending_closes_by_date_and_shared_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_mode: str,
) -> None:
    import trade_plan_monitor.runtime.production as production

    async def scenario() -> None:
        target_date = INDEX_CUTOFF.date()
        startup_date = target_date + timedelta(days=1)
        clock = ControlledClock(INDEX_CUTOFF.replace(hour=9, minute=0))
        plans = (
            _plan(
                plan_id="pending-one",
                symbol="000001.SZ",
                market="SZSE",
                condition={
                    "type": "INDEX_CLOSE_GTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 2,
                },
            ),
            _plan(
                plan_id="pending-two",
                symbol="002001.SZ",
                market="SZSE",
                condition={
                    "type": "INDEX_RETURN_GTE",
                    "index_role": "BOARD_REFERENCE",
                    "window": "OFFICIAL_OPEN_DAYS",
                    "window_size": 1,
                    "threshold_ratio": Decimal("-1"),
                },
            ),
            _plan(
                plan_id="pending-other-index",
                symbol="600000.SH",
                market="SSE",
                condition={
                    "type": "INDEX_CLOSE_GTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 2,
                },
            ),
        )
        database = tmp_path / "monitor.sqlite3"
        _activate_plans(database, clock, plans)
        clock.current = INDEX_CUTOFF.replace(hour=16)
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=True,
        )
        engine, work_factory = _work_factory(database, clock)
        if recovery_mode == "revision_conflict":
            monkeypatch.setattr(
                production.TushareMarketIndexProvider,
                "_content_revision",
                staticmethod(lambda _minute, _daily: 17),
            )

        class PendingSDK(OfflineSDK):
            def __init__(
                self,
                *,
                available: bool,
                failed_index: MarketIndexCode | None = None,
                mutate_index: MarketIndexCode | None = None,
            ) -> None:
                super().__init__(clock, tuple(plan.symbol for plan in plans))
                self.available = available
                self.failed_index = failed_index
                self.mutate_index = mutate_index

            def __getattr__(self, name: str):
                request = super().__getattr__(name)

                def checked(**kwargs: object) -> pd.DataFrame:
                    assert engine.pool.checkedout() == 0
                    if (
                        self.failed_index is not None
                        and name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
                        and kwargs.get("ts_code") == self.failed_index.value
                    ):
                        self.calls.append((name, dict(kwargs)))
                        raise RuntimeError("offline index failure")
                    return request(**kwargs)

                return checked

            def _stock_daily(self, kwargs: dict[str, object]) -> pd.DataFrame:
                frame = super()._stock_daily(kwargs)
                if self.available:
                    return frame
                return frame.loc[frame["trade_date"] != target_date.strftime("%Y%m%d")].reset_index(
                    drop=True
                )

            def _index_daily(self, kwargs: dict[str, object]) -> pd.DataFrame:
                days = []
                current = target_date
                while len(days) < 260:
                    if current.weekday() < 5:
                        days.append(current)
                    current -= timedelta(days=1)
                frame = pd.DataFrame(
                    [
                        {
                            "ts_code": kwargs["ts_code"],
                            "trade_date": trade_date.strftime("%Y%m%d"),
                            "open": "100",
                            "high": "100",
                            "low": "100",
                            "close": "100",
                            "vol": "1000",
                            "amount": "10000",
                        }
                        for trade_date in reversed(days)
                    ]
                )
                if kwargs["ts_code"] == self.mutate_index:
                    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = "101"
                return frame

            def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
                minutes = []
                current = datetime.combine(target_date, NOW.timetz()).replace(
                    hour=9, minute=35, second=0
                )
                while current.time() <= datetime.min.replace(hour=11, minute=30).time():
                    minutes.append(current)
                    current += timedelta(minutes=5)
                current = current.replace(hour=13, minute=5)
                while current.time() <= datetime.min.replace(hour=15).time():
                    minutes.append(current)
                    current += timedelta(minutes=5)
                return pd.DataFrame(
                    [
                        {
                            "ts_code": kwargs["ts_code"],
                            "freq": "5MIN",
                            "time": minute.strftime("%Y-%m-%d %H:%M:%S"),
                            "open": "100",
                            "high": "100",
                            "low": "100",
                            "close": "100",
                            "vol": "1000",
                            "amount": "10000",
                        }
                        for minute in minutes
                    ]
                )

        def pipeline_with(sdk: PendingSDK, controller):
            monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
            return ProductionMonitorPipeline(
                configuration=load_application_config(config).tushare,
                certification_directory=tmp_path / "data" / "live-certification",
                stock_certification=create_stock_certification(
                    observed_at=INDEX_CUTOFF.replace(hour=16),
                    endpoint_url=ENDPOINT,
                    capabilities=_ready_stock_capabilities(),
                    source_time_label=SourceTimeLabel.START,
                ),
                clock=clock,
                request_controller=controller,
                unit_of_work_factory=work_factory,
                runtime_generation=uuid4(),
                publisher=lambda _event: None,
            )

        seed_pace = VirtualPace()
        seed_controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=seed_pace.monotonic,
            pace_sleep=seed_pace.sleep,
        )
        seed_sdk = PendingSDK(available=False)
        seed = pipeline_with(seed_sdk, seed_controller)
        try:
            await seed.refresh_references(target_date)
            assert seed.active_plans() == ()
            await _warm_frozen_references(seed, plans, target_date, work_factory)
            pending = await seed.evaluations.run_official_close_batch(
                plans=plans,
                trade_date=target_date,
                evaluated_at=clock.now(),
                close_attempt=1,
            )
            assert [item.status for item in pending] == [
                OfficialCloseCycleStatus.CLOSE_PENDING,
                OfficialCloseCycleStatus.CLOSE_PENDING,
                OfficialCloseCycleStatus.CLOSE_PENDING,
            ]
            assert all(
                seed.evaluations.pending_close_date(plan.symbol) == target_date for plan in plans
            )
            seed_snapshot_hashes = {
                index_code: snapshot.snapshot_hash
                for index_code, snapshot in seed.index_service.latest_snapshots().items()
            }
            with work_factory() as work:
                assert all(
                    work.projections.get_market_index_snapshot(snapshot_hash) is not None
                    for snapshot_hash in seed_snapshot_hashes.values()
                )
        finally:
            await seed_controller.aclose()

        clock.current = datetime.combine(startup_date, NOW.timetz())
        recovery_pace = VirtualPace()
        recovery_controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=recovery_pace.monotonic,
            pace_sleep=recovery_pace.sleep,
        )
        recovery_sdk = PendingSDK(
            available=recovery_mode != "official_missing",
            failed_index=(
                MarketIndexCode.SHENZHEN_COMPONENT if recovery_mode == "index_error" else None
            ),
            mutate_index=(
                MarketIndexCode.SHENZHEN_COMPONENT if recovery_mode == "revision_conflict" else None
            ),
        )
        recovery = pipeline_with(recovery_sdk, recovery_controller)
        try:
            await recovery.refresh_references(startup_date)
            assert recovery.active_plans() == ()
            await recovery.recover_startup(startup_date)
            assert all(
                recovery.evaluations.pending_close_date(p.symbol) == target_date for p in plans
            )
            await _warm_frozen_references(recovery, plans, target_date, work_factory)

            async def frozen_batch():
                results = await recovery.evaluations.run_official_close_batch(
                    plans=plans, trade_date=target_date, evaluated_at=clock.now(), close_attempt=1
                )
                if any(
                    item.status
                    not in {OfficialCloseCycleStatus.COMMITTED, OfficialCloseCycleStatus.DUPLICATE}
                    for item in results
                ):
                    raise RuntimeError("frozen startup recovery failed")

            if recovery_mode in {"success", "index_error"}:
                await frozen_batch()
            elif recovery_mode == "official_missing":
                with pytest.raises(RuntimeError, match="frozen startup recovery failed"):
                    await frozen_batch()
            else:
                from trade_plan_monitor.state.projections import ProjectionIdentityConflictError

                with pytest.raises(ProjectionIdentityConflictError):
                    await frozen_batch()

            index_calls = [
                (name, str(kwargs["ts_code"]))
                for name, kwargs in recovery_sdk.calls
                if name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
            ]
            assert index_calls
            assert all(count == 1 for count in Counter(index_calls).values())
            assert {code for _name, code in index_calls} == {
                index_code.value for index_code in ALWAYS_ON_INDEX_CODES
            }
            remaining = tuple(
                recovery.evaluations.pending_close_date(plan.symbol) for plan in plans
            )
            if recovery_mode in {"success", "index_error"}:
                assert remaining == (None, None, None)
                with work_factory() as work:
                    assert all(
                        work.projections.get_decision_head(plan.symbol) is not None
                        for plan in plans
                    )
                    if recovery_mode == "index_error":
                        shenzhen = work.projections.get_decision_head(plans[0].symbol)
                        shanghai = work.projections.get_decision_head(plans[2].symbol)
                        assert shenzhen is not None and shanghai is not None
                        assert shenzhen.result.snapshot.reference_market.health is (
                            MarketIndexHealth.BLOCKED
                        )
                        assert shanghai.result.snapshot.reference_market.health is (
                            MarketIndexHealth.LIVE
                        )
                        assert (
                            shanghai.result.snapshot.reference_market.snapshot_hash
                            == seed_snapshot_hashes[MarketIndexCode.SSE_COMPOSITE]
                        )
                    else:
                        for plan in plans:
                            decision = work.projections.get_decision_head(plan.symbol)
                            assert decision is not None
                            assert plan.reference_market is not None
                            assert (
                                decision.result.snapshot.reference_market.snapshot_hash
                                == seed_snapshot_hashes[plan.reference_market.index_code]
                            )
            else:
                assert remaining == (target_date, target_date, target_date)
        finally:
            await recovery_controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalidated_by", ("expiry", "tamper"))
def test_production_pipeline_shares_index_snapshots_and_fails_closed_after_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalidated_by: str,
) -> None:
    from sqlalchemy import delete, func, select

    import trade_plan_monitor.runtime.production as production
    from trade_plan_monitor.market_data.models import MinuteBar
    from trade_plan_monitor.state.models import (
        EvaluationResult,
        LatestQuote,
        MarketIndexSnapshot,
        SymbolDecisionHead,
    )

    async def scenario() -> None:
        clock = ControlledClock(INDEX_CUTOFF.replace(hour=9, minute=0))
        same_index_one = _plan(
            plan_id="same-index-one",
            symbol="000001.SZ",
            market="SZSE",
            condition={
                "type": "INDEX_CLOSE_GTE_MA",
                "index_role": "BOARD_REFERENCE",
                "period": 2,
            },
        )
        same_index_two = _plan(
            plan_id="same-index-two",
            symbol="002001.SZ",
            market="SZSE",
            condition={
                "type": "INDEX_RETURN_GTE",
                "index_role": "BOARD_REFERENCE",
                "window": "FIVE_MINUTE_BUCKETS",
                "window_size": 1,
                "threshold_ratio": Decimal("-1"),
            },
        )
        bse = _plan(
            plan_id="bse-blocked",
            symbol="830001.BJ",
            market="BSE",
            condition={
                "type": "ALL",
                "conditions": [
                    {"type": "NON_DECREASING_CLOSE"},
                    {
                        "type": "INDEX_RETURN_GTE",
                        "index_role": "BOARD_REFERENCE",
                        "window": "FIVE_MINUTE_BUCKETS",
                        "window_size": 1,
                        "threshold_ratio": Decimal("-1"),
                    },
                ],
            },
        )
        other_index = _plan(
            plan_id="other-index",
            symbol="600000.SH",
            market="SSE",
            condition={
                "type": "INDEX_RETURN_GTE",
                "index_role": "BOARD_REFERENCE",
                "window": "FIVE_MINUTE_BUCKETS",
                "window_size": 1,
                "threshold_ratio": Decimal("-1"),
            },
        )
        schema_one = _plan(
            plan_id="schema-one",
            symbol="300001.SZ",
            market="SZSE",
            condition={"type": "NON_DECREASING_CLOSE"},
            schema_version=1,
        )
        plans = (same_index_one, same_index_two, bse, other_index, schema_one)
        database = tmp_path / "monitor.sqlite3"
        _activate_plans(database, clock, plans)
        current = seed_current(tmp_path, clock=clock)
        clock.current = INDEX_CUTOFF + timedelta(seconds=12)
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=clock.now(),
            include_index=True,
        )
        sdk = OfflineSDK(clock, (*tuple(plan.symbol for plan in plans), current.symbol))
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        pace = VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine = create_sqlite_engine(database)
        sessions = create_session_factory(engine)

        def work_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

        # Persist only historical input: startup now repairs at most one symbol.
        symbols = tuple(plan.symbol for plan in plans)
        prefix = tuple(
            INDEX_CUTOFF.replace(hour=9, minute=31) + timedelta(minutes=offset)
            for offset in range(64)
        )
        with work_factory() as work:
            assert all(work.history.get_latest_quote(symbol) is None for symbol in symbols)
            work.history.upsert_minutes(
                tuple(
                    MinuteBar(
                        symbol=symbol,
                        bar_end=end,
                        open_fen=6400,
                        high_fen=6410,
                        low_fen=6390,
                        close_fen=6405,
                        volume_shares=1000,
                        amount_yuan=Decimal("64000"),
                        received_at=clock.now(),
                    )
                    for symbol in symbols
                    for end in prefix
                )
            )
            # The repository derives replaceable quotes; this fixture seeds minutes only.
            work._session.execute(delete(LatestQuote).where(LatestQuote.symbol.in_(symbols)))
            work.commit()
        with work_factory() as work:
            persisted = []
            for symbol in symbols:
                bars = work.history.list_minutes(symbol, start=prefix[0], end=INDEX_CUTOFF)
                assert tuple(bar.bar_end for bar in bars) == prefix
                assert work.history.get_latest_quote(symbol) is None
                persisted.extend(bars)
            assert len(persisted) == 320
            for model in (EvaluationResult, SymbolDecisionHead, MarketIndexSnapshot):
                assert work._session.scalar(select(func.count()).select_from(model)) == 0

        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data" / "live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=ENDPOINT,
                capabilities=_ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work_factory,
            runtime_generation=uuid4(),
            publisher=lambda _event: None,
        )
        try:
            profile = pipeline.index_provider.profile
            assert profile.source_time_label is TushareMarketIndexSourceTimeLabel.END
            assert profile.capabilities[MarketIndexCode.BSE_50] is (
                TushareMarketIndexCapabilityStatus.ERROR
            )
            assert sum(
                status is TushareMarketIndexCapabilityStatus.READY
                for status in profile.capabilities.values()
            ) == len(ALWAYS_ON_INDEX_CODES)
            assert controller.executor_workers == 1
            assert controller.max_concurrency == 1

            await pipeline.refresh_references(INDEX_CUTOFF.date())
            await pipeline.recover_startup(INDEX_CUTOFF.date())
            assert Counter(name for name, _ in sdk.calls)["rt_min_daily"] <= 1
            current_results = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=INDEX_CUTOFF.date(),
                    due_at=clock.now(),
                    bar_end=INDEX_CUTOFF,
                )
            )
            assert len(current_results) == 1
            assert current_results[0].snapshot["plan_hash"] == plan_sha256(current)
            assert current_results[0].snapshot["data_blockers"] == []
            assert pipeline.active_plans() == (current,)
            await _warm_frozen_references(pipeline, plans, INDEX_CUTOFF.date(), work_factory)
            from trade_plan_monitor.market_index.requirements import plan_index_fact_requests
            from trade_plan_monitor.market_index.snapshots import _blocked_snapshot

            frozen_snapshots = dict(pipeline.index_service.latest_snapshots())
            frozen_snapshots[MarketIndexCode.BSE_50] = _blocked_snapshot(
                index_code=MarketIndexCode.BSE_50,
                decision_cutoff=INDEX_CUTOFF,
                requests=plan_index_fact_requests(bse),
                issue=MarketIndexIssueCode.PROVIDER_UNAVAILABLE,
                observed_at=clock.now(),
            )
            frozen_batch, _events = pipeline.evaluations._persist_market_index_batch(
                RuntimeMarketIndexBatch(
                    decision_cutoff=INDEX_CUTOFF, snapshots_by_index=frozen_snapshots
                )
            )
            # Explicit typed historical inputs exercise the frozen predicate/evidence oracle.
            fetched = pipeline.provider.realtime_minutes(tuple(plan.symbol for plan in plans))
            results = await pipeline.evaluations.run_intraday_batch_from_minutes(
                plans=plans,
                bucket_end=INDEX_CUTOFF,
                evaluated_at=clock.now(),
                minutes_by_symbol={
                    p.symbol: tuple(m for m in fetched if m.symbol == p.symbol) for p in plans
                },
                market_index_batch=frozen_batch,
            )
            assert all(result.status is IntradayCycleStatus.COMMITTED for result in results)

            decisions = {
                result.evaluation_result.snapshot.symbol: result.evaluation_result
                for result in results
                if result.evaluation_result is not None
            }
            assert len(results) == len(decisions) == 5
            assert set(decisions) == set(symbols)
            with work_factory() as work:
                for symbol in symbols:
                    bars = work.history.list_minutes(
                        symbol,
                        start=prefix[0],
                        end=INDEX_CUTOFF,
                    )
                    assert tuple(bar.bar_end for bar in bars) == (*prefix, INDEX_CUTOFF)
                    head = work.projections.get_decision_head(symbol)
                    assert head is not None and head.activation_revision == 1
                    assert head.result == decisions[symbol]
            first_snapshot = decisions[same_index_one.symbol].snapshot.reference_market
            second_snapshot = decisions[same_index_two.symbol].snapshot.reference_market
            assert first_snapshot is not None and second_snapshot is not None
            assert first_snapshot.snapshot_hash == second_snapshot.snapshot_hash
            assert first_snapshot.health is MarketIndexHealth.LIVE
            with work_factory() as work:
                for mismatched in (
                    None,
                    pipeline.index_service.latest_snapshots()[MarketIndexCode.SSE_COMPOSITE],
                ):
                    with pytest.raises(
                        ValueError,
                        match="reference-market snapshots must agree|immutable snapshot",
                    ):
                        RuntimeEvaluationService._persist_projection_dependencies(
                            work,
                            decisions[same_index_one.symbol],
                            plan=same_index_one,
                            reference_market_snapshot=mismatched,
                            health_snapshot=None,
                            activation_revision=1,
                            runtime_generation=uuid4(),
                        )
            assert decisions[other_index.symbol].snapshot.reference_market.health is (
                MarketIndexHealth.LIVE
            )
            assert decisions[schema_one.symbol].snapshot.reference_market is None

            bse_snapshot = decisions[bse.symbol].snapshot.reference_market
            assert bse_snapshot is not None
            assert bse_snapshot.health is MarketIndexHealth.BLOCKED
            assert frozen_batch.snapshots_by_index[MarketIndexCode.BSE_50].issues == (
                MarketIndexIssueCode.PROVIDER_UNAVAILABLE,
            )
            evidence_roots = decisions[bse.symbol].snapshot.condition_evidence
            index_evidence = tuple(
                item for root in evidence_roots for item in _index_condition_evidence(root)
            )
            assert len(index_evidence) == 1
            assert index_evidence[0].plan_path == "entry.condition.conditions[1]"
            assert index_evidence[0].outcome is ConditionOutcome.MISSING_INPUT
            entry_evidence = next(
                root
                for root in evidence_roots
                if isinstance(root, ConditionEvidence)
                and any(child.index_evidence is not None for child in root.children)
            )
            assert entry_evidence.children[0].index_evidence is None

            index_calls = [
                (name, str(kwargs["ts_code"]))
                for name, kwargs in sdk.calls
                if name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
            ]
            assert Counter(index_calls) == Counter(
                {
                    (name, code.value): 1
                    for name in ("idx_mins", "rt_idx_min_daily", "index_daily")
                    for code in ALWAYS_ON_INDEX_CODES
                }
            )
            assert all(code != MarketIndexCode.BSE_50.value for _, code in index_calls)

            calls_before_invalidation = tuple(index_calls)
            certification = tmp_path / "data/live-certification/tushare-board-index-live.json"
            if invalidated_by == "expiry":
                clock.current += timedelta(days=8)
            else:
                document = json.loads(certification.read_text(encoding="utf-8"))
                document["evidenceHash"] = "0" * 64
                certification.write_text(json.dumps(document), encoding="utf-8")
                clock.current += timedelta(minutes=5)
            invalidated = await pipeline.index_service.prepare(
                plans=plans,
                decision_cutoff=clock.now().replace(second=0, microsecond=0),
                observed_no_later_than=clock.now(),
            )
            assert all(
                snapshot.health is MarketIndexHealth.BLOCKED
                for snapshot in invalidated.snapshots_by_index.values()
            )
            assert [
                (name, str(kwargs["ts_code"]))
                for name, kwargs in sdk.calls
                if name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
            ] == list(calls_before_invalidation)
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


async def _wait_for_current_head(database, symbol, clock):
    from sqlalchemy import select

    engine = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(engine)
        for _ in range(500):
            with sessions() as session:
                head = session.get(DailyRecord, "evaluation-head-" + symbol)
                if head is not None:
                    snapshot = json.loads(head.payload_json)
                    if snapshot.get("minute_target") == clock.now().replace(second=0).isoformat():
                        immutable = tuple(
                            session.scalars(
                                select(DailyRecord).where(DailyRecord.kind == "EVALUATION")
                            )
                        )
                        assert any(
                            row.id != head.id and row.payload_json == head.payload_json
                            for row in immutable
                        )
                        return head.payload_json
            await asyncio.sleep(0.01)
        raise AssertionError("scheduled current runtime did not persist the target head")
    finally:
        engine.dispose()


async def _warm_frozen_references(pipeline, plans, target_date, work_factory):
    """Acquire explicit history for retained service tests, never current plan admission."""
    for exchange in sorted({plan.market for plan in plans}):
        days = pipeline.provider.trading_calendar_for_exchange(
            exchange, target_date - timedelta(days=366), target_date
        )
        with work_factory() as work:
            work.references.upsert_trading_days(days)
            work.commit()
    for plan in plans:
        bars = pipeline.provider.daily_bars(
            plan.symbol, target_date - timedelta(days=366), target_date - timedelta(days=1)
        )
        assert bars
        with work_factory() as work:
            work.history.upsert_daily_bars(bars)
            work.commit()


@pytest.mark.parametrize("official_close, expected_alerts", (("55.00", 1), ("70.00", 0)))
def test_current_daily_reminder_startup_and_restart_keep_source_binding(
    tmp_path,
    monkeypatch,
    official_close,
    expected_alerts,
):
    """The real installed owner evaluates a reviewed prior close without inventory authority."""
    from sqlalchemy import func, select
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
    from tests.unit.test_unified_plan_domain import unified_payload

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition
    from trade_plan_monitor.state.models import AlertEvent, EvaluationResult, SymbolDecisionHead

    async def scenario():
        clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0), released_sleeps=0)
        raw = current_sample_plan().model_dump(mode="json")
        raw["ordinary_rules"] = []
        raw["monitoring"] = unified_payload()["monitoring"]
        raw["alert_rules"] = [
            {
                "kind": "RISK_ALERT",
                "rule_id": "startup-source-reminder",
                "condition": {
                    "type": "DAILY_PRICE_COMPARE",
                    "field": "close",
                    "offset": 0,
                    "comparator": "LT",
                    "reference": {
                        "mode": "FIXED",
                        "value": "6200",
                        "unit": "FEN",
                        "as_of": str(NOW.date()),
                        "source": "Synthetic reviewed official close threshold",
                    },
                },
                "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
            }
        ]
        plan = UnifiedTradePlan.model_validate(raw)
        seed_current(tmp_path, plan=plan, clock=clock)
        database = tmp_path / "monitor.sqlite3"
        engine = create_sqlite_engine(database)
        sessions = create_session_factory(engine)
        with sessions.begin() as session:
            session.add(
                RuntimeLiveness(
                    id=1, schema_version=1, revision=0, last_alive_at=clock.now().isoformat()
                )
            )
        clock.current = NOW + timedelta(days=1)
        config = _write_configuration_and_evidence(
            tmp_path, observed_at=clock.now(), include_index=False
        )
        sdk = CurrentCloseSDK(clock, (plan.symbol,), official_closes={NOW.date(): official_close})
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return create_live_tushare_request_controller(
                clock=clock,
                monotonic=pace.monotonic,
                pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        monkeypatch.setattr(
            monitor_composition, "create_live_tushare_request_controller", controller_factory
        )

        def committed():
            with sessions() as session:
                head = session.get(DailyRecord, "evaluation-head-" + plan.symbol)
                assert head is not None
                rows = tuple(
                    (row.id, row.revision, row.payload_json)
                    for row in session.scalars(
                        select(DailyRecord)
                        .where(DailyRecord.kind == "EVALUATION")
                        .order_by(DailyRecord.id)
                    )
                )
                assert len(rows) == 2
                assert {row[2] for row in rows} == {head.payload_json}
                assert (
                    session.scalar(select(func.count()).select_from(AlertEvent)) == expected_alerts
                )
                for model in (EvaluationResult, SymbolDecisionHead):
                    assert session.scalar(select(func.count()).select_from(model)) == 0
                return rows, json.loads(head.payload_json)

        first = create_monitor_composition(config_path=config, database_path=database)
        try:
            assert (await first.start()).status is RuntimeServiceStatus.RUNNING
            before, snapshot = committed()
            assert snapshot["plan_hash"] == plan_sha256(plan)
            assert snapshot["activation_revision"] == 1
            assert snapshot["official_trade_date"] == str(NOW.date())
            assert snapshot["daily_evidence"]["bars"][-1]["close"] == str(
                int(Decimal(official_close) * 100)
            )
            assert snapshot["alerts"][0]["outcome"] == (
                "SATISFIED" if expected_alerts else "UNSATISFIED"
            )
            assert snapshot["minute_target"] is None
            assert snapshot["signals"] == snapshot["risks"] == []
            assert "daily" in [name for name, _kwargs in sdk.calls]
            assert "adj_factor" in [name for name, _kwargs in sdk.calls]
            assert "rt_min" not in [name for name, _kwargs in sdk.calls]
        finally:
            await first.stop()
        second = create_monitor_composition(config_path=config, database_path=database)
        try:
            assert (await second.start()).status is RuntimeServiceStatus.RUNNING
            after, restored = committed()
            assert after == before and restored == snapshot
        finally:
            await second.stop()
            engine.dispose()

    asyncio.run(scenario())
