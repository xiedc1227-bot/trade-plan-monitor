"""Public Schema9 source review, activation, opening, approval and execution chain."""

from datetime import datetime, time, timedelta

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY, Chain
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository


@pytest.fixture(params=[("MARKET_VALUE_CAP", False, "ORDINARY"),
    ("OPEN_COST_CAP", False, "ORDINARY"), ("MARKET_VALUE_CAP", True, "WEAK_MINIMUM"),
    ("OPEN_COST_CAP", True, "BROKEN_STRONG")])
def p3_chain(tmp_path, request):
    mode, combined, route, *cap = request.param
    chain = Chain(tmp_path)
    chain.route = "BROKEN_STRONG" if route == "BROKEN_STRONG" else "WEAK_MINIMUM"
    chain.p3_route, chain.capital_mode = route, mode
    plan, _ = inputs_for(200 if route == "WEAK_MINIMUM" else 1000,
        chain.route, mode, combined)
    raw = plan.model_dump(mode="json")
    if cap:
        raw["position"]["limit"]["capital_policy"]["cap_fen"] = cap[0]
    if combined:
        raw["position"]["limit"]["max_qty"] = 1000
    if mode == "OPEN_COST_CAP":
        raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"].update(
            effective_from="2026-01-01", effective_through="2026-12-31")
    chain.plan = type(plan).model_validate(raw)
    with chain.client:
        chain.activate()
        with chain.plans._unit_of_work() as work:
            history = tuple(FRIDAY-timedelta(days=i) for i in reversed(range(60)))
            for previous, day in zip((history[0]-timedelta(days=1), *history, TUESDAY),
                                     (*history, TUESDAY, WEDNESDAY), strict=True):
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=True, previous_trade_date=previous))
            work.commit()
        chain.position()
        if mode == "OPEN_COST_CAP":
            with chain.plans._unit_of_work() as work:
                position = work.daily.get("simulation-position-"+plan.symbol)
                lots = position["payload"]["batches"]
            receipt = chain.post("simulation-capital-openings", dict(
                planVersionId=chain.version["id"], expectedInventoryRevision=position["revision"],
                expectedBookRevision=0, observedAt=chain.now.isoformat(),
                source="Explicit synthetic historical simulation costs",
                excerpt="The current complete opening lot retained basis is20000fen",
                reason="Reviewed opening before an explicit simulated buy", confirmed=True,
                lots=[dict(lot_id=lot["id"], bucket=lot["bucket"], quantity=lot["quantity"],
                           retained_basis_fen=20000) for lot in lots]))
            assert receipt["inventoryChanged"] is receipt["authorityGranted"] is False
        yield chain


def test_public_schema9_complete_chain_preserves_exact_quantity_and_book(p3_chain):
    chain = p3_chain
    if chain.p3_route == "ORDINARY":
        chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        expected = 200
    else:
        resource = chain.runtime.run_inputs(plan=chain.plan,
            inputs=exception_inputs(chain)).snapshot["exception_candidates"][0]
        expected = 300 if chain.route == "BROKEN_STRONG" else 100
        shown = chain.post("plan-exception-previews", dict(
            candidateId=resource["candidate"]["candidate_id"], expectedRevision=1,
            proposedQuantity=300 if chain.route == "BROKEN_STRONG" else None))
        approved = chain.post("plan-exception-decisions", dict(commandId="public-approval",
            candidateId=shown["candidateId"], expectedRevision=1, decision="APPROVE",
            reason="Reviewed this exact public occurrence", previewId=shown["previewId"],
            previewHash=shown["previewHash"]))
        assert approved["candidate"]["frozen_quantity"] == expected
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    signal = ready.snapshot["signals"][0]
    assert signal["executable_qty"] == expected
    preview = chain.post("plan-capital-previews", dict(planVersionId=chain.version["id"],
        ruleId=signal["rule_id"], **({"occurrenceId": signal["market_linkage"][
            "calculation"]["approval"]["candidate_id"],
            "proposedQuantity": 300 if chain.route == "BROKEN_STRONG" else None}
            if chain.p3_route != "ORDINARY" else {})))
    assert preview["assessment"]["outcome"] == "PASS" and preview["authorityGranted"] is False
    receipt = chain.simulate(signal, quantity=expected)
    assert receipt["quantity"] == expected and receipt["inventory"]["totalQty"] == 100+expected
    if chain.capital_mode == "OPEN_COST_CAP":
        with chain.plans._unit_of_work() as work:
            book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
            assert book.retained_basis_fen == 20000+expected*161+500
