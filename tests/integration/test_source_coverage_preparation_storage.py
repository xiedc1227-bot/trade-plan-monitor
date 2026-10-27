"""Preparation raw evidence is durable without changing existing documents or receipts."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.integration.test_source_coverage_storage_adversarial import _private_inputs
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.backtest.preparation_models import PreparationRecord, PreparationSource
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
_PREPARATION = "raw-evidence-preparation"
_ATTEMPT = "raw-evidence-attempt"
_AUX = {"backtest_preparation_assurance_metadata", "backtest_preparation_assurance"}
_GUARDS = {
    "pma_preparation_assurance_update", "pma_preparation_assurance_delete",
    "pma_preparation_assurance_metadata_insert", "pma_preparation_assurance_metadata_update",
    "pma_preparation_assurance_metadata_delete",
}


def _api():
    from trade_plan_monitor.backtest import preparation_assurance_store

    return preparation_assurance_store


def _inputs(*, suffix="\n\t"):
    draft, text, mapping = _baseline()
    source = PreparationSource(source_id="original-source", text=text,
                               available_at=_NOW, effective_trade_date=_NOW.date())
    assessment = assess_source_coverage(draft, mapping, text)
    inputs, _ = _private_inputs(draft, text, assessment, suffix=suffix)
    return _rebind(inputs, source.binding_hash), source


def _rebind(inputs, binding):
    return CoverageInputs.build(
        source_hash=inputs.source_hash, source_binding_hash=binding,
        initial_coverage=inputs.initial_coverage, normalization=inputs.normalization,
        derivation=inputs.derivation, derivation_issues=inputs.derivation_issues,
    )


def _evidence(**updates):
    inputs, _ = _inputs()
    values = {
        "preparation_id": _PREPARATION, "item_index": 0, "attempt_id": _ATTEMPT,
        "source_binding_hash": inputs.source_binding_hash, "candidate_hash": "c" * 64,
        "inputs": inputs, "created_at": _NOW,
    }
    return _api().PreparationInputEvidence.build(**(values | updates))


def _tables(connection):
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def _old_rows(connection):
    return {
        table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        for table in ("backtest_preparation", "backtest_preparation_idempotency")
    }


def _legacy(path, *, version=2):
    _, source = _inputs()
    record = PreparationRecord(
        preparation_id=_PREPARATION, revision=1, source=source, source_revision=1,
        created_at=_NOW, updated_at=_NOW,
    )
    document = " \n" + record.model_dump_json() + "\n\t"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE backtest_preparation_metadata (
                singleton INTEGER PRIMARY KEY, domain TEXT NOT NULL,
                schema_version INTEGER NOT NULL);
            CREATE TABLE backtest_preparation (
                preparation_id TEXT PRIMARY KEY, document_json TEXT NOT NULL);
            CREATE TABLE backtest_preparation_idempotency (
                idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                response_json TEXT NOT NULL);
        """)
        connection.execute("INSERT INTO backtest_preparation_metadata VALUES(1,?,?)",
                           ("backtest-preparation-v1", version))
        connection.execute("INSERT INTO backtest_preparation VALUES(?,?)", (_PREPARATION, document))
        connection.execute("INSERT INTO backtest_preparation_idempotency VALUES(?,?,?)",
                           ("old-exact-intent", "b" * 64, document))
        if version == 2:
            connection.execute("CREATE TABLE backtest_plan_selection "
                               "(selection_id TEXT PRIMARY KEY, document_json TEXT NOT NULL)")
    return record


def test_new_empty_preparation_store_installs_both_auxiliary_tables(tmp_path):
    path = tmp_path / "new-preparation.sqlite3"
    PreparationStore(path)
    with closing(sqlite3.connect(path)) as connection:
        assert _AUX <= _tables(connection)
        count = connection.execute("SELECT count(*) FROM backtest_preparation_assurance").fetchone()
        assert count == (0,)


@pytest.mark.parametrize("version", [1, 2])
def test_opening_old_preparation_never_silently_adds_assurance_tables(tmp_path, version):
    path = tmp_path / "old-preparation.sqlite3"
    expected = _legacy(path, version=version)
    with closing(sqlite3.connect(path)) as connection:
        before = _old_rows(connection)

    assert PreparationStore(path).get(_PREPARATION) == expected

    with closing(sqlite3.connect(path)) as connection:
        assert not (_AUX & _tables(connection))
        assert _old_rows(connection) == before


@pytest.mark.parametrize("version", [1, 2])
def test_old_assurance_read_is_absent_and_does_not_create_or_rewrite_anything(tmp_path, version):
    path = tmp_path / "old-read.sqlite3"
    _legacy(path, version=version)
    with closing(sqlite3.connect(path)) as connection:
        tables, old = _tables(connection), _old_rows(connection)
        changed = connection.total_changes

        assert _api().input_evidence(connection, _PREPARATION, _ATTEMPT) is None

        assert connection.total_changes == changed
        assert _tables(connection) == tables
        assert _old_rows(connection) == old


