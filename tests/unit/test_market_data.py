import traceback
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from inspect import Parameter, signature
from typing import Protocol, get_type_hints
from zoneinfo import ZoneInfo

import pytest
from pandas import DataFrame, Timestamp
from pydantic import ValidationError
from requests import Response
from requests.exceptions import HTTPError, Timeout

from trade_plan_monitor.market_data.aggregation import (
    TA_FORMULA_VERSION,
    FiveMinuteBar,
    aggregate_five_minute_bar,
    aggregate_provisional_daily_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
    is_complete_five_minute_bucket,
)
from trade_plan_monitor.market_data.models import (
    DailyBar,
    DailyLimit,
    MinuteBar,
    ProviderCapabilities,
    ProviderCapabilityStatus,
    TradingDay,
)
from trade_plan_monitor.market_data.provider import MarketDataProvider
from trade_plan_monitor.market_data.reconciliation import (
    CloseReconciliationStatus,
    reconcile_daily_close,
)
from trade_plan_monitor.market_data.sessions import (
    DEFAULT_DATA_GRACE,
    SourceTimeLabel,
    SourceTimeMappingUnverifiedError,
    TradingSession,
    expected_minute_ends,
    is_minute_usable,
    normalize_source_minute,
    session_for_minute_end,
)
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _shanghai_time(hour: int, minute: int, *, day: int = 19) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=SHANGHAI)


def _minute_bar_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "003043.SZ",
        "bar_end": _shanghai_time(9, 31),
        "open_fen": 6400,
        "high_fen": 6450,
        "low_fen": 6380,
        "close_fen": 6430,
        "volume_shares": 125_600,
        "amount_yuan": Decimal("8079200.50"),
        "received_at": _shanghai_time(9, 31) + timedelta(seconds=12),
    }
    payload.update(overrides)
    return payload


def _daily_bar_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "003043.SZ",
        "trade_date": date(2026, 8, 19),
        "open_fen": 6400,
        "high_fen": 6900,
        "low_fen": 6350,
        "close_fen": 6671,
        "volume_shares": 52_515_277,
        "amount_yuan": Decimal("460697377"),
        "is_official": False,
        "received_at": _shanghai_time(15, 0),
    }
    payload.update(overrides)
    return payload


def _provisional_minute(bar_end: datetime, index: int = 0) -> MinuteBar:
    return MinuteBar(
        symbol="003043.SZ",
        bar_end=bar_end,
        open_fen=6400 + index,
        high_fen=6450 + index,
        low_fen=6380 - index,
        close_fen=6430 + index,
        volume_shares=100 + index,
        amount_yuan=Decimal("10.25") + index,
        received_at=bar_end + timedelta(seconds=12 + index),
    )


def _daily_bar(**overrides: object) -> DailyBar:
    return DailyBar.model_validate(_daily_bar_payload(**overrides))


def test_market_reconcile_15_00_provisional_close_remains_pending() -> None:
    provisional = _daily_bar()

    intent = reconcile_daily_close(
        symbol=provisional.symbol,
        current_trade_date=provisional.trade_date,
        daily_bars=(provisional,),
    )

    assert intent.status is CloseReconciliationStatus.CLOSE_PENDING
    assert intent.advance_close_risk is False
    assert intent.provisional_bar == provisional
    assert intent.official_bar is None
    assert intent.close_delta_fen is None


@pytest.mark.parametrize(
    ("official_close_fen", "expected_delta"),
    [(6_671, 0), (6_680, 9)],
)
def test_market_reconcile_current_official_close_matches_or_replaces_provisional(
    official_close_fen: int,
    expected_delta: int,
) -> None:
    provisional = _daily_bar()
    official = _daily_bar(
        close_fen=official_close_fen,
        is_official=True,
        received_at=_shanghai_time(15, 20),
    )

    forward = reconcile_daily_close(
        symbol=provisional.symbol,
        current_trade_date=provisional.trade_date,
        daily_bars=(provisional, official),
    )
    reordered = reconcile_daily_close(
        symbol=provisional.symbol,
        current_trade_date=provisional.trade_date,
        daily_bars=(official, provisional),
    )

    assert forward == reordered
    assert forward.status is CloseReconciliationStatus.OFFICIAL_READY
    assert forward.advance_close_risk is True
    assert forward.provisional_bar == provisional
    assert forward.official_bar == official
    assert forward.close_delta_fen == expected_delta
    assert forward.official_bar.is_official is True


def test_market_reconcile_delayed_or_official_only_close_is_deterministic() -> None:
    trade_date = date(2026, 8, 19)
    pending = reconcile_daily_close(
        symbol="003043.SZ",
        current_trade_date=trade_date,
        daily_bars=(),
    )
    official = _daily_bar(
        is_official=True,
        received_at=_shanghai_time(17, 0),
    )
    ready = reconcile_daily_close(
        symbol="003043.SZ",
        current_trade_date=trade_date,
        daily_bars=(official,),
    )

    assert pending.status is CloseReconciliationStatus.CLOSE_PENDING
    assert pending.advance_close_risk is False
    assert ready.status is CloseReconciliationStatus.OFFICIAL_READY
    assert ready.advance_close_risk is True
    assert ready.provisional_bar is None
    assert ready.official_bar == official
    assert ready.close_delta_fen is None
    assert ready == reconcile_daily_close(
        symbol="003043.SZ",
        current_trade_date=trade_date,
        daily_bars=(official,),
    )


def test_market_reconcile_rejects_wrong_date_symbol_shape_or_duplicate_provenance() -> None:
    provisional = _daily_bar()
    wrong_date = _daily_bar(
        trade_date=date(2026, 8, 18),
        received_at=_shanghai_time(15, 0, day=18),
    )
    wrong_symbol = _daily_bar(symbol="600519.SH")

    for bars in ((wrong_date,), (wrong_symbol,)):
        with pytest.raises(ValueError, match="current trading date|symbol"):
            reconcile_daily_close(
                symbol=provisional.symbol,
                current_trade_date=provisional.trade_date,
                daily_bars=bars,
            )

    with pytest.raises(TypeError, match="tuple"):
        reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=[provisional],  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="DailyBar"):
        reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=(object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="at most 2"):
        reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=(provisional, provisional, provisional),
        )
    with pytest.raises(ValueError, match="one provisional"):
        reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=(provisional, provisional),
        )


