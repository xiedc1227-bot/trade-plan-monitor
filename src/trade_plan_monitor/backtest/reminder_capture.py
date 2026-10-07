"""Private, bounded delivery receipts; the online eligibility predicate owns authority."""

from typing import Literal

from pydantic import Field
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, func, select

from trade_plan_monitor.backtest.loop_input import MAX_LOOP_RECORDS
from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.notifications.daily_models import DailyAlertEvent
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

CAPTURE_METADATA = MetaData()
CAPTURE_TABLE = Table(
    "monitor_loop_reminder",
    CAPTURE_METADATA,
    Column("sequence", Integer, primary_key=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("payload_json", Text, nullable=False),
)


class CapturedReminder(ResearchValue):
    sequence: int = Field(ge=1, le=MAX_LOOP_RECORDS)
    event: DailyAlertEvent
    captured_at: LoopTimestamp
    status: Literal["CAPTURED", "SUPPRESSED"]
    cause_revision: int | None = Field(ge=1)
    inventory_revision: int = Field(ge=0)

    @property
    def execution_candidate(self) -> bool:
        return (
            self.status == "CAPTURED"
            and self.event.signal_type != "REMINDER"
            and self.event.quantity is not None
            and self.event.quantity > 0
        )


class ReminderCapture:
    """Participate in the caller's private transaction without constructing any sink."""

    def __init__(self, work, *, limit):
        if type(limit) is not int or not 1 <= limit <= MAX_LOOP_RECORDS:
            raise ValueError("invalid reminder limit")
        self.work, self.session, self.limit = work, work.daily.session, limit

    def capture(self, event: DailyAlertEvent, now) -> CapturedReminder:
        prior = self.session.scalar(
            select(CAPTURE_TABLE.c.payload_json).where(
                CAPTURE_TABLE.c.event_id == str(event.event_id)
            )
        )
        if prior is not None:
            stored = CapturedReminder.model_validate_json(prior)
            if stored.event != event:
                raise ValueError("LOOP_REMINDER_ID_CONFLICT")
            return stored
        if now < event.evaluated_at:
            raise ValueError("LOOP_REMINDER_CAPTURE_PRECEDES_EVALUATION")
        count = self.session.scalar(select(func.count()).select_from(CAPTURE_TABLE))
        if count >= self.limit:
            raise ValueError("LOOP_REMINDER_LIMIT_EXCEEDED")
        allowed = daily_delivery_allowed(self.session, event, now)
        cause = self.work.daily.get(event.cause_id)
        position = self.work.daily.get("simulation-position-" + event.symbol)
        value = CapturedReminder(
            sequence=count + 1,
            event=event,
            captured_at=now,
            status="CAPTURED" if allowed else "SUPPRESSED",
            cause_revision=None if cause is None else cause["revision"],
            inventory_revision=0 if position is None else position["revision"],
        )
        self.session.execute(
            CAPTURE_TABLE.insert().values(
                sequence=value.sequence,
                event_id=str(event.event_id),
                payload_json=value.model_dump_json(),
            )
        )
        return value

    def page(self, *, after_sequence=0, limit=100) -> tuple[CapturedReminder, ...]:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or (type(limit) is not int or not 1 <= limit <= 500)
        ):
            raise ValueError("invalid reminder page")
        rows = self.session.scalars(
            select(CAPTURE_TABLE.c.payload_json)
            .where(CAPTURE_TABLE.c.sequence > after_sequence)
            .order_by(CAPTURE_TABLE.c.sequence)
            .limit(limit)
        )
        return tuple(CapturedReminder.model_validate_json(raw) for raw in rows)
