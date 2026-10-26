"""Freeze actual reviewed local facts without importing their live execution authority."""

import pytest
from sqlalchemy import select
from tests.integration.test_market_exception_runtime import approve_current, exception_inputs
from tests.integration.test_p3_chain import p3_chain as p3_chain

from trade_plan_monitor.backtest.exception_replay_input import FrozenExceptionEvent
from trade_plan_monitor.backtest.p3_replay_input import (
    CapitalExceptionReplayProgram,
    CapitalReplayProgram,
    CapitalResearchInput,
    FrozenCapitalExceptionEvent,
    FrozenCapitalOpening,
)
from trade_plan_monitor.backtest.research_input import ResearchReview
from trade_plan_monitor.decision.market_exception_decision import parse_linkage_decision
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_models import CapitalBookEvent, CapitalEventRow


def frozen_opening(chain, *, available_at=None):
    with chain.plans._unit_of_work() as work:
        stored = work.daily.session.scalars(select(CapitalEventRow)).one()
        event = CapitalBookEvent.model_validate_json(stored.payload_json)
    return FrozenCapitalOpening.build(
        source_event_id=event.event_hash, plan_hash=plan_sha256(chain.plan),
        symbol=chain.plan.symbol, provenance="RECORDED_LOCAL", observed_at=chain.now,
        received_at=event.received_at, available_at=available_at or event.received_at,
        order=0, confirmed=True, source=event.details["source"],
        excerpt=event.details["excerpt"], reason=event.details["reason"], recorded_event=event,
        lots=tuple(dict(source_lot_id=lot.lot_id, bucket=lot.bucket, quantity=lot.quantity,
            retained_basis_fen=lot.retained_basis_fen,
            reference=dict(kind="OPENING", lot_key="frozen-opening-core"))
            for lot in event.book.lots))


def research_run_input(chain, *, openings=(), events=(), operations=()):
    from datetime import timedelta

    from tests.integration.test_backtest_runner import _execution_config
    from tests.integration.test_daily_plan_chain import TUESDAY

    from trade_plan_monitor.backtest.index_data import build_backtest_index_requirement
    from trade_plan_monitor.backtest.run_input import BacktestInitialLotInput, BacktestRunInput

    requirement = build_backtest_index_requirement(chain.plan)
    research = CapitalResearchInput(started_at=chain.now, inventory_known=True,
        review=ResearchReview(content_hash=daily_plan_content_sha256(chain.plan),
            reviewed_at=chain.now, confirmed=True, evidence="Explicit frozen capital research"),
        exception_authorization_events=events, operations=operations,
        capital_program=CapitalReplayProgram(opening_events=openings))
    return BacktestRunInput(run_formula_version="backtest-run-v10", plan_snapshot=chain.plan,
        plan_sha256=plan_sha256(chain.plan), dataset_hash="a"*64,
        start=chain.now.date(), end=TUESDAY, initial_cash_fen=1000000,
        initial_lots=(BacktestInitialLotInput(lot_key="frozen-opening-core", bucket="CORE",
            acquired_trade_date=chain.now.date()-timedelta(days=3), quantity=100,
            cost_basis_fen=99999),), execution_config=_execution_config(), manual_event_risk=False,
        indicator_formula_version="daily-ta-v2", research_input=research,
        reference_market_binding=chain.plan.reference_market, market_index_data_hash="b"*64,
        index_requirement_hash=requirement.index_requirement_hash,
        formula_definition_hash=requirement.formula_definition_hash)


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_v10_research_freezes_budget_separately_and_preserves_earlier_authority(p3_chain):
    from datetime import timedelta

    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    empty = research_run_input(p3_chain)
    opening = frozen_opening(p3_chain, available_at=p3_chain.now+timedelta(hours=1))
    supplied = research_run_input(p3_chain, openings=(opening,))
    assert supplied.initial_lots[0].cost_basis_fen != opening.lots[0].retained_basis_fen
    assert supplied.run_id != empty.run_id
    assert supplied.authority_id == empty.authority_id
    assert BacktestRunInput.model_validate_json(supplied.model_dump_json()) == supplied
    for change in ({"run_formula_version": "backtest-run-v9"}, {"research_input": None}):
        with pytest.raises(ValueError):
            BacktestRunInput.model_validate(supplied.model_dump(mode="python") | change)


