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

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import ActionableSignalType
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan, activation_is_eligible_on
from trade_plan_monitor.notifications.models import AlertEvent, AlertPayload
from trade_plan_monitor.notifications.render import render_alert
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventError,
    MonitorEventIdentityConflictError,
    MonitorEventLog,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import ActivePlan, AuditLog, PlanVersion, PlanVersionStatus
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

DEFAULT_REPLAY_RETENTION = timedelta(days=7)
MAX_REPLAY_LIMIT = 1_000
MAX_ALERT_LIST_LIMIT = 100
MAX_ALERT_LIST_ROWS = 10_000
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


class AlertRevisionConflictError(OutboxError):
    """The caller's acknowledgement revision is no longer current."""

    code = "ALERT_REVISION_CONFLICT"


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
        events: MonitorEventLog | None = None,
    ) -> None:
        if not isinstance(replay_retention, timedelta) or replay_retention <= timedelta(0):
            raise ValueError("replay_retention must be a positive timedelta")
        self._session = session
        self._clock = clock
        self._id_factory = id_factory
        self._replay_retention = replay_retention
        self._events = events or MonitorEventLog(
            session,
            clock=clock,
            replay_retention=replay_retention,
        )

    def enqueue(self, payload: AlertPayload) -> AlertEvent:
        """Atomically claim one dedup key and return its stable event."""

        if type(payload) is not AlertPayload:
            raise TypeError("payload must be an AlertPayload")

        lock_failure = False
        try:
            self._events.lock_for_append()
        except MonitorEventError:
            lock_failure = True
        if lock_failure:
            raise OutboxStorageError("Alert event could not be persisted")
        existing = self._session.scalar(
            select(AlertEventRow).where(AlertEventRow.dedup_key == payload.dedup_key)
        )
        if existing is not None:
            return self._deduplicated_event(existing, payload)

        event_id = str(payload.event_id)
        if self._session.get(AlertEventRow, event_id) is not None:
            raise AlertIdentityConflictError("Alert event identity is already in use")

        created_at = self._now()
        if created_at < payload.evaluated_at:
            raise ValueError("clock cannot precede alert evaluation")
        monitor_draft = MonitorEventDraft(
            event_id=payload.event_id,
            event_type=MonitorEventType.ALERT_CREATED,
            aggregate_id=event_id,
            payload=MonitorEventPayload(
                entity_id=event_id,
                symbol=payload.symbol,
                revision=0,
            ),
            occurred_at=created_at,
        )
        monitor_event = None
        message_text = render_alert(payload)
        integrity_failure = False
        monitor_identity_failure = False
        monitor_storage_failure = False
        try:
            with self._session.begin_nested():
                monitor_event = self._events.append(monitor_draft)
                row = AlertEventRow(
                    id=event_id,
                    sequence=monitor_event.sequence,
                    dedup_key=payload.dedup_key,
                    payload_json=_payload_json(payload),
                    message_text=message_text,
                    created_at=created_at.isoformat(),
                    acknowledged_at=None,
                )
                self._session.add(row)
                self._session.flush()
        except MonitorEventIdentityConflictError:
            self._session.expire_all()
            monitor_identity_failure = True
        except MonitorEventError:
            self._session.expire_all()
            monitor_storage_failure = True
        except IntegrityError:
            self._session.expire_all()
            integrity_failure = True

        if monitor_identity_failure:
            raise AlertIdentityConflictError("Alert event identity is already in use")
        if monitor_storage_failure:
            raise OutboxStorageError("Alert event could not be persisted")
        if integrity_failure:
            existing = self._session.scalar(
                select(AlertEventRow).where(AlertEventRow.dedup_key == payload.dedup_key)
            )
            if existing is not None:
                return self._deduplicated_event(existing, payload)
            raise OutboxStorageError("Alert event could not be persisted") from None
        if monitor_event is None:  # pragma: no cover - assigned before the alert insert
            raise OutboxStorageError("Alert event could not be persisted")
        event = AlertEvent(
            **payload.model_dump(mode="python", round_trip=True),
            sequence=monitor_event.sequence,
            message_text=message_text,
            created_at=created_at,
            acknowledged_at=None,
        )
        return event

    def has_dedup_key(self, dedup_key: str) -> bool:
        """Return whether one validated durable alert identity already exists."""

        normalized_key = _dedup_key(dedup_key)
        row = self._session.scalar(
            select(AlertEventRow).where(AlertEventRow.dedup_key == normalized_key).limit(1)
        )
        if row is None:
            return False
        _event_from_row(row)
        return True

    def get(self, event_id: UUID) -> AlertEvent:
        """Return one event visible to the current transaction."""

        normalized_id = _event_id(event_id)
        row = self._session.get(AlertEventRow, normalized_id)
        if row is None:
            raise AlertNotFoundError("Alert event was not found")
        return _event_from_row(row)

    def is_current_actionable(
        self,
        event: AlertEvent,
        *,
        market_date: date,
    ) -> bool:
        """Return whether a retained alert still belongs to the current active plan."""

        if type(event) is not AlertEvent:
            raise TypeError("event must be an AlertEvent")
        if isinstance(market_date, datetime) or not isinstance(market_date, date):
            raise TypeError("market_date must be a date")
        plan = self._active_plan_for_event(event)
        return plan is not None and activation_is_eligible_on(plan.activation, market_date)

    def is_delivery_allowed(
        self,
        event: AlertEvent,
        *,
        market_date: date,
    ) -> bool:
        """Allow current alerts plus target-date-valid cross-day risk recovery."""

        if type(event) is not AlertEvent:
            raise TypeError("event must be an AlertEvent")
        if isinstance(market_date, datetime) or not isinstance(market_date, date):
            raise TypeError("market_date must be a date")
        plan = self._active_plan_for_event(event)
        if plan is None:
            return False
        if activation_is_eligible_on(plan.activation, market_date):
            return True
        return (
            event.signal_type is ActionableSignalType.RISK_BREACH
            and event.created_at.astimezone(_SHANGHAI).date() > event.trading_date
            and activation_is_eligible_on(plan.activation, event.trading_date)
        )

    def _active_plan_for_event(self, event: AlertEvent) -> TradePlan | None:
        row = self._session.execute(
            select(PlanVersion, ActivePlan)
            .join(ActivePlan, ActivePlan.plan_version_id == PlanVersion.id)
            .where(ActivePlan.symbol == event.symbol)
        ).one_or_none()
        if row is None:
            return False
        version, active = row
        if (
            version.id != active.plan_version_id
            or version.status != PlanVersionStatus.ACTIVE
            or version.plan_id != event.plan_id
            or version.version != event.plan_version
            or version.plan_hash != event.plan_hash
            or version.symbol != event.symbol
        ):
            return False
        try:
            plan = load_plan_json(version.payload_json)
        except (TypeError, ValueError):
            raise OutboxStorageError("Stored plan data is invalid") from None
        if plan_sha256(plan) != event.plan_hash:
            raise OutboxStorageError("Stored plan data is invalid")
        return plan

    def list_events(
        self,
        *,
        symbol: str | None,
        signal_type: str | None,
        acknowledged: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[AlertEvent, ...], int]:
        """Return one stable bounded page in committed delivery order."""

        if symbol is not None and (
            type(symbol) is not str or not _is_share_symbol(symbol)
        ):
            raise ValueError("symbol must be a canonical A-share identity")
        if signal_type is not None and (
            not isinstance(signal_type, str) or signal_type not in _ACTIONABLE_SIGNAL_TYPES
        ):
            raise ValueError("signal_type must be actionable")
        if acknowledged is not None and type(acknowledged) is not bool:
            raise TypeError("acknowledged must be a boolean or None")
        if (start_at is None) != (end_at is None):
            raise ValueError("alert time filters must appear together")
        if start_at is not None and end_at is not None:
            normalized_start = _query_datetime(start_at)
            normalized_end = _query_datetime(end_at)
            if normalized_start > normalized_end:
                raise ValueError("alert time filter is reversed")
        else:
            normalized_start = None
            normalized_end = None
        if type(offset) is not int or not 0 <= offset <= MAX_ALERT_LIST_ROWS:
            raise ValueError(f"offset must be between 0 and {MAX_ALERT_LIST_ROWS}")
        if type(limit) is not int or not 1 <= limit <= MAX_ALERT_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_ALERT_LIST_LIMIT}")

        filters = []
        if symbol is not None:
            filters.append(func.json_extract(AlertEventRow.payload_json, "$.symbol") == symbol)
        if signal_type is not None:
            filters.append(
                func.json_extract(AlertEventRow.payload_json, "$.signal_type") == signal_type
            )
        if acknowledged is not None:
            acknowledgement_column = AlertEventRow.acknowledged_at
            filters.append(
                acknowledgement_column.is_not(None)
                if acknowledged
                else acknowledgement_column.is_(None)
            )
        if normalized_start is not None and normalized_end is not None:
            filters.extend(
                (
                    AlertEventRow.created_at >= normalized_start.isoformat(),
                    AlertEventRow.created_at <= normalized_end.isoformat(),
                )
            )

        total = self._session.scalar(
            select(func.count()).select_from(AlertEventRow).where(*filters)
        )
        bounded_total = min(total or 0, MAX_ALERT_LIST_ROWS)
        if offset >= bounded_total:
            return (), bounded_total
        effective_limit = min(limit, bounded_total - offset)
        rows = self._session.scalars(
            select(AlertEventRow)
            .where(*filters)
            .order_by(AlertEventRow.sequence)
            .offset(offset)
            .limit(effective_limit)
        ).all()
        return tuple(_event_from_row(row) for row in rows), bounded_total

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

    def acknowledge(
        self,
        event_id: UUID,
        *,
        expected_revision: int | None = None,
    ) -> AlertEvent:
        """Mark an alert seen once without touching delivery or strategy state."""

        normalized_id = _event_id(event_id)
        if expected_revision is not None and expected_revision not in {0, 1}:
            raise ValueError("expected_revision must be zero or one")
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
        current_revision = 0 if before.acknowledged_at is None else 1
        if expected_revision is not None and expected_revision != current_revision:
            raise AlertRevisionConflictError("Alert acknowledgement revision is stale")
        if before.acknowledged_at is not None:
            return before

        acknowledged_at = self._now()
        if acknowledged_at < before.created_at:
            raise ValueError("clock cannot precede alert creation")
        integrity_failure = False
        monitor_failure = False
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
                self._events.append(
                    MonitorEventDraft(
                        event_id=monitor_event_id(
                            MonitorEventType.ALERT_ACKNOWLEDGED,
                            normalized_id,
                            "acknowledged",
                        ),
                        event_type=MonitorEventType.ALERT_ACKNOWLEDGED,
                        aggregate_id=normalized_id,
                        payload=MonitorEventPayload(
                            entity_id=normalized_id,
                            symbol=after.symbol,
                            revision=1,
                        ),
                        occurred_at=acknowledged_at,
                    )
                )
                self._session.flush()
        except MonitorEventError:
            self._session.expire_all()
            monitor_failure = True
        except IntegrityError:
            self._session.expire_all()
            integrity_failure = True

        if monitor_failure or integrity_failure:
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

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return value.astimezone(_SHANGHAI)


