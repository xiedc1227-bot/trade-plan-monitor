"""Bounded, read-only legacy historical inputs; never a replay or send permit."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal

from sqlalchemy import Integer, cast, select
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import (
    OfficialCloseEvaluationIdentity,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    SignalType,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_data.sessions import SHANGHAI
from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.runtime.close_recovery_evidence import (
    _CONTENT_ERRORS,
    _SYMBOL,
    LegacyCloseRecoveryReader,
    UnknownCloseRecovery,
    _calendar_open_on,
    _CompletionReader,
    _require,
)
from trade_plan_monitor.runtime.missed_close_recovery import (
    MAX_CLOSE_DISCOVERY_DAYS,
    CompletionStatus,
    MissedCloseScope,
    discover_missed_closes,
)
from trade_plan_monitor.state.activation_history import (
    ActivationHistoryLimit,
    MissingActivationEvidence,
    read_activation_history,
    read_monitor_highwater,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    EvaluationLedger,
    EvaluationResult,
    MonitorEvent,
    MonitorSequence,
    PlanActivationState,
    PlanVersion,
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionLot,
    PositionOpeningBalance,
    RiskState,
    TradingCalendar,
)
from trade_plan_monitor.state.position_inventory_history import (
    PositionInventoryHistoryReader,
    ProvenInventoryHistory,
    _HistoryLimit,
    _ReadBudget,
    _UnknownEvidence,
)
from trade_plan_monitor.state.position_lot_evidence import (
    _date,
    _reject_constant,
    _timestamp,
    _unique_object,
)
from trade_plan_monitor.state.position_lot_history import (
    _AUDIT,
    _bounded_query,
    _MissingEvidence,
    _raw,
)
from trade_plan_monitor.state.recovery_read_session import require_owned_recovery_session
from trade_plan_monitor.state.repositories import (
    MarketReferenceRepository,
    RiskStateRecord,
    _canonical_json,
    _risk_state_hash,
)


class HistoricalCloseUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    HISTORY_LIMIT = "HISTORY_LIMIT"
    INACTIVE_PLAN = "INACTIVE_PLAN"
    UNSUPPORTED_PLAN = "UNSUPPORTED_PLAN"


@dataclass(frozen=True, slots=True)
class UnknownHistoricalClose:
    reason: HistoricalCloseUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True, slots=True)
class ProvenHistoricalClose:
    scope: MissedCloseScope
    inventory: ProvenInventoryHistory
    current_risk: RiskStateRecord | None
    risk_state: RiskStateSnapshot | None
    trading_calendar: tuple[TradingDay, ...]
    high_water_sequence: int
    status: Literal["PROVEN"] = field(default="PROVEN", init=False)


class LegacyHistoricalCloseReader:
    """Prepare the earliest missing suffix close in one owned SQLite snapshot.

    The caller must use the application's explicit-BEGIN engine. SQL failures and
    borrowed-session violations propagate; malformed stored evidence is UNKNOWN.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def missing_targets(
        self, symbol: str, observed_at: datetime,
    ) -> tuple[date, ...] | UnknownHistoricalClose:
        """Find only unfinished closes after the last committed task node."""

        symbol = _SYMBOL.validate_python(symbol, strict=True)
        observed_at = _canonical_shanghai(observed_at)
        session = self._session_factory()
        require_owned_recovery_session(session, (
            ActivePlan, AuditLog, EvaluationLedger, EvaluationResult, MonitorEvent,
            MonitorSequence, PlanActivationState, PlanVersion, TradingCalendar,
        ))
        with session, session.no_autoflush:
            try:
                read_monitor_highwater(session)
                history = read_activation_history(session, symbol)
                _require(all(item.occurred_at <= observed_at for item in history))
                boundary = history[-1]
                if boundary.plan_version_id is None:
                    return UnknownHistoricalClose(HistoricalCloseUnknownReason.INACTIVE_PLAN)
                scope = LegacyCloseRecoveryReader._scope(session, symbol, observed_at, boundary)
                if isinstance(scope, UnknownCloseRecovery):
                    return UnknownHistoricalClose(HistoricalCloseUnknownReason(scope.reason))
                reader = _CompletionReader(session, scope, boundary.sequence)
                anchor = _latest_completed_close(
                    session, scope, reader, observed_at.date() + timedelta(days=1),
                )
                start = (scope.activated_at.date() if anchor is None else
                         anchor.evaluation_identity.official_trade_date + timedelta(days=1))
                if start > observed_at.date():
                    return ()
                missing = []
                for item in _scan_close_suffix(scope, session, reader.read, start):
                    _require(item.status is CompletionStatus.ABSENT
                             and not item.causal_history_gap)
                    missing.append(item.identity.official_trade_date)
                return tuple(missing)
            except ActivationHistoryLimit, _HistoryLimit:
                reason = HistoricalCloseUnknownReason.HISTORY_LIMIT
            except MissingActivationEvidence, _MissingEvidence:
                reason = HistoricalCloseUnknownReason.MISSING_EVIDENCE
            except (*_CONTENT_ERRORS, OverflowError):
                reason = HistoricalCloseUnknownReason.INVALID_EVIDENCE
            return UnknownHistoricalClose(reason)

    def prepare(self, symbol: str, trade_date: date, observed_at: datetime
                ) -> ProvenHistoricalClose | UnknownHistoricalClose:
        symbol = _SYMBOL.validate_python(symbol, strict=True)
        observed_at = _canonical_shanghai(observed_at)
        if type(trade_date) is not date:
            raise TypeError("trade_date must be a date")
        session = self._session_factory()
        require_owned_recovery_session(session, (
            ActivePlan, AuditLog, EvaluationLedger, EvaluationResult, MonitorEvent,
            MonitorSequence, PlanActivationState, PlanVersion, PositionInventoryConfirmation,
            PositionInventoryState, PositionLot, PositionOpeningBalance, RiskState, TradingCalendar,
        ))
        with session, session.no_autoflush:
            try:
                return self._read(session, symbol, trade_date, observed_at)
            except ActivationHistoryLimit, _HistoryLimit:
                reason = HistoricalCloseUnknownReason.HISTORY_LIMIT
            except MissingActivationEvidence, _MissingEvidence:
                reason = HistoricalCloseUnknownReason.MISSING_EVIDENCE
            except _UnknownEvidence as error:
                reason = HistoricalCloseUnknownReason(error.reason)
            except (*_CONTENT_ERRORS, OverflowError):
                reason = HistoricalCloseUnknownReason.INVALID_EVIDENCE
            return UnknownHistoricalClose(reason)

    @staticmethod
    def _read(session, symbol, trade_date, observed_at):
        highwater = read_monitor_highwater(session)
        history = read_activation_history(session, symbol)
        _require(all(item.occurred_at <= observed_at for item in history))
        boundary = history[-1]
        if boundary.plan_version_id is None:
            return UnknownHistoricalClose(HistoricalCloseUnknownReason.INACTIVE_PLAN)
        scope = LegacyCloseRecoveryReader._scope(session, symbol, observed_at, boundary)
        if isinstance(scope, UnknownCloseRecovery):
            return UnknownHistoricalClose(HistoricalCloseUnknownReason(scope.reason))
        reader = _CompletionReader(session, scope, boundary.sequence)
        # A proven committed close is the task checkpoint at any plan age;
        # completed trading decisions are never recalculated.
        anchor = _latest_completed_close(session, scope, reader, trade_date)
        window_start = (
            scope.activated_at.date() if anchor is None
            else anchor.evaluation_identity.official_trade_date + timedelta(days=1)
        )
        completions = {}

        def completion_on(identity):
            value = reader.read(identity)
            completions[identity.official_trade_date] = value
            return value

        absent = []
        proven_results = []
        earlier_absent = False
        for item in _scan_close_suffix(scope, session, completion_on, window_start):
            _require(item.status is not CompletionStatus.UNKNOWN and not item.causal_history_gap)
            _require(not (earlier_absent and item.status is CompletionStatus.PROVEN))
            if item.status is CompletionStatus.ABSENT:
                earlier_absent = True
                absent.append(item)
            else:
                proven_results.append(completions[item.identity.official_trade_date].result)
        _require(bool(absent) and absent[0].identity.official_trade_date == trade_date)
        cutoff = datetime.combine(trade_date, time(15), SHANGHAI)
        inventory = PositionInventoryHistoryReader._read(session, symbol, cutoff, observed_at)
        _require(inventory.high_water_sequence == highwater)
        results = tuple(proven_results)
        _require(all(result.snapshot.signal_type is not SignalType.BLOCKED_DATA
                     for result in results))
        current, risk = _risk_inputs(session, scope, results, cutoff,
                                     anchor=anchor, reader=reader)
        calendar = _calendar(session, scope.plan.market, trade_date)
        return ProvenHistoricalClose(scope, inventory, current, risk, calendar, highwater)


