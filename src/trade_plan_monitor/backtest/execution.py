"""Pure deterministic execution-model-v1 state machine for offline backtests."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from decimal import Decimal

from pydantic import TypeAdapter

from trade_plan_monitor.backtest.models import (
    EquitySnapshot,
    ExecutionBar,
    ExecutionBatch,
    ExecutionConfig,
    ExecutionFill,
    ExecutionOrder,
    ExecutionOutcome,
    ExecutionSide,
    ExecutionSignal,
    ExecutionStatus,
    FeeBreakdown,
    PositionLot,
    PositionSnapshot,
    UnfilledReason,
)
from trade_plan_monitor.decision.models import ActionableSignalType
from trade_plan_monitor.market_data.models import DailyLimit, ShanghaiDatetime

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_SHANGHAI_DATETIME = TypeAdapter(ShanghaiDatetime)
_MORNING_OPEN = time(9, 30)
_MORNING_LAST_OPEN = time(11, 29)
_AFTERNOON_OPEN = time(13, 0)
_AFTERNOON_LAST_OPEN = time(14, 59)
_BUY_SIGNALS = frozenset(
    {
        ActionableSignalType.BUY_CORE_READY,
        ActionableSignalType.BUY_TACTICAL_READY,
    }
)
_EXECUTABLE_SIGNALS = frozenset(
    {
        *_BUY_SIGNALS,
        ActionableSignalType.PRESSURE_REDUCE_READY,
        ActionableSignalType.RISK_EXIT_READY,
    }
)


def _ceiling_fraction(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _rate_ceiling(notional_fen: int, rate: Decimal) -> int:
    numerator, denominator = rate.as_integer_ratio()
    return _ceiling_fraction(notional_fen * numerator, denominator)


def _fill_price(open_fen: int, *, side: ExecutionSide, config: ExecutionConfig) -> int:
    basis_points = (
        config.buy_slippage_bps if side is ExecutionSide.BUY else config.sell_slippage_bps
    )
    slippage_numerator, slippage_denominator = basis_points.as_integer_ratio()
    denominator = 10_000 * slippage_denominator
    factor_numerator = (
        denominator + slippage_numerator
        if side is ExecutionSide.BUY
        else denominator - slippage_numerator
    )
    scaled_price = open_fen * factor_numerator
    price = (
        _ceiling_fraction(scaled_price, denominator)
        if side is ExecutionSide.BUY
        else scaled_price // denominator
    )
    if price <= 0:
        raise ValueError("configured slippage must preserve a positive fill price")
    return price


def _minute_ceiling(value: datetime) -> datetime:
    rounded = value.replace(second=0, microsecond=0)
    return rounded if value == rounded else rounded + timedelta(minutes=1)


def _session_open(value: datetime, at: time) -> datetime:
    return value.replace(
        hour=at.hour,
        minute=at.minute,
        second=0,
        microsecond=0,
    )


def _candidate_open_at_or_after(value: datetime) -> datetime | None:
    """Return the same-day A-share minute open, or ``None`` for a later session."""

    candidate = _minute_ceiling(value)
    candidate_time = candidate.time()
    if candidate_time <= _MORNING_OPEN:
        return _session_open(candidate, _MORNING_OPEN)
    if candidate_time <= _MORNING_LAST_OPEN:
        return candidate
    if candidate_time <= _AFTERNOON_OPEN:
        return _session_open(candidate, _AFTERNOON_OPEN)
    if candidate_time <= _AFTERNOON_LAST_OPEN:
        return candidate
    return None


def _candidate_relation(
    *,
    order: ExecutionOrder,
    bar_open_at: datetime,
    previous_suspension: ExecutionBar | None,
) -> int:
    """Compare a bar with the next required execution minute (-1 early, 0 exact, 1 gap)."""

    if previous_suspension is None:
        anchor = order.submitted_at
        expected = _candidate_open_at_or_after(anchor)
    else:
        anchor = previous_suspension.bar_end - timedelta(minutes=1)
        expected = _candidate_open_at_or_after(anchor + timedelta(minutes=1))
    if expected is not None:
        if bar_open_at < expected:
            return -1
        return 0 if bar_open_at == expected else 1

    if bar_open_at <= anchor:
        return -1
    if bar_open_at.date() > anchor.date() and bar_open_at.time() == _MORNING_OPEN:
        return 0
    return 1


def _fees(
    *,
    side: ExecutionSide,
    notional_fen: int,
    config: ExecutionConfig,
) -> FeeBreakdown:
    commission = max(
        config.minimum_commission_fen,
        _rate_ceiling(notional_fen, config.commission_rate),
    )
    stamp_duty = (
        _rate_ceiling(notional_fen, config.stamp_duty_rate) if side is ExecutionSide.SELL else 0
    )
    transfer_fee = _rate_ceiling(notional_fen, config.transfer_fee_rate)
    return FeeBreakdown(
        commission_fen=commission,
        stamp_duty_fen=stamp_duty,
        transfer_fee_fen=transfer_fee,
        total_fen=commission + stamp_duty + transfer_fee,
    )


class DeterministicExecutionEngine:
    """In-memory deterministic simulator with no clock, I/O, or side effects."""

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        run_id: str,
        plan_hash: str,
        dataset_hash: str,
        symbol: str,
        initial_cash_fen: int,
        max_position_qty: int,
        core_target_qty: int,
        tactical_target_qty: int,
        initial_lots: tuple[PositionLot, ...] = (),
    ) -> None:
        for value, name in (
            (run_id, "run_id"),
            (plan_hash, "plan_hash"),
            (dataset_hash, "dataset_hash"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 hash")
        if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
            raise ValueError("symbol must be a canonical A-share symbol")
        if type(initial_cash_fen) is not int or initial_cash_fen < 0:
            raise ValueError("initial_cash_fen must be a non-negative integer")
        if (
            type(max_position_qty) is not int
            or max_position_qty <= 0
            or max_position_qty % config.lot_size
        ):
            raise ValueError("max_position_qty must be a positive board-lot quantity")
        for value, name in (
            (core_target_qty, "core_target_qty"),
            (tactical_target_qty, "tactical_target_qty"),
        ):
            if type(value) is not int or value < 0 or value % config.lot_size:
                raise ValueError(f"{name} must be a non-negative board-lot quantity")
        if core_target_qty + tactical_target_qty > max_position_qty:
            raise ValueError("bucket targets cannot exceed plan maximum quantity")

        lots: dict[str, PositionLot] = {}
        for lot in initial_lots:
            if lot.symbol != symbol:
                raise ValueError("initial lot symbol must match the engine symbol")
            if lot.remaining_quantity == 0:
                raise ValueError("initial_lots cannot contain closed lots")
            if lot.lot_id in lots:
                raise ValueError("initial lot identities must be unique")
            lots[lot.lot_id] = lot
        if sum(lot.remaining_quantity for lot in lots.values()) > max_position_qty:
            raise ValueError("initial lots cannot exceed plan maximum quantity")

        self._config = config
        self._run_id = run_id
        self._plan_hash = plan_hash
        self._dataset_hash = dataset_hash
        self._symbol = symbol
        self._max_position_qty = max_position_qty
        self._bucket_targets = {
            "CORE": core_target_qty,
            "TACTICAL": tactical_target_qty,
        }
        self._cash_fen = initial_cash_fen
        self._lots = lots
        self._pending_orders: dict[str, ExecutionOrder] = {}
        self._suspension_seen: dict[str, ExecutionBar] = {}
        self._signals: dict[str, ExecutionSignal] = {}
        self._last_bar_end: datetime | None = None
        self._total_cost_fen = 0
        self._realized_pnl_fen = 0

    @property
    def cash_fen(self) -> int:
        return self._cash_fen

    @property
    def open_lots(self) -> tuple[PositionLot, ...]:
        return tuple(self._lots[lot_id] for lot_id in sorted(self._lots))

    @property
    def position_quantity(self) -> int:
        return sum(lot.remaining_quantity for lot in self._lots.values())

    @property
    def position_snapshots(self) -> tuple[PositionSnapshot, ...]:
        snapshots: list[PositionSnapshot] = []
        for bucket in ("CORE", "TACTICAL"):
            bucket_lots = tuple(lot for lot in self._lots.values() if lot.bucket == bucket)
            quantity = sum(lot.remaining_quantity for lot in bucket_lots)
            if quantity == 0:
                continue
            snapshots.append(
                PositionSnapshot(
                    symbol=self._symbol,
                    bucket=bucket,
                    quantity=quantity,
                    cost_basis_fen=sum(lot.cost_basis_fen for lot in bucket_lots),
                )
            )
        return tuple(snapshots)

    @property
    def total_cost_fen(self) -> int:
        """Cumulative commission, tax, and transfer fees."""

        return self._total_cost_fen

    @property
    def total_fees_fen(self) -> int:
        return self._total_cost_fen

    @property
    def realized_pnl_fen(self) -> int:
        return self._realized_pnl_fen

    def submit_signal(self, signal: ExecutionSignal) -> ExecutionBatch:
        """Accept a unique signal, or explicitly ignore a non-trade risk signal."""

        self._validate_signal_scope(signal)
        existing = self._signals.get(signal.signal_id)
        if existing is not None:
            if existing != signal:
                raise ValueError("conflicting signal content under an existing identity")
            return ExecutionBatch()
        self._signals[signal.signal_id] = signal

        if signal.signal_type not in _EXECUTABLE_SIGNALS:
            outcome = ExecutionOutcome.create(
                signal_id=signal.signal_id,
                order_id=None,
                resolved_at=signal.signal_at,
                source_bar_id=None,
                status=ExecutionStatus.IGNORED,
                reason=UnfilledReason.NON_EXECUTABLE_SIGNAL,
                fill_id=None,
            )
            return ExecutionBatch(outcomes=(outcome,))

        order = ExecutionOrder.from_signal(signal)
        self._pending_orders[order.order_id] = order
        return ExecutionBatch(orders=(order,))

    def process_bar(self, bar: ExecutionBar, daily_limit: DailyLimit) -> ExecutionBatch:
        """Resolve pending orders against their first eligible tradable future minute."""

        self._validate_bar_scope(bar, daily_limit)
        if self._last_bar_end is not None and bar.bar_end <= self._last_bar_end:
            raise ValueError("execution bars must be strictly increasing")
        self._last_bar_end = bar.bar_end

        fills: list[ExecutionFill] = []
        outcomes: list[ExecutionOutcome] = []
        pending = sorted(
            self._pending_orders.values(),
            key=lambda order: (order.submitted_at, order.order_id),
        )
        for order in pending:
            bar_open_at = bar.bar_end - timedelta(minutes=1)
            if bar_open_at < order.submitted_at:
                continue
            relation = _candidate_relation(
                order=order,
                bar_open_at=bar_open_at,
                previous_suspension=self._suspension_seen.get(order.order_id),
            )
            if relation < 0:
                continue
            if relation > 0:
                outcomes.append(self._reject_on_bar(order, UnfilledReason.MISSING_NEXT_MINUTE, bar))
                continue
            if not bar.is_tradable:
                self._suspension_seen[order.order_id] = bar
                continue

            fill_price = _fill_price(bar.open_fen, side=order.side, config=self._config)
            if order.side is ExecutionSide.BUY and (
                bar.open_fen >= daily_limit.up_limit_fen or fill_price >= daily_limit.up_limit_fen
            ):
                outcomes.append(self._reject_on_bar(order, UnfilledReason.LIMIT_UP_LOCKED, bar))
                continue
            if order.side is ExecutionSide.SELL and (
                bar.open_fen <= daily_limit.down_limit_fen
                or fill_price <= daily_limit.down_limit_fen
            ):
                outcomes.append(self._reject_on_bar(order, UnfilledReason.LIMIT_DOWN_LOCKED, bar))
                continue

            if order.side is ExecutionSide.BUY:
                fill, outcome = self._fill_buy(order, bar, fill_price)
            else:
                fill, outcome = self._fill_sell(order, bar, fill_price)
            outcomes.append(outcome)
            if fill is not None:
                fills.append(fill)

        return ExecutionBatch(fills=tuple(fills), outcomes=tuple(outcomes))

    def finalize(self, *, replay_boundary: datetime) -> ExecutionBatch:
        """Close the finite replay range and reject every unresolved order once."""

        resolved_boundary = _SHANGHAI_DATETIME.validate_python(replay_boundary, strict=True)
        if self._last_bar_end is not None and resolved_boundary < self._last_bar_end:
            raise ValueError("replay_boundary cannot precede the latest execution bar")
        if any(order.submitted_at > resolved_boundary for order in self._pending_orders.values()):
            raise ValueError("replay_boundary cannot precede a pending order")
        outcomes = tuple(
            self._reject(
                order,
                (
                    UnfilledReason.SUSPENDED
                    if order.order_id in self._suspension_seen
                    else UnfilledReason.NO_NEXT_MINUTE
                ),
                resolved_at=resolved_boundary,
                source_bar_id=(
                    self._suspension_seen[order.order_id].source_bar_id
                    if order.order_id in self._suspension_seen
                    else None
                ),
            )
            for order in sorted(
                self._pending_orders.values(),
                key=lambda item: (item.submitted_at, item.order_id),
            )
        )
        return ExecutionBatch(outcomes=outcomes)

    def equity_snapshot(self, *, at: datetime, mark_price_fen: int) -> EquitySnapshot:
        return EquitySnapshot.create(
            run_id=self._run_id,
            symbol=self._symbol,
            marked_at=at,
            mark_price_fen=mark_price_fen,
            cash_fen=self._cash_fen,
            position_quantity=self.position_quantity,
            cost_basis_fen=sum(lot.cost_basis_fen for lot in self._lots.values()),
            realized_pnl_fen=self._realized_pnl_fen,
            total_cost_fen=self._total_cost_fen,
        )

    def _validate_signal_scope(self, signal: ExecutionSignal) -> None:
        if signal.run_id != self._run_id:
            raise ValueError("signal run_id must match the execution engine")
        if signal.plan_hash != self._plan_hash:
            raise ValueError("signal plan_hash must match the execution engine")
        if signal.dataset_hash != self._dataset_hash:
            raise ValueError("signal dataset_hash must match the execution engine")
        if signal.symbol != self._symbol:
            raise ValueError("signal symbol must match the execution engine")
        if self._last_bar_end is not None and signal.signal_at < self._last_bar_end:
            raise ValueError("signal cannot precede the latest processed execution bar")

    def _validate_bar_scope(self, bar: ExecutionBar, daily_limit: DailyLimit) -> None:
        if bar.symbol != self._symbol or daily_limit.symbol != self._symbol:
            raise ValueError("bar and daily limit symbol must match the execution engine")
        if daily_limit.trade_date != bar.bar_end.date():
            raise ValueError("daily limit trade date must match the execution bar")

    def _reject(
        self,
        order: ExecutionOrder,
        reason: UnfilledReason,
        *,
        resolved_at: datetime,
        source_bar_id: str | None,
    ) -> ExecutionOutcome:
        self._pending_orders.pop(order.order_id, None)
        self._suspension_seen.pop(order.order_id, None)
        return ExecutionOutcome.create(
            signal_id=order.signal_id,
            order_id=order.order_id,
            resolved_at=resolved_at,
            source_bar_id=source_bar_id,
            status=ExecutionStatus.UNFILLED,
            reason=reason,
            fill_id=None,
        )

    def _reject_on_bar(
        self,
        order: ExecutionOrder,
        reason: UnfilledReason,
        bar: ExecutionBar,
    ) -> ExecutionOutcome:
        return self._reject(
            order,
            reason,
            resolved_at=bar.bar_end - timedelta(minutes=1),
            source_bar_id=bar.source_bar_id,
        )

    def _filled_outcome(self, order: ExecutionOrder, fill: ExecutionFill) -> ExecutionOutcome:
        self._pending_orders.pop(order.order_id, None)
        self._suspension_seen.pop(order.order_id, None)
        return ExecutionOutcome.create(
            signal_id=order.signal_id,
            order_id=order.order_id,
            resolved_at=fill.filled_at,
            source_bar_id=fill.source_bar_id,
            status=ExecutionStatus.FILLED,
            reason=None,
            fill_id=fill.fill_id,
        )

    def _fill_buy(
        self,
        order: ExecutionOrder,
        bar: ExecutionBar,
        fill_price: int,
    ) -> tuple[ExecutionFill | None, ExecutionOutcome]:
        available_position = self._max_position_qty - self.position_quantity
        bucket_position = sum(
            lot.remaining_quantity for lot in self._lots.values() if lot.bucket == order.bucket
        )
        available_bucket = self._bucket_targets[order.bucket] - bucket_position
        if available_bucket <= 0:
            return None, self._reject_on_bar(order, UnfilledReason.TARGET_POSITION_REACHED, bar)
        candidate_quantity = min(
            order.requested_quantity,
            available_position,
            available_bucket,
        )
        candidate_quantity -= candidate_quantity % self._config.lot_size
        if candidate_quantity == 0:
            return None, self._reject_on_bar(order, UnfilledReason.MAX_POSITION_REACHED, bar)

        quantity = candidate_quantity
        fees: FeeBreakdown | None = None
        while quantity > 0:
            notional = fill_price * quantity
            fees = _fees(side=ExecutionSide.BUY, notional_fen=notional, config=self._config)
            if notional + fees.total_fen <= self._cash_fen:
                break
            quantity -= self._config.lot_size
        if quantity == 0 or fees is None:
            return None, self._reject_on_bar(order, UnfilledReason.INSUFFICIENT_CASH, bar)

        notional = fill_price * quantity
        cash_delta = -(notional + fees.total_fen)
        filled_at = bar.bar_end - timedelta(minutes=1)
        fill = ExecutionFill.create(
            order=order,
            config_hash=self._config.config_hash,
            source_bar_id=bar.source_bar_id,
            filled_at=filled_at,
            quantity=quantity,
            price_fen=fill_price,
            fees=fees,
            cash_delta_fen=cash_delta,
        )
        lot = PositionLot.from_fill(
            fill_id=fill.fill_id,
            symbol=order.symbol,
            bucket=order.bucket,
            acquired_trade_date=filled_at.date(),
            quantity=quantity,
            cost_basis_fen=-cash_delta,
        )
        self._cash_fen += cash_delta
        self._total_cost_fen += fees.total_fen
        self._lots[lot.lot_id] = lot
        return fill, self._filled_outcome(order, fill)

    def _fill_sell(
        self,
        order: ExecutionOrder,
        bar: ExecutionBar,
        fill_price: int,
    ) -> tuple[ExecutionFill | None, ExecutionOutcome]:
        target_id = order.target_lot_id
        target = self._lots.get(target_id) if target_id is not None else None
        if target is None or target.bucket != order.bucket:
            return None, self._reject_on_bar(order, UnfilledReason.TARGET_LOT_NOT_FOUND, bar)
        if target.acquired_trade_date >= bar.bar_end.date():
            return None, self._reject_on_bar(order, UnfilledReason.T_PLUS_ONE, bar)

        quantity = min(order.requested_quantity, target.remaining_quantity)
        quantity -= quantity % self._config.lot_size
        if quantity == 0:
            return None, self._reject_on_bar(order, UnfilledReason.TARGET_LOT_NOT_FOUND, bar)
        notional = fill_price * quantity
        fees = _fees(side=ExecutionSide.SELL, notional_fen=notional, config=self._config)
        cash_delta = notional - fees.total_fen
        if self._cash_fen + cash_delta < 0:
            return None, self._reject_on_bar(order, UnfilledReason.INSUFFICIENT_CASH, bar)

        if quantity == target.remaining_quantity:
            released_cost = target.cost_basis_fen
        else:
            numerator = target.cost_basis_fen * quantity
            denominator = target.remaining_quantity
            released_cost = (2 * numerator + denominator) // (2 * denominator)
            released_cost = min(released_cost, target.cost_basis_fen - 1)
            released_cost = max(0, released_cost)
        realized = cash_delta - released_cost
        filled_at = bar.bar_end - timedelta(minutes=1)
        fill = ExecutionFill.create(
            order=order,
            config_hash=self._config.config_hash,
            source_bar_id=bar.source_bar_id,
            filled_at=filled_at,
            quantity=quantity,
            price_fen=fill_price,
            fees=fees,
            cash_delta_fen=cash_delta,
            cost_basis_released_fen=released_cost,
            realized_pnl_fen=realized,
        )

        remaining = target.remaining_quantity - quantity
        remaining_cost = target.cost_basis_fen - released_cost
        if remaining == 0:
            del self._lots[target.lot_id]
        else:
            self._lots[target.lot_id] = target.model_copy(
                update={
                    "remaining_quantity": remaining,
                    "cost_basis_fen": remaining_cost,
                }
            )
        self._cash_fen += cash_delta
        self._total_cost_fen += fees.total_fen
        self._realized_pnl_fen += realized
        return fill, self._filled_outcome(order, fill)


__all__ = ["DeterministicExecutionEngine"]
