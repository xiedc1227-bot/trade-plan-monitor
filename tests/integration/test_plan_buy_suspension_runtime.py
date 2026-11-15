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

    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
    from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
    from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanVersion
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
        # Only the isolated fixture seeds activation. Production Schema10 stays rejected.
        for model in (ActivePlan, PlanActivationState):
            active = work.daily.session.get(model, chain.plan.symbol)
            active.plan_version_id, active.revision = identity, 2
        work.daily.session.get(PlanVersion, identity).status = "ACTIVE"
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
