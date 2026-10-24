"""Real daily composition offers candidates, never automatic exception trades."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY, Chain
from tests.integration.test_market_linkage_runtime import index_snapshot
from tests.unit.test_market_exception_contract import exception_payload
from tests.unit.test_relative_strength import stock_fixture

from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.market_index.models import SmaFactRequest
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.runtime.market_exceptions import (
    apply_exception_decision,
    current_exception_authority,
)
from trade_plan_monitor.state.market_exception_service import (
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    preview_exception,
)


@pytest.fixture(params=["WEAK_MINIMUM", "BROKEN_STRONG"])
def exception_chain(tmp_path, request):
    chain = Chain(tmp_path)
    chain.route = request.param
    raw = exception_payload()
    raw["risk_branches"] = []
    raw["position"]["max_qty"] = 1000
    zone = dict(low_fen=100, high_fen=200, include_low=True, include_high=True)
    raw["levels"]["low_buy"] = zone
    raw["ordinary_rules"][0].update(
        validity={"mode": "PLAN_ACTIVE"}, independent_signal={"mode": "ONCE_PER_RULE"},
        condition=dict(type="DAILY_PRICE_IN_RANGE", field="close", offset=0, range=zone))
    raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = (
        100 if chain.route == "WEAK_MINIMUM" else 500)
    chain.plan = MarketExceptionTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar
        with chain.plans._unit_of_work() as work:
            for previous, day in ((FRIDAY-timedelta(days=1), FRIDAY),
                                  (FRIDAY, TUESDAY), (TUESDAY, WEDNESDAY)):
                work.daily.session.add(TradingCalendar(
                    exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous))
            work.commit()
        chain.position()
        yield chain


def exception_inputs(chain, *, correction=False, refetch=False):
    snapshot, days = index_snapshot(chain.plan)
    bars = []
    for i, bar in enumerate(snapshot.official_daily_bars):
        close = Decimal(200 if i < 58 else 190 if i == 58 else
                        195 if chain.route == "WEAK_MINIMUM" else 180)
        bars.append(bar.model_copy(update=dict(open_points=close, close_points=close,
            high_points=close+1, low_points=close-1)))
    if correction:
        bars[30] = bars[30].model_copy(update={"low_points": Decimal(1)})
    snapshot = build_market_index_snapshot(
        index_code=snapshot.index_code, decision_cutoff=snapshot.decision_cutoff,
        requests=(SmaFactRequest(period=60),), five_minute_bars=snapshot.five_minute_bars,
        official_daily_bars=tuple(bars), content_revision=2 if correction else 1,
        observed_at=datetime.combine(FRIDAY, time(16), SH), observed_no_later_than=chain.now)
    series = stock_fixture(days, datetime.combine(FRIDAY, time(16), SH))
    prices = [Decimal(100+i+2*(i % 2)) for i in range(len(days))]
    stock = tuple(bar.model_copy(update=dict(symbol=chain.plan.symbol,
        bar_id=("refetch-" if refetch else "")+bar.bar_id,
        open=price, close=price, high=price+1, low=price-1))
        for bar, price in zip(series.bars, prices, strict=True))
    series = series.model_copy(update={"symbol": chain.plan.symbol, "bars": stock})
    quote = None if chain.now.date() == FRIDAY else DailyExecutionQuote(
        symbol=chain.plan.symbol, price_fen=161, quote_at=chain.now, available_at=chain.now,
        evaluated_at=chain.now, tradable=True, special_state_verified=True,
        liquidity_available=True)
    return DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=FRIDAY,
        series=series, session_dates=(*days, TUESDAY, WEDNESDAY), suspended_dates=(),
        quote=quote, data_blockers=(), linked_index=snapshot)


def approve_current(chain):
    current = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    row = current.snapshot["exception_candidates"][0]
    with chain.plans._unit_of_work() as work:
        shown = preview_exception(work.daily, ExceptionPreviewCommand(
            candidate_id=row["candidate"]["candidate_id"], expected_revision=row["revision"],
            proposed_quantity=None if chain.route == "WEAK_MINIMUM" else 300),
            current=lambda c: current_exception_authority(work, c, chain.now), now=chain.now)
        approved = apply_exception_decision(work, ExceptionDecisionCommand(
            command_id="review-once", candidate_id=shown.candidate_id, expected_revision=1,
            decision="APPROVE", reason="Reviewed this occurrence", preview_id=shown.preview_id,
            preview_hash=shown.preview_hash), now=chain.now)
        work.commit()
    return approved


def test_actual_runtime_requires_approval_and_keeps_full_quantity(exception_chain):
    chain = exception_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert first.snapshot["signals"] == []
    assert len(first.snapshot["exception_candidates"]) == 1, first.snapshot["market_linkage"]
    assert first.snapshot["market_linkage"][0]["calculation"]["authorized_quantity"] == 0
    with chain.plans._unit_of_work() as work:
        from uuid import UUID

        from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

        reminder = work.alerts.get(UUID(next(i for i in first.event_ids if i)))
        assert reminder.quantity is None
        assert reminder.alert_kind == "EXCEPTION_REVIEW"
        assert daily_delivery_allowed(work.daily.session, reminder, chain.now)
    approved = approve_current(chain)
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL")) == 1
        assert not daily_delivery_allowed(work.daily.session, reminder, chain.now)
    same_clock = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert same_clock.snapshot["signals"][0]["planned_qty"] == approved.candidate.frozen_quantity
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert ready.snapshot["signals"][0]["executable_qty"] == approved.candidate.frozen_quantity


def test_refetch_keeps_candidate_but_correction_invalidates(exception_chain):
    chain = exception_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    original = first.snapshot["exception_candidates"][0]
    refreshed = chain.runtime.run_inputs(plan=chain.plan,
        inputs=exception_inputs(chain, refetch=True))
    assert refreshed.snapshot["exception_candidates"][0] == original
    corrected = chain.runtime.run_inputs(plan=chain.plan,
        inputs=exception_inputs(chain, correction=True))
    assert corrected.snapshot["exception_candidates"][0]["candidate"]["state"] == "INVALIDATED"


def test_rejection_and_clone_cannot_create_another_occurrence(exception_chain):
    chain = exception_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    row = first.snapshot["exception_candidates"][0]
    with chain.plans._unit_of_work() as work:
        apply_exception_decision(work, ExceptionDecisionCommand(
            command_id="reject", candidate_id=row["candidate"]["candidate_id"],
            expected_revision=1, decision="REJECT", reason="Reject once"), now=chain.now)
        work.commit()
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(chain.plan.symbol)
    chain.activate(plan_id="cloned-plan", activation_revision=active.revision,
                   supplement_revision=1)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert len(result.snapshot["exception_candidates"]) == 1
    assert result.snapshot["exception_candidates"][0]["candidate"]["state"] == "REJECTED"
    assert not result.snapshot["signals"]


def test_revocation_masks_read_and_queued_buy_without_waiting_for_evaluation(exception_chain):
    from uuid import UUID

    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
    from trade_plan_monitor.state.market_exception_service import (
        ExceptionRevocationCommand,
        revoke_exception,
    )

    chain = exception_chain
    approved = approve_current(chain)
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(UUID(next(i for i in result.event_ids if i)))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        revoke_exception(work.daily, ExceptionRevocationCommand(
            command_id="withdraw", approval_id=approved.event.event_id, expected_revision=2,
            reason="Explicit withdrawal"), now=chain.now)
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)
    read = chain.client.get("/api/v1/plan-runtime/" + chain.plan.symbol)
    assert read.status_code == 200, read.text
    assert read.json()["snapshot"]["signals"][0]["executableQty"] == 0


def test_completion_proof_tracks_candidate_authority_revision(exception_chain):
    from uuid import uuid4

    from trade_plan_monitor.runtime.status_authority import (
        capture_condition_completion_proof,
        condition_completion_matches,
    )
    from trade_plan_monitor.state.repositories import MarketReferenceRepository

    chain = exception_chain
    generation = uuid4()
    with chain.plans._unit_of_work() as work:
        calendar = MarketReferenceRepository(work.daily.session).list_trading_days(
            "SSE", FRIDAY, WEDNESDAY)
    inputs = exception_inputs(chain).model_copy(update={
        "runtime_generation": str(generation), "trading_calendar": calendar})
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    with chain.plans._unit_of_work() as work:
        proof = capture_condition_completion_proof(work.daily.session, plan=chain.plan,
            result=result, runtime_generation=generation, configuration_revision=1,
            now=chain.now, consumed_inputs=inputs)
        assert proof is not None
        assert condition_completion_matches(work.daily.session, proof=proof,
            snapshot=result.snapshot, now=chain.now)
        candidate = result.snapshot["exception_candidates"][0]["candidate"]
        apply_exception_decision(work, ExceptionDecisionCommand(
            command_id="reject", candidate_id=candidate["candidate_id"], expected_revision=1,
            decision="REJECT", reason="Declined"), now=chain.now)
        assert not condition_completion_matches(work.daily.session, proof=proof,
            snapshot=result.snapshot, now=chain.now)
