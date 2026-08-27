"""Immutable values for deterministic, offline simulated execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.decision.models import ActionableSignalType, SignalIntent
from trade_plan_monitor.domain.plan_models import PositionBucket
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime

Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
StableIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
NonNegativeFen = Annotated[int, Field(strict=True, ge=0)]
SignedFen = Annotated[int, Field(strict=True)]
PositiveBoardLot = Annotated[int, Field(strict=True, gt=0, multiple_of=100)]
NonNegativeBoardLot = Annotated[int, Field(strict=True, ge=0, multiple_of=100)]
NonNegativeShares = Annotated[int, Field(strict=True, ge=0)]
StrictBoolean = Annotated[bool, Field(strict=True)]
NonNegativeRate = Annotated[
    Decimal,
    Field(strict=True, ge=Decimal("0"), le=Decimal("1"), allow_inf_nan=False),
]
NonNegativeBasisPoints = Annotated[
    Decimal,
    Field(strict=True, ge=Decimal("0"), lt=Decimal("10000"), allow_inf_nan=False),
]

_SIGNAL_ID_DOMAIN = b"backtest-execution-signal-v1\0"
_BAR_ID_DOMAIN = b"backtest-execution-bar-v1\0"
_ORDER_ID_DOMAIN = b"backtest-execution-order-v1\0"
_FILL_ID_DOMAIN = b"backtest-execution-fill-v1\0"
_LOT_ID_DOMAIN = b"backtest-position-lot-v1\0"
_OUTCOME_ID_DOMAIN = b"backtest-execution-outcome-v1\0"
_EQUITY_ID_DOMAIN = b"backtest-equity-v1\0"
_CONFIG_ID_DOMAIN = b"backtest-execution-config-v1\0"


def _stable_hash(domain: bytes, value: object) -> str:
    payload = canonical_json(value).encode("utf-8")
    return sha256(domain + payload).hexdigest()


class _ExecutionValue(BaseModel):
    """Keep execution boundaries closed, frozen, and strict."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy while revalidating every public update."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class ExecutionSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(StrEnum):
    FILLED = "FILLED"
    UNFILLED = "UNFILLED"
    IGNORED = "IGNORED"


class UnfilledReason(StrEnum):
    """Stable fail-closed outcomes from execution-model-v1."""

    NON_EXECUTABLE_SIGNAL = "NON_EXECUTABLE_SIGNAL"
    SUSPENDED = "SUSPENDED"
    MISSING_NEXT_MINUTE = "MISSING_NEXT_MINUTE"
    NO_NEXT_MINUTE = "NO_NEXT_MINUTE"
    LIMIT_UP_LOCKED = "LIMIT_UP_LOCKED"
    LIMIT_DOWN_LOCKED = "LIMIT_DOWN_LOCKED"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    MAX_POSITION_REACHED = "MAX_POSITION_REACHED"
    TARGET_POSITION_REACHED = "TARGET_POSITION_REACHED"
    TARGET_LOT_NOT_FOUND = "TARGET_LOT_NOT_FOUND"
    T_PLUS_ONE = "T_PLUS_ONE"


class ExecutionConfig(_ExecutionValue):
    """Explicit versioned costs and directional slippage."""

    formula_version: Literal["execution-model-v1"] = "execution-model-v1"
    lot_size: Literal[100] = 100
    commission_rate: NonNegativeRate
    minimum_commission_fen: NonNegativeFen
    stamp_duty_rate: NonNegativeRate
    transfer_fee_rate: NonNegativeRate
    buy_slippage_bps: NonNegativeBasisPoints
    sell_slippage_bps: NonNegativeBasisPoints

    @property
    def config_hash(self) -> str:
        return _stable_hash(_CONFIG_ID_DOMAIN, self)


