"""Strict Tushare ``stk_mins`` adapter for one verified historical day."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Protocol, cast
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalMinuteProfileUnverifiedError,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    DailyBar,
    DailyLimit,
    MinuteBar,
    TradingDay,
)
from trade_plan_monitor.market_data.sessions import (
    DEFAULT_DATA_GRACE,
    SourceTimeLabel,
    expected_minute_ends,
    normalize_source_minute,
)
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SYMBOL_ADAPTER = TypeAdapter(AShareSymbol)
_HISTORICAL_MINUTE_FIELDS = "ts_code,trade_time,open,close,high,low,vol,amount"
_REQUIRED_COLUMNS = frozenset(_HISTORICAL_MINUTE_FIELDS.split(","))
_MAX_NORMALIZED_INTEGER_DIGITS = 640
_OPENING_SPECIAL_TIME = time(9, 30)


class HistoricalReferenceProvider(Protocol):
    """Reference surfaces that require an explicit historical exchange."""

    def trading_calendar_for_exchange(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> Iterable[TradingDay]: ...

    def daily_limits(self, trade_date: date) -> Iterable[DailyLimit]: ...

    def daily_bars(self, symbol: str, start: date, end: date) -> Iterable[DailyBar]: ...


class TushareHistoricalMinuteProvider:
    """Normalize historical minutes under a separate, versioned source contract."""

    __slots__ = ("_client", "_profile", "_reference_provider")

    def __init__(
        self,
        client: object,
        *,
        now: Callable[[], datetime],
        profile: HistoricalMinuteProfile = HistoricalMinuteProfile.UNVERIFIED,
        reference_provider: HistoricalReferenceProvider | None = None,
    ) -> None:
        if not callable(now):
            raise TypeError("now must be callable")
        if not isinstance(profile, HistoricalMinuteProfile):
            raise TypeError("profile must be a HistoricalMinuteProfile")
        if reference_provider is not None and any(
            not callable(getattr(reference_provider, method, None))
            for method in (
                "trading_calendar_for_exchange",
                "daily_limits",
                "daily_bars",
            )
        ):
            raise TypeError("reference_provider must expose historical reference methods")
        self._client = client
        self._profile = profile
        self._reference_provider = reference_provider or TushareMarketDataProvider(
            client,
            now=now,
            is_open_on=lambda _trade_date: None,
            source_time_label=SourceTimeLabel.UNVERIFIED,
        )

    @property
    def profile(self) -> HistoricalMinuteProfile:
        """Return the independent historical-label profile."""

        return self._profile

    def historical_minute_batch(
        self,
        symbol: str,
        trade_date: date,
    ) -> HistoricalMinuteBatch:
        """Fetch and strictly normalize one complete historical trading day."""

        normalized_symbol = _validated_symbol(symbol)
        normalized_date = _validated_trade_date(trade_date)
        expected = expected_minute_ends(normalized_date, is_open=True)
        if len(expected) != 240:
            raise ValueError("trade_date must be a weekday trading-date candidate")
        if self._profile is HistoricalMinuteProfile.UNVERIFIED:
            raise HistoricalMinuteProfileUnverifiedError("historical minute profile is UNVERIFIED")
        if self._profile is not HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1:
            raise HistoricalMinuteProfileUnverifiedError("historical minute profile is unsupported")

        frame = self._fetch_frame(
            symbol=normalized_symbol,
            trade_date=normalized_date,
        )
        invalid_response = False
        batch: HistoricalMinuteBatch | None = None
        try:
            batch = self._normalize_verified_frame(
                frame,
                symbol=normalized_symbol,
                trade_date=normalized_date,
                expected=expected,
            )
        except DecimalException, KeyError, OverflowError, TypeError, ValidationError, ValueError:
            invalid_response = True
        if invalid_response or batch is None:
            raise TushareProviderError(
                TushareErrorCode.INVALID_RESPONSE,
                "stk_mins",
            ) from None
        return batch

    def historical_minutes(self, symbol: str, trade_date: date) -> tuple[MinuteBar, ...]:
        """Return only the 240 canonical executable minutes for one day."""

        return self.historical_minute_batch(symbol, trade_date).bars

    def trading_calendar(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[TradingDay, ...]:
        """Fetch one explicit exchange; Tushare's empty value defaults to SSE."""

        if exchange not in {"SSE", "SZSE"}:
            raise ValueError(f"UNSUPPORTED_HISTORICAL_CALENDAR:{exchange}")
        fetch = getattr(
            self._reference_provider,
            "historical_trading_calendar_for_exchange",
            self._reference_provider.trading_calendar_for_exchange,
        )
        values = tuple(fetch(exchange, start, end))
        if any(value.exchange != exchange for value in values):
            raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, "trade_cal")
        return values

    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]:
        """Delegate actual daily limits as an immutable historical tuple."""

        fetch = getattr(
            self._reference_provider,
            "historical_daily_limits",
            self._reference_provider.daily_limits,
        )
        values = tuple(fetch(trade_date))
        return tuple(
            value.model_copy(
                update={"received_at": datetime.combine(value.trade_date, time(9, 30), _SHANGHAI)}
            )
            for value in values
        )

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]:
        """Delegate official unadjusted daily bars as an immutable tuple."""

        fetch = getattr(
            self._reference_provider,
            "historical_daily_bars",
            self._reference_provider.daily_bars,
        )
        values = tuple(fetch(symbol, start, end))
        return tuple(
            value.model_copy(
                update={"received_at": datetime.combine(value.trade_date, time(15, 20), _SHANGHAI)}
            )
            for value in values
        )

    def historical_adjustment_factors(self, symbol: str, start: date, end: date):
        """Preserve provider receipt and declare the historical session-open convention."""
        from trade_plan_monitor.backtest.daily_basis import HistoricalAdjustmentFactor

        normalized_symbol = _validated_symbol(symbol)
        factors, received_at = self._reference_provider.daily_adjustment_factors(
            normalized_symbol, start, end,
        )
        return tuple(HistoricalAdjustmentFactor(
            symbol=normalized_symbol, trade_date=day, factor=factor,
            available_at=datetime.combine(day, time(9, 30), _SHANGHAI),
            collected_at=received_at,
        ) for day, factor in sorted(factors.items()))

    def _fetch_frame(self, *, symbol: str, trade_date: date) -> pd.DataFrame:
        provider_error: TushareProviderError | None = None
        frame: object | None = None
        try:
            endpoint = self._client.stk_mins  # type: ignore[attr-defined]
            frame = endpoint(
                fields=_HISTORICAL_MINUTE_FIELDS,
                ts_code=symbol,
                freq="1min",
                start_date=f"{trade_date.isoformat()} 00:00:00",
                end_date=f"{trade_date.isoformat()} 23:59:59",
            )
        except Exception as error:
            provider_error = TushareMarketDataProvider._safe_provider_error("stk_mins", error)
        if provider_error is not None:
            raise provider_error from None
        if not isinstance(frame, pd.DataFrame):
            raise TushareProviderError(
                TushareErrorCode.INVALID_RESPONSE,
                "stk_mins",
            ) from None
        return frame

    def _normalize_verified_frame(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        trade_date: date,
        expected: tuple[datetime, ...],
    ) -> HistoricalMinuteBatch:
        counts = Counter(frame.columns)
        if any(counts[column] != 1 for column in _REQUIRED_COLUMNS):
            raise ValueError("historical response schema is invalid")
        if len(frame.index) != 241:
            raise ValueError("verified profile requires exactly 241 source rows")

        rows = frame.to_dict(orient="records")
        parsed: list[
            tuple[
                datetime,
                int,
                int,
                int,
                int,
                int,
                Decimal,
            ]
        ] = []
        for row in rows:
            row_symbol = _validated_symbol(row["ts_code"])
            if row_symbol != symbol:
                raise ValueError("historical response contains a wrong symbol")
            source_time = _source_datetime(row["trade_time"])
            if source_time.date() != trade_date:
                raise ValueError("historical response contains a wrong date")
            open_fen = _price_fen(row["open"])
            close_fen = _price_fen(row["close"])
            high_fen = _price_fen(row["high"])
            low_fen = _price_fen(row["low"])
            if low_fen > high_fen or not low_fen <= open_fen <= high_fen:
                raise ValueError("historical response contains invalid OHLC")
            if not low_fen <= close_fen <= high_fen:
                raise ValueError("historical response contains invalid OHLC")
            volume_shares = _scaled_integer(row["vol"], places=0)
            amount_yuan = _nonnegative_decimal(row["amount"])
            parsed.append(
                (
                    source_time,
                    open_fen,
                    high_fen,
                    low_fen,
                    close_fen,
                    volume_shares,
                    amount_yuan,
                )
            )

        source_times = tuple(item[0] for item in parsed)
        if len(set(source_times)) != len(source_times):
            raise ValueError("historical response contains duplicate source times")
        ascending = tuple(sorted(source_times))
        if source_times not in (ascending, tuple(reversed(ascending))):
            raise ValueError("historical response order must be monotonic")

        special_time = datetime.combine(trade_date, _OPENING_SPECIAL_TIME, _SHANGHAI)
        expected_source_times = frozenset((*expected, special_time))
        if frozenset(source_times) != expected_source_times:
            raise ValueError("historical response does not match the verified timestamp set")

        by_time = {item[0]: item for item in parsed}
        special_values = by_time[special_time]
        opening_special = HistoricalOpeningSpecial(
            symbol=symbol,
            source_time=special_values[0],
            open_fen=special_values[1],
            high_fen=special_values[2],
            low_fen=special_values[3],
            close_fen=special_values[4],
            volume_shares=special_values[5],
            amount_yuan=special_values[6],
        )

        bars: list[MinuteBar] = []
        for source_time in expected:
            values = by_time[source_time]
            bar_end = normalize_source_minute(
                source_time,
                label=SourceTimeLabel.END,
                is_open=True,
            )
            bars.append(
                MinuteBar(
                    symbol=symbol,
                    bar_end=bar_end,
                    open_fen=values[1],
                    high_fen=values[2],
                    low_fen=values[3],
                    close_fen=values[4],
                    volume_shares=values[5],
                    amount_yuan=values[6],
                    received_at=bar_end + DEFAULT_DATA_GRACE,
                )
            )

        return HistoricalMinuteBatch(
            symbol=symbol,
            trade_date=trade_date,
            contract_version=self._profile,
            bars=tuple(bars),
            opening_special=opening_special,
        )


