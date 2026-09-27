"""Bounded, coalesced recovery admission; business readiness remains with callers.

The schedule owns no tasks, requests or database. A caller supplies the current
requirements and reports one bounded step's result. Target revisions fence stale
results; the caller must additionally check activation inside its commit transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from trade_plan_monitor.runtime.clock import Clock, _canonical_shanghai

MAX_RECOVERY_SCOPES = 32
MAINTENANCE_INTERVAL = timedelta(seconds=30)


class RecoveryDisposition(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RETRY = "RETRY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class RecoveryRequirement:
    """Stable scope key plus current activation/semantic/target dependency revision."""

    scope_key: str
    revision: str

    def __post_init__(self) -> None:
        for value in (self.scope_key, self.revision):
            if type(value) is not str or not value or len(value) > 256:
                raise ValueError("recovery identity must contain 1 to 256 characters")


@dataclass(frozen=True, slots=True)
class RecoveryStepResult:
    disposition: RecoveryDisposition
    next_retry_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, RecoveryDisposition):
            raise TypeError("disposition must be a RecoveryDisposition")
        if (self.disposition is RecoveryDisposition.RETRY) != (self.next_retry_at is not None):
            raise ValueError("only RETRY requires next_retry_at")
        if self.next_retry_at is not None:
            object.__setattr__(self, "next_retry_at", _canonical_shanghai(self.next_retry_at))

    @classmethod
    def ready(cls) -> RecoveryStepResult:
        return cls(RecoveryDisposition.READY)

    @classmethod
    def retry(cls, at: datetime) -> RecoveryStepResult:
        return cls(RecoveryDisposition.RETRY, at)

    @classmethod
    def blocked(cls) -> RecoveryStepResult:
        return cls(RecoveryDisposition.BLOCKED)


@dataclass(frozen=True, slots=True, eq=False)
class RecoveryTicket:
    requirement: RecoveryRequirement
    _entry_identity: object


@dataclass(frozen=True, slots=True)
class RecoveryScopeSnapshot:
    requirement: RecoveryRequirement
    disposition: RecoveryDisposition
    next_retry_at: datetime | None
    in_progress: bool


@dataclass(slots=True)
class _Entry:
    requirement: RecoveryRequirement
    identity: object
    result: RecoveryStepResult


class RecoverySchedule:
    """Single event-loop owner, fair eligible selection, no per-target retry bypass."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._order: list[str] = []
        self._owned: RecoveryTicket | None = None

    def synchronize(self, requirements: tuple[RecoveryRequirement, ...]) -> None:
        """Replace desired work atomically; never release an in-flight ticket early."""

        if type(requirements) is not tuple or any(
            not isinstance(item, RecoveryRequirement) for item in requirements
        ):
            raise TypeError("requirements must be a tuple of RecoveryRequirement")
        if len(requirements) > MAX_RECOVERY_SCOPES:
            raise ValueError("at most 32 recovery scopes are allowed")
        keys = [item.scope_key for item in requirements]
        if len(set(keys)) != len(keys):
            raise ValueError("recovery scope keys must be unique")
        replacement: dict[str, _Entry] = {}
        for requirement in requirements:
            previous = self._entries.get(requirement.scope_key)
            if previous is not None and previous.requirement == requirement:
                replacement[requirement.scope_key] = previous
            else:
                # The operation failed, not the minute target. Preserve its retry
                # deadline across a rolling target instead of admitting a retry storm.
                result = (
                    previous.result
                    if previous is not None
                    and previous.result.disposition is RecoveryDisposition.RETRY
                    else RecoveryStepResult(RecoveryDisposition.PENDING)
                )
                replacement[requirement.scope_key] = _Entry(requirement, object(), result)
        self._order = [key for key in self._order if key in replacement]
        self._order.extend(key for key in keys if key not in self._order)
        self._entries = replacement

    def resolve_local(
        self, requirement: RecoveryRequirement, result: RecoveryStepResult, *, now: datetime,
    ) -> bool:
        """Set eligible exact local facts without consuming a round-robin turn.

        Never supersede a physical owner, a future retry or terminal state. Only
        deliberate requirement synchronization can rearm READY/BLOCKED entries.
        """
        if not isinstance(requirement, RecoveryRequirement):
            raise TypeError("requirement must be a RecoveryRequirement")
        if not isinstance(result, RecoveryStepResult):
            raise TypeError("result must be a RecoveryStepResult")
        current = _canonical_shanghai(now)
        if result.disposition is RecoveryDisposition.PENDING or (
            result.next_retry_at is not None and result.next_retry_at <= current
        ):
            raise ValueError("local resolution requires READY, BLOCKED or a future RETRY")
        entry = self._entries.get(requirement.scope_key)
        if (entry is None or entry.requirement != requirement
                or (self._owned is not None
                    and self._owned.requirement.scope_key == requirement.scope_key)
                or entry.result.disposition in (
                    RecoveryDisposition.READY, RecoveryDisposition.BLOCKED,
                )
                or (entry.result.next_retry_at is not None
                    and current < entry.result.next_retry_at)):
            return False
        entry.result = result
        return True

    def claim(self, *, now: datetime) -> RecoveryTicket | None:
        """Return at most one eligible step; absence never means business readiness."""

        current = _canonical_shanghai(now)
        if self._owned is not None:
            return None
        for key in self._order:
            entry = self._entries[key]
            result = entry.result
            if result.disposition in (RecoveryDisposition.READY, RecoveryDisposition.BLOCKED):
                continue
            if result.next_retry_at is not None and current < result.next_retry_at:
                continue
            self._order.remove(key)
            self._order.append(key)
            self._owned = RecoveryTicket(entry.requirement, entry.identity)
            return self._owned
        return None

    def is_current(self, ticket: RecoveryTicket) -> bool:
        """Check target identity; not a substitute for transaction-level plan fences."""

        if ticket is None or ticket is not self._owned:
            return False
        entry = self._entries.get(ticket.requirement.scope_key)
        return entry is not None and entry.identity is ticket._entry_identity

    def complete(self, ticket: RecoveryTicket, result: RecoveryStepResult) -> bool:
        """Discard stale business results, but retain the stable scope's retry gate."""

        if ticket is not self._owned or ticket is None:
            raise ValueError("ticket is not owned by this schedule")
        if not isinstance(result, RecoveryStepResult):
            raise TypeError("result must be a RecoveryStepResult")
        accepted = self.is_current(ticket)
        if accepted:
            self._entries[ticket.requirement.scope_key].result = result
        elif result.disposition is RecoveryDisposition.RETRY:
            entry = self._entries.get(ticket.requirement.scope_key)
            if entry is not None:
                # A slow failure belongs to the physical operation even if the
                # desired minute changed meanwhile. It cannot authorize READY.
                previous_retry = entry.result.next_retry_at
                if previous_retry is None or result.next_retry_at > previous_retry:
                    entry.result = result
        self._owned = None
        return accepted

    def next_wake_at(self, *, now: datetime) -> datetime:
        """Bound local maintenance independently of provider request eligibility."""

        current = _canonical_shanghai(now)
        wake = current + MAINTENANCE_INTERVAL
        if self._owned is not None:
            return wake
        for entry in self._entries.values():
            result = entry.result
            if result.disposition is RecoveryDisposition.PENDING:
                return current
            if result.next_retry_at is not None:
                wake = min(wake, max(current, result.next_retry_at))
        return wake

    def snapshot(self) -> tuple[RecoveryScopeSnapshot, ...]:
        return tuple(
            RecoveryScopeSnapshot(
                requirement=entry.requirement,
                disposition=entry.result.disposition,
                next_retry_at=entry.result.next_retry_at,
                in_progress=(
                    self._owned is not None and self._owned._entry_identity is entry.identity
                ),
            )
            for entry in self._entries.values()
        )


