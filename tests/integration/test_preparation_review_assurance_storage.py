"""Current review receipts share sealed storage without changing historical payloads."""

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from tests.integration.test_preparation_current_assurance import _ready, _two_sources
from tests.integration.test_source_coverage_preparation_storage import _NOW

from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, CoverageIssue
from trade_plan_monitor.backtest.preparation_assurance_store import (
    ASSURANCE_TRIGGERS,
    PreparationInputEvidence,
    input_evidence,
    save_input_evidence,
)
from trade_plan_monitor.backtest.preparation_current_assurance import read_current_assurance
from trade_plan_monitor.backtest.preparation_review_assurance_models import (
    PreparationReviewAssurance,
)
from trade_plan_monitor.backtest.preparation_review_assurance_store import (
    review_assurance,
    save_review_assurance,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.domain.daily_hash import canonical


def _case(tmp_path, *, collection=False, **updates):
    if collection:
        store, record, _ = _two_sources(tmp_path)
    else:
        store, record, _, _, _ = _ready(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        proofs = read_current_assurance(connection, record)
    values = dict(preparation_id=record.preparation_id, command_id="synthetic-review-command",
        command_request_hash="c" * 64, previous_revision=record.revision,
        reviewed_revision=record.revision + 1, review_revision=record.review_revision + 1,
        original_review_hash="d" * 64, frozen_manifest_hash="f" * 64,
        proofs=proofs, created_at=_NOW)
    return store, record, PreparationReviewAssurance.build(**(values | updates))


@pytest.mark.parametrize("collection", [False, True])
def test_round_trip_retains_the_entire_exact_review_proof_and_real_attempts(tmp_path, collection):
    store, record, value = _case(tmp_path, collection=collection)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        saved = save_review_assurance(connection, value)
        restored = review_assurance(connection, value.preparation_id, value.review_revision)

        assert saved == restored == value
        assert restored.authority_granted is False and restored.kind == "REVIEW"
        assert restored.proofs == value.proofs
        assert all(proof.binding.attempt_id for proof in restored.proofs)
        assert record.review is None
        connection.rollback()


def _replace(value, **updates):
    return type(value).build(**(
        {name: getattr(value, name) for name in type(value).model_fields
         if name not in {"evidence_key", "evidence_hash"}} | updates))


def _proof(value, **updates):
    values = {name: getattr(value, name) for name in type(value).model_fields
              if name not in {"status", "evidence_hash"}}
    values.update(updates)
    values["prefix_hash"] = source_prefix_hash(values["prefix"], values["binding"])
    values["parent_hash"] = (None if values["binding"].independent or not values["prefix"]
                             else values["prefix"][-1].assurance_hash)
    return type(value).build(**values)


def _old_rows(connection):
    return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("backtest_preparation", "backtest_preparation_idempotency")}


def test_exact_retry_keeps_original_time_and_never_writes_or_commits_again(tmp_path):
    store, _, original = _case(tmp_path)
    later = _replace(original, created_at=original.created_at + timedelta(minutes=1))
    assert original.evidence_key == later.evidence_key
    assert original.evidence_hash != later.evidence_hash
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        before = _old_rows(connection)
        statements = []
        connection.set_trace_callback(statements.append)
        save_review_assurance(connection, original)
        changes = connection.total_changes

        assert save_review_assurance(connection, later) == original
        assert review_assurance(connection, original.preparation_id,
                                original.review_revision) == original
        assert connection.total_changes == changes
        assert _old_rows(connection) == before
        assert connection.in_transaction
        assert not any(sql.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK"))
                       for sql in statements)
        connection.rollback()
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert review_assurance(connection, original.preparation_id,
                                original.review_revision) is None


@pytest.mark.parametrize("field", ["command_id", "command_request_hash", "original_review_hash",
                                  "frozen_manifest_hash", "proofs", "previous_revision"])
def test_changed_command_or_proof_conflicts_without_overwriting_the_receipt(tmp_path, field):
    store, _, original = _case(tmp_path)
    updates = {field: "changed-command" if field == "command_id" else "a" * 64}
    if field == "proofs":
        proof = original.proofs[0]
        updates = {"proofs": (_proof(proof, binding=proof.binding.model_copy(update={
            "candidate_revision": proof.binding.candidate_revision + 1})),)}
    elif field == "previous_revision":
        updates = dict(previous_revision=original.previous_revision + 1,
                       reviewed_revision=original.reviewed_revision + 1)
    changed = _replace(original, **updates)
    assert original.evidence_key == changed.evidence_key
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        save_review_assurance(connection, original)
        changes = connection.total_changes

        with pytest.raises(PreparationConflictError) as error:
            save_review_assurance(connection, changed)

        assert error.value.code == "SOURCE_COVERAGE_COMMAND_CONFLICT"
        assert connection.total_changes == changes
        assert review_assurance(connection, original.preparation_id,
                                original.review_revision) == original
        connection.rollback()


def test_review_slot_and_real_input_attempt_are_separate_kind_namespaces(tmp_path):
    store, record, value = _case(tmp_path)
    actual_attempt = value.proofs[0].binding.attempt_id
    slot = f"review-{value.review_revision}"
    assert actual_attempt != slot
    with closing(sqlite3.connect(store.database_path)) as connection:
        original = input_evidence(connection, record.preparation_id, actual_attempt)
        aliased = PreparationInputEvidence.build(**(
            original.model_dump(mode="python", exclude={"evidence_key", "evidence_hash"})
            | {"attempt_id": slot, "inputs": original.inputs}))
        connection.execute("BEGIN IMMEDIATE")
        save_input_evidence(connection, aliased)
        save_review_assurance(connection, value)

        assert input_evidence(connection, record.preparation_id, slot) == aliased
        assert review_assurance(connection, record.preparation_id, value.review_revision) == value
        projected = connection.execute(
            "SELECT item_index,attempt_id,source_binding_hash,candidate_hash "
            "FROM backtest_preparation_assurance WHERE evidence_key=?", (value.evidence_key,),
        ).fetchone()
        binding = value.proofs[-1].binding
        assert projected == (binding.item_index, slot, binding.source_binding_hash,
                             binding.candidate_hash)
        assert value.proofs[0].binding.attempt_id == actual_attempt
        connection.rollback()


@pytest.mark.parametrize("operation", ["read", "save"])
def test_missing_auxiliary_tables_require_upgrade_without_creating_anything(tmp_path, operation):
    _, _, value = _case(tmp_path)
    with closing(sqlite3.connect(":memory:")) as connection:
        before = connection.execute("SELECT * FROM sqlite_master").fetchall()

        with pytest.raises(PreparationConflictError) as error:
            if operation == "read":
                review_assurance(connection, value.preparation_id, value.review_revision)
            else:
                save_review_assurance(connection, value)

        assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert connection.total_changes == 0 and not connection.in_transaction
        assert connection.execute("SELECT * FROM sqlite_master").fetchall() == before


@pytest.mark.parametrize("guard", tuple(ASSURANCE_TRIGGERS))
def test_every_existing_sql_seal_is_required_for_both_read_and_save(tmp_path, guard):
    store, _, value = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("DROP TRIGGER " + guard)
        changes = connection.total_changes
        for operation in (
            lambda: review_assurance(connection, value.preparation_id, value.review_revision),
            lambda: save_review_assurance(connection, value),
        ):
            with pytest.raises(PreparationConflictError) as error:
                operation()
            assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
            assert str(error.value) == "SOURCE_COVERAGE_INTEGRITY"
        assert connection.total_changes == changes


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_normal_sql_cannot_mutate_a_saved_review_receipt(tmp_path, operation):
    store, _, value = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        save_review_assurance(connection, value)

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE backtest_preparation_assurance SET evidence_hash=evidence_hash "
                "WHERE evidence_key=?" if operation == "UPDATE" else
                "DELETE FROM backtest_preparation_assurance WHERE evidence_key=?",
                (value.evidence_key,))

        assert review_assurance(connection, value.preparation_id, value.review_revision) == value
        connection.rollback()


