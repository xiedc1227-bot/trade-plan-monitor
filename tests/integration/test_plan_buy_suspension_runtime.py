"""Guard-first runtime with real isolated proof; seeded activation is local T07 evidence."""

from datetime import datetime, time, timedelta

import pytest
from tests.integration.test_plan_buy_suspension_recovery import (
    advance,
    guard_row,
    pipeline,
)
from tests.integration.test_plan_buy_suspension_recovery import (
    chain as chain,
)
from tests.integration.test_unified_runtime import current_plan

from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState


def prepare(chain, *, side="BUY", plan=None, before_guard=None):
    chain.plan = current_plan(mixed=False) if plan is None else plan
    if side == "SELL":
        raw = chain.plan.model_dump(mode="python")
        raw["ordinary_rules"][0]["side"] = "SELL"
        chain.plan = type(chain.plan).model_validate(raw)
    chain.activate()
    chain.position(core=0, tactical=100)
    if before_guard is not None:
        before_guard(chain)
    from tests.integration.test_market_linkage_review import source_mapping

    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
    from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
    from trade_plan_monitor.web.routers.plans import PlanReviewConfirmationCommand

    raw = chain.plan.model_dump(mode="python")
    raw.update(schema_version=10, execution_version="condition-plan-v6", version=2,
        buy_suspension={"condition": {"type": "MINUTE_CLOSE_BELOW",
            "timeframe_minutes": 5, "price_fen": 2420}, "effective_from": chain.now.replace(
                hour=9, minute=30, second=0, microsecond=0)})
    chain.plan = BuySuspensionTradePlan.model_validate(raw)
    draft = BuySuspensionPlanDraft.from_executable(chain.plan)
    source, mapping = source_mapping(draft)
    with chain.plans._unit_of_work() as work:
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
            clock=lambda: chain.now)
        details = work.plans.get_version_details(identity)
        coverage = SourceCoverageStore(work.daily.session).latest(identity)
        reviewed = confirm_daily_review(work, PlanReviewConfirmationCommand(
            plan_version_id=identity, content_hash=details.content_hash,
            source_hash=details.source_hash, review_evidence_hash=details.review_evidence_hash,
            coverage_evidence_hash=coverage.assessment.evidence_hash,
            coverage_rules_version=coverage.assessment.rules_version, expected_revision=0),
            clock=lambda: chain.now)
        # T08 opens the real reviewed activation transaction, including event/audit.
        work.plans.activate(chain.plan, expected_revision=1, validation=PlanValidationResult())
        work.commit()
    chain.version = {"id": identity, "contentHash": reviewed.content_hash,
        "sourceHash": reviewed.source_hash, "reviewEvidenceHash": reviewed.review_evidence_hash}
    return pipeline(chain)


def inputs(chain, *, revision=None):
    target = datetime.combine(chain.now.date(), time(9, 35), chain.now.tzinfo)
    with chain.plans._unit_of_work() as work:
        minutes = work.history.list_minutes(chain.plan.symbol,
            start=target.replace(minute=31), end=target)
        calendar = work.references.list_trading_days(chain.plan.market,
            chain.now.date(), chain.now.date())
    bar = aggregate_five_minute_bar(minutes, bucket_end=target, is_open=True) if minutes else None
    quote = DailyExecutionQuote(symbol=chain.plan.symbol, price_fen=2430, quote_at=chain.now,
        available_at=chain.now, evaluated_at=chain.now, tradable=True,
        special_state_verified=True, liquidity_available=True)
    return DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=None, series=None,
        session_dates=(chain.now.date(),), suspended_dates=(), quote=quote, data_blockers=(),
        minute_target=target if bar else None, minute_prefix=minutes,
        five_minute_bars=(bar,) if bar else (), trading_calendar=calendar,
        buy_suspension_revision=revision)


