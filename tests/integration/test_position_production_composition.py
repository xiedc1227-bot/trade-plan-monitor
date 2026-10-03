"""WEBF09 coverage for the production manual-position composition."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select

from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    PositionLot,
    RequestIdempotency,
    RuntimeLiveness,
)
from trade_plan_monitor.state.repositories import (
    MaxPositionExceededError,
    PositionReductionError,
    PositionT1LockedError,
    RevisionConflictError,
)
from trade_plan_monitor.state.runtime_liveness import RuntimeLivenessRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_composition import (
    MonitorWebComposition,
    SystemClock,
    create_monitor_composition,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FIXED_NOW = datetime(2026, 9, 3, 10, 30, tzinfo=_SHANGHAI)
_SAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
)


@pytest.fixture(autouse=True)
def _fixed_production_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sleep_until(_clock: SystemClock, _deadline: datetime) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(SystemClock, "now", lambda _clock: _FIXED_NOW)
    monkeypatch.setattr(SystemClock, "sleep_until", sleep_until)


@pytest.fixture(autouse=True)
def _reject_provider_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production-composition tests offline even if startup changes later."""

    from tushare.pro.client import DataApi

    def reject(_client: object, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("WEBF09 tests must not request an external provider")

    monkeypatch.setattr(DataApi, "query", reject)


def _seed_active_plan(database_path: Path, *, initialize_liveness: bool = True) -> None:
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
        sessions = create_session_factory(engine)
        if initialize_liveness:
            RuntimeLivenessRepository(sessions).initialize_empty(_FIXED_NOW)
        plan_source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
        plan = load_plan_yaml(plan_source)
        assert plan.schema_version == 1
        assert plan.activation.mode == "MANUAL"
        assert plan.position.max_qty == 200
        validation = validate_trade_plan(
            plan,
            available_market_evidence=set(ALL_MARKET_EVIDENCE),
        )
        assert validation.can_activate
        with SqlAlchemyUnitOfWork(
            sessions,
            clock=lambda: _FIXED_NOW,
        ) as work:
            work.plans.save_draft(plan, source_text=plan_source)
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validation,
            )
            work.references.upsert_trading_days(
                (
                    TradingDay(
                        exchange="SZSE",
                        cal_date=date(2026, 9, 3),
                        is_open=True,
                        previous_trade_date=date(2026, 9, 2),
                    ),
                    TradingDay(
                        exchange="SZSE",
                        cal_date=date(2026, 9, 4),
                        is_open=True,
                        previous_trade_date=date(2026, 9, 3),
                    ),
                    TradingDay(
                        exchange="SZSE",
                        cal_date=date(2026, 9, 5),
                        is_open=False,
                        previous_trade_date=date(2026, 9, 4),
                    ),
                )
            )
            work.commit()
    finally:
        engine.dispose()


def _production_position_app(
    tmp_path: Path, *, initialize_liveness: bool = True,
) -> tuple[FastAPI, MonitorWebComposition, Path]:
    config_path = tmp_path / "config" / "app.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}\n", encoding="utf-8")
    database_path = tmp_path / "state" / "monitor.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_active_plan(database_path, initialize_liveness=initialize_liveness)
    composition = create_monitor_composition(
        config_path=config_path,
        database_path=database_path,
    )
    return create_app(runtime_factory=lambda: composition), composition, database_path


def _buy_payload(
    *,
    symbol: str = "003043.SZ",
    quantity: int = 100,
    acquired_trade_date: str = "2026-09-03",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "bucket": "CORE",
        "quantity": quantity,
        "acquiredTradeDate": acquired_trade_date,
        "costFen": 6_400,
        "relatedAlertId": None,
        "expectedRevision": 0,
    }


def _assert_unavailable(response: Response) -> None:
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_missing_liveness_and_removed_position_write_leave_state_unchanged(tmp_path: Path) -> None:
    app, _composition, database_path = _production_position_app(
        tmp_path, initialize_liveness=False,
    )
    engine = create_sqlite_engine(database_path)
    sessions = create_session_factory(engine)

    def mutation_snapshot():
        with sessions() as session:
            return {
                model.__tablename__: session.execute(
                    select(model.__table__).order_by(*model.__table__.primary_key),
                ).all()
                for model in (PositionLot, RequestIdempotency, AuditLog)
            }

    try:
        before = mutation_snapshot()
        assert before["position_lot"] == []
        assert before["request_idempotency"] == []
        with sessions() as session:
            assert session.scalars(select(RuntimeLiveness)).all() == []
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            health = client.get("/api/v1/health")
            assert health.status_code == 200
            assert health.json()["status"] == "BLOCKED"
            assert health.json()["blockReason"] == "LEGACY_PLANS_REQUIRE_REVIEW"
            response = client.post(
                "/api/v1/position-lots",
                headers={"Idempotency-Key": "webf09-missing-liveness"},
                json=_buy_payload(),
            )
            assert response.status_code == 405
            assert mutation_snapshot() == before
            with sessions() as session:
                assert session.scalars(select(RuntimeLiveness)).all() == []
    finally:
        engine.dispose()


