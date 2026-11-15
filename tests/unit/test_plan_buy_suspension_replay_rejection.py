"""Unsupported new-contract work stops before old frozen/update adapters run."""

import pytest
from pydantic import ValidationError
from tests.unit.test_backtest_run_input import _config, _goldens
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_plan_buy_suspension_contract import suspension_payload
from tests.unit.test_unified_replay_input import research_input

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
from trade_plan_monitor.backtest.runner import BacktestBlockedError, OfflineBacktestRunner
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan


@pytest.mark.parametrize("native", [False, True])
def test_legacy_update_context_rejects_schema10_without_dropping_its_guard(native):
    raw = suspension_payload()
    plan = BuySuspensionTradePlan.model_validate(raw)
    with pytest.raises(ValidationError, match="BUY_SUSPENSION_UPDATE_UNSUPPORTED"):
        PlanUpdateContext(
            base_hash=plan_sha256(plan), snapshot=plan if native else raw, available_at=at(),
        )


def test_direct_frozen_runner_rejects_new_plan_before_opening_any_dataset():
    class UnavailableDatasetSource:
        def open_frozen_dataset(self, dataset_hash):
            raise AssertionError("unsupported guard plan must not enter the old frozen adapter")

    plan = BuySuspensionTradePlan.model_validate(suspension_payload())
    runner = OfflineBacktestRunner(UnavailableDatasetSource())
    with pytest.raises(BacktestBlockedError) as error:
        runner.run(
            plan=plan, dataset_hash="0" * 64, initial_cash_fen=1000000,
            execution_config=_config(_goldens()["cases"][0]), manual_event_risk=False,
            research_input=research_input(plan),
        )
    assert error.value.blockers == ("BUY_SUSPENSION_FROZEN_UNSUPPORTED",)
