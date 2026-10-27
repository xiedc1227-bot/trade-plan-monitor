"""Actual preparation mutations atomically register supported human policy corrections."""

import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from tests.integration.test_plan_preparation_worker import collection_claim
from tests.integration.test_preparation_current_assurance import (
    _command,
    _ready,
    _rows,
    _two_sources,
)
from tests.integration.test_source_coverage_preparation_commit import (
    _NOW,
    _finish,
    _initial_loop_case,
    _running,
)
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_source_coverage_baseline import _append_as_context
from tests.unit.test_source_coverage_treatments import _supplemented_maximum

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
    OpeningAccountFacts,
    OpeningFact,
    validate_opening_evidence,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import MaterializedUpdateCandidate
from trade_plan_monitor.backtest import preparation_current_assurance as current
from trade_plan_monitor.backtest import preparation_human_assurance_store as human
from trade_plan_monitor.backtest import preparation_review_assurance_store as receipts
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import KnownLoopCash, LoopAccountInput
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    PlanCollectionPreparationInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    CollectionPreparationReviewCommand,
    collection_item_binding,
    correct_collection_candidate,
    frozen_preparation,
    prepare_frozen_plan,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.plan_validation import ValidationIssue
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _nullable_case(identity, *, with_inputs=True, source_value=None, after_max=300,
                   extra=None, source_id="first", available_at=None):
    draft, text, mapping, _ = _supplemented_maximum(source_value)
    if after_max != 300:
        draft = draft.model_copy(update={"position": draft.position.model_copy(update={
            "max_qty": after_max})})
        digest = daily_draft_content_sha256(draft)
        mapping = mapping.model_copy(update=dict(candidate_content_hash=digest,
            bindings=tuple(binding.model_copy(update={"value": after_max})
                if binding.path == "position.max_qty" else binding for binding in mapping.bindings),
            supplements=tuple(supplement.model_copy(update=dict(value=after_max,
                candidate_content_hash=digest)) for supplement in mapping.supplements)))
    account_text = "账户记录：当前持仓0股。"
    for fragment, role in ((account_text, "ACCOUNT"),
                           ("历史记录：2026-08-01买入100股。", "HISTORICAL")):
        text, mapping = _append_as_context(text, mapping, fragment, semantic_role=role,
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Exact original record"))
    if extra:
        text, mapping = _append_as_context(text, mapping, extra, semantic_role="COMMENTARY",
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Human says background"))
    source = PreparationSource(source_id=source_id, text=text,
        available_at=available_at or at(19),
        effective_trade_date=(available_at or at(19)).date())
    before_value = source_value if type(source_value) is int else None
    before_draft = draft.model_copy(update={"position": draft.position.model_copy(update={
        "max_qty": before_value})})
    ceiling_ids = tuple(clause.clause_id for clause in mapping.clauses
                        if "position.max_qty" in clause.paths)
    before_mapping = mapping.model_copy(update=dict(
        candidate_content_hash=daily_draft_content_sha256(before_draft), supplements=(),
        clauses=tuple(clause.model_copy(update=dict(disposition="UNRESOLVED", paths=(),
            reason="The source explicitly leaves this maximum missing."))
            if before_value is None and clause.clause_id in ceiling_ids else clause
            for clause in mapping.clauses),
        bindings=tuple(binding.model_copy(update=dict(value=before_value, origin="SOURCE",
            clause_ids=ceiling_ids, supplement_id=None)) if binding.path == "position.max_qty"
            else binding for binding in mapping.bindings
            if before_value is not None or binding.path != "position.max_qty")))
    start = text.index(account_text)
    opening = OpeningAccountFacts(inventory_quantity=OpeningFact(value=0, start=start,
        end=start + len(account_text), excerpt=account_text),
        lots=(), cash_fen=None, snapshot_at=None)
    validate_opening_evidence(opening, text)
    output = LoopPlanExtractionOutput(schema_version="monitor-loop-extraction-v1",
        draft=before_draft, clauses=before_mapping.clauses, bindings=before_mapping.bindings,
        assumptions=(), warnings=(), opening_account=opening)
    reviewed = output.review(text)
    result = LoopPlanExtractionResult(request_id=identity, provider_id=UUID(int=2),
        model="synthetic-no-provider-call", prompt_version="monitor-loop-extract-v1",
        source_id=source.source_id,
        source_text_sha256=source.source_hash, source_binding_hash=source.binding_hash,
        authored_at=source.authored_at, available_at=source.available_at,
        effective_trade_date=source.effective_trade_date, draft=before_draft,
        daily_mapping=reviewed.mapping, opening_account=opening,
        validation_issues=tuple(ValidationIssue(code=issue.code, path=issue.path,
            severity="ERROR", message=issue.reason, activationBlocking=True)
            for issue in reviewed.issues), assumptions=(), warnings=(), usage=None,
        status=PlanExtractionStatus.SUCCEEDED,
        evidence_hash=sha256(canonical_json(dict(domain="monitor-loop-extraction-evidence-v1",
            source_binding_hash=source.binding_hash, plan_mapping=reviewed.mapping,
            opening_account=opening)).encode()).hexdigest())
    inputs = None
    if with_inputs:
        image = before_draft.model_dump(mode="json")
        trace = capture_normalization(image, image, text)
        coverage = assess_source_coverage(before_draft, reviewed.mapping, text,
            normalization=trace, origin="AI_NEW")
        raw = "\n" + json.dumps(output.model_dump(mode="json"), ensure_ascii=False,
                                 indent=2) + "\n\t"
        derivation = SourceDerivationEvidence.build(kind="FULL_DRAFT",
            source_hash=source.source_hash,
            raw_json=raw, context_json=None, base_hash=None,
            stages=(DerivationStage.build(phase="SOURCE_NORMALIZED",
                output_json=canonical(output.model_dump(mode="json"))),))
        inputs = CoverageInputs.build(source_hash=source.source_hash,
            source_binding_hash=source.binding_hash, initial_coverage=coverage,
            normalization=trace, derivation=derivation)
    return source, result, inputs, draft, mapping


def _single(tmp_path, **options):
    source, result, inputs, draft, mapping = _nullable_case(UUID(int=101), **options)
    store, running, candidate, _ = _running(tmp_path, owned=True,
        case=(inputs, source, result.to_preparation_candidate()))
    record = _finish(store, running, candidate, inputs)
    record = store.clear_work_claim(record.preparation_id,
        generation=record.work_claim.generation, expected_revision=record.revision)
    command = _command(record).model_copy(update={"draft": draft, "mapping": mapping})
    return store, record, command, inputs


def _finish_item(store, record, index, result, inputs):
    claim = collection_claim(record, index, generation=str(result.request_id)).model_copy(
        update={"claimed_at": _NOW, "base_hash": record.items[index].base_hash
                if record.items[index].independent else (
                    record.items[index - 1].candidate.candidate_hash if index else None)})
    running = store.start_attempt(record.preparation_id, expected_revision=record.revision,
        idempotency_key=f"start-{index}", work_claim=claim)
    calling = store.begin_call(record.preparation_id, generation=claim.generation,
        owner_id=claim.owner_id, expected_revision=running.revision)
    finished = store.finish_attempt(record.preparation_id, attempt_id=claim.generation,
        expected_revision=calling.revision, idempotency_key=f"finish-{index}",
        candidate=result.to_preparation_candidate(), inputs=inputs, worker_owner_id=claim.owner_id)
    return store.clear_work_claim(record.preparation_id, generation=claim.generation,
                                   expected_revision=finished.revision)


def _collection(tmp_path, *, independent=False, **options):
    source, result, inputs, draft, mapping = _nullable_case(UUID(int=202 if independent else 201),
        source_id="second" if independent else "first",
        available_at=None if not independent else at(19) + timedelta(days=1), **options)
    first = _initial_loop_case(UUID(int=201)) if independent else None
    store = PreparationStore(tmp_path / "human-collection.sqlite3", clock=lambda: _NOW)
    record = store.create(PlanCollectionPreparationInput(preparation_id="human-collection",
        sources=(first[0], source) if independent else (source,)), idempotency_key="create")
    index = int(independent)
    if independent:
        record = _finish_item(store, record, 0, first[2], first[3])
        # This is a server-owned independent source fixture, not client authority or
        # a substitute for the separately planned reviewed-library lineage adapter.
        record = CollectionPreparationRecord.model_validate(record.model_dump(mode="python") | {
            "items": (record.items[0], record.items[1].model_copy(update={"independent": True})),
        })
        with closing(sqlite3.connect(store.database_path)) as connection, connection:
            connection.execute("UPDATE backtest_preparation SET document_json=? "
                "WHERE preparation_id=?", (record.model_dump_json(), record.preparation_id))
    record = _finish_item(store, record, index, result, inputs)
    command = CollectionItemCorrectionCommand(expected_revision=record.revision,
        binding=collection_item_binding(record.items[index]), confirmed=True,
        evidence="Explicit registered parameter correction for this actual source.",
        draft=draft, mapping=mapping)
    return store, record, command, inputs, index


def _snapshot(store):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return _rows(connection)


def _require(store, record):
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = _rows(connection)
        try:
            return current.require_current_reviewed_preparation(connection, record)
        finally:
            assert _rows(connection) == before and connection.total_changes == 0


def test_actual_nullable_loop_fixture_is_unresolved_but_old_human_review_can_freeze(tmp_path):
    store, record, command, inputs = _single(tmp_path)
    original = LoopPlanExtractionResult.model_validate_json(record.candidate.payload_json)
    assert original.draft.position.max_qty is None
    assert original.validation_issues and record.candidate.validation == "UNRESOLVED"
    assert any("position" in issue.path for issue in original.validation_issues)
    assert inputs.initial_coverage.coverage_complete is False
    assert original.opening_account.inventory_quantity.value == 0
    assert prepare_frozen_plan(record, command, _NOW).version.snapshot.position.max_qty == 300
    captured = store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id)
    assert captured.candidate_json == record.candidate.payload_json


@pytest.mark.parametrize("with_inputs", [True, False], ids=["private_input", "missing_input"])
def test_single_registered_supplement_commits_human_and_current_review_with_original_input(
    tmp_path, with_inputs,
):
    store, record, command, _ = _single(tmp_path, with_inputs=with_inputs)
    original = store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id)

    reviewed = store.review_and_freeze(record.preparation_id, command=command,
                                      idempotency_key="human-review")

    receipt = _require(store, reviewed)
    assert frozen_preparation(reviewed).version.snapshot.position.max_qty == 300
    assert receipt.proofs[0].source_assessment.origin == "HUMAN"
    assert not receipt.proofs[0].current_automatic_fidelity_verified
    assert receipt.authority_granted is False
    with closing(sqlite3.connect(store.database_path)) as connection:
        operation = human.human_operation(connection, reviewed.preparation_id, 0,
                                           reviewed.candidate_revision)
        assert operation is not None
        assert operation.original_input_state == ("PRESENT" if with_inputs else "MISSING")
        assert operation.original_candidate.payload_json == record.candidate.payload_json
        kinds = [row[0] for row in connection.execute("SELECT kind FROM "
            "backtest_preparation_assurance ORDER BY kind")]
        assert kinds == (["HUMAN_OPERATION", "INPUT", "REVIEW"] if with_inputs
                         else ["HUMAN_OPERATION", "REVIEW"])
    assert store.input_evidence(record.preparation_id, record.attempts[-1].attempt_id) == original
    assert reviewed.candidate.payload_json != record.candidate.payload_json


