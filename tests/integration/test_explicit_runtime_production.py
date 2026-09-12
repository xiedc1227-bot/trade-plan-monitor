from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.live_profiles import (
    create_stock_certification,
    write_live_certification,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import (
    MinuteBar,
    ProviderCapabilities,
    ProviderCapabilityStatus,
    TradingDay,
)
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeCycleStatus,
    ExplicitRuntimeEvaluationService,
    StaleExplicitDecisionError,
)
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import (
    ProductionMonitorPipeline,
    create_explicit_runtime_evaluation_service,
)
from trade_plan_monitor.runtime.request_control import (
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEventType
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
)
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_composition import create_monitor_composition

SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
TARGET_DATE = TARGET.date()
PREPARED_AT = TARGET - timedelta(minutes=10)
NOW = TARGET + timedelta(seconds=2)
PIPELINE_NOW = TARGET + timedelta(seconds=15)
ENDPOINT = "https://example.test"


def _plan(*, safety: bool = False, active_date: date = TARGET_DATE) -> ExplicitTradePlan:
    return ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "isolated-r09-buy",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "ISOLATED R09 BUY SUBSET",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "TRADING_DAY", "trading_day": active_date.isoformat()},
            "position": {
                "inventory_scope": "ALL_REGISTERED",
                "lot_size": 100,
                "max_qty": 300,
            },
            "monitoring": {
                "timeframe_minutes": 5,
                "indicator_formula_version": "ta-v1",
            },
            "rules": [
                {
                    "rule_id": "buy-100",
                    "condition": {
                        "type": "ALL",
                        "conditions": [
                            {
                                "type": "COMPLETED_CLOSE_IN_RANGE",
                                "low_fen": 980,
                                "high_fen": 1000,
                                "include_low": True,
                                "include_high": True,
                            },
                            {
                                "type": "VOLUME_TO_MEAN_GTE",
                                "window_bars": 5,
                                "minimum_ratio": "1.5",
                                "history_scope": "CONTIGUOUS_TRADING_BARS",
                            },
                        ],
                    },
                    "action": {"type": "BUY", "quantity": 100},
                    "confirmation": {
                        "kind": "COMPLETED_BAR_CLOSE",
                        "timeframe_minutes": 5,
                    },
                    "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
                    "safety_conditions": (
                        {"type": "MANUAL_EVENT_RISK_CLEAR"} if safety else None
                    ),
                }
            ],
            "conflict_policy": {
                "trade_conflict": "BLOCK_BOTH",
                "risk_conflict": "RISK_ONLY",
            },
        }
    )


def _work(engine, *, now: datetime = NOW):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: now)


