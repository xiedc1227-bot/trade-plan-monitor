"""Current preparation proof is reconstructed from actual atomic attempt evidence.

These synthetic stores retain the real full loop protocol and raw private bytes.
Historical frozen documents and completed review receipts keep their old codecs.
"""

import importlib
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from tests.integration.test_plan_preparation_worker import (
    collection_claim,
    collection_update_result,
)
from tests.integration.test_source_coverage_preparation_commit import (
    _NOW,
    _finish,
    _initial_loop_case,
    _running,
)
from tests.integration.test_source_coverage_preparation_storage import _legacy, _rebind
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_coverage_baseline import _append_as_context

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
)
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_derivation_replay import expand_update_with_evidence
from trade_plan_monitor.ai.source_normalization import capture_normalization, validate_normalization
from trade_plan_monitor.ai.update_review import (
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import (
    ASSURANCE_TRIGGERS,
    PreparationInputEvidence,
)
from trade_plan_monitor.backtest.preparation_models import (
    PlanCollectionPreparationInput,
    PreparationCandidate,
    PreparationRecord,
    PreparationReview,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionPreparationReviewCommand,
    PreparationReviewCommand,
    collection_item_binding,
    frozen_collection,
    frozen_preparation,
    prepare_frozen_plan,
)
from trade_plan_monitor.backtest.preparation_store import (
    PreparationConflictError,
    PreparationStore,
    _request_hash,
)
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.source_coverage_authority import extraction_inputs
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_UNKNOWN = "Everything else depends on the blue lantern."


def _api():
    return importlib.import_module("trade_plan_monitor.backtest.preparation_current_assurance")


def _case(*, extra=None):
    source, mapping, original, inputs = _initial_loop_case(UUID(int=101))
    if extra is None:
        return source, mapping, original, inputs
    text, mapping = _append_as_context(
        source.text, mapping, extra, semantic_role="COMMENTARY",
        misclassification=dict(disposition="CONTEXT", paths=[], reason="Background commentary"),
    )
    source = source.model_copy(update={"text": text})
    output = LoopPlanExtractionOutput(
        schema_version="monitor-loop-extraction-v1", draft=original.draft,
        clauses=mapping.clauses, bindings=mapping.bindings,
        assumptions=(), warnings=(), opening_account=original.opening_account,
    )
    image = original.draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    coverage = assess_source_coverage(original.draft, mapping, text,
        normalization=trace, origin="AI_NEW")
    derivation = SourceDerivationEvidence.build(
        kind="FULL_DRAFT", source_hash=source.source_hash,
        raw_json="\n" + json.dumps(output.model_dump(mode="json"), ensure_ascii=False,
                                   indent=2) + "\n\t",
        context_json=None, base_hash=None,
        stages=(DerivationStage.build(phase="SOURCE_NORMALIZED",
            output_json=canonical(output.model_dump(mode="json"))),),
    )
    result = original.model_copy(update={
        "source_text_sha256": source.source_hash, "source_binding_hash": source.binding_hash,
        "daily_mapping": mapping, "coverage": coverage, "normalization_trace": trace,
        "evidence_hash": sha256(canonical_json({
            "domain": "monitor-loop-extraction-evidence-v1",
            "source_binding_hash": source.binding_hash,
            "plan_mapping": mapping, "opening_account": original.opening_account,
        }).encode()).hexdigest(),
    })
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, initial_coverage=coverage,
        normalization=trace, derivation=derivation)
    return source, mapping, result, inputs


def _ready(tmp_path, *, extra=None, with_inputs=True, metadata_mismatch=False):
    source, mapping, result, inputs = _case(extra=extra)
    if metadata_mismatch:
        changed = source.model_copy(update={
            "authored_at": source.available_at - timedelta(hours=1),
        })
        assert changed.source_hash == source.source_hash
        assert changed.binding_hash != source.binding_hash
        source, inputs = changed, _rebind(inputs, changed.binding_hash)
    store, running, candidate, _ = _running(tmp_path, owned=True,
        case=(inputs, source, result.to_preparation_candidate()))
    record = _finish(store, running, candidate, inputs if with_inputs else None)
    record = store.clear_work_claim(record.preparation_id,
        generation=record.work_claim.generation, expected_revision=record.revision)
    return store, record, result, inputs, mapping


