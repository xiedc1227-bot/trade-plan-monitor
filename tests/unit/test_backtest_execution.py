from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.execution import DeterministicExecutionEngine
from trade_plan_monitor.backtest.models import (
    ExecutionBar,
    ExecutionConfig,
    ExecutionSignal,
    ExecutionStatus,
    PositionLot,
    UnfilledReason,
)
from trade_plan_monitor.decision.models import ActionableSignalType
from trade_plan_monitor.market_data.models import DailyLimit

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RUN_ID = "1" * 64
_PLAN_HASH = "2" * 64
_DATASET_HASH = "3" * 64
_RESULT_HASH = "4" * 64
_SYMBOL = "600000.SH"


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=_SHANGHAI)


_DEFAULT_SIGNAL_AT = _at(24, 10, 0)


def _config(
    *,
    commission_rate: Decimal = Decimal("0.0003"),
    minimum_commission_fen: int = 500,
    stamp_duty_rate: Decimal = Decimal("0.0005"),
    transfer_fee_rate: Decimal = Decimal("0.00001"),
    buy_slippage_bps: Decimal = Decimal("10"),
    sell_slippage_bps: Decimal = Decimal("10"),
) -> ExecutionConfig:
    return ExecutionConfig(
        commission_rate=commission_rate,
        minimum_commission_fen=minimum_commission_fen,
        stamp_duty_rate=stamp_duty_rate,
        transfer_fee_rate=transfer_fee_rate,
        buy_slippage_bps=buy_slippage_bps,
        sell_slippage_bps=sell_slippage_bps,
    )


def _engine(
    *,
    cash_fen: int = 1_000_000,
    max_position_qty: int = 1_000,
    core_target_qty: int = 500,
    tactical_target_qty: int = 500,
    config: ExecutionConfig | None = None,
    initial_lots: tuple[PositionLot, ...] = (),
) -> DeterministicExecutionEngine:
    return DeterministicExecutionEngine(
        config=config or _config(),
        run_id=_RUN_ID,
        plan_hash=_PLAN_HASH,
        dataset_hash=_DATASET_HASH,
        symbol=_SYMBOL,
        initial_cash_fen=cash_fen,
        max_position_qty=max_position_qty,
        core_target_qty=core_target_qty,
        tactical_target_qty=tactical_target_qty,
        initial_lots=initial_lots,
    )


def _signal(
    signal_type: ActionableSignalType,
    *,
    at: datetime = _DEFAULT_SIGNAL_AT,
    quantity: int | None = 100,
    bucket: str | None = "CORE",
    target_lot_id: str | None = None,
    cause_id: str = "decision-001",
) -> ExecutionSignal:
    return ExecutionSignal.create(
        run_id=_RUN_ID,
        plan_hash=_PLAN_HASH,
        dataset_hash=_DATASET_HASH,
        result_hash=_RESULT_HASH,
        signal_type=signal_type,
        symbol=_SYMBOL,
        signal_at=at,
        trading_date=at.date(),
        cause_id=cause_id,
        quantity=quantity,
        bucket=bucket,
        target_lot_id=target_lot_id,
    )


def _bar(
    at: datetime,
    *,
    open_fen: int = 1_000,
    high_fen: int | None = None,
    low_fen: int | None = None,
    close_fen: int | None = None,
    volume_shares: int = 10_000,
    is_tradable: bool = True,
) -> ExecutionBar:
    return ExecutionBar.create(
        symbol=_SYMBOL,
        bar_end=at,
        open_fen=open_fen,
        high_fen=high_fen if high_fen is not None else open_fen,
        low_fen=low_fen if low_fen is not None else open_fen,
        close_fen=close_fen if close_fen is not None else open_fen,
        volume_shares=volume_shares,
        is_tradable=is_tradable,
    )


def _limit(day: int, *, up: int = 1_100, down: int = 900) -> DailyLimit:
    return DailyLimit(
        symbol=_SYMBOL,
        trade_date=date(2026, 8, day),
        up_limit_fen=up,
        down_limit_fen=down,
        received_at=_at(day, 9, 0),
    )


def _initial_lot(
    *,
    acquired_day: int,
    quantity: int = 100,
    bucket: str = "TACTICAL",
    cost_basis_fen: int = 100_000,
) -> PositionLot:
    return PositionLot.create_initial(
        run_id=_RUN_ID,
        symbol=_SYMBOL,
        bucket=bucket,
        acquired_trade_date=date(2026, 8, acquired_day),
        quantity=quantity,
        cost_basis_fen=cost_basis_fen,
        source_key=f"seed-{acquired_day}-{bucket}",
    )