@pytest.mark.parametrize("breach", [False, True])
def test_same_bar_guard_precedes_buy_and_records_real_suppression(chain, breach):
    owner = prepare(chain)
    owner.daily_evaluations._buy_suspension_current = owner.buy_suspension_current
    if breach:
        chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
    row = advance(chain)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    if not breach:
        assert result.snapshot["signals"][0]["executable_qty"] == 100
        assert "buy_suspension_blocker" not in result.snapshot
    else:
        assert result.snapshot["signals"] == []
        assert result.event_ids == ()
        snapshot = DailyEvaluationState.model_validate(result.snapshot)
        assert snapshot.buy_suspension_blocker == "BUY_SUSPENSION_LATCHED"
        assert snapshot.buy_suspension_owner_plan_version_id == row["state"].owner_plan_version_id
        assert snapshot.buy_suspension_revision == row["revision"]
        assert snapshot.buy_suspension_target == row["state"].target
        assert snapshot.buy_suspension_skipped_rules == (chain.plan.ordinary_rules[0].rule_id,)
        assert snapshot.ordinary_evaluations is None


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_missing_record_is_unknown_buy_but_preserves_independent_sell(chain, side):
    owner = prepare(chain, side=side)
    owner.daily_evaluations._buy_suspension_current = owner.buy_suspension_current
    # No acquisition and no guard row: absence is not a whole-cycle exception.
    result = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=inputs(chain))
    assert result.snapshot["buy_suspension_revision"] is None
    assert result.snapshot["buy_suspension_blocker"] == "BUY_SUSPENSION_UNVERIFIED"
    if side == "BUY":
        assert result.snapshot["signals"] == []
    else:
        # Supply verified minute inputs after acquisition, then remove only the guard.
        row = advance(chain)
        captured = inputs(chain, revision=row["revision"])
        from trade_plan_monitor.state.daily_models import DailyRecord
        with chain.plans._unit_of_work() as work:
            work.daily.session.delete(work.daily.session.get(DailyRecord, row["id"]))
            work.commit()
        result = owner.daily_evaluations.run_inputs(plan=chain.plan,
            inputs=captured.model_copy(update={"buy_suspension_revision": None}))
        assert result.snapshot["signals"][0]["side"] == "SELL"
        assert result.snapshot["signals"][0]["executable_qty"] == 100


def test_latch_invalidates_old_ready_without_consuming_or_erasing_history(chain):
    owner = prepare(chain)
    owner.daily_evaluations._buy_suspension_current = owner.buy_suspension_current
    row = advance(chain)
    first = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    signal = first.snapshot["signals"][0]
    assert signal["state"] == "READY"
    chain.sdk.breach = row["state"].target
    # Accept the correction through the actual storage seam used by T06.
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        old = work.history.list_minutes(chain.plan.symbol, start=chain.sdk.breach,
            end=chain.sdk.breach)[0]
        work.history.upsert_minutes((old.model_copy(update={"close_fen": 2419,
            "received_at": chain.now}),))
        work.commit()
    row = advance(chain)
    assert row["state"].outcome == "LATCHED"
    second = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    assert second.snapshot["signals"][0]["state"] == "INVALIDATED"
    assert second.snapshot["signals"][0]["simulated_qty"] == 0
    assert guard_row(chain)["state"].trigger is not None


def test_guarded_cache_is_revoked_and_buy_condition_is_never_called_after_breach(
    chain, monkeypatch,
):
    from tests.integration.test_plan_buy_suspension_simulation import breach

    from trade_plan_monitor.decision import unified_lifecycle

    owner = prepare(chain)
    row = advance(chain)
    captured = inputs(chain, revision=row["revision"])
    first = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured)
    assert first.snapshot["signals"][0]["executable_qty"] == 100
    assert owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured).duplicate
    breach(chain)

    def forbidden(*args, **kwargs):
        pytest.fail("BUY condition was evaluated after guard prohibition")

    monkeypatch.setattr(unified_lifecycle, "evaluate_unified_condition", forbidden)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=guard_row(chain)["revision"]))
    assert not result.duplicate
    assert result.snapshot["signals"][0]["executable_qty"] == 0
    assert result.snapshot["buy_suspension_blocker"] == "BUY_SUSPENSION_LATCHED"


def test_same_captured_inputs_cannot_reuse_cached_allow_after_actual_clock_target_moves(chain):
    owner = prepare(chain)
    row = advance(chain)
    captured = inputs(chain, revision=row["revision"])
    assert owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured).snapshot[
        "signals"][0]["executable_qty"] == 100
    assert owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured).duplicate
    chain.now += timedelta(minutes=5)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured)
    assert not result.duplicate
    assert result.snapshot["signals"][0]["executable_qty"] == 0
    assert result.snapshot["buy_suspension_target"] == chain.now.replace(
        minute=40, second=0, microsecond=0).isoformat()


def test_schema10_without_guard_field_still_requires_owned_runtime_admission(chain):
    from trade_plan_monitor.runtime.daily_service import _buy_suspension_status

    prepare(chain)
    retired = chain.plan.model_copy(update={"buy_suspension": None})
    with chain.plans._unit_of_work() as work:
        allowed, _, _ = _buy_suspension_status(work, retired, chain.now, None)
        assert not allowed