def _scan_close_suffix(scope, session, completion_on, start):
    """Page only the unfinished task suffix; 32 dates is a read batch, not plan expiry."""

    window_start = start
    while True:
        remaining_days = (scope.observed_at.date() - window_start).days + 1
        if remaining_days <= 0:
            raise ValueError("window_start must lie within observed activation history")
        window_end = window_start + timedelta(
            days=min(MAX_CLOSE_DISCOVERY_DAYS, remaining_days) - 1,
        )
        is_open_on = _calendar_open_on(session, window_start, window_end)
        window = discover_missed_closes(
            scope=scope, is_open_on=is_open_on, completion_on=completion_on,
            window_start=window_start, max_calendar_days=MAX_CLOSE_DISCOVERY_DAYS,
        )
        yield from window.candidates
        if window.next_window_start is None:
            return
        window_start = window.next_window_start


def _latest_completed_close(session, scope, reader, target_date):
    """Use the latest committed task node, not the plan's original activation age."""

    anchor_date = session.scalar(select(EvaluationLedger.target_value).where(
        EvaluationLedger.plan_hash == plan_sha256(scope.plan),
        EvaluationLedger.symbol == scope.plan.symbol,
        EvaluationLedger.evaluation_kind == "OFFICIAL_CLOSE",
        EvaluationLedger.formula_version == scope.plan.monitoring.indicator_formula_version,
        EvaluationLedger.target_value < target_date.isoformat(),
        EvaluationLedger.target_value >= scope.activated_at.date().isoformat(),
    ).order_by(EvaluationLedger.target_value.desc()).limit(1))
    if anchor_date is None:
        return None
    day = _date(anchor_date)
    _require(datetime.combine(day, time(15), SHANGHAI) >= scope.activated_at)
    identity = OfficialCloseEvaluationIdentity(
        plan_hash=plan_sha256(scope.plan), symbol=scope.plan.symbol,
        official_trade_date=day,
        formula_version=scope.plan.monitoring.indicator_formula_version,
    )
    completion = reader.read(identity)
    if completion.status is not CompletionStatus.PROVEN or completion.result is None:
        raise _MissingEvidence()
    result = completion.result
    _require(result.snapshot.signal_type is not SignalType.BLOCKED_DATA
             and result.snapshot.market_data_at == datetime.combine(day, time(15), SHANGHAI)
             and result.snapshot.evaluated_at >= result.snapshot.market_data_at
             and result.snapshot.evaluated_at <= scope.observed_at)
    return result


