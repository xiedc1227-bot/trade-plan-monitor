"""Kind-local LINEAGE records in the existing sealed preparation auxiliary store."""

import sqlite3

from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES
from trade_plan_monitor.backtest.preparation_assurance_store import assurance_available
from trade_plan_monitor.backtest.preparation_lineage_models import PreparationLineage, lineage_key
from trade_plan_monitor.domain.daily_hash import canonical

_COLUMNS = ("evidence_key,preparation_id,item_index,attempt_id,kind,source_binding_hash,"
            "candidate_hash,payload_json,evidence_hash,created_at")


def _conflict(code):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


def _projection(value):
    last = value.placements[-1]
    # A creation slot is never a provider attempt. Use a real reused candidate,
    # because the newly created SINGLE tail has no candidate yet.
    return (value.evidence_key, value.preparation_id, last.consumer_item_index,
        "lineage-create", value.kind, last.owner_binding.source_binding_hash,
        last.owner_binding.candidate_hash, canonical(value.model_dump(mode="json")),
        value.evidence_hash, value.created_at.isoformat())


def lineage(connection, preparation_id):
    """Read by exact creation identity; missing schemas never trigger an upgrade."""
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    key = lineage_key(preparation_id)
    try:
        row = connection.execute("SELECT " + _COLUMNS
            + " FROM backtest_preparation_assurance WHERE evidence_key=?", (key,)).fetchone()
        if row is None:
            row = connection.execute("SELECT " + _COLUMNS
                + " FROM backtest_preparation_assurance WHERE preparation_id=? "
                "AND attempt_id='lineage-create' AND kind='LINEAGE'", (preparation_id,)).fetchone()
        if row is None:
            return None
        payload = row[7]
        if (type(payload) is not str or len(payload) > MAX_PROOF_BYTES
                or len(payload.encode("utf-8")) > MAX_PROOF_BYTES):
            raise ValueError("lineage payload exceeds its bounded text envelope")
        value = PreparationLineage.model_validate_json(payload)
        if value.evidence_key != key or _projection(value) != tuple(row):
            raise ValueError("lineage stored projection differs")
        return value
    except (ValueError, TypeError, RecursionError, sqlite3.DatabaseError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None


def save_lineage(connection, value):
    """Stage an immutable record inside the caller's transaction; never commit."""
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    value = PreparationLineage.model_validate_json(value.model_dump_json())
    previous = lineage(connection, value.preparation_id)
    if previous is not None:
        if previous.intent() != value.intent():
            raise _conflict("SOURCE_COVERAGE_COMMAND_CONFLICT")
        return previous
    connection.execute("INSERT INTO backtest_preparation_assurance VALUES (?,?,?,?,?,?,?,?,?,?)",
                       _projection(value))
    return value
