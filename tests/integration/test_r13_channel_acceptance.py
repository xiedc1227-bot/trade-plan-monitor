"""R13 regression: notification consumers accept production explicit alerts."""

import asyncio
import json

import httpx
import pytest
from tests.integration.test_explicit_runtime_production import (
    PIPELINE_NOW,
    TARGET,
    _pipeline_fixture,
    _three_rule_plan,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.notifications.channels import (
    ConsoleChannel,
    DeliveryChannel,
    InAppChannel,
    WebhookChannel,
    WebhookConfig,
)
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.notifications.models import ExplicitAlertEvent
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import create_session_factory


@pytest.mark.parametrize("price", [990, 1080, 949], ids=["BUY", "SELL", "RISK_ALERT"])
def test_production_explicit_alert_completes_in_app_delivery(tmp_path, monkeypatch, price):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=price,
            plan=_three_rule_plan(),
        )
        dispatcher = NotificationDispatcher(
            create_session_factory(engine),
            channels=(InAppChannel(),),
            clock=lambda: PIPELINE_NOW,
            enforce_current_plan=True,
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            attempts = await dispatcher.dispatch_pending()
            assert len(attempts) == 1
            assert attempts[0].status.value == "DELIVERED", attempts[0]
            signal_type = {990: "BUY", 1080: "SELL", 949: "RISK_ALERT"}[price]
            with work() as unit_of_work:
                events, total = unit_of_work.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=signal_type,
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
                result = unit_of_work.explicit_rules.get(
                    plan_hash=plan_sha256(plan),
                    symbol=plan.symbol,
                    target_bucket_end=TARGET,
                    activation_revision=1,
                )
            assert total == 1
            event = events[0]
            assert type(event) is ExplicitAlertEvent
            assert event.event_id == attempts[0].event_id
            assert event.plan_version == plan.version
            assert event.plan_hash == plan_sha256(plan)
            assert event.quantity == (None if signal_type == "RISK_ALERT" else 100)
            assert result is not None
            assert result.plan_hash == event.plan_hash
            assert result.target_bucket_end == event.target_bucket_end
            assert len(result.result_hash) == 64
        finally:
            await dispatcher.aclose()
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_console_and_webhook_preserve_the_bounded_explicit_event_envelope(
    tmp_path,
    monkeypatch,
):
    requests: list[dict[str, object]] = []
    console_lines: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(204, request=request)

    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=990,
            plan=_three_rule_plan(),
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            with work() as unit_of_work:
                events, total = unit_of_work.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
            assert total == 1
            event = events[0]
            assert type(event) is ExplicitAlertEvent
            assert event.quantity == 100

            console = ConsoleChannel(write_line=console_lines.append)
            console_result = await console.deliver(event)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                webhook = WebhookChannel(
                    client=client,
                    config=WebhookConfig(
                        enabled=True,
                        endpoint="https://hooks.example.test/alerts",
                        allowlisted_hosts=("hooks.example.test",),
                    ),
                )
                webhook_result = await webhook.deliver(event)
                with pytest.raises(TypeError, match="notification event"):
                    await webhook.deliver(object())

            assert console_result.channel is DeliveryChannel.CONSOLE
            assert console_result.delivered is True
            assert webhook_result.channel is DeliveryChannel.WEBHOOK
            assert webhook_result.delivered is True
            assert str(event.event_id) in console_lines[0]
            assert requests == [
                {
                    "createdAt": event.created_at.isoformat(),
                    "eventId": str(event.event_id),
                    "messageText": event.message_text,
                    "sequence": event.sequence,
                    "severity": "ACTION",
                    "signalType": "BUY",
                    "symbol": plan.symbol,
                }
            ]
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "channel",
    [
        InAppChannel(),
        ConsoleChannel(write_line=lambda _line: None),
    ],
    ids=["IN_APP", "CONSOLE"],
)
def test_local_channels_keep_rejecting_values_outside_the_versioned_event_union(channel):
    with pytest.raises(TypeError, match="notification event"):
        asyncio.run(channel.deliver(object()))