def test_collection_correction_needs_explicit_account_and_whole_review_for_current_receipt(
    tmp_path,
):
    store, record, command, _, index = _collection(tmp_path)
    assert correct_collection_candidate(record, command)[1].draft.position.max_qty == 300
    attempt_id = record.items[index].attempts[-1].attempt_id
    original = store.input_evidence(record.preparation_id, attempt_id)

    corrected = store.correct_collection_item(record.preparation_id, command=command,
                                              idempotency_key="human-correct")

    assert corrected.review is None and corrected.status == "CANDIDATE"
    with closing(sqlite3.connect(store.database_path)) as connection:
        operation = human.human_operation(connection, corrected.preparation_id, index,
                                           corrected.items[index].candidate_revision)
        assert operation is not None
        proof, = current.read_current_assurance(connection, corrected)
        assert proof.source_assessment.origin == "HUMAN"
        assert receipts.review_assurance(connection, corrected.preparation_id,
                                         corrected.review_revision) is None
    with pytest.raises(PreparationConflictError):
        _require(store, corrected)
    account = LoopAccountInput(snapshot_at=corrected.items[0].source.execution_available_at,
        inventory_known=True, cash=KnownLoopCash(balance_fen=1000000), lots=(), opening_mark=None,
        evidence="Explicit human account review: zero shares and cash 1000000 fen.")
    whole = CollectionPreparationReviewCommand(expected_revision=corrected.revision,
        items=tuple(collection_item_binding(item) for item in corrected.items), confirmed=True,
        evidence="Explicit review of every corrected source and the actual opening account.",
        account=account)
    reviewed = store.review_and_freeze(corrected.preparation_id, command=whole,
                                      idempotency_key="human-whole-review")
    assert _require(store, reviewed).proofs
    assert store.input_evidence(record.preparation_id, attempt_id) == original