class ExecutionSignal(_ExecutionValue):
    """Decision signal plus the event time needed by simulated execution."""

    signal_id: StableIdentifier
    run_id: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    result_hash: Sha256Hex
    signal_type: ActionableSignalType
    symbol: AShareSymbol
    signal_at: ShanghaiDatetime
    trading_date: Annotated[date, Field(strict=True)]
    cause_id: StableIdentifier
    quantity: PositiveBoardLot | None
    bucket: PositionBucket | None
    target_lot_id: StableIdentifier | None

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        plan_hash: str,
        dataset_hash: str,
        result_hash: str,
        signal_type: ActionableSignalType,
        symbol: str,
        signal_at: datetime,
        trading_date: date,
        cause_id: str,
        quantity: int | None,
        bucket: PositionBucket | None,
        target_lot_id: str | None,
    ) -> Self:
        values = {
            "run_id": run_id,
            "plan_hash": plan_hash,
            "dataset_hash": dataset_hash,
            "result_hash": result_hash,
            "signal_type": signal_type,
            "symbol": symbol,
            "signal_at": signal_at,
            "trading_date": trading_date,
            "cause_id": cause_id,
            "quantity": quantity,
            "bucket": bucket,
            "target_lot_id": target_lot_id,
        }
        return cls(signal_id=_stable_hash(_SIGNAL_ID_DOMAIN, values), **values)

    @classmethod
    def from_intent(
        cls,
        intent: SignalIntent,
        *,
        run_id: str,
        dataset_hash: str,
        result_hash: str,
        signal_at: datetime,
    ) -> Self:
        return cls.create(
            run_id=run_id,
            plan_hash=intent.plan_hash,
            dataset_hash=dataset_hash,
            result_hash=result_hash,
            signal_type=intent.signal_type,
            symbol=intent.symbol,
            signal_at=signal_at,
            trading_date=intent.trading_date,
            cause_id=intent.cause_id,
            quantity=intent.quantity,
            bucket=intent.bucket,
            target_lot_id=intent.target_lot_id,
        )

    @model_validator(mode="after")
    def validate_identity_and_shape(self) -> Self:
        values = self.model_dump(mode="python", exclude={"signal_id"}, round_trip=True)
        if self.signal_id != _stable_hash(_SIGNAL_ID_DOMAIN, values):
            raise ValueError("signal_id must match the canonical execution signal")
        if self.signal_at.date() != self.trading_date:
            raise ValueError("signal_at must fall on trading_date")
        if self.signal_type is ActionableSignalType.RISK_BREACH:
            if any(value is not None for value in (self.quantity, self.bucket, self.target_lot_id)):
                raise ValueError("risk breach cannot imply an execution order")
            return self
        if self.quantity is None or self.bucket is None:
            raise ValueError("trade-shaped signals require quantity and bucket")
        if self.signal_type in {
            ActionableSignalType.BUY_CORE_READY,
            ActionableSignalType.BUY_TACTICAL_READY,
        }:
            if self.target_lot_id is not None:
                raise ValueError("buy signals cannot identify a target lot")
        elif self.target_lot_id is None:
            raise ValueError("sell-shaped signals require a target lot")
        if self.signal_type is ActionableSignalType.BUY_CORE_READY and self.bucket != "CORE":
            raise ValueError("core buy must use the CORE bucket")
        if (
            self.signal_type
            in {
                ActionableSignalType.BUY_TACTICAL_READY,
                ActionableSignalType.PRESSURE_REDUCE_READY,
            }
            and self.bucket != "TACTICAL"
        ):
            raise ValueError("tactical signal must use the TACTICAL bucket")
        return self


class ExecutionBar(_ExecutionValue):
    """Bounded one-minute execution candidate with explicit tradability."""

    source_bar_id: StableIdentifier
    symbol: AShareSymbol
    bar_end: ShanghaiDatetime
    open_fen: PositiveFen
    high_fen: PositiveFen
    low_fen: PositiveFen
    close_fen: PositiveFen
    volume_shares: NonNegativeShares
    is_tradable: StrictBoolean

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        bar_end: datetime,
        open_fen: int,
        high_fen: int,
        low_fen: int,
        close_fen: int,
        volume_shares: int,
        is_tradable: bool,
    ) -> Self:
        values = {
            "symbol": symbol,
            "bar_end": bar_end,
            "open_fen": open_fen,
            "high_fen": high_fen,
            "low_fen": low_fen,
            "close_fen": close_fen,
            "volume_shares": volume_shares,
            "is_tradable": is_tradable,
        }
        return cls(source_bar_id=_stable_hash(_BAR_ID_DOMAIN, values), **values)

    @model_validator(mode="after")
    def validate_identity_and_ohlc(self) -> Self:
        values = self.model_dump(mode="python", exclude={"source_bar_id"}, round_trip=True)
        if self.source_bar_id != _stable_hash(_BAR_ID_DOMAIN, values):
            raise ValueError("source_bar_id must match the canonical execution bar")
        if self.bar_end.second != 0 or self.bar_end.microsecond != 0:
            raise ValueError("execution bar_end must be a whole-minute timestamp")
        if self.low_fen > self.high_fen:
            raise ValueError("low_fen cannot exceed high_fen")
        if not self.low_fen <= self.open_fen <= self.high_fen:
            raise ValueError("open_fen must be within the bar range")
        if not self.low_fen <= self.close_fen <= self.high_fen:
            raise ValueError("close_fen must be within the bar range")
        if not self.is_tradable and self.volume_shares != 0:
            raise ValueError("a non-tradable execution bar must have zero volume")
        return self


