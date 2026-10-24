"""Exercise the real frozen dataset readers and workers, including published loop reports."""

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
from tests.integration.test_market_exception_replay import exception_loop_input, research_run_input
from tests.integration.test_market_exception_runtime import exception_chain as exception_chain

from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetRequest
from trade_plan_monitor.backtest.loop_replay import run_frozen_loop
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFactor,
    ResearchSimulation,
)
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner


def test_frozen_workers_preserve_both_exception_routes_and_isolate_authority(
    exception_chain, tmp_path
):
    chain = exception_chain
    market, dataset, calendar, daily, indices, factors = market_fixture(
        tmp_path, chain.plan, chain.route
    )
    event = frozen_market_approval(tmp_path, chain, calendar, daily, indices, factors)
    quantity = 100 if chain.route == "WEAK_MINIMUM" else 300
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="explicit-buy",
        order=1,
        at=datetime.combine(TUESDAY, time(9, 35, 12), SH),
        rule_id=event.candidate.binding.rule_id,
        occurrence=1,
        quantity=quantity,
    )
    frozen = research_run_input(chain, events=(event,), operations=(operation,)).research_input
    proof = ResearchAdjustmentProof(
        proof_id="explicit-frozen-basis",
        dataset_hash=dataset,
        symbol=chain.plan.symbol,
        provider="TUSHARE",
        available_at=chain.now,
        received_at=chain.now,
        adjustment_as_of=FRIDAY,
        quote_basis_factor=Decimal(1),
        factors=tuple(
            ResearchFactor(trade_date=d.trade_date, factor=Decimal(1))
            for d in daily
            if d.trade_date <= FRIDAY
        ),
        evidence="Synthetic explicit verified adjustment factors",
    )
    frozen = frozen.model_copy(
        update={
            "adjustment_proofs": (proof,),
            "calendar_extension": tuple(d for d in calendar if d.cal_date > TUESDAY),
        }
    )
    report = OfflineBacktestRunner(market).run(
        plan=chain.plan,
        dataset_hash=dataset,
        initial_cash_fen=1000000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
    )
    assert report.exception_outcomes[0].status == "APPLIED", report.exception_outcomes
    assert report.metrics.trade_count == 1, report.operations
    assert report.final_inventory.total_qty == quantity
    assert "RESEARCH_SCENARIO" in report.limitations
    from trade_plan_monitor.backtest.composition import _detail_view
    from trade_plan_monitor.backtest.reporting import persist_report
    from trade_plan_monitor.backtest.results import BacktestDetailKind, BacktestResultStore
    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    with market.open_frozen_dataset(dataset) as reader:
        frozen_input = BacktestRunInput.create(plan=chain.plan, manifest=reader.manifest,
            initial_cash_fen=1000000, initial_lots=(), execution_config=_execution_config(),
            manual_event_risk=False, research_input=frozen)
    results = BacktestResultStore(tmp_path / "research-results.sqlite")
    import json
    for decision in report.current_events:
        encoded = decision.model_dump(mode="json")
        assert len(json.dumps(encoded).encode()) < 32000, json.dumps({
            key: len(json.dumps(value).encode()) for key, value in encoded.items()})
    referenced = next(d for d in report.current_events if any(
        hasattr(s, "market_linkage_ref") for s in d.signals))
    corrupted = referenced.model_dump(mode="json")
    corrupted["signals"][0]["market_linkage_ref"] = "0" * 64
    with pytest.raises(ValueError, match="frozen linkage"):
        type(referenced).model_validate_json(json.dumps(corrupted))
    persist_report(results, report, run_input=frozen_input)
    details = results.list_details(report.run_id, kind=BacktestDetailKind.DECISION)
    recorded = [d for d in details if d.payload.get("exception_outcomes")]
    assert len(recorded) == 1
    view = _detail_view(recorded[0])
    assert view.research_decision.exception_outcomes[0].provenance == "RESEARCH_SCENARIO"
    _publish_loop(tmp_path, market, dataset, chain, event, operation, quantity)
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="EXCEPTION_EVENT") == ()
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()


def _publish_loop(directory, market, dataset, chain, event, operation, quantity):
    from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
    from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
    from trade_plan_monitor.backtest.results import BacktestResultStore

    run = exception_loop_input(chain, events=(event,), operations=(operation,))
    prepared = prepared_fixture(directory, chain.plan, chain.now, run.initial_account)
    with market.open_frozen_dataset(dataset) as reader:
        scope = reader.scope
    request = LoopDatasetRequest(scope=scope, boundary=run.boundary, schedule=prepared.schedule)
    frozen = market.freeze_loop_dataset(request)
    assert frozen.ready, frozen.blockers
    run = run.model_copy(
        update={
            "schedule": prepared.schedule,
            "dataset_hash": frozen.manifest.dataset_hash,
            "initial_account": prepared.account,
        }
    )
    jobs = BacktestJobRepository(
        directory / "results.sqlite", clock=lambda: run.boundary.evidence_cutoff
    )
    results = BacktestResultStore(jobs.database_path)
    reference = results.record_loop_input(
        prepared=prepared, run_input=run, dataset=frozen.manifest, market_source=market
    )
    jobs.submit(MonitorLoopJobRequest(input_reference=reference), "exception-loop")
    claim = jobs.claim_next()
    report = run_frozen_loop(
        results, reference, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert report.exception_outcomes[0].status == "APPLIED", report.exception_outcomes
    assert report.cycle.fills == 1, report.exception_requests
    assert report.final_inventory.total_qty == quantity
    assert report.exception_provenance == ("RESEARCH_SCENARIO",)
    assert jobs.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    assert BacktestResultStore(jobs.database_path).get_loop_report(reference.run_id) == report


def test_future_authorization_does_not_change_prior_research_events(exception_chain, tmp_path):
    from tests.integration.test_market_exception_replay_mutations import changed_event

    chain = exception_chain
    market, dataset, calendar, daily, indices, factors = market_fixture(
        tmp_path, chain.plan, chain.route
    )
    source = frozen_market_approval(tmp_path, chain, calendar, daily, indices, factors)
    late = datetime.combine(TUESDAY, time(9, 40), SH)
    event = changed_event(source, state="APPROVED", at=late, quantity=source.event.quantity)
    proof = ResearchAdjustmentProof(
        proof_id="explicit-frozen-basis",
        dataset_hash=dataset,
        symbol=chain.plan.symbol,
        provider="TUSHARE",
        available_at=chain.now,
        received_at=chain.now,
        adjustment_as_of=FRIDAY,
        quote_basis_factor=Decimal(1),
        factors=tuple(
            ResearchFactor(trade_date=d.trade_date, factor=Decimal(1))
            for d in daily
            if d.trade_date <= FRIDAY
        ),
        evidence="Synthetic basis",
    )
    reports = []
    for events in ((), (event,)):
        frozen = research_run_input(chain, events=events).research_input.model_copy(
            update={
                "adjustment_proofs": (proof,),
                "calendar_extension": tuple(d for d in calendar if d.cal_date > TUESDAY),
            }
        )
        reports.append(
            OfflineBacktestRunner(market).run(
                plan=chain.plan,
                dataset_hash=dataset,
                initial_cash_fen=1000000,
                execution_config=_execution_config(),
                manual_event_risk=False,
                research_input=frozen,
            )
        )
    assert all(report.metrics.trade_count == 0 for report in reports)
    assert reports[1].exception_outcomes[0].status == "APPLIED"
    assert [e for e in reports[0].current_events if e.at < late] == [
        e for e in reports[1].current_events if e.at < late
    ]
