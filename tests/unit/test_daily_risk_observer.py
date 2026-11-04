"""Observe only real native risk comparisons and new-cause branches."""

from copy import deepcopy
from datetime import date
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.decision import daily_risk
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan

DAYS = tuple(date(2026, 9, day) for day in (21, 22, 23, 24))


def run(previous=(), *, day=DAYS[0], close=3800, plan=None, **changes):
    arguments = dict(
        previous=previous,
        close_date=day,
        close_fen=close,
        basis_id="synthetic",
        session_dates=DAYS,
        suspended_dates=(),
        facts=(),
    )
    arguments.update(changes)
    return daily_risk.advance_daily_risks(
        plan or DailyTradePlan.model_validate(synthetic_plan_payload()), **arguments
    )


def ordinary(rows):
    return next(row for row in rows if row["kind"] == "ORDINARY_TECHNICAL")


def test_first_breach_preserves_frozen_return_and_original_call_counts(monkeypatch):
    calls = []
    compare, next_session = daily_risk.compare, daily_risk.next_session

    def compared(*args):
        calls.append(("compare", args))
        return compare(*args)

    def next_day(*args):
        calls.append(("next_session", args))
        return next_session(*args)

    monkeypatch.setattr(daily_risk, "compare", compared)
    monkeypatch.setattr(daily_risk, "next_session", next_day)
    original = run()
    expected_calls = list(calls)
    calls.clear()
    observations, births = [], []
    observed = run(_evaluation_observer=observations.append, _birth_observer=births.append)
    assert observed == original
    assert canonical(observed) == canonical(original)
    assert sha256(canonical(observed).encode()).hexdigest() == (
        "c106aea505446bab5dd4a0a9bcba7ff23ed2056027ffb5f25f406eba24e8141a"
    )
    assert calls == expected_calls
    assert [name for name, _ in calls] == ["compare", "next_session"]
    assert len(observations) == len(births) == 1
    fact = observations[0]
    assert fact.risk_identity == "ORDINARY_TECHNICAL" and fact.kind == "ORDINARY_TECHNICAL"
    assert (fact.status_before, fact.status_after) == ("CLEAR", "PENDING")
    assert fact.close_date == DAYS[0] and fact.close_fen == 3800
    assert fact.risk_line_fen == 3818 and fact.risk_comparison == "LT" and fact.below is True
    assert fact.current_basis_id == "synthetic" and fact.latched_basis_id is None
    assert fact.breach_trade_date_before is None and fact.second_close_date_before is None
    assert fact.expected_second_close_date is None
    assert fact.breach_trade_date_after == DAYS[0] and fact.second_close_date_after == DAYS[1]
    assert fact.confirmation_close_used is False and fact.blockers == ()
    assert births[0].status_before == "CLEAR" and births[0].status_after == "PENDING"
    assert births[0].close_date == DAYS[0] and births[0].risk_identity == fact.risk_identity
    with pytest.raises(ValidationError):
        fact.status_after = "CLEAR"
    with pytest.raises(ValidationError):
        births[0].close_date = DAYS[1]
    ordinary(observed)["blockers"].append("changed later")
    assert fact.blockers == ()