@pytest.mark.parametrize("options", [
    {"extra": "Only buy when turnover exceeds 3 percent."},
    {"source_value": 300, "after_max": 500},
], ids=["unknown_background", "explicit_nonnull_limit"])
def test_human_correction_cannot_waive_source_and_rolls_back_every_row(tmp_path, options):
    store, record, command, _, _ = _collection(tmp_path, **options)
    before = _snapshot(store)

    with pytest.raises(PreparationConflictError) as error:
        store.correct_collection_item(record.preparation_id, command=command,
                                      idempotency_key="must-block-correction")

    assert error.value.code == "SOURCE_COVERAGE_REQUIRED"
    assert _snapshot(store) == before and store.get(record.preparation_id) == record


def test_human_operation_failure_rolls_back_freeze_and_both_receipts(tmp_path, monkeypatch):
    store, record, command, _ = _single(tmp_path)
    before, calls = _snapshot(store), []
    original_save = human.save_human_operation

    def fail_after_save(connection, operation):
        assert connection.in_transaction
        saved = original_save(connection, operation)
        calls.append(saved)
        raise RuntimeError("Injected human operation persistence failure")

    monkeypatch.setattr(human, "save_human_operation", fail_after_save)
    with pytest.raises(RuntimeError, match="Injected human operation persistence failure"):
        store.review_and_freeze(record.preparation_id, command=command,
                                idempotency_key="human-review")
    assert len(calls) == 1
    assert _snapshot(store) == before and store.get(record.preparation_id) == record


