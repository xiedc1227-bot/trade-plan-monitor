"""Synchronous Tushare adapter for normalized A-share market data.

Provider values are validated and converted at this boundary. Retry, pacing,
thread-pool execution, and live entitlement checks belong to later runtime tasks.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Hashable
from datetime import date, datetime, timedelta
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import TypeVar
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import TypeAdapter, ValidationError
from requests import exceptions as requests_exceptions

from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    DailyBar,
    DailyLimit,
    Exchange,
    MinuteBar,
    ProviderCapabilities,
    ProviderCapabilityStatus,
    TradingDay,
)
from trade_plan_monitor.market_data.sessions import (
    DEFAULT_DATA_GRACE,
    SourceTimeLabel,
    SourceTimeMappingUnverifiedError,
    is_minute_usable,
    normalize_source_minute,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SYMBOL_ADAPTER = TypeAdapter(AShareSymbol)
_EXCHANGE_ADAPTER = TypeAdapter(Exchange)
_MAX_REALTIME_SYMBOLS = 10
_MAX_NORMALIZED_INTEGER_DIGITS = 640
_MINUTE_FIELDS = "ts_code,time,open,close,high,low,vol,amount"
_CURRENT_DAY_FIELDS = "ts_code,freq,time,open,close,high,low,vol,amount"
_TRADING_CALENDAR_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_DAILY_LIMIT_FIELDS = "trade_date,ts_code,up_limit,down_limit"
_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"
_ValueT = TypeVar("_ValueT")
_ROW_ERRORS = (
    DecimalException,
    KeyError,
    OverflowError,
    TypeError,
    ValidationError,
    ValueError,
)
_STATUS_CONTEXT = (
    r"(?:^|\b(?:http(?:/\d+(?:\.\d+)?)?(?:\s+status)?|status(?:\s+code)?|"
    r"error\s+code)\s*(?:(?:is|was)\s*)?[:=]?\s*)"
)
_STATUS_SUFFIX = r"(?!\w|[.][a-z0-9])"
_PERMISSION_STATUS_PATTERN = re.compile(rf"{_STATUS_CONTEXT}(?:401|403){_STATUS_SUFFIX}")
_RATE_LIMIT_STATUS_PATTERN = re.compile(rf"{_STATUS_CONTEXT}429{_STATUS_SUFFIX}")


class TushareErrorCode(StrEnum):
    """Stable adapter errors independent of Tushare's message wording."""

    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    ERROR = "ERROR"


class TushareFailureKind(StrEnum):
    """Content-free failure locations safe to retain in bounded audit evidence."""

    TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
    TRANSPORT_TLS = "TRANSPORT_TLS"
    TRANSPORT_CONNECTION = "TRANSPORT_CONNECTION"
    HTTP_STATUS = "HTTP_STATUS"
    PROVIDER_STATUS = "PROVIDER_STATUS"
    RESPONSE_DECODE = "RESPONSE_DECODE"
    RESPONSE_SCHEMA = "RESPONSE_SCHEMA"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    UNCLASSIFIED = "UNCLASSIFIED"


class TushareHTTPStatusClass(StrEnum):
    """Bounded HTTP status families without retaining a response or request."""

    REDIRECTION = "HTTP_3XX"
    CLIENT_ERROR = "HTTP_4XX"
    SERVER_ERROR = "HTTP_5XX"


class TushareProviderError(RuntimeError):
    """One sanitized provider or response failure."""

    def __init__(
        self,
        code: TushareErrorCode,
        operation: str,
        *,
        failure_kind: TushareFailureKind = TushareFailureKind.DOMAIN_VALIDATION,
        http_status_class: TushareHTTPStatusClass | None = None,
    ) -> None:
        if not isinstance(code, TushareErrorCode):
            raise TypeError("code must be a TushareErrorCode")
        if not isinstance(failure_kind, TushareFailureKind):
            raise TypeError("failure_kind must be a TushareFailureKind")
        if http_status_class is not None and not isinstance(
            http_status_class, TushareHTTPStatusClass
        ):
            raise TypeError("http_status_class must be a TushareHTTPStatusClass")
        self.code = code
        self.operation = operation
        self.failure_kind = failure_kind
        self.http_status_class = http_status_class
        super().__init__(f"Tushare {operation} failed ({code.value})")


