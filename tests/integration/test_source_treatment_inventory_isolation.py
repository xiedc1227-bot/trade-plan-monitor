"""Offline evidence for the independent inventory and reminder-only source contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_explicit_runtime_production import _seed_active, _three_rule_plan

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitInventorySnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.identity import explicit_alert_event_id
from trade_plan_monitor.notifications.models import build_explicit_alert_payload
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeCycleStatus,
    ExplicitRuntimeEvaluationService,
)
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
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


def _work(engine):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW)


def _app(engine):
    return create_app(
        runtime_factory=_InertRuntime,
        position_service=PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine), clock=lambda: NOW
        ),
        alert_service=PersistentAlertOperationService(
            unit_of_work_factory=lambda: _work(engine), clock=lambda: NOW
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


def test_independent_inventory_http_retry_restart_and_reconfirmation_never_double_count(
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
            confirmed = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-confirm"},
                json=CONFIRMATION,
            )
            replay = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-confirm"},
                json=CONFIRMATION,
            )
            assert confirmed.status_code == replay.status_code == 200
            first = confirmed.json()
            assert replay.json() == first
            assert first["status"] == "KNOWN"
            assert first["totalQuantity"] == first["sellableQuantity"] == 100
            assert first["inventoryRevision"] == 1
            assert len(first["openingBalances"]) == 1
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
            assert replay.status_code == 200
            assert replay.json() == first
            reconfirmed = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "source-inventory-reconfirm"},
                json={**CONFIRMATION, "expectedRevision": 1},
            )
            assert reconfirmed.status_code == 200, reconfirmed.text
            current = reconfirmed.json()
            assert current["inventoryRevision"] == 2
            assert current["confirmationId"] != first["confirmationId"]
            assert current["totalQuantity"] == current["sellableQuantity"] == 100
            assert current["openingBalances"] == first["openingBalances"]
            readback = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            assert readback.status_code == 200
            assert readback.json() == current
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
def test_explicit_reminder_and_acknowledgement_leave_registered_inventory_unchanged(
    tmp_path: Path,
    signal_type: str,
    close_fen: int,
    quantity: int | None,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"reminder-only-{signal_type}.sqlite3")
    try:
        upgrade_database(engine)
        _seed_calendar(engine)
        plan = _three_rule_plan()
        with TestClient(_app(engine), base_url=BASE_URL) as client:
            confirmed = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": f"opening-{signal_type}"},
                json=CONFIRMATION,
            )
            assert confirmed.status_code == 200, confirmed.text
            before = confirmed.json()
            result = evaluate_explicit_rules(
                plan=plan,
                bars=_bars(close_fen),
                trading_calendar=(),
                target_bucket_end=TARGET,
                evaluated_at=NOW,
                activation_revision=1,
                inventory=ExplicitInventorySnapshot(
                    status=before["status"],
                    total_qty=before["totalQuantity"],
                    sellable_qty=before["sellableQuantity"],
                    inventory_revision=before["inventoryRevision"],
                ),
                rule_states=(),
            )
            assert len(result.signal_intents) == 1
            signal = result.signal_intents[0]
            with _work(engine) as work:
                event = work.alerts.enqueue_explicit(
                    build_explicit_alert_payload(
                        event_id=explicit_alert_event_id(signal),
                        plan=plan,
                        result=result,
                        signal=signal,
                    )
                )
                work.commit()
            assert event.signal_type == signal_type
            assert event.quantity == quantity
            after_reminder = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            assert after_reminder.status_code == 200
            assert after_reminder.json() == before

            command = {"alertId": str(event.event_id), "expectedRevision": 0}
            acknowledged = client.post(
                "/api/v1/alert-acknowledgements",
                headers={"Idempotency-Key": f"ack-{signal_type}"},
                json=command,
            )
            replay = client.post(
                "/api/v1/alert-acknowledgements",
                headers={"Idempotency-Key": f"ack-{signal_type}"},
                json=command,
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
            after_acknowledgement = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY)
            assert after_acknowledgement.status_code == 200
            assert after_acknowledgement.json() == before
    finally:
        engine.dispose()
