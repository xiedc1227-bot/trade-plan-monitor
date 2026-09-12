from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.position_service import PersistentPositionOperationService
from trade_plan_monitor.web.routers.positions import PositionInventoryConfirmationCommand
from trade_plan_monitor.web.schemas import MutationContext

NOW = datetime(2026, 9, 14, 9, 20, tzinfo=ZoneInfo("Asia/Shanghai"))


def _work(engine):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW)


def _seed_calendar(work) -> None:
    work.references.upsert_trading_days(
        (
            TradingDay(
                exchange="SZSE",
                cal_date=date(2026, 9, 14),
                is_open=True,
                previous_trade_date=date(2026, 9, 11),
            ),
        )
    )


def test_inventory_distinguishes_unknown_from_explicit_zero_and_survives_restart(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-zero.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            unknown = work.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                cutoff=NOW,
            )
            assert unknown.status == "UNKNOWN"
            assert unknown.total_qty is None
            assert unknown.sellable_qty is None
            assert unknown.inventory_revision == 0
            _seed_calendar(work)
            known = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=0,
                sellable_quantity=0,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            work.commit()
            assert known.status == "KNOWN"
            assert known.total_qty == 0
            assert known.sellable_qty == 0
            assert known.opening_balances == ()

        with _work(engine) as restarted:
            restored = restarted.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                cutoff=NOW,
            )
            assert restored == known
    finally:
        engine.dispose()


def test_confirmed_opening_balance_needs_no_active_plan_cost_or_acquisition_date(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-opening.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            _seed_calendar(work)
            first = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            assert first.status == "KNOWN"
            assert first.total_qty == first.sellable_qty == 100
            assert len(first.opening_balances) == 1
            balance = first.opening_balances[0]
            assert balance.original_qty == balance.remaining_qty == 100
            assert balance.sellable_from == date(2026, 9, 14)
            assert not hasattr(balance, "cost_fen")
            assert not hasattr(balance, "acquired_trade_date")

            repeated = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=first.inventory_revision,
            )
            work.commit()
            assert repeated.total_qty == 100
            assert repeated.opening_balances == first.opening_balances
    finally:
        engine.dispose()


def test_inventory_confirmation_counts_included_lots_once_and_fences_revision(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-lot.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            _seed_calendar(work)
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=100,
                acquired_trade_date=date(2026, 9, 11),
                cost_fen=990,
                board_lot=100,
                max_position_qty=300,
            )
            current = work.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                cutoff=NOW,
            )
            assert current.status == "UNKNOWN"
            confirmed = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(lot.id,),
                complete_registration=True,
                expected_revision=current.inventory_revision,
            )
            assert confirmed.total_qty == 100
            assert confirmed.sellable_qty == 100
            assert confirmed.opening_balances == ()

            with pytest.raises(RevisionConflictError):
                work.positions.confirm_inventory(
                    symbol="003043.SZ",
                    as_of_trade_date=date(2026, 9, 14),
                    total_quantity=200,
                    sellable_quantity=200,
                    included_lot_ids=(lot.id,),
                    complete_registration=True,
                    expected_revision=current.inventory_revision,
                )
    finally:
        engine.dispose()


def test_inventory_confirmation_idempotency_replays_across_service_restart(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-idempotency.sqlite3")
    factory = create_session_factory(engine)
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            _seed_calendar(work)
            work.commit()

        def new_service() -> PersistentPositionOperationService:
            return PersistentPositionOperationService(
                unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(
                    factory,
                    clock=lambda: NOW,
                ),
                clock=lambda: NOW,
            )

        command = PositionInventoryConfirmationCommand(
            symbol="003043.SZ",
            as_of_trade_date=date(2026, 9, 14),
            expected_revision=0,
            total_quantity=100,
            sellable_quantity=100,
            included_lot_ids=(),
            complete_registration=True,
        )
        context = MutationContext(
            idempotency_key="inventory-confirm-1",
            request_id="a" * 32,
        )
        first = asyncio.run(
            new_service().confirm_position_inventory(command=command, context=context)
        )
        replay = asyncio.run(
            new_service().confirm_position_inventory(command=command, context=context)
        )

        assert replay == first
        snapshot = asyncio.run(
            new_service().get_position_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
            )
        )
        assert snapshot.total_quantity == 100
        assert len(snapshot.opening_balances) == 1
    finally:
        engine.dispose()


