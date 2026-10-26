"""Actual simulation allocations and budget sidecar commit or roll back together."""

from datetime import timedelta
from itertools import count

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_p3_opening import context, opening
from tests.integration.test_p3_storage import NOW, database

from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_capital_service import confirm_capital_opening

__all__ = ["database"]


def setup_account(session, quantity=400, with_book=True):
    for delta in (0, 1):
        day = NOW.date() + timedelta(days=delta)
        session.add(
            TradingCalendar(
                exchange="SSE",
                cal_date=day,
                is_open=True,
                previous_trade_date=day - timedelta(days=1),
            )
        )
    session.flush()
    identifiers = count()
    daily = DailyRepository(
        session, clock=lambda: NOW, id_factory=lambda: f"fixture-{next(identifiers):08d}"
    )
    account = DailyAccounting(daily)
    account.initialize(
        symbol="601021.SH", core_qty=0, tactical_qty=quantity, expected_revision=0, now=NOW
    )
    if with_book:
        ctx = context()
        confirm_capital_opening(
            session, opening(ctx), command_id="opening", now=NOW, current=lambda _: ctx
        )
    return account


def simulate(account, identity, side, quantity=100, revision=1, debit=None, now=NOW):
    return account.simulate(
        symbol="601021.SH",
        identity=identity,
        side=side,
        quantities={"TACTICAL": quantity},
        expected_revision=revision,
        now=now,
        capital_debit_fen=debit,
    )


def test_budget_buy_and_actual_newest_sell_allocation_have_exact_basis(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        account = setup_account(session)
        simulate(account, "new", "BUY", debit=100500)
        repo = CapitalRepository(session)
        assert repo.get("601021.SH").retained_basis_fen == 550501
        simulate(account, "sell-old", "SELL", revision=2)
        assert repo.get("601021.SH").retained_basis_fen == 438001
        # On the next day the newest lot is sellable, and precisely its100500 is released.
        simulate(account, "sell-new", "SELL", revision=3, now=NOW + timedelta(days=1))
        book = repo.get("601021.SH")
        assert book.retained_basis_fen == 337501
        assert book.inventory_revision == 4 and book.lots[0].quantity == 300


def test_older_buy_records_unknown_and_selling_unknown_lot_restores_known_basis(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        account = setup_account(session)
        simulate(account, "old-version-buy", "BUY")
        repo = CapitalRepository(session)
        assert repo.get("601021.SH").retained_basis_fen is None
        simulate(account, "sell-unknown", "SELL", revision=2, now=NOW + timedelta(days=1))
        assert repo.get("601021.SH").retained_basis_fen == 450001


def test_missing_old_cost_blocks_known_budget_buy_before_any_inventory_write(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        account = setup_account(session, with_book=False)
        with pytest.raises(ValueError, match="CAPITAL_BASE_UNKNOWN"):
            simulate(account, "cannot-infer", "BUY", debit=100500)
        assert account.snapshot("601021.SH", NOW.date())["revision"] == 1
        assert CapitalRepository(session).get("601021.SH") is None


def test_explicit_empty_inventory_creates_budget_only_with_the_buy(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        account = setup_account(session, quantity=0, with_book=False)
        assert CapitalRepository(session).get("601021.SH") is None
        simulate(account, "empty-buy", "BUY", debit=100500)
        book = CapitalRepository(session).get("601021.SH")
        assert book.revision == 1 and book.inventory_revision == 2
        assert book.retained_basis_fen == 100500


def test_old_binary_quantity_change_marks_cost_unknown_without_vetoing_sell(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        account = setup_account(session)
        old = account.repo.get("simulation-position-601021.SH")
        data = dict(old["payload"])
        data["batches"] = [dict(data["batches"][0], quantity=300)]
        account.repo.save(
            old["id"],
            kind="POSITION",
            symbol="601021.SH",
            lineage="601021.SH",
            expected_revision=1,
            payload=data,
        )
        simulate(account, "risk-sell", "SELL", revision=2)
        repo = CapitalRepository(session)
        assert repo.get("601021.SH").retained_basis_fen is None
        simulate(account, "risk-rest", "SELL", quantity=200, revision=3)
        assert repo.get("601021.SH").retained_basis_fen == 0


def test_fault_after_inventory_and_budget_writes_rolls_every_effect_back(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        setup_account(session)
    with pytest.raises(RuntimeError, match="fault"):
        with Session(engine) as session, session.begin():
            account = DailyAccounting(
                DailyRepository(session, clock=lambda: NOW, id_factory=lambda: "fixture")
            )
            simulate(account, "rolled-back", "BUY", debit=100500)
            raise RuntimeError("fault after both writes")
    with Session(engine) as session:
        book = CapitalRepository(session).get("601021.SH")
        assert book.revision == 1 and book.retained_basis_fen == 450001
        assert (
            DailyAccounting(
                DailyRepository(session, clock=lambda: NOW, id_factory=lambda: "fixture")
            ).snapshot("601021.SH", NOW.date())["revision"]
            == 1
        )
