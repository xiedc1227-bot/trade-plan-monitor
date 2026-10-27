"""Authenticate human operations against transaction-local preparation state."""

import json
import sqlite3
from hashlib import sha256
from types import SimpleNamespace

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    PlanCandidateReview,
    build_initial_review,
    context_from_review,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import input_evidence
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    CollectionPreparationRecord,
    decode_preparation_record_json,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    PreparationReviewCommand,
    collection_item_binding,
    correct_collection_candidate,
    frozen_preparation,
    prepare_frozen_plan,
)
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def _conflict(code="SOURCE_COVERAGE_REQUIRED"):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


def _item(record, index):
    return record.items[index] if isinstance(record, CollectionPreparationRecord) else record


def _refs(proofs):
    return tuple(PrefixAssuranceRef(binding=proof.binding, assurance_hash=proof.evidence_hash)
                 for proof in proofs)


def _command(operation):
    model = (CollectionItemCorrectionCommand if operation.operation == "CORRECT_ITEM"
             else PreparationReviewCommand)
    return model.model_validate_json(operation.command_json)


def _registered_response(connection, operation):
    from trade_plan_monitor.backtest.preparation_store import _request_hash

    if any(value is None for value in (operation.command_id, operation.command_request_hash,
                                       operation.after_record_hash)):
        raise _conflict()
    command = _command(operation)
    expected = _request_hash(operation.operation, operation.preparation_id, command)
    row = connection.execute(
        "SELECT request_hash,response_json FROM backtest_preparation_idempotency "
        "WHERE idempotency_key=?", (operation.command_id,),
    ).fetchone()
    if row is None or row[0] != expected or expected != operation.command_request_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    try:
        response = decode_preparation_record_json(row[1])
    except (ValueError, TypeError, RecursionError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    if (response.preparation_id != operation.preparation_id
            or response.revision != operation.after_revision
            or response.updated_at != operation.created_at
            or daily_hash("preparation-human-after-record-v1", response.model_dump(mode="json"))
            != operation.after_record_hash):
        raise _conflict("SOURCE_COVERAGE_STALE")
    if (isinstance(response, CollectionPreparationRecord)
            and operation.item_index >= len(response.items)):
        raise _conflict("SOURCE_COVERAGE_STALE")
    selected = _item(response, operation.item_index)
    if selected.candidate is None:
        raise _conflict("SOURCE_COVERAGE_STALE")
    if (selected.source, selected.source_revision, selected.candidate_revision,
        selected.candidate.candidate_hash, selected.candidate.evidence_hash) != (
        operation.source, operation.source_revision, operation.after_candidate_revision,
        operation.after_candidate_hash, operation.after_evidence_hash,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    if command.expected_revision != operation.before_revision:
        raise _conflict("SOURCE_COVERAGE_STALE")
    if operation.operation == "CORRECT_ITEM":
        if (command.binding.source_id, command.binding.source_revision,
            command.binding.candidate_revision, command.binding.candidate_hash,
            command.binding.evidence_hash) != (
            operation.source.source_id, operation.source_revision,
            operation.before_candidate_revision, operation.before_candidate_hash,
            operation.before_evidence_hash,
        ):
            raise _conflict("SOURCE_COVERAGE_STALE")
    elif (command.expected_source_revision, command.expected_candidate_revision,
          command.candidate_hash, command.evidence_hash) != (
        operation.source_revision, operation.before_candidate_revision,
        operation.before_candidate_hash, operation.before_evidence_hash,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return response, command


def _inputs(connection, record, index, checkpoint, state, key, digest):
    selected = _item(record, index)
    if not selected.attempts or selected.attempts[-1].status != "SUCCEEDED":
        raise _conflict()
    attempt = selected.attempts[-1]
    saved = input_evidence(connection, record.preparation_id, attempt.attempt_id)
    if state == "MISSING":
        if saved is not None or key is not None or digest is not None:
            raise _conflict("SOURCE_COVERAGE_STALE")
        return None
    if saved is None or saved.candidate_json is None:
        raise _conflict("SOURCE_COVERAGE_STALE")
    if (saved.evidence_key, saved.evidence_hash, saved.preparation_id, saved.item_index,
        saved.attempt_id, saved.source_binding_hash, saved.candidate_hash, saved.candidate_json,
        saved.inputs.source_hash, saved.inputs.source_binding_hash) != (
        key, digest, record.preparation_id, index, attempt.attempt_id,
        selected.source.binding_hash, checkpoint.candidate_hash, checkpoint.payload_json,
        selected.source.source_hash, selected.source.binding_hash,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return saved


def _original_source(record, index, checkpoint, base_review):
    """Validate historical correspondence without declaring the original AI complete."""
    from trade_plan_monitor.backtest import preparation_current_assurance as current
    selected = _item(record, index)
    if (checkpoint.source_hash, checkpoint.source_revision) != (
        selected.source.binding_hash, selected.source_revision,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    schema = json.loads(checkpoint.payload_json).get("schema_version")
    if schema == "monitor-loop-extraction-v1":
        original, _ = current._initial(selected, SimpleNamespace(
            candidate_json=checkpoint.payload_json))
        if original.evidence_hash != checkpoint.evidence_hash:
            raise _conflict("SOURCE_COVERAGE_STALE")
        return original
    if schema == "monitor-loop-candidate-evidence-v1":
        original = PlanCandidateReview.model_validate_json(checkpoint.payload_json)
        if (original.source_id, original.source_hash, original.available_at,
            original.evidence_hash) != (selected.source.source_id, selected.source.binding_hash,
                selected.source.execution_available_at, checkpoint.evidence_hash):
            raise _conflict("SOURCE_COVERAGE_STALE")
        return original
    if base_review is None or getattr(selected, "independent", False):
        raise _conflict()
    original = MaterializedUpdateCandidate.model_validate_json(checkpoint.payload_json)
    extraction = original.extraction
    context = context_from_review(base_review, selected.base_hash)
    expected = sha256(canonical_json(dict(domain="monitor-loop-update-evidence-v1",
        source_binding_hash=selected.source.binding_hash, context=context,
        output=extraction.output)).encode()).hexdigest()
    if (str(extraction.request_id), extraction.source_id, extraction.source_binding_hash,
        extraction.source_text_sha256, extraction.base_hash, extraction.evidence_hash,
        extraction.authored_at, extraction.available_at, extraction.effective_trade_date,
        original.review.evidence_hash) != (
        selected.attempts[-1].attempt_id, selected.source.source_id, selected.source.binding_hash,
        selected.source.source_hash, selected.base_hash, expected, selected.source.authored_at,
        selected.source.available_at, selected.source.effective_trade_date,
        checkpoint.evidence_hash,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return original


def _proof(operation, prefix_proofs, base_review):
    binding, prefix = operation.assessment_binding, _refs(prefix_proofs)
    if operation.resolved_update is None:
        from trade_plan_monitor.ai.source_human_initial_assurance import (
            assess_human_initial_current,
        )
        return assess_human_initial_current(operation.source, operation.resolved_review,
            operation.resolved_mapping, operation, binding=binding, prefix=prefix)
    from trade_plan_monitor.ai.source_human_change_assurance import assess_human_change_current
    if not prefix_proofs or not prefix_proofs[-1].coverage_complete:
        raise _conflict()
    parent = prefix_proofs[-1]
    return assess_human_change_current(operation.source, operation.resolved_update,
        operation.resolved_review, operation.resolved_mapping, operation,
        context=context_from_review(base_review, parent.binding.candidate_hash),
        base_review=base_review, verified_parent=parent, binding=binding, prefix=prefix)


def read_human_assurance(connection, record, index, *, prefix_proofs=(), base_review=None,
                         _context=None):
    """Committed operations require their actual immutable command response, not a self-hash."""
    from trade_plan_monitor.backtest import preparation_human_assurance_store as store

    if isinstance(record, CollectionPreparationRecord):
        from trade_plan_monitor.backtest.preparation_lineage_authority import require_owned_item

        require_owned_item(connection, record, index, context=_context)

    selected = _item(record, index)
    operation = store.human_operation(connection, record.preparation_id, index,
                                      selected.candidate_revision)
    if operation is None:
        raise _conflict()
    response, command = _registered_response(connection, operation)
    if (type(response) is not type(record) or selected != _item(response, index)
            or record.revision < response.revision
            or operation.prefix != _refs(prefix_proofs)
            or operation.source != selected.source
            or operation.source_revision != selected.source_revision
            or operation.attempt_id != selected.attempts[-1].attempt_id):
        raise _conflict("SOURCE_COVERAGE_STALE")
    if isinstance(record, CollectionPreparationRecord):
        if (operation.operation != "CORRECT_ITEM"
                or response.items[:index] != record.items[:index]):
            raise _conflict()
        actual_review = PlanCandidateReview.model_validate_json(selected.candidate.payload_json)
        expected_candidate = CollectionPreparationCandidate(
            **actual_review.to_preparation_candidate().model_dump(mode="python"),
            source_revision=selected.source_revision, source_hash=selected.source.binding_hash,
            base_hash=selected.base_hash)
        if actual_review != operation.resolved_review or selected.candidate != expected_candidate:
            raise _conflict("SOURCE_COVERAGE_STALE")
    else:
        manifest = frozen_preparation(record)
        if (record != response or operation.final_frozen_hash != manifest.manifest_hash
                or manifest.mapping != operation.resolved_mapping
                or manifest.version.snapshot != operation.resolved_review.draft.to_executable()
                or manifest.version.review.evidence != command.evidence):
            raise _conflict("SOURCE_COVERAGE_STALE")
    saved = _inputs(connection, record, index, operation.original_candidate,
                    operation.original_input_state, operation.original_input_key,
                    operation.original_input_hash)
    inputs_hash = None if saved is None else saved.inputs.evidence_hash
    if operation.assessment_binding.inputs_hash != inputs_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    original = _original_source(record, index, operation.original_candidate, base_review)
    if not isinstance(record, CollectionPreparationRecord):
        if (operation.operation != "REVIEW_AND_FREEZE"
                or command.draft is None and command.mapping is None
                or not hasattr(original, "daily_mapping")
                or daily_draft_content_sha256(operation.resolved_draft)
                == daily_draft_content_sha256(original.draft)
                and operation.resolved_mapping == original.daily_mapping):
            raise _conflict()
    if command.mapping is not None and command.mapping != operation.resolved_mapping or (
        command.draft is not None and command.draft != operation.resolved_draft
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    if isinstance(command, CollectionItemCorrectionCommand) and command.update is not None and (
        command.update != operation.resolved_update
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    if operation.previous_human_ref is not None:
        previous = store.human_operation(connection, record.preparation_id, index,
                                          operation.before_candidate_revision)
        if (previous is None or previous.evidence_hash != operation.previous_human_ref
                or previous.prefix != operation.prefix
                or previous.parent_hash != operation.parent_hash
                or previous.independent != operation.independent
                or previous.source != operation.source
                or previous.source_revision != operation.source_revision
                or previous.attempt_id != operation.attempt_id
                or previous.after_candidate_revision != operation.before_candidate_revision
                or previous.after_revision > operation.before_revision
                or previous.created_at > operation.created_at
                or previous.original_candidate != operation.original_candidate
                or previous.original_candidate_revision != operation.original_candidate_revision
                or (previous.original_input_state, previous.original_input_key,
                    previous.original_input_hash) != (operation.original_input_state,
                        operation.original_input_key, operation.original_input_hash)
                or (previous.after_candidate_hash, previous.after_evidence_hash) != (
                    operation.before_candidate_hash, operation.before_evidence_hash)):
            raise _conflict("SOURCE_COVERAGE_STALE")
        _registered_response(connection, previous)
    return _proof(operation, prefix_proofs, base_review)


def _checkpoint(connection, previous, index, prefix_proofs, base_review):
    from trade_plan_monitor.backtest import preparation_human_assurance_store as store

    selected = _item(previous, index)
    last = store.human_operation(connection, previous.preparation_id, index,
                                 selected.candidate_revision)
    if last is not None:
        read_human_assurance(connection, previous, index, prefix_proofs=prefix_proofs,
                             base_review=base_review)
        return (last.original_candidate, last.original_candidate_revision,
                last.original_input_state, last.original_input_key, last.original_input_hash, last)
    saved = input_evidence(connection, previous.preparation_id, selected.attempts[-1].attempt_id)
    if saved is not None:
        if saved.candidate_json is None:
            raise _conflict()
        if (saved.candidate_hash != selected.candidate.candidate_hash
                or saved.candidate_json != selected.candidate.payload_json):
            # Old corrected payloads have no provable original candidate revision.
            code = ("SOURCE_COVERAGE_REQUIRED" if json.loads(
                selected.candidate.payload_json).get("schema_version")
                == "monitor-loop-candidate-evidence-v1" else "SOURCE_COVERAGE_STALE")
            raise _conflict(code)
        state, key, digest = "PRESENT", saved.evidence_key, saved.evidence_hash
    else:
        state, key, digest = "MISSING", None, None
    return selected.candidate, selected.candidate_revision, state, key, digest, None


def _register_human_correction(connection, previous, proposed, command, *, command_id,
                               command_request_hash, now):
    """Prepare and validate a human operation before any old record/receipt is written."""
    from trade_plan_monitor.backtest import preparation_current_assurance as current
    from trade_plan_monitor.backtest import preparation_human_assurance_store as store
    from trade_plan_monitor.backtest.preparation_store import _request_hash
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    previous = current._actual_record(connection, previous)
    if type(previous) is not type(proposed):
        raise _conflict("SOURCE_COVERAGE_STALE")
    collection = isinstance(previous, CollectionPreparationRecord)
    from trade_plan_monitor.backtest.preparation_lineage_authority import (
        CurrentAssuranceContext,
        require_owned_item,
    )

    context = CurrentAssuranceContext()
    if collection:
        index, review = correct_collection_candidate(previous, command)
        require_owned_item(connection, previous, index, context=context)
        selected, after = previous.items[index], proposed.items[index]
        expected_candidate = CollectionPreparationCandidate(
            **review.to_preparation_candidate().model_dump(mode="python"),
            source_revision=selected.source_revision, source_hash=selected.source.binding_hash,
            base_hash=selected.base_hash)
        if (command.binding != collection_item_binding(selected)
                or after.source != selected.source
                or after.source_revision != selected.source_revision
                or after.attempts != selected.attempts or after.base_hash != selected.base_hash
                or after.candidate != expected_candidate
                or proposed.items[:index] != previous.items[:index] or proposed.review is not None):
            raise _conflict("SOURCE_COVERAGE_STALE")
    else:
        if not isinstance(command, PreparationReviewCommand):
            raise _conflict("SOURCE_COVERAGE_STALE")
        index, selected, after = 0, previous, proposed
        manifest = prepare_frozen_plan(previous, command, now)
        if frozen_preparation(proposed) != manifest:
            raise _conflict("SOURCE_COVERAGE_STALE")
        from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
        initial = LoopPlanExtractionResult.model_validate_json(selected.candidate.payload_json)
        draft, mapping = command.draft or initial.draft, command.mapping or initial.daily_mapping
        if (command.draft is None and command.mapping is None) or (
            daily_draft_content_sha256(draft) == daily_draft_content_sha256(initial.draft)
            and mapping == initial.daily_mapping
        ):
            raise _conflict()
        review = build_initial_review(draft, mapping, selected.source)
    if (command.expected_revision != previous.revision or proposed.revision != previous.revision + 1
            or proposed.updated_at != now or proposed.created_at != previous.created_at
            or after.candidate_revision != selected.candidate_revision + 1):
        raise _conflict("SOURCE_COVERAGE_STALE")
    operation_name = "CORRECT_ITEM" if collection else "REVIEW_AND_FREEZE"
    if command_request_hash != _request_hash(operation_name, previous.preparation_id, command):
        raise _conflict("SOURCE_COVERAGE_STALE")
    prefix_proofs = current.read_current_assurance_prefix(connection, previous, index,
                                                         _context=context)
    base = (None if not index or selected.independent else
            preparation_candidate_review(previous, index - 1)) if collection else None
    if (collection and index and not selected.independent
            and not prefix_proofs[-1].coverage_complete):
        raise _conflict()
    checkpoint, revision, state, key, digest, last = _checkpoint(
        connection, previous, index, prefix_proofs, base)
    saved = _inputs(connection, previous, index, checkpoint, state, key, digest)
    original = _original_source(previous, index, checkpoint, base)
    output = None
    if collection:
        output = None if not index or selected.independent else (command.update or (
            last.resolved_update if last is not None else original.extraction.output))
        draft = review.draft if output is None else output.draft
        mapping = command.mapping or (last.resolved_mapping if last is not None else (
            original.daily_mapping if output is None and hasattr(original, "daily_mapping")
            else output.review(selected.source.text).mapping if output is not None else None))
        if mapping is None:
            raise _conflict()
    assessment_candidate = after.candidate if collection else checkpoint
    binding = CandidateBinding(preparation_id=previous.preparation_id, item_index=index,
        source_id=selected.source.source_id, source_revision=selected.source_revision,
        source_binding_hash=selected.source.binding_hash,
        candidate_revision=after.candidate_revision if collection else revision,
        candidate_hash=assessment_candidate.candidate_hash,
        review_evidence_hash=review.evidence_hash,
        attempt_id=selected.attempts[-1].attempt_id,
        inputs_hash=None if saved is None else saved.inputs.evidence_hash,
        independent=getattr(selected, "independent", False))
    prefix = _refs(prefix_proofs)
    operation = PreparationHumanOperation.build(preparation_id=previous.preparation_id,
        item_index=index, operation=operation_name, source=selected.source,
        source_revision=selected.source_revision, before_revision=previous.revision,
        after_revision=proposed.revision, before_candidate_revision=selected.candidate_revision,
        before_candidate_hash=selected.candidate.candidate_hash,
        before_evidence_hash=selected.candidate.evidence_hash,
        after_candidate_revision=after.candidate_revision,
        after_candidate_hash=after.candidate.candidate_hash,
        after_evidence_hash=after.candidate.evidence_hash,
        attempt_id=binding.attempt_id, original_input_state=state, original_input_key=key,
        original_input_hash=digest, original_candidate=checkpoint,
        original_candidate_revision=revision,
        command_json=canonical_json(command), resolved_draft=draft, resolved_mapping=mapping,
        resolved_update=output, resolved_review=review, assessment_binding=binding,
        prefix=prefix, prefix_hash=source_prefix_hash(prefix, binding),
        parent_hash=None if not index or binding.independent else prefix_proofs[-1].evidence_hash,
        independent=binding.independent,
        final_frozen_hash=None if collection else manifest.manifest_hash,
        previous_human_ref=None if last is None else last.evidence_hash,
        command_id=command_id, command_request_hash=command_request_hash,
        after_record_hash=daily_hash("preparation-human-after-record-v1",
                                     proposed.model_dump(mode="json")),
        created_at=now)
    proof = _proof(operation, prefix_proofs, base)
    if not proof.coverage_complete:
        raise _conflict()
    store.save_human_operation(connection, operation)
    return proof


def register_human_correction(connection, previous, proposed, command, *, command_id,
                              command_request_hash, now):
    """Sanitized atomic write boundary; no authority is created outside the caller transaction."""
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    try:
        return _register_human_correction(connection, previous, proposed, command,
            command_id=command_id, command_request_hash=command_request_hash, now=now)
    except PreparationConflictError:
        raise
    except sqlite3.DatabaseError:
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    except RecursionError:
        raise _conflict("SOURCE_COVERAGE_LIMIT_EXCEEDED") from None
    except (ValueError, TypeError, KeyError, IndexError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error)
                else "SOURCE_COVERAGE_REQUIRED")
        raise _conflict(code) from None
