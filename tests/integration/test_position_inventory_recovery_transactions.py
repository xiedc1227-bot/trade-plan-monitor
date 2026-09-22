"""Inventory evidence and application receipts share one durable transaction."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tests.integration.test_position_production_composition import _seed_active_plan

from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AuditLog,
    MonitorEvent,
    MonitorSequence,
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionLot,
    PositionOpeningBalance,
    RequestIdempotency,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.position_service import PersistentPositionOperationService
from trade_plan_monitor.web.routers.positions import (
    PositionInventoryClosureCommand,
    PositionInventoryConfirmationCommand,
    PositionLotClosureCommand,
    PositionLotCreateCommand,
)
from trade_plan_monitor.web.schemas import MutationContext

_DATE = date(2026, 9, 4)
_NOW = datetime(2026, 9, 4, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
_CASES = (
    "confirm_zero",
    "confirm_opening",
    "reconfirm",
    "buy",
    "reduce_lot",
    "close_lot",
    "reduce_opening",
    "close_opening",
)
_TABLES = (
    PositionLot,
    PositionOpeningBalance,
    PositionInventoryConfirmation,
    PositionInventoryState,
    AuditLog,
    MonitorEvent,
    MonitorSequence,
    RequestIdempotency,
)


def _state(engine):
    with engine.connect() as connection:
        return {
            model.__tablename__: connection.execute(
                select(model.__table__).order_by(*model.__table__.primary_key.columns)
            ).all()
            for model in _TABLES
        }


def _prepare(engine, case):
    """Seed preconditions independently of the service request being verified."""
    revision = 0
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _NOW) as work:
        if case in {"buy", "reconfirm", "reduce_opening", "close_opening"}:
            snapshot = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=_DATE,
                total_quantity=0 if case == "buy" else 200,
                sellable_quantity=0 if case == "buy" else 200,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            revision = snapshot.inventory_revision
        if case in {"reduce_lot", "close_lot"}:
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=200,
                acquired_trade_date=date(2026, 9, 3),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=200,
            )
            work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=_DATE,
                total_quantity=200,
                sellable_quantity=200,
                included_lot_ids=(lot.id,),
                complete_registration=True,
                expected_revision=1,
            )
        work.commit()

    if case in {"confirm_zero", "confirm_opening", "reconfirm"}:
        quantity = 0 if case == "confirm_zero" else 200
        return "confirm_position_inventory", PositionInventoryConfirmationCommand(
            symbol="003043.SZ",
            as_of_trade_date=_DATE,
            expected_revision=revision,
            total_quantity=quantity,
            sellable_quantity=quantity,
            included_lot_ids=(),
            complete_registration=True,
        )
    if case == "buy":
        return "record_position_lot", PositionLotCreateCommand(
            symbol="003043.SZ",
            bucket="CORE",
            quantity=100,
            acquired_trade_date=_DATE,
            cost_fen=6400,
            expected_revision=0,
        )
    quantity = 100 if case.startswith("reduce") else 200
    if case.endswith("lot"):
        return "close_position_lot", PositionLotClosureCommand(
            lot_id=lot.id,
            quantity=quantity,
            trade_date=_DATE,
            expected_revision=0,
        )
    return "close_position_inventory", PositionInventoryClosureCommand(
        source_type="OPENING_BALANCE",
        source_id=snapshot.opening_balances[0].id,
        quantity=quantity,
        trade_date=_DATE,
        expected_revision=0,
    )


def _service(engine, work_type=SqlAlchemyUnitOfWork):
    return PersistentPositionOperationService(
        unit_of_work_factory=lambda: work_type(
            create_session_factory(engine),
            clock=lambda: _NOW,
        ),
        clock=lambda: _NOW,
    )


def _assert_new_evidence(session, previous_ids, case):
    rows = session.scalars(select(AuditLog)).all()
    added = [row for row in rows if row.id not in previous_ids]
    confirmation = case in {"confirm_zero", "confirm_opening", "reconfirm"}
    assert len(added) == (1 if confirmation else 2)
    action = "POSITION_INVENTORY_CONFIRMED" if confirmation else "POSITION_INVENTORY_CHANGED"
    evidence_rows = [row for row in added if row.action == action]
    assert len(evidence_rows) == 1
    evidence = json.loads(evidence_rows[0].details_json)["recoveryEvidence"]
    assert evidence["schemaVersion"] == 1
    if not confirmation:
        assert evidence["syncOutcome"] == "SYNCED"
        assert evidence["sourceAudit"]["id"] in {row.id for row in added}


@pytest.mark.parametrize("case", _CASES)
def test_restarted_service_replays_without_duplicate_inventory_evidence(tmp_path: Path, case):
    path = tmp_path / "replay.sqlite3"
    _seed_active_plan(path)
    engine = create_sqlite_engine(path)
    try:
        method, command = _prepare(engine, case)
        with create_session_factory(engine)() as session:
            previous_ids = set(session.scalars(select(AuditLog.id)).all())
        context = MutationContext(idempotency_key="inventory-replay", request_id="a" * 32)
        first = asyncio.run(getattr(_service(engine), method)(command=command, context=context))
        with create_session_factory(engine)() as session:
            _assert_new_evidence(session, previous_ids, case)
            receipt = session.get(RequestIdempotency, context.idempotency_key)
            assert receipt.status == "COMPLETED"
            assert receipt.response_json is not None
        persisted = _state(engine)
        engine.dispose()
        engine = create_sqlite_engine(path)
        replay = asyncio.run(getattr(_service(engine), method)(command=command, context=context))
        assert replay == first
        assert _state(engine) == persisted
    finally:
        engine.dispose()


@pytest.mark.parametrize("case", _CASES)
def test_failure_after_inventory_evidence_and_receipt_rolls_back_everything(tmp_path: Path, case):
    path = tmp_path / "rollback.sqlite3"
    _seed_active_plan(path)
    engine = create_sqlite_engine(path)
    try:
        method, command = _prepare(engine, case)
        before = _state(engine)
        with create_session_factory(engine)() as session:
            previous_ids = set(session.scalars(select(AuditLog.id)).all())
        context = MutationContext(idempotency_key="inventory-rollback", request_id="b" * 32)

        class FailBeforeCommit(SqlAlchemyUnitOfWork):
            def commit(self):
                session = self._require_session()
                session.flush()
                _assert_new_evidence(session, previous_ids, case)
                receipt = session.get(RequestIdempotency, context.idempotency_key)
                assert receipt.status == "COMPLETED"
                assert receipt.response_json is not None
                raise RuntimeError("injected after evidence and receipt")

        with pytest.raises(RuntimeError, match="injected after evidence and receipt"):
            asyncio.run(
                getattr(_service(engine, FailBeforeCommit), method)(
                    command=command,
                    context=context,
                )
            )
        assert _state(engine) == before
        # The same key remains usable: no orphan receipt, sequence or revision escaped.
        asyncio.run(getattr(_service(engine), method)(command=command, context=context))
        with create_session_factory(engine)() as session:
            _assert_new_evidence(session, previous_ids, case)
    finally:
        engine.dispose()


@pytest.mark.parametrize("case", ("buy", "reduce_lot", "reduce_opening"))
def test_inventory_evidence_id_collision_preserves_existing_row_and_rolls_back(
    tmp_path: Path, case
):
    path = tmp_path / "collision.sqlite3"
    _seed_active_plan(path)
    engine = create_sqlite_engine(path)
    try:
        method, command = _prepare(engine, case)
        source_id = "d" * 32
        collision_id = str(
            uuid5(
                NAMESPACE_URL,
                "trade-plan-monitor:inventory-recovery:v1:" + source_id,
            )
        )
        with create_session_factory(engine).begin() as session:
            session.add(
                AuditLog(
                    id=collision_id,
                    action="EXISTING",
                    entity_type="OTHER",
                    entity_id="kept",
                    before_hash=None,
                    after_hash=None,
                    details_json='{"retained":true}',
                    created_at=_NOW.isoformat(),
                )
            )
        before = _state(engine)
        identities = iter(["c" * 32, source_id] if case == "buy" else [source_id])

        class CollidingIds(SqlAlchemyUnitOfWork):
            def __init__(self, factory, **kwargs):
                super().__init__(factory, id_factory=lambda: next(identities), **kwargs)

        context = MutationContext(idempotency_key="inventory-collision", request_id="c" * 32)
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed: audit_log.id"):
            asyncio.run(
                getattr(_service(engine, CollidingIds), method)(
                    command=command,
                    context=context,
                )
            )
        assert _state(engine) == before
    finally:
        engine.dispose()