def test_independent_later_item_uses_initial_human_correction_and_preserves_prefix(tmp_path):
    store, record, command, _, index = _collection(tmp_path, independent=True)
    assert index == 1 and record.items[1].independent and record.items[1].base_hash is None

    corrected = store.correct_collection_item(record.preparation_id, command=command,
                                              idempotency_key="human-independent-correct")

    assert corrected.items[0] == record.items[0]
    assert corrected.items[1].independent and corrected.review is None
    with closing(sqlite3.connect(store.database_path)) as connection:
        proofs = current.read_current_assurance(connection, corrected)
        assert proofs[1].source_assessment.origin == "HUMAN"
        assert proofs[1].parent_hash is None and len(proofs[1].prefix) == 1
        assert proofs[1].coverage_complete and proofs[1].authority_granted is False


def test_repeated_correction_retains_original_input_and_replays_original_human_receipt(tmp_path):
    store, record, first_command, _, index = _collection(tmp_path)
    attempt_id = record.items[index].attempts[-1].attempt_id
    original = store.input_evidence(record.preparation_id, attempt_id)
    first = store.correct_collection_item(record.preparation_id, command=first_command,
                                         idempotency_key="first-human")
    with closing(sqlite3.connect(store.database_path)) as connection:
        first_op = human.human_operation(connection, first.preparation_id, index,
                                         first.items[index].candidate_revision)
    mapping = first_command.mapping.model_copy(update={"supplements": tuple(
        row.model_copy(update={"reason": row.reason + " Explicitly reassessed again."})
        for row in first_command.mapping.supplements)})
    second_command = first_command.model_copy(update=dict(expected_revision=first.revision,
        binding=collection_item_binding(first.items[index]), mapping=mapping,
        evidence="A second explicit human parameter review of the same exact source."))

    second = store.correct_collection_item(first.preparation_id, command=second_command,
                                           idempotency_key="second-human")

    with closing(sqlite3.connect(store.database_path)) as connection:
        second_op = human.human_operation(connection, second.preparation_id, index,
                                          second.items[index].candidate_revision)
        assert second_op.previous_human_ref == first_op.evidence_hash
        assert second_op.original_candidate == first_op.original_candidate
        assert second_op.original_candidate_revision == first_op.original_candidate_revision
        assert current.read_current_assurance(connection, second)[0].coverage_complete
    before_replay = _snapshot(store)
    assert store.correct_collection_item(record.preparation_id, command=first_command,
                                         idempotency_key="first-human") == first
    assert _snapshot(store) == before_replay
    assert store.input_evidence(record.preparation_id, attempt_id) == original