class TushareMarketDataProvider:
    """Normalize one injected synchronous Tushare Pro client."""

    __slots__ = (
        "_client",
        "_grace",
        "_is_open_on",
        "_now",
        "_probe_symbol",
        "_source_time_label",
    )

    def __init__(
        self,
        client: object,
        *,
        now: Callable[[], datetime],
        is_open_on: Callable[[date], bool | None],
        source_time_label: SourceTimeLabel = SourceTimeLabel.UNVERIFIED,
        grace: timedelta = DEFAULT_DATA_GRACE,
        probe_symbol: str | None = None,
    ) -> None:
        if not callable(now):
            raise TypeError("now must be callable")
        if not callable(is_open_on):
            raise TypeError("is_open_on must be callable")
        if not isinstance(source_time_label, SourceTimeLabel):
            raise TypeError("source_time_label must be a SourceTimeLabel")
        if not isinstance(grace, timedelta):
            raise TypeError("grace must be a timedelta")
        if grace < timedelta(0):
            raise ValueError("grace cannot be negative")

        self._client = client
        self._now = now
        self._is_open_on = is_open_on
        self._source_time_label = source_time_label
        self._grace = grace
        self._probe_symbol = (
            self._validated_symbol(probe_symbol) if probe_symbol is not None else None
        )

    def probe_capabilities(self) -> ProviderCapabilities:
        """Probe all five provider surfaces without cross-capability short-circuiting."""

        probe_date = self._received_at().date()
        symbol = self._probe_symbol
        if symbol is None:
            realtime_status = ProviderCapabilityStatus.UNVERIFIED
            current_day_status = ProviderCapabilityStatus.UNVERIFIED
        else:
            realtime_status = self._probe_status(
                "rt_min",
                fields=_MINUTE_FIELDS,
                required={
                    "ts_code",
                    "time",
                    "open",
                    "close",
                    "high",
                    "low",
                    "vol",
                    "amount",
                },
                ts_code=symbol,
                freq="1MIN",
            )
            current_day_status = self._probe_status(
                "rt_min_daily",
                fields=_CURRENT_DAY_FIELDS,
                required={"freq", "time", "open", "close", "high", "low", "vol", "amount"},
                allow_minute_symbol_alias=True,
                ts_code=symbol,
                freq="1MIN",
            )

        calendar_status = self._probe_status(
            "trade_cal",
            fields=_TRADING_CALENDAR_FIELDS,
            required={"exchange", "cal_date", "is_open", "pretrade_date"},
            exchange="",
            start_date=self._date_argument(probe_date),
            end_date=self._date_argument(probe_date),
        )
        limit_status = self._probe_status(
            "stk_limit",
            fields=_DAILY_LIMIT_FIELDS,
            required={"trade_date", "ts_code", "up_limit", "down_limit"},
            trade_date=self._date_argument(probe_date),
        )
        if symbol is None:
            daily_status = ProviderCapabilityStatus.UNVERIFIED
        else:
            daily_status = self._probe_status(
                "daily",
                fields=_DAILY_FIELDS,
                required={
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                },
                ts_code=symbol,
                start_date=self._date_argument(probe_date),
                end_date=self._date_argument(probe_date),
            )
        return ProviderCapabilities(
            realtime_minutes=realtime_status,
            current_day_minutes=current_day_status,
            trading_calendar=calendar_status,
            daily_limits=limit_status,
            daily_bars=daily_status,
        )

    def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]:
        """Return completed normalized minutes for up to ten requested symbols."""

        requested = self._validated_symbols(symbols)
        self._require_verified_source_time()
        frame = self._fetch_frame(
            "rt_min",
            fields=_MINUTE_FIELDS,
            ts_code=",".join(requested),
            freq="1MIN",
        )
        self._require_columns(
            frame,
            "rt_min",
            {"ts_code", "time", "open", "close", "high", "low", "vol", "amount"},
        )
        return self._normalized_minutes(
            frame,
            symbol_column="ts_code",
            requested=frozenset(requested),
            require_current_day_frequency=False,
        )

    def current_day_minutes(self, symbol: str) -> list[MinuteBar]:
        """Return completed current-day minutes for one requested symbol."""

        requested_symbol = self._validated_symbol(symbol)
        self._require_verified_source_time()
        frame = self._fetch_frame(
            "rt_min_daily",
            fields=_CURRENT_DAY_FIELDS,
            ts_code=requested_symbol,
            freq="1MIN",
        )
        symbol_column = self._minute_daily_symbol_column(frame)
        self._require_columns(
            frame,
            "rt_min_daily",
            {symbol_column, "time", "open", "close", "high", "low", "vol", "amount"},
        )
        return self._normalized_minutes(
            frame,
            symbol_column=symbol_column,
            requested=frozenset({requested_symbol}),
            require_current_day_frequency=True,
        )

    def trading_calendar(
        self,
        start: date,
        end: date,
    ) -> list[TradingDay]:
        """Return normalized A-share calendar rows in the requested date range."""

        return self._trading_calendar("", start, end)

    def trading_calendar_for_exchange(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> list[TradingDay]:
        """Return calendar rows for one explicit historical exchange."""

        if type(exchange) is not str:
            raise TypeError("exchange must be a string")
        return self._trading_calendar(self._validated_exchange(exchange), start, end)

    def historical_trading_calendar_for_exchange(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> list[TradingDay]:
        """Return a fail-closed calendar response for historical synchronization."""

        if type(exchange) is not str:
            raise TypeError("exchange must be a string")
        return self._trading_calendar(
            self._validated_exchange(exchange),
            start,
            end,
            strict_response=True,
        )

    def _trading_calendar(
        self,
        exchange: str,
        start: date,
        end: date,
        *,
        strict_response: bool = False,
    ) -> list[TradingDay]:
        """Fetch and normalize calendar rows for the selected exchange."""

        self._validated_date_range(start, end)
        requested_exchange = self._validated_exchange(exchange) if exchange else None
        frame = self._fetch_frame(
            "trade_cal",
            fields=_TRADING_CALENDAR_FIELDS,
            exchange=exchange,
            start_date=self._date_argument(start),
            end_date=self._date_argument(end),
        )
        self._require_columns(
            frame,
            "trade_cal",
            {"exchange", "cal_date", "is_open", "pretrade_date"},
        )

        candidates: dict[Hashable, TradingDay] = {}
        rejected: set[Hashable] = set()
        for row in frame.to_dict(orient="records"):
            identity: Hashable | None = None
            try:
                row_exchange = self._validated_exchange(row["exchange"])
                cal_date = self._source_date(row["cal_date"])
                if requested_exchange is not None and row_exchange != requested_exchange:
                    if strict_response:
                        raise ValueError("calendar response contains another exchange")
                    continue
                if not start <= cal_date <= end:
                    if strict_response:
                        raise ValueError("calendar response contains an out-of-range date")
                    continue
                identity = (row_exchange, cal_date)
                value = TradingDay(
                    exchange=row_exchange,
                    cal_date=cal_date,
                    is_open=self._open_flag(row["is_open"]),
                    previous_trade_date=self._source_date(row["pretrade_date"]),
                )
            except _ROW_ERRORS:
                if strict_response:
                    raise TushareProviderError(
                        TushareErrorCode.INVALID_RESPONSE,
                        "trade_cal",
                    ) from None
                if identity is not None:
                    self._reject_identity(candidates, rejected, identity)
                continue
            if strict_response and identity in candidates:
                raise TushareProviderError(
                    TushareErrorCode.INVALID_RESPONSE,
                    "trade_cal",
                ) from None
            self._record_candidate(candidates, rejected, identity, value)

        return sorted(
            candidates.values(),
            key=lambda value: (value.cal_date, value.exchange),
        )

    def daily_limits(self, trade_date: date) -> list[DailyLimit]:
        """Return actual provider-supplied price limits for one trade date."""

        return self._daily_limits(trade_date, strict_response=False)

    def historical_daily_limits(self, trade_date: date) -> list[DailyLimit]:
        """Return fail-closed daily limits for historical synchronization."""

        return self._daily_limits(trade_date, strict_response=True)

    def _daily_limits(
        self,
        trade_date: date,
        *,
        strict_response: bool,
    ) -> list[DailyLimit]:
        """Fetch and normalize one daily-limit response."""

        self._validated_date(trade_date, name="trade_date")
        frame = self._fetch_frame(
            "stk_limit",
            fields=_DAILY_LIMIT_FIELDS,
            trade_date=self._date_argument(trade_date),
        )
        self._require_columns(
            frame,
            "stk_limit",
            {"trade_date", "ts_code", "up_limit", "down_limit"},
        )
        received_at = self._received_at()
        candidates: dict[Hashable, DailyLimit] = {}
        rejected: set[Hashable] = set()
        for row in frame.to_dict(orient="records"):
            identity: Hashable | None = None
            try:
                row_symbol = self._validated_symbol(row["ts_code"])
                row_date = self._source_date(row["trade_date"])
                if row_date != trade_date:
                    if strict_response:
                        raise ValueError("daily-limit response contains another date")
                    continue
                identity = (row_symbol, row_date)
                value = DailyLimit(
                    symbol=row_symbol,
                    trade_date=row_date,
                    up_limit_fen=self._price_fen(row["up_limit"]),
                    down_limit_fen=self._price_fen(row["down_limit"]),
                    received_at=received_at,
                )
            except _ROW_ERRORS:
                if strict_response:
                    raise TushareProviderError(
                        TushareErrorCode.INVALID_RESPONSE,
                        "stk_limit",
                    ) from None
                if identity is not None:
                    self._reject_identity(candidates, rejected, identity)
                continue
            if strict_response and identity in candidates:
                raise TushareProviderError(
                    TushareErrorCode.INVALID_RESPONSE,
                    "stk_limit",
                ) from None
            self._record_candidate(candidates, rejected, identity, value)

        return sorted(
            candidates.values(),
            key=lambda value: (value.symbol, value.trade_date),
        )

    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        """Return official unadjusted daily bars converted to shares and yuan."""

        return self._daily_bars(symbol, start, end, strict_response=False)

    def historical_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[DailyBar]:
        """Return fail-closed daily bars for historical synchronization."""

        return self._daily_bars(symbol, start, end, strict_response=True)

    def _daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        *,
        strict_response: bool,
    ) -> list[DailyBar]:
        """Fetch and normalize one daily-bar response."""

        requested_symbol = self._validated_symbol(symbol)
        self._validated_date_range(start, end)
        frame = self._fetch_frame(
            "daily",
            fields=_DAILY_FIELDS,
            ts_code=requested_symbol,
            start_date=self._date_argument(start),
            end_date=self._date_argument(end),
        )
        self._require_columns(
            frame,
            "daily",
            {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"},
        )
        received_at = self._received_at()
        candidates: dict[Hashable, DailyBar] = {}
        rejected: set[Hashable] = set()
        for row in frame.to_dict(orient="records"):
            identity: Hashable | None = None
            try:
                row_symbol = self._validated_symbol(row["ts_code"])
                row_date = self._source_date(row["trade_date"])
                if row_symbol != requested_symbol or not start <= row_date <= end:
                    if strict_response:
                        raise ValueError("daily response contains another requested identity")
                    continue
                identity = (row_symbol, row_date)
                value = DailyBar(
                    symbol=row_symbol,
                    trade_date=row_date,
                    open_fen=self._price_fen(row["open"]),
                    high_fen=self._price_fen(row["high"]),
                    low_fen=self._price_fen(row["low"]),
                    close_fen=self._price_fen(row["close"]),
                    volume_shares=self._scaled_integer(row["vol"], places=2),
                    amount_yuan=self._shift_decimal(row["amount"], places=3),
                    is_official=True,
                    received_at=received_at,
                )
            except _ROW_ERRORS:
                if strict_response:
                    raise TushareProviderError(
                        TushareErrorCode.INVALID_RESPONSE,
                        "daily",
                    ) from None
                if identity is not None:
                    self._reject_identity(candidates, rejected, identity)
                continue
            if strict_response and identity in candidates:
                raise TushareProviderError(
                    TushareErrorCode.INVALID_RESPONSE,
                    "daily",
                ) from None
            self._record_candidate(candidates, rejected, identity, value)

        return sorted(
            candidates.values(),
            key=lambda value: (value.symbol, value.trade_date),
        )

    def _fetch_frame(self, operation: str, *, fields: str, **kwargs: object) -> pd.DataFrame:
        provider_error: TushareProviderError | None = None
        try:
            endpoint = getattr(self._client, operation)
            frame = endpoint(fields=fields, **kwargs)
        except Exception as error:
            provider_error = self._safe_provider_error(operation, error)
        if provider_error is not None:
            raise provider_error
        if not isinstance(frame, pd.DataFrame):
            raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, operation)
        return frame

    def _probe_status(
        self,
        operation: str,
        *,
        fields: str,
        required: set[str],
        allow_minute_symbol_alias: bool = False,
        **kwargs: object,
    ) -> ProviderCapabilityStatus:
        try:
            frame = self._fetch_frame(operation, fields=fields, **kwargs)
            if allow_minute_symbol_alias:
                required = {*required, self._minute_daily_symbol_column(frame)}
            self._require_columns(frame, operation, required)
        except TushareProviderError as error:
            if error.code is TushareErrorCode.BLOCKED_PERMISSION:
                return ProviderCapabilityStatus.BLOCKED_PERMISSION
            if error.code is TushareErrorCode.RATE_LIMITED:
                return ProviderCapabilityStatus.RATE_LIMITED
            return ProviderCapabilityStatus.ERROR
        return ProviderCapabilityStatus.READY

    @staticmethod
    def _safe_provider_error(operation: str, error: Exception) -> TushareProviderError:
        if isinstance(error, TushareProviderError):
            return error
        structured_code = TushareMarketDataProvider._structured_http_error_code(error)
        if structured_code is not None:
            code = structured_code
            return TushareProviderError(
                code,
                operation,
                failure_kind=TushareFailureKind.HTTP_STATUS,
                http_status_class=TushareMarketDataProvider._http_status_class(error),
            )
        if isinstance(error, requests_exceptions.Timeout):
            return TushareProviderError(
                TushareErrorCode.TIMEOUT,
                operation,
                failure_kind=TushareMarketDataProvider._transport_failure_kind(
                    error, TushareFailureKind.TRANSPORT_TIMEOUT
                ),
            )
        if isinstance(error, requests_exceptions.SSLError):
            return TushareProviderError(
                TushareErrorCode.TRANSIENT,
                operation,
                failure_kind=TushareFailureKind.TRANSPORT_TLS,
            )
        if isinstance(error, requests_exceptions.ConnectionError):
            return TushareProviderError(
                TushareErrorCode.TRANSIENT,
                operation,
                failure_kind=TushareMarketDataProvider._transport_failure_kind(
                    error, TushareFailureKind.TRANSPORT_CONNECTION
                ),
            )
        message = str(error).casefold()
        if any(
            marker in message
            for marker in (
                "permission",
                "forbidden",
                "unauthorized",
                "无权限",
                "权限",
            )
        ) or _PERMISSION_STATUS_PATTERN.search(message):
            code = TushareErrorCode.BLOCKED_PERMISSION
        elif any(
            marker in message
            for marker in ("rate limit", "too many requests", "频率", "每分钟")
        ) or _RATE_LIMIT_STATUS_PATTERN.search(message):
            code = TushareErrorCode.RATE_LIMITED
        elif any(
            marker in message
            for marker in ("timeout", "timed out", "connection", "temporarily unavailable")
        ):
            code = TushareErrorCode.TRANSIENT
        else:
            code = TushareErrorCode.ERROR
        return TushareProviderError(
            code,
            operation,
            failure_kind=(
                TushareFailureKind.PROVIDER_STATUS
                if code is not TushareErrorCode.ERROR
                else TushareFailureKind.UNCLASSIFIED
            ),
        )

    @staticmethod
    def safe_failure_metadata(operation: str, error: Exception) -> dict[str, str | None]:
        """Return only fixed-enum diagnostic fields suitable for audit persistence."""

        classified = TushareMarketDataProvider._safe_provider_error(operation, error)
        return {
            "code": classified.code.value,
            "failureKind": classified.failure_kind.value,
            "httpStatusClass": (
                None
                if classified.http_status_class is None
                else classified.http_status_class.value
            ),
        }

    @staticmethod
    def _transport_failure_kind(
        error: Exception,
        default: TushareFailureKind,
    ) -> TushareFailureKind:
        kind = getattr(error, "_tushare_failure_kind", None)
        return kind if isinstance(kind, TushareFailureKind) else default

    @staticmethod
    def _http_status_class(error: Exception) -> TushareHTTPStatusClass | None:
        if not isinstance(error, requests_exceptions.HTTPError) or error.response is None:
            return None
        status_code = getattr(error.response, "status_code", None)
        if type(status_code) is not int:
            return None
        if 300 <= status_code <= 399:
            return TushareHTTPStatusClass.REDIRECTION
        if 400 <= status_code <= 499:
            return TushareHTTPStatusClass.CLIENT_ERROR
        if 500 <= status_code <= 599:
            return TushareHTTPStatusClass.SERVER_ERROR
        return None

    @staticmethod
    def _structured_http_error_code(error: Exception) -> TushareErrorCode | None:
        if not isinstance(error, requests_exceptions.HTTPError):
            return None
        response = error.response
        if response is None:
            return None
        status_code = getattr(response, "status_code", None)
        if type(status_code) is not int or not 100 <= status_code <= 599:
            return None
        if status_code in (401, 403):
            return TushareErrorCode.BLOCKED_PERMISSION
        if status_code == 429:
            return TushareErrorCode.RATE_LIMITED
        if status_code == 408 or 500 <= status_code <= 599:
            return TushareErrorCode.TRANSIENT
        return TushareErrorCode.ERROR

    @staticmethod
    def _require_columns(
        frame: pd.DataFrame,
        operation: str,
        required: set[str],
    ) -> None:
        counts = Counter(frame.columns)
        if any(counts[column] != 1 for column in required):
            raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, operation)

    @staticmethod
    def _minute_daily_symbol_column(frame: pd.DataFrame) -> str:
        aliases = {name for name in ("ts_code", "code") if name in frame.columns}
        if len(aliases) != 1:
            raise TushareProviderError(
                TushareErrorCode.INVALID_RESPONSE,
                "rt_min_daily",
            )
        return aliases.pop()

    def _normalized_minutes(
        self,
        frame: pd.DataFrame,
        *,
        symbol_column: str,
        requested: frozenset[str],
        require_current_day_frequency: bool,
    ) -> list[MinuteBar]:
        received_at = self._received_at()
        candidates: dict[Hashable, MinuteBar] = {}
        rejected: set[Hashable] = set()

        for row in frame.to_dict(orient="records"):
            identity: Hashable | None = None
            try:
                symbol = self._validated_symbol(row[symbol_column])
                if symbol not in requested:
                    continue
                source_time = self._source_datetime(row["time"])
                is_open = self._is_open_on(source_time.date())
                bar_end = normalize_source_minute(
                    source_time,
                    label=self._source_time_label,
                    is_open=is_open,
                )
                identity = (symbol, bar_end)
                if require_current_day_frequency and (
                    ("freq" in row and row["freq"] != "1MIN")
                    or source_time.date() != received_at.date()
                ):
                    raise ValueError("current-day minute row has invalid frequency or date")
                if not is_minute_usable(
                    bar_end,
                    as_of=received_at,
                    is_open=is_open,
                    grace=self._grace,
                ):
                    continue
                bar = MinuteBar(
                    symbol=symbol,
                    bar_end=bar_end,
                    open_fen=self._price_fen(row["open"]),
                    high_fen=self._price_fen(row["high"]),
                    low_fen=self._price_fen(row["low"]),
                    close_fen=self._price_fen(row["close"]),
                    volume_shares=self._scaled_integer(row["vol"], places=0),
                    amount_yuan=self._nonnegative_decimal(row["amount"]),
                    received_at=received_at,
                )
            except _ROW_ERRORS:
                if identity is not None:
                    self._reject_identity(candidates, rejected, identity)
                continue
            self._record_candidate(candidates, rejected, identity, bar)

        return sorted(candidates.values(), key=lambda value: (value.symbol, value.bar_end))

    def _received_at(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now must return an Asia/Shanghai-aware datetime")
        canonical = value.replace(tzinfo=_SHANGHAI)
        if value.utcoffset() != canonical.utcoffset():
            raise ValueError("now must return an Asia/Shanghai-aware datetime")
        return canonical

    @staticmethod
    def _record_candidate(
        candidates: dict[Hashable, _ValueT],
        rejected: set[Hashable],
        identity: Hashable,
        value: _ValueT,
    ) -> None:
        if identity in rejected:
            return
        existing = candidates.get(identity)
        if existing is None:
            candidates[identity] = value
        elif existing != value:
            TushareMarketDataProvider._reject_identity(candidates, rejected, identity)

    @staticmethod
    def _reject_identity(
        candidates: dict[Hashable, _ValueT],
        rejected: set[Hashable],
        identity: Hashable,
    ) -> None:
        candidates.pop(identity, None)
        rejected.add(identity)

    def _require_verified_source_time(self) -> None:
        if self._source_time_label is SourceTimeLabel.UNVERIFIED:
            raise SourceTimeMappingUnverifiedError("source time label mapping is UNVERIFIED")

    @staticmethod
    def _source_datetime(value: object) -> datetime:
        if isinstance(value, str):
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise TypeError("minute time must be a datetime or canonical string")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=_SHANGHAI)
        return parsed

    @staticmethod
    def _source_date(value: object) -> date:
        if isinstance(value, str):
            return datetime.strptime(value, "%Y%m%d").date()
        if isinstance(value, datetime) or not isinstance(value, date):
            raise TypeError("provider date must be a date or YYYYMMDD string")
        return value

    @staticmethod
    def _open_flag(value: object) -> bool:
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value in ("0", "1"):
            return value == "1"
        raise ValueError("is_open must be encoded as 0 or 1")

    @staticmethod
    def _nonnegative_decimal(value: object) -> Decimal:
        if isinstance(value, bool):
            raise TypeError("numeric values cannot be bool")
        converted = Decimal(str(value))
        if not converted.is_finite() or (converted.is_signed() and not converted.is_zero()):
            raise ValueError("numeric value must be finite and non-negative")
        return converted

    @classmethod
    def _price_fen(cls, value: object) -> int:
        price_fen = cls._scaled_integer(value, places=2)
        if price_fen <= 0:
            raise ValueError("price must convert exactly to positive integer fen")
        return price_fen

    @classmethod
    def _scaled_integer(cls, value: object, *, places: int) -> int:
        converted = cls._nonnegative_decimal(value)
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

    @classmethod
    def _shift_decimal(cls, value: object, *, places: int) -> Decimal:
        converted = cls._nonnegative_decimal(value)
        sign, digits, exponent = converted.as_tuple()
        shifted_exponent = int(exponent) + places
        return Decimal((sign, digits, shifted_exponent))

    @staticmethod
    def _validated_symbol(value: object) -> str:
        try:
            return _SYMBOL_ADAPTER.validate_python(value)
        except ValidationError as error:
            raise ValueError("symbol must be a canonical A-share code") from error

    @staticmethod
    def _validated_exchange(value: object) -> str:
        try:
            return _EXCHANGE_ADAPTER.validate_python(value)
        except ValidationError as error:
            raise ValueError("exchange must be SSE, SZSE, or BSE") from error

    @classmethod
    def _validated_symbols(cls, symbols: tuple[str, ...]) -> tuple[str, ...]:
        if type(symbols) is not tuple:
            raise TypeError("symbols must be a tuple")
        if not 1 <= len(symbols) <= _MAX_REALTIME_SYMBOLS:
            raise ValueError("symbols must contain between one and ten values")
        validated = tuple(cls._validated_symbol(symbol) for symbol in symbols)
        if len(set(validated)) != len(validated):
            raise ValueError("symbols cannot contain duplicates")
        return validated

    @staticmethod
    def _validated_date(value: object, *, name: str) -> date:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise TypeError(f"{name} must be a date")
        return value

    @classmethod
    def _validated_date_range(cls, start: object, end: object) -> tuple[date, date]:
        valid_start = cls._validated_date(start, name="start")
        valid_end = cls._validated_date(end, name="end")
        if valid_start > valid_end:
            raise ValueError("start cannot be after end")
        return valid_start, valid_end

    @staticmethod
    def _date_argument(value: date) -> str:
        return value.strftime("%Y%m%d")


__all__ = [
    "TushareErrorCode",
    "TushareFailureKind",
    "TushareHTTPStatusClass",
    "TushareMarketDataProvider",
    "TushareProviderError",
]
