"""Bounded realtime batch orchestration with per-symbol failure isolation."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.models import AShareSymbol, MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_data.provider import MarketDataProvider
from trade_plan_monitor.market_data.sessions import session_for_minute_end
from trade_plan_monitor.runtime.clock import Clock, _canonical_shanghai
from trade_plan_monitor.runtime.health import (
    SymbolHealthErrorCode,
    SymbolHealthSnapshot,
    SymbolHealthTracker,
    SystemHealthSnapshot,
    summarize_system_health,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestPriority,
    TushareOperation,
    TushareRequestController,
)

_MAX_ACTIVE_SYMBOLS = 10
_MAX_PROVIDER_ROWS = 1_000
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")

ActiveSymbols = Callable[[], tuple[str, ...]]
PersistMinutes = Callable[[tuple[MinuteBar, ...]], None]
LoadMinutes = Callable[..., tuple[MinuteBar, ...]]
PersistFiveMinute = Callable[[FiveMinuteBar], None]
IsOpenOn = Callable[[date], bool | None]


def _ceil_to_whole_second(value: datetime) -> datetime:
    canonical = _canonical_shanghai(value)
    if canonical.microsecond:
        canonical += timedelta(seconds=1)
    return canonical.replace(microsecond=0)


class SymbolHealthRestoreState(BaseModel):
    """Exact durable health scoped to one active-plan generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: str
    activation_revision: int = Field(ge=1)
    snapshot: SymbolHealthSnapshot | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not _SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("symbol must use a canonical A-share identity")
        if self.snapshot is not None and self.snapshot.symbol != self.symbol:
            raise ValueError("health snapshot must match its activation symbol")
        return self


class _RuntimeContextValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class SymbolRuntimeContext(_RuntimeContextValue):
    """Immutable normalized facts assembled for one symbol and bucket."""

    symbol: AShareSymbol
    bar_end: ShanghaiDatetime
    minutes: tuple[MinuteBar, ...] = Field(default=(), max_length=5)
    five_minute_bar: FiveMinuteBar | None
    health: SymbolHealthSnapshot

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if session_for_minute_end(self.bar_end) is None:
            raise ValueError("symbol context must target a canonical monitoring minute")
        if self.health.symbol != self.symbol or self.health.target_end != self.bar_end:
            raise ValueError("symbol context health must match its identity")
        if any(minute.symbol != self.symbol for minute in self.minutes):
            raise ValueError("symbol context minutes must match its symbol")
        if self.five_minute_bar is not None and (
            self.five_minute_bar.symbol != self.symbol
            or self.five_minute_bar.bar_end != self.bar_end
        ):
            raise ValueError("five-minute aggregate must match its symbol context")
        return self


class RealtimeBatchResult(_RuntimeContextValue):
    """One bounded batch result containing isolated immutable contexts."""

    bar_end: ShanghaiDatetime
    observed_at: ShanghaiDatetime
    contexts: tuple[SymbolRuntimeContext, ...] = Field(
        default=(),
        max_length=_MAX_ACTIVE_SYMBOLS,
    )
    health: SystemHealthSnapshot

    def context_for(self, symbol: str) -> SymbolRuntimeContext:
        for context in self.contexts:
            if context.symbol == symbol:
                return context
        raise KeyError(symbol)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.health.observed_at != self.observed_at:
            raise ValueError("batch and system health observations must match")
        if tuple(item.health for item in self.contexts) != self.health.symbols:
            raise ValueError("batch contexts and system health must remain aligned")
        if any(item.bar_end != self.bar_end for item in self.contexts):
            raise ValueError("batch contexts must share one market target")
        return self


