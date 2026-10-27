"""Adversarial sidecar checks use disposable databases and no external services."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_coverage_storage import (
    NOW,
    VERSION,
    append,
)
from tests.integration.test_source_coverage_storage import (
    database as database,
)

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.models import PlanReviewProvenance
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageCommandConflict,
    SourceCoverageIntegrityError,
    SourceCoverageStore,
)
from trade_plan_monitor.state.source_coverage_values import CoverageInputs, CoverageReviewReceipt

_REVIEW_ID = "00000000-0000-0000-0000-000000000003"
_SEALS = {
    *(f"pma_seal_source_coverage_{table}_{operation}"
      for table in ("installation", "cutover", "input", "assessment", "review")
      for operation in ("update", "delete")),
    "pma_seal_source_coverage_installation_insert",
    "pma_seal_source_coverage_cutover_insert",
    "pma_seal_source_coverage_assessment_insert",
}


def _history(engine, assessment):
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        return tuple(append(store, assessment, revision=index, command=f"history-{index + 1}")
                     for index in range(3))


@pytest.mark.parametrize("lookup", ["latest", "command"])
def test_deleting_a_nonadjacent_ancestor_invalidates_a_later_history_record(database, lookup):
    engine, _, assessment, _, _ = database
    _history(engine, assessment)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_assessment_delete")
        connection.execute(text("DELETE FROM source_coverage_assessment WHERE revision=1"))

    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError):
        store = SourceCoverageStore(session)
        store.latest(VERSION) if lookup == "latest" else store.command("history-3")


@pytest.mark.parametrize("column,value", [
    ("command_id", "forged-ancestor-command"),
    ("request_hash", "f" * 64),
    ("created_at", "2001-01-01T00:00:00+08:00"),
])
def test_an_ancestor_projection_cannot_disagree_with_its_hashed_payload(database, column, value):
    engine, _, assessment, _, _ = database
    _history(engine, assessment)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_assessment_update")
        connection.execute(text(
            f"UPDATE source_coverage_assessment SET {column}=:value WHERE revision=2"
        ), {"value": value})

    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError):
        SourceCoverageStore(session).latest(VERSION)


def _private_inputs(draft, source, assessment, *, suffix="\n\t"):
    after = draft.model_dump(mode="json")
    before = {**after, "name": "Original display name\n第二行"}
    normalization = capture_normalization(before, after, source)
    raw = json.dumps({"draft": before}, ensure_ascii=False, indent=2) + suffix
    derivation = SourceDerivationEvidence.build(
        kind="FULL_DRAFT", source_hash=scope_hash(source), raw_json=raw,
        context_json=None, base_hash=None,
        stages=(DerivationStage.build(phase="SOURCE_NORMALIZED",
                                     output_json=canonical({"draft": after})),),
    )
    inputs = CoverageInputs.build(
        source_hash=scope_hash(source), source_binding_hash="a" * 64,
        initial_coverage=assessment, normalization=normalization, derivation=derivation,
    )
    return inputs, raw


def test_private_raw_bytes_and_normalization_envelopes_roundtrip_exactly(database):
    engine, _, assessment, draft, source = database
    inputs, raw = _private_inputs(draft, source, assessment)
    assert raw != canonical(json.loads(raw))
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        store.save_input(VERSION, inputs)
        record = append(store, assessment, inputs=inputs)
    with Session(engine) as session:
        store = SourceCoverageStore(session)
        loaded = store.input(VERSION)
        assert loaded == inputs
        assert loaded.derivation.raw_json == raw
        assert loaded.derivation.raw_hash == scope_hash(raw)
        assert loaded.normalization.changes == inputs.normalization.changes
        assert "第二行" in loaded.normalization.changes[0].before_json
        assert store.latest(VERSION) == record
        assert store.latest(VERSION).inputs == inputs


def test_same_request_cannot_replace_private_raw_bytes_with_equivalent_json(database):
    engine, _, assessment, draft, source = database
    first, raw = _private_inputs(draft, source, assessment)
    changed, changed_raw = _private_inputs(draft, source, assessment, suffix="\n")
    assert json.loads(raw) == json.loads(changed_raw)
    assert first.evidence_hash != changed.evidence_hash
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        assert store.save_input(VERSION, first) == first
        with pytest.raises(SourceCoverageCommandConflict):
            store.save_input(VERSION, changed)
        original = append(store, assessment, inputs=first)
        with pytest.raises(SourceCoverageCommandConflict):
            append(store, assessment, inputs=changed)
        assert append(store, assessment, inputs=first) == original


@pytest.mark.parametrize("mutation", [
    "source_projection", "selfhash_projection", "noncanonical_payload", "raw_preimage",
    "normalization_preimage",
])
def test_private_input_corruption_is_rejected_without_echoing_stored_content(database, mutation):
    engine, _, assessment, draft, source = database
    inputs, _ = _private_inputs(draft, source, assessment)
    with Session(engine) as session, session.begin():
        SourceCoverageStore(session).save_input(VERSION, inputs)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_input_update")
        if mutation in {"source_projection", "selfhash_projection"}:
            column = "source_hash" if mutation == "source_projection" else "evidence_hash"
            connection.execute(text(f"UPDATE source_coverage_input SET {column}=:value"),
                               {"value": "f" * 64})
        else:
            payload = inputs.model_dump(mode="json")
            if mutation == "raw_preimage":
                payload["derivation"]["raw_json"] += " SECRET_STORED_CONTENT"
            elif mutation == "normalization_preimage":
                payload["normalization"]["changes"][0]["before_json"] = canonical({
                    "present": True, "value": "SECRET_STORED_CONTENT",
                })
            document = json.dumps(payload, ensure_ascii=False, indent=2) if (
                mutation == "noncanonical_payload") else canonical(payload)
            connection.execute(text("UPDATE source_coverage_input SET payload_json=:payload"),
                               {"payload": document})
    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError) as error:
        SourceCoverageStore(session).input(VERSION)
    assert str(error.value) == "Stored source coverage evidence is invalid"
    assert "SECRET_STORED_CONTENT" not in str(error.value)


def _review(session, draft, source):
    _, mapping = source_mapping(draft)
    original = build_daily_review(draft, mapping, source)
    assert original.issues == ()
    session.add(PlanReviewProvenance(
        plan_version_id=VERSION, origin="MANUAL", extraction_id=None,
        source_hash=scope_hash(source), draft_hash=daily_draft_sha256(draft),
        confirmed_at=NOW.isoformat(), content_hash=original.content_hash,
        review_evidence_hash=original.evidence_hash,
        mapping_json=canonical(mapping.model_dump(mode="json")), required_issues_json="[]",
        resolutions_json="[]", review_id=_REVIEW_ID, review_revision=1,
    ))
    session.flush()
    return original


def _receipt(record, original, **updates):
    proof = record.assessment
    values = {
        "plan_version_id": VERSION, "review_id": _REVIEW_ID, "review_revision": 1,
        "coverage_revision": record.revision, "coverage_bundle_hash": record.evidence_hash,
        "coverage_evidence_hash": proof.evidence_hash,
        "coverage_rules_version": proof.rules_version,
        "source_hash": proof.source_hash, "content_hash": proof.content_hash,
        "mapping_hash": proof.mapping_hash, "original_review_evidence_hash": original.evidence_hash,
        "confirmed_at": NOW,
    }
    return CoverageReviewReceipt.build(**(values | updates))


def test_exact_receipt_binds_current_bundle_and_old_review_without_changing_old_rows(database):
    engine, _, assessment, draft, source = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        record = append(store, assessment)
        expected = _receipt(record, original)
        assert store.save_receipt(expected) == expected
        assert store.save_receipt(expected) == expected
        assert expected.authority_granted is False
    with Session(engine) as session:
        loaded = SourceCoverageStore(session).receipt(_REVIEW_ID)
        assert loaded == expected
        stored = session.get(PlanReviewProvenance, VERSION)
        assert stored.review_evidence_hash == original.evidence_hash
        assert stored.mapping_json == canonical(source_mapping(draft)[1].model_dump(mode="json"))


@pytest.mark.parametrize("updates", [
    {"coverage_revision": 2}, {"coverage_bundle_hash": "f" * 64},
    {"coverage_evidence_hash": "f" * 64}, {"source_hash": "f" * 64},
    {"content_hash": "f" * 64}, {"mapping_hash": "f" * 64},
    {"review_revision": 2}, {"review_id": "another-original-review"},
    {"original_review_evidence_hash": "f" * 64}, {"confirmed_at": NOW + timedelta(minutes=1)},
])
def test_a_selfhashed_receipt_cannot_bind_another_proof_or_original_review(database, updates):
    engine, _, assessment, draft, source = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        record = append(store, assessment)
        with pytest.raises(ValueError):
            store.save_receipt(_receipt(record, original, **updates))
        assert store.receipt(updates.get("review_id", _REVIEW_ID)) is None


def test_new_receipt_cannot_use_a_stale_coverage_revision(database):
    engine, _, assessment, draft, source = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        first = append(store, assessment)
        stale = _receipt(first, original)
        append(store, assessment, revision=1, command="newer-proof")
        with pytest.raises(ValueError):
            store.save_receipt(stale)
        assert store.receipt(_REVIEW_ID) is None


def test_an_incomplete_current_proof_cannot_receive_a_review_receipt(database):
    engine, _, assessment, draft, source = database
    incomplete = CoverageAssessment.build(**assessment.model_dump(mode="python", exclude={
        "evidence_hash", "status", "issues", "obligations",
    }), obligations=assessment.obligations, issues=(CoverageIssue(
        code="SOURCE_CONTEXT_UNVERIFIED", message="Unknown source remains.",
    ),))
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        record = append(store, incomplete)
        with pytest.raises(ValueError):
            store.save_receipt(_receipt(record, original))
        assert store.receipt(_REVIEW_ID) is None


def test_a_second_session_cannot_append_using_an_observed_stale_revision(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as first_session, Session(engine) as second_session:
        first, second = SourceCoverageStore(first_session), SourceCoverageStore(second_session)
        assert first.latest(VERSION) is None
        # End the observation before a new fenced write; SQLite cannot upgrade a stale WAL reader.
        first_session.rollback()
        append(second, assessment, command="competing-committed-proof")
        second_session.commit()
        with pytest.raises(RevisionConflictError):
            append(first, assessment, command="stale-observed-proof")
        first_session.rollback()
    with Session(engine) as session:
        assert SourceCoverageStore(session).latest(VERSION).revision == 1


def test_all_thirteen_exact_immutable_seal_names_are_installed(database):
    engine, _, _, _, _ = database
    with engine.connect() as connection:
        names = set(connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'pma_seal_source_coverage_%'"
        )).scalars())
    assert len(names) == 13
    assert names == _SEALS


@pytest.mark.parametrize("seal", sorted(_SEALS))
def test_any_missing_seal_blocks_reads_with_a_sanitized_integrity_error(database, seal):
    engine, _, _, _, _ = database
    assert seal in _SEALS
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP TRIGGER {seal}")

    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError) as error:
        SourceCoverageStore(session).latest(VERSION)

    assert str(error.value) == "Stored source coverage evidence is invalid"


def test_same_named_but_changed_seal_definition_does_not_restore_trust(database):
    engine, _, _, _, _ = database
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_assessment_update")
        connection.exec_driver_sql(
            "CREATE TRIGGER pma_seal_source_coverage_assessment_update "
            "BEFORE UPDATE ON source_coverage_assessment "
            "BEGIN SELECT 'SECRET_ALTERED_TRIGGER'; END"
        )

    with Session(engine) as session, pytest.raises(SourceCoverageIntegrityError) as error:
        SourceCoverageStore(session).latest(VERSION)

    assert str(error.value) == "Stored source coverage evidence is invalid"
    assert "SECRET_ALTERED_TRIGGER" not in str(error.value)


@pytest.mark.parametrize("table", ["assessment", "input", "review"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_ordinary_sql_cannot_mutate_inserted_proofs_inputs_or_receipts(database, table, operation):
    engine, _, assessment, draft, source = database
    inputs, _ = _private_inputs(draft, source, assessment)
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        store.save_input(VERSION, inputs)
        record = append(store, assessment, inputs=inputs)
        store.save_receipt(_receipt(record, original))
    assert table in {"assessment", "input", "review"}
    sql = (f"UPDATE source_coverage_{table} SET evidence_hash=evidence_hash" if operation
           == "UPDATE" else f"DELETE FROM source_coverage_{table}")

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(sql)

    with Session(engine) as session:
        store = SourceCoverageStore(session)
        assert store.latest(VERSION) == record
        assert store.input(VERSION) == inputs
        assert store.receipt(_REVIEW_ID).coverage_bundle_hash == record.evidence_hash


def test_direct_assessment_insert_cannot_skip_a_history_revision(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        append(SourceCoverageStore(session), assessment)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql(
            "INSERT INTO source_coverage_assessment "
            "(plan_version_id,revision,command_id,request_hash,payload_json,"
            "evidence_hash,created_at) "
            "SELECT plan_version_id,3,'gap-command',request_hash,payload_json,"
            "evidence_hash,created_at "
            "FROM source_coverage_assessment WHERE revision=1"
        )
    with Session(engine) as session:
        assert SourceCoverageStore(session).latest(VERSION).revision == 1


def test_immutable_old_receipt_remains_readable_after_current_proof_changes(database):
    engine, _, assessment, draft, source = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        original = _review(session, draft, source)
        first = append(store, assessment)
        receipt = _receipt(first, original)
        store.save_receipt(receipt)
        newer = append(store, assessment, revision=1, command="changed-current-proof")
        assert newer.evidence_hash != receipt.coverage_bundle_hash
        assert store.receipt(_REVIEW_ID) == receipt
        # An exact historical retry is evidence replay, never a current-eligibility calculation.
        assert store.save_receipt(receipt) == receipt
        assert receipt.authority_granted is False


def test_latest_read_uses_bounded_assessment_queries_instead_of_decoding_all_ancestors(database):
    engine, _, assessment, _, _ = database
    with Session(engine) as session, session.begin():
        store = SourceCoverageStore(session)
        for revision in range(24):
            append(store, assessment, revision=revision, command=f"bounded-history-{revision}")
    statements = []

    def count_queries(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "source_coverage_assessment" in (
            statement.lower()
        ):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        with Session(engine) as session:
            assert SourceCoverageStore(session).latest(VERSION).revision == 24
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
    assert 1 <= len(statements) <= 2