@pytest.mark.parametrize("field", ["request_hash", "response_json"])
def test_actual_command_response_binding_rejects_self_signed_substitution(tmp_path, field):
    store, before, command, _ = _single(tmp_path)
    reviewed = store.review_and_freeze(before.preparation_id, command=command,
                                      idempotency_key="human-review")
    assert _require(store, reviewed)
    replacement = ("f" * 64 if field == "request_hash" else reviewed.model_copy(update={
        "updated_at": reviewed.updated_at + timedelta(seconds=1),
    }).model_dump_json())
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute(f"UPDATE backtest_preparation_idempotency SET {field}=? "
                           "WHERE idempotency_key='human-review'", (replacement,))

    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)

    assert error.value.code == "SOURCE_COVERAGE_STALE"


@pytest.mark.parametrize("explicit_unchanged", [False, True])
def test_account_or_unchanged_policy_cannot_reclassify_missing_ai_input_as_human(
    tmp_path, explicit_unchanged,
):
    store, record, result, _, mapping = _ready(tmp_path, with_inputs=False)
    command = _command(record)
    account = LoopAccountInput(snapshot_at=record.source.execution_available_at,
        inventory_known=True, cash=KnownLoopCash(balance_fen=1000000), lots=(), opening_mark=None,
        evidence="Only the opening account is explicitly reviewed; source policy is unchanged.")
    command = command.model_copy(update={"account": account})
    if explicit_unchanged:
        command = command.model_copy(update={"draft": result.draft, "mapping": mapping})
    before = _snapshot(store)

    with pytest.raises(PreparationConflictError) as error:
        store.review_and_freeze(record.preparation_id, command=command,
                                idempotency_key="no-human-policy-change")

    assert error.value.code == "SOURCE_COVERAGE_REQUIRED" and _snapshot(store) == before


