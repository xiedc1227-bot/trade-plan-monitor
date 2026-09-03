"""WEBF09 coverage for the production manual-position composition."""

from __future__ import annotations

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
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_composition import (
    MonitorWebComposition,
    create_monitor_composition,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FIXED_NOW = datetime(2026, 9, 3, 10, 30, tzinfo=_SHANGHAI)
_SAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
)


@pytest.fixture(autouse=True)
def _reject_provider_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production-composition tests offline even if startup changes later."""

    from tushare.pro.client import DataApi

    def reject(_client: object, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("WEBF09 tests must not request an external provider")

    monkeypatch.setattr(DataApi, "query", reject)


def _seed_active_plan(database_path: Path) -> None:
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
        plan_source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
        plan = load_plan_yaml(plan_source)
        validation = validate_trade_plan(
            plan,
            available_market_evidence=set(ALL_MARKET_EVIDENCE),
        )
        assert validation.can_activate
        with SqlAlchemyUnitOfWork(
            create_session_factory(engine),
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


def _production_position_app(tmp_path: Path) -> tuple[FastAPI, MonitorWebComposition, Path]:
    config_path = tmp_path / "config" / "app.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}\n", encoding="utf-8")
    database_path = tmp_path / "state" / "monitor.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_active_plan(database_path)
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


def _assert_conflict(response: Response) -> None:
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def _assert_unavailable(response: Response) -> None:
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


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
    app, _composition, _database_path = _production_position_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-calendar-buy"},
            json=_buy_payload(),
        )
        assert created.status_code == 200
        lot_id = created.json()["lotId"]
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
    _assert_conflict(closed_reduction)
    _assert_unavailable(missing_reduction)


def test_position_create_replays_atomically_and_uses_active_plan_maximum(
    tmp_path: Path,
) -> None:
    app, _composition, _database_path = _production_position_app(tmp_path)

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

    assert created.status_code == 200
    assert created.json()["quantity"] == 200
    assert created.json()["revision"] == 0
    assert replayed.status_code == 200
    assert replayed.json() == created.json()
    _assert_conflict(maximum)
    _assert_conflict(missing_active_plan)
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["lotId"] == created.json()["lotId"]


def test_position_closure_replays_and_rejects_t1_remaining_and_stale_revision(
    tmp_path: Path,
) -> None:
    app, _composition, database_path = _production_position_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/position-lots",
            headers={"Idempotency-Key": "webf09-close-buy"},
            json=_buy_payload(quantity=200),
        )
        assert created.status_code == 200
        lot_id = created.json()["lotId"]
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

    _assert_conflict(t1_locked)
    assert closed.status_code == 200
    assert closed.json()["appliedQuantity"] == 100
    assert closed.json()["beforeRemainingQuantity"] == 200
    assert closed.json()["afterRemainingQuantity"] == 100
    assert closed.json()["lot"]["revision"] == 1
    assert replayed.status_code == 200
    assert replayed.json() == closed.json()
    _assert_conflict(stale)
    _assert_conflict(exceeds_remaining)
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
    finally:
        engine.dispose()
