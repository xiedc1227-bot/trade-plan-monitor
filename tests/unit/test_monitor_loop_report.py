"""Market valuation never substitutes cost basis or invents missing account facts."""

from decimal import localcontext

import pytest
from pydantic import ValidationError
from tests.unit.test_monitor_loop_input import account, lot
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.loop_account import LoopAccountState, LoopLedgerLot
from trade_plan_monitor.backtest.loop_input import KnownLoopCash, UnknownLoopCash
from trade_plan_monitor.backtest.loop_report import project_loop_valuation


def state(opening=None, **changes):
    opening = opening or account()
    return LoopAccountState(
        **(
            {
                "revision": 1,
                "cash": opening.cash,
                "inventory_known": opening.inventory_known,
                "lots": tuple(
                    LoopLedgerLot(**value.model_dump(exclude={"sellable_quantity", "evidence"}))
                    for value in opening.lots
                ),
                "realized_pnl_fen": 0,
                "paid_fees_fen": 0,
            }
            | changes
        )
    )


def valued(value, price=3970):
    return project_loop_valuation(
        value,
        at=at(20, 10),
        price_fen=price,
        price_at=at(20, 9, 59),
        available_at=at(20, 9, 59, 12),
    )


def test_historical_cost_and_market_equity_are_separate_exact_amounts():
    point = valued(state(account(cash=KnownLoopCash(balance_fen=500000))))
    assert point.accounting_cost_fen == 401050
    assert point.market_value_fen == 397000
    assert point.equity_fen == 897000
    assert point.unrealized_pnl_fen == point.cost_pnl_fen == -4050
    assert point.valuation_valid


@pytest.mark.parametrize("missing", ["cash", "inventory", "price", "cost"])
def test_unknown_facts_preserve_corresponding_null_values(missing):
    opening = account(cash=KnownLoopCash(balance_fen=0))
    if missing == "cash":
        opening = opening.model_copy(update={"cash": UnknownLoopCash()})
    if missing == "inventory":
        opening = opening.model_copy(update={"inventory_known": False, "lots": ()})
    if missing == "cost":
        opening = opening.model_copy(update={"lots": (lot(cost_basis_fen=None),)})
    point = (
        project_loop_valuation(state(opening), at=at(20, 10))
        if missing == "price"
        else valued(state(opening))
    )
    assert point.valuation_valid == (missing == "cost")
    assert (point.equity_fen is None) == (missing != "cost")
    if missing in {"inventory", "price", "cost"}:
        assert point.cost_pnl_fen is None
    if missing == "cash":
        assert point.cash_fen is None and point.market_value_fen == 397000


def test_empty_inventory_needs_no_price_and_zero_cash_is_known():
    point = project_loop_valuation(state(account(lots=())), at=at())
    assert point.valuation_valid and point.equity_fen == point.market_value_fen == 0
    assert point.cash_fen == point.cost_pnl_fen == 0


def test_price_times_and_safe_integer_overflow_reject():
    with pytest.raises(ValueError):
        project_loop_valuation(
            state(), at=at(), price_fen=4000, price_at=at(20, 10), available_at=at(20, 10)
        )
    with pytest.raises(ValidationError):
        valued(state(), price=9007199254740991)


def test_projection_is_independent_of_decimal_context():
    with localcontext() as context:
        context.prec = 2
        first = valued(state())
    assert first == valued(state()) and first.cost_pnl_fen == -4050
