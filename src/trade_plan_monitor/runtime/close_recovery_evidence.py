"""Read-only legacy close occurrence evidence; never replay or delivery permission."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import AShareSymbol, TradePlan
from trade_plan_monitor.runtime.clock import SHANGHAI, _canonical_shanghai
from trade_plan_monitor.runtime.missed_close_recovery import (
    MAX_CLOSE_DISCOVERY_DAYS,
    CompletionStatus,
    MissedCloseScope,
    MissedCloseWindow,
    OfficialCloseCompletion,
    discover_missed_closes,
)
from trade_plan_monitor.state.activation_history import (
    ActivationHistoryLimit,
    MissingActivationEvidence,
    monitor_from_row,
    monitor_query,
    read_activation_history,
    read_monitor_highwater,
)
from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MonitorEventStorageError,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    EvaluationLedger,
    MonitorSequence,
    PlanActivationState,
    PlanVersion,
    TradingCalendar,
)
from trade_plan_monitor.state.models import EvaluationResult as ResultRow
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow
from trade_plan_monitor.state.projections import ProjectionError, _result_from_row
from trade_plan_monitor.state.recovery_read_session import require_owned_recovery_session

_MAX_PLAN = 1024 * 1024
_MAX_RESULT = 8 * 1024 * 1024
_SYMBOL = TypeAdapter(AShareSymbol)
_CONTENT_ERRORS = (ValueError, TypeError, RecursionError, MonitorEventStorageError, ProjectionError)


class CloseRecoveryUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    HISTORY_LIMIT = "HISTORY_LIMIT"
    INACTIVE_PLAN = "INACTIVE_PLAN"
    UNSUPPORTED_PLAN = "UNSUPPORTED_PLAN"


@dataclass(frozen=True, slots=True)
class UnknownCloseRecovery:
    reason: CloseRecoveryUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


def _require(agreement: bool) -> None:
    if not agreement:
        raise ValueError("Close recovery evidence does not agree")


def _calendar_open_on(session, start, end):
    """Read a bounded SSE calendar window; missing or malformed days stay unknown."""

    rows = session.execute(select(
        TradingCalendar.cal_date,
        cast(TradingCalendar.is_open, Integer),
        func.typeof(TradingCalendar.is_open),
    ).where(
        TradingCalendar.exchange == "SSE",
        TradingCalendar.cal_date >= start,
        TradingCalendar.cal_date <= end,
    )).all()
    by_date = {day: (is_open, storage_type) for day, is_open, storage_type in rows}

    def is_open_on(day):
        value = by_date.get(day)
        return (bool(value[0]) if value is not None and value[1] == "integer"
                and value[0] in (0, 1) else None)

    return is_open_on


class LegacyCloseRecoveryReader:
    """Own a fresh app explicit-BEGIN session and one coherent read snapshot.

    SQL failures propagate. Invalid stored evidence stays UNKNOWN. Callers must use
    state.database's single-engine factory, never a borrowed Connection. No provider,
    flush, commit, state reconstruction, replay scheduling or notification is performed.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def discover(
        self, symbol: str, observed_at: datetime, *, window_start: date | None = None,
        max_calendar_days: int = MAX_CLOSE_DISCOVERY_DAYS,
    ) -> MissedCloseWindow | UnknownCloseRecovery:
        symbol = _SYMBOL.validate_python(symbol, strict=True)
        observed_at = _canonical_shanghai(observed_at)
        if (type(max_calendar_days) is not int
                or not 1 <= max_calendar_days <= MAX_CLOSE_DISCOVERY_DAYS):
            raise ValueError("max_calendar_days must be an integer between 1 and 32")
        if window_start is not None and type(window_start) is not date:
            raise TypeError("window_start must be a date")
        session = self._session_factory()
        require_owned_recovery_session(session, (
            MonitorSequence, MonitorRow, AuditLog, PlanActivationState, ActivePlan,
            PlanVersion, TradingCalendar, EvaluationLedger, ResultRow,
        ))
        with session, session.no_autoflush:
            try:
                read_monitor_highwater(session)
                history = read_activation_history(session, symbol)
                _require(all(boundary.occurred_at <= observed_at for boundary in history))
                boundary = history[-1]
                if boundary.plan_version_id is None:
                    return UnknownCloseRecovery(CloseRecoveryUnknownReason.INACTIVE_PLAN)
                scope = self._scope(session, symbol, observed_at, boundary)
            except ActivationHistoryLimit:
                return UnknownCloseRecovery(CloseRecoveryUnknownReason.HISTORY_LIMIT)
            except MissingActivationEvidence:
                return UnknownCloseRecovery(CloseRecoveryUnknownReason.MISSING_EVIDENCE)
            except _CONTENT_ERRORS:
                return UnknownCloseRecovery(CloseRecoveryUnknownReason.INVALID_EVIDENCE)
            if isinstance(scope, UnknownCloseRecovery):
                return scope
            evidence = _CompletionReader(session, scope, boundary.sequence)

            start = scope.activated_at.date() if window_start is None else window_start
            today = scope.observed_at.date()
            if not scope.activated_at.date() <= start <= today:
                raise ValueError("window_start must lie within observed activation history")
            days = min(max_calendar_days, (today - start).days + 1)
            is_open_on = _calendar_open_on(
                session, start, start + timedelta(days=days - 1),
            )

            return discover_missed_closes(
                scope=scope, is_open_on=is_open_on, completion_on=evidence.read,
                window_start=window_start, max_calendar_days=max_calendar_days,
            )

    @staticmethod
    def _scope(session, symbol, observed_at, boundary):
        version = session.execute(select(
            PlanVersion.id, PlanVersion.plan_id, PlanVersion.version, PlanVersion.symbol,
            PlanVersion.plan_hash, PlanVersion.status,
            func.substr(PlanVersion.payload_json, 1, _MAX_PLAN + 1).label("payload_json"),
        ).where(PlanVersion.id == boundary.plan_version_id)).one_or_none()
        if version is None:
            raise MissingActivationEvidence()
        _require(type(version.payload_json) is str
                 and len(version.payload_json.encode("utf-8")) <= _MAX_PLAN)
        plan = load_plan_json(version.payload_json)
        if type(plan) is not TradePlan:
            return UnknownCloseRecovery(CloseRecoveryUnknownReason.UNSUPPORTED_PLAN)
        version_id = UUID(version.id)
        _require(
            str(version_id) == boundary.plan_version_id
            and version.status == "ACTIVE"
            and version.plan_id == plan.plan_id and version.version == plan.version
            and version.symbol == plan.symbol == symbol
            and version.plan_hash == plan_sha256(plan)
            and version.payload_json == dump_plan_json(plan)
        )
        return MissedCloseScope(
            plan=plan, plan_version_id=version.id, activation_revision=boundary.revision,
            activated_at=boundary.occurred_at, observed_at=observed_at,
        )