class RecoveryCoordinator:
    """Own an injected recovery loop without changing production composition.

    Requirements are local reads, not provider probes. Their revisions include
    configuration/activation changes as well as semantic and target identity.
    Execute owns one bounded step through existing request control and returns a
    RETRY, READY or BLOCKED; storage/programming faults must propagate.
    Readiness here describes only that step, never permission to evaluate/send.

    A stop drains the active callback before returning. Cancellation propagates
    through that callback; its physical worker remains owned by request control
    until the controller is drained by lifecycle cleanup. This object is single
    use, so neither cancellation nor a fault can recycle an outstanding ticket.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        requirements: Callable[[datetime], tuple[RecoveryRequirement, ...]],
        execute: Callable[[RecoveryTicket], Awaitable[RecoveryStepResult]],
    ) -> None:
        self._clock = clock
        self._requirements = requirements
        self._execute = execute
        self._schedule = RecoverySchedule()
        self._wake = asyncio.Event()
        self._started = False
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def wake(self) -> None:
        """Signal a local change on the owning event loop, coalescing notifications."""

        self._wake.set()

    def snapshot(self) -> tuple[RecoveryScopeSnapshot, ...]:
        return self._schedule.snapshot()

    async def run(self, *, stop: asyncio.Event) -> None:
        if self._started:
            raise RuntimeError("recovery coordinator already has an owner")
        self._started = True
        self._running = True
        try:
            while not stop.is_set():
                # Clear before the local snapshot, never after an awaited step:
                # changes signalled during work must survive until reconciliation.
                self._wake.clear()
                now = _canonical_shanghai(self._clock.now())
                self._schedule.synchronize(self._requirements(now))
                ticket = self._schedule.claim(now=now)
                if ticket is None:
                    await self._wait(self._schedule.next_wake_at(now=now), stop)
                    continue
                result = await self._execute(ticket)
                completed_at = _canonical_shanghai(self._clock.now())
                if not isinstance(result, RecoveryStepResult):
                    raise TypeError("recovery step must return RecoveryStepResult")
                if result.disposition is RecoveryDisposition.PENDING:
                    raise ValueError("a completed step must report READY, RETRY or BLOCKED")
                if result.next_retry_at is not None and result.next_retry_at <= completed_at:
                    # Clock jumps or a delayed callback can consume the reported
                    # retry window. Reconcile at maintenance instead of crashing
                    # or repeatedly admitting an immediately failing callback.
                    result = RecoveryStepResult.retry(completed_at + MAINTENANCE_INTERVAL)
                self._schedule.synchronize(self._requirements(completed_at))
                self._schedule.complete(ticket, result)
                # An async callback may complete without suspending. Let stop and
                # configuration-change tasks run even when many scopes are ready.
                await asyncio.sleep(0)
        finally:
            self._running = False

    async def _wait(self, deadline: datetime, stop: asyncio.Event) -> None:
        waiters = (
            asyncio.create_task(self._clock.sleep_until(deadline)),
            asyncio.create_task(stop.wait()),
            asyncio.create_task(self._wake.wait()),
        )
        try:
            done, _ = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=MAINTENANCE_INTERVAL.total_seconds(),
            )
            for task in done:
                task.result()
        finally:
            for task in waiters:
                task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
