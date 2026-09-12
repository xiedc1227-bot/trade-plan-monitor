"""R13 regression: actual IN_APP adapter must accept production explicit alerts."""

import asyncio

import pytest
from tests.integration.test_explicit_runtime_production import (
    PIPELINE_NOW,
    TARGET,
    _pipeline_fixture,
    _three_rule_plan,
)

from trade_plan_monitor.notifications.channels import InAppChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import create_session_factory


@pytest.mark.parametrize("price", [990, 1080, 949], ids=["BUY", "SELL", "RISK_ALERT"])
def test_production_explicit_alert_completes_in_app_delivery(tmp_path, monkeypatch, price):
    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = _pipeline_fixture(
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
        finally:
            await dispatcher.aclose()
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
