"""Offline opt-in evaluator proofs; HOLD metadata is not dispatcher send authority."""

import asyncio
from datetime import UTC, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import func, select
from test_explicit_runtime_production import (
    NOW,
    TARGET,
    _database,
    _seed_active,
    _seed_facts,
    _three_rule_plan,
)
from test_ten_symbol_runtime import (
    _actionable_episode_result,
    _at,
    _bar,
    _daily_bar,
    _official_context,
    _runtime_context,
    _runtime_plan,
)

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.notifications.delivery_eligibility import DeliveryEligibilityRepository
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEventType
from trade_plan_monitor.state.models import (
    AlertDeliveryEligibility,
    AlertEvent,
    AuditLog,
    DailyBar,
    EvaluationLedger,
    EvaluationResult,
    ExplicitEvaluationLedger,
    ExplicitRuleOccurrenceState,
    MinuteBar,
    RiskState,
    SymbolDecisionHead,
    ZoneEpisode,
)
from trade_plan_monitor.state.models import MonitorEvent as MonitorEventRow
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def _scenario(tmp_path, kind, *, no_signal=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if kind == "explicit":
        engine, plan = _database(tmp_path, "explicit.db", current_volume=1 if no_signal else 300)
        target, now = TARGET, NOW
    else:
        engine = create_sqlite_engine(tmp_path / "legacy.db")
        upgrade_database(engine)
        plan = _runtime_plan()
        target = _at(9, 40) if kind == "intraday" else _at(17, 0)
        now = target + timedelta(seconds=20)
    sessions = create_session_factory(engine)
    committed_at = now + timedelta(seconds=1)
    clock = [committed_at.astimezone(UTC) if kind == "explicit" else committed_at]
    published = []

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: clock[0])

    async def minutes(symbol, bucket):
        return [_bar(symbol, _at(9, minute)) for minute in range(31, bucket.minute + 1)]

    async def daily(*_args):
        return [_daily_bar(
            trade_date=target.date(), close_fen=6200 if no_signal else 6000,
            is_official=True, received_at=now,
        )]

    def service(**options):
        if kind == "explicit":
            return ExplicitRuntimeEvaluationService(
                work, committed_event_publisher=published.append, **options,
            )
        return RuntimeEvaluationService(
            fetch_minutes=minutes,
            fetch_official_daily=daily,
            official_observed_at=lambda value: value,
            unit_of_work_factory=work,
            context_builder=_runtime_context,
            official_context_builder=_official_context,
            evaluator=(
                (lambda context: _actionable_episode_result(plan, context))
                if kind == "intraday" and not no_signal else evaluate
            ),
            committed_event_publisher=published.append,
            event_id_factory=lambda: UUID(int=71),
            **options,
        )

    def run(instance):
        if kind == "explicit":
            return asyncio.run(instance.run_intraday_and_publish(
                plan=plan, target_bucket_end=target, evaluated_at=now,
            ))
        if kind == "official":
            return asyncio.run(instance.run_official_close(
                plan=plan, trade_date=target.date(), evaluated_at=now, close_attempt=3,
            ))
        return asyncio.run(instance.run_intraday(
            plan=plan, bucket_end=target, evaluated_at=now,
        ))

    return SimpleNamespace(
        kind=kind, engine=engine, sessions=sessions, plan=plan, target=target, now=now,
        clock=clock, work=work, published=published, service=service, run=run,
    )


@pytest.fixture(params=["intraday", "official", "explicit"])
def scenario(request, tmp_path):
    instance = _scenario(tmp_path, request.param)
    yield instance
    instance.engine.dispose()


@pytest.mark.parametrize("options", [{}, {"recovery_delivery": False}, {"recovery_delivery": True}])
def test_only_opt_in_adds_initial_hold_to_committed_alert(scenario, options):
    result = scenario.run(scenario.service(**options))
    events = result.committed_events if scenario.kind == "explicit" else (result.committed_event,)
    assert len(events) == 1 and events[0] is not None
    with scenario.sessions() as session:
        metadata = DeliveryEligibilityRepository(session, clock=lambda: scenario.now).get(
            events[0].event_id,
        )
        audits = session.scalars(select(AuditLog).where(
            AuditLog.action == "ALERT_DELIVERY_CLASSIFIED",
        )).all()
        if options.get("recovery_delivery", False):
            assert metadata.status.value == "HOLD"
            assert metadata.revision == 0
            assert metadata.reason == "RECOVERY_REQUIRED"
            assert metadata.result_hash is None and metadata.barrier is None
            assert len(audits) == 1
        else:
            assert metadata is None and audits == []
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
    assert [event.event_id for event in scenario.published
            if event.event_type is MonitorEventType.ALERT_CREATED] == [events[0].event_id]