def _checkpoint_transition(session, scope, reader, anchor):
    """Read only stored checkpoints needed to establish the current risk source."""

    checkpoint = anchor
    while not checkpoint.transitions:
        previous = _latest_completed_close(
            session, scope, reader, checkpoint.evaluation_identity.official_trade_date,
        )
        if previous is None:
            raise _MissingEvidence()
        _require(previous.snapshot.signal_type is not SignalType.BLOCKED_DATA
                 and _business(previous.snapshot.risk) == _business(checkpoint.snapshot.risk))
        checkpoint = previous
    _require(len(checkpoint.transitions) == 1)
    previous = _latest_completed_close(
        session, scope, reader, checkpoint.evaluation_identity.official_trade_date,
    )
    _require(previous is None or previous.snapshot.signal_type is not SignalType.BLOCKED_DATA)
    return checkpoint, previous


def _calendar(session, exchange, trade_date):
    start = trade_date - timedelta(days=366)
    fields = {"exchange": 8, "cal_date": 10, "is_open": None, "previous_trade_date": 10}
    query = _bounded_query(TradingCalendar, fields)
    query = query.with_only_columns(*(
        cast(column, Integer).label(column.key) if column.key == "is_open" else column
        for column in query.selected_columns
    )).where(TradingCalendar.exchange == exchange, TradingCalendar.cal_date >= start,
             TradingCalendar.cal_date <= trade_date).limit(368)
    rows = session.execute(query).mappings().all()
    _require(len(rows) <= 367)
    for row in rows:
        raw = _raw(row, fields)
        _require(raw["is_open"] in (0, 1))
        _date(raw["cal_date"])
        _date(raw["previous_trade_date"])
    return MarketReferenceRepository(session).list_trading_days(exchange, start, trade_date)


