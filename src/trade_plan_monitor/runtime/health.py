"""Immutable per-symbol and batch health for realtime runtime orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)

from trade_plan_monitor.decision.models import DataHealthSnapshot, DataHealthStatus
from trade_plan_monitor.market_data.aggregation import (
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    MinuteBar,
    ProviderCapabilityStatus,
    ShanghaiDatetime,
)
from trade_plan_monitor.market_data.sessions import session_for_minute_end

_MAX_ACTIVE_SYMBOLS = 10
_MAX_GAPS = 240
LEGACY_RUNTIME_GENERATION = UUID("00000000-0000-4000-8000-000000000001")

NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
HealthName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
HealthErrorCode = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


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


class RuntimeServiceStatus(StrEnum):
    """Stable lifecycle states exposed to later transport adapters."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class RuntimeResourceStatus(StrEnum):
    """Sanitized readiness states for local runtime resources."""

    UNVERIFIED = "UNVERIFIED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class RuntimeGapSnapshot(_RuntimeHealthValue):
    """One explicit missing completed minute without provider response data."""

    symbol: AShareSymbol
    bar_end: ShanghaiDatetime


class RecoveryIssueSnapshot(_RuntimeHealthValue):
    """Safe per-plan reason and retry for interrupted-close recovery."""

    symbol: AShareSymbol
    reason: HealthErrorCode
    next_retry_at: ShanghaiDatetime


class ProviderHealthSnapshot(_RuntimeHealthValue):
    """One independently probed provider capability observation."""

    capability: HealthName
    status: ProviderCapabilityStatus
    checked_at: ShanghaiDatetime
    latency_ms: NonNegativeInteger
    error_code: HealthErrorCode | None = None
    next_retry_at: ShanghaiDatetime | None = None

    @model_validator(mode="after")
    def validate_provider_state(self) -> Self:
        if self.status is ProviderCapabilityStatus.READY and (
            self.error_code is not None or self.next_retry_at is not None
        ):
            raise ValueError("ready provider health cannot retain an error or retry")
        if self.status is ProviderCapabilityStatus.UNVERIFIED and (
            self.error_code is not None or self.next_retry_at is not None
        ):
            raise ValueError("unverified provider health cannot retain an error or retry")
        if (
            self.status
            not in {
                ProviderCapabilityStatus.READY,
                ProviderCapabilityStatus.UNVERIFIED,
            }
            and self.error_code is None
        ):
            raise ValueError("non-ready provider health requires a stable error code")
        if self.next_retry_at is not None and self.next_retry_at < self.checked_at:
            raise ValueError("provider retry cannot precede its observation")
        return self


class ExecutorHealthSnapshot(_RuntimeHealthValue):
    """Bounded executor utilization without thread or request details."""

    max_workers: Annotated[int, Field(strict=True, ge=1, le=2)]
    active_count: Annotated[int, Field(strict=True, ge=0, le=2)]
    waiting_count: Annotated[int, Field(strict=True, ge=0, le=32)]

    @model_validator(mode="after")
    def validate_utilization(self) -> Self:
        if self.active_count > self.max_workers:
            raise ValueError("active executor work cannot exceed max_workers")
        return self


class DatabaseHealthSnapshot(_RuntimeHealthValue):
    """Sanitized SQLite, WAL, checkpoint, and backup health."""

    status: RuntimeResourceStatus
    wal_status: RuntimeResourceStatus
    last_checkpoint_at: ShanghaiDatetime | None = None
    last_backup_at: ShanghaiDatetime | None = None
    error_code: HealthErrorCode | None = None

    @model_validator(mode="after")
    def validate_database_state(self) -> Self:
        ready = (
            self.status is RuntimeResourceStatus.READY
            and self.wal_status is RuntimeResourceStatus.READY
        )
        neutral = self.status in {
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        } and self.wal_status in {
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        }
        if (ready or neutral) and self.error_code is not None:
            raise ValueError("ready database health cannot retain an error")
        if not ready and not neutral and self.error_code is None:
            raise ValueError("non-ready database health requires a stable error code")
        return self


