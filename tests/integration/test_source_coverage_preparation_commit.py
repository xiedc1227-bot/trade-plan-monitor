"""Attempt completion commits its exact raw evidence with the existing candidate receipt."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_plan_preparation_worker import (
    collection_claim,
    collection_update_result,
)
from tests.integration.test_source_coverage_preparation_storage import _inputs, _legacy, _rebind
from tests.integration.test_source_treatment_review_api import literal_draft
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_coverage_baseline import _append_as_context

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
    OpeningAccountFacts,
    OpeningFact,
    validate_opening_evidence,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import (
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest import preparation_assurance_store, preparation_store
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.preparation_models import (
    PlanCollectionPreparationInput,
    PreparationCandidateInput,
    PreparationSource,
    PreparationWorkClaim,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    collection_item_binding,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationCallOutcome
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _running(tmp_path, *, owned=False, case=None):
    inputs, source = _inputs() if case is None else case[:2]
    store = PreparationStore(tmp_path / "finish-with-evidence.sqlite3", clock=lambda: _NOW)
    initial = store.create(SinglePlanPreparationInput(
        preparation_id="finish-with-evidence", sources=(source,),
    ), idempotency_key="create-original")
    claim = None if not owned else PreparationWorkClaim(
        generation=str(UUID(int=101)), owner_id="test-completion-owner",
        source_revision=initial.source_revision, source_hash=initial.source.binding_hash,
        admission_key="test-completion-reservation", intent_hash="a" * 64,
        claimed_at=_NOW, intent_json='{"synthetic":"no provider call"}', phase="READY",
    )
    running = store.start_attempt(
        initial.preparation_id, expected_revision=initial.revision,
        idempotency_key="start-original", work_claim=claim,
    )
    if owned:
        running = store.begin_call(
            initial.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
            expected_revision=running.revision,
        )
    candidate = case[2] if case is not None else PreparationCandidateInput(
        payload_json=inputs.derivation.stages[-1].output_json, validation="VALID",
        evidence_hash=inputs.initial_coverage.evidence_hash, issues=(),
    )
    return store, running, candidate, inputs


def _finish(store, running, candidate, inputs):
    return store.finish_attempt(
        running.preparation_id, attempt_id=running.attempts[-1].attempt_id,
        expected_revision=running.revision, idempotency_key="finish-original",
        candidate=candidate, inputs=inputs,
        worker_owner_id=None if running.work_claim is None else running.work_claim.owner_id,
    )


def _receipts(store):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return connection.execute(
            "SELECT * FROM backtest_preparation_idempotency ORDER BY idempotency_key"
        ).fetchall()


def test_finish_attempt_persists_inputs_bound_to_its_actual_source_and_candidate(tmp_path):
    store, running, candidate, inputs = _running(tmp_path)
    attempt_id = running.attempts[-1].attempt_id

    finished = store.finish_attempt(
        running.preparation_id, attempt_id=attempt_id, expected_revision=running.revision,
        idempotency_key="finish-original", candidate=candidate, inputs=inputs,
    )

    assert finished.status == "CANDIDATE" and finished.attempts[-1].status == "SUCCEEDED"
    proof = store.input_evidence(running.preparation_id, attempt_id)
    assert proof is not None
    assert proof.preparation_id == running.preparation_id
    assert proof.item_index == 0 and proof.attempt_id == attempt_id
    assert proof.source_binding_hash == running.source.binding_hash
    assert proof.candidate_hash == finished.candidate.candidate_hash
    assert proof.candidate_json == finished.candidate.payload_json
    assert proof.inputs == inputs and proof.created_at == _NOW
    assert proof.authority_granted is False


def test_finish_without_raw_inputs_preserves_historical_candidate_without_inventing_proof(tmp_path):
    store, running, candidate, _ = _running(tmp_path)

    finished = _finish(store, running, candidate, None)

    assert finished.status == "CANDIDATE"
    assert finished.candidate.payload_json == candidate.payload_json
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) is None


def test_same_finish_replay_reuses_original_record_and_exact_private_evidence(tmp_path):
    store, running, candidate, inputs = _running(tmp_path)
    finished = _finish(store, running, candidate, inputs)
    proof = store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id)
    receipts = _receipts(store)

    assert _finish(store, running, candidate, inputs) == finished

    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) == proof


def test_same_finish_key_with_new_private_raw_bytes_conflicts_without_replacing_anything(tmp_path):
    store, running, candidate, inputs = _running(tmp_path)
    finished = _finish(store, running, candidate, inputs)
    proof = store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id)
    changed, _ = _inputs(suffix="\n")
    assert changed.source_binding_hash == inputs.source_binding_hash
    assert changed.evidence_hash != inputs.evidence_hash
    receipts = _receipts(store)

    with pytest.raises(PreparationConflictError):
        _finish(store, running, candidate, changed)

    assert store.get(running.preparation_id) == finished
    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) == proof


@pytest.mark.parametrize("mutation", ["source-text", "source-binding", "missing-binding"])
def test_finish_rejects_input_for_another_actual_source_without_ending_the_attempt(
    tmp_path, mutation,
):
    store, running, candidate, inputs = _running(tmp_path)
    if mutation == "source-text":
        changed = CoverageInputs.build(source_hash="f" * 64,
                                       source_binding_hash=inputs.source_binding_hash)
    else:
        changed = _rebind(inputs, None if mutation == "missing-binding" else "f" * 64)
    receipts = _receipts(store)

    with pytest.raises(ValueError):
        _finish(store, running, candidate, changed)

    assert store.get(running.preparation_id) == running
    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) is None


def test_auxiliary_insert_then_failure_rolls_back_candidate_attempt_receipt_and_raw(
    tmp_path, monkeypatch,
):
    store, running, candidate, inputs = _running(tmp_path)
    original = preparation_assurance_store.save_input_evidence
    receipts, calls = _receipts(store), []

    def fail_after_insert(connection, evidence):
        result = original(connection, evidence)
        calls.append(result)
        raise RuntimeError("injected after real raw evidence insert")

    monkeypatch.setattr(preparation_assurance_store, "save_input_evidence", fail_after_insert)
    if getattr(preparation_store, "save_input_evidence", None) is original:
        monkeypatch.setattr(preparation_store, "save_input_evidence", fail_after_insert)

    with pytest.raises(RuntimeError, match="injected after real raw evidence insert"):
        _finish(store, running, candidate, inputs)

    assert len(calls) == 1
    assert store.get(running.preparation_id) == running
    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) is None


def test_old_receipt_insert_failure_rolls_back_both_old_candidate_and_auxiliary_proof(tmp_path):
    store, running, candidate, inputs = _running(tmp_path)
    receipts = _receipts(store)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER test_reject_finish_receipt BEFORE INSERT "
            "ON backtest_preparation_idempotency WHEN NEW.idempotency_key='finish-original' "
            "BEGIN SELECT RAISE(ABORT,'test-only receipt failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        _finish(store, running, candidate, inputs)

    assert store.get(running.preparation_id) == running
    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) is None


def test_old_store_with_inputs_requires_upgrade_and_leaves_the_attempt_running(tmp_path):
    path = tmp_path / "old-preparation.sqlite3"
    initial = _legacy(path)
    store = PreparationStore(path, clock=lambda: _NOW)
    running = store.start_attempt(initial.preparation_id, expected_revision=initial.revision,
                                  idempotency_key="start-old-attempt")
    inputs, _ = _inputs()
    candidate = PreparationCandidateInput(
        payload_json=inputs.derivation.stages[-1].output_json, validation="VALID",
        evidence_hash=inputs.initial_coverage.evidence_hash, issues=(),
    )
    receipts = _receipts(store)

    with pytest.raises(PreparationConflictError) as error:
        _finish(store, running, candidate, inputs)

    assert error.value.code == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
    assert store.get(running.preparation_id) == running
    assert _receipts(store) == receipts
    assert store.input_evidence(running.preparation_id, running.attempts[-1].attempt_id) is None


def test_restart_reads_the_exact_raw_bytes_without_rewriting_candidate_payload(tmp_path):
    store, running, candidate, inputs = _running(tmp_path)
    finished = _finish(store, running, candidate, inputs)
    with closing(sqlite3.connect(store.database_path)) as connection:
        before = connection.execute("SELECT * FROM backtest_preparation").fetchall()

    restarted = PreparationStore(store.database_path)
    restored = restarted.get(running.preparation_id)
    proof = restarted.input_evidence(running.preparation_id, running.attempts[-1].attempt_id)

    assert restored == finished
    assert restored.candidate.payload_json == candidate.payload_json
    assert proof.candidate_json == restored.candidate.payload_json
    assert proof.inputs.derivation.raw_json == inputs.derivation.raw_json
    assert proof.inputs.derivation.raw_json.endswith("\n\t")
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert connection.execute("SELECT * FROM backtest_preparation").fetchall() == before


def _completion_service(store):
    service = object.__new__(PreparationService)
    service._store = store
    service._extractor = SimpleNamespace(max_repairs=0)
    service._closed = False
    released = []
    service._release = released.append
    return service, released


def test_service_completion_forwards_successful_candidate_private_inputs(tmp_path):
    store, running, candidate, inputs = _running(tmp_path, owned=True)
    service, released = _completion_service(store)

    service._complete(running, PreparationCallOutcome(candidate=candidate, inputs=inputs),
                      retries=0, token=CancellationToken())

    proof = PreparationStore(store.database_path).input_evidence(
        running.preparation_id, running.work_claim.generation,
    )
    assert proof is not None and proof.inputs == inputs
    assert len(released) == 1 and released[0].work_claim.phase == "ENDED"
    assert proof.candidate_hash == released[0].candidate.candidate_hash


@pytest.mark.parametrize("unknown", [False, True], ids=["classified-error", "unknown-timeout"])
def test_service_failure_or_unknown_outcome_never_persists_a_successful_raw_proof(
    tmp_path, unknown,
):
    store, running, _, inputs = _running(tmp_path, owned=True)
    service, released = _completion_service(store)
    outcome = (PreparationCallOutcome(unknown=True, inputs=inputs) if unknown else
               PreparationCallOutcome(error_code="INVALID_OUTPUT", inputs=inputs))

    service._complete(running, outcome, retries=0, token=CancellationToken())

    restored = store.get(running.preparation_id)
    assert restored.candidate is None
    assert store.input_evidence(running.preparation_id, running.work_claim.generation) is None
    if unknown:
        assert restored.work_claim.phase == "UNKNOWN" and released == []
    else:
        assert restored.status == "FAILED" and len(released) == 1


def _initial_loop_case(attempt_id):
    """Build one schema-valid synthetic response and its full original, unpruned map."""
    draft = literal_draft(complete=True)
    text, mapping = source_mapping(draft)
    account_text = "账户记录：当前持仓0股。"
    history = "历史记录：2026-08-01买入100股。"
    for extra, role in ((account_text, "ACCOUNT"), (history, "HISTORICAL")):
        text, mapping = _append_as_context(
            text, mapping, extra, semantic_role=role, misclassification={
                "disposition": "CONTEXT", "paths": (),
                "reason": "Exact original non-policy record.",
            },
        )
    source = PreparationSource(source_id="first", text=text, available_at=at(19),
                               effective_trade_date=at(19).date())
    start = text.index(account_text)
    opening = OpeningAccountFacts(
        inventory_quantity=OpeningFact(value=0, start=start, end=start + len(account_text),
                                       excerpt=account_text),
        lots=(), cash_fen=None, snapshot_at=None,
    )
    validate_opening_evidence(opening, text)
    output = LoopPlanExtractionOutput(
        schema_version="monitor-loop-extraction-v1", draft=draft, clauses=mapping.clauses,
        bindings=mapping.bindings, assumptions=(), warnings=(), opening_account=opening,
    )
    raw_json = "\n" + json.dumps(output.model_dump(mode="json"),
                                 ensure_ascii=False, indent=2) + "\n\t"
    assert LoopPlanExtractionOutput.model_validate_json(raw_json) == output
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    coverage = assess_source_coverage(draft, mapping, text, normalization=trace, origin="AI_NEW")
    assert coverage.coverage_complete is True
    derivation = SourceDerivationEvidence.build(
        kind="FULL_DRAFT", source_hash=source.source_hash, raw_json=raw_json,
        context_json=None, base_hash=None, stages=(DerivationStage.build(
            phase="SOURCE_NORMALIZED", output_json=canonical(output.model_dump(mode="json")),
        ),),
    )
    inputs = CoverageInputs.build(
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        initial_coverage=coverage, normalization=trace, derivation=derivation,
    )
    result = LoopPlanExtractionResult(
        request_id=attempt_id, provider_id=UUID(int=2), model="synthetic-no-provider-call",
        prompt_version="monitor-loop-extract-v1", source_text_sha256=source.source_hash,
        source_id=source.source_id, source_binding_hash=source.binding_hash,
        authored_at=source.authored_at, available_at=source.available_at,
        effective_trade_date=source.effective_trade_date,
        draft=draft, daily_mapping=mapping, assumptions=(), warnings=(), validation_issues=(),
        usage=None, status=PlanExtractionStatus.SUCCEEDED, opening_account=opening,
        evidence_hash=sha256(canonical_json({
            "domain": "monitor-loop-extraction-evidence-v1",
            "source_binding_hash": source.binding_hash,
            "plan_mapping": mapping, "opening_account": opening,
        }).encode()).hexdigest(), coverage=coverage, normalization_trace=trace,
    )
    return source, mapping, result, inputs


def test_service_loop_result_branch_preserves_the_full_original_candidate_and_unbound_map(tmp_path):
    source, mapping, result, inputs = _initial_loop_case(UUID(int=101))
    store, running, _, _ = _running(
        tmp_path, owned=True, case=(inputs, source, result.to_preparation_candidate()),
    )
    service, _ = _completion_service(store)

    service._complete(running, PreparationCallOutcome(result=result, inputs=inputs),
                      retries=0, token=CancellationToken())

    proof = store.input_evidence(running.preparation_id, running.work_claim.generation)
    original = LoopPlanExtractionResult.model_validate_json(proof.candidate_json)
    assert proof.candidate_json == result.to_preparation_candidate().payload_json
    assert original.daily_mapping == mapping
    assert original.daily_mapping.clauses[-1].semantic_role == "HISTORICAL"
    assert original.daily_mapping.clauses[-1].paths == ()
    assert all(original.daily_mapping.clauses[-1].clause_id not in binding.clause_ids
               for binding in original.daily_mapping.bindings)
    assert proof.candidate_hash == store.get(running.preparation_id).candidate.candidate_hash


def _collection_chain(tmp_path):
    first_id, second_id = UUID(int=201), UUID(int=202)
    first_source, original_map, initial, first_inputs = _initial_loop_case(first_id)
    second_source, patch = delta("总持仓最多500股。", values={"max_qty": 500})
    store = PreparationStore(tmp_path / "two-source-evidence.sqlite3", clock=lambda: _NOW)
    record = store.create(PlanCollectionPreparationInput(
        preparation_id="two-source-evidence", sources=(first_source, second_source),
    ), idempotency_key="create-chain")
    claim = collection_claim(record, 0, generation=str(first_id)).model_copy(update={
        "claimed_at": _NOW,
    })
    running = store.start_attempt(record.preparation_id, expected_revision=record.revision,
                                  idempotency_key="start-first", work_claim=claim)
    calling = store.begin_call(record.preparation_id, generation=claim.generation,
                               owner_id=claim.owner_id, expected_revision=running.revision)
    first = store.finish_attempt(
        record.preparation_id, attempt_id=claim.generation, expected_revision=calling.revision,
        idempotency_key="finish-first", candidate=initial.to_preparation_candidate(),
        inputs=first_inputs, worker_owner_id=claim.owner_id,
    )
    base = build_initial_review(initial.draft, original_map, first_source)
    context = context_from_review(base, first.items[0].candidate.candidate_hash)
    expanded = expand_delta_output(patch, context)
    output = expand_compact_output(expanded, second_source, context=context)
    raw_json = "\n" + json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    derivation = SourceDerivationEvidence.build(
        kind="PREDECESSOR_PATCH", source_hash=second_source.source_hash, raw_json=raw_json,
        context_json=canonical(context.model_dump(mode="json")), base_hash=context.base_hash,
        stages=(DerivationStage.build(phase="DELTA_EXPANDED", output_json=canonical(
            expanded.model_dump(mode="json"))), DerivationStage.build(
            phase="SOURCE_NORMALIZED", output_json=canonical(output.model_dump(mode="json")))),
    )
    result = collection_update_result(base, second_source, output, second_id, context).model_copy(
        update={"source_derivation": derivation},
    )
    materialized = materialize_extraction(base, context.base_hash, second_source, result)
    assert materialized.extraction.source_derivation is not None
    second_inputs = CoverageInputs.build(
        source_hash=second_source.source_hash, source_binding_hash=second_source.binding_hash,
        derivation=materialized.extraction.source_derivation,
    )
    claim = collection_claim(first, 1, generation=str(second_id)).model_copy(update={
        "claimed_at": _NOW,
    })
    running = store.start_attempt(first.preparation_id, expected_revision=first.revision,
                                  idempotency_key="start-second", work_claim=claim)
    calling = store.begin_call(first.preparation_id, generation=claim.generation,
                               owner_id=claim.owner_id, expected_revision=running.revision)
    finished = store.finish_attempt(
        first.preparation_id, attempt_id=claim.generation, expected_revision=calling.revision,
        idempotency_key="finish-second", candidate=materialized.to_preparation_candidate(),
        inputs=second_inputs, worker_owner_id=claim.owner_id,
    )
    return store, finished, original_map, (first_inputs, second_inputs)


def test_consecutive_loop_and_delta_inputs_bind_actual_collection_items_and_predecessor(tmp_path):
    store, finished, _, inputs = _collection_chain(tmp_path)
    assert len(finished.items) == 2
    for index, item in enumerate(finished.items):
        attempt_id = item.attempts[-1].attempt_id
        proof = store.input_evidence(finished.preparation_id, attempt_id)
        assert proof.item_index == index and proof.attempt_id == attempt_id
        assert proof.source_binding_hash == item.source.binding_hash
        assert proof.inputs == inputs[index]
        assert proof.candidate_hash == item.candidate.candidate_hash
        assert proof.candidate_json == item.candidate.payload_json
        assert "source-derivation-v1" not in proof.candidate_json
    assert inputs[0].derivation.kind == "FULL_DRAFT"
    assert inputs[1].derivation.kind == "PREDECESSOR_PATCH"
    assert inputs[1].derivation.base_hash == finished.items[0].candidate.candidate_hash
    assert "draft" not in json.loads(inputs[1].derivation.raw_json)


def test_human_correction_does_not_replace_original_candidate_json_or_lose_background_map(tmp_path):
    store, finished, original_map, _ = _collection_chain(tmp_path)
    attempt_id = finished.items[0].attempts[-1].attempt_id
    proof_before = store.input_evidence(finished.preparation_id, attempt_id)
    original = LoopPlanExtractionResult.model_validate_json(proof_before.candidate_json)
    assert original.daily_mapping == original_map
    cleared = store.clear_work_claim(
        finished.preparation_id, generation=finished.work_claim.generation,
        expected_revision=finished.revision,
    )
    changed = original.draft.model_copy(update={"name": "Explicitly corrected display name"})
    command = CollectionItemCorrectionCommand(
        expected_revision=cleared.revision, binding=collection_item_binding(cleared.items[0]),
        confirmed=True, evidence="Explicit synthetic display correction; raw evidence is retained.",
        draft=changed, mapping=original.daily_mapping,
    )

    corrected = store.correct_collection_item(cleared.preparation_id, command=command,
                                              idempotency_key="human-display-correction")

    assert corrected.items[0].candidate.payload_json != proof_before.candidate_json
    assert corrected.items[0].candidate.candidate_hash != proof_before.candidate_hash
    restarted = PreparationStore(store.database_path)
    preserved = restarted.input_evidence(finished.preparation_id, attempt_id)
    assert preserved == proof_before
    original_again = LoopPlanExtractionResult.model_validate_json(preserved.candidate_json)
    assert original_again.daily_mapping == original_map
    assert original_again.daily_mapping.clauses[-1].semantic_role == "HISTORICAL"
    assert original_again.daily_mapping.clauses[-1].paths == ()