def _risk_inputs(session, scope, results, cutoff, *, anchor=None, reader=None):
    budget = _ReadBudget()
    fields = {
        "symbol": 9, "plan_hash": 64, "status": 32, "breach_trade_date": 10,
        "prior_close_fen": None, "revision": None, "updated_at": 64,
    }
    rows = budget.rows(session, _bounded_query(RiskState, fields).where(
        RiskState.symbol == scope.plan.symbol,
    ), fields, ("breach_trade_date",))
    current = None
    if rows:
        raw = rows[0]
        written = _timestamp(raw["updated_at"])
        breach = None if raw["breach_trade_date"] is None else _date(raw["breach_trade_date"])
        decoded = RiskStateSnapshot(**(raw | {
            "updated_at": _canonical_shanghai(written), "breach_trade_date": breach,
            "status": RiskStatus(raw["status"]),
        }))
        _require(decoded.revision > 0 and written <= scope.observed_at)
        current = RiskStateRecord(**(raw | {"updated_at": written, "breach_trade_date": breach}))
    audit_fields = _AUDIT | {"created_at": 64}
    audits = budget.rows(session, _bounded_query(AuditLog, audit_fields).where(
        AuditLog.entity_type == "RISK_STATE", AuditLog.entity_id == scope.plan.symbol,
    ), audit_fields, ("before_hash", "after_hash"))
    by_revision = {}
    for audit in audits:
        details = json.loads(audit["details_json"], object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
        _require(type(details) is dict and set(details) == {"revision", "status", "symbol"})
        revision = details["revision"]
        _require(type(revision) is int and revision > 0 and revision not in by_revision)
        _require(audit["action"] == "RISK_STATE_UPDATED"
                 and details["symbol"] == scope.plan.symbol
                 and details["status"] in tuple(item.value for item in RiskStatus)
                 and audit["details_json"] == _canonical_json(details)
                 and _timestamp(audit["created_at"]) <= scope.observed_at)
        by_revision[revision] = audit
    digest = plan_sha256(scope.plan)
    transitions = [transition for result in results for transition in result.transitions]
    _require(all(type(item) is RiskTransitionIntent for item in transitions))
    if current is not None:
        _match_risk_audit(current, by_revision)
        _require(all(revision <= current.revision for revision in by_revision))
    if anchor is not None:
        # A proven completed close is the state checkpoint. The physical risk
        # row may have been written during a later recovery, so a transition's
        # source-effective time is the official close, not that write time.
        risk = anchor.snapshot.risk
        _require(not results)
        _require(len(anchor.transitions) <= 1)
        if current is None or current.plan_hash != digest:
            _require(not anchor.transitions and risk.status is RiskStatus.CLEAR
                     and risk.breach_trade_date is None
                     and (current is not None or not audits)
                     and risk.revision == (0 if current is None else current.revision))
            return current, None
        _require(_business(risk) == _business(current) and reader is not None)
        checkpoint, previous = _checkpoint_transition(session, scope, reader, anchor)
        risk = checkpoint.snapshot.risk
        transition = checkpoint.transitions[0]
        source = checkpoint.snapshot.market_data_at
        _require(source == datetime.combine(
            checkpoint.evaluation_identity.official_trade_date, time(15), SHANGHAI,
        ) and source < cutoff and transition.risk == risk
                 and transition.expected_revision == risk.revision - 1
                 and risk.updated_at == checkpoint.snapshot.evaluated_at)
        prior_risk = None if previous is None else previous.snapshot.risk
        if prior_risk is None or prior_risk.status is RiskStatus.CLEAR:
            _require(risk.status is RiskStatus.BREACHED_PENDING_CONFIRMATION
                     and risk.breach_trade_date == source.date())
        else:
            _require(risk.status in (RiskStatus.CLEAR, RiskStatus.EXIT_PENDING_SETTLEMENT))
            if risk.status is RiskStatus.EXIT_PENDING_SETTLEMENT:
                _require(prior_risk.status is RiskStatus.BREACHED_PENDING_CONFIRMATION
                         and risk.breach_trade_date == prior_risk.breach_trade_date
                         and risk.prior_close_fen == prior_risk.prior_close_fen)
        if prior_risk is not None:
            _require(transition.expected_revision == prior_risk.revision)
        audit = by_revision.get(risk.revision)
        if audit is None:
            raise _MissingEvidence()
        if risk.revision == 1:
            _require(audit["before_hash"] is None)
        else:
            predecessor = by_revision.get(transition.expected_revision)
            if predecessor is None:
                raise _MissingEvidence()
            _require(audit["before_hash"] == predecessor["after_hash"])
        return current, risk.model_copy(update={"updated_at": source})
    if current is None or current.plan_hash != digest:
        _require(not transitions and (current is not None or not audits))
        revision = 0 if current is None else current.revision
        for result in results:
            risk = result.snapshot.risk
            _require(risk.status is RiskStatus.CLEAR and risk.breach_trade_date is None
                     and risk.revision == revision)
        return current, None
    _require(bool(transitions))
    previous = None
    prior_audit = None
    source = None
    initial_revision = transitions[0].expected_revision
    for result in results:
        risk = result.snapshot.risk
        _require(len(result.transitions) <= 1)
        if not result.transitions:
            if previous is None:
                _require(risk.status is RiskStatus.CLEAR and risk.breach_trade_date is None
                         and risk.revision == initial_revision)
            else:
                _require(_business(risk) == _business(previous))
            continue
        transition = result.transitions[0]
        source = result.snapshot.market_data_at
        expected_source = datetime.combine(result.evaluation_identity.official_trade_date,
                                           time(15), SHANGHAI)
        _require(source == expected_source and source < cutoff
                 and transition.risk.updated_at == result.snapshot.evaluated_at
                 and transition.expected_revision == risk.revision - 1)
        if previous is None or previous.status is RiskStatus.CLEAR:
            _require(risk.status is RiskStatus.BREACHED_PENDING_CONFIRMATION
                     and risk.breach_trade_date == source.date())
        else:
            _require(risk.status in (RiskStatus.CLEAR, RiskStatus.EXIT_PENDING_SETTLEMENT))
            if risk.status is RiskStatus.EXIT_PENDING_SETTLEMENT:
                _require(previous.status is RiskStatus.BREACHED_PENDING_CONFIRMATION
                         and risk.breach_trade_date == previous.breach_trade_date
                         and risk.prior_close_fen == previous.prior_close_fen)
        if previous is not None:
            _require(transition.expected_revision == previous.revision)
        audit = by_revision.get(risk.revision)
        if audit is None:
            raise _MissingEvidence()
        persisted = RiskStateRecord(**(risk.model_dump() | {
            "status": risk.status.value, "updated_at": _timestamp(audit["created_at"]),
        }))
        _match_risk_audit(persisted, by_revision)
        if prior_audit is not None:
            _require(audit["before_hash"] == prior_audit["after_hash"])
        elif risk.revision == 1:
            _require(audit["before_hash"] is None)
        else:
            predecessor = by_revision.get(transition.expected_revision)
            if predecessor is None:
                raise _MissingEvidence()
            prior_hash = predecessor["after_hash"]
            _require(type(prior_hash) is str and len(prior_hash) == 64
                     and all(character in "0123456789abcdef" for character in prior_hash)
                     and audit["before_hash"] == prior_hash)
        previous, prior_audit = risk, audit
    _require(previous is not None and _business(previous) == _business(current))
    # Only this input copy substitutes source time. Canonical results and the
    # captured physical row retain their evaluation and writer timestamps.
    return current, previous.model_copy(update={"updated_at": source})


def _business(risk):
    return risk.model_dump(exclude={"updated_at"})


def _match_risk_audit(risk, by_revision):
    audit = by_revision.get(risk.revision)
    if audit is None:
        raise _MissingEvidence()
    _require(audit["after_hash"] == _risk_state_hash(risk)
             and audit["created_at"] == risk.updated_at.isoformat()
             and audit["details_json"] == _canonical_json({
                 "revision": risk.revision, "status": risk.status, "symbol": risk.symbol,
             }))
