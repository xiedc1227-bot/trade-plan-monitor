from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY, Chain
from tests.unit.test_market_linkage_contract import linked_payload

from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    SmaFactRequest,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs


def index_snapshot(plan, *, missing=False, correction=False):
    days = tuple(FRIDAY - timedelta(days=i) for i in reversed(range(60)))
    bars = tuple(
        MarketIndexBar(
            index_code=plan.reference_market.index_code,
            interval="OFFICIAL_DAILY",
            bar_at=datetime.combine(day, time(15), SH),
            observed_at=datetime.combine(day, time(16), SH),
            open_points=Decimal(100 + i),
            high_points=Decimal(101 + i),
            low_points=Decimal(99 + i),
            close_points=Decimal(100 + i),
            source_kind="OFFICIAL",
            provider_revision=1,
        )
        for i, day in enumerate(days)
    )
    if correction:
        bars = bars[:-1] + (
            bars[-1].model_copy(update={"low_points": Decimal(1), "provider_revision": 2}),
        )
    minute = bars[-1].model_copy(update={"interval": MarketIndexInterval.FIVE_MINUTE})
    return build_market_index_snapshot(
        index_code=plan.reference_market.index_code,
        decision_cutoff=datetime.combine(FRIDAY, time(15), SH),
        requests=(SmaFactRequest(period=60),),
        five_minute_bars=(minute,),
        official_daily_bars=bars[:-1] if missing else bars,
        content_revision=2 if correction else 1,
        observed_at=datetime.combine(FRIDAY, time(16), SH),
        observed_no_later_than=datetime.combine(FRIDAY, time(16), SH),
    ), days


@pytest.fixture
def linked_chain(tmp_path):
    chain = Chain(tmp_path)
    raw = linked_payload()
    raw["risk_branches"] = []
    raw["position"]["max_qty"] = 1000
    raw["ordinary_rules"][0].update(
        validity={"mode": "PLAN_ACTIVE"},
        independent_signal={"mode": "ONCE_PER_RULE"},
        condition=dict(
            type="DAILY_PRICE_IN_RANGE", field="close", offset=0, range=raw["levels"]["low_buy"]
        ),
    )
    chain.plan = MarketLinkedTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar

        with chain.plans._unit_of_work() as work:
            for previous, day in (
                (FRIDAY - timedelta(days=1), FRIDAY),
                (FRIDAY, TUESDAY),
                (TUESDAY, WEDNESDAY),
            ):
                work.daily.session.add(
                    TradingCalendar(
                        exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous
                    )
                )
            work.commit()
        chain.position()
        yield chain


def linked_inputs(chain, *, missing=False, correction=False):
    snapshot, days = index_snapshot(chain.plan, missing=missing, correction=correction)
    quote = (
        None
        if chain.now.date() == FRIDAY
        else DailyExecutionQuote(
            symbol=chain.plan.symbol,
            price_fen=3970,
            quote_at=chain.now,
            available_at=chain.now,
            evaluated_at=chain.now,
            tradable=True,
            special_state_verified=True,
            liquidity_available=True,
        )
    )
    return DailyRuntimeInputs(
        evaluated_at=chain.now,
        official_trade_date=FRIDAY,
        series=chain.series(),
        session_dates=(*days, TUESDAY, WEDNESDAY),
        suspended_dates=(),
        quote=quote,
        data_blockers=(),
        linked_index=snapshot,
    )


def test_real_runtime_freezes_whole_quantity_and_next_session(linked_chain):
    chain = linked_chain
    confirmed = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    assert confirmed.snapshot["signals"], confirmed.snapshot["market_linkage"]
    signal = confirmed.snapshot["signals"][0]
    assert signal["planned_qty"] == 300
    assert signal["executable_qty"] == 0
    assert signal["market_linkage"]["selection"]["group"] == "S0"
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    assert ready.snapshot["signals"][0]["signal_id"] == signal["signal_id"]
    assert ready.snapshot["signals"][0]["executable_qty"] == 300
    receipt = chain.simulate(ready.snapshot["signals"][0])
    assert receipt["quantity"] == 300
    assert receipt["inventory"]["totalQty"] == 400


def test_missing_exact_d_cannot_confirm(linked_chain):
    chain = linked_chain
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain, missing=True))
    assert not result.snapshot["signals"]
    assert result.snapshot["market_linkage"][0]["calculation"]["authorized_quantity"] == 0


