import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "market_data" / "tushare_frames.json"
RECEIVED_AT = datetime(2026, 8, 20, 9, 33, 12, tzinfo=SHANGHAI)


def _load_frames() -> dict[str, pd.DataFrame]:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {
        name: pd.DataFrame(frame["rows"], columns=frame["columns"]) for name, frame in raw.items()
    }


class FakeTushareClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def rt_min(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("rt_min", kwargs))
        return self.frames["rt_min"].copy(deep=True)

    def rt_min_daily(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("rt_min_daily", kwargs))
        return self.frames["rt_min_daily"].copy(deep=True)

    def trade_cal(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("trade_cal", kwargs))
        return self.frames["trade_cal"].copy(deep=True)

    def stk_limit(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("stk_limit", kwargs))
        return self.frames["stk_limit"].copy(deep=True)

    def daily(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("daily", kwargs))
        return self.frames["daily"].copy(deep=True)


def _provider(
    client: FakeTushareClient,
    *,
    received_at: datetime = RECEIVED_AT,
    is_open_on: Callable[[date], bool | None] | None = None,
    source_time_label: SourceTimeLabel = SourceTimeLabel.START,
) -> TushareMarketDataProvider:
    return TushareMarketDataProvider(
        client,
        now=lambda: received_at,
        is_open_on=is_open_on or (lambda value: value == date(2026, 8, 20)),
        source_time_label=source_time_label,
        probe_symbol="003043.SZ",
    )


def _invoke_frame_method(
    provider: TushareMarketDataProvider,
    frame_name: str,
) -> object:
    if frame_name == "rt_min":
        return provider.realtime_minutes(("003043.SZ",))
    if frame_name == "rt_min_daily":
        return provider.current_day_minutes("003043.SZ")
    if frame_name == "trade_cal":
        return provider.trading_calendar(date(2026, 8, 19), date(2026, 8, 22))
    if frame_name == "stk_limit":
        return provider.daily_limits(date(2026, 8, 20))
    if frame_name == "daily":
        return provider.daily_bars("003043.SZ", date(2026, 8, 19), date(2026, 8, 19))
    raise AssertionError(f"unknown fixture frame: {frame_name}")


def test_tushare_rt_min_normalizes_healthy_requested_symbols_and_units() -> None:
    client = FakeTushareClient(_load_frames())

    bars = _provider(client).realtime_minutes(("003043.SZ", "600000.SH", "000001.SZ"))

    assert bars == [
        MinuteBar(
            symbol="003043.SZ",
            bar_end=datetime(2026, 8, 20, 9, 31, tzinfo=SHANGHAI),
            open_fen=6300,
            high_fen=6330,
            low_fen=6290,
            close_fen=6320,
            volume_shares=125600,
            amount_yuan=Decimal("8079200.50"),
            received_at=RECEIVED_AT,
        ),
        MinuteBar(
            symbol="600000.SH",
            bar_end=datetime(2026, 8, 20, 9, 31, tzinfo=SHANGHAI),
            open_fen=1005,
            high_fen=1007,
            low_fen=1003,
            close_fen=1006,
            volume_shares=514800,
            amount_yuan=Decimal("5171897"),
            received_at=RECEIVED_AT,
        ),
    ]
    assert {bar.symbol for bar in bars} == {"003043.SZ", "600000.SH"}
    assert client.calls == [
        (
            "rt_min",
            {
                "ts_code": "003043.SZ,600000.SH,000001.SZ",
                "freq": "1MIN",
                "fields": "ts_code,time,open,close,high,low,vol,amount",
            },
        )
    ]