@pytest.mark.parametrize("p3_chain", [("MARKET_VALUE_CAP", False, "WEAK_MINIMUM"),
    ("OPEN_COST_CAP", True, "BROKEN_STRONG")], indirect=True)
def test_actual_capital_exception_source_uses_new_envelope_and_old_reader_rejects_it(p3_chain):
    chain = p3_chain
    evaluation = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    pending = ExceptionCandidate.model_validate(
        evaluation.snapshot["exception_candidates"][0]["candidate"])
    decision = parse_linkage_decision(evaluation.snapshot["market_linkage"][0])
    receipt = approve_current(chain)
    frozen = FrozenCapitalExceptionEvent.build(plan_hash=plan_sha256(chain.plan),
        provenance="RECORDED_LOCAL", order=1, candidate=pending, decision=decision,
        event=receipt.event)
    assert FrozenCapitalExceptionEvent.model_validate_json(frozen.model_dump_json()) == frozen
    with pytest.raises(ValueError):
        FrozenExceptionEvent.model_validate_json(frozen.model_dump_json())
    program = CapitalExceptionReplayProgram(exception_authorization_events=(frozen,))
    program.validate_scope(plans=(chain.plan,), started_at=chain.now)
    research = CapitalResearchInput(started_at=chain.now, inventory_known=True,
        review=ResearchReview(content_hash=daily_plan_content_sha256(chain.plan),
            reviewed_at=chain.now, confirmed=True, evidence="Explicit frozen capital research"),
        exception_authorization_events=(frozen,), capital_program=CapitalReplayProgram())
    assert CapitalResearchInput.model_validate_json(research.model_dump_json()) == research


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_recorded_opening_is_exact_and_can_be_read_without_current_database(p3_chain, monkeypatch):
    chain = p3_chain
    with chain.plans._unit_of_work() as work:
        stored = work.daily.session.scalars(select(CapitalEventRow)).one()
        event = CapitalBookEvent.model_validate_json(stored.payload_json)
    values = dict(source_event_id=event.event_hash, plan_hash=plan_sha256(chain.plan),
        symbol=chain.plan.symbol, provenance="RECORDED_LOCAL", observed_at=chain.now,
        received_at=event.received_at, available_at=event.received_at, order=0, confirmed=True,
        source=event.details["source"], excerpt=event.details["excerpt"],
        reason=event.details["reason"], recorded_event=event,
        lots=tuple(dict(source_lot_id=lot.lot_id, bucket=lot.bucket, quantity=lot.quantity,
            retained_basis_fen=lot.retained_basis_fen,
            reference=dict(kind="OPENING", lot_key="frozen-opening-core"))
            for lot in event.book.lots))
    frozen = FrozenCapitalOpening.build(**values)
    def unavailable(*args, **kwargs):
        raise AssertionError("Frozen validation must not read the current budget")
    monkeypatch.setattr(CapitalRepository, "get", unavailable)
    program = CapitalReplayProgram(opening_events=(frozen,))
    program.validate_scope((chain.plan,))
    assert CapitalReplayProgram.model_validate_json(program.model_dump_json()) == program
    raw = frozen.model_dump(mode="python", exclude={"envelope_hash"})
    raw["lots"][0]["retained_basis_fen"] += 1
    with pytest.raises(ValueError, match="lot costs"):
        FrozenCapitalOpening.build(**raw)


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY"),
    ("OPEN_COST_CAP", True, "BROKEN_STRONG")], indirect=True)
