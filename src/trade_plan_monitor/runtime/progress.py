"""Owner-written progress evidence, separate from transport and durable presence.

This tracker does not authorize work, cancel a worker or own scheduling. Callers
must complete a token only after its bounded unit really completes, and call stop
only after the owner's work has physically drained.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from trade_plan_monitor.runtime.clock import _canonical_shanghai

ProgressState = Literal["STARTING", "SCHEDULED", "WORKING", "STALLED", "STOPPED"]


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    runtime_generation: UUID
    observed_at: datetime
    state: ProgressState
    last_progress_at: datetime | None
    next_wake_at: datetime | None
    progress_due_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ProgressRecord:
    state: ProgressState = "STARTING"
    token: object | None = None
    deadline: float | None = None
    next_wake: float | None = None
    last_progress: datetime | None = None
    inherited_stall: bool = False


class RuntimeProgress:
    """One lifecycle owner's token-fenced, monotonic progress timeline."""

    def __init__(
        self, runtime_generation: UUID, *, clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(runtime_generation) is not UUID or runtime_generation.version != 4:
            raise ValueError("progress requires an owner UUIDv4")
        if not callable(clock) or not callable(monotonic):
            raise TypeError("progress clocks must be callable")
        self.runtime_generation = runtime_generation
        self._clock = clock
        self._monotonic = monotonic
        self._record = _ProgressRecord()

    @property
    def has_owned_step(self) -> bool:
        return self._record.token is not None

    def monotonic_now(self) -> float:
        """Capture a deadline for pending owner work without changing progress."""
        return self._tick()

    def authority_token(self) -> object:
        """Return immutable owner evidence for before/after read fencing."""
        return self._record

    def begin_step(self, *, timeout_seconds: float) -> object:
        if (
            isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            raise ValueError("bounded step duration must be positive and finite")
        return self.begin_step_at(deadline=self._tick() + timeout_seconds)

    def begin_step_at(self, *, deadline: float) -> object:
        """Retain the original deadline when collecting a concurrent work unit."""
        if (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ValueError("bounded step deadline must be finite")
        record = self._record
        if record.state == "STOPPED":
            raise RuntimeError("progress owner is stopped")
        if record.token is not None:
            raise RuntimeError("unfinished progress step is already owned")
        now = self._tick()
        inherited_stall = self._is_stalled(record, now)
        token = object()
        # Retain the overdue deadline until a real completion, even when beginning
        # the local reconsideration that will eventually repair the stalled state.
        self._record = _ProgressRecord(
            state="WORKING", token=token,
            deadline=record.deadline if inherited_stall else deadline,
            last_progress=record.last_progress, inherited_stall=inherited_stall,
        )
        return token

    def complete_step(self, token: object, *, next_wake_at: datetime) -> bool:
        record = self._record
        if record.token is None or token is not record.token or record.state == "STOPPED":
            return False
        now_wall = _canonical_shanghai(self._clock())
        next_wake_at = _canonical_shanghai(next_wake_at)
        delay = (next_wake_at - now_wall).total_seconds()
        if not 0 <= delay <= 30:
            raise ValueError("local reconsideration must be scheduled within 0..30 seconds")
        now = self._tick()
        self._record = _ProgressRecord(
            state="SCHEDULED", deadline=now + delay,
            next_wake=now + delay, last_progress=now_wall,
        )
        return True

    def stop(self) -> None:
        """Revoke tokens after the lifecycle owner has completed physical cleanup."""
        self._record = _ProgressRecord(
            state="STOPPED", last_progress=self._record.last_progress,
        )

    def snapshot(self) -> ProgressSnapshot:
        record = self._record
        now_wall = _canonical_shanghai(self._clock())
        now = self._tick()

        def wall_deadline(deadline: float | None) -> datetime | None:
            return None if deadline is None else now_wall + timedelta(seconds=deadline - now)

        last_progress = record.last_progress
        if last_progress is not None and last_progress > now_wall:
            last_progress = None
        return ProgressSnapshot(
            runtime_generation=self.runtime_generation, observed_at=now_wall,
            state="STALLED" if self._is_stalled(record, now) else record.state,
            last_progress_at=last_progress, next_wake_at=wall_deadline(record.next_wake),
            progress_due_at=wall_deadline(record.deadline),
        )

    @staticmethod
    def _is_stalled(record: _ProgressRecord, now: float) -> bool:
        return record.state != "STOPPED" and (
            record.inherited_stall or record.deadline is not None and now > record.deadline
        )

    def _tick(self) -> float:
        value = self._monotonic()
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("monotonic clock must provide a finite number")
        return value
