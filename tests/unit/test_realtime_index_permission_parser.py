"""Current-day index permission proof validates every returned SDK row."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.clock import SHANGHAI

DAY = date(2026, 9, 8)
CODE = MarketIndexCode.SSE_COMPOSITE
PHYSICAL_START = datetime(2026, 9, 8, 10, 5, 16, tzinfo=SHANGHAI)


def _frame(
    label: TushareMarketIndexSourceTimeLabel, *, opening_snapshot: bool = False,
) -> pd.DataFrame:
    first_end = datetime(2026, 9, 8, 9, 35)
    offset = (
        timedelta(minutes=5)
        if label is TushareMarketIndexSourceTimeLabel.START else timedelta()
    )
    sources = [first_end + timedelta(minutes=5 * index) - offset for index in range(7)]
    if opening_snapshot:
        sources.insert(0, datetime(2026, 9, 8, 9, 30))
    return pd.DataFrame([{
        "ts_code": CODE.value,
        "freq": "5MIN",
        "time": source.strftime("%Y-%m-%d %H:%M:%S"),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "vol": "1000",
        "amount": "10000",
    } for source in sources])


def _provider(frame: pd.DataFrame, label: TushareMarketIndexSourceTimeLabel):
    calls: list[dict[str, object]] = []

    class SDK:
        def rt_idx_min_daily(self, **kwargs):
            calls.append(kwargs)
            return frame

    profile = certified_tushare_market_index_profile(
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.READY
                if code is CODE else TushareMarketIndexCapabilityStatus.DEFERRED
            ) for code in MarketIndexCode
        },
        source_time_label=label,
    )
    provider = TushareMarketIndexProvider(profile=profile, client=SDK())
    return provider, calls


@pytest.mark.parametrize(
    ("label", "opening_snapshot", "without_freq"),
    (
        (TushareMarketIndexSourceTimeLabel.END, False, False),
        (TushareMarketIndexSourceTimeLabel.END, True, False),
        (TushareMarketIndexSourceTimeLabel.START, False, False),
        (TushareMarketIndexSourceTimeLabel.START, False, True),
    ),
)
def test_complete_current_day_batch_proves_readability_without_cache(
    label, opening_snapshot, without_freq,
) -> None:
    frame = _frame(label, opening_snapshot=opening_snapshot)
    if without_freq:
        frame = frame.drop(columns="freq")
    provider, calls = _provider(frame, label)

    provider.probe_realtime_minutes_permission(CODE, DAY, lambda: PHYSICAL_START)

    assert calls == [{
        "ts_code": CODE.value,
        "freq": "5MIN",
        "fields": "ts_code,freq,time,open,close,high,low,vol,amount",
    }]
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}


def test_end_labeled_full_session_accepts_48_bars_plus_opening_snapshot() -> None:
    sources = [
        datetime(2026, 9, 8, hour, minute) + timedelta(minutes=5 * offset)
        for hour, minute in ((9, 35), (13, 5))
        for offset in range(24)
    ]
    frame = _frame(TushareMarketIndexSourceTimeLabel.END, opening_snapshot=True)
    template = frame.iloc[[1]].copy()
    rows = [frame.iloc[0].to_dict()]
    for source in sources:
        row = template.iloc[0].to_dict()
        row["time"] = source.strftime("%Y-%m-%d %H:%M:%S")
        rows.append(row)
    provider, calls = _provider(
        pd.DataFrame(rows), TushareMarketIndexSourceTimeLabel.END,
    )

    provider.probe_realtime_minutes_permission(
        CODE, DAY, lambda: datetime(2026, 9, 8, 15, 0, 12, tzinfo=SHANGHAI),
    )

    assert len(calls) == 1
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}


@pytest.mark.parametrize("identity_column", ("ts_code", "code"))
def test_one_completed_row_with_one_certified_identity_proves_readability(
    identity_column,
) -> None:
    frame = _frame(TushareMarketIndexSourceTimeLabel.END).iloc[[-1]].copy()
    if identity_column == "code":
        frame = frame.rename(columns={"ts_code": "code"})
    provider, calls = _provider(frame, TushareMarketIndexSourceTimeLabel.END)

    provider.probe_realtime_minutes_permission(CODE, DAY, lambda: PHYSICAL_START)

    assert len(calls) == 1
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}


def test_dual_identity_columns_cannot_prove_realtime_permission() -> None:
    frame = _frame(TushareMarketIndexSourceTimeLabel.END)
    frame["code"] = CODE.value
    provider, _ = _provider(frame, TushareMarketIndexSourceTimeLabel.END)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_realtime_minutes_permission(CODE, DAY, lambda: PHYSICAL_START)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "damage",
    ("mixed", "wrong_freq", "duplicate", "duplicate_column", "future", "bad_ohlc",
     "extra_column", "too_many", "opening_only", "unfinished_first"),
)
def test_bad_current_day_batch_cannot_prove_realtime_permission(damage) -> None:
    frame = _frame(TushareMarketIndexSourceTimeLabel.END)
    physical_start = PHYSICAL_START
    if damage == "mixed":
        frame.loc[0, "ts_code"] = MarketIndexCode.STAR_50.value
    elif damage == "wrong_freq":
        frame.loc[0, "freq"] = "1MIN"
    elif damage == "duplicate":
        frame.loc[1, "time"] = frame.loc[0, "time"]
    elif damage == "duplicate_column":
        frame.insert(4, "open_copy", frame["open"])
        frame.columns = ["open" if name == "open_copy" else name for name in frame.columns]
    elif damage == "future":
        frame.loc[0, "time"] = "2026-09-08 10:10:00"
    elif damage == "bad_ohlc":
        frame.loc[0, "low"] = "101"
    elif damage == "extra_column":
        frame["unexpected"] = "value"
    elif damage == "too_many":
        frame = pd.concat((frame,) * 8, ignore_index=True)
    elif damage == "opening_only":
        frame = frame.iloc[[0]].copy()
        frame.loc[frame.index[0], "time"] = "2026-09-08 09:30:00"
    else:
        physical_start = datetime(2026, 9, 8, 9, 35, 11, tzinfo=SHANGHAI)
        frame = frame.iloc[[0]]
    provider, calls = _provider(frame, TushareMarketIndexSourceTimeLabel.END)

    with pytest.raises(TushareProviderError) as caught:
        provider.probe_realtime_minutes_permission(CODE, DAY, lambda: physical_start)

    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    assert len(calls) == 1
    assert provider._historical_minute_cache == {}
    assert provider._intraday_daily_cache == {}