def _event_id(value: UUID) -> str:
    if type(value) is not UUID:
        raise TypeError("event_id must be a UUID")
    return str(value)


def _dedup_key(value: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("dedup_key must be a lowercase SHA-256 digest")
    return value


_ACTIONABLE_SIGNAL_TYPES = {
    "BUY_CORE_READY",
    "BUY_TACTICAL_READY",
    "PRESSURE_REDUCE_READY",
    "RISK_BREACH",
    "RISK_EXIT_READY",
    "RISK_EXIT_PENDING_SETTLEMENT",
}


def _is_share_symbol(value: str) -> bool:
    prefix, separator, suffix = value.partition(".")
    return (
        separator == "."
        and len(prefix) == 6
        and prefix.isascii()
        and prefix.isdecimal()
        and suffix in {"BJ", "SH", "SZ"}
    )


def _query_datetime(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("alert time filter must be an aware datetime")
    normalized = value.astimezone(_SHANGHAI)
    if normalized.utcoffset() != timedelta(hours=8):  # pragma: no cover - zone invariant
        raise ValueError("alert time filter must use Shanghai time")
    return normalized


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
    "AlertRevisionConflictError",
    "AlertOutbox",
    "DEFAULT_REPLAY_RETENTION",
    "MAX_ALERT_LIST_LIMIT",
    "MAX_ALERT_LIST_ROWS",
    "MAX_REPLAY_LIMIT",
    "OutboxError",
    "OutboxStorageError",
]