def test_refetch_metadata_and_intraday_revision_do_not_invalidate_daily_signal(linked_chain):
    from trade_plan_monitor.state.market_linkage_authority import linked_index_current

    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    original, _ = index_snapshot(chain.plan)
    refreshed = build_market_index_snapshot(
        index_code=original.index_code, decision_cutoff=chain.now,
        requests=original.fact_requests,
        five_minute_bars=(original.latest_completed_five_minute,),
        official_daily_bars=(original.official_daily_bars[0].model_copy(update={
            "bar_at": original.official_daily_bars[0].bar_at - timedelta(days=1),
        }),) + tuple(bar.model_copy(update={
            "observed_at": chain.now, "provider_revision": 537,
        }) for bar in original.official_daily_bars),
        content_revision=537, observed_at=chain.now, observed_no_later_than=chain.now,
    )
    with chain.plans._unit_of_work() as work:
        work.projections.put_market_index_snapshot(refreshed, provider_content_revision=537)
        work.projections.advance_market_index_head(refreshed, provider_content_revision=537)
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert linked_index_current(work.daily.session, first.snapshot, chain.now)
    repeated = chain.runtime.run_inputs(plan=chain.plan,
        inputs=linked_inputs(chain).model_copy(update={"linked_index": refreshed}))
    assert repeated.snapshot["signals"][0]["signal_id"] == first.snapshot["signals"][0]["signal_id"]
    assert repeated.snapshot["signals"][0]["executable_qty"] == 300
    assert chain.simulate(repeated.snapshot["signals"][0])["quantity"] == 300


def test_correction_invalidates_without_resizing_or_restoration(linked_chain):
    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    chain.now += timedelta(seconds=1)
    changed = chain.runtime.run_inputs(
        plan=chain.plan, inputs=linked_inputs(chain, correction=True)
    )
    assert changed.snapshot["signals"][0]["state"] == "INVALIDATED"
    assert (
        changed.snapshot["signals"][0]["planned_qty"] == first.snapshot["signals"][0]["planned_qty"]
    )
    chain.now += timedelta(seconds=1)
    restored = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    assert len(restored.snapshot["signals"]) == 1
    assert restored.snapshot["signals"][0]["executable_qty"] == 0


@pytest.mark.parametrize("correct_price", [False, True])
def test_stock_refetch_preserves_signal_but_price_correction_invalidates(
    linked_chain, correct_price
):
    from trade_plan_monitor.market_data.daily_data import DailySeries

    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    inputs = linked_inputs(chain)
    raw = inputs.series.model_dump()
    raw.update(cutoff=chain.now, adjustment_as_of=chain.now.date())
    for bar in raw["bars"]:
        bar.update(bar_id="refetched-" + bar["bar_id"], received_at=chain.now,
                   available_at=chain.now, adjustment_as_of=chain.now.date())
        for field in ("open", "high", "low", "close"):
            bar[field] = bar[field].quantize(Decimal("0.00"))
    if correct_price:
        raw["bars"][-1]["low"] -= Decimal(1)
    refreshed = DailySeries.model_validate(raw)
    result = chain.runtime.run_inputs(plan=chain.plan,
        inputs=inputs.model_copy(update={"series": refreshed}))
    signal = result.snapshot["signals"][0]
    assert signal["signal_id"] == first.snapshot["signals"][0]["signal_id"]
    assert signal["planned_qty"] == 300
    assert signal["state"] == ("INVALIDATED" if correct_price else "READY")
    assert signal["executable_qty"] == (0 if correct_price else 300)
    if not correct_price:
        assert chain.simulate(signal)["quantity"] == 300


