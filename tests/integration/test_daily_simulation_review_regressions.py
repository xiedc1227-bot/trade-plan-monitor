"""Permanent independent-review reproductions for the minimal simulation contract."""

import asyncio
import json
from datetime import date, timedelta

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SYMBOL, TUESDAY, WEDNESDAY, ready_chain
from tests.integration.test_daily_plan_chain import chain as chain
from tests.integration.test_daily_production_reevaluation import (
    production_chain as production_chain,
)

from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.state.models import TradingCalendar


def test_calendar_reprojection(chain):
    series, ready = ready_chain(chain)
    assert ready.snapshot["signals"][0]["executable_qty"] == 100
    with chain.plans._unit_of_work() as work:
        for i in range(1001):
            day = date(2020, 1, 1) + timedelta(days=i)
            work.daily.session.add(
                TradingCalendar(
                    exchange="SSE",
                    cal_date=day,
                    is_open=True,
                    previous_trade_date=day - timedelta(days=1),
                )
            )
        work.commit()
    projected = asyncio.run(chain.runtime.reevaluate_version(chain.version["id"]))
    assert projected.snapshot["quote"]["tradable"] is True, projected.snapshot


def test_explicit_negative_technical_fact_is_verified_without_forging_satisfaction(chain):
    ready_chain(chain)
    with chain.plans._unit_of_work() as work:
        negative = [
            r
            for r in work.daily.list(kind="FACT", symbol=SYMBOL)
            if r["payload"].get("satisfied") is False
        ]
    assert {r["payload"]["kind"] for r in negative} == {
        "SEVERE_STRUCTURE",
        "SEVERE_DETERIORATION",
    }
    assert all(r["payload"]["verified"] is True for r in negative)
    assert all(r["payload"]["content_hash"] == chain.version["contentHash"] for r in negative)


def test_latched_risk_with_missing_auxiliary(chain):
    series, ready = ready_chain(chain)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": kind,
                "kind": kind,
                "tradeDate": "2026-09-18",
                "expectedRevision": 0,
                "evidence": "Synthetic complete severe technical evidence explicitly verified",
            },
        )
    chain.evaluate(series=series, price=3970)
    result = chain.runtime.run_inputs(
        plan=chain.plan,
        inputs=DailyRuntimeInputs(
            evaluated_at=chain.now,
            official_trade_date=None,
            series=None,
            session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
            suspended_dates=(),
            quote=DailyExecutionQuote(
                symbol=SYMBOL,
                price_fen=3970,
                quote_at=chain.now,
                available_at=chain.now,
                evaluated_at=chain.now,
                tradable=True,
                special_state_verified=True,
                liquidity_available=True,
            ),
            data_blockers=("DAILY_QFQ_PROVIDER_UNAVAILABLE",),
        ),
    )
    action = result.snapshot["risk_action"]
    assert action["core_qty"] == 100, result.snapshot
    chain.simulate(action, 100)


def test_legacy_head_production_entry(production_chain):
    from sqlalchemy import update

    from trade_plan_monitor.state.daily_models import DailyRecord

    c = production_chain
    c.evaluate(series=c.series(), official=FRIDAY)
    with c.plans._unit_of_work() as work:
        row = work.daily.get("evaluation-head-" + SYMBOL)
        old = row["payload"]
        old["inventory"]["orders"] = []
        work.daily.session.execute(
            update(DailyRecord)
            .where(DailyRecord.id == row["id"])
            .values(payload_json=json.dumps(old))
        )
        work.commit()
    assert c.client.get("/api/v1/plan-runtime/" + SYMBOL).json()["status"] == "UNSUPPORTED"
    result = asyncio.run(
        c.runtime.run_target(plan=c.plan, evaluated_at=c.now, official_trade_date=FRIDAY)
    )
    assert result.snapshot["status"] == "UNSUPPORTED"


