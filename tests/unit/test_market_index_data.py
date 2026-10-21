from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import IntEnum, StrEnum
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
    canonical_decimal,
    canonical_json,
    market_index_bar_set_hash,
    market_index_request_set_hash,
)
from trade_plan_monitor.market_index.formulas import calculate_requested_facts
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactUnit,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSourceKind,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_canonical_index_primitives_keep_exact_bytes_and_typed_boundaries():
    class Label(StrEnum):
        LIVE = "LIVE"

    class Count(IntEnum):
        ONE = 1

    class Text(str):
        pass

    assert canonical_json({
        "z": [None, True, 1, "中文", Label.LIVE, Count.ONE],
        "d": Decimal("12.3400"), "day": date(2026, 9, 5),
        "time": datetime(2026, 9, 5, 10, 0, tzinfo=SHANGHAI),
    }) == (
        '{"d":"12.34","day":"2026-09-05","time":"2026-09-05T10:00:00.000000+08:00",'
        '"z":[null,true,1,"中文","LIVE",1]}'
    )
    with pytest.raises(TypeError, match="unsupported canonical"):
        canonical_json(Text("text"))
    with pytest.raises(ValueError, match="floating point"):
        canonical_json(1.0)
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json(datetime(2026, 9, 5))
    with pytest.raises(ValueError, match="finite"):
        canonical_json(Decimal("NaN"))


def _bar(
    *,
    at: datetime,
    close: str,
    interval: MarketIndexInterval,
    revision: int = 1,
) -> MarketIndexBar:
    close_points = Decimal(close)
    return MarketIndexBar(
        index_code=MarketIndexCode.CHINEXT,
        interval=interval,
        bar_at=at,
        open_points=close_points - Decimal("0.2"),
        high_points=close_points + Decimal("0.5"),
        low_points=close_points - Decimal("0.5"),
        close_points=close_points,
        volume=None,
        amount=None,
        observed_at=at + timedelta(seconds=2),
        source_kind=(
            MarketIndexSourceKind.OFFICIAL
            if interval is MarketIndexInterval.OFFICIAL_DAILY
            else MarketIndexSourceKind.PROVISIONAL
        ),
        provider_revision=revision,
    )


def _daily_bars() -> tuple[MarketIndexBar, ...]:
    return tuple(
        _bar(
            at=datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
            close=str(9 + day),
            interval=MarketIndexInterval.OFFICIAL_DAILY,
        )
        for day in range(1, 6)
    )


def _five_minute_bars() -> tuple[MarketIndexBar, ...]:
    return tuple(
        _bar(
            at=datetime(2026, 9, 2, 10, minute, tzinfo=SHANGHAI),
            close=close,
            interval=MarketIndexInterval.FIVE_MINUTE,
        )
        for minute, close in ((25, "100"), (30, "110"), (35, "121"))
    )


def test_market_index_bar_requires_exact_index_identity_and_completed_timestamp() -> None:
    valid = _five_minute_bars()[-1]
    assert valid.close_points == Decimal("121")

    with pytest.raises(ValidationError, match="five-minute boundary"):
        _bar(
            at=datetime(2026, 9, 2, 10, 34, tzinfo=SHANGHAI),
            close="121",
            interval=MarketIndexInterval.FIVE_MINUTE,
        )

    with pytest.raises(ValidationError, match="15:00"):
        _bar(
            at=datetime(2026, 8, 1, 14, 59, tzinfo=SHANGHAI),
            close="10",
            interval=MarketIndexInterval.OFFICIAL_DAILY,
        )

    with pytest.raises(ValidationError):
        MarketIndexBar.model_validate(
            {
                **valid.model_dump(mode="python"),
                "index_code": "300750.SZ",
            }
        )


def test_market_index_bar_rejects_binary_float_and_invalid_ohlc() -> None:
    valid = _five_minute_bars()[-1]
    with pytest.raises(ValidationError):
        MarketIndexBar.model_validate(
            {
                **valid.model_dump(mode="python"),
                "close_points": 121.0,
            }
        )

    with pytest.raises(ValidationError, match="OHLC"):
        MarketIndexBar.model_validate(
            {
                **valid.model_dump(mode="python"),
                "high_points": Decimal("120"),
            }
        )


@pytest.mark.parametrize("value", [Decimal("1E+10000"), Decimal("1E-10000")])
def test_canonical_decimal_rejects_oversized_fixed_point_expansion(value: Decimal) -> None:
    with pytest.raises(ValueError, match="expansion is too large"):
        canonical_decimal(value)


