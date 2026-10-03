"""Offline evidence for the independent inventory and reminder-only source contracts."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.integration.current_pipeline_fixture import (
    PIPELINE_NOW,
    current_pipeline_fixture,
)
from tests.integration.current_pipeline_fixture import (
    TARGET as PIPELINE_TARGET,
)
from tests.integration.test_explicit_runtime_production import _seed_active, _three_rule_plan

from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.daily_models import DailyAlertEvent
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeCycleStatus,
    ExplicitRuntimeEvaluationService,
)
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.position_service import PersistentPositionOperationService

TARGET = datetime(2026, 9, 14, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
NOW = TARGET + timedelta(seconds=2)
SYMBOL = "003043.SZ"
BASE_URL = "http://127.0.0.1:8765"
INVENTORY_QUERY = {"symbol": SYMBOL, "asOfTradeDate": "2026-09-14"}
CONFIRMATION = {
    "symbol": SYMBOL,
    "asOfTradeDate": "2026-09-14",
    "expectedRevision": 0,
    "totalQuantity": 100,
    "sellableQuantity": 100,
    "includedLotIds": [],
    "completeRegistration": True,
}


class _InertRuntime:
    async def start(self):
        return SimpleNamespace(status=RuntimeServiceStatus.RUNNING, read_only=False)

    async def stop(self) -> None:
        return None


def _work(engine, *, now=NOW):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: now)


def _app(engine, *, now=NOW):
    return create_app(
        runtime_factory=_InertRuntime,
        position_service=PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine, now=now), clock=lambda: now
        ),
        alert_service=PersistentAlertOperationService(
            unit_of_work_factory=lambda: _work(engine, now=now), clock=lambda: now
        ),
    )


def _seed_calendar(engine) -> None:
    with _work(engine) as work:
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
        work.commit()


def _bars(close_fen: int) -> tuple[FiveMinuteBar, ...]:
    return tuple(
        FiveMinuteBar(
            symbol=SYMBOL,
            bar_end=TARGET - timedelta(minutes=(5 - index) * 5),
            open_fen=close_fen,
            high_fen=close_fen,
            low_fen=close_fen,
            close_fen=close_fen,
            volume_shares=150 if index == 5 else 100,
            amount_yuan=Decimal("0"),
        )
        for index in range(6)
    )


def test_historical_inventory_read_survives_restart_with_writes_removed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "independent-inventory.sqlite3"
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
        _seed_calendar(engine)
        with TestClient(_app(engine), base_url=BASE_URL) as client:
            unknown = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            assert unknown.status_code == 200
            assert unknown.json()["status"] == "UNKNOWN"
            assert unknown.json()["totalQuantity"] is None
            assert unknown.json()["sellableQuantity"] is None
            assert unknown.json()["inventoryRevision"] == 0
            assert unknown.json()["openingBalances"] == []
            removed_write = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-confirm"},
                json=CONFIRMATION,
            )
            assert removed_write.status_code == 404
        with _work(engine) as work:
            work.positions.confirm_inventory(
                symbol=SYMBOL, as_of_trade_date=TARGET.date(),
                total_quantity=100, sellable_quantity=100, included_lot_ids=(),
                complete_registration=True, expected_revision=0,
            )
            work.commit()
        with TestClient(_app(engine), base_url=BASE_URL) as client:
            confirmed = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            replay = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-confirm"},
                json=CONFIRMATION,
            )
            assert confirmed.status_code == 200
            assert replay.status_code == 404
            first = confirmed.json()
            assert first["status"] == "KNOWN"
            assert first["totalQuantity"] == first["sellableQuantity"] == 100
            assert first["inventoryRevision"] == 1
            assert len(first["openingBalances"]) == 1
            first_bytes = confirmed.content
    finally:
        engine.dispose()

    restarted = create_sqlite_engine(database_path)
    try:
        with TestClient(_app(restarted), base_url=BASE_URL) as client:
            replay = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-confirm"},
                json=CONFIRMATION,
            )
            assert replay.status_code == 404
            reconfirmed = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-reconfirm"},
                json={**CONFIRMATION, "expectedRevision": 1},
            )
            assert reconfirmed.status_code == 404
            readback = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            assert readback.status_code == 200
            assert readback.content == first_bytes
    finally:
        restarted.dispose()


def test_pure_risk_runtime_commits_without_registering_unknown_inventory(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "unknown-inventory-risk.sqlite3")
    try:
        upgrade_database(engine)
        plan = _three_rule_plan()
        # Trusted runtime fixture only: this does not exercise or open public activation.
        _seed_active(engine, plan)
        _seed_calendar(engine)
        with _work(engine) as work:
            before = work.positions.inventory_snapshot(
                SYMBOL, as_of_trade_date=TARGET.date(), cutoff=NOW
            )
            for bar in _bars(949):
                work.history.upsert_five_minute(**bar.model_dump())
            work.commit()
        assert before.status == "UNKNOWN"
        assert before.total_qty is None
        assert before.sellable_qty is None

        cycle = ExplicitRuntimeEvaluationService(lambda: _work(engine)).run_intraday(
            plan=plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        assert cycle.status is ExplicitRuntimeCycleStatus.COMMITTED
        assert cycle.evaluation_result.inventory_revision is None
        assert len(cycle.committed_events) == 1
        assert cycle.committed_events[0].signal_type == "RISK_ALERT"
        assert cycle.committed_events[0].quantity is None
        with _work(engine) as work:
            after = work.positions.inventory_snapshot(
                SYMBOL, as_of_trade_date=TARGET.date(), cutoff=NOW
            )
        assert after == before
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("signal_type", "close_fen", "quantity"),
    (("BUY", 990, 100), ("SELL", 1080, 100), ("RISK_ALERT", 949, None)),
)
def test_current_alert_and_acknowledgement_leave_both_inventories_unchanged(
    tmp_path: Path,
    monkeypatch,
    signal_type: str,
    close_fen: int,
    quantity: int | None,
) -> None:
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60, current_close_fen=close_fen,
        )
        try:
            with work() as transaction:
                transaction.positions.confirm_inventory(
                    symbol=SYMBOL, as_of_trade_date=TARGET.date(),
                    total_quantity=100, sellable_quantity=100, included_lot_ids=(),
                    complete_registration=True, expected_revision=0,
                )
                simulation_before = transaction.daily.get("simulation-position-" + SYMBOL)
                transaction.commit()
            assert simulation_before is not None
            with TestClient(_app(engine, now=PIPELINE_NOW), base_url=BASE_URL) as client:
                before = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
                assert before.status_code == 200
                assert before.json()["status"] == "KNOWN"
                assert before.json()["totalQuantity"] == 100
                removed_write = client.post(
                    "/api/v1/position-inventory-confirmations",
                    headers={"Idempotency-Key": f"opening-{signal_type}"},
                    json=CONFIRMATION,
                )
                assert removed_write.status_code == 404
            await pipeline.refresh_references(PIPELINE_TARGET.date())
            await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=PIPELINE_TARGET.date(), due_at=PIPELINE_NOW,
                bar_end=PIPELINE_TARGET,
            ))
            with work() as transaction:
                events, total = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=None if signal_type == "RISK_ALERT" else signal_type,
                    acknowledged=None, start_at=None, end_at=None, offset=0, limit=10,
                )
                simulation_after_alert = transaction.daily.get("simulation-position-" + SYMBOL)
            assert total == 1
            event = events[0]
            assert type(event) is DailyAlertEvent
            assert event.signal_type == ("REMINDER" if signal_type == "RISK_ALERT" else signal_type)
            assert event.alert_kind == ("RISK_ALERT" if signal_type == "RISK_ALERT" else None)
            assert event.quantity == quantity
            assert simulation_after_alert == simulation_before

            with TestClient(_app(engine, now=PIPELINE_NOW), base_url=BASE_URL) as client:
                after_alert = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
                assert after_alert.content == before.content
                command = {"alertId": str(event.event_id), "expectedRevision": 0}
                acknowledged = client.post(
                    "/api/v1/alert-acknowledgements",
                    headers={"Idempotency-Key": f"ack-{signal_type}"}, json=command,
                )
                replay = client.post(
                    "/api/v1/alert-acknowledgements",
                    headers={"Idempotency-Key": f"ack-{signal_type}"}, json=command,
                )
                assert acknowledged.status_code == replay.status_code == 200
                assert replay.json() == acknowledged.json()
                assert acknowledged.json()["acknowledgedAt"] is not None
                assert acknowledged.json()["revision"] == 1
                already_acknowledged = client.post(
                    "/api/v1/alert-acknowledgements",
                    headers={"Idempotency-Key": f"ack-again-{signal_type}"},
                    json={"alertId": str(event.event_id), "expectedRevision": 1},
                )
                assert already_acknowledged.status_code == 200
                assert already_acknowledged.json() == acknowledged.json()
                after_ack = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
                assert after_ack.content == before.content
            with work() as transaction:
                assert transaction.daily.get("simulation-position-" + SYMBOL) == simulation_before
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