def _seed_active(engine, plan: ExplicitTradePlan) -> None:
    source_id = str(uuid4())
    version_id = str(uuid4())
    source_text = "isolated trusted R09 fixture; not public review"
    with create_session_factory(engine)() as session, session.begin():
        session.add(
            PlanSource(
                id=source_id,
                source_text=source_text,
                source_hash=sha256(source_text.encode()).hexdigest(),
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add(
            PlanVersion(
                id=version_id,
                plan_id=plan.plan_id,
                version=plan.version,
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status="ACTIVE",
                payload_json=dump_plan_json(plan),
                source_id=source_id,
                revision=1,
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add_all(
            (
                PlanVersionReview(
                    plan_version_id=version_id,
                    review_issues_json="[]",
                ),
                PlanReviewProvenance(
                    plan_version_id=version_id,
                    origin="MANUAL",
                    extraction_id=None,
                    source_hash=sha256(source_text.encode()).hexdigest(),
                    draft_hash=plan_sha256(plan),
                    confirmed_at=None,
                ),
                PlanActivationState(
                    symbol=plan.symbol,
                    plan_version_id=version_id,
                    revision=1,
                    changed_at=PREPARED_AT.isoformat(),
                ),
                ActivePlan(
                    symbol=plan.symbol,
                    plan_version_id=version_id,
                    activated_at=PREPARED_AT.isoformat(),
                    revision=1,
                ),
            )
        )


def _seed_facts(engine, plan: ExplicitTradePlan, *, current_volume: int = 300) -> None:
    first = TARGET - timedelta(minutes=25)
    volumes = (100, 100, 100, 100, 600, current_volume)
    with _work(engine, now=PREPARED_AT) as work:
        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TARGET.date(),
                    is_open=True,
                    previous_trade_date=date(2026, 9, 11),
                ),
            )
        )
        for index, volume in enumerate(volumes):
            work.history.upsert_five_minute(
                **FiveMinuteBar(
                    symbol=plan.symbol,
                    bar_end=first + timedelta(minutes=index * 5),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=volume,
                    amount_yuan=Decimal("0"),
                ).model_dump()
            )
        work.positions.confirm_inventory(
            symbol=plan.symbol,
            as_of_trade_date=TARGET.date(),
            total_quantity=100,
            sellable_quantity=100,
            included_lot_ids=(),
            complete_registration=True,
            expected_revision=0,
        )
        if plan.rules[0].safety_conditions is not None:
            work.manual_event_risk.upsert(
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status=ManualEventRiskStatus.CLEAR,
                expires_on=TARGET.date(),
                expected_revision=0,
            )
        work.commit()


def _database(tmp_path: Path, name: str, *, current_volume: int = 300, safety=False):
    engine = create_sqlite_engine(tmp_path / name)
    upgrade_database(engine)
    plan = _plan(safety=safety)
    _seed_active(engine, plan)
    _seed_facts(engine, plan, current_volume=current_volume)
    return engine, plan


class _PipelineClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.current = max(self.current, deadline)


class _SchedulerClock(_PipelineClock):
    def __init__(self, current: datetime) -> None:
        super().__init__(current)
        self.sleep_calls: list[datetime] = []

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleep_calls.append(deadline)
        if len(self.sleep_calls) == 1:
            self.current = max(self.current, deadline)
            await asyncio.sleep(0)
            return
        await asyncio.Event().wait()


class _InertLifecycle:
    async def start(self):
        return SimpleNamespace(status=RuntimeServiceStatus.RUNNING, read_only=False)

    async def stop(self) -> None:
        return None


class _ExplicitPipelineSDK:
    """Offline source exposing only facts declared by the explicit BUY plan."""

    def __init__(self, *, current_volume: int) -> None:
        self.current_volume = current_volume
        self.source_time = TARGET - timedelta(minutes=1)
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def request(**kwargs: object) -> pd.DataFrame:
            self.calls.append(name)
            if name == "trade_cal":
                start = date.fromisoformat(str(kwargs["start_date"]))
                end = date.fromisoformat(str(kwargs["end_date"]))
                exchange = str(kwargs["exchange"])
                rows = []
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
            if name in {"rt_min", "rt_min_daily"}:
                source_times = (
                    (self.source_time,)
                    if name == "rt_min"
                    else tuple(
                        self.source_time.replace(hour=9, minute=30)
                        + timedelta(minutes=offset)
                        for offset in range(
                            int(
                                (
                                    self.source_time
                                    - self.source_time.replace(hour=9, minute=30)
                                ).total_seconds()
                                // 60
                            )
                            + 1
                        )
                    )
                )
                return pd.DataFrame(
                    [
                        {
                            "ts_code": "003043.SZ",
                            "freq": "1MIN",
                            "time": source_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "open": "9.90",
                            "high": "9.90",
                            "low": "9.90",
                            "close": "9.90",
                            "vol": str(
                                self.current_volume
                                if source_time == self.source_time
                                else 60
                            ),
                            "amount": "0",
                        }
                        for source_time in source_times
                    ]
                )
            raise AssertionError(f"explicit pipeline requested undeclared endpoint: {name}")

        return request


def _seed_pipeline_facts(engine, plan: ExplicitTradePlan) -> None:
    with _work(engine, now=PREPARED_AT) as work:
        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange=plan.market,
                    cal_date=TARGET.date(),
                    is_open=True,
                    previous_trade_date=date(2026, 9, 11),
                ),
            )
        )
        for index, volume in enumerate((100, 100, 100, 100, 600)):
            work.history.upsert_five_minute(
                **FiveMinuteBar(
                    symbol=plan.symbol,
                    bar_end=TARGET - timedelta(minutes=(5 - index) * 5),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=volume,
                    amount_yuan=Decimal("0"),
                ).model_dump()
            )
        work.history.upsert_minutes(
            tuple(
                MinuteBar(
                    symbol=plan.symbol,
                    bar_end=TARGET - timedelta(minutes=offset),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=60,
                    amount_yuan=Decimal("0"),
                    received_at=NOW,
                )
                for offset in (4, 3, 2, 1)
            )
        )
        work.positions.confirm_inventory(
            symbol=plan.symbol,
            as_of_trade_date=TARGET.date(),
            total_quantity=100,
            sellable_quantity=100,
            included_lot_ids=(),
            complete_registration=True,
            expected_revision=0,
        )
        if plan.rules[0].safety_conditions is not None:
            work.manual_event_risk.upsert(
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status=ManualEventRiskStatus.CLEAR,
                expires_on=TARGET.date(),
                expected_revision=0,
            )
        work.commit()


