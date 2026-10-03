"""Final admission occurs after a durable claim and before channel I/O."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_notification_delivery import NOW, _payload, _unit_of_work
from tests.integration.current_pipeline_fixture import (
    PIPELINE_NOW,
    TARGET,
    current_pipeline_fixture,
)

from trade_plan_monitor.notifications.channels import (
    ChannelDeliveryResult,
    DeliveryChannel,
)
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import DeliveryAttempt


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


def test_current_risk_reminder_requires_current_evaluation(tmp_path, monkeypatch):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60, current_close_fen=949,
        )
        sessions = create_session_factory(engine)
        try:
            await pipeline.refresh_references(TARGET.date())
            await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=TARGET.date(),
                due_at=PIPELINE_NOW, bar_end=TARGET,
            ))
            with work() as transaction:
                alerts, total = transaction.alerts.list_events(
                    symbol=plan.symbol, signal_type=None, acknowledged=None,
                    start_at=None, end_at=None, offset=0, limit=10,
                )
            assert total == 1
            risk = alerts[0]
            assert risk.signal_type == "REMINDER"
            assert risk.alert_kind == "RISK_ALERT"
            assert risk.quantity is None
            admission = CurrentDeliveryAdmission(sessions, runtime_generation=uuid4)
            assert admission(risk, PIPELINE_NOW + timedelta(seconds=1)) is True
            with sessions.begin() as session:
                head = session.get(DailyRecord, "evaluation-head-" + plan.symbol)
                assert head is not None
                session.delete(head)
            assert admission(risk, PIPELINE_NOW + timedelta(seconds=3)) is False
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_current_buy_requires_fresh_quote_and_expires_after_five_minutes(
    tmp_path, monkeypatch,
):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60, current_close_fen=990,
        )
        sessions = create_session_factory(engine)
        try:
            await pipeline.refresh_references(TARGET.date())
            await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=TARGET.date(),
                due_at=PIPELINE_NOW, bar_end=TARGET,
            ))
            with work() as transaction:
                alerts, total = transaction.alerts.list_events(
                    symbol=plan.symbol, signal_type="BUY", acknowledged=None,
                    start_at=None, end_at=None, offset=0, limit=10,
                )
            assert total == 1
            event = alerts[0]
            admission = CurrentDeliveryAdmission(sessions, runtime_generation=uuid4)
            assert admission(event, PIPELINE_NOW + timedelta(seconds=89)) is True
            assert admission(event, PIPELINE_NOW + timedelta(seconds=90)) is True
            assert admission(event, TARGET + timedelta(minutes=5, seconds=-1)) is True
            assert admission(event, TARGET + timedelta(minutes=5)) is True
            assert admission(event, TARGET + timedelta(minutes=5, seconds=1)) is False
            assert admission(event, event.evaluated_at + timedelta(minutes=5)) is False
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
