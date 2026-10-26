"""Queued reminders revalidate current capital without creating new occurrences."""

from datetime import datetime, time, timedelta
from uuid import UUID

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_p3_chain import p3_chain as p3_chain

from trade_plan_monitor.notifications.daily_models import render_daily_alert
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed


@pytest.mark.parametrize("p3_chain", [
    ("MARKET_VALUE_CAP", False, "ORDINARY", 48300),
    ("OPEN_COST_CAP", False, "ORDINARY")], indirect=True)
def test_rule_specific_budget_message_and_send_time_stale_suppression(p3_chain):
    chain = p3_chain
    chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(UUID(ready.event_ids[0]))
        assert event.quantity == 200 and event.rule_id == chain.plan.ordinary_rules[0].rule_id
        assert event.capital_mode == chain.capital_mode
        assert "超限不缩量" in render_daily_alert(event)
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    if chain.capital_mode == "MARKET_VALUE_CAP":
        chain.now += timedelta(seconds=1)
        inputs = exception_inputs(chain)
        inputs = inputs.model_copy(update={"quote": inputs.quote.model_copy(
            update={"price_fen": 162})})
        blocked = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        assert blocked.snapshot["signals"][0]["planned_qty"] == 200
        assert blocked.snapshot["signals"][0]["capital_execution"]["outcome"] == "FAIL"
    else:
        book = chain.client.get("/api/v1/simulation-capital-books/"+chain.plan.symbol).json()
        chain.post("simulation-capital-openings", dict(planVersionId=chain.version["id"],
            expectedInventoryRevision=book["inventoryRevision"],
            expectedBookRevision=book["bookRevision"], observedAt=chain.now.isoformat(),
            source="Explicit corrected simulation basis", excerpt="Retained lot cost530000fen",
            reason="Current retained cost correction", confirmed=True,
            lots=[dict(**lot, retained_basis_fen=530000) for lot in book["inventoryLots"]]))
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
