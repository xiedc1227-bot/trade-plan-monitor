"""One pure guard transition: continuous bounded progress and irreversible breach."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from tests.unit.test_plan_buy_suspension_state import at, basis_payload, state_payload

from trade_plan_monitor.decision.buy_suspension import (
    BuySuspensionBatch,
    transition_buy_suspension,
)
from trade_plan_monitor.market_data.models import MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState


def minute(end, close=2430, *, low=None, symbol="002240.SZ"):
    return MinuteBar(symbol=symbol, bar_end=end, open_fen=2430,
                     high_fen=max(2430, close), low_fen=min(2430, close) if low is None else low,
                     close_fen=close, volume_shares=100, amount_yuan=Decimal("2430"),
                     received_at=end)


def batch(*, start=None, through=None, closes=None, missing=(), low=None, is_open=True,
          basis="actual", calendar="actual", generation="process-1"):
    start = start or at("2026-09-30T09:30:00")
    through = through or at()
    closes = closes or {}
    ends = expected_minute_ends(start.date(), is_open=is_open)
    rows = tuple(minute(end, closes.get(end, 2430), low=low) for end in ends
                 if start < end <= through and end not in missing)
    cal = TradingDay(exchange="SZSE", cal_date=start.date(), is_open=is_open,
                     previous_trade_date=start.date() - timedelta(days=1))
    price = {**basis_payload(), "trade_date": start.date(), "anchor_date": through.date(),
             "verified_at": through}
    return BuySuspensionBatch(start=start, through=through, minutes=rows,
        calendar=cal if calendar == "actual" else calendar,
        basis=price if basis == "actual" else basis, generation=generation)


def initial(**changes):
    return DailyBuySuspensionState.model_validate(state_payload(**changes))


def apply(state=None, value=None, *, target=None, observed=None, generation="process-1",
          invalidate=None):
    value = value if value is not None else batch()
    target = target or value.through
    return transition_buy_suspension(state or initial(), target=target,
        evaluated_at=observed or max(target, value.through), generation=generation,
        batch=value, invalidate=invalidate)


@pytest.mark.parametrize("close,outcome", [(2419, "LATCHED"), (2420, "CLEAR_THROUGH_TARGET"),
                                          (2421, "CLEAR_THROUGH_TARGET")])
def test_strict_first_completed_close_needs_no_previous_crossing(close, outcome):
    result = apply(value=batch(closes={at(): close}))
    assert result.outcome == outcome
    if result.trigger:
        assert result.trigger.close_fen == 2419 and result.trigger.bar_end == at()
        assert result.trigger.basis.anchor_factor == Decimal("2.75")


def test_low_alone_and_incomplete_buckets_cannot_trigger():
    assert apply(value=batch(low=2410)).outcome == "CLEAR_THROUGH_TARGET"
    partial = batch(closes={at(): 2419}, missing=(at("2026-09-30T09:33:00"),))
    state = apply(value=partial)
    assert state.outcome == "UNVERIFIED" and state.blocker == "MINUTE_GAP"
    assert state.coverage is None and state.trigger is None


def test_valid_later_breach_latches_despite_earlier_gap_without_claiming_first():
    end = at("2026-09-30T09:40:00")
    state = apply(value=batch(through=end, closes={end: 2419}, missing=(at(),)))
    assert state.outcome == "LATCHED" and state.trigger.bar_end == end
    assert state.coverage is None
    assert state.unresolved_interval == (at("2026-09-30T09:30:00"), end)


def test_source_calendar_and_factor_gaps_block_then_actual_evidence_completes():
    for value, reason in (
        (batch(calendar=None), "CALENDAR_UNVERIFIED"),
        (batch(basis=None), "PRICE_BASIS_UNVERIFIED"),
        (batch(basis={**basis_payload(), "trade_date_factor": Decimal("2.74")}),
         "PRICE_BASIS_UNVERIFIED"),
    ):
        state = apply(value=value)
        assert state.outcome == "UNVERIFIED" and state.blocker == reason
        assert apply(state).outcome == "CLEAR_THROUGH_TARGET"


def test_missing_calendar_does_not_certify_an_empty_interval():
    start = at("2026-09-30T09:30:00")
    state = initial(target=start, evaluated_at=start)
    assert apply(state, batch(start=start, through=start, calendar=None)).outcome == "UNVERIFIED"
    proved = apply(state, batch(start=start, through=start, basis=None))
    assert proved.outcome == "CLEAR_THROUGH_TARGET" and proved.coverage.anchor_factor is None


def test_gap_or_skipped_prefix_never_advanced_by_cursor_alone():
    end = at("2026-09-30T09:40:00")
    skipped = batch(start=at(), through=end)
    state = apply(value=skipped)
    assert state.outcome == "UNVERIFIED" and state.coverage is None
    first = apply(value=batch(), target=end)
    assert first.outcome == "UNVERIFIED" and first.coverage.through == at()
    assert apply(first, skipped).outcome == "CLEAR_THROUGH_TARGET"


def test_observation_and_batch_future_boundaries_fail_closed():
    future = at("2026-09-30T09:40:00")
    with pytest.raises(ValueError):
        apply(value=batch(through=future, closes={future: 2419}), target=at(), observed=at())
    with pytest.raises(ValueError):
        apply(value=batch(), target=future, observed=at())
    late = batch().model_copy(update={"minutes": tuple(
        row.model_copy(update={"received_at": future}) for row in batch().minutes)})
    state = apply(value=late)
    assert state.outcome == "UNVERIFIED" and state.trigger is None


def test_effective_start_excludes_the_preceding_bucket_and_includes_next_close():
    start, end = at(), at("2026-09-30T09:40:00")
    definition = initial().definition.model_copy(update={"effective_from": start})
    state = initial(definition=definition, target=end, evaluated_at=end)
    value = batch(start=start, through=end, closes={end: 2419})
    result = apply(state, value)
    assert result.trigger.bar_end == end
    assert result.definition.effective_from == start


@pytest.mark.parametrize("reason", ["PROOF_INVALIDATED", "GENERATION_CHANGED"])
def test_clear_invalidation_discards_prefix_and_bounded_rechecking_can_latch(reason):
    clear = apply()
    invalid = transition_buy_suspension(clear, target=at(), evaluated_at=at(),
        generation="process-1", invalidate=reason)
    assert invalid.outcome == "UNVERIFIED" and invalid.coverage is None
    assert invalid.unresolved_interval == (clear.definition.effective_from, at())
    revised = apply(invalid, batch(closes={at(): 2419}))
    assert revised.outcome == "LATCHED"


def test_restart_generation_drops_old_clear_then_can_complete_again():
    clear = apply()
    invalid = transition_buy_suspension(clear, target=at(), evaluated_at=at(),
        generation="process-2")
    assert invalid.outcome == "UNVERIFIED" and invalid.coverage is None
    assert invalid.blocker == "GENERATION_CHANGED"
    checked = apply(invalid, batch(generation="process-2"), generation="process-2")
    assert checked.outcome == "CLEAR_THROUGH_TARGET"


def test_latch_survives_rebound_correction_new_day_restart_and_invalidated_proof():
    latched = apply(value=batch(closes={at(): 2419}))
    corrected = apply(latched, batch(), invalidate="PROOF_INVALIDATED")
    assert corrected.trigger == latched.trigger and corrected.outcome == "LATCHED"
    later = at("2026-10-09T09:35:00")
    restored = corrected.model_validate_json(corrected.model_dump_json())
    restarted = transition_buy_suspension(restored,
        target=later, evaluated_at=later, generation="process-2", invalidate="GENERATION_CHANGED")
    assert restarted.trigger == latched.trigger and restarted.outcome == "LATCHED"


def test_batch_bound_and_duplicate_or_wrong_symbol_inputs_cannot_prove_coverage():
    value = batch()
    with pytest.raises(ValueError):
        value.model_copy(update={"minutes": value.minutes * 49})
    for rows in (value.minutes + value.minutes[:1],
                 tuple(row.model_copy(update={"symbol": "601021.SH"}) for row in value.minutes)):
        with pytest.raises(ValueError):
            apply(value=value.model_copy(update={"minutes": rows}))


def test_source_and_calendar_owner_must_match_exact_actual_batch_date():
    value = batch()
    with pytest.raises(ValueError):
        apply(value=value.model_copy(update={"calendar": value.calendar.model_copy(
            update={"exchange": "SSE"})}))
    with pytest.raises(ValueError):
        apply(value=value.model_copy(update={"basis": {**basis_payload(),
            "trade_date": date(2026, 9, 29)}}))


def test_target_extension_and_idempotent_same_batch_do_not_claim_unchecked_data():
    clear = apply()
    assert apply(clear).state_hash == clear.state_hash
    later = at("2026-09-30T09:40:00")
    pending = transition_buy_suspension(clear, target=later, evaluated_at=later,
                                      generation="process-1")
    assert pending.outcome == "UNVERIFIED" and pending.coverage.through == at()
    assert pending.unresolved_interval == (at(), later)


def test_changed_anchor_invalidates_old_prefix_before_consuming_later_batch():
    clear = apply()
    later = at("2026-09-30T09:40:00")
    changed_basis = {**basis_payload(), "anchor_factor": Decimal("3"),
                     "trade_date_factor": Decimal("3"), "verified_at": later}
    changed = apply(clear, batch(start=at(), through=later, basis=changed_basis))
    assert changed.outcome == "UNVERIFIED" and changed.coverage is None
    checked = apply(changed, batch(through=later, basis=changed_basis))
    assert checked.outcome == "CLEAR_THROUGH_TARGET"


def test_guard_not_yet_effective_never_returns_clear():
    state = initial(definition=initial().definition.model_copy(
        update={"effective_from": at("2026-10-09T09:30:00")}))
    result = transition_buy_suspension(state, target=at(), evaluated_at=at(),
                                       generation="process-1")
    assert result.outcome == "UNVERIFIED" and result.blocker == "START_NOT_REACHED"


@pytest.mark.parametrize("value", [batch(basis=None), batch(calendar=None),
    batch(missing=(at(),)), batch().model_copy(update={"minutes": tuple(
        row.model_copy(update={"received_at": at("2026-09-30T09:40:00")})
        for row in batch().minutes)})])
def test_failed_recheck_of_covered_interval_cannot_restore_old_clear_from_cursor(value):
    clear = apply()
    failed = apply(clear, value)
    assert failed.outcome == "UNVERIFIED" and failed.coverage is None
    assert failed.unresolved_interval == (clear.definition.effective_from, at())
    no_data = transition_buy_suspension(failed, target=at(), evaluated_at=at(),
                                       generation="process-1")
    assert no_data.outcome == "UNVERIFIED"


def test_finite_budget_pause_preserves_prefix_so_next_batch_can_finish():
    end = at("2026-09-30T09:40:00")
    first = apply(target=end)
    paused = transition_buy_suspension(first, target=end, evaluated_at=end,
        generation="process-1", invalidate="BATCH_BUDGET_EXHAUSTED")
    assert paused.outcome == "UNVERIFIED" and paused.coverage == first.coverage
    assert paused.blocker == "BATCH_BUDGET_EXHAUSTED"
    finished = apply(paused, batch(start=at(), through=end))
    assert finished.outcome == "CLEAR_THROUGH_TARGET"


def test_empty_target_recheck_failure_does_not_leave_unknown_with_empty_unresolved_interval():
    clear = apply()
    empty_failed = batch(start=at(), through=at(), calendar=None)
    result = apply(clear, empty_failed)
    assert result.outcome == "UNVERIFIED" and result.coverage is None
    assert result.unresolved_interval == (clear.definition.effective_from, at())
