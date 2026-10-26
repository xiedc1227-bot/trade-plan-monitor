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
