"""Independent negative and future-event oracles for both private execution paths."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_replay import (
    exception_loop_input,
    frozen_approval,
    research_run_input,
)
from tests.integration.test_market_exception_runtime import exception_chain as exception_chain
from tests.integration.test_market_exception_runtime import exception_inputs

from trade_plan_monitor.backtest.exception_replay import apply_frozen_exception
from trade_plan_monitor.backtest.exception_replay_input import (
    ExceptionReplayProgram,
    FrozenExceptionEvent,
)
from trade_plan_monitor.backtest.loop_report import LoopReportWriter, verify_loop_events
from trade_plan_monitor.backtest.loop_runner import LoopFrame, LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.research_input import ResearchSimulation
from trade_plan_monitor.backtest.research_session import ResearchSession
from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.state.market_exception_models import new_candidate, transition_candidate


def changed_event(source, *, state, at, candidate=None, quantity=None):
    candidate = candidate or source.candidate
    _, event = transition_candidate(
        candidate,
        to_state=state,
        expected_revision=1 if candidate.state == "PENDING" else 2,
        now=at,
        reason="Explicit frozen mutation scenario",
        command_id="mutation-" + state,
        quantity=quantity,
        preview_hash=source.event.preview_hash if state == "APPROVED" else None,
    )
    return FrozenExceptionEvent.build(
        **source.model_dump(exclude={"envelope_hash", "event", "candidate"}),
        candidate=candidate,
        event=event,
    )


def calendar_for(chain):
    days = exception_inputs(chain).session_dates
    return tuple(
        TradingDay(
            exchange="SSE",
            cal_date=day,
            is_open=True,
            previous_trade_date=days[i - 1] if i else day - timedelta(days=1),
        )
        for i, day in enumerate(days)
    )


def frame(chain, calendar, *, correction=False):
    inputs = exception_inputs(chain, correction=correction).model_copy(
        update={"trading_calendar": calendar}
    )
    if chain.now.date() != TUESDAY:
        return LoopFrame(runtime=inputs)
    minute = MinuteBar(
        symbol=chain.plan.symbol,
        bar_end=chain.now,
        received_at=chain.now,
        open_fen=161,
        close_fen=161,
        high_fen=162,
        low_fen=160,
        volume_shares=1000,
        amount_yuan=Decimal(1610),
    )
    limit = DailyLimit(
        symbol=chain.plan.symbol,
        trade_date=TUESDAY,
        up_limit_fen=200,
        down_limit_fen=100,
        received_at=chain.now.replace(hour=8, minute=0),
    )
    return LoopFrame(runtime=inputs, minute=minute, daily_limit=limit)


@pytest.mark.parametrize("entry", ["RESEARCH", "LOOP"])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "approval_only",
        "late",
        "rejected",
        "revoked",
        "correction",
        "quantity",
        "future_revoke",
    ],
)
def test_explicit_script_and_original_authority_gates_on_both_paths(
    exception_chain, tmp_path, entry, mutation
):
    chain = exception_chain
    source = frozen_approval(chain)
    original_now = chain.now
    calendar = calendar_for(chain)
    q = source.event.quantity

    def at(minute):
        return datetime.combine(TUESDAY, time(9, minute), SH)

    events = (source,)
    if mutation == "missing":
        events = ()
    elif mutation == "late":
        events = (changed_event(source, state="APPROVED", at=at(40), quantity=q),)
    elif mutation == "rejected":
        events = (changed_event(source, state="REJECTED", at=original_now),)
    elif mutation in {"revoked", "future_revoke"}:
        approved, _ = transition_candidate(
            source.candidate,
            to_state="APPROVED",
            expected_revision=1,
            now=source.event.received_at,
            reason=source.event.reason,
            command_id=source.event.command_id,
            quantity=q,
            preview_hash=source.event.preview_hash,
            request_hash=source.event.request_hash,
        )
        events = (
            source,
            changed_event(
                source,
                state="REVOKED",
                at=at(34) if mutation == "revoked" else at(40),
                candidate=approved,
            ),
        )
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="script",
        at=at(35),
        order=1,
        rule_id=source.candidate.binding.rule_id,
        occurrence=1,
        quantity=q + 100 if mutation == "quantity" else q,
    )
    operations = () if mutation == "approval_only" else (operation,)
    ExceptionReplayProgram(exception_authorization_events=events, operations=operations)
    ticks = sorted(
        {
            original_now,
            at(34),
            at(35),
            at(36),
            at(37),
            at(40),
            *(e.event.received_at for e in events),
        }
    )
    expected = q if mutation == "future_revoke" else 0
    if entry == "RESEARCH":
        session = ResearchSession(
            tmp_path, research_run_input(chain, events=events, operations=operations), calendar
        )
        try:
            outcomes = []
            for tick in ticks:
                chain.now = session.now = tick
                inputs = frame(
                    chain, calendar, correction=mutation == "correction" and tick >= at(34)
                ).runtime
                session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
                for event in events:
                    if event.event.received_at == tick:
                        outcomes.append(apply_frozen_exception(session, event))
                        session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
                for op in operations:
                    if op.at == tick:
                        session.apply_operation(op, ended=False)
            assert session.inventory()["total_qty"] == expected
            if mutation == "future_revoke":
                assert outcomes[-1].blockers == ("EXCEPTION_REPLAY_STATE_MISMATCH",)
        finally:
            session.close()
    else:
        run = exception_loop_input(chain, events=events, operations=operations)
        frames = []
        for tick in ticks:
            chain.now = tick
            frames.append(
                frame(chain, calendar, correction=mutation == "correction" and tick >= at(34))
            )
        audit = []
        with LoopSession(tmp_path, run, calendar) as session:
            writer = LoopReportWriter(session, sink=audit.append)
            runner = LoopRunner(session, report_writer=writer)
            report = writer.finish(runner.run(frames))
            assert report.final_inventory.total_qty == expected, report.exception_requests
            verify_loop_events(report, audit)
            if mutation == "future_revoke":
                assert report.exception_outcomes[-1].blockers == (
                    "EXCEPTION_REPLAY_STATE_MISMATCH",
                )


def test_frozen_input_rejects_foreign_plan_window_and_ambiguous_order(exception_chain):
    chain = exception_chain
    source = frozen_approval(chain)
    with pytest.raises(ValueError, match="window"):
        changed_event(
            source,
            state="APPROVED",
            at=source.candidate.binding.expires_at,
            quantity=source.event.quantity,
        )
    program = ExceptionReplayProgram(exception_authorization_events=(source,))
    changed = chain.plan.model_copy(update={"name": "different reviewed content"})
    with pytest.raises(ValueError, match="identity"):
        program.validate_scope(plans=(changed,), started_at=chain.now)
    with pytest.raises(ValueError, match="distinct same-time"):
        ExceptionReplayProgram(
            exception_authorization_events=(source,),
            operations=(
                ResearchSimulation(
                    kind="SIMULATE",
                    operation_id="ambiguous",
                    at=source.event.received_at,
                    order=source.order,
                    rule_id=source.candidate.binding.rule_id,
                    occurrence=1,
                    quantity=source.event.quantity,
                ),
            ),
        )


def test_schema7_preserves_explicit_risk_operations(exception_chain):
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="explicit-risk",
        at=exception_chain.now,
        order=1,
        risk_kind="SEVERE_TECHNICAL",
        quantity=100,
    )
    assert research_run_input(
        exception_chain, operations=(operation,)
    ).research_input.operations == (operation,)


@pytest.mark.parametrize("field", ["minimum", "increment"])
def test_resealed_frozen_binding_rejects_grid_field_mismatch(exception_chain, field):
    source = frozen_approval(exception_chain)
    original = source.candidate
    binding = original.binding.model_copy(
        update={field: getattr(original.binding, field) + 100}
    )
    candidate = new_candidate(binding, original.created_at, signal_seed=original.signal_seed)
    with pytest.raises(ValueError, match="source binding mismatch"):
        changed_event(
            source, state="REJECTED", at=source.event.received_at, candidate=candidate
        )


def test_future_approval_cannot_change_earlier_loop_decisions(exception_chain, tmp_path):
    chain = exception_chain
    source = frozen_approval(chain)
    start = chain.now
    late = datetime.combine(TUESDAY, time(9, 40), SH)
    future = changed_event(source, state="APPROVED", at=late, quantity=source.event.quantity)
    calendar = calendar_for(chain)
    prefixes = []
    for index, events in enumerate(((), (future,))):
        chain.now = start
        run = exception_loop_input(chain, events=events)
        directory = tmp_path / f"causal-{index}"
        directory.mkdir()
        frames = []
        for tick in (start, late - timedelta(minutes=5), late):
            chain.now = tick
            frames.append(frame(chain, calendar))
        audit = []
        with LoopSession(directory, run, calendar) as session:
            writer = LoopReportWriter(session, sink=audit.append)
            runner = LoopRunner(session, report_writer=writer)
            report = writer.finish(runner.run(frames))
            assert report.cycle.fills == 0
            if events:
                assert report.exception_outcomes[0].status == "APPLIED"
        prefixes.append([(e.at, e.payload) for e in audit if e.at < late])
    assert prefixes[0] == prefixes[1]