def test_default_monitor_composition_injects_persistent_position_service(
    tmp_path: Path,
) -> None:
    app, composition, _database_path = _production_position_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert composition.position_service is not None
        assert app.state.position_operation_service is composition.position_service
        response = client.get(
            "/api/v1/position-lots",
            params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-03"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "symbol": "003043.SZ",
        "asOfTradeDate": "2026-09-03",
        "offset": 0,
        "limit": 20,
        "total": 0,
    }
    assert not hasattr(app.state, "position_operation_service")


def test_position_page_is_paginated_and_projects_sellability_on_the_backend(
    tmp_path: Path,
) -> None:
    app, _composition, database_path = _production_position_app(tmp_path)
    engine = create_sqlite_engine(database_path)
    try:
        with SqlAlchemyUnitOfWork(
            create_session_factory(engine),
            clock=lambda: _FIXED_NOW,
        ) as work:
            work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=100,
                acquired_trade_date=date(2026, 9, 2),
                cost_fen=6_300,
                board_lot=100,
                max_position_qty=200,
            )
            work.positions.record_buy(
                symbol="003043.SZ",
                bucket="TACTICAL",
                quantity=100,
                acquired_trade_date=date(2026, 9, 3),
                cost_fen=6_400,
                board_lot=100,
                max_position_qty=200,
            )
            work.commit()
    finally:
        engine.dispose()

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.get(
            "/api/v1/position-lots",
            params={
                "symbol": "003043.SZ",
                "asOfTradeDate": "2026-09-03",
                "offset": 0,
                "limit": 1,
            },
        )
        second = client.get(
            "/api/v1/position-lots",
            params={
                "symbol": "003043.SZ",
                "asOfTradeDate": "2026-09-03",
                "offset": 1,
                "limit": 1,
            },
        )

    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["items"][0]["acquiredTradeDate"] == "2026-09-02"
    assert first.json()["items"][0]["sellableQuantity"] == 100
    assert second.status_code == 200
    assert second.json()["total"] == 2
    assert second.json()["items"][0]["acquiredTradeDate"] == "2026-09-03"
    assert second.json()["items"][0]["sellableQuantity"] == 0


def test_position_calendar_distinguishes_known_closed_from_missing_authority(
    tmp_path: Path,
) -> None:
    app, _composition, database_path = _production_position_app(tmp_path)
    engine = create_sqlite_engine(database_path)
    try:
        with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _FIXED_NOW) as work:
            lot = work.positions.record_buy(
                symbol="003043.SZ", bucket="CORE", quantity=100,
                acquired_trade_date=date(2026, 9, 3), cost_fen=6400,
                board_lot=100, max_position_qty=200,
            )
            work.commit()
    finally:
        engine.dispose()

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-calendar-buy"},
            json=_buy_payload(),
        )
        assert created.status_code == 405
        lot_id = lot.id
        known_closed = client.get(
            "/api/v1/position-lots",
            params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-05"},
        )
        missing = client.get(
            "/api/v1/position-lots",
            params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-06"},
        )
        closed_reduction = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-calendar-closed"},
            json={
                "lotId": lot_id,
                "quantity": 100,
                "tradeDate": "2026-09-05",
                "expectedRevision": 0,
            },
        )
        missing_reduction = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-calendar-missing"},
            json={
                "lotId": lot_id,
                "quantity": 100,
                "tradeDate": "2026-09-06",
                "expectedRevision": 0,
            },
        )

    assert known_closed.status_code == 200
    assert known_closed.json()["items"][0]["sellableQuantity"] == 0
    _assert_unavailable(missing)
    assert closed_reduction.status_code == 404
    assert missing_reduction.status_code == 404
    engine = create_sqlite_engine(database_path)
    try:
        with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _FIXED_NOW) as work:
            with pytest.raises(PositionT1LockedError):
                work.positions.reduce_lot(lot_id, quantity=100, trade_date=date(2026, 9, 3))
            assert work.positions.get_lot(lot_id).remaining_qty == 100
    finally:
        engine.dispose()


