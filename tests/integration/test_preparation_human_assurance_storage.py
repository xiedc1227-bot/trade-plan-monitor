"""Human-operation integrity uses the sealed sidecar without inventing provider input."""

import importlib
import json
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from tests.integration.test_preparation_current_assurance import _command, _ready, _two_sources
from tests.integration.test_source_coverage_preparation_commit import _NOW
from tests.integration.test_source_coverage_preparation_storage import _legacy
from tests.unit.test_source_coverage_treatments import _supplemented_maximum

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.update_review import MaterializedUpdateCandidate, build_initial_review
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationCandidate,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    collection_item_binding,
    prepare_frozen_plan,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash


def _models():
    return importlib.import_module("trade_plan_monitor.backtest.preparation_human_assurance_models")


def _api():
    return importlib.import_module("trade_plan_monitor.backtest.preparation_human_assurance_store")


def _values(tmp_path, *, missing=False):
    store, record, original, inputs, mapping = _ready(tmp_path, with_inputs=not missing)
    draft = original.draft.model_copy(update={"name": "Explicit human display correction"})
    command = _command(record).model_copy(update={"draft": draft, "mapping": mapping})
    review = build_initial_review(draft, mapping, record.source)
    manifest = prepare_frozen_plan(record, command, _NOW)
    after = PreparationCandidate(payload_json=canonical_json(manifest), validation="VALID",
        evidence_hash=manifest.version.evidence_hash, source_revision=record.source_revision,
        source_hash=record.source.binding_hash)
    captured = store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id)
    binding = CandidateBinding(preparation_id=record.preparation_id, item_index=0,
        source_id=record.source.source_id, source_revision=record.source_revision,
        source_binding_hash=record.source.binding_hash,
        candidate_revision=record.candidate_revision,
        candidate_hash=record.candidate.candidate_hash,
        review_evidence_hash=review.evidence_hash, attempt_id=record.attempts[-1].attempt_id,
        inputs_hash=None if missing else inputs.evidence_hash, independent=False)
    values = dict(preparation_id=record.preparation_id, item_index=0,
        operation="REVIEW_AND_FREEZE", source=record.source, source_revision=record.source_revision,
        before_revision=record.revision, after_revision=record.revision + 1,
        before_candidate_revision=record.candidate_revision,
        before_candidate_hash=record.candidate.candidate_hash,
        before_evidence_hash=record.candidate.evidence_hash,
        after_candidate_revision=record.candidate_revision + 1,
        after_candidate_hash=after.candidate_hash, after_evidence_hash=after.evidence_hash,
        attempt_id=record.attempts[-1].attempt_id,
        original_input_state="MISSING" if missing else "PRESENT",
        original_input_key=None if missing else captured.evidence_key,
        original_input_hash=None if missing else captured.evidence_hash,
        original_candidate=record.candidate,
        original_candidate_revision=record.candidate_revision,
        command_json=canonical_json(command), resolved_draft=draft, resolved_mapping=mapping,
        resolved_update=None, resolved_review=review, assessment_binding=binding,
        prefix=(), prefix_hash=source_prefix_hash((), binding), parent_hash=None,
        independent=False, final_frozen_hash=manifest.manifest_hash, previous_human_ref=None,
        created_at=_NOW)
    return store, values


def _operation(tmp_path, **updates):
    store, values = _values(tmp_path)
    return store, _models().PreparationHumanOperation.build(**(values | updates))


def _save(store, value):
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        return _api().save_human_operation(connection, value)


def _read(store, value):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return _api().human_operation(connection, value.preparation_id,
            value.item_index, value.after_candidate_revision)


def _rows(connection):
    return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("backtest_preparation", "backtest_preparation_idempotency",
                          "backtest_preparation_assurance")}


def test_existing_actual_fixture_and_registered_null_supplement_have_full_source_shapes(tmp_path):
    store, values = _values(tmp_path)
    record = store.get(values["preparation_id"])
    assert values["original_candidate"] == record.candidate
    assert values["resolved_mapping"].clauses[-1].semantic_role == "HISTORICAL"
    assert values["original_candidate"].source_hash == values["source"].binding_hash
    draft, source, mapping, span = _supplemented_maximum()
    assert source[slice(*span)] == "position.max_qty = null"
    assert mapping.supplements[0].value == draft.position.max_qty == 300


def test_model_identity_full_selfhash_kind_local_slot_and_no_authority(tmp_path):
    store, value = _operation(tmp_path)
    assert value.version == "preparation-human-operation-v1"
    assert value.kind == "HUMAN_OPERATION" and value.authority_granted is False
    assert value.slot == f"human-0-{value.after_candidate_revision}"
    assert value.attempt_id != value.slot
    assert value.evidence_key == _models().human_operation_key(
        value.preparation_id, value.item_index, value.after_candidate_revision)
    assert value.evidence_hash == daily_hash(value.version,
        value.model_dump(mode="json", exclude={"evidence_hash"}))
    assert value.original_candidate == store.get(value.preparation_id).candidate
    assert value.resolved_review.draft == value.resolved_draft
    with pytest.raises(ValueError):
        type(value).model_validate(value.model_dump(mode="json") | {"authority_granted": True})