class _CompletionReader:
    def __init__(self, session, scope, activation_sequence):
        self.session = session
        self.scope = scope
        self.activation_sequence = activation_sequence
        self.publications = None
        self.publications_since = None
        self.publications_unknown = False

    def read(self, identity):
        try:
            return self._read(identity)
        except _CONTENT_ERRORS:
            return self._evidence(identity, CompletionStatus.UNKNOWN)

    def _evidence(self, identity, status, result=None):
        return OfficialCloseCompletion(
            identity=identity, plan_version_id=self.scope.plan_version_id,
            activation_revision=self.scope.activation_revision,
            activated_at=self.scope.activated_at, observed_at=self.scope.observed_at,
            status=status, result=result, committed_publication=status is CompletionStatus.PROVEN,
        )

    def _read(self, identity):
        key = (identity.plan_hash, identity.symbol, identity.kind,
               identity.official_trade_date.isoformat(), identity.formula_version)
        ledger = self.session.get(EvaluationLedger, key)
        # Content limits must not hide the existence of a claimed identity.
        row = self.session.execute(select(
            ResultRow.plan_hash, ResultRow.symbol, ResultRow.evaluation_kind,
            ResultRow.target_value, ResultRow.formula_version, ResultRow.result_hash,
            ResultRow.evaluated_at, ResultRow.source_at, ResultRow.schema_version,
            func.substr(ResultRow.result_json, 1, _MAX_RESULT + 1).label("result_json"),
            func.length(ResultRow.position_lots_json).label("position_lots_length"),
        ).where(
            ResultRow.plan_hash == key[0], ResultRow.symbol == key[1],
            ResultRow.evaluation_kind == key[2], ResultRow.target_value == key[3],
            ResultRow.formula_version == key[4],
        )).one_or_none()
        if ledger is None and row is None:
            status = (CompletionStatus.UNKNOWN if self._orphan_possible(identity)
                      else CompletionStatus.ABSENT)
            return self._evidence(identity, status)
        _require(ledger is not None and row is not None)
        _require(type(row.result_json) is str
                 and len(row.result_json.encode("utf-8")) <= _MAX_RESULT
                 and 0 <= row.position_lots_length <= _MAX_RESULT)
        result = _result_from_row(row)
        _require(ledger.result_hash == result.result_hash
                 and ledger.evaluated_at == result.snapshot.evaluated_at.isoformat())
        publication_id = monitor_event_id(
            MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, identity.symbol,
            identity.model_dump_json(), result.result_hash,
        )
        publication = monitor_from_row(self.session.execute(
            monitor_query().where(MonitorRow.id == str(publication_id)),
        ).one_or_none())
        _require(
            publication.event_type is MonitorEventType.SYMBOL_SNAPSHOT_UPDATED
            and publication.payload.symbol == identity.symbol
            and publication.payload.result_hash == result.result_hash
            and publication.occurred_at == result.snapshot.evaluated_at
            and publication.sequence > self.activation_sequence
        )
        # The scanner checks activation <= cutoff <= evaluated <= observation,
        # exact plan/result identity and the source cutoff. No signal/alert gate.
        return self._evidence(identity, CompletionStatus.PROVEN, result)

    def _orphan_possible(self, identity):
        cutoff = datetime.combine(identity.official_trade_date, time(15), SHANGHAI)
        if (self.publications is None or self.publications_since > cutoff
                ) and not self.publications_unknown:
            rows = self.session.execute(monitor_query().where(
                MonitorRow.aggregate_id == identity.symbol,
                MonitorRow.event_type == MonitorEventType.SYMBOL_SNAPSHOT_UPDATED.value,
                # An official close cannot be published before its source cutoff.
                # Bound the scan to the interrupted interval, not the plan's age.
                MonitorRow.occurred_at >= cutoff.isoformat(),
                MonitorRow.occurred_at <= self.scope.observed_at.isoformat(),
            ).order_by(MonitorRow.sequence).limit(MAX_EVENT_REPLAY_LIMIT + 1)).all()
            try:
                _require(len(rows) <= MAX_EVENT_REPLAY_LIMIT)
                self.publications = tuple(monitor_from_row(row) for row in rows)
                self.publications_since = cutoff
            except _CONTENT_ERRORS:
                self.publications_unknown = True
        if self.publications_unknown:
            return True
        # Recovered closes may be published later, but never before their source cutoff.
        return any(publication.event_id == monitor_event_id(
            MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, identity.symbol,
            identity.model_dump_json(), publication.payload.result_hash,
        ) for publication in self.publications)
