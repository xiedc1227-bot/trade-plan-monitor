from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.decision.models import ConditionOutcome, MissingInputCode
from trade_plan_monitor.domain.plan_models import (
    CompletedCloseInRangeCondition,
    ExplicitAllCondition,
    ExplicitAnyCondition,
    VolumeToMeanGteCondition,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import TradingDay

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bar(end: datetime, volume: int, close: int = 990, symbol: str = "003043.SZ") -> FiveMinuteBar:
    return FiveMinuteBar(
        symbol=symbol,
        bar_end=end,
        open_fen=close,
        high_fen=close,
        low_fen=close,
        close_fen=close,
        volume_shares=volume,
        amount_yuan=Decimal("0"),
    )


def _continuous_bars(current_volume: int, current_close: int = 990) -> tuple[FiveMinuteBar, ...]:
    first = datetime(2026, 9, 14, 9, 40, tzinfo=SHANGHAI)
    volumes = [100, 100, 100, 100, 600, current_volume]
    return tuple(
        _bar(first + timedelta(minutes=5 * index), volume, current_close)
        for index, volume in enumerate(volumes)
    )


def _volume_condition() -> VolumeToMeanGteCondition:
    return VolumeToMeanGteCondition(
        window_bars=5,
        minimum_ratio="1.5",
        history_scope="CONTIGUOUS_TRADING_BARS",
    )


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        (200, ConditionOutcome.UNSATISFIED),
        (299, ConditionOutcome.UNSATISFIED),
        (300, ConditionOutcome.SATISFIED),
        (301, ConditionOutcome.SATISFIED),
    ],
)
def test_mean_volume_uses_preceding_nonuniform_window_and_exact_equality(
    volume: int,
    expected: ConditionOutcome,
) -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition

    bars = _continuous_bars(volume)
    original_precision = getcontext().prec
    getcontext().prec = 2
    try:
        evidence = evaluate_explicit_condition(
            _volume_condition(),
            bars=bars,
            target_bucket_end=bars[-1].bar_end,
            trading_calendar=(),
            plan_path="rules[0].condition.conditions[1]",
        )
    finally:
        getcontext().prec = original_precision

    assert evidence.outcome is expected
    facts = {fact.key: fact.value for fact in evidence.facts}
    assert facts["sum_volume_shares"] == 1000
    assert facts["mean_volume_shares"] == Decimal("200")
    assert facts["current_volume_shares"] == volume
    assert evidence.bar_ends == tuple(bar.bar_end for bar in bars)


@pytest.mark.parametrize(
    ("close", "expected"),
    [
        (979, False),
        (980, True),
        (981, True),
        (999, True),
        (1000, True),
        (1001, False),
    ],
)
def test_completed_close_range_honors_inclusive_fen_boundaries(
    close: int,
    expected: bool,
) -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition

    bars = _continuous_bars(300, close)
    condition = CompletedCloseInRangeCondition(
        low_fen=980,
        high_fen=1000,
        include_low=True,
        include_high=True,
    )

    evidence = evaluate_explicit_condition(
        condition,
        bars=bars,
        target_bucket_end=bars[-1].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition.conditions[0]",
    )

    assert (evidence.outcome is ConditionOutcome.SATISFIED) is expected


def test_volume_window_rejects_gap_wrong_order_future_and_mixed_symbol() -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition

    bars = _continuous_bars(300)
    invalid_series = (
        bars[:2] + bars[3:],
        tuple(reversed(bars)),
        bars + (_bar(bars[-1].bar_end + timedelta(minutes=5), 300),),
        bars[:-1] + (_bar(bars[-1].bar_end, 300, symbol="000001.SZ"),),
    )

    for invalid in invalid_series:
        evidence = evaluate_explicit_condition(
            _volume_condition(),
            bars=invalid,
            target_bucket_end=bars[-1].bar_end,
            trading_calendar=(),
            plan_path="rules[0].condition",
        )
        assert evidence.outcome is ConditionOutcome.MISSING_INPUT


def test_volume_window_accepts_lunch_and_confirmed_previous_trading_day_adjacency() -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition

    lunch_ends = [(11, 15), (11, 20), (11, 25), (11, 30), (13, 5), (13, 10)]
    lunch = tuple(
        _bar(
            datetime(2026, 9, 14, hour, minute, tzinfo=SHANGHAI),
            150 if index == len(lunch_ends) - 1 else 100,
        )
        for index, (hour, minute) in enumerate(lunch_ends)
    )
    cross_day_ends = (
            datetime(2026, 9, 11, 14, 45, tzinfo=SHANGHAI),
            datetime(2026, 9, 11, 14, 50, tzinfo=SHANGHAI),
            datetime(2026, 9, 11, 14, 55, tzinfo=SHANGHAI),
            datetime(2026, 9, 11, 15, 0, tzinfo=SHANGHAI),
            datetime(2026, 9, 14, 9, 35, tzinfo=SHANGHAI),
            datetime(2026, 9, 14, 9, 40, tzinfo=SHANGHAI),
        )
    cross_day = tuple(
        _bar(end, 150 if index == len(cross_day_ends) - 1 else 100)
        for index, end in enumerate(cross_day_ends)
    )
    calendar = (
        TradingDay(
            exchange="SZSE",
            cal_date=date(2026, 9, 14),
            is_open=True,
            previous_trade_date=date(2026, 9, 11),
        ),
    )

    for bars, rows in ((lunch, ()), (cross_day, calendar)):
        evidence = evaluate_explicit_condition(
            _volume_condition(),
            bars=bars,
            target_bucket_end=bars[-1].bar_end,
            trading_calendar=rows,
            plan_path="rules[0].condition",
        )
        assert evidence.outcome is ConditionOutcome.SATISFIED

    missing_calendar = evaluate_explicit_condition(
        _volume_condition(),
        bars=cross_day,
        target_bucket_end=cross_day[-1].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition",
    )
    assert missing_calendar.outcome is ConditionOutcome.MISSING_INPUT
    assert missing_calendar.missing_inputs == (MissingInputCode.TRADING_CALENDAR,)


def test_zero_mean_is_data_and_logical_three_value_semantics_are_scoped() -> None:
    from trade_plan_monitor.decision.explicit_conditions import evaluate_explicit_condition

    first = datetime(2026, 9, 14, 9, 40, tzinfo=SHANGHAI)
    zero_bars = tuple(_bar(first + timedelta(minutes=5 * index), 0) for index in range(6))
    price = CompletedCloseInRangeCondition(
        low_fen=980,
        high_fen=1000,
        include_low=True,
        include_high=True,
    )
    missing_volume_bars = zero_bars[:-2] + zero_bars[-1:]
    any_condition = ExplicitAnyCondition(conditions=(price, _volume_condition()))
    all_condition = ExplicitAllCondition(conditions=(price, _volume_condition()))

    zero = evaluate_explicit_condition(
        _volume_condition(),
        bars=zero_bars,
        target_bucket_end=zero_bars[-1].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition",
    )
    any_result = evaluate_explicit_condition(
        any_condition,
        bars=missing_volume_bars,
        target_bucket_end=zero_bars[-1].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition",
    )
    all_result = evaluate_explicit_condition(
        all_condition,
        bars=missing_volume_bars,
        target_bucket_end=zero_bars[-1].bar_end,
        trading_calendar=(),
        plan_path="rules[0].condition",
    )

    assert zero.outcome is ConditionOutcome.SATISFIED
    assert any_result.outcome is ConditionOutcome.SATISFIED
    assert all_result.outcome is ConditionOutcome.MISSING_INPUT
