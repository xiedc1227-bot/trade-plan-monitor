from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitInventorySnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.identity import explicit_alert_event_id
from trade_plan_monitor.notifications.models import build_explicit_alert_payload
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.position_service import PersistentPositionOperationService

SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
NOW = TARGET + timedelta(seconds=2)
BASE_URL = "http://127.0.0.1:8765"


class _RejectPlanService:
    async def save_plan_draft(self, **_kwargs):
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)


class _InertLifecycle:
    async def start(self):
        return SimpleNamespace(status=RuntimeServiceStatus.RUNNING, read_only=False)

    async def stop(self) -> None:
        return None


def _app(**services):
    return create_app(runtime_factory=_InertLifecycle, **services)


def _plan() -> ExplicitTradePlan:
    return ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "isolated-r09-transport",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "ISOLATED R09 TRANSPORT",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "TRADING_DAY", "trading_day": "2026-09-14"},
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
                        "type": "COMPLETED_CLOSE_IN_RANGE",
                        "low_fen": 980,
                        "high_fen": 1000,
                        "include_low": True,
                        "include_high": True,
                    },
                    "action": {"type": "BUY", "quantity": 100},
                    "confirmation": {
                        "kind": "COMPLETED_BAR_CLOSE",
                        "timeframe_minutes": 5,
                    },
                    "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
                    "safety_conditions": None,
                }
            ],
            "conflict_policy": {
                "trade_conflict": "BLOCK_BOTH",
                "risk_conflict": "RISK_ONLY",
            },
        }
    )


def _risk_sell_plan() -> ExplicitTradePlan:
    payload = _plan().model_dump(mode="python", round_trip=True)
    payload["rules"] = [
        {
            "rule_id": "sell-100",
            "condition": {
                "type": "COMPLETED_CLOSE_IN_RANGE",
                "low_fen": 1080,
                "high_fen": 1100,
                "include_low": True,
                "include_high": True,
            },
            "action": {
                "type": "SELL",
                "quantity": 100,
                "inventory_scope": "ALL_REGISTERED",
            },
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
            "safety_conditions": None,
        },
        {
            "rule_id": "risk-under-1200",
            "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            "action": {"type": "RISK_ALERT"},
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
            "safety_conditions": None,
        },
    ]
    payload["conflict_policy"]["risk_conflict"] = "RISK_WITH_SELL_BLOCK_BUY"
    return ExplicitTradePlan.model_validate(payload)


def _work(engine, *, now: datetime = NOW):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: now)


def test_plan_capability_reports_public_r12_activation() -> None:
    plan_json = dump_plan_json(_plan())
    with TestClient(_app(plan_service=_RejectPlanService()), base_url=BASE_URL) as client:
        capability = client.get("/api/v1/plan-capabilities")
        blocked = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "r09-v3-blocked"},
            json={
                "basePlanVersionId": None,
                "extractionId": None,
                "planJson": plan_json,
                "sourceText": "isolated trusted review only",
                "reviewIssues": [],
                "expectedRevision": 0,
            },
        )
        partial = json.loads(plan_json)
        partial["rules"][0]["repeat_policy"] = None
        invalid = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "r09-v3-partial"},
            json={
                "planJson": json.dumps(partial),
                "sourceText": "incomplete source-only draft",
                "reviewIssues": [],
                "expectedRevision": 0,
            },
        )

    assert capability.status_code == 200
    assert capability.json() == {
        "schemaVersion": 3,
        "executionMode": "EXPLICIT_RULES",
        "executionVersion": "explicit-rules-v1",
        "supportedActions": ["BUY", "SELL", "RISK_ALERT"],
        "publicActivationAvailable": False,
        "isolatedTrustedReviewOnly": True,
        "pendingRequirements": ["ORDINARY_PLAN_FORMS"],
    }
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert invalid.status_code == 503


