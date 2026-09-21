"""Bounded read-only proof of the persisted activation event/audit chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MAX_PUBLIC_SEQUENCE,
    MonitorEvent,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.events import _event_from_row as _monitor_from_row
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    MonitorSequence,
    PlanActivationState,
)
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow

_BOUNDARIES = (MonitorEventType.PLAN_ACTIVATED, MonitorEventType.PLAN_DEACTIVATED)
_ACTIONS = ("PLAN_ACTIVATED", "PLAN_DEACTIVATED")


class MissingActivationEvidence(ValueError):
    pass


class ActivationHistoryLimit(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActivationBoundary:
    revision: int
    plan_version_id: str | None
    occurred_at: datetime
    sequence: int


def _require(agreement: bool) -> None:
    if not agreement:
        raise ValueError("Historical evidence does not agree")


def monitor_query():
    # Truncate before loading/parsing, not after fetching an unbounded historical blob.
    return select(
        MonitorRow.id,
        MonitorRow.sequence,
        MonitorRow.event_type,
        MonitorRow.schema_version,
        MonitorRow.aggregate_id,
        MonitorRow.occurred_at,
        func.substr(MonitorRow.payload_json, 1, 4097).label("payload_json"),
    )


def monitor_from_row(row) -> MonitorEvent:
    if row is None:
        raise MissingActivationEvidence()
    _require(len(row.payload_json) <= 4096)
    return _monitor_from_row(row)


def read_monitor_highwater(session: Session) -> int:
    states = session.scalars(select(MonitorSequence).limit(2)).all()
    if not states:
        raise MissingActivationEvidence()
    _require(len(states) == 1 and states[0].singleton_id == 1)
    highwater = states[0].last_sequence
    _require(type(highwater) is int and 0 <= highwater <= MAX_PUBLIC_SEQUENCE)
    # The owned SQLite snapshot keeps this global maximum coherent with every
    # subsequently read publication, alert, and activation boundary sequence.
    retained_maximum = session.scalar(select(func.max(MonitorRow.sequence)))
    _require(
        retained_maximum is None
        or (type(retained_maximum) is int and 0 < retained_maximum <= highwater)
    )
    return highwater


def read_activation_history(session: Session, symbol: str) -> tuple[ActivationBoundary, ...]:
    """Validate the bounded event/audit chain and current persisted pointers.

    The caller owns a fresh no_autoflush read snapshot and must first call
    read_monitor_highwater in that same snapshot. This helper owns no transaction.
    """
    rows = session.execute(
        monitor_query()
        .where(
            MonitorRow.aggregate_id == symbol,
            MonitorRow.event_type.in_([item.value for item in _BOUNDARIES]),
        )
        .order_by(MonitorRow.sequence)
        .limit(MAX_EVENT_REPLAY_LIMIT + 1)
    ).all()
    audits = session.execute(
        select(
            AuditLog.id,
            AuditLog.action,
            AuditLog.before_hash,
            AuditLog.after_hash,
            AuditLog.created_at,
            func.substr(AuditLog.details_json, 1, 4097).label("details_json"),
        )
        .where(
            AuditLog.entity_type == "ACTIVE_PLAN",
            AuditLog.entity_id == symbol,
            AuditLog.action.in_(_ACTIONS),
        )
        .limit(MAX_EVENT_REPLAY_LIMIT + 1)
    ).all()
    if max(len(rows), len(audits)) > MAX_EVENT_REPLAY_LIMIT:
        raise ActivationHistoryLimit()
    if not rows or not audits:
        raise MissingActivationEvidence()
    _require(len(rows) == len(audits))
    by_revision = {}
    for audit in audits:
        _require(len(audit.details_json) <= 4096)
        details = json.loads(audit.details_json)
        _require(
            isinstance(details, dict)
            and set(details) == {"symbol", "revision", "planVersionId"}
        )
        revision = details["revision"]
        _require(
            type(revision) is int
            and revision > 0
            and revision not in by_revision
            and details["symbol"] == symbol
            and isinstance(details["planVersionId"], str)
        )
        by_revision[revision] = (audit, details["planVersionId"])
    previous_hash, active_version = None, None
    history = []
    for revision, row in enumerate(rows, start=1):
        boundary = monitor_from_row(row)
        _require(boundary.payload.revision == revision and revision in by_revision)
        audit, plan_version_id = by_revision[revision]
        activating = boundary.event_type is MonitorEventType.PLAN_ACTIVATED
        _require(
            audit.action == (_ACTIONS[0] if activating else _ACTIONS[1])
            and audit.created_at == boundary.occurred_at.isoformat()
            and audit.before_hash == previous_hash
            and boundary.event_id
            == monitor_event_id(boundary.event_type, symbol, str(revision))
        )
        _require(
            boundary.payload.entity_id == (plan_version_id if activating else symbol)
        )
        if not activating:
            _require(active_version == plan_version_id)
        active_version = plan_version_id if activating else None
        snapshot = {
            "planVersionId": active_version,
            "revision": revision,
            "symbol": symbol,
            "activatedAt" if activating else "changedAt": audit.created_at,
        }
        digest = sha256(
            json.dumps(
                snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        _require(audit.after_hash == digest)
        previous_hash = digest
        history.append(ActivationBoundary(
            revision, active_version, boundary.occurred_at, boundary.sequence,
        ))
    tip = session.get(PlanActivationState, symbol)
    active = session.get(ActivePlan, symbol)
    if tip is None:
        raise MissingActivationEvidence()
    _require(
        tip.revision == len(rows)
        and tip.plan_version_id == active_version
        and tip.changed_at == boundary.occurred_at.isoformat()
    )
    if active_version is None:
        _require(active is None)
    else:
        _require(
            active is not None
            and active.plan_version_id == active_version
            and active.revision == tip.revision
            and active.activated_at == tip.changed_at
        )
    return tuple(history)
