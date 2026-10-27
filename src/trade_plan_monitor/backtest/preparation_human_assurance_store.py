"""Human operation integrity on the existing sealed generic preparation sidecar."""

import sqlite3

from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES
from trade_plan_monitor.backtest.preparation_assurance_store import assurance_available
from trade_plan_monitor.backtest.preparation_human_assurance_models import (
    PreparationHumanOperation,
    human_operation_key,
    human_operation_slot,
)
from trade_plan_monitor.domain.daily_hash import canonical

_COLUMNS = ("evidence_key,preparation_id,item_index,attempt_id,kind,source_binding_hash,"
            "candidate_hash,payload_json,evidence_hash,created_at")


def _conflict(code):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


def _decode(row):
    if not isinstance(row[7], str) or len(row[7].encode("utf-8")) > MAX_PROOF_BYTES + 128:
        raise ValueError("human operation stored payload exceeds its bounded envelope")
    value = PreparationHumanOperation.model_validate_json(row[7])
    if (canonical(value.model_dump(mode="json")) != row[7]
            or (value.evidence_key, value.preparation_id, value.item_index, value.slot,
                value.kind, value.source_binding_hash, value.after_candidate_hash,
                value.evidence_hash, value.created_at.isoformat()) != (*row[:7], *row[8:])):
        raise ValueError("human operation storage projection differs")
    return value


def human_operation(connection, preparation_id, item_index, after_candidate_revision):
    """Read the exact identity, with one kind-local fallback to expose a damaged key."""
    key = human_operation_key(preparation_id, item_index, after_candidate_revision)
    slot = human_operation_slot(item_index, after_candidate_revision)
    if not assurance_available(connection):
        return None
    try:
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM backtest_preparation_assurance WHERE evidence_key=?",
            (key,),
        ).fetchone()
        if row is None:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM backtest_preparation_assurance "
                "WHERE preparation_id=? AND attempt_id=? AND kind='HUMAN_OPERATION'",
                (preparation_id, slot),
            ).fetchone()
        if row is None:
            return None
        value = _decode(row)
        if value.evidence_key != key:
            raise ValueError("human operation requested identity differs")
        return value
    except (ValueError, TypeError, RecursionError, sqlite3.DatabaseError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None


def save_human_operation(connection, operation):
    """Join the caller's transaction; this does not authenticate actual preparation state."""
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    operation = PreparationHumanOperation.model_validate_json(operation.model_dump_json())
    previous = human_operation(connection, operation.preparation_id, operation.item_index,
                               operation.after_candidate_revision)
    if previous is not None:
        if previous.intent() != operation.intent():
            raise _conflict("SOURCE_COVERAGE_COMMAND_CONFLICT")
        return previous
    connection.execute(
        "INSERT INTO backtest_preparation_assurance VALUES (?,?,?,?,?,?,?,?,?,?)",
        (operation.evidence_key, operation.preparation_id, operation.item_index, operation.slot,
         operation.kind, operation.source_binding_hash, operation.after_candidate_hash,
         canonical(operation.model_dump(mode="json")), operation.evidence_hash,
         operation.created_at.isoformat()),
    )
    return operation
