"""Risk exits and actionable notification checks retain their own authority."""

from datetime import datetime, time, timedelta
from uuid import UUID

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, Chain
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_p2_chain import p2_chain as p2_chain
from tests.integration.test_p2_chain import with_economics
from tests.unit.test_p2_composition import fixture
from tests.unit.test_p2_policy_contract import p2_payload

from trade_plan_monitor.domain.p2_policy_models import P2TradePlan
from trade_plan_monitor.notifications.daily_models import render_daily_alert
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed


@pytest.mark.parametrize("p2_chain", [("ORDINARY", "REQUIRED")], indirect=True)
def test_actionable_message_uses_own_rule_and_rechecks_current_gate(p2_chain):
    chain = p2_chain
    chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    inputs = exception_inputs(chain)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    with chain.plans._unit_of_work() as work:
        event = next(work.alerts.get(UUID(i)) for i in result.event_ids)
        assert event.rule_id == chain.plan.ordinary_rules[0].rule_id
        assert event.pretrade_mode == "REQUIRED"
        assert "估算不是实际盈亏或批准" in render_daily_alert(event)
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.now += timedelta(seconds=1)
    inputs = exception_inputs(chain)
    inputs = inputs.model_copy(update={"quote": inputs.quote.model_copy(
        update={"price_fen": 175})})
    blocked = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    assert blocked.snapshot["signals"][0]["executable_qty"] == 0
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_risk_exit_bypasses_failed_buy_economics(tmp_path):
    chain = Chain(tmp_path)
    chain.route = "WEAK_MINIMUM"
    plan, _ = fixture(1000)
    raw = with_economics(plan).model_dump(mode="json")
    raw["risk_branches"] = [r for r in p2_payload()["risk_branches"]
                            if r["kind"] != "ORDINARY_TECHNICAL"]
    raw["ordinary_rules"][0]["pretrade_policy"]["economics"]["gates"][
        "min_net_reward_fen"] = 1000000
    chain.plan = P2TradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar
        with chain.plans._unit_of_work() as work:
            work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=FRIDAY,
                is_open=True, previous_trade_date=FRIDAY-timedelta(days=1)))
            work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=TUESDAY,
                is_open=True, previous_trade_date=FRIDAY))
            work.commit()
        chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
        chain.position()
        chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
            chain.now += timedelta(seconds=1)
            chain.post("daily-plan-facts", dict(planVersionId=chain.version["id"],
                contentHash=chain.version["contentHash"], factId="risk-"+kind,
                kind=kind, tradeDate=str(FRIDAY), expectedRevision=0,
                evidence="Synthetic complete technical failure independently verified"))
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        assert all(s["executable_qty"] == 0 for s in result.snapshot["signals"])
        assert result.snapshot["risk_action"]["status"] == "RISK_EXIT"
        assert result.snapshot["risk_action"]["core_qty"] == 100
        assert result.snapshot["risk_action"]["blockers"] == []
        receipt = chain.simulate(result.snapshot["risk_action"], quantity=100)
        assert receipt["side"] == "SELL" and receipt["quantity"] == 100