def test_market_reconcile_intent_is_closed_immutable_and_revalidates_copy() -> None:
    provisional = _daily_bar()
    pending = reconcile_daily_close(
        symbol=provisional.symbol,
        current_trade_date=provisional.trade_date,
        daily_bars=(provisional,),
    )

    with pytest.raises(ValidationError):
        pending.advance_close_risk = True  # type: ignore[misc]
    with pytest.raises(ValidationError):
        pending.model_copy(update={"advance_close_risk": True})
    with pytest.raises(ValidationError):
        pending.model_copy(update={"official_bar": provisional})


def test_market_models_minute_bar_preserves_normalized_units() -> None:
    bar = MinuteBar.model_validate(_minute_bar_payload())

    assert bar.symbol == "003043.SZ"
    assert (bar.open_fen, bar.high_fen, bar.low_fen, bar.close_fen) == (
        6400,
        6450,
        6380,
        6430,
    )
    assert bar.volume_shares == 125_600
    assert bar.amount_yuan == Decimal("8079200.50")
    assert bar.bar_end.tzinfo is SHANGHAI


def test_market_models_preserve_source_and_receipt_facts_for_persistence() -> None:
    bar = MinuteBar.model_validate(_minute_bar_payload())
    persistence_facts = bar.model_dump(mode="python")

    assert persistence_facts["bar_end"] == _shanghai_time(9, 31)
    assert persistence_facts["received_at"] == _shanghai_time(9, 31) + timedelta(seconds=12)
    assert persistence_facts["volume_shares"] == 125_600
    assert persistence_facts["amount_yuan"] == Decimal("8079200.50")


def test_market_models_are_closed_and_immutable() -> None:
    bar = MinuteBar.model_validate(_minute_bar_payload())

    with pytest.raises(ValidationError, match="frozen"):
        bar.close_fen = 6440
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MinuteBar.model_validate({**_minute_bar_payload(), "raw_payload": "unsafe"})


@pytest.mark.parametrize(
    "update",
    [
        {"symbol": "invalid"},
        {"close_fen": -1},
        {"close_fen": 6500},
    ],
)
def test_market_models_revalidate_public_copy_updates(update: dict[str, object]) -> None:
    bar = MinuteBar.model_validate(_minute_bar_payload())

    with pytest.raises(ValidationError):
        bar.model_copy(update=update)


def test_market_models_accept_valid_public_copy_updates() -> None:
    bar = MinuteBar.model_validate(_minute_bar_payload())

    copied = bar.model_copy(update={"close_fen": 6420})

    assert copied.close_fen == 6420
    assert bar.close_fen == 6430


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"low_fen": 6460}, "low_fen"),
        ({"high_fen": 6370}, "high_fen"),
        ({"open_fen": 6370}, "open_fen"),
        ({"open_fen": 6460}, "open_fen"),
        ({"close_fen": 6370}, "close_fen"),
        ({"close_fen": 6460}, "close_fen"),
    ],
)
def test_market_models_reject_malformed_minute_ohlc(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        MinuteBar.model_validate(_minute_bar_payload(**overrides))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_fen", 64.0),
        ("high_fen", "6450"),
        ("low_fen", True),
        ("close_fen", Decimal("6430")),
        ("volume_shares", 125_600.0),
        ("amount_yuan", 8_079_200.50),
    ],
)
def test_market_models_require_exact_normalized_numeric_types(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        MinuteBar.model_validate(_minute_bar_payload(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume_shares", -1),
        ("amount_yuan", Decimal("-0.01")),
        ("amount_yuan", Decimal("NaN")),
        ("amount_yuan", Decimal("Infinity")),
    ],
)
def test_market_models_reject_negative_or_nonfinite_activity(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        MinuteBar.model_validate(_minute_bar_payload(**{field: value}))


@pytest.mark.parametrize(
    "symbol",
    ["003043", "003043.sz", "SZ.003043", "003043.HK", "003043.SZ OR 1=1", " 003043.SZ "],
)
def test_market_models_reject_invalid_a_share_symbols(symbol: str) -> None:
    with pytest.raises(ValidationError):
        MinuteBar.model_validate(_minute_bar_payload(symbol=symbol))


@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        datetime(2026, 8, 19, 9, 31),
        datetime(2026, 8, 19, 1, 31, tzinfo=UTC),
    ],
)
def test_market_models_reject_naive_or_non_shanghai_timestamps(
    invalid_timestamp: datetime,
) -> None:
    with pytest.raises(ValidationError, match="Asia/Shanghai|timezone"):
        MinuteBar.model_validate(_minute_bar_payload(bar_end=invalid_timestamp))
    with pytest.raises(ValidationError, match="Asia/Shanghai|timezone"):
        MinuteBar.model_validate(_minute_bar_payload(received_at=invalid_timestamp))


def test_market_models_normalize_shanghai_offset_and_round_trip_json() -> None:
    fixed_shanghai_offset = timezone(timedelta(hours=8))
    bar = MinuteBar.model_validate(
        _minute_bar_payload(
            bar_end=datetime(2026, 8, 19, 9, 31, tzinfo=fixed_shanghai_offset),
            received_at=datetime(2026, 8, 19, 9, 31, 12, tzinfo=fixed_shanghai_offset),
        )
    )

    restored = MinuteBar.model_validate_json(bar.model_dump_json())

    assert isinstance(bar.bar_end.tzinfo, ZoneInfo)
    assert bar.bar_end.tzinfo.key == "Asia/Shanghai"
    assert restored == bar


def test_market_models_reject_minute_received_before_bar_end() -> None:
    with pytest.raises(ValidationError, match="received_at"):
        MinuteBar.model_validate(_minute_bar_payload(received_at=_shanghai_time(9, 30, day=19)))