def test_buy_fills_only_on_next_minute_with_exact_slippage_and_fees() -> None:
    engine = _engine()
    signal = _signal(ActionableSignalType.BUY_CORE_READY)

    accepted = engine.submit_signal(signal)
    same_bucket = engine.process_bar(_bar(_at(24, 10, 0)), _limit(24))
    source_bar = _bar(_at(24, 10, 1))
    filled = engine.process_bar(source_bar, _limit(24))

    assert len(accepted.orders) == 1
    assert same_bucket.is_empty
    assert len(filled.fills) == 1
    fill = filled.fills[0]
    assert fill.quantity == 100
    assert fill.price_fen == 1_001
    assert fill.notional_fen == 100_100
    assert fill.fees.commission_fen == 500
    assert fill.fees.stamp_duty_fen == 0
    assert fill.fees.transfer_fee_fen == 2
    assert fill.fees.total_fen == 502
    assert fill.cash_delta_fen == -100_602
    assert engine.cash_fen == 899_398
    assert engine.position_quantity == 100
    assert engine.total_cost_fen == 502
    outcome = filled.outcomes[0]
    assert outcome.status is ExecutionStatus.FILLED
    assert outcome.resolved_at == fill.filled_at == _at(24, 10, 0)
    assert outcome.source_bar_id == fill.source_bar_id == source_bar.source_bar_id
    with pytest.raises(ValueError, match="outcome_id"):
        outcome.model_copy(update={"resolved_at": _at(24, 10, 1)})
    with pytest.raises(ValueError, match="outcome_id"):
        outcome.model_copy(update={"source_bar_id": "f" * 64})


def test_execution_is_independent_of_ambient_decimal_precision_and_scale() -> None:
    def execute(precision: int, rate: Decimal):
        with localcontext() as context:
            context.prec = precision
            config = _config(
                commission_rate=rate,
                minimum_commission_fen=0,
                stamp_duty_rate=Decimal("0.123456789"),
                transfer_fee_rate=Decimal("0.0000123456789"),
                buy_slippage_bps=Decimal("123.456789"),
                sell_slippage_bps=Decimal("98.7654321"),
            )
            engine = _engine(cash_fen=10**15, config=config)
            engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY))
            batch = engine.process_bar(
                _bar(_at(24, 10, 1), open_fen=123_456_789),
                _limit(24, up=200_000_000, down=1),
            )
            return config.config_hash, batch

    low_precision = execute(6, Decimal("0.1234567890"))
    high_precision = execute(50, Decimal("0.123456789"))

    assert low_precision == high_precision
    hostile = _config(commission_rate=Decimal("1E-1000000000"))
    with pytest.raises(ValueError, match="decimal expansion is too large"):
        _ = hostile.config_hash


def test_sell_enforces_t_plus_one_and_then_uses_directional_costs() -> None:
    same_day_lot = _initial_lot(acquired_day=24)
    blocked_engine = _engine(initial_lots=(same_day_lot,))
    blocked_engine.submit_signal(
        _signal(
            ActionableSignalType.RISK_EXIT_READY,
            target_lot_id=same_day_lot.lot_id,
            bucket="TACTICAL",
        )
    )

    source_bar = _bar(_at(24, 10, 1))
    blocked = blocked_engine.process_bar(source_bar, _limit(24))

    assert blocked.outcomes[0].reason is UnfilledReason.T_PLUS_ONE
    assert blocked.outcomes[0].resolved_at == _at(24, 10, 0)
    assert blocked.outcomes[0].source_bar_id == source_bar.source_bar_id
    assert blocked_engine.position_quantity == 100

    settled_lot = _initial_lot(acquired_day=23)
    engine = _engine(initial_lots=(settled_lot,))
    engine.submit_signal(
        _signal(
            ActionableSignalType.PRESSURE_REDUCE_READY,
            target_lot_id=settled_lot.lot_id,
            bucket="TACTICAL",
        )
    )
    sold = engine.process_bar(_bar(_at(24, 10, 1), open_fen=1_100), _limit(24, up=1_200))

    fill = sold.fills[0]
    assert fill.price_fen == 1_098
    assert fill.notional_fen == 109_800
    assert fill.fees.commission_fen == 500
    assert fill.fees.stamp_duty_fen == 55
    assert fill.fees.transfer_fee_fen == 2
    assert fill.cash_delta_fen == 109_243
    assert fill.realized_pnl_fen == 9_243
    assert engine.realized_pnl_fen == 9_243
    assert engine.position_quantity == 0


