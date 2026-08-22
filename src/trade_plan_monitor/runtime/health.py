"""Immutable per-symbol and batch health for realtime runtime orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.decision.models import DataHealthSnapshot, DataHealthStatus
from trade_plan_monitor.market_data.aggregation import expected_five_minute_ends
from trade_plan_monitor.market_data.models import AShareSymbol, MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_data.sessions import session_for_minute_end

_MAX_ACTIVE_SYMBOLS = 10
_MAX_GAPS = 240

NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]


class _RuntimeHealthValue(BaseModel):
    """Keep runtime health values closed, immutable, and copy-revalidated."""

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


class SymbolHealthErrorCode(StrEnum):
    """Stable sanitized reasons for non-live per-symbol runtime health."""

    INCOMPLETE_BUCKET = "INCOMPLETE_BUCKET"
    HISTORY_GAP = "HISTORY_GAP"
    STALE_DATA = "STALE_DATA"
    PROVIDER_BLOCKED = "PROVIDER_BLOCKED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    INVALID_CONTEXT = "INVALID_CONTEXT"
    CALENDAR_BLOCKED = "CALENDAR_BLOCKED"


class SymbolHealthSnapshot(_RuntimeHealthValue):
    """One isolated symbol's actionable data-health facts and gap state."""

    symbol: AShareSymbol
    observed_at: ShanghaiDatetime
    target_end: ShanghaiDatetime
    data_health: DataHealthSnapshot
    gaps: tuple[ShanghaiDatetime, ...] = Field(default=(), max_length=_MAX_GAPS)
    consecutive_incomplete_buckets: NonNegativeInteger
    error_code: SymbolHealthErrorCode | None

    @property
    def actionable(self) -> bool:
        """Return whether this snapshot can enter actionable evaluation."""

        return (
            self.data_health.status is DataHealthStatus.LIVE
            and self.data_health.required_data_complete
            and self.data_health.fresh
        )

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if session_for_minute_end(self.target_end) is None:
            raise ValueError("health target must be a canonical monitoring minute")
        if self.observed_at < self.target_end:
            raise ValueError("health observation cannot precede its target")
        if self.data_health.symbol != self.symbol:
            raise ValueError("data health symbol must match runtime health")
        if self.gaps != tuple(sorted(set(self.gaps))):
            raise ValueError("health gaps must be unique and strictly ordered")
        if any(gap > self.target_end for gap in self.gaps):
            raise ValueError("health gaps cannot follow the observed target")
        if self.actionable and (self.gaps or self.error_code is not None):
            raise ValueError("actionable health cannot retain a gap or error")
        if not self.actionable and self.error_code is None:
            raise ValueError("non-actionable health requires a stable error code")
        return self


class SystemHealthSnapshot(_RuntimeHealthValue):
    """One immutable current-batch summary without cross-symbol cancellation."""

    observed_at: ShanghaiDatetime
    symbols: tuple[SymbolHealthSnapshot, ...] = Field(
        default=(),
        max_length=_MAX_ACTIVE_SYMBOLS,
    )

    @property
    def active_symbol_count(self) -> int:
        return len(self.symbols)

    @property
    def live_symbol_count(self) -> int:
        return self._count(DataHealthStatus.LIVE)

    @property
    def stale_symbol_count(self) -> int:
        return self._count(DataHealthStatus.STALE)

    @property
    def gapped_symbol_count(self) -> int:
        return self._count(DataHealthStatus.GAPPED)

    @property
    def degraded_symbol_count(self) -> int:
        return self._count(DataHealthStatus.DEGRADED)

    @property
    def blocked_symbol_count(self) -> int:
        return self._count(DataHealthStatus.BLOCKED)

    @property
    def actionable_symbol_count(self) -> int:
        return sum(item.actionable for item in self.symbols)

    @property
    def all_symbols_actionable(self) -> bool:
        return bool(self.symbols) and self.actionable_symbol_count == len(self.symbols)

    @property
    def system_status(self) -> DataHealthStatus:
        statuses = {item.data_health.status for item in self.symbols}
        if not statuses:
            return DataHealthStatus.STARTING
        if len(statuses) > 1:
            return DataHealthStatus.DEGRADED
        return next(iter(statuses))

    def _count(self, status: DataHealthStatus) -> int:
        return sum(item.data_health.status is status for item in self.symbols)

    @model_validator(mode="after")
    def validate_symbols(self) -> Self:
        identities = tuple(item.symbol for item in self.symbols)
        if len(identities) != len(set(identities)):
            raise ValueError("system health symbols must be unique")
        if any(item.observed_at != self.observed_at for item in self.symbols):
            raise ValueError("system and symbol health observations must match")
        return self