class DeliveryHealthSnapshot(_RuntimeHealthValue):
    """Bounded alert-delivery counters and retry state."""

    status: RuntimeResourceStatus
    pending_count: NonNegativeInteger
    failed_count: NonNegativeInteger
    last_delivered_at: ShanghaiDatetime | None = None
    next_retry_at: ShanghaiDatetime | None = None
    error_code: HealthErrorCode | None = None

    @model_validator(mode="after")
    def validate_delivery_state(self) -> Self:
        neutral = self.status in {
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        }
        if (self.status is RuntimeResourceStatus.READY or neutral) and (
            self.failed_count != 0 or self.next_retry_at is not None or self.error_code is not None
        ):
            raise ValueError("ready delivery health cannot retain a failure")
        if (
            self.status
            not in {
                RuntimeResourceStatus.READY,
                RuntimeResourceStatus.UNVERIFIED,
                RuntimeResourceStatus.STOPPED,
            }
            and self.error_code is None
        ):
            raise ValueError("non-ready delivery health requires a stable error code")
        return self


class RuntimeHealthDetails(_RuntimeHealthValue):
    """Injected dynamic facts used by the lifecycle-owned health builder."""

    last_completed_minute: ShanghaiDatetime | None = None
    latest_evaluation_at: ShanghaiDatetime | None = None
    gaps: tuple[RuntimeGapSnapshot, ...] = Field(default=(), max_length=2_400)
    recovery_issues: tuple[RecoveryIssueSnapshot, ...] = Field(default=(), max_length=10)
    next_retry_at: ShanghaiDatetime | None = None
    cooldown_until: ShanghaiDatetime | None = None
    providers: tuple[ProviderHealthSnapshot, ...] = Field(default=(), max_length=5)
    executor: ExecutorHealthSnapshot
    database: DatabaseHealthSnapshot
    delivery: DeliveryHealthSnapshot


class RuntimeHealthSnapshot(RuntimeHealthDetails):
    """One secret-free operational snapshot for the owned runtime process."""

    status: RuntimeServiceStatus
    read_only: bool = Field(strict=True)
    block_reason: Literal["LEGACY_PLANS_REQUIRE_REVIEW"] | None = None
    degraded_reason: HealthErrorCode | None = None
    runtime_generation: UUID4 = Field(default_factory=uuid4, exclude=True)
    observed_at: ShanghaiDatetime
    started_at: ShanghaiDatetime
    stopped_at: ShanghaiDatetime | None = None
    last_completed_minute_age_seconds: NonNegativeInteger | None = None
    latest_evaluation_age_seconds: NonNegativeInteger | None = None
    next_poll_at: ShanghaiDatetime | None = None

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        safe_error: ValidationError | None = None
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = _validation_error_without_inputs(error)
        if safe_error is not None:
            raise safe_error
        raise AssertionError("validation boundary completed without a result")

    @model_validator(mode="after")
    def validate_runtime_health(self) -> Self:
        if self.status is RuntimeServiceStatus.RUNNING and self.read_only:
            raise ValueError("RUNNING health requires read_only=false")
        if self.status is RuntimeServiceStatus.DEGRADED and not self.read_only:
            raise ValueError("DEGRADED health requires read_only=true")
        if self.status is not RuntimeServiceStatus.DEGRADED and self.degraded_reason is not None:
            raise ValueError("only DEGRADED health may carry a degraded reason")
        if (self.status is RuntimeServiceStatus.BLOCKED) != (
            self.block_reason is not None
        ):
            raise ValueError("BLOCKED health requires exactly one block reason")
        if self.status is RuntimeServiceStatus.BLOCKED and not self.read_only:
            raise ValueError("BLOCKED health requires read_only=true")
        if self.started_at > self.observed_at:
            raise ValueError("runtime observation cannot precede startup")
        if (self.status is RuntimeServiceStatus.STOPPED) != (self.stopped_at is not None):
            raise ValueError("only stopped runtime health requires stopped_at")
        stopped_in_range = self.stopped_at is None or (
            self.started_at <= self.stopped_at <= self.observed_at
        )
        if not stopped_in_range:
            raise ValueError("stopped_at must belong to the observed lifecycle")
        self._validate_age(
            self.last_completed_minute,
            self.last_completed_minute_age_seconds,
            "last completed minute",
        )
        self._validate_age(
            self.latest_evaluation_at,
            self.latest_evaluation_age_seconds,
            "latest evaluation",
        )
        gaps = tuple((gap.symbol, gap.bar_end) for gap in self.gaps)
        if gaps != tuple(sorted(set(gaps))):
            raise ValueError("runtime gaps must be unique and strictly ordered")
        capabilities = tuple(provider.capability for provider in self.providers)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("provider health capabilities must be unique")
        if any(provider.checked_at > self.observed_at for provider in self.providers):
            raise ValueError("provider health cannot be observed in the future")
        return self

    def _validate_age(
        self,
        timestamp: datetime | None,
        age_seconds: int | None,
        label: str,
    ) -> None:
        if (timestamp is None) != (age_seconds is None):
            raise ValueError(f"{label} timestamp and age must be present together")
        if timestamp is None:
            return
        age = self.observed_at - timestamp
        if age < timedelta(0) or int(age.total_seconds()) != age_seconds:
            raise ValueError(f"{label} age must match the observation")