def _validated_symbol(value: object) -> str:
    try:
        return cast(str, _SYMBOL_ADAPTER.validate_python(value))
    except ValidationError as error:
        raise ValueError("symbol must be a canonical A-share code") from error


def _validated_trade_date(value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("trade_date must be a date")
    return value


def _source_datetime(value: object) -> datetime:
    if isinstance(value, str):
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("trade_time must be a datetime or canonical string")
    if parsed.second or parsed.microsecond or getattr(parsed, "nanosecond", 0):
        raise ValueError("trade_time must identify a whole minute")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=_SHANGHAI)
    canonical = parsed.replace(tzinfo=_SHANGHAI)
    if parsed.utcoffset() != canonical.utcoffset():
        raise ValueError("trade_time timezone must be Asia/Shanghai")
    return canonical


def _nonnegative_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("numeric values cannot be bool")
    converted = Decimal(str(value))
    if not converted.is_finite() or (converted.is_signed() and not converted.is_zero()):
        raise ValueError("numeric value must be finite and non-negative")
    _require_safe_decimal_shape(converted)
    return converted


def _require_safe_decimal_shape(value: Decimal) -> None:
    _sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("numeric exponent must be finite")
    if len(digits) > _MAX_NORMALIZED_INTEGER_DIGITS:
        raise ValueError("numeric coefficient exceeds the safe digit limit")
    if exponent >= 0:
        expanded = len(digits) + exponent
    else:
        expanded = max(len(digits), -exponent + 1)
    if expanded > _MAX_NORMALIZED_INTEGER_DIGITS:
        raise ValueError("numeric expansion exceeds the safe digit limit")


