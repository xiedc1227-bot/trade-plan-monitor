"""Typed streamed loop audit and market valuations, separate from accounting cost."""

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_account import LoopAccountReceipt, LoopAccountState, SignedFen
from trade_plan_monitor.backtest.loop_input import (
    MAX_LOOP_RECORDS,
    KnownLoopCash,
    SafeFen,
    SafePositiveFen,
)
from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary, LoopTimestamp
from trade_plan_monitor.backtest.reminder_capture import CapturedReminder
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.research_report import ResearchReminder, ResearchRuleEvidence
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.state.daily_state_models import (
    DailyInventoryView,
    DailyRiskAction,
    DailyRiskState,
    DailySignalState,
)

LOOP_REPORT_VERSION = "backtest-report-v4"
LOOP_EVENT_VERSION = "monitor-loop-event-v1"
MAX_AUDIT_EVENTS = 6 * MAX_LOOP_RECORDS + 1
_EVENT_SET_DOMAIN = b"monitor-loop-event-set-v1\0"
_METRIC_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class LoopAttempt(ResearchValue):
    intent_id: str
    cause_id: str
    at: LoopTimestamp
    minute: MinuteBar
    status: Literal["FILLED", "BLOCKED", "CLOSED"]
    reason: str | None
    receipt: LoopAccountReceipt | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "FILLED") != (self.receipt is not None):
            raise ValueError("loop execution status must bind its committed receipt")
        if (self.status == "FILLED") != (self.reason is None):
            raise ValueError("loop execution reason must match its status")
        return self


class LoopCycleSummary(ResearchValue):
    evaluations: int = Field(ge=0, le=MAX_LOOP_RECORDS)
    intents: int = Field(ge=0, le=MAX_LOOP_RECORDS)
    attempts: int = Field(ge=0, le=MAX_LOOP_RECORDS)
    fills: int = Field(ge=0, le=MAX_LOOP_RECORDS)
    unfilled_intents: int = Field(ge=0, le=MAX_LOOP_RECORDS)

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.fills > min(self.attempts, self.intents)
            or self.unfilled_intents > self.intents - self.fills
        ):
            raise ValueError("loop cycle counts are inconsistent")
        return self


