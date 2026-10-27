"""A fresh run must retain preparation authority through its caller's final commit."""

import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager

import pytest
from tests.integration.test_preparation_current_assurance import _two_sources

from trade_plan_monitor.backtest.preparation_review import (
    CollectionPreparationReviewCommand,
    collection_item_binding,
    frozen_preparation,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore


def _reviewed(tmp_path):
    store, record, _ = _two_sources(tmp_path)
    command = CollectionPreparationReviewCommand(expected_revision=record.revision,
        items=tuple(collection_item_binding(item) for item in record.items), confirmed=True,
        evidence="Explicit current review of the complete synthetic source/input chain.",
        account=None)
    # This fixture's opening cash is supplied explicitly, independently of source coverage.
    from tests.integration.test_plan_preparation_review import collection_review_command

    command = command.model_copy(update={"account": collection_review_command(record).account})
    reviewed = store.review_and_freeze(record.preparation_id, command=command,
                                      idempotency_key="run-fence-review")
    return store, reviewed, frozen_preparation(reviewed)


def _fence(store, preparation_id, manifest_hash):
    module = importlib.import_module("trade_plan_monitor.backtest.preparation_run_fence")
    return module.current_prepared_run_fence(store, preparation_id, manifest_hash)


def _rows(store):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("backtest_preparation", "backtest_preparation_idempotency",
                          "backtest_preparation_assurance",
                          "backtest_preparation_assurance_metadata")}


def test_fence_freshly_checks_actual_inputs_and_review_in_one_held_writer_transaction(
    tmp_path, monkeypatch,
):
    store, record, frozen = _reviewed(tmp_path)
    before, actual_connect, traces, held = _rows(store), store._connect, [], []

    @contextmanager
    def tracked():
        with actual_connect() as connection:
            held.append(connection)
            connection.set_trace_callback(traces.append)
            yield connection

    monkeypatch.setattr(store, "_connect", tracked)
    with _fence(store, record.preparation_id, frozen.manifest_hash) as current:
        assert current == frozen and held[-1].in_transaction
        assert traces[0] == "BEGIN IMMEDIATE"
        assert any("backtest_preparation_assurance" in sql and "SELECT" in sql for sql in traces)
        assert any("backtest_preparation_idempotency" in sql and "SELECT" in sql for sql in traces)
    assert _rows(store) == before
    assert not any(sql.upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                   for sql in traces)


def test_another_source_writer_cannot_commit_until_the_run_fence_is_released(tmp_path):
    store, record, frozen = _reviewed(tmp_path)
    other = PreparationStore(store.database_path, busy_timeout_ms=40)
    source = record.items[-1].source.model_copy(update={"text": "A later clarified source."})

    def edit():
        return other.edit_collection(record.preparation_id, expected_revision=record.revision,
            source=source, idempotency_key="edit-after-fence")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with _fence(store, record.preparation_id, frozen.manifest_hash):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                pool.submit(edit).result(timeout=5)
            assert store.get(record.preparation_id) == record
        edited = pool.submit(edit).result(timeout=5)
    assert edited.items[-1].source == source and edited.review is None
    with pytest.raises(PreparationConflictError):
        with _fence(store, record.preparation_id, frozen.manifest_hash):
            pytest.fail("A later source edit cannot reuse the old current review")


def test_fence_exception_releases_writer_reservation_without_business_changes(tmp_path):
    store, record, frozen = _reviewed(tmp_path)
    before = _rows(store)
    with pytest.raises(RuntimeError, match="Caller final admission failed"):
        with _fence(store, record.preparation_id, frozen.manifest_hash):
            raise RuntimeError("Caller final admission failed")
    assert _rows(store) == before
    with _fence(store, record.preparation_id, frozen.manifest_hash) as retry:
        assert retry == frozen


def test_wrong_manifest_does_not_change_or_consume_current_preparation(tmp_path):
    store, record, _ = _reviewed(tmp_path)
    before = _rows(store)
    with pytest.raises(PreparationConflictError) as error:
        with _fence(store, record.preparation_id, "f" * 64):
            pytest.fail("A different manifest cannot enter the current run fence")
    assert error.value.code == "SOURCE_COVERAGE_STALE" and _rows(store) == before


def test_missing_current_review_receipt_blocks_fresh_run_but_history_survives(tmp_path):
    store, record, frozen = _reviewed(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS

        connection.execute("DROP TRIGGER pma_preparation_assurance_delete")
        connection.execute("DELETE FROM backtest_preparation_assurance WHERE kind='REVIEW'")
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_delete"])
    before = _rows(store)
    assert frozen_preparation(store.get(record.preparation_id)) == frozen
    with pytest.raises(PreparationConflictError) as error:
        with _fence(store, record.preparation_id, frozen.manifest_hash):
            pytest.fail("A historical review without current evidence cannot admit a new run")
    assert error.value.code == "SOURCE_COVERAGE_REQUIRED" and _rows(store) == before


def test_missing_preparation_is_a_sanitized_conflict_without_new_rows(tmp_path):
    store, _, _ = _reviewed(tmp_path)
    before = _rows(store)
    with pytest.raises(PreparationConflictError) as error:
        with _fence(store, "missing-preparation", "f" * 64):
            pytest.fail("An absent preparation cannot enter the current run fence")
    assert error.value.code == "PREPARATION_NOT_FOUND" and _rows(store) == before
