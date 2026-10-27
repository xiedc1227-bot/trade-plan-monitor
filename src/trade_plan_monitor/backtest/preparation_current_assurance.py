"""Rebuild current preparation coverage from exact, transaction-local server state.

This reader grants neither a human review nor execution authority. Original input
and frozen/review codecs remain independent; no evidence is inferred on read.
"""

import json
import sqlite3
from hashlib import sha256

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
    validate_opening_evidence,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.source_candidate_models import CandidateBinding, PrefixAssuranceRef
from trade_plan_monitor.ai.source_change_composition import assess_change_current
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_assurance_store import (
    assurance_available,
    input_evidence,
)
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    CollectionPreparationRecord,
    PreparationCandidate,
    PreparationRecord,
    decode_preparation_record_json,
)
from trade_plan_monitor.backtest.preparation_review import (
    PreparationSemanticError,
    frozen_collection,
    frozen_preparation,
)
from trade_plan_monitor.domain.daily_hash import daily_hash


def _conflict(code):
    # PreparationStore imports this reader at mutation boundaries.
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


def _actual_record(connection, record):
    if not isinstance(record, (PreparationRecord, CollectionPreparationRecord)):
        raise _conflict("SOURCE_COVERAGE_STALE")
    row = connection.execute(
        "SELECT document_json FROM backtest_preparation WHERE preparation_id=?",
        (record.preparation_id,),
    ).fetchone()
    if row is None:
        raise _conflict("SOURCE_COVERAGE_STALE")
    try:
        actual = decode_preparation_record_json(row[0])
    except (ValueError, TypeError, RecursionError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    if actual != record or actual.preparation_id != record.preparation_id:
        raise _conflict("SOURCE_COVERAGE_STALE")
    return actual


def _original_input(connection, record, index, item, candidate_hash):
    if item.candidate is None or not item.attempts or item.attempts[-1].status != "SUCCEEDED":
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    attempt = item.attempts[-1]
    evidence = input_evidence(connection, record.preparation_id, attempt.attempt_id)
    if evidence is None or evidence.candidate_json is None:
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    if (evidence.preparation_id, evidence.item_index, evidence.attempt_id,
        evidence.source_binding_hash, evidence.candidate_hash, evidence.inputs.source_hash,
        evidence.inputs.source_binding_hash, attempt.source_revision, attempt.source_hash) != (
        record.preparation_id, index, attempt.attempt_id, item.source.binding_hash,
        candidate_hash, item.source.source_hash, item.source.binding_hash,
        item.source_revision, item.source.binding_hash,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return evidence


def _bound_original(item, evidence, *, collection, original=None):
    """The full original payload must reproduce the actual candidate wrapper hash."""
    values = ((item.candidate if original is None else original).model_dump(mode="python")
              | {"payload_json": evidence.candidate_json,
                 "source_revision": item.source_revision,
                 "source_hash": item.source.binding_hash})
    model = CollectionPreparationCandidate if collection else PreparationCandidate
    if collection:
        values["base_hash"] = item.base_hash
    bound = model.model_validate(values)
    if bound.candidate_hash != evidence.candidate_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    return bound


def _binding(record, index, item, evidence, candidate, review, *, candidate_revision=None):
    return CandidateBinding(preparation_id=record.preparation_id, item_index=index,
        source_id=item.source.source_id, source_revision=item.source_revision,
        source_binding_hash=item.source.binding_hash,
        candidate_revision=(item.candidate_revision if candidate_revision is None
                            else candidate_revision),
        candidate_hash=candidate.candidate_hash, review_evidence_hash=review.evidence_hash,
        attempt_id=item.attempts[-1].attempt_id, inputs_hash=evidence.inputs.evidence_hash,
        independent=getattr(item, "independent", False))


def _initial(item, evidence):
    original = LoopPlanExtractionResult.model_validate_json(evidence.candidate_json)
    source = item.source
    if (original.status is not PlanExtractionStatus.SUCCEEDED
            or (str(original.request_id), original.source_id, original.source_text_sha256,
                original.source_binding_hash, original.authored_at, original.available_at,
                original.effective_trade_date) != (
                item.attempts[-1].attempt_id, source.source_id, source.source_hash,
                source.binding_hash, source.authored_at, source.available_at,
                source.effective_trade_date)):
        raise _conflict("SOURCE_COVERAGE_STALE")
    output = LoopPlanExtractionOutput(schema_version=original.schema_version,
        draft=original.draft, clauses=original.daily_mapping.clauses,
        bindings=original.daily_mapping.bindings, assumptions=original.assumptions,
        warnings=original.warnings, opening_account=original.opening_account)
    reviewed = output.review(source.text)
    validate_opening_evidence(original.opening_account, source.text)
    expected = sha256(canonical_json(dict(domain="monitor-loop-extraction-evidence-v1",
        source_binding_hash=source.binding_hash, plan_mapping=reviewed.mapping,
        opening_account=original.opening_account)).encode()).hexdigest()
    if (reviewed.mapping != original.daily_mapping
            or original.evidence_hash != expected
            or original.to_preparation_candidate().payload_json != evidence.candidate_json):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return original, build_initial_review(original.draft, original.daily_mapping, source)


def _single(connection, record):
    if record.candidate is None:
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    manifest = None
    if record.status == "REVIEWED":
        try:
            manifest = frozen_preparation(record)
        except PreparationSemanticError:
            raise _conflict("SOURCE_COVERAGE_REQUIRED") from None
    candidate_hash = (record.candidate.candidate_hash if manifest is None
                      else manifest.extraction_candidate_hash)
    evidence = _original_input(connection, record, 0, record, candidate_hash)
    original, review = _initial(record, evidence)
    candidate = _bound_original(record, evidence, collection=False,
        original=None if manifest is None else original.to_preparation_candidate())
    if original.evidence_hash != candidate.evidence_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    if manifest is not None and (
        manifest.extraction_evidence_hash != original.evidence_hash
        or manifest.mapping != original.daily_mapping
        or manifest.opening_evidence != original.opening_account
        or manifest.version.snapshot != original.draft.to_executable()
    ):
        # A current human correction requires its own exact registered receipt.
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    binding = _binding(record, 0, record, evidence, candidate, review,
        candidate_revision=None if manifest is None else manifest.extraction_candidate_revision)
    return (assess_initial_current(record.source, review, original.daily_mapping,
                                  evidence.inputs, binding=binding),)


def _collection(connection, record):
    if record.reviewed_base is not None or record.workflow == "COMPOSITION":
        # Original owners must come from explicit immutable reuse lineage, never a hash search.
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    proofs, base = [], None
    for index, item in enumerate(record.items):
        if item.candidate is None:
            raise _conflict("SOURCE_COVERAGE_REQUIRED")
        if json.loads(item.candidate.payload_json).get("schema_version") == (
            "monitor-loop-candidate-evidence-v1"
        ):
            raise _conflict("SOURCE_COVERAGE_REQUIRED")
        evidence = _original_input(connection, record, index, item, item.candidate.candidate_hash)
        candidate = _bound_original(item, evidence, collection=True)
        prefix = tuple(PrefixAssuranceRef(binding=proof.binding,
            assurance_hash=proof.evidence_hash) for proof in proofs)
        if index == 0 or item.independent:
            original, review = _initial(item, evidence)
            if original.evidence_hash != candidate.evidence_hash:
                raise _conflict("SOURCE_COVERAGE_STALE")
            proof = assess_initial_current(item.source, review, original.daily_mapping,
                evidence.inputs, binding=_binding(record, index, item, evidence, candidate, review),
                prefix=prefix)
        else:
            materialized = MaterializedUpdateCandidate.model_validate_json(evidence.candidate_json)
            extraction = materialized.extraction
            if str(extraction.request_id) != item.attempts[-1].attempt_id:
                raise _conflict("SOURCE_COVERAGE_STALE")
            context = context_from_review(base, proofs[-1].binding.candidate_hash)
            expected = materialize_extraction(base, context.base_hash, item.source, extraction)
            if (expected != materialized or item.base_hash != context.base_hash
                    or candidate.evidence_hash != materialized.review.evidence_hash):
                raise _conflict("SOURCE_COVERAGE_STALE")
            extraction = extraction.model_copy(update={
                "source_derivation": evidence.inputs.derivation,
                "derivation_issues": tuple(row.code for row in evidence.inputs.derivation_issues),
            })
            materialized = materialized.model_copy(update={"extraction": extraction})
            review = materialized.review
            proof = assess_change_current(item.source, extraction.output, materialized,
                evidence.inputs, context=context, base_review=base, verified_parent=proofs[-1],
                binding=_binding(record, index, item, evidence, candidate, review), prefix=prefix)
        proofs.append(proof)
        base = review
    return tuple(proofs)


def read_current_assurance(connection, record):
    """Purely read and recompute all original source proofs on this SQLite connection.

    Missing historical input cannot acquire retrospective fidelity. This function
    intentionally has no caller-provided source/header/hash override and never
    creates tables, upgrades a store, or writes an assessment or review receipt.
    """
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    try:
        if not assurance_available(connection):
            raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
        actual = _actual_record(connection, record)
        return (_collection(connection, actual) if isinstance(actual, CollectionPreparationRecord)
                else _single(connection, actual))
    except PreparationConflictError:
        raise
    except sqlite3.DatabaseError:
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    except RecursionError:
        raise _conflict("SOURCE_COVERAGE_LIMIT_EXCEEDED") from None
    except (ValueError, TypeError, KeyError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error)
                else "SOURCE_COVERAGE_STALE")
        raise _conflict(code) from None


def require_current_preparation(connection, record):
    """Require current complete coverage; this is not a human review permission."""
    proofs = read_current_assurance(connection, record)
    if not proofs or any(not proof.coverage_complete for proof in proofs):
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    return proofs


def verify_current_review_candidate(connection, previous, proposed):
    """Verify before/after policy within the caller's existing review transaction.

    Human policy corrections require their own registered operation proof; until
    supplied, a complete original extraction cannot certify a changed snapshot.
    """
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    proofs = require_current_preparation(connection, previous)
    if type(previous) is not type(proposed) or proposed.status != "REVIEWED":
        raise _conflict("SOURCE_COVERAGE_STALE")
    try:
        current = (_collection(connection, proposed)
                   if isinstance(proposed, CollectionPreparationRecord)
                   else _single(connection, proposed))
    except PreparationConflictError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if isinstance(error, RecursionError)
                or "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error) else "SOURCE_COVERAGE_REQUIRED")
        raise _conflict(code) from None
    if current != proofs:
        raise _conflict("SOURCE_COVERAGE_STALE")
    return proofs


def _manifest(record):
    return (frozen_collection(record) if isinstance(record, CollectionPreparationRecord)
            else frozen_preparation(record))


def save_current_review(connection, previous, proposed, *, command_id, command_request_hash, now):
    """Save the new receipt in the same transaction as the original human review."""
    from trade_plan_monitor.backtest.preparation_review_assurance_models import (
        PreparationReviewAssurance,
    )
    from trade_plan_monitor.backtest.preparation_review_assurance_store import save_review_assurance

    if proposed.review is None or (proposed.updated_at, proposed.review.reviewed_at) != (now, now):
        raise _conflict("SOURCE_COVERAGE_STALE")
    proofs = verify_current_review_candidate(connection, previous, proposed)
    try:
        receipt = PreparationReviewAssurance.build(preparation_id=proposed.preparation_id,
            command_id=command_id, command_request_hash=command_request_hash,
            previous_revision=previous.revision, reviewed_revision=proposed.revision,
            review_revision=proposed.review_revision, original_review_hash=daily_hash(
                "preparation-original-review-v1", proposed.review.model_dump(mode="json")),
            frozen_manifest_hash=_manifest(proposed).manifest_hash, proofs=proofs, created_at=now)
    except RecursionError:
        raise _conflict("SOURCE_COVERAGE_LIMIT_EXCEEDED") from None
    except (ValueError, TypeError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error)
                else "SOURCE_COVERAGE_INTEGRITY")
        raise _conflict(code) from None
    return save_review_assurance(connection, receipt)


