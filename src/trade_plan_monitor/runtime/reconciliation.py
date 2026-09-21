"""Bounded, coalesced recovery admission; business readiness remains with callers.

The schedule owns no tasks, requests or database. A caller supplies the current
requirements and reports one bounded step's result. Target revisions fence stale
results; the caller must additionally check activation inside its commit transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from trade_plan_monitor.runtime.clock import _canonical_shanghai

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
