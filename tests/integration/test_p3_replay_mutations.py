"""Future budget/quote/policy inputs cannot change the already available prefix."""

from datetime import datetime, time, timedelta

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_p3_chain import p3_chain as p3_chain
from tests.integration.test_p3_replay import (
    calendar_for,
    capital_loop_input,
    frozen_opening,
    loop_frames,
)

from trade_plan_monitor.backtest.loop_report import LoopReportWriter, verify_loop_events
from trade_plan_monitor.backtest.loop_runner import LoopFrame, LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.p3_replay import apply_frozen_capital
from trade_plan_monitor.backtest.p3_replay_input import FrozenCapitalOpening


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
@pytest.mark.parametrize("mutation", ["missing", "late", "wrong_lot", "wrong_quantity"])
def test_unknown_cost_and_exact_lots_never_infer_past_authority(p3_chain, tmp_path, mutation):
    chain = p3_chain
    opening = frozen_opening(chain)
    calendar = calendar_for(chain)
    run = capital_loop_input(chain, mode="OBSERVE_ONLY")
    with LoopSession(tmp_path / mutation, run, calendar) as session:
        if mutation != "missing":
            raw = opening.model_dump(mode="python", exclude={"envelope_hash", "recorded_event"})
            raw.update(provenance="RESEARCH_SCENARIO", recorded_event=None)
            if mutation == "late":
                raw["available_at"] += timedelta(minutes=1)
            elif mutation == "wrong_lot":
                raw["lots"][0]["reference"]["lot_key"] = "another-lot"
            else:
                raw["lots"][0]["quantity"] += 100
            result = apply_frozen_capital(session, FrozenCapitalOpening.build(**raw))
            assert result.status == "BLOCKED"
        from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
        with session.work() as work:
            assert CapitalRepository(work.daily.session).get(chain.plan.symbol) is None
        assert session.inventory()["total_qty"] == 100


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
@pytest.mark.parametrize("mutation", ["book", "quote", "policy"])
def test_future_changes_preserve_earlier_loop_decisions(p3_chain, tmp_path, mutation):
    chain = p3_chain
    start = chain.now
    late = datetime.combine(TUESDAY, time(9, 30 if mutation == "policy" else 37), SH)
    opening = frozen_opening(chain, available_at=late)
    calendar = calendar_for(chain)
    prefixes = []
    for index in range(2):
        chain.now = start
        run = capital_loop_input(chain, mode="OBSERVE_ONLY",
            openings=(opening,) if index and mutation == "book" else ())
        frames = loop_frames(chain, calendar)
        if index and mutation == "quote":
            last = frames[-1]
            quote = last.runtime.quote.model_copy(update={"price_fen": 162})
            frames[-1] = LoopFrame(runtime=last.runtime.model_copy(update={"quote": quote}))
        if index and mutation == "policy":
            from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput
            from trade_plan_monitor.backtest.plan_schedule import (
                ScheduledLoopSchedule,
                ScheduledPlanVersion,
                ScheduledScheduleEntry,
            )
            version = run.schedule.entries[0].version
            raw = chain.plan.model_dump(mode="json")
            raw["position"]["limit"]["capital_policy"]["cap_fen"] += 1
            future_plan = type(chain.plan).model_validate(raw)
            from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
            def scheduled(plan, at, identity, version=version):
                return ScheduledPlanVersion.model_validate(version.model_dump(mode="python") | dict(
                    version_id=identity, snapshot=plan, plan_hash=plan_sha256(plan),
                    available_at=at, information_cutoff=at,
                    review=version.review.model_copy(update=dict(reviewed_at=at,
                        content_hash=daily_plan_content_sha256(plan)))))
            old = ScheduledPlanVersion.model_validate(version.model_dump(mode="python"))
            new = scheduled(future_plan, late, "future-capital")
            schedule = ScheduledLoopSchedule(entries=tuple(ScheduledScheduleEntry(
                effective_trade_date=d, version=v)
                for d, v in ((start.date(), old), (TUESDAY, new))))
            # Both sides use scheduled identity rules; only the future entry differs.
            run = ScheduledLoopInput.model_validate(run.model_dump(mode="python") | dict(
                schema_version="monitor-loop-input-v2", schedule=schedule))
        elif mutation == "policy":
            # Construct the same scheduled original prefix without the future entry.
            from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput
            from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule
            schedule = ScheduledLoopSchedule.model_validate_json(run.schedule.model_dump_json())
            run = ScheduledLoopInput.model_validate(run.model_dump(mode="python") | dict(
                schema_version="monitor-loop-input-v2", schedule=schedule))
        audit = []
        with LoopSession(tmp_path / f"{mutation}-{index}", run, calendar) as session:
            writer = LoopReportWriter(session, sink=audit.append)
            report = writer.finish(LoopRunner(session, report_writer=writer).run(frames))
            assert report.cycle.fills == 0
            verify_loop_events(report, audit)
        prefixes.append([(e.at, e.payload) for e in audit if e.at < late])
    assert prefixes[0] == prefixes[1]


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_delayed_source_budget_survives_reviewed_policy_replacement(p3_chain, tmp_path):
    from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput
    from trade_plan_monitor.backtest.p3_replay_input import CapitalReplayProgram
    from trade_plan_monitor.backtest.plan_schedule import (
        ScheduledLoopSchedule,
        ScheduledPlanVersion,
        ScheduledScheduleEntry,
    )
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256

    chain = p3_chain
    start = chain.now
    late = datetime.combine(TUESDAY, time(9, 35), SH)
    opening = frozen_opening(chain, available_at=late)
    initial = capital_loop_input(chain, mode="OBSERVE_ONLY")
    original = ScheduledPlanVersion.model_validate(
        initial.schedule.entries[0].version.model_dump(mode="python"))
    raw = chain.plan.model_dump(mode="json")
    raw["position"]["limit"]["capital_policy"]["cap_fen"] += 1
    successor = type(chain.plan).model_validate(raw)
    available = late.replace(hour=9, minute=30)
    version = ScheduledPlanVersion.model_validate(original.model_dump(mode="python") | dict(
        version_id="replacement", snapshot=successor, plan_hash=plan_sha256(successor),
        available_at=available, information_cutoff=available,
        review=original.review.model_copy(update=dict(
            content_hash=daily_plan_content_sha256(successor), reviewed_at=available))))
    schedule = ScheduledLoopSchedule(entries=(
        ScheduledScheduleEntry(effective_trade_date=start.date(), version=original),
        ScheduledScheduleEntry(effective_trade_date=TUESDAY, version=version)))
    run = ScheduledLoopInput.model_validate(initial.model_dump(mode="python") | dict(
        schema_version="monitor-loop-input-v2", schedule=schedule,
        capital_program=CapitalReplayProgram(opening_events=(opening,))))
    calendar = calendar_for(chain)
    frames = loop_frames(chain, calendar)
    with LoopSession(tmp_path / "delayed-source", run, calendar) as session:
        runner = LoopRunner(session)
        runner.run(frames)
        assert session.plan == successor
        assert session.capital.outcomes[0].status == "APPLIED", session.capital.outcomes
        from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
        with session.work() as work:
            assert CapitalRepository(work.daily.session).get(
                chain.plan.symbol).retained_basis_fen == 20000


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_frozen_buy_reference_reconciles_exact_private_lot_and_releases_residual_cost(
    p3_chain, tmp_path,
):
    from tests.integration.test_daily_plan_chain import WEDNESDAY
    from tests.integration.test_market_exception_runtime import exception_inputs
    from tests.integration.test_p3_replay import research_run_input

    from trade_plan_monitor.backtest.research_input import ResearchSimulation
    from trade_plan_monitor.backtest.research_session import ResearchSession
    from trade_plan_monitor.state.daily_accounting import DailyAccounting
    from trade_plan_monitor.state.database import create_sqlite_engine
    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository

    chain = p3_chain
    opening = frozen_opening(chain)
    directory = tmp_path / "lot-reference"
    directory.mkdir()
    session = ResearchSession(directory, research_run_input(chain, openings=(opening,)),
                              calendar_for(chain))
    try:
        session.capital.apply(session.now)
        session.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        chain.now = session.now = datetime.combine(TUESDAY, time(9, 35), SH)
        ready = session.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        signal = ready.snapshot["signals"][0]
        filled = session.apply_operation(ResearchSimulation(kind="SIMULATE", operation_id="buy",
            at=chain.now, order=1, rule_id=signal["rule_id"], occurrence=1, quantity=200),
            ended=False)
        assert filled.status == "APPLIED"
        raw = opening.model_dump(mode="python", exclude={"envelope_hash"})
        raw.update(source_event_id="explicit-after-buy-correction", provenance="RESEARCH_SCENARIO",
            recorded_event=None, observed_at=chain.now, received_at=chain.now,
            available_at=chain.now, excerpt="Explicit cost of new buy lot32701fen",
            lots=(*raw["lots"], dict(source_lot_id=None, bucket="TACTICAL", quantity=200,
                retained_basis_fen=32701,
                reference=dict(kind="BUY_SIGNAL", signal_id=signal["signal_id"]))))
        wrong = {**raw, "lots": (*raw["lots"][:1], {**raw["lots"][1],
            "reference": dict(kind="BUY_SIGNAL", signal_id="0"*64)})}
        blocked = apply_frozen_capital(session, FrozenCapitalOpening.build(**wrong))
        assert blocked.blockers == ("CAPITAL_REPLAY_BUY_LOT_MISSING",)
        receipt = apply_frozen_capital(session, FrozenCapitalOpening.build(**raw))
        assert receipt.status == "APPLIED", receipt
        session.now = datetime.combine(WEDNESDAY, time(10), SH)
        with session.work() as work:
            account = DailyAccounting(work.daily)
            for revision, expected in ((2, 36351), (3, 20000)):
                account.simulate(symbol=chain.plan.symbol, identity=f"selected-sell-{revision}",
                    side="SELL", quantities={"TACTICAL": 100}, expected_revision=revision,
                    lot_allocations=({"id": filled.simulation_id, "bucket": "TACTICAL",
                                      "quantity": 100},), now=session.now)
                assert CapitalRepository(work.daily.session).get(
                    chain.plan.symbol).retained_basis_fen == expected
            final = CapitalRepository(work.daily.session).get(chain.plan.symbol)
            work.commit()
    finally:
        session.close()
    from sqlalchemy.orm import Session
    engine = create_sqlite_engine(directory / "runtime.sqlite")
    try:
        with Session(engine) as reopened:
            assert CapitalRepository(reopened).get(chain.plan.symbol) == final
    finally:
        engine.dispose()