def test_market_index_bar_rejects_oversized_decimal_before_hashing() -> None:
    valid = _five_minute_bars()[-1]
    oversized = Decimal("1E+10000")

    with pytest.raises(ValidationError, match="canonical decimal expansion is too large"):
        MarketIndexBar.model_validate(
            {
                **valid.model_dump(mode="python"),
                "open_points": oversized,
                "high_points": oversized,
                "low_points": oversized,
                "close_points": oversized,
            }
        )


def test_market_index_formula_goldens_cover_sma_lookback_and_returns() -> None:
    requests = (
        SmaFactRequest(period=3),
        SmaLookbackFactRequest(period=2, lookback=2),
        ReturnFactRequest(
            window=ReturnWindow.FIVE_MINUTE_BUCKETS,
            window_size=2,
        ),
        ReturnFactRequest(
            window=ReturnWindow.OFFICIAL_OPEN_DAYS,
            window_size=2,
        ),
    )

    facts = calculate_requested_facts(
        index_code=MarketIndexCode.CHINEXT,
        five_minute_bars=_five_minute_bars(),
        official_daily_bars=_daily_bars(),
        requests=requests,
        input_cutoff=datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI),
    )

    assert facts[0].value == Decimal("13")
    assert facts[0].comparison_value is None
    assert facts[0].unit is MarketIndexFactUnit.POINTS
    assert facts[1].value == Decimal("13.5")
    assert facts[1].comparison_value == Decimal("11.5")
    assert facts[2].value == Decimal("0.21")
    assert facts[2].unit is MarketIndexFactUnit.RATIO
    assert facts[3].value == Decimal("0.1666666666666666666666666666666666666666666666667")
    assert all(fact.formula_definition_hash == FORMULA_DEFINITION_HASH for fact in facts)


def test_formula_requests_enforce_approved_parameter_bounds() -> None:
    for payload in (
        {"formula_id": "SMA", "period": 1},
        {"formula_id": "SMA", "period": 251},
        {"formula_id": "SMA_LOOKBACK", "period": 20, "lookback": 0},
        {"formula_id": "SMA_LOOKBACK", "period": 20, "lookback": 61},
        {"formula_id": "RETURN", "window": "OFFICIAL_OPEN_DAYS", "window_size": 0},
        {"formula_id": "RETURN", "window": "OFFICIAL_OPEN_DAYS", "window_size": 251},
    ):
        request_type = {
            "SMA": SmaFactRequest,
            "SMA_LOOKBACK": SmaLookbackFactRequest,
            "RETURN": ReturnFactRequest,
        }[str(payload["formula_id"])]
        with pytest.raises(ValidationError):
            request_type.model_validate(payload)


def test_insufficient_history_is_explicit() -> None:
    with pytest.raises(ValueError, match="INSUFFICIENT_HISTORY"):
        calculate_requested_facts(
            index_code=MarketIndexCode.CHINEXT,
            five_minute_bars=_five_minute_bars(),
            official_daily_bars=_daily_bars(),
            requests=(SmaLookbackFactRequest(period=4, lookback=2),),
            input_cutoff=datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI),
        )


def test_canonical_hashes_are_order_independent_and_content_sensitive() -> None:
    bars = _daily_bars()
    requests = (
        ReturnFactRequest(window=ReturnWindow.OFFICIAL_OPEN_DAYS, window_size=2),
        SmaFactRequest(period=3),
    )

    assert market_index_bar_set_hash(bars) == market_index_bar_set_hash(tuple(reversed(bars)))
    assert market_index_request_set_hash(requests) == market_index_request_set_hash(
        tuple(reversed(requests))
    )

    changed = bars[:-1] + (bars[-1].model_copy(update={"close_points": Decimal("14.01")}),)
    assert market_index_bar_set_hash(bars) != market_index_bar_set_hash(changed)
    assert FORMULA_DEFINITION_HASH == FORMULA_DEFINITION_HASH.lower()
    assert len(FORMULA_DEFINITION_HASH) == 64


def test_market_index_health_and_issue_codes_are_closed() -> None:
    assert tuple(MarketIndexHealth) == (
        MarketIndexHealth.LIVE,
        MarketIndexHealth.STALE,
        MarketIndexHealth.GAPPED,
        MarketIndexHealth.BLOCKED,
    )
    assert MarketIndexIssueCode.FUTURE_DATA.value == "FUTURE_DATA"
    assert MarketIndexIssueCode.PROVIDER_UNAVAILABLE.value == "PROVIDER_UNAVAILABLE"
