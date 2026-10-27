"""Hold current preparation authority through a caller's final run admission.

The caller acquires the jobs writer first, then enters this preparation writer,
and releases this fence after the jobs transaction commits or rolls back. Market
copying and provider operations must finish before entering either writer.
"""

from contextlib import contextmanager

from pydantic import TypeAdapter

from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.preparation_current_assurance import (
    require_current_reviewed_preparation,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

_IDENTIFIER = TypeAdapter(StableIdentifier)
_HASH = TypeAdapter(Sha256Hex)


@contextmanager
def current_prepared_run_fence(store, preparation_id, expected_manifest_hash):
    """Recompute actual evidence without writes, retaining the real database lock."""
    preparation_id = _IDENTIFIER.validate_python(preparation_id)
    expected_manifest_hash = _HASH.validate_python(expected_manifest_hash)
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            record = store._read(connection, preparation_id)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise PreparationConflictError("SOURCE_COVERAGE_INTEGRITY") from None
        if record is None:
            raise PreparationConflictError("PREPARATION_NOT_FOUND")
        require_current_reviewed_preparation(connection, record)
        try:
            current = frozen_preparation(record)
        except RecursionError:
            raise PreparationConflictError("SOURCE_COVERAGE_LIMIT_EXCEEDED") from None
        except (ValueError, TypeError, KeyError):
            raise PreparationConflictError("SOURCE_COVERAGE_INTEGRITY") from None
        if (current.preparation_id != preparation_id
                or current.manifest_hash != expected_manifest_hash):
            raise PreparationConflictError("SOURCE_COVERAGE_STALE")
        yield current