class LoopValuation(ResearchValue):
    at: LoopTimestamp
    account_revision: int = Field(ge=1)
    price_fen: SafePositiveFen | None
    price_at: LoopTimestamp | None
    available_at: LoopTimestamp | None
    cash_fen: SafeFen | None
    position_quantity: SafeFen | None
    market_value_fen: SafeFen | None
    equity_fen: SafeFen | None
    accounting_cost_fen: SafeFen | None
    realized_pnl_fen: SignedFen | None
    unrealized_pnl_fen: SignedFen | None
    cost_pnl_fen: SignedFen | None
    valuation_valid: bool
    blockers: tuple[str, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def consistent(self):
        if (self.price_fen is None) != (self.price_at is None) or (
            (self.price_fen is None) != (self.available_at is None)
        ):
            raise ValueError("valuation price requires its original evidence times")
        if self.price_fen is not None and not self.price_at <= self.available_at <= self.at:
            raise ValueError("valuation cannot consume future evidence")
        market = (
            0
            if self.position_quantity == 0
            else None
            if self.position_quantity is None or self.price_fen is None
            else self.position_quantity * self.price_fen
        )
        equity = None if market is None or self.cash_fen is None else market + self.cash_fen
        unrealized = (
            None
            if market is None or self.accounting_cost_fen is None
            else market - self.accounting_cost_fen
        )
        pnl = (
            None
            if unrealized is None or self.realized_pnl_fen is None
            else unrealized + self.realized_pnl_fen
        )
        if (
            self.market_value_fen,
            self.equity_fen,
            self.unrealized_pnl_fen,
            self.cost_pnl_fen,
            self.valuation_valid,
        ) != (market, equity, unrealized, pnl, equity is not None):
            raise ValueError("valuation arithmetic is inconsistent")
        return self


def project_loop_valuation(
    account: LoopAccountState, *, at, price_fen=None, price_at=None, available_at=None
) -> LoopValuation:
    quantity = sum(lot.quantity for lot in account.lots) if account.inventory_known else None
    cash = account.cash.balance_fen if isinstance(account.cash, KnownLoopCash) else None
    market = (
        0
        if quantity == 0
        else None
        if quantity is None or price_fen is None
        else quantity * price_fen
    )
    equity = None if cash is None or market is None else cash + market
    cost = account.accounting_cost_fen
    unrealized = None if cost is None or market is None else market - cost
    pnl = (
        None
        if unrealized is None or account.realized_pnl_fen is None
        else unrealized + account.realized_pnl_fen
    )
    blockers = []
    if cash is None:
        blockers.append("CASH_UNKNOWN")
    if quantity is None:
        blockers.append("INVENTORY_UNKNOWN")
    elif quantity and price_fen is None:
        blockers.append("MARK_PRICE_UNKNOWN")
    if cost is None:
        blockers.append("ACCOUNTING_COST_UNKNOWN")
    return LoopValuation(
        at=at,
        account_revision=account.revision,
        price_fen=price_fen,
        price_at=price_at,
        available_at=available_at,
        cash_fen=cash,
        position_quantity=quantity,
        market_value_fen=market,
        equity_fen=equity,
        accounting_cost_fen=cost,
        realized_pnl_fen=account.realized_pnl_fen,
        unrealized_pnl_fen=unrealized,
        cost_pnl_fen=pnl,
        valuation_valid=equity is not None,
        blockers=tuple(blockers),
    )


class LoopEvaluation(ResearchValue):
    kind: Literal["EVALUATED"] = "EVALUATED"
    evaluation_id: Sha256Hex | None
    duplicate: bool
    official_trade_date: date | None
    minute_target: LoopTimestamp | None
    inventory: DailyInventoryView
    signals: tuple[DailySignalState, ...] = Field(max_length=500)
    risks: tuple[DailyRiskState, ...] = Field(max_length=2)
    alerts: tuple[ResearchReminder, ...] = Field(max_length=10)
    risk_action: DailyRiskAction
    conditions: tuple[ResearchRuleEvidence, ...] = Field(max_length=12)
    blockers: tuple[str, ...] = Field(max_length=20)


class LoopReminder(ResearchValue):
    kind: Literal["REMINDED"] = "REMINDED"
    reminder: CapturedReminder


class LoopRequest(ResearchValue):
    kind: Literal["REQUESTED"] = "REQUESTED"
    intent_id: Sha256Hex
    cause_id: str
    ready_at: LoopTimestamp


class LoopExecution(ResearchValue):
    kind: Literal["EXECUTED"] = "EXECUTED"
    attempt: LoopAttempt


class LoopResultingState(ResearchValue):
    kind: Literal["STATE"] = "STATE"
    account: LoopAccountState
    inventory: DailyInventoryView


class LoopValuationEvent(ResearchValue):
    kind: Literal["VALUATION"] = "VALUATION"
    valuation: LoopValuation


type LoopAuditPayload = Annotated[
    LoopEvaluation
    | LoopReminder
    | LoopRequest
    | LoopExecution
    | LoopResultingState
    | LoopValuationEvent,
    Field(discriminator="kind"),
]


class LoopAuditEvent(ResearchValue):
    schema_version: Literal["monitor-loop-event-v1"] = LOOP_EVENT_VERSION
    run_id: Sha256Hex
    sequence: int = Field(ge=1, le=MAX_AUDIT_EVENTS)
    at: LoopTimestamp
    event_id: Sha256Hex
    cause_event_id: Sha256Hex | None
    payload: LoopAuditPayload

    @model_validator(mode="after")
    def integrity(self):
        if self.event_id != _event_hash(self.model_dump(mode="python", exclude={"event_id"})):
            raise ValueError("loop audit hash mismatch")
        if isinstance(self.payload, LoopExecution) and self.payload.attempt.at != self.at:
            raise ValueError("loop execution time mismatch")
        if isinstance(self.payload, LoopValuationEvent) and self.payload.valuation.at != self.at:
            raise ValueError("loop valuation time mismatch")
        if isinstance(self.payload, LoopReminder) and self.payload.reminder.captured_at != self.at:
            raise ValueError("loop reminder time mismatch")
        return self


def _event_hash(value):
    # The run binds the whole dataset; semantic event identity binds causal past.
    # Run membership remains checked separately and included in the stream digest.
    causal_value = {key: item for key, item in value.items() if key != "run_id"}
    return sha256((LOOP_EVENT_VERSION + "\0" + canonical_json(causal_value)).encode()).hexdigest()


def _digest_event(digest, event):
    raw = canonical_json(event).encode()
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)