def _rows(connection):
    tables = tuple(row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    return {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables}


def _stored_read(store, operation):
    with closing(sqlite3.connect(store.database_path)) as connection:
        before, changes = _rows(connection), connection.total_changes
        record = store._read(connection, "finish-with-evidence")
        try:
            return operation(connection, record)
        finally:
            assert connection.total_changes == changes and _rows(connection) == before


def _command(record):
    return PreparationReviewCommand(
        expected_revision=record.revision, expected_source_revision=record.source_revision,
        expected_candidate_revision=record.candidate_revision,
        candidate_hash=record.candidate.candidate_hash,
        evidence_hash=record.candidate.evidence_hash, confirmed=True,
        evidence="Explicit synthetic review of this exact source and opening account.",
    )


def _replace_input(store, replacement):
    """Inject a self-consistent damaged record, then restore every storage seal."""
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute(
            "UPDATE backtest_preparation_assurance SET payload_json=?, evidence_hash=? "
            "WHERE evidence_key=?",
            (canonical(replacement.model_dump(mode="json")), replacement.evidence_hash,
             replacement.evidence_key),
        )
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
    assert store.input_evidence(replacement.preparation_id, replacement.attempt_id) == replacement


def test_real_atomic_fixture_keeps_full_raw_protocol_and_every_unbound_original_clause(tmp_path):
    store, record, original, inputs, mapping = _ready(tmp_path)
    proof = store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id)
    assert proof.candidate_json == record.candidate.payload_json
    restored = LoopPlanExtractionResult.model_validate_json(proof.candidate_json)
    assert restored.daily_mapping == mapping and restored.evidence_hash == original.evidence_hash
    raw = LoopPlanExtractionOutput.model_validate_json(inputs.derivation.raw_json)
    assert raw.opening_account.inventory_quantity.value == 0
    assert inputs.derivation.raw_json.startswith("\n")
    assert inputs.derivation.raw_json.endswith("\n\t")
    assert raw.clauses[-1].semantic_role == "HISTORICAL" and not raw.clauses[-1].paths
    assert raw.clauses[-1].clause_id not in {
        identity for binding in raw.bindings for identity in binding.clause_ids}
    assert validate_normalization(inputs.normalization, original.draft, record.source.text) == (
        original.draft.model_dump(mode="json"))


def test_current_initial_recomputes_complete_from_actual_record_and_atomic_input_without_writes(
    tmp_path,
):
    store, record, _, inputs, mapping = _ready(tmp_path)

    proofs = _stored_read(store, _api().read_current_assurance)

    assert isinstance(proofs, tuple) and len(proofs) == 1
    proof = proofs[0]
    assert proof.coverage_complete and proof.status == "COMPLETE"
    assert proof.current_automatic_fidelity_verified and proof.authority_granted is False
    assert proof.source_assessment == inputs.initial_coverage
    assert proof.binding.preparation_id == record.preparation_id
    assert proof.binding.candidate_hash == record.candidate.candidate_hash
    assert proof.binding.attempt_id == record.attempts[-1].attempt_id
    assert proof.binding.inputs_hash == inputs.evidence_hash
    assert proof.binding.review_evidence_hash == build_initial_review(
        LoopPlanExtractionResult.model_validate_json(record.candidate.payload_json).draft,
        mapping, record.source).evidence_hash
    assert proof.source_refs[0].source_hash == record.source.source_hash
    assert proof.source_refs[0].source_binding_hash == record.source.binding_hash
    assert _stored_read(store, _api().require_current_preparation) == proofs
    assert record.review is None and store.get(record.preparation_id) == record


