"""Independent technical risk still evaluates, notifies and sells under a BUY ban."""

from datetime import datetime, time
from uuid import UUID

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY
from tests.integration.test_plan_buy_suspension_recovery import advance
from tests.integration.test_plan_buy_suspension_runtime import chain as chain
from tests.integration.test_plan_buy_suspension_runtime import prepare
from tests.integration.test_unified_runtime import current_plan
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs, daily_delivery_allowed
from trade_plan_monitor.state.simulation import SimulationCommand, simulate_inventory


@pytest.mark.parametrize("latched", [False, True])
def test_guard_alone_never_stops_actual_risk_evaluation_notification_or_sell(chain, latched):
    raw = current_plan(mixed=False, risk=True).model_dump(mode="python")
    severe = unified_payload()["risk_branches"][1]
    severe["condition"] = current_plan().ordinary_rules[0].condition.conditions[0].model_dump(
        mode="python")
    raw["risk_branches"] = [severe]
    owner = prepare(chain, plan=UnifiedTradePlan.model_validate(raw))
    revision = None
    if latched:
        chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
        row = advance(chain)
        assert row["state"].outcome == "LATCHED"
        revision = row["revision"]
    series = chain.series(FRIDAY)
    chain.now = datetime.combine(FRIDAY, time(16), SH)
    def captured(quote=None):
        return DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=FRIDAY,
            series=series, session_dates=(FRIDAY, TUESDAY, WEDNESDAY), suspended_dates=(),
            quote=quote, data_blockers=(), buy_suspension_revision=revision)

    first = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured())
    assert first.snapshot["risks"][0]["status"] == "CONFIRMED"
    chain.now = datetime.combine(TUESDAY, time(10), SH)
    quote = DailyExecutionQuote(symbol=chain.plan.symbol, price_fen=2430, quote_at=chain.now,
        available_at=chain.now, evaluated_at=chain.now, tradable=True,
        special_state_verified=True, liquidity_available=True)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured(quote))
    action = result.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT" and action["tactical_qty"] == 100
    assert result.snapshot["buy_suspension_blocker"] == (
        "BUY_SUSPENSION_LATCHED" if latched else "BUY_SUSPENSION_UNVERIFIED")
    with chain.plans._unit_of_work() as work:
        event = next(work.alerts.get(UUID(identity)) for identity in result.event_ids
            if work.alerts.get(UUID(identity)).signal_type == "RISK_EXIT")
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        inventory = work.daily.get("simulation-position-" + chain.plan.symbol)
        cause = work.daily.get(action["cause_id"])
        receipt = simulate_inventory(work, SimulationCommand(plan_version_id=UUID(
            chain.version["id"]), cause_id=cause["id"], expected_cause_revision=cause["revision"],
            expected_inventory_revision=inventory["revision"], quantity=100), chain.now)
        work.commit()
    assert receipt.side == "SELL" and receipt.inventory.total_qty == 0
