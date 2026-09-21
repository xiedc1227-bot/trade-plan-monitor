"""Durable close discovery proves occurrences only, from a single read snapshot."""

from datetime import timedelta
from uuid import uuid1, uuid4

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_recovery_alert_provenance import NOW, _reactivate
from test_recovery_alert_provenance import history as history

from trade_plan_monitor.decision.models import EvaluationResult, SignalType
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import AuditLog, TradingCalendar
from trade_plan_monitor.state.repositories import EvaluationKind
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
def closes(history):
    with history.factory() as session:
        session.add(TradingCalendar(exchange="SSE", cal_date=NOW.date(), is_open=True))
        session.commit()
    return history


def discover(history, **kwargs):
    from trade_plan_monitor.runtime.close_recovery_evidence import LegacyCloseRecoveryReader

    return LegacyCloseRecoveryReader(history.factory).discover(
        history.plan.symbol, kwargs.pop("observed_at", NOW.replace(minute=30)), **kwargs,
    )


def mutate(history, *statements):
    with history.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def test_committed_occurrence_proven_without_alert_and_read_only(closes):
    mutate(closes, "DELETE FROM alert_event",
           "DELETE FROM monitor_event WHERE event_type = 'alert.created'")
    statements = []
    sqlalchemy_event.listen(
        closes.engine, "before_cursor_execute",
        lambda connection, cursor, statement, parameters, context, many: statements.append(
            statement,
        ),
    )
    window = discover(closes)
    assert window.scope.activation_revision == 1
    assert window.scope.plan_version_id == closes.activation.plan_version_id
    assert [item.status for item in window.candidates] == ["PROVEN"]
    assert window.candidates[0].reason == "committed_occurrence_only"
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)