@pytest.mark.parametrize("column,replacement", [
    ("evidence_key", "a" * 64), ("preparation_id", "other-preparation"), ("item_index", 1),
    ("attempt_id", "review-other"), ("kind", "INPUT"), ("source_binding_hash", "a" * 64),
    ("candidate_hash", "a" * 64), ("payload_json", "{}"), ("evidence_hash", "a" * 64),
    ("created_at", "2026-10-27T11:00:00+08:00"),
])
def test_corrupted_payload_or_any_projection_is_an_explicit_integrity_failure(
    tmp_path, column, replacement,
):
    store, _, value = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        save_review_assurance(connection, value)
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute(f"UPDATE backtest_preparation_assurance SET {column}=? "
                           "WHERE evidence_key=?", (replacement, value.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])

        with pytest.raises(PreparationConflictError) as error:
            review_assurance(connection, value.preparation_id, value.review_revision)

        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        connection.rollback()


def test_noncanonical_but_equivalent_json_is_not_accepted_as_exact_stored_bytes(tmp_path):
    store, _, value = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        save_review_assurance(connection, value)
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute("UPDATE backtest_preparation_assurance SET payload_json=? "
                           "WHERE evidence_key=?",
                           ("\n" + canonical(value.model_dump(mode="json")), value.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])

        with pytest.raises(PreparationConflictError) as error:
            review_assurance(connection, value.preparation_id, value.review_revision)

        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        connection.rollback()


