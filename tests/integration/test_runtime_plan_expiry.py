"""A long interruption expires plan work atomically without touching holdings."""

import asyncio
import json
from datetime import date, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json, load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan, TradePlan
from trade_plan_monitor.notifications.channels import ConsoleChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.legacy_plan_invalidation import (
    LegacyPlanInvalidationConflict,
    preview_legacy_invalidation,
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
from trade_plan_monitor.state.repositories import PlanRepository
from trade_plan_monitor.state.runtime_liveness import (
    RuntimeLivenessError,
    RuntimeLivenessRepository,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_composition import (
    _ProductionRuntimeState,
    create_monitor_composition,
)

NOW = datetime(2026, 9, 23, 10, tzinfo=SHANGHAI)
SYMBOLS = ("003043.SZ", "003044.SZ")


def _admit_in_child(database: str, exit_after_commit: int) -> None:
    import os

    engine = create_sqlite_engine(Path(database))
    factory = create_session_factory(engine)

    class Clock:
        def now(self):
            return NOW

    state = _ProductionRuntimeState(
        config_path=Path(database).with_suffix(".yaml"),
        database_path=Path(database),
        engine=engine,
        session_factory=factory,
        clock=Clock(),
        request_controller=object(),
    )
    state._admit_sync()
    os._exit(exit_after_commit)


def _pause_expiry_after_first_plan(database: str, reached) -> None:
    import time

    original_deactivate = PlanRepository.deactivate

    def pause_after_deactivate(self, symbol, *, expected_revision, cause=None):
        result = original_deactivate(self, symbol, expected_revision=expected_revision, cause=cause)
        if symbol == SYMBOLS[0]:
            reached.set()
            time.sleep(30)
        return result

    PlanRepository.deactivate = pause_after_deactivate
    _admit_in_child(database, 0)


def _manual_invalidate_in_child(database: str, fingerprint: str, reached=None) -> None:
    if reached is not None:
        import time

        original_deactivate = PlanRepository.deactivate

        def pause_after_first(self, symbol, *, expected_revision, cause=None):
            result = original_deactivate(
                self, symbol, expected_revision=expected_revision, cause=cause
            )
            if symbol == SYMBOLS[0]:
                reached.set()
                time.sleep(30)
            return result

        PlanRepository.deactivate = pause_after_first
    engine = create_sqlite_engine(Path(database))
    factory = create_session_factory(engine)
    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        work.invalidate_legacy_plans(expected_fingerprint=fingerprint)
        work.commit()
    engine.dispose()


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


def test_missing_heartbeat_manual_preview_and_invalidation_preserve_holdings(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    event_id = str(UUID(int=402))
    with factory.begin() as session:
        session.add(
            AlertEvent(
                id=event_id,
                sequence=1,
                dedup_key="a" * 64,
                payload_json="{}",
                message_text="held alert",
                created_at=NOW.isoformat(),
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
                updated_at=NOW.isoformat(),
            )
        )
    with factory() as session:
        preview = preview_legacy_invalidation(session)
    assert tuple(item.symbol for item in preview.plans) == SYMBOLS
    assert all(item.plan_version_id for item in preview.plans)

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        invalidated = work.invalidate_legacy_plans(
            expected_fingerprint=preview.fingerprint,
        )
        work.commit()
    assert invalidated == SYMBOLS
    with factory() as session:
        assert session.scalars(select(ActivePlan)).all() == []
        assert session.scalars(select(PendingOfficialClose)).all() == []
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000
        assert session.get(AlertDeliveryEligibility, event_id).status == "SUPPRESS"
        assert set(session.scalars(select(PlanVersion.status)).all()) == {"SUPERSEDED"}
        assert set(session.scalars(select(PlanVersion.payload_json)).all()) == {"{}"}
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "LEGACY_PLANS_MANUALLY_INVALIDATED")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "OFFICIAL_CLOSE_MANUALLY_INVALIDATED")
            )
            == 2
        )

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        repeated = work.invalidate_legacy_plans(
            expected_fingerprint=preview.fingerprint,
        )
        work.commit()
    assert repeated == SYMBOLS
    with factory() as session:
        assert session.get(AlertDeliveryEligibility, event_id).status == "SUPPRESS"
    engine.dispose()


