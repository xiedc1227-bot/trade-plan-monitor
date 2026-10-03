"""Current condition-plan alerts survive the production notification pipeline."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import func, select
from tests.integration.current_pipeline_fixture import (
    PIPELINE_NOW,
    TARGET,
    current_pipeline_fixture,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.notifications.channels import (
    ConsoleChannel,
    DeliveryChannel,
    InAppChannel,
    WebhookChannel,
    WebhookConfig,
)
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.daily_models import DailyAlertEvent
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertEvent,
    DeliveryAttempt,
)


@pytest.mark.parametrize("price", [990, 1080, 949], ids=["BUY", "SELL", "RISK_ALERT"])
def test_production_condition_alert_completes_in_app_delivery(tmp_path, monkeypatch, price):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=price,
        )
        sessions = create_session_factory(engine)
        dispatcher = NotificationDispatcher(
            sessions,
            channels=(InAppChannel(),),
            clock=lambda: PIPELINE_NOW,
            enforce_current_plan=True,
            admission=CurrentDeliveryAdmission(
                sessions,
                runtime_generation=lambda: pipeline.evaluations._runtime_generation,
            ),
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
            with sessions() as session:
                assert session.scalars(select(AlertEvent)).one().id
                assert session.scalar(select(func.count()).select_from(
                    DailyRecord,
                ).where(DailyRecord.kind == "EVALUATION")) >= 1
                assert session.get(ActivePlan, plan.symbol) is not None
            with sessions() as session:
                assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 0
            attempts = await dispatcher.dispatch_pending()
            assert len(attempts) == 1
            assert attempts[0].status.value == "DELIVERED", attempts[0]
            signal_type = {990: "BUY", 1080: "SELL", 949: "REMINDER"}[price]
            with work() as unit_of_work:
                events, total = unit_of_work.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=None if signal_type == "REMINDER" else signal_type,
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
                result = unit_of_work.daily.get("evaluation-head-" + plan.symbol)
            assert total == 1
            event = events[0]
            assert type(event) is DailyAlertEvent
            assert event.event_id == attempts[0].event_id
            assert event.plan_version == plan.version
            assert event.plan_hash == plan_sha256(plan)
            assert event.quantity == (None if signal_type == "REMINDER" else 100)
            if signal_type == "REMINDER":
                assert event.alert_kind == "RISK_ALERT"
                assert event.severity == "RISK"
            assert result is not None
            assert result["payload"]["plan_hash"] == event.plan_hash
            assert result["payload"]["minute_target"] == TARGET.isoformat()
            assert await dispatcher.dispatch_pending() == ()
            with sessions() as session:
                assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1
        finally:
            await dispatcher.aclose()
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("price", [990, 1080, 949], ids=["BUY", "SELL", "RISK_ALERT"])
def test_current_admission_holds_condition_alert_after_plan_revocation(
    tmp_path, monkeypatch, price,
):
    async def scenario():
        engine, _work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=price,
        )
        sessions = create_session_factory(engine)
        dispatcher = NotificationDispatcher(
            sessions,
            channels=(InAppChannel(),),
            clock=lambda: PIPELINE_NOW,
            enforce_current_plan=True,
            admission=CurrentDeliveryAdmission(
                sessions,
                runtime_generation=lambda: pipeline.evaluations._runtime_generation,
            ),
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
            with sessions.begin() as session:
                event = session.scalars(select(AlertEvent)).one()
                event_id = event.id
                assert session.scalar(select(func.count()).select_from(
                    DailyRecord,
                ).where(DailyRecord.kind == "EVALUATION")) >= 1
                active = session.get(ActivePlan, plan.symbol)
                assert active is not None
                session.delete(active)
            assert await dispatcher.dispatch_pending() == ()
            with sessions() as session:
                assert session.get(AlertEvent, event_id) is not None
                assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
                assert session.scalar(select(func.count()).select_from(
                    DailyRecord,
                ).where(DailyRecord.kind == "EVALUATION")) >= 1
        finally:
            await dispatcher.aclose()
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_console_and_webhook_preserve_the_bounded_current_event_envelope(
    tmp_path,
    monkeypatch,
):
    requests: list[dict[str, object]] = []
    console_lines: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(204, request=request)

    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=990,
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
            assert type(event) is DailyAlertEvent
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