@pytest.mark.parametrize("future_close", [2435, 3000])
def test_production_and_engineering_share_literal_chronological_trace(
    chain, monkeypatch, future_close,
):
    """A03: actual SDK/SQL/runtime versus a chronological private transition.

    Independent fixture instances differ only after the first breach. No public
    replay runner, frozen format or precomputed production result is involved.
    """
    from decimal import Decimal

    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.decision.buy_suspension import (
        BuySuspensionBatch,
        transition_buy_suspension,
    )
    from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
    from trade_plan_monitor.state.activation_history import resolve_buy_suspension_context
    from trade_plan_monitor.state.daily_accounting import DailyAccounting
    from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState

    origin = chain.now.replace(hour=9, minute=30, second=0, microsecond=0)
    targets = [origin + timedelta(minutes=n) for n in (5, 10, 15, 20)]
    closes = dict(zip(targets, (2430, 2420, 2419, future_close), strict=True))
    native = chain.sdk.stk_mins

    def scheduled_minutes(**kwargs):
        frame = native(**kwargs)
        frame["close"] = [str(Decimal(closes.get(datetime.fromisoformat(t).replace(
            tzinfo=chain.now.tzinfo), 2430)) / 100) for t in frame["trade_time"]]
        frame["high"] = [str(max(Decimal(c), Decimal("24.30"))) for c in frame["close"]]
        frame["low"] = "24.19"
        return frame

    monkeypatch.setattr(chain.sdk, "stk_mins", scheduled_minutes)
    owner, saved = public_production_guard(chain)
    generation = owner.suspension_generation()
    with chain.plans._unit_of_work() as work:
        context = resolve_buy_suspension_context(work.plans, chain.plan.symbol)
        engine = DailyBuySuspensionState(symbol=chain.plan.symbol,
            owner_plan_version_id=saved["id"], content_hash=context.owner.content_hash,
            source_hash=context.owner.source_hash, review_id=context.owner.review_id,
            birth_activation_revision=context.birth_revision, definition=chain.plan.buy_suspension,
            target=targets[0], evaluated_at=chain.now)
    persisted, trace, ready_id, engineering_signal = {}, [], None, None
    for index, target in enumerate(targets):
        chain.now = target + timedelta(minutes=1)
        call_start = len(chain.sdk.calls)
        row = advance(chain)
        state = row["state"]
        with chain.plans._unit_of_work() as work:
            minutes = work.history.list_minutes(chain.plan.symbol,
                start=origin + timedelta(minutes=1), end=target)
            calendar = work.references.list_trading_days(chain.plan.market,
                target.date(), target.date())[0]
            for identity, payload in persisted.items():
                assert work.daily.get(identity)["payload"] == payload
            allowed = owner.buy_suspension_current(work, chain.plan,
                expected_revision=row["revision"])
            inventory = DailyAccounting(work.daily).snapshot(chain.plan.symbol, target.date())
        assert all(m.bar_end <= target for m in minutes)
        for name, command in chain.sdk.calls[call_start:]:
            if name == "stk_mins":
                assert datetime.fromisoformat(command["end_date"]).replace(
                    tzinfo=chain.now.tzinfo) <= target
        left = engine.coverage.through if engine.coverage else origin
        value = BuySuspensionBatch(start=left, through=target,
            minutes=tuple(m for m in minutes if left < m.bar_end <= target),
            calendar=calendar, generation=generation, basis=dict(
                source_contract="TUSHARE_STK_MINS_241_END_V1", trade_date=target.date(),
                anchor_date=target.date(), trade_date_factor=Decimal(chain.sdk.factor),
                anchor_factor=Decimal(chain.sdk.factor), verified_at=chain.now))
        engine = transition_buy_suspension(engine, target=target, evaluated_at=chain.now,
            generation=generation, batch=value)
        current_minutes = tuple(m for m in minutes if target - timedelta(minutes=5) < m.bar_end)
        bar = (aggregate_five_minute_bar(current_minutes, bucket_end=target, is_open=True)
               if len(current_minutes) == 5 else None)
        captured = inputs(chain, revision=row["revision"]).model_copy(update={
            "minute_target": target, "minute_prefix": current_minutes,
            "five_minute_bars": () if bar is None else (bar,)})
        result = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=captured)
        engineering_allowed = engine.outcome == "CLEAR_THROUGH_TARGET"
        confirmed = confirm_signal(chain.plan, chain.plan.ordinary_rules[0], series=None,
            facts=(), previous=() if engineering_signal is None else (engineering_signal,),
            session_dates=captured.session_dates, plan_version_id=saved["id"],
            review_id=engine.review_id, bars=captured.five_minute_bars, target=target,
            trading_calendar=captured.trading_calendar, buy_suspension_allowed=engineering_allowed)
        if confirmed is not None:
            engineering_signal = confirmed
        assert engineering_signal is not None
        engineering_signal = check_execution(chain.plan, engineering_signal,
            inventory=inventory, quote_fen=captured.quote.price_fen, evaluated_at=chain.now,
            tradable=True, risk_blocked=False, risk_known=True,
            buy_suspension_allowed=engineering_allowed,
            buy_suspension_latched=engine.outcome == "LATCHED")
        signals = result.snapshot["signals"]
        quantity = sum(s["executable_qty"] for s in signals if s["side"] == "BUY")
        actual = (target, state.outcome,
            None if state.trigger is None else state.trigger.bar_end,
            None if state.trigger is None else state.trigger.close_fen, allowed, quantity)
        replay = (target, engine.outcome,
            None if engine.trigger is None else engine.trigger.bar_end,
            None if engine.trigger is None else engine.trigger.close_fen,
            engineering_allowed, engineering_signal["executable_qty"])
        expected = (target, "CLEAR_THROUGH_TARGET" if index < 2 else "LATCHED",
            None if index < 2 else targets[2], None if index < 2 else 2419,
            index < 2, 100 if index < 2 else 0)
        assert actual == replay == expected
        trace.append(actual)
        if index < 2:
            assert bar.close_fen == closes[target] and bar.low_fen == 2419
            ready_id = signals[0]["signal_id"]
        else:
            assert result.snapshot.get("ordinary_evaluations") is None
            with chain.plans._unit_of_work() as work:
                old_ready = work.daily.get(ready_id)["payload"]
                assert old_ready["state"] == "INVALIDATED" and old_ready["simulated_qty"] == 0
                assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
        with chain.plans._unit_of_work() as work:
            persisted[result.evaluation_id] = work.daily.get(result.evaluation_id)["payload"]
    assert [point[-1] for point in trace] == [100, 100, 0, 0]
    with chain.plans._unit_of_work() as work:
        for identity, payload in persisted.items():
            assert work.daily.get(identity)["payload"] == payload