def test_missing_heartbeat_manual_invalidation_rejects_changed_preview(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    with factory() as session:
        preview = preview_legacy_invalidation(session)
    with factory.begin() as session:
        session.query(ActivePlan).filter_by(symbol=SYMBOLS[0]).update({"revision": 2})
    with pytest.raises(LegacyPlanInvalidationConflict):
        with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
            work.invalidate_legacy_plans(
                expected_fingerprint=preview.fingerprint,
            )
            work.commit()
    with factory() as session:
        assert len(session.scalars(select(ActivePlan)).all()) == 2
        assert len(session.scalars(select(PendingOfficialClose)).all()) == 2
    engine.dispose()


def test_missing_heartbeat_manual_invalidation_rejects_new_heartbeat(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    with factory() as session:
        preview = preview_legacy_invalidation(session)
    with factory.begin() as session:
        from trade_plan_monitor.state.models import RuntimeLiveness

        session.add(
            RuntimeLiveness(
                id=1,
                schema_version=1,
                revision=0,
                last_alive_at=NOW.isoformat(),
            )
        )
    with pytest.raises(LegacyPlanInvalidationConflict, match="liveness"):
        with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
            work.invalidate_legacy_plans(expected_fingerprint=preview.fingerprint)
            work.commit()
    with factory() as session:
        assert len(session.scalars(select(ActivePlan)).all()) == 2
    engine.dispose()


def test_missing_heartbeat_manual_invalidation_rolls_back_partial_failure(
    tmp_path, monkeypatch
):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    with factory() as session:
        preview = preview_legacy_invalidation(session)
    original = PlanRepository.deactivate
    calls = 0

    def fail_second(self, symbol, *, expected_revision, cause=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-plan failure")
        return original(self, symbol, expected_revision=expected_revision, cause=cause)

    monkeypatch.setattr(PlanRepository, "deactivate", fail_second)
    with pytest.raises(RuntimeError, match="injected second-plan failure"):
        with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
            work.invalidate_legacy_plans(expected_fingerprint=preview.fingerprint)
            work.commit()
    with factory() as session:
        assert len(session.scalars(select(ActivePlan)).all()) == 2
        assert len(session.scalars(select(PendingOfficialClose)).all()) == 2
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000
        assert session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "LEGACY_PLANS_MANUALLY_INVALIDATED")
        ) == 0
    engine.dispose()


def test_process_kill_mid_manual_invalidation_leaves_full_review_set_for_retry(tmp_path):
    database = tmp_path / "state.db"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    with factory() as session:
        fingerprint = preview_legacy_invalidation(session).fingerprint
    engine.dispose()

    context = get_context("spawn")
    reached = context.Event()
    child = context.Process(
        target=_manual_invalidate_in_child,
        args=(str(database), fingerprint, reached),
    )
    child.start()
    try:
        assert reached.wait(timeout=15), f"manual child exited early: {child.exitcode}"
        child.terminate()
        child.join(timeout=10)
        assert not child.is_alive()
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)

    reopened = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(reopened)
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 2
            assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 2
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
            assert session.scalar(select(PositionLot.remaining_qty)) == 1000
    finally:
        reopened.dispose()

    restarted = context.Process(
        target=_manual_invalidate_in_child, args=(str(database), fingerprint)
    )
    restarted.start()
    restarted.join(timeout=15)
    if restarted.is_alive():
        restarted.terminate()
        restarted.join(timeout=5)
        pytest.fail("manual invalidation retry did not finish")
    assert restarted.exitcode == 0
    verified = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(verified)
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 0
            assert session.scalar(select(PositionLot.remaining_qty)) == 1000
            assert session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "LEGACY_PLANS_MANUALLY_INVALIDATED")
            ) == 1
    finally:
        verified.dispose()


