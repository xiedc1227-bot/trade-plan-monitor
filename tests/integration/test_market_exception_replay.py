"""Frozen exception authority is explicit, bounded and causally replayable."""

import json

import pytest
from tests.integration.test_market_exception_runtime import (
    approve_current,
    exception_inputs,
)
from tests.integration.test_market_exception_runtime import (
    exception_chain as exception_chain,
)

from trade_plan_monitor.backtest.exception_replay_input import (
    ExceptionReplayProgram,
    ExceptionResearchInput,
    FrozenExceptionEvent,
)
from trade_plan_monitor.decision.market_exception_decision import MarketExceptionDecision
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate


def research_run_input(chain, *, events=(), operations=()):
    from tests.integration.test_backtest_runner import _execution_config
    from tests.integration.test_daily_plan_chain import TUESDAY

    from trade_plan_monitor.backtest.index_data import build_backtest_index_requirement
    from trade_plan_monitor.backtest.research_input import ResearchReview
    from trade_plan_monitor.backtest.run_input import BacktestRunInput
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    requirement = build_backtest_index_requirement(chain.plan)
    research = ExceptionResearchInput(
        started_at=chain.now,
        inventory_known=True,
        review=ResearchReview(
            content_hash=daily_plan_content_sha256(chain.plan),
            reviewed_at=chain.now,
            confirmed=True,
            evidence="Explicit synthetic research review",
        ),
        operations=operations,
        exception_authorization_events=events,
    )
    return BacktestRunInput(
        run_formula_version="backtest-run-v8",
        plan_snapshot=chain.plan,
        plan_sha256=plan_sha256(chain.plan),
        dataset_hash="a" * 64,
        start=chain.now.date(),
        end=TUESDAY,
        initial_cash_fen=1000000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        indicator_formula_version="daily-ta-v2",
        research_input=research,
        reference_market_binding=chain.plan.reference_market,
        market_index_data_hash="b" * 64,
        index_requirement_hash=requirement.index_requirement_hash,
        formula_definition_hash=requirement.formula_definition_hash,
    )


def test_exception_run_requires_v8_and_hashes_events_without_changing_past_identity(
    exception_chain,
):
    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    chain = exception_chain
    empty = research_run_input(chain)
    event = frozen_approval(chain)
    supplied = research_run_input(chain, events=(event,))
    assert empty.run_id != supplied.run_id
    assert empty.authority_id == supplied.authority_id
    assert BacktestRunInput.model_validate_json(supplied.model_dump_json()) == supplied
    with pytest.raises(ValueError):
        BacktestRunInput.model_validate(
            {**supplied.model_dump(mode="python"), "run_formula_version": "backtest-run-v7"}
        )


def frozen_approval(chain, *, provenance="RESEARCH_SCENARIO"):
    evaluation = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    pending = ExceptionCandidate.model_validate(
        evaluation.snapshot["exception_candidates"][0]["candidate"]
    )
    proof = MarketExceptionDecision.model_validate(evaluation.snapshot["market_linkage"][0])
    receipt = approve_current(chain)
    return FrozenExceptionEvent.build(
        plan_hash=plan_sha256(chain.plan),
        candidate=pending,
        decision=proof,
        event=receipt.event,
        provenance=provenance,
        order=0,
    )


def test_frozen_envelope_preserves_original_authority_and_rejects_corruption(exception_chain):
    value = frozen_approval(exception_chain)
    assert FrozenExceptionEvent.model_validate_json(value.model_dump_json()) == value
    for key, change in (
        ("plan_hash", "0" * 64),
        ("provenance", "RECORDED_LOCAL"),
        ("schema_version", "frozen-exception-event-v99"),
    ):
        raw = value.model_dump(mode="json")
        raw[key] = change
        with pytest.raises(ValueError):
            FrozenExceptionEvent.model_validate_json(json.dumps(raw))
    bad = value.model_dump(mode="python", exclude={"envelope_hash"})
    bad["event"] = type(value.event).model_construct(
        **{**value.event.model_dump(mode="python"), "quantity": 999}
    )
    with pytest.raises(ValueError):
        FrozenExceptionEvent.build(**bad)


