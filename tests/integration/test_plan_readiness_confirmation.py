"""Calendar events and expiry from actual prior results; no future evaluation is invented."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.integration.test_plan_rule_evaluation_output import mixed_current as _mixed_current
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.runtime import production
from trade_plan_monitor.runtime.progress import RuntimeProgress
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

mixed_current = _mixed_current


class OwnedProgress:
    """Use the real progress tracker only around actual pipeline units."""

    def __init__(self, generation, clock):
        self.tracker = RuntimeProgress(generation, clock=clock.now,
                                      monotonic=lambda: clock.now().timestamp())

    def begin_progress_step(self, *, timeout_seconds):
        return self.tracker.begin_step(timeout_seconds=timeout_seconds)

    def begin_progress_step_at(self, *, deadline):
        return self.tracker.begin_step_at(deadline=deadline)

    def complete_progress_step(self, token, *, next_wake_at):
        return self.tracker.complete_step(token, next_wake_at=next_wake_at)

    def progress_monotonic_now(self):
        return self.tracker.monotonic_now()


@pytest.fixture(autouse=True)
def actual_progress(monkeypatch, request):
    from tests.integration import current_pipeline_fixture

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    native_plan = current_pipeline_fixture.current_three_rule_plan

    def simple_plan(**kwargs):
        raw = native_plan(**kwargs).model_dump(mode="json")
        if getattr(request, "param", None) != "complex-daily":
            for rule in raw["ordinary_rules"]:
                rule["independent_signal"] = {"mode": "ONCE_PER_RULE"}
        if getattr(request, "param", None) == "expired-daily":
            raw["ordinary_rules"][0]["validity"] = {
                "mode": "DATE_RANGE", "start_date": "2026-09-11", "end_date": "2026-09-11"}
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(current_pipeline_fixture, "current_three_rule_plan", simple_plan)
    factory = production.ProductionMonitorPipeline
    trackers = []

    def build(**kwargs):
        owned = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        kwargs["progress_owner"] = owned
        trackers.append(owned.tracker)
        return factory(**kwargs)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", build)
    return trackers


def bind_owner(case, tracker):
    def owner():
        token, configuration, plans = case.pipeline.runtime_status_snapshot()
        return replace(case.current[0], token=token, configuration_revision=configuration,
                       plans=plans, progress=tracker.snapshot())

    case.owner = owner
    case.reader = RuntimeStatusReadService(case.sessions, owner, clock=case.pipeline._clock.now)
    return case


@pytest.fixture
def minute_case(tmp_path, monkeypatch, actual_progress):
    case = bind_owner(_current_status(tmp_path, monkeypatch), actual_progress[0])
    try:
        yield case
    finally:
        case.close()


@pytest.fixture
def daily_case(mixed_current, actual_progress):
    return bind_owner(mixed_current, actual_progress[0])


def read(case):
    return asyncio.run(case.reader.get_plan_readiness(
        version_id=case.result.snapshot["plan_version_id"]))


def maintain(case):
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))


def test_complete_current_false_keeps_its_actual_result_and_bounded_context(minute_case):
    case = minute_case
    assessed = read(case)
    rule = next(r for r in assessed.rules if r.facts.owner_id == "sell-100")
    assert rule.state == "CONDITION_FALSE"
    assert rule.facts.expected_confirmation is None
    assert rule.facts.observation.expires_at == min(
        case.owner().progress.progress_due_at,
        case.result.snapshot["minute_target"] and case.now.replace(second=0, microsecond=0)
        + timedelta(seconds=90))
    assert assessed.fresh_until is None  # notification is still unverified


def test_daily_future_event_preserves_all_prior_leaves_and_exact_target(daily_case):
    case = daily_case
    assessed = read(case)
    rule = assessed.rules[0]
    assert rule.state == "WAITING_OFFICIAL_CONFIRMATION"
    wait = rule.facts.expected_confirmation
    assert wait.target.trade_date == case.now.date()
    assert wait.expected_at == case.now.replace(hour=15, minute=0, second=0, microsecond=0)
    assert rule.facts.evaluated_target.trade_date < wait.target.trade_date
    assert rule.facts.root_outcome == "UNSATISFIED"
    assert len(rule.facts.leaves) == 1
    assert rule.facts.leaves[0].reason == "EXPECTED_CONFIRMATION"
    assert assessed.fresh_until is None


@pytest.mark.parametrize("actual_progress", ["complex-daily"], indirect=True)
@pytest.mark.parametrize("corrected", [False, True])
def test_current_complex_daily_comparison_keeps_result_without_future_wait(daily_case, corrected):
    from trade_plan_monitor.runtime.status_authority import (
        condition_confirmation_inputs,
        condition_daily_admission_matches,
    )

    case = daily_case
    assert case.plan.schema_version == 5
    assert case.plan.ordinary_rules[0].independent_signal.mode == "REVIEWED_INDEPENDENT_EVENT"
    snapshot = case.result.snapshot
    if corrected:
        inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
        day = inputs.series.bars[-1].trade_date
        case.daily_source.official_closes[day] = "35.00"
        admitted = asyncio.run(case.pipeline.prepare_daily_inputs(
            case.plan, case.now, day, inputs.minute_prefix))
        fresh = case.pipeline.daily_evaluations.run_inputs(
            plan=case.plan, inputs=admitted, expected_activation_revision=1)
        assert not fresh.duplicate
        snapshot = fresh.snapshot
    owner = case.owner().plans[0]
    assert condition_daily_admission_matches(proof=owner.completion, snapshot=snapshot,
        admission=owner.daily_admission, now=case.now)
    actual = snapshot["ordinary_evaluations"][0]
    assert any(
        signal["rule_id"] == actual["rule_id"] for signal in snapshot["signals"]
    ) == corrected
    with case.sessions() as session, session.begin():
        future = condition_confirmation_inputs(session, plan=case.plan, now=case.now)[0]
    assert future.trade_date == case.now.date()
    assessed = read(case)
    rule = assessed.rules[0]
    assert rule.state == ("CONDITION_TRUE" if corrected else "CONDITION_FALSE")
    assert rule.facts.root_outcome == ("SATISFIED" if corrected else "UNSATISFIED")
    assert rule.facts.root_outcome == actual["evidence"]["outcome"]
    assert rule.facts.expected_target == rule.facts.evaluated_target
    assert str(rule.facts.evaluated_target.trade_date) == actual["target"]["trade_date"]
    assert rule.facts.evaluated_target.trade_date < future.trade_date
    assert rule.facts.observation.availability == "CURRENT"
    assert rule.facts.expected_confirmation is None
    assert next(a for a in assessed.axes if a.axis == "DATA_EVALUATION").state == "PASS"


@pytest.mark.parametrize("actual_progress", ["complex-daily"], indirect=True)
def test_expired_complex_daily_comparison_does_not_gain_future_wait(daily_case):
    case = daily_case
    prior = case.result.snapshot["ordinary_evaluations"][0]
    assert case.plan.ordinary_rules[0].independent_signal.mode == "REVIEWED_INDEPENDENT_EVENT"
    assert prior["evidence"]["outcome"] == "UNSATISFIED"
    case.pipeline._clock.current += timedelta(seconds=91)
    maintain(case)
    rule = read(case).rules[0]
    assert rule.state == "UNKNOWN"
    assert rule.facts.observation.availability == "CACHED"
    assert rule.facts.expected_confirmation is None
    assert rule.facts.root_outcome == prior["evidence"]["outcome"]
    assert str(rule.facts.evaluated_target.trade_date) == prior["target"]["trade_date"]


@pytest.mark.parametrize("past_present", [True, False])
def test_minute_future_wait_requires_already_completed_partial_minutes(minute_case, past_present):
    from trade_plan_monitor.market_data.models import MinuteBar

    case = minute_case
    case.pipeline._clock.current += timedelta(seconds=91)
    if past_present:
        old = case.result.snapshot["minute_prefix"][-1]
        bar = MinuteBar.model_validate_json(json.dumps(old))
        case.pipeline.persist_minutes((bar.model_copy(update={
            "bar_end": bar.bar_end + timedelta(minutes=1),
            "received_at": case.pipeline._clock.now()}),))
    maintain(case)  # Real bounded maintenance completes progress; a timer does not.
    assessed = read(case)
    rule = next(r for r in assessed.rules if r.facts.owner_id == "sell-100")
    assert rule.state == ("WAITING_OFFICIAL_CONFIRMATION" if past_present else "MISSING_INPUT")
    assert len(rule.facts.leaves) == 1
    assert rule.facts.evaluated_target.bucket_end == case.deadline.bar_end
    if past_present:
        assert rule.facts.expected_confirmation.target.bucket_end == (
            case.deadline.bar_end + timedelta(minutes=5))
    else:
        assert rule.facts.expected_confirmation is None
        assert rule.facts.leaves[0].reason == "MISSING_DATA"


def test_actual_new_activation_has_all_leaves_before_its_first_evaluation(minute_case, tmp_path):
    from tests.integration.test_daily_plan_chain import Chain

    from trade_plan_monitor.domain.unified_plan_models import condition_leaves

    case = minute_case
    chain = Chain(tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    with chain.client:
        chain.activate(version=2, activation_revision=1)
    version_id = chain.version["id"]
    assert case.owner().plans[0].completion is None
    assessed = asyncio.run(case.reader.get_plan_readiness(version_id=version_id))
    for rule in assessed.rules:
        native = next(r for r in (*chain.plan.ordinary_rules, *chain.plan.alert_rules)
                      if r.rule_id == rule.facts.owner_id)
        assert rule.state == "AWAITING_FIRST_EVALUATION"
        assert len(rule.facts.leaves) == len(tuple(condition_leaves(native.condition)))
        assert all(leaf.state == "UNKNOWN" for leaf in rule.facts.leaves)
        assert rule.facts.evaluated_at is None and rule.facts.root_outcome is None
        assert rule.facts.expected_confirmation is None


@pytest.mark.parametrize("changed", ["daily", "calendar", "calendar-absent", "owner"])
def test_future_daily_event_never_hides_a_changed_prior_dependency(daily_case, changed):
    from trade_plan_monitor.market_data.models import TradingDay

    case = daily_case
    if changed == "daily":
        inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
        day = inputs.series.bars[-1].trade_date
        case.daily_source.official_closes[day] = "35.00"
        asyncio.run(case.pipeline.prepare_daily_inputs(
            case.plan, case.now, day, inputs.minute_prefix))
    elif changed == "calendar":
        with case.work() as work:
            work.references.upsert_trading_days((TradingDay(exchange=case.plan.market,
                cal_date=case.now.date(), is_open=False,
                previous_trade_date=case.now.date() - timedelta(days=3)),))
            work.commit()
    elif changed == "calendar-absent":
        from sqlalchemy import delete

        from trade_plan_monitor.state.models import TradingCalendar

        with case.work() as work:
            work.daily.session.execute(delete(TradingCalendar).where(
                TradingCalendar.exchange == case.plan.market,
                TradingCalendar.cal_date == case.now.date()))
            work.commit()
    else:
        case.pipeline._status_progress_owner.tracker.stop()
    assessed = read(case)
    assert assessed.rules[0].state == "UNKNOWN"
    assert assessed.rules[0].facts.expected_confirmation is None
    assert len(assessed.rules[0].facts.leaves) == 1


@pytest.mark.parametrize("boundary", ["due", "lunch", "close", "midnight", "holiday"])
def test_calendar_boundary_without_a_new_prior_proof_cannot_roll_wait_forward(
    minute_case, boundary,
):
    case = minute_case
    starts = {
        "due": case.deadline.bar_end + timedelta(minutes=5),
        "lunch": case.now.replace(hour=12, minute=0),
        "close": case.now.replace(hour=15, minute=0),
        "midnight": case.now.replace(hour=0, minute=0) + timedelta(days=1),
        "holiday": case.now + timedelta(days=6),
    }
    case.pipeline._clock.current = starts[boundary]
    maintain(case)
    assessed = read(case)
    assert all(rule.facts.expected_confirmation is None for rule in assessed.rules)
    assert not any(rule.state == "WAITING_OFFICIAL_CONFIRMATION" for rule in assessed.rules)
    assert assessed.fresh_until is None


def test_real_missing_human_leaf_is_not_relabelled_as_future_wait(
    tmp_path, monkeypatch, actual_progress,
):
    from tests.integration.current_pipeline_fixture import current_three_rule_plan

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = current_three_rule_plan().model_dump(mode="json")
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0]["condition"] = {"type": "ALL", "conditions": [
        {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 900},
        {"type": "REVIEWED_FACT", "fact_kind": "TECHNICAL", "validity_scope": "TRADE_DATE",
         "evidence_requirement": "Human verifies the completed five-minute pattern"}]}
    case = _current_status(tmp_path, monkeypatch, plan=UnifiedTradePlan.model_validate(raw))
    bind_owner(case, actual_progress[0])
    try:
        assessed = read(case)
        first = assessed.rules[0]
        assert first.facts.root_outcome == "UNSATISFIED"
        assert first.state == "MISSING_INPUT"
        assert first.reason == "HUMAN_EVIDENCE_REQUIRED"
        assert len(first.facts.leaves) == 2
        assert first.facts.expected_confirmation is None
    finally:
        case.close()


@pytest.mark.parametrize("gate", ["once", "predecessor"])
def test_real_gate_early_return_does_not_become_a_calendar_wait(
    tmp_path, monkeypatch, actual_progress, gate,
):
    from tests.integration.current_pipeline_fixture import current_three_rule_plan

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = current_three_rule_plan().model_dump(mode="json")
    identity, leaves = ("low-buy", 2) if gate == "once" else ("sell-100", 1)
    if gate == "predecessor":
        raw["ordinary_rules"][1]["independent_signal"] = {
            "mode": "AFTER_RULE_COMPLETED", "prior_rule_id": "low-buy"}
    case = _current_status(tmp_path, monkeypatch, plan=UnifiedTradePlan.model_validate(raw))
    bind_owner(case, actual_progress[0])
    try:
        case.pipeline._clock.current += timedelta(seconds=1)
        inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
        fresh = case.pipeline.daily_evaluations.run_inputs(plan=case.plan,
            inputs=inputs.model_copy(update={"evaluated_at": case.pipeline._clock.now()}),
            expected_activation_revision=1)
        assert not fresh.duplicate
        assert all(row["rule_id"] != identity
                   for row in fresh.snapshot.get("ordinary_evaluations", ()))
        assessed = read(case)
        buy = next(rule for rule in assessed.rules if rule.facts.owner_id == identity)
        assert buy.state == "UNKNOWN"
        assert buy.facts.expected_confirmation is None
        assert len(buy.facts.leaves) == leaves
    finally:
        case.close()


@pytest.mark.parametrize("actual_progress", ["expired-daily"], indirect=True)
def test_future_event_outside_native_rule_validity_keeps_prior_record(daily_case):
    case = daily_case
    prior = case.result.snapshot["ordinary_evaluations"][0]
    assert prior["evidence"]["outcome"] == "UNSATISFIED"
    rule = read(case).rules[0]
    assert rule.state == "UNKNOWN"
    assert rule.facts.expected_confirmation is None
    assert rule.facts.root_outcome == prior["evidence"]["outcome"]
    assert rule.facts.evaluated_at == case.now
    assert len(rule.facts.leaves) == 1


@pytest.mark.parametrize("mixed_current", ["daily-reset"], indirect=True)
def test_reset_path_with_prior_false_does_not_claim_future_admission(daily_case):
    case = daily_case
    case.pipeline._clock.current += timedelta(seconds=91)
    prior = case.result.snapshot["ordinary_evaluations"][0]
    assert prior["evidence"]["outcome"] == "UNSATISFIED"
    maintain(case)
    assessed = read(case)
    rule = assessed.rules[0]
    assert rule.state == "UNKNOWN"
    assert rule.facts.expected_confirmation is None
    assert rule.facts.root_outcome == "UNSATISFIED"
    assert rule.facts.evaluated_at == case.now


def test_get_does_not_renew_context_or_acquire_or_write(minute_case, monkeypatch):
    from sqlalchemy import event

    case = minute_case
    first = read(case)
    old_deadline = first.rules[1].facts.observation.expires_at

    def forbidden(*args, **kwargs):
        pytest.fail("readiness GET cannot acquire or evaluate")

    monkeypatch.setattr(case.pipeline, "prepare_daily_inputs", forbidden)
    monkeypatch.setattr(case.sdk, "daily", forbidden, raising=False)
    monkeypatch.setattr(case.sdk, "adj_factor", forbidden, raising=False)

    def readonly(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE"}

    event.listen(case.engine, "before_cursor_execute", readonly)
    try:
        case.pipeline._clock.current += timedelta(seconds=1)
        second = read(case)
        assert second.rules[1].facts.observation.expires_at == old_deadline
        case.pipeline._clock.current = old_deadline
        expired = read(case)
        assert expired.rules[1].state == "UNKNOWN"
        assert expired.rules[1].facts.expected_confirmation is None
        assert expired.fresh_until is None
    finally:
        event.remove(case.engine, "before_cursor_execute", readonly)