def test_missing_heartbeat_keeps_system_health_available_without_monitor_work(
    tmp_path, monkeypatch
):
    database = tmp_path / "state.db"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW, initialize=False)
    engine.dispose()
    config = tmp_path / "config.yaml"
    config.write_text("{}\n", encoding="utf-8")
    requests: list[tuple[object, ...]] = []

    from tushare.pro.client import DataApi

    def reject_provider_request(_client, *args, **kwargs):
        requests.append((args, kwargs))
        raise AssertionError("blocked maintenance must not contact provider")

    monkeypatch.setattr(DataApi, "query", reject_provider_request)
    composition = create_monitor_composition(config_path=config, database_path=database)
    app = create_app(runtime_factory=lambda: composition)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/v1/health")
        ordinary_write = client.post(
            "/api/v1/plan-deactivations",
            headers={"Idempotency-Key": "blocked-ordinary-write"},
            json={"symbol": SYMBOLS[0], "expectedRevision": 1},
        )
        assert ordinary_write.status_code == 409
        preview_response = client.get("/api/v1/system/legacy-plan-invalidation")
        assert preview_response.status_code == 200
        assert preview_response.json()["available"] is True
        assert [item["symbol"] for item in preview_response.json()["plans"]] == list(SYMBOLS)
        incomplete = client.post(
            "/api/v1/system/legacy-plan-invalidation",
            json={"fingerprint": preview_response.json()["fingerprint"]},
        )
        assert incomplete.status_code == 422
        confirmed = client.post(
            "/api/v1/system/legacy-plan-invalidation",
            json={
                "fingerprint": preview_response.json()["fingerprint"],
                "confirmation": "INVALIDATE_LEGACY_PLANS",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["symbols"] == list(SYMBOLS)
        assert confirmed.json()["restartRequired"] is True
        repeat = client.post(
            "/api/v1/system/legacy-plan-invalidation",
            json={
                "fingerprint": preview_response.json()["fingerprint"],
                "confirmation": "INVALIDATE_LEGACY_PLANS",
            },
        )
        assert repeat.status_code == 200
        assert repeat.json() == confirmed.json()
        assert composition._runtime.owned_task_count == 0
    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["blockReason"] == "LEGACY_PLANS_REQUIRE_REVIEW"
    assert response.json()["readOnly"] is True
    assert requests == []
    with create_session_factory(create_sqlite_engine(database))() as session:
        assert session.scalars(select(ActivePlan)).all() == []
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000
        assert session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "LEGACY_PLANS_MANUALLY_INVALIDATED")
        ) == 1

    restarted = create_monitor_composition(config_path=config, database_path=database)
    restarted_app = create_app(runtime_factory=lambda: restarted)
    with TestClient(restarted_app, base_url="http://127.0.0.1:8765") as client:
        health_after_restart = client.get("/api/v1/health")
        preview_after_restart = client.get("/api/v1/system/legacy-plan-invalidation")
        stale_confirmation = client.post(
            "/api/v1/system/legacy-plan-invalidation",
            json={
                "fingerprint": preview_response.json()["fingerprint"],
                "confirmation": "INVALIDATE_LEGACY_PLANS",
            },
        )
    assert health_after_restart.status_code == 200
    assert health_after_restart.json()["status"] == "DEGRADED"
    assert health_after_restart.json()["blockReason"] is None
    assert preview_after_restart.json()["available"] is False
    assert stale_confirmation.status_code == 409
    with create_session_factory(create_sqlite_engine(database))() as session:
        assert session.scalars(select(ActivePlan)).all() == []
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000


def test_production_admission_expires_long_interruption_before_loading_active_plans(tmp_path):
    database = tmp_path / "state.db"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=121))

    class Clock:
        def now(self):
            return NOW

    state = _ProductionRuntimeState(
        config_path=tmp_path / "config.yaml",
        database_path=database,
        engine=engine,
        session_factory=factory,
        clock=Clock(),
        request_controller=object(),
    )
    try:
        state._admit_sync()
        assert state._load_active_symbols_sync() == ()
        with factory() as session:
            assert session.scalar(select(PositionLot.remaining_qty)) == 1000
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 5
        assert RuntimeLivenessRepository(factory).load().last_alive_at == NOW
    finally:
        engine.dispose()


def test_expiry_survives_process_exit_and_restart_without_duplicate_audit(tmp_path):
    database = tmp_path / "state.db"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=121))
    engine.dispose()

    context = get_context("spawn")
    for expected_code in (17, 0):
        child = context.Process(target=_admit_in_child, args=(str(database), expected_code))
        child.start()
        child.join(timeout=15)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
            pytest.fail("runtime admission child did not finish")
        assert child.exitcode == expected_code

    reopened = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(reopened)
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 0
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 5
            assert session.scalar(select(PositionLot.remaining_qty)) == 1000
    finally:
        reopened.dispose()


