"""Actual copied datasets, private workers and publication/read-back for capital policies."""

import json
from datetime import datetime, time
from decimal import Decimal

import pytest
from tests.integration.market_exception_replay_support import (
    frozen_market_approval,
    market_fixture,
    prepared_fixture,
)
from tests.integration.test_backtest_runner import _execution_config
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY
from tests.integration.test_p3_chain import p3_chain as p3_chain
from tests.integration.test_p3_replay import capital_loop_input, frozen_opening, research_run_input

from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetRequest
from trade_plan_monitor.backtest.loop_replay import run_frozen_loop
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFactor,
    ResearchSimulation,
)
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner


@pytest.mark.parametrize("p3_chain", [("MARKET_VALUE_CAP", True, "WEAK_MINIMUM"),
    ("OPEN_COST_CAP", True, "BROKEN_STRONG")], indirect=True)
def test_real_frozen_workers_publish_reopen_capital_and_preserve_both_exception_routes(
    p3_chain, tmp_path,
):
    chain = p3_chain
    market, dataset, calendar, daily, indices, factors = market_fixture(
        tmp_path, chain.plan, chain.route)
    opening = frozen_opening(chain) if chain.capital_mode == "OPEN_COST_CAP" else None
    openings = () if opening is None else (opening,)
    event = frozen_market_approval(tmp_path, chain, calendar, daily, indices, factors,
        run_input_factory=lambda c: research_run_input(c, openings=openings))
    quantity = 100 if chain.route == "WEAK_MINIMUM" else 300
    operation = ResearchSimulation(kind="SIMULATE", operation_id="explicit-p3-buy", order=2,
        at=datetime.combine(TUESDAY, time(9, 35, 12), SH),
        rule_id=event.candidate.binding.rule_id, occurrence=1, quantity=quantity)
    run = research_run_input(chain, openings=openings, events=(event,), operations=(operation,))
    proof = ResearchAdjustmentProof(proof_id="explicit-frozen-basis", dataset_hash=dataset,
        symbol=chain.plan.symbol, provider="TUSHARE", available_at=chain.now,
        received_at=chain.now, adjustment_as_of=FRIDAY, quote_basis_factor=Decimal(1),
        factors=tuple(ResearchFactor(trade_date=d.trade_date, factor=Decimal(1))
            for d in daily if d.trade_date <= FRIDAY), evidence="Synthetic verified basis")
    frozen = run.research_input.model_copy(update=dict(adjustment_proofs=(proof,),
        calendar_extension=tuple(d for d in calendar if d.cal_date > TUESDAY)))
    report = OfflineBacktestRunner(market).run(plan=chain.plan, dataset_hash=dataset,
        initial_cash_fen=run.initial_cash_fen, initial_lots=run.initial_lots,
        execution_config=_execution_config(), manual_event_risk=False, research_input=frozen)
    assert report.exception_outcomes[0].status == "APPLIED", report.exception_outcomes
    assert report.metrics.trade_count == 1, report.operations
    assert report.final_inventory.total_qty == 100+quantity
    if opening is not None:
        assert report.capital_outcomes[0].status == "APPLIED", report.capital_outcomes
    from trade_plan_monitor.backtest.reporting import persist_report
    from trade_plan_monitor.backtest.results import BacktestDetailKind, BacktestResultStore
    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    with market.open_frozen_dataset(dataset) as reader:
        frozen_input = BacktestRunInput.create(plan=chain.plan, manifest=reader.manifest,
            initial_cash_fen=run.initial_cash_fen, initial_lots=run.initial_lots,
            execution_config=_execution_config(), manual_event_risk=False, research_input=frozen)
    for decision in report.current_events:
        encoded = decision.model_dump(mode="json")
        assert len(json.dumps(encoded).encode()) < 32000, {
            k: len(json.dumps(v).encode()) for k, v in encoded.items()}
    if opening is not None:
        from trade_plan_monitor.backtest.research_signal_projection import CapitalLinkageReference
        referenced = next(e for e in report.current_events if any(
            isinstance(p, CapitalLinkageReference) for p in e.signal_linkage or ()))
        corrupt = referenced.model_dump(mode="json")
        proof = next(p for p in corrupt["signal_linkage"] if "base_evidence_hash" in p)
        proof["base_evidence_hash"] = "0"*64
        with pytest.raises(ValueError, match="frozen capital base"):
            type(referenced).model_validate_json(json.dumps(corrupt))
    results = BacktestResultStore(tmp_path / "research-results.sqlite")
    persist_report(results, report, run_input=frozen_input)
    details = BacktestResultStore(results.database_path).list_details(
        report.run_id, kind=BacktestDetailKind.DECISION)
    assert any(d.payload.get("exception_outcomes") for d in details)
    if opening is not None:
        assert any(d.payload.get("capital_outcomes") for d in details)
    publish_loop(tmp_path, market, dataset, chain, openings, event, operation, quantity)
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()


def publish_loop(directory, market, dataset, chain, openings, event, operation, quantity):
    from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
    from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
    from trade_plan_monitor.backtest.results import BacktestResultStore

    run = capital_loop_input(chain, openings=openings, events=(event,), operations=(operation,))
    prepared = prepared_fixture(directory, chain.plan, chain.now, run.initial_account)
    with market.open_frozen_dataset(dataset) as reader:
        scope = reader.scope
    request = LoopDatasetRequest(scope=scope, boundary=run.boundary, schedule=prepared.schedule)
    frozen = market.freeze_loop_dataset(request)
    assert frozen.ready, frozen.blockers
    run = run.model_copy(update=dict(schedule=prepared.schedule,
        dataset_hash=frozen.manifest.dataset_hash, initial_account=prepared.account))
    jobs = BacktestJobRepository(directory / "results.sqlite",
        clock=lambda: run.boundary.evidence_cutoff)
    results = BacktestResultStore(jobs.database_path)
    reference = results.record_loop_input(prepared=prepared, run_input=run,
        dataset=frozen.manifest, market_source=market)
    jobs.submit(MonitorLoopJobRequest(input_reference=reference), "capital-loop")
    claim = jobs.claim_next()
    report = run_frozen_loop(results, reference, cancellation_token=CancellationToken(),
        progress_callback=lambda _: None)
    assert report.exception_outcomes[0].status == "APPLIED", report.exception_outcomes
    assert report.cycle.fills == 1, report.exception_requests
    assert report.final_inventory.total_qty == 100+quantity
    if openings:
        assert report.capital_outcomes[0].status == "APPLIED", report.capital_outcomes
    assert jobs.complete(claim.job_id, claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False))
    assert BacktestResultStore(jobs.database_path).get_loop_report(reference.run_id) == report