@pytest.mark.parametrize(
    ("signal_type", "open_fen", "limit_kwargs", "reason"),
    [
        (
            ActionableSignalType.BUY_CORE_READY,
            1_100,
            {"up": 1_100, "down": 900},
            UnfilledReason.LIMIT_UP_LOCKED,
        ),
        (
            ActionableSignalType.RISK_EXIT_READY,
            900,
            {"up": 1_100, "down": 900},
            UnfilledReason.LIMIT_DOWN_LOCKED,
        ),
    ],
)
def test_actual_daily_limits_conservatively_reject_orders(
    signal_type: ActionableSignalType,
    open_fen: int,
    limit_kwargs: dict[str, int],
    reason: UnfilledReason,
) -> None:
    initial_lot = _initial_lot(acquired_day=23)
    engine = _engine(initial_lots=(initial_lot,))
    target = initial_lot.lot_id if signal_type is ActionableSignalType.RISK_EXIT_READY else None
    bucket = "TACTICAL" if target else "CORE"
    engine.submit_signal(_signal(signal_type, target_lot_id=target, bucket=bucket))

    source_bar = _bar(_at(24, 10, 1), open_fen=open_fen)
    result = engine.process_bar(source_bar, _limit(24, **limit_kwargs))

    assert result.fills == ()
    assert result.outcomes[0].reason is reason
    assert result.outcomes[0].resolved_at == _at(24, 10, 0)
    assert result.outcomes[0].source_bar_id == source_bar.source_bar_id


def test_order_waits_through_zero_volume_then_uses_first_tradable_minute() -> None:
    engine = _engine()
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY))

    suspended_minute = engine.process_bar(
        _bar(_at(24, 10, 1), volume_shares=0, is_tradable=False),
        _limit(24),
    )
    resumed = engine.process_bar(_bar(_at(24, 10, 2)), _limit(24))

    assert suspended_minute.is_empty
    assert len(resumed.fills) == 1
    assert resumed.fills[0].filled_at == _at(24, 10, 1)


def test_suspension_is_reported_if_no_tradable_minute_remains() -> None:
    engine = _engine()
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY))

    source_bar = _bar(_at(24, 10, 1), volume_shares=0, is_tradable=False)
    waiting = engine.process_bar(source_bar, _limit(24))
    result = engine.finalize(replay_boundary=_at(24, 10, 1))

    assert waiting.is_empty
    assert result.outcomes[0].reason is UnfilledReason.SUSPENDED
    assert result.outcomes[0].resolved_at == _at(24, 10, 1)
    assert result.outcomes[0].source_bar_id == source_bar.source_bar_id


def test_buy_is_capped_by_plan_maximum_and_cash_in_board_lots() -> None:
    free = _config(
        commission_rate=Decimal("0"),
        minimum_commission_fen=0,
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        buy_slippage_bps=Decimal("0"),
        sell_slippage_bps=Decimal("0"),
    )
    initial = _initial_lot(acquired_day=23, quantity=100, bucket="CORE")
    engine = _engine(
        cash_fen=250_000,
        max_position_qty=300,
        core_target_qty=300,
        tactical_target_qty=0,
        config=free,
        initial_lots=(initial,),
    )
    engine.submit_signal(
        _signal(ActionableSignalType.BUY_CORE_READY, quantity=300, cause_id="partial-buy")
    )

    result = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    assert result.fills[0].requested_quantity == 300
    assert result.fills[0].quantity == 200
    assert engine.position_quantity == 300


def test_buy_is_also_capped_by_its_bucket_target() -> None:
    free = _config(
        commission_rate=Decimal("0"),
        minimum_commission_fen=0,
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        buy_slippage_bps=Decimal("0"),
        sell_slippage_bps=Decimal("0"),
    )
    initial = _initial_lot(acquired_day=23, quantity=100, bucket="CORE")
    engine = _engine(
        config=free,
        max_position_qty=1_000,
        core_target_qty=200,
        tactical_target_qty=500,
        initial_lots=(initial,),
    )
    engine.submit_signal(
        _signal(ActionableSignalType.BUY_CORE_READY, quantity=300, cause_id="bucket-cap")
    )

    result = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    assert result.fills[0].quantity == 100
    assert engine.position_snapshots[0].quantity == 200