def test_process_kill_mid_expiry_rolls_back_every_record_then_restart_expires_once(tmp_path):
    database = tmp_path / "state.db"
    old_alive = NOW - timedelta(hours=121)
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=old_alive)
    event_id = str(UUID(int=402))
    with factory.begin() as session:
        session.add(
            AlertEvent(
                id=event_id,
                sequence=1,
                dedup_key="a" * 64,
                payload_json="{}",
                message_text="held alert",
                created_at=old_alive.isoformat(),
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
                updated_at=old_alive.isoformat(),
            )
        )
    engine.dispose()

    context = get_context("spawn")
    reached = context.Event()
    child = context.Process(
        target=_pause_expiry_after_first_plan,
        args=(str(database), reached),
    )
    child.start()
    try:
        assert reached.wait(timeout=15), f"child exited before expiry pause: {child.exitcode}"
        child.terminate()
        child.join(timeout=10)
        assert not child.is_alive()
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)

    reopened = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(reopened)
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 2
            assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 2
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
            assert session.get(AlertDeliveryEligibility, event_id).status == "HOLD"
        assert RuntimeLivenessRepository(sessions).load().last_alive_at == old_alive
    finally:
        reopened.dispose()

    restarted = context.Process(target=_admit_in_child, args=(str(database), 0))
    restarted.start()
    restarted.join(timeout=15)
    if restarted.is_alive():
        restarted.terminate()
        restarted.join(timeout=5)
        pytest.fail("runtime admission restart did not finish")
    assert restarted.exitcode == 0

    verified = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(verified)
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivePlan)) == 0
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 5
            assert session.scalar(select(PositionLot.remaining_qty)) == 1000
            assert session.get(AlertDeliveryEligibility, event_id).status == "SUPPRESS"
    finally:
        verified.dispose()


def test_production_admission_uses_one_observation_at_exact_120_hour_boundary(tmp_path):
    database = tmp_path / "state.db"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=120))

    class Clock:
        calls = 0

        def now(self):
            self.calls += 1
            return NOW if self.calls == 1 else NOW + timedelta(microseconds=1)

    clock = Clock()
    state = _ProductionRuntimeState(
        config_path=tmp_path / "config.yaml",
        database_path=database,
        engine=engine,
        session_factory=factory,
        clock=clock,
        request_controller=object(),
    )
    try:
        state._admit_sync()
        with factory() as session:
            active = session.scalars(select(ActivePlan.symbol).order_by(ActivePlan.symbol))
            assert tuple(active) == SYMBOLS
        assert RuntimeLivenessRepository(factory).load().last_alive_at == NOW
    finally:
        engine.dispose()


def test_more_than_120_hours_expires_all_plans_and_pending_closes_once(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=120, microseconds=1))

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == SYMBOLS
        work.commit()
    assert RuntimeLivenessRepository(factory).load().last_alive_at == NOW
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


def test_expiry_covers_legacy_and_explicit_families_without_changing_plan_definitions(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    _seed(factory, last_alive_at=NOW - timedelta(hours=121))

    legacy = load_plan_yaml(
        (Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml").read_text(
            encoding="utf-8"
        )
    )
    explicit = ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "expired-explicit-plan",
            "version": 1,
            "symbol": SYMBOLS[1],
            "name": "Expired explicit plan",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "MANUAL"},
            "position": {"inventory_scope": "ALL_REGISTERED", "lot_size": 100, "max_qty": 300},
            "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
            "rules": [
                {
                    "rule_id": "risk-950",
                    "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
                    "action": {"type": "RISK_ALERT"},
                    "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                    "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
                    "safety_conditions": None,
                }
            ],
            "conflict_policy": {"trade_conflict": "BLOCK_BOTH", "risk_conflict": "RISK_ONLY"},
        }
    )
    assert isinstance(legacy, TradePlan)
    documents = {legacy.symbol: dump_plan_json(legacy), explicit.symbol: dump_plan_json(explicit)}
    with factory.begin() as session:
        for plan in (legacy, explicit):
            version = session.scalar(select(PlanVersion).where(PlanVersion.symbol == plan.symbol))
            version.plan_id = plan.plan_id
            version.plan_hash = plan_sha256(plan)
            version.payload_json = documents[plan.symbol]

    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        assert work.expire_active_plans_after_interruption() == SYMBOLS
        work.commit()
    with factory() as session:
        versions = {row.symbol: row for row in session.scalars(select(PlanVersion))}
        assert set(versions) == set(SYMBOLS)
        assert all(row.status == "SUPERSEDED" for row in versions.values())
        assert {symbol: row.payload_json for symbol, row in versions.items()} == documents
        assert isinstance(load_plan_json(versions[legacy.symbol].payload_json), TradePlan)
        assert isinstance(load_plan_json(versions[explicit.symbol].payload_json), ExplicitTradePlan)
        assert session.scalar(select(PositionLot.remaining_qty)) == 1000
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
