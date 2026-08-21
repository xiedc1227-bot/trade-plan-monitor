from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.market_data.indicators import (
    TA_FORMULA_VERSION,
    IndicatorSeries,
    calculate_ta_v1,
)
from trade_plan_monitor.market_data.models import DailyBar

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _daily_bars(count: int = 220, *, symbol: str = "003043.SZ") -> tuple[DailyBar, ...]:
    start = date(2025, 1, 1)
    bars: list[DailyBar] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close_fen = 6_000 + index * 3 + ((index % 7) - 3) * 5
        open_fen = close_fen + ((index % 3) - 1) * 8
        high_fen = max(open_fen, close_fen) + 20 + index % 5
        low_fen = min(open_fen, close_fen) - 18 - index % 4
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=trade_date,
                open_fen=open_fen,
                high_fen=high_fen,
                low_fen=low_fen,
                close_fen=close_fen,
                volume_shares=1_000_000 + index * 1_000,
                amount_yuan=Decimal("60000000") + index * Decimal("10000.25"),
                is_official=True,
                received_at=datetime.combine(trade_date, time(16), SHANGHAI),
            )
        )
    return tuple(bars)


def test_ta_v1_matches_fixed_pandas_and_wilder_golden_values() -> None:
    result = calculate_ta_v1(_daily_bars())
    latest = result.points[-1]

    assert result.formula_version == "ta-v1"
    assert result.symbol == "003043.SZ"
    assert latest.bar_at == date(2025, 8, 8)
    assert latest.ema10_yuan == pytest.approx(66.41405330734709)
    assert latest.ema12_yuan == pytest.approx(66.38755265566631)
    assert latest.ema26_yuan == pytest.approx(66.18707054440716)
    assert latest.macd_yuan == pytest.approx(0.200482111259149)
    assert latest.macd_signal_yuan == pytest.approx(0.208738073074784)
    assert latest.macd_histogram_yuan == pytest.approx(-0.008255961815636)
    assert latest.boll_middle_yuan == pytest.approx(66.285)
    assert latest.boll_upper_yuan == pytest.approx(66.65445906403552)
    assert latest.boll_lower_yuan == pytest.approx(65.91554093596447)
    assert latest.rsi14 == pytest.approx(62.276278734753156)
    assert latest.atr14_yuan == pytest.approx(0.479647785901799)
    assert latest.ma20_yuan == pytest.approx(66.285)
    assert latest.ma50_yuan == pytest.approx(65.834)
    assert latest.ma200_yuan == pytest.approx(63.58425)


def test_ta_v1_uses_explicit_window_gaps_and_wilder_seeds() -> None:
    result = calculate_ta_v1(_daily_bars(20))

    assert result.points[0].ema10_yuan == pytest.approx(59.85)
    assert result.points[0].macd_yuan == pytest.approx(0.0)
    assert result.points[0].macd_signal_yuan == pytest.approx(0.0)
    assert result.points[0].macd_histogram_yuan == pytest.approx(0.0)
    assert result.points[0].boll_middle_yuan is None
    assert result.points[0].rsi14 is None
    assert result.points[0].atr14_yuan is None
    assert result.points[13].atr14_yuan == pytest.approx(0.4671428571428561)
    assert result.points[13].rsi14 is None
    assert result.points[14].rsi14 == pytest.approx(64.0000000000002)
    assert result.points[18].ma20_yuan is None
    assert result.points[19].ma20_yuan is not None
    assert result.points[19].boll_middle_yuan == result.points[19].ma20_yuan
    assert result.points[-1].ma50_yuan is None
    assert result.points[-1].ma200_yuan is None


def test_ta_v1_is_repeatable_closed_and_immutable() -> None:
    bars = _daily_bars(20)
    first = calculate_ta_v1(bars)
    second = calculate_ta_v1(bars)

    assert first == second
    assert isinstance(first, IndicatorSeries)
    assert TA_FORMULA_VERSION == "ta-v1"
    with pytest.raises(ValidationError, match="frozen"):
        first.formula_version = "ta-v2"
    with pytest.raises(ValidationError, match="frozen"):
        first.points[-1].ema10_yuan = 0.0
    with pytest.raises(ValidationError):
        first.model_copy(update={"formula_version": "ta-v2"})
    with pytest.raises(ValidationError):
        first.points[-1].model_copy(update={"rsi14": 101.0})


def test_ta_v1_rejects_empty_unbounded_mixed_or_nonmonotonic_input() -> None:
    bars = _daily_bars(2)

    with pytest.raises(ValueError, match="at least one"):
        calculate_ta_v1(())
    with pytest.raises(TypeError, match="tuple"):
        calculate_ta_v1(list(bars))
    with pytest.raises(ValueError, match="10000"):
        calculate_ta_v1((bars[0],) * 10_001)
    with pytest.raises(ValueError, match="one symbol"):
        calculate_ta_v1(
            (
                bars[0],
                bars[1].model_copy(update={"symbol": "600519.SH"}),
            )
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        calculate_ta_v1(tuple(reversed(bars)))
    with pytest.raises(ValueError, match="strictly increasing"):
        calculate_ta_v1((bars[0], bars[0]))


def test_ta_v1_rejects_mixed_daily_and_five_minute_bar_types() -> None:
    from trade_plan_monitor.market_data.aggregation import FiveMinuteBar

    daily = _daily_bars(1)[0]
    intraday = FiveMinuteBar(
        symbol=daily.symbol,
        bar_end=datetime(2026, 8, 21, 9, 35, tzinfo=SHANGHAI),
        formula_version="ta-v1",
        open_fen=daily.open_fen,
        high_fen=daily.high_fen,
        low_fen=daily.low_fen,
        close_fen=daily.close_fen,
        volume_shares=daily.volume_shares,
        amount_yuan=daily.amount_yuan,
    )

    with pytest.raises(TypeError, match="one bar type"):
        calculate_ta_v1((daily, intraday))


def test_ta_v1_calculates_time_aligned_five_minute_series() -> None:
    from trade_plan_monitor.market_data.aggregation import FiveMinuteBar

    start = datetime(2026, 8, 21, 9, 35, tzinfo=SHANGHAI)
    bars = tuple(
        FiveMinuteBar(
            symbol="003043.SZ",
            bar_end=start + timedelta(minutes=5 * index),
            formula_version="ta-v1",
            open_fen=6_400 + index,
            high_fen=6_430 + index,
            low_fen=6_390 + index,
            close_fen=6_420 + index,
            volume_shares=500_000 + index,
            amount_yuan=Decimal("32000000") + index,
        )
        for index in range(20)
    )

    result = calculate_ta_v1(bars)

    assert result.points[-1].bar_at == bars[-1].bar_end
    assert result.points[-1].boll_middle_yuan is not None
    assert result.points[-1].ma20_yuan is not None
    assert result.points[-1].ma50_yuan is None


def test_ta_v1_rejects_prices_outside_finite_float_calculation_range() -> None:
    huge_fen = 10**400
    bar = _daily_bars(1)[0].model_copy(
        update={
            "open_fen": huge_fen,
            "high_fen": huge_fen + 1,
            "low_fen": huge_fen - 1,
            "close_fen": huge_fen,
        }
    )

    with pytest.raises(ValueError, match="finite float range"):
        calculate_ta_v1((bar,))