def test_real_run_target_prepares_guard_before_same_bar_buy_and_invalidates_ready(
    chain, monkeypatch,
):
    from functools import partial

    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.decision import unified_lifecycle

    owner, _ = public_production_guard(chain)
    first_guard = advance(chain)
    first = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=first_guard["revision"]))
    ready = first.snapshot["signals"][0]
    assert ready["state"] == "READY" and ready["executable_qty"] == 100
    target = first_guard["state"].target + timedelta(minutes=5)
    chain.now = target + timedelta(minutes=1)
    chain.sdk.breach = target
    # Acquire the completed same-bar market data through the real bounded SDK
    # adapter, without advancing or creating the guard. This is the scheduler's
    # accepted market-storage seam, not a fabricated guard outcome.
    window = chain.client.portal.call(partial(owner.recovery.buy_suspension_window,
        owner.suspension_history, symbol=chain.plan.symbol, through=target,
        current=lambda: True, source_key=owner.suspension_generation()))
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(window.bars)
        work.commit()
        assert work.daily.get_buy_suspension(symbol=chain.plan.symbol,
            owner_plan_version_id=chain.version["id"])["state"].trigger is None
    order = []
    native_guard, native_prepare = owner.advance_buy_suspension, owner.daily_evaluations._prepare

    async def guarded(*args, **kwargs):
        order.append("guard-start")
        result = await native_guard(*args, **kwargs)
        assert result["state"].trigger.bar_end == target
        order.append("guard-latched")
        return result

    async def prepared(*args, **kwargs):
        order.append("prepare-start")
        result = await native_prepare(*args, **kwargs)
        assert result.five_minute_bars[-1].close_fen == 2419
        assert result.minute_target == target
        order.append("prepare-complete")
        return result

    def forbidden(*args, **kwargs):
        pytest.fail("same-bar BUY condition ran after production guard latched")

    monkeypatch.setattr(owner, "advance_buy_suspension", guarded)
    monkeypatch.setattr(owner.daily_evaluations, "_prepare", prepared)
    monkeypatch.setattr(unified_lifecycle, "evaluate_unified_condition", forbidden)
    result = chain.client.portal.call(partial(owner.daily_evaluations.run_target,
        plan=chain.plan, evaluated_at=chain.now, minutes=window.bars))
    assert order == ["prepare-start", "guard-start", "guard-latched", "prepare-complete"]
    assert result.snapshot["buy_suspension_blocker"] == "BUY_SUSPENSION_LATCHED"
    signal = result.snapshot["signals"][0]
    assert signal["signal_id"] == ready["signal_id"]
    assert signal["state"] == "INVALIDATED" and signal["simulated_qty"] == 0
    assert signal["executable_qty"] == 0
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
        assert work.daily.get(first.evaluation_id)["payload"] == first.snapshot


