"""Inventory proof rejects incomplete, borrowed and over-budget durable evidence."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from trade_plan_monitor.state import database
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import AuditLog, PositionInventoryState
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SYMBOL = "003043.SZ"
NOW = datetime(2026, 9, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def engine(tmp_path):
    database = create_sqlite_engine(tmp_path / "inventory-boundaries.sqlite3")
    upgrade_database(database)
    with SqlAlchemyUnitOfWork(create_session_factory(database), clock=lambda: NOW) as work:
        work.positions.record_buy(
            symbol=SYMBOL, bucket="CORE", quantity=1000, acquired_trade_date=date(2026, 9, 11),
            cost_fen=990, board_lot=100, max_position_qty=2000,
        )
        work.commit()
    yield database
    database.dispose()


def read(engine, **kwargs):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    return PositionInventoryHistoryReader(create_session_factory(engine)).read(
        SYMBOL, cutoff=NOW, observed_at=NOW + timedelta(days=3), **kwargs,
    )


def test_symbol_inventory_lookup_has_index_and_upgrade_preserves_data(engine):
    before = None
    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT * FROM position_lot").all()
    config = Config()
    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0020_lot_history_indexes")
    assert "ix_position_lot_symbol" not in {
        item["name"] for item in inspect(engine).get_indexes("position_lot")
    }
    upgrade_database(engine)
    upgrade_database(engine)
    assert "ix_position_lot_symbol" in {
        item["name"] for item in inspect(engine).get_indexes("position_lot")
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM position_lot").all() == before
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT id FROM position_lot WHERE symbol = ? LIMIT 257", (SYMBOL,),
        ).all()
    assert any("ix_position_lot_symbol" in row[-1] for row in plan)


@pytest.mark.parametrize("sql", [
    "DELETE FROM audit_log WHERE action='POSITION_INVENTORY_CHANGED'",
    "DELETE FROM audit_log WHERE action='POSITION_BUY_RECORDED'",
    "DELETE FROM position_lot",
    "DELETE FROM monitor_event",
    "UPDATE position_lot SET remaining_qty=900",
    "UPDATE position_inventory_state SET revision=2",
    "UPDATE audit_log SET after_hash='bad' WHERE action='POSITION_INVENTORY_CHANGED'",
    "UPDATE monitor_event SET occurred_at='2026-09-14T10:00:01+08:00'",
    "UPDATE monitor_sequence SET last_sequence=0",
])
def test_missing_or_conflicting_history_cannot_prove_inventory(engine, sql):
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)
    assert read(engine).status == "UNKNOWN"


def test_unknown_scope_is_not_assumed_empty(engine):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    result = PositionInventoryHistoryReader(create_session_factory(engine)).read(
        "600000.SH", cutoff=NOW, observed_at=NOW,
    )
    assert result.status == "UNKNOWN"


def test_limit_cannot_be_used_as_a_complete_chain(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE position_inventory_state SET revision=257")
    assert read(engine).reason == "HISTORY_LIMIT"


def test_database_failures_are_not_content_unknown(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE audit_log")
    with pytest.raises(OperationalError):
        read(engine)


def test_external_connection_and_dirty_session_remain_caller_owned(engine):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    with engine.connect() as connection, Session(connection) as session:
        with pytest.raises(ValueError):
            PositionInventoryHistoryReader(lambda: session).read(
                SYMBOL, cutoff=NOW, observed_at=NOW,
            )
        assert not connection.closed
    with create_session_factory(engine)() as session:
        state = session.get(PositionInventoryState, SYMBOL)
        state.revision = 2
        with pytest.raises(ValueError):
            PositionInventoryHistoryReader(lambda: session).read(
                SYMBOL, cutoff=NOW, observed_at=NOW,
            )
        assert session.in_transaction() and state in session.dirty


def test_one_snapshot_does_not_mix_a_concurrent_confirmation(engine):
    fired = False

    def concurrent_writer(connection, cursor, statement, parameters, context, executemany):
        nonlocal fired
        if fired or "FROM position_inventory_state" not in statement:
            return
        fired = True
        with engine.begin() as other:
            other.exec_driver_sql("UPDATE position_inventory_state SET revision=2")

    event.listen(engine, "after_cursor_execute", concurrent_writer)
    try:
        result = read(engine)
    finally:
        event.remove(engine, "after_cursor_execute", concurrent_writer)
    assert fired and result.status == "PROVEN" and result.current_revision == 1
    assert read(engine).status == "UNKNOWN"


def test_preused_session_rejection_does_not_delete_pending_audit(engine):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    with create_session_factory(engine)() as session:
        pending = AuditLog(id="pending", action="OTHER", entity_type="OTHER", entity_id=SYMBOL,
                           details_json="{}", created_at=NOW.isoformat())
        session.add(pending)
        with pytest.raises(ValueError):
            PositionInventoryHistoryReader(lambda: session).read(
                SYMBOL, cutoff=NOW, observed_at=NOW,
            )
        assert pending in session.new
        assert session.scalar(text("SELECT count(*) FROM audit_log WHERE id='pending'")) == 0


def _buy(engine, at=NOW):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: at) as work:
        lot = work.positions.record_buy(
            symbol=SYMBOL, bucket="CORE", quantity=100, acquired_trade_date=date(2026, 9, 11),
            cost_fen=990, board_lot=100, max_position_qty=100000,
        )
        work.commit()
        return lot


def test_publication_order_is_checked_across_different_lots(engine):
    _buy(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE monitor_event SET sequence=3 WHERE sequence=1")
        connection.exec_driver_sql("UPDATE monitor_event SET sequence=1 WHERE sequence=2")
        connection.exec_driver_sql("UPDATE monitor_event SET sequence=2 WHERE sequence=3")
    assert read(engine).status == "UNKNOWN"


def test_registration_clock_reversal_is_not_repaired_by_sorting_timestamps(engine):
    _buy(engine, NOW - timedelta(seconds=1))
    assert read(engine).status == "UNKNOWN"


def test_unconsumed_source_audit_is_not_ignored(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO audit_log SELECT 'orphan', action, entity_type, entity_id, "
            "before_hash, after_hash, details_json, created_at FROM audit_log "
            "WHERE action='POSITION_BUY_RECORDED'"
        )
    assert read(engine).status == "UNKNOWN"


def test_receipt_byte_budget_applies_across_individually_valid_records(engine):
    for _ in range(39):
        _buy(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE audit_log SET details_json=details_json || :padding "
            "WHERE entity_type='POSITION_INVENTORY'"
        ), {"padding": " " * 230000})
    assert read(engine).reason == "HISTORY_LIMIT"


def test_later_registration_is_excluded_but_future_observation_is_not_assumed(engine):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    _buy(engine, NOW + timedelta(days=1))
    reader = PositionInventoryHistoryReader(create_session_factory(engine))
    assert reader.read(SYMBOL, cutoff=NOW, observed_at=NOW).status == "UNKNOWN"
    result = read(engine)
    assert result.status == "PROVEN"
    assert result.inventory_revision == 1 and result.current_revision == 2


def test_no_future_trade_date_can_enter_selected_history(engine):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW) as work:
        work.positions.record_buy(
            symbol=SYMBOL, bucket="CORE", quantity=100,
            acquired_trade_date=NOW.date() + timedelta(days=1),
            cost_fen=990, board_lot=100, max_position_qty=10000,
        )
        work.commit()
    assert read(engine).status == "UNKNOWN"


def test_invalid_call_times_reject_before_acquiring_session():
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    def forbidden():
        pytest.fail("invalid caller inputs must not acquire a session")

    reader = PositionInventoryHistoryReader(forbidden)
    for cutoff, observed in ((NOW.replace(tzinfo=None), NOW), (NOW, NOW - timedelta(seconds=1))):
        with pytest.raises(ValueError):
            reader.read(SYMBOL, cutoff=cutoff, observed_at=observed)


@pytest.mark.parametrize("offset, expected", [(1, "PROVEN"), (4, "UNKNOWN")])
def test_closure_can_differ_from_audit_time_but_not_exceed_observation(engine, offset, expected):
    with engine.connect() as connection:
        lot_id = connection.exec_driver_sql("SELECT id FROM position_lot").scalar_one()
    ticks = iter((NOW + timedelta(days=offset), NOW))
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: next(ticks)) as work:
        work.positions.reduce_lot(lot_id, quantity=1000, trade_date=NOW.date())
        work.commit()
    assert read(engine).status == expected


def test_mapper_specific_foreign_bind_is_rejected_without_borrowing_it(engine, tmp_path):
    from trade_plan_monitor.state.position_inventory_history import PositionInventoryHistoryReader

    other = create_sqlite_engine(tmp_path / "other.sqlite3")
    try:
        with Session(engine, binds={AuditLog: other}) as session:
            with pytest.raises(ValueError):
                PositionInventoryHistoryReader(lambda: session).read(
                    SYMBOL, cutoff=NOW, observed_at=NOW,
                )
            assert not session.in_transaction()
    finally:
        other.dispose()


def test_complete_256_mutation_history_is_proven_and_257th_is_not_truncated(engine):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW) as work:
        for _ in range(255):
            work.positions.record_buy(
                symbol=SYMBOL, bucket="CORE", quantity=100,
                acquired_trade_date=date(2026, 9, 11), cost_fen=990,
                board_lot=100, max_position_qty=100000,
            )
        work.commit()
    result = read(engine)
    assert result.status == "PROVEN"
    assert result.inventory_revision == 256 and len(result.position_lots) == 256
    _buy(engine)
    assert read(engine).reason == "HISTORY_LIMIT"


@pytest.mark.parametrize("sql", [
    "UPDATE position_inventory_state SET revision=1.5",
    "UPDATE position_lot SET remaining_qty=0.5",
    "UPDATE position_lot SET acquired_trade_date='20260911'",
    "UPDATE audit_log SET details_json=CAST(details_json AS BLOB)",
])
def test_sqlite_storage_types_cannot_coerce_into_valid_evidence(engine, sql):
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)
    assert read(engine).status == "UNKNOWN"
