"""Removing a pending exception cannot grant a trade or require new source proof."""

from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_source_coverage_exception_actions import _candidate, _stale_source
from tests.integration.test_source_coverage_exception_actions import (
    exception_chain as exception_chain,
)

from trade_plan_monitor.runtime.market_exceptions import apply_exception_decision
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.market_exception_service import ExceptionDecisionCommand


def test_rejection_after_source_diagnostic_refresh_removes_only_the_pending_permission(
    exception_chain,
):
    chain = exception_chain
    candidate = _candidate(chain)
    _stale_source(chain)
    refreshed = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert "SOURCE_COVERAGE_STALE" in refreshed.snapshot["data_blockers"]
    assert not refreshed.snapshot["signals"]

    with chain.plans._unit_of_work() as work:
        before = DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date())
        receipt = apply_exception_decision(work, ExceptionDecisionCommand(
            command_id="reject-after-source-refresh", candidate_id=candidate.candidate_id,
            expected_revision=1, decision="REJECT", reason="Withdraw the pending permission"),
            now=chain.now)
        assert receipt.candidate.state == "REJECTED"
        assert receipt.candidate.frozen_quantity is None
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL")
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
        assert DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date()) == before
        work.commit()
