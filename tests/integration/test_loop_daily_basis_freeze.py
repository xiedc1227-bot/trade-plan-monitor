"""Factor ownership survives mutable market sources and participates in run identity."""

import json
from datetime import datetime, time
from decimal import Decimal

import pytest
from tests.integration.test_monitor_loop_input_store import scheduled_frozen_case

from trade_plan_monitor.backtest.daily_basis import DailyBasisStore, HistoricalAdjustmentFactor
from trade_plan_monitor.backtest.loop_dataset import (
    ScheduledLoopDatasetManifest,
    ScheduledLoopDatasetRequest,
    freeze_scheduled_loop_dataset,
)
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.backtest.time import SHANGHAI


def test_frozen_factors_change_identity_and_are_owned_by_submitted_result(tmp_path):
    _, market, prepared, run, original = scheduled_frozen_case(tmp_path)
    basis = DailyBasisStore(market.database_path)
    proofs = tuple(
        HistoricalAdjustmentFactor(
            symbol=prepared.schedule.symbol,
            trade_date=d.trade_date,
            factor=Decimal("1"),
            available_at=datetime.combine(d.trade_date, time(9, 30), SHANGHAI),
            collected_at=run.boundary.submitted_at,
        )
        for d in original.days
        if d.state != "CLOSED"
    )
    basis.record(proofs)
    dataset = freeze_scheduled_loop_dataset(
        market,
        ScheduledLoopDatasetRequest(
            scope=original.scope, schedule=run.schedule, boundary=run.boundary
        ),
    ).manifest
    assert dataset.dataset_hash != original.dataset_hash
    assert dataset.adjustment_factors == proofs
    assert "adjustment_factors" not in original.model_dump()
    changed = run.model_copy(update={"dataset_hash": dataset.dataset_hash})
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = results.record_loop_input(
        prepared=prepared, run_input=changed, dataset=dataset, market_source=market
    )
    basis.record(tuple(p.model_copy(update={"factor": Decimal("2")}) for p in proofs))
    stored = BacktestResultStore(results.database_path).get_loop_input(reference)
    assert stored.dataset.adjustment_factors == proofs
    payload = dataset.model_dump(mode="json")
    payload["adjustment_factors"][0]["factor"] = "9"
    with pytest.raises(ValueError, match="identity"):
        ScheduledLoopDatasetManifest.model_validate_json(json.dumps(payload))