def test_authoritative_inventory_http_distinguishes_unknown_and_confirmed_zero(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-http.sqlite3")
    upgrade_database(engine)
    try:
        with _work(engine, now=TARGET - timedelta(minutes=1)) as work:
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
        service = PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine),
            clock=lambda: NOW,
        )
        with TestClient(_app(position_service=service), base_url=BASE_URL) as client:
            unknown = client.get(
                "/api/v1/position-inventory",
                params={"symbol": "003043.SZ", "asOfTradeDate": "2026-09-14"},
            )
            confirmed = client.post(
                "/api/v1/position-inventory-confirmations",
                headers={"Idempotency-Key": "r09-confirm-zero"},
                json={
                    "symbol": "003043.SZ",
                    "asOfTradeDate": "2026-09-14",
                    "expectedRevision": 0,
                    "totalQuantity": 0,
                    "sellableQuantity": 0,
                    "includedLotIds": [],
                    "completeRegistration": True,
                },
            )

        assert unknown.status_code == 200
        assert unknown.json()["status"] == "UNKNOWN"
        assert unknown.json()["totalQuantity"] is None
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "KNOWN"
        assert confirmed.json()["totalQuantity"] == 0
        assert confirmed.json()["inventoryRevision"] == 1
    finally:
        engine.dispose()


def test_explicit_buy_alert_is_queryable_with_versioned_evidence(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-alert-http.sqlite3")
    upgrade_database(engine)
    plan = _plan()
    bar = FiveMinuteBar(
        symbol=plan.symbol,
        bar_end=TARGET,
        open_fen=990,
        high_fen=990,
        low_fen=990,
        close_fen=990,
        volume_shares=100,
        amount_yuan=Decimal("0"),
    )
    result = evaluate_explicit_rules(
        plan=plan,
        bars=(bar,),
        trading_calendar=(),
        target_bucket_end=TARGET,
        evaluated_at=NOW,
        activation_revision=1,
        inventory=ExplicitInventorySnapshot(status="KNOWN", total_qty=100, inventory_revision=1),
        rule_states=(),
    )
    signal = result.signal_intents[0]
    try:
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
        service = PersistentAlertOperationService(
            unit_of_work_factory=lambda: _work(engine), clock=lambda: NOW
        )
        with TestClient(_app(alert_service=service), base_url=BASE_URL) as client:
            response = client.get(
                "/api/v1/alerts",
                params={"symbol": plan.symbol, "signalType": "BUY"},
            )

        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 1
        assert page["items"][0]["eventId"] == str(event.event_id)
        assert page["items"][0]["payloadSchemaVersion"] == "explicit-rule-alert-v1"
        assert page["items"][0]["conditionEvidence"]["code"] == ("COMPLETED_CLOSE_IN_RANGE")
        assert "positionPrefill" not in page["items"][0]
    finally:
        engine.dispose()


def test_explicit_sell_and_risk_alerts_keep_type_quantity_and_rendering_through_api(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-multi-http.sqlite3")
    upgrade_database(engine)
    plan = _risk_sell_plan()
    bar = FiveMinuteBar(
        symbol=plan.symbol,
        bar_end=TARGET,
        open_fen=1080,
        high_fen=1080,
        low_fen=1080,
        close_fen=1080,
        volume_shares=100,
        amount_yuan=Decimal("0"),
    )
    result = evaluate_explicit_rules(
        plan=plan,
        bars=(bar,),
        trading_calendar=(),
        target_bucket_end=TARGET,
        evaluated_at=NOW,
        activation_revision=1,
        inventory=ExplicitInventorySnapshot(
            status="KNOWN",
            total_qty=100,
            sellable_qty=100,
            inventory_revision=1,
        ),
        rule_states=(),
    )
    try:
        with _work(engine) as work:
            for signal in result.signal_intents:
                work.alerts.enqueue_explicit(
                    build_explicit_alert_payload(
                        event_id=explicit_alert_event_id(signal),
                        plan=plan,
                        result=result,
                        signal=signal,
                    )
                )
            work.commit()
        service = PersistentAlertOperationService(
            unit_of_work_factory=lambda: _work(engine), clock=lambda: NOW
        )
        with TestClient(_app(alert_service=service), base_url=BASE_URL) as client:
            all_alerts = client.get("/api/v1/alerts", params={"symbol": plan.symbol})
            risk_only = client.get(
                "/api/v1/alerts",
                params={"symbol": plan.symbol, "signalType": "RISK_ALERT"},
            )

        assert all_alerts.status_code == risk_only.status_code == 200
        assert all_alerts.json()["total"] == 2
        by_type = {item["signalType"]: item for item in all_alerts.json()["items"]}
        assert by_type["SELL"]["quantity"] == 100
        assert "卖出提醒" in by_type["SELL"]["messageText"]
        assert by_type["RISK_ALERT"]["quantity"] is None
        assert "风险提醒" in by_type["RISK_ALERT"]["messageText"]
        assert risk_only.json()["total"] == 1
        assert risk_only.json()["items"][0]["signalType"] == "RISK_ALERT"
    finally:
        engine.dispose()


def test_inventory_closure_command_debits_opening_balance_without_active_plan(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "opening-closure-http.sqlite3")
    upgrade_database(engine)
    try:
        with _work(engine, now=TARGET - timedelta(minutes=1)) as work:
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
            inventory = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=TARGET.date(),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            opening_id = inventory.opening_balances[0].id
            work.commit()
        service = PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine),
            clock=lambda: NOW,
        )
        payload = {
            "sourceType": "OPENING_BALANCE",
            "sourceId": opening_id,
            "quantity": 100,
            "tradeDate": TARGET.date().isoformat(),
            "expectedRevision": 0,
        }
        with TestClient(_app(position_service=service), base_url=BASE_URL) as client:
            closed = client.post(
                "/api/v1/position-inventory-closures",
                headers={"Idempotency-Key": "opening-close-1"},
                json=payload,
            )
            replay = client.post(
                "/api/v1/position-inventory-closures",
                headers={"Idempotency-Key": "opening-close-1"},
                json=payload,
            )
            current = client.get(
                "/api/v1/position-inventory",
                params={
                    "symbol": "003043.SZ",
                    "asOfTradeDate": TARGET.date().isoformat(),
                },
            )

        assert closed.status_code == 200, closed.text
        assert replay.json() == closed.json()
        assert closed.json() == {
            "sourceType": "OPENING_BALANCE",
            "sourceId": opening_id,
            "symbol": "003043.SZ",
            "appliedQuantity": 100,
            "tradeDate": TARGET.date().isoformat(),
            "beforeRemainingQuantity": 100,
            "afterRemainingQuantity": 0,
            "revision": 1,
        }
        assert current.json()["status"] == "KNOWN"
        assert current.json()["totalQuantity"] == 0
        assert current.json()["sellableQuantity"] == 0
    finally:
        engine.dispose()


