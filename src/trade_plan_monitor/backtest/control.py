"""Bounded operational progress and cooperative cancellation controls."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PROGRESS_UNITS = 100_000

type BacktestOperationPhase = Literal[
    "SYNC_CALENDAR",
    "SYNC_DAILY",
    "SYNC_MINUTE",
    "SYNC_LIMIT",
    "FREEZE_VERIFY",
    "FREEZE_PUBLISH",
]


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


class BacktestOperationCancelled(RuntimeError):
    """Typed cooperative-cancellation signal raised only at safe boundaries."""

    def __init__(self, phase: BacktestOperationPhase) -> None:
        self.phase = phase
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

    def raise_if_cancelled(self, phase: BacktestOperationPhase) -> None:
        if self._event.is_set():
            raise BacktestOperationCancelled(phase)


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
) -> None:
    """Observe cancellation at one named safe boundary."""

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled(phase)


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
    "BacktestProgress",
    "BacktestProgressCallback",
    "CancellationToken",
    "check_cancelled",
    "report_progress",
    "validate_operation_controls",
]