@pytest.mark.parametrize(
    "close,status,below", [(3800, "CONFIRMED", True), (4100, "OBSERVATION", False)]
)
def test_actual_second_close_records_true_or_false_without_rebirthing(close, status, below):
    previous = run()
    ordinary(previous)["origin_evaluation_id"] = "original-evaluation"
    saved = deepcopy(previous)
    observations, births = [], []
    result = run(
        previous,
        day=DAYS[1],
        close=close,
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    assert result == run(previous, day=DAYS[1], close=close) and previous == saved
    fact = observations[0]
    assert (fact.status_before, fact.status_after, fact.below) == ("PENDING", status, below)
    assert fact.confirmation_close_used is True and fact.expected_second_close_date == DAYS[1]
    assert fact.latched_basis_id == fact.current_basis_id == "synthetic"
    assert fact.breach_trade_date_before == fact.breach_trade_date_after == DAYS[0]
    assert fact.second_close_date_before == fact.second_close_date_after == DAYS[1]
    assert ordinary(result)["origin_evaluation_id"] == "original-evaluation" and births == []


def test_early_nonbreach_is_not_a_completed_second_close_false():
    observations, births = [], []
    result = run(
        run(), close=4100, _evaluation_observer=observations.append, _birth_observer=births.append
    )
    assert ordinary(result)["status"] == "PENDING"
    assert observations[0].below is False
    assert observations[0].confirmation_close_used is False
    assert observations[0].expected_second_close_date == DAYS[1] and births == []
    with pytest.raises(ValidationError):
        observations[0].model_copy(update={"confirmation_close_used": True})
    with pytest.raises(ValidationError):
        observations[0].model_copy(update={"below": "false"})


@pytest.mark.parametrize(
    "policy,status", [("RESUME_FIRST_CLOSE", "CONFIRMED"), ("RESTART_ADJACENT_PAIR", "PENDING")]
)
def test_real_resumption_preserves_original_confirmation_and_restart(policy, status):
    raw = synthetic_plan_payload()
    raw["risk_branches"][0]["suspension_confirmation_policy"] = policy
    plan = DailyTradePlan.model_validate(raw)
    pending = run(plan=plan, suspended_dates=(DAYS[1],))
    observations, births = [], []
    result = run(
        pending,
        day=DAYS[2],
        plan=plan,
        suspended_dates=(DAYS[1],),
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    assert result == run(pending, day=DAYS[2], plan=plan, suspended_dates=(DAYS[1],))
    fact = observations[0]
    assert fact.status_after == status and fact.confirmation_close_used is True
    assert fact.expected_second_close_date == DAYS[1]
    assert fact.breach_trade_date_after == (DAYS[2] if status == "PENDING" else DAYS[0])
    assert fact.second_close_date_after == (DAYS[3] if status == "PENDING" else DAYS[1])
    assert births == []


def test_basis_mismatch_retains_the_native_blocker_without_claiming_a_pair_result():
    observations, births = [], []
    result = run(
        run(),
        day=DAYS[1],
        basis_id="changed-basis",
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    fact = observations[0]
    assert fact.below is True and fact.confirmation_close_used is False
    assert fact.latched_basis_id == "synthetic" and fact.current_basis_id == "changed-basis"
    assert fact.blockers == ("PERSISTED_RISK_BASIS_EQUIVALENCE_REQUIRED",)
    assert ordinary(result)["status"] == "PENDING" and births == []


@pytest.mark.parametrize(
    "skip",
    ["confirmed", "fulfilled", "disabled", "before-start", "cutover", "no-close", "no-price"],
)
def test_skipped_native_branches_create_neither_current_comparison_nor_birth(skip):
    previous, arguments = (), {}
    if skip in {"confirmed", "fulfilled"}:
        previous = run(run(), day=DAYS[1])
        if skip == "fulfilled":
            ordinary(previous).update(
                status="FULFILLED", cause_cutover_at="2026-09-22T15:00:00+08:00"
            )
        arguments["day"] = DAYS[1]
    elif skip == "disabled":
        arguments["allow_new_causes"] = False
    elif skip == "before-start":
        arguments["effective_start_date"] = DAYS[1]
    elif skip == "cutover":
        previous = run()
        ordinary(previous)["cause_cutover_at"] = "2026-09-21T15:00:00+08:00"
    elif skip == "no-close":
        arguments["day"] = None
    else:
        arguments["close"] = None
    observations, births = [], []
    result = run(
        previous,
        **arguments,
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    assert result == run(previous, **arguments)
    assert observations == births == []


def test_observation_reentry_keeps_the_original_cause_and_does_not_emit_a_birth():
    previous = run(run(), day=DAYS[1], close=4100)
    ordinary(previous)["origin_evaluation_id"] = "first-cause-evaluation"
    observations, births = [], []
    result = run(
        previous,
        day=DAYS[2],
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    assert (observations[0].status_before, observations[0].status_after) == (
        "OBSERVATION",
        "PENDING",
    )
    assert ordinary(result)["origin_evaluation_id"] == "first-cause-evaluation" and births == []


def test_fulfilled_cutover_creates_a_birth_only_after_the_actual_new_cause_reset():
    previous = run(run(), day=DAYS[1])
    ordinary(previous).update(
        status="FULFILLED",
        cause_cutover_at="2026-09-22T15:00:00+08:00",
        origin_evaluation_id="old-cause-evaluation",
    )
    births = []
    result = run(previous, day=DAYS[2], _birth_observer=births.append)
    assert len(births) == 1 and births[0].status_before == "CLEAR"
    assert births[0].status_after == "PENDING" and births[0].close_date == DAYS[2]
    assert ordinary(result)["status"] == "PENDING"
    assert "origin_evaluation_id" not in ordinary(result)  # No producer assignment in this slice.


@pytest.mark.parametrize("before,birth_count", [("CLEAR", 1), ("OBSERVATION", 0)])
def test_severe_birth_comes_from_the_actual_clear_confirmation_branch(before, birth_count):
    previous = run(close=4100)
    severe = next(row for row in previous if row["kind"] == "SEVERE_TECHNICAL")
    severe["status"] = before
    facts = tuple(
        dict(id=kind, kind=kind, verified=True, trade_date=str(DAYS[0]))
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION")
    )
    births = []
    result = run(previous, close=4100, facts=facts, _birth_observer=births.append)
    assert next(row for row in result if row["kind"] == "SEVERE_TECHNICAL")["status"] == "CONFIRMED"
    assert len(births) == birth_count
    if births:
        assert births[0].kind == births[0].risk_identity == "SEVERE_TECHNICAL"
        assert (births[0].status_before, births[0].status_after) == ("CLEAR", "CONFIRMED")


@pytest.mark.parametrize(
    "scenario", ["no-breach", "resolve-second", "restart", "basis-gap", "missing-official-close"]
)
def test_observing_other_real_branches_adds_no_comparison_or_calendar_call(monkeypatch, scenario):
    previous, arguments = (), {}
    if scenario == "no-breach":
        arguments["close"] = 4100
    else:
        previous = run()
        arguments["day"] = DAYS[1]
        if scenario == "resolve-second":
            ordinary(previous)["second_close_date"] = None
        elif scenario == "restart":
            ordinary(previous)["suspension_confirmation_policy"] = "RESTART_ADJACENT_PAIR"
            arguments.update(day=DAYS[2], suspended_dates=(DAYS[1],))
        elif scenario == "basis-gap":
            arguments["basis_id"] = "changed-basis"
        else:
            arguments["day"] = DAYS[2]
    calls = []
    compare, next_session = daily_risk.compare, daily_risk.next_session

    def compared(*args):
        calls.append(("compare", args))
        return compare(*args)

    def next_day(*args):
        calls.append(("next_session", args))
        return next_session(*args)

    monkeypatch.setattr(daily_risk, "compare", compared)
    monkeypatch.setattr(daily_risk, "next_session", next_day)
    original = run(previous, **arguments)
    original_calls = list(calls)
    calls.clear()
    observations, births = [], []
    observed = run(
        previous,
        **arguments,
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    assert canonical(observed) == canonical(original) and calls == original_calls
    assert len(observations) == 1
    if scenario == "resolve-second":
        assert [name for name, _ in calls] == ["compare", "next_session", "next_session"]
        assert observations[0].second_close_date_before is None
        assert observations[0].expected_second_close_date == DAYS[1]
        assert observations[0].confirmation_close_used is True
    elif scenario == "missing-official-close":
        assert observations[0].blockers == ("NEXT_OFFICIAL_CLOSE_UNVERIFIED",)
        assert observations[0].confirmation_close_used is False


def test_quantitative_severe_birth_retains_the_actual_native_condition_proof():
    from tests.unit.test_daily_conditions import synthetic_series
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    plan = UnifiedTradePlan.model_validate(unified_payload())
    series, _ = synthetic_series(2)
    day = series.bars[-1].trade_date
    branch = next(item for item in plan.risk_branches if item.kind == "SEVERE_TECHNICAL")
    facts = tuple(
        dict(id=kind, kind=kind, verified=True, trade_date=str(day))
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION")
    )
    evidence = evaluate_unified_condition(branch.condition, series, facts=facts)
    assert evidence.outcome == "SATISFIED"
    births = []
    result = daily_risk.advance_daily_risks(
        plan,
        previous=(),
        close_date=day,
        close_fen=series.bars[-1].close,
        basis_id=series.basis_id,
        session_dates=series.session_dates,
        suspended_dates=(),
        facts=facts,
        severe_evidence={branch.kind: evidence},
        _birth_observer=births.append,
    )
    severe = next(item for item in result if item["kind"] == "SEVERE_TECHNICAL")
    assert severe["technical_evidence"] == [evidence.model_dump(mode="json")]
    assert len(births) == 1 and births[0].kind == "SEVERE_TECHNICAL"
