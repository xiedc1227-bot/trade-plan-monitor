"""Final admission occurs after a durable claim and before channel I/O."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_explicit_runtime_production import (
    NOW as EXPLICIT_NOW,
)
from test_explicit_runtime_production import (
    TARGET,
    _database,
    _seed_active,
    _seed_facts,
    _three_rule_plan,
)
from test_notification_delivery import NOW, _payload, _unit_of_work

from trade_plan_monitor.notifications.channels import (
    ChannelDeliveryResult,
    DeliveryChannel,
)
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import DeliveryAttempt, PositionInventoryConfirmation
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
def database_engine(tmp_path):
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    yield engine
    engine.dispose()


class RecordingChannel:
    channel = DeliveryChannel.IN_APP
    enabled = True

    def __init__(self):
        self.sent = []

    async def deliver(self, event):
        self.sent.append(event.event_id)
        return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)


def test_held_event_requires_fresh_admission_after_claim(database_engine):
    with _unit_of_work(database_engine) as work:
        event = work.alerts.enqueue_recoverable(_payload(910))
        work.commit()

    calls = []
    channel = RecordingChannel()

    def admission(candidate, observed_at):
        calls.append((candidate.event_id, observed_at))
        return len(calls) == 1

    dispatcher = NotificationDispatcher(
        create_session_factory(database_engine), channels=(channel,), clock=lambda: NOW,
        id_factory=lambda: "claimed-before-final-check", admission=admission,
    )
    assert asyncio.run(dispatcher.dispatch_pending()) == ()
    assert calls == [(event.event_id, NOW), (event.event_id, NOW)]
    assert channel.sent == []
    with create_session_factory(database_engine)() as session:
        claim = session.scalar(select(DeliveryAttempt).where(
            DeliveryAttempt.channel == DeliveryChannel.IN_APP.value,
        ))
        assert claim.status == "CLAIMED"

    restarted = NotificationDispatcher(
        create_session_factory(database_engine), channels=(channel,),
        clock=lambda: NOW + timedelta(seconds=60), admission=lambda *_: True,
    )
    attempts = asyncio.run(restarted.dispatch_pending())
    assert len(attempts) == 1
    assert channel.sent == [event.event_id]
    assert attempts[0].attempt == 1


def test_pending_scan_reaches_later_event_behind_held_events(database_engine):
    with _unit_of_work(database_engine) as work:
        for number in range(911, 1013):
            work.alerts.enqueue_recoverable(_payload(number))
        work.commit()

    channel = RecordingChannel()
    dispatcher = NotificationDispatcher(
        create_session_factory(database_engine), channels=(channel,), clock=lambda: NOW,
        admission=lambda event, _: event.event_id.int == 1012,
    )
    assert asyncio.run(dispatcher.dispatch_pending(limit=1)) == ()
    assert asyncio.run(dispatcher.dispatch_pending(limit=1)) == ()
    # A bounded scan cursor must eventually pass an arbitrary run of held rows.
    for _ in range(102):
        if asyncio.run(dispatcher.dispatch_pending(limit=1)):
            break
    assert channel.sent == [UUID(int=1012)]


def test_explicit_risk_requires_current_result_and_holdings(tmp_path):
    engine = create_sqlite_engine(tmp_path / "explicit-risk.db")
    upgrade_database(engine)
    plan = _three_rule_plan(overlapping_risk=True)
    _seed_active(engine, plan)
    _seed_facts(engine, plan)
    sessions = create_session_factory(engine)
    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: EXPLICIT_NOW)

    outcome = asyncio.run(ExplicitRuntimeEvaluationService(
        work, recovery_delivery=True,
    ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=EXPLICIT_NOW))
    risk = next(event for event in outcome.committed_events if event.signal_type == "RISK_ALERT")
    generation = uuid4()
    admission = CurrentDeliveryAdmission(sessions, runtime_generation=lambda: generation)
    assert admission(risk, EXPLICIT_NOW + timedelta(seconds=1)) is True
    with sessions.begin() as session:
        session.delete(session.get(PositionInventoryConfirmation, plan.symbol))
    assert admission(risk, EXPLICIT_NOW + timedelta(seconds=3)) is False
    engine.dispose()


def test_explicit_buy_releases_only_with_current_result_and_expires_at_90_seconds(tmp_path):
    engine, plan = _database(tmp_path, "explicit-buy.db")
    sessions = create_session_factory(engine)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: EXPLICIT_NOW)

    outcome = asyncio.run(ExplicitRuntimeEvaluationService(
        work, recovery_delivery=True,
    ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=EXPLICIT_NOW))
    event = outcome.committed_events[0]
    admission = CurrentDeliveryAdmission(sessions, runtime_generation=uuid4)
    assert admission(event, TARGET + timedelta(seconds=89)) is True
    assert admission(event, TARGET + timedelta(seconds=90)) is False
    engine.dispose()
