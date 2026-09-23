"""Persistent, per-channel dispatch for committed notification outbox events."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from trade_plan_monitor.notifications.channels import (
    ChannelDeliveryResult,
    ChannelErrorCode,
    ConsoleChannel,
    DeliveryChannel,
    InAppChannel,
    NotificationChannel,
    NotificationEvent,
)
from trade_plan_monitor.notifications.outbox import AlertOutbox, OutboxError
from trade_plan_monitor.state.models import ActivePlan as ActivePlanRow
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow
from trade_plan_monitor.state.models import DeliveryAttempt as DeliveryAttemptRow
from trade_plan_monitor.state.models import PlanVersion as PlanVersionRow
from trade_plan_monitor.state.models import PlanVersionStatus

SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
Admission = Callable[[NotificationEvent, datetime], bool]

DEFAULT_RETRY_BACKOFF = (
    timedelta(seconds=30),
    timedelta(seconds=60),
    timedelta(seconds=300),
)
DEFAULT_CLAIM_LEASE = timedelta(seconds=60)
MAX_DISPATCH_LIMIT = 100
_MAX_RETRY_DELAYS = 10
_MAX_RETRY_DELAY = timedelta(days=1)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CHANNEL_ORDER = {
    DeliveryChannel.IN_APP: 0,
    DeliveryChannel.CONSOLE: 1,
    DeliveryChannel.WEBHOOK: 2,
}


class DeliveryAttemptStatus(StrEnum):
    """Closed durable state machine for one channel attempt."""

    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DeliveryAttemptRecord:
    """Secret-free immutable view of one persisted delivery attempt."""

    id: str
    event_id: UUID
    channel: DeliveryChannel
    attempt: int
    status: DeliveryAttemptStatus
    response_code: int | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    error_code: ChannelErrorCode | None


@dataclass(frozen=True, slots=True)
class _AttemptPlan:
    attempt: int
    existing_id: str | None = None
    expected_lease: str | None = None


@dataclass(frozen=True, slots=True)
class _AttemptClaim:
    id: str
    event_id: UUID
    channel: DeliveryChannel
    attempt: int
    lease_until: datetime


class DeliveryDispatchError(RuntimeError):
    """Base for sanitized dispatcher failures."""

    code = "DELIVERY_DISPATCH_ERROR"


class DeliveryStorageError(DeliveryDispatchError):
    """Durable outbox or attempt state could not be read or updated safely."""

    code = "DELIVERY_STORAGE_ERROR"


class NotificationDispatcher:
    """Deliver committed alerts without holding a transaction over channel I/O."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        channels: Iterable[NotificationChannel] | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        retry_backoff: tuple[timedelta, ...] = DEFAULT_RETRY_BACKOFF,
        enforce_current_plan: bool = False,
        admission: Admission | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory
        self._clock = clock or _system_clock
        self._id_factory = id_factory or _system_id
        self._retry_backoff = _validated_retry_backoff(retry_backoff)
        if type(enforce_current_plan) is not bool:
            raise TypeError("enforce_current_plan must be a boolean")
        self._enforce_current_plan = enforce_current_plan
        if admission is not None and not callable(admission):
            raise TypeError("admission must be callable")
        self._admission = admission
        self._scan_after: dict[DeliveryChannel, int] = {}

        configured = (
            (InAppChannel(), ConsoleChannel()) if channels is None else _bounded_channels(channels)
        )
        has_in_app = any(
            getattr(channel, "channel", None) is DeliveryChannel.IN_APP for channel in configured
        )
        if not has_in_app:
            configured = (InAppChannel(), *configured)
        by_name: dict[DeliveryChannel, NotificationChannel] = {}
        for channel in configured:
            channel_name = getattr(channel, "channel", None)
            if not isinstance(channel_name, DeliveryChannel):
                raise TypeError("channels must implement the notification channel contract")
            if not isinstance(getattr(channel, "enabled", None), bool):
                raise TypeError("channels must expose a boolean enabled state")
            if not callable(getattr(channel, "deliver", None)):
                raise TypeError("channels must implement asynchronous delivery")
            if channel_name in by_name:
                raise ValueError("each notification channel may be configured only once")
            by_name[channel_name] = channel
        self._channels = tuple(
            sorted(by_name.values(), key=lambda item: _CHANNEL_ORDER[item.channel])
        )

    async def dispatch_pending(
        self,
        *,
        limit: int = MAX_DISPATCH_LIMIT,
    ) -> tuple[DeliveryAttemptRecord, ...]:
        """Attempt at most ``limit`` due event/channel pairs in stable order."""

        _validate_dispatch_limit(limit)
        now = self._now()
        pending: list[tuple[NotificationEvent, NotificationChannel]] = []
        for channel in self._enabled_channels():
            pending.extend((event, channel) for event in self._pending_events(channel, now, limit))
        pending.sort(key=lambda item: (item[0].sequence, _CHANNEL_ORDER[item[1].channel]))

        attempts: list[DeliveryAttemptRecord] = []
        for event, channel in pending[:limit]:
            attempt = await self._dispatch_if_due(event, channel)
            if attempt is not None:
                attempts.append(attempt)
        return tuple(attempts)

    async def dispatch_event(self, event_id: UUID) -> tuple[DeliveryAttemptRecord, ...]:
        """Attempt every due enabled channel for one committed event."""

        normalized_id = _event_id(event_id)
        event = self._load_event(normalized_id)
        if not self._event_is_delivery_allowed(event, self._now()):
            return ()
        attempts: list[DeliveryAttemptRecord] = []
        for channel in self._enabled_channels():
            attempt = await self._dispatch_if_due(event, channel)
            if attempt is not None:
                attempts.append(attempt)
        return tuple(attempts)

    async def aclose(self) -> None:
        """Close channel resources that expose an asynchronous close hook."""

        for channel in self._channels:
            close = getattr(channel, "aclose", None)
            if callable(close):
                await close()

    def _enabled_channels(self) -> tuple[NotificationChannel, ...]:
        return tuple(channel for channel in self._channels if channel.enabled)

    async def _dispatch_if_due(
        self,
        event: NotificationEvent,
        channel: NotificationChannel,
    ) -> DeliveryAttemptRecord | None:
        claim_started_at = self._now()
        if not self._event_is_delivery_allowed(event, claim_started_at):
            return None
        plan = self._next_attempt_plan(event.event_id, channel.channel, claim_started_at)
        if plan is None:
            return None
        claim = self._claim_attempt(
            event.event_id,
            channel.channel,
            plan,
            claim_started_at,
        )
        if claim is None:
            return None

        # The claim and the channel call are separate transactions. A plan, risk
        # result or holding can change in between, so the final check is here.
        if self._admission is not None and not self._event_is_delivery_allowed(
            event, self._now()
        ):
            return None

        try:
            result = await channel.deliver(event)
        except Exception:
            result = ChannelDeliveryResult(
                channel=channel.channel,
                delivered=False,
                retryable=True,
                response_code=None,
                error_code=ChannelErrorCode.CHANNEL_FAILURE,
            )
        if type(result) is not ChannelDeliveryResult or result.channel is not channel.channel:
            result = ChannelDeliveryResult(
                channel=channel.channel,
                delivered=False,
                retryable=True,
                response_code=None,
                error_code=ChannelErrorCode.CHANNEL_FAILURE,
            )
        return self._finalize_claim(
            claim,
            result,
            self._now(),
        )

    def _pending_events(
        self,
        channel: NotificationChannel,
        now: datetime,
        limit: int,
    ) -> tuple[NotificationEvent, ...]:
        latest_number = (
            select(func.max(DeliveryAttemptRow.attempt))
            .where(
                DeliveryAttemptRow.event_id == AlertEventRow.id,
                DeliveryAttemptRow.channel == channel.channel.value,
            )
            .correlate(AlertEventRow)
            .scalar_subquery()
        )
        latest = aliased(DeliveryAttemptRow)
        known_statuses = tuple(status.value for status in DeliveryAttemptStatus)
        statement = select(AlertEventRow).outerjoin(
            latest,
            and_(
                latest.event_id == AlertEventRow.id,
                latest.channel == channel.channel.value,
                latest.attempt == latest_number,
            ),
        )
        if self._enforce_current_plan and self._admission is None:
            statement = statement.join(
                ActivePlanRow,
                ActivePlanRow.symbol
                == func.json_extract(AlertEventRow.payload_json, "$.symbol"),
            ).join(
                PlanVersionRow,
                and_(
                    PlanVersionRow.id == ActivePlanRow.plan_version_id,
                    PlanVersionRow.plan_id
                    == func.json_extract(AlertEventRow.payload_json, "$.plan_id"),
                    PlanVersionRow.version
                    == func.json_extract(AlertEventRow.payload_json, "$.plan_version"),
                    PlanVersionRow.plan_hash
                    == func.json_extract(AlertEventRow.payload_json, "$.plan_hash"),
                    PlanVersionRow.status == PlanVersionStatus.ACTIVE,
                ),
            )
        statement = (
            statement
            .where(
                or_(
                    latest.id.is_(None),
                    and_(
                        latest.status == DeliveryAttemptStatus.RETRY_PENDING.value,
                        or_(
                            latest.next_retry_at.is_(None),
                            latest.next_retry_at <= now.isoformat(),
                        ),
                    ),
                    and_(
                        latest.status == DeliveryAttemptStatus.CLAIMED.value,
                        or_(
                            latest.next_retry_at.is_(None),
                            latest.next_retry_at <= now.isoformat(),
                        ),
                    ),
                    latest.status.not_in(known_statuses),
                )
            )
            .order_by(AlertEventRow.sequence)
            .limit(limit)
        )
        if self._admission is not None:
            statement = statement.where(
                AlertEventRow.sequence > self._scan_after.get(channel.channel, 0)
            )
        loaded: tuple[NotificationEvent, ...] | None = None
        try:
            with self._session_factory() as session:
                rows = session.scalars(statement).all()
                outbox = AlertOutbox(
                    session,
                    clock=self._clock,
                    id_factory=self._id_factory,
                )
                candidates = tuple(outbox.get(UUID(row.id)) for row in rows)
                loaded = tuple(
                    event
                    for event in candidates
                    if self._admission is not None or not self._enforce_current_plan
                    or outbox.is_delivery_allowed(event, market_date=now.date())
                )[:limit]
                if self._admission is not None:
                    self._scan_after[channel.channel] = (
                        rows[-1].sequence if rows else 0
                    )
        except OutboxError, SQLAlchemyError, TypeError, ValueError:
            pass
        if loaded is None:
            raise DeliveryStorageError("Pending alert delivery state is invalid")
        return loaded

    def _load_event(self, event_id: UUID) -> NotificationEvent:
        loaded: NotificationEvent | None = None
        try:
            with self._session_factory() as session:
                loaded = AlertOutbox(
                    session,
                    clock=self._clock,
                    id_factory=self._id_factory,
                ).get(event_id)
        except OutboxError, SQLAlchemyError, TypeError, ValueError:
            pass
        if loaded is None:
            raise DeliveryStorageError("Committed alert event is unavailable")
        return loaded

    def _event_is_delivery_allowed(self, event: NotificationEvent, now: datetime) -> bool:
        if self._admission is not None:
            try:
                allowed = self._admission(event, now)
            except DeliveryDispatchError:
                raise
            except Exception:
                raise DeliveryStorageError("Alert delivery authority is unavailable") from None
            if type(allowed) is not bool:
                raise DeliveryStorageError("Alert delivery authority is invalid")
            return allowed
        if not self._enforce_current_plan:
            return True
        allowed: bool | None = None
        try:
            with self._session_factory() as session:
                allowed = AlertOutbox(
                    session,
                    clock=self._clock,
                    id_factory=self._id_factory,
                ).is_delivery_allowed(event, market_date=now.date())
        except OutboxError, SQLAlchemyError, TypeError, ValueError:
            pass
        if allowed is None:
            raise DeliveryStorageError("Alert delivery validity is unavailable")
        return allowed

    def _next_attempt_plan(
        self,
        event_id: UUID,
        channel: DeliveryChannel,
        now: datetime,
    ) -> _AttemptPlan | None:
        plan: _AttemptPlan | None = None
        completed = False
        try:
            with self._session_factory() as session:
                latest = session.scalar(
                    select(DeliveryAttemptRow)
                    .where(
                        DeliveryAttemptRow.event_id == str(event_id),
                        DeliveryAttemptRow.channel == channel.value,
                    )
                    .order_by(DeliveryAttemptRow.attempt.desc())
                    .limit(1)
                )
                if latest is None:
                    plan = _AttemptPlan(attempt=1)
                else:
                    status = DeliveryAttemptStatus(latest.status)
                    if status is DeliveryAttemptStatus.RETRY_PENDING:
                        if latest.attempt >= self._max_attempts:
                            raise ValueError("pending delivery exceeded its attempt bound")
                        next_retry_at = _stored_datetime(latest.next_retry_at)
                        if next_retry_at is None:
                            raise ValueError("pending delivery is missing its retry time")
                        if next_retry_at <= now:
                            plan = _AttemptPlan(attempt=latest.attempt + 1)
                    elif status is DeliveryAttemptStatus.CLAIMED:
                        lease_until = _stored_datetime(latest.next_retry_at)
                        if lease_until is None:
                            raise ValueError("claimed delivery is missing its lease time")
                        if lease_until <= now:
                            plan = _AttemptPlan(
                                attempt=latest.attempt,
                                existing_id=_delivery_id(latest.id),
                                expected_lease=latest.next_retry_at,
                            )
                completed = True
        except SQLAlchemyError, TypeError, ValueError:
            pass
        if not completed:
            raise DeliveryStorageError("Stored delivery attempt is invalid")
        return plan

    def _claim_attempt(
        self,
        event_id: UUID,
        channel: DeliveryChannel,
        plan: _AttemptPlan,
        claimed_at: datetime,
    ) -> _AttemptClaim | None:
        lease_until = claimed_at + DEFAULT_CLAIM_LEASE
        if plan.existing_id is not None:
            reclaimed = False
            completed = False
            try:
                with self._session_factory() as session:
                    with session.begin():
                        result = session.execute(
                            update(DeliveryAttemptRow)
                            .where(
                                DeliveryAttemptRow.id == plan.existing_id,
                                DeliveryAttemptRow.event_id == str(event_id),
                                DeliveryAttemptRow.channel == channel.value,
                                DeliveryAttemptRow.attempt == plan.attempt,
                                DeliveryAttemptRow.status == DeliveryAttemptStatus.CLAIMED.value,
                                DeliveryAttemptRow.next_retry_at == plan.expected_lease,
                            )
                            .values(next_retry_at=lease_until.isoformat())
                            .execution_options(synchronize_session=False)
                        )
                        reclaimed = result.rowcount == 1
                completed = True
            except SQLAlchemyError, TypeError, ValueError:
                pass
            if not completed:
                raise DeliveryStorageError("Delivery attempt could not be reclaimed")
            if not reclaimed:
                return None
            return _AttemptClaim(
                id=plan.existing_id,
                event_id=event_id,
                channel=channel,
                attempt=plan.attempt,
                lease_until=lease_until,
            )

        delivery_id = ""
        collision = False
        completed = False
        try:
            delivery_id = _delivery_id(self._id_factory())
            row = DeliveryAttemptRow(
                id=delivery_id,
                event_id=str(event_id),
                channel=channel.value,
                attempt=plan.attempt,
                status=DeliveryAttemptStatus.CLAIMED.value,
                response_code=None,
                next_retry_at=lease_until.isoformat(),
                delivered_at=None,
                error_code=None,
            )
            with self._session_factory() as session:
                with session.begin():
                    session.add(row)
                    session.flush()
            completed = True
        except IntegrityError:
            collision = True
        except SQLAlchemyError, TypeError, ValueError:
            pass
        if completed:
            return _AttemptClaim(
                id=delivery_id,
                event_id=event_id,
                channel=channel,
                attempt=plan.attempt,
                lease_until=lease_until,
            )
        if not collision:
            raise DeliveryStorageError("Delivery attempt could not be claimed")

        competing_claim = None
        lookup_completed = False
        try:
            with self._session_factory() as session:
                competing_claim = session.scalar(
                    select(DeliveryAttemptRow.id).where(
                        DeliveryAttemptRow.event_id == str(event_id),
                        DeliveryAttemptRow.channel == channel.value,
                        DeliveryAttemptRow.attempt == plan.attempt,
                    )
                )
            lookup_completed = True
        except SQLAlchemyError, TypeError, ValueError:
            pass
        if not lookup_completed:
            raise DeliveryStorageError("Competing delivery claim could not be checked")
        if competing_claim is not None:
            return None
        raise DeliveryStorageError("Delivery attempt identity could not be claimed")

    def _finalize_claim(
        self,
        claim: _AttemptClaim,
        result: ChannelDeliveryResult,
        completed_at: datetime,
    ) -> DeliveryAttemptRecord | None:
        if result.delivered:
            status = DeliveryAttemptStatus.DELIVERED
            next_retry_at = None
            delivered_at = completed_at
        elif result.retryable and claim.attempt < self._max_attempts:
            status = DeliveryAttemptStatus.RETRY_PENDING
            next_retry_at = completed_at + self._retry_backoff[claim.attempt - 1]
            delivered_at = None
        else:
            status = DeliveryAttemptStatus.FAILED
            next_retry_at = None
            delivered_at = None

        finalized = False
        completed = False
        try:
            with self._session_factory() as session:
                with session.begin():
                    update_result = session.execute(
                        update(DeliveryAttemptRow)
                        .where(
                            DeliveryAttemptRow.id == claim.id,
                            DeliveryAttemptRow.event_id == str(claim.event_id),
                            DeliveryAttemptRow.channel == claim.channel.value,
                            DeliveryAttemptRow.attempt == claim.attempt,
                            DeliveryAttemptRow.status == DeliveryAttemptStatus.CLAIMED.value,
                            DeliveryAttemptRow.next_retry_at == claim.lease_until.isoformat(),
                        )
                        .values(
                            status=status.value,
                            response_code=result.response_code,
                            next_retry_at=(
                                None if next_retry_at is None else next_retry_at.isoformat()
                            ),
                            delivered_at=(
                                None if delivered_at is None else delivered_at.isoformat()
                            ),
                            error_code=(
                                None if result.error_code is None else result.error_code.value
                            ),
                        )
                        .execution_options(synchronize_session=False)
                    )
                    finalized = update_result.rowcount == 1
            completed = True
        except SQLAlchemyError, TypeError, ValueError:
            pass
        if not completed:
            raise DeliveryStorageError("Delivery attempt could not be finalized")
        if not finalized:
            return None
        return DeliveryAttemptRecord(
            id=claim.id,
            event_id=claim.event_id,
            channel=claim.channel,
            attempt=claim.attempt,
            status=status,
            response_code=result.response_code,
            next_retry_at=next_retry_at,
            delivered_at=delivered_at,
            error_code=result.error_code,
        )

    @property
    def _max_attempts(self) -> int:
        return len(self._retry_backoff) + 1

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return value.astimezone(_SHANGHAI)