@pytest.mark.parametrize("field", ["previous_revision", "reviewed_revision", "review_revision"])
@pytest.mark.parametrize("bad", [True, 0, -1, 9_007_199_254_740_992])
def test_review_revisions_are_strict_positive_safe_integers(tmp_path, field, bad):
    _, _, value = _case(tmp_path)

    with pytest.raises(ValueError):
        _replace(value, **{field: bad})


@pytest.mark.parametrize("problem", ["gap", "other_preparation", "missing_prefix", "blocked"])
def test_review_model_rejects_incomplete_or_inexact_current_prefixes(tmp_path, problem):
    _, _, value = _case(tmp_path, collection=problem == "missing_prefix")
    first = value.proofs[0]

    with pytest.raises(ValueError):
        if problem == "gap":
            proofs = (_proof(first, binding=first.binding.model_copy(update={"item_index": 1})),)
        elif problem == "other_preparation":
            proofs = (_proof(first, binding=first.binding.model_copy(update={
                "preparation_id": "other-preparation"})),)
        elif problem == "missing_prefix":
            proofs = (first, _proof(value.proofs[1], prefix=()))
        else:
            proofs = (_proof(first, issues=(CoverageIssue(
                code="SOURCE_COVERAGE_REQUIRED", message="Unproven source"),)),)
        _replace(value, proofs=proofs)


def test_review_requires_the_full_nonempty_prefix_and_actual_next_revision(tmp_path):
    _, _, value = _case(tmp_path)
    for changes in ({"proofs": ()}, {"reviewed_revision": value.previous_revision},
                    {"authority_granted": True}, {"evidence_hash": "a" * 64},
                    {"evidence_key": "a" * 64}):
        with pytest.raises(ValueError):
            PreparationReviewAssurance.model_validate(value.model_dump(mode="python") | changes)


def test_complete_review_receipt_over_eight_mib_is_rejected_without_truncation(tmp_path):
    _, _, value = _case(tmp_path)
    original = value.proofs[0]
    proofs = []
    for index in range(128):
        source_id = f"synthetic-bounded-source-{index}"
        binding = original.binding.model_copy(update={
            "item_index": index, "source_id": source_id, "independent": True})
        refs = tuple(row.model_copy(update={"source_id": source_id})
                     for row in original.source_refs)
        owners = tuple(row.model_copy(update={"source_id": source_id})
                       for row in original.owners)
        globals_ = tuple(row.model_copy(update={"source_id": source_id})
                         for row in original.global_obligations)
        prefix = tuple(PrefixAssuranceRef(binding=row.binding, assurance_hash=row.evidence_hash)
                       for row in proofs)
        proofs.append(_proof(original, binding=binding, source_refs=refs, owners=owners,
                             global_obligations=globals_, prefix=prefix))
    assert len(canonical([proof.model_dump(mode="json") for proof in proofs]).encode()) > (
        MAX_PROOF_BYTES)

    with pytest.raises(ValueError, match="SOURCE_COVERAGE_LIMIT_EXCEEDED"):
        _replace(value, proofs=tuple(proofs))

    assert len(proofs) == 128