@pytest.mark.parametrize("field", ["after_revision", "after_candidate_revision"])
def test_model_requires_exactly_one_revision_advance(tmp_path, field):
    _, values = _values(tmp_path)
    with pytest.raises(ValueError):
        _models().PreparationHumanOperation.build(**(values | {field: values[field] + 1}))


@pytest.mark.parametrize("mutation", ["command-whitespace", "false-confirmation", "wrong-command"])
def test_command_is_canonical_existing_typed_explicit_human_intent(tmp_path, mutation):
    _, values = _values(tmp_path)
    command = json.loads(values["command_json"])
    if mutation == "false-confirmation":
        command["confirmed"] = False
    elif mutation == "wrong-command":
        command["unregistered_flag"] = "ignore unknown conditions"
    value = ("\n" + values["command_json"] if mutation == "command-whitespace"
             else canonical(command))
    with pytest.raises(ValueError):
        _models().PreparationHumanOperation.build(**(values | {"command_json": value}))


def test_registered_null_supplement_is_preserved_as_human_mapping_not_provider_evidence(tmp_path):
    _, values = _values(tmp_path, missing=True)
    draft, text, mapping, _ = _supplemented_maximum()
    source = PreparationSource(source_id="missing-raw-human-source", text=text,
        available_at=_NOW, effective_trade_date=_NOW.date())
    original = values["original_candidate"].model_copy(update={"source_hash": source.binding_hash})
    review = build_initial_review(draft, mapping, source)
    binding = values["assessment_binding"].model_copy(update=dict(source_id=source.source_id,
        source_binding_hash=source.binding_hash, candidate_hash=original.candidate_hash,
        review_evidence_hash=review.evidence_hash))
    value = _models().PreparationHumanOperation.build(**(values | dict(source=source,
        original_candidate=original, before_candidate_hash=original.candidate_hash,
        resolved_draft=draft, resolved_mapping=mapping, resolved_review=review,
        assessment_binding=binding, prefix_hash=source_prefix_hash((), binding))))
    assert value.original_input_state == "MISSING"
    assert value.original_input_key is value.original_input_hash is None
    assert value.resolved_mapping.supplements == mapping.supplements
    assert value.resolved_review.bindings and value.authority_granted is False
    assert "normalization" not in type(value).model_fields
    assert "derivation" not in type(value).model_fields


def test_delta_keeps_proposed_current_namespace_distinct_from_materialized_review(tmp_path):
    store, record, inputs = _two_sources(tmp_path)
    current = importlib.import_module("trade_plan_monitor.backtest.preparation_current_assurance")
    with closing(sqlite3.connect(store.database_path)) as connection:
        parent, _ = current.read_current_assurance(connection, record)
    item = record.items[1]
    original = MaterializedUpdateCandidate.model_validate_json(item.candidate.payload_json)
    output, reviewed = original.extraction.output, original.review
    mapping = output.review(item.source.text).mapping
    assert output.draft != reviewed.draft
    after = CollectionPreparationCandidate(**reviewed.to_preparation_candidate().model_dump(),
        source_revision=item.source_revision, source_hash=item.source.binding_hash,
        base_hash=item.base_hash)
    command = CollectionItemCorrectionCommand(expected_revision=record.revision,
        binding=collection_item_binding(item), confirmed=True,
        evidence="Explicit synthetic change review with a complete current source mapping.",
        update=output, mapping=mapping)
    binding = CandidateBinding(preparation_id=record.preparation_id, item_index=1,
        source_id=item.source.source_id, source_revision=item.source_revision,
        source_binding_hash=item.source.binding_hash,
        candidate_revision=item.candidate_revision + 1, candidate_hash=after.candidate_hash,
        review_evidence_hash=reviewed.evidence_hash, attempt_id=item.attempts[-1].attempt_id,
        inputs_hash=inputs[1].evidence_hash, independent=False)
    prefix = (PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash),)
    captured = store.input_evidence(record.preparation_id, item.attempts[-1].attempt_id)

    value = _models().PreparationHumanOperation.build(preparation_id=record.preparation_id,
        item_index=1, operation="CORRECT_ITEM", source=item.source,
        source_revision=item.source_revision, before_revision=record.revision,
        after_revision=record.revision + 1, before_candidate_revision=item.candidate_revision,
        before_candidate_hash=item.candidate.candidate_hash,
        before_evidence_hash=item.candidate.evidence_hash,
        after_candidate_revision=item.candidate_revision + 1,
        after_candidate_hash=after.candidate_hash, after_evidence_hash=after.evidence_hash,
        attempt_id=item.attempts[-1].attempt_id, original_input_state="PRESENT",
        original_input_key=captured.evidence_key, original_input_hash=captured.evidence_hash,
        original_candidate=item.candidate, original_candidate_revision=item.candidate_revision,
        command_json=canonical_json(command), resolved_draft=output.draft,
        resolved_mapping=mapping, resolved_update=output, resolved_review=reviewed,
        assessment_binding=binding, prefix=prefix, prefix_hash=source_prefix_hash(prefix, binding),
        parent_hash=parent.evidence_hash, independent=False, created_at=_NOW)

    assert value.resolved_draft == value.resolved_update.draft
    assert value.resolved_draft != value.resolved_review.draft
    assert _save(store, value) == _read(store, value) == value


