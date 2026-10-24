"""Explicit exception requests; FOLLOW_REMINDERS never supplies human consent."""

from datetime import timedelta

from trade_plan_monitor.backtest.exception_replay import (
    ExceptionExecutionRequestOutcome,
    apply_frozen_exception,
)
from trade_plan_monitor.backtest.response_policy import LoopIntent
from trade_plan_monitor.domain.daily_hash import daily_hash


class LoopExceptionProgram:
    def __init__(self, session):
        self.session = session
        self.program = session.run_input.exception_program
        self.reminders = {}
        self.processed = set()
        self.outcomes, self.requests = [], []

    def retain(self, reminder):
        with self.session.work() as work:
            cause = work.daily.get(reminder.event.cause_id)
        linked = None if cause is None else cause["payload"].get("market_linkage")
        if not linked or not linked.get("calculation", {}).get("approval"):
            return False
        if reminder.execution_candidate:
            self.reminders[reminder.event.cause_id] = reminder
        return True

    def apply(self, runner, frame):
        if self.program is None:
            return
        now = frame.runtime.evaluated_at
        actions = [
            (e.order, "EVENT", e)
            for e in self.program.exception_authorization_events
            if e.event.received_at == now
        ]
        actions.extend((o.order, "OPERATION", o) for o in self.program.operations if o.at == now)
        for _, kind, value in sorted(actions, key=lambda row: row[0]):
            key = (kind, value.envelope_hash if kind == "EVENT" else value.operation_id)
            if key in self.processed:
                continue
            self.processed.add(key)
            if kind == "EVENT":
                self.outcomes.append(apply_frozen_exception(self.session, value))
                runner._evaluate(frame.runtime)
            else:
                self.requests.append(self._request(runner, value))

    def _request(self, runner, operation):
        reason, intent = None, None
        with self.session.work() as work:
            causes = [
                row
                for row in work.daily.iter_records(symbol=self.session.plan.symbol, kind="SIGNAL")
                if row["payload"]["rule_id"] == operation.rule_id
            ]
        cause = (
            causes[operation.occurrence - 1]
            if operation.occurrence is not None and operation.occurrence <= len(causes)
            else None
        )
        reminder = None if cause is None else self.reminders.get(cause["id"])
        if self.session.run_input.response.mode == "OBSERVE_ONLY":
            reason = "LOOP_OBSERVE_ONLY"
        elif reminder is None:
            reason = "EXCEPTION_REPLAY_EXECUTABLE_REMINDER_MISSING"
        elif operation.quantity != reminder.event.quantity:
            reason = "EXCEPTION_REPLAY_FULL_QUANTITY_REQUIRED"
        elif len(runner.policy.intents) >= self.session.run_input.limits.max_intents:
            raise ValueError("LOOP_INTENT_LIMIT_EXCEEDED")
        else:
            identity = daily_hash(
                "exception-loop-operation-v1",
                {
                    "authority": self.session.selection.authority_id,
                    "operation_id": operation.operation_id,
                },
            )
            ready = max(operation.at, reminder.captured_at) + timedelta(
                seconds=self.session.run_input.response.response_delay_seconds
            )
            intent = LoopIntent(identity, reminder, ready)
            runner.policy.intents[identity] = intent
            if runner.report_writer is not None:
                runner.report_writer.requested(intent, operation=operation)
        return ExceptionExecutionRequestOutcome(
            operation_id=operation.operation_id,
            at=operation.at,
            status="BLOCKED" if reason else "REQUESTED",
            blockers=() if reason is None else (reason,),
            intent_id=None if intent is None else intent.intent_id,
        )

    def finish(self):
        if self.program is None:
            return
        cutoff = self.session.run_input.boundary.evidence_cutoff
        required = {
            ("EVENT", e.envelope_hash)
            for e in self.program.exception_authorization_events
            if e.event.received_at <= cutoff
        }
        required.update(
            ("OPERATION", o.operation_id) for o in self.program.operations if o.at <= cutoff
        )
        if required != self.processed:
            raise ValueError("EXCEPTION_REPLAY_TIMELINE_MISSING")