def test_inventory_closure_command_debits_registered_core_lot(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "lot-closure-http.sqlite3")
    upgrade_database(engine)
    try:
        with _work(engine, now=TARGET - timedelta(minutes=1)) as work:
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
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=100,
                acquired_trade_date=date(2026, 9, 11),
                cost_fen=990,
                board_lot=100,
                max_position_qty=300,
            )
            unconfirmed = work.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=TARGET.date(),
                cutoff=TARGET,
            )
            work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=TARGET.date(),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(lot.id,),
                complete_registration=True,
                expected_revision=unconfirmed.inventory_revision,
            )
            work.commit()
        service = PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine),
            clock=lambda: NOW,
        )
        with TestClient(_app(position_service=service), base_url=BASE_URL) as client:
            closed = client.post(
                "/api/v1/position-inventory-closures",
                headers={"Idempotency-Key": "core-close-1"},
                json={
                    "sourceType": "LOT",
                    "sourceId": lot.id,
                    "quantity": 100,
                    "tradeDate": TARGET.date().isoformat(),
                    "expectedRevision": 0,
                },
            )
            current = client.get(
                "/api/v1/position-inventory",
                params={
                    "symbol": "003043.SZ",
                    "asOfTradeDate": TARGET.date().isoformat(),
                },
            )

        assert closed.status_code == 200, closed.text
        assert closed.json()["sourceType"] == "LOT"
        assert closed.json()["sourceId"] == lot.id
        assert closed.json()["afterRemainingQuantity"] == 0
        assert current.json()["status"] == "KNOWN"
        assert current.json()["totalQuantity"] == 0
    finally:
        engine.dispose()
