"""Current review guards preserve trusted-corruption and resource-limit categories."""

import sqlite3
from contextlib import closing

import pytest
from tests.integration.test_preparation_current_assurance import _command, _ready, _rows
from tests.integration.test_preparation_current_review import _require, _reviewed

from trade_plan_monitor.backtest import preparation_current_assurance as current
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError


def test_malformed_original_server_response_is_integrity_failure_not_a_stale_user_selection(
    tmp_path,
):
    store, _, reviewed = _reviewed(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("UPDATE backtest_preparation_idempotency SET response_json=? "
                           "WHERE idempotency_key='current-human-review'", ("{invalid",))

    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)

    assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
    assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("kind", ["explicit_limit", "recursion"])
def test_current_reviewed_manifest_limit_is_explicit_and_the_read_remains_pure(
    tmp_path, monkeypatch, kind,
):
    store, _, reviewed = _reviewed(tmp_path)

    def limit(record):
        if kind == "recursion":
            raise RecursionError("Synthetic bounded manifest depth")
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")

    monkeypatch.setattr(current, "_manifest", limit)
    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)

    assert error.value.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"


def test_post_review_scope_resource_limit_keeps_its_category_and_rolls_back_all_writes(
    tmp_path, monkeypatch,
):
    store, record, _, _, _ = _ready(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)
    actual = current._single
    calls = []

    def second_phase_limit(connection, candidate):
        calls.append(candidate.status)
        if candidate.status == "REVIEWED":
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        return actual(connection, candidate)

    monkeypatch.setattr(current, "_single", second_phase_limit)
    with pytest.raises(PreparationConflictError) as error:
        store.review_and_freeze(record.preparation_id, command=_command(record),
                                idempotency_key="post-phase-resource-limit")

    assert calls == ["CANDIDATE", "REVIEWED"]
    assert error.value.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"
    assert store.get(record.preparation_id) == record
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before
