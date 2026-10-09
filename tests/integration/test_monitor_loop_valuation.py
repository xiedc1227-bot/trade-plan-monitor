"""Streamed loop reports retain causal state and honest return denominators."""

from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from tests.integration.test_monitor_loop_cycle import calendar, cycle_input, frames
from tests.unit.test_monitor_loop_input import account, lot
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.loop_input import (
    KnownLoopCash,
    LoopOpeningMark,
    LoopResponsePolicy,
)
from trade_plan_monitor.backtest.loop_report import (
    LoopCycleSummary,
    LoopReportWriter,
    MonitorLoopReport,
    verify_loop_events,
)
from trade_plan_monitor.backtest.loop_runner import LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession


def report_case(tmp_path, value=None, source=None):
    events = []
    with LoopSession(tmp_path, value or cycle_input(), calendar()) as session:
        writer = LoopReportWriter(session, sink=events.append)
        summary = LoopRunner(session, report_writer=writer).run(source or frames())
        report = writer.finish(summary)
        assert not hasattr(writer, "events")
        verify_loop_events(report, iter(events))
    return report, events


def test_evaluated_reminded_requested_executed_and_resulting_state_are_causal(tmp_path):
    report, events = report_case(tmp_path)
    assert report.schema_version == "backtest-report-v4"
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    by_id = {event.event_id: event for event in events}
    executions = [
        e for e in events if e.payload.kind == "EXECUTED" and e.payload.attempt.status == "FILLED"
    ]
    assert len(executions) == report.cycle.fills == 2
    for execution in executions:
        request = by_id[execution.cause_event_id]
        reminder = by_id[request.cause_event_id]
        evaluation = by_id[reminder.cause_event_id]
        assert [e.payload.kind for e in (evaluation, reminder, request)] == [
            "EVALUATED",
            "REMINDED",
            "REQUESTED",
        ]
        resulting = events[execution.sequence]
        assert resulting.payload.kind == "STATE" and resulting.cause_event_id == execution.event_id
        assert resulting.payload.account == execution.payload.attempt.receipt.account
        assert any(
            e.payload.kind == "EVALUATED" and e.cause_event_id == resulting.event_id for e in events
        )
    assert report.final_account.cash.balance_fen == 503590
    assert report.final_inventory.total_qty == 200
    assert report.metrics.paid_fees_fen == report.final_account.paid_fees_fen == 1210
    assert report.metrics.slippage_fen == 200
    assert report.boundary == cycle_input().boundary
    assert report.last_evidence_at == report.last_valuation_at == at(20, 9, 43, 12)


def test_cost_pnl_and_interval_return_do_not_label_opening_loss_as_period_loss(tmp_path):
    opening = account(
        cash=KnownLoopCash(balance_fen=500000),
        lots=(lot(),),
        opening_mark=LoopOpeningMark(
            price_fen=3970, price_at=at(20, 8, 59), available_at=at(), evidence="Known opening mark"
        ),
    )
    value = cycle_input(initial_account=opening, response=LoopResponsePolicy(mode="OBSERVE_ONLY"))
    report, _ = report_case(tmp_path, value)
    assert report.opening_valuation.equity_fen == 897000
    assert report.final_valuation.equity_fen == 902000
    assert report.metrics.equity_change_fen == 5000 and report.metrics.cost_pnl_fen == 950
    with localcontext() as context:
        context.prec = 28
        assert report.metrics.interval_return == Decimal(5000) / Decimal(897000)
    assert report.metrics.paid_fees_fen == report.metrics.slippage_fen == report.cycle.fills == 0
    assert report.final_inventory.total_qty == 100


def test_later_quote_does_not_backfill_unknown_opening_mark(tmp_path):
    report, _ = report_case(tmp_path)
    assert report.opening_valuation.equity_fen is None
    assert report.final_valuation.equity_fen is not None
    assert report.metrics.interval_return is report.metrics.equity_change_fen is None
    assert "OPENING_VALUATION_UNKNOWN" in report.metrics.blockers


def test_zero_opening_equity_keeps_null_return_without_losing_known_zero(tmp_path):
    value = cycle_input(
        initial_account=account(lots=()), response=LoopResponsePolicy(mode="OBSERVE_ONLY")
    )
    report, _ = report_case(tmp_path, value)
    assert report.metrics.initial_equity_fen == report.metrics.final_equity_fen == 0
    assert report.metrics.interval_return is None
    assert "ZERO_OPENING_EQUITY" in report.metrics.blockers


def test_stream_hash_order_and_report_identity_detect_tampering(tmp_path):
    report, events = report_case(tmp_path)
    assert MonitorLoopReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.model_copy(update={"event_set_hash": "f" * 64})
    for corrupt in (events[:-1], reversed(events), [events[0], *events]):
        with pytest.raises(ValueError):
            verify_loop_events(report, corrupt)


