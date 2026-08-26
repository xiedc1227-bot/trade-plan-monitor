import json
import traceback
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalMinuteProfileUnverifiedError,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import ProviderCapabilities
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider
from trade_plan_monitor.runtime.request_control import TushareOperation

SHANGHAI = ZoneInfo("Asia/Shanghai")
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "market_data" / "tushare_stk_mins_241.json"


class FakeTushareClient:
    def __init__(
        self,
        response: object,
        *,
        calendar_response: object | None = None,
        limit_response: object | None = None,
        daily_response: object | None = None,
    ) -> None:
        self.response = response
        self.calendar_response = calendar_response
        self.limit_response = limit_response
        self.daily_response = daily_response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def stk_mins(self, **kwargs: object) -> object:
        self.calls.append(("stk_mins", kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, pd.DataFrame):
            return self.response.copy(deep=True)
        return self.response

    def trade_cal(self, **kwargs: object) -> object:
        self.calls.append(("trade_cal", kwargs))
        if isinstance(self.calendar_response, pd.DataFrame):
            return self.calendar_response.copy(deep=True)
        return self.calendar_response

    def stk_limit(self, **kwargs: object) -> object:
        self.calls.append(("stk_limit", kwargs))
        if isinstance(self.limit_response, pd.DataFrame):
            return self.limit_response.copy(deep=True)
        return self.limit_response

    def daily(self, **kwargs: object) -> object:
        self.calls.append(("daily", kwargs))
        if isinstance(self.daily_response, pd.DataFrame):
            return self.daily_response.copy(deep=True)
        return self.daily_response


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_frame(*, descending: bool = True) -> pd.DataFrame:
    fixture = _fixture()
    trade_date = date.fromisoformat(fixture["tradeDate"])
    source_times = [
        datetime.combine(
            trade_date,
            time.fromisoformat(fixture["openingSpecialTime"]),
            SHANGHAI,
        )
    ]
    for raw_start, raw_end in fixture["sessionMinuteRanges"]:
        cursor = datetime.combine(trade_date, time.fromisoformat(raw_start), SHANGHAI)
        end = datetime.combine(trade_date, time.fromisoformat(raw_end), SHANGHAI)
        while cursor <= end:
            source_times.append(cursor)
            cursor += timedelta(minutes=1)
    if descending:
        source_times.reverse()
    facts = fixture["facts"]
    rows = [
        {
            "ts_code": fixture["symbol"],
            "trade_time": source_time.strftime("%Y-%m-%d %H:%M:%S"),
            **facts,
        }
        for source_time in source_times
    ]
    assert len(rows) == fixture["expectedRawRows"]
    return pd.DataFrame(rows, columns=fixture["columns"])


def _provider(
    client: FakeTushareClient,
    *,
    profile: HistoricalMinuteProfile = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
) -> TushareHistoricalMinuteProvider:
    return TushareHistoricalMinuteProvider(
        client,
        now=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=SHANGHAI),
        profile=profile,
    )


def _assert_invalid(frame: pd.DataFrame) -> None:
    client = FakeTushareClient(frame)
    with pytest.raises(TushareProviderError) as captured:
        _provider(client).historical_minute_batch("600000.SH", date(2026, 8, 24))
    assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert str(captured.value) == "Tushare stk_mins failed (INVALID_RESPONSE)"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_unverified_historical_profile_fails_before_sdk_call_without_touching_realtime_state() -> (
    None
):
    client = FakeTushareClient(_fixture_frame())
    realtime_before = ProviderCapabilities()

    with pytest.raises(
        HistoricalMinuteProfileUnverifiedError,
        match="historical minute profile is UNVERIFIED",
    ):
        _provider(
            client,
            profile=HistoricalMinuteProfile.UNVERIFIED,
        ).historical_minutes("600000.SH", date(2026, 8, 24))

    assert client.calls == []
    assert ProviderCapabilities() == realtime_before
    assert TushareOperation.HISTORICAL_MINUTES.value == "historical_minutes"