def test_old_store_write_requires_explicit_assurance_upgrade(tmp_path):
    path = tmp_path / "old-write.sqlite3"
    _legacy(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(PreparationConflictError) as error:
            _api().save_input_evidence(connection, _evidence())
        assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert not (_AUX & _tables(connection))


@pytest.mark.parametrize("version", [1, 2])
def test_explicit_upgrade_preserves_exact_legacy_documents_and_receipts(tmp_path, version):
    path = tmp_path / "explicit-upgrade.sqlite3"
    expected = _legacy(path, version=version)
    # Preserve the pre-existing v1-to-v2 selection-table upgrade separately from assurance.
    PreparationStore(path)
    with closing(sqlite3.connect(path)) as connection:
        before = _old_rows(connection)

    _api().upgrade_preparation_assurance(path)

    with closing(sqlite3.connect(path)) as connection:
        assert _AUX <= _tables(connection)
        assert _old_rows(connection) == before
    assert PreparationStore(path).get(_PREPARATION) == expected
    # An exact second explicit upgrade is harmless and does not rewrite old data.
    _api().upgrade_preparation_assurance(path)
    with closing(sqlite3.connect(path)) as connection:
        assert _old_rows(connection) == before


def test_auxiliary_evidence_survives_reopen_with_exact_raw_and_normalization_bytes(tmp_path):
    path = tmp_path / "roundtrip.sqlite3"
    PreparationStore(path)
    api, evidence = _api(), _evidence()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        assert api.save_input_evidence(connection, evidence) == evidence
    PreparationStore(path)
    with closing(sqlite3.connect(path)) as connection:
        loaded = api.input_evidence(connection, _PREPARATION, _ATTEMPT)
        assert loaded == evidence
        assert loaded.inputs.derivation.raw_json == evidence.inputs.derivation.raw_json
        assert loaded.inputs.normalization.changes == evidence.inputs.normalization.changes
        assert loaded.inputs.evidence_hash == evidence.inputs.evidence_hash
        assert loaded.inputs.derivation.raw_json.endswith("\n\t")


def test_retry_ignores_new_timestamp_but_preserves_the_original_evidence(tmp_path):
    path = tmp_path / "retry.sqlite3"
    PreparationStore(path)
    api, original = _api(), _evidence()
    later = _evidence(created_at=_NOW + timedelta(hours=1))
    assert original.evidence_key == later.evidence_key
    assert original.evidence_hash != later.evidence_hash
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        assert api.save_input_evidence(connection, original) == original
        assert api.save_input_evidence(connection, later) == original
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT).created_at == _NOW


@pytest.mark.parametrize("mutation", ["raw-bytes", "candidate", "item-index"])
def test_same_attempt_rejects_changed_private_intent(tmp_path, mutation):
    path = tmp_path / "conflict.sqlite3"
    PreparationStore(path)
    api, original = _api(), _evidence()
    if mutation == "raw-bytes":
        inputs, _ = _inputs(suffix="\n")
        changed = _evidence(inputs=inputs)
        assert json.loads(original.inputs.derivation.raw_json) == json.loads(
            changed.inputs.derivation.raw_json)
    else:
        changed = _evidence(**({"candidate_hash": "d" * 64} if mutation == "candidate"
                               else {"item_index": 1}))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        api.save_input_evidence(connection, original)
        with pytest.raises(PreparationConflictError):
            api.save_input_evidence(connection, changed)
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) == original


@pytest.mark.parametrize("binding", [None, "f" * 64])
def test_input_source_binding_must_match_the_outer_attempt_binding(binding):
    inputs, _ = _inputs()
    different = _rebind(inputs, binding)
    with pytest.raises(ValueError):
        _evidence(inputs=different)


def test_evidence_key_is_identity_only_while_full_selfhash_covers_private_input():
    first = _evidence()
    private, _ = _inputs(suffix="\n")
    changed = _evidence(inputs=private)
    assert first.version == "preparation-input-evidence-v1"
    assert first.evidence_key == changed.evidence_key
    assert first.evidence_hash != changed.evidence_hash
    assert first.evidence_hash == daily_hash(first.version, first.model_dump(
        mode="json", exclude={"evidence_hash"}))
    tampered = first.model_dump(mode="json")
    tampered["candidate_hash"] = "f" * 64
    with pytest.raises(ValueError):
        type(first).model_validate(tampered)


def test_save_joins_the_callers_transaction_and_never_commits_it(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    PreparationStore(path)
    api, evidence = _api(), _evidence()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        api.save_input_evidence(connection, evidence)
        assert connection.in_transaction is True
        connection.rollback()
    with closing(sqlite3.connect(path)) as connection:
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) is None