def require_current_reviewed_preparation(connection, record):
    """Fresh reuse needs the actual human receipt and current source proof together."""
    from trade_plan_monitor.backtest.preparation_review_assurance_store import review_assurance
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    actual = _actual_record(connection, record)
    if actual.status != "REVIEWED" or actual.review is None:
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    proofs = require_current_preparation(connection, actual)
    receipt = review_assurance(connection, actual.preparation_id, actual.review_revision)
    if receipt is None:
        raise _conflict("SOURCE_COVERAGE_REQUIRED")
    try:
        manifest = _manifest(actual)
    except PreparationConflictError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if isinstance(error, RecursionError)
                or "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error) else "SOURCE_COVERAGE_INTEGRITY")
        raise _conflict(code) from None
    try:
        original = connection.execute(
            "SELECT request_hash,response_json FROM backtest_preparation_idempotency "
            "WHERE idempotency_key=?", (receipt.command_id,),
        ).fetchone()
    except sqlite3.DatabaseError:
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    if original is None or original[0] != receipt.command_request_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    try:
        original_response = decode_preparation_record_json(original[1])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    if (receipt.reviewed_revision != actual.revision
            or receipt.created_at != actual.review.reviewed_at
            or receipt.original_review_hash != daily_hash(
                "preparation-original-review-v1", actual.review.model_dump(mode="json"))
            or receipt.frozen_manifest_hash != manifest.manifest_hash
            or receipt.proofs != proofs or original_response != actual):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return receipt
