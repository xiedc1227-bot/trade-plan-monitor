"""Money projections never authorize or resize current monitor simulations."""

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from hashlib import sha256

from trade_plan_monitor.backtest.execution import _fees, _fill_price
from trade_plan_monitor.backtest.models import ExecutionSide
from trade_plan_monitor.backtest.research_report import (
    ResearchEquity,
    ResearchMetrics,
    ResearchOperationValuation,
)


def _safe_amounts(*values):
    if any(abs(value) > 9_007_199_254_740_991 for value in values if value is not None):
        raise ValueError("RESEARCH_VALUATION_SAFE_NUMBER_EXCEEDED")


class ResearchValuation:
    def __init__(self, run_input):
        self.run_input = run_input
        self.cash = run_input.initial_cash_fen
        self.initial_equity = self.cash + sum(lot.cost_basis_fen for lot in run_input.initial_lots)
        self.valid = run_input.research_input.inventory_known
        self.blockers = [] if self.valid else ["VALUATION_EXCLUDES_UNKNOWN_HOLDINGS"]
        self.cost = self.trades = 0
        self.marks = {}

    def operation(self, outcome):
        if outcome.kind != "SIMULATE" or outcome.status != "APPLIED":
            return outcome
        side = ExecutionSide(outcome.side)
        price = _fill_price(
            outcome.monitor_price_fen, side=side, config=self.run_input.execution_config
        )
        notional = price * outcome.quantity
        fees = _fees(
            side=side, notional_fen=notional, config=self.run_input.execution_config
        ).total_fen
        delta = -notional - fees if side is ExecutionSide.BUY else notional - fees
        _safe_amounts(price, notional, fees, delta, self.cash + delta, self.cost + fees)
        if self.valid and self.cash + delta < 0:
            self.valid = False
            self.blockers.append("INSUFFICIENT_RESEARCH_CASH")
        if self.valid:
            self.cash += delta
            self.cost += fees
        self.trades += 1
        return outcome.model_copy(
            update={
                "valuation": ResearchOperationValuation(
                    status="PROJECTED" if self.valid else "BLOCKED",
                    blockers=tuple(self.blockers),
                    research_price_fen=price,
                    notional_fen=notional,
                    fees_fen=fees,
                    cash_delta_fen=delta,
                    cash_after_fen=self.cash if self.valid else None,
                )
            }
        )

    def mark(self, at, inventory, price):
        valid = self.valid and (price is not None or inventory.total_qty == 0)
        blockers = tuple(self.blockers) + (
            () if valid or not self.valid else ("RESEARCH_MARK_PRICE_MISSING",)
        )
        market = (
            None if inventory.total_qty is None or price is None else inventory.total_qty * price
        )
        if inventory.total_qty == 0:
            market = 0
        _safe_amounts(price, self.cash, market, self.cash + market if market is not None else None)
        self.marks[at.date()] = ResearchEquity(
            snapshot_id=sha256((self.run_input.authority_id + str(at.date())).encode()).hexdigest(),
            marked_at=at,
            mark_price_fen=price,
            cash_fen=self.cash if self.valid else None,
            position_quantity=inventory.total_qty,
            market_value_fen=market,
            equity_fen=self.cash + market if valid else None,
            valuation_valid=valid,
            blockers=blockers,
        )

    def metrics(self, outcomes):
        final = list(self.marks.values())[-1]
        valid = final.valuation_valid and self.run_input.research_input.inventory_known
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            total_return = (
                Decimal(final.equity_fen - self.initial_equity) / Decimal(self.initial_equity)
                if valid
                else None
            )
        return ResearchMetrics(
            initial_cash_fen=self.run_input.initial_cash_fen,
            initial_equity_fen=self.initial_equity
            if self.run_input.research_input.inventory_known
            else None,
            final_cash_fen=final.cash_fen,
            final_equity_fen=final.equity_fen,
            total_return=total_return,
            total_cost_fen=self.cost,
            trade_count=self.trades,
            blocked_count=sum(outcome.status == "BLOCKED" for outcome in outcomes),
            valuation_valid=valid,
        )
