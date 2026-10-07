"""Incremental historical synchronization with background request admission."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from threading import local
from time import monotonic, sleep
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.backtest.control import (
    BacktestOperationPhase,
    BacktestProgressCallback,
    CancellationToken,
    check_cancelled,
    report_progress,
    validate_operation_controls,
)
from trade_plan_monitor.backtest.dataset import DatasetScope, exchange_for_symbol
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProvider
from trade_plan_monitor.runtime.request_control import (
    LIVE_TUSHARE_MIN_INTERVAL,
    RequestPriority,
    TushareOperation,
)

_T = TypeVar("_T")


class HistoricalRequestController(Protocol):
    """Minimum async request-control surface needed by historical sync."""

    def execute(
        self,
        operation: TushareOperation,
        call: Callable[[], _T],
        *,
        work_key: str,
        priority: RequestPriority,
    ) -> Awaitable[_T]: ...


class _InlineHistoricalRequestController:
    """Execute one provider call inline on the coordinator-owned worker thread."""

    async def execute(
        self,
        _operation: TushareOperation,
        call: Callable[[], _T],
        *,
        work_key: str,
        priority: RequestPriority,
    ) -> _T:
        if not work_key.startswith("backtest:"):
            raise ValueError("historical work_key must use the backtest namespace")
        if priority is not RequestPriority.BACKGROUND:
            raise ValueError("historical sync must use background priority")
        return call()


class BacktestSyncResult(BaseModel):
    """Sanitized count-only outcome; provider bodies and secrets are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    calendar_rows: int = Field(ge=0)
    minute_days: int = Field(ge=0)
    daily_limit_rows: int = Field(ge=0)
    daily_bar_rows: int = Field(ge=0)
    network_calls: int = Field(ge=0)


