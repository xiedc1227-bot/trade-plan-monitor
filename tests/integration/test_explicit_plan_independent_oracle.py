"""R13 independent literal-plan numeric oracle at the production pipeline boundary.

Trusted plan/inventory fixtures are explicitly seeded here. The separate Chromium
acceptance proves public creation/review/registration; this matrix does not.
"""

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from tests.integration.current_pipeline_fixture import (
    current_pipeline_fixture,
    replace_current_plan,
)
from tests.integration.test_explicit_runtime_production import (
    PIPELINE_NOW,
    TARGET,
    _InertLifecycle,
)

from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.app import create_app


@pytest.mark.parametrize("price", [979, 980, 981, 999, 1000, 1001])
@pytest.mark.parametrize("volume", [200, 299, 300, 301])
def test_literal_buy_uses_inclusive_price_and_arithmetic_mean(tmp_path, monkeypatch, price, volume):
    # Independent oracle: sum([100,100,100,100,600])/5=200, median=100.
    # Excluding this bar is observable: at 300, including it raises the threshold.
    expected = 980 <= price <= 1000 and volume >= 300

    async def scenario():
        engine, work, plan, sdk, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=volume - 160,
            current_close_fen=price,
            prior_minute_volume=40,
        )
        try:
            # Four earlier minute volumes sum to 160; SDK supplies the last one.
            await pipeline.refresh_references(TARGET.date())
            result = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TARGET.date(),
                    due_at=PIPELINE_NOW,
                    bar_end=TARGET,
                )
            )
            with work() as transaction:
                alerts, count = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type="BUY",
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
                from trade_plan_monitor.state.daily_accounting import DailyAccounting
                inventory = DailyAccounting(transaction.daily).snapshot(
                    plan.symbol, TARGET.date())
            assert len(result) == 1
            assert count == int(expected), (price, volume, expected, alerts,
                result[0].snapshot["signals"], result[0].snapshot["data_blockers"],
                result[0].snapshot["five_minute_bars"])
            assert inventory["total_qty"] == 100
            assert set(sdk.calls) == {"trade_cal", "rt_min"}
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("transition", ["replace", "disable", "expire"])
def test_retained_explicit_alert_is_not_current_after_lifecycle_change(
    tmp_path,
    monkeypatch,
    transition,
):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
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
            if transition == "replace":
                replace_current_plan(tmp_path)
            elif transition == "disable":
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    transaction.commit()
            now = PIPELINE_NOW + (timedelta(days=1) if transition == "expire" else timedelta())
            pipeline._clock.current = now
            service = PersistentAlertOperationService(unit_of_work_factory=work, clock=lambda: now)
            with TestClient(
                create_app(runtime_factory=_InertLifecycle, alert_service=service)
            ) as client:
                response = client.get("/api/v1/alerts?symbol=003043.SZ")
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert response.json()["items"][0]["currentActionable"] is False
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("price", [949, 950, 951, 1079, 1080, 1081, 1099, 1100, 1101])
def test_literal_sell_and_pure_risk_boundaries(tmp_path, monkeypatch, price):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=price,
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
            with work() as transaction:
                alerts, _ = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=None,
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
                from trade_plan_monitor.state.daily_accounting import DailyAccounting
                inventory = DailyAccounting(transaction.daily).snapshot(
                    plan.symbol, TARGET.date())
            expected = "REMINDER" if price < 950 else "SELL" if 1080 <= price <= 1100 else None
            assert [event.signal_type for event in alerts] == (
                [] if expected is None else [expected]
            )
            if alerts:
                assert alerts[0].quantity == (None if expected == "REMINDER" else 100)
                if expected == "REMINDER":
                    assert alerts[0].alert_kind == "RISK_ALERT"
            assert inventory["total_qty"] == 100
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_temporary_intrabar_satisfaction_then_failed_close_never_alerts(tmp_path, monkeypatch):
    async def scenario():
        engine, work, plan, sdk, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            sdk.source_time = TARGET - timedelta(minutes=2)
            assert (
                await pipeline.run_deadline(
                    MarketDeadline(
                        kind=DeadlineKind.REALTIME_MINUTE,
                        trade_date=TARGET.date(),
                        due_at=TARGET - timedelta(minutes=1) + timedelta(seconds=15),
                        bar_end=TARGET - timedelta(minutes=1),
                    )
                )
                == ()
            )
            sdk.source_time = TARGET - timedelta(minutes=1)
            sdk.current_close_fen = 1001
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=TARGET.date(),
                due_at=PIPELINE_NOW,
                bar_end=TARGET,
            )
            assert len(await pipeline.run_deadline(deadline)) == 1
            repeated = await pipeline.run_deadline(deadline)
            assert len(repeated) == 1 and repeated[0].event_ids == ()
            with work() as transaction:
                alerts, count = transaction.alerts.list_events(
                    symbol=plan.symbol,
                    signal_type=None,
                    acknowledged=None,
                    start_at=None,
                    end_at=None,
                    offset=0,
                    limit=10,
                )
            assert alerts == () and count == 0
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
