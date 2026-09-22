"""Reconstruct registered inventory at a cutoff from durable, real SQLite writes."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.inventory_evidence import InventoryConfirmationSnapshot
from trade_plan_monitor.state.opening_balance_evidence import OpeningBalanceEvidenceSnapshot
from trade_plan_monitor.state.position_inventory_history import (
    PositionInventoryHistoryReader,
    ProvenInventoryHistory,
    UnknownInventoryHistory,
)
from trade_plan_monitor.state.repositories import PositionLotRecord
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SYMBOL = "003043.SZ"
D1 = datetime(2026, 9, 14, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
D2 = D1 + timedelta(days=1)
D3 = D1 + timedelta(days=2)
TRADE_DATE = D1.date()


@pytest.fixture
def engine(tmp_path):
    database = create_sqlite_engine(tmp_path / "inventory-history.sqlite3")
    upgrade_database(database)
    try:
        yield database
    finally:
        database.dispose()


def _work(engine, at):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: at)


def _buy(work, *, quantity=1000, symbol=SYMBOL):
    return work.positions.record_buy(
        symbol=symbol, bucket="CORE", quantity=quantity,
        acquired_trade_date=date(2026, 9, 11), cost_fen=990,
        board_lot=100, max_position_qty=10000,
    )


def _confirm(work, *, total, revision, lots=(), day=TRADE_DATE):
    work.references.upsert_trading_days((TradingDay(
        exchange="SZSE", cal_date=day, is_open=True,
        previous_trade_date=date(2026, 9, 11) if day == D1.date() else D2.date(),
    ),))
    return work.positions.confirm_inventory(
        symbol=SYMBOL, as_of_trade_date=day,
        total_quantity=total, sellable_quantity=total,
        included_lot_ids=lots, complete_registration=True, expected_revision=revision,
    )


def _read(engine, *, cutoff=D2, observed_at=D3, symbol=SYMBOL):
    return PositionInventoryHistoryReader(create_session_factory(engine)).read(
        symbol, cutoff=cutoff, observed_at=observed_at,
    )


def _registered_quantity(result):
    assert isinstance(result, ProvenInventoryHistory), result
    assert isinstance(result.position_lots, tuple)
    assert isinstance(result.opening_balances, tuple)
    assert all(isinstance(lot, PositionLotRecord) for lot in result.position_lots)
    assert all(
        isinstance(balance, OpeningBalanceEvidenceSnapshot) for balance in result.opening_balances
    )
    return sum(lot.remaining_qty for lot in result.position_lots) + sum(
        balance.remaining_qty for balance in result.opening_balances
    )


def test_registered_buy_is_proven_without_claiming_complete_account_inventory(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()

    result = _read(engine)

    assert _registered_quantity(result) == 1000
    assert result.status == "PROVEN"
    assert result.symbol == SYMBOL and result.cutoff == D2 and result.observed_at == D3
    assert result.inventory_revision == result.current_revision == 1
    assert result.position_lots == (lot,) and result.opening_balances == ()
    assert result.confirmation is None
    assert result.high_water_sequence == 1
    with pytest.raises(FrozenInstanceError):
        result.inventory_revision = 99


def test_backdated_sale_changes_inventory_only_when_manually_registered(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(lot.id, quantity=300, trade_date=D1.date())
        work.commit()

    earlier = _read(engine)
    immediately_before = _read(engine, cutoff=D3 - timedelta(microseconds=1))
    at_registration = _read(engine, cutoff=D3)

    assert _registered_quantity(earlier) == _registered_quantity(immediately_before) == 1000
    assert earlier.inventory_revision == 1 and earlier.current_revision == 2
    assert _registered_quantity(at_registration) == 700
    assert at_registration.inventory_revision == at_registration.current_revision == 2
    assert earlier.high_water_sequence == at_registration.high_water_sequence == 2


def test_registered_sale_survives_reopen_and_repeated_reads_do_not_reduce_again(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(lot.id, quantity=300, trade_date=D1.date())
        work.commit()
    path = engine.url.database
    engine.dispose()
    reopened = create_sqlite_engine(path)
    try:
        first = _read(reopened, cutoff=D3)
        second = _read(reopened, cutoff=D3)
        assert first == second
        assert _registered_quantity(first) == 700
        with reopened.connect() as connection:
            assert connection.scalar(text("SELECT remaining_qty FROM position_lot")) == 700
            assert connection.scalar(text(
                "SELECT count(*) FROM audit_log WHERE action='POSITION_REDUCTION_RECORDED'"
            )) == 1
    finally:
        reopened.dispose()


def test_lot_closed_later_remains_open_in_earlier_inventory(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(lot.id, quantity=1000, trade_date=D1.date())
        work.commit()

    earlier = _read(engine)
    later = _read(engine, cutoff=D3)

    assert _registered_quantity(earlier) == 1000
    assert earlier.position_lots[0].closed_at is None
    assert _registered_quantity(later) == 0 and later.position_lots == ()
    assert later.inventory_revision == 2


def test_rolled_back_manual_sale_is_absent_after_reopen(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(lot.id, quantity=300, trade_date=D1.date())
        # Leaving without commit rolls back the source, receipt, publication and quantity.
    engine.dispose()

    result = _read(engine, cutoff=D3)

    assert _registered_quantity(result) == 1000
    assert result.inventory_revision == result.current_revision == result.high_water_sequence == 1


@pytest.mark.parametrize("sold", [300, 1000])
def test_opening_balance_reduction_and_closure_use_registration_time(engine, sold):
    with _work(engine, D1) as work:
        inventory = _confirm(work, total=1000, revision=0)
        opening_id = inventory.opening_balances[0].id
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_opening_balance(
            opening_id, quantity=sold, trade_date=D1.date(),
        )
        work.commit()
    engine.dispose()

    earlier = _read(engine)
    later = _read(engine, cutoff=D3)

    assert _registered_quantity(earlier) == 1000
    assert earlier.position_lots == ()
    assert earlier.opening_balances[0].id == opening_id
    assert earlier.opening_balances[0].revision == 0
    assert earlier.opening_balances[0].closed_at is None
    assert earlier.inventory_revision == 1 and earlier.current_revision == 2
    assert _registered_quantity(later) == 1000 - sold
    assert later.inventory_revision == 2
    if sold == 1000:
        assert later.opening_balances == ()
    else:
        assert later.opening_balances[0].revision == 3


def test_all_mutations_at_same_registration_instant_are_included(engine):
    with _work(engine, D1) as work:
        first = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(first.id, quantity=300, trade_date=D1.date())
        second = _buy(work, quantity=200)
        work.positions.reduce_lot(first.id, quantity=100, trade_date=D1.date())
        work.commit()

    before = _read(engine, cutoff=D3 - timedelta(microseconds=1))
    inclusive = _read(engine, cutoff=D3)

    assert _registered_quantity(before) == 1000 and before.inventory_revision == 1
    assert _registered_quantity(inclusive) == 800 and inclusive.inventory_revision == 4
    assert {lot.id: lot.remaining_qty for lot in inclusive.position_lots} == {
        first.id: 600, second.id: 200,
    }


def test_reconfirmation_preserves_historical_confirmation_and_both_member_roots(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        first = _confirm(work, total=1200, revision=1, lots=(lot.id,))
        work.commit()
    with _work(engine, D3) as work:
        latest = _confirm(work, total=1200, revision=2, lots=(lot.id,), day=D3.date())
        work.commit()

    earlier = _read(engine, cutoff=D1)
    later = _read(engine, cutoff=D3)

    assert _registered_quantity(earlier) == _registered_quantity(later) == 1200
    assert earlier.inventory_revision == 2 and earlier.current_revision == 3
    assert isinstance(earlier.confirmation, InventoryConfirmationSnapshot)
    assert earlier.confirmation.confirmation_id == first.confirmation_id
    assert earlier.confirmation.as_of_trade_date == D1.date()
    assert earlier.confirmation.confirmed_at == D1.isoformat()
    assert earlier.confirmation.included_lot_ids == (lot.id,)
    assert earlier.confirmation.opening_balance_ids == (first.opening_balances[0].id,)
    assert later.confirmation.confirmation_id == latest.confirmation_id
    assert later.confirmation.as_of_trade_date == D3.date()
    assert later.confirmation.confirmed_at == D3.isoformat()


def test_reconfirming_no_sale_keeps_quantity_and_does_not_invent_sale_registration(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        work.commit()
    with _work(engine, D3) as work:
        _confirm(work, total=1000, revision=1, lots=(lot.id,), day=D3.date())
        work.commit()

    assert _registered_quantity(_read(engine, cutoff=D3)) == 1000
    with engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM audit_log WHERE action='POSITION_REDUCTION_RECORDED'"
        )) == 0
        assert connection.scalar(text("SELECT remaining_qty FROM position_lot")) == 1000


@pytest.mark.parametrize("statement", [
    "DELETE FROM audit_log WHERE action='POSITION_INVENTORY_CHANGED'",
    "DELETE FROM audit_log WHERE action='POSITION_BUY_RECORDED'",
    "DELETE FROM position_lot",
])
def test_missing_receipt_source_or_current_member_does_not_prove_inventory(engine, statement):
    with _work(engine, D1) as work:
        _buy(work)
        work.commit()
    with engine.begin() as connection:
        connection.execute(text(statement))

    result = _read(engine)

    assert isinstance(result, UnknownInventoryHistory)
    assert result.status == "UNKNOWN"


def test_no_registered_history_cannot_prove_an_empty_account(engine):
    result = _read(engine)
    assert isinstance(result, UnknownInventoryHistory)
    assert result.status == "UNKNOWN" and result.reason == "MISSING_EVIDENCE"


def test_other_symbols_do_not_change_selected_inventory_revision(engine):
    with _work(engine, D1) as work:
        lot = _buy(work)
        _buy(work, symbol="003044.SZ", quantity=200)
        work.commit()
    with _work(engine, D3) as work:
        _buy(work, symbol="003044.SZ", quantity=300)
        work.commit()

    result = _read(engine)

    assert _registered_quantity(result) == 1000
    assert result.position_lots == (lot,)
    assert result.inventory_revision == result.current_revision == 1
    assert result.high_water_sequence == 3


def test_synced_confirmation_retains_old_members_without_invalidating_registered_ledger(engine):
    with _work(engine, D1) as work:
        original = _buy(work)
        _confirm(work, total=1000, revision=1, lots=(original.id,))
        work.commit()
    with _work(engine, D3) as work:
        work.positions.reduce_lot(original.id, quantity=1000, trade_date=D1.date())
        replacement = _buy(work, quantity=200)
        work.commit()

    result = _read(engine, cutoff=D3)
    assert _registered_quantity(result) == 200
    assert result.position_lots == (replacement,)
    assert result.confirmation.included_lot_ids == (original.id,)
    assert result.confirmation.inventory_revision == result.current_revision == 4


def test_cutoff_before_first_registration_is_only_an_empty_registered_ledger(engine):
    with _work(engine, D1) as work:
        _buy(work)
        work.commit()
    result = _read(engine, cutoff=D1 - timedelta(seconds=1))
    assert _registered_quantity(result) == 0
    assert result.inventory_revision == 0 and result.current_revision == 1
    assert result.confirmation is None


def test_explicit_zero_total_confirmation_proves_registered_empty_inventory(engine):
    with _work(engine, D1) as work:
        confirmation = _confirm(work, total=0, revision=0)
        work.commit()
    result = _read(engine)
    assert _registered_quantity(result) == 0
    assert result.confirmation.confirmation_id == confirmation.confirmation_id
    assert result.confirmation.complete_registration is True
    assert result.inventory_revision == result.current_revision == 1
    assert result.high_water_sequence == 0


def test_malformed_confirmation_boolean_is_not_coerced_to_true(engine):
    with _work(engine, D1) as work:
        _confirm(work, total=0, revision=0)
        work.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        try:
            connection.exec_driver_sql(
                "UPDATE position_inventory_confirmation SET complete_registration=2"
            )
        finally:
            connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    assert isinstance(_read(engine), UnknownInventoryHistory)