def test_full_model_byte_bound_is_exact_and_never_truncates_the_operation(tmp_path, monkeypatch):
    _, value = _operation(tmp_path)
    module = _models()
    assert module.MAX_PROOF_BYTES == 8 * 1024 * 1024
    payload = canonical(value.model_dump(mode="json", exclude={"evidence_hash"})).encode("utf-8")
    monkeypatch.setattr(module, "MAX_PROOF_BYTES", len(payload))
    assert type(value).model_validate_json(value.model_dump_json()) == value
    monkeypatch.setattr(module, "MAX_PROOF_BYTES", len(payload) - 1)
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        type(value).model_validate_json(value.model_dump_json())
    assert value.resolved_mapping.clauses[-1].semantic_role == "HISTORICAL"


def test_command_size_is_limited_by_utf8_bytes_before_typed_parsing(tmp_path):
    _, values = _values(tmp_path)
    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _models().PreparationHumanOperation.build(**(values | dict(command_json="中" * 400000)))


@pytest.mark.parametrize("state,key,proof", [
    ("PRESENT", None, "a" * 64), ("PRESENT", "b" * 64, None),
    ("MISSING", "b" * 64, "a" * 64),
])
def test_input_presence_is_explicit_and_never_an_invented_partial_input(
    tmp_path, state, key, proof,
):
    _, values = _values(tmp_path)
    with pytest.raises(ValueError):
        _models().PreparationHumanOperation.build(**(values | dict(
            original_input_state=state, original_input_key=key, original_input_hash=proof)))


