"""Recovery evidence must never borrow a caller's transaction or split snapshots."""

from datetime import timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_close_recovery_evidence import NOW, discover, mutate
from test_close_recovery_evidence import closes as closes
from test_close_recovery_evidence import history as history

from trade_plan_monitor.notifications.recovery_provenance import LegacyAlertOriginReader
from trade_plan_monitor.runtime.close_recovery_evidence import LegacyCloseRecoveryReader
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertEvent,
    AuditLog,
    EvaluationLedger,
    EvaluationResult,
    MonitorEvent,
    MonitorSequence,
    PlanActivationState,
    PlanVersion,
    TradingCalendar,
)

_SHARED_MODELS = (
    MonitorSequence, MonitorEvent, AuditLog, PlanActivationState, ActivePlan,
    PlanVersion, EvaluationLedger, EvaluationResult,
)
_READER_MODELS = {
    "close": (*_SHARED_MODELS, TradingCalendar),
    "origin": (*_SHARED_MODELS, AlertEvent),
}


class ObservedSession(Session):
    """Observe lifecycle effects while retaining real SQLAlchemy behavior."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects = []

    def __enter__(self):
        self.effects.append("enter")
        return super().__enter__()

    def flush(self, *args, **kwargs):
        self.effects.append("flush")
        return super().flush(*args, **kwargs)

    def commit(self):
        self.effects.append("commit")
        return super().commit()

    def rollback(self):
        self.effects.append("rollback")
        return super().rollback()

    def close(self):
        self.effects.append("close")
        return super().close()


def _read(kind, closes, factory):
    if kind == "close":
        return LegacyCloseRecoveryReader(factory).discover(
            closes.plan.symbol, NOW.replace(minute=30),
        )
    return LegacyAlertOriginReader(factory).read(closes.alert.event_id)


def _status(kind, outcome):
    return outcome.candidates[0].status if kind == "close" else outcome.status


def _assert_rejected(kind, closes, session, *engines):
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    session.effects.clear()
    for engine in engines:
        event.listen(engine, "before_cursor_execute", observe)
    try:
        try:
            outcome = _read(kind, closes, lambda: session)
        except ValueError:
            pass
        else:
            pytest.fail(f"Reader accepted unsafe session: {_status(kind, outcome)}")
        assert session.effects == [], "Rejected sessions remain owned by their caller"
        assert statements == [], "Binding validation must precede every SQL statement"
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("kind", _READER_MODELS)
def test_uncommitted_persisted_close_evidence_cannot_be_reported_as_proven(closes, kind):
    tables = (EvaluationLedger.__table__, EvaluationResult.__table__,
              MonitorEvent.__table__, AlertEvent.__table__)
    with closes.factory() as original:
        persisted = {}
        for table in tables:
            query = select(table)
            if table is MonitorEvent.__table__:
                query = query.where(table.c.event_type.in_(
                    ["symbol.snapshot.updated", "alert.created"],
                ))
            persisted[table] = [dict(row) for row in original.execute(query).mappings()]
    mutate(closes, "DELETE FROM alert_event", "DELETE FROM evaluation_result",
           "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type IN "
           "('symbol.snapshot.updated', 'alert.created')")
    expected = "ABSENT" if kind == "close" else "UNKNOWN"
    assert _status(kind, _read(kind, closes, closes.factory)) == expected

    with closes.factory() as writer:
        for table in tables:
            writer.execute(table.insert(), persisted[table])
        connection = writer.connection()
        transaction = connection.get_transaction()
        assert _status(kind, _read(kind, closes, closes.factory)) == expected
        borrowed = ObservedSession(bind=connection)
        try:
            assert not borrowed.in_transaction()
            assert not borrowed.identity_map
            _assert_rejected(kind, closes, borrowed, closes.engine)
            assert connection.get_transaction() is transaction
            assert transaction.is_active
            assert writer.scalar(select(EvaluationLedger.result_hash)) == closes.result.result_hash
            writer.commit()
        finally:
            Session.close(borrowed)
    assert _status(kind, _read(kind, closes, closes.factory)) == "PROVEN"


@pytest.mark.parametrize("kind", _READER_MODELS)
def test_idle_connection_bound_session_is_rejected_before_starting_transaction(closes, kind):
    with closes.engine.connect() as connection:
        session = ObservedSession(bind=connection)
        try:
            assert not connection.in_transaction()
            _assert_rejected(kind, closes, session, closes.engine)
            assert not connection.in_transaction()
            assert not connection.closed
        finally:
            Session.close(session)


@pytest.mark.parametrize("routing", ["mapper", "table"])
@pytest.mark.parametrize(
    "kind,model",
    [(kind, model) for kind, models in _READER_MODELS.items() for model in models],
    ids=[f"{kind}-{model.__name__}"
         for kind, models in _READER_MODELS.items() for model in models],
)
def test_each_evidence_binding_rejects_caller_connection(closes, kind, model, routing):
    with closes.factory() as writer:
        connection = writer.connection()
        transaction = connection.get_transaction()
        key = model if routing == "mapper" else model.__table__
        session = ObservedSession(bind=closes.engine, binds={key: connection})
        try:
            _assert_rejected(kind, closes, session, closes.engine)
            assert connection.get_transaction() is transaction
            assert transaction.is_active
        finally:
            Session.close(session)


@pytest.mark.parametrize("kind", _READER_MODELS)
@pytest.mark.parametrize("routing", ["mapper", "table"])
def test_same_file_via_different_engine_cannot_split_the_snapshot(closes, kind, routing):
    other_engine = create_sqlite_engine(closes.engine.url.database)
    key = EvaluationResult if routing == "mapper" else EvaluationResult.__table__
    session = ObservedSession(bind=closes.engine, binds={key: other_engine})
    try:
        _assert_rejected(kind, closes, session, closes.engine, other_engine)
    finally:
        Session.close(session)
        other_engine.dispose()


@pytest.mark.parametrize("kind", _READER_MODELS)
def test_unbound_session_is_rejected_without_taking_ownership(closes, kind):
    session = ObservedSession()
    try:
        _assert_rejected(kind, closes, session, closes.engine)
    finally:
        Session.close(session)


@pytest.mark.parametrize("kind", _READER_MODELS)
@pytest.mark.parametrize("state", ["active", "pending", "dirty"])
def test_caller_owned_session_is_untouched_on_rejection(closes, kind, state):
    session = ObservedSession(bind=closes.engine)
    try:
        if state == "active":
            session.begin()
        elif state == "pending":
            row = TradingCalendar(exchange="SSE", cal_date=NOW.date() + timedelta(days=1),
                                  is_open=True)
            session.add(row)
        else:
            row = session.get(TradingCalendar, ("SSE", NOW.date()))
            row.is_open = False
        transaction = session.get_transaction()
        _assert_rejected(kind, closes, session, closes.engine)
        assert session.get_transaction() is transaction
        assert transaction.is_active
        if state == "pending":
            assert row in session.new
        elif state == "dirty":
            assert row in session.dirty
            assert row.is_open is False
        assert discover(closes).candidates[0].status == "PROVEN"
    finally:
        Session.close(session)


@pytest.mark.parametrize("kind", _READER_MODELS)
@pytest.mark.parametrize("routing", ["mapper", "table"])
def test_explicit_routes_to_one_engine_preserve_valid_proofs(closes, kind, routing):
    bindings = {
        model if routing == "mapper" else model.__table__: closes.engine
        for model in _READER_MODELS[kind]
    }
    session = ObservedSession(bind=closes.engine, binds=bindings)
    outcome = _read(kind, closes, lambda: session)
    assert _status(kind, outcome) == "PROVEN"
    assert "flush" not in session.effects
    assert "commit" not in session.effects
    assert session.effects == ["enter", "close"]
