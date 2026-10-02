"""Synthetic reviewed daily rules; no historical source threshold is invented."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.domain.daily_plan_models import DailyAll, DailyAny, DailyPriceCompare
from trade_plan_monitor.market_data.daily_data import CertifiedDailyBar, DailySeries
from trade_plan_monitor.market_data.daily_indicators import calculate_daily_ta_v2
from trade_plan_monitor.market_data.indicators import calculate_ta_v1
from trade_plan_monitor.market_data.models import DailyBar

SH = ZoneInfo("Asia/Shanghai")


def synthetic_series(count=70):
    bars = []
    raw = []
    for i in range(count):
        day = date(2026, 6, 1) + timedelta(days=i)
        stamp = datetime(day.year, day.month, day.day, 16, tzinfo=SH)
        close = 3900 + i
        original = DailyBar(
            symbol="601021.SH",
            trade_date=day,
            open_fen=close - 10,
            high_fen=close + 20,
            low_fen=close - 20,
            close_fen=close,
            volume_shares=1000 + i,
            amount_yuan=Decimal(1000),
            is_official=True,
            received_at=stamp,
        )
        raw.append(original)
        bars.append(
            CertifiedDailyBar(
                bar_id=f"synthetic-{i}",
                symbol=original.symbol,
                trade_date=day,
                open=Decimal(close - 10),
                high=Decimal(close + 20),
                low=Decimal(close - 20),
                close=Decimal(close),
                volume_shares=1000 + i,
                official=True,
                provider="synthetic",
                available_at=stamp,
                received_at=stamp,
                basis_id="synthetic-qfq",
                adjustment_as_of=raw[-1].trade_date,
            )
        )
    # A coherent end-date basis, explicitly certified in this offline fixture.
    bars = [b.model_copy(update={"adjustment_as_of": raw[-1].trade_date}) for b in bars]
    return DailySeries(
        symbol="601021.SH",
        bars=tuple(bars),
        basis_id="synthetic-qfq",
        adjustment_as_of=raw[-1].trade_date,
        provider="synthetic",
        quote_comparable=True,
        session_dates=tuple(b.trade_date for b in bars),
        suspended_dates=(),
        cutoff=bars[-1].available_at,
    ), tuple(raw)


def test_v2_histogram_doubles_v1_without_changing_dif_dea():
    series, raw = synthetic_series()
    old = calculate_ta_v1(raw)
    new = calculate_daily_ta_v2(series)
    for v1, v2 in zip(old.points, new, strict=True):
        assert float(v2["MACD_DIF"]) == pytest.approx(v1.macd_yuan)
        assert float(v2["MACD_DEA"]) == pytest.approx(v1.macd_signal_yuan)
        assert float(v2["MACD_HIST"]) == pytest.approx(2 * v1.macd_histogram_yuan)
    assert new[58]["MA60"] is None
    assert new[59]["MA60"] is not None


def test_daily_all_any_missing_retains_each_evidence():
    series, _ = synthetic_series()

    def leaf(value, offset=0):
        return DailyPriceCompare(
            type="DAILY_PRICE_COMPARE",
            field="close",
            offset=offset,
            comparator="GT",
            reference={
                "mode": "FIXED",
                "value": str(value),
                "unit": "FEN",
                "as_of": series.bars[-1].trade_date,
                "source": "Synthetic human supplement",
            },
        )

    missing, yes, no = leaf(0, 499), leaf(0), leaf(9999)
    assert (
        evaluate_daily_condition(DailyAll(type="ALL", conditions=(missing, no)), series).outcome
        == "UNSATISFIED"
    )
    result = evaluate_daily_condition(DailyAny(type="ANY", conditions=(missing, yes)), series)
    assert result.outcome == "SATISFIED"
    assert len(result.children) == 2
    assert (
        evaluate_daily_condition(DailyAll(type="ALL", conditions=(missing, yes)), series).outcome
        == "MISSING_INPUT"
    )


def test_raw_or_incoherent_daily_basis_cannot_be_admitted():
    series, _ = synthetic_series()
    with pytest.raises(ValueError):
        DailySeries.model_validate({**series.model_dump(), "quote_comparable": False})
    with pytest.raises(ValueError):
        DailySeries.model_validate(
            {**series.model_dump(), "session_dates": series.session_dates[:-1]}
        )
