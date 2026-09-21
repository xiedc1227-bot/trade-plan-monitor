"""Read-only historical legacy origin proof; not current delivery eligibility."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
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
from trade_plan_monitor.state.activation_history import (
    ActivationHistoryLimit,
    MissingActivationEvidence,
    read_activation_history,
    read_monitor_highwater,
)
from trade_plan_monitor.state.activation_history import (
    monitor_from_row as _monitor,
)
from trade_plan_monitor.state.activation_history import (
    monitor_query as _monitor_query,
)
from trade_plan_monitor.state.events import (
    MonitorEventStorageError,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.models import (
    EvaluationLedger,
    PlanVersion,
)
from trade_plan_monitor.state.models import EvaluationResult as ResultRow
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow
from trade_plan_monitor.state.projections import ProjectionError, _result_from_row

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


_MissingEvidence = MissingActivationEvidence


def _require(agreement: bool) -> None:
    if not agreement:
        raise ValueError("Historical evidence does not agree")


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
        read_monitor_highwater(session)
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
        try:
            history = read_activation_history(session, event.symbol)
        except ActivationHistoryLimit:
            return UnknownLegacyAlertOrigin(LegacyOriginUnknownReason.HISTORY_LIMIT)
        origin = None
        for boundary in history:
            if boundary.sequence < publication.sequence:
                origin = (
                    boundary.revision, boundary.plan_version_id, boundary.occurred_at,
                )
            _require(not publication.sequence <= boundary.sequence <= event.sequence)
        _require(origin is not None and origin[1] == version_id)
        target_cutoff = datetime.combine(
            identity.official_trade_date, time(15), tzinfo=event.evaluated_at.tzinfo
        )
        _require(origin[2] <= target_cutoff and origin[2] <= event.evaluated_at)
        return ProvenLegacyAlertOrigin(event, version_id, origin[0], identity, result_hash)
