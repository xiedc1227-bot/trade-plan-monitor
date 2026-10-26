"""Actual API review/activation, runtime and whole simulation for all P2 routes."""

from datetime import datetime, time, timedelta

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY, Chain
from tests.integration.test_market_exception_runtime import approve_current, exception_inputs
from tests.unit.test_p2_composition import fixture


def with_economics(plan, mode="REQUIRED"):
    from tests.unit.test_p2_economics import economics

    from trade_plan_monitor.domain.p2_policy_models import P2TradePlan
    raw = plan.model_dump(mode="json")
    raw["levels"]["pressure"] = dict(low_fen=180, high_fen=200,
        include_low=True, include_high=True)
    raw["levels"]["risk_line_fen"] = 140
    policy = raw["ordinary_rules"][0]["pretrade_policy"]
    policy["economics"] = economics() | dict(target_price_fen=180, risk_price_fen=140,
        gates=dict(min_net_reward_fen=0, min_reward_risk_ratio="0.8"))
    policy["economics"]["fee_schedule"].update(effective_from="2026-09-01",
        effective_through="2026-10-31", minimum_commission_fen=0, symbols=[plan.symbol])
    policy["level_evidence"] = [dict(level=level, dimension=dimension,
        source="synthetic", excerpt="reviewed fixture evidence", as_of=None, indicator=None)
        for level in ("PRESSURE", "RISK") for dimension in ("PRICE_STRUCTURE", "TREND")]
    if mode == "PREVIEW_ONLY":
        policy["economics"]["mode"] = mode
        policy["economics"].pop("gates")
    return P2TradePlan.model_validate(raw)


@pytest.fixture(params=["ORDINARY", "WEAK_MINIMUM", "BROKEN_STRONG"])
def p2_chain(tmp_path, request):
    chain = Chain(tmp_path)
    chain.p2_route = request.param[0] if isinstance(request.param, tuple) else request.param
    chain.route = "BROKEN_STRONG" if chain.p2_route == "BROKEN_STRONG" else "WEAK_MINIMUM"
    chain.plan, _ = fixture(200 if chain.p2_route == "WEAK_MINIMUM" else 1000, chain.route)
    if isinstance(request.param, tuple):
        chain.plan = with_economics(chain.plan)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar
        with chain.plans._unit_of_work() as work:
            history = tuple(FRIDAY-timedelta(days=i) for i in reversed(range(60)))
            for previous, day in zip((history[0]-timedelta(days=1), *history, TUESDAY),
                                     (*history, TUESDAY, WEDNESDAY), strict=True):
                work.daily.session.add(TradingCalendar(
                    exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous))
            work.commit()
        chain.position()
        yield chain


def test_review_activate_confirm_and_simulate_p2_quantity(p2_chain):
    chain = p2_chain
    if chain.p2_route == "ORDINARY":
        chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
        expected = 200
    else:
        approved = approve_current(chain)
        expected = approved.candidate.frozen_quantity
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    signal = result.snapshot["signals"][0]
    assert signal["pretrade"]["sizing"]["q0"] == (100 if expected == 100 else 500)
    assert signal["executable_qty"] == expected
    receipt = chain.simulate(signal)
    assert receipt["quantity"] == expected
