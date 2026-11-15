"""Queued BUY is checked at send time; all channels here are local counters."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select
from tests.integration.test_plan_buy_suspension_recovery import guard_row
from tests.integration.test_plan_buy_suspension_runtime import inputs
from tests.integration.test_plan_buy_suspension_simulation import breach, ready
from tests.integration.test_plan_buy_suspension_simulation import chain as chain

from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.state.models import AlertEvent


class CounterChannel:
    channel = DeliveryChannel.IN_APP
    enabled = True

    def __init__(self):
        self.sent = []

    async def deliver(self, event):
        self.sent.append(event.event_id)
        return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)


def queued(chain, signal):
    with chain.plans._unit_of_work() as work:
        for row in work.daily.session.scalars(select(AlertEvent)).all():
            event = work.alerts.get(UUID(row.id))
            if getattr(event, "cause_id", None) == signal["signal_id"]:
                return event
    raise AssertionError("real runtime did not enqueue the signal")


def admission(chain, current):
    return CurrentDeliveryAdmission(chain.plans._session_factory,
        runtime_generation=lambda: chain.composition._runtime.runtime_generation,
        buy_suspension_current=current)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_actual_queued_event_rechecks_latch_without_rewriting_signal_or_event(chain, side):
    owner, signal = ready(chain, side=side)
    event = queued(chain, signal)
    check = admission(chain, owner.buy_suspension_current)
    assert check(event, chain.now)
    breach(chain)
    if side == "SELL":
        # The accepted minute correction independently invalidated the old
        # market snapshot. Refresh that prerequisite; a BUY latch alone is no veto.
        owner.daily_evaluations.run_inputs(plan=chain.plan,
            inputs=inputs(chain, revision=guard_row(chain)["revision"]))
    assert check(event, chain.now) is (side == "SELL")
    with chain.plans._unit_of_work() as work:
        assert work.alerts.get(event.event_id) == event
        assert work.daily.get(signal["signal_id"])["payload"]["state"] == "READY"


def test_inner_missing_guard_predicate_fails_closed_while_sell_still_delivers(chain):
    _, signal = ready(chain)
    event = queued(chain, signal)
    check = admission(chain, None)
    assert not check(event, chain.now)
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_claim_is_not_a_send_permit_when_guard_latches_before_delivery(chain, monkeypatch):
    owner, signal = ready(chain)
    event = queued(chain, signal)
    channel = CounterChannel()
    check = admission(chain, owner.buy_suspension_current)
    dispatcher = NotificationDispatcher(chain.plans._session_factory, channels=(channel,),
        clock=lambda: chain.now, admission=check)
    original = dispatcher._claim_attempt

    def latch_after_claim(*args):
        result = original(*args)
        if result is not None:
            breach(chain)
        return result

    monkeypatch.setattr(dispatcher, "_claim_attempt", latch_after_claim)
    assert asyncio.run(dispatcher.dispatch_event(event.event_id)) == ()
    assert channel.sent == []


@pytest.mark.parametrize("enforce", [False, True])
@pytest.mark.parametrize("entry", ["dispatch_event", "dispatch_pending"])
def test_entire_missing_dispatcher_callback_cannot_send_guarded_buy(chain, enforce, entry):
    _, signal = ready(chain)
    event = queued(chain, signal)
    breach(chain)
    channel = CounterChannel()
    dispatcher = NotificationDispatcher(chain.plans._session_factory, channels=(channel,),
        clock=lambda: chain.now, enforce_current_plan=enforce, admission=None)
    attempts = (dispatcher.dispatch_event(event.event_id) if entry == "dispatch_event"
                else dispatcher.dispatch_pending())
    assert asyncio.run(attempts) == ()
    assert channel.sent == []


def test_production_dispatcher_uses_the_real_guard_reader(chain):
    _, signal = ready(chain)
    event = queued(chain, signal)
    state = chain.composition._runtime._run_deadline.__self__
    assert state._dispatcher._admission(event, chain.now)
    breach(chain)
    assert not state._dispatcher._admission(event, chain.now)


def test_old_queued_buy_from_before_guard_activation_is_rechecked_without_callback(chain):
    from datetime import timedelta
    from decimal import Decimal

    from trade_plan_monitor.market_data.models import MinuteBar
    from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs

    saved = []

    def before_guard(value):
        from tests.integration.test_plan_buy_suspension_recovery import pipeline
        from tests.integration.test_plan_buy_suspension_runtime import inputs

        target = value.now.replace(minute=35, second=0, microsecond=0)
        minutes = tuple(MinuteBar(symbol=value.plan.symbol,
            bar_end=target - timedelta(minutes=4-i), open_fen=2430, high_fen=2430,
            low_fen=2419, close_fen=2430, volume_shares=100, amount_yuan=Decimal("2430"),
            received_at=value.now) for i in range(5))
        with value.plans._unit_of_work() as work:
            work.history.upsert_minutes(minutes)
            work.commit()
        captured = DailyRuntimeInputs.model_validate(inputs(value).model_dump(mode="python"))
        result = pipeline(value).daily_evaluations.run_inputs(plan=value.plan, inputs=captured)
        saved.append(queued(value, result.snapshot["signals"][0]))

    from tests.integration.test_plan_buy_suspension_runtime import prepare

    prepare(chain, before_guard=before_guard)
    assert saved[0].plan_version == 1 and chain.plan.version == 2
    channel = CounterChannel()
    dispatcher = NotificationDispatcher(chain.plans._session_factory, channels=(channel,),
        clock=lambda: chain.now, admission=None, enforce_current_plan=False)
    assert asyncio.run(dispatcher.dispatch_event(saved[0].event_id)) == ()
    assert channel.sent == []