class PositionLot(_ExecutionValue):
    """One exact simulated holding lot and its remaining total cost basis."""

    lot_id: StableIdentifier
    symbol: AShareSymbol
    bucket: PositionBucket
    acquired_trade_date: Annotated[date, Field(strict=True)]
    original_quantity: PositiveBoardLot
    remaining_quantity: NonNegativeBoardLot
    cost_basis_fen: NonNegativeFen
    source_fill_id: StableIdentifier | None = None

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Allow only remaining quantity and remaining cost basis to advance."""

        if update and set(update) - {"remaining_quantity", "cost_basis_fen"}:
            raise ValueError("position lot identity fields cannot be changed")
        return super().model_copy(update=update, deep=deep)

    @classmethod
    def create_initial(
        cls,
        *,
        run_id: str,
        symbol: str,
        bucket: PositionBucket,
        acquired_trade_date: date,
        quantity: int,
        cost_basis_fen: int,
        source_key: str,
    ) -> Self:
        identity = _stable_hash(
            _LOT_ID_DOMAIN,
            {
                "kind": "INITIAL",
                "run_id": run_id,
                "symbol": symbol,
                "bucket": bucket,
                "acquired_trade_date": acquired_trade_date,
                "quantity": quantity,
                "cost_basis_fen": cost_basis_fen,
                "source_key": source_key,
            },
        )
        return cls(
            lot_id=f"lot-{identity[:32]}",
            symbol=symbol,
            bucket=bucket,
            acquired_trade_date=acquired_trade_date,
            original_quantity=quantity,
            remaining_quantity=quantity,
            cost_basis_fen=cost_basis_fen,
        )

    @classmethod
    def from_initial_input(
        cls,
        *,
        run_id: str,
        symbol: str,
        lot_key: str,
        bucket: PositionBucket,
        acquired_trade_date: date,
        quantity: int,
        cost_basis_fen: int,
    ) -> Self:
        """Derive one run-bound lot from an already-hashed public input."""

        return cls.create_initial(
            run_id=run_id,
            symbol=symbol,
            bucket=bucket,
            acquired_trade_date=acquired_trade_date,
            quantity=quantity,
            cost_basis_fen=cost_basis_fen,
            source_key=lot_key,
        )

    @classmethod
    def from_fill(
        cls,
        *,
        fill_id: str,
        symbol: str,
        bucket: PositionBucket,
        acquired_trade_date: date,
        quantity: int,
        cost_basis_fen: int,
    ) -> Self:
        identity = _stable_hash(_LOT_ID_DOMAIN, {"kind": "FILL", "fill_id": fill_id})
        return cls(
            lot_id=f"lot-{identity[:32]}",
            symbol=symbol,
            bucket=bucket,
            acquired_trade_date=acquired_trade_date,
            original_quantity=quantity,
            remaining_quantity=quantity,
            cost_basis_fen=cost_basis_fen,
            source_fill_id=fill_id,
        )

    @model_validator(mode="after")
    def validate_remaining_shape(self) -> Self:
        if self.remaining_quantity > self.original_quantity:
            raise ValueError("remaining quantity cannot exceed original quantity")
        if self.remaining_quantity == 0 and self.cost_basis_fen != 0:
            raise ValueError("closed lot cannot retain cost basis")
        if self.remaining_quantity > 0 and self.cost_basis_fen == 0:
            raise ValueError("open lot requires a positive cost basis")
        if self.source_fill_id is not None:
            expected = _stable_hash(
                _LOT_ID_DOMAIN,
                {"kind": "FILL", "fill_id": self.source_fill_id},
            )
            if self.lot_id != f"lot-{expected[:32]}":
                raise ValueError("fill-created lot identity must match its source fill")
        return self


class PositionSnapshot(_ExecutionValue):
    symbol: AShareSymbol
    bucket: PositionBucket
    quantity: NonNegativeBoardLot
    cost_basis_fen: NonNegativeFen


class FeeBreakdown(_ExecutionValue):
    commission_fen: NonNegativeFen
    stamp_duty_fen: NonNegativeFen
    transfer_fee_fen: NonNegativeFen
    total_fen: NonNegativeFen

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_fen != (self.commission_fen + self.stamp_duty_fen + self.transfer_fee_fen):
            raise ValueError("fee total must equal its components")
        return self


class ExecutionOrder(_ExecutionValue):
    """One accepted order awaiting exactly one future minute candidate."""

    order_id: StableIdentifier
    signal_id: StableIdentifier
    run_id: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    result_hash: Sha256Hex
    signal_type: ActionableSignalType
    side: ExecutionSide
    symbol: AShareSymbol
    submitted_at: ShanghaiDatetime
    trading_date: Annotated[date, Field(strict=True)]
    requested_quantity: PositiveBoardLot
    bucket: PositionBucket
    target_lot_id: StableIdentifier | None

    @classmethod
    def from_signal(cls, signal: ExecutionSignal) -> Self:
        if signal.quantity is None or signal.bucket is None:
            raise ValueError("non-trade signal cannot create an execution order")
        side = (
            ExecutionSide.BUY
            if signal.signal_type
            in {
                ActionableSignalType.BUY_CORE_READY,
                ActionableSignalType.BUY_TACTICAL_READY,
            }
            else ExecutionSide.SELL
        )
        values = {
            "signal_id": signal.signal_id,
            "run_id": signal.run_id,
            "plan_hash": signal.plan_hash,
            "dataset_hash": signal.dataset_hash,
            "result_hash": signal.result_hash,
            "signal_type": signal.signal_type,
            "side": side,
            "symbol": signal.symbol,
            "submitted_at": signal.signal_at,
            "trading_date": signal.trading_date,
            "requested_quantity": signal.quantity,
            "bucket": signal.bucket,
            "target_lot_id": signal.target_lot_id,
        }
        return cls(order_id=_stable_hash(_ORDER_ID_DOMAIN, values), **values)

    @model_validator(mode="after")
    def validate_identity_and_side(self) -> Self:
        values = self.model_dump(mode="python", exclude={"order_id"}, round_trip=True)
        if self.order_id != _stable_hash(_ORDER_ID_DOMAIN, values):
            raise ValueError("order_id must match the canonical order")
        buy_signal = self.signal_type in {
            ActionableSignalType.BUY_CORE_READY,
            ActionableSignalType.BUY_TACTICAL_READY,
        }
        if buy_signal != (self.side is ExecutionSide.BUY):
            raise ValueError("order side must match signal type")
        if self.side is ExecutionSide.BUY and self.target_lot_id is not None:
            raise ValueError("buy order cannot target an existing lot")
        if self.side is ExecutionSide.SELL and self.target_lot_id is None:
            raise ValueError("sell order must target one exact lot")
        return self


class ExecutionFill(_ExecutionValue):
    """One simulated fill with complete deterministic traceability."""

    fill_id: StableIdentifier
    order_id: StableIdentifier
    signal_id: StableIdentifier
    run_id: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    result_hash: Sha256Hex
    config_hash: Sha256Hex
    source_bar_id: StableIdentifier
    side: ExecutionSide
    symbol: AShareSymbol
    bucket: PositionBucket
    target_lot_id: StableIdentifier | None
    filled_at: ShanghaiDatetime
    requested_quantity: PositiveBoardLot
    quantity: PositiveBoardLot
    price_fen: PositiveFen
    notional_fen: PositiveFen
    fees: FeeBreakdown
    cash_delta_fen: SignedFen
    cost_basis_released_fen: NonNegativeFen = 0
    realized_pnl_fen: SignedFen | None = None

    @classmethod
    def create(
        cls,
        *,
        order: ExecutionOrder,
        config_hash: str,
        source_bar_id: str,
        filled_at: datetime,
        quantity: int,
        price_fen: int,
        fees: FeeBreakdown,
        cash_delta_fen: int,
        cost_basis_released_fen: int = 0,
        realized_pnl_fen: int | None = None,
    ) -> Self:
        values = {
            "order_id": order.order_id,
            "signal_id": order.signal_id,
            "run_id": order.run_id,
            "plan_hash": order.plan_hash,
            "dataset_hash": order.dataset_hash,
            "result_hash": order.result_hash,
            "config_hash": config_hash,
            "source_bar_id": source_bar_id,
            "side": order.side,
            "symbol": order.symbol,
            "bucket": order.bucket,
            "target_lot_id": order.target_lot_id,
            "filled_at": filled_at,
            "requested_quantity": order.requested_quantity,
            "quantity": quantity,
            "price_fen": price_fen,
            "notional_fen": price_fen * quantity,
            "fees": fees,
            "cash_delta_fen": cash_delta_fen,
            "cost_basis_released_fen": cost_basis_released_fen,
            "realized_pnl_fen": realized_pnl_fen,
        }
        return cls(fill_id=_stable_hash(_FILL_ID_DOMAIN, values), **values)

    @model_validator(mode="after")
    def validate_arithmetic_and_identity(self) -> Self:
        if self.quantity > self.requested_quantity:
            raise ValueError("fill quantity cannot exceed requested quantity")
        if self.notional_fen != self.price_fen * self.quantity:
            raise ValueError("notional must equal price times quantity")
        if self.side is ExecutionSide.BUY:
            if self.cash_delta_fen != -(self.notional_fen + self.fees.total_fen):
                raise ValueError("buy cash delta must include notional and fees")
            if self.cost_basis_released_fen != 0 or self.realized_pnl_fen is not None:
                raise ValueError("buy fill cannot release or realize cost basis")
            if self.target_lot_id is not None:
                raise ValueError("buy fill cannot target an existing lot")
        else:
            if self.cash_delta_fen != self.notional_fen - self.fees.total_fen:
                raise ValueError("sell cash delta must equal net proceeds")
            expected_realized = self.cash_delta_fen - self.cost_basis_released_fen
            if self.realized_pnl_fen != expected_realized:
                raise ValueError("sell realized PnL must equal net proceeds less cost basis")
            if self.target_lot_id is None:
                raise ValueError("sell fill must identify its target lot")
        values = self.model_dump(mode="python", exclude={"fill_id"}, round_trip=True)
        if self.fill_id != _stable_hash(_FILL_ID_DOMAIN, values):
            raise ValueError("fill_id must match the canonical fill")
        return self


class ExecutionOutcome(_ExecutionValue):
    """Final outcome for one signal/order; never implies a broker action."""

    outcome_id: StableIdentifier
    signal_id: StableIdentifier
    order_id: StableIdentifier | None
    resolved_at: ShanghaiDatetime
    source_bar_id: StableIdentifier | None
    status: ExecutionStatus
    reason: UnfilledReason | None
    fill_id: StableIdentifier | None

    @classmethod
    def create(
        cls,
        *,
        signal_id: str,
        order_id: str | None,
        resolved_at: datetime,
        source_bar_id: str | None,
        status: ExecutionStatus,
        reason: UnfilledReason | None,
        fill_id: str | None,
    ) -> Self:
        values = {
            "signal_id": signal_id,
            "order_id": order_id,
            "resolved_at": resolved_at,
            "source_bar_id": source_bar_id,
            "status": status,
            "reason": reason,
            "fill_id": fill_id,
        }
        return cls(outcome_id=_stable_hash(_OUTCOME_ID_DOMAIN, values), **values)

    @model_validator(mode="after")
    def validate_shape_and_identity(self) -> Self:
        if self.status is ExecutionStatus.FILLED:
            if (
                self.fill_id is None
                or self.reason is not None
                or self.order_id is None
                or self.source_bar_id is None
            ):
                raise ValueError(
                    "filled outcome requires order/fill/source bar and no rejection reason"
                )
        elif self.fill_id is not None or self.reason is None:
            raise ValueError("non-filled outcome requires a reason and no fill")
        if self.status is ExecutionStatus.UNFILLED and self.order_id is None:
            raise ValueError("unfilled outcome requires an accepted order")
        if self.status is ExecutionStatus.IGNORED and self.order_id is not None:
            raise ValueError("ignored signal cannot have an order")
        if self.status is ExecutionStatus.IGNORED and self.source_bar_id is not None:
            raise ValueError("ignored signal cannot identify an execution bar")
        if self.status is ExecutionStatus.UNFILLED:
            if self.reason is UnfilledReason.NO_NEXT_MINUTE and self.source_bar_id is not None:
                raise ValueError("no-next-minute outcome cannot identify an execution bar")
            if self.reason is not UnfilledReason.NO_NEXT_MINUTE and self.source_bar_id is None:
                raise ValueError("bar-resolved outcome must identify its execution bar")
        values = self.model_dump(mode="python", exclude={"outcome_id"}, round_trip=True)
        if self.outcome_id != _stable_hash(_OUTCOME_ID_DOMAIN, values):
            raise ValueError("outcome_id must match the canonical outcome")
        return self


class ExecutionBatch(_ExecutionValue):
    """New immutable artifacts emitted by one engine call."""

    orders: tuple[ExecutionOrder, ...] = ()
    fills: tuple[ExecutionFill, ...] = ()
    outcomes: tuple[ExecutionOutcome, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.orders and not self.fills and not self.outcomes


class EquitySnapshot(_ExecutionValue):
    """One exact event-time mark without retaining minute-by-minute engine state."""

    snapshot_id: StableIdentifier
    run_id: Sha256Hex
    symbol: AShareSymbol
    marked_at: ShanghaiDatetime
    mark_price_fen: PositiveFen
    cash_fen: NonNegativeFen
    position_quantity: NonNegativeBoardLot
    market_value_fen: NonNegativeFen
    cost_basis_fen: NonNegativeFen
    realized_pnl_fen: SignedFen
    unrealized_pnl_fen: SignedFen
    total_cost_fen: NonNegativeFen
    equity_fen: NonNegativeFen

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        symbol: str,
        marked_at: datetime,
        mark_price_fen: int,
        cash_fen: int,
        position_quantity: int,
        cost_basis_fen: int,
        realized_pnl_fen: int,
        total_cost_fen: int,
    ) -> Self:
        values = {
            "run_id": run_id,
            "symbol": symbol,
            "marked_at": marked_at,
            "mark_price_fen": mark_price_fen,
            "cash_fen": cash_fen,
            "position_quantity": position_quantity,
            "market_value_fen": mark_price_fen * position_quantity,
            "cost_basis_fen": cost_basis_fen,
            "realized_pnl_fen": realized_pnl_fen,
            "unrealized_pnl_fen": mark_price_fen * position_quantity - cost_basis_fen,
            "total_cost_fen": total_cost_fen,
            "equity_fen": cash_fen + mark_price_fen * position_quantity,
        }
        return cls(snapshot_id=_stable_hash(_EQUITY_ID_DOMAIN, values), **values)

    @model_validator(mode="after")
    def validate_arithmetic_and_identity(self) -> Self:
        if self.market_value_fen != self.mark_price_fen * self.position_quantity:
            raise ValueError("market value must equal mark price times quantity")
        if self.unrealized_pnl_fen != self.market_value_fen - self.cost_basis_fen:
            raise ValueError("unrealized PnL must equal market value less cost basis")
        if self.equity_fen != self.cash_fen + self.market_value_fen:
            raise ValueError("equity must equal cash plus market value")
        values = self.model_dump(mode="python", exclude={"snapshot_id"}, round_trip=True)
        if self.snapshot_id != _stable_hash(_EQUITY_ID_DOMAIN, values):
            raise ValueError("snapshot_id must match the canonical equity snapshot")
        return self


__all__ = [
    "EquitySnapshot",
    "ExecutionBar",
    "ExecutionBatch",
    "ExecutionConfig",
    "ExecutionFill",
    "ExecutionOrder",
    "ExecutionOutcome",
    "ExecutionSide",
    "ExecutionSignal",
    "ExecutionStatus",
    "FeeBreakdown",
    "PositionLot",
    "PositionSnapshot",
    "UnfilledReason",
]