def live_runtime_started_at(
    value: object,
    *,
    observed_at: datetime,
) -> datetime | None:
    """Return the active generation only while scheduler progress is not overdue."""

    if type(observed_at) is not datetime or observed_at.utcoffset() != timedelta(hours=8):
        raise ValueError("runtime liveness observation must use Asia/Shanghai")
    status = getattr(value, "status", None)
    read_only = getattr(value, "read_only", None)
    started_at = getattr(value, "started_at", None)
    next_poll_at = getattr(value, "next_poll_at", None)
    if (
        not isinstance(status, RuntimeServiceStatus)
        or type(read_only) is not bool
        or type(started_at) is not datetime
        or started_at.utcoffset() != timedelta(hours=8)
        or (
            next_poll_at is not None
            and (
                type(next_poll_at) is not datetime
                or next_poll_at.utcoffset() != timedelta(hours=8)
            )
        )
    ):
        raise ValueError("runtime liveness requires a validated lifecycle snapshot")
    if (
        status is not RuntimeServiceStatus.RUNNING
        or read_only
        or next_poll_at is None
        or observed_at < started_at
        or observed_at > next_poll_at
    ):
        return None
    return started_at


def live_runtime_identity(
    value: object,
    *,
    observed_at: datetime,
) -> tuple[datetime, UUID] | None:
    """Return exact causal runtime identity only while its progress is live."""

    started_at = live_runtime_started_at(value, observed_at=observed_at)
    generation = getattr(value, "runtime_generation", None)
    if started_at is None or type(generation) is not UUID or generation.version != 4:
        return None
    return started_at, generation


def _validation_error_without_inputs(error: ValidationError) -> ValidationError:
    line_errors = error.errors(include_url=False)
    for line_error in line_errors:
        line_error.pop("input", None)
    return ValidationError.from_exception_data(
        error.title,
        line_errors,
        hide_input=True,
    )


