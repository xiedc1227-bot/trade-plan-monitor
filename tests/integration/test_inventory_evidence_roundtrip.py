"""Decode the inventory receipts emitted by real transactional repositories."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, select

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.inventory_evidence import (
    ValidatedInventoryMutation,
    decode_inventory_mutation,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionLot,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SYMBOL = "003043.SZ"
DAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 22, 2, 30, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_sqlite_engine(tmp_path / "inventory-roundtrip.sqlite3")
    upgrade_database(database)
    try:
        yield database
    finally:
        database.dispose()


class Inputs:
    def __init__(self):
        self.ids = 0
        self.ticks = 0
        self.utc = False

    def identity(self):
        self.ids += 1
        return f"roundtrip-{self.ids}"

    def clock(self):
        self.ticks += 1
        timestamp = NOW + timedelta(seconds=self.ticks)
        return timestamp if self.utc else timestamp.astimezone(ZoneInfo("Asia/Shanghai"))


def _work(engine, inputs, *, identities=None):
    return SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=inputs.clock,
        id_factory=inputs.identity if identities is None else lambda: next(identities),
    )


def _confirm(work, *, total=400, revision=0, lots=()):
    work.references.upsert_trading_days(
        (
            TradingDay(
                exchange="SZSE",
                cal_date=DAY,
                is_open=True,
                previous_trade_date=date(2026, 9, 11),
            ),
        )
    )
    return work.positions.confirm_inventory(
        symbol=SYMBOL,
        as_of_trade_date=DAY,
        total_quantity=total,
        sellable_quantity=total,
        included_lot_ids=lots,
        complete_registration=True,
        expected_revision=revision,
    )


def _buy(work, *, quantity=400, board_lot=100):
    return work.positions.record_buy(
        symbol=SYMBOL,
        bucket="CORE",
        quantity=quantity,
        acquired_trade_date=date(2026, 9, 11),
        cost_fen=990,
        board_lot=board_lot,
        max_position_qty=board_lot * 2000,
    )


def _decode(row):
    result = decode_inventory_mutation(
        audit_id=row.id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before_hash=row.before_hash,
        after_hash=row.after_hash,
        details_json=row.details_json,
        created_at=row.created_at,
    )
    assert isinstance(result, ValidatedInventoryMutation), result
    assert result.status == "VALID"
    assert (result.audit_id, result.action, result.entity_id) == (
        row.id,
        row.action,
        row.entity_id,
    )
    assert result.created_at == row.created_at
    return result


def _last_audit(engine, inputs):
    with create_session_factory(engine)() as session:
        return session.get(AuditLog, f"roundtrip-{inputs.ids}")


def _receipt(engine, source_id):
    receipt_id = str(uuid5(NAMESPACE_URL, "trade-plan-monitor:inventory-recovery:v1:" + source_id))
    with create_session_factory(engine)() as session:
        return session.get(AuditLog, receipt_id)


@pytest.mark.parametrize("total,include_lot", [(0, False), (400, False), (500, True)])
def test_confirmation_roundtrip_preserves_raw_fields_and_created_opening(
    engine, total, include_lot
):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        lot = _buy(work) if include_lot else None
        inputs.utc = True
        inventory = _confirm(
            work, total=total, revision=int(include_lot), lots=(lot.id,) if lot else ()
        )
        work.commit()
    row = _last_audit(engine, inputs)
    result = _decode(row)
    raw = json.loads(row.details_json)["recoveryEvidence"]
    assert result.before is None
    assert (result.previous_revision, result.next_revision) == (
        int(include_lot),
        int(include_lot) + 1,
    )
    assert result.effective_trade_date == DAY
    assert (
        result.total_delta is None and result.sync_outcome is None and result.source_audit is None
    )
    assert result.after.confirmation_id == inventory.confirmation_id
    assert result.after.as_of_trade_date == DAY
    assert result.after.confirmed_at == row.created_at
    assert result.after.confirmed_at.endswith("+00:00")
    assert result.after.included_lot_ids == ((lot.id,) if lot else ())
    assert result.after.opening_balance_ids == tuple(item.id for item in inventory.opening_balances)
    assert asdict(result.after) | {"as_of_trade_date": DAY.isoformat()} == raw["after"]
    if total:
        opening = result.created_opening_balance
        assert opening.id == inventory.opening_balances[0].id
        assert opening.original_qty == (100 if include_lot else total)
        assert opening.remaining_qty == opening.original_qty
        assert opening.sellable_from == DAY
        assert opening.confirmation_id == result.after.confirmation_id
        assert opening.revision == 0 and opening.closed_at is None
    else:
        assert result.created_opening_balance is None
    with pytest.raises(FrozenInstanceError):
        result.after.total_qty = 999


@pytest.mark.parametrize("reuse_id", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_reconfirmation_accepts_repository_id_reuse_and_previous_opening(engine, reuse_id, stale):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        initial = _confirm(work)
        work.commit()
    first = _decode(_last_audit(engine, inputs))
    previous_revision = initial.inventory_revision
    if stale:
        with create_session_factory(engine).begin() as session:
            session.get(PositionInventoryState, SYMBOL).revision += 3
        previous_revision += 3
    identities = iter([initial.confirmation_id, "reconfirmation-audit"]) if reuse_id else None
    with _work(engine, inputs, identities=identities) as work:
        _confirm(work, revision=previous_revision)
        work.commit()
    if reuse_id:
        with create_session_factory(engine)() as session:
            row = session.get(AuditLog, "reconfirmation-audit")
    else:
        row = _last_audit(engine, inputs)
    result = _decode(row)
    assert result.before == first.after
    assert (result.previous_revision, result.next_revision) == (
        previous_revision,
        previous_revision + 1,
    )
    assert result.created_opening_balance is None
    assert result.after.opening_balance_ids == first.after.opening_balance_ids
    assert (result.before.confirmation_id == result.after.confirmation_id) is reuse_id
    assert row.before_hash is None


@pytest.mark.parametrize(
    "command,outcome",
    [(command, outcome) for command in ("buy", "lot", "opening") for outcome in ("SYNCED", "STALE")]
    + [("buy", "MISSING"), ("lot", "MISSING")],
)
def test_change_roundtrip_matches_actual_source_and_sync_outcome(engine, command, outcome):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        lot = _buy(work) if command == "lot" else None
        previous = int(lot is not None)
        if outcome != "MISSING":
            inputs.utc = True
            inventory = _confirm(work, revision=previous, lots=(lot.id,) if lot else ())
            previous = inventory.inventory_revision
        work.commit()
    inputs.utc = False
    if outcome == "STALE":
        # Model a restored legacy state whose confirmation predates its revision.
        with create_session_factory(engine).begin() as session:
            session.get(PositionInventoryState, SYMBOL).revision += 3
        previous += 3
    with _work(engine, inputs) as work:
        if command == "buy":
            changed = _buy(work, quantity=7, board_lot=7)
        elif command == "lot":
            changed = work.positions.reduce_lot(lot.id, quantity=7, board_lot=7, trade_date=DAY)
        else:
            changed = work.positions.reduce_opening_balance(
                inventory.opening_balances[0].id,
                quantity=7,
                board_lot=7,
                trade_date=DAY,
            )
        work.commit()
    source = _last_audit(engine, inputs)
    result = _decode(_receipt(engine, source.id))
    assert (result.previous_revision, result.next_revision) == (previous, previous + 1)
    assert result.source_audit.id == source.id
    assert result.source_audit.action == source.action
    assert result.source_audit.entity_type == source.entity_type
    assert result.source_audit.entity_id == changed.id == source.entity_id
    assert result.created_at == source.created_at
    assert result.effective_trade_date == (date(2026, 9, 11) if command == "buy" else DAY)
    assert result.total_delta == (7 if command == "buy" else -7)
    assert result.sync_outcome == outcome
    assert result.created_opening_balance is None
    if outcome == "MISSING":
        assert result.before is None and result.after is None
    elif outcome == "STALE":
        assert result.after == result.before
        assert result.before.inventory_revision != previous
    else:
        assert result.after.total_qty == result.before.total_qty + result.total_delta
        assert result.after.sellable_qty == min(result.before.sellable_qty, result.after.total_qty)
        assert result.after.inventory_revision == previous + 1
        assert result.after.confirmed_at == result.before.confirmed_at
        assert result.after.included_lot_ids_json == result.before.included_lot_ids_json
        assert result.after.opening_balance_ids_json == result.before.opening_balance_ids_json


def test_roundtrip_after_odd_opening_reductions_and_zero_closure(engine):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        inventory = _confirm(work, total=100)
        work.commit()
    for quantity, board_lot, expected_total in [(7, 7, 93), (3, 3, 90), (90, 30, 0)]:
        with _work(engine, inputs) as work:
            work.positions.reduce_opening_balance(
                inventory.opening_balances[0].id,
                quantity=quantity,
                board_lot=board_lot,
                trade_date=DAY,
            )
            work.commit()
        source = _last_audit(engine, inputs)
        result = _decode(_receipt(engine, source.id))
        assert result.sync_outcome == "SYNCED"
        assert result.total_delta == -quantity
        assert result.after.total_qty == result.after.sellable_qty == expected_total


def test_reconfirmation_can_create_an_odd_opening_remainder(engine):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        inventory = _confirm(work, total=100)
        work.positions.reduce_opening_balance(
            inventory.opening_balances[0].id,
            quantity=7,
            board_lot=7,
            trade_date=DAY,
        )
        _confirm(work, total=100, revision=2)
        work.commit()
    result = _decode(_last_audit(engine, inputs))
    assert result.before.total_qty == 93
    assert result.after.total_qty == 100
    assert result.created_opening_balance.original_qty == 7
    assert result.created_opening_balance.remaining_qty == 7
    assert len(result.after.opening_balance_ids) == 2


def test_writer_accepted_nul_in_lot_id_survives_receipt_and_confirmation_decode(engine):
    inputs = Inputs()
    lot_id = "lot\u0000a"
    identities = iter([lot_id, "nul-buy-audit", "nul-confirmation", "nul-confirmation-audit"])
    with _work(engine, inputs, identities=identities) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, inputs, identities=identities) as work:
        _confirm(work, revision=1, lots=(lot.id,))
        work.commit()
    receipt = _decode(_receipt(engine, "nul-buy-audit"))
    assert receipt.source_audit.entity_id == lot_id
    with create_session_factory(engine)() as session:
        confirmation = _decode(session.get(AuditLog, "nul-confirmation-audit"))
    assert confirmation.after.included_lot_ids == (lot_id,)
    assert json.loads(confirmation.after.included_lot_ids_json) == [lot_id]


def test_uncommitted_receipt_decodes_but_rollback_and_reopen_preserve_only_committed_rows(engine):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        _confirm(work)
        work.commit()
    committed = _decode(_last_audit(engine, inputs))
    with _work(engine, inputs) as work:
        lot = _buy(work)
        session = work._require_session()
        receipt = session.scalar(
            select(AuditLog).where(AuditLog.action == "POSITION_INVENTORY_CHANGED")
        )
        uncommitted = _decode(receipt)
        assert uncommitted.after.total_qty == 800
        # Context exit without commit rolls back the lot, confirmation and receipt.
    path = Path(engine.url.database)
    engine.dispose()
    reopened = create_sqlite_engine(path)
    try:
        with create_session_factory(reopened)() as session:
            assert session.get(AuditLog, uncommitted.audit_id) is None
            assert session.get(AuditLog, uncommitted.source_audit.id) is None
            assert session.get(PositionLot, lot.id) is None
            assert session.get(PositionInventoryConfirmation, SYMBOL).total_qty == 400
            assert _decode(session.get(AuditLog, committed.audit_id)) == committed
    finally:
        reopened.dispose()