@pytest.mark.parametrize("value", [0, 1, "true", None, (), {}])
def test_recovery_delivery_rejects_non_boolean(scenario, value):
    with pytest.raises(TypeError, match="recovery_delivery must be a bool"):
        scenario.service(recovery_delivery=value)


@pytest.mark.parametrize("failed_table", ["alert_delivery_eligibility", "audit_log"])
def test_metadata_or_audit_failure_rolls_back_decision_and_allows_retry(
    scenario, failed_table,
):
    def fail_insert(connection, cursor, statement, parameters, context, many):
        if statement.startswith(f"INSERT INTO {failed_table}"):
            if failed_table != "audit_log" or "ALERT_DELIVERY_CLASSIFIED" in str(parameters):
                raise RuntimeError("injected delivery storage failure")

    with scenario.sessions() as session:
        original_audits = session.scalar(select(func.count()).select_from(AuditLog))
    sql_event.listen(scenario.engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="injected delivery storage failure"):
            scenario.run(scenario.service(recovery_delivery=True))
    finally:
        sql_event.remove(scenario.engine, "before_cursor_execute", fail_insert)
    with scenario.sessions() as session:
        for model in (
            EvaluationLedger, EvaluationResult, SymbolDecisionHead, RiskState, ZoneEpisode,
            ExplicitEvaluationLedger, ExplicitRuleOccurrenceState, AlertEvent,
            AlertDeliveryEligibility,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0, model
        assert session.scalar(select(func.count()).select_from(AuditLog)) == original_audits
        assert session.scalars(select(MonitorEventRow).where(
            MonitorEventRow.event_type.in_(("ALERT_CREATED", "SYMBOL_SNAPSHOT_UPDATED")),
        )).all() == []
        # Market acquisition precedes the decision transaction and remains durable.
        if scenario.kind == "intraday":
            assert session.scalar(select(func.count()).select_from(MinuteBar)) == 10
        elif scenario.kind == "official":
            assert session.scalar(select(func.count()).select_from(DailyBar)) == 1
    assert not any(event.event_type in (
        MonitorEventType.ALERT_CREATED, MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
    ) for event in scenario.published)
    if scenario.kind == "official":
        assert scenario.service().pending_close_date(scenario.plan.symbol) == scenario.target.date()
    retried = scenario.run(scenario.service(recovery_delivery=True))
    assert retried.status.value == "COMMITTED"
    with scenario.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
        assert session.scalar(select(func.count()).select_from(AlertDeliveryEligibility)) == 1


def test_restarted_duplicate_preserves_metadata_payload_and_audit(scenario):
    first = scenario.run(scenario.service(recovery_delivery=True))
    event = first.committed_events[0] if scenario.kind == "explicit" else first.committed_event
    with scenario.sessions.begin() as session:
        repository = DeliveryEligibilityRepository(
            session, clock=lambda: scenario.now + timedelta(minutes=5),
        )
        saved = repository.expire_actionable(event.event_id, expected_revision=0)
        if scenario.kind != "official":
            assert saved.status.value == "SUPPRESS"
        payload = session.get(AlertEvent, str(event.event_id)).payload_json
        audit_count = session.scalar(select(func.count()).select_from(AuditLog))
    publication_count = len(scenario.published)
    duplicate = scenario.run(scenario.service(recovery_delivery=True))
    assert duplicate.status.value == "DUPLICATE"
    assert len(scenario.published) == publication_count
    with scenario.sessions() as session:
        assert DeliveryEligibilityRepository(session, clock=lambda: scenario.now).get(
            event.event_id,
        ) == saved
        assert session.get(AlertEvent, str(event.event_id)).payload_json == payload
        assert session.scalar(select(func.count()).select_from(AuditLog)) == audit_count


def test_opt_in_replay_does_not_backfill_a_default_path_alert(scenario):
    scenario.run(scenario.service())
    duplicate = scenario.run(scenario.service(recovery_delivery=True))
    assert duplicate.status.value == "DUPLICATE"
    with scenario.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
        assert session.scalar(select(func.count()).select_from(AlertDeliveryEligibility)) == 0


@pytest.mark.parametrize("kind", ["intraday", "official", "explicit"])
def test_opt_in_preserves_canonical_result_alert_and_state(tmp_path, kind):
    snapshots = []
    for enabled in (False, True):
        instance = _scenario(tmp_path / str(enabled), kind)
        try:
            result = instance.run(instance.service(recovery_delivery=enabled))
            with instance.sessions() as session:
                alert = session.scalar(select(AlertEvent))
                snapshots.append((
                    result,
                    alert.payload_json,
                    alert.message_text,
                    tuple((event.event_id, event.sequence, event.event_type)
                          for event in instance.published),
                    tuple(tuple(session.execute(select(model.__table__)).all()) for model in (
                        EvaluationLedger, EvaluationResult, SymbolDecisionHead, RiskState,
                        ZoneEpisode, ExplicitEvaluationLedger, ExplicitRuleOccurrenceState,
                    )),
                ))
        finally:
            instance.engine.dispose()
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("kind", ["intraday", "official", "explicit"])
def test_no_signal_commits_result_without_alert_or_delivery_metadata(tmp_path, kind):
    instance = _scenario(tmp_path, kind, no_signal=True)
    try:
        result = instance.run(instance.service(recovery_delivery=True))
        assert result.status.value == "COMMITTED"
        with instance.sessions() as session:
            ledger = ExplicitEvaluationLedger if kind == "explicit" else EvaluationLedger
            assert session.scalar(select(func.count()).select_from(ledger)) == 1
            for model in (AlertEvent, AlertDeliveryEligibility):
                assert session.scalar(select(func.count()).select_from(model)) == 0
        assert not any(event.event_type is MonitorEventType.ALERT_CREATED
                       for event in instance.published)
    finally:
        instance.engine.dispose()


@pytest.mark.parametrize("failed_table", [None, "alert_delivery_eligibility", "audit_log"])
def test_explicit_two_intents_are_atomic_with_initial_hold(tmp_path, failed_table):
    engine = create_sqlite_engine(tmp_path / "multi.db")
    upgrade_database(engine)
    plan = _three_rule_plan(overlapping_risk=True)
    _seed_active(engine, plan)
    _seed_facts(engine, plan)
    sessions = create_session_factory(engine)
    target = TARGET + timedelta(minutes=5)
    now = target + timedelta(seconds=2)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: now)

    with work() as transaction:
        transaction.history.upsert_five_minute(**FiveMinuteBar(
            symbol=plan.symbol, bar_end=target, open_fen=1080, high_fen=1080,
            low_fen=1080, close_fen=1080, volume_shares=300, amount_yuan=Decimal("0"),
        ).model_dump())
        transaction.commit()
    published = []
    attempts = []

    def fail_second(connection, cursor, statement, parameters, context, many):
        if failed_table and statement.startswith(f"INSERT INTO {failed_table}"):
            if failed_table != "audit_log" or "ALERT_DELIVERY_CLASSIFIED" in str(parameters):
                attempts.append(parameters)
                if len(attempts) == 2:
                    raise RuntimeError("second intent delivery storage failure")

    def run():
        return asyncio.run(ExplicitRuntimeEvaluationService(
            work, committed_event_publisher=published.append, recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=target, evaluated_at=now))

    sql_event.listen(engine, "before_cursor_execute", fail_second)
    try:
        if failed_table:
            with pytest.raises(RuntimeError, match="second intent delivery storage failure"):
                run()
            assert len(attempts) == 2
            with work() as transaction:
                assert transaction.explicit_rules.get(
                    plan_hash=plan_sha256(plan), symbol=plan.symbol,
                    target_bucket_end=target, activation_revision=1,
                ) is None
                assert transaction.explicit_rules.states(
                    plan_hash=plan_sha256(plan), symbol=plan.symbol, activation_revision=1,
                ) == ()
            with sessions() as session:
                for model in (AlertEvent, AlertDeliveryEligibility):
                    assert session.scalar(select(func.count()).select_from(model)) == 0
                assert session.scalars(select(AuditLog).where(
                    AuditLog.action == "ALERT_DELIVERY_CLASSIFIED",
                )).all() == []
            assert published == []
        sql_event.remove(engine, "before_cursor_execute", fail_second)
        result = run()
        assert {event.signal_type for event in result.committed_events} == {"SELL", "RISK_ALERT"}
        with sessions() as session:
            records = session.scalars(select(AlertDeliveryEligibility)).all()
            assert len(records) == 2
            assert {record.status for record in records} == {"HOLD"}
        assert len(published) == 2
    finally:
        if sql_event.contains(engine, "before_cursor_execute", fail_second):
            sql_event.remove(engine, "before_cursor_execute", fail_second)
        engine.dispose()
