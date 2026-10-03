"""Round-trip durable opening receipts through the real writer and engine restart."""

from __future__ import annotations

import json
from datetime import UTC, date, timedelta

import pytest
from sqlalchemy import select
from tests.integration.test_position_inventory_recovery_audit import (
    DAY,
    NOW,
    SYMBOL,
    Inputs,
    _confirm,
    _hash,
    _work,
)

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
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
from trade_plan_monitor.state.opening_balance_evidence import (
    UnknownOpeningMutation,
    ValidatedOpeningMutation,
    decode_opening_balance_mutation,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def _state(engine):
    models = (PositionLot, PositionOpeningBalance, PositionInventoryConfirmation,
        PositionInventoryState, AuditLog, MonitorEvent, MonitorSequence, RequestIdempotency)
    with engine.connect() as connection:
        return {model.__tablename__: connection.execute(
            select(model.__table__).order_by(*model.__table__.primary_key.columns)
        ).all() for model in models}


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / "opening-decoder.sqlite3"
    engine = create_sqlite_engine(path)
    upgrade_database(engine)
    inputs = Inputs()
    with _work(engine, inputs) as work:
        result = _confirm(work, total=100)
        work.commit()
    yield path, engine, inputs, result.opening_balances[0]
    engine.dispose()


def _reopened_audits(path, engine, ids):
    engine.dispose()
    restarted = create_sqlite_engine(path)
    try:
        with create_session_factory(restarted)() as session:
            rows = [session.get(AuditLog, identity) for identity in ids]
            return restarted, [
                {
                    key: getattr(row, key)
                    for key in (
                        "action", "entity_type", "entity_id", "before_hash", "after_hash",
                        "details_json", "created_at",
                    )
                }
                for row in rows
            ]
    except BaseException:
        restarted.dispose()
        raise


@pytest.mark.parametrize("quantity,board_lot", [(25, 25), (100, 100), (7, 7)])
def test_writer_receipts_decode_after_reopen_with_same_day_sellability(
    inventory, quantity, board_lot,
):
    path, engine, inputs, opening = inventory
    with _work(engine, inputs) as work:
        work.positions.reduce_opening_balance(
            opening.id, quantity=quantity, board_lot=board_lot, trade_date=DAY,
        )
        work.commit()
    restarted, [audit] = _reopened_audits(path, engine, [f"manual-{inputs.ids}"])
    try:
        persisted = _state(restarted)
        result = decode_opening_balance_mutation(**audit)
        assert isinstance(result, ValidatedOpeningMutation)
        assert result.status == "VALID"
        assert result.action == "POSITION_OPENING_BALANCE_REDUCTION_RECORDED"
        assert (result.quantity, result.board_lot) == (quantity, board_lot)
        assert result.effective_trade_date == result.before.sellable_from == DAY
        assert result.entity_id == result.before.id == result.after.id == opening.id
        assert result.before.remaining_qty == 100
        assert result.after.remaining_qty == 100 - quantity
        assert result.after.revision == quantity // board_lot
        assert result.before.closed_at is None
        assert (result.after.closed_at is not None) == (quantity == 100)
        assert result.before.confirmation_id == opening.confirmation_id
        assert (result.entity_id, result.before.confirmation_id) == ("manual-2", "manual-1")
        assert result.after.original_qty == 100
        assert result.after.symbol == SYMBOL
        assert result.created_at == audit["created_at"]
        assert _state(restarted) == persisted
    finally:
        restarted.dispose()


@pytest.mark.parametrize(
    "reductions",
    [
        [(7, 7, DAY, 93, 1), (3, 3, DAY, 90, 2)],
        [(25, 25, date(2026, 9, 18), 75, 1), (75, 25, DAY, 0, 4)],
    ],
)
def test_custom_lots_and_out_of_order_dates_follow_each_receipt(inventory, reductions):
    path, engine, inputs, opening = inventory
    ids = []
    for quantity, board_lot, day, _, _ in reductions:
        with _work(engine, inputs) as work:
            work.positions.reduce_opening_balance(
                opening.id, quantity=quantity, board_lot=board_lot, trade_date=day,
            )
            work.commit()
        ids.append(f"manual-{inputs.ids}")
    restarted, audits = _reopened_audits(path, engine, ids)
    try:
        persisted = _state(restarted)
        results = [decode_opening_balance_mutation(**audit) for audit in audits]
        for result, (quantity, board_lot, day, remaining, revision) in zip(
            results, reductions, strict=True,
        ):
            assert isinstance(result, ValidatedOpeningMutation)
            assert (result.quantity, result.board_lot) == (quantity, board_lot)
            assert result.effective_trade_date == day
            assert (result.after.remaining_qty, result.after.revision) == (remaining, revision)
        assert results[0].after == results[1].before
        assert results[0].after_hash == results[1].before_hash
        assert _state(restarted) == persisted
    finally:
        restarted.dispose()


def test_raw_utc_closure_preserved_while_verifying_legacy_dto_hash(inventory):
    path, engine, inputs, opening = inventory
    closure_time = NOW.astimezone(UTC)
    audit_time = NOW - timedelta(seconds=1)
    timestamps = iter([closure_time, audit_time])
    with SqlAlchemyUnitOfWork(
        create_session_factory(engine), clock=lambda: next(timestamps), id_factory=inputs.identity,
    ) as work:
        work.positions.reduce_opening_balance(opening.id, quantity=100, trade_date=DAY)
        work.commit()
    restarted, [audit] = _reopened_audits(path, engine, [f"manual-{inputs.ids}"])
    try:
        result = decode_opening_balance_mutation(**audit)
        assert isinstance(result, ValidatedOpeningMutation)
        assert result.after.closed_at == closure_time.isoformat()
        assert result.created_at == audit_time.isoformat()
        # Independently construct the historical DTO JSON, including its UTC spelling.
        before = {
            "id": opening.id, "symbol": SYMBOL, "original_qty": 100, "remaining_qty": 100,
            "sellable_from": DAY.isoformat(), "confirmation_id": opening.confirmation_id,
            "revision": 0, "closed_at": None,
        }
        after = dict(
            before, remaining_qty=0, revision=1,
            closed_at=closure_time.isoformat().replace("+00:00", "Z"),
        )
        assert result.before_hash == audit["before_hash"] == _hash(before)
        assert result.after_hash == audit["after_hash"] == _hash(after)
        assert result.after_hash != _hash(dict(after, closed_at=closure_time.isoformat()))
    finally:
        restarted.dispose()


def test_legacy_receipt_without_envelope_is_unknown_and_stays_untouched(inventory):
    path, engine, inputs, opening = inventory
    with _work(engine, inputs) as work:
        work.positions.reduce_opening_balance(opening.id, quantity=100, trade_date=DAY)
        work.commit()
    identity = f"manual-{inputs.ids}"
    with create_session_factory(engine).begin() as session:
        session.get(AuditLog, identity).details_json = json.dumps(
            {"quantity": 100, "symbol": SYMBOL},
        )
    restarted, [audit] = _reopened_audits(path, engine, [identity])
    try:
        persisted = _state(restarted)
        result = decode_opening_balance_mutation(**audit)
        assert isinstance(result, UnknownOpeningMutation)
        assert result.status == "UNKNOWN"
        assert result.reason.value == "MISSING_EVIDENCE"
        assert _state(restarted) == persisted
    finally:
        restarted.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "POSITION_INVENTORY_CHANGED"},
        {"entity_type": "POSITION_LOT"},
        {"entity_id": "another-opening"},
    ],
)
def test_real_receipt_cannot_be_rebound_to_another_scope(inventory, changes):
    path, engine, inputs, opening = inventory
    with _work(engine, inputs) as work:
        work.positions.reduce_opening_balance(opening.id, quantity=100, trade_date=DAY)
        work.commit()
    restarted, [audit] = _reopened_audits(path, engine, [f"manual-{inputs.ids}"])
    try:
        persisted = _state(restarted)
        result = decode_opening_balance_mutation(**(audit | changes))
        assert isinstance(result, UnknownOpeningMutation)
        assert result.status == "UNKNOWN"
        assert result.reason.value == "INVALID_EVIDENCE"
        assert _state(restarted) == persisted
    finally:
        restarted.dispose()