@pytest.mark.parametrize("descending", [False, True])
def test_verified_241_profile_preserves_opening_special_and_returns_240_ordered_minutes(
    descending: bool,
) -> None:
    frame = _fixture_frame(descending=descending)
    frame.insert(0, "ignored_extra", "safe")
    client = FakeTushareClient(frame)
    provider = _provider(client)

    batch = provider.historical_minute_batch("600000.SH", date(2026, 8, 24))

    expected_ends = expected_minute_ends(date(2026, 8, 24), is_open=True)
    assert isinstance(batch, HistoricalMinuteBatch)
    assert batch.contract_version is HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
    assert batch.symbol == "600000.SH"
    assert batch.trade_date == date(2026, 8, 24)
    assert tuple(bar.bar_end for bar in batch.bars) == expected_ends
    assert len(batch.bars) == 240
    assert all(bar.received_at == bar.bar_end + timedelta(seconds=12) for bar in batch.bars)
    assert batch.bars[0].model_dump(mode="python") == {
        "symbol": "600000.SH",
        "bar_end": datetime(2026, 8, 24, 9, 31, tzinfo=SHANGHAI),
        "open_fen": 1001,
        "high_fen": 1005,
        "low_fen": 999,
        "close_fen": 1003,
        "volume_shares": 100,
        "amount_yuan": Decimal("1003.00"),
        "received_at": datetime(2026, 8, 24, 9, 31, 12, tzinfo=SHANGHAI),
    }
    assert isinstance(batch.opening_special, HistoricalOpeningSpecial)
    assert batch.opening_special.model_dump(mode="python") == {
        "symbol": "600000.SH",
        "source_time": datetime(2026, 8, 24, 9, 30, tzinfo=SHANGHAI),
        "open_fen": 1001,
        "high_fen": 1005,
        "low_fen": 999,
        "close_fen": 1003,
        "volume_shares": 100,
        "amount_yuan": Decimal("1003.00"),
    }
    assert all(bar.bar_end.time() != time(13, 0) for bar in batch.bars)
    assert provider.historical_minutes("600000.SH", date(2026, 8, 24)) == batch.bars
    assert client.calls == [
        (
            "stk_mins",
            {
                "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
                "ts_code": "600000.SH",
                "freq": "1min",
                "start_date": "2026-08-24 00:00:00",
                "end_date": "2026-08-24 23:59:59",
            },
        ),
        (
            "stk_mins",
            {
                "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
                "ts_code": "600000.SH",
                "freq": "1min",
                "start_date": "2026-08-24 00:00:00",
                "end_date": "2026-08-24 23:59:59",
            },
        ),
    ]


def test_historical_reference_methods_return_immutable_tuples() -> None:
    class ReferenceProvider:
        def trading_calendar_for_exchange(
            self,
            exchange: str,
            start: date,
            end: date,
        ) -> list[object]:
            assert (start, end) == (date(2026, 8, 24), date(2026, 8, 25))
            assert exchange == "SZSE"
            return []

        def daily_limits(self, trade_date: date) -> list[object]:
            assert trade_date == date(2026, 8, 24)
            return []

        def daily_bars(self, symbol: str, start: date, end: date) -> list[object]:
            assert (symbol, start, end) == (
                "600000.SH",
                date(2026, 8, 1),
                date(2026, 8, 24),
            )
            return []

    provider = TushareHistoricalMinuteProvider(
        FakeTushareClient(_fixture_frame()),
        now=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=SHANGHAI),
        profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        reference_provider=ReferenceProvider(),  # type: ignore[arg-type]
    )

    assert provider.trading_calendar("SZSE", date(2026, 8, 24), date(2026, 8, 25)) == ()
    assert provider.daily_limits(date(2026, 8, 24)) == ()
    assert provider.daily_bars("600000.SH", date(2026, 8, 1), date(2026, 8, 24)) == ()