def test_unknown_background_is_recomputed_as_blocked_with_its_complete_original_span(tmp_path):
    store, record, original, _, _ = _ready(tmp_path, extra=_UNKNOWN)
    assert original.daily_mapping.clauses[-1].disposition == "CONTEXT"
    assert original.daily_mapping.clauses[-1].semantic_role == "COMMENTARY"

    proofs = _stored_read(store, _api().read_current_assurance)

    assert len(proofs) == 1 and proofs[0].status == "BLOCKED"
    assert proofs[0].authority_granted is False
    obligations = [row for row in proofs[0].source_assessment.obligations
                   if row.excerpt == _UNKNOWN]
    assert obligations and all(row.scope == "UNKNOWN" for row in obligations)
    assert all(record.source.text[row.start:row.end] == _UNKNOWN for row in obligations)
    with pytest.raises(PreparationConflictError) as error:
        _stored_read(store, _api().require_current_preparation)
    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"


def test_missing_original_input_remains_history_but_cannot_become_current_authority(tmp_path):
    store, record, _, _, _ = _ready(tmp_path, with_inputs=False)
    assert store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id) is None
    with pytest.raises(PreparationConflictError) as error:
        _stored_read(store, _api().require_current_preparation)
    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"
    assert store.get(record.preparation_id) == record


def test_current_read_requires_explicit_aux_upgrade_and_never_modifies_a_legacy_store(tmp_path):
    path = tmp_path / "legacy-preparation.sqlite3"
    legacy = _legacy(path)
    store = PreparationStore(path)
    with closing(sqlite3.connect(path)) as connection:
        before, changes = _rows(connection), connection.total_changes
        record = store._read(connection, legacy.preparation_id)
        with pytest.raises(PreparationConflictError) as error:
            _api().require_current_preparation(connection, record)
        assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert connection.total_changes == changes and _rows(connection) == before


@pytest.mark.parametrize("problem", ["missing_full_candidate", "different_full_candidate"])
def test_valid_input_selfhash_cannot_replace_the_exact_actual_full_candidate(tmp_path, problem):
    store, record, original, _, _ = _ready(tmp_path)
    captured = store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id)
    if problem == "missing_full_candidate":
        value = None
    else:
        value = original.model_copy(update={
            "draft": original.draft.model_copy(update={"name": "Another full postimage"}),
        }).to_preparation_candidate().payload_json
        assert value != captured.candidate_json
    replacement = PreparationInputEvidence.build(**(
        captured.model_dump(mode="python", exclude={"evidence_key", "evidence_hash"})
        | {"candidate_json": value, "inputs": captured.inputs}))
    _replace_input(store, replacement)

    with pytest.raises(PreparationConflictError) as error:
        _stored_read(store, _api().require_current_preparation)

    expected = ("SOURCE_COVERAGE_REQUIRED" if value is None else "SOURCE_COVERAGE_STALE")
    assert error.value.code == expected
    assert store.get(record.preparation_id) == record


def test_same_text_with_changed_source_metadata_cannot_reuse_original_raw_binding(tmp_path):
    store, record, original, inputs, _ = _ready(tmp_path, metadata_mismatch=True)
    assert original.source_text_sha256 == record.source.source_hash == inputs.source_hash
    assert original.source_binding_hash != record.source.binding_hash
    assert inputs.source_binding_hash == record.source.binding_hash

    with pytest.raises(PreparationConflictError) as error:
        _stored_read(store, _api().require_current_preparation)

    assert error.value.code == "SOURCE_COVERAGE_STALE"


@pytest.mark.parametrize("problem", ["unknown_background", "missing_input"])
def test_review_gate_blocks_before_any_old_freeze_or_receipt_is_committed(tmp_path, problem):
    store, record, _, _, _ = _ready(tmp_path,
        extra=_UNKNOWN if problem == "unknown_background" else None,
        with_inputs=problem != "missing_input")
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)

    with pytest.raises(PreparationConflictError) as error:
        store.review_and_freeze(record.preparation_id, command=_command(record),
                                idempotency_key="current-review-must-block")

    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"
    assert store.get(record.preparation_id) == record
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before


