"""Kind-scoped REVIEW records in the existing sealed preparation assurance table."""

import sqlite3

from trade_plan_monitor.backtest.preparation_assurance_store import assurance_available
from trade_plan_monitor.backtest.preparation_review_assurance_models import (
    PreparationReviewAssurance,
    review_assurance_key,
)
from trade_plan_monitor.domain.daily_hash import canonical

_COLUMNS = ("evidence_key,preparation_id,item_index,attempt_id,kind,source_binding_hash,"
            "candidate_hash,payload_json,evidence_hash,created_at")


def _conflict(code):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


def _projection(value):
    last = value.proofs[-1].binding
    # Non-INPUT attempt_id is a kind-local slot, never the extraction attempt.
    # Every real attempt remains unchanged inside its proof.binding.attempt_id.
    return (value.evidence_key, value.preparation_id, last.item_index,
            f"review-{value.review_revision}", value.kind, last.source_binding_hash,
            last.candidate_hash, canonical(value.model_dump(mode="json")), value.evidence_hash,
            value.created_at.isoformat())


def review_assurance(connection, preparation_id, review_revision):
    """Read one immutable receipt without upgrading, mutating or granting authority."""
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    key = review_assurance_key(preparation_id, review_revision)
    try:
        row = connection.execute(
            "SELECT " + _COLUMNS + " FROM backtest_preparation_assurance WHERE evidence_key=?",
            (key,),
        ).fetchone()
        if row is None:
            # The unique slot index also detects an independently corrupted key.
            row = connection.execute(
                "SELECT " + _COLUMNS + " FROM backtest_preparation_assurance "
                "WHERE preparation_id=? AND attempt_id=? AND kind='REVIEW'",
                (preparation_id, f"review-{review_revision}"),
            ).fetchone()
        if row is None:
            return None
        value = PreparationReviewAssurance.model_validate_json(row[7])
        if value.evidence_key != key or _projection(value) != tuple(row):
            raise ValueError("stored review assurance projection differs")
        return value
    except (ValueError, TypeError, RecursionError, sqlite3.DatabaseError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None


def save_review_assurance(connection, value):
    """Insert into the caller's transaction; exact-intent retry keeps original time."""
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    value = PreparationReviewAssurance.model_validate_json(value.model_dump_json())
    previous = review_assurance(connection, value.preparation_id, value.review_revision)
    if previous is not None:
        if previous.intent() != value.intent():
            raise _conflict("SOURCE_COVERAGE_COMMAND_CONFLICT")
        return previous
    connection.execute("INSERT INTO backtest_preparation_assurance VALUES (?,?,?,?,?,?,?,?,?,?)",
                       _projection(value))
    return value