def test_tushare_rt_min_daily_accepts_documented_code_alias_and_sorts_minutes() -> None:
    client = FakeTushareClient(_load_frames())

    bars = _provider(client).current_day_minutes("003043.SZ")

    assert [(bar.bar_end.minute, bar.volume_shares, bar.amount_yuan) for bar in bars] == [
        (31, 10000, Decimal("631000")),
        (32, 20000, Decimal("1265000.25")),
    ]
    assert all(bar.symbol == "003043.SZ" for bar in bars)
    assert all(bar.received_at == RECEIVED_AT for bar in bars)
    assert client.calls == [
        (
            "rt_min_daily",
            {
                "ts_code": "003043.SZ",
                "freq": "1MIN",
                "fields": "ts_code,freq,time,open,close,high,low,vol,amount",
            },
        )
    ]


def test_tushare_trade_cal_normalizes_dates_open_flags_and_exchange() -> None:
    client = FakeTushareClient(_load_frames())

    days = _provider(client).trading_calendar(date(2026, 8, 19), date(2026, 8, 22))

    assert days == [
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, 19),
            is_open=True,
            previous_trade_date=date(2026, 8, 18),
        ),
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, 20),
            is_open=True,
            previous_trade_date=date(2026, 8, 19),
        ),
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, 22),
            is_open=False,
            previous_trade_date=date(2026, 8, 21),
        ),
    ]
    assert client.calls == [
        (
            "trade_cal",
            {
                "exchange": "",
                "start_date": "20260819",
                "end_date": "20260822",
                "fields": "exchange,cal_date,is_open,pretrade_date",
            },
        )
    ]


def test_tushare_stk_limit_normalizes_actual_limit_prices() -> None:
    client = FakeTushareClient(_load_frames())

    limits = _provider(client).daily_limits(date(2026, 8, 20))

    assert limits == [
        DailyLimit(
            symbol="003043.SZ",
            trade_date=date(2026, 8, 20),
            up_limit_fen=1506,
            down_limit_fen=1234,
            received_at=RECEIVED_AT,
        ),
        DailyLimit(
            symbol="600000.SH",
            trade_date=date(2026, 8, 20),
            up_limit_fen=1007,
            down_limit_fen=825,
            received_at=RECEIVED_AT,
        ),
    ]
    assert client.calls == [
        (
            "stk_limit",
            {
                "trade_date": "20260820",
                "fields": "trade_date,ts_code,up_limit,down_limit",
            },
        )
    ]


def test_tushare_daily_converts_hands_and_thousand_yuan_at_boundary() -> None:
    client = FakeTushareClient(_load_frames())

    bars = _provider(client).daily_bars(
        "003043.SZ",
        date(2026, 8, 19),
        date(2026, 8, 19),
    )

    assert bars == [
        DailyBar(
            symbol="003043.SZ",
            trade_date=date(2026, 8, 19),
            open_fen=6400,
            high_fen=6900,
            low_fen=6350,
            close_fen=6671,
            volume_shares=52_515_277,
            amount_yuan=Decimal("460697377"),
            is_official=True,
            received_at=RECEIVED_AT,
        )
    ]
    assert client.calls == [
        (
            "daily",
            {
                "ts_code": "003043.SZ",
                "start_date": "20260819",
                "end_date": "20260819",
                "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
            },
        )
    ]


def test_tushare_rows_isolate_nulls_and_apply_deterministic_duplicate_policy() -> None:
    frames = _load_frames()
    healthy = frames["rt_min"].iloc[1].copy()
    conflict = frames["rt_min"].iloc[0].copy()
    conflict["close"] = "63.21"
    null_row = frames["rt_min"].iloc[0].copy()
    null_row["ts_code"] = "000001.SZ"
    null_row["vol"] = None
    frames["rt_min"] = pd.DataFrame(
        [
            frames["rt_min"].iloc[0],
            conflict,
            healthy,
            healthy.copy(),
            null_row,
        ],
        columns=frames["rt_min"].columns,
    )
    client = FakeTushareClient(frames)

    bars = _provider(client).realtime_minutes(("003043.SZ", "600000.SH", "000001.SZ"))

    assert [bar.symbol for bar in bars] == ["600000.SH"]
    assert bars[0].volume_shares == 514800


