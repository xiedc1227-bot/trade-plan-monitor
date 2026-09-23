"""Read the durable cause that permanently invalidates one plan version."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.state.models import AuditLog

TERMINAL_INVALIDATION_CAUSES = (
    "OUTAGE_OVER_120_HOURS",
    "MANUAL_LEGACY_INVALIDATION",
)


class PlanInvalidationEvidenceError(RuntimeError):
    """The deactivation audit cannot safely prove an invalidation decision."""


def was_terminally_invalidated(
    session: Session, *, symbol: str, plan_version_id: str
) -> bool:
    """Use only after the caller has serialized its plan/alert decision writer."""

    scope = (
        AuditLog.action == "PLAN_DEACTIVATED",
        AuditLog.entity_type == "ACTIVE_PLAN",
        AuditLog.entity_id == symbol,
    )
    malformed = session.scalar(
        select(AuditLog.id)
        .where(*scope, func.json_valid(AuditLog.details_json) != 1)
        .limit(1)
    )
    if malformed is not None:
        raise PlanInvalidationEvidenceError("Plan deactivation audit is invalid")
    matching = session.scalar(
        select(AuditLog.id)
        .where(
            *scope,
            func.json_extract(AuditLog.details_json, "$.planVersionId") == plan_version_id,
            func.json_extract(AuditLog.details_json, "$.cause").in_(
                TERMINAL_INVALIDATION_CAUSES
            ),
        )
        .limit(1)
    )
    return matching is not None