def test_private_research_budget_uses_exact_source_and_whole_current_execution(p3_chain, tmp_path):
    from datetime import datetime, time, timedelta

    from tests.integration.test_daily_plan_chain import SH, TUESDAY

    from trade_plan_monitor.backtest.exception_replay import apply_frozen_exception
    from trade_plan_monitor.backtest.p3_replay import apply_frozen_capital
    from trade_plan_monitor.backtest.research_input import ResearchSimulation
    from trade_plan_monitor.backtest.research_session import ResearchSession
    from trade_plan_monitor.market_data.models import TradingDay

    chain = p3_chain
    opening = frozen_opening(chain)
    inputs = exception_inputs(chain)
    event = None
    if chain.p3_route != "ORDINARY":
        evaluation = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        candidate = ExceptionCandidate.model_validate(
            evaluation.snapshot["exception_candidates"][0]["candidate"])
        event = FrozenCapitalExceptionEvent.build(plan_hash=plan_sha256(chain.plan),
            provenance="RECORDED_LOCAL", order=1, candidate=candidate,
            decision=parse_linkage_decision(evaluation.snapshot["market_linkage"][0]),
            event=approve_current(chain).event)
    calendar = tuple(TradingDay(exchange="SSE", cal_date=d, is_open=True,
        previous_trade_date=inputs.session_dates[i-1] if i else d-timedelta(days=1))
        for i, d in enumerate(inputs.session_dates))
    run = research_run_input(chain, openings=(opening,), events=() if event is None else (event,))
    (tmp_path / "private").mkdir()
    session = ResearchSession(tmp_path / "private", run, calendar)
    try:
        with session.work() as work:
            assert CapitalRepository(work.daily.session).get(chain.plan.symbol) is None
        applied = apply_frozen_capital(session, opening)
        assert applied.status == "APPLIED", applied
        before = session.inventory()
        session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        if event is not None:
            assert apply_frozen_exception(session, event).status == "APPLIED"
            assert session.inventory() == before
        chain.now = session.now = datetime.combine(TUESDAY, time(9, 35), SH)
        ready = session.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        signal = ready.snapshot["signals"][0]
        quantity = 200 if event is None else 300
        assert signal["executable_qty"] == quantity
        outcome = session.apply_operation(ResearchSimulation(kind="SIMULATE",
            operation_id="separate-p3-fill", at=chain.now, order=2,
            rule_id=signal["rule_id"], occurrence=1, quantity=quantity), ended=False)
        assert outcome.status == "APPLIED", outcome
        with session.work() as work:
            book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
            assert book.retained_basis_fen == 20000+quantity*161+500
            assert book.inventory_revision == outcome.inventory_after.revision
            assert book.retained_basis_fen != run.initial_lots[0].cost_basis_fen+quantity*161+500
    finally:
        session.close()


def capital_loop_input(chain, *, openings=(), events=(), operations=(), mode="FOLLOW_REMINDERS"):
    from datetime import datetime, time

    from tests.integration.test_daily_plan_chain import SH, TUESDAY
    from tests.unit.test_monitor_loop_input import costs
    from tests.unit.test_monitor_loop_schedule import version

    from trade_plan_monitor.backtest.loop_input import (
        LoopAccountInput,
        LoopInitialLot,
        LoopResponsePolicy,
        MonitorLoopInput,
        PositionLimitFunding,
    )
    from trade_plan_monitor.backtest.plan_schedule import (
        LoopEndBoundary,
        LoopSchedule,
        LoopScheduleEntry,
    )
    return MonitorLoopInput(
        run_formula_version="backtest-run-v10",
        schedule=LoopSchedule(entries=(LoopScheduleEntry(effective_trade_date=chain.now.date(),
            version=version(plan=chain.plan, available=chain.now)),)),
        boundary=LoopEndBoundary.resolve(started_at=chain.now,
            submitted_at=datetime.combine(TUESDAY, time(10, 0, 12), SH)),
        dataset_hash="a"*64, costs=costs(), response=LoopResponsePolicy(mode=mode),
        initial_account=LoopAccountInput(snapshot_at=chain.now, inventory_known=True,
            cash=PositionLimitFunding(), opening_mark=None,
            lots=(LoopInitialLot(lot_key="frozen-opening-core", bucket="CORE", quantity=100,
                cost_basis_fen=None, acquired_trade_date=None, sellable_quantity=100,
                evidence="Explicit independently confirmed opening quantity"),),
            evidence="No spendable cash constraint; budget costs explicitly supplied separately"),
        exception_program=CapitalExceptionReplayProgram(
            exception_authorization_events=events, operations=operations),
        capital_program=CapitalReplayProgram(opening_events=openings))


