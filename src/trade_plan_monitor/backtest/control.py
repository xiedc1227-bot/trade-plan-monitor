"""Bounded operational progress and cooperative cancellation controls."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PROGRESS_UNITS = 100_000

type BacktestDataPhase = Literal[
    "SYNC_CALENDAR",
    "SYNC_DAILY",
    "SYNC_MINUTE",
    "SYNC_LIMIT",
    "FREEZE_VERIFY",
    "FREEZE_PUBLISH",
]
type BacktestRunPhase = Literal[
    "RUN_DAY_TRANSITION",
    "RUN_MINUTE",
    "RUN_EVALUATION",
    "RUN_FINALIZE",
    "RUN_REPORT_HANDOFF",
]
type BacktestOperationPhase = BacktestDataPhase | BacktestRunPhase


class BacktestProgress(BaseModel):
    """Small immutable progress value that cannot carry facts or identities."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    phase: BacktestOperationPhase
    completed_units: int = Field(ge=1, le=MAX_PROGRESS_UNITS)
    total_units: int = Field(ge=1, le=MAX_PROGRESS_UNITS)

    @model_validator(mode="after")
    def validate_completion(self) -> BacktestProgress:
        if self.completed_units > self.total_units:
            raise ValueError("completed_units cannot exceed total_units")
        return self


type BacktestProgressCallback = Callable[[BacktestProgress], None]


class BacktestCancellationResult(BaseModel):
    """Closed engine outcome returned instead of a partial completed report."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    phase: BacktestRunPhase
    last_safe_event_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BacktestOperationCancelled(RuntimeError):
    """Typed cooperative-cancellation signal raised only at safe boundaries."""

    def __init__(
        self,
        phase: BacktestOperationPhase,
        last_safe_event_id: str | None = None,
    ) -> None:
        self.phase = phase
        self.last_safe_event_id = last_safe_event_id
        super().__init__(f"BACKTEST_OPERATION_CANCELLED:{phase}")


class CancellationToken:
    """Cross-thread-safe idempotent cancellation flag."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(
        self,
        phase: BacktestOperationPhase,
        last_safe_event_id: str | None = None,
    ) -> None:
        if self._event.is_set():
            raise BacktestOperationCancelled(phase, last_safe_event_id)


class MonotonicProgressThrottle:
    """Thread-safe one-second write throttle with no persisted elapsed values."""

    __slots__ = ("_clock", "_interval_seconds", "_last_key", "_last_seen", "_lock")

    def __init__(
        self,
        *,
        interval_seconds: float = 1.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int | float):
            raise TypeError("interval_seconds must be a number")
        if float(interval_seconds) <= 0:
            raise ValueError("interval_seconds must be positive")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._interval_seconds = float(interval_seconds)
        self._clock = clock
        self._last_key: str | None = None
        self._last_seen: float | None = None
        self._lock = Lock()

    def admit(self, key: str, *, force: bool = False) -> bool:
        """Return whether one write may proceed, forcing named transitions through."""

        if type(key) is not str or not key:
            raise ValueError("progress throttle key must be a non-empty string")
        if type(force) is not bool:
            raise TypeError("force must be a boolean")
        current = float(self._clock())
        with self._lock:
            previous = self._last_seen if self._last_key == key else None
            if previous is not None and current < previous:
                raise RuntimeError("monotonic clock moved backwards")
            if not force and previous is not None:
                if current - previous < self._interval_seconds:
                    return False
            self._last_key = key
            self._last_seen = current
            return True

    def forget(self, key: str) -> None:
        """Discard one completed or superseded claim's in-memory throttle state."""

        if type(key) is not str or not key:
            raise ValueError("progress throttle key must be a non-empty string")
        with self._lock:
            if self._last_key == key:
                self._last_key = None
                self._last_seen = None


def validate_operation_controls(
    cancellation_token: CancellationToken | None,
    progress_callback: BacktestProgressCallback | None,
) -> None:
    """Reject invalid internal adapters before an operation performs work."""

    if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
        raise TypeError("cancellation_token must be a CancellationToken or None")
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")


def check_cancelled(
    cancellation_token: CancellationToken | None,
    phase: BacktestOperationPhase,
    last_safe_event_id: str | None = None,
) -> None:
    """Observe cancellation at one named safe boundary."""

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled(phase, last_safe_event_id)


def report_progress(
    progress_callback: BacktestProgressCallback | None,
    *,
    phase: BacktestOperationPhase,
    completed_units: int,
    total_units: int,
) -> None:
    """Emit one bounded progress value without retaining callback state."""

    if progress_callback is not None:
        progress_callback(
            BacktestProgress(
                phase=phase,
                completed_units=completed_units,
                total_units=total_units,
            )
        )


__all__ = [
    "MAX_PROGRESS_UNITS",
    "BacktestOperationCancelled",
    "BacktestOperationPhase",
    "BacktestCancellationResult",
    "BacktestRunPhase",
    "BacktestProgress",
    "BacktestProgressCallback",
    "CancellationToken",
    "MonotonicProgressThrottle",
    "check_cancelled",
    "report_progress",
    "validate_operation_controls",
]
