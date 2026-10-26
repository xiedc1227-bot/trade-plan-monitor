"""P2 decisions consume only facts available at their decision cutoff."""

from datetime import timedelta

import pytest
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_p2_chain import p2_chain as p2_chain
from tests.integration.test_p2_replay import frozen_approval, research_run_input

from trade_plan_monitor.decision.p2_composition import evaluate_p2_market

pytestmark = pytest.mark.parametrize("p2_chain",
    [(route, "REQUIRED") for route in ("WEAK_MINIMUM", "BROKEN_STRONG")], indirect=True)


def decision(chain, inputs):
    return evaluate_p2_market(chain.plan, chain.plan.ordinary_rules[0],
        series=inputs.series, index_bars=inputs.linked_index.official_daily_bars,
        session_dates=inputs.session_dates, decision_session=inputs.official_trade_date,
        cutoff=inputs.evaluated_at, inventory={"known": True, "total_qty": 0},
        risk="UNSATISFIED")


@pytest.mark.parametrize("field", ["received_at", "available_at", "adjustment_as_of"])
def test_future_daily_evidence_cannot_supply_q0(p2_chain, field):
    from pydantic import ValidationError

    from trade_plan_monitor.decision.p2_composition import prepare_p2_rule

    chain = p2_chain
    inputs = exception_inputs(chain)
    later = inputs.evaluated_at + timedelta(days=1)
    series = inputs.series
    changes = ({field: later.date()} if field == "adjustment_as_of" else
        {"bars": (*series.bars[:-1], type(series.bars[-1]).model_construct(
            **{**series.bars[-1].__dict__, field: later}))})
    with pytest.raises(ValidationError):
        series.model_copy(update=changes)
    # Exercise the policy's second boundary even if an internal caller bypasses parsing.
    series = type(series).model_construct(**{**series.__dict__, **changes})
    effective, sizing = prepare_p2_rule(chain.plan, chain.plan.ordinary_rules[0],
        series=series, decision_session=inputs.official_trade_date, cutoff=inputs.evaluated_at)
    assert sizing.q0 is None and effective is None


def test_refetch_identity_does_not_change_consumed_p2_hash(p2_chain):
    from decimal import Decimal

    original = decision(p2_chain, exception_inputs(p2_chain))
    refetched = decision(p2_chain, exception_inputs(p2_chain, refetch=True))
    assert original.sizing == refetched.sizing
    assert original.decision.consumed_hash == refetched.decision.consumed_hash
    inputs = exception_inputs(p2_chain)
    bars = tuple(bar.model_copy(update={key: getattr(bar, key).quantize(Decimal("0.000"))
        for key in ("open", "high", "low", "close")}) for bar in inputs.series.bars)
    same_values = decision(p2_chain, inputs.model_copy(update={
        "series": inputs.series.model_copy(update={"bars": bars})}))
    assert original.decision.consumed_hash == same_values.decision.consumed_hash
    corrected = decision(p2_chain, exception_inputs(p2_chain, correction=True))
    assert original.decision.consumed_hash != corrected.decision.consumed_hash


def test_future_approval_does_not_change_prior_private_state(p2_chain, tmp_path):
    from trade_plan_monitor.backtest.exception_replay import apply_frozen_exception
    from trade_plan_monitor.backtest.research_session import ResearchSession
    from trade_plan_monitor.market_data.models import TradingDay

    chain = p2_chain
    event = frozen_approval(chain)
    inputs = exception_inputs(chain)
    calendar = tuple(TradingDay(exchange="SSE", cal_date=day, is_open=True,
        previous_trade_date=inputs.session_dates[i - 1] if i else day-timedelta(days=1))
        for i, day in enumerate(inputs.session_dates))
    session = ResearchSession(tmp_path, research_run_input(chain, events=(event,)), calendar)
    try:
        session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        before = session.inventory()
        session.now = event.event.received_at - timedelta(seconds=1)
        outcome = apply_frozen_exception(session, event)
        assert outcome.status == "BLOCKED"
        assert outcome.blockers == ("EXCEPTION_REPLAY_RECEIPT_TIME_MISMATCH",)
        session.now = event.event.received_at
        assert session.inventory() == before
        with session.work() as work:
            assert work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL") == ()
        assert apply_frozen_exception(session, event).status == "APPLIED"
    finally:
        session.close()