def frozen_approval(chain):
    inputs = exception_inputs(chain)
    evaluation = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    candidate = ExceptionCandidate.model_validate(
        evaluation.snapshot["exception_candidates"][0]["candidate"])
    return FrozenCapitalExceptionEvent.build(plan_hash=plan_sha256(chain.plan),
        provenance="RECORDED_LOCAL", order=1, candidate=candidate,
        decision=parse_linkage_decision(evaluation.snapshot["market_linkage"][0]),
        event=approve_current(chain).event)


def calendar_for(chain):
    from datetime import timedelta

    from trade_plan_monitor.market_data.models import TradingDay
    days = exception_inputs(chain).session_dates
    return tuple(TradingDay(exchange="SSE", cal_date=d, is_open=True,
        previous_trade_date=days[i-1] if i else d-timedelta(days=1))
        for i, d in enumerate(days))


def loop_frames(chain, calendar):
    from datetime import datetime, time
    from decimal import Decimal

    from tests.integration.test_daily_plan_chain import SH, TUESDAY

    from trade_plan_monitor.backtest.loop_runner import LoopFrame
    from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar

    frames = [LoopFrame(runtime=exception_inputs(chain).model_copy(
        update={"trading_calendar": calendar}))]
    for minute in (35, 36, 37):
        chain.now = datetime.combine(TUESDAY, time(9, minute), SH)
        bar = MinuteBar(symbol=chain.plan.symbol, bar_end=chain.now, received_at=chain.now,
            open_fen=161, close_fen=161, high_fen=162, low_fen=160, volume_shares=1000,
            amount_yuan=Decimal(1610))
        frames.append(LoopFrame(runtime=exception_inputs(chain).model_copy(
            update={"trading_calendar": calendar}), minute=bar,
            daily_limit=DailyLimit(symbol=chain.plan.symbol, trade_date=TUESDAY,
                up_limit_fen=200, down_limit_fen=100, received_at=chain.now.replace(hour=8))))
    return frames


def test_loop_preserves_capital_policy_separate_approval_and_report_integrity(p3_chain, tmp_path):
    from datetime import datetime, time
    from types import SimpleNamespace

    from tests.integration.test_daily_plan_chain import SH, TUESDAY

    from trade_plan_monitor.backtest.loop_publication import validate_report_input
    from trade_plan_monitor.backtest.loop_report import LoopReportWriter, verify_loop_events
    from trade_plan_monitor.backtest.loop_runner import LoopRunner
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.research_input import ResearchSimulation

    chain = p3_chain
    opening = frozen_opening(chain) if chain.capital_mode == "OPEN_COST_CAP" else None
    event = frozen_approval(chain) if chain.p3_route != "ORDINARY" else None
    quantity = 200 if event is None else 100 if chain.route == "WEAK_MINIMUM" else 300
    operation = ResearchSimulation(kind="SIMULATE", operation_id="p3-explicit-request", order=2,
        at=datetime.combine(TUESDAY, time(9, 35), SH),
        rule_id=chain.plan.ordinary_rules[0].rule_id, occurrence=1, quantity=quantity)
    run = capital_loop_input(chain, openings=() if opening is None else (opening,),
        events=() if event is None else (event,), operations=() if event is None else (operation,))
    calendar = calendar_for(chain)
    frames = loop_frames(chain, calendar)
    audit = []
    with LoopSession(tmp_path / "loop-private", run, calendar) as session:
        writer = LoopReportWriter(session, sink=audit.append)
        runner = LoopRunner(session, report_writer=writer)
        cycle = runner.run(frames)
        report = writer.finish(cycle)
        assert cycle.fills == 1, [e for e in audit if e.payload.kind == "EXECUTED"]
        assert report.final_inventory.total_qty == 100+quantity
        assert session.account().cash.kind == "POSITION_LIMIT_ONLY"
        if opening is not None:
            assert report.capital_outcomes[0].status == "APPLIED"
            with session.work() as work:
                book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
                assert book.retained_basis_fen == 20000+quantity*161+500
        verify_loop_events(report, audit)
        validate_report_input(SimpleNamespace(run_input=run), report)
