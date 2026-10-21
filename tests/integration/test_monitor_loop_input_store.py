"""Submitted inputs survive mutable preparation/market state and remain bounded."""

import json
import os
import sqlite3
from datetime import timedelta
from hashlib import sha256
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


def test_scheduled_stored_input_has_a_distinct_codec():
    from trade_plan_monitor.backtest.loop_input_store import (
        ScheduledStoredLoopInput,
        StoredLoopInput,
    )

    assert not issubclass(ScheduledStoredLoopInput, StoredLoopInput)


def scheduled_frozen_case(tmp_path, *, end_day=20, later_text=None):
    """Synthetic reviewed sources and complete offline market evidence, August 19/20."""
    from tests.integration.test_plan_preparation_review import (
        collection_review_command,
        ready_collection,
    )

    from trade_plan_monitor.backtest.loop_dataset import (
        ScheduledLoopDatasetRequest,
        freeze_scheduled_loop_dataset,
    )
    from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput

    preparation, ready = ready_collection(tmp_path, later_text=later_text)
    prepared = frozen_preparation(
        preparation.review_and_freeze(
            ready.preparation_id,
            command=collection_review_command(ready),
            idempotency_key="review",
        )
    )
    snapshot = prepared.items[0].version.snapshot
    market = BacktestMarketStore(tmp_path / "scheduled-market.sqlite3")
    for number in (19, 20):
        day = at(number).date()
        market.record_trading_days(
            (
                _calendar().model_copy(
                    update={
                        "exchange": snapshot.market,
                        "cal_date": day,
                        "previous_trade_date": at(number - 1).date(),
                    }
                ),
            )
        )
        market.record_minute_batch(_minute_batch(symbol=snapshot.symbol, trade_date=day))
        market.record_daily_limits(
            (
                _limit().model_copy(
                    update={
                        "symbol": snapshot.symbol,
                        "trade_date": day,
                        "received_at": at(number, 9, 30),
                    }
                ),
            )
        )
        market.record_daily_bars(
            (
                _daily().model_copy(
                    update={
                        "symbol": snapshot.symbol,
                        "trade_date": day,
                        "received_at": at(number, 15, 20),
                    }
                ),
            )
        )
    boundary = LoopEndBoundary.resolve(
        started_at=at(19),
        submitted_at=NOW,
        end_date=at(end_day).date(),
    )
    dataset = freeze_scheduled_loop_dataset(
        market,
        ScheduledLoopDatasetRequest(
            scope=DatasetScope(
                symbols=(snapshot.symbol,),
                start=at(19).date(),
                end=at(end_day).date(),
                warmup_start=at(19).date(),
                historical_profile=PROFILE,
            ),
            schedule=prepared.schedule,
            boundary=boundary,
        ),
    ).manifest
    run_input = ScheduledLoopInput(
        schedule=prepared.schedule,
        initial_account=prepared.account,
        boundary=boundary,
        dataset_hash=dataset.dataset_hash,
        response=LoopResponsePolicy(mode="FOLLOW_REMINDERS"),
        costs=costs(),
    )
    return preparation, market, prepared, run_input, dataset


def test_scheduled_bundle_round_trip_keeps_complete_frozen_chain_and_copied_days(tmp_path):
    from trade_plan_monitor.backtest.loop_input_store import (
        ScheduledStoredLoopInput,
        StoredLoopInput,
    )

    preparation, market, prepared, run_input, dataset = scheduled_frozen_case(tmp_path)
    store = LoopInputStore(tmp_path / "results.sqlite3")
    stored = store.persist(
        prepared=prepared, run_input=run_input, dataset=dataset, market_source=market
    )
    assert isinstance(stored, ScheduledStoredLoopInput)
    assert (
        stored.prepared == prepared and stored.run_input == run_input and stored.dataset == dataset
    )
    assert len(stored.day_hashes) == len(set(stored.day_hashes)) == 2
    with pytest.raises(ValueError):
        StoredLoopInput.model_validate_json(stored.model_dump_json())
    record = preparation.get(prepared.preparation_id)
    preparation.edit_collection(
        record.preparation_id,
        source=record.items[1].source.model_copy(update={"text": "Synthetic later source edit."}),
        expected_revision=record.revision,
        idempotency_key="edit-after-copy",
    )
    with sqlite3.connect(market.database_path) as connection:
        for table in (
            "market_minute_head",
            "market_head",
            "market_minute_artifact",
            "market_artifact",
        ):
            connection.execute(f"DELETE FROM {table}")
    restarted = LoopInputStore(tmp_path / "results.sqlite3")
    assert restarted.load(stored.reference) == stored
    with restarted.open_dataset(stored.reference) as reader:
        days = tuple(reader)
    assert [day.trade_date for day in days] == [at(19).date(), at(20).date()]
    assert [len(day.minutes) for day in days] == [240, 240]


