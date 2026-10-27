"""Current proofs are append-only, exact on retry and independent of old bytes."""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_index_permission_scope_migration import _migrate
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.models import PlanSource, PlanVersion
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageCommandConflict,
    SourceCoverageIntegrityError,
    SourceCoverageStore,
    SourceCoverageUpgradeRequired,
)
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
VERSION = "00000000-0000-0000-0000-000000000001"
SOURCE = "00000000-0000-0000-0000-000000000002"


def _damage_seal(connection, table, operation):
    connection.exec_driver_sql(f"DROP TRIGGER pma_seal_{table}_{operation}")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "coverage.sqlite3"
    engine = create_sqlite_engine(path)
    _migrate(engine, "head")
    draft, source, mapping = _baseline()
    assessment = assess_source_coverage(draft, mapping, source)
    with Session(engine) as session, session.begin():
        session.add(PlanSource(id=SOURCE, source_text=source, source_hash=scope_hash(source),
                               created_at=NOW.isoformat()))
        session.flush()
        session.add(PlanVersion(id=VERSION, plan_id=draft.plan_id, version=draft.version,
            symbol=draft.symbol, plan_hash=daily_draft_sha256(draft), status="DRAFT",
            payload_json=daily_draft_json(draft), source_id=SOURCE, revision=0,
            created_at=NOW.isoformat()))
    yield engine, path, assessment, draft, source
    engine.dispose()


def append(store, assessment, *, revision=0, command="coverage-command", inputs=None):
    return store.append(VERSION, assessment, inputs=inputs, expected_revision=revision,
                        command_id=command, now=NOW)


def test_reopen_replay_stale_revision_and_changed_intent(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        assert store.cutover(VERSION) is None
        assert store.latest(VERSION) is None
        first = append(store, assessment)
        second = append(store, assessment, revision=1, command="reassess")
        assert second.revision == 2
        assert second.before_hash == first.evidence_hash
        assert append(store, assessment) == first
        with pytest.raises(SourceCoverageCommandConflict):
            append(store, assessment, revision=1)
        with pytest.raises(RevisionConflictError):
            append(store, assessment, command="stale")
    with Session(engine) as session:
        store = SourceCoverageStore(session)
        assert store.latest(VERSION) == second
        assert store.command("coverage-command") == first


def test_proof_write_rolls_back_with_owning_transaction(database):
    engine, _, assessment, _, _ = database
    with pytest.raises(RuntimeError, match="fault"):
        with Session(engine) as session, session.begin():
            append(SourceCoverageStore(session), assessment)
            raise RuntimeError("fault after proof")
    with Session(engine) as session:
        assert SourceCoverageStore(session).latest(VERSION) is None


def test_private_input_retry_compares_excluded_evidence(database):
    engine, _, _, draft, source = database
    raw = draft.model_dump(mode="json")
    trace = capture_normalization(raw, raw, source, reason="TEST_IDENTITY")
    inputs = CoverageInputs.build(source_hash=scope_hash(source), normalization=trace)
    altered = CoverageInputs.build(source_hash=scope_hash(source))
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        assert store.save_input(VERSION, inputs) == inputs
        assert store.save_input(VERSION, inputs) == inputs
        with pytest.raises(SourceCoverageCommandConflict):
            store.save_input(VERSION, altered)
    with Session(engine) as session:
        assert SourceCoverageStore(session).input(VERSION) == inputs


@pytest.mark.parametrize("column,value", [
    ("evidence_hash", "a" * 64), ("request_hash", "b" * 64),
    ("created_at", "2001-01-01T00:00:00+08:00"),
    ("payload_json", '{"secret":"never echo this raw stored content"}'),
])
def test_stored_tampering_is_sanitized(database, column, value):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        append(SourceCoverageStore(session), assessment)
    with engine.begin() as connection:
        _damage_seal(connection, "source_coverage_assessment", "update")
        connection.execute(text(f"UPDATE source_coverage_assessment SET {column}=:value"),
                           {"value": value})
    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError) as error:
        SourceCoverageStore(session).latest(VERSION)
    assert str(error.value) == "Stored source coverage evidence is invalid"
    assert "secret" not in str(error.value)