def test_save_roundtrip_uses_existing_sealed_table_and_does_not_rewrite_input_or_old_rows(tmp_path):
    store, value = _operation(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)
        schema = connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    assert _save(store, value) == value
    PreparationStore(store.database_path)
    assert _read(store, value) == value
    with closing(sqlite3.connect(store.database_path)) as connection:
        after = _rows(connection)
        for table in ("backtest_preparation", "backtest_preparation_idempotency"):
            assert after[table] == before[table]
        assert before["backtest_preparation_assurance"][0] in (
            after["backtest_preparation_assurance"])
        row = connection.execute("SELECT attempt_id,kind,candidate_hash FROM "
            "backtest_preparation_assurance WHERE evidence_key=?", (value.evidence_key,)).fetchone()
        assert row == (value.slot, "HUMAN_OPERATION", value.after_candidate_hash)
        after_schema = connection.execute(
            "SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert after_schema == schema


def test_same_intent_retry_keeps_original_time_but_changed_intent_conflicts(tmp_path):
    store, values = _values(tmp_path)
    first = _models().PreparationHumanOperation.build(**values)
    later = _models().PreparationHumanOperation.build(**(values | dict(
        created_at=_NOW + timedelta(hours=1))))
    assert first.evidence_key == later.evidence_key and first.evidence_hash != later.evidence_hash
    assert _save(store, first) == _save(store, later) == first
    command = json.loads(values["command_json"])
    command["evidence"] += " A different explicit intent."
    changed = _models().PreparationHumanOperation.build(**(values | dict(
        command_json=canonical(command))))
    with pytest.raises(PreparationConflictError) as error:
        _save(store, changed)
    assert error.value.code == "SOURCE_COVERAGE_COMMAND_CONFLICT"
    assert _read(store, first) == first


def test_second_correction_of_one_real_attempt_uses_a_distinct_kind_local_slot(tmp_path):
    store, values = _values(tmp_path)
    first = _models().PreparationHumanOperation.build(**values)
    second = _models().PreparationHumanOperation.build(**(values | dict(
        before_revision=values["after_revision"], after_revision=values["after_revision"] + 1,
        before_candidate_revision=values["after_candidate_revision"],
        after_candidate_revision=values["after_candidate_revision"] + 1,
        previous_human_ref=first.evidence_hash)))
    assert first.attempt_id == second.attempt_id
    assert first.slot != second.slot and first.evidence_key != second.evidence_key
    _save(store, first)
    _save(store, second)
    assert _read(store, first) == first and _read(store, second) == second


def test_store_joins_caller_transaction_and_rollback_leaves_no_human_receipt(tmp_path):
    store, value = _operation(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _api().save_human_operation(connection, value)
        assert connection.in_transaction
        connection.rollback()
    assert _read(store, value) is None


def test_native_backup_preserves_human_operation_and_original_input(tmp_path):
    store, value = _operation(tmp_path)
    _save(store, value)
    path = tmp_path / "backup.sqlite3"
    with (closing(sqlite3.connect(store.database_path)) as source,
          closing(sqlite3.connect(path)) as backup):
        source.backup(backup)
        assert _rows(source) == _rows(backup)
    backup_store = PreparationStore(path)
    assert _read(backup_store, value) == value
    assert backup_store.input_evidence(value.preparation_id, value.attempt_id) == (
        store.input_evidence(value.preparation_id, value.attempt_id))


def test_read_uses_at_most_two_indexed_lookups_and_performs_no_writes(tmp_path):
    store, value = _operation(tmp_path)
    _save(store, value)
    uri = f"file:{store.database_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        statements = []
        conn.set_trace_callback(statements.append)
        assert _api().human_operation(conn, value.preparation_id, 0,
            value.after_candidate_revision) == value
        assert conn.total_changes == 0
    selects = [sql for sql in statements if "FROM backtest_preparation_assurance " in sql]
    assert 1 <= len(selects) <= 2
    assert all("WHERE" in sql for sql in selects)


@pytest.mark.parametrize("guard", sorted(ASSURANCE_TRIGGERS))
def test_human_read_checks_every_existing_immutable_seal(tmp_path, guard):
    store, value = _operation(tmp_path)
    _save(store, value)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute(f"DROP TRIGGER {guard}")
        with pytest.raises(PreparationConflictError) as error:
            _api().human_operation(connection, value.preparation_id, 0,
                value.after_candidate_revision)
        assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("mutation", ["key", "slot", "candidate", "selfhash", "canonical"])
def test_resealed_row_tampering_is_sanitized_integrity_failure(tmp_path, mutation):
    store, value = _operation(tmp_path)
    _save(store, value)
    columns = dict(key="evidence_key", slot="attempt_id", candidate="candidate_hash",
                   selfhash="evidence_hash", canonical="payload_json")
    changed = ("\n" + canonical(value.model_dump(mode="json")) if mutation == "canonical"
               else "f" * 64)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute(f"UPDATE backtest_preparation_assurance SET {columns[mutation]}=? "
                           "WHERE evidence_key=?", (changed, value.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
        with pytest.raises(PreparationConflictError) as error:
            _api().human_operation(connection, value.preparation_id, 0,
                value.after_candidate_revision)
        assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"


def test_oversized_stored_payload_is_blocked_before_decoding_unbounded_json(tmp_path, monkeypatch):
    store, value = _operation(tmp_path)
    _save(store, value)

    def forbidden_parse(*args, **kwargs):
        pytest.fail("Oversized damaged storage must be rejected before JSON model parsing.")

    monkeypatch.setattr(type(value), "model_validate_json", forbidden_parse)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute("UPDATE backtest_preparation_assurance SET payload_json=? "
            "WHERE evidence_key=?", (" " * (8 * 1024 * 1024 + 129), value.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
        with pytest.raises(PreparationConflictError) as error:
            _api().human_operation(connection, value.preparation_id, 0,
                value.after_candidate_revision)
        assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_normal_sql_cannot_modify_or_delete_human_operation(tmp_path, operation):
    store, value = _operation(tmp_path)
    _save(store, value)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(f"{operation} " + (
                "backtest_preparation_assurance SET evidence_hash=evidence_hash "
                if operation == "UPDATE" else "FROM backtest_preparation_assurance ")
                + "WHERE evidence_key=?", (value.evidence_key,))
    assert _read(store, value) == value


def test_legacy_absent_aux_read_is_unknown_and_write_requires_upgrade_without_ddl(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy(path)
    store, value = _operation(tmp_path / "new-fixture")
    with closing(sqlite3.connect(path)) as connection:
        schema = connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert _api().human_operation(connection, value.preparation_id, 0,
            value.after_candidate_revision) is None
        with pytest.raises(PreparationConflictError) as error:
            _api().save_human_operation(connection, value)
        assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert connection.total_changes == 0
        after_schema = connection.execute(
            "SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert after_schema == schema
    assert store.input_evidence(value.preparation_id, value.attempt_id) is not None
