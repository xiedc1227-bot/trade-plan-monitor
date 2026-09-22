"""Inventory writer receipts preserve raw facts without changing existing mutations."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
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
from trade_plan_monitor.state.events import MonitorEventType, monitor_event_id
from trade_plan_monitor.state.models import (
    AuditLog,
    MonitorEvent,
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionOpeningBalance,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SYMBOL = "003043.SZ"
DAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 22, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
CONFIRMATION_FIELDS = {
    "symbol",
    "confirmation_id",
    "as_of_trade_date",
    "confirmed_at",
    "inventory_revision",
    "total_qty",
    "sellable_qty",
    "included_lot_ids_json",
    "opening_balance_ids_json",
    "complete_registration",
}
OPENING_FIELDS = {
    "id",
    "symbol",
    "original_qty",
    "remaining_qty",
    "sellable_from",
    "confirmation_id",
    "revision",
    "closed_at",
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_sqlite_engine(tmp_path / "inventory-evidence.sqlite3")
    upgrade_database(database)
    try:
        yield database
    finally:
        database.dispose()


class Inputs:
    def __init__(self):
        self.ids = 0
        self.ticks = 0

    def identity(self):
        self.ids += 1
        return f"manual-{self.ids}"

    def clock(self):
        self.ticks += 1
        return NOW + timedelta(seconds=self.ticks)


def _work(engine, inputs):
    return SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=inputs.clock,
        id_factory=inputs.identity,
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


def _buy(work):
    return work.positions.record_buy(
        symbol=SYMBOL,
        bucket="CORE",
        quantity=400,
        acquired_trade_date=date(2026, 9, 11),
        cost_fen=990,
        board_lot=100,
        max_position_qty=2000,
    )


def _hash(value):
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _confirmation(session):
    row = session.get(PositionInventoryConfirmation, SYMBOL)
    if row is None:
        return None
    values = {name: getattr(row, name) for name in CONFIRMATION_FIELDS}
    values["as_of_trade_date"] = row.as_of_trade_date.isoformat()
    return values


@pytest.mark.parametrize(
    "total,repeat,stale",
    [(0, False, False), (400, False, False), (400, True, False), (400, True, True)],
)
def test_confirmation_preserves_before_after_creation_and_existing_hash(
    engine,
    total,
    repeat,
    stale,
):
    inputs = Inputs()
    before = None
    revision = 0
    if repeat:
        with _work(engine, inputs) as work:
            _confirm(work, total=total)
            work.commit()
        with create_session_factory(engine).begin() as session:
            row = session.get(PositionInventoryConfirmation, SYMBOL)
            row.confirmed_at = "2026-09-14T01:20:00+00:00"
            row.included_lot_ids_json = "[  ]"
            row.opening_balance_ids_json = '[ "manual-2" ]'
            if stale:
                session.get(PositionInventoryState, SYMBOL).revision = 4
            before = _confirmation(session)
            revision = 4 if stale else 1
    baseline = inputs.ids, inputs.ticks
    with _work(engine, inputs) as work:
        result = _confirm(work, total=total, revision=revision)
        work.commit()
    assert (inputs.ids - baseline[0], inputs.ticks - baseline[1]) == (
        3 if total and not repeat else 2,
        1,
    )
    with create_session_factory(engine)() as session:
        audit = session.get(AuditLog, f"manual-{inputs.ids}")
        after = _confirmation(session)
        assert session.scalars(select(MonitorEvent)).all() == []
    assert set(after) == CONFIRMATION_FIELDS
    assert after["inventory_revision"] == revision + 1
    assert audit.before_hash is None
    assert audit.after_hash == _hash(
        {
            "confirmationId": result.confirmation_id,
            "inventoryRevision": revision + 1,
            "sellableQty": total,
            "symbol": SYMBOL,
            "totalQty": total,
        }
    )
    created = None
    if total and not repeat:
        opening = result.opening_balances[0]
        created = {
            "id": opening.id,
            "symbol": SYMBOL,
            "original_qty": total,
            "remaining_qty": total,
            "sellable_from": DAY.isoformat(),
            "confirmation_id": result.confirmation_id,
            "revision": 0,
            "closed_at": None,
        }
    assert json.loads(audit.details_json) == {
        "asOfTradeDate": DAY.isoformat(),
        "completeRegistration": True,
        "recoveryEvidence": {
            "schemaVersion": 1,
            "previousInventoryRevision": revision,
            "nextInventoryRevision": revision + 1,
            "before": before,
            "after": after,
            "createdOpeningBalance": created,
        },
    }


@pytest.mark.parametrize("command", ["buy", "lot", "opening"])
@pytest.mark.parametrize("outcome", ["SYNCED", "MISSING", "STALE"])
def test_inventory_changes_link_source_and_preserve_raw_confirmation(engine, command, outcome):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        lot = _buy(work) if command == "lot" else None
        inventory = _confirm(work, revision=1 if lot else 0, lots=(lot.id,) if lot else ())
        opening_id = inventory.opening_balances[0].id if command == "opening" else None
        work.commit()
    with create_session_factory(engine).begin() as session:
        row = session.get(PositionInventoryConfirmation, SYMBOL)
        row.confirmed_at = "2026-09-14T01:20:00+00:00"
        row.included_lot_ids_json = '[ "成员", "manual-unused" ]'
        row.opening_balance_ids_json = "[  ]"
        if outcome == "MISSING":
            session.delete(row)
            session.flush()
        elif outcome == "STALE":
            row.inventory_revision = 0
        before = _confirmation(session)
    baseline = inputs.ids, inputs.ticks
    with _work(engine, inputs) as work:
        if command == "buy":
            record = _buy(work)
        elif command == "lot":
            record = work.positions.reduce_lot(lot.id, quantity=100, trade_date=DAY)
        else:
            record = work.positions.reduce_opening_balance(opening_id, quantity=100, trade_date=DAY)
        work.commit()
    assert (inputs.ids - baseline[0], inputs.ticks - baseline[1]) == (
        2 if command == "buy" else 1,
        1,
    )
    source_id = f"manual-{inputs.ids}"
    with create_session_factory(engine)() as session:
        source = session.get(AuditLog, source_id)
        receipt = session.get(
            AuditLog,
            str(
                uuid5(
                    NAMESPACE_URL,
                    "trade-plan-monitor:inventory-recovery:v1:" + source_id,
                )
            ),
        )
        after = _confirmation(session)
        event = session.get(
            MonitorEvent,
            str(
                monitor_event_id(
                    MonitorEventType.POSITION_UPDATED,
                    record.id,
                    str(record.remaining_qty),
                )
            ),
        )
    assert receipt is not None
    delta = 400 if command == "buy" else -100
    expected_after = None if before is None else dict(before)
    if outcome == "SYNCED":
        expected_after.update(
            total_qty=400 + delta,
            sellable_qty=min(400, 400 + delta),
            inventory_revision=inventory.inventory_revision + 1,
        )
    assert after == expected_after
    previous_state = {"inventoryRevision": inventory.inventory_revision, "confirmation": before}
    next_state = {"inventoryRevision": inventory.inventory_revision + 1, "confirmation": after}
    assert receipt.action == "POSITION_INVENTORY_CHANGED"
    assert (receipt.entity_type, receipt.entity_id) == ("POSITION_INVENTORY", SYMBOL)
    assert receipt.created_at == source.created_at == event.occurred_at
    assert (receipt.before_hash, receipt.after_hash) == (_hash(previous_state), _hash(next_state))
    assert json.loads(receipt.details_json) == {
        "recoveryEvidence": {
            "schemaVersion": 1,
            "sourceAudit": {
                "id": source.id,
                "action": source.action,
                "entityType": source.entity_type,
                "entityId": source.entity_id,
            },
            "effectiveTradeDate": "2026-09-11" if command == "buy" else DAY.isoformat(),
            "totalDelta": delta,
            "syncOutcome": outcome,
            "before": previous_state,
            "after": next_state,
        }
    }


def test_opening_reductions_preserve_closure_custom_lot_and_nonmonotonic_dates(engine):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        inventory = _confirm(work, total=100)
        work.commit()
    opening = inventory.opening_balances[0]
    expected = {
        "id": opening.id,
        "symbol": SYMBOL,
        "original_qty": 100,
        "remaining_qty": 100,
        "sellable_from": DAY.isoformat(),
        "confirmation_id": inventory.confirmation_id,
        "revision": 0,
        "closed_at": None,
    }
    for qty, day in [(25, date(2026, 9, 18)), (75, DAY)]:
        baseline = inputs.ids, inputs.ticks
        with _work(engine, inputs) as work:
            before_dto = work.positions.get_opening_balance(opening.id).model_dump(mode="json")
            result = work.positions.reduce_opening_balance(
                opening.id,
                quantity=qty,
                trade_date=day,
                board_lot=25,
            )
            work.commit()
        assert (inputs.ids - baseline[0], inputs.ticks - baseline[1]) == (1, 2 if qty == 75 else 1)
        with create_session_factory(engine)() as session:
            row = session.get(PositionOpeningBalance, opening.id)
            after = {name: getattr(row, name) for name in OPENING_FIELDS}
            after["sellable_from"] = row.sellable_from.isoformat()
            audit = session.get(AuditLog, f"manual-{inputs.ids}")
        assert after["remaining_qty"] == expected["remaining_qty"] - qty
        assert after["revision"] == expected["revision"] + qty // 25
        if qty == 75:
            assert after["closed_at"] == (NOW + timedelta(seconds=inputs.ticks - 1)).isoformat()
            assert after["closed_at"] != audit.created_at
        assert (audit.before_hash, audit.after_hash) == (
            _hash(before_dto),
            _hash(result.model_dump(mode="json")),
        )
        assert json.loads(audit.details_json) == {
            "quantity": qty,
            "symbol": SYMBOL,
            "recoveryEvidence": {
                "schemaVersion": 1,
                "effectiveTradeDate": day.isoformat(),
                "boardLot": 25,
                "before": expected,
                "after": after,
            },
        }
        expected = after


def test_changing_board_lots_and_raw_utc_closure_keep_legacy_dto_hash(engine):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        inventory = _confirm(work, total=100)
        opening = inventory.opening_balances[0]
        for quantity, board_lot, remaining, revision in [(7, 7, 93, 1), (3, 3, 90, 2)]:
            result = work.positions.reduce_opening_balance(
                opening.id,
                quantity=quantity,
                board_lot=board_lot,
                trade_date=DAY,
            )
            assert (result.remaining_qty, result.revision) == (remaining, revision)
        work.commit()
    closure_time = NOW.astimezone(UTC)
    audit_time = NOW - timedelta(seconds=1)
    timestamps = iter([closure_time, audit_time])
    baseline_ids = inputs.ids
    with SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=lambda: next(timestamps),
        id_factory=inputs.identity,
    ) as work:
        result = work.positions.reduce_opening_balance(
            opening.id,
            quantity=90,
            board_lot=30,
            trade_date=DAY,
        )
        work.commit()
    assert inputs.ids == baseline_ids + 1
    assert next(timestamps, None) is None
    with create_session_factory(engine)() as session:
        source = session.get(AuditLog, f"manual-{inputs.ids}")
        receipt = session.get(
            AuditLog,
            str(
                uuid5(
                    NAMESPACE_URL,
                    "trade-plan-monitor:inventory-recovery:v1:" + source.id,
                )
            ),
        )
    evidence = json.loads(source.details_json)["recoveryEvidence"]
    assert evidence["before"]["revision"] == 2
    assert evidence["after"]["revision"] == 5
    assert evidence["after"]["closed_at"] == closure_time.isoformat()
    assert result.model_dump(mode="json")["closed_at"].endswith("Z")
    assert source.after_hash == _hash(result.model_dump(mode="json"))
    assert source.after_hash != _hash(evidence["after"])
    assert source.created_at == receipt.created_at == audit_time.isoformat()


@pytest.mark.parametrize("command", ["buy", "lot", "opening"])
def test_accepted_shanghai_fold_clock_reaches_publication_unchanged(engine, command):
    inputs = Inputs()
    with _work(engine, inputs) as work:
        lot = _buy(work) if command == "lot" else None
        inventory = _confirm(work, revision=1 if lot else 0, lots=(lot.id,) if lot else ())
        work.commit()
    # Historical Shanghai DST folds are accepted clocks; serializing and reparsing
    # this datetime loses fold=1 and changes the event validator's interpretation.
    occurred_at = datetime(1991, 9, 15, 1, 30, tzinfo=ZoneInfo("Asia/Shanghai"), fold=1)
    with SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=lambda: occurred_at,
        id_factory=inputs.identity,
    ) as work:
        if command == "buy":
            record = _buy(work)
        elif command == "lot":
            record = work.positions.reduce_lot(lot.id, quantity=100, trade_date=DAY)
        else:
            record = work.positions.reduce_opening_balance(
                inventory.opening_balances[0].id,
                quantity=100,
                trade_date=DAY,
            )
        work.commit()
    with create_session_factory(engine)() as session:
        source = session.get(AuditLog, f"manual-{inputs.ids}")
        publication = session.get(
            MonitorEvent,
            str(
                monitor_event_id(
                    MonitorEventType.POSITION_UPDATED,
                    record.id,
                    str(record.remaining_qty),
                )
            ),
        )
        receipt = session.get(
            AuditLog,
            str(
                uuid5(
                    NAMESPACE_URL,
                    "trade-plan-monitor:inventory-recovery:v1:" + source.id,
                )
            ),
        )
    assert source.created_at == receipt.created_at == publication.occurred_at
    assert source.created_at == occurred_at.isoformat()
