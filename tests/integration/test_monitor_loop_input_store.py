"""Submitted inputs survive mutable preparation/market state and remain bounded."""

import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from tests.integration.test_backtest_market_store import (
    PROFILE,
    _calendar,
    _daily,
    _limit,
    _minute_batch,
)
from tests.integration.test_plan_preparation_review import NOW, ready_preparation, review_command
from tests.unit.test_monitor_loop_input import costs
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.jobs.models import MAX_JOB_REQUEST_BYTES, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetRequest
from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy, MonitorLoopInput
from trade_plan_monitor.backtest.loop_input_store import LoopInputStore
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.results import BacktestResultStore


def frozen_case(tmp_path, *, days=1):
    preparation, ready = ready_preparation(
        tmp_path,
        metadata={
            "authored_at": at(24),
            "available_at": at(24),
            "effective_trade_date": at(24).date(),
        },
    )
    prepared = frozen_preparation(
        preparation.review_and_freeze(
            "one",
            command=review_command(ready),
            idempotency_key="review",
        )
    )
    market = BacktestMarketStore(tmp_path / "market.sqlite3")
    symbol = prepared.version.snapshot.symbol
    for offset in range(days):
        day = at(24).date() + timedelta(days=offset)
        previous = at(21).date() if offset == 0 else day - timedelta(days=1)
        market.record_trading_days(
            (
                _calendar().model_copy(
                    update={
                        "exchange": "SZSE",
                        "cal_date": day,
                        "previous_trade_date": previous,
                    }
                ),
            )
        )
        market.record_minute_batch(_minute_batch(symbol=symbol, trade_date=day))
        market.record_daily_limits(
            (
                _limit().model_copy(
                    update={
                        "symbol": symbol,
                        "trade_date": day,
                        "received_at": at(24, 9, 30) + timedelta(days=offset),
                    }
                ),
            )
        )
        market.record_daily_bars(
            (
                _daily().model_copy(
                    update={
                        "symbol": symbol,
                        "trade_date": day,
                        "received_at": at(24, 15, 20) + timedelta(days=offset),
                    }
                ),
            )
        )
    boundary = LoopEndBoundary.resolve(
        started_at=at(24),
        submitted_at=NOW,
        end_date=day,
    )
    dataset = market.freeze_loop_dataset(
        LoopDatasetRequest(
            scope=DatasetScope(
                symbols=(symbol,),
                start=at(24).date(),
                end=day,
                warmup_start=at(24).date(),
                historical_profile=PROFILE,
            ),
            boundary=boundary,
            schedule=prepared.schedule,
        )
    ).manifest
    run_input = MonitorLoopInput(
        schedule=prepared.schedule,
        initial_account=prepared.account,
        boundary=boundary,
        dataset_hash=dataset.dataset_hash,
        response=LoopResponsePolicy(mode="FOLLOW_REMINDERS"),
        costs=costs(),
    )
    return preparation, market, prepared, run_input, dataset


def test_complete_input_and_market_copy_survive_original_record_removal(tmp_path):
    preparation, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    with sqlite3.connect(preparation.database_path) as connection:
        connection.execute("DELETE FROM backtest_preparation_idempotency")
        connection.execute("DELETE FROM backtest_preparation")
    with sqlite3.connect(market.database_path) as connection:
        connection.execute("DELETE FROM market_minute_head")
        connection.execute("DELETE FROM market_head")
        connection.execute("DELETE FROM market_minute_artifact")
        connection.execute("DELETE FROM market_artifact")
    restarted = BacktestResultStore(results.database_path)
    stored = restarted.get_loop_input(reference)
    assert (
        stored.run_input == run_input and stored.prepared == prepared and stored.dataset == dataset
    )
    with restarted.loop_input_store.open_dataset(reference) as reader:
        assert len(tuple(reader)[0].minutes) == 240
    assert len(reference.model_dump_json().encode()) < MAX_JOB_REQUEST_BYTES
    assert (
        restarted.record_loop_input(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=market,
        )
        == reference
    )


