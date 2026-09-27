"""Serial current-day recovery with explicit gap targeting and realtime yielding."""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.market_data.models import AShareSymbol, MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_data.provider import MarketDataProvider
from trade_plan_monitor.market_data.sessions import session_for_minute_end
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.runtime.recovery_targets import (
    MinuteCoverage,
    RecoveryTarget,
    check_minute_coverage,
    select_current_day_rows,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestNotStartedError,
    RequestPriority,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.repositories import RepositoryError

_MAX_ACTIVE_SYMBOLS = 10
_MAX_RECOVERY_BARS = 240
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


ActiveSymbols = Callable[[], tuple[str, ...]]
PersistMinutes = Callable[[tuple[MinuteBar, ...]], None]
IsOpenOn = Callable[[date], bool | None]
RealtimePending = Callable[[], bool]
PendingCloseDate = Callable[[str], date | None]
RecoverPendingClose = Callable[[str, date], Awaitable[bool]]
ReadPersistedEnds = Callable[[str, tuple[datetime, ...]], tuple[datetime, ...]]


class RecoveryMode(StrEnum):
    """The bounded reason for one current-day recovery pass."""

    STARTUP = "STARTUP"
    GAP_REPAIR = "GAP_REPAIR"


class RecoveryErrorCode(StrEnum):
    """Stable recovery failures that contain no provider or storage details."""

    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    ERROR = "ERROR"
    QUEUE_FULL = "QUEUE_FULL"
    CLOSED = "CLOSED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class RecoveryAdmissionChangedError(RuntimeError):
    """A frozen acquisition lost authority and must be captured again."""


@dataclass(frozen=True)
class ScopedRecoveryResult:
    """Minute evidence only, never plan readiness or permission to evaluate.

    Storage failures are visible faults; callers must not treat them as normal
    provider retry. A complete slice says nothing about other plan prerequisites.
    """

    symbol: str
    target: RecoveryTarget
    coverage: MinuteCoverage
    error_code: RecoveryErrorCode | None = None
    next_retry_at: datetime | None = None
    yielded_to_realtime: bool = False
    retarget_required: bool = False
    persistence_error: Exception | None = field(default=None, repr=False, compare=False)
    request_error: RequestControlError | None = field(default=None, repr=False, compare=False)

    @property
    def ready(self) -> bool:
        return (
            self.target.completed_minute_end is not None
            and self.coverage.complete
            and self.error_code is None
            and not self.yielded_to_realtime
            and not self.retarget_required
        )


class _RecoveryValue(BaseModel):
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


class RecoverySymbolResult(_RecoveryValue):
    """Sanitized outcome for one serial current-day provider call."""

    symbol: AShareSymbol
    requested_gaps: tuple[ShanghaiDatetime, ...] = Field(
        default=(),
        max_length=_MAX_RECOVERY_BARS,
    )
    recovered_ends: tuple[ShanghaiDatetime, ...] = Field(
        default=(),
        max_length=_MAX_RECOVERY_BARS,
    )
    remaining_gaps: tuple[ShanghaiDatetime, ...] = Field(
        default=(),
        max_length=_MAX_RECOVERY_BARS,
    )
    error_code: RecoveryErrorCode | None = None
    next_retry_at: ShanghaiDatetime | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        for name, values in (
            ("requested_gaps", self.requested_gaps),
            ("recovered_ends", self.recovered_ends),
            ("remaining_gaps", self.remaining_gaps),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be unique and strictly ordered")
            if any(session_for_minute_end(value) is None for value in values):
                raise ValueError(f"{name} must contain canonical monitoring minutes")
        if self.requested_gaps:
            requested = set(self.requested_gaps)
            if not set(self.recovered_ends).issubset(requested):
                raise ValueError("targeted recovery cannot report unrequested minutes")
            if not set(self.remaining_gaps).issubset(requested):
                raise ValueError("remaining gaps must come from the requested gaps")
            if set(self.recovered_ends) & set(self.remaining_gaps):
                raise ValueError("recovered and remaining gap identities cannot overlap")
            if set(self.recovered_ends) | set(self.remaining_gaps) != requested:
                raise ValueError("recovered and remaining identities must partition requested gaps")
        elif self.remaining_gaps:
            raise ValueError("startup recovery cannot report unrequested remaining gaps")
        if self.error_code is not None and self.recovered_ends:
            raise ValueError("failed recovery cannot report persisted bars")
        if self.next_retry_at is not None and self.error_code is None:
            raise ValueError("next_retry_at requires a recovery error")
        return self


class PendingCloseRecoveryResult(_RecoveryValue):
    """Sanitized startup retry outcome for one durable CLOSE_PENDING target."""

    symbol: AShareSymbol
    trade_date: date
    resolved: bool = Field(strict=True)
    error_code: RecoveryErrorCode | None = None

    @model_validator(mode="after")
    def validate_pending_result(self) -> Self:
        if isinstance(self.trade_date, datetime):
            raise ValueError("pending close trade_date must be a calendar date")
        if self.resolved and self.error_code is not None:
            raise ValueError("resolved pending close cannot retain an error")
        return self


class RecoveryBatchResult(_RecoveryValue):
    """One bounded serial recovery pass with no hidden background ownership."""

    mode: RecoveryMode
    trade_date: date
    results: tuple[RecoverySymbolResult, ...] = Field(
        default=(),
        max_length=_MAX_ACTIVE_SYMBOLS,
    )
    pending_close_results: tuple[PendingCloseRecoveryResult, ...] = Field(
        default=(),
        max_length=_MAX_ACTIVE_SYMBOLS,
    )
    yielded_to_realtime: bool = False

    @property
    def attempted_symbols(self) -> tuple[str, ...]:
        return tuple(result.symbol for result in self.results)

    @property
    def persisted_bar_count(self) -> int:
        return sum(len(result.recovered_ends) for result in self.results)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if isinstance(self.trade_date, datetime):
            raise ValueError("recovery trade_date must be a calendar date")
        symbols = self.attempted_symbols
        if len(set(symbols)) != len(symbols):
            raise ValueError("a recovery pass cannot attempt one symbol twice")
        pending_symbols = tuple(result.symbol for result in self.pending_close_results)
        if len(set(pending_symbols)) != len(pending_symbols):
            raise ValueError("startup recovery cannot retry one pending close twice")
        if any(result.trade_date > self.trade_date for result in self.pending_close_results):
            raise ValueError("pending close cannot follow the startup date")
        observed_dates = {
            value.date()
            for result in self.results
            for value in (result.requested_gaps + result.recovered_ends + result.remaining_gaps)
        }
        if observed_dates and observed_dates != {self.trade_date}:
            raise ValueError("recovery identities must match the recovery trade date")
        return self


class RecoveryService:
    """Coordinate serial ``rt_min_daily`` work without delaying known realtime work."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        request_controller: TushareRequestController,
        active_symbols: ActiveSymbols,
        persist_minutes: PersistMinutes,
        is_open_on: IsOpenOn,
        realtime_pending: RealtimePending,
        pending_close_date: PendingCloseDate | None = None,
        recover_pending_close: RecoverPendingClose | None = None,
    ) -> None:
        dependencies = (active_symbols, persist_minutes, is_open_on, realtime_pending)
        if any(not callable(dependency) for dependency in dependencies):
            raise TypeError("recovery service dependencies must be callable")
        if not callable(getattr(provider, "current_day_minutes", None)):
            raise TypeError("provider must expose current_day_minutes")
        if not isinstance(request_controller, TushareRequestController):
            raise TypeError("request_controller must be a TushareRequestController")
        if (pending_close_date is None) != (recover_pending_close is None):
            raise TypeError("pending close lookup and recovery must be configured together")
        if pending_close_date is not None and not callable(pending_close_date):
            raise TypeError("pending_close_date must be callable")
        if recover_pending_close is not None and not callable(recover_pending_close):
            raise TypeError("recover_pending_close must be callable")
        self._provider = provider
        self._request_controller = request_controller
        self._active_symbols = active_symbols
        self._persist_minutes = persist_minutes
        self._is_open_on = is_open_on
        self._realtime_pending = realtime_pending
        self._pending_close_date = pending_close_date
        self._recover_pending_close = recover_pending_close
        self._serial = asyncio.Lock()
        self._physical_condition = threading.Condition()
        self._physical_active = False

    async def recover_scope(
        self,
        *,
        symbol: str,
        target: RecoveryTarget,
        required_ends: tuple[datetime, ...],
        read_persisted_ends: ReadPersistedEnds,
        now: Callable[[], datetime],
        persist_selected: PersistMinutes | None = None,
        admission_current: Callable[[], bool] | None = None,
        fetch_current_day: Callable[[], object] | None = None,
        cancelled: threading.Event | None = None,
    ) -> ScopedRecoveryResult:
        """Acquire at most one symbol and verify its bounded persisted requirement.

        This opt-in seam does not run the legacy startup batch. The caller owns
        requirements, target recomputation, plan identity fencing and scheduling;
        ``read_persisted_ends`` must read committed facts for the supplied symbol.
        Current-day data cannot repair missing history from earlier sessions.
        """

        self._validated_active_symbols((symbol,))
        if not isinstance(target, RecoveryTarget):
            raise TypeError("target must be a RecoveryTarget")
        if not callable(read_persisted_ends) or not callable(now):
            raise TypeError("scoped recovery requires persistence and clock callbacks")
        cutoff = target.completed_minute_end or target.observed_at
        empty = check_minute_coverage(
            required_ends=required_ends, persisted_ends=(), cutoff=cutoff,
        )
        result = ScopedRecoveryResult(symbol, target, empty)

        cancelled = cancelled if cancelled is not None else threading.Event()

        def clock_matches() -> bool:
            current = _canonical_shanghai(now())
            return (
                current >= target.observed_at and current.date() == target.observed_at.date()
                and not cancelled.is_set()
                and (admission_current is None or admission_current())
            )

        def read_coverage() -> MinuteCoverage:
            return check_minute_coverage(
                required_ends=required_ends,
                persisted_ends=read_persisted_ends(symbol, required_ends), cutoff=cutoff,
            )

        async with self._serial:
            if not clock_matches():
                return replace(result, retarget_required=True)
            try:
                result = replace(result, coverage=read_coverage())
            except RecoveryAdmissionChangedError:
                return replace(result, retarget_required=True)
            except (OSError, SQLAlchemyError, RepositoryError) as error:
                return replace(result, error_code=RecoveryErrorCode.PERSISTENCE_FAILED,
                               persistence_error=error)
            if not clock_matches():
                return replace(result, retarget_required=True)
            if result.ready or target.completed_minute_end is None:
                return result
            current_missing = tuple(
                value for value in result.coverage.missing_ends
                if value.date() == target.observed_at.date()
            )
            if target.trade_date != target.observed_at.date() or not current_missing:
                return result
            if self._should_yield():
                return replace(result, yielded_to_realtime=True)
            try:
                raw_rows = await self._execute_joined(
                    symbol=symbol, before_start=clock_matches,
                    fetch_current_day=fetch_current_day, cancelled=cancelled,
                )
            except RequestNotStartedError:
                return replace(result, retarget_required=True)
            except RequestControlError as error:
                return replace(
                    result, error_code=RecoveryErrorCode(error.code.value),
                    next_retry_at=error.next_retry_at, retarget_required=not clock_matches(),
                    request_error=error,
                )
            if not clock_matches():
                return replace(result, retarget_required=True)
            if type(raw_rows) is not list:
                return replace(result, error_code=RecoveryErrorCode.INVALID_RESPONSE)
            try:
                rows = select_current_day_rows(
                    rows=tuple(raw_rows), symbol=symbol, target=target, now=now(),
                )
            except (TypeError, ValueError):
                return replace(result, error_code=RecoveryErrorCode.INVALID_RESPONSE)
            selected = tuple(row for row in rows if row.bar_end in current_missing)
            try:
                if selected:
                    (persist_selected or self._persist_minutes)(selected)
                result = replace(result, coverage=read_coverage())
            except RecoveryAdmissionChangedError:
                return replace(result, retarget_required=True)
            except (OSError, SQLAlchemyError, RepositoryError) as error:
                return replace(result, error_code=RecoveryErrorCode.PERSISTENCE_FAILED,
                               persistence_error=error)
            return replace(result, retarget_required=not clock_matches())

    async def recover_startup(self, *, trade_date: date) -> RecoveryBatchResult:
        """Recover every active symbol once on a known-open current trading day."""

        normalized_date = self._trade_date(trade_date)
        symbols = self._validated_active_symbols(self._active_symbols())
        targets = (
            tuple((symbol, ()) for symbol in symbols) if self._known_open(normalized_date) else ()
        )
        return await self._run(
            mode=RecoveryMode.STARTUP,
            trade_date=normalized_date,
            targets=targets,
            pending_symbols=symbols,
        )

    async def repair_detected_gaps(
        self,
        *,
        trade_date: date,
        gaps: Mapping[str, tuple[datetime, ...]],
    ) -> RecoveryBatchResult:
        """Fetch only active symbols with explicit canonical current-day gaps."""

        normalized_date = self._trade_date(trade_date)
        symbols = self._validated_active_symbols(self._active_symbols())
        normalized_gaps = self._validated_gaps(gaps, trade_date=normalized_date)
        if not self._known_open(normalized_date):
            return RecoveryBatchResult(mode=RecoveryMode.GAP_REPAIR, trade_date=normalized_date)
        targets = tuple(
            (symbol, normalized_gaps[symbol]) for symbol in symbols if normalized_gaps.get(symbol)
        )
        return await self._run(
            mode=RecoveryMode.GAP_REPAIR,
            trade_date=normalized_date,
            targets=targets,
            pending_symbols=(),
        )

    async def _run(
        self,
        *,
        mode: RecoveryMode,
        trade_date: date,
        targets: tuple[tuple[str, tuple[datetime, ...]], ...],
        pending_symbols: tuple[str, ...],
    ) -> RecoveryBatchResult:
        results: list[RecoverySymbolResult] = []
        pending_results: list[PendingCloseRecoveryResult] = []
        yielded = False
        async with self._serial:
            for symbol in pending_symbols:
                if self._should_yield():
                    yielded = True
                    break
                pending_result = await self._recover_pending_symbol(
                    symbol=symbol,
                    startup_date=trade_date,
                )
                if pending_result is not None:
                    pending_results.append(pending_result)
            for symbol, requested_gaps in targets:
                if yielded:
                    break
                if self._should_yield():
                    yielded = True
                    break
                results.append(
                    await self._recover_symbol(
                        trade_date=trade_date,
                        symbol=symbol,
                        requested_gaps=requested_gaps,
                    )
                )
        return RecoveryBatchResult(
            mode=mode,
            trade_date=trade_date,
            results=tuple(results),
            pending_close_results=tuple(pending_results),
            yielded_to_realtime=yielded,
        )

    async def _recover_pending_symbol(
        self,
        *,
        symbol: str,
        startup_date: date,
    ) -> PendingCloseRecoveryResult | None:
        if self._pending_close_date is None or self._recover_pending_close is None:
            return None
        try:
            pending_date = self._pending_close_date(symbol)
        except Exception:
            return PendingCloseRecoveryResult(
                symbol=symbol,
                trade_date=startup_date,
                resolved=False,
                error_code=RecoveryErrorCode.INVALID_RESPONSE,
            )
        if pending_date is None:
            return None
        if (
            isinstance(pending_date, datetime)
            or not isinstance(pending_date, date)
            or pending_date > startup_date
        ):
            return PendingCloseRecoveryResult(
                symbol=symbol,
                trade_date=startup_date,
                resolved=False,
                error_code=RecoveryErrorCode.INVALID_RESPONSE,
            )
        try:
            resolved = await self._recover_pending_close(symbol, pending_date)
        except asyncio.CancelledError:
            raise
        except Exception:
            return PendingCloseRecoveryResult(
                symbol=symbol,
                trade_date=pending_date,
                resolved=False,
                error_code=RecoveryErrorCode.ERROR,
            )
        if type(resolved) is not bool:
            return PendingCloseRecoveryResult(
                symbol=symbol,
                trade_date=pending_date,
                resolved=False,
                error_code=RecoveryErrorCode.INVALID_RESPONSE,
            )
        return PendingCloseRecoveryResult(
            symbol=symbol,
            trade_date=pending_date,
            resolved=resolved,
        )

    async def _recover_symbol(
        self,
        *,
        trade_date: date,
        symbol: str,
        requested_gaps: tuple[datetime, ...],
    ) -> RecoverySymbolResult:
        try:
            raw_rows = await self._execute_joined(
                symbol=symbol,
            )
        except RequestControlError as error:
            return RecoverySymbolResult(
                symbol=symbol,
                requested_gaps=requested_gaps,
                remaining_gaps=requested_gaps,
                error_code=RecoveryErrorCode(error.code.value),
                next_retry_at=error.next_retry_at,
            )

        rows = self._validated_rows(raw_rows, symbol=symbol, trade_date=trade_date)
        if rows is None:
            return RecoverySymbolResult(
                symbol=symbol,
                requested_gaps=requested_gaps,
                remaining_gaps=requested_gaps,
                error_code=RecoveryErrorCode.INVALID_RESPONSE,
            )
        if requested_gaps:
            requested = set(requested_gaps)
            selected = tuple(row for row in rows if row.bar_end in requested)
        else:
            selected = rows
        if selected:
            try:
                self._persist_minutes(selected)
            except Exception:
                return RecoverySymbolResult(
                    symbol=symbol,
                    requested_gaps=requested_gaps,
                    remaining_gaps=requested_gaps,
                    error_code=RecoveryErrorCode.PERSISTENCE_FAILED,
                )
        recovered = tuple(row.bar_end for row in selected)
        remaining = tuple(value for value in requested_gaps if value not in set(recovered))
        return RecoverySymbolResult(
            symbol=symbol,
            requested_gaps=requested_gaps,
            recovered_ends=recovered,
            remaining_gaps=remaining,
        )

    async def _execute_joined(
        self,
        *,
        symbol: str,
        before_start: Callable[[], bool] | None = None,
        fetch_current_day: Callable[[], object] | None = None,
        cancelled: threading.Event | None = None,
    ) -> object:
        cancelled = cancelled if cancelled is not None else threading.Event()
        request = asyncio.create_task(
            self._request_controller.execute(
                TushareOperation.CURRENT_DAY_MINUTES,
                lambda: self._current_day_call(
                    symbol, before_start=before_start,
                    fetch_current_day=fetch_current_day,
                ),
                work_key=f"recovery:{symbol}",
                priority=RequestPriority.RECOVERY,
            )
        )
        try:
            return await asyncio.shield(request)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await request
            except Exception:
                pass
            raise
        finally:
            await self._join_physical_idle()

    def _current_day_call(
        self, symbol: str, *, before_start: Callable[[], bool] | None = None,
        fetch_current_day: Callable[[], object] | None = None,
    ) -> object:
        if before_start is not None and not before_start():
            raise RequestNotStartedError("recovery target changed before provider start")
        with self._physical_condition:
            if self._physical_active:
                raise TushareProviderError(
                    TushareErrorCode.TRANSIENT,
                    "rt_min_daily",
                ) from None
            self._physical_active = True
        try:
            if fetch_current_day is not None:
                return fetch_current_day()
            return self._provider.current_day_minutes(symbol)
        finally:
            with self._physical_condition:
                self._physical_active = False
                self._physical_condition.notify_all()

    def _wait_for_physical_idle(self) -> None:
        with self._physical_condition:
            self._physical_condition.wait_for(lambda: not self._physical_active)

    async def _join_physical_idle(self) -> None:
        with self._physical_condition:
            if not self._physical_active:
                return
        waiter = asyncio.create_task(asyncio.to_thread(self._wait_for_physical_idle))
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            await waiter
            raise

    @staticmethod
    def _validated_rows(
        raw_rows: object,
        *,
        symbol: str,
        trade_date: date,
    ) -> tuple[MinuteBar, ...] | None:
        if type(raw_rows) is not list or len(raw_rows) > _MAX_RECOVERY_BARS:
            return None
        by_end: dict[datetime, MinuteBar] = {}
        for row in raw_rows:
            if not isinstance(row, MinuteBar):
                return None
            if (
                row.symbol != symbol
                or row.bar_end.date() != trade_date
                or session_for_minute_end(row.bar_end) is None
            ):
                return None
            previous = by_end.get(row.bar_end)
            if previous is not None and previous != row:
                return None
            by_end[row.bar_end] = row
        return tuple(by_end[value] for value in sorted(by_end))

    @staticmethod
    def _trade_date(value: date) -> date:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise TypeError("trade_date must be a date")
        return value

    @staticmethod
    def _validated_active_symbols(symbols: object) -> tuple[str, ...]:
        if type(symbols) is not tuple:
            raise TypeError("active_symbols must return a tuple")
        if len(symbols) > _MAX_ACTIVE_SYMBOLS:
            raise ValueError("recovery supports at most 10 active symbols")
        if any(
            type(symbol) is not str or _SYMBOL_PATTERN.fullmatch(symbol) is None
            for symbol in symbols
        ):
            raise ValueError("active symbols must use canonical A-share identities")
        if len(set(symbols)) != len(symbols):
            raise ValueError("active symbols must be unique")
        return symbols

    @staticmethod
    def _validated_gaps(
        gaps: Mapping[str, tuple[datetime, ...]],
        *,
        trade_date: date,
    ) -> dict[str, tuple[datetime, ...]]:
        if not isinstance(gaps, Mapping):
            raise TypeError("gaps must be a mapping")
        if len(gaps) > _MAX_ACTIVE_SYMBOLS:
            raise ValueError("gap repair supports at most 10 symbols")
        normalized: dict[str, tuple[datetime, ...]] = {}
        for symbol, values in gaps.items():
            if type(symbol) is not str or _SYMBOL_PATTERN.fullmatch(symbol) is None:
                raise ValueError("gap symbols must use canonical A-share identities")
            if type(values) is not tuple:
                raise TypeError("each gap collection must be a tuple")
            if len(values) > _MAX_RECOVERY_BARS:
                raise ValueError("one symbol cannot request more than 240 gaps")
            if any(
                not isinstance(value, datetime)
                or value.date() != trade_date
                or session_for_minute_end(value) is None
                for value in values
            ):
                raise ValueError("gaps must be canonical minutes on the recovery date")
            if values != tuple(sorted(set(values))):
                raise ValueError("gaps must be unique and strictly ordered")
            normalized[symbol] = values
        return normalized

    def _known_open(self, trade_date: date) -> bool:
        try:
            return self._is_open_on(trade_date) is True
        except Exception:
            return False

    def _should_yield(self) -> bool:
        try:
            return self._realtime_pending() is not False
        except Exception:
            return True


__all__ = [
    "PendingCloseRecoveryResult",
    "RecoveryBatchResult",
    "RecoveryErrorCode",
    "RecoveryMode",
    "RecoveryService",
    "RecoverySymbolResult",
    "ScopedRecoveryResult",
]