def test_frozen_stream_has_no_implicit_approval_or_duplicate_event(exception_chain):
    empty = ExceptionReplayProgram()
    assert empty.exception_authorization_events == () and empty.operations == ()
    value = frozen_approval(exception_chain)
    program = ExceptionReplayProgram(exception_authorization_events=(value,))
    assert program.provenances == ("RESEARCH_SCENARIO",)
    with pytest.raises(ValueError, match="unique"):
        ExceptionReplayProgram(exception_authorization_events=(value, value))
    with pytest.raises(ValueError, match="plan"):
        program.validate_scope(plans=(), started_at=exception_chain.now)


def test_loop_requires_explicit_exception_program_and_preserves_old_encoding(exception_chain):
    from tests.unit.test_monitor_loop_input import frozen

    from trade_plan_monitor.backtest.loop_input import decode_monitor_loop_input_json
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    old = frozen()
    assert "exception_program" not in old.model_dump()
    raw = old.model_dump(mode="json")
    version = raw["schedule"]["entries"][0]["version"]
    version["snapshot"] = exception_chain.plan.model_dump(mode="json")
    version["plan_hash"] = plan_sha256(exception_chain.plan)
    version["review"]["content_hash"] = daily_plan_content_sha256(exception_chain.plan)
    with pytest.raises(ValueError):
        decode_monitor_loop_input_json(json.dumps(raw))
    raw.update(
        run_formula_version="backtest-run-v8",
        exception_program=ExceptionReplayProgram().model_dump(mode="json"),
    )
    current = decode_monitor_loop_input_json(json.dumps(raw))
    assert current.schedule.entries[0].version.snapshot.schema_version == 7
    assert current.exception_program.exception_authorization_events == ()


def test_private_replay_uses_shared_approval_and_requires_separate_execution(
    exception_chain, tmp_path
):
    from datetime import datetime, time, timedelta

    from tests.integration.test_daily_plan_chain import SH, TUESDAY

    from trade_plan_monitor.backtest.exception_replay import apply_frozen_exception
    from trade_plan_monitor.backtest.research_input import ResearchSimulation
    from trade_plan_monitor.backtest.research_session import ResearchSession
    from trade_plan_monitor.market_data.models import TradingDay

    chain = exception_chain
    event = frozen_approval(chain)
    inputs = exception_inputs(chain)
    calendar = tuple(
        TradingDay(
            exchange="SSE",
            cal_date=day,
            is_open=True,
            previous_trade_date=inputs.session_dates[i - 1] if i else day - timedelta(days=1),
        )
        for i, day in enumerate(inputs.session_dates)
    )
    session = ResearchSession(tmp_path, research_run_input(chain, events=(event,)), calendar)
    try:
        session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        before = session.inventory()
        applied = apply_frozen_exception(session, event)
        assert applied.status == "APPLIED", applied
        assert session.inventory() == before
        assert applied.provenance == "RESEARCH_SCENARIO"
        chain.now = session.now = datetime.combine(TUESDAY, time(9, 35), SH)
        ready = session.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        quantity = 100 if chain.route == "WEAK_MINIMUM" else 300
        assert ready.snapshot["signals"][0]["executable_qty"] == quantity
        outcome = session.apply_operation(
            ResearchSimulation(
                kind="SIMULATE",
                operation_id="separate-whole-fill",
                at=chain.now,
                order=1,
                rule_id=event.candidate.binding.rule_id,
                occurrence=1,
                quantity=quantity,
            ),
            ended=False,
        )
        assert outcome.status == "APPLIED", outcome
        assert session.inventory()["total_qty"] == quantity
    finally:
        session.close()


def exception_loop_input(chain, *, events=(), operations=(), mode="FOLLOW_REMINDERS"):
    from datetime import datetime, time

    from tests.integration.test_daily_plan_chain import SH, TUESDAY
    from tests.unit.test_monitor_loop_input import account, costs
    from tests.unit.test_monitor_loop_schedule import version

    from trade_plan_monitor.backtest.loop_input import (
        KnownLoopCash,
        LoopResponsePolicy,
        MonitorLoopInput,
    )
    from trade_plan_monitor.backtest.plan_schedule import (
        LoopEndBoundary,
        LoopSchedule,
        LoopScheduleEntry,
    )

    start = events[0].candidate.created_at if events else chain.now
    return MonitorLoopInput(
        run_formula_version="backtest-run-v8",
        exception_program=ExceptionReplayProgram(
            exception_authorization_events=events, operations=operations
        ),
        schedule=LoopSchedule(
            entries=(
                LoopScheduleEntry(
                    effective_trade_date=start.date(),
                    version=version(plan=chain.plan, available=start),
                ),
            )
        ),
        boundary=LoopEndBoundary.resolve(
            started_at=start, submitted_at=datetime.combine(TUESDAY, time(10, 0, 12), SH)
        ),
        initial_account=account(
            snapshot_at=start, lots=(), cash=KnownLoopCash(balance_fen=1000000)
        ),
        dataset_hash="a" * 64,
        response=LoopResponsePolicy(mode=mode),
        costs=costs(),
    )