def test_preserved_old_alert_does_not_break_shared_outbox(chain):
    from trade_plan_monitor.state.daily_repository import daily_hash
    from trade_plan_monitor.state.models import AlertEvent

    _, ready = ready_chain(chain)
    identity = ready.event_ids[0]
    with chain.plans._unit_of_work() as work:
        row = work.daily.session.get(AlertEvent, identity)
        raw = json.loads(row.payload_json)
        raw["payload_schema_version"] = "daily-plan-alert-v1"
        raw["filled_qty"] = raw.pop("simulated_qty")
        raw["next_step"] = "REGISTER_ACTUAL_EXECUTION"
        raw["dedup_key"] = daily_hash(
            "daily-plan-alert-v1",
            {
                "cause_id": raw["cause_id"],
                "plan_hash": raw["plan_hash"],
                "side": raw["signal_type"],
                "filled_qty": raw["filled_qty"],
            },
        )
        row.dedup_key = raw["dedup_key"]
        row.payload_json = json.dumps(raw)
        row.message_text = (
            f"{raw['name']} {raw['symbol']} {raw['signal_type']} 提醒："
            f"原收盘确认 {raw['confirmed_trade_date']}，仅 {raw['execution_date']} 收盘前有效，"
            f"剩余 {raw['quantity']} 股。信号 {raw['cause_id']}；"
            "当前仍须在区间并核验可交易条件。实际成交须独立登记。"
        )
        work.commit()
    with chain.plans._unit_of_work() as work:
        page = work.alerts.list_events(
            symbol=None,
            signal_type=None,
            acknowledged=None,
            start_at=None,
            end_at=None,
            offset=0,
            limit=100,
        )
        from uuid import UUID

        obsolete = work.alerts.get(UUID(identity))
        assert obsolete.status == "UNSUPPORTED"
        assert obsolete.message_text == row.message_text
        assert any(event.event_id == UUID(identity) for event in page[0])
        assert any(event.event_id == UUID(identity) for event in work.alerts.replay_after(0))
        assert not work.alerts.is_delivery_allowed(obsolete, market_date=chain.now.date())
    from trade_plan_monitor.web.alert_service import PersistentAlertOperationService

    chain.app.state.alert_operation_service = PersistentAlertOperationService(
        unit_of_work_factory=chain.plans._unit_of_work, clock=lambda: chain.now
    )
    response = chain.client.get("/api/v1/alerts")
    assert response.status_code == 200, response.text
    old = next(item for item in response.json()["items"] if item["eventId"] == identity)
    assert old["status"] == "UNSUPPORTED"
    assert old["currentActionable"] is False
    acknowledged = chain.post(
        "alert-acknowledgements", {"alertId": identity, "expectedRevision": 0}
    )
    assert acknowledged["status"] == "UNSUPPORTED"
    assert acknowledged["revision"] == 1
    from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher

    dispatcher = NotificationDispatcher(
        chain.plans._require_session_factory(), clock=lambda: chain.now
    )
    # This uses the default enforce_current_plan=False: obsolete data is still
    # never delivered through built-in or custom channels.
    assert asyncio.run(dispatcher.dispatch_event(UUID(identity))) == ()
    assert asyncio.run(dispatcher.dispatch_pending()) == ()
    asyncio.run(dispatcher.aclose())