def _historical_review_receipt(store, record):
    """Install an exact pre-current receipt using only the unchanged historical codec."""
    command = _command(record)
    manifest = prepare_frozen_plan(record, command, _NOW)
    candidate = PreparationCandidate(payload_json=canonical_json(manifest), validation="VALID",
        evidence_hash=manifest.version.evidence_hash, source_revision=record.source_revision,
        source_hash=record.source.binding_hash)
    review = PreparationReview(source_revision=record.source_revision,
        candidate_revision=record.candidate_revision + 1,
        candidate_hash=candidate.candidate_hash, evidence_hash=candidate.evidence_hash,
        confirmed=True, reviewed_at=_NOW)
    historical = PreparationRecord.model_validate(record.model_dump(mode="python") | dict(
        revision=record.revision + 1, status="REVIEWED", candidate=candidate, review=review,
        candidate_revision=record.candidate_revision + 1,
        review_revision=record.review_revision + 1, updated_at=_NOW))
    encoded = historical.model_dump_json()
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("UPDATE backtest_preparation SET document_json=? WHERE preparation_id=?",
                           (encoded, record.preparation_id))
        request_hash = _request_hash("REVIEW_AND_FREEZE", record.preparation_id, command)
        connection.execute("INSERT INTO backtest_preparation_idempotency VALUES(?,?,?)",
                           ("historical-review", request_hash, encoded))
    return command, historical, manifest


def test_historical_frozen_and_original_receipt_stay_readable_without_current_inputs(tmp_path):
    store, record, _, _, _ = _ready(tmp_path, with_inputs=False)
    command, historical, manifest = _historical_review_receipt(store, record)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)

    restarted = PreparationStore(store.database_path)
    assert frozen_preparation(restarted.get(record.preparation_id)) == manifest
    assert restarted.replay_review(record.preparation_id, command=command,
                                   idempotency_key="historical-review") == historical
    assert restarted.review_and_freeze(record.preparation_id, command=command,
                                       idempotency_key="historical-review") == historical
    assert historical.candidate.payload_json == canonical_json(manifest)
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before


def test_current_review_rechecks_complete_proof_inside_existing_transaction_and_replays_once(
    tmp_path, monkeypatch,
):
    store, record, _, _, _ = _ready(tmp_path)
    before = _stored_read(store, _api().require_current_preparation)
    actual_guard = _api().verify_current_review_candidate
    calls = []

    def guarded(connection, previous, proposed):
        assert connection.in_transaction is True
        assert store._read(connection, record.preparation_id) == previous == record
        result = actual_guard(connection, previous, proposed)
        calls.append(result)
        return result

    monkeypatch.setattr(_api(), "verify_current_review_candidate", guarded)
    command = _command(record)
    reviewed = store.review_and_freeze(record.preparation_id, command=command,
                                      idempotency_key="current-complete-review")
    assert reviewed.status == "REVIEWED" and calls == [before]
    assert frozen_preparation(reviewed).extraction_candidate_hash == record.candidate.candidate_hash
    assert _stored_read(store, _api().require_current_preparation) == before
    assert store.review_and_freeze(record.preparation_id, command=command,
        idempotency_key="current-complete-review") == reviewed
    assert calls == [before]


def _two_sources(tmp_path):
    first_id, second_id = UUID(int=201), UUID(int=202)
    source, mapping, original, inputs = _initial_loop_case(first_id)
    current_source, patch = delta("position.max_qty = 500", values={"max_qty": 500})
    store = PreparationStore(tmp_path / "current-two-sources.sqlite3", clock=lambda: _NOW)
    record = store.create(PlanCollectionPreparationInput(
        preparation_id="current-two-sources", sources=(source, current_source)),
        idempotency_key="create-two")

    def finish(item_index, record, identity, candidate, inputs):
        claim = collection_claim(record, item_index, generation=str(identity)).model_copy(
            update={"claimed_at": _NOW})
        running = store.start_attempt(record.preparation_id, expected_revision=record.revision,
            idempotency_key=f"start-{item_index}", work_claim=claim)
        calling = store.begin_call(record.preparation_id, generation=claim.generation,
            owner_id=claim.owner_id, expected_revision=running.revision)
        finished = store.finish_attempt(record.preparation_id, attempt_id=claim.generation,
            expected_revision=calling.revision, idempotency_key=f"finish-{item_index}",
            candidate=candidate, inputs=inputs, worker_owner_id=claim.owner_id)
        return store.clear_work_claim(record.preparation_id, generation=claim.generation,
                                       expected_revision=finished.revision)

    first = finish(0, record, first_id, original.to_preparation_candidate(), inputs)
    base = build_initial_review(original.draft, mapping, source)
    context = context_from_review(base, first.items[0].candidate.candidate_hash)
    raw = "\n" + json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n\t"
    output, derivation = expand_update_with_evidence(raw, current_source, context)
    extraction = collection_update_result(base, current_source, output, second_id, context)
    extraction = extraction.model_copy(update={"source_derivation": derivation})
    materialized = materialize_extraction(base, context.base_hash, current_source, extraction)
    current_inputs = extraction_inputs(materialized.extraction)
    completed = finish(1, first, second_id, materialized.to_preparation_candidate(), current_inputs)
    return store, completed, (inputs, current_inputs)