def test_tushare_missing_or_ambiguous_columns_fail_closed() -> None:
    frames = _load_frames()
    frames["rt_min"] = frames["rt_min"].drop(columns="vol")
    client = FakeTushareClient(frames)

    with pytest.raises(TushareProviderError) as missing:
        _provider(client).realtime_minutes(("003043.SZ",))

    assert missing.value.code is TushareErrorCode.INVALID_RESPONSE

    frames = _load_frames()
    frames["rt_min_daily"]["ts_code"] = frames["rt_min_daily"]["code"]
    client = FakeTushareClient(frames)

    with pytest.raises(TushareProviderError) as ambiguous:
        _provider(client).current_day_minutes("003043.SZ")

    assert ambiguous.value.code is TushareErrorCode.INVALID_RESPONSE


def test_tushare_duplicate_required_column_is_an_ambiguous_schema() -> None:
    frames = _load_frames()
    frames["rt_min"] = pd.concat(
        [frames["rt_min"], frames["rt_min"][["vol"]]],
        axis="columns",
    )
    client = FakeTushareClient(frames)

    with pytest.raises(TushareProviderError) as ambiguous:
        _provider(client).realtime_minutes(("003043.SZ",))

    assert ambiguous.value.code is TushareErrorCode.INVALID_RESPONSE


def test_tushare_distinguishes_schema_less_from_typed_empty_frames() -> None:
    frames = _load_frames()
    frames["rt_min"] = pd.DataFrame()
    client = FakeTushareClient(frames)

    with pytest.raises(TushareProviderError) as invalid:
        _provider(client).realtime_minutes(("003043.SZ",))

    assert invalid.value.code is TushareErrorCode.INVALID_RESPONSE

    frames = _load_frames()
    frames["rt_min"] = frames["rt_min"].iloc[0:0]
    client = FakeTushareClient(frames)

    assert _provider(client).realtime_minutes(("003043.SZ",)) == []


def test_tushare_realtime_accepts_ten_symbols_and_rejects_eleven_before_call() -> None:
    ten_symbols = tuple(f"{value:06d}.SZ" for value in range(1, 11))
    frames = _load_frames()
    template = frames["rt_min"].iloc[0].copy()
    rows = []
    for symbol in ten_symbols:
        row = template.copy()
        row["ts_code"] = symbol
        rows.append(row)
    frames["rt_min"] = pd.DataFrame(rows, columns=frames["rt_min"].columns)
    client = FakeTushareClient(frames)

    bars = _provider(client).realtime_minutes(ten_symbols)

    assert [bar.symbol for bar in bars] == list(ten_symbols)
    assert client.calls[0][1]["ts_code"] == ",".join(ten_symbols)
    with pytest.raises(ValueError, match="between one and ten"):
        _provider(client).realtime_minutes((*ten_symbols, "000011.SZ"))
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("frame_name", "missing_column"),
    [
        ("rt_min", "vol"),
        ("rt_min_daily", "amount"),
        ("trade_cal", "pretrade_date"),
        ("stk_limit", "down_limit"),
        ("daily", "close"),
    ],
)
def test_tushare_all_interfaces_reject_missing_required_columns(
    frame_name: str,
    missing_column: str,
) -> None:
    frames = _load_frames()
    frames[frame_name] = frames[frame_name].drop(columns=missing_column)

    with pytest.raises(TushareProviderError) as invalid:
        _invoke_frame_method(_provider(FakeTushareClient(frames)), frame_name)

    assert invalid.value.code is TushareErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "frame_name",
    ["rt_min_daily", "trade_cal", "stk_limit", "daily"],
)
def test_tushare_all_reference_interfaces_accept_typed_empty_frames(
    frame_name: str,
) -> None:
    frames = _load_frames()
    frames[frame_name] = frames[frame_name].iloc[0:0]

    assert _invoke_frame_method(_provider(FakeTushareClient(frames)), frame_name) == []