def test_expired_plan_latched_risk_uses_actual_production_deadline_and_simulation(
    tmp_path, monkeypatch
):
    from datetime import datetime

    from tests.integration.test_daily_plan_chain import SH, Chain
    from tests.integration.test_daily_production_reevaluation import (
        DailyRecoverySDK,
        ProductionDailyChain,
    )

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan as DailyTradePlan
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    c = ProductionDailyChain(
        tmp_path,
        monkeypatch,
        sdk_type=DailyRecoverySDK,
        initial_now=datetime(2026, 9, 18, 14, tzinfo=SH),
    )
    raw = c.plan.model_dump(mode="json")
    raw["activation"] = {"mode": "DATE_RANGE", "start_date": str(FRIDAY), "end_date": str(FRIDAY)}
    raw["levels"]["risk_line_fen"] = 3700
    c.plan = DailyTradePlan.model_validate(raw)
    with c.client:
        c.activate()
        c.position()
        state = c.composition._runtime._run_deadline.__self__
        c.now = datetime(2026, 9, 18, 16, tzinfo=SH)
        deadline = MarketDeadline(
            kind=DeadlineKind.OFFICIAL_CLOSE, trade_date=FRIDAY, due_at=c.now, close_attempt=1
        )
        c.client.portal.call(state.run_deadline, deadline)
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
            c.fact(kind)
        assert (
            next(r for r in c.current()["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"]
            == "CONFIRMED"
        )
        c.now = datetime(2026, 9, 22, 10, tzinfo=SH)
        c.fact("TRADABILITY", official=True)
        assert c.plan.symbol in state._pipeline.active_symbols()
        # The SDK supplies one certified minute per deadline. A real five-minute
        # decision needs all five minutes, rather than a fabricated current quote.
        for minute in range(1, 6):
            bar_end = datetime(2026, 9, 22, 10, minute, tzinfo=SH)
            c.now = bar_end + timedelta(seconds=12)
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=TUESDAY, due_at=c.now, bar_end=bar_end
            )
            c.client.portal.call(state.run_deadline, deadline)
        current = c.current()
        assert current["quote"] is not None, {
            "blockers": current["dataBlockers"],
            "risk": current["riskAction"],
            "calls": c.sdk.calls[-8:],
        }
        assert current["riskAction"]["coreQty"] == 100, current
        assert current["signals"] == []
        action = {
            "cause_id": current["riskAction"]["causeId"],
            "cause_revision": current["riskAction"]["causeRevision"],
        }
        Chain.simulate(c, action, 100)
        assert c.current()["inventory"]["totalQty"] == 0
        assert (
            next(r for r in c.current()["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"]
            == "FULFILLED"
        )
        assert c.plan.symbol not in state._pipeline.active_symbols()


def test_new_fact_blocks_queued_notification_before_reevaluation(chain):
    from uuid import UUID

    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

    _, ready = ready_chain(chain)
    identity = ready.event_ids[0]
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(UUID(identity))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.app.state.runtime_lifecycle = None
    chain.post(
        "plan-facts",
        {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "race-invalidation",
            "kind": "SIGNAL_INVALIDATION",
            "signalId": ready.snapshot["signals"][0]["signal_id"],
            "tradeDate": str(TUESDAY),
            "evidence": "Synthetic independently verified current invalidation facts",
            "expectedRevision": 0,
        },
    )
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(
            work.daily.session, work.alerts.get(UUID(identity)), chain.now
        )


@pytest.mark.parametrize("boundary", ["api", "production"])
def test_old_active_broker_plan_does_not_break_production_targets(production_chain, boundary):
    from hashlib import sha256

    from tests.unit.test_daily_plan import synthetic_plan_payload

    from trade_plan_monitor.state.models import ActivePlan, PlanVersion

    c = production_chain
    original_plan, original_version = c.plan, c.version
    other = c.plan.model_copy(update={"symbol": "601022.SH", "plan_id": "other-valid-daily"})
    c.plan = other
    c.activate()
    c.plan, c.version = original_plan, original_version
    with c.plans._unit_of_work() as work:
        row = work.daily.session.get(PlanVersion, c.version["id"])
        active = work.daily.session.get(ActivePlan, SYMBOL)
        original_active = (active.plan_version_id, active.revision, active.activated_at)
        # Preserve actual historical schema4 bytes; malformed current bytes are corruption.
        raw = synthetic_plan_payload()
        raw["trading_rules"].update(
            {
                "buy_min_qty": 100,
                "buy_increment": 100,
                "sell_increment": 100,
                "odd_lot_liquidation": False,
                "as_of": "2026-09-18",
                "evidence": "Original independently reviewed broker rules",
            }
        )
        serialized = json.dumps(
            raw, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
        row.payload_json = serialized
        row.plan_hash = sha256(serialized.encode()).hexdigest()
        work.commit()
    if boundary == "api":
        response = c.client.get("/api/v1/plan-versions/" + c.version["id"])
        assert response.status_code == 200, response.text
        assert not response.json()["canActivate"]
        assert response.json()["obsoleteReason"] == "DAILY_DRAFT_OBSOLETE"
        listed = c.client.get("/api/v1/plan-versions")
        assert listed.status_code == 200, listed.text
        assert {item["symbol"] for item in listed.json()["items"]} == {SYMBOL, other.symbol}
        with c.plans._unit_of_work() as work:
            active = work.daily.session.get(ActivePlan, SYMBOL)
            assert (active.plan_version_id, active.revision, active.activated_at) == original_active
            old = work.daily.session.get(PlanVersion, c.version["id"])
            assert old.payload_json == serialized
            assert old.plan_hash == sha256(serialized.encode()).hexdigest()
        return
    pipeline = c.composition._runtime._run_deadline.__self__._pipeline
    assert tuple(plan.symbol for plan in pipeline.active_plans()) == (other.symbol,)


def test_invalidation_after_simulation_preserves_consumption(chain):
    series, ready = ready_chain(chain)
    signal = ready.snapshot["signals"][0]
    chain.simulate(signal)
    chain.post(
        "plan-facts",
        {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "after-simulation-invalidation",
            "kind": "SIGNAL_INVALIDATION",
            "signalId": signal["signal_id"],
            "tradeDate": str(TUESDAY),
            "evidence": "Synthetic independently verified technical invalidation after simulation",
            "expectedRevision": 0,
        },
    )
    result = chain.evaluate(series=series, price=3970)
    assert result.snapshot["signals"][0]["state"] == "SIMULATED"
    assert result.snapshot["signals"][0]["simulated_qty"] == 100
    from tests.integration.test_daily_simulation import command, inventory

    from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService

    before = inventory(chain)
    chain.runtime = DailyRuntimeEvaluationService(
        chain.plans._unit_of_work, clock=lambda: chain.now
    )
    restarted = chain.evaluate(series=series, price=3970)
    assert restarted.snapshot["signals"][0]["state"] == "SIMULATED"
    assert restarted.event_ids == ()
    chain.post("simulated-trades", command(chain, restarted.snapshot["signals"][0]), status=409)
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=SYMBOL, kind="SIMULATION")) == 1


