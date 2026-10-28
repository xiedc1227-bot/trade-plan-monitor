"""Real dispatcher claims cannot cache source permission across channel admission."""

import asyncio

import pytest
from sqlalchemy import select
from tests.integration.test_source_coverage_delivery import _admission, _corrupt_source, _event
from tests.integration.test_source_coverage_simulation_actions import _stale
from tests.integration.test_source_coverage_simulation_actions import current as current

from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.notifications.dispatcher import (
    DeliveryStorageError,
    NotificationDispatcher,
)
from trade_plan_monitor.state.models import DeliveryAttempt


class LocalRecordingChannel:
    """Local memory only; no console, webhook or other external notification."""

    channel = DeliveryChannel.IN_APP
    enabled = True

    def __init__(self):
        self.sent = []

    async def deliver(self, event):
        self.sent.append(event.event_id)
        return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)


def _dispatcher(chain, *, admission=None):
    channel = LocalRecordingChannel()
    return NotificationDispatcher(chain.plans._session_factory, channels=(channel,),
        clock=lambda: chain.now, admission=admission or _admission(chain)), channel


def _attempts(chain):
    with chain.plans._session_factory() as session:
        return tuple(session.execute(select(DeliveryAttempt.__table__).order_by(
            DeliveryAttempt.id)).all())


def test_stale_queued_message_does_not_claim_or_send_any_channel(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    _stale(chain)
    dispatcher, channel = _dispatcher(chain)
    assert asyncio.run(dispatcher.dispatch_event(event.event_id)) == ()
    assert channel.sent == [] and _attempts(chain) == ()


def test_source_changed_after_real_claim_is_rechecked_before_local_channel_io(current, monkeypatch):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    dispatcher, channel = _dispatcher(chain)
    claim_attempt = dispatcher._claim_attempt
    claims = []

    def claim_then_change(*args, **kwargs):
        claim = claim_attempt(*args, **kwargs)
        assert claim is not None
        _stale(chain)  # A real committed assessment, after the real committed claim.
        claims.append(claim.id)
        return claim

    monkeypatch.setattr(dispatcher, "_claim_attempt", claim_then_change)
    assert asyncio.run(dispatcher.dispatch_event(event.event_id)) == ()
    assert len(claims) == 1 and channel.sent == []
    with chain.plans._session_factory() as session:
        claim = session.get(DeliveryAttempt, claims[0])
        assert claim.status == "CLAIMED" and claim.attempt == 1


def test_runtime_generation_revocation_after_claim_cannot_use_earlier_admission(current,
                                                                            monkeypatch):
    from tests.integration.test_source_coverage_delivery import _GENERATION

    chain, signal = current
    event = _event(chain, signal["signal_id"])
    generation = [_GENERATION]
    dispatcher, channel = _dispatcher(chain, admission=_admission(chain,
        generation=lambda: generation[0]))
    claim_attempt = dispatcher._claim_attempt

    def claim_then_revoke(*args, **kwargs):
        claim = claim_attempt(*args, **kwargs)
        assert claim is not None
        generation[0] = None
        return claim

    monkeypatch.setattr(dispatcher, "_claim_attempt", claim_then_revoke)
    assert asyncio.run(dispatcher.dispatch_event(event.event_id)) == ()
    assert channel.sent == [] and len(_attempts(chain)) == 1


def test_original_delivered_receipt_is_not_reopened_after_source_changes(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    dispatcher, channel = _dispatcher(chain)
    delivered = asyncio.run(dispatcher.dispatch_event(event.event_id))
    assert len(delivered) == 1 and delivered[0].status.value == "DELIVERED"
    assert channel.sent == [event.event_id]
    before = _attempts(chain)
    _stale(chain)
    restarted, second_channel = _dispatcher(chain)
    assert asyncio.run(restarted.dispatch_event(event.event_id)) == ()
    assert second_channel.sent == [] and _attempts(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.alerts.get(event.event_id) == event


def test_corrupt_source_after_claim_preserves_sanitized_delivery_failure(current, monkeypatch):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    dispatcher, channel = _dispatcher(chain)
    claim_attempt = dispatcher._claim_attempt

    def claim_then_corrupt(*args, **kwargs):
        claim = claim_attempt(*args, **kwargs)
        assert claim is not None
        _corrupt_source(chain)
        return claim

    monkeypatch.setattr(dispatcher, "_claim_attempt", claim_then_corrupt)
    with pytest.raises(DeliveryStorageError) as error:
        asyncio.run(dispatcher.dispatch_event(event.event_id))
    assert "source_coverage_assessment" not in str(error.value)
    assert channel.sent == [] and len(_attempts(chain)) == 1