def test_completely_insufficient_cash_rejects_without_leverage() -> None:
    engine = _engine(cash_fen=100)
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY))

    result = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    assert result.outcomes[0].reason is UnfilledReason.INSUFFICIENT_CASH
    assert engine.cash_fen == 100
    assert engine.position_quantity == 0


def test_missing_or_wrong_target_lot_cannot_sell_another_position() -> None:
    initial = _initial_lot(acquired_day=23)
    engine = _engine(initial_lots=(initial,))
    engine.submit_signal(
        _signal(
            ActionableSignalType.PRESSURE_REDUCE_READY,
            target_lot_id="lot-does-not-exist",
            bucket="TACTICAL",
        )
    )

    result = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    assert result.outcomes[0].reason is UnfilledReason.TARGET_LOT_NOT_FOUND
    assert engine.open_lots == (initial,)


@pytest.mark.parametrize(
    "signal_type",
    [
        ActionableSignalType.RISK_BREACH,
        ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
    ],
)
def test_non_executable_risk_signals_never_create_orders(
    signal_type: ActionableSignalType,
) -> None:
    initial = _initial_lot(acquired_day=23)
    target = (
        initial.lot_id if signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT else None
    )
    signal = _signal(
        signal_type,
        quantity=None if signal_type is ActionableSignalType.RISK_BREACH else 100,
        bucket=None if signal_type is ActionableSignalType.RISK_BREACH else "TACTICAL",
        target_lot_id=target,
    )
    engine = _engine(initial_lots=(initial,))

    result = engine.submit_signal(signal)

    assert result.orders == ()
    assert result.fills == ()
    assert result.outcomes[0].status is ExecutionStatus.IGNORED
    assert result.outcomes[0].reason is UnfilledReason.NON_EXECUTABLE_SIGNAL
    assert result.outcomes[0].resolved_at == signal.signal_at
    assert result.outcomes[0].source_bar_id is None


def test_duplicate_signal_is_idempotent_and_stable_identities_repeat() -> None:
    first_signal = _signal(ActionableSignalType.BUY_CORE_READY)
    repeated_signal = _signal(ActionableSignalType.BUY_CORE_READY)
    assert first_signal.signal_id == repeated_signal.signal_id
    assert _bar(_at(24, 10, 1)).source_bar_id == _bar(_at(24, 10, 1)).source_bar_id
    engine = _engine()

    first = engine.submit_signal(first_signal)
    duplicate = engine.submit_signal(repeated_signal)
    filled = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    assert len(first.orders) == 1
    assert duplicate.is_empty
    assert len(filled.fills) == 1
    assert engine.position_quantity == 100


def test_finalize_rejects_pending_order_once_when_no_next_minute_exists() -> None:
    engine = _engine()
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=_at(24, 15, 0)))

    replay_boundary = _at(24, 15, 30)
    first = engine.finalize(replay_boundary=replay_boundary)
    repeated = engine.finalize(replay_boundary=replay_boundary)

    assert first.fills == ()
    assert first.outcomes[0].reason is UnfilledReason.NO_NEXT_MINUTE
    assert first.outcomes[0].resolved_at == replay_boundary
    assert first.outcomes[0].source_bar_id is None
    assert repeated.is_empty


def test_finalize_rejects_a_boundary_before_replay_or_pending_order() -> None:
    engine = _engine()
    engine.process_bar(_bar(_at(24, 15, 0)), _limit(24))
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=_at(24, 15, 30)))

    with pytest.raises(ValueError, match="latest execution bar"):
        engine.finalize(replay_boundary=_at(24, 14, 59))
    with pytest.raises(ValueError, match="pending order"):
        engine.finalize(replay_boundary=_at(24, 15, 0))


def test_first_future_bar_is_candidate_without_wall_clock_inference() -> None:
    engine = _engine()
    engine.process_bar(_bar(_at(24, 15, 0)), _limit(24))
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=_at(24, 16, 0)))

    next_trade_date = engine.process_bar(_bar(_at(25, 9, 31)), _limit(25))

    assert len(next_trade_date.fills) == 1
    assert next_trade_date.fills[0].filled_at == _at(25, 9, 30)


def test_signal_inside_minute_cannot_use_an_open_that_precedes_it() -> None:
    engine = _engine()
    signal_at = _at(24, 10, 0).replace(second=30)
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=signal_at))

    bar_already_open = engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))
    next_unopened_bar = engine.process_bar(_bar(_at(24, 10, 2)), _limit(24))

    assert bar_already_open.is_empty
    assert len(next_unopened_bar.fills) == 1
    assert next_unopened_bar.fills[0].filled_at == _at(24, 10, 1)


