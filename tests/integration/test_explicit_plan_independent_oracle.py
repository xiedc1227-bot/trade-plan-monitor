"""R13 independent literal-plan numeric oracle at the production pipeline boundary.

Trusted plan/inventory fixtures are explicitly seeded here. The separate Chromium
acceptance proves public creation/review/registration; this matrix does not.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_explicit_runtime_production import (
    PIPELINE_NOW,
    TARGET,
    _InertLifecycle,
    _pipeline_fixture,
    _rotate_active_plan,
    _three_rule_plan,
)

from trade_plan_monitor.market_data.models import MinuteBar
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
        engine, work, plan, sdk, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=volume - 160,
            current_close_fen=price,
            plan=_three_rule_plan(),
        )
        try:
            # Four earlier minute volumes sum to 160; SDK supplies the last one.
            with work() as transaction:
                transaction.history.upsert_minutes(
                    tuple(
                        MinuteBar(
                            symbol=plan.symbol,
                            bar_end=TARGET - timedelta(minutes=offset),
                            open_fen=990,
                            high_fen=990,
                            low_fen=990,
                            close_fen=990,
                            volume_shares=40,
                            amount_yuan=Decimal("0"),
                            received_at=PIPELINE_NOW,
                        )
                        for offset in (4, 3, 2, 1)
                    )
                )
                transaction.commit()
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
                inventory = transaction.positions.inventory_snapshot(
                    plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    cutoff=TARGET,
                )
            assert len(result) == 1
            assert count == int(expected), (price, volume, expected, alerts)
            assert inventory.total_qty == 100
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
        engine, work, plan, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
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
            if transition == "replace":
                _rotate_active_plan(engine, plan)
            elif transition == "disable":
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    transaction.commit()
            now = PIPELINE_NOW + (timedelta(days=1) if transition == "expire" else timedelta())
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
        engine, work, plan, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            current_close_fen=price,
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
                inventory = transaction.positions.inventory_snapshot(
                    plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    cutoff=TARGET,
                )
            expected = "RISK_ALERT" if price < 950 else "SELL" if 1080 <= price <= 1100 else None
            assert [event.signal_type for event in alerts] == (
                [] if expected is None else [expected]
            )
            if alerts:
                assert alerts[0].quantity == (None if expected == "RISK_ALERT" else 100)
            assert inventory.total_qty == 100
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_temporary_intrabar_satisfaction_then_failed_close_never_alerts(tmp_path, monkeypatch):
    async def scenario():
        engine, work, plan, sdk, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path,
            monkeypatch,
            current_volume=60,
            plan=_three_rule_plan(),
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
            assert await pipeline.run_deadline(deadline) == ()
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