def test_scheduled_copied_day_hash_cannot_be_rebound_to_another_date(tmp_path):
    _, market, prepared, run_input, dataset = scheduled_frozen_case(tmp_path)
    store = LoopInputStore(tmp_path / "results.sqlite3")
    stored = store.persist(
        prepared=prepared, run_input=run_input, dataset=dataset, market_source=market
    )
    changed = stored.model_copy(update={"day_hashes": tuple(reversed(stored.day_hashes))})
    # Recompute the outer content address: inner date binding must still detect the swap.
    store.bundle_path(changed.reference).write_text(canonical_json(changed), encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        store.load(changed.reference)
    assert store.load(stored.reference) == stored


@pytest.mark.parametrize("mismatch", ["account", "plan_binding", "requirements"])
def test_scheduled_unbound_collection_rejected_before_publication(tmp_path, mismatch):
    from trade_plan_monitor.backtest.loop_dataset import ScheduledLoopDatasetManifest

    _, market, prepared, run_input, dataset = scheduled_frozen_case(tmp_path)
    if mismatch == "account":
        changed = run_input.initial_account.model_copy(
            update={
                "cash": run_input.initial_account.cash.model_copy(update={"balance_fen": 7}),
            }
        )
        run_input = run_input.model_copy(update={"initial_account": changed})
    else:
        values = dataset.model_dump(mode="python")
        if mismatch == "plan_binding":
            values["plan_bindings"] = values["plan_bindings"][:1]
        else:
            values["requirements"]["minute_observations"] = 99
        values.pop("dataset_hash")
        dataset = ScheduledLoopDatasetManifest.build(**values)
        run_input = run_input.model_copy(update={"dataset_hash": dataset.dataset_hash})
    store = LoopInputStore(tmp_path / "results.sqlite3")
    with pytest.raises(ValueError, match="bind"):
        store.persist(prepared=prepared, run_input=run_input, dataset=dataset, market_source=market)
    assert not store.root.exists()


def test_scheduled_result_registration_and_restart_use_first_causal_snapshot(tmp_path):
    _, market, prepared, run_input, dataset = scheduled_frozen_case(tmp_path)
    BacktestJobRepository(tmp_path / "results.sqlite3")
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    restarted = BacktestResultStore(results.database_path)
    assert restarted.get_loop_input(reference).prepared == prepared
    assert restarted.get_loop_input_reference(run_input.run_id) == reference


def test_scheduled_future_source_changes_bundle_but_not_earlier_authority_or_dataset(tmp_path):
    cases = []
    for name, text in (("first", None), ("changed", "调整最大仓位为300股，其余规则保留。")):
        directory = tmp_path / name
        directory.mkdir()
        _, market, prepared, run_input, dataset = scheduled_frozen_case(
            directory,
            end_day=19,
            later_text=text,
        )
        stored = LoopInputStore(directory / "results.sqlite3").persist(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=market,
        )
        payload_bytes = canonical_json(stored).encode()
        assert (
            stored.reference.bundle_hash
            == sha256(
                b"monitor-loop-stored-input-v2\0" + payload_bytes,
            ).hexdigest()
        )
        assert (
            stored.reference.bundle_hash
            != sha256(
                b"monitor-loop-stored-input-v1\0" + payload_bytes,
            ).hexdigest()
        )
        cases.append(stored)
    first, changed = cases
    assert first.dataset == changed.dataset
    assert len(first.dataset.plan_bindings) == 1
    assert first.run_input.schedule.select(at(19, 10)).authority_id == (
        changed.run_input.schedule.select(at(19, 10)).authority_id
    )
    assert first.reference.bundle_hash != changed.reference.bundle_hash
    assert first.run_input.input_hash != changed.run_input.input_hash


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
    BacktestJobRepository(tmp_path / "results.sqlite3")
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