def test_later_correction_with_lower_content_hash_revision_advances_head(linked_chain):
    chain = linked_chain
    original, _ = index_snapshot(chain.plan)

    def revised(revision, observed, *, correct=False):
        bars = original.official_daily_bars
        if correct:
            bars = bars[:-1] + (bars[-1].model_copy(update={"low_points": Decimal(1)}),)
        return build_market_index_snapshot(
            index_code=original.index_code, decision_cutoff=original.decision_cutoff,
            requests=original.fact_requests,
            five_minute_bars=(original.latest_completed_five_minute,),
            official_daily_bars=bars, content_revision=revision,
            observed_at=observed, observed_no_later_than=observed,
        )

    initial = revised(999, chain.now)
    chain.runtime.run_inputs(plan=chain.plan,
        inputs=linked_inputs(chain).model_copy(update={"linked_index": initial}))
    chain.now += timedelta(seconds=1)
    corrected = revised(2, chain.now, correct=True)
    changed = chain.runtime.run_inputs(plan=chain.plan,
        inputs=linked_inputs(chain).model_copy(update={"linked_index": corrected}))
    assert changed.snapshot["signals"][0]["state"] == "INVALIDATED"
    with chain.plans._unit_of_work() as work:
        head = work.projections.get_market_index_head(
            mapping_version=corrected.mapping_version, index_code=corrected.index_code,
            decision_cutoff=corrected.decision_cutoff, request_set_hash=corrected.request_set_hash,
        )
        assert head.snapshot.snapshot_hash == corrected.snapshot_hash
    chain.now += timedelta(seconds=1)
    old = chain.runtime.run_inputs(plan=chain.plan,
        inputs=linked_inputs(chain).model_copy(update={"linked_index": initial}))
    assert old.snapshot["signals"][0]["state"] == "INVALIDATED"


def test_shared_scheduled_index_request_includes_linked_history():
    import asyncio

    from tests.integration.test_market_index_runtime import CUTOFF, OBSERVED_AT, _DashboardProvider

    from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
    from trade_plan_monitor.runtime.market_indexes import RuntimeMarketIndexService

    provider = _DashboardProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    plan = MarketLinkedTradePlan.model_validate(linked_payload())
    service.set_linked_plans((plan, plan.model_copy(update={"symbol": "600001.SH"})))
    asyncio.run(
        service.prepare(plans=(), decision_cutoff=CUTOFF, observed_no_later_than=OBSERVED_AT)
    )
    requests = [r for r in provider.requests if r[0] == plan.reference_market.index_code]
    assert len(requests) == 1
    assert requests[0][-1] == 60


def test_correction_before_reevaluation_fences_simulation_and_is_read_only(linked_chain):
    from uuid import UUID, uuid4

    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
    from trade_plan_monitor.runtime.status_authority import (
        capture_condition_completion_proof,
        condition_completion_matches,
    )
    from trade_plan_monitor.state.market_linkage_authority import linked_index_current
    from trade_plan_monitor.state.repositories import MarketReferenceRepository

    chain = linked_chain
    chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    generation = uuid4()
    with chain.plans._unit_of_work() as work:
        calendar = MarketReferenceRepository(work.daily.session).list_trading_days(
            "SSE", FRIDAY, WEDNESDAY)
    consumed = linked_inputs(chain).model_copy(update={
        "runtime_generation": str(generation), "trading_calendar": calendar})
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=consumed)
    with chain.plans._unit_of_work() as work:
        assert linked_index_current(work.daily.session, ready.snapshot, chain.now)
        event = work.alerts.get(UUID(ready.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        proof = capture_condition_completion_proof(work.daily.session, plan=chain.plan,
            result=ready, runtime_generation=generation, configuration_revision=1,
            now=chain.now, consumed_inputs=consumed)
        assert proof is not None
        assert condition_completion_matches(work.daily.session, proof=proof,
                                            snapshot=ready.snapshot, now=chain.now)
        changed, _ = index_snapshot(chain.plan, correction=True)
        chain.now += timedelta(seconds=1)
        work.projections.put_market_index_snapshot(changed, provider_content_revision=2)
        work.projections.advance_market_index_head(
            changed, provider_content_revision=2, observed_at=chain.now
        )
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert not linked_index_current(work.daily.session, ready.snapshot, chain.now)
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)
        assert not condition_completion_matches(work.daily.session, proof=proof,
                                                snapshot=ready.snapshot, now=chain.now)
        assert capture_condition_completion_proof(work.daily.session, plan=chain.plan,
            result=ready, runtime_generation=generation, configuration_revision=1,
            now=chain.now, consumed_inputs=consumed) is None
        assert not work.daily.session.new and not work.daily.session.dirty
        revision = work.daily.get("simulation-position-" + chain.plan.symbol)["revision"]
    signal = ready.snapshot["signals"][0]
    chain.post(
        "simulated-trades",
        {
            "planVersionId": chain.version["id"],
            "causeId": signal["signal_id"],
            "expectedCauseRevision": signal["revision"],
            "expectedInventoryRevision": revision,
            "quantity": 300,
        },
        status=409,
    )