def test_input_or_source_mismatch_is_not_persisted(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        with pytest.raises(ValueError, match="source"):
            append(SourceCoverageStore(session), assessment,
                   inputs=CoverageInputs.build(source_hash="f" * 64))
    with engine.begin() as connection:
        connection.execute(text("UPDATE plan_source SET source_hash=:hash"), {"hash": "e" * 64})
    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError):
        append(SourceCoverageStore(session), assessment)


def test_native_backup_preserves_proof_and_inputs_exactly(database, tmp_path):
    engine, path, assessment, _, source = database
    inputs = CoverageInputs.build(source_hash=scope_hash(source))
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        store.save_input(VERSION, inputs)
        expected = append(store, assessment, inputs=inputs)
    target = tmp_path / "backup.sqlite3"
    with sqlite3.connect(path) as original, sqlite3.connect(target) as backup:
        original.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    copied = create_sqlite_engine(target)
    try:
        with Session(copied) as session:
            assert SourceCoverageStore(session).latest(VERSION) == expected
            assert SourceCoverageStore(session).input(VERSION) == inputs
    finally:
        copied.dispose()


def test_absent_migration_and_marker_never_create_authority(tmp_path):
    engine = create_sqlite_engine(tmp_path / "old.sqlite3")
    try:
        _migrate(engine, "0027_simulation_capital")
        with Session(engine) as session, pytest.raises(SourceCoverageUpgradeRequired):
            SourceCoverageStore(session).latest(VERSION)
        _migrate(engine, "head")
        with engine.begin() as connection:
            _damage_seal(connection, "source_coverage_installation", "delete")
            connection.execute(text("DELETE FROM source_coverage_installation"))
        with Session(engine) as session, pytest.raises(SourceCoverageUpgradeRequired):
            SourceCoverageStore(session).latest(VERSION)
    finally:
        engine.dispose()


def test_missing_history_revision_is_detected(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        append(store, assessment)
        append(store, assessment, revision=1, command="second")
    with engine.begin() as connection:
        _damage_seal(connection, "source_coverage_assessment", "delete")
        connection.execute(text("DELETE FROM source_coverage_assessment WHERE revision=1"))
    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError):
        SourceCoverageStore(session).latest(VERSION)


def test_old_plan_bytes_are_unchanged_by_current_assessment(database):
    engine, _, assessment, _, _ = database
    with engine.connect() as connection:
        before = tuple(connection.execute(text("SELECT * FROM plan_version")).one())
    with Session(engine) as session, session.begin():
        append(SourceCoverageStore(session), assessment)
    with engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT * FROM plan_version")).one()) == before
        payload = connection.execute(text(
            "SELECT payload_json FROM source_coverage_assessment",
        )).scalar()
        assert json.loads(payload)["authority_granted"] is False


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_normal_sql_cannot_rewrite_or_delete_coverage_history(database, operation):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        expected = append(SourceCoverageStore(session), assessment)
    query = ("DELETE FROM source_coverage_assessment" if operation == "delete" else
             "UPDATE source_coverage_assessment SET command_id='changed'")
    with pytest.raises(IntegrityError, match="immutable"):
        with engine.begin() as connection:
            connection.exec_driver_sql(query)
    with Session(engine) as session:
        assert SourceCoverageStore(session).latest(VERSION) == expected


def test_removing_a_guard_is_integrity_failure_even_before_rows_change(database):
    engine, _, _, _, _ = database
    with engine.begin() as connection:
        _damage_seal(connection, "source_coverage_cutover", "insert")
    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError):
        SourceCoverageStore(session).installation()
