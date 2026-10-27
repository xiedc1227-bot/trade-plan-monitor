"""A real SQL review cannot remain current through a later transaction's old cache."""

import sqlite3
from contextlib import closing

import pytest
from tests.integration.test_preparation_lineage_authority import _NOW, _root

from trade_plan_monitor.backtest import preparation_current_assurance as current
from trade_plan_monitor.backtest.preparation_lineage_authority import CurrentAssuranceContext
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore


def test_a_committed_transaction_cache_cannot_resurrect_a_missing_actual_review_command(tmp_path):
    store = PreparationStore(tmp_path / "transaction-cache.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    context = CurrentAssuranceContext()
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN")
        receipt = current.require_current_reviewed_preparation(connection, root, _context=context)
        assert receipt.proofs[0].coverage_complete
        connection.commit()

        connection.execute("DELETE FROM backtest_preparation_idempotency WHERE idempotency_key=?",
                           ("review-" + root.preparation_id,))
        connection.commit()
        assert PreparationStore._read(connection, root.preparation_id) == root
        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
            current.require_current_reviewed_preparation(connection, root)

        changes = connection.total_changes
        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
            current.require_current_reviewed_preparation(connection, root, _context=context)
        assert connection.total_changes == changes


def test_external_committed_change_invalidates_cache_without_changing_local_total_changes(tmp_path):
    store = PreparationStore(tmp_path / "external-cache.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    context = CurrentAssuranceContext()
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN")
        receipt = current.require_current_reviewed_preparation(connection, root, _context=context)
        assert receipt.proofs[0].coverage_complete
        connection.commit()
        changes = connection.total_changes
        data_version = connection.execute("PRAGMA data_version").fetchone()[0]

        with closing(sqlite3.connect(store.database_path)) as other, other:
            other.execute("DELETE FROM backtest_preparation_idempotency WHERE idempotency_key=?",
                          ("review-" + root.preparation_id,))
        assert connection.total_changes == changes
        assert connection.execute("PRAGMA data_version").fetchone()[0] != data_version
        connection.execute("BEGIN")
        assert connection.in_transaction  # Match the original flag: isolate data_version.
        assert PreparationStore._read(connection, root.preparation_id) == root
        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
            current.require_current_reviewed_preparation(connection, root)

        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
            current.require_current_reviewed_preparation(connection, root, _context=context)
        assert connection.total_changes == changes


def test_same_immediate_transaction_caches_real_verification_without_writes(tmp_path, monkeypatch):
    store = PreparationStore(tmp_path / "stable-cache.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    context = CurrentAssuranceContext()
    original, calls = current._initial, []

    def observe_full_initial(item, evidence):
        calls.append(item.source.source_id)
        return original(item, evidence)  # Transparent observation runs every real check.

    monkeypatch.setattr(current, "_initial", observe_full_initial)
    statements = []
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.set_trace_callback(statements.append)
        changes = connection.total_changes
        receipt = current.require_current_reviewed_preparation(connection, root, _context=context)
        assert calls == [root.items[0].source.source_id]
        assert any("FROM BACKTEST_PREPARATION_ASSURANCE" in sql.upper() for sql in statements)

        statements.clear()
        cached = current.require_current_reviewed_preparation(connection, root, _context=context)
        assert cached is receipt
        assert calls == [root.items[0].source.source_id]
        assert any("FROM BACKTEST_PREPARATION WHERE" in sql.upper() for sql in statements)
        assert not any("FROM BACKTEST_PREPARATION_ASSURANCE" in sql.upper() for sql in statements)

        statements.clear()
        fresh = current.require_current_reviewed_preparation(connection, root,
                                                             _context=CurrentAssuranceContext())
        assert fresh == receipt and calls == [root.items[0].source.source_id] * 2
        assert any("FROM BACKTEST_PREPARATION_ASSURANCE" in sql.upper() for sql in statements)
        assert connection.total_changes == changes
        connection.rollback()
