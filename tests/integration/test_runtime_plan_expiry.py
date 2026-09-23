"""A long interruption expires plan work atomically without touching holdings."""

import asyncio
import json
from datetime import date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from trade_plan_monitor.notifications.channels import ConsoleChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertDeliveryEligibility,
    AlertEvent,
    AuditLog,
    DeliveryAttempt,
    MonitorEvent,
    PendingOfficialClose,
    PlanActivationState,
    PlanSource,
    PlanVersion,
    PositionLot,
)
from trade_plan_monitor.state.runtime_liveness import (
    RuntimeLivenessError,
    RuntimeLivenessRepository,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 23, 10, tzinfo=SHANGHAI)
SYMBOLS = ("003043.SZ", "003044.SZ")


def _seed(factory, *, last_alive_at, initialize=True):
    if initialize:
        RuntimeLivenessRepository(factory).initialize_empty(last_alive_at)
    with factory.begin() as session:
        for index, symbol in enumerate(SYMBOLS, 1):
            source_id = str(UUID(int=index))
            version_id = str(UUID(int=index + 10))
            session.add(
                PlanSource(
                    id=source_id,
                    source_text="test",
                    source_hash=f"{index:064x}",
                    created_at=last_alive_at.isoformat(),
                )
            )
            session.flush()
            session.add(
                PlanVersion(
                    id=version_id,
                    plan_id=f"plan-{index}",
                    version=1,
                    symbol=symbol,
                    plan_hash=f"{index + 10:064x}",
                    status="ACTIVE",
                    payload_json="{}",
                    source_id=source_id,
                    revision=0,
                    created_at=last_alive_at.isoformat(),
                )
            )
            session.flush()
            session.add(
                PlanActivationState(
                    symbol=symbol,
                    plan_version_id=version_id,
                    revision=1,
                    changed_at=last_alive_at.isoformat(),
                )
            )
            session.add(
                ActivePlan(
                    symbol=symbol,
                    plan_version_id=version_id,
                    revision=1,
                    activated_at=last_alive_at.isoformat(),
                )
            )
            session.add(
                PendingOfficialClose(
                    plan_hash=f"{index + 10:064x}",
                    symbol=symbol,
                    trade_date=date(2026, 9, 18),
                    formula_version="v1",
                    pending_json="{}",
                    created_at=last_alive_at.isoformat(),
                    updated_at=last_alive_at.isoformat(),
                )
            )
        session.add(
            PositionLot(
                id=str(UUID(int=100)),
                symbol=SYMBOLS[0],
                bucket="CORE",
                quantity=1000,
                remaining_qty=1000,
                acquired_trade_date=date(2026, 9, 1),
                cost_fen=1000,
                related_alert_id=None,
                closed_at=None,
            )
        )


def test_more_than_120_hours_expires_all_plans_and_pending_closes_once(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=120, microseconds=1))

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == SYMBOLS
        work.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActivePlan)) == 0
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 0
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000
        assert set(session.scalars(select(PlanVersion.status)).all()) == {"SUPERSEDED"}
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 5
        audits = session.scalars(select(AuditLog)).all()
        assert {audit.action for audit in audits} == {
            "OFFICIAL_CLOSE_EXPIRED",
            "PLAN_DEACTIVATED",
            "RUNTIME_INTERRUPTION_EXPIRED",
        }
        assert all(
            json.loads(audit.details_json)["cause"] == "OUTAGE_OVER_120_HOURS" for audit in audits
        )
        outage = next(audit for audit in audits if audit.action == "RUNTIME_INTERRUPTION_EXPIRED")
        assert (
            json.loads(outage.details_json)["lastAliveAt"]
            == (NOW - timedelta(hours=120, microseconds=1)).isoformat()
        )

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == ()
        work.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 5
    engine.dispose()


def test_exactly_120_hours_does_not_expire_plans_or_pending_closes(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=120))
    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == ()
        work.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActivePlan)) == 2
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 2
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
    engine.dispose()