def test_current_review_failure_rolls_back_both_evidence_kinds(tmp_path, monkeypatch):
    store, record, command, _ = _single(tmp_path)
    before = _snapshot(store)
    actual_save, calls = receipts.save_review_assurance, []

    def fail_after_review(connection, receipt):
        assert connection.in_transaction
        calls.append(actual_save(connection, receipt))
        raise RuntimeError("Injected review failure after human evidence")

    monkeypatch.setattr(receipts, "save_review_assurance", fail_after_review)
    with pytest.raises(RuntimeError, match="Injected review failure after human evidence"):
        store.review_and_freeze(record.preparation_id, command=command,
                                idempotency_key="human-review")
    assert len(calls) == 1 and _snapshot(store) == before


def test_correction_uses_only_its_selected_prefix_and_invalidates_later_human_authority(tmp_path):
    store, record, command, _, _ = _collection(tmp_path, independent=True)
    later = store.correct_collection_item(record.preparation_id, command=command,
                                         idempotency_key="later-human")
    raw_first = LoopPlanExtractionResult.model_validate_json(later.items[0].candidate.payload_json)
    first_command = CollectionItemCorrectionCommand(expected_revision=later.revision,
        binding=collection_item_binding(later.items[0]), confirmed=True,
        evidence="Explicit re-evaluation of the first complete source; reconsider later sources.",
        draft=raw_first.draft, mapping=raw_first.daily_mapping)

    corrected = store.correct_collection_item(later.preparation_id, command=first_command,
                                              idempotency_key="earlier-human")

    assert corrected.items[1].candidate is None and corrected.items[1].attempts == ()
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert current.read_current_assurance_prefix(connection, corrected, 1)[0].coverage_complete
        with pytest.raises(PreparationConflictError):
            current.read_current_assurance(connection, corrected)
        assert human.human_operation(connection, later.preparation_id, 1,
                                     later.items[1].candidate_revision) is not None


def _twice_corrected(tmp_path):
    store, before, command, _, _ = _collection(tmp_path)
    first = store.correct_collection_item(before.preparation_id, command=command,
                                         idempotency_key="first-human")
    second_command = command.model_copy(update=dict(expected_revision=first.revision,
        binding=collection_item_binding(first.items[0]),
        evidence="A second explicit correction with the exact actual original checkpoint."))
    second = store.correct_collection_item(before.preparation_id, command=second_command,
                                           idempotency_key="second-human")
    with closing(sqlite3.connect(store.database_path)) as connection:
        prior = human.human_operation(connection, first.preparation_id, 0,
                                      first.items[0].candidate_revision)
    return store, first, second, prior


