"""Structural lineage integrity, separate from later actual-parent authentication."""

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from tests.integration.test_preparation_lineage_storage import _case, _replace

from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_lineage_models import (
    LineagePlacement,
    PreparationLineage,
)
from trade_plan_monitor.backtest.preparation_lineage_store import lineage, save_lineage
from trade_plan_monitor.backtest.preparation_models import (
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash


def _replace_payload(connection, payload):
    """Simulate corruption, then restore the exact required seal before reading."""
    connection.execute("DROP TRIGGER pma_preparation_assurance_update")
    connection.execute(
        "UPDATE backtest_preparation_assurance SET payload_json=?", (payload,),
    )
    connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])


@pytest.mark.parametrize("field", [
    "leaf_assurance_hash", "leaf_current_review_hash", "leaf_manifest_hash",
])
def test_direct_original_owner_cannot_rehash_conflicting_leaf_hashes(tmp_path, field):
    _, _, original = _case(tmp_path)
    row = original.placements[0]
    assert row.owner_binding == row.leaf_owner_binding
    assert original.evidence_hash == daily_hash(
        original.version, original.model_dump(mode="json", exclude={"evidence_hash"}),
    )
    with pytest.raises(ValueError):
        changed = LineagePlacement.model_validate(
            row.model_dump(mode="python") | {field: "9" * 64},
        )
        _replace(original, placements=(changed,))


def test_original_leaf_cannot_be_the_new_consumer_itself(tmp_path):
    _, _, original = _case(tmp_path)
    row = original.placements[0]
    with pytest.raises(ValueError):
        changed = row.model_copy(update={
            "leaf_owner_binding": row.leaf_owner_binding.model_copy(update={
                "preparation_id": original.preparation_id,
            }),
        })
        _replace(original, placements=(changed,))


def test_real_alias_keeps_distinct_original_proof_domains(tmp_path):
    """A relay's review/proof/manifest can differ from its original leaf's values."""
    _, _, original = _case(tmp_path)
    row = original.placements[0].model_copy(update={
        "leaf_owner_binding": original.placements[0].leaf_owner_binding.model_copy(update={
            "preparation_id": "original-owner", "item_index": 3,
        }),
        "leaf_assurance_hash": "7" * 64,
        "leaf_current_review_hash": "8" * 64,
        "leaf_manifest_hash": "9" * 64,
    })
    alias = _replace(original, placements=(row,))
    assert alias.placements[0].owner_binding != alias.placements[0].leaf_owner_binding
    assert alias.placements[0].leaf_assurance_hash != alias.placements[0].owner_proof_hash
    assert alias.authority_granted is False


@pytest.mark.parametrize("field,value", [
    ("source_id", "another-source"),
    ("source_revision", 2),
    ("source_binding_hash", "9" * 64),
    ("candidate_revision", 3),
    ("candidate_hash", "9" * 64),
    ("review_evidence_hash", "9" * 64),
    ("attempt_id", "another-attempt"),
    ("inputs_hash", "9" * 64),
    ("independent", False),
], ids=["source-id", "source-rev", "binding", "candidate-rev", "candidate", "review",
        "attempt", "inputs", "independent"])
def test_alias_cannot_change_any_exact_copied_source_coordinate(tmp_path, field, value):
    _, _, original = _case(tmp_path)
    row = original.placements[0]
    with pytest.raises(ValueError):
        row.model_copy(update={
            "leaf_owner_binding": row.leaf_owner_binding.model_copy(update={
                "preparation_id": "original-owner", field: value,
            }),
        })


@pytest.mark.parametrize("invalid_payload", ["oversize", "blob"])
def test_stored_payload_envelope_is_rejected_before_json_decoding(
    tmp_path, monkeypatch, invalid_payload,
):
    store, _, original = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        save_lineage(connection, original)
        if invalid_payload == "oversize":
            payload = canonical(original.model_dump(mode="json"))
            payload += " " * (MAX_PROOF_BYTES + 1 - len(payload.encode("utf-8")))
            assert len(payload.encode("utf-8")) == MAX_PROOF_BYTES + 1
        else:
            payload = sqlite3.Binary(canonical(original.model_dump(mode="json")).encode("utf-8"))
        _replace_payload(connection, payload)
        calls = []

        def decoder(*args, **kwargs):
            calls.append(True)
            raise AssertionError("unbounded or non-text persisted payload reached JSON decoding")

        monkeypatch.setattr(PreparationLineage, "model_validate_json", decoder)
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, original.preparation_id)
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        assert calls == []
        assert "Next source." not in str(error.value)


def test_missing_guard_is_checked_before_any_payload_decoder(tmp_path, monkeypatch):
    store, _, original = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        save_lineage(connection, original)
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")

        def decoder(*args, **kwargs):
            pytest.fail("missing mandatory seal must be rejected before payload decoding")

        monkeypatch.setattr(PreparationLineage, "model_validate_json", decoder)
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, original.preparation_id)
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("state,expected_reads", [("present", 1), ("missing", 2), ("key", 2)])
def test_lineage_reader_uses_at_most_two_identity_point_reads(tmp_path, state, expected_reads):
    store, _, original = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        if state != "missing":
            save_lineage(connection, original)
        if state == "key":
            connection.execute("DROP TRIGGER pma_preparation_assurance_update")
            connection.execute(
                "UPDATE backtest_preparation_assurance SET evidence_key=?", ("9" * 64,),
            )
            connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
        changes, statements = connection.total_changes, []
        connection.set_trace_callback(statements.append)
        if state == "key":
            with pytest.raises(PreparationConflictError) as error:
                lineage(connection, original.preparation_id)
            assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
        else:
            assert lineage(connection, original.preparation_id) == (
                original if state == "present" else None
            )
        queries = [sql for sql in statements
                   if " FROM backtest_preparation_assurance WHERE " in sql]
        assert len(queries) == expected_reads
        assert "WHERE evidence_key=" in queries[0]
        if expected_reads == 2:
            assert "WHERE preparation_id=" in queries[1]
            assert "attempt_id='lineage-create' AND kind='LINEAGE'" in queries[1]
        assert connection.total_changes == changes
        assert not any(sql.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK", "INSERT"))
                       for sql in statements)


def test_two_selected_owners_preserve_original_selection_order_and_retry(tmp_path):
    store, _, original = _case(tmp_path, composition=True)
    first = original.placements[0]
    second_binding = first.owner_binding.model_copy(update={"preparation_id": "second-owner"})
    second = first.model_copy(update={
        "consumer_item_index": 0, "owner_binding": second_binding,
        "leaf_owner_binding": second_binding,
    })
    first = first.model_copy(update={"consumer_item_index": 1})
    command = PreparedPlanCompositionInput(preparation_id=original.preparation_id, plans=(
        ReviewedPlanReference(preparation_id="owner", manifest_hash="e" * 64),
        ReviewedPlanReference(preparation_id="second-owner", manifest_hash="e" * 64),
    ))
    value = _replace(original, command_json=canonical_json(command), selection_order=(1, 0),
                     placements=(second, first))
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        assert save_lineage(connection, value) == value
        assert save_lineage(connection, _replace(
            value, created_at=value.created_at + timedelta(seconds=1),
        )) == value
        assert lineage(connection, value.preparation_id) == value
        assert connection.execute(
            "SELECT item_index,attempt_id,candidate_hash FROM backtest_preparation_assurance",
        ).fetchone() == (1, "lineage-create", first.owner_binding.candidate_hash)
    with pytest.raises(ValueError):
        _replace(value, selection_order=(0, 1))
    with pytest.raises(ValueError):
        _replace(value, selection_order=(1,), placements=(second,))