class SymbolHealthTracker:
    """Track only the bounded state needed for per-symbol health transitions."""

    def __init__(self, *, stale_after: timedelta) -> None:
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        self._stale_after = stale_after
        self._snapshots: dict[str, SymbolHealthSnapshot] = {}
        self._gaps: dict[str, set[datetime]] = {}
        self._incomplete_streaks: dict[str, int] = {}
        self._last_required_bucket: dict[str, datetime] = {}

    def retain_only(self, symbols: tuple[str, ...]) -> None:
        """Discard disabled in-memory trackers so reactivation starts independently."""

        if type(symbols) is not tuple or len(symbols) > _MAX_ACTIVE_SYMBOLS:
            raise ValueError("active symbols must be a tuple capped at 10")
        active = set(symbols)
        self._snapshots = {
            symbol: snapshot for symbol, snapshot in self._snapshots.items() if symbol in active
        }
        self._gaps = {symbol: gaps for symbol, gaps in self._gaps.items() if symbol in active}
        self._incomplete_streaks = {
            symbol: streak
            for symbol, streak in self._incomplete_streaks.items()
            if symbol in active
        }
        self._last_required_bucket = {
            symbol: bucket
            for symbol, bucket in self._last_required_bucket.items()
            if symbol in active
        }

    def record_minute(
        self,
        *,
        symbol: str,
        bar_end: datetime,
        observed_at: datetime,
        minutes: tuple[MinuteBar, ...],
        blocked_error_code: SymbolHealthErrorCode | None = None,
    ) -> SymbolHealthSnapshot:
        """Record immediate completeness for one canonical realtime minute."""

        if session_for_minute_end(bar_end) is None:
            raise ValueError("bar_end must be a canonical monitoring minute")
        if type(minutes) is not tuple or len(minutes) > 1:
            raise ValueError("minute health input must be a tuple of at most one value")
        return self._record(
            symbol=symbol,
            target_end=bar_end,
            observed_at=observed_at,
            minutes=minutes,
            expected=(bar_end,),
            required_bucket=False,
            blocked_error_code=blocked_error_code,
        )

    def record_bucket(
        self,
        *,
        symbol: str,
        bucket_end: datetime,
        observed_at: datetime,
        minutes: tuple[MinuteBar, ...],
        blocked_error_code: SymbolHealthErrorCode | None = None,
    ) -> SymbolHealthSnapshot:
        """Record one required five-minute bucket without affecting another symbol."""

        expected = expected_five_minute_ends(bucket_end)
        if type(minutes) is not tuple or len(minutes) > len(expected):
            raise ValueError("bucket minutes must be a tuple of at most five values")
        return self._record(
            symbol=symbol,
            target_end=bucket_end,
            observed_at=observed_at,
            minutes=minutes,
            expected=expected,
            required_bucket=True,
            blocked_error_code=blocked_error_code,
        )

    def _record(
        self,
        *,
        symbol: str,
        target_end: datetime,
        observed_at: datetime,
        minutes: tuple[MinuteBar, ...],
        expected: tuple[datetime, ...],
        required_bucket: bool,
        blocked_error_code: SymbolHealthErrorCode | None,
    ) -> SymbolHealthSnapshot:
        if any(not isinstance(minute, MinuteBar) for minute in minutes):
            raise TypeError("bucket minutes must contain normalized MinuteBar values")
        if any(minute.symbol != symbol for minute in minutes):
            raise ValueError("bucket minutes must match the health symbol")
        minute_ends = tuple(minute.bar_end for minute in minutes)
        if len(minute_ends) != len(set(minute_ends)):
            raise ValueError("bucket minutes cannot contain duplicate identities")
        if any(minute_end not in expected for minute_end in minute_ends):
            raise ValueError("bucket minutes must belong to the required bucket")

        previous = self._snapshots.get(symbol)
        if previous is not None and target_end < previous.target_end:
            raise ValueError("health target cannot regress")
        if previous is not None and observed_at < previous.observed_at:
            raise ValueError("health observation time cannot regress")

        same_trade_date = previous is None or previous.target_end.date() == target_end.date()

        missing = set(expected).difference(minute_ends)
        retained_gaps = set(self._gaps.get(symbol, set())) if same_trade_date else set()
        retained_gaps.difference_update(minute_ends)
        retained_gaps.update(missing)
        gaps = tuple(sorted(retained_gaps))
        current_incomplete = bool(missing)
        incomplete_streak = self._incomplete_streaks.get(symbol, 0) if same_trade_date else 0
        last_required_bucket = self._last_required_bucket.get(symbol) if same_trade_date else None
        if required_bucket:
            same_bucket = last_required_bucket == target_end
            if current_incomplete:
                if not same_bucket:
                    incomplete_streak += 1
            else:
                incomplete_streak = 0
            last_required_bucket = target_end

        latest_candidates = [minute.bar_end for minute in minutes]
        if previous is not None and previous.data_health.latest_bar_end is not None:
            latest_candidates.append(previous.data_health.latest_bar_end)
        latest_bar_end = max(latest_candidates, default=None)
        data_age_seconds: int | None = None
        if latest_bar_end is not None:
            age = observed_at - latest_bar_end
            if age < timedelta(0):
                raise ValueError("health observation cannot precede latest market data")
            data_age_seconds = int(age.total_seconds())

        required_complete = not gaps and not current_incomplete and blocked_error_code is None
        fresh = (
            blocked_error_code is None
            and latest_bar_end is not None
            and observed_at - latest_bar_end <= self._stale_after
        )
        if blocked_error_code is not None:
            status = DataHealthStatus.BLOCKED
            error_code = blocked_error_code
        elif gaps:
            status = (
                DataHealthStatus.DEGRADED
                if current_incomplete and incomplete_streak >= 2
                else DataHealthStatus.GAPPED
            )
            error_code = (
                SymbolHealthErrorCode.INCOMPLETE_BUCKET
                if current_incomplete
                else SymbolHealthErrorCode.HISTORY_GAP
            )
        elif not fresh:
            status = DataHealthStatus.STALE
            error_code = SymbolHealthErrorCode.STALE_DATA
        else:
            status = DataHealthStatus.LIVE
            error_code = None

        snapshot = SymbolHealthSnapshot(
            symbol=symbol,
            observed_at=observed_at,
            target_end=target_end,
            data_health=DataHealthSnapshot(
                symbol=symbol,
                status=status,
                latest_bar_end=latest_bar_end,
                data_age_seconds=data_age_seconds,
                required_data_complete=required_complete,
                fresh=fresh,
            ),
            gaps=gaps,
            consecutive_incomplete_buckets=incomplete_streak,
            error_code=error_code,
        )
        self._snapshots[symbol] = snapshot
        self._gaps[symbol] = retained_gaps
        self._incomplete_streaks[symbol] = incomplete_streak
        if last_required_bucket is None:
            self._last_required_bucket.pop(symbol, None)
        else:
            self._last_required_bucket[symbol] = last_required_bucket
        return snapshot


def summarize_system_health(
    *,
    observed_at: datetime,
    symbols: tuple[SymbolHealthSnapshot, ...],
) -> SystemHealthSnapshot:
    """Build an immutable system summary from already isolated symbol facts."""

    if type(symbols) is not tuple:
        raise TypeError("symbols must be a tuple")
    return SystemHealthSnapshot(observed_at=observed_at, symbols=symbols)


__all__ = [
    "SymbolHealthErrorCode",
    "SymbolHealthSnapshot",
    "SymbolHealthTracker",
    "SystemHealthSnapshot",
    "summarize_system_health",
]