def _pipeline_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    current_volume: int,
    plan: ExplicitTradePlan | None = None,
):
    import trade_plan_monitor.runtime.production as production

    clock = _PipelineClock(PIPELINE_NOW)
    database = tmp_path / f"explicit-pipeline-{current_volume}.sqlite3"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    sessions = create_session_factory(engine)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

    plan = _plan() if plan is None else plan
    _seed_active(engine, plan)
    _seed_pipeline_facts(engine, plan)
    config = tmp_path / f"config-{current_volume}" / "app.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"tushare:\n  api_url: {ENDPOINT}\n  token: offline-test-token\n",
        encoding="utf-8",
    )
    certification_directory = config.parent.parent / "data" / "live-certification"
    evidence = create_stock_certification(
        observed_at=PIPELINE_NOW,
        endpoint_url=ENDPOINT,
        capabilities=ProviderCapabilities(
            **{
                key: ProviderCapabilityStatus.READY
                for key in ProviderCapabilities.model_fields
            }
        ),
        source_time_label=SourceTimeLabel.START,
    )
    write_live_certification(
        certification_directory / "tushare-stock-live.json",
        evidence,
    )
    sdk = _ExplicitPipelineSDK(current_volume=current_volume)
    monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
    def build_pipeline():
        controller = create_live_tushare_request_controller(clock=clock)
        published = []
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=certification_directory,
            stock_certification=evidence,
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work,
            runtime_generation=uuid4(),
            publisher=published.append,
        )
        return controller, pipeline, published

    controller, pipeline, published = build_pipeline()
    return engine, work, plan, sdk, build_pipeline, controller, pipeline, published


def _rotated_plan(plan: ExplicitTradePlan) -> ExplicitTradePlan:
    payload = plan.model_dump(mode="python", round_trip=True)
    payload["version"] = plan.version + 1
    condition = payload["rules"][0]["condition"]["conditions"][0]
    condition["low_fen"] = 1080
    condition["high_fen"] = 1100
    return ExplicitTradePlan.model_validate(payload)


