"""The mounted submission route freezes explicit capital facts before queue admission."""

import asyncio
from datetime import datetime, time

import pytest
from tests.integration.market_exception_replay_support import market_fixture, prepared_fixture
from tests.integration.test_backtest_run_api import _client
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_monitor_loop_submission import Coordinator, payload
from tests.integration.test_p3_chain import p3_chain as p3_chain
from tests.integration.test_p3_replay import capital_loop_input, frozen_opening

from trade_plan_monitor.backtest.composition import _ProductionBacktestService
from trade_plan_monitor.backtest.dataset_service import BacktestDatasetService
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.p3_replay_input import (
    CapitalExceptionReplayProgram,
    CapitalReplayProgram,
)
from trade_plan_monitor.backtest.pagination import HmacCursorSigner
from trade_plan_monitor.backtest.result_service import BacktestResultService
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_real_prepared_http_admission_requires_explicit_capital_and_replays_same_job(
    p3_chain, tmp_path,
):
    chain = p3_chain
    market, _, _, _, _, _ = market_fixture(tmp_path, chain.plan, chain.route)
    opening = frozen_opening(chain)
    run = capital_loop_input(chain, openings=(opening,))
    prepared = prepared_fixture(tmp_path, chain.plan, chain.now, run.initial_account)
    jobs = BacktestJobRepository(tmp_path / "admission-results.sqlite",
        clock=lambda: datetime.combine(TUESDAY, time(10, 0, 12), SH))
    results = BacktestResultStore(jobs.database_path)
    coordinator = Coordinator()
    signer = HmacCursorSigner(b"x"*32)

    async def read_prepared(identity):
        assert identity == prepared.preparation_id
        return prepared

    service = _ProductionBacktestService(plan_snapshot_reader=None, market_store=market,
        repository=jobs, result_store=results,
        dataset_service=BacktestDatasetService(store=market, cursor_signer=signer),
        result_service=BacktestResultService(store=results, cursor_signer=signer),
        coordinator=coordinator, result_cursor_signer=signer,
        job_cursor_signer=BacktestApiCursorSigner(b"x"*32), prepared_plan_reader=read_prepared)
    client = _client(operation_service=service)
    try:
        missing = client.post("/api/v1/backtest-runs", json=payload(prepared),
            headers={"Idempotency-Key": "missing-budget"})
        assert missing.status_code == 409, missing.text
        assert coordinator.authorized == []
        values = payload(prepared,
            capitalProgram=CapitalReplayProgram(opening_events=(opening,)).model_dump(mode="json"),
            exceptionProgram=CapitalExceptionReplayProgram().model_dump(mode="json"))
        first = client.post("/api/v1/backtest-runs", json=values,
            headers={"Idempotency-Key": "explicit-budget"})
        assert first.status_code == 202, first.text
        duplicate = client.post("/api/v1/backtest-runs", json=values,
            headers={"Idempotency-Key": "explicit-budget"})
        assert duplicate.status_code == 202 and duplicate.json() == first.json()
        assert coordinator.authorized == [first.json()["jobId"]]
        stored = results.get_loop_input(results.get_loop_input_reference(first.json()["runId"]))
        assert stored.run_input.run_formula_version == "backtest-run-v10"
        assert stored.run_input.capital_program.opening_events == (opening,)
        assert stored.run_input.initial_account.cash.kind == "POSITION_LIMIT_ONLY"
        assert stored.run_input.initial_account.accounting_cost_fen is None
        from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
        with chain.plans._unit_of_work() as work:
            assert CapitalRepository(work.daily.session).get(
                chain.plan.symbol).retained_basis_fen == 20000
            assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
    finally:
        client.close()
        asyncio.run(service.stop_metadata())
