"""A stopped production monitor resumes one missed close across real processes."""

import asyncio
import json
from datetime import date, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_live_pipeline_acceptance import (
    ControlledClock,
    VirtualPace,
    _write_configuration_and_evidence,
)
from test_s3_missed_close_kill_restart import CurrentCloseSDK, _inventory_bytes, _seed

from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.outbox import AlertOutbox
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertDeliveryEligibility,
    AlertEvent,
    DailyBar,
    DeliveryAttempt,
    EvaluationLedger,
    EvaluationResult,
    RuntimeLiveness,
)

TRADE_DATE = date(2026, 9, 8)
SYMBOL = "003043.SZ"


def _run_monitor_process(
    root: str,
    observed_at: datetime,
    expected_results: int,
    crash_after_start: bool,
) -> None:
    import os

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    base = Path(root)
    clock = ControlledClock(observed_at)
    sdk = CurrentCloseSDK(clock, (SYMBOL,), official_closes={TRADE_DATE: "55.00"})

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monitor_composition.SystemClock = lambda: clock
    monitor_composition.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _config: sdk

    async def scenario():
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config" / "app.yaml",
            database_path=base / "monitor.sqlite3",
        )
        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.RUNNING
            assert health.read_only is False
            assert health.recovery_issues == (), health.recovery_issues
            for _ in range(20):
                if clock.sleep_calls:
                    break
                await asyncio.sleep(0)
            assert clock.sleep_calls
            engine = create_sqlite_engine(base / "monitor.sqlite3")
            try:
                with create_session_factory(engine)() as session:
                    results = session.scalars(
                        select(DailyRecord).where(
                            DailyRecord.kind == "EVALUATION",
                            DailyRecord.id != "evaluation-head-" + SYMBOL,
                        )
                    ).all()
                    current = [
                        row
                        for row in results
                        if json.loads(row.payload_json)["official_trade_date"]
                        == TRADE_DATE.isoformat()
                    ]
                    assert len(current) == expected_results
                    assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                    assert session.scalar(select(func.count()).select_from(ActivePlan)) == 1
            finally:
                engine.dispose()
            if crash_after_start:
                os._exit(23)
        finally:
            await composition.stop()

    asyncio.run(scenario())


def _spawn_monitor(
    root: Path,
    observed_at: datetime,
    expected_results: int,
    *,
    crash_after_start=False,
) -> None:
    process = get_context("spawn").Process(
        target=_run_monitor_process,
        args=(str(root), observed_at, expected_results, crash_after_start),
    )
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("production monitor child did not finish")
    assert process.exitcode == (23 if crash_after_start else 0)


def test_stopped_monitor_recovers_missed_close_once_after_process_restart(tmp_path):
    database = tmp_path / "monitor.sqlite3"
    before_close = datetime(2026, 9, 8, 14, tzinfo=SHANGHAI)
    after_close = datetime(2026, 9, 8, 16, tzinfo=SHANGHAI)
    clock = ControlledClock(before_close.replace(hour=9))
    _seed(tmp_path)
    inventory = _inventory_bytes(tmp_path)
    _write_configuration_and_evidence(
        tmp_path,
        observed_at=before_close,
        include_index=False,
    )

    engine = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(engine)
        with sessions.begin() as session:
            session.get(RuntimeLiveness, 1).last_alive_at = clock.now().isoformat()
    finally:
        engine.dispose()

    _spawn_monitor(tmp_path, before_close, 0, crash_after_start=True)
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine)() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DailyBar)
                    .where(
                        DailyBar.symbol == SYMBOL,
                        DailyBar.trade_date == TRADE_DATE,
                        DailyBar.is_official.is_(True),
                    )
                )
                == 0
            )
    finally:
        engine.dispose()

    _spawn_monitor(tmp_path, after_close, 1)
    _spawn_monitor(tmp_path, after_close + timedelta(minutes=1), 2)

    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine)() as session:
            assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
            assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
            assert (
                session.scalar(
                    select(DailyBar.close_fen).where(
                        DailyBar.symbol == SYMBOL,
                        DailyBar.trade_date == TRADE_DATE,
                        DailyBar.is_official.is_(True),
                    )
                )
                is None
            )
            head = session.get(DailyRecord, "evaluation-head-" + SYMBOL)
            snapshot = json.loads(head.payload_json)
            assert snapshot["official_trade_date"] == TRADE_DATE.isoformat()
            assert snapshot["daily_evidence"]["bars"][-1]["close"] == "5500"
            assert snapshot["signals"] == snapshot["risks"] == []
            assert snapshot["alerts"][0]["outcome"] == "SATISFIED"
            assert snapshot["alerts"][0]["confirmed_trade_date"] == TRADE_DATE.isoformat()
            assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
            assert session.scalars(select(AlertDeliveryEligibility.status)).all() == []
            assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1
            assert session.scalars(select(DeliveryAttempt.status)).all() == ["DELIVERED"]
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 1
    finally:
        engine.dispose()
    assert _inventory_bytes(tmp_path) == inventory

    engine = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(engine)
        with sessions() as session:
            event_id = UUID(session.scalar(select(AlertEvent.id)))
            alert = AlertOutbox(
                session,
                clock=lambda: after_close,
                id_factory=lambda: str(uuid4()),
            ).get(event_id)
        admission = CurrentDeliveryAdmission(
            sessions,
            runtime_generation=lambda: uuid4(),
        )
        assert admission(alert, after_close + timedelta(minutes=1)) is True
    finally:
        engine.dispose()
