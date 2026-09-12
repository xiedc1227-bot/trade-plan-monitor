"""WEBF10 coverage for the production alert-center composition."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DecisionZone,
    EvidenceFact,
    EvidenceUnit,
    NextStep,
    NextStepCode,
    SignalIntent,
)
from trade_plan_monitor.domain.plan_models import OfficialCloseBelowLevelCondition
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertPayload, AlertSeverity
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    MonitorEvent,
    PositionLot,
    RequestIdempotency,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_composition import (
    MonitorWebComposition,
    create_monitor_composition,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FIRST_AT = datetime(2026, 9, 3, 10, 5, tzinfo=_SHANGHAI)
_SECOND_AT = datetime(2026, 9, 3, 10, 10, tzinfo=_SHANGHAI)
_SYMBOL = "003043.SZ"


@pytest.fixture(autouse=True)
def _reject_provider_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production-composition tests offline even if startup changes later."""

    from tushare.pro.client import DataApi

    def reject(_client: object, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("WEBF10 tests must not request an external provider")

    monkeypatch.setattr(DataApi, "query", reject)


def _alert_payload(identity: int, *, evaluated_at: datetime) -> AlertPayload:
    evidence = ConditionEvidence(
        condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=6_070,
                unit=EvidenceUnit.FEN,
            ),
        ),
    )
    signal = SignalIntent(
        signal_type=ActionableSignalType.RISK_BREACH,
        plan_hash="a" * 64,
        symbol=_SYMBOL,
        trading_date=evaluated_at.date(),
        cause_id=f"risk-{identity}",
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY),
    )
    return AlertPayload(
        event_id=UUID(int=identity),
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash=signal.plan_hash,
        symbol=signal.symbol,
        name="华亚智能",
        signal_type=signal.signal_type,
        severity=AlertSeverity.RISK,
        trading_date=signal.trading_date,
        cause_id=signal.cause_id,
        evaluated_at=evaluated_at,
        market_data_at=evaluated_at,
        data_age_seconds=0,
        price_fen=6_070,
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        zone=DecisionZone.BELOW_RISK,
        relevant_zone=None,
        risk_line_fen=6_080,
        next_step=signal.next_step,
    )


def _seed_alerts(database_path: Path) -> tuple[str, str]:
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
        session_factory = create_session_factory(engine)
        with SqlAlchemyUnitOfWork(
            session_factory,
            clock=lambda: _FIRST_AT + timedelta(seconds=1),
        ) as work:
            first = work.alerts.enqueue(_alert_payload(1, evaluated_at=_FIRST_AT))
            work.commit()
        with SqlAlchemyUnitOfWork(
            session_factory,
            clock=lambda: _SECOND_AT + timedelta(seconds=1),
        ) as work:
            second = work.alerts.enqueue(_alert_payload(2, evaluated_at=_SECOND_AT))
            work.commit()
        with SqlAlchemyUnitOfWork(
            session_factory,
            clock=lambda: _SECOND_AT + timedelta(seconds=2),
        ) as work:
            work.alerts.acknowledge(first.event_id)
            work.commit()
        return str(first.event_id), str(second.event_id)
    finally:
        engine.dispose()


def _production_alert_app(
    tmp_path: Path,
) -> tuple[FastAPI, MonitorWebComposition, Path, str, str]:
    config_path = tmp_path / "config" / "app.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}\n", encoding="utf-8")
    database_path = tmp_path / "state" / "monitor.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    first_id, second_id = _seed_alerts(database_path)
    composition = create_monitor_composition(
        config_path=config_path,
        database_path=database_path,
    )
    return (
        create_app(runtime_factory=lambda: composition),
        composition,
        database_path,
        first_id,
        second_id,
    )


def test_default_monitor_composition_queries_filtered_canonical_alerts(
    tmp_path: Path,
) -> None:
    app, composition, _database_path, _first_id, second_id = _production_alert_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert composition.alert_service is not None
        assert app.state.alert_operation_service is composition.alert_service
        response = client.get(
            "/api/v1/alerts",
            params={
                "symbol": _SYMBOL,
                "signalType": "RISK_BREACH",
                "acknowledged": "false",
                "startAt": _SECOND_AT.isoformat(),
                "endAt": (_SECOND_AT + timedelta(minutes=1)).isoformat(),
                "offset": 0,
                "limit": 1,
            },
        )

    assert response.status_code == 200
    page = response.json()
    assert page["symbol"] == _SYMBOL
    assert page["signalType"] == "RISK_BREACH"
    assert page["acknowledged"] is False
    assert page["total"] == 1
    assert [item["eventId"] for item in page["items"]] == [second_id]
    assert page["items"][0]["matchedConditions"][0]["code"] == (
        "OFFICIAL_CLOSE_BELOW_LEVEL"
    )
    assert page["items"][0]["currentActionable"] is False
    assert page["items"][0]["positionPrefill"] is None
    assert not hasattr(app.state, "alert_operation_service")


def test_alert_acknowledgement_is_atomic_replayable_and_position_isolated(
    tmp_path: Path,
) -> None:
    app, _composition, database_path, _first_id, second_id = _production_alert_app(tmp_path)
    command = {"alertId": second_id, "expectedRevision": 0}

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        acknowledged = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-1"},
            json=command,
        )
        replayed = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-1"},
            json=command,
        )
        already_acknowledged = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-noop"},
            json={"alertId": second_id, "expectedRevision": 1},
        )
        stale = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-stale"},
            json=command,
        )
        key_reuse = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-1"},
            json={"alertId": second_id, "expectedRevision": 1},
        )
        missing = client.post(
            "/api/v1/alert-acknowledgements",
            headers={"Idempotency-Key": "webf10-ack-missing"},
            json={"alertId": str(UUID(int=999)), "expectedRevision": 0},
        )
        diagnostic = client.post(
            "/api/v1/diagnostic-evaluations",
            headers={"Idempotency-Key": "webf10-diagnostic"},
            json={
                "symbol": _SYMBOL,
                "evaluationKind": "OFFICIAL_CLOSE",
                "bucketEnd": None,
                "officialTradeDate": "2026-09-03",
                "expectedRevision": 0,
            },
        )

    assert acknowledged.status_code == 200
    assert acknowledged.json()["revision"] == 1
    assert acknowledged.json()["acknowledgedAt"] is not None
    assert replayed.status_code == 200
    assert replayed.json() == acknowledged.json()
    assert already_acknowledged.status_code == 200
    assert already_acknowledged.json() == acknowledged.json()
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"
    assert key_reuse.status_code == 422
    assert key_reuse.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert diagnostic.status_code == 503
    assert diagnostic.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    engine = create_sqlite_engine(database_path)
    try:
        with create_session_factory(engine)() as session:
            assert session.scalar(select(func.count()).select_from(PositionLot)) == 0
            assert session.scalar(select(func.count()).select_from(RequestIdempotency)) == 2
            alert_audits = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "ALERT_EVENT")
            ).all()
            event_types = session.scalars(
                select(MonitorEvent.event_type).order_by(MonitorEvent.sequence)
            ).all()
        assert [entry.action for entry in alert_audits] == [
            "ALERT_ACKNOWLEDGED",
            "ALERT_ACKNOWLEDGED",
        ]
        assert event_types == [
            "alert.created",
            "alert.created",
            "alert.acknowledged",
            "alert.acknowledged",
        ]
    finally:
        engine.dispose()