@pytest.mark.parametrize("script", [False, True])
def test_loop_approval_never_implies_response_and_script_uses_next_complete_minute(
    exception_chain, tmp_path, script
):
    from datetime import datetime, time, timedelta
    from decimal import Decimal

    from tests.integration.test_daily_plan_chain import SH, TUESDAY

    from trade_plan_monitor.backtest.loop_report import LoopReportWriter, verify_loop_events
    from trade_plan_monitor.backtest.loop_runner import LoopFrame, LoopRunner
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.research_input import ResearchSimulation
    from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar, TradingDay

    chain = exception_chain
    event = frozen_approval(chain)
    days = exception_inputs(chain).session_dates
    calendar = tuple(
        TradingDay(
            exchange="SSE",
            cal_date=d,
            is_open=True,
            previous_trade_date=days[i - 1] if i else d - timedelta(days=1),
        )
        for i, d in enumerate(days)
    )
    quantity = 100 if chain.route == "WEAK_MINIMUM" else 300
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="explicit-request",
        order=1,
        at=datetime.combine(TUESDAY, time(9, 35), SH),
        rule_id=event.candidate.binding.rule_id,
        occurrence=1,
        quantity=quantity,
    )
    run = exception_loop_input(chain, events=(event,), operations=(operation,) if script else ())
    frames = [
        LoopFrame(runtime=exception_inputs(chain).model_copy(update={"trading_calendar": calendar}))
    ]
    for minute in (35, 36, 37):
        chain.now = datetime.combine(TUESDAY, time(9, minute), SH)
        bar = MinuteBar(
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
        frames.append(
            LoopFrame(
                runtime=exception_inputs(chain).model_copy(update={"trading_calendar": calendar}),
                minute=bar,
                daily_limit=DailyLimit(
                    symbol=chain.plan.symbol,
                    trade_date=TUESDAY,
                    up_limit_fen=200,
                    down_limit_fen=100,
                    received_at=chain.now.replace(hour=8),
                ),
            )
        )
    audit = []
    with LoopSession(tmp_path, run, calendar) as session:
        writer = LoopReportWriter(session, sink=audit.append)
        runner = LoopRunner(session, report_writer=writer)
        cycle = runner.run(frames)
        report = writer.finish(cycle)
        assert runner.exceptions.outcomes[0].status == "APPLIED", runner.exceptions.outcomes
        assert cycle.fills == int(script)
        assert report.final_inventory.total_qty == (quantity if script else 0)
        assert report.exception_provenance == ("RESEARCH_SCENARIO",)
        verify_loop_events(report, audit)
        from hashlib import sha256
        from types import SimpleNamespace

        from trade_plan_monitor.backtest.canonical import canonical_json
        from trade_plan_monitor.backtest.loop_publication import validate_report_input

        validate_report_input(SimpleNamespace(run_input=run), report)
        tampered = report.model_dump(mode="python", exclude={"report_hash"})
        tampered["exception_provenance"] = ("RECORDED_LOCAL",)
        forged = type(report)(**tampered, report_hash=sha256(
            (report.schema_version + "\0" + canonical_json(tampered)).encode()).hexdigest())
        with pytest.raises(ValueError, match="exception"):
            validate_report_input(SimpleNamespace(run_input=run), forged)
        if script:
            from trade_plan_monitor.backtest.loop_publication import validate_exception_operation
            from trade_plan_monitor.backtest.loop_report import _event_hash

            request = next(e for e in audit if e.payload.kind == "REQUESTED")
            validate_exception_operation(run, request)
            raw = request.model_dump(mode="python", exclude={"event_id"})
            raw["payload"]["source_operation"]["quantity"] = quantity + 100
            changed = type(request)(**raw, event_id=_event_hash(raw))
            with pytest.raises(ValueError, match="frozen input"):
                validate_exception_operation(run, changed)
            executions = [e.payload.attempt for e in audit if e.payload.kind == "EXECUTED"]
            assert executions[0].at == datetime.combine(TUESDAY, time(9, 36), SH)
