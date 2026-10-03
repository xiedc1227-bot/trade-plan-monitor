"""Regression coverage for persisted manual-event-risk confirmations."""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.runtime.production_context import _manual_event_risk_for_plan
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.manual_event_risk_service import (
    PersistentManualEventRiskOperationService,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_NOW = datetime(2026, 9, 12, 10, 5, tzinfo=_SHANGHAI)
_SYMBOL = "003043.SZ"
_PLAN_HASH = "a" * 64


def _work_factory(database: Path) -> tuple[object, callable]:
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    session_factory = create_session_factory(engine)
    return engine, lambda: SqlAlchemyUnitOfWork(session_factory, clock=lambda: _NOW)


def test_manual_event_risk_is_three_state_scoped_expiring_and_audited(tmp_path: Path) -> None:
    """Only current, explicit confirmations may become Boolean production input."""

    engine, work_factory = _work_factory(tmp_path / "manual-event-risk.sqlite3")
    try:
        with work_factory() as work:
            assert (
                _manual_event_risk_for_plan(
                    work.manual_event_risk.get(_SYMBOL),
                    plan_hash=_PLAN_HASH,
                    trade_date=date(2026, 9, 12),
                    cutoff=_NOW,
                )
                is None
            )
            clear = work.manual_event_risk.upsert(
                symbol=_SYMBOL,
                plan_hash=_PLAN_HASH,
                status=ManualEventRiskStatus.CLEAR,
                expires_on=date(2026, 9, 12),
                expected_revision=0,
            )
            work.commit()

        assert clear.revision == 1
        assert clear.confirmed_at == _NOW
        assert (
            _manual_event_risk_for_plan(
                clear,
                plan_hash=_PLAN_HASH,
                trade_date=date(2026, 9, 12),
                cutoff=_NOW,
            )
            is False
        )
        assert (
            _manual_event_risk_for_plan(
                clear,
                plan_hash="b" * 64,
                trade_date=date(2026, 9, 12),
                cutoff=_NOW,
            )
            is None
        )
        assert (
            _manual_event_risk_for_plan(
                clear,
                plan_hash=_PLAN_HASH,
                trade_date=date(2026, 9, 13),
                cutoff=_NOW,
            )
            is None
        )

        with work_factory() as work:
            risky = work.manual_event_risk.upsert(
                symbol=_SYMBOL,
                plan_hash=_PLAN_HASH,
                status=ManualEventRiskStatus.RISK_PRESENT,
                expires_on=date(2026, 9, 13),
                expected_revision=clear.revision,
            )
            work.commit()

        assert risky.revision == 2
        assert (
            _manual_event_risk_for_plan(
                risky,
                plan_hash=_PLAN_HASH,
                trade_date=date(2026, 9, 12),
                cutoff=_NOW,
            )
            is True
        )
        with create_session_factory(engine)() as session:
            audits = session.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "MANUAL_EVENT_RISK")
                .order_by(AuditLog.created_at)
            ).all()
        assert [audit.action for audit in audits] == [
            "MANUAL_EVENT_RISK_CONFIRMED",
            "MANUAL_EVENT_RISK_CONFIRMED",
        ]
    finally:
        engine.dispose()


def test_historical_manual_event_risk_api_exposes_unknown_reason() -> None:
    """The ordinary local API is the only browser entrypoint for this state."""

    class _Service:
        async def get_manual_event_risk(self, *, symbol: str) -> object:
            assert symbol == _SYMBOL
            return {
                "symbol": symbol,
                "planVersionId": None,
                "status": "UNKNOWN",
                "reason": "NO_ACTIVE_PLAN",
                "expiresOn": None,
                "confirmedAt": None,
                "revision": 0,
            }

    client = TestClient(create_app(manual_event_risk_service=_Service()))
    unknown = client.get("/api/v1/manual-event-risk", params={"symbol": _SYMBOL})
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "UNKNOWN"
    assert unknown.json()["reason"] == "NO_ACTIVE_PLAN"


def test_manual_event_risk_service_survives_restart_and_fails_closed_on_scope_drift(
    tmp_path: Path,
) -> None:
    """The production storage boundary owns plan scope, expiration, and idempotency."""

    database = tmp_path / "manual-event-risk-service.sqlite3"
    engine, work_factory = _work_factory(database)
    plan = load_plan_yaml(
        (Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml").read_text(
            encoding="utf-8"
        )
    )
    try:
        with work_factory() as work:
            work.plans.save_draft(plan, source_text="synthetic manual event risk test")
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()

        service = PersistentManualEventRiskOperationService(
            unit_of_work_factory=work_factory,
            clock=lambda: _NOW,
        )
        unknown = asyncio.run(service.get_manual_event_risk(symbol=plan.symbol))
        assert unknown.status.value == "UNKNOWN"
        assert unknown.reason is not None and unknown.reason.value == "MISSING_CONFIRMATION"

        # Seed immutable historical evidence through its repository, not a current Web mutation.
        with work_factory() as work:
            work.manual_event_risk.upsert(symbol=plan.symbol, plan_hash=plan_sha256(plan),
                status=ManualEventRiskStatus.CLEAR, expires_on=_NOW.date(), expected_revision=0)
            work.commit()
        confirmed = asyncio.run(service.get_manual_event_risk(symbol=plan.symbol))
        assert confirmed.status.value == "CLEAR"
        assert confirmed.revision == 1

        restarted = PersistentManualEventRiskOperationService(
            unit_of_work_factory=work_factory,
            clock=lambda: _NOW,
        )
        restarted_view = asyncio.run(restarted.get_manual_event_risk(symbol=plan.symbol))
        assert restarted_view.status.value == "CLEAR"
        assert restarted_view == confirmed

        with work_factory() as work:
            work.manual_event_risk.upsert(
                symbol=plan.symbol,
                plan_hash="b" * 64,
                status=ManualEventRiskStatus.CLEAR,
                expires_on=_NOW.date(),
                expected_revision=confirmed.revision,
            )
            work.commit()
        changed = asyncio.run(restarted.get_manual_event_risk(symbol=plan.symbol))
        assert changed.status.value == "UNKNOWN"
        assert changed.reason is not None and changed.reason.value == "PLAN_CHANGED"

        later = PersistentManualEventRiskOperationService(
            unit_of_work_factory=work_factory,
            clock=lambda: _NOW + timedelta(days=1),
        )
        with work_factory() as work:
            work.manual_event_risk.upsert(
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status=ManualEventRiskStatus.CLEAR,
                expires_on=_NOW.date(),
                expected_revision=changed.revision,
            )
            work.commit()
        expired = asyncio.run(later.get_manual_event_risk(symbol=plan.symbol))
        assert expired.status.value == "UNKNOWN"
        assert expired.reason is not None and expired.reason.value == "EXPIRED"
    finally:
        engine.dispose()