def test_current_two_source_chain_binds_actual_inputs_and_retains_parent_owners(tmp_path):
    store, record, inputs = _two_sources(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before, changes = _rows(connection), connection.total_changes
        actual = store._read(connection, record.preparation_id)

        proofs = _api().require_current_preparation(connection, actual)

        assert connection.total_changes == changes and _rows(connection) == before
    assert isinstance(proofs, tuple) and len(proofs) == 2
    assert all(proof.coverage_complete and proof.authority_granted is False for proof in proofs)
    first, second = proofs
    assert second.prefix[-1].assurance_hash == first.evidence_hash
    assert second.parent_hash == first.evidence_hash
    for index, proof in enumerate(proofs):
        item = record.items[index]
        assert proof.binding.item_index == index
        assert proof.binding.candidate_hash == item.candidate.candidate_hash
        assert proof.binding.attempt_id == item.attempts[-1].attempt_id
        assert proof.binding.inputs_hash == inputs[index].evidence_hash
    changed = next(owner for owner in second.owners if owner.path == "position.max_qty")
    assert changed.source_id == record.items[1].source.source_id
    inherited = next(owner for owner in second.owners if owner.path == "ordinary_rules[0].quantity")
    assert inherited.source_id == record.items[0].source.source_id
    assert inherited.origin == "BASE"
    assert len(second.source_refs) == 2
    assert "draft" not in json.loads(inputs[1].derivation.raw_json)
    assert inputs[1].derivation.base_hash == record.items[0].candidate.candidate_hash


def test_current_collection_review_keeps_exact_source_proofs_after_freeze(tmp_path):
    store, record, _ = _two_sources(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _api().require_current_preparation(connection, record)
    command = CollectionPreparationReviewCommand(expected_revision=record.revision,
        items=tuple(collection_item_binding(item) for item in record.items), confirmed=True,
        evidence="Explicit synthetic review of the complete two-source policy.")
    reviewed = store.review_and_freeze(record.preparation_id, command=command,
                                      idempotency_key="current-collection-review")
    assert reviewed.status == "REVIEWED" and len(frozen_collection(reviewed).items) == 2
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _api().require_current_preparation(connection, reviewed) == before


def test_current_review_guard_failure_rolls_back_candidate_and_original_receipt(
    tmp_path, monkeypatch,
):
    store, record, _, _, _ = _ready(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)
    actual_guard = _api().verify_current_review_candidate

    def fail_after_verification(connection, previous, proposed):
        assert actual_guard(connection, previous, proposed)
        raise RuntimeError("Synthetic review proof failure")

    monkeypatch.setattr(_api(), "verify_current_review_candidate", fail_after_verification)
    command = _command(record)
    with pytest.raises(RuntimeError, match="Synthetic review proof failure"):
        store.review_and_freeze(record.preparation_id, command=command,
                                idempotency_key="rollback-current-review")
    assert store.get(record.preparation_id) == record
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert _rows(connection) == before
    monkeypatch.setattr(_api(), "verify_current_review_candidate", actual_guard)
    assert store.review_and_freeze(record.preparation_id, command=command,
        idempotency_key="rollback-current-review").status == "REVIEWED"
