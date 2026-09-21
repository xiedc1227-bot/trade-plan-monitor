"""Offline proofs of original legacy alert attribution, never delivery eligibility."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EvaluationResult,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationIdentity,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import OfficialCloseBelowLevelCondition
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.notifications.models import AlertPayload, build_alert_payload
from trade_plan_monitor.notifications.render import render_alert
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MonitorEventDraft,
    MonitorEventLog,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.repositories import EvaluationKind
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 7, 15, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


def _result(plan):
    digest = plan_sha256(plan)
    evidence = ConditionEvidence(
        condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
        outcome=ConditionOutcome.SATISFIED,
    )
    next_step = NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
    signal = SignalIntent(
        signal_type=ActionableSignalType.RISK_BREACH,
        plan_hash=digest,
        symbol=plan.symbol,
        trading_date=NOW.date(),
        cause_id="risk-origin",
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    snapshot = SymbolDecisionSnapshot(
        symbol=plan.symbol,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=digest,
        evaluated_at=NOW,
        market_data_at=NOW.replace(minute=0),
        price_fen=6000,
        zone=DecisionZone.BELOW_RISK,
        signal_type=SignalType.RISK_BREACH,
        position=PositionSummary(
            core_quantity=0,
            tactical_quantity=0,
            total_quantity=0,
            sellable_core_quantity=0,
            sellable_tactical_quantity=0,
        ),
        episode=None,
        risk=RiskStateSnapshot(
            symbol=plan.symbol,
            plan_hash=digest,
            status=RiskStatus.BREACHED_PENDING_CONFIRMATION,
            breach_trade_date=NOW.date(),
            prior_close_fen=6000,
            revision=1,
            updated_at=NOW,
        ),
        data_health=DataHealthSnapshot(
            symbol=plan.symbol,
            status=DataHealthStatus.LIVE,
            latest_bar_end=NOW,
            data_age_seconds=0,
            required_data_complete=True,
            fresh=True,
        ),
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=OfficialCloseEvaluationIdentity(
            plan_hash=digest, symbol=plan.symbol, official_trade_date=NOW.date()
        ),
    )


@pytest.fixture
def history(tmp_path):
    engine = create_sqlite_engine(tmp_path / "provenance.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    source = (Path(__file__).parents[2] / "config/plans/003043.SZ.sample.yaml").read_text(
        encoding="utf-8"
    )
    plan = load_plan_yaml(source)
    validation = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)
    clock = [NOW - timedelta(minutes=10)]

    def work():
        return SqlAlchemyUnitOfWork(factory, clock=lambda: clock[0])

    with work() as uow:
        uow.plans.save_draft(plan, source_text=source)
        activation = uow.plans.activate(plan, expected_revision=0, validation=validation)
        uow.commit()
    clock[0] = NOW
    result = _result(plan)
    with work() as uow:
        identity = result.evaluation_identity
        uow.evaluations.claim(
            plan_hash=identity.plan_hash,
            symbol=identity.symbol,
            evaluation_kind=EvaluationKind.OFFICIAL_CLOSE,
            bucket_end=None,
            official_trade_date=identity.official_trade_date,
            formula_version=identity.formula_version,
            result_hash=result.result_hash,
            evaluated_at=NOW,
        )
        uow.projections.add_evaluation_result(result)
        publication = uow.events.append(
            MonitorEventDraft(
                event_id=monitor_event_id(
                    MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                    plan.symbol,
                    identity.model_dump_json(),
                    result.result_hash,
                ),
                event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                aggregate_id=plan.symbol,
                payload=MonitorEventPayload(
                    entity_id=plan.symbol, symbol=plan.symbol, result_hash=result.result_hash
                ),
                occurred_at=NOW,
            )
        )
        alert = uow.alerts.enqueue(build_alert_payload(event_id=uuid4(), plan=plan, result=result))
        uow.commit()
    yield SimpleNamespace(
        engine=engine,
        factory=factory,
        plan=plan,
        validation=validation,
        work=work,
        clock=clock,
        activation=activation,
        result=result,
        publication=publication,
        alert=alert,
    )
    engine.dispose()


def _read(history):
    from trade_plan_monitor.notifications.recovery_provenance import LegacyAlertOriginReader

    return LegacyAlertOriginReader(history.factory).read(history.alert.event_id)


def _reactivate(history):
    history.clock[0] += timedelta(minutes=1)
    with history.work() as uow:
        uow.plans.deactivate(history.plan.symbol, expected_revision=1)
        uow.plans.activate(history.plan, expected_revision=2, validation=history.validation)
        uow.commit()


def test_proves_committed_original_identity_without_writes_or_replay_horizon(history):
    statements = []
    sqlalchemy_event.listen(
        history.engine,
        "before_cursor_execute",
        lambda connection, cursor, statement, parameters, context, many: statements.append(
            statement
        ),
    )
    origin = _read(history)
    assert origin.status == "PROVEN"
    assert origin.event == history.alert
    assert origin.plan_version_id == history.activation.plan_version_id
    assert origin.activation_revision == 1
    assert origin.evaluation_identity == history.result.evaluation_identity
    assert origin.result_hash == history.result.result_hash
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)


def test_same_hash_reactivation_never_relabels_original(history):
    _reactivate(history)
    assert _read(history).activation_revision == 1


def test_old_origin_is_queryable_after_replay_horizon(history):
    with history.factory() as session:
        events = MonitorEventLog(session, clock=lambda: NOW + timedelta(days=8))
        assert events.replay_page_after(0, limit=100).requires_snapshot
    assert _read(history).status == "PROVEN"


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM evaluation_result",
        "UPDATE evaluation_result SET result_json = '{}'",
        "UPDATE plan_version SET payload_json = '{}'",
        "UPDATE alert_event SET payload_json = '{}'",
        "DELETE FROM monitor_event WHERE event_type = 'plan.activated'",
        "DELETE FROM audit_log WHERE action = 'PLAN_ACTIVATED'",
        "UPDATE audit_log SET details_json = '{}' WHERE action = 'PLAN_ACTIVATED'",
        "UPDATE monitor_event SET payload_json = '{}' WHERE event_type = 'symbol.snapshot.updated'",
        "DELETE FROM monitor_event WHERE event_type = 'symbol.snapshot.updated'",
        "UPDATE evaluation_ledger SET evaluated_at = '2026-08-07T15:06:00+08:00'",
        "UPDATE audit_log SET after_hash = 'wrong' WHERE action = 'PLAN_ACTIVATED'",
        "UPDATE monitor_event SET occurred_at = '2026-08-07T15:06:00+08:00' "
        "WHERE event_type = 'alert.created'",
        "UPDATE monitor_event SET sequence = 99 WHERE event_type = 'alert.created'",
        "DELETE FROM alert_event",
    ],
)
def test_missing_or_corrupt_historical_evidence_is_unknown(history, mutation):
    with history.engine.begin() as connection:
        connection.execute(text(mutation))
    assert _read(history).status == "UNKNOWN"


def test_duplicate_activation_audit_is_ambiguous(history):
    with history.factory() as session:
        original = session.scalar(select(AuditLog).where(AuditLog.action == "PLAN_ACTIVATED"))
        session.add(
            AuditLog(
                id=str(uuid4()),
                action=original.action,
                entity_type=original.entity_type,
                entity_id=original.entity_id,
                before_hash=original.before_hash,
                after_hash=original.after_hash,
                details_json=original.details_json,
                created_at=original.created_at,
            )
        )
        session.commit()
    assert _read(history).status == "UNKNOWN"


def test_publication_cannot_cross_activation_interval(history):
    _reactivate(history)
    with history.engine.begin() as connection:
        connection.execute(
            text("UPDATE monitor_event SET sequence = 100 WHERE id = :id"),
            {"id": str(history.alert.event_id)},
        )
        connection.execute(text("UPDATE alert_event SET sequence = 100"))
    assert _read(history).status == "UNKNOWN"


def test_missing_boundary_event_is_not_hidden_by_older_activation(history):
    _reactivate(history)
    with history.engine.begin() as connection:
        connection.execute(text("DELETE FROM monitor_event WHERE event_type = 'plan.deactivated'"))
    assert _read(history).status == "UNKNOWN"


def test_missing_trailing_audits_and_events_do_not_make_chain_complete(history):
    _reactivate(history)
    with history.engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM monitor_event WHERE event_type IN "
                "('plan.activated', 'plan.deactivated') "
                "AND json_extract(payload_json, '$.revision') > 1"
            )
        )
        connection.execute(
            text(
                "DELETE FROM audit_log WHERE action IN "
                "('PLAN_ACTIVATED', 'PLAN_DEACTIVATED') "
                "AND json_extract(details_json, '$.revision') > 1"
            )
        )
    assert _read(history).status == "UNKNOWN"


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM plan_activation_state",
        "UPDATE plan_activation_state SET revision = 9",
        "UPDATE plan_activation_state SET changed_at = '2026-08-07T15:06:00+08:00'",
        "DELETE FROM active_plan",
        "UPDATE active_plan SET revision = 9",
    ],
)
def test_activation_chain_requires_authoritative_tip(history, mutation):
    with history.engine.begin() as connection:
        connection.execute(text(mutation))
    assert _read(history).status == "UNKNOWN"


def test_database_fault_is_not_authoritative_absence(history):
    def fail(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            raise OperationalError(statement, parameters, RuntimeError("offline fault"))

    sqlalchemy_event.listen(history.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        _read(history)


@pytest.mark.parametrize("table", ["monitor_event", "evaluation_result", "audit_log"])
def test_later_database_fault_propagates_outside_content_parsers(history, table):
    def fail(connection, cursor, statement, parameters, context, many):
        if f"FROM {table}" in statement:
            raise OperationalError(statement, parameters, RuntimeError("offline fault"))

    sqlalchemy_event.listen(history.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        _read(history)


def test_consistently_rehashed_ledger_and_result_still_require_canonical_result(history):
    with history.engine.begin() as connection:
        connection.execute(text("PRAGMA defer_foreign_keys = ON"))
        connection.execute(
            text("UPDATE evaluation_ledger SET result_hash = :digest"), {"digest": "f" * 64}
        )
        connection.execute(
            text("UPDATE evaluation_result SET result_hash = :digest"), {"digest": "f" * 64}
        )
    assert _read(history).status == "UNKNOWN"


def test_well_formed_alert_must_equal_rebuilt_original_payload(history):
    with history.factory() as session:
        row = session.get(AlertRow, str(history.alert.event_id))
        data = json.loads(row.payload_json)
        data["name"] = "Changed name"
        payload = AlertPayload.model_validate_json(json.dumps(data))
        row.payload_json = payload.model_dump_json()
        row.message_text = render_alert(payload)
        session.commit()
    assert _read(history).status == "UNKNOWN"


@pytest.mark.parametrize(
    "column,table,where",
    [
        ("payload_json", "monitor_event", "event_type = 'plan.activated'"),
        ("details_json", "audit_log", "action = 'PLAN_ACTIVATED'"),
    ],
)
def test_oversized_historical_payload_is_unknown(history, column, table, where):
    with history.engine.begin() as connection:
        connection.execute(
            text(f"UPDATE {table} SET {column} = :blob WHERE {where}"), {"blob": " " * 4097 + "{}"}
        )
    assert _read(history).status == "UNKNOWN"


def test_history_row_budget_never_accepts_a_truncated_chain(history):
    with history.factory() as session:
        session.add_all(
            [
                AuditLog(
                    id=str(uuid4()),
                    action="PLAN_ACTIVATED",
                    entity_type="ACTIVE_PLAN",
                    entity_id=history.plan.symbol,
                    before_hash=None,
                    after_hash=None,
                    details_json="{}",
                    created_at=NOW.isoformat(),
                )
                for _ in range(MAX_EVENT_REPLAY_LIMIT)
            ]
        )
        session.commit()
    result = _read(history)
    assert result.status == "UNKNOWN"
    assert result.reason == "HISTORY_LIMIT"


def test_reader_rejects_nonfresh_session_without_flushing(history):
    from trade_plan_monitor.notifications.recovery_provenance import LegacyAlertOriginReader

    with history.factory() as session:
        pending = AuditLog(
            id=str(uuid4()),
            action="PENDING",
            entity_type="TEST",
            entity_id="x",
            before_hash=None,
            after_hash=None,
            details_json="{}",
            created_at="x",
        )
        session.add(pending)
        transaction = session.get_transaction()
        with pytest.raises(ValueError, match="fresh"):
            LegacyAlertOriginReader(lambda: session).read(history.alert.event_id)
        assert pending in session.new
        assert session.get_transaction() is transaction
        with history.factory() as independent:
            assert independent.get(AuditLog, pending.id) is None


def test_reader_rejects_preused_session_with_cached_objects(history):
    from trade_plan_monitor.notifications.recovery_provenance import LegacyAlertOriginReader

    with history.factory() as session:
        cached = session.get(AlertRow, str(history.alert.event_id))
        session.commit()
        assert not session.in_transaction()
        with pytest.raises(ValueError, match="fresh"):
            LegacyAlertOriginReader(lambda: session).read(history.alert.event_id)
        assert cached in session


def test_inactive_tip_does_not_erase_known_original_activation(history):
    history.clock[0] += timedelta(minutes=1)
    with history.work() as uow:
        uow.plans.deactivate(history.plan.symbol, expected_revision=1)
        uow.commit()
    origin = _read(history)
    assert origin.status == "PROVEN"
    assert origin.activation_revision == 1


def test_sequences_beyond_committed_highwater_cannot_relabel_original(history):
    _reactivate(history)
    with history.engine.begin() as connection:
        connection.execute(
            text("UPDATE monitor_event SET sequence = 100 WHERE id = :id"),
            {"id": str(history.publication.event_id)},
        )
        connection.execute(
            text("UPDATE monitor_event SET sequence = 101 WHERE id = :id"),
            {"id": str(history.alert.event_id)},
        )
        connection.execute(text("UPDATE alert_event SET sequence = 101"))
    assert _read(history).status == "UNKNOWN"


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM monitor_sequence",
        "UPDATE monitor_sequence SET last_sequence = 0",
        "UPDATE monitor_sequence SET last_sequence = 'invalid'",
        "UPDATE monitor_sequence SET last_sequence = 9007199254740992",
    ],
)
def test_missing_or_invalid_sequence_highwater_is_unknown(history, mutation):
    with history.engine.begin() as connection:
        connection.execute(text(mutation))
    assert _read(history).status == "UNKNOWN"


@pytest.mark.parametrize("minutes_after_cutoff", [1, 6])
def test_consistent_origin_activation_cannot_follow_target_or_evaluation(
    history, minutes_after_cutoff
):
    occurred_at = NOW.replace(minute=minutes_after_cutoff).isoformat()
    state = {
        "planVersionId": history.activation.plan_version_id,
        "revision": 1,
        "symbol": history.plan.symbol,
        "activatedAt": occurred_at,
    }
    digest = sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with history.engine.begin() as connection:
        connection.execute(
            text("UPDATE monitor_event SET occurred_at = :at WHERE event_type = 'plan.activated'"),
            {"at": occurred_at},
        )
        connection.execute(
            text(
                "UPDATE audit_log SET created_at = :at, after_hash = :digest "
                "WHERE action = 'PLAN_ACTIVATED'"
            ),
            {"at": occurred_at, "digest": digest},
        )
        connection.execute(
            text("UPDATE plan_activation_state SET changed_at = :at"), {"at": occurred_at}
        )
        connection.execute(text("UPDATE active_plan SET activated_at = :at"), {"at": occurred_at})
    assert _read(history).status == "UNKNOWN"
