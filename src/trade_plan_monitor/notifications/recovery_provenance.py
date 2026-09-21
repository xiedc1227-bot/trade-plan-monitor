"""Read-only historical legacy origin proof; not current delivery eligibility."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import ActionableSignalType, OfficialCloseEvaluationIdentity
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.notifications.models import AlertEvent, build_alert_payload
from trade_plan_monitor.notifications.outbox import OutboxStorageError
from trade_plan_monitor.notifications.outbox import _event_from_row as _alert_from_row
from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MAX_PUBLIC_SEQUENCE,
    MonitorEvent,
    MonitorEventStorageError,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.events import _event_from_row as _monitor_from_row
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    EvaluationLedger,
    MonitorSequence,
    PlanActivationState,
    PlanVersion,
)
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.models import EvaluationResult as ResultRow
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow
from trade_plan_monitor.state.projections import ProjectionError, _result_from_row

_BOUNDARIES = (MonitorEventType.PLAN_ACTIVATED, MonitorEventType.PLAN_DEACTIVATED)
_ACTIONS = ("PLAN_ACTIVATED", "PLAN_DEACTIVATED")
_RISK_SIGNALS = frozenset(
    (
        ActionableSignalType.RISK_BREACH,
        ActionableSignalType.RISK_EXIT_READY,
        ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
    )
)


class LegacyOriginUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    UNSUPPORTED_SIGNAL = "UNSUPPORTED_SIGNAL"
    HISTORY_LIMIT = "HISTORY_LIMIT"


@dataclass(frozen=True, slots=True)
class UnknownLegacyAlertOrigin:
    reason: LegacyOriginUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True, slots=True)
class ProvenLegacyAlertOrigin:
    event: AlertEvent
    plan_version_id: str
    activation_revision: int
    evaluation_identity: OfficialCloseEvaluationIdentity
    result_hash: str
    status: Literal["PROVEN"] = field(default="PROVEN", init=False)


class _MissingEvidence(ValueError):
    pass


def _require(agreement: bool) -> None:
    if not agreement:
        raise ValueError("Historical evidence does not agree")


def _monitor_query():
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


def _monitor(row) -> MonitorEvent:
    if row is None:
        raise _MissingEvidence()
    _require(len(row.payload_json) <= 4096)
    return _monitor_from_row(row)


class LegacyAlertOriginReader:
    """Own one fresh app-configured Session/read snapshot, with no commit or flush.

    The factory must use state.database's explicit-BEGIN engine. A pre-used or dirty
    session is rejected. SQL faults propagate; only content-validation failures become
    UNKNOWN. History is capped by row count, never the seven-day replay horizon.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def read(self, event_id: UUID) -> ProvenLegacyAlertOrigin | UnknownLegacyAlertOrigin:
        if type(event_id) is not UUID:
            raise TypeError("event_id must be a UUID")
        session = self._session_factory()
        if (
            session.in_transaction()
            or session.identity_map
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise ValueError("Origin reader requires a fresh session")
        with session, session.no_autoflush:
            try:
                return self._read(session, event_id)
            except _MissingEvidence:
                return UnknownLegacyAlertOrigin(LegacyOriginUnknownReason.MISSING_EVIDENCE)
            except (
                ValueError,
                TypeError,
                RecursionError,
                OutboxStorageError,
                MonitorEventStorageError,
                ProjectionError,
            ):
                # Wrapping repository methods are deliberately not called: these errors
                # arise only from pure row parsers, never SQLAlchemy read failures.
                return UnknownLegacyAlertOrigin(LegacyOriginUnknownReason.INVALID_EVIDENCE)

    def _read(self, session: Session, event_id: UUID):
        states = session.scalars(select(MonitorSequence).limit(2)).all()
        if not states:
            raise _MissingEvidence()
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
        row = session.scalar(
            select(AlertRow).where(
                AlertRow.id == str(event_id),
                func.length(AlertRow.payload_json) <= 1024 * 1024,
                func.length(AlertRow.message_text) <= 32768,
            )
        )
        if row is None:
            raise _MissingEvidence()
        event = _alert_from_row(row)
        if type(event) is not AlertEvent or event.signal_type not in _RISK_SIGNALS:
            return UnknownLegacyAlertOrigin(LegacyOriginUnknownReason.UNSUPPORTED_SIGNAL)
        created = _monitor(
            session.execute(_monitor_query().where(MonitorRow.id == str(event_id))).one_or_none()
        )
        _require(
            created.event_type is MonitorEventType.ALERT_CREATED
            and created.sequence == event.sequence
            and created.payload.symbol == event.symbol
            and created.occurred_at == event.created_at
        )
        versions = session.execute(
            select(
                PlanVersion.id,
                PlanVersion.plan_id,
                PlanVersion.version,
                PlanVersion.symbol,
                PlanVersion.plan_hash,
                func.substr(PlanVersion.payload_json, 1, 1024 * 1024 + 1).label("payload_json"),
            )
            .where(PlanVersion.plan_id == event.plan_id, PlanVersion.version == event.plan_version)
            .limit(2)
        ).all()
        if not versions:
            raise _MissingEvidence()
        _require(len(versions) == 1)
        version = versions[0]
        _require(len(version.payload_json) <= 1024 * 1024)
        plan = load_plan_json(version.payload_json)
        _require(
            version.symbol == plan.symbol == event.symbol
            and version.plan_hash == plan_sha256(plan) == event.plan_hash
            and plan.plan_id == event.plan_id
            and plan.version == event.plan_version
        )
        identity = OfficialCloseEvaluationIdentity(
            plan_hash=event.plan_hash,
            symbol=event.symbol,
            official_trade_date=event.trading_date,
            formula_version=plan.monitoring.indicator_formula_version,
        )
        key = (
            identity.plan_hash,
            identity.symbol,
            identity.kind,
            identity.official_trade_date.isoformat(),
            identity.formula_version,
        )
        result_row = session.scalar(
            select(ResultRow).where(
                ResultRow.plan_hash == key[0],
                ResultRow.symbol == key[1],
                ResultRow.evaluation_kind == key[2],
                ResultRow.target_value == key[3],
                ResultRow.formula_version == key[4],
                func.length(ResultRow.result_json) <= 8 * 1024 * 1024,
                func.length(ResultRow.position_lots_json) <= 8 * 1024 * 1024,
            )
        )
        ledger = session.get(EvaluationLedger, key)
        if result_row is None or ledger is None:
            raise _MissingEvidence()
        result = _result_from_row(result_row)
        _require(
            ledger.result_hash == result.result_hash
            and ledger.evaluated_at == result.snapshot.evaluated_at.isoformat()
        )
        payload = build_alert_payload(event_id=event_id, plan=plan, result=result)
        _require(
            payload.model_dump(mode="python")
            == event.model_dump(
                mode="python", exclude={"sequence", "message_text", "created_at", "acknowledged_at"}
            )
        )
        publication_id = monitor_event_id(
            MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
            event.symbol,
            identity.model_dump_json(),
            result.result_hash,
        )
        publication = _monitor(
            session.execute(
                _monitor_query().where(MonitorRow.id == str(publication_id))
            ).one_or_none()
        )
        _require(
            publication.event_type is MonitorEventType.SYMBOL_SNAPSHOT_UPDATED
            and publication.payload.symbol == event.symbol
            and publication.payload.result_hash == result.result_hash
            and publication.occurred_at == result.snapshot.evaluated_at
            and publication.sequence < created.sequence
        )
        return self._origin(session, event, version.id, identity, result.result_hash, publication)

    @staticmethod
    def _origin(session, event, version_id, identity, result_hash, publication):
        rows = session.execute(
            _monitor_query()
            .where(
                MonitorRow.aggregate_id == event.symbol,
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
                AuditLog.entity_id == event.symbol,
                AuditLog.action.in_(_ACTIONS),
            )
            .limit(MAX_EVENT_REPLAY_LIMIT + 1)
        ).all()
        if max(len(rows), len(audits)) > MAX_EVENT_REPLAY_LIMIT:
            return UnknownLegacyAlertOrigin(LegacyOriginUnknownReason.HISTORY_LIMIT)
        if not rows or not audits:
            raise _MissingEvidence()
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
                and details["symbol"] == event.symbol
                and isinstance(details["planVersionId"], str)
            )
            by_revision[revision] = (audit, details["planVersionId"])
        previous_hash, active_version, origin = None, None, None
        for revision, row in enumerate(rows, start=1):
            boundary = _monitor(row)
            _require(boundary.payload.revision == revision and revision in by_revision)
            audit, plan_version_id = by_revision[revision]
            activating = boundary.event_type is MonitorEventType.PLAN_ACTIVATED
            _require(
                audit.action == (_ACTIONS[0] if activating else _ACTIONS[1])
                and audit.created_at == boundary.occurred_at.isoformat()
                and audit.before_hash == previous_hash
                and boundary.event_id
                == monitor_event_id(boundary.event_type, event.symbol, str(revision))
            )
            _require(
                boundary.payload.entity_id == (plan_version_id if activating else event.symbol)
            )
            if not activating:
                _require(active_version == plan_version_id)
            active_version = plan_version_id if activating else None
            snapshot = {
                "planVersionId": active_version,
                "revision": revision,
                "symbol": event.symbol,
                "activatedAt" if activating else "changedAt": audit.created_at,
            }
            digest = sha256(
                json.dumps(
                    snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            _require(audit.after_hash == digest)
            previous_hash = digest
            if boundary.sequence < publication.sequence:
                origin = (revision, active_version, boundary.occurred_at)
            _require(not publication.sequence <= boundary.sequence <= event.sequence)
        tip = session.get(PlanActivationState, event.symbol)
        active = session.get(ActivePlan, event.symbol)
        if tip is None:
            raise _MissingEvidence()
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
        _require(origin is not None and origin[1] == version_id)
        target_cutoff = datetime.combine(
            identity.official_trade_date, time(15), tzinfo=event.evaluated_at.tzinfo
        )
        _require(origin[2] <= target_cutoff and origin[2] <= event.evaluated_at)
        return ProvenLegacyAlertOrigin(event, version_id, origin[0], identity, result_hash)