def test_expired_latched_risk_survives_new_production_composition(tmp_path, monkeypatch):
    from datetime import datetime

    from tests.integration.test_daily_plan_chain import SH, Chain
    from tests.integration.test_daily_production_reevaluation import (
        DailyRecoverySDK,
        ProductionDailyChain,
    )

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan as DailyTradePlan
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    c = ProductionDailyChain(
        tmp_path,
        monkeypatch,
        sdk_type=DailyRecoverySDK,
        initial_now=datetime(2026, 9, 18, 14, tzinfo=SH),
    )
    raw = c.plan.model_dump(mode="json")
    raw["activation"] = {"mode": "DATE_RANGE", "start_date": str(FRIDAY), "end_date": str(FRIDAY)}
    raw["levels"]["risk_line_fen"] = 3700
    c.plan = DailyTradePlan.model_validate(raw)
    with c.client:
        c.activate()
        c.position()
        state = c.composition._runtime._run_deadline.__self__
        c.now = datetime(2026, 9, 18, 16, tzinfo=SH)
        c.client.portal.call(
            state.run_deadline,
            MarketDeadline(
                kind=DeadlineKind.OFFICIAL_CLOSE, trade_date=FRIDAY, due_at=c.now, close_attempt=1
            ),
        )
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
            c.fact(kind)
        assert (
            next(r for r in c.current()["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"]
            == "CONFIRMED"
        )
    c.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    c.compose()
    with c.client:
        state = c.composition._runtime._run_deadline.__self__
        assert c.plan.symbol in state._pipeline.active_symbols()
        c.fact("TRADABILITY", official=True)
        for minute in range(1, 6):
            bar_end = datetime(2026, 9, 22, 10, minute, tzinfo=SH)
            c.now = bar_end + timedelta(seconds=12)
            c.client.portal.call(
                state.run_deadline,
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=TUESDAY,
                    due_at=c.now,
                    bar_end=bar_end,
                ),
            )
        current = c.current()
        assert current["riskAction"]["coreQty"] == 100, current
        assert current["signals"] == []
        Chain.simulate(
            c,
            {
                "cause_id": current["riskAction"]["causeId"],
                "cause_revision": current["riskAction"]["causeRevision"],
            },
            100,
        )
        assert c.current()["inventory"]["totalQty"] == 0
        assert c.plan.symbol not in state._pipeline.active_symbols()
