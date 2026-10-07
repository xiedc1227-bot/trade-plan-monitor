"""Offline single-plan response cycle over frozen, causally available monitoring frames."""

from datetime import time, timedelta
from typing import Literal, Self

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.control import check_cancelled
from trade_plan_monitor.backtest.loop_account import LoopAccountReceipt, calculate_loop_costs
from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.response_policy import ReminderResponsePolicy
from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.simulation import SimulationAuthorityError, SimulationCommand


class LoopFrame(ResearchValue):
    runtime: DailyRuntimeInputs
    minute: MinuteBar | None = None
    daily_limit: DailyLimit | None = None

    @model_validator(mode="after")
    def bound(self) -> Self:
        minute, quote = self.minute, self.runtime.quote
        if minute is not None and (
            quote is None
            or minute.received_at > self.runtime.evaluated_at
            or quote.symbol != minute.symbol
            or quote.price_fen != minute.close_fen
            or quote.quote_at != minute.bar_end
            or quote.available_at != minute.received_at
        ):
            raise ValueError("LOOP_FILL_MINUTE_QUOTE_BINDING_MISMATCH")
        if (
            self.daily_limit is not None
            and minute is not None
            and (
                self.daily_limit.symbol != minute.symbol
                or self.daily_limit.trade_date != minute.bar_end.date()
            )
        ):
            raise ValueError("LOOP_DAILY_LIMIT_BINDING_MISMATCH")
        return self


class LoopAttempt(ResearchValue):
    intent_id: str
    cause_id: str
    at: LoopTimestamp
    minute: MinuteBar
    status: Literal["FILLED", "BLOCKED", "CLOSED"]
    reason: str | None
    receipt: LoopAccountReceipt | None = None


class LoopCycleSummary(ResearchValue):
    evaluations: int = Field(ge=0, le=70000)
    intents: int = Field(ge=0, le=70000)
    attempts: int = Field(ge=0, le=70000)
    fills: int = Field(ge=0, le=70000)
    unfilled_intents: int = Field(ge=0, le=70000)


