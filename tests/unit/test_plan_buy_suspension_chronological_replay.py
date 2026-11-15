"""Chronological engineering replay only; no public frozen contract or trade API."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from tests.unit.test_plan_buy_suspension_state import at, basis_payload
from tests.unit.test_plan_buy_suspension_transition import batch, initial

from trade_plan_monitor.decision.buy_suspension import transition_buy_suspension


def midnight(day):
    return datetime.combine(day, time(), at().tzinfo)


def test_actual_current_anchor_date_can_advance_when_its_actual_factor_stays_equal():
    start = at("2026-09-30T14:55:00")
    end = at("2026-10-09T09:35:00")
    definition = initial().definition.model_copy(update={"effective_from": start})
    state = initial(definition=definition, target=start, evaluated_at=start)
    first_end = at("2026-10-01T00:00:00")
    first_basis = {**basis_payload(), "verified_at": first_end}
    state = transition_buy_suspension(state, target=first_end, evaluated_at=first_end,
        generation="process-1", batch=batch(start=start, through=first_end, basis=first_basis))
    assert state.outcome == "CLEAR_THROUGH_TARGET"
    # Explicit synthetic closed calendar dates, never absence-of-data inference.
    for offset in range(8):
        left = midnight(date(2026, 10, 1) + timedelta(days=offset))
        right = left + timedelta(days=1)
        state = transition_buy_suspension(state, target=right, evaluated_at=right,
            generation="process-1", batch=batch(start=left, through=right,
                                                 is_open=False, basis=None))
        assert state.coverage.through == right
    current_basis = {**basis_payload(), "trade_date": end.date(), "anchor_date": end.date(),
                     "verified_at": end}
    state = transition_buy_suspension(state, target=end, evaluated_at=end, generation="process-1",
        batch=batch(start=midnight(end.date()), through=end, basis=current_basis))
    assert state.outcome == "CLEAR_THROUGH_TARGET"
    assert state.coverage.anchor_date == end.date()
    assert state.coverage.anchor_factor == Decimal("2.75")


@pytest.mark.parametrize("downtime_breach", [False, True])
def test_finite_stable_multiday_interval_finishes_with_one_day_bounded_batches(downtime_breach):
    target = at("2026-10-12T09:40:00")
    state = initial(target=target, evaluated_at=target)
    start = state.definition.effective_from
    steps, hashes = 0, []
    while start < target:
        right = min(midnight(start.date() + timedelta(days=1)), target)
        open_day = start.date() in {date(2026, 9, 30), date(2026, 10, 9), date(2026, 10, 12)}
        proof = {**basis_payload(), "trade_date": start.date(), "anchor_date": target.date(),
                 "verified_at": target} if open_day else None
        breach_end = at("2026-10-09T09:35:00")
        closes = {breach_end: 2419} if downtime_breach else {}
        value = batch(start=start, through=right, is_open=open_day, basis=proof, closes=closes)
        assert len(value.minutes) <= 240
        state = transition_buy_suspension(state, target=target, evaluated_at=target,
                                          generation="process-1", batch=value)
        steps += 1
        hashes.append(state.state_hash)
        # Resume in another process/object without turning a cursor into permission.
        state = state.model_validate_json(state.model_dump_json())
        if state.trigger is not None:
            assert downtime_breach and state.trigger.bar_end == breach_end
            assert state.outcome == "LATCHED"
            break
        assert state.coverage.through == right
        if right < target:
            state = transition_buy_suspension(state, target=target, evaluated_at=target,
                generation="process-1", invalidate="BATCH_BUDGET_EXHAUSTED")
            assert state.outcome == "UNVERIFIED" and state.coverage.through == right
        start = right
    assert steps <= 13 and len(set(hashes)) == steps
    assert state.outcome == ("LATCHED" if downtime_breach else "CLEAR_THROUGH_TARGET")
    assert len(state.model_dump_json()) < 2500  # No unbounded retained bar sequence.


def chronological_trace(*, restart_after=None, mutate_future=False):
    closes = [2430, 2419, 2435, 2410]
    if mutate_future:
        closes[-1] = 3000
    state, trace = initial(), []
    for index, close in enumerate(closes):
        left = at("2026-09-30T09:30:00") + timedelta(minutes=5 * index)
        right = left + timedelta(minutes=5)
        state = transition_buy_suspension(state, target=right, evaluated_at=right,
            generation="process-1", batch=batch(start=left, through=right, closes={right: close}))
        # Engineering BUY candidate is considered only after this same-bar guard.
        trace.append((right, state.outcome, state.outcome == "CLEAR_THROUGH_TARGET",
                      None if state.trigger is None else state.trigger.bar_end))
        if index == restart_after:
            state = state.model_validate_json(state.model_dump_json())
    return state, trace


def test_per_bar_chronological_trace_has_same_bar_ban_and_no_future_influence():
    state, trace = chronological_trace()
    restored, restarted_trace = chronological_trace(restart_after=1)
    _, changed_future = chronological_trace(mutate_future=True)
    assert trace == restarted_trace == changed_future
    assert state == restored
    assert [row[1] for row in trace] == ["CLEAR_THROUGH_TARGET", "LATCHED", "LATCHED", "LATCHED"]
    assert [row[2] for row in trace] == [True, False, False, False]
    assert trace[1][0] == trace[1][3] == at("2026-09-30T09:40:00")


def test_gap_recovery_replays_the_real_missing_interval_instead_of_resetting_to_now():
    target = at("2026-09-30T09:45:00")
    state = initial(target=target, evaluated_at=target)
    gap = batch(through=target, missing=(at(),))
    unknown = transition_buy_suspension(state, target=target, evaluated_at=target,
        generation="process-1", batch=gap)
    assert unknown.outcome == "UNVERIFIED" and unknown.coverage is None
    repaired = batch(through=target, closes={at(): 2419})
    recovered = transition_buy_suspension(unknown, target=target, evaluated_at=target,
        generation="process-1", batch=repaired)
    assert recovered.outcome == "LATCHED" and recovered.trigger.bar_end == at()
    assert recovered.definition.effective_from == at("2026-09-30T09:30:00")


def test_latched_replay_does_not_leak_into_an_unrelated_plan_or_symbol():
    latched, _ = chronological_trace()
    for changes in ({"owner_plan_version_id": "unrelated-owner"}, {"symbol": "601021.SH"}):
        other = initial(**changes)
        assert other.outcome == "UNVERIFIED" and other.trigger is None
        assert other.definition == latched.definition
    assert latched.outcome == "LATCHED"