class BacktestSyncService:
    """Fetch only missing historical surfaces and persist after each network call."""

    def __init__(
        self,
        *,
        provider: HistoricalMinuteProvider,
        store: BacktestMarketStore,
        request_controller: HistoricalRequestController,
        today: Callable[[], date],
    ) -> None:
        required = (
            "trading_calendar",
            "historical_minute_batch",
            "daily_limits",
            "daily_bars",
        )
        if any(not callable(getattr(provider, name, None)) for name in required):
            raise TypeError("provider does not satisfy HistoricalMinuteProvider")
        if not isinstance(store, BacktestMarketStore):
            raise TypeError("store must be a BacktestMarketStore")
        if not callable(getattr(request_controller, "execute", None)):
            raise TypeError("request_controller must expose execute")
        if not callable(today):
            raise TypeError("today must be callable")
        self._provider = provider
        self._store = store
        self._controller = request_controller
        self._today = today
        self._last_request_started_at: float | None = None

    async def sync(
        self,
        scope: DatasetScope,
        *,
        refresh: bool = False,
        cancellation_token: CancellationToken | None = None,
        progress_callback: BacktestProgressCallback | None = None,
    ) -> BacktestSyncResult:
        """Synchronize a closed range; network calls never overlap DB transactions."""

        if not isinstance(scope, DatasetScope):
            raise TypeError("scope must be a DatasetScope")
        if type(refresh) is not bool:
            raise TypeError("refresh must be a bool")
        validate_operation_controls(cancellation_token, progress_callback)
        check_cancelled(cancellation_token, "SYNC_CALENDAR")
        today = self._today()
        if isinstance(today, datetime) or not isinstance(today, date):
            raise TypeError("today must return a date")
        if scope.end >= today:
            raise ValueError("backtest sync accepts closed historical dates only")

        calendar_rows = 0
        minute_days = 0
        limit_rows = 0
        daily_rows = 0
        network_calls = 0
        exchanges = tuple(sorted({exchange_for_symbol(symbol) for symbol in scope.symbols}))
        unsupported = tuple(exchange for exchange in exchanges if exchange not in {"SSE", "SZSE"})
        if unsupported:
            raise ValueError(f"UNSUPPORTED_HISTORICAL_CALENDAR:{unsupported[0]}")
        missing_exchanges = tuple(
            exchange
            for exchange in exchanges
            if refresh
            or any(
                not self._store.has_head(f"CALENDAR:{exchange}:{day.isoformat()}")
                for day in _dates(scope.warmup_start, scope.end)
            )
        )
        for completed_calendars, exchange in enumerate(missing_exchanges, start=1):
            calendar = tuple(
                await self._execute(
                    TushareOperation.TRADING_CALENDAR,
                    lambda exchange=exchange: self._provider.trading_calendar(
                        exchange,
                        scope.warmup_start,
                        scope.end,
                    ),
                    work_key=(
                        f"backtest:calendar:{exchange}:{scope.warmup_start.isoformat()}:"
                        f"{scope.end.isoformat()}"
                    ),
                    cancellation_token=cancellation_token,
                    phase="SYNC_CALENDAR",
                )
            )
            _require_exact_identities(
                calendar,
                expected=frozenset(
                    (exchange, day) for day in _dates(scope.warmup_start, scope.end)
                ),
                identity=lambda item: (item.exchange, item.cal_date),
                surface="trade_cal",
            )
            self._store.record_trading_days(calendar)
            calendar_rows += len(calendar)
            network_calls += 1
            report_progress(
                progress_callback,
                phase="SYNC_CALENDAR",
                completed_units=completed_calendars,
                total_units=len(missing_exchanges),
            )
            check_cancelled(cancellation_token, "SYNC_CALENDAR")

        check_cancelled(cancellation_token, "SYNC_DAILY")
        open_dates = tuple(
            day
            for day in _dates(scope.warmup_start, scope.end)
            if any(
                (calendar := self._store.current_trading_day(exchange, day)) is not None
                and calendar.is_open
                for exchange in exchanges
            )
        )

        symbol_work: list[tuple[str, tuple[date, ...], tuple[date, ...], tuple[date, ...]]] = []
        for symbol in scope.symbols:
            symbol_exchange = exchange_for_symbol(symbol)
            symbol_open_dates = tuple(
                day
                for day in open_dates
                if (calendar := self._store.current_trading_day(symbol_exchange, day)) is not None
                and calendar.is_open
            )
            missing_daily = tuple(
                day
                for day in symbol_open_dates
                if refresh or not self._store.has_head(f"DAILY:{symbol}:{day.isoformat()}")
            )
            missing_minutes = tuple(
                day
                for day in symbol_open_dates
                if day >= scope.start
                and (refresh or not self._store.has_head(f"MINUTE:{symbol}:{day.isoformat()}"))
            )
            symbol_work.append((symbol, symbol_open_dates, missing_daily, missing_minutes))

        daily_total = sum(bool(missing_daily) for _, _, missing_daily, _ in symbol_work)
        minute_total = sum(len(missing_minutes) for _, _, _, missing_minutes in symbol_work)
        completed_daily = 0
        completed_minutes = 0
        for symbol, _symbol_open_dates, missing_daily, missing_minutes in symbol_work:
            check_cancelled(cancellation_token, "SYNC_DAILY")
            if missing_daily:
                daily = tuple(
                    await self._execute(
                        TushareOperation.DAILY_BARS,
                        lambda symbol=symbol, missing_daily=missing_daily: (
                            self._provider.daily_bars(
                                symbol,
                                missing_daily[0],
                                missing_daily[-1],
                            )
                        ),
                        work_key=(
                            f"backtest:daily:{symbol}:{missing_daily[0].isoformat()}:"
                            f"{missing_daily[-1].isoformat()}"
                        ),
                        cancellation_token=cancellation_token,
                        phase="SYNC_DAILY",
                    ),
                )
                requested_range = frozenset(
                    (symbol, day)
                    for day in _symbol_open_dates
                    if missing_daily[0] <= day <= missing_daily[-1]
                )
                _require_exact_identities(
                    daily,
                    expected=requested_range,
                    identity=lambda item: (item.symbol, item.trade_date),
                    surface="daily",
                )
                selected_daily = tuple(
                    item
                    for item in daily
                    if item.symbol == symbol and item.trade_date in missing_daily
                )
                self._store.record_daily_bars(selected_daily)
                daily_rows += len(selected_daily)
                network_calls += 1
                completed_daily += 1
                report_progress(
                    progress_callback,
                    phase="SYNC_DAILY",
                    completed_units=completed_daily,
                    total_units=daily_total,
                )
                check_cancelled(cancellation_token, "SYNC_DAILY")

            for day in missing_minutes:
                check_cancelled(cancellation_token, "SYNC_MINUTE")
                batch = await self._execute(
                    TushareOperation.HISTORICAL_MINUTES,
                    lambda symbol=symbol, day=day: self._provider.historical_minute_batch(
                        symbol,
                        day,
                    ),
                    work_key=f"backtest:minutes:{symbol}:{day.isoformat()}",
                    cancellation_token=cancellation_token,
                    phase="SYNC_MINUTE",
                )
                if batch.symbol != symbol or batch.trade_date != day:
                    raise ValueError("INVALID_RESPONSE:stk_mins")
                self._store.record_minute_batch(batch)
                minute_days += 1
                network_calls += 1
                completed_minutes += 1
                report_progress(
                    progress_callback,
                    phase="SYNC_MINUTE",
                    completed_units=completed_minutes,
                    total_units=minute_total,
                )
                check_cancelled(cancellation_token, "SYNC_MINUTE")

        check_cancelled(cancellation_token, "SYNC_LIMIT")
        limit_work: list[tuple[date, tuple[str, ...]]] = []
        for day in (value for value in open_dates if value >= scope.start):
            missing_symbols = tuple(
                symbol
                for symbol in scope.symbols
                if exchange_for_symbol(symbol)
                in {
                    exchange
                    for exchange in exchanges
                    if (calendar := self._store.current_trading_day(exchange, day)) is not None
                    and calendar.is_open
                }
                and (refresh or not self._store.has_head(f"LIMIT:{symbol}:{day.isoformat()}"))
            )
            if not missing_symbols:
                continue
            limit_work.append((day, missing_symbols))

        for completed_limits, (day, missing_symbols) in enumerate(limit_work, start=1):
            check_cancelled(cancellation_token, "SYNC_LIMIT")
            limits = tuple(
                await self._execute(
                    TushareOperation.DAILY_LIMITS,
                    lambda day=day: self._provider.daily_limits(day),
                    work_key=f"backtest:limits:{day.isoformat()}",
                    cancellation_token=cancellation_token,
                    phase="SYNC_LIMIT",
                )
            )
            selected_limits = tuple(item for item in limits if item.symbol in missing_symbols)
            _require_exact_identities(
                selected_limits,
                expected=frozenset((symbol, day) for symbol in missing_symbols),
                identity=lambda item: (item.symbol, item.trade_date),
                surface="stk_limit",
            )
            self._store.record_daily_limits(selected_limits)
            limit_rows += len(selected_limits)
            network_calls += 1
            report_progress(
                progress_callback,
                phase="SYNC_LIMIT",
                completed_units=completed_limits,
                total_units=len(limit_work),
            )
            check_cancelled(cancellation_token, "SYNC_LIMIT")

        return BacktestSyncResult(
            calendar_rows=calendar_rows,
            minute_days=minute_days,
            daily_limit_rows=limit_rows,
            daily_bar_rows=daily_rows,
            network_calls=network_calls,
        )

    async def _execute(
        self,
        operation: TushareOperation,
        call: Callable[[], _T],
        *,
        work_key: str,
        cancellation_token: CancellationToken | None,
        phase: BacktestOperationPhase,
    ) -> _T:
        check_cancelled(cancellation_token, phase)

        def guarded_call() -> _T:
            # The existing single worker serializes sync. Pace inside its callback
            # so controller admission delays (or existing retries) cannot bunch starts.
            if self._last_request_started_at is not None:
                deadline = (
                    self._last_request_started_at + LIVE_TUSHARE_MIN_INTERVAL.total_seconds()
                )
                while (remaining := deadline - monotonic()) > 0:
                    check_cancelled(cancellation_token, phase)
                    sleep(min(remaining, 0.05))
            check_cancelled(cancellation_token, phase)
            self._last_request_started_at = monotonic()
            return call()

        return await self._controller.execute(
            operation,
            guarded_call,
            work_key=work_key,
            priority=RequestPriority.BACKGROUND,
        )