def test_tushare_rt_min_daily_accepts_only_the_two_documented_symbol_aliases() -> None:
    frames = _load_frames()
    frames["rt_min_daily"] = frames["rt_min_daily"].rename(columns={"code": "ts_code"})
    assert _provider(FakeTushareClient(frames)).current_day_minutes("003043.SZ")

    frames = _load_frames()
    frames["rt_min_daily"] = frames["rt_min_daily"].rename(columns={"code": "symbol"})
    with pytest.raises(TushareProviderError) as unknown:
        _provider(FakeTushareClient(frames)).current_day_minutes("003043.SZ")
    assert unknown.value.code is TushareErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("frequency", "source_time"),
    [
        ("5MIN", "2026-08-20 09:30:00"),
        ("1MIN", "2026-08-19 09:30:00"),
    ],
)
def test_tushare_rt_min_daily_rejects_non_one_minute_or_non_current_rows(
    frequency: str,
    source_time: str,
) -> None:
    frames = _load_frames()
    frames["rt_min_daily"] = frames["rt_min_daily"].iloc[[0]].copy()
    frames["rt_min_daily"].loc[:, "freq"] = frequency
    frames["rt_min_daily"].loc[:, "time"] = source_time

    bars = _provider(
        FakeTushareClient(frames),
        is_open_on=lambda _value: True,
    ).current_day_minutes("003043.SZ")

    assert bars == []


def test_tushare_minute_adapter_wires_end_labels_and_completion_grace() -> None:
    frames = _load_frames()
    frames["rt_min_daily"] = frames["rt_min_daily"].iloc[[0]].copy()
    frames["rt_min_daily"].loc[:, "time"] = "2026-08-20 09:31:00"
    before_grace = datetime(2026, 8, 20, 9, 31, 11, tzinfo=SHANGHAI)
    at_grace = datetime(2026, 8, 20, 9, 31, 12, tzinfo=SHANGHAI)

    assert (
        _provider(
            FakeTushareClient(frames),
            received_at=before_grace,
            source_time_label=SourceTimeLabel.END,
        ).current_day_minutes("003043.SZ")
        == []
    )
    bars = _provider(
        FakeTushareClient(frames),
        received_at=at_grace,
        source_time_label=SourceTimeLabel.END,
    ).current_day_minutes("003043.SZ")
    assert [bar.bar_end for bar in bars] == [datetime(2026, 8, 20, 9, 31, tzinfo=SHANGHAI)]


@pytest.mark.parametrize("open_state", [False, None])
def test_tushare_minute_adapter_fails_closed_for_closed_or_unknown_day(
    open_state: bool | None,
) -> None:
    client = FakeTushareClient(_load_frames())

    bars = _provider(
        client,
        is_open_on=lambda _value: open_state,
    ).realtime_minutes(("003043.SZ",))

    assert bars == []


def test_tushare_decimal_scaling_ignores_ambient_context_precision() -> None:
    frames = _load_frames()
    frames["daily"] = frames["daily"].iloc[[0]].copy()
    frames["daily"].loc[:, "open"] = "123.45"
    frames["daily"].loc[:, "high"] = "123.46"
    frames["daily"].loc[:, "low"] = "123.44"
    frames["daily"].loc[:, "close"] = "123.45"

    with localcontext() as context:
        context.prec = 3
        bars = _provider(FakeTushareClient(frames)).daily_bars(
            "003043.SZ",
            date(2026, 8, 19),
            date(2026, 8, 19),
        )

    assert len(bars) == 1
    assert (bars[0].open_fen, bars[0].high_fen, bars[0].low_fen) == (
        12345,
        12346,
        12344,
    )
    assert bars[0].volume_shares == 52_515_277
    assert bars[0].amount_yuan == Decimal("460697377")