def test_missing_expected_next_minute_fails_closed_on_the_gap_source_bar() -> None:
    engine = _engine()
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=_at(24, 10, 0)))
    gap_source = _bar(_at(24, 10, 2))

    result = engine.process_bar(gap_source, _limit(24))

    assert result.fills == ()
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.reason is UnfilledReason.MISSING_NEXT_MINUTE
    assert outcome.resolved_at == _at(24, 10, 1)
    assert outcome.source_bar_id == gap_source.source_bar_id
    assert engine.finalize(replay_boundary=_at(24, 10, 2)).is_empty


def test_lunch_break_is_a_valid_next_session_boundary_not_a_minute_gap() -> None:
    engine = _engine()
    engine.submit_signal(_signal(ActionableSignalType.BUY_CORE_READY, at=_at(24, 11, 30)))
    afternoon_open = _bar(_at(24, 13, 1))

    result = engine.process_bar(afternoon_open, _limit(24))

    assert len(result.fills) == 1
    assert result.outcomes[0].resolved_at == _at(24, 13, 0)
    assert result.outcomes[0].source_bar_id == afternoon_open.source_bar_id


def test_sell_rejects_when_fees_would_make_cash_negative() -> None:
    expensive_minimum = _config(
        commission_rate=Decimal("0"),
        minimum_commission_fen=500,
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        buy_slippage_bps=Decimal("0"),
        sell_slippage_bps=Decimal("0"),
    )
    initial = _initial_lot(acquired_day=23, cost_basis_fen=200)
    engine = _engine(cash_fen=0, config=expensive_minimum, initial_lots=(initial,))
    engine.submit_signal(
        _signal(
            ActionableSignalType.RISK_EXIT_READY,
            target_lot_id=initial.lot_id,
            bucket="TACTICAL",
        )
    )

    result = engine.process_bar(
        _bar(_at(24, 10, 1), open_fen=2),
        _limit(24, up=3, down=1),
    )

    assert result.fills == ()
    assert result.outcomes[0].reason is UnfilledReason.INSUFFICIENT_CASH
    assert engine.cash_fen == 0
    assert engine.open_lots == (initial,)


def test_position_lot_identity_fields_cannot_be_changed_by_model_copy() -> None:
    lot = _initial_lot(acquired_day=23)

    with pytest.raises(ValueError, match="identity fields"):
        lot.model_copy(update={"lot_id": "lot-forged"})
    with pytest.raises(ValueError, match="identity fields"):
        lot.model_copy(update={"source_fill_id": "fill-forged"})


def test_equity_and_position_snapshots_expose_exact_integer_state() -> None:
    initial = _initial_lot(acquired_day=23, cost_basis_fen=100_000)
    engine = _engine(cash_fen=900_000, initial_lots=(initial,))

    snapshot = engine.equity_snapshot(at=_at(24, 15, 0), mark_price_fen=1_050)

    assert snapshot.cash_fen == 900_000
    assert snapshot.position_quantity == 100
    assert snapshot.market_value_fen == 105_000
    assert snapshot.cost_basis_fen == 100_000
    assert snapshot.unrealized_pnl_fen == 5_000
    assert snapshot.equity_fen == 1_005_000
    assert engine.position_snapshots[0].quantity == 100


def test_values_are_frozen_strict_and_model_copy_revalidates_updates() -> None:
    config = _config()
    bar = _bar(_at(24, 10, 1))

    with pytest.raises(ValidationError):
        config.model_copy(update={"commission_rate": 0.1})
    with pytest.raises(ValidationError):
        bar.model_copy(update={"low_fen": 1_100})
    with pytest.raises(ValidationError):
        ExecutionConfig(
            commission_rate=0.0003,
            minimum_commission_fen=500,
            stamp_duty_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            buy_slippage_bps=Decimal("10"),
            sell_slippage_bps=Decimal("10"),
        )
    with pytest.raises(ValidationError):
        config.minimum_commission_fen = 0
    with pytest.raises(ValidationError, match="whole-minute"):
        _bar(_at(24, 10, 1).replace(second=1))


def test_engine_rejects_wrong_limit_identity_and_non_monotonic_bars() -> None:
    engine = _engine()
    engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))

    with pytest.raises(ValueError, match="strictly increasing"):
        engine.process_bar(_bar(_at(24, 10, 1)), _limit(24))
    with pytest.raises(ValueError, match="trade date"):
        _engine().process_bar(_bar(_at(24, 10, 1)), _limit(25))