class SymbolHealthSnapshot(_RuntimeHealthValue):
    """One isolated symbol's actionable data-health facts and gap state."""

    symbol: AShareSymbol
    observed_at: ShanghaiDatetime
    target_end: ShanghaiDatetime
    data_health: DataHealthSnapshot
    gaps: tuple[ShanghaiDatetime, ...] = Field(default=(), max_length=_MAX_GAPS)
    consecutive_incomplete_buckets: NonNegativeInteger
    last_required_bucket_end: ShanghaiDatetime | None = None
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
        if self.last_required_bucket_end is not None and (
            five_minute_bucket_end(self.last_required_bucket_end)
            != self.last_required_bucket_end
            or self.last_required_bucket_end > self.target_end
        ):
            raise ValueError("last required bucket must be canonical and not follow target")
        if self.consecutive_incomplete_buckets > 0 and self.last_required_bucket_end is None:
            raise ValueError("an incomplete streak requires its last required bucket")
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

    def restore(self, snapshots: tuple[SymbolHealthSnapshot, ...]) -> None:
        """Hydrate exact durable tracker state before the first post-restart batch."""

        if type(snapshots) is not tuple or len(snapshots) > _MAX_ACTIVE_SYMBOLS:
            raise ValueError("health snapshots must be a tuple capped at 10")
        if any(type(snapshot) is not SymbolHealthSnapshot for snapshot in snapshots):
            raise TypeError("health snapshots must contain exact SymbolHealthSnapshot values")
        symbols = tuple(snapshot.symbol for snapshot in snapshots)
        if len(symbols) != len(set(symbols)):
            raise ValueError("health snapshot symbols must be unique")
        for snapshot in snapshots:
            previous = self._snapshots.get(snapshot.symbol)
            if previous is not None and previous != snapshot:
                raise ValueError("health tracker cannot overwrite hydrated state")
            self._snapshots[snapshot.symbol] = snapshot
            self._gaps[snapshot.symbol] = set(snapshot.gaps)
            self._incomplete_streaks[snapshot.symbol] = (
                snapshot.consecutive_incomplete_buckets
            )
            if snapshot.last_required_bucket_end is None:
                self._last_required_bucket.pop(snapshot.symbol, None)
            else:
                self._last_required_bucket[snapshot.symbol] = (
                    snapshot.last_required_bucket_end
                )

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

    def replace(self, symbol: str, snapshot: SymbolHealthSnapshot | None) -> None:
        """Replace one symbol state when its activation generation changes."""

        if type(symbol) is not str or not symbol:
            raise ValueError("symbol must be a non-empty string")
        if snapshot is not None and (
            type(snapshot) is not SymbolHealthSnapshot or snapshot.symbol != symbol
        ):
            raise ValueError("replacement snapshot must match the exact symbol")
        self._snapshots.pop(symbol, None)
        self._gaps.pop(symbol, None)
        self._incomplete_streaks.pop(symbol, None)
        self._last_required_bucket.pop(symbol, None)
        if snapshot is not None:
            self.restore((snapshot,))

    def gaps_for(self, symbol: str, *, trade_date: date) -> tuple[datetime, ...]:
        """Return retained canonical gaps for one symbol and trading date."""

        if type(symbol) is not str or not symbol:
            raise ValueError("symbol must be a non-empty string")
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        return tuple(
            sorted(gap for gap in self._gaps.get(symbol, set()) if gap.date() == trade_date)
        )

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
        if type(minutes) is not tuple or len(minutes) > 1 + _MAX_GAPS:
            raise ValueError("minute health input exceeds the target plus retained-gap bound")
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
        if type(minutes) is not tuple or len(minutes) > len(expected) + _MAX_GAPS:
            raise ValueError("bucket health input exceeds the target plus retained-gap bound")
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
        previous = self._snapshots.get(symbol)
        if previous is not None and target_end < previous.target_end:
            raise ValueError("health target cannot regress")
        if previous is not None and observed_at < previous.observed_at:
            raise ValueError("health observation time cannot regress")

        same_trade_date = previous is None or previous.target_end.date() == target_end.date()

        missing = set(expected).difference(minute_ends)
        retained_gaps = set(self._gaps.get(symbol, set())) if same_trade_date else set()
        if any(minute_end not in set(expected) | retained_gaps for minute_end in minute_ends):
            raise ValueError("bucket minutes must belong to the target or a retained gap")
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
            last_required_bucket_end=last_required_bucket,
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
    "DatabaseHealthSnapshot",
    "DeliveryHealthSnapshot",
    "ExecutorHealthSnapshot",
    "LEGACY_RUNTIME_GENERATION",
    "ProviderHealthSnapshot",
    "RuntimeGapSnapshot",
    "RuntimeHealthDetails",
    "RuntimeHealthSnapshot",
    "RuntimeResourceStatus",
    "RuntimeServiceStatus",
    "SymbolHealthErrorCode",
    "SymbolHealthSnapshot",
    "SymbolHealthTracker",
    "SystemHealthSnapshot",
    "live_runtime_started_at",
    "live_runtime_identity",
    "summarize_system_health",
]