def test_tushare_extreme_decimal_row_cannot_abort_healthy_symbol() -> None:
    frames = _load_frames()
    frames["rt_min"].loc[0, "open"] = "1e999999"
    client = FakeTushareClient(frames)

    bars = _provider(client).realtime_minutes(("003043.SZ", "600000.SH"))

    assert [bar.symbol for bar in bars] == ["600000.SH"]


def test_tushare_overflowing_source_minute_cannot_abort_healthy_symbol() -> None:
    frames = _load_frames()
    frames["rt_min"].loc[0, "time"] = "9999-12-31 23:59:00"
    client = FakeTushareClient(frames)

    bars = _provider(
        client,
        is_open_on=lambda _value: True,
    ).realtime_minutes(("003043.SZ", "600000.SH"))

    assert [bar.symbol for bar in bars] == ["600000.SH"]


@pytest.mark.parametrize("bad_first", [False, True])
def test_tushare_bad_payload_invalidates_every_duplicate_of_the_identity(
    bad_first: bool,
) -> None:
    frames = _load_frames()
    good_minute = frames["rt_min"].iloc[0]
    bad_minute = frames["rt_min"].iloc[0].copy()
    bad_minute["close"] = "not-a-price"
    minute_pair = [bad_minute, good_minute] if bad_first else [good_minute, bad_minute]
    frames["rt_min"] = pd.DataFrame(
        [*minute_pair, frames["rt_min"].iloc[1]],
        columns=frames["rt_min"].columns,
    )
    minute_bars = _provider(FakeTushareClient(frames)).realtime_minutes(("003043.SZ", "600000.SH"))
    assert [bar.symbol for bar in minute_bars] == ["600000.SH"]

    frames = _load_frames()
    good_limit = frames["stk_limit"].iloc[0]
    bad_limit = frames["stk_limit"].iloc[0].copy()
    bad_limit["down_limit"] = "not-a-price"
    limit_pair = [bad_limit, good_limit] if bad_first else [good_limit, bad_limit]
    frames["stk_limit"] = pd.DataFrame(
        [*limit_pair, frames["stk_limit"].iloc[1]],
        columns=frames["stk_limit"].columns,
    )
    limits = _provider(FakeTushareClient(frames)).daily_limits(date(2026, 8, 20))
    assert [limit.symbol for limit in limits] == ["600000.SH"]


@pytest.mark.parametrize("bad_first", [False, True])
def test_tushare_bad_payload_permanently_invalidates_calendar_and_daily_identity(
    bad_first: bool,
) -> None:
    frames = _load_frames()
    good_day = frames["trade_cal"].iloc[0]
    bad_day = good_day.copy()
    bad_day["pretrade_date"] = None
    day_pair = [bad_day, good_day] if bad_first else [good_day, bad_day]
    frames["trade_cal"] = pd.DataFrame(
        [*day_pair, *[frames["trade_cal"].iloc[index] for index in (1, 2)]],
        columns=frames["trade_cal"].columns,
    )
    days = _provider(FakeTushareClient(frames)).trading_calendar(
        date(2026, 8, 19),
        date(2026, 8, 22),
    )
    assert [day.cal_date for day in days] == [date(2026, 8, 20), date(2026, 8, 22)]

    frames = _load_frames()
    good_daily = frames["daily"].iloc[0]
    bad_daily = good_daily.copy()
    bad_daily["amount"] = "not-an-amount"
    healthy_prior = good_daily.copy()
    healthy_prior["trade_date"] = "20260818"
    daily_pair = [bad_daily, good_daily] if bad_first else [good_daily, bad_daily]
    frames["daily"] = pd.DataFrame(
        [*daily_pair, healthy_prior],
        columns=frames["daily"].columns,
    )
    bars = _provider(FakeTushareClient(frames)).daily_bars(
        "003043.SZ",
        date(2026, 8, 18),
        date(2026, 8, 19),
    )
    assert [bar.trade_date for bar in bars] == [date(2026, 8, 18)]