class LoopRunner:
    def __init__(self, session, *, emit=None):
        self.session, self.emit = session, emit
        self.policy = ReminderResponsePolicy(
            session.run_input.response,
            authority_id=session.selection.authority_id,
            limit=session.run_input.limits.max_intents,
        )
        self.evaluations = self.attempts = self.fills = 0

    def _evaluate(self, inputs):
        if self.evaluations >= self.session.run_input.limits.max_evaluations:
            raise ValueError("LOOP_EVALUATION_LIMIT_EXCEEDED")
        self.evaluations += 1
        evaluated = self.session.evaluate(inputs)
        for reminder in self.session.capture(evaluated.event_ids):
            self.policy.register(reminder)

    def run(self, frames, *, cancellation_token=None) -> LoopCycleSummary:
        previous = None
        for frame in frames:
            check_cancelled(cancellation_token, "RUN_EVALUATION")
            frame = LoopFrame.model_validate_json(frame.model_dump_json())
            now = frame.runtime.evaluated_at
            if previous is not None and now < previous:
                raise ValueError("LOOP_TIME_ORDER_INVALID")
            previous = now
            if now < self.session.run_input.boundary.started_at:
                continue  # Historical warm-up supplies no reminder or trade authority.
            if now > self.session.run_input.boundary.evidence_cutoff:
                break
            if frame.minute is not None and frame.minute.symbol != self.session.plan.symbol:
                raise ValueError("LOOP_FRAME_SYMBOL_MISMATCH")
            self._evaluate(frame.runtime)
            if frame.minute is None:
                continue
            for intent in self.policy.pending():
                check_cancelled(cancellation_token, "RUN_EVALUATION")
                minute = frame.minute
                start = minute.bar_end - timedelta(minutes=1)
                clock = start.time().replace(tzinfo=None)
                if (
                    start < intent.ready_at
                    or minute.bar_end in intent.attempted_intervals
                    or not (time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15))
                ):
                    continue
                if self.attempts >= self.session.run_input.limits.max_execution_attempts:
                    raise ValueError("LOOP_EXECUTION_ATTEMPT_LIMIT_EXCEEDED")
                intent.attempted_intervals.add(minute.bar_end)
                self.attempts += 1
                command, reason, closed = self._command(intent)
                receipt = None
                if reason is None:
                    reason = self._price_blocker(frame, intent)
                if reason is None:
                    # Reserve the next evaluation before committing; no unrefreshed fill at the cap.
                    if self.evaluations >= self.session.run_input.limits.max_evaluations:
                        raise ValueError("LOOP_EVALUATION_LIMIT_EXCEEDED")
                    try:
                        receipt = self.session.execute(command, request_key=intent.intent_id)
                    except SimulationAuthorityError as error:
                        reason = error.reason
                    except RevisionConflictError:
                        reason = "LOOP_STATE_REVISION_CHANGED"
                    except ValueError as error:
                        if str(error) not in {
                            "LOOP_CASH_UNKNOWN",
                            "LOOP_CASH_INSUFFICIENT",
                            "LOOP_CURRENT_MINUTE_EVIDENCE_REQUIRED",
                        }:
                            raise
                        reason = str(error)
                status = "FILLED" if receipt is not None else "CLOSED" if closed else "BLOCKED"
                if status in {"FILLED", "CLOSED"}:
                    intent.status = status
                if receipt is not None:
                    self.fills += 1
                event = LoopAttempt(
                    intent_id=intent.intent_id,
                    cause_id=intent.reminder.event.cause_id,
                    at=now,
                    minute=minute,
                    status=status,
                    reason=reason,
                    receipt=receipt,
                )
                if self.emit is not None:
                    self.emit(event)
                if receipt is not None:
                    self._evaluate(frame.runtime)
        return LoopCycleSummary(
            evaluations=self.evaluations,
            intents=len(self.policy.intents),
            attempts=self.attempts,
            fills=self.fills,
            unfilled_intents=sum(i.status == "PENDING" for i in self.policy.intents.values()),
        )

    def _command(self, intent):
        event = intent.reminder.event
        with self.session.work() as work:
            cause = work.daily.get(event.cause_id)
            head = work.daily.get("evaluation-head-" + self.session.plan.symbol)
            if cause is None or head is None:
                return None, "LOOP_CURRENT_AUTHORITY_MISSING", True
            payload = cause["payload"]
            if cause["kind"] == "SIGNAL":
                closed = payload["state"] in {"SIMULATED", "EXPIRED", "INVALIDATED"}
                quantity = payload["executable_qty"]
                if closed or quantity == 0:
                    return None, ";".join(payload["blockers"]) or payload["state"], closed
            else:
                action = head["payload"]["risk_action"]
                if payload["status"] == "FULFILLED":
                    return None, "RISK_FULFILLED", True
                if action.get("cause_id") != cause["id"] or action["status"] != "RISK_EXIT":
                    return None, "RISK_NOT_EXECUTABLE", False
                if action != event.risk_scope:
                    return None, "LOOP_RISK_SCOPE_CHANGED", True
                quantity = (action.get("core_qty") or 0) + (action.get("tactical_qty") or 0)
            if quantity != event.quantity:
                return None, "LOOP_AUTHORIZED_QUANTITY_CHANGED", True
            return (
                SimulationCommand(
                    plan_version_id=self.session.identity("version"),
                    cause_id=cause["id"],
                    expected_cause_revision=cause["revision"],
                    expected_inventory_revision=self.session.inventory()["revision"],
                    quantity=quantity,
                ),
                None,
                False,
            )

    def _price_blocker(self, frame, intent):
        limit, minute = frame.daily_limit, frame.minute
        days = tuple(
            day
            for day in frame.runtime.trading_calendar
            if day.exchange == self.session.plan.market and day.cal_date == minute.bar_end.date()
        )
        if len(days) != 1 or not days[0].is_open:
            return "LOOP_TRADING_DAY_UNVERIFIED"
        if limit is None or limit.received_at > frame.runtime.evaluated_at:
            return "LOOP_DAILY_LIMIT_UNAVAILABLE"
        if minute.volume_shares == 0:
            return "LOOP_MINUTE_NOT_TRADABLE"
        if minute.volume_shares < intent.reminder.event.quantity:
            return "LOOP_MINUTE_LIQUIDITY_INSUFFICIENT"
        side = (
            "SELL"
            if intent.reminder.event.signal_type == "RISK_EXIT"
            else (intent.reminder.event.signal_type)
        )
        price = calculate_loop_costs(
            side=side,
            quote_fen=minute.close_fen,
            quantity=intent.reminder.event.quantity,
            costs=self.session.run_input.costs,
        ).fill_price_fen
        if side == "BUY" and (minute.open_fen >= limit.up_limit_fen or price >= limit.up_limit_fen):
            return "LIMIT_UP_LOCKED"
        if side == "SELL" and (
            minute.open_fen <= limit.down_limit_fen or price <= limit.down_limit_fen
        ):
            return "LIMIT_DOWN_LOCKED"
        return None