def _replace_human(store, operation, **updates):
    values = {key: getattr(operation, key) for key in type(operation).model_fields
              if key not in {"evidence_hash", "evidence_key"}}
    replacement = PreparationHumanOperation.build(**(values | updates))
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute("UPDATE backtest_preparation_assurance "
            "SET payload_json=?,evidence_hash=? "
            "WHERE evidence_key=?", (canonical(replacement.model_dump(mode="json")),
                                     replacement.evidence_hash, operation.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
    return replacement


def test_previous_human_prefix_cannot_be_substituted_by_a_valid_selfhash(tmp_path):
    store, _, second, prior = _twice_corrected(tmp_path)
    prefix = (PrefixAssuranceRef(binding=prior.assessment_binding, assurance_hash="f" * 64),)
    replacement = _replace_human(store, prior, prefix=prefix,
        prefix_hash=source_prefix_hash(prefix, prior.assessment_binding), parent_hash="f" * 64)
    with closing(sqlite3.connect(store.database_path)) as connection:
        current_op = human.human_operation(connection, second.preparation_id, 0,
                                           second.items[0].candidate_revision)
    # Keep the new link self-consistent too. Actual command responses and source
    # policy are unchanged; only the claimed previous prefix was substituted.
    _replace_human(store, current_op, previous_human_ref=replacement.evidence_hash)

    with closing(sqlite3.connect(store.database_path)) as connection:
        with pytest.raises(PreparationConflictError) as error:
            current.read_current_assurance(connection, second)
    assert error.value.code == "SOURCE_COVERAGE_STALE"


@pytest.mark.parametrize("mutation", ["previous_request", "previous_response", "before_candidate"])
def test_previous_human_link_requires_real_response_and_candidate_transition(tmp_path, mutation):
    store, first, second, _ = _twice_corrected(tmp_path)
    if mutation == "before_candidate":
        with closing(sqlite3.connect(store.database_path)) as connection:
            operation = human.human_operation(connection, second.preparation_id, 0,
                                               second.items[0].candidate_revision)
        _replace_human(store, operation, before_candidate_hash="f" * 64)
    else:
        column, value = ("request_hash", "f" * 64) if mutation == "previous_request" else (
            "response_json", first.model_copy(update={
                "updated_at": first.updated_at + timedelta(seconds=1),
            }).model_dump_json())
        with closing(sqlite3.connect(store.database_path)) as connection, connection:
            connection.execute(f"UPDATE backtest_preparation_idempotency SET {column}=? "
                               "WHERE idempotency_key='first-human'", (value,))
    with closing(sqlite3.connect(store.database_path)) as connection:
        with pytest.raises(PreparationConflictError) as error:
            current.read_current_assurance(connection, second)
    assert error.value.code == "SOURCE_COVERAGE_STALE"


@pytest.mark.parametrize("mutation", ["attempt", "source_metadata"])
def test_missing_input_human_proof_requires_actual_attempt_and_source_coords(tmp_path, mutation):
    store, before, command, _ = _single(tmp_path, with_inputs=False)
    reviewed = store.review_and_freeze(before.preparation_id, command=command,
                                      idempotency_key="missing-input-human")
    if mutation == "attempt":
        with closing(sqlite3.connect(store.database_path)) as connection:
            operation = human.human_operation(connection, reviewed.preparation_id, 0,
                                               reviewed.candidate_revision)
        binding = operation.assessment_binding.model_copy(update={"attempt_id": "not-the-attempt"})
        _replace_human(store, operation, attempt_id=binding.attempt_id,
            assessment_binding=binding, prefix_hash=source_prefix_hash((), binding))
    else:
        store.edit_source(reviewed.preparation_id, expected_revision=reviewed.revision,
            idempotency_key="change-metadata", source=reviewed.source.model_copy(update={
                "available_at": reviewed.source.available_at + timedelta(minutes=1),
            }))
    with pytest.raises(PreparationConflictError) as error:
        _require(store, reviewed)
    assert error.value.code == "SOURCE_COVERAGE_STALE"


def test_dependent_delta_correction_keeps_actual_parent_and_original_provider_input(tmp_path):
    store, record, inputs = _two_sources(tmp_path)
    item = record.items[1]
    original = MaterializedUpdateCandidate.model_validate_json(item.candidate.payload_json)
    output = original.extraction.output
    command = CollectionItemCorrectionCommand(expected_revision=record.revision,
        binding=collection_item_binding(item), confirmed=True,
        evidence="Explicit human reassessment of the exact source update and inherited parent.",
        update=output, mapping=output.review(item.source.text).mapping)
    captured = store.input_evidence(record.preparation_id, item.attempts[-1].attempt_id)

    corrected = store.correct_collection_item(record.preparation_id, command=command,
                                              idempotency_key="human-delta")

    with closing(sqlite3.connect(store.database_path)) as connection:
        parent, proof = current.read_current_assurance(connection, corrected)
        assert proof.coverage_complete and proof.source_assessment.origin == "HUMAN"
        assert proof.parent_hash == parent.evidence_hash
        assert proof.source_assessment.automatic_fidelity_verified is False
        operation = human.human_operation(connection, corrected.preparation_id, 1,
                                           corrected.items[1].candidate_revision)
        assert operation.original_candidate.payload_json == item.candidate.payload_json
        assert operation.assessment_binding.inputs_hash == inputs[1].evidence_hash
    assert store.input_evidence(record.preparation_id, item.attempts[-1].attempt_id) == captured
    assert corrected.review is None