def test_position_create_replays_atomically_and_uses_active_plan_maximum(
    tmp_path: Path,
) -> None:
    app, _composition, database_path = _production_position_app(tmp_path)

    engine = create_sqlite_engine(database_path)
    try:
        with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _FIXED_NOW) as work:
            created_lot = work.positions.record_buy(
                symbol="003043.SZ", bucket="CORE", quantity=200,
                acquired_trade_date=date(2026, 9, 3), cost_fen=6400,
                board_lot=100, max_position_qty=200,
            )
            work.commit()
        with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _FIXED_NOW) as work:
            with pytest.raises(MaxPositionExceededError):
                work.positions.record_buy(
                    symbol="003043.SZ", bucket="CORE", quantity=100,
                    acquired_trade_date=date(2026, 9, 3), cost_fen=6400,
                    board_lot=100, max_position_qty=200,
                )
            assert work.positions.get_lot(created_lot.id).remaining_qty == 200
    finally:
        engine.dispose()

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-buy-1"},
            json=_buy_payload(quantity=200),
        )
        replayed = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-buy-1"},
            json=_buy_payload(quantity=200),
        )
        maximum = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-buy-over-max"},
            json=_buy_payload(quantity=100),
        )
        missing_active_plan = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-buy-without-plan"},
            json=_buy_payload(symbol="000001.SZ"),
        )
        page = client.get(
            "/api/v1/position-lots",
            params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-04"},
        )

    assert created.status_code == replayed.status_code == 405
    assert maximum.status_code == missing_active_plan.status_code == 405
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["lotId"] == created_lot.id

    engine = create_sqlite_engine(database_path)
    try:
        with create_session_factory(engine)() as session:
            audit = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "POSITION_LOT")
            ).one()
        evidence = json.loads(audit.details_json)["recoveryEvidence"]
        assert evidence["schemaVersion"] == 1
        assert evidence["effectiveTradeDate"] == "2026-09-03"
        assert evidence["before"] is None
        assert evidence["after"]["id"] == created_lot.id
        assert evidence["after"]["remaining_qty"] == 200
        with create_session_factory(engine)() as session:
            assert session.scalars(select(RequestIdempotency)).all() == []
    finally:
        engine.dispose()


def test_position_closure_replays_and_rejects_t1_remaining_and_stale_revision(
    tmp_path: Path,
) -> None:
    app, _composition, database_path = _production_position_app(tmp_path)
    engine = create_sqlite_engine(database_path)
    sessions = create_session_factory(engine)
    try:
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: _FIXED_NOW) as work:
            lot = work.positions.record_buy(
                symbol="003043.SZ", bucket="CORE", quantity=200,
                acquired_trade_date=date(2026, 9, 3), cost_fen=6400,
                board_lot=100, max_position_qty=200,
            )
            work.commit()
        lot_id = lot.id
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: _FIXED_NOW) as work:
            with pytest.raises(PositionT1LockedError):
                work.positions.reduce_lot(
                    lot_id, quantity=100, trade_date=date(2026, 9, 3),
                    expected_revision=0,
                )
        next_day = datetime(2026, 9, 4, 10, 30, tzinfo=_SHANGHAI)
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: next_day) as work:
            reduced_lot = work.positions.reduce_lot(
                lot_id, quantity=100, trade_date=date(2026, 9, 4),
                expected_revision=0,
            )
            work.commit()
        assert reduced_lot.remaining_qty == 100
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: next_day) as work:
            with pytest.raises(RevisionConflictError):
                work.positions.reduce_lot(
                    lot_id, quantity=100, trade_date=date(2026, 9, 4),
                    expected_revision=0,
                )
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: next_day) as work:
            with pytest.raises(PositionReductionError):
                work.positions.reduce_lot(
                    lot_id, quantity=200, trade_date=date(2026, 9, 4),
                    expected_revision=1,
                )
    finally:
        engine.dispose()

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-close-buy"},
            json=_buy_payload(quantity=200),
        )
        assert created.status_code == 405
        closure_base = {
            "lotId": lot_id,
            "quantity": 100,
            "expectedRevision": 0,
        }
        t1_locked = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-close-same-day"},
            json={**closure_base, "tradeDate": "2026-09-03"},
        )
        closed = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-close-next-day"},
            json={**closure_base, "tradeDate": "2026-09-04"},
        )
        replayed = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-close-next-day"},
            json={**closure_base, "tradeDate": "2026-09-04"},
        )
        stale = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-close-stale"},
            json={**closure_base, "tradeDate": "2026-09-04"},
        )
        exceeds_remaining = client.post(
            "/api/v1/position-lot-closures",
            headers={"Idempotency-Key": "webf09-close-too-many"},
            json={
                "lotId": lot_id,
                "quantity": 200,
                "tradeDate": "2026-09-04",
                "expectedRevision": 1,
            },
        )
        page = client.get(
            "/api/v1/position-lots",
            params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-04"},
        )

    assert all(response.status_code == 404 for response in (
        t1_locked, closed, replayed, stale, exceeds_remaining,
    ))
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["remainingQuantity"] == 100
    assert page.json()["items"][0]["sellableQuantity"] == 100
    assert page.json()["items"][0]["revision"] == 1

    engine = create_sqlite_engine(database_path)
    try:
        with create_session_factory(engine)() as session:
            position_audits = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "POSITION_LOT")
            ).all()
        assert [entry.action for entry in position_audits] == [
            "POSITION_BUY_RECORDED",
            "POSITION_REDUCTION_RECORDED",
        ]
        bought, reduced = [
            json.loads(entry.details_json)["recoveryEvidence"] for entry in position_audits
        ]
        assert reduced["schemaVersion"] == 1
        assert reduced["effectiveTradeDate"] == "2026-09-04"
        assert reduced["before"] == bought["after"]
        assert reduced["after"] == {**bought["after"], "remaining_qty": 100}
    finally:
        engine.dispose()