def test_no_claim_no_result_no_publication_is_absent(closes):
    mutate(closes, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type = 'symbol.snapshot.updated'")
    assert discover(closes).candidates[0].status == "ABSENT"


@pytest.mark.parametrize("mutation", [
    "DELETE FROM evaluation_result",
    "UPDATE evaluation_result SET result_json = '{}'",
    "UPDATE evaluation_ledger SET evaluated_at = '2026-08-07T15:06:00+08:00'",
    "DELETE FROM monitor_event WHERE event_type = 'symbol.snapshot.updated'",
    "UPDATE monitor_event SET payload_json = '{}' WHERE event_type = 'symbol.snapshot.updated'",
    "UPDATE monitor_event SET occurred_at = '2026-08-07T15:06:00+08:00' "
    "WHERE event_type = 'symbol.snapshot.updated'",
])
def test_claimed_but_unproven_is_unknown(closes, mutation):
    mutate(closes, mutation)
    assert discover(closes).candidates[0].status == "UNKNOWN"


def test_orphan_canonical_publication_blocks_absence(closes):
    mutate(closes, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger")
    assert discover(closes).candidates[0].status == "UNKNOWN"


@pytest.mark.parametrize("table,column,size", [
    ("evaluation_result", "result_json", 8 * 1024 * 1024 + 1),
    ("evaluation_result", "position_lots_json", 8 * 1024 * 1024 + 1),
    ("monitor_event", "payload_json", 4097),
])
def test_oversized_content_never_disappears_as_absent(closes, table, column, size):
    with closes.engine.begin() as connection:
        suffix = " WHERE event_type = 'symbol.snapshot.updated'" if table == "monitor_event" else ""
        connection.execute(text(f"UPDATE {table} SET {column} = :blob{suffix}"),
                           {"blob": " " * size})
    assert discover(closes).candidates[0].status == "UNKNOWN"


@pytest.mark.parametrize("mutation", [
    "DELETE FROM trading_calendar",
    "UPDATE trading_calendar SET exchange = 'SZSE'",
])
def test_only_known_sse_calendar_can_certify_occurrence(closes, mutation):
    mutate(closes, mutation)
    assert discover(closes).candidates[0].reason == "calendar_unknown"


def test_closed_calendar_suppresses_obligation(closes):
    mutate(closes, "UPDATE trading_calendar SET is_open = 0")
    assert discover(closes).candidates == ()


@pytest.mark.parametrize("mutation", [
    "DELETE FROM active_plan",
    "UPDATE active_plan SET revision = 9",
    "UPDATE plan_activation_state SET revision = 9",
    "UPDATE plan_version SET status = 'DRAFT'",
    "UPDATE plan_version SET plan_hash = 'bad'",
    "UPDATE plan_version SET payload_json = '{}'",
    "DELETE FROM audit_log WHERE action = 'PLAN_ACTIVATED'",
    "UPDATE monitor_sequence SET last_sequence = 0",
])
def test_invalid_scope_never_certifies_absence(closes, mutation):
    mutate(closes, mutation)
    assert discover(closes).status == "UNKNOWN"


def test_inactive_scope_is_typed_unknown(closes):
    closes.clock[0] += timedelta(minutes=1)
    with closes.work() as uow:
        uow.plans.deactivate(closes.plan.symbol, expected_revision=1)
        uow.commit()
    assert discover(closes).reason == "INACTIVE_PLAN"


def test_future_activation_boundary_is_unknown(closes):
    _reactivate(closes)
    assert discover(closes, observed_at=NOW).status == "UNKNOWN"


def test_dirty_session_is_rejected_without_flush(closes):
    from trade_plan_monitor.runtime.close_recovery_evidence import LegacyCloseRecoveryReader

    with closes.factory() as session:
        pending = TradingCalendar(exchange="SSE", cal_date=NOW.date() + timedelta(days=1),
                                  is_open=True)
        session.add(pending)
        with pytest.raises(ValueError, match="fresh"):
            LegacyCloseRecoveryReader(lambda: session).discover(closes.plan.symbol, NOW)
        assert pending in session.new


def test_sql_fault_propagates(closes):
    def fail(connection, cursor, statement, parameters, context, many):
        if "FROM evaluation_result" in statement:
            raise OperationalError(statement, parameters, RuntimeError("test failure"))
    sqlalchemy_event.listen(closes.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        discover(closes)


@pytest.mark.parametrize("beijing, non_v4", [(True, False), (False, True)])
def test_repository_accepted_scope_identifiers_remain_supported(closes, beijing, non_v4):
    plan = closes.plan.model_copy(update={
        "plan_id": "alternative-plan", "version": 2,
        **({"symbol": "920001.BJ", "market": "BSE"} if beijing else {}),
    })
    validation = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)
    with SqlAlchemyUnitOfWork(closes.factory, clock=lambda: NOW.replace(hour=14),
                             id_factory=lambda: str(uuid1() if non_v4 else uuid4())) as uow:
        uow.plans.save_draft(plan, source_text="alternative canonical identifier fixture")
        uow.plans.activate(plan, expected_revision=0 if beijing else 1, validation=validation)
        uow.commit()
    from trade_plan_monitor.runtime.close_recovery_evidence import LegacyCloseRecoveryReader
    result = LegacyCloseRecoveryReader(closes.factory).discover(plan.symbol, NOW.replace(minute=30))
    assert result.candidates[0].status == "ABSENT"


def publish_result(closes, result):
    mutate(closes, "DELETE FROM alert_event", "DELETE FROM evaluation_result",
           "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type = 'symbol.snapshot.updated'")
    identity = result.evaluation_identity
    with closes.work() as uow:
        uow.evaluations.claim(
            plan_hash=identity.plan_hash, symbol=identity.symbol,
            evaluation_kind=EvaluationKind.OFFICIAL_CLOSE, bucket_end=None,
            official_trade_date=identity.official_trade_date,
            formula_version=identity.formula_version, result_hash=result.result_hash,
            evaluated_at=result.snapshot.evaluated_at,
        )
        uow.projections.add_evaluation_result(result)
        uow.events.append(MonitorEventDraft(
            event_id=monitor_event_id(MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, identity.symbol,
                                      identity.model_dump_json(), result.result_hash),
            event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
            aggregate_id=identity.symbol,
            payload=MonitorEventPayload(entity_id=identity.symbol, symbol=identity.symbol,
                                        result_hash=result.result_hash),
            occurred_at=result.snapshot.evaluated_at,
        ))
        uow.commit()


@pytest.mark.parametrize("signal", [SignalType.WAIT, SignalType.BLOCKED_DATA])
def test_no_alert_wait_and_blocked_are_committed_occurrences_only(closes, signal):
    payload = closes.result.model_dump(mode="python", exclude={"result_hash"})
    payload["snapshot"]["signal_type"] = signal
    payload["signal_intent"] = None
    publish_result(closes, EvaluationResult.build(**payload))
    result = discover(closes)
    assert result.candidates[0].status == "PROVEN"
    assert result.candidates[0].reason == "committed_occurrence_only"
    assert not hasattr(result, "replay_ready")


def test_same_hash_reactivation_cannot_claim_old_publication_sequence(closes):
    # Persisted write order is decisive even if timestamps would allow attribution.
    closes.clock[0] = NOW.replace(hour=14, minute=58)
    _reactivate(closes)
    window = discover(closes)
    assert window.scope.activation_revision == 3
    assert window.candidates[0].status == "UNKNOWN"


def test_same_hash_reactivation_after_close_excludes_old_obligation(closes):
    _reactivate(closes)
    window = discover(closes)
    assert window.scope.activation_revision == 3
    assert window.candidates == ()


def test_explicit_plan_is_unsupported_scope(closes):
    from test_explicit_runtime_production import _plan
    plan = _plan(active_date=NOW.date())
    with closes.engine.begin() as connection:
        connection.execute(text("UPDATE plan_version SET plan_id=:id, payload_json=:payload, "
                                "plan_hash=:hash"),
                           {"id": plan.plan_id, "payload": dump_plan_json(plan),
                            "hash": plan_sha256(plan)})
    assert discover(closes).reason == "UNSUPPORTED_PLAN"


def test_history_budget_is_typed_unknown(closes):
    with closes.factory() as session:
        session.add_all(AuditLog(
            id=str(uuid4()), action="PLAN_ACTIVATED", entity_type="ACTIVE_PLAN",
            entity_id=closes.plan.symbol, before_hash=None, after_hash=None,
            details_json="{}", created_at=NOW.isoformat(),
        ) for _ in range(MAX_EVENT_REPLAY_LIMIT))
        session.commit()
    assert discover(closes).reason == "HISTORY_LIMIT"


@pytest.mark.parametrize("exact_exists, expected", [(True, "PROVEN"), (False, "UNKNOWN")])
def test_orphan_scan_budget_never_proves_absence_but_exact_proof_survives(
    closes, exact_exists, expected,
):
    with closes.engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO monitor_event "
            "(id,sequence,event_type,schema_version,aggregate_id,occurred_at,payload_json) "
            "SELECT :id,:sequence,event_type,schema_version,aggregate_id,occurred_at,payload_json "
            "FROM monitor_event WHERE id=:original"
        ), [{"id": str(uuid4()), "sequence": 10 + index,
             "original": str(closes.publication.event_id)}
            for index in range(MAX_EVENT_REPLAY_LIMIT)])
        connection.execute(text("UPDATE monitor_sequence SET last_sequence=:value"),
                           {"value": MAX_EVENT_REPLAY_LIMIT + 9})
    if not exact_exists:
        mutate(closes, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger")
    assert discover(closes).candidates[0].status == expected


@pytest.mark.parametrize("payload", ["{}", " " * 4097])
def test_malformed_orphan_publication_never_means_absent(closes, payload):
    mutate(closes, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger")
    with closes.engine.begin() as connection:
        connection.execute(text("UPDATE monitor_event SET payload_json=:payload "
                                "WHERE event_type='symbol.snapshot.updated'"),
                           {"payload": payload})
    assert discover(closes).candidates[0].status == "UNKNOWN"


@pytest.mark.parametrize("change", ["calendar", "activation"])
def test_reader_uses_one_snapshot_and_next_fresh_reader_observes_concurrent_commit(closes, change):
    changed = False

    def change_after_first_read(connection, cursor, statement, parameters, context, many):
        nonlocal changed
        if changed or "FROM monitor_sequence" not in statement:
            return
        changed = True
        if change == "calendar":
            mutate(closes, "DELETE FROM trading_calendar")
        else:
            _reactivate(closes)

    sqlalchemy_event.listen(closes.engine, "after_cursor_execute", change_after_first_read)
    first = discover(closes)
    assert changed
    assert first.scope.activation_revision == 1
    assert first.candidates[0].status == "PROVEN"
    restarted = discover(closes)
    if change == "calendar":
        assert restarted.candidates[0].reason == "calendar_unknown"
    else:
        assert restarted.scope.activation_revision == 3
        assert restarted.candidates == ()


def test_corrupt_calendar_boolean_is_unknown(closes):
    mutate(closes, "PRAGMA ignore_check_constraints = ON",
           "UPDATE trading_calendar SET is_open=2", "PRAGMA ignore_check_constraints = OFF")
    assert discover(closes).candidates[0].reason == "calendar_unknown"


@pytest.mark.parametrize("value", ["garbage", 1.5])
def test_calendar_cast_cannot_hide_invalid_storage_type(closes, value):
    with closes.engine.begin() as connection:
        connection.execute(text("PRAGMA ignore_check_constraints = ON"))
        connection.execute(text("UPDATE trading_calendar SET is_open=:value"), {"value": value})
        connection.execute(text("PRAGMA ignore_check_constraints = OFF"))
    assert discover(closes).candidates[0].reason == "calendar_unknown"


@pytest.mark.parametrize("table,column", [
    ("plan_version", "payload_json"), ("evaluation_result", "result_json"),
])
def test_blob_payload_is_unknown_without_masking_programming_errors(closes, table, column):
    with closes.engine.begin() as connection:
        connection.execute(text(f"UPDATE {table} SET {column}=:value"), {"value": b"{}"})
    outcome = discover(closes)
    if table == "plan_version":
        assert outcome.status == "UNKNOWN"
    else:
        assert outcome.candidates[0].status == "UNKNOWN"


def test_preused_session_is_rejected(closes):
    from trade_plan_monitor.runtime.close_recovery_evidence import LegacyCloseRecoveryReader
    with closes.factory() as session:
        cached = session.get(TradingCalendar, ("SSE", NOW.date()))
        session.commit()
        with pytest.raises(ValueError, match="fresh"):
            LegacyCloseRecoveryReader(lambda: session).discover(closes.plan.symbol, NOW)
        assert cached in session