class LoopMetrics(ResearchValue):
    initial_equity_fen: SafeFen | None
    final_equity_fen: SafeFen | None
    equity_change_fen: SignedFen | None
    interval_return: Decimal | None
    maximum_drawdown: Decimal | None
    turnover: Decimal | None
    cost_pnl_fen: SignedFen | None
    realized_pnl_fen: SignedFen | None
    unrealized_pnl_fen: SignedFen | None
    paid_fees_fen: SafeFen
    slippage_fen: SafeFen
    valuation_valid: bool
    blockers: tuple[str, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def consistent(self):
        first, last = self.initial_equity_fen, self.final_equity_fen
        valid = first is not None and last is not None
        change = last - first if valid else None
        with localcontext(_METRIC_CONTEXT):
            interval = Decimal(change) / Decimal(first) if valid and first > 0 else None
        if (self.equity_change_fen, self.interval_return, self.valuation_valid) != (
            change,
            interval,
            valid,
        ):
            raise ValueError("loop return must use known positive opening market equity")
        if self.maximum_drawdown is not None and (
            not self.maximum_drawdown.is_finite()
            or not Decimal(0) <= self.maximum_drawdown <= Decimal(1)
        ):
            raise ValueError("loop drawdown is invalid")
        if self.turnover is not None and (not self.turnover.is_finite() or self.turnover < 0):
            raise ValueError("loop turnover is invalid")
        if (self.maximum_drawdown is not None or self.turnover is not None) and (
            not valid or first == 0
        ):
            raise ValueError("loop normalized metrics require a positive market denominator")
        return self


class MonitorLoopReport(ResearchValue):
    schema_version: Literal["backtest-report-v4"] = LOOP_REPORT_VERSION
    run_id: Sha256Hex
    input_hash: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    authority_id: Sha256Hex
    symbol: str
    boundary: LoopEndBoundary
    cycle: LoopCycleSummary
    event_count: int = Field(ge=1, le=MAX_AUDIT_EVENTS)
    event_set_hash: Sha256Hex
    opening_valuation: LoopValuation
    final_valuation: LoopValuation
    final_account: LoopAccountState
    final_inventory: DailyInventoryView
    last_evidence_at: LoopTimestamp | None
    last_valuation_at: LoopTimestamp
    metrics: LoopMetrics
    report_hash: Sha256Hex

    @model_validator(mode="after")
    def integrity(self):
        expected = sha256(
            (
                LOOP_REPORT_VERSION
                + "\0"
                + canonical_json(self.model_dump(mode="python", exclude={"report_hash"}))
            ).encode()
        ).hexdigest()
        if self.report_hash != expected:
            raise ValueError("loop report hash mismatch")
        if not self.boundary.started_at <= self.last_valuation_at <= self.boundary.evidence_cutoff:
            raise ValueError("loop valuation is outside its frozen boundary")
        if (
            self.last_evidence_at is not None
            and self.last_evidence_at > self.boundary.evidence_cutoff
        ):
            raise ValueError("loop evidence is outside its frozen cutoff")
        if (
            self.final_valuation.at != self.last_valuation_at
            or self.final_account.revision != self.final_valuation.account_revision
        ):
            raise ValueError("final loop state/valuation mismatch")
        final = self.final_valuation
        expected_final = project_loop_valuation(
            self.final_account,
            at=final.at,
            price_fen=final.price_fen,
            price_at=final.price_at,
            available_at=final.available_at,
        )
        if final != expected_final or self.opening_valuation.at != self.boundary.started_at:
            raise ValueError("loop report valuation must bind exact account/boundary")
        if (
            self.metrics.initial_equity_fen,
            self.metrics.final_equity_fen,
            self.metrics.cost_pnl_fen,
            self.metrics.realized_pnl_fen,
            self.metrics.unrealized_pnl_fen,
            self.metrics.paid_fees_fen,
        ) != (
            self.opening_valuation.equity_fen,
            final.equity_fen,
            final.cost_pnl_fen,
            final.realized_pnl_fen,
            final.unrealized_pnl_fen,
            self.final_account.paid_fees_fen,
        ):
            raise ValueError("loop report metrics do not match account valuations")
        quantity = (
            sum(lot.quantity for lot in self.final_account.lots)
            if self.final_account.inventory_known
            else None
        )
        if (
            self.final_inventory.symbol != self.symbol
            or self.final_inventory.known != self.final_account.inventory_known
            or self.final_inventory.total_qty != quantity
        ):
            raise ValueError("loop report inventory does not match account lots")
        return self


class LoopReportWriter:
    """Stream event bytes to the caller; only finite causal indexes and metrics stay in memory."""

    def __init__(self, session, *, sink: Callable[[LoopAuditEvent], None]):
        if not callable(sink):
            raise TypeError("loop audit sink must be callable")
        self.session, self.sink = session, sink
        self._sequence = 0
        self._digest = sha256(_EVENT_SET_DOMAIN)
        self._reminders, self._requests = {}, {}
        self._evaluation_id = self._state_id = self._last_event_id = None
        self._last_evidence_at = None
        self._price = self._price_at = self._available_at = None
        opening = session.run_input.initial_account.opening_mark
        if opening is not None:
            self._price, self._price_at, self._available_at = (
                opening.price_fen,
                opening.price_at,
                opening.available_at,
            )
            self._last_evidence_at = opening.available_at
        self.opening = self._mark(session.run_input.boundary.started_at)
        self.final = self.opening
        self._peak = self.opening.equity_fen
        self._drawdown = Decimal(0)
        self._path_valid = self.opening.valuation_valid
        self._notional = self._slippage = 0
        self._finished = False
        self._completed_cycle = None
        self._emit(self.opening.at, LoopValuationEvent(valuation=self.opening))

    def _emit(self, at, payload, cause=None):
        if self._finished:
            raise ValueError("LOOP_REPORT_ALREADY_COMPLETE")
        values = dict(
            schema_version=LOOP_EVENT_VERSION,
            run_id=self.session.run_input.run_id,
            sequence=self._sequence + 1,
            at=at,
            cause_event_id=cause,
            payload=payload,
        )
        event = LoopAuditEvent(event_id=_event_hash(values), **values)
        self.sink(event)  # A failed write never advances the digest or completion identity.
        _digest_event(self._digest, event)
        self._sequence = event.sequence
        self._last_event_id = event.event_id
        return event.event_id

    def evaluated(self, inputs, result):
        with self.session.work() as work:
            facts = tuple(
                {**row["payload"], "id": row["id"]}
                for row in work.daily.list(symbol=self.session.plan.symbol, kind="FACT")
            )
        conditions = tuple(
            ResearchRuleEvidence(
                rule_id=rule.rule_id,
                evidence=evaluate_unified_condition(
                    rule.condition,
                    inputs.series,
                    facts=facts,
                    bars=inputs.five_minute_bars,
                    target=inputs.minute_target,
                    trading_calendar=inputs.trading_calendar,
                    macd_min_observations=500
                    if self.session.plan.monitoring is None
                    else self.session.plan.monitoring.macd_min_observations,
                ),
            )
            for rule in (*self.session.plan.ordinary_rules, *self.session.plan.alert_rules)
        )
        snapshot = result.snapshot
        value = LoopEvaluation.model_validate_json(
            canonical_json(
                dict(
                    evaluation_id=result.evaluation_id,
                    duplicate=result.duplicate,
                    official_trade_date=inputs.official_trade_date,
                    minute_target=inputs.minute_target,
                    inventory=snapshot["inventory"],
                    signals=tuple(snapshot["signals"]),
                    risks=tuple(snapshot["risks"]),
                    alerts=tuple(snapshot.get("alerts", ())),
                    risk_action=snapshot["risk_action"],
                    conditions=conditions,
                    blockers=inputs.data_blockers,
                )
            )
        )
        self._evaluation_id = self._emit(inputs.evaluated_at, value, self._state_id)

    def reminded(self, reminder):
        signature = sha256(canonical_json(reminder).encode()).hexdigest()
        previous = self._reminders.get(reminder.sequence)
        if previous is not None:
            if previous[0] != signature:
                raise ValueError("LOOP_AUDIT_REMINDER_CONFLICT")
            return
        if len(self._reminders) >= MAX_LOOP_RECORDS:
            raise ValueError("LOOP_REMINDER_LIMIT_EXCEEDED")
        identity = self._emit(
            reminder.captured_at, LoopReminder(reminder=reminder), self._evaluation_id
        )
        self._reminders[reminder.sequence] = (signature, identity)

    def requested(self, intent):
        if len(self._requests) >= MAX_LOOP_RECORDS:
            raise ValueError("LOOP_INTENT_LIMIT_EXCEEDED")
        reminder_id = self._reminders[intent.reminder.sequence][1]
        self._requests[intent.intent_id] = self._emit(
            intent.reminder.captured_at,
            LoopRequest(
                intent_id=intent.intent_id,
                cause_id=intent.reminder.event.cause_id,
                ready_at=intent.ready_at,
            ),
            reminder_id,
        )

    def executed(self, attempt):
        identity = self._emit(
            attempt.at, LoopExecution(attempt=attempt), self._requests[attempt.intent_id]
        )
        if attempt.receipt is not None:
            settlement = attempt.receipt.settlement
            self._notional += settlement.notional_fen
            self._slippage += (
                abs(settlement.fill_price_fen - settlement.quote_fen) * settlement.quantity
            )
            self._state_id = self._emit(
                attempt.at,
                LoopResultingState(
                    account=self.session.account(),
                    inventory=DailyInventoryView.model_validate(self.session.inventory()),
                ),
                identity,
            )

    def _mark(self, at):
        return project_loop_valuation(
            self.session.account(),
            at=at,
            price_fen=self._price,
            price_at=self._price_at,
            available_at=self._available_at,
        )

    def observed(self, inputs):
        quote = inputs.quote
        if quote is not None:
            if (
                quote.symbol != self.session.plan.symbol
                or not quote.quote_at <= quote.available_at <= inputs.evaluated_at
            ):
                raise ValueError("LOOP_MARK_EVIDENCE_BINDING_MISMATCH")
            self._price, self._price_at, self._available_at = (
                quote.price_fen,
                quote.quote_at,
                quote.available_at,
            )
            self._last_evidence_at = max(
                self._last_evidence_at or quote.available_at, quote.available_at
            )
        if inputs.series is not None:
            if inputs.series.cutoff > inputs.evaluated_at:
                raise ValueError("LOOP_DAILY_EVIDENCE_FOLLOWS_EVALUATION")
            for bar in inputs.series.bars:
                self._last_evidence_at = max(
                    self._last_evidence_at or bar.received_at, bar.received_at
                )
        self.final = self._mark(inputs.evaluated_at)
        self._path_valid = self._path_valid and self.final.valuation_valid
        if self.final.equity_fen is not None:
            self._peak = max(self._peak or 0, self.final.equity_fen)
            if self._peak > 0:
                with localcontext(_METRIC_CONTEXT):
                    self._drawdown = max(
                        self._drawdown,
                        Decimal(self._peak - self.final.equity_fen) / Decimal(self._peak),
                    )
        self._emit(
            inputs.evaluated_at, LoopValuationEvent(valuation=self.final), self._last_event_id
        )

    def complete_cycle(self, cycle: LoopCycleSummary) -> None:
        if self._completed_cycle is not None or self._finished:
            raise ValueError("LOOP_REPORT_ALREADY_COMPLETE")
        self._completed_cycle = cycle

    def finish(self, cycle: LoopCycleSummary) -> MonitorLoopReport:
        if not isinstance(cycle, LoopCycleSummary) or cycle != self._completed_cycle:
            raise ValueError("LOOP_CYCLE_MUST_COMPLETE")
        if self._finished:
            raise ValueError("LOOP_REPORT_ALREADY_COMPLETE")
        first, last = self.opening.equity_fen, self.final.equity_fen
        valid = first is not None and last is not None
        change = last - first if valid else None
        denominator = valid and first > 0
        blockers = []
        if first is None:
            blockers.append("OPENING_VALUATION_UNKNOWN")
        if last is None:
            blockers.append("FINAL_VALUATION_UNKNOWN")
        if first == 0:
            blockers.append("ZERO_OPENING_EQUITY")
        if not self._path_valid:
            blockers.append("INCOMPLETE_VALUATION_PATH")
        with localcontext(_METRIC_CONTEXT):
            interval = Decimal(change) / Decimal(first) if denominator else None
            turnover = Decimal(self._notional) / Decimal(first) if denominator else None
        account = self.session.account()
        metrics = LoopMetrics(
            initial_equity_fen=first,
            final_equity_fen=last,
            equity_change_fen=change,
            interval_return=interval,
            maximum_drawdown=self._drawdown if denominator and self._path_valid else None,
            turnover=turnover,
            cost_pnl_fen=self.final.cost_pnl_fen,
            realized_pnl_fen=self.final.realized_pnl_fen,
            unrealized_pnl_fen=self.final.unrealized_pnl_fen,
            paid_fees_fen=account.paid_fees_fen,
            slippage_fen=self._slippage,
            valuation_valid=valid,
            blockers=tuple(blockers),
        )
        run = self.session.run_input
        values = dict(
            schema_version=LOOP_REPORT_VERSION,
            run_id=run.run_id,
            input_hash=run.input_hash,
            plan_hash=self.session.selection.version.plan_hash,
            dataset_hash=run.dataset_hash,
            authority_id=self.session.selection.authority_id,
            symbol=self.session.plan.symbol,
            boundary=run.boundary,
            cycle=cycle,
            event_count=self._sequence,
            event_set_hash=self._digest.hexdigest(),
            opening_valuation=self.opening,
            final_valuation=self.final,
            final_account=account,
            final_inventory=DailyInventoryView.model_validate(self.session.inventory()),
            last_evidence_at=self._last_evidence_at,
            last_valuation_at=self.final.at,
            metrics=metrics,
        )
        report = MonitorLoopReport(
            report_hash=sha256(
                (LOOP_REPORT_VERSION + "\0" + canonical_json(values)).encode()
            ).hexdigest(),
            **values,
        )
        self._finished = True
        return report


def verify_loop_events(report: MonitorLoopReport, events: Iterable[LoopAuditEvent]) -> None:
    """Verify ordered canonical bytes and causal ancestry without collecting the trail."""
    report = MonitorLoopReport.model_validate_json(report.model_dump_json())
    digest = sha256(_EVENT_SET_DOMAIN)
    seen, counts = (
        {},
        {kind: 0 for kind in ("EVALUATED", "REMINDED", "REQUESTED", "EXECUTED", "FILLED")},
    )
    sequence, previous = 0, report.boundary.started_at
    opening = final = None
    requests, terminal, attempted, reminders = {}, set(), set(), set()
    causal_inputs = {}
    parents = {
        "REMINDED": "EVALUATED",
        "REQUESTED": "REMINDED",
        "EXECUTED": "REQUESTED",
        "STATE": "EXECUTED",
    }
    for event in events:
        event = LoopAuditEvent.model_validate_json(event.model_dump_json())
        sequence += 1
        if (
            event.run_id != report.run_id
            or event.sequence != sequence
            or not previous <= event.at <= report.boundary.evidence_cutoff
        ):
            raise ValueError("LOOP_AUDIT_ORDER_BINDING_MISMATCH")
        previous = event.at
        kind = event.payload.kind
        if event.cause_event_id is not None and event.cause_event_id not in seen:
            raise ValueError("LOOP_AUDIT_CAUSE_NOT_AVAILABLE")
        if kind in parents and seen.get(event.cause_event_id) != parents[kind]:
            raise ValueError("LOOP_AUDIT_CAUSE_KIND_MISMATCH")
        payload = event.payload
        if kind == "REMINDED":
            reminder = payload.reminder
            if reminder.sequence in reminders:
                raise ValueError("LOOP_AUDIT_REMINDER_REPEATED")
            reminders.add(reminder.sequence)
            if reminder.event.evaluated_at > event.at:
                raise ValueError("LOOP_AUDIT_REMINDER_PRECEDES_EVALUATION")
            causal_inputs[event.event_id] = (
                reminder.event.cause_id,
                reminder.execution_candidate,
                reminder.captured_at,
            )
        elif kind == "REQUESTED":
            cause, eligible, captured_at = causal_inputs[event.cause_event_id]
            if (
                not eligible
                or payload.cause_id != cause
                or payload.ready_at < captured_at
                or payload.intent_id in requests
            ):
                raise ValueError("LOOP_AUDIT_REQUEST_AUTHORITY_MISMATCH")
            requests[payload.intent_id] = (event.event_id, payload.cause_id, payload.ready_at)
        elif kind == "EXECUTED":
            attempt = payload.attempt
            request = requests.get(attempt.intent_id)
            if (
                request is None
                or request[:2] != (event.cause_event_id, attempt.cause_id)
                or attempt.minute.bar_end - timedelta(minutes=1) < request[2]
            ):
                raise ValueError("LOOP_AUDIT_EXECUTION_CAUSE_MISMATCH")
            interval = (attempt.intent_id, attempt.minute.bar_end)
            if attempt.intent_id in terminal or interval in attempted:
                raise ValueError("LOOP_AUDIT_EXECUTION_REPEATED")
            attempted.add(interval)
            if attempt.status in {"FILLED", "CLOSED"}:
                terminal.add(attempt.intent_id)
            causal_inputs[event.event_id] = (
                None
                if attempt.receipt is None
                else sha256(canonical_json(attempt.receipt.account).encode()).hexdigest()
            )
        elif kind == "STATE":
            if (
                causal_inputs[event.cause_event_id]
                != sha256(canonical_json(payload.account).encode()).hexdigest()
            ):
                raise ValueError("LOOP_AUDIT_RESULTING_STATE_MISMATCH")
        seen[event.event_id] = kind
        if kind in counts:
            counts[kind] += 1
            if counts[kind] > MAX_LOOP_RECORDS:
                raise ValueError("LOOP_AUDIT_KIND_LIMIT_EXCEEDED")
        if kind == "EXECUTED" and event.payload.attempt.receipt is not None:
            counts["FILLED"] += 1
        if kind == "VALUATION":
            final = event.payload.valuation
            if opening is None:
                opening = final
        _digest_event(digest, event)
    if (
        sequence != report.event_count
        or digest.hexdigest() != report.event_set_hash
        or final != report.final_valuation
        or opening != report.opening_valuation
        or counts["EVALUATED"] != report.cycle.evaluations
        or counts["REQUESTED"] != report.cycle.intents
        or counts["EXECUTED"] != report.cycle.attempts
        or counts["FILLED"] != report.cycle.fills
        or len(requests) - len(terminal) != report.cycle.unfilled_intents
    ):
        raise ValueError("LOOP_AUDIT_REPORT_BINDING_MISMATCH")
