"""Offline connected historical input proof, never delivery permission."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_close_recovery_evidence import mutate
from test_recovery_alert_provenance import NOW
from test_recovery_alert_provenance import history as history

from trade_plan_monitor.decision.models import (
    EvaluationResult,
    RiskStatus,
    RiskTransitionIntent,
    SignalType,
)
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    PositionInventoryState,
    RiskState,
    TradingCalendar,
)
from trade_plan_monitor.state.repositories import EvaluationKind

TARGET = NOW.date() + timedelta(days=3)
OBSERVED = NOW + timedelta(days=3, minutes=25)


@pytest.fixture
def historical(history):
    mutate(history, "DELETE FROM alert_event", "DELETE FROM evaluation_result",
           "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type IN "
           "('symbol.snapshot.updated', 'alert.created')")
    with history.factory() as session:
        session.add(PositionInventoryState(symbol=history.plan.symbol, revision=0))
        session.add_all(TradingCalendar(
            exchange=exchange, cal_date=NOW.date() + timedelta(days=offset),
            is_open=offset not in (1, 2),
            previous_trade_date=NOW.date() + timedelta(days=offset - 1),
        ) for exchange in {"SSE", history.plan.market} for offset in range(7))
        session.commit()
    return history


def prepare(historical, day=TARGET, observed=OBSERVED):
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    return LegacyHistoricalCloseReader(historical.factory).prepare(
        historical.plan.symbol, day, observed,
    )


def publish(historical, *, day=None, risk=None, transition=True, writer=None,
            source_missing=False, signal_type=SignalType.WAIT):
    day = NOW.date() if day is None else day
    payload = historical.result.model_dump(mode="python", exclude={"result_hash"})
    evaluated = NOW.replace(year=day.year, month=day.month, day=day.day)
    payload["evaluation_identity"]["official_trade_date"] = day
    payload["snapshot"]["evaluated_at"] = evaluated
    payload["snapshot"]["market_data_at"] = evaluated.replace(minute=0)
    if source_missing:
        payload["snapshot"]["market_data_at"] = None
        payload["snapshot"]["price_fen"] = None
    payload["snapshot"]["data_health"]["latest_bar_end"] = evaluated
    payload["snapshot"]["signal_type"] = signal_type
    payload["signal_intent"] = None
    if risk is not None:
        payload["snapshot"]["risk"] = risk
    result = EvaluationResult.build(**payload)
    if transition:
        payload["transitions"] = (RiskTransitionIntent(
            risk=result.snapshot.risk, expected_revision=result.snapshot.risk.revision - 1,
        ),)
        result = EvaluationResult.build(**payload)
    historical.clock[0] = writer or evaluated + timedelta(minutes=1)
    with historical.work() as uow:
        identity = result.evaluation_identity
        if transition:
            values = result.snapshot.risk.model_dump(exclude={"updated_at", "revision"})
            uow.risk.upsert(**values, expected_revision=result.snapshot.risk.revision - 1)
        uow.evaluations.claim(
            plan_hash=identity.plan_hash, symbol=identity.symbol,
            evaluation_kind=EvaluationKind.OFFICIAL_CLOSE, bucket_end=None,
            official_trade_date=day, formula_version=identity.formula_version,
            result_hash=result.result_hash, evaluated_at=evaluated,
        )
        uow.projections.add_evaluation_result(result)
        uow.events.append(MonitorEventDraft(
            event_id=monitor_event_id(MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, identity.symbol,
                                      identity.model_dump_json(), result.result_hash),
            event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, aggregate_id=identity.symbol,
            payload=MonitorEventPayload(entity_id=identity.symbol, symbol=identity.symbol,
                                       result_hash=result.result_hash),
            occurred_at=evaluated,
        ))
        uow.commit()
    return result


def initial_risk(historical, revision=0, price=6000):
    return historical.result.snapshot.risk.model_copy(update={
        "status": RiskStatus.CLEAR, "breach_trade_date": None,
        "revision": revision, "prior_close_fen": price,
    })


def test_missing_risk_with_compatible_initial_result_can_seed_clear(historical):
    publish(historical, risk=initial_risk(historical), transition=False)
    proof = prepare(historical)
    assert proof.status == "PROVEN"
    assert proof.current_risk is None and proof.risk_state is None
    assert proof.inventory.current_revision == 0
    assert proof.scope.activation_revision == 1


def test_prior_blocked_data_occurrence_cannot_prove_causal_risk_history(historical):
    publish(historical, risk=initial_risk(historical), transition=False,
            signal_type=SignalType.BLOCKED_DATA)
    assert prepare(historical).status == "UNKNOWN"


def test_source_cutoff_is_separate_from_evaluation_and_writer_clock(historical):
    result = publish(historical)
    proof = prepare(historical)
    assert proof.status == "PROVEN"
    assert proof.current_risk.updated_at == NOW + timedelta(minutes=1)
    assert proof.risk_state.updated_at == NOW.replace(minute=0)
    assert result.snapshot.risk.updated_at == NOW


def test_same_plan_row_without_attributable_transition_is_unknown(historical):
    publish(historical)
    mutate(historical, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type='symbol.snapshot.updated'")
    assert prepare(historical, NOW.date()).status == "UNKNOWN"


def test_database_fault_propagates(historical):
    def fail(connection, cursor, statement, parameters, context, many):
        if "FROM monitor_sequence" in statement:
            raise OperationalError(statement, parameters, RuntimeError("offline fault"))
    event.listen(historical.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        prepare(historical)


def test_borrowed_session_is_rejected_without_closing(historical):
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    with historical.factory() as session:
        session.execute(text("SELECT 1"))
        transaction = session.get_transaction()
        with pytest.raises(ValueError, match="fresh"):
            LegacyHistoricalCloseReader(lambda: session).prepare(
                historical.plan.symbol, TARGET, OBSERVED,
            )
        assert session.get_transaction() is transaction


def test_later_wait_keeps_transition_source_even_with_new_snapshot_time(historical):
    original = publish(historical)
    wait_risk = original.snapshot.risk.model_copy(update={"updated_at": OBSERVED})
    publish(historical, day=TARGET, risk=wait_risk.model_copy(update={
        "updated_at": OBSERVED.replace(minute=5),
    }), transition=False)
    proof = prepare(historical, TARGET + timedelta(days=1), OBSERVED + timedelta(days=1))
    assert proof.status == "PROVEN"
    assert proof.risk_state.updated_at == NOW.replace(minute=0)
    assert proof.current_risk.updated_at == NOW + timedelta(minutes=1)


def test_different_plan_uses_physical_revision_and_varying_initial_close(historical):
    historical.clock[0] = NOW
    with historical.work() as uow:
        row = uow.risk.upsert(symbol=historical.plan.symbol, plan_hash="f" * 64,
                             status="CLEAR", breach_trade_date=None,
                             prior_close_fen=5500, expected_revision=0)
        uow.commit()
    publish(historical, risk=initial_risk(historical, row.revision), transition=False)
    publish(historical, day=TARGET, risk=initial_risk(historical, row.revision, 6100),
            transition=False)
    proof = prepare(historical, TARGET + timedelta(days=1), OBSERVED + timedelta(days=1))
    assert proof.status == "PROVEN"
    assert proof.risk_state is None
    assert proof.current_risk.revision == 1 and proof.current_risk.plan_hash == "f" * 64


@pytest.mark.parametrize("mutation", (
    "UPDATE audit_log SET before_hash='" + "a" * 64 + "' "
    "WHERE entity_type='RISK_STATE' AND json_extract(details_json,'$.revision')=2",
    "DELETE FROM audit_log WHERE entity_type='RISK_STATE' "
    "AND json_extract(details_json,'$.revision')=1",
))
def test_first_scoped_transition_must_link_to_physical_predecessor_audit(
    historical, mutation,
):
    historical.clock[0] = NOW
    with historical.work() as uow:
        uow.risk.upsert(symbol=historical.plan.symbol, plan_hash="f" * 64,
                        status="CLEAR", breach_trade_date=None,
                        prior_close_fen=5500, expected_revision=0)
        uow.commit()
    publish(historical, risk=historical.result.snapshot.risk.model_copy(update={
        "revision": 2,
    }))
    assert prepare(historical).status == "PROVEN"
    mutate(historical, mutation)
    assert prepare(historical).status == "UNKNOWN"


@pytest.mark.parametrize("mutation", [
    "DELETE FROM risk_state",
    "UPDATE risk_state SET plan_hash='" + "f" * 64 + "'",
    "DELETE FROM audit_log WHERE entity_type='RISK_STATE'",
    "UPDATE audit_log SET details_json='{}' WHERE entity_type='RISK_STATE'",
    "UPDATE audit_log SET after_hash='bad' WHERE entity_type='RISK_STATE'",
    "UPDATE audit_log SET created_at='2026-08-07T15:07:00+08:00' "
    "WHERE entity_type='RISK_STATE'",
    "UPDATE risk_state SET revision=2",
    "UPDATE risk_state SET updated_at='2026-08-11T15:00:00+08:00'",
    "UPDATE risk_state SET prior_close_fen=6100",
    "UPDATE risk_state SET prior_close_fen='broken'",
])
def test_contradictory_risk_or_audit_is_unknown(historical, mutation):
    publish(historical)
    mutate(historical, mutation)
    assert prepare(historical).status == "UNKNOWN"


def test_missing_risk_with_orphan_audit_cannot_seed_initial(historical):
    publish(historical)
    mutate(historical, "DELETE FROM risk_state", "DELETE FROM evaluation_result",
           "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type='symbol.snapshot.updated'")
    assert prepare(historical, NOW.date()).status == "UNKNOWN"


def test_missing_risk_with_noninitial_snapshot_cannot_seed_initial(historical):
    publish(historical, transition=False)
    assert prepare(historical).status == "UNKNOWN"


def test_wait_cannot_silently_change_risk_business_fields(historical):
    result = publish(historical)
    publish(historical, day=TARGET, transition=False,
            risk=result.snapshot.risk.model_copy(update={"prior_close_fen": 6100}))
    assert prepare(historical, TARGET + timedelta(days=1),
                   OBSERVED + timedelta(days=1)).status == "UNKNOWN"


def test_target_must_be_earliest_absence_and_later_commit_is_causal_gap(historical):
    assert prepare(historical).status == "UNKNOWN"
    assert prepare(historical, NOW.date()).status == "PROVEN"
    publish(historical, day=TARGET, risk=initial_risk(historical), transition=False)
    assert prepare(historical, NOW.date()).status == "UNKNOWN"


def test_unknown_calendar_or_claim_in_later_suffix_blocks_preparation(historical):
    mutate(historical, "DELETE FROM trading_calendar WHERE cal_date='2026-08-10'")
    assert prepare(historical, NOW.date()).status == "UNKNOWN"


def test_whole_activation_span_cannot_be_truncated_to_recent_days(historical):
    result = prepare(historical, NOW.date(), NOW + timedelta(days=32))
    assert result.status == "UNKNOWN" and result.reason == "HISTORY_LIMIT"


@pytest.mark.parametrize("corrupt_anchor", [False, True])
def test_long_lived_plan_resumes_after_latest_committed_close(historical, corrupt_anchor):
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader

    anchor_day = NOW.date() + timedelta(days=35)
    target_day = anchor_day + timedelta(days=1)
    observed = datetime.combine(target_day, NOW.timetz()).replace(hour=17)
    with historical.factory() as session:
        session.add_all(TradingCalendar(
            exchange=exchange, cal_date=day, is_open=True,
            previous_trade_date=day - timedelta(days=1),
        ) for exchange in {"SSE", historical.plan.market}
            for day in (anchor_day, target_day))
        session.commit()
    anchor_time = datetime.combine(anchor_day, NOW.timetz())
    publish(historical, day=anchor_day, risk=historical.result.snapshot.risk.model_copy(
        update={"updated_at": anchor_time, "breach_trade_date": anchor_day},
    ))
    if corrupt_anchor:
        mutate(historical, "UPDATE audit_log SET before_hash='" + "f" * 64
               + "' WHERE entity_type='RISK_STATE'")

    reader = LegacyHistoricalCloseReader(historical.factory)
    assert reader.missing_targets(historical.plan.symbol, observed) == (target_day,)
    assert reader.prepare(historical.plan.symbol, target_day, observed).status == (
        "UNKNOWN" if corrupt_anchor else "PROVEN"
    )


def test_inventory_classification_is_preserved(historical):
    mutate(historical, "UPDATE position_inventory_state SET revision=257")
    result = prepare(historical, NOW.date())
    assert result.status == "UNKNOWN" and result.reason == "HISTORY_LIMIT"


def test_successful_reader_performs_only_reads(historical):
    publish(historical)
    statements = []
    event.listen(historical.engine, "before_cursor_execute",
                 lambda connection, cursor, statement, parameters, context, many:
                 statements.append(statement))
    assert prepare(historical).status == "PROVEN"
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)


def test_sellability_calendar_cannot_coerce_invalid_boolean(historical):
    publish(historical)
    with historical.engine.begin() as connection:
        connection.execute(text("PRAGMA ignore_check_constraints = ON"))
        connection.execute(text("UPDATE trading_calendar SET is_open=2 "
                                "WHERE exchange=:exchange AND cal_date='2026-08-09'"),
                           {"exchange": historical.plan.market})
        connection.execute(text("PRAGMA ignore_check_constraints = OFF"))
    assert prepare(historical).status == "UNKNOWN"


def test_transition_requires_actual_source_and_evaluation_timestamp(historical):
    publish(historical, source_missing=True)
    assert prepare(historical).status == "UNKNOWN"


def test_transition_risk_timestamp_cannot_be_an_older_snapshot_time(historical):
    risk = historical.result.snapshot.risk.model_copy(update={"updated_at": NOW.replace(minute=0)})
    publish(historical, risk=risk)
    assert prepare(historical).status == "UNKNOWN"


def test_current_risk_audit_must_be_unique_and_collection_bounded(historical):
    publish(historical)
    with historical.factory() as session:
        original = session.scalar(select(AuditLog).where(AuditLog.entity_type == "RISK_STATE"))
        copies = {column.name: getattr(original, column.name)
                  for column in AuditLog.__table__.columns if column.name != "id"}
        session.add(AuditLog(id=str(uuid4()), **copies))
        session.commit()
    assert prepare(historical).status == "UNKNOWN"
    with historical.factory() as session:
        session.add_all(AuditLog(id=str(uuid4()), **copies) for _ in range(255))
        session.commit()
    assert prepare(historical).reason == "HISTORY_LIMIT"


@pytest.mark.parametrize("corrupt", [False, True])
def test_prior_transition_chain_requires_matching_audit_links(historical, corrupt):
    publish(historical)
    risk = initial_risk(historical, revision=2).model_copy(update={
        "updated_at": OBSERVED.replace(minute=5),
    })
    publish(historical, day=TARGET, risk=risk)
    if corrupt:
        mutate(historical, "UPDATE audit_log SET before_hash='" + "f" * 64
               + "' WHERE entity_type='RISK_STATE' AND "
               "json_extract(details_json,'$.revision')=2")
    proof = prepare(historical, TARGET + timedelta(days=1), OBSERVED + timedelta(days=1))
    assert proof.status == ("UNKNOWN" if corrupt else "PROVEN")
    if not corrupt:
        assert proof.risk_state.status is RiskStatus.CLEAR
        assert proof.risk_state.updated_at == OBSERVED.replace(minute=0)


def test_snapshot_is_coherent_across_concurrent_writer(historical):
    publish(historical)
    changed = False

    def change_after_highwater(connection, cursor, statement, parameters, context, many):
        nonlocal changed
        if not changed and "FROM monitor_sequence" in statement:
            changed = True
            mutate(historical, "UPDATE risk_state SET prior_close_fen=6100")

    event.listen(historical.engine, "after_cursor_execute", change_after_highwater)
    assert prepare(historical).status == "PROVEN"
    assert changed
    assert prepare(historical).status == "UNKNOWN"


def test_other_plan_tip_cannot_hide_a_later_orphan_risk_audit(historical):
    historical.clock[0] = NOW
    with historical.work() as uow:
        uow.risk.upsert(symbol=historical.plan.symbol, plan_hash="f" * 64,
                        status="CLEAR", breach_trade_date=None,
                        prior_close_fen=5500, expected_revision=0)
        uow.commit()
    with historical.factory() as session:
        session.add(AuditLog(
            id=str(uuid4()), action="RISK_STATE_UPDATED", entity_type="RISK_STATE",
            entity_id=historical.plan.symbol, before_hash="f" * 64, after_hash="f" * 64,
            details_json='{"revision":2,"status":"CLEAR","symbol":"003043.SZ"}',
            created_at=NOW.isoformat(),
        ))
        session.commit()
    assert prepare(historical, NOW.date()).status == "UNKNOWN"


@pytest.mark.parametrize("model", [RiskState, PositionInventoryState, TradingCalendar])
def test_all_reader_tables_must_use_the_owned_engine(historical, model, tmp_path):
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    from trade_plan_monitor.state.database import create_sqlite_engine

    other = create_sqlite_engine(tmp_path / "other.db")
    try:
        with Session(bind=historical.engine, binds={model: other}) as session:
            with pytest.raises(ValueError, match="one engine"):
                LegacyHistoricalCloseReader(lambda: session).prepare(
                    historical.plan.symbol, TARGET, OBSERVED,
                )
            assert not session.in_transaction()
    finally:
        other.dispose()


def test_connection_bound_session_cannot_borrow_uncommitted_evidence(historical):
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    with historical.engine.connect() as connection, Session(bind=connection) as session:
        with pytest.raises(ValueError, match="SQLite engine"):
            LegacyHistoricalCloseReader(lambda: session).prepare(
                historical.plan.symbol, TARGET, OBSERVED,
            )
        assert not connection.in_transaction()


@pytest.mark.parametrize("repeat_pending", [False, True])
def test_transition_chain_rejects_incompatible_pending_state(historical, repeat_pending):
    result = publish(historical)
    pending = result.snapshot.risk.model_copy(update={
        "status": RiskStatus.EXIT_PENDING_SETTLEMENT, "revision": 2,
        "prior_close_fen": 6000 if repeat_pending else 6100,
        "updated_at": OBSERVED.replace(minute=5),
    })
    publish(historical, day=TARGET, risk=pending)
    target, observed = TARGET + timedelta(days=1), OBSERVED + timedelta(days=1)
    if repeat_pending:
        publish(historical, day=target, risk=pending.model_copy(update={
            "revision": 3, "updated_at": observed.replace(minute=5),
        }))
        target, observed = target + timedelta(days=1), observed + timedelta(days=1)
    assert prepare(historical, target, observed).status == "UNKNOWN"