def _rotate_active_plan(engine, current: ExplicitTradePlan) -> ExplicitTradePlan:
    replacement = _rotated_plan(current)
    source_id = str(uuid4())
    version_id = str(uuid4())
    source_text = "isolated trusted R09 rotation fixture; not public review"
    with create_session_factory(engine)() as session, session.begin():
        active = session.get(ActivePlan, current.symbol)
        state = session.get(PlanActivationState, current.symbol)
        old_version = None if active is None else session.get(PlanVersion, active.plan_version_id)
        assert active is not None and state is not None and old_version is not None
        session.add(
            PlanSource(
                id=source_id,
                source_text=source_text,
                source_hash=sha256(source_text.encode()).hexdigest(),
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add(
            PlanVersion(
                id=version_id,
                plan_id=replacement.plan_id,
                version=replacement.version,
                symbol=replacement.symbol,
                plan_hash=plan_sha256(replacement),
                status="ACTIVE",
                payload_json=dump_plan_json(replacement),
                source_id=source_id,
                revision=1,
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add_all(
            (
                PlanVersionReview(
                    plan_version_id=version_id,
                    review_issues_json="[]",
                ),
                PlanReviewProvenance(
                    plan_version_id=version_id,
                    origin="MANUAL",
                    extraction_id=None,
                    source_hash=sha256(source_text.encode()).hexdigest(),
                    draft_hash=plan_sha256(replacement),
                    confirmed_at=None,
                ),
            )
        )
        session.flush()
        old_version.status = "SUPERSEDED"
        active.plan_version_id = version_id
        active.revision += 1
        active.activated_at = PREPARED_AT.isoformat()
        state.plan_version_id = version_id
        state.revision += 1
        state.changed_at = PREPARED_AT.isoformat()
    return replacement


@pytest.mark.parametrize(
    ("last_minute_volume", "expected_alerts"),
    ((59, 0), (60, 1)),
)
def test_actual_production_deadline_dispatches_only_qualified_explicit_buy(
    tmp_path: Path,
    monkeypatch,
    last_minute_volume: int,
    expected_alerts: int,
) -> None:
    async def scenario() -> None:
        (
            engine,
            work,
            plan,
            sdk,
            _build_pipeline,
            controller,
            pipeline,
            published,
        ) = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=last_minute_volume,
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            result = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            alert_service = PersistentAlertOperationService(
                unit_of_work_factory=work,
                clock=lambda: PIPELINE_NOW,
            )
            with TestClient(
                create_app(
                    runtime_factory=_InertLifecycle,
                    alert_service=alert_service,
                ),
                base_url="http://127.0.0.1:8765",
            ) as client:
                response = client.get(
                    "/api/v1/alerts",
                    params={"symbol": plan.symbol, "signalType": "BUY"},
                )
            with work() as transaction:
                inventory = transaction.positions.inventory_snapshot(
                    plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    cutoff=TARGET,
                )

            assert len(result) == 1
            assert response.status_code == 200
            assert response.json()["total"] == expected_alerts
            assert inventory.total_qty == 100
            assert (
                MonitorEventType.ALERT_CREATED
                in {event.event_type for event in published}
            ) is bool(expected_alerts)
            assert set(sdk.calls) == {"trade_cal", "rt_min"}
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_actual_deadline_waits_for_completed_bucket_and_restart_deduplicates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        (
            engine,
            work,
            plan,
            sdk,
            build_pipeline,
            controller,
            pipeline,
            published,
        ) = _pipeline_fixture(tmp_path, monkeypatch, current_volume=60)
        restarted_controller = None
        try:
            await pipeline.refresh_references(TARGET.date())
            sdk.source_time = TARGET - timedelta(minutes=2)
            incomplete = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=TARGET - timedelta(minutes=1) + timedelta(seconds=15),
                    bar_end=TARGET - timedelta(minutes=1),
                )
            )
            with work() as transaction:
                before, before_total = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
            assert incomplete == ()
            assert before == () and before_total == 0

            sdk.source_time = TARGET - timedelta(minutes=1)
            committed = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            calls_after_commit = len(sdk.calls)
            await controller.aclose()
            restarted_controller, restarted, restarted_published = build_pipeline()
            await restarted.recover_startup(TARGET.date())
            calls_after_recovery = len(sdk.calls)
            duplicate = await restarted.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            with work() as transaction:
                after, after_total = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )

            assert len(committed) == 1
            assert duplicate == ()
            assert len(after) == 1 and after_total == 1
            assert MonitorEventType.ALERT_CREATED in {
                event.event_type for event in published
            }
            assert MonitorEventType.ALERT_CREATED not in {
                event.event_type for event in restarted_published
            }
            assert calls_after_recovery > calls_after_commit
            assert len(sdk.calls) == calls_after_recovery
            assert set(sdk.calls) <= {"trade_cal", "rt_min", "rt_min_daily"}
        finally:
            if restarted_controller is not None:
                await restarted_controller.aclose()
            else:
                await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_real_monitor_composition_scheduler_dispatches_explicit_buy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    async def scenario() -> None:
        database = tmp_path / "scheduled-explicit.sqlite3"
        engine = create_sqlite_engine(database)
        upgrade_database(engine)
        plan = _plan()
        _seed_active(engine, plan)
        _seed_pipeline_facts(engine, plan)
        engine.dispose()

        initial_now = TARGET - timedelta(minutes=1) + timedelta(seconds=15)
        clock = _SchedulerClock(initial_now)
        config = tmp_path / "config" / "app.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"tushare:\n  api_url: {ENDPOINT}\n  token: offline-test-token\n",
            encoding="utf-8",
        )
        evidence = create_stock_certification(
            observed_at=initial_now,
            endpoint_url=ENDPOINT,
            capabilities=ProviderCapabilities(
                **{
                    key: ProviderCapabilityStatus.READY
                    for key in ProviderCapabilities.model_fields
                }
            ),
            source_time_label=SourceTimeLabel.START,
        )
        write_live_certification(
            tmp_path / "data" / "live-certification" / "tushare-stock-live.json",
            evidence,
        )
        sdk = _ExplicitPipelineSDK(current_volume=60)
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
        composition = create_monitor_composition(
            config_path=config,
            database_path=database,
        )
        try:
            await composition.start()
            for _ in range(300):
                engine = create_sqlite_engine(database)
                try:
                    with _work(engine, now=clock.now()) as work:
                        alerts, total = work.alerts.list_events(
                            symbol=plan.symbol,
                            signal_type="BUY",
                            acknowledged=None,
                            start_at=None,
                            end_at=None,
                            offset=0,
                            limit=10,
                        )
                finally:
                    engine.dispose()
                if total:
                    break
                await asyncio.sleep(0.01)
            assert len(alerts) == 1 and total == 1
            assert clock.sleep_calls[0] > TARGET
            assert clock.sleep_calls[0].replace(second=0, microsecond=0) == TARGET
            assert set(sdk.calls) <= {"trade_cal", "rt_min", "rt_min_daily"}
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("plan_state", ("expired", "deactivated", "rotated"))
def test_actual_deadline_rejects_ineligible_or_replaced_explicit_plan(
    tmp_path: Path,
    monkeypatch,
    plan_state: str,
) -> None:
    async def scenario() -> None:
        seeded_plan = _plan(
            active_date=(date(2026, 9, 11) if plan_state == "expired" else TARGET.date())
        )
        (
            engine,
            work,
            plan,
            sdk,
            _build_pipeline,
            controller,
            pipeline,
            published,
        ) = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            plan=seeded_plan,
        )
        replacement = None
        try:
            if plan_state == "deactivated":
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    transaction.commit()
            elif plan_state == "rotated":
                replacement = _rotate_active_plan(engine, plan)

            await pipeline.refresh_references(TARGET.date())
            result = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            with work() as transaction:
                alerts, total = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )

            assert alerts == () and total == 0
            assert MonitorEventType.ALERT_CREATED not in {
                event.event_type for event in published
            }
            if plan_state == "rotated":
                assert replacement is not None
                assert len(result) == 1
                assert result[0].evaluation_result.plan_hash == plan_sha256(replacement)
            else:
                assert result == ()
                assert "rt_min" not in sdk.calls
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    ("deactivation", "rotation", "inventory", "manual-risk"),
)
def test_actual_deadline_revision_guards_reject_stale_explicit_buy(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    async def scenario() -> None:
        seeded_plan = _plan(safety=mutation == "manual-risk")
        (
            engine,
            work,
            plan,
            _sdk,
            _build_pipeline,
            controller,
            pipeline,
            published,
        ) = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            plan=seeded_plan,
        )

        def mutate(_result) -> None:
            if mutation == "rotation":
                _rotate_active_plan(engine, plan)
                return
            with work() as transaction:
                if mutation == "deactivation":
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                elif mutation == "inventory":
                    transaction.positions.confirm_inventory(
                        symbol=plan.symbol,
                        as_of_trade_date=TARGET.date(),
                        total_quantity=100,
                        sellable_quantity=100,
                        included_lot_ids=(),
                        complete_registration=True,
                        expected_revision=1,
                    )
                else:
                    transaction.manual_event_risk.upsert(
                        symbol=plan.symbol,
                        plan_hash=plan_sha256(plan),
                        status=ManualEventRiskStatus.RISK_PRESENT,
                        expires_on=TARGET.date(),
                        expected_revision=1,
                    )
                transaction.commit()

        pipeline.explicit_evaluations._after_evaluate = mutate
        try:
            await pipeline.refresh_references(TARGET.date())
            with pytest.raises(StaleExplicitDecisionError):
                await pipeline.run_deadline(
                    MarketDeadline(
                        kind=DeadlineKind.REALTIME_MINUTE,
                        trade_date=TARGET.date(),
                        due_at=PIPELINE_NOW,
                        bar_end=TARGET,
                    )
                )
            with work() as transaction:
                alerts, total = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
                states = transaction.explicit_rules.states(
                    plan_hash=plan_sha256(plan),
                    symbol=plan.symbol,
                    activation_revision=1,
                )
                inventory = transaction.positions.inventory_snapshot(
                    plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    cutoff=PIPELINE_NOW,
                )

            assert alerts == () and total == 0
            assert states == ()
            assert inventory.total_qty == 100
            assert MonitorEventType.ALERT_CREATED not in {
                event.event_type for event in published
            }
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_production_sqlite_dispatch_requires_price_and_mean_volume_then_deduplicates(
    tmp_path: Path,
) -> None:
    false_engine, false_plan = _database(
        tmp_path, "explicit-price-only.sqlite3", current_volume=299
    )
    true_engine, true_plan = _database(tmp_path, "explicit-qualified.sqlite3")
    try:
        false_service = create_explicit_runtime_evaluation_service(
            lambda: _work(false_engine)
        )
        false_cycle = false_service.run_intraday(
            plan=false_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        assert false_cycle.committed_events == ()

        true_service = create_explicit_runtime_evaluation_service(lambda: _work(true_engine))
        first = true_service.run_intraday(
            plan=true_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        replay = true_service.run_intraday(
            plan=true_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        assert first.status is ExplicitRuntimeCycleStatus.COMMITTED
        assert first.committed_events[0].quantity == 100
        assert replay.status is ExplicitRuntimeCycleStatus.DUPLICATE
        assert replay.committed_events == ()
    finally:
        false_engine.dispose()
        true_engine.dispose()


def test_expired_explicit_plan_commits_evidence_but_never_a_new_buy_alert(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-expired.sqlite3")
    upgrade_database(engine)
    plan = _plan(active_date=date(2026, 9, 11))
    _seed_active(engine, plan)
    _seed_facts(engine, plan)
    try:
        cycle = create_explicit_runtime_evaluation_service(lambda: _work(engine)).run_intraday(
            plan=plan,
            target_bucket_end=TARGET,
            evaluated_at=NOW,
        )
        assert cycle.status is ExplicitRuntimeCycleStatus.COMMITTED
        assert cycle.committed_events == ()
        assert "PLAN_INACTIVE" in cycle.evaluation_result.rule_results[0].blockers
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ["activation", "inventory", "manual-risk"])
def test_commit_guard_rejects_concurrent_consumed_revision_changes(
    tmp_path: Path,
    mutation: str,
) -> None:
    engine, plan = _database(tmp_path, f"explicit-stale-{mutation}.sqlite3", safety=True)

    def mutate(_result) -> None:
        with _work(engine) as work:
            if mutation == "activation":
                work.plans.deactivate(plan.symbol, expected_revision=1)
            elif mutation == "inventory":
                work.positions.confirm_inventory(
                    symbol=plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    total_quantity=100,
                    sellable_quantity=100,
                    included_lot_ids=(),
                    complete_registration=True,
                    expected_revision=1,
                )
            else:
                work.manual_event_risk.upsert(
                    symbol=plan.symbol,
                    plan_hash=plan_sha256(plan),
                    status=ManualEventRiskStatus.RISK_PRESENT,
                    expires_on=TARGET.date(),
                    expected_revision=1,
                )
            work.commit()

    try:
        service = ExplicitRuntimeEvaluationService(lambda: _work(engine), after_evaluate=mutate)
        with pytest.raises(StaleExplicitDecisionError):
            service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
        with _work(engine) as work:
            assert work.explicit_rules.states(
                plan_hash=plan_sha256(plan), symbol=plan.symbol, activation_revision=1
            ) == ()
            listed, total = work.alerts.list_events(
                symbol=plan.symbol,
                signal_type="BUY",
                acknowledged=None,
                start_at=None,
                end_at=None,
                offset=0,
                limit=10,
            )
            assert listed == () and total == 0
    finally:
        engine.dispose()
