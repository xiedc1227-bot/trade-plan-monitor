"""Bounded response intents derived only from eligible captured reminders."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy
from trade_plan_monitor.backtest.reminder_capture import CapturedReminder
from trade_plan_monitor.domain.daily_hash import daily_hash


@dataclass(slots=True)
class LoopIntent:
    intent_id: str
    reminder: CapturedReminder
    ready_at: datetime
    status: str = "PENDING"
    attempted_intervals: set[datetime] = field(default_factory=set)


class ReminderResponsePolicy:
    def __init__(self, policy: LoopResponsePolicy, *, authority_id: str, limit: int):
        self.policy, self.authority_id, self.limit = policy, authority_id, limit
        self.intents: dict[str, LoopIntent] = {}

    def register(self, reminder: CapturedReminder) -> None:
        if self.policy.mode != "FOLLOW_REMINDERS" or not reminder.execution_candidate:
            return
        identity = daily_hash(
            "monitor-loop-intent-v1",
            {
                "authority": self.authority_id,
                "reminder": reminder.event.dedup_key,
            },
        )
        if identity in self.intents:
            return
        if len(self.intents) >= self.limit:
            raise ValueError("LOOP_INTENT_LIMIT_EXCEEDED")
        try:
            ready = reminder.captured_at + timedelta(seconds=self.policy.response_delay_seconds)
        except OverflowError:
            raise ValueError("LOOP_RESPONSE_DELAY_OUTSIDE_RANGE") from None
        self.intents[identity] = LoopIntent(identity, reminder, ready)

    def pending(self) -> tuple[LoopIntent, ...]:
        # Shared monitoring decides conflicts; this order only preserves risk priority.
        return tuple(
            sorted(
                (i for i in self.intents.values() if i.status == "PENDING"),
                key=lambda i: (
                    i.reminder.event.signal_type != "RISK_EXIT",
                    i.ready_at,
                    i.intent_id,
                ),
            )
        )
