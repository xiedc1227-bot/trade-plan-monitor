"""Typed append-only ledger for committed monitor business events."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from trade_plan_monitor.domain.plan_models import AShareSymbol
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.models import MonitorEvent as MonitorEventRow
from trade_plan_monitor.state.models import MonitorSequence

Clock = Callable[[], datetime]

DEFAULT_EVENT_RETENTION = timedelta(days=7)
MAX_EVENT_REPLAY_LIMIT = 1_000
MAX_SQLITE_SEQUENCE = 2**63 - 1
MONITOR_EVENT_NAMESPACE = UUID("d389b36f-4500-57c1-ad5b-566dc39e7865")
_SHANGHAI = ZoneInfo("Asia/Shanghai")

EventEntityId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, strip_whitespace=True),
]
EventStatus = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        strip_whitespace=True,
    ),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]
NonNegativeRevision = Annotated[int, Field(strict=True, ge=0, le=MAX_SQLITE_SEQUENCE)]
PositiveSequence = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_SEQUENCE)]


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _EventValue(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

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


class MonitorEventType(StrEnum):
    """Closed vocabulary of committed business events visible to monitor clients."""

    SYMBOL_SNAPSHOT_UPDATED = "symbol.snapshot.updated"
    SYMBOL_HEALTH_UPDATED = "symbol.health.updated"
    ALERT_CREATED = "alert.created"
    ALERT_ACKNOWLEDGED = "alert.acknowledged"
    PLAN_EXTRACTION_UPDATED = "plan.extraction.updated"
    PLAN_ACTIVATED = "plan.activated"
    PLAN_DEACTIVATED = "plan.deactivated"
    POSITION_UPDATED = "position.updated"
    AI_PROVIDER_UPDATED = "ai.provider.updated"
    SYSTEM_HEALTH_UPDATED = "system.health.updated"


class MonitorEventPayload(_EventValue):
    """Bounded invalidation hint; canonical state remains available through REST."""

    entity_id: EventEntityId
    symbol: AShareSymbol | None = None
    revision: NonNegativeRevision | None = None
    status: EventStatus | None = None
    result_hash: Sha256Digest | None = None


_EVENT_PAYLOAD_FIELDS = {
    MonitorEventType.SYMBOL_SNAPSHOT_UPDATED: frozenset({"entity_id", "symbol", "result_hash"}),
    MonitorEventType.SYMBOL_HEALTH_UPDATED: frozenset(
        {"entity_id", "symbol", "revision", "status"}
    ),
    MonitorEventType.ALERT_CREATED: frozenset({"entity_id", "symbol", "revision"}),
    MonitorEventType.ALERT_ACKNOWLEDGED: frozenset({"entity_id", "symbol", "revision"}),
    MonitorEventType.PLAN_EXTRACTION_UPDATED: frozenset({"entity_id", "revision", "status"}),
    MonitorEventType.PLAN_ACTIVATED: frozenset({"entity_id", "symbol", "revision"}),
    MonitorEventType.PLAN_DEACTIVATED: frozenset({"entity_id", "symbol", "revision"}),
    MonitorEventType.POSITION_UPDATED: frozenset({"entity_id", "symbol", "status"}),
    MonitorEventType.AI_PROVIDER_UPDATED: frozenset({"entity_id", "revision"}),
    MonitorEventType.SYSTEM_HEALTH_UPDATED: frozenset({"entity_id", "status"}),
}

_SYMBOL_AGGREGATE_EVENTS = frozenset(
    {
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.PLAN_ACTIVATED,
        MonitorEventType.PLAN_DEACTIVATED,
    }
)
_ENTITY_AGGREGATE_EVENTS = frozenset(
    {
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.ALERT_CREATED,
        MonitorEventType.ALERT_ACKNOWLEDGED,
        MonitorEventType.PLAN_EXTRACTION_UPDATED,
        MonitorEventType.PLAN_DEACTIVATED,
        MonitorEventType.POSITION_UPDATED,
        MonitorEventType.AI_PROVIDER_UPDATED,
        MonitorEventType.SYSTEM_HEALTH_UPDATED,
    }
)


class MonitorEventDraft(_EventValue):
    """Stable idempotent identity and semantics before sequence allocation."""

    event_id: UUID
    event_type: MonitorEventType = Field(alias="type")
    aggregate_id: EventEntityId
    payload: MonitorEventPayload
    occurred_at: ShanghaiDatetime
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1

    @model_validator(mode="after")
    def require_event_specific_hints(self) -> Self:
        present_fields = frozenset(self.payload.model_dump(mode="python", exclude_none=True).keys())
        if present_fields != _EVENT_PAYLOAD_FIELDS[self.event_type]:
            raise ValueError("event payload fields do not match the event type")
        if self.event_type in _SYMBOL_AGGREGATE_EVENTS and self.aggregate_id != self.payload.symbol:
            raise ValueError("symbol event aggregate_id must match payload symbol")
        if (
            self.event_type in _ENTITY_AGGREGATE_EVENTS
            and self.aggregate_id != self.payload.entity_id
        ):
            raise ValueError("entity event aggregate_id must match payload entity_id")
        if self.event_type in {
            MonitorEventType.ALERT_CREATED,
            MonitorEventType.ALERT_ACKNOWLEDGED,
        }:
            try:
                alert_id = UUID(self.aggregate_id)
            except ValueError:
                raise ValueError("alert aggregate_id must be a canonical UUID") from None
            if str(alert_id) != self.aggregate_id:
                raise ValueError("alert aggregate_id must be a canonical UUID")
        if (
            self.event_type is MonitorEventType.ALERT_CREATED
            and str(self.event_id) != self.aggregate_id
        ):
            raise ValueError("alert.created event_id must match its alert aggregate")
        expected_alert_revision = {
            MonitorEventType.ALERT_CREATED: 0,
            MonitorEventType.ALERT_ACKNOWLEDGED: 1,
        }.get(self.event_type)
        if expected_alert_revision is not None and self.payload.revision != expected_alert_revision:
            raise ValueError("alert event revision does not match its lifecycle state")
        if (
            self.event_type
            in {
                MonitorEventType.SYMBOL_HEALTH_UPDATED,
                MonitorEventType.PLAN_ACTIVATED,
                MonitorEventType.PLAN_DEACTIVATED,
            }
            and self.payload.revision == 0
        ):
            raise ValueError("persisted state event revision must be positive")
        if self.event_type is MonitorEventType.POSITION_UPDATED and self.payload.status not in {
            "OPEN",
            "CLOSED",
        }:
            raise ValueError("position event status must be OPEN or CLOSED")
        return self


class MonitorEvent(MonitorEventDraft):
    """Committed event with its durable global sequence."""

    sequence: PositiveSequence


class MonitorReplayPage(_EventValue):
    """One contiguous retained page checked against the durable high-water mark."""

    after_sequence: Annotated[int, Field(strict=True, ge=0, le=MAX_SQLITE_SEQUENCE)]
    high_water_sequence: Annotated[int, Field(strict=True, ge=0, le=MAX_SQLITE_SEQUENCE)]
    events: tuple[MonitorEvent, ...] = Field(default=(), max_length=MAX_EVENT_REPLAY_LIMIT)
    requires_snapshot: bool

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        sequences = tuple(event.sequence for event in self.events)
        expected = tuple(range(self.after_sequence + 1, self.after_sequence + 1 + len(sequences)))
        if self.requires_snapshot and self.events:
            raise ValueError("snapshot recovery cannot include incremental events")
        if sequences != expected:
            raise ValueError("replay events must be contiguous after the cursor")
        if sequences and sequences[-1] > self.high_water_sequence:
            raise ValueError("replay events cannot exceed the durable high-water mark")
        return self


class MonitorEventError(RuntimeError):
    """Base for sanitized durable monitor-event failures."""

    code = "MONITOR_EVENT_ERROR"


class MonitorEventIdentityConflictError(MonitorEventError):
    """One event UUID cannot represent different event semantics."""

    code = "MONITOR_EVENT_IDENTITY_CONFLICT"


class MonitorEventNotFoundError(MonitorEventError):
    """The requested durable monitor event does not exist."""

    code = "MONITOR_EVENT_NOT_FOUND"


class MonitorEventStorageError(MonitorEventError):
    """Stored data or a database constraint prevents a safe ledger operation."""

    code = "MONITOR_EVENT_STORAGE_ERROR"


def _database_operation[Result](operation: Callable[[], Result], message: str) -> Result:
    try:
        return operation()
    except MonitorEventError:
        raise
    except SQLAlchemyError:
        pass
    raise MonitorEventStorageError(message)


class MonitorEventLog:
    """Append and replay monitor events inside the caller-owned transaction."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Clock,
        replay_retention: timedelta = DEFAULT_EVENT_RETENTION,
    ) -> None:
        if not isinstance(replay_retention, timedelta) or replay_retention <= timedelta(0):
            raise ValueError("replay_retention must be a positive timedelta")
        self._session = session
        self._clock = clock
        self._replay_retention = replay_retention

    def append(self, draft: MonitorEventDraft) -> MonitorEvent:
        """Allocate one global sequence or return the exact existing identity."""

        if type(draft) is not MonitorEventDraft:
            raise TypeError("draft must be a MonitorEventDraft")
        return _database_operation(
            lambda: self._append(draft),
            "Monitor event could not be persisted",
        )

    def _append(self, draft: MonitorEventDraft) -> MonitorEvent:
        event_id = str(draft.event_id)
        # Take SQLite's writer turn before any identity read so a deferred
        # transaction cannot later fail while upgrading a stale WAL snapshot.
        self._serialize_writers()
        existing = self._session.get(MonitorEventRow, event_id)
        if existing is not None:
            return self._matching_event(existing, draft)

        event = MonitorEvent(
            **draft.model_dump(mode="python", round_trip=True, by_alias=False),
            sequence=self._next_sequence(),
        )
        row = MonitorEventRow(
            id=event_id,
            sequence=event.sequence,
            event_type=event.event_type.value,
            schema_version=event.schema_version,
            aggregate_id=event.aggregate_id,
            payload_json=_canonical_json(
                event.payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
            occurred_at=event.occurred_at.isoformat(),
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            existing = self._session.get(MonitorEventRow, event_id)
            if existing is not None:
                return self._matching_event(existing, draft)
            raise MonitorEventStorageError("Monitor event could not be persisted") from None
        return event

    def lock_for_append(self) -> None:
        """Serialize a compound producer before it checks related identities."""

        _database_operation(
            self._serialize_writers,
            "Monitor event writer lock is unavailable",
        )

    def get(self, event_id: UUID) -> MonitorEvent:
        if type(event_id) is not UUID:
            raise TypeError("event_id must be a UUID")
        return _database_operation(
            lambda: self._get(event_id),
            "Monitor event could not be loaded",
        )

    def _get(self, event_id: UUID) -> MonitorEvent:
        row = self._session.get(MonitorEventRow, str(event_id))
        if row is None:
            raise MonitorEventNotFoundError("Monitor event was not found")
        return _event_from_row(row)

    def current_sequence(self) -> int:
        return _database_operation(
            self._current_sequence,
            "Monitor sequence could not be loaded",
        )

    def _current_sequence(self) -> int:
        state = self._session.get(MonitorSequence, 1)
        if (
            state is None
            or type(state.last_sequence) is not int
            or not 0 <= state.last_sequence <= MAX_SQLITE_SEQUENCE
        ):
            raise MonitorEventStorageError("Monitor sequence state is invalid")
        retained_maximum = self._session.scalar(select(func.max(MonitorEventRow.sequence)))
        if retained_maximum is not None and (
            type(retained_maximum) is not int or retained_maximum > state.last_sequence
        ):
            raise MonitorEventStorageError("Monitor sequence state is invalid")
        return state.last_sequence

    def replay_page_after(
        self,
        sequence: int,
        *,
        limit: int = MAX_EVENT_REPLAY_LIMIT,
    ) -> MonitorReplayPage:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if sequence > MAX_SQLITE_SEQUENCE:
            raise ValueError("sequence must fit the SQLite integer range")
        if type(limit) is not int or not 1 <= limit <= MAX_EVENT_REPLAY_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_EVENT_REPLAY_LIMIT}")
        return _database_operation(
            lambda: self._replay_page_after(sequence, limit=limit),
            "Monitor events could not be replayed",
        )

    def _replay_page_after(
        self,
        sequence: int,
        *,
        limit: int,
    ) -> MonitorReplayPage:
        high_water = self.current_sequence()
        if sequence > high_water:
            return MonitorReplayPage(
                after_sequence=sequence,
                high_water_sequence=high_water,
                requires_snapshot=True,
            )
        if sequence == high_water:
            return MonitorReplayPage(
                after_sequence=sequence,
                high_water_sequence=high_water,
                requires_snapshot=False,
            )

        cutoff = self._now() - self._replay_retention
        available_count, first_sequence, last_sequence = self._session.execute(
            select(
                func.count(MonitorEventRow.sequence),
                func.min(MonitorEventRow.sequence),
                func.max(MonitorEventRow.sequence),
            ).where(
                MonitorEventRow.sequence > sequence,
                MonitorEventRow.sequence <= high_water,
                MonitorEventRow.occurred_at >= cutoff.isoformat(),
            )
        ).one()
        if not (
            available_count == high_water - sequence
            and first_sequence == sequence + 1
            and last_sequence == high_water
        ):
            return MonitorReplayPage(
                after_sequence=sequence,
                high_water_sequence=high_water,
                requires_snapshot=True,
            )
        rows = self._session.scalars(
            select(MonitorEventRow)
            .where(
                MonitorEventRow.sequence > sequence,
                MonitorEventRow.sequence <= high_water,
                MonitorEventRow.occurred_at >= cutoff.isoformat(),
            )
            .order_by(MonitorEventRow.sequence)
            .limit(limit)
        ).all()
        return MonitorReplayPage(
            after_sequence=sequence,
            high_water_sequence=high_water,
            events=tuple(_event_from_row(row) for row in rows),
            requires_snapshot=False,
        )

    def _matching_event(
        self,
        row: MonitorEventRow,
        draft: MonitorEventDraft,
    ) -> MonitorEvent:
        event = _event_from_row(row)
        stored = event.model_dump(mode="json", by_alias=True, exclude={"sequence"})
        candidate = draft.model_dump(mode="json", by_alias=True)
        if stored != candidate:
            raise MonitorEventIdentityConflictError(
                "Monitor event identity has conflicting semantics"
            )
        return event

    def _serialize_writers(self) -> None:
        result = self._session.execute(
            update(MonitorSequence)
            .where(MonitorSequence.singleton_id == 1)
            .values(last_sequence=MonitorSequence.last_sequence)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise MonitorEventStorageError("Monitor sequence state is unavailable")

    def _next_sequence(self) -> int:
        state = self._session.get(MonitorSequence, 1)
        if (
            state is None
            or type(state.last_sequence) is not int
            or not 0 <= state.last_sequence < MAX_SQLITE_SEQUENCE
        ):
            raise MonitorEventStorageError("Monitor sequence state is invalid")
        state.last_sequence += 1
        self._session.flush()
        return state.last_sequence

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return value.astimezone(_SHANGHAI)


def monitor_event_id(
    event_type: MonitorEventType,
    aggregate_id: str,
    *identity_parts: str,
) -> UUID:
    """Derive a stable UUID from one immutable business-mutation identity."""

    if type(event_type) is not MonitorEventType:
        raise TypeError("event_type must be a MonitorEventType")
    if (
        not isinstance(aggregate_id, str)
        or not aggregate_id
        or aggregate_id != aggregate_id.strip()
        or len(aggregate_id) > 128
    ):
        raise ValueError("aggregate_id must be a non-empty identifier of at most 128 characters")
    if any(not isinstance(part, str) or not part or len(part) > 256 for part in identity_parts):
        raise ValueError("identity_parts must be non-empty bounded strings")
    identity = _canonical_json([event_type.value, aggregate_id, *identity_parts])
    return uuid5(MONITOR_EVENT_NAMESPACE, identity)


def _event_from_row(row: MonitorEventRow) -> MonitorEvent:
    event = None
    try:
        event = MonitorEvent(
            event_id=UUID(row.id),
            event_type=MonitorEventType(row.event_type),
            sequence=row.sequence,
            schema_version=row.schema_version,
            aggregate_id=row.aggregate_id,
            payload=MonitorEventPayload.model_validate_json(row.payload_json),
            occurred_at=datetime.fromisoformat(row.occurred_at),
        )
    except TypeError, ValueError:
        pass
    if event is None:
        raise MonitorEventStorageError("Stored monitor event is invalid")
    return event


def _canonical_json(value: object) -> str:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError, ValueError, UnicodeError:
        pass
    else:
        return serialized
    raise MonitorEventStorageError("Monitor event cannot be serialized")


__all__ = [
    "DEFAULT_EVENT_RETENTION",
    "MAX_EVENT_REPLAY_LIMIT",
    "MAX_SQLITE_SEQUENCE",
    "MONITOR_EVENT_NAMESPACE",
    "MonitorEvent",
    "MonitorEventDraft",
    "MonitorEventError",
    "MonitorEventIdentityConflictError",
    "MonitorEventLog",
    "MonitorEventNotFoundError",
    "MonitorEventPayload",
    "MonitorEventStorageError",
    "MonitorEventType",
    "MonitorReplayPage",
    "monitor_event_id",
]
