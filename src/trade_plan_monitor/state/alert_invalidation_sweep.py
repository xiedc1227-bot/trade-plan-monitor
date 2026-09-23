"""Bounded post-admission classification of alerts for superseded plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trade_plan_monitor.notifications.delivery_eligibility import (
    DeliveryEligibilityRepository,
    DeliveryMetadataError,
)
from trade_plan_monitor.notifications.outbox import OutboxError, _event_from_row
from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.state.models import AlertEvent, AuditLog, PlanVersion, RuntimeLiveness
from trade_plan_monitor.state.plan_invalidation_evidence import (
    PlanInvalidationEvidenceError,
    was_terminally_invalidated,
)

MAX_SWEEP_BATCH = 100


@dataclass(frozen=True, slots=True)
class AlertInvalidationBatch:
    next_sequence: int
    scanned: int
    suppressed: int
    unclassified: int


def latest_alert_sequence(session: Session) -> int:
    """Freeze one indexed alert high-water mark without loading old payloads."""

    return (
        session.scalar(
            select(AlertEvent.sequence).order_by(AlertEvent.sequence.desc()).limit(1)
        )
        or 0
    )


def sweep_invalidated_alerts(
    session: Session,
    *,
    after_sequence: int,
    through_sequence: int,
    expected_liveness_revision: int,
    now: datetime,
    limit: int = MAX_SWEEP_BATCH,
) -> AlertInvalidationBatch:
    """Classify at most ``limit`` old events, never blocking admission on history size.

    The caller commits this batch and only then advances its in-memory cursor.
    A restart may scan again; terminal receipts and audit IDs are idempotent.
    """

    if type(after_sequence) is not int or after_sequence < 0:
        raise ValueError("after_sequence must be nonnegative")
    if type(through_sequence) is not int or through_sequence < after_sequence:
        raise ValueError("through_sequence must not precede after_sequence")
    if type(expected_liveness_revision) is not int or expected_liveness_revision < 0:
        raise ValueError("expected_liveness_revision must be nonnegative")
    if type(limit) is not int or not 1 <= limit <= MAX_SWEEP_BATCH:
        raise ValueError("limit must be between 1 and 100")
    observed_at = _canonical_shanghai(now)
    with session.begin_nested():
        locked = session.execute(
            update(RuntimeLiveness)
            .where(
                RuntimeLiveness.id == 1,
                RuntimeLiveness.revision == expected_liveness_revision,
            )
            .values(revision=RuntimeLiveness.revision)
            .execution_options(synchronize_session=False)
        )
        if locked.rowcount != 1:
            raise DeliveryMetadataError("Runtime liveness revision is stale or unavailable")
        rows = session.scalars(
            select(AlertEvent)
            .where(
                AlertEvent.sequence > after_sequence,
                AlertEvent.sequence <= through_sequence,
            )
            .order_by(AlertEvent.sequence)
            .limit(limit)
        ).all()
        repository = DeliveryEligibilityRepository(session, clock=lambda: observed_at)
        versions: dict[tuple[str, int], PlanVersion | None] = {}
        invalidated_versions: dict[str, bool | None] = {}
        suppressed = 0
        unclassified = 0
        for row in rows:
            try:
                event = _event_from_row(row)
            except OutboxError:
                _audit_unclassified(session, row, reason="CANONICAL_ALERT_INVALID", now=observed_at)
                unclassified += 1
                continue
            identity = (event.plan_id, event.plan_version)
            if identity not in versions:
                versions[identity] = session.scalar(
                    select(PlanVersion).where(
                        PlanVersion.plan_id == event.plan_id,
                        PlanVersion.version == event.plan_version,
                    )
                )
            version = versions[identity]
            if version is None or version.status != "SUPERSEDED":
                continue
            if version.symbol != event.symbol or version.plan_hash != event.plan_hash:
                _audit_unclassified(session, row, reason="PLAN_IDENTITY_MISMATCH", now=observed_at)
                unclassified += 1
                continue
            if version.id not in invalidated_versions:
                try:
                    invalidated_versions[version.id] = was_terminally_invalidated(
                        session, symbol=version.symbol, plan_version_id=version.id
                    )
                except PlanInvalidationEvidenceError:
                    invalidated_versions[version.id] = None
            if invalidated_versions[version.id] is None:
                _audit_unclassified(
                    session, row, reason="PLAN_INVALIDATION_EVIDENCE_INVALID", now=observed_at
                )
                unclassified += 1
                continue
            if not invalidated_versions[version.id]:
                continue
            try:
                before = repository.get(event.event_id)
                if before is None or before.status.value != "SUPPRESS":
                    repository.suppress_invalidated_identity(
                        event.event_id,
                        plan_id=version.plan_id,
                        plan_version=version.version,
                        plan_hash=version.plan_hash,
                        symbol=version.symbol,
                    )
                    suppressed += 1
            except DeliveryMetadataError:
                _audit_unclassified(
                    session, row, reason="DELIVERY_METADATA_INVALID", now=observed_at
                )
                unclassified += 1
        return AlertInvalidationBatch(
            next_sequence=rows[-1].sequence if rows else after_sequence,
            scanned=len(rows),
            suppressed=suppressed,
            unclassified=unclassified,
        )


def _audit_unclassified(session: Session, row: AlertEvent, *, reason: str, now: datetime) -> None:
    audit_id = str(uuid5(NAMESPACE_URL, f"alert-invalidation-unclassified:{row.id}:{reason}"))
    if session.get(AuditLog, audit_id) is not None:
        return
    session.add(
        AuditLog(
            id=audit_id,
            action="ALERT_INVALIDATION_UNCLASSIFIED",
            entity_type="alert_event",
            entity_id=row.id,
            before_hash=None,
            after_hash=None,
            details_json=json.dumps(
                {"reason": reason, "sequence": row.sequence},
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at=now.isoformat(),
        )
    )