def test_actual_realtime_deadline_does_not_yield_its_own_required_guard(chain, monkeypatch):
    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    owner, _ = public_production_guard(chain)
    native_minutes = chain.sdk._stock_minutes

    def consistent_minutes(name, kwargs):
        frame = native_minutes(name, kwargs)
        for index, stamp in frame["time"].items():
            end = (datetime.fromisoformat(stamp).replace(tzinfo=chain.now.tzinfo)
                   + timedelta(minutes=1))
            if end == chain.sdk.breach:
                frame.loc[index, "close"] = "24.19"
        return frame

    monkeypatch.setattr(chain.sdk, "_stock_minutes", consistent_minutes)
    row = advance(chain)
    assert row["state"].outcome == "CLEAR_THROUGH_TARGET"
    target = row["state"].target + timedelta(minutes=5)
    chain.now = target + timedelta(seconds=12)
    chain.sdk.breach = target
    deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=target.date(), bar_end=target, due_at=chain.now)
    chain.client.portal.call(chain.composition._runtime._execute_deadline, deadline)
    current = guard_row(chain)["state"]
    assert current.outcome == "LATCHED"
    assert current.trigger.bar_end == target
    assert current.trigger.close_fen == 2419
    assert not owner._running_deadline


def test_guard_yields_to_another_physically_active_live_request(chain):
    import asyncio
    from threading import Event

    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.runtime.request_control import TushareOperation

    owner, _ = public_production_guard(chain)
    entered, release = Event(), Event()

    def another_live():
        entered.set()
        assert release.wait(5)
        return "live-completed"

    async def scenario():
        task = asyncio.create_task(owner._controller.execute(
            TushareOperation.REALTIME_MINUTES, another_live, work_key="a03-other-live"))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert owner._controller.active_count == 1
            before = len(chain.sdk.calls)
            assert await owner.advance_buy_suspension(chain.plan) is None
            assert len(chain.sdk.calls) == before
            assert owner._controller.active_count == 1
        finally:
            release.set()
            assert await task == "live-completed"
        assert owner._controller.active_count == 0

    chain.client.portal.call(scenario)


def test_guard_keeps_next_realtime_deadline_reservation(chain):
    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    owner, _ = public_production_guard(chain)
    owner._gap_repair_due_at = chain.now + timedelta(seconds=1)
    before = len(chain.sdk.calls)
    assert advance(chain) is None
    assert len(chain.sdk.calls) == before


def test_real_deadline_reserves_next_live_duty_and_yields_guard(chain):
    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    owner, _ = public_production_guard(chain)
    row = advance(chain)
    target = row["state"].target + timedelta(minutes=5)
    # A late current duty is within one second of its next native minute duty.
    chain.now = target + timedelta(minutes=1, seconds=11)
    chain.sdk.breach = target
    before = sum(name == "stk_mins" for name, _ in chain.sdk.calls)
    deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=target.date(), bar_end=target, due_at=target + timedelta(seconds=12))
    chain.client.portal.call(chain.composition._runtime._execute_deadline, deadline)
    assert sum(name == "stk_mins" for name, _ in chain.sdk.calls) == before
    assert guard_row(chain)["state"].trigger is None
    assert owner._gap_repair_due_at is None


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_real_deadline_clears_next_live_reservation_on_failure(chain, monkeypatch, failure):
    import asyncio
    from concurrent.futures import CancelledError

    from tests.integration.test_plan_buy_suspension_activation import public_production_guard

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    owner, _ = public_production_guard(chain)
    target = chain.now.replace(minute=40, second=0, microsecond=0)
    chain.now = target + timedelta(seconds=12)
    deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=target.date(), bar_end=target, due_at=chain.now)
    raised = asyncio.CancelledError if failure == "cancel" else RuntimeError

    async def fail(_deadline):
        assert owner._gap_repair_due_at == target + timedelta(minutes=1, seconds=12)
        raise raised("fixture duty interruption")

    monkeypatch.setattr(owner.coordinator, "run_deadline", fail)
    with pytest.raises(CancelledError if failure == "cancel" else raised):
        chain.client.portal.call(chain.composition._runtime._execute_deadline, deadline)
    assert owner._gap_repair_due_at is None and not owner._running_deadline
