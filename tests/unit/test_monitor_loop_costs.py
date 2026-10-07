"""Exact source fee assumptions use absolute per-share fen slippage."""

import pytest
from tests.unit.test_monitor_loop_input import costs


def test_source_fee_example_preserves_absolute_slippage_and_each_fee_ceiling():
    from trade_plan_monitor.backtest.loop_account import calculate_loop_costs

    buy = calculate_loop_costs(side="BUY", quote_fen=2870, quantity=100, costs=costs())
    assert (buy.fill_price_fen, buy.notional_fen) == (2871, 287100)
    assert (buy.commission_fen, buy.stamp_duty_fen, buy.transfer_fee_fen) == (500, 0, 3)
    assert buy.total_fees_fen == 503
    sell = calculate_loop_costs(side="SELL", quote_fen=2930, quantity=100, costs=costs())
    assert (sell.fill_price_fen, sell.notional_fen) == (2929, 292900)
    assert (sell.commission_fen, sell.stamp_duty_fen, sell.transfer_fee_fen) == (500, 147, 3)
    assert sell.total_fees_fen == 650


@pytest.mark.parametrize(
    "changes",
    [
        {"side": "OTHER"},
        {"quote_fen": True},
        {"quote_fen": 0},
        {"quote_fen": 1, "side": "SELL"},
        {"quantity": 150},
        {"quantity": False},
        {"quote_fen": 9_007_199_254_740_991},
    ],
)
def test_costs_reject_invalid_units_nonpositive_or_unsafe_fill(changes):
    from trade_plan_monitor.backtest.loop_account import calculate_loop_costs

    with pytest.raises(ValueError):
        calculate_loop_costs(
            **({"side": "BUY", "quote_fen": 2870, "quantity": 100, "costs": costs()} | changes)
        )