class BlockingBacktestSyncCore:
    """Blocking worker facade that owns no executor or request-controller thread."""

    _worker_pacing = local()

    def __init__(
        self,
        *,
        provider: HistoricalMinuteProvider,
        store: BacktestMarketStore,
        today: Callable[[], date],
    ) -> None:
        self._service = BacktestSyncService(
            provider=provider,
            store=store,
            request_controller=_InlineHistoricalRequestController(),
            today=today,
        )

    def sync(
        self,
        scope: DatasetScope,
        *,
        refresh: bool = False,
        cancellation_token: CancellationToken | None = None,
        progress_callback: BacktestProgressCallback | None = None,
    ) -> BacktestSyncResult:
        """Run the existing workflow inline; only the outer coordinator owns a thread."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("blocking historical sync cannot run in an event loop")
        # Production creates a fresh core for each job on the same owned worker.
        # Carry only its request-start time across jobs, including failed/cancelled syncs.
        self._service._last_request_started_at = getattr(
            self._worker_pacing, "last_request_started_at", None,
        )
        try:
            return asyncio.run(
                self._service.sync(
                    scope,
                    refresh=refresh,
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                )
            )
        finally:
            self._worker_pacing.last_request_started_at = self._service._last_request_started_at


BacktestBlockingSyncService = BlockingBacktestSyncCore


def _dates(start: date, end: date) -> tuple[date, ...]:
    values: list[date] = []
    cursor = start
    while cursor <= end:
        values.append(cursor)
        cursor += timedelta(days=1)
    return tuple(values)


def _require_exact_identities[T](
    values: tuple[T, ...],
    *,
    expected: frozenset[object],
    identity: Callable[[T], object],
    surface: str,
) -> None:
    """Fail before persistence when a fetched surface is partial or ambiguous."""

    try:
        actual = tuple(identity(value) for value in values)
    except AttributeError, TypeError, ValueError:
        raise ValueError(f"INVALID_RESPONSE:{surface}") from None
    if len(actual) != len(expected) or frozenset(actual) != expected:
        raise ValueError(f"INVALID_RESPONSE:{surface}")


__all__ = [
    "BacktestBlockingSyncService",
    "BacktestSyncResult",
    "BacktestSyncService",
    "BlockingBacktestSyncCore",
    "HistoricalRequestController",
]
