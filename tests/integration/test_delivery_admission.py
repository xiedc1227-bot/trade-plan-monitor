"""Final admission occurs after a durable claim and before channel I/O."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from test_notification_delivery import NOW, _payload, _unit_of_work

from trade_plan_monitor.notifications.channels import (
    ChannelDeliveryResult,
    DeliveryChannel,
)
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
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