def test_repeated_offline_run_produces_identical_report_and_event_bytes(tmp_path):
    first, events = report_case(tmp_path / "first")
    second, other = report_case(tmp_path / "second")
    assert first == second and events == other


def test_cancelled_cycle_cannot_finish_partial_report(tmp_path):
    token = CancellationToken()
    token.cancel()
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        writer = LoopReportWriter(session, sink=lambda value: None)
        with pytest.raises(BacktestOperationCancelled):
            LoopRunner(session, report_writer=writer).run(frames(), cancellation_token=token)
        with pytest.raises(ValueError, match="COMPLETE"):
            writer.finish(None)
        with pytest.raises(ValueError, match="COMPLETE"):
            writer.finish(
                LoopCycleSummary(evaluations=0, intents=0, attempts=0, fills=0, unfilled_intents=0)
            )


def test_blocked_cash_retains_pending_intent_and_unliquidated_holdings(tmp_path):
    value = cycle_input(
        initial_account=account(), response=LoopResponsePolicy(mode="FOLLOW_REMINDERS")
    )
    report, events = report_case(tmp_path, value, frames(end=37))
    assert report.cycle.fills == 0 and report.cycle.unfilled_intents == 1
    attempts = [e.payload.attempt for e in events if e.payload.kind == "EXECUTED"]
    assert [value.reason for value in attempts] == ["LOOP_CASH_INSUFFICIENT"]
    assert report.final_inventory.total_qty == 100
    assert report.final_account.accounting_cost_fen == 401050
    assert not any(e.payload.kind == "STATE" for e in events)


def test_canonical_rehash_cannot_hide_a_changed_execution_cause(tmp_path):
    from trade_plan_monitor.backtest.loop_report import LoopAuditEvent, _event_hash

    report, events = report_case(tmp_path)
    index = next(i for i, event in enumerate(events) if event.payload.kind == "EXECUTED")
    original = events[index]
    attempt = original.payload.attempt.model_copy(update={"intent_id": "f" * 64})
    payload = original.payload.model_copy(update={"attempt": attempt})
    values = original.model_dump(mode="python", exclude={"event_id"}) | {"payload": payload}
    events[index] = LoopAuditEvent(event_id=_event_hash(values), **values)
    with pytest.raises(ValueError, match="EXECUTION_CAUSE"):
        verify_loop_events(report, events)


def test_stream_sink_failure_prevents_a_completed_report(tmp_path):
    count = 0

    def sink(value):
        nonlocal count
        count += 1
        if value.payload.kind == "STATE":
            raise OSError("synthetic post-fill audit write failure")

    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        writer = LoopReportWriter(session, sink=sink)
        with pytest.raises(OSError, match="audit write"):
            LoopRunner(session, report_writer=writer).run(frames())
        with pytest.raises(ValueError, match="COMPLETE"):
            writer.finish(
                LoopCycleSummary(evaluations=1, intents=1, attempts=1, fills=1, unfilled_intents=0)
            )
        assert count > 1


@pytest.mark.parametrize(
    "case,controls",
    [
        (
            "test_new_risk_blocks_pending_buy_and_keeps_its_exit_authority_after_expiry",
            {"after_expiry": False},
        ),
        (
            "test_new_risk_blocks_pending_buy_and_keeps_its_exit_authority_after_expiry",
            {"after_expiry": True},
        ),
        ("test_expired_plan_closes_delayed_ordinary_intent_without_reactivation", {}),
        ("test_repeated_signal_never_creates_a_zero_time_trade_loop", {}),
        ("test_nonautomatic_modes_capture_but_never_generate_trades", {"mode": "OBSERVE_ONLY"}),
        ("test_nonautomatic_modes_capture_but_never_generate_trades", {"mode": "RECORDED_ACTIONS"}),
    ],
)
def test_existing_risk_expiry_and_observation_cycles_keep_streamed_report_parity(
    tmp_path, monkeypatch, case, controls
):
    from tests.integration import test_monitor_loop_cycle

    initialize, run = LoopRunner.__init__, LoopRunner.run
    reports = []

    def reported(self, session, **options):
        events = []
        writer = LoopReportWriter(session, sink=events.append)
        initialize(self, session, report_writer=writer, **options)
        self.test_events = events

    def verified(self, frames, **options):
        summary = run(self, frames, **options)
        report = self.report_writer.finish(summary)
        verify_loop_events(report, self.test_events)
        reports.append(report)
        return summary

    monkeypatch.setattr(LoopRunner, "__init__", reported)
    monkeypatch.setattr(LoopRunner, "run", verified)
    getattr(test_monitor_loop_cycle, case)(tmp_path, **controls)
    assert len(reports) == 1