def test_native_backup_preserves_private_evidence_exactly(tmp_path):
    path, backup_path = tmp_path / "original.sqlite3", tmp_path / "backup.sqlite3"
    PreparationStore(path)
    api, evidence = _api(), _evidence()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        api.save_input_evidence(connection, evidence)
    with (closing(sqlite3.connect(path)) as original,
          closing(sqlite3.connect(backup_path)) as backup):
        original.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    PreparationStore(backup_path)
    with closing(sqlite3.connect(backup_path)) as connection:
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) == evidence


def test_present_assurance_reads_do_not_write_or_change_the_schema(tmp_path):
    path = tmp_path / "read-only.sqlite3"
    PreparationStore(path)
    api, evidence = _api(), _evidence()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        api.save_input_evidence(connection, evidence)
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        schema = connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) == evidence
        assert connection.total_changes == 0
        after = connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert after == schema


def test_five_immutable_guards_are_installed_and_the_export_is_read_only(tmp_path):
    path = tmp_path / "guard-inventory.sqlite3"
    PreparationStore(path)
    api = _api()
    assert set(api.ASSURANCE_TRIGGERS) == _GUARDS
    with pytest.raises(TypeError):
        api.ASSURANCE_TRIGGERS["not-a-registered-guard"] = "SELECT 1"
    with closing(sqlite3.connect(path)) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'pma_preparation_assurance_%'"
        )}
        assert names == _GUARDS


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_ordinary_sql_cannot_modify_or_delete_raw_evidence(tmp_path, operation):
    path = tmp_path / "immutable-raw.sqlite3"
    PreparationStore(path)
    api, evidence = _api(), _evidence()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        api.save_input_evidence(connection, evidence)
    with closing(sqlite3.connect(path)) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE backtest_preparation_assurance SET evidence_hash=evidence_hash" if
                operation == "UPDATE" else "DELETE FROM backtest_preparation_assurance"
            )
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) == evidence


@pytest.mark.parametrize("guard", sorted(_GUARDS))
def test_missing_immutable_guard_is_explicit_sanitized_integrity_failure(tmp_path, guard):
    path = tmp_path / "missing-guard.sqlite3"
    PreparationStore(path)
    api = _api()
    assert guard in _GUARDS
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f"DROP TRIGGER {guard}")
        with pytest.raises(PreparationConflictError) as error:
            api.input_evidence(connection, _PREPARATION, _ATTEMPT)
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"


def test_same_named_but_changed_guard_never_restores_trust(tmp_path):
    path = tmp_path / "changed-guard.sqlite3"
    PreparationStore(path)
    api = _api()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute(
            "CREATE TRIGGER pma_preparation_assurance_update "
            "BEFORE UPDATE ON backtest_preparation_assurance "
            "BEGIN SELECT 'SECRET_BROKEN_GUARD'; END"
        )
        with pytest.raises(PreparationConflictError) as error:
            api.input_evidence(connection, _PREPARATION, _ATTEMPT)
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        assert "SECRET_BROKEN_GUARD" not in str(error.value)


@pytest.mark.parametrize("table", sorted(_AUX))
def test_partially_missing_auxiliary_schema_is_corruption_not_an_old_absent_proof(tmp_path, table):
    path = tmp_path / "partial-aux.sqlite3"
    PreparationStore(path)
    api = _api()
    assert table in _AUX
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f"DROP TABLE {table}")
        with pytest.raises(PreparationConflictError) as error:
            api.input_evidence(connection, _PREPARATION, _ATTEMPT)
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("foreign", [False, True], ids=["empty-sqlite", "foreign-domain"])
def test_explicit_upgrade_refuses_an_untagged_database_without_adding_tables(tmp_path, foreign):
    path = tmp_path / "wrong-domain.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        if foreign:
            connection.execute("CREATE TABLE foreign_domain(id INTEGER)")
        before = _tables(connection)
    with pytest.raises(ValueError):
        _api().upgrade_preparation_assurance(path)
    with closing(sqlite3.connect(path)) as connection:
        assert _tables(connection) == before


def test_old_document_change_and_private_input_rollback_together(tmp_path):
    path = tmp_path / "combined-rollback.sqlite3"
    _legacy(path)
    api, evidence = _api(), _evidence()
    api.upgrade_preparation_assurance(path)
    with closing(sqlite3.connect(path)) as connection:
        before = _old_rows(connection)
    with pytest.raises(RuntimeError, match="simulated caller failure"):
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE backtest_preparation SET document_json=document_json || ' ' "
                "WHERE preparation_id=?", (_PREPARATION,),
            )
            api.save_input_evidence(connection, evidence)
            assert connection.in_transaction
            raise RuntimeError("simulated caller failure")
    with closing(sqlite3.connect(path)) as connection:
        assert _old_rows(connection) == before
        assert api.input_evidence(connection, _PREPARATION, _ATTEMPT) is None
