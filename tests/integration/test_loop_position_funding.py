"""Position-limited research never requires an invented cash balance."""

import pytest
from tests.integration.test_monitor_loop_account import command
from tests.unit.test_monitor_loop_input import account, frozen
from tests.unit.test_monitor_loop_schedule import calendar


def test_position_only_buy_accounts_for_costs_without_cash_and_preserves_replay(tmp_path):
    from trade_plan_monitor.backtest.loop_input import PositionLimitFunding
    from trade_plan_monitor.backtest.loop_publication import _verify_settlement
    from trade_plan_monitor.backtest.loop_report import project_loop_valuation
    from trade_plan_monitor.backtest.loop_session import LoopSession

    run = frozen(initial_account=account(cash=PositionLimitFunding()))
    with LoopSession(tmp_path, run, calendar()) as loop:
        offered = command(loop)
        before = loop.account()
        receipt = loop.execute(offered, request_key="position-limited-buy")
        assert receipt.account.cash.kind == "POSITION_LIMIT_ONLY"
        assert loop.inventory()["total_qty"] == 200
        assert receipt.account.accounting_cost_fen == 798654
        assert receipt.account.paid_fees_fen == 504
        assert _verify_settlement(before, receipt, run.costs) == receipt.account
        valuation = project_loop_valuation(
            receipt.account, at=loop.now, price_fen=3971, price_at=loop.now, available_at=loop.now
        )
        assert valuation.equity_fen is None and valuation.cash_fen is None
        assert "CASH_UNKNOWN" not in valuation.blockers
        assert "CAPITAL_NOT_MODELED" in valuation.blockers
        assert loop.execute(offered, request_key="position-limited-buy") == receipt


def test_no_cash_constraint_does_not_bypass_plan_quantity_authority(tmp_path):
    from trade_plan_monitor.backtest.loop_input import PositionLimitFunding
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(
        tmp_path, frozen(initial_account=account(cash=PositionLimitFunding())), calendar()
    ) as loop:
        offered = command(loop)
        before = loop.account()
        with pytest.raises(ValueError):
            loop.execute(offered.model_copy(update={"quantity": 1000}), request_key="oversized")
        assert loop.account() == before


def test_position_only_sell_preserves_realized_pnl_and_settlement_integrity(tmp_path):
    from tests.unit.test_monitor_loop_input import lot
    from tests.unit.test_monitor_loop_schedule import row, version
    from tests.unit.test_unified_replay_input import research_plan

    from trade_plan_monitor.backtest.loop_input import PositionLimitFunding
    from trade_plan_monitor.backtest.loop_publication import _verify_settlement
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.plan_schedule import LoopSchedule

    original = research_plan()
    plan = original.model_copy(
        update={"ordinary_rules": (original.ordinary_rules[0].model_copy(update={"side": "SELL"}),)}
    )
    opening = account(
        cash=PositionLimitFunding(),
        lots=(
            lot(),
            lot(
                "tactical",
                bucket="TACTICAL",
                quantity=200,
                sellable_quantity=100,
                cost_basis_fen=574205,
            ),
        ),
    )
    run = frozen(
        schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)), initial_account=opening
    )
    with LoopSession(tmp_path, run, calendar()) as loop:
        offered = command(loop)
        before = loop.account()
        receipt = loop.execute(offered, request_key="position-sell")
        assert receipt.account.cash == PositionLimitFunding()
        assert receipt.account.realized_pnl_fen == 109095
        assert receipt.account.accounting_cost_fen == 688153
        assert receipt.account.paid_fees_fen == 703
        assert _verify_settlement(before, receipt, run.costs) == receipt.account