def test_historical_reference_provider_requires_explicit_exchange_calendar() -> None:
    class LegacyReferenceProvider:
        def trading_calendar(self, start: date, end: date) -> list[object]:
            del start, end
            return []

        def daily_limits(self, trade_date: date) -> list[object]:
            del trade_date
            return []

        def daily_bars(self, symbol: str, start: date, end: date) -> list[object]:
            del symbol, start, end
            return []

    with pytest.raises(TypeError, match="historical reference methods"):
        TushareHistoricalMinuteProvider(
            FakeTushareClient(_fixture_frame()),
            now=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=SHANGHAI),
            profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
            reference_provider=LegacyReferenceProvider(),  # type: ignore[arg-type]
        )


def test_historical_calendar_requests_the_explicit_exchange() -> None:
    calendar = pd.DataFrame(
        (
            {
                "exchange": "SZSE",
                "cal_date": "20260824",
                "is_open": "1",
                "pretrade_date": "20260821",
            },
        )
    )
    client = FakeTushareClient(_fixture_frame(), calendar_response=calendar)

    values = _provider(client).trading_calendar(
        "SZSE",
        date(2026, 8, 24),
        date(2026, 8, 24),
    )

    assert len(values) == 1
    assert values[0].exchange == "SZSE"
    assert client.calls[-1] == (
        "trade_cal",
        {
            "fields": "exchange,cal_date,is_open,pretrade_date",
            "exchange": "SZSE",
            "start_date": "20260824",
            "end_date": "20260824",
        },
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORICAL_CALENDAR:BSE"):
        _provider(client).trading_calendar(
            "BSE",
            date(2026, 8, 24),
            date(2026, 8, 24),
        )


@pytest.mark.parametrize("anomaly", ["duplicate", "wrong-exchange", "bad-extra-row"])
def test_real_historical_calendar_adapter_rejects_ambiguous_raw_rows(anomaly: str) -> None:
    row = {
        "exchange": "SSE",
        "cal_date": "20260824",
        "is_open": "1",
        "pretrade_date": "20260821",
    }
    rows = [row]
    if anomaly == "duplicate":
        rows.append(dict(row))
    elif anomaly == "wrong-exchange":
        rows.append({**row, "exchange": "SZSE"})
    else:
        rows.append({**row, "cal_date": "not-a-date"})
    client = FakeTushareClient(
        _fixture_frame(),
        calendar_response=pd.DataFrame(rows),
    )

    with pytest.raises(TushareProviderError) as captured:
        _provider(client).trading_calendar(
            "SSE",
            date(2026, 8, 24),
            date(2026, 8, 24),
        )

    assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert str(captured.value) == "Tushare trade_cal failed (INVALID_RESPONSE)"


@pytest.mark.parametrize("surface", ["daily", "stk_limit"])
def test_real_historical_reference_adapter_rejects_duplicate_raw_identity(
    surface: str,
) -> None:
    daily_row = {
        "ts_code": "600000.SH",
        "trade_date": "20260824",
        "open": "10.00",
        "high": "10.10",
        "low": "9.90",
        "close": "10.05",
        "vol": "1000.00",
        "amount": "10.00",
    }
    limit_row = {
        "trade_date": "20260824",
        "ts_code": "600000.SH",
        "up_limit": "11.00",
        "down_limit": "9.00",
    }
    client = FakeTushareClient(
        _fixture_frame(),
        daily_response=pd.DataFrame((daily_row, dict(daily_row))),
        limit_response=pd.DataFrame((limit_row, dict(limit_row))),
    )
    provider = _provider(client)

    with pytest.raises(TushareProviderError) as captured:
        if surface == "daily":
            provider.daily_bars(
                "600000.SH",
                date(2026, 8, 24),
                date(2026, 8, 24),
            )
        else:
            provider.daily_limits(date(2026, 8, 24))

    assert captured.value.code is TushareErrorCode.INVALID_RESPONSE
    assert str(captured.value) == f"Tushare {surface} failed (INVALID_RESPONSE)"


def test_historical_schema_requires_each_expected_column_exactly_once() -> None:
    missing = _fixture_frame().drop(columns=["amount"])
    _assert_invalid(missing)

    duplicated = _fixture_frame()
    duplicated.insert(len(duplicated.columns), "amount_copy", duplicated["amount"])
    duplicated.columns = [*duplicated.columns[:-1], "amount"]
    _assert_invalid(duplicated)

    _assert_invalid(pd.DataFrame())


def _mutate_frame(mutator: Callable[[pd.DataFrame], None]) -> pd.DataFrame:
    frame = _fixture_frame(descending=False)
    mutator(frame)
    return frame


@pytest.mark.parametrize(
    "frame",
    [
        _fixture_frame(descending=False).iloc[:-1].copy(),
        pd.concat(
            [_fixture_frame(descending=False), _fixture_frame(descending=False).iloc[[0]]],
            ignore_index=True,
        ),
        _mutate_frame(lambda frame: frame.__setitem__("close", None)),
        _mutate_frame(lambda frame: frame.__setitem__("high", "9.00")),
        _mutate_frame(lambda frame: frame.__setitem__("vol", -1)),
        _mutate_frame(lambda frame: frame.__setitem__("amount", "-0.01")),
        _mutate_frame(lambda frame: frame.__setitem__("amount", "1E+1000000000")),
        _mutate_frame(lambda frame: frame.__setitem__("ts_code", "000001.SZ")),
        _mutate_frame(
            lambda frame: frame.__setitem__(
                "trade_time",
                frame["trade_time"].str.replace("2026-08-24", "2026-08-25"),
            )
        ),
        _mutate_frame(
            lambda frame: frame.__setitem__(
                "trade_time",
                frame["trade_time"].where(
                    frame.index != 151,
                    "2026-08-24 13:00:00",
                ),
            )
        ),
        _mutate_frame(
            lambda frame: frame.__setitem__(
                "trade_time",
                frame["trade_time"].where(
                    frame.index != 10,
                    "2026-08-24 09:40:00.000001",
                ),
            )
        ),
    ],
    ids=(
        "missing-row",
        "duplicate-row",
        "null",
        "invalid-ohlc",
        "negative-volume",
        "negative-amount",
        "oversized-amount-exponent",
        "wrong-symbol",
        "wrong-date",
        "extra-1300",
        "sub-minute",
    ),
)
def test_historical_rows_fail_closed_as_one_response(frame: pd.DataFrame) -> None:
    _assert_invalid(frame)


def test_historical_rejects_arbitrary_row_order_and_conflicting_duplicate() -> None:
    unordered = _fixture_frame(descending=False)
    unordered.iloc[[10, 11]] = unordered.iloc[[11, 10]].to_numpy()
    _assert_invalid(unordered)

    conflict = _fixture_frame(descending=False)
    duplicate = conflict.iloc[[10]].copy()
    duplicate.loc[:, "close"] = "10.04"
    conflict = pd.concat([conflict, duplicate], ignore_index=True)
    _assert_invalid(conflict)


def test_historical_provider_error_is_stable_and_drops_raw_context() -> None:
    token = "FAKE_HISTORICAL_TOKEN_DO_NOT_USE"
    client = FakeTushareClient(RuntimeError(f"403 permission denied token={token}"))

    with pytest.raises(TushareProviderError) as captured:
        _provider(client).historical_minutes("600000.SH", date(2026, 8, 24))

    assert captured.value.code is TushareErrorCode.BLOCKED_PERMISSION
    assert str(captured.value) == "Tushare stk_mins failed (BLOCKED_PERMISSION)"
    surfaces = "\n".join(
        (
            str(captured.value),
            repr(captured.value),
            repr(vars(captured.value)),
            "".join(traceback.format_exception(captured.value)),
        )
    )
    assert token not in surfaces
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("symbol", "trade_date"),
    [
        ("60000.SH", date(2026, 8, 24)),
        ("600000.SH", datetime(2026, 8, 24, tzinfo=SHANGHAI)),
        ("600000.SH", date(2026, 8, 23)),
    ],
)
def test_historical_request_identity_fails_before_sdk_call(
    symbol: str,
    trade_date: date,
) -> None:
    client = FakeTushareClient(_fixture_frame())

    with pytest.raises((TypeError, ValueError, TushareProviderError)):
        _provider(client).historical_minutes(symbol, trade_date)

    assert client.calls == []