def _system_clock() -> datetime:
    return datetime.now(tz=_SHANGHAI)


def _system_id() -> str:
    return str(uuid4())


def _event_id(value: UUID) -> UUID:
    if type(value) is not UUID:
        raise TypeError("event_id must be a UUID")
    return value


def _delivery_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 36:
        raise ValueError("id_factory must return a non-empty identifier of at most 36 characters")
    return value


def _stored_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored delivery timestamp must be timezone aware")
    return parsed.astimezone(_SHANGHAI)


def _bounded_channels(
    channels: Iterable[NotificationChannel],
) -> tuple[NotificationChannel, ...]:
    bounded: list[NotificationChannel] = []
    for channel in channels:
        if len(bounded) == len(DeliveryChannel):
            raise ValueError("channels may contain at most three adapters")
        bounded.append(channel)
    return tuple(bounded)


def _validated_retry_backoff(value: tuple[timedelta, ...]) -> tuple[timedelta, ...]:
    if type(value) is not tuple or len(value) > _MAX_RETRY_DELAYS:
        raise ValueError("retry_backoff must be a bounded tuple")
    if any(
        not isinstance(delay, timedelta) or delay <= timedelta(0) or delay > _MAX_RETRY_DELAY
        for delay in value
    ):
        raise ValueError("retry delays must be positive and at most one day")
    return value


def _validate_dispatch_limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_DISPATCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_DISPATCH_LIMIT}")


__all__ = [
    "DEFAULT_CLAIM_LEASE",
    "DEFAULT_RETRY_BACKOFF",
    "DeliveryAttemptRecord",
    "DeliveryAttemptStatus",
    "DeliveryDispatchError",
    "DeliveryStorageError",
    "MAX_DISPATCH_LIMIT",
    "NotificationDispatcher",
]
