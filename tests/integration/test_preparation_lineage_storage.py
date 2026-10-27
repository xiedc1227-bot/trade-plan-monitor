"""LINEAGE storage integrity is separate from actual parent/command authority."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_lineage_models import (
    LineagePlacement,
    PreparationLineage,
    lineage_key,
)
from trade_plan_monitor.backtest.preparation_lineage_store import lineage, save_lineage
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.domain.daily_hash import canonical

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _case(tmp_path, *, composition=False):
    store = PreparationStore(tmp_path / "lineage.sqlite", clock=lambda: _NOW)
    binding = CandidateBinding(preparation_id="owner", item_index=0, source_id="source",
        source_revision=1, source_binding_hash="a" * 64, candidate_revision=2,
        candidate_hash="b" * 64, review_evidence_hash="c" * 64,
        attempt_id="real-owner-attempt", inputs_hash=None, independent=True)
    placement = LineagePlacement(consumer_item_index=0, owner_binding=binding,
        owner_revision=6, owner_review_revision=1, owner_review_hash="d" * 64,
        owner_manifest_hash="e" * 64, owner_proof_hash="f" * 64,
        leaf_owner_binding=binding, leaf_assurance_hash="f" * 64,
        leaf_current_review_hash="d" * 64, leaf_manifest_hash="e" * 64)
    reference = ReviewedPlanReference(preparation_id="owner", manifest_hash="e" * 64)
    command = (PreparedPlanCompositionInput(preparation_id="child", plans=(reference,))
        if composition else SingleSourcePreparationInput(preparation_id="child",
            reviewed_base=reference, source=PreparationSource(source_id="next", text="Next source.",
                available_at=_NOW, effective_trade_date=_NOW.date())))
    value = PreparationLineage.build(preparation_id="child",
        operation="COMPOSE_REVIEWED" if composition else "CREATE_SINGLE",
        command_id="creation-command", command_request_hash="1" * 64,
        command_json=canonical_json(command), created_revision=1,
        creation_response_hash="2" * 64, selection_order=(0,), placements=(placement,),
        created_at=_NOW)
    return store, command, value


def _replace(value, **updates):
    return type(value).build(**({name: getattr(value, name) for name in type(value).model_fields
        if name not in {"evidence_key", "evidence_hash"}} | updates))


@pytest.mark.parametrize("composition", [False, True])
def test_lineage_round_trip_has_kind_local_slot_and_original_owner_refs(tmp_path, composition):
    store, command, value = _case(tmp_path, composition=composition)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert save_lineage(connection, value) == value
        assert lineage(connection, "child") == value
        row = connection.execute("SELECT item_index,attempt_id,kind,source_binding_hash,"
            "candidate_hash FROM backtest_preparation_assurance").fetchone()
        assert row == (0, "lineage-create", "LINEAGE", "a" * 64, "b" * 64)
        assert value.placements[0].owner_binding.attempt_id == "real-owner-attempt"
        assert value.authority_granted is False and value.command_json == canonical_json(command)
        assert connection.execute("SELECT count(*) FROM backtest_preparation").fetchone() == (0,)
        assert connection.in_transaction
        connection.rollback()
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert lineage(connection, "child") is None


def test_exact_intent_retry_retains_original_time_without_commit_or_business_write(tmp_path):
    store, _, value = _case(tmp_path)
    later = _replace(value, created_at=value.created_at + timedelta(minutes=1))
    assert later.evidence_key == value.evidence_key and later.evidence_hash != value.evidence_hash
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        save_lineage(connection, value)
        changes, statements = connection.total_changes, []
        connection.set_trace_callback(statements.append)
        assert save_lineage(connection, later) == value
        assert lineage(connection, "child") == value and connection.total_changes == changes
        assert connection.in_transaction
        assert not any(sql.upper().startswith(("COMMIT", "BEGIN", "ROLLBACK"))
                       for sql in statements)


@pytest.mark.parametrize("field,value", [
    ("command_id", "other-command"), ("command_request_hash", "3" * 64),
    ("creation_response_hash", "3" * 64),
])
def test_changed_lineage_intent_cannot_reuse_creation_slot(tmp_path, field, value):
    store, _, original = _case(tmp_path)
    changed = _replace(original, **{field: value})
    with closing(sqlite3.connect(store.database_path)) as connection:
        save_lineage(connection, original)
        with pytest.raises(PreparationConflictError) as error:
            save_lineage(connection, changed)
        assert error.value.code == "SOURCE_COVERAGE_COMMAND_CONFLICT"


@pytest.mark.parametrize("field,value", [
    ("created_revision", True), ("created_revision", 0), ("created_revision", 2),
    ("selection_order", (True,)), ("selection_order", (1,)),
    ("selection_order", (0, 0)), ("authority_granted", True),
    ("preparation_id", "another-consumer"), ("operation", "REVIEW_AND_FREEZE"),
    ("command_json", "{}"), ("command_json", " " * (1024 * 1024 + 1)),
], ids=lambda value: value[:32] if isinstance(value, str) else None)
def test_invalid_structure_cannot_be_rehashed_into_lineage(tmp_path, field, value):
    _, _, original = _case(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        _replace(original, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("consumer_item_index", True), ("owner_revision", 0), ("owner_review_revision", "1"),
    ("leaf_owner_binding", None),
])
def test_placement_strict_coordinates_are_not_coerced(tmp_path, field, value):
    _, _, original = _case(tmp_path)
    placement = original.placements[0]
    with pytest.raises(ValueError):
        type(placement).model_validate(placement.model_dump(mode="python") | {field: value})


@pytest.mark.parametrize("field,value", [
    ("item_index", 1), ("attempt_id", "not-lineage"), ("kind", "REVIEW"),
    ("source_binding_hash", "3" * 64), ("candidate_hash", "3" * 64),
    ("evidence_hash", "3" * 64), ("evidence_key", "3" * 64),
    ("payload_json", "{}"), ("created_at", "2026-10-28T10:00:00+08:00"),
])
def test_corrupt_projection_is_detected_by_exact_key_or_slot_fallback(tmp_path, field, value):
    store, _, original = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        save_lineage(connection, original)
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute(f"UPDATE backtest_preparation_assurance SET {field}=?", (value,))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, "child")
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"


@pytest.mark.parametrize("guard", tuple(ASSURANCE_TRIGGERS))
def test_every_existing_seal_is_required_even_for_a_missing_lineage(tmp_path, guard):
    store, _, _ = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute(f"DROP TRIGGER {guard}")
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, "child")
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"


def test_read_missing_old_auxiliary_schema_never_upgrades_or_writes():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        changes = connection.total_changes
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, "child")
        assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert connection.total_changes == changes
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert tables == [("unrelated",)]


def test_lineage_key_is_strict_and_does_not_depend_on_time():
    assert lineage_key("child") == lineage_key("child")
    for value in (None, True, 1, "bad id"):
        with pytest.raises(ValueError):
            lineage_key(value)


def test_noncanonical_payload_is_rejected_even_with_valid_model_hash(tmp_path):
    store, _, original = _case(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        save_lineage(connection, original)
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        payload = canonical(original.model_dump(mode="json")) + " "
        connection.execute("UPDATE backtest_preparation_assurance SET payload_json=?", (payload,))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
        with pytest.raises(PreparationConflictError) as error:
            lineage(connection, "child")
        assert error.value.code == "SOURCE_COVERAGE_INTEGRITY"
