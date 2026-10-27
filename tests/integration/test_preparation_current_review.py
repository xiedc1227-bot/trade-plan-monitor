"""Complete source evidence does not substitute for an atomic current human review."""

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from tests.integration.test_preparation_current_assurance import (
    _command,
    _historical_review_receipt,
    _ready,
    _rows,
)

from trade_plan_monitor.backtest import preparation_current_assurance as current
from trade_plan_monitor.backtest import preparation_review_assurance_store as receipts
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_review_assurance_models import (
    PreparationReviewAssurance,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash


def _reviewed(tmp_path):
    store, before, _, _, _ = _ready(tmp_path)
    command = _command(before)
    reviewed = store.review_and_freeze(before.preparation_id, command=command,
                                      idempotency_key="current-human-review")
    return store, before, reviewed


def _require(store, record):
    with closing(sqlite3.connect(store.database_path)) as connection:
        before, changes = _rows(connection), connection.total_changes
        try:
            return current.require_current_reviewed_preparation(connection, record)
        finally:
            assert connection.total_changes == changes and _rows(connection) == before


def test_old_human_review_with_complete_current_inputs_does_not_create_a_current_receipt(tmp_path):
    store, candidate, _, _, _ = _ready(tmp_path)
    _, reviewed, _ = _historical_review_receipt(store, candidate)
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert current.require_current_preparation(connection, reviewed)
    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)
    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"
    assert frozen_preparation(reviewed)


def test_new_review_atomically_binds_actual_historical_review_manifest_and_all_source_proofs(
    tmp_path,
):
    store, before, reviewed = _reviewed(tmp_path)
    receipt = _require(store, reviewed)
    assert receipt.preparation_id == reviewed.preparation_id
    assert receipt.previous_revision == before.revision
    assert receipt.reviewed_revision == reviewed.revision
    assert receipt.review_revision == reviewed.review_revision
    assert receipt.command_id == "current-human-review"
    assert receipt.original_review_hash == daily_hash(
        "preparation-original-review-v1", reviewed.review.model_dump(mode="json"))
    assert receipt.frozen_manifest_hash == frozen_preparation(reviewed).manifest_hash
    assert receipt.authority_granted is False
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert receipt.proofs == current.require_current_preparation(connection, reviewed)
        rows = connection.execute("SELECT kind,attempt_id FROM backtest_preparation_assurance "
                                  "ORDER BY kind").fetchall()
        assert rows == [("INPUT", before.attempts[-1].attempt_id),
                        ("REVIEW", f"review-{reviewed.review_revision}")]


def test_failed_current_receipt_write_rolls_back_old_review_and_both_receipts(
    tmp_path, monkeypatch,
):
    store, record, _, _, _ = _ready(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)
    actual_save = receipts.save_review_assurance

    def fail_after_write(connection, receipt):
        assert connection.in_transaction
        assert actual_save(connection, receipt) == receipt
        raise RuntimeError("Synthetic current receipt write failure")

    monkeypatch.setattr(receipts, "save_review_assurance", fail_after_write)
    with pytest.raises(RuntimeError, match="Synthetic current receipt write failure"):
        store.review_and_freeze(record.preparation_id, command=_command(record),
                                idempotency_key="current-human-review")
    assert store.get(record.preparation_id) == record
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before
    monkeypatch.setattr(receipts, "save_review_assurance", actual_save)
    reviewed = store.review_and_freeze(record.preparation_id, command=_command(record),
                                      idempotency_key="current-human-review")
    assert _require(store, reviewed).proofs


@pytest.mark.parametrize("field", [
    "original_review_hash", "frozen_manifest_hash", "command_request_hash", "created_at",
])
def test_a_self_consistent_receipt_cannot_substitute_the_actual_review_or_command(tmp_path, field):
    store, _, reviewed = _reviewed(tmp_path)
    receipt = _require(store, reviewed)
    values = {name: getattr(receipt, name) for name in type(receipt).model_fields
              if name not in {"evidence_key", "evidence_hash"}}
    changed = receipt.created_at + timedelta(seconds=1) if field == "created_at" else "f" * 64
    replacement = PreparationReviewAssurance.build(**(values | {field: changed}))
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute("UPDATE backtest_preparation_assurance "
            "SET payload_json=?,evidence_hash=?,created_at=? "
            "WHERE evidence_key=?", (canonical(replacement.model_dump(mode="json")),
                                     replacement.evidence_hash, replacement.created_at.isoformat(),
                                     replacement.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)
    assert error.value.code == "SOURCE_COVERAGE_STALE"


def test_current_review_requires_the_original_server_idempotency_receipt(tmp_path):
    store, _, reviewed = _reviewed(tmp_path)
    assert _require(store, reviewed)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DELETE FROM backtest_preparation_idempotency "
                           "WHERE idempotency_key='current-human-review'")
    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)
    assert error.value.code == "SOURCE_COVERAGE_STALE"


@pytest.mark.parametrize("stage", ["source", "review"])
def test_source_and_receipt_resource_limits_are_explicit_and_roll_back(
    tmp_path, monkeypatch, stage,
):
    store, record, _, _, _ = _ready(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)

    def limit(*args, **kwargs):
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")

    if stage == "source":
        monkeypatch.setattr(current, "assess_initial_current", limit)
    else:
        monkeypatch.setattr(PreparationReviewAssurance, "build", limit)
    with pytest.raises(PreparationConflictError) as error:
        store.review_and_freeze(record.preparation_id, command=_command(record),
                                idempotency_key="current-resource-limit")
    assert error.value.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"
    assert store.get(record.preparation_id) == record
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before