def _price_fen(value: object) -> int:
    price_fen = _scaled_integer(value, places=2)
    if price_fen <= 0:
        raise ValueError("price must convert exactly to positive integer fen")
    return price_fen


def _scaled_integer(value: object, *, places: int) -> int:
    converted = _nonnegative_decimal(value)
    if converted.is_zero():
        return 0
    sign, digits, exponent = converted.as_tuple()
    shifted_exponent = int(exponent) + places
    integer_digits = digits
    if shifted_exponent < 0:
        fractional_count = -shifted_exponent
        if fractional_count >= len(digits) or any(digits[-fractional_count:]):
            raise ValueError("numeric value does not convert to an exact integer")
        integer_digits = digits[:-fractional_count]
    elif shifted_exponent > 0:
        if len(digits) + shifted_exponent > _MAX_NORMALIZED_INTEGER_DIGITS:
            raise ValueError("normalized integer exceeds the safe digit limit")
        integer_digits = digits + (0,) * shifted_exponent
    if len(integer_digits) > _MAX_NORMALIZED_INTEGER_DIGITS:
        raise ValueError("normalized integer exceeds the safe digit limit")
    result = 0
    for digit in integer_digits:
        result = result * 10 + digit
    return -result if sign else result


__all__ = ["TushareHistoricalMinuteProvider"]