def test_inventory_keeps_known_total_but_never_guesses_sellability_without_calendar(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-calendar-gap.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            _seed_calendar(work)
            confirmed = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            work.commit()

        with _work(engine) as restarted:
            future = restarted.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 15),
                cutoff=NOW + timedelta(days=1),
            )

        assert confirmed.total_qty == confirmed.sellable_qty == 100
        assert future.status == "KNOWN"
        assert future.total_qty == 100
        assert future.sellable_qty is None
        assert future.missing_reasons == ("SELLABLE_QUANTITY_UNKNOWN",)
    finally:
        engine.dispose()


def test_opening_balance_closure_is_audited_revisioned_and_restart_safe(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-opening-close.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            _seed_calendar(work)
            confirmed = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=100,
                included_lot_ids=(),
                complete_registration=True,
                expected_revision=0,
            )
            balance = confirmed.opening_balances[0]
            closed = work.positions.reduce_opening_balance(
                balance.id,
                quantity=100,
                trade_date=date(2026, 9, 14),
                expected_revision=0,
            )
            work.commit()

        assert closed.remaining_qty == 0
        assert closed.revision == 1
        assert closed.closed_at == NOW
        with _work(engine) as restarted:
            restored = restarted.positions.get_opening_balance(balance.id)
            inventory = restarted.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                cutoff=NOW,
            )
        assert restored == closed
        assert inventory.status == "KNOWN"
        assert inventory.total_qty == inventory.sellable_qty == 0
        assert inventory.inventory_revision == confirmed.inventory_revision + 1
    finally:
        engine.dispose()


def test_lot_bought_on_confirmation_day_can_be_closed_after_t_plus_one(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "inventory-lot-t-plus-one.sqlite3")
    try:
        upgrade_database(engine)
        with _work(engine) as work:
            work.references.upsert_trading_days(
                (
                    TradingDay(
                        exchange="SZSE",
                        cal_date=date(2026, 9, 14),
                        is_open=True,
                        previous_trade_date=date(2026, 9, 11),
                    ),
                    TradingDay(
                        exchange="SZSE",
                        cal_date=date(2026, 9, 15),
                        is_open=True,
                        previous_trade_date=date(2026, 9, 14),
                    ),
                )
            )
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=100,
                acquired_trade_date=date(2026, 9, 14),
                cost_fen=990,
                board_lot=100,
                max_position_qty=300,
            )
            unconfirmed = work.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                cutoff=NOW,
            )
            confirmed = work.positions.confirm_inventory(
                symbol="003043.SZ",
                as_of_trade_date=date(2026, 9, 14),
                total_quantity=100,
                sellable_quantity=0,
                included_lot_ids=(lot.id,),
                complete_registration=True,
                expected_revision=unconfirmed.inventory_revision,
            )
            closed = work.positions.reduce_lot(
                lot.id,
                quantity=100,
                trade_date=date(2026, 9, 15),
                expected_revision=0,
            )
            work.commit()

        assert closed.remaining_qty == 0
        with _work(engine) as restarted:
            inventory = restarted.positions.inventory_snapshot(
                "003043.SZ",
                as_of_trade_date=date(2026, 9, 15),
                cutoff=NOW + timedelta(days=1),
            )
        assert inventory.total_qty == inventory.sellable_qty == 0
        assert inventory.inventory_revision == confirmed.inventory_revision + 1
    finally:
        engine.dispose()
