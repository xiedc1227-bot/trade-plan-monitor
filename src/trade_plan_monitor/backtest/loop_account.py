"""Private exact-fen money participant; shared simulation owns inventory/authority."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select

from trade_plan_monitor.backtest.loop_input import (
    KnownLoopCash,
    LoopCosts,
    PositionLimitFunding,
    SafeFen,
    SafePositiveFen,
    SafePositiveShares,
    UnknownLoopCash,
)
from trade_plan_monitor.backtest.models import StableIdentifier
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.run_input import MAX_SAFE_INTEGER
from trade_plan_monitor.runtime.daily_service import minute_source_current
from trade_plan_monitor.state.simulation import (
    SimulationCommand,
    SimulationReceipt,
    simulate_inventory,
)

SignedFen = Annotated[int, Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)]
_REQUEST_KEY = TypeAdapter(StableIdentifier)
ACCOUNT_METADATA = MetaData()
ACCOUNT_TABLE = Table(
    "monitor_loop_account",
    ACCOUNT_METADATA,
    Column("singleton_id", Integer, primary_key=True),
    Column("payload_json", Text, nullable=False),
)
RECEIPT_TABLE = Table(
    "monitor_loop_fill",
    ACCOUNT_METADATA,
    Column("request_key", String(128), primary_key=True),
    Column("payload_json", Text, nullable=False),
)


class LoopFillCosts(ResearchValue):
    side: Literal["BUY", "SELL"]
    quote_fen: SafePositiveFen
    quantity: SafePositiveShares
    fill_price_fen: SafePositiveFen
    notional_fen: SafePositiveFen
    commission_fen: SafeFen
    stamp_duty_fen: SafeFen
    transfer_fee_fen: SafeFen
    total_fees_fen: SafeFen

    @model_validator(mode="after")
    def sums(self):
        if self.notional_fen != self.fill_price_fen * self.quantity or self.total_fees_fen != (
            self.commission_fen + self.stamp_duty_fen + self.transfer_fee_fen
        ):
            raise ValueError("inconsistent fill amounts")
        return self


def calculate_loop_costs(*, side, quote_fen, quantity, costs: LoopCosts) -> LoopFillCosts:
    """Keep existing upward fee rounding; never round through floats or basis points."""
    if side not in {"BUY", "SELL"} or type(quote_fen) is not int or type(quantity) is not int:
        raise ValueError("invalid loop fill units")
    if (
        not 0 < quote_fen <= MAX_SAFE_INTEGER
        or not 0 < quantity <= MAX_SAFE_INTEGER
        or quantity % 100
    ):
        raise ValueError("invalid loop fill units")
    price = (
        quote_fen + costs.buy_slippage_fen if side == "BUY" else quote_fen - costs.sell_slippage_fen
    )
    notional = price * quantity

    def fee(rate):
        numerator, denominator = rate.as_integer_ratio()
        return (notional * numerator + denominator - 1) // denominator

    commission = max(costs.minimum_commission_fen, fee(costs.commission_rate))
    stamp = fee(costs.stamp_duty_rate) if side == "SELL" else 0
    transfer = fee(costs.transfer_fee_rate)
    return LoopFillCosts(
        side=side,
        quote_fen=quote_fen,
        quantity=quantity,
        fill_price_fen=price,
        notional_fen=notional,
        commission_fen=commission,
        stamp_duty_fen=stamp,
        transfer_fee_fen=transfer,
        total_fees_fen=commission + stamp + transfer,
    )


class LoopLedgerLot(ResearchValue):
    lot_key: StableIdentifier
    bucket: Literal["CORE", "TACTICAL"]
    quantity: SafePositiveShares
    cost_basis_fen: SafeFen | None
    acquired_trade_date: date | None
    plan_version_id: str | None = Field(default=None, exclude_if=lambda v: v is None)


class LoopAccountState(ResearchValue):
    revision: int = Field(ge=1, le=MAX_SAFE_INTEGER)
    cash: KnownLoopCash | UnknownLoopCash | PositionLimitFunding
    inventory_known: bool
    lots: tuple[LoopLedgerLot, ...] = Field(max_length=500)
    realized_pnl_fen: SignedFen | None
    paid_fees_fen: SafeFen

    @classmethod
    def from_opening(cls, opening):
        """Project reviewed opening facts identically for execution and verification."""
        return cls(
            revision=1,
            cash=opening.cash,
            inventory_known=opening.inventory_known,
            realized_pnl_fen=0,
            paid_fees_fen=0,
            lots=tuple(
                LoopLedgerLot(
                    lot_key=lot.lot_key,
                    bucket=lot.bucket,
                    quantity=lot.quantity,
                    cost_basis_fen=lot.cost_basis_fen,
                    acquired_trade_date=lot.acquired_trade_date,
                )
                for lot in opening.lots
            ),
        )

    @model_validator(mode="after")
    def bounded(self):
        keys = tuple((lot.lot_key, lot.bucket) for lot in self.lots)
        if len(set(keys)) != len(keys) or (not self.inventory_known and self.lots):
            raise ValueError("inconsistent ledger lots")
        if (
            sum(lot.quantity for lot in self.lots) > MAX_SAFE_INTEGER
            or sum(lot.cost_basis_fen or 0 for lot in self.lots) > MAX_SAFE_INTEGER
        ):
            raise ValueError("ledger totals exceed safe integer bounds")
        return self

    @property
    def accounting_cost_fen(self):
        if not self.inventory_known or any(lot.cost_basis_fen is None for lot in self.lots):
            return None
        return sum(lot.cost_basis_fen for lot in self.lots)


class LoopAccountReceipt(ResearchValue):
    request_key: StableIdentifier
    command: SimulationCommand
    costs: LoopCosts
    authority_receipt: SimulationReceipt
    settlement: LoopFillCosts
    released_cost_fen: SafeFen | None
    account: LoopAccountState

    @model_validator(mode="after")
    def consistent(self):
        authority = self.authority_receipt
        if self.command.quantity != authority.quantity or self.settlement != calculate_loop_costs(
            side=authority.side,
            quote_fen=authority.price_fen,
            quantity=authority.quantity,
            costs=self.costs,
        ):
            raise ValueError("inconsistent money/simulation receipt")
        for bucket, quantity in (
            ("CORE", authority.inventory.core_qty),
            ("TACTICAL", authority.inventory.tactical_qty),
        ):
            if sum(lot.quantity for lot in self.account.lots if lot.bucket == bucket) != quantity:
                raise ValueError("inconsistent receipt inventory")
        return self


class LoopAccountParticipant:
    """No commit here: a caller owns the money/inventory/receipt transaction."""

    def __init__(self, work):
        self.work, self.session = work, work.daily.session

    def initialize(self, opening):
        value = LoopAccountState.from_opening(opening)
        self.session.execute(
            ACCOUNT_TABLE.insert().values(singleton_id=1, payload_json=value.model_dump_json())
        )

    def state(self):
        raw = self.session.scalar(
            select(ACCOUNT_TABLE.c.payload_json).where(ACCOUNT_TABLE.c.singleton_id == 1)
        )
        if raw is None:
            raise ValueError("LOOP_ACCOUNT_MISSING")
        return LoopAccountState.model_validate_json(raw)

    def _save(self, value):
        self.session.execute(
            ACCOUNT_TABLE.update()
            .where(ACCOUNT_TABLE.c.singleton_id == 1)
            .values(payload_json=value.model_dump_json())
        )

    @staticmethod
    def _quantities(batches):
        return {(batch["id"], batch["bucket"]): batch["quantity"] for batch in batches}

    def apply(self, command, *, request_key, costs, now, identity_factory):
        command = SimulationCommand.model_validate(command.model_dump())
        request_key = _REQUEST_KEY.validate_python(request_key)
        prior = self.session.scalar(
            select(RECEIPT_TABLE.c.payload_json).where(RECEIPT_TABLE.c.request_key == request_key)
        )
        if prior is not None:
            receipt = LoopAccountReceipt.model_validate_json(prior)
            if receipt.command != command or receipt.costs != costs:
                raise ValueError("LOOP_FILL_REQUEST_CONFLICT")
            return receipt
        details = self.work.plans.get_version_details(str(command.plan_version_id))
        if details is None:
            raise ValueError("LOOP_PLAN_VERSION_NOT_FOUND")
        self.work.daily.lock_symbol(details.symbol)
        before = self.state()
        if before.cash.kind == "UNKNOWN":
            raise ValueError("LOOP_CASH_UNKNOWN")
        head = self.work.daily.get("evaluation-head-" + details.symbol)
        cause = self.work.daily.get(command.cause_id)
        if (
            head is None
            or cause is None
            or cause["symbol"] != details.symbol
            or (cause["kind"] not in {"SIGNAL", "RISK"})
        ):
            raise ValueError("LOOP_EXECUTION_EVIDENCE_MISSING")
        if head["payload"].get("minute_target") is not None and not minute_source_current(
            self.session, head["payload"], now
        ):
            raise ValueError("LOOP_CURRENT_MINUTE_EVIDENCE_REQUIRED")
        side = "SELL" if cause["kind"] == "RISK" else cause["payload"]["side"]
        quote = (head["payload"].get("quote") or {}).get("price_fen")
        settlement = calculate_loop_costs(
            side=side, quote_fen=quote, quantity=command.quantity, costs=costs
        )
        cash_delta = (
            -settlement.notional_fen - settlement.total_fees_fen
            if side == "BUY"
            else settlement.notional_fen - settlement.total_fees_fen
        )
        cash = before.cash
        if isinstance(cash, KnownLoopCash):
            if cash.balance_fen + cash_delta < 0:
                raise ValueError("LOOP_CASH_INSUFFICIENT")
            cash = KnownLoopCash(balance_fen=cash.balance_fen + cash_delta)
        position = self.work.daily.get("simulation-position-" + details.symbol)
        old_quantities = (
            {} if position is None else self._quantities(position["payload"]["batches"])
        )
        if old_quantities != {(lot.lot_key, lot.bucket): lot.quantity for lot in before.lots}:
            raise ValueError("LOOP_MONEY_INVENTORY_MISMATCH")
        authority = simulate_inventory(
            self.work, command, now=now, identity_factory=identity_factory
        )
        position = self.work.daily.get("simulation-position-" + details.symbol)
        new_quantities = self._quantities(position["payload"]["batches"])
        lots, released = [], 0
        for lot in before.lots:
            remaining = new_quantities.get((lot.lot_key, lot.bucket), 0)
            debit = lot.quantity - remaining
            if debit < 0:
                raise ValueError("LOOP_MONEY_INVENTORY_MISMATCH")
            # Whole-fen released basis rounds down; every residual fen stays with the lot.
            basis = (
                None if lot.cost_basis_fen is None else lot.cost_basis_fen * debit // lot.quantity
            )
            if debit:
                released = None if basis is None or released is None else released + basis
            if remaining:
                lots.append(
                    lot.model_copy(
                        update={
                            "quantity": remaining,
                            "cost_basis_fen": None
                            if lot.cost_basis_fen is None
                            else lot.cost_basis_fen - basis,
                        }
                    )
                )
        if side == "BUY":
            lots.append(
                LoopLedgerLot(
                    lot_key=authority.simulation_id,
                    bucket="TACTICAL",
                    quantity=command.quantity,
                    cost_basis_fen=settlement.notional_fen + settlement.total_fees_fen,
                    acquired_trade_date=now.date(),
                    plan_version_id=str(command.plan_version_id),
                )
            )
        if new_quantities != {(lot.lot_key, lot.bucket): lot.quantity for lot in lots}:
            raise ValueError("LOOP_MONEY_INVENTORY_MISMATCH")
        pnl = before.realized_pnl_fen
        if side == "SELL":
            pnl = None if pnl is None or released is None else pnl + cash_delta - released
        after = LoopAccountState(
            revision=before.revision + 1,
            cash=cash,
            inventory_known=before.inventory_known,
            lots=tuple(lots),
            realized_pnl_fen=pnl,
            paid_fees_fen=before.paid_fees_fen + settlement.total_fees_fen,
        )
        receipt = LoopAccountReceipt(
            request_key=request_key,
            command=command,
            costs=costs,
            authority_receipt=authority,
            settlement=settlement,
            released_cost_fen=released,
            account=after,
        )
        self._save(after)
        self.session.execute(
            RECEIPT_TABLE.insert().values(
                request_key=request_key, payload_json=receipt.model_dump_json()
            )
        )
        return receipt