class SymbolService:
    """Fetch one active-symbol batch and isolate persistence/context failures."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        request_controller: TushareRequestController,
        active_symbols: ActiveSymbols,
        persist_minutes: PersistMinutes,
        load_minutes: LoadMinutes,
        persist_five_minute: PersistFiveMinute,
        is_open_on: IsOpenOn,
        health_tracker: SymbolHealthTracker,
        clock: Clock | None = None,
        progress_unit=None,
    ) -> None:
        dependencies = (
            active_symbols,
            persist_minutes,
            load_minutes,
            persist_five_minute,
            is_open_on,
        )
        if any(not callable(dependency) for dependency in dependencies):
            raise TypeError("symbol service dependencies must be callable")
        if not isinstance(request_controller, TushareRequestController):
            raise TypeError("request_controller must be a TushareRequestController")
        if not isinstance(health_tracker, SymbolHealthTracker):
            raise TypeError("health_tracker must be a SymbolHealthTracker")
        if clock is not None and not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        self._provider = provider
        self._request_controller = request_controller
        self._active_symbols = active_symbols
        self._persist_minutes = persist_minutes
        self._load_minutes = load_minutes
        self._persist_five_minute = persist_five_minute
        self._is_open_on = is_open_on
        self._health_tracker = health_tracker
        self._clock = clock
        self._progress_unit = progress_unit or (lambda **_kwargs: nullcontext())
        self._hydrated_generations: dict[str, int] = {}

    def restore_health(
        self,
        *,
        symbols: tuple[str, ...],
        states: tuple[SymbolHealthRestoreState, ...],
    ) -> None:
        """Restore validated durable tracker state before acquiring a new batch."""

        requested = set(self._validated_active_symbols(symbols))
        if type(states) is not tuple or any(
            type(state) is not SymbolHealthRestoreState for state in states
        ):
            raise TypeError("health restore states must be an exact tuple")
        state_by_symbol = {state.symbol: state for state in states}
        if len(state_by_symbol) != len(states) or set(state_by_symbol) != requested:
            raise ValueError("health restore states must match the active symbols exactly")
        self._hydrated_generations = {
            symbol: revision
            for symbol, revision in self._hydrated_generations.items()
            if symbol in requested
        }
        for symbol in symbols:
            state = state_by_symbol[symbol]
            if self._hydrated_generations.get(symbol) == state.activation_revision:
                continue
            self._health_tracker.replace(symbol, state.snapshot)
            self._hydrated_generations[symbol] = state.activation_revision

    async def run_realtime_batch(
        self,
        *,
        bar_end: datetime,
        observed_at: datetime,
        symbols: tuple[str, ...] | None = None,
    ) -> RealtimeBatchResult:
        """Run one canonical-minute batch without cross-symbol cancellation."""

        if session_for_minute_end(bar_end) is None:
            raise ValueError("bar_end must be a canonical monitoring minute")
        observed_at = _ceil_to_whole_second(observed_at)
        if observed_at < bar_end:
            raise ValueError("batch observation cannot precede its market target")
        required_bucket = five_minute_bucket_end(bar_end) == bar_end
        expected = expected_five_minute_ends(bar_end) if required_bucket else (bar_end,)
        symbols = self._validated_active_symbols(
            self._active_symbols() if symbols is None else symbols
        )
        self._health_tracker.retain_only(symbols)
        if not symbols:
            observed_at = await self._post_fetch_observed_at(observed_at)
            return RealtimeBatchResult(
                bar_end=bar_end,
                observed_at=observed_at,
                contexts=(),
                health=summarize_system_health(observed_at=observed_at, symbols=()),
            )

        with self._progress_unit(timeout_seconds=90):
            acquisition = await self._acquire_and_validate_rows(
                symbols=symbols, bar_end=bar_end, observed_at=observed_at,
                required_bucket=required_bucket,
            )
        if isinstance(acquisition, RealtimeBatchResult):
            return acquisition
        observed_at, rows_by_symbol, invalid_symbols, calendar_ready = acquisition
        contexts = tuple(
            self._build_symbol_context(
                symbol=symbol,
                bar_end=bar_end,
                observed_at=observed_at,
                expected=expected,
                rows=rows_by_symbol.get(symbol, ()),
                invalid=symbol in invalid_symbols,
                missing_current=symbol not in rows_by_symbol,
                required_bucket=required_bucket,
                calendar_ready=calendar_ready,
            )
            for symbol in symbols
        )
        health = summarize_system_health(
            observed_at=observed_at,
            symbols=tuple(context.health for context in contexts),
        )
        return RealtimeBatchResult(
            bar_end=bar_end,
            observed_at=observed_at,
            contexts=contexts,
            health=health,
        )

    async def _acquire_and_validate_rows(
        self, *, symbols, bar_end, observed_at, required_bucket,
    ):
        try:
            raw_rows = await self._request_controller.execute(
                TushareOperation.REALTIME_MINUTES,
                lambda: self._provider.realtime_minutes(symbols),
                work_key="realtime:stock",
                priority=RequestPriority.MARKET_DEADLINE,
            )
        except RequestControlError:
            observed_at = await self._post_fetch_observed_at(observed_at)
            return self._blocked_batch(
                symbols=symbols,
                bar_end=bar_end,
                observed_at=observed_at,
                error_code=SymbolHealthErrorCode.PROVIDER_BLOCKED,
                required_bucket=required_bucket,
            )
        observed_at = await self._post_fetch_observed_at(observed_at)

        if type(raw_rows) is not list or len(raw_rows) > _MAX_PROVIDER_ROWS:
            return self._blocked_batch(
                symbols=symbols,
                bar_end=bar_end,
                observed_at=observed_at,
                error_code=SymbolHealthErrorCode.INVALID_CONTEXT,
                required_bucket=required_bucket,
            )

        rows_by_symbol, invalid_symbols = self._isolate_rows(
            raw_rows,
            symbols=symbols,
            expected={bar_end},
        )
        try:
            calendar_ready = self._is_open_on(bar_end.date()) is True
        except Exception:
            calendar_ready = False
        return observed_at, rows_by_symbol, invalid_symbols, calendar_ready


    async def _post_fetch_observed_at(self, requested_at: datetime) -> datetime:
        observed_at = _ceil_to_whole_second(requested_at)
        if self._clock is None:
            return observed_at
        now = _canonical_shanghai(self._clock.now())
        observed_at = max(observed_at, _ceil_to_whole_second(now))
        if now < observed_at:
            await self._clock.sleep_until(observed_at)
            if _canonical_shanghai(self._clock.now()) < observed_at:
                raise RuntimeError("clock returned before the realtime observation boundary")
        return observed_at

    def _build_symbol_context(
        self, **kwargs,
    ) -> SymbolRuntimeContext:
        with self._progress_unit(timeout_seconds=30):
            return self._build_symbol_context_local(**kwargs)

    def _build_symbol_context_local(
        self,
        *,
        symbol: str,
        bar_end: datetime,
        observed_at: datetime,
        expected: tuple[datetime, ...],
        rows: tuple[MinuteBar, ...],
        invalid: bool,
        missing_current: bool,
        required_bucket: bool,
        calendar_ready: bool,
    ) -> SymbolRuntimeContext:
        error_code = SymbolHealthErrorCode.INVALID_CONTEXT if invalid else None
        if error_code is None:
            for row in rows:
                try:
                    self._persist_minutes((row,))
                except Exception:
                    error_code = SymbolHealthErrorCode.PERSISTENCE_FAILED
                    break

        loaded: tuple[MinuteBar, ...] = ()
        health_minutes: tuple[MinuteBar, ...] = ()
        aggregate: FiveMinuteBar | None = None
        if error_code is None:
            try:
                retained_gaps = self._health_tracker.gaps_for(
                    symbol,
                    trade_date=bar_end.date(),
                )
                allowed_ends = set((*expected, *retained_gaps))
                loaded_range = self._load_minutes(
                    symbol,
                    start=min(allowed_ends),
                    end=expected[-1],
                )
                if type(loaded_range) is not tuple:
                    raise TypeError("minute loader must return a tuple")
                if any(not isinstance(minute, MinuteBar) for minute in loaded_range):
                    raise TypeError("minute loader must return normalized MinuteBar values")
                if any(
                    minute.symbol != symbol
                    or not min(allowed_ends) <= minute.bar_end <= expected[-1]
                    for minute in loaded_range
                ):
                    raise ValueError("loaded minutes must match the requested symbol and range")
                if len({minute.bar_end for minute in loaded_range}) != len(loaded_range):
                    raise ValueError("loaded minutes cannot contain duplicate identities")
                if missing_current:
                    loaded_range = tuple(
                        minute for minute in loaded_range if minute.bar_end != bar_end
                    )
                health_minutes = tuple(
                    sorted(
                        (minute for minute in loaded_range if minute.bar_end in allowed_ends),
                        key=lambda minute: minute.bar_end,
                    )
                )
                loaded = tuple(minute for minute in health_minutes if minute.bar_end in expected)
            except TypeError, ValueError:
                loaded = ()
                error_code = SymbolHealthErrorCode.INVALID_CONTEXT
            except Exception:
                loaded = ()
                error_code = SymbolHealthErrorCode.PERSISTENCE_FAILED

        if error_code is None and not calendar_ready:
            error_code = SymbolHealthErrorCode.CALENDAR_BLOCKED
        elif error_code is None and required_bucket:
            try:
                aggregate = aggregate_five_minute_bar(
                    loaded,
                    bucket_end=bar_end,
                    is_open=True,
                )
                if aggregate is not None:
                    try:
                        self._persist_five_minute(aggregate)
                    except Exception:
                        aggregate = None
                        error_code = SymbolHealthErrorCode.PERSISTENCE_FAILED
            except TypeError, ValueError:
                aggregate = None
                error_code = SymbolHealthErrorCode.INVALID_CONTEXT

        try:
            if required_bucket:
                health = self._health_tracker.record_bucket(
                    symbol=symbol,
                    bucket_end=bar_end,
                    observed_at=observed_at,
                    minutes=health_minutes,
                    blocked_error_code=error_code,
                )
            else:
                health = self._health_tracker.record_minute(
                    symbol=symbol,
                    bar_end=bar_end,
                    observed_at=observed_at,
                    minutes=health_minutes,
                    blocked_error_code=error_code,
                )
        except TypeError, ValueError:
            loaded = ()
            aggregate = None
            if required_bucket:
                health = self._health_tracker.record_bucket(
                    symbol=symbol,
                    bucket_end=bar_end,
                    observed_at=observed_at,
                    minutes=(),
                    blocked_error_code=SymbolHealthErrorCode.INVALID_CONTEXT,
                )
            else:
                health = self._health_tracker.record_minute(
                    symbol=symbol,
                    bar_end=bar_end,
                    observed_at=observed_at,
                    minutes=(),
                    blocked_error_code=SymbolHealthErrorCode.INVALID_CONTEXT,
                )
        return SymbolRuntimeContext(
            symbol=symbol,
            bar_end=bar_end,
            minutes=loaded,
            five_minute_bar=aggregate,
            health=health,
        )

    def _blocked_batch(
        self,
        *,
        symbols: tuple[str, ...],
        bar_end: datetime,
        observed_at: datetime,
        error_code: SymbolHealthErrorCode,
        required_bucket: bool,
    ) -> RealtimeBatchResult:
        contexts: list[SymbolRuntimeContext] = []
        for symbol in symbols:
            health = (
                self._health_tracker.record_bucket(
                    symbol=symbol,
                    bucket_end=bar_end,
                    observed_at=observed_at,
                    minutes=(),
                    blocked_error_code=error_code,
                )
                if required_bucket
                else self._health_tracker.record_minute(
                    symbol=symbol,
                    bar_end=bar_end,
                    observed_at=observed_at,
                    minutes=(),
                    blocked_error_code=error_code,
                )
            )
            contexts.append(
                SymbolRuntimeContext(
                    symbol=symbol,
                    bar_end=bar_end,
                    minutes=(),
                    five_minute_bar=None,
                    health=health,
                )
            )
        context_tuple = tuple(contexts)
        health = summarize_system_health(
            observed_at=observed_at,
            symbols=tuple(context.health for context in context_tuple),
        )
        return RealtimeBatchResult(
            bar_end=bar_end,
            observed_at=observed_at,
            contexts=context_tuple,
            health=health,
        )

    @staticmethod
    def _validated_active_symbols(value: object) -> tuple[str, ...]:
        if type(value) is not tuple:
            raise TypeError("active symbols must be a tuple")
        if len(value) > _MAX_ACTIVE_SYMBOLS:
            raise ValueError("at most 10 active symbols are supported")
        if any(
            type(symbol) is not str or _SYMBOL_PATTERN.fullmatch(symbol) is None for symbol in value
        ):
            raise ValueError("active symbols must be canonical A-share symbols")
        if len(value) != len(set(value)):
            raise ValueError("active symbols must be unique")
        return value

    @staticmethod
    def _isolate_rows(
        rows: list[object],
        *,
        symbols: tuple[str, ...],
        expected: set[datetime],
    ) -> tuple[dict[str, tuple[MinuteBar, ...]], set[str]]:
        requested = set(symbols)
        isolated: dict[str, dict[datetime, MinuteBar]] = {}
        invalid: set[str] = set()
        for row in rows:
            if not isinstance(row, MinuteBar) or row.symbol not in requested:
                continue
            if row.bar_end not in expected:
                invalid.add(row.symbol)
                continue
            by_identity = isolated.setdefault(row.symbol, {})
            previous = by_identity.get(row.bar_end)
            if previous is not None and previous != row:
                invalid.add(row.symbol)
            else:
                by_identity[row.bar_end] = row
        for symbol in invalid:
            isolated.pop(symbol, None)
        return (
            {
                symbol: tuple(row for _, row in sorted(by_identity.items()))
                for symbol, by_identity in isolated.items()
            },
            invalid,
        )


__all__ = ["RealtimeBatchResult", "SymbolRuntimeContext", "SymbolService"]