def test_missing_liveness_blocks_bulk_expiry_without_touching_legacy_plan(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(days=6), initialize=False)
    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        with pytest.raises(RuntimeLivenessError):
            work.expire_active_plans_after_interruption()
        work.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActivePlan)) == 2
    engine.dispose()


def test_failure_during_second_plan_rolls_back_every_expiry_record(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(days=6))
    event_id = str(UUID(int=302))
    with factory.begin() as session:
        session.add(
            AlertEvent(
                id=event_id,
                sequence=1,
                dedup_key="d" * 64,
                payload_json="{}",
                message_text="held alert",
                created_at=(NOW - timedelta(days=6)).isoformat(),
                acknowledged_at=None,
            )
        )
        session.flush()
        session.add(
            AlertDeliveryEligibility(
                event_id=event_id,
                schema_version=1,
                revision=0,
                delivery_class="STATE_RISK",
                source_cutoff=None,
                expires_at=None,
                status="HOLD",
                reason="RECOVERY_REQUIRED",
                barrier_json=None,
                result_hash=None,
                updated_at=(NOW - timedelta(days=6)).isoformat(),
            )
        )
    calls = 0

    def interrupted_id():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("simulated exit before the second plan")
        return str(UUID(int=200 + calls))

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW, id_factory=interrupted_id) as work:
        with pytest.raises(RuntimeError, match="simulated exit"):
            work.expire_active_plans_after_interruption()
        work.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActivePlan)) == 2
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 2
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert session.scalar(select(func.count()).select_from(MonitorEvent)) == 0
        assert session.get(AlertDeliveryEligibility, event_id).status == "HOLD"
    engine.dispose()


def test_long_interruption_terminally_suppresses_existing_delivery_receipts(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(days=6))
    event_id = str(UUID(int=300))
    legacy_event_id = str(UUID(int=301))
    with factory.begin() as session:
        session.add(
            AlertEvent(
                id=event_id,
                sequence=1,
                dedup_key="f" * 64,
                payload_json="{}",
                message_text="historical alert",
                created_at=(NOW - timedelta(days=6)).isoformat(),
                acknowledged_at=None,
            )
        )
        session.flush()
        session.add(
            AlertEvent(
                id=legacy_event_id,
                sequence=2,
                dedup_key="e" * 64,
                payload_json="{}",
                message_text="legacy historical alert",
                created_at=(NOW - timedelta(days=6)).isoformat(),
                acknowledged_at=None,
            )
        )
        session.add(
            AlertDeliveryEligibility(
                event_id=event_id,
                schema_version=1,
                revision=0,
                delivery_class="STATE_RISK",
                source_cutoff=None,
                expires_at=None,
                status="HOLD",
                reason="RECOVERY_REQUIRED",
                barrier_json=None,
                result_hash=None,
                updated_at=(NOW - timedelta(days=6)).isoformat(),
            )
        )
    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == SYMBOLS
        work.commit()
    with factory() as session:
        receipt = session.get(AlertDeliveryEligibility, event_id)
        assert (receipt.status, receipt.reason, receipt.revision) == (
            "SUPPRESS",
            "ACTIVE_IDENTITY_INVALID",
            1,
        )
        outage = session.scalar(
            select(AuditLog).where(AuditLog.action == "RUNTIME_INTERRUPTION_EXPIRED")
        )
        assert json.loads(outage.details_json)["suppressedReceipts"] == 1
    delivered_lines: list[str] = []
    dispatcher = NotificationDispatcher(
        factory,
        channels=(ConsoleChannel(write_line=delivered_lines.append),),
        clock=lambda: NOW,
        enforce_current_plan=True,
    )
    try:
        assert asyncio.run(dispatcher.dispatch_pending()) == ()
    finally:
        asyncio.run(dispatcher.aclose())
    assert delivered_lines == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 0
    engine.dispose()
