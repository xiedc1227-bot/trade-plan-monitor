"""Real committed writer audits round-trip through the isolated decoder."""

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, select

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.position_lot_evidence import (
    ValidatedLotMutation,
    decode_position_lot_mutation,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 22, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_sqlite_engine(tmp_path / "decode-lot.sqlite3")
    upgrade_database(database)
    try:
        yield database
    finally:
        database.dispose()


def decode(row):
    return decode_position_lot_mutation(
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before_hash=row.before_hash,
        after_hash=row.after_hash,
        details_json=row.details_json,
        created_at=row.created_at,
    )


@pytest.mark.parametrize("reductions", [(), (7,), (14,), (7, 7)])
def test_committed_late_buy_partial_full_and_same_day_reductions(engine, reductions):
    factory = create_session_factory(engine)
    with SqlAlchemyUnitOfWork(factory, clock=lambda: NOW) as work:
        lot = work.positions.record_buy(
            symbol="830001.BJ",
            bucket="CORE",
            quantity=14,
            acquired_trade_date=date(2026, 9, 11),
            cost_fen=123,
            board_lot=7,
            max_position_qty=28,
        )
        for quantity in reductions:
            work.positions.reduce_lot(
                lot.id, quantity=quantity, trade_date=date(2026, 9, 14), board_lot=7
            )
        work.commit()
    with factory() as session:
        rows = session.scalars(select(AuditLog).where(AuditLog.entity_id == lot.id)).all()
        original = [(r.details_json, r.before_hash, r.after_hash, r.created_at) for r in rows]
        decoded = sorted((decode(row) for row in rows), key=lambda item: -item.after.remaining_qty)
        assert [
            (r.details_json, r.before_hash, r.after_hash, r.created_at) for r in rows
        ] == original
    assert len(decoded) == 1 + len(reductions)
    assert all(isinstance(item, ValidatedLotMutation) for item in decoded)
    assert decoded[0].effective_trade_date == date(2026, 9, 11)
    remaining = 14
    for mutation, quantity in zip(decoded[1:], reductions, strict=True):
        assert mutation.before.remaining_qty == remaining
        remaining -= quantity
        assert mutation.after.remaining_qty == remaining
        assert mutation.quantity == quantity
        assert mutation.effective_trade_date == date(2026, 9, 14)
    assert all(item.created_at.date() == date(2026, 9, 22) for item in decoded)


def test_committed_custom_identifier_longer_than_uuid_roundtrips(engine):
    factory = create_session_factory(engine)
    identities = iter(("x" * 64, "audit-custom-id"))
    with SqlAlchemyUnitOfWork(
        factory, clock=lambda: NOW, id_factory=lambda: next(identities)
    ) as work:
        lot = work.positions.record_buy(
            symbol="003043.SZ",
            bucket="TACTICAL",
            quantity=100,
            acquired_trade_date=date(2026, 9, 11),
            cost_fen=123,
            board_lot=100,
            max_position_qty=200,
        )
        work.commit()
    with factory() as session:
        row = session.scalars(select(AuditLog).where(AuditLog.entity_id == lot.id)).one()
        mutation = decode(row)
    assert isinstance(mutation, ValidatedLotMutation)
    assert mutation.after.id == "x" * 64
