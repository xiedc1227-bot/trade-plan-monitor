"""Real historical normalizer, with SDK responses confined to offline fixtures."""

from datetime import datetime, timedelta

import pytest
from tests.unit.test_tushare_historical import (
    SHANGHAI,
    FakeTushareClient,
    _fixture_frame,
)

from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.tushare import TushareProviderError
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider


def test_current_target_prefix_uses_actual_receipt_and_exact_request():
    target = datetime(2026, 8, 24, 9, 35, tzinfo=SHANGHAI)
    frame = _fixture_frame()
    frame = frame.loc[frame.trade_time <= "2026-08-24 09:35:00"].copy()
    client = FakeTushareClient(frame)
    received = target + timedelta(minutes=2)
    provider = TushareHistoricalMinuteProvider(client, now=lambda: received,
        profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1)
    window = provider.buy_suspension_minutes("600000.SH", target)
    assert len(window.bars) == 5
    assert window.through == target and window.received_at == received
    assert all(bar.received_at == received for bar in window.bars)
    assert len(window.source_hash) == 64
    assert client.calls[0][1]["end_date"] == "2026-08-24 09:35:00"
    assert "adj" not in client.calls[0][1]


@pytest.mark.parametrize("fault", ["missing", "future", "duplicate"])
def test_window_refuses_incomplete_future_or_duplicate_source(fault):
    target = datetime(2026, 8, 24, 9, 35, tzinfo=SHANGHAI)
    frame = _fixture_frame()
    frame = frame.loc[frame.trade_time <= "2026-08-24 09:35:00"].copy()
    if fault == "missing":
        frame = frame.iloc[:-1]
    elif fault == "future":
        frame.iloc[0, frame.columns.get_loc("trade_time")] = "2026-08-24 09:36:00"
    else:
        frame.iloc[0] = frame.iloc[1]
    provider = TushareHistoricalMinuteProvider(FakeTushareClient(frame), now=lambda: target,
        profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1)
    with pytest.raises(TushareProviderError):
        provider.buy_suspension_minutes("600000.SH", target)


def test_unverified_or_future_target_never_calls_sdk():
    target = datetime(2026, 8, 24, 9, 35, tzinfo=SHANGHAI)
    for profile, observed in (
        (HistoricalMinuteProfile.UNVERIFIED, target),
        (HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1, target - timedelta(minutes=1)),
    ):
        client = FakeTushareClient(_fixture_frame())
        provider = TushareHistoricalMinuteProvider(
            client, now=lambda t=observed: t, profile=profile)
        with pytest.raises(ValueError):
            provider.buy_suspension_minutes("600000.SH", target)
        assert client.calls == []
