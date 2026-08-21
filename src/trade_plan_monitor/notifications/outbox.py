"""Session-bound transactional outbox for committed alert events."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_plan_monitor.notifications.models import AlertEvent, AlertPayload
from trade_plan_monitor.notifications.render import render_alert
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow
from trade_plan_monitor.state.models import AlertSequence, AuditLog

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

DEFAULT_REPLAY_RETENTION = timedelta(days=7)
MAX_REPLAY_LIMIT = 1_000
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class OutboxError(RuntimeError):
    """Base for sanitized notification persistence failures."""

    code = "OUTBOX_ERROR"


class AlertIdentityConflictError(OutboxError):
    """One durable identity cannot represent different alert semantics."""

    code = "ALERT_IDENTITY_CONFLICT"


class AlertNotFoundError(OutboxError):
    """The requested durable alert does not exist."""

    code = "ALERT_NOT_FOUND"


class OutboxStorageError(OutboxError):
    """Stored data or a database constraint prevents a safe outbox operation."""

    code = "OUTBOX_STORAGE_ERROR"


class AlertOutbox:
    """Persist, replay, and acknowledge alerts within the caller's transaction."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Clock,
        id_factory: IdFactory,
        replay_retention: timedelta = DEFAULT_REPLAY_RETENTION,
    ) -> None:
        if not isinstance(replay_retention, timedelta) or replay_retention <= timedelta(0):
            raise ValueError("replay_retention must be a positive timedelta")
        self._session = session
        self._clock = clock
        self._id_factory = id_factory
        self._replay_retention = replay_retention

    def enqueue(self, payload: AlertPayload) -> AlertEvent:
        """Atomically claim one dedup key and return its stable event."""

        if type(payload) is not AlertPayload:
            raise TypeError("payload must be an AlertPayload")

        self._serialize_writers()
        existing = self._session.scalar(
            select(AlertEventRow).where(AlertEventRow.dedup_key == payload.dedup_key)
        )
        if existing is not None:
            return self._deduplicated_event(existing, payload)

        event_id = str(payload.event_id)
        if self._session.get(AlertEventRow, event_id) is not None:
            raise AlertIdentityConflictError("Alert event identity is already in use")

        sequence = self._next_sequence()

        created_at = self._now()
        if created_at < payload.evaluated_at:
            raise ValueError("clock cannot precede alert evaluation")
        event = AlertEvent(
            **payload.model_dump(mode="python", round_trip=True),
            sequence=sequence,
            message_text=render_alert(payload),
            created_at=created_at,
            acknowledged_at=None,
        )
        row = AlertEventRow(
            id=event_id,
            sequence=sequence,
            dedup_key=payload.dedup_key,
            payload_json=_payload_json(payload),
            message_text=event.message_text,
            created_at=event.created_at.isoformat(),
            acknowledged_at=None,
        )
        integrity_failure = False
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            integrity_failure = True

        if integrity_failure:
            existing = self._session.scalar(
                select(AlertEventRow).where(AlertEventRow.dedup_key == payload.dedup_key)
            )
            if existing is not None:
                return self._deduplicated_event(existing, payload)
            raise OutboxStorageError("Alert event could not be persisted") from None
        return event

    def get(self, event_id: UUID) -> AlertEvent:
        """Return one event visible to the current transaction."""

        normalized_id = _event_id(event_id)
        row = self._session.get(AlertEventRow, normalized_id)
        if row is None:
            raise AlertNotFoundError("Alert event was not found")
        return _event_from_row(row)

    def replay_after(
        self,
        sequence: int,
        *,
        limit: int = MAX_REPLAY_LIMIT,
    ) -> tuple[AlertEvent, ...]:
        """Return retained events after an exclusive monotonically increasing cursor."""

        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= MAX_REPLAY_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_REPLAY_LIMIT}")
        cutoff = self._now() - self._replay_retention
        rows = self._session.scalars(
            select(AlertEventRow)
            .where(
                AlertEventRow.sequence > sequence,
                AlertEventRow.created_at >= cutoff.isoformat(),
            )
            .order_by(AlertEventRow.sequence)
            .limit(limit)
        ).all()
        return tuple(_event_from_row(row) for row in rows)

    def acknowledge(self, event_id: UUID) -> AlertEvent:
        """Mark an alert seen once without touching delivery or strategy state."""

        normalized_id = _event_id(event_id)
        self._session.execute(
            update(AlertEventRow)
            .where(AlertEventRow.id == normalized_id)
            .values(acknowledged_at=AlertEventRow.acknowledged_at)
            .execution_options(synchronize_session=False)
        )
        row = self._session.get(AlertEventRow, normalized_id)
        if row is None:
            raise AlertNotFoundError("Alert event was not found")
        before = _event_from_row(row)
        if before.acknowledged_at is not None:
            return before

        acknowledged_at = self._now()
        if acknowledged_at < before.created_at:
            raise ValueError("clock cannot precede alert creation")
        integrity_failure = False
        try:
            with self._session.begin_nested():
                row.acknowledged_at = acknowledged_at.isoformat()
                self._session.flush()
                after = _event_from_row(row)
                self._session.add(
                    AuditLog(
                        id=_audit_id(self._id_factory()),
                        action="ALERT_ACKNOWLEDGED",
                        entity_type="ALERT_EVENT",
                        entity_id=normalized_id,
                        before_hash=_event_hash(before),
                        after_hash=_event_hash(after),
                        details_json=_canonical_json(
                            {
                                "acknowledgedAt": acknowledged_at.isoformat(),
                                "eventId": normalized_id,
                            }
                        ),
                        created_at=acknowledged_at.isoformat(),
                    )
                )
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            integrity_failure = True

        if integrity_failure:
            raise OutboxStorageError("Alert acknowledgement could not be persisted") from None
        return after

    def _deduplicated_event(
        self,
        row: AlertEventRow,
        payload: AlertPayload,
    ) -> AlertEvent:
        event = _event_from_row(row)
        stored_semantics = AlertPayload.model_validate(
            event.model_dump(
                mode="python",
                round_trip=True,
                exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
            )
        )
        if _semantic_payload(stored_semantics) != _semantic_payload(payload):
            raise AlertIdentityConflictError("Alert dedup identity has conflicting semantics")
        return event

    def _serialize_writers(self) -> None:
        # The singleton row takes SQLite's writer turn even when no alerts remain.
        result = self._session.execute(
            update(AlertSequence)
            .where(AlertSequence.singleton_id == 1)
            .values(last_sequence=AlertSequence.last_sequence)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise OutboxStorageError("Alert sequence state is unavailable")

    def _next_sequence(self) -> int:
        state = self._session.get(AlertSequence, 1)
        if state is None or type(state.last_sequence) is not int or state.last_sequence < 0:
            raise OutboxStorageError("Alert sequence state is invalid")
        state.last_sequence += 1
        self._session.flush()
        return state.last_sequence

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return value.astimezone(_SHANGHAI)


def _event_id(value: UUID) -> str:
    if type(value) is not UUID:
        raise TypeError("event_id must be a UUID")
    return str(value)


def _audit_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 36:
        raise ValueError("id_factory must return a non-empty identifier of at most 36 characters")
    return value


def _payload_json(payload: AlertPayload) -> str:
    return _canonical_json(payload.model_dump(mode="json", round_trip=True))


def _semantic_payload(payload: AlertPayload) -> object:
    value = payload.model_dump(mode="python", round_trip=True, exclude={"event_id"})
    return _semantic_value(value)


def _semantic_value(value: object) -> object:
    if isinstance(value, Decimal):
        return ("decimal", _canonical_decimal(value))
    if isinstance(value, Enum):
        return (
            "enum",
            type(value).__module__,
            type(value).__qualname__,
            _semantic_value(value.value),
        )
    if type(value) is datetime:
        return ("datetime", value.isoformat())
    if type(value) is date:
        return ("date", value.isoformat())
    if isinstance(value, UUID):
        return ("uuid", str(value))
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise OutboxStorageError("Alert semantic data is invalid")
        return (
            "mapping",
            tuple((key, _semantic_value(value[key])) for key in sorted(value)),
        )
    if isinstance(value, (tuple, list)):
        return ("sequence", tuple(_semantic_value(item) for item in value))
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        return ("float", value)
    if type(value) is str:
        return ("str", value)
    raise OutboxStorageError("Alert semantic data is invalid")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise OutboxStorageError("Alert semantic data is invalid")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite guard above
        raise OutboxStorageError("Alert semantic data is invalid")
    if not any(digits):
        return "0"
    normalized_digits = list(digits)
    normalized_exponent = exponent
    while normalized_digits[-1] == 0:
        normalized_digits.pop()
        normalized_exponent += 1
    coefficient = "".join(str(digit) for digit in normalized_digits)
    prefix = "-" if sign else ""
    return f"{prefix}{coefficient}e{normalized_exponent}"


def _event_hash(event: AlertEvent) -> str:
    value = _canonical_json(event.model_dump(mode="json", round_trip=True))
    return sha256(value.encode("utf-8")).hexdigest()


def _event_from_row(row: AlertEventRow) -> AlertEvent:
    try:
        payload = AlertPayload.model_validate_json(row.payload_json)
        identity_matches = row.id == str(payload.event_id) and row.dedup_key == payload.dedup_key
        event = AlertEvent(
            **payload.model_dump(mode="python", round_trip=True),
            sequence=row.sequence,
            message_text=row.message_text,
            created_at=datetime.fromisoformat(row.created_at),
            acknowledged_at=(
                None if row.acknowledged_at is None else datetime.fromisoformat(row.acknowledged_at)
            ),
        )
    except TypeError, ValueError:
        pass
    else:
        if identity_matches:
            return event
    raise OutboxStorageError("Stored alert event is invalid") from None


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
    raise OutboxStorageError("Alert data cannot be serialized") from None


__all__ = [
    "AlertIdentityConflictError",
    "AlertNotFoundError",
    "AlertOutbox",
    "DEFAULT_REPLAY_RETENTION",
    "MAX_REPLAY_LIMIT",
    "OutboxError",
    "OutboxStorageError",
]