def test_result_store_is_inert_and_repeated_copy_is_immutable(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    assert not results.loop_input_store.root.exists()
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    before = {
        file.name: file.read_bytes() for file in results.loop_input_store.root.rglob("*.json")
    }
    assert (
        results.record_loop_input(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=market,
        )
        == reference
    )
    assert before == {
        file.name: file.read_bytes() for file in results.loop_input_store.root.rglob("*.json")
    }
    with pytest.raises(ValueError):
        reference.model_copy(update={"run_id": "../bad"})


def test_large_market_copy_queues_only_a_verified_path_free_reference(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path, days=5)
    repository = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: NOW)
    results = BacktestResultStore(repository.database_path)
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    assert (
        sum(file.stat().st_size for file in results.loop_input_store.root.rglob("*.json"))
        > MAX_JOB_REQUEST_BYTES
    )
    request = MonitorLoopJobRequest(input_reference=reference)
    first = repository.submit(request, "first")
    assert repository.submit(request, "first") == first
    assert first.run_id == run_input.run_id and first.dataset_hash == dataset.dataset_hash
    with sqlite3.connect(repository.database_path) as connection:
        payload = connection.execute("SELECT request_json FROM backtest_job").fetchone()[0]
    assert len(payload.encode()) < MAX_JOB_REQUEST_BYTES
    assert set(json.loads(payload)) == {"kind", "inputReference"}
    assert "source" not in payload and "snapshot" not in payload and str(tmp_path) not in payload
    with pytest.raises(JobAdmissionError) as busy:
        repository.submit(
            request.model_copy(
                update={
                    "input_reference": reference.model_copy(
                        update={"bundle_hash": "f" * 64},
                    )
                }
            ),
            "different",
        )
    assert busy.value.code == "BACKTEST_BUSY"


def test_missing_reference_cannot_acknowledge_admission(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    repository = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: NOW)
    results = BacktestResultStore(repository.database_path)
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    results.loop_input_store.bundle_path(reference).unlink()
    with pytest.raises((RuntimeError, ValueError)):
        repository.submit(MonitorLoopJobRequest(input_reference=reference), "missing")
    with sqlite3.connect(repository.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_job").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM backtest_job_idempotency").fetchone()[0] == 0
        )


@pytest.mark.parametrize("target", ["bundle", "day", "row", "snapshot"])
def test_corruption_has_no_fallback_and_never_overwrites_original(tmp_path, target):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    stored = results.get_loop_input(reference)
    if target in {"bundle", "day"}:
        path = (
            results.loop_input_store.bundle_path(reference)
            if target == "bundle"
            else results.loop_input_store.day_path(stored.day_hashes[0])
        )
        path.write_bytes(b"{}")
    else:
        with sqlite3.connect(results.database_path) as connection:
            if target == "row":
                connection.execute("UPDATE backtest_run_input SET input_json = '{}' ")
            else:
                connection.execute("UPDATE backtest_plan_snapshot SET snapshot_json = '{}' ")
    with pytest.raises((RuntimeError, ValueError)):
        results.get_loop_input(reference)


def test_unbound_account_or_dataset_cannot_be_persisted(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    changed = run_input.model_copy(
        update={
            "initial_account": run_input.initial_account.model_copy(
                update={
                    "cash": run_input.initial_account.cash.model_copy(update={"balance_fen": 1})
                },
            )
        }
    )
    with pytest.raises(ValueError, match="bind"):
        results.record_loop_input(
            prepared=prepared,
            run_input=changed,
            dataset=dataset,
            market_source=market,
        )
    assert not results.loop_input_store.root.exists()


def test_failed_copy_never_binds_or_admits_partial_input_and_retry_is_exact(tmp_path, monkeypatch):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    original = os.link

    def fail_bundle(source, destination):
        if Path(destination).name.startswith("bundle-"):
            raise OSError("synthetic atomic publication failure")
        return original(source, destination)

    monkeypatch.setattr(os, "link", fail_bundle)
    with pytest.raises(OSError, match="synthetic"):
        results.record_loop_input(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=market,
        )
    with sqlite3.connect(results.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_run_input").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM backtest_plan_snapshot").fetchone()[0] == 0
    assert not tuple(results.loop_input_store.root.glob(".writing-*"))
    assert not tuple(results.loop_input_store.root.glob("bundle-*.json"))
    monkeypatch.setattr(os, "link", original)
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    assert results.get_loop_input(reference).run_input == run_input
    assert LoopInputStore(results.database_path).load(reference).reference == reference


def test_reserved_submission_binds_the_original_small_reference(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    repository = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: NOW)
    results = BacktestResultStore(repository.database_path)
    intent = canonical_json({"preparationId": "one", "endDate": dataset.scope.end})
    reservation = repository.claim_run_submission(intent, "reserved")
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    receipt = repository.finalize_run_submission(
        MonitorLoopJobRequest(input_reference=reference),
        reservation,
    )
    replay = repository.claim_run_submission(intent, "reserved")
    assert replay.receipt == receipt
    assert json.loads(replay.canonical_request_json)["inputReference"] == reference.model_dump(
        mode="json"
    )


def test_unowned_directory_is_rejected_without_overwriting_it(tmp_path):
    _, market, prepared, run_input, dataset = frozen_case(tmp_path)
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    root = results.loop_input_store.root
    root.mkdir()
    original = root / "foreign.json"
    original.write_bytes(b"unrelated input")
    with pytest.raises(RuntimeError, match="ownership"):
        results.record_loop_input(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=market,
        )
    assert original.read_bytes() == b"unrelated input" and len(tuple(root.iterdir())) == 1
