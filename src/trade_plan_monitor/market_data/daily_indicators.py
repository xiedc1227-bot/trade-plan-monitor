"""daily-ta-v2 uses completed adjusted prices and the established Wilder seeds."""

from decimal import Decimal

import pandas as pd

from trade_plan_monitor.market_data.daily_data import DailySeries
from trade_plan_monitor.market_data.indicators import _wilder_atr, _wilder_rsi

PARAMETERS = {
    "MA20": {"period": 20},
    "MA60": {"period": 60},
    "MACD_DIF": {"fast": 12, "slow": 26, "signal": 9},
    "MACD_DEA": {"fast": 12, "slow": 26, "signal": 9},
    "MACD_HIST": {"fast": 12, "slow": 26, "signal": 9},
    "RSI14": {"period": 14},
    "ATR14": {"period": 14},
    **{
        name: {"period": 20, "deviations": 2}
        for name in ("BOLL_LOWER", "BOLL_MIDDLE", "BOLL_UPPER", "BOLL_BANDWIDTH")
    },
}


def calculate_daily_ta_v2(series: DailySeries) -> tuple[dict[str, Decimal | None], ...]:
    """Calculate in yuan without rounding adjusted historical prices to ticks."""
    series = DailySeries.model_validate(series.model_dump())
    close = pd.Series([float(b.close / 100) for b in series.bars], dtype="float64")
    high = pd.Series([float(b.high / 100) for b in series.bars], dtype="float64")
    low = pd.Series([float(b.low / 100) for b in series.bars], dtype="float64")
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    ma20 = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    upper, lower = ma20 + 2 * std, ma20 - 2 * std
    values = {
        "MA20": ma20,
        "MA60": close.rolling(60).mean(),
        "MACD_DIF": dif,
        "MACD_DEA": dea,
        "MACD_HIST": 2 * (dif - dea),
        "RSI14": _wilder_rsi(close),
        "ATR14": _wilder_atr(high, low, close),
        "BOLL_LOWER": lower,
        "BOLL_MIDDLE": ma20,
        "BOLL_UPPER": upper,
        "BOLL_BANDWIDTH": (upper - lower) / ma20 * 100,
    }
    return tuple(
        {
            name: None if value[i] is None or pd.isna(value[i]) else Decimal(str(float(value[i])))
            for name, value in values.items()
        }
        for i in range(len(series.bars))
    )