def test_market_models_trading_day_preserves_exchange_calendar_contract() -> None:
    trading_day = TradingDay(
        exchange="SSE",
        cal_date=date(2026, 8, 19),
        is_open=True,
        previous_trade_date=date(2026, 8, 18),
    )

    assert trading_day.exchange == "SSE"
    assert trading_day.cal_date == date(2026, 8, 19)
    assert trading_day.is_open is True
    assert trading_day.previous_trade_date == date(2026, 8, 18)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "exchange": "NYSE",
            "cal_date": date(2026, 8, 19),
            "is_open": True,
            "previous_trade_date": date(2026, 8, 18),
        },
        {
            "exchange": "SZSE",
            "cal_date": date(2026, 8, 19),
            "is_open": 1,
            "previous_trade_date": date(2026, 8, 18),
        },
        {
            "exchange": "SZSE",
            "cal_date": date(2026, 8, 19),
            "is_open": False,
            "previous_trade_date": date(2026, 8, 19),
        },
    ],
)
def test_market_models_reject_invalid_trading_days(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TradingDay.model_validate(payload)


def test_market_models_daily_limit_uses_actual_integer_fen_prices() -> None:
    price_limit = DailyLimit(
        symbol="003043.SZ",
        trade_date=date(2026, 8, 19),
        up_limit_fen=7338,
        down_limit_fen=6004,
        received_at=_shanghai_time(8, 40),
    )

    assert price_limit.up_limit_fen == 7338
    assert price_limit.down_limit_fen == 6004


@pytest.mark.parametrize(
    "payload",
    [
        {"up_limit_fen": 6004, "down_limit_fen": 6004},
        {"up_limit_fen": 6003, "down_limit_fen": 6004},
        {"up_limit_fen": 7338.0, "down_limit_fen": 6004},
        {"up_limit_fen": 7338, "down_limit_fen": -1},
    ],
)
def test_market_models_reject_invalid_daily_limits(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DailyLimit.model_validate(
            {
                "symbol": "003043.SZ",
                "trade_date": date(2026, 8, 19),
                "received_at": _shanghai_time(8, 40),
                **payload,
            }
        )


def test_market_models_reject_daily_limit_received_before_trade_date() -> None:
    with pytest.raises(ValidationError, match="received_at"):
        DailyLimit(
            symbol="003043.SZ",
            trade_date=date(2026, 8, 19),
            up_limit_fen=7338,
            down_limit_fen=6004,
            received_at=_shanghai_time(8, 40, day=18),
        )


def test_market_models_daily_bar_distinguishes_provisional_and_official() -> None:
    provisional = DailyBar.model_validate(_daily_bar_payload(is_official=False))
    official = DailyBar.model_validate(
        _daily_bar_payload(is_official=True, received_at=_shanghai_time(16, 0))
    )

    assert provisional.is_official is False
    assert official.is_official is True
    assert official.volume_shares == 52_515_277
    assert official.amount_yuan == Decimal("460697377")
    assert official.trade_date == provisional.trade_date


@pytest.mark.parametrize(
    "overrides",
    [
        {"low_fen": 7000},
        {"close_fen": 7000},
        {"volume_shares": -1},
        {"amount_yuan": Decimal("-1")},
        {"is_official": 1},
        {"trade_date": "20260819"},
    ],
)
def test_market_models_reject_invalid_daily_bars(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DailyBar.model_validate(_daily_bar_payload(**overrides))


def test_market_models_reject_daily_bar_received_before_trade_date() -> None:
    with pytest.raises(ValidationError, match="received_at"):
        DailyBar.model_validate(_daily_bar_payload(received_at=_shanghai_time(15, 0, day=18)))


def test_market_models_provider_capabilities_fail_closed_by_default() -> None:
    capabilities = ProviderCapabilities()

    assert capabilities.realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.current_day_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.trading_calendar is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.daily_limits is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.daily_bars is ProviderCapabilityStatus.UNVERIFIED


def test_market_models_provider_capabilities_are_independent_and_closed() -> None:
    capabilities = ProviderCapabilities(
        realtime_minutes="READY",
        current_day_minutes="BLOCKED_PERMISSION",
        trading_calendar="RATE_LIMITED",
        daily_limits="ERROR",
        daily_bars="UNVERIFIED",
    )

    assert capabilities.realtime_minutes is ProviderCapabilityStatus.READY
    assert capabilities.current_day_minutes is ProviderCapabilityStatus.BLOCKED_PERMISSION
    assert capabilities.trading_calendar is ProviderCapabilityStatus.RATE_LIMITED
    assert capabilities.daily_limits is ProviderCapabilityStatus.ERROR
    with pytest.raises(ValidationError):
        ProviderCapabilities(realtime_minutes="AVAILABLE")


def test_market_models_provider_protocol_matches_approved_contract() -> None:
    expected_annotations = {
        "probe_capabilities": {"return": ProviderCapabilities},
        "realtime_minutes": {"symbols": tuple[str, ...], "return": list[MinuteBar]},
        "current_day_minutes": {"symbol": str, "return": list[MinuteBar]},
        "trading_calendar": {
            "start": date,
            "end": date,
            "return": list[TradingDay],
        },
        "daily_limits": {"trade_date": date, "return": list[DailyLimit]},
        "daily_bars": {
            "symbol": str,
            "start": date,
            "end": date,
            "return": list[DailyBar],
        },
    }

    public_methods = {
        name
        for name, value in vars(MarketDataProvider).items()
        if not name.startswith("_") and callable(value)
    }
    assert MarketDataProvider.__bases__ == (Protocol,)
    assert getattr(MarketDataProvider, "_is_protocol", False) is True
    assert public_methods == set(expected_annotations)

    for method_name, annotations in expected_annotations.items():
        method = getattr(MarketDataProvider, method_name)
        parameters = tuple(signature(method).parameters.values())
        assert parameters[0].name == "self"
        assert all(item.kind is Parameter.POSITIONAL_OR_KEYWORD for item in parameters)
        assert all(item.default is Parameter.empty for item in parameters)
        assert get_type_hints(method) == annotations


def test_market_session_expected_minutes_cover_only_monitoring_intervals() -> None:
    minute_ends = expected_minute_ends(date(2026, 8, 19), is_open=True)

    assert len(minute_ends) == 240
    assert minute_ends[:2] == (_shanghai_time(9, 31), _shanghai_time(9, 32))
    assert minute_ends[119:122] == (
        _shanghai_time(11, 30),
        _shanghai_time(13, 1),
        _shanghai_time(13, 2),
    )
    assert minute_ends[-1] == _shanghai_time(15, 0)
    assert _shanghai_time(9, 25) not in minute_ends
    assert _shanghai_time(9, 30) not in minute_ends
    assert _shanghai_time(13, 0) not in minute_ends
    assert all(item.tzinfo is SHANGHAI for item in minute_ends)


@pytest.mark.parametrize(
    ("trade_date", "is_open"),
    [
        (date(2026, 8, 22), True),
        (date(2026, 8, 23), True),
        (date(2026, 8, 20), False),
        (date(2026, 8, 20), None),
    ],
)
def test_market_session_weekends_holidays_and_unknown_days_fail_closed(
    trade_date: date,
    is_open: bool | None,
) -> None:
    assert expected_minute_ends(trade_date, is_open=is_open) == ()


@pytest.mark.parametrize(
    ("bar_end", "expected"),
    [
        (_shanghai_time(9, 31), TradingSession.MORNING),
        (_shanghai_time(11, 30), TradingSession.MORNING),
        (_shanghai_time(13, 1), TradingSession.AFTERNOON),
        (_shanghai_time(15, 0), TradingSession.AFTERNOON),
        (_shanghai_time(9, 25), None),
        (_shanghai_time(9, 30), None),
        (_shanghai_time(11, 31), None),
        (_shanghai_time(12, 0), None),
        (_shanghai_time(13, 0), None),
        (_shanghai_time(15, 1), None),
    ],
)
def test_market_session_classifies_canonical_bar_ends(
    bar_end: datetime,
    expected: TradingSession | None,
) -> None:
    assert session_for_minute_end(bar_end) is expected


@pytest.mark.parametrize(
    ("source_time", "label", "expected"),
    [
        (_shanghai_time(9, 30), SourceTimeLabel.START, _shanghai_time(9, 31)),
        (_shanghai_time(9, 31), SourceTimeLabel.END, _shanghai_time(9, 31)),
        (_shanghai_time(14, 59), SourceTimeLabel.START, _shanghai_time(15, 0)),
        (_shanghai_time(15, 0), SourceTimeLabel.END, _shanghai_time(15, 0)),
    ],
)
def test_market_timestamp_normalizes_explicit_start_or_end_labels(
    source_time: datetime,
    label: SourceTimeLabel,
    expected: datetime,
) -> None:
    assert normalize_source_minute(source_time, label=label, is_open=True) == expected


def test_market_timestamp_unverified_label_mapping_fails_closed() -> None:
    with pytest.raises(SourceTimeMappingUnverifiedError, match="UNVERIFIED"):
        normalize_source_minute(
            _shanghai_time(9, 31),
            label=SourceTimeLabel.UNVERIFIED,
            is_open=None,
        )


@pytest.mark.parametrize(
    ("source_time", "label"),
    [
        (_shanghai_time(9, 25), SourceTimeLabel.START),
        (_shanghai_time(9, 25), SourceTimeLabel.END),
        (_shanghai_time(11, 30), SourceTimeLabel.START),
        (_shanghai_time(12, 0), SourceTimeLabel.END),
        (_shanghai_time(13, 0), SourceTimeLabel.END),
        (_shanghai_time(15, 0), SourceTimeLabel.START),
    ],
)
def test_market_timestamp_rejects_labels_outside_one_monitoring_session(
    source_time: datetime,
    label: SourceTimeLabel,
) -> None:
    with pytest.raises(ValueError, match="monitoring session"):
        normalize_source_minute(source_time, label=label, is_open=True)


def test_market_timestamp_normalizes_fixed_shanghai_offset() -> None:
    fixed_shanghai_offset = timezone(timedelta(hours=8))
    normalized = normalize_source_minute(
        datetime(2026, 8, 19, 9, 30, tzinfo=fixed_shanghai_offset),
        label=SourceTimeLabel.START,
        is_open=True,
    )

    assert normalized == _shanghai_time(9, 31)
    assert normalized.tzinfo is SHANGHAI


@pytest.mark.parametrize(
    "source_time",
    [
        datetime(2026, 8, 19, 9, 30),
        datetime(2026, 8, 19, 1, 30, tzinfo=UTC),
        _shanghai_time(9, 30).replace(second=1),
        Timestamp("2026-08-19T09:30:00.000000001+08:00"),
    ],
)
def test_market_timestamp_rejects_noncanonical_source_times(source_time: datetime) -> None:
    with pytest.raises(ValueError, match="Asia/Shanghai|whole minute"):
        normalize_source_minute(source_time, label=SourceTimeLabel.START, is_open=True)


@pytest.mark.parametrize(
    ("source_time", "is_open"),
    [
        (_shanghai_time(9, 30, day=22), True),
        (_shanghai_time(9, 30), False),
        (_shanghai_time(9, 30), None),
    ],
)
def test_market_timestamp_closed_or_unknown_trading_day_fails_closed(
    source_time: datetime,
    is_open: bool | None,
) -> None:
    with pytest.raises(ValueError, match="closed or unknown"):
        normalize_source_minute(
            source_time,
            label=SourceTimeLabel.START,
            is_open=is_open,
        )


def test_market_session_applies_default_twelve_second_grace() -> None:
    bar_end = _shanghai_time(9, 31)

    assert DEFAULT_DATA_GRACE == timedelta(seconds=12)
    assert (
        is_minute_usable(
            bar_end,
            as_of=bar_end + timedelta(seconds=11),
            is_open=True,
        )
        is False
    )
    assert (
        is_minute_usable(
            bar_end,
            as_of=bar_end + DEFAULT_DATA_GRACE,
            is_open=True,
        )
        is True
    )


def test_market_session_grace_is_configurable_and_fails_closed_outside_session() -> None:
    bar_end = _shanghai_time(9, 31)

    assert (
        is_minute_usable(
            bar_end,
            as_of=bar_end + timedelta(seconds=5),
            is_open=True,
            grace=timedelta(seconds=5),
        )
        is True
    )
    assert (
        is_minute_usable(
            _shanghai_time(12, 0),
            as_of=_shanghai_time(12, 1),
            is_open=True,
        )
        is False
    )
    with pytest.raises(ValueError, match="grace"):
        is_minute_usable(
            bar_end,
            as_of=bar_end + timedelta(seconds=12),
            is_open=True,
            grace=timedelta(seconds=-1),
        )


@pytest.mark.parametrize(
    ("bar_end", "is_open"),
    [
        (_shanghai_time(9, 31, day=22), True),
        (_shanghai_time(9, 31), False),
        (_shanghai_time(9, 31), None),
    ],
)
def test_market_session_minute_usability_requires_open_trading_day(
    bar_end: datetime,
    is_open: bool | None,
) -> None:
    assert (
        is_minute_usable(
            bar_end,
            as_of=bar_end + DEFAULT_DATA_GRACE,
            is_open=is_open,
        )
        is False
    )


@pytest.mark.parametrize(
    ("minute_end", "expected_bucket_end"),
    [
        (_shanghai_time(9, 31), _shanghai_time(9, 35)),
        (_shanghai_time(9, 35), _shanghai_time(9, 35)),
        (_shanghai_time(9, 36), _shanghai_time(9, 40)),
        (_shanghai_time(11, 30), _shanghai_time(11, 30)),
        (_shanghai_time(13, 1), _shanghai_time(13, 5)),
        (_shanghai_time(14, 59), _shanghai_time(15, 0)),
        (_shanghai_time(15, 0), _shanghai_time(15, 0)),
    ],
)
def test_market_complete_bucket_uses_session_relative_five_minute_boundaries(
    minute_end: datetime,
    expected_bucket_end: datetime,
) -> None:
    assert five_minute_bucket_end(minute_end) == expected_bucket_end


def test_market_complete_bucket_expected_minutes_never_cross_lunch() -> None:
    assert expected_five_minute_ends(_shanghai_time(11, 30)) == tuple(
        _shanghai_time(11, minute) for minute in range(26, 31)
    )
    assert expected_five_minute_ends(_shanghai_time(13, 5)) == tuple(
        _shanghai_time(13, minute) for minute in range(1, 6)
    )


@pytest.mark.parametrize(
    "minute_end",
    [
        _shanghai_time(9, 25),
        _shanghai_time(9, 30),
        _shanghai_time(12, 0),
        _shanghai_time(13, 0),
        _shanghai_time(15, 1),
    ],
)
def test_market_complete_bucket_rejects_non_session_minutes(minute_end: datetime) -> None:
    with pytest.raises(ValueError, match="monitoring session"):
        five_minute_bucket_end(minute_end)


@pytest.mark.parametrize(
    "bucket_end",
    [_shanghai_time(9, 34), _shanghai_time(11, 29), _shanghai_time(13, 4)],
)
def test_market_complete_bucket_rejects_non_boundary_end(bucket_end: datetime) -> None:
    with pytest.raises(ValueError, match="five-minute boundary"):
        expected_five_minute_ends(bucket_end)


def test_market_complete_bucket_accepts_all_five_minutes_in_any_order() -> None:
    bucket_end = _shanghai_time(9, 35)
    minute_ends = tuple(reversed(expected_five_minute_ends(bucket_end)))

    assert (
        is_complete_five_minute_bucket(
            minute_ends,
            bucket_end=bucket_end,
            is_open=True,
        )
        is True
    )


@pytest.mark.parametrize(
    "minute_ends",
    [
        tuple(_shanghai_time(9, minute) for minute in range(31, 35)),
        (
            _shanghai_time(9, 31),
            _shanghai_time(9, 32),
            _shanghai_time(9, 33),
            _shanghai_time(9, 34),
            _shanghai_time(9, 34),
        ),
        tuple(_shanghai_time(9, minute) for minute in range(31, 37)),
        (
            _shanghai_time(11, 27),
            _shanghai_time(11, 28),
            _shanghai_time(11, 29),
            _shanghai_time(11, 30),
            _shanghai_time(13, 1),
        ),
    ],
)
def test_market_complete_bucket_missing_duplicate_extra_or_cross_session_fails_closed(
    minute_ends: tuple[datetime, ...],
) -> None:
    assert (
        is_complete_five_minute_bucket(
            minute_ends,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        is False
    )


@pytest.mark.parametrize(
    ("bucket_end", "is_open"),
    [
        (_shanghai_time(9, 35, day=22), True),
        (_shanghai_time(9, 35), False),
        (_shanghai_time(9, 35), None),
    ],
)
def test_market_complete_bucket_requires_open_trading_day(
    bucket_end: datetime,
    is_open: bool | None,
) -> None:
    assert (
        is_complete_five_minute_bucket(
            expected_five_minute_ends(bucket_end),
            bucket_end=bucket_end,
            is_open=is_open,
        )
        is False
    )


def test_market_complete_bucket_rejects_one_shot_iterators_without_consuming() -> None:
    bucket_end = _shanghai_time(9, 35)
    expected = expected_five_minute_ends(bucket_end)
    one_shot = iter(expected)

    assert (
        is_complete_five_minute_bucket(
            one_shot,
            bucket_end=bucket_end,
            is_open=True,
        )
        is False
    )
    assert next(one_shot) == expected[0]


def test_market_complete_bucket_rejects_collection_without_iterating_it() -> None:
    class NeverIteratedCollection:
        def __len__(self) -> int:
            return 5

        def __iter__(self):
            raise AssertionError("non-tuple collection must not be consumed")

        def __contains__(self, item: object) -> bool:
            return False

    assert (
        is_complete_five_minute_bucket(
            NeverIteratedCollection(),
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        is False
    )


def test_market_complete_bucket_rejects_collection_that_misreports_length() -> None:
    expected = expected_five_minute_ends(_shanghai_time(9, 35))

    class MisreportedCollection:
        def __len__(self) -> int:
            return 5

        def __iter__(self):
            return iter((*expected, expected[-1]))

        def __contains__(self, item: object) -> bool:
            return item in expected

    assert (
        is_complete_five_minute_bucket(
            MisreportedCollection(),
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        is False
    )


def _complete_minute_bars(
    *,
    bucket_end: datetime | None = None,
) -> tuple[MinuteBar, ...]:
    bucket_end = bucket_end or _shanghai_time(9, 35)
    values = (
        (6400, 6420, 6390, 6410, 100_000, "1000000.10"),
        (6410, 6440, 6405, 6430, 110_000, "1100000.20"),
        (6430, 6450, 6420, 6440, 120_000, "1200000.30"),
        (6440, 6460, 6435, 6450, 130_000, "1300000.40"),
        (6450, 6470, 6440, 6460, 140_000, "1400000.50"),
    )
    return tuple(
        MinuteBar(
            symbol="003043.SZ",
            bar_end=bar_end,
            open_fen=open_fen,
            high_fen=high_fen,
            low_fen=low_fen,
            close_fen=close_fen,
            volume_shares=volume_shares,
            amount_yuan=Decimal(amount_yuan),
            received_at=bar_end + timedelta(seconds=12),
        )
        for bar_end, (
            open_fen,
            high_fen,
            low_fen,
            close_fen,
            volume_shares,
            amount_yuan,
        ) in zip(expected_five_minute_ends(bucket_end), values, strict=True)
    )


def test_market_aggregate_complete_five_minute_bar_is_exact_and_reorder_stable() -> None:
    minutes = _complete_minute_bars()

    aggregate = aggregate_five_minute_bar(
        tuple(reversed(minutes)),
        bucket_end=_shanghai_time(9, 35),
        is_open=True,
    )

    assert aggregate == FiveMinuteBar(
        symbol="003043.SZ",
        bar_end=_shanghai_time(9, 35),
        formula_version="ta-v1",
        open_fen=6400,
        high_fen=6470,
        low_fen=6390,
        close_fen=6460,
        volume_shares=600_000,
        amount_yuan=Decimal("6000001.50"),
    )
    assert (
        aggregate_five_minute_bar(
            minutes,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        == aggregate
    )
    assert TA_FORMULA_VERSION == "ta-v1"


def test_market_aggregate_decimal_amount_is_exact_across_ambient_precision() -> None:
    minutes = tuple(
        minute.model_copy(update={"amount_yuan": Decimal("0.123456789")})
        for minute in _complete_minute_bars()
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = aggregate_five_minute_bar(
            minutes,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = aggregate_five_minute_bar(
            minutes,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )

    assert low_precision == high_precision
    assert low_precision is not None
    assert low_precision.amount_yuan == Decimal("0.617283945")


def test_market_aggregate_decimal_amount_has_a_safe_exact_digit_span() -> None:
    minutes = _complete_minute_bars()
    extreme_zero = minutes[0].model_copy(update={"amount_yuan": Decimal("0E-100000000")})
    one_yuan = minutes[1].model_copy(update={"amount_yuan": Decimal("1")})
    zero_tail = tuple(
        minute.model_copy(update={"amount_yuan": Decimal("0")}) for minute in minutes[2:]
    )

    aggregate = aggregate_five_minute_bar(
        (extreme_zero, one_yuan, *zero_tail),
        bucket_end=_shanghai_time(9, 35),
        is_open=True,
    )

    assert aggregate is not None
    assert aggregate.amount_yuan == Decimal("1")

    at_limit = minutes[0].model_copy(update={"amount_yuan": Decimal("1E-639")})
    aggregate = aggregate_five_minute_bar(
        (at_limit, one_yuan, *zero_tail),
        bucket_end=_shanghai_time(9, 35),
        is_open=True,
    )

    assert aggregate is not None
    assert aggregate.amount_yuan == Decimal(f"1.{('0' * 638)}1")

    beyond_limit = minutes[0].model_copy(update={"amount_yuan": Decimal("1E-640")})
    with pytest.raises(ValueError, match="safe digit"):
        aggregate_five_minute_bar(
            (beyond_limit, one_yuan, *zero_tail),
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )

    max_coefficient = Decimal("9" * 640)
    huge_first = minutes[0].model_copy(update={"amount_yuan": max_coefficient})
    huge_second = minutes[1].model_copy(update={"amount_yuan": max_coefficient})
    with pytest.raises(ValueError, match="safe digit"):
        aggregate_five_minute_bar(
            (huge_first, huge_second, *zero_tail),
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )


def test_market_aggregate_missing_duplicate_then_recovered_is_fail_closed_and_stable() -> None:
    minutes = _complete_minute_bars()
    missing = minutes[:-1]
    duplicate_without_last = (*minutes[:-1], minutes[-2])

    assert (
        aggregate_five_minute_bar(
            missing,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        is None
    )
    assert (
        aggregate_five_minute_bar(
            duplicate_without_last,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )
        is None
    )

    recovered = aggregate_five_minute_bar(
        minutes,
        bucket_end=_shanghai_time(9, 35),
        is_open=True,
    )
    assert recovered is not None
    assert (
        recovered.symbol,
        recovered.bar_end,
        recovered.formula_version,
    ) == ("003043.SZ", _shanghai_time(9, 35), "ta-v1")


def test_market_aggregate_never_crosses_lunch_or_closed_unknown_day() -> None:
    morning = _complete_minute_bars(bucket_end=_shanghai_time(11, 30))
    afternoon = _complete_minute_bars(bucket_end=_shanghai_time(13, 5))
    cross_lunch = (*morning[-3:], *afternoon[:2])

    assert (
        aggregate_five_minute_bar(
            cross_lunch,
            bucket_end=_shanghai_time(13, 5),
            is_open=True,
        )
        is None
    )
    for is_open in (False, None):
        assert (
            aggregate_five_minute_bar(
                afternoon,
                bucket_end=_shanghai_time(13, 5),
                is_open=is_open,
            )
            is None
        )


def test_market_aggregate_rejects_mixed_symbols_and_remains_immutable() -> None:
    minutes = _complete_minute_bars()
    mixed = (
        *minutes[:-1],
        minutes[-1].model_copy(update={"symbol": "600519.SH"}),
    )

    with pytest.raises(ValueError, match="one symbol"):
        aggregate_five_minute_bar(
            mixed,
            bucket_end=_shanghai_time(9, 35),
            is_open=True,
        )

    aggregate = aggregate_five_minute_bar(
        minutes,
        bucket_end=_shanghai_time(9, 35),
        is_open=True,
    )
    assert aggregate is not None
    with pytest.raises(ValidationError, match="frozen"):
        aggregate.close_fen = 6500
    with pytest.raises(ValidationError):
        aggregate.model_copy(update={"close_fen": -1})
    with pytest.raises(ValidationError, match="five-minute boundary"):
        aggregate.model_copy(update={"bar_end": _shanghai_time(9, 36)})


def test_market_aggregate_provisional_daily_bar_uses_exact_slice_facts() -> None:
    minute_ends = expected_minute_ends(date(2026, 8, 19), is_open=True)[:5]
    minutes = tuple(
        _provisional_minute(bar_end, index) for index, bar_end in enumerate(minute_ends)
    )

    aggregate = aggregate_provisional_daily_bar(
        current_day_minutes=minutes,
        source_as_of=minute_ends[-1],
    )

    assert aggregate == DailyBar(
        symbol="003043.SZ",
        trade_date=date(2026, 8, 19),
        open_fen=6400,
        high_fen=6454,
        low_fen=6376,
        close_fen=6434,
        volume_shares=510,
        amount_yuan=Decimal("61.25"),
        is_official=False,
        received_at=max(minute.received_at for minute in minutes),
    )
    assert (
        aggregate_provisional_daily_bar(
            current_day_minutes=minutes,
            source_as_of=minute_ends[-1],
        )
        == aggregate
    )


def test_market_aggregate_full_trading_day_remains_provisional() -> None:
    minute_ends = expected_minute_ends(date(2026, 8, 19), is_open=True)
    minutes = tuple(
        _provisional_minute(bar_end, index) for index, bar_end in enumerate(minute_ends)
    )

    aggregate = aggregate_provisional_daily_bar(
        current_day_minutes=minutes,
        source_as_of=_shanghai_time(15, 0),
    )

    assert len(minutes) == 240
    assert aggregate is not None
    assert aggregate.trade_date == date(2026, 8, 19)
    assert aggregate.close_fen == minutes[-1].close_fen
    assert aggregate.is_official is False


@pytest.mark.parametrize(
    "current_day_minutes",
    [
        [],
        (),
        (_provisional_minute(_shanghai_time(9, 31)),) * 2,
        (
            _provisional_minute(_shanghai_time(9, 31)),
            _provisional_minute(_shanghai_time(9, 33), 1),
        ),
        tuple(
            reversed(
                (
                    _provisional_minute(_shanghai_time(9, 31)),
                    _provisional_minute(_shanghai_time(9, 32), 1),
                )
            )
        ),
    ],
)
def test_market_aggregate_provisional_daily_bar_rejects_non_exact_slices(
    current_day_minutes: object,
) -> None:
    assert (
        aggregate_provisional_daily_bar(
            current_day_minutes=current_day_minutes,  # type: ignore[arg-type]
            source_as_of=_shanghai_time(9, 35),
        )
        is None
    )


def test_market_aggregate_provisional_daily_bar_rejects_wrong_cutoff_and_facts() -> None:
    minute_ends = expected_minute_ends(date(2026, 8, 19), is_open=True)[:5]
    minutes = tuple(
        _provisional_minute(bar_end, index) for index, bar_end in enumerate(minute_ends)
    )

    for source_as_of in (
        _shanghai_time(9, 34),
        _shanghai_time(9, 36),
        _shanghai_time(13, 0),
    ):
        assert (
            aggregate_provisional_daily_bar(
                current_day_minutes=minutes,
                source_as_of=source_as_of,
            )
            is None
        )

    assert (
        aggregate_provisional_daily_bar(
            current_day_minutes=(
                *minutes[:-1],
                minutes[-1].model_copy(update={"symbol": "600519.SH"}),
            ),
            source_as_of=minute_ends[-1],
        )
        is None
    )
    assert (
        aggregate_provisional_daily_bar(
            current_day_minutes=(
                *minutes[:-1],
                minutes[-1].model_copy(
                    update={
                        "bar_end": _shanghai_time(9, 35, day=20),
                        "received_at": _shanghai_time(9, 36, day=20),
                    }
                ),
            ),
            source_as_of=minute_ends[-1],
        )
        is None
    )


class _TushareStubClient:
    def __init__(self, responses: dict[str, DataFrame | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, operation: str):
        def endpoint(**kwargs: object) -> DataFrame:
            self.calls.append((operation, kwargs))
            response = self.responses[operation]
            if isinstance(response, Exception):
                raise response
            return response.copy(deep=True)

        return endpoint


def _tushare_provider(
    client: object,
    *,
    source_time_label: SourceTimeLabel = SourceTimeLabel.START,
    probe_symbol: str | None = "003043.SZ",
) -> TushareMarketDataProvider:
    return TushareMarketDataProvider(
        client,
        now=lambda: _shanghai_time(9, 33, day=20) + timedelta(seconds=12),
        is_open_on=lambda value: value == date(2026, 8, 20),
        source_time_label=source_time_label,
        probe_symbol=probe_symbol,
    )


def _empty_tushare_frames() -> dict[str, DataFrame]:
    return {
        "rt_min": DataFrame(
            columns=["ts_code", "time", "open", "close", "high", "low", "vol", "amount"]
        ),
        "rt_min_daily": DataFrame(
            columns=[
                "code",
                "freq",
                "time",
                "open",
                "close",
                "high",
                "low",
                "vol",
                "amount",
            ]
        ),
        "trade_cal": DataFrame(columns=["exchange", "cal_date", "is_open", "pretrade_date"]),
        "stk_limit": DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"]),
        "daily": DataFrame(
            columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        ),
    }


def test_tushare_current_day_minutes_accepts_omitted_fixed_frequency() -> None:
    frames = _empty_tushare_frames()
    frames["rt_min_daily"] = DataFrame(
        [
            {
                "ts_code": "003043.SZ",
                "time": "2026-08-20 09:31:00",
                "open": "10",
                "close": "10.5",
                "high": "11",
                "low": "9",
                "vol": "100",
                "amount": "200",
            }
        ]
    )

    bars = _tushare_provider(_TushareStubClient(frames)).current_day_minutes(
        "003043.SZ"
    )

    assert len(bars) == 1
    assert bars[0].bar_end == _shanghai_time(9, 32, day=20)


def test_tushare_current_day_minutes_rejects_wrong_returned_frequency() -> None:
    frames = _empty_tushare_frames()
    frames["rt_min_daily"] = DataFrame(
        [
            {
                "ts_code": "003043.SZ",
                "freq": "5MIN",
                "time": "2026-08-20 09:31:00",
                "open": "10",
                "close": "10.5",
                "high": "11",
                "low": "9",
                "vol": "100",
                "amount": "200",
            }
        ]
    )

    assert (
        _tushare_provider(_TushareStubClient(frames)).current_day_minutes("003043.SZ")
        == []
    )


def test_tushare_unverified_source_time_fails_before_sdk_call() -> None:
    client = _TushareStubClient(_empty_tushare_frames())
    provider = _tushare_provider(
        client,
        source_time_label=SourceTimeLabel.UNVERIFIED,
    )

    with pytest.raises(SourceTimeMappingUnverifiedError):
        provider.realtime_minutes(("003043.SZ",))

    assert client.calls == []


@pytest.mark.parametrize(
    ("provider_error", "expected_code"),
    [
        (Exception("403 permission denied"), TushareErrorCode.BLOCKED_PERMISSION),
        (Exception("429 rate limit"), TushareErrorCode.RATE_LIMITED),
        (Timeout("request timed out"), TushareErrorCode.TRANSIENT),
        (Exception("unclassified provider failure"), TushareErrorCode.ERROR),
        (Exception("invalid symbol 600403.SH"), TushareErrorCode.ERROR),
        (Exception("unknown token abc429xyz"), TushareErrorCode.ERROR),
        (Exception("record 1401 is invalid"), TushareErrorCode.ERROR),
        (Exception("stock code 403.SZ"), TushareErrorCode.ERROR),
        (Exception("data error 403.5"), TushareErrorCode.ERROR),
        (Exception("HTTP status 401"), TushareErrorCode.BLOCKED_PERMISSION),
        (Exception("HTTP/1.1 401"), TushareErrorCode.BLOCKED_PERMISSION),
        (Exception("error code is 403"), TushareErrorCode.BLOCKED_PERMISSION),
        (Exception("HTTP 429"), TushareErrorCode.RATE_LIMITED),
        (Exception("status is 429"), TushareErrorCode.RATE_LIMITED),
    ],
)
def test_tushare_provider_errors_use_stable_codes_and_drop_raw_context(
    provider_error: Exception,
    expected_code: TushareErrorCode,
) -> None:
    frames = _empty_tushare_frames()
    client = _TushareStubClient({**frames, "rt_min": provider_error})

    with pytest.raises(TushareProviderError) as captured:
        _tushare_provider(client).realtime_minutes(("003043.SZ",))

    assert captured.value.code is expected_code
    assert str(captured.value) == f"Tushare rt_min failed ({expected_code.value})"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert [operation for operation, _ in client.calls] == ["rt_min"]


@pytest.mark.parametrize(
    ("status_code", "message", "expected_code"),
    [
        (401, "opaque provider failure", TushareErrorCode.BLOCKED_PERMISSION),
        (403, "opaque provider failure", TushareErrorCode.BLOCKED_PERMISSION),
        (429, "opaque provider failure", TushareErrorCode.RATE_LIMITED),
        (503, "opaque provider failure", TushareErrorCode.TRANSIENT),
        (422, "403 permission denied", TushareErrorCode.ERROR),
    ],
)
def test_tushare_provider_errors_prefer_structured_http_status(
    status_code: int,
    message: str,
    expected_code: TushareErrorCode,
) -> None:
    response = Response()
    response.status_code = status_code
    provider_error = HTTPError(message, response=response)
    client = _TushareStubClient({**_empty_tushare_frames(), "rt_min": provider_error})

    with pytest.raises(TushareProviderError) as captured:
        _tushare_provider(client).realtime_minutes(("003043.SZ",))

    assert captured.value.code is expected_code
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_tushare_token_sentinel_never_appears_in_provider_or_error_surfaces() -> None:
    fake_token = "FAKE_TUSHARE_TOKEN_DO_NOT_USE"
    frames = _empty_tushare_frames()
    client = _TushareStubClient({**frames, "rt_min": Exception(f"401 token={fake_token}")})
    provider = _tushare_provider(client)

    with pytest.raises(TushareProviderError) as captured:
        provider.realtime_minutes(("003043.SZ",))

    exposed = "\n".join(
        (
            repr(provider),
            repr(captured.value),
            repr(vars(captured.value)),
            str(captured.value),
            "".join(traceback.format_exception(captured.value)),
        )
    )
    assert fake_token not in exposed
    assert fake_token not in captured.value.__dict__.values()


def test_tushare_capability_probe_is_independent_and_serializes_only_states() -> None:
    fake_token = "FAKE_TUSHARE_TOKEN_DO_NOT_USE"
    frames = _empty_tushare_frames()
    client = _TushareStubClient(
        {
            **frames,
            "rt_min": Exception(f"403 token={fake_token}"),
            "trade_cal": Exception("429 rate limit"),
            "stk_limit": Timeout(f"timed out token={fake_token}"),
        }
    )

    capabilities = _tushare_provider(client).probe_capabilities()

    assert capabilities == ProviderCapabilities(
        realtime_minutes=ProviderCapabilityStatus.BLOCKED_PERMISSION,
        current_day_minutes=ProviderCapabilityStatus.READY,
        trading_calendar=ProviderCapabilityStatus.RATE_LIMITED,
        daily_limits=ProviderCapabilityStatus.ERROR,
        daily_bars=ProviderCapabilityStatus.READY,
    )
    assert client.calls == [
        (
            "rt_min",
            {
                "fields": "ts_code,time,open,close,high,low,vol,amount",
                "ts_code": "003043.SZ",
                "freq": "1MIN",
            },
        ),
        (
            "rt_min_daily",
            {
                "fields": "ts_code,freq,time,open,close,high,low,vol,amount",
                "ts_code": "003043.SZ",
                "freq": "1MIN",
            },
        ),
        (
            "trade_cal",
            {
                "fields": "exchange,cal_date,is_open,pretrade_date",
                "exchange": "",
                "start_date": "20260820",
                "end_date": "20260820",
            },
        ),
        (
            "stk_limit",
            {
                "fields": "trade_date,ts_code,up_limit,down_limit",
                "trade_date": "20260820",
            },
        ),
        (
            "daily",
            {
                "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
                "ts_code": "003043.SZ",
                "start_date": "20260820",
                "end_date": "20260820",
            },
        ),
    ]
    assert fake_token not in capabilities.model_dump_json()


def test_tushare_capability_probe_without_symbol_keeps_symbol_methods_unverified() -> None:
    client = _TushareStubClient(_empty_tushare_frames())

    capabilities = _tushare_provider(client, probe_symbol=None).probe_capabilities()

    assert capabilities.realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.current_day_minutes is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.daily_bars is ProviderCapabilityStatus.UNVERIFIED
    assert capabilities.trading_calendar is ProviderCapabilityStatus.READY
    assert capabilities.daily_limits is ProviderCapabilityStatus.READY
    assert [operation for operation, _ in client.calls] == ["trade_cal", "stk_limit"]


@pytest.mark.parametrize(
    ("failed_operation", "failed_field"),
    [
        ("rt_min", "realtime_minutes"),
        ("rt_min_daily", "current_day_minutes"),
        ("trade_cal", "trading_calendar"),
        ("stk_limit", "daily_limits"),
        ("daily", "daily_bars"),
    ],
)
def test_tushare_each_capability_can_fail_without_changing_the_other_four(
    failed_operation: str,
    failed_field: str,
) -> None:
    frames = _empty_tushare_frames()
    client = _TushareStubClient(
        {**frames, failed_operation: Exception("unclassified provider failure")}
    )

    capabilities = _tushare_provider(client).probe_capabilities()

    for field, status in capabilities.model_dump(mode="python").items():
        expected = (
            ProviderCapabilityStatus.ERROR
            if field == failed_field
            else ProviderCapabilityStatus.READY
        )
        assert status is expected
    assert [operation for operation, _ in client.calls] == [
        "rt_min",
        "rt_min_daily",
        "trade_cal",
        "stk_limit",
        "daily",
    ]


def test_tushare_provider_public_methods_match_the_provider_protocol() -> None:
    method_names = (
        "probe_capabilities",
        "realtime_minutes",
        "current_day_minutes",
        "trading_calendar",
        "daily_limits",
        "daily_bars",
    )

    for method_name in method_names:
        protocol_method = getattr(MarketDataProvider, method_name)
        implementation_method = getattr(TushareMarketDataProvider, method_name)
        implementation_parameters = signature(implementation_method).parameters
        protocol_parameters = signature(protocol_method).parameters
        assert tuple(implementation_parameters) == tuple(protocol_parameters)
        for parameter_name, protocol_parameter in protocol_parameters.items():
            implementation_parameter = implementation_parameters[parameter_name]
            assert implementation_parameter.kind is protocol_parameter.kind
            assert implementation_parameter.default == protocol_parameter.default
        assert get_type_hints(implementation_method) == get_type_hints(protocol_method)
