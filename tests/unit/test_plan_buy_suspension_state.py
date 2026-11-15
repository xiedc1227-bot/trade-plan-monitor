"""Private suspension state has exact ownership, bounded proof and durable evidence."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState

ZONE = ZoneInfo("Asia/Shanghai")


def at(value="2026-09-30T09:35:00"):
    return datetime.fromisoformat(value).replace(tzinfo=ZONE)


def state_payload(**changes):
    return dict(
        version="buy-suspension-state-v1", symbol="002240.SZ",
        owner_plan_version_id="owner-version", content_hash="a" * 64,
        source_hash="b" * 64, review_id="owner-review", birth_activation_revision=3,
        definition={"condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                                  "price_fen": 2420},
                    "effective_from": at("2026-09-30T09:30:00")},
        evaluated_at=at(), target=at(), coverage=None, trigger=None,
        blocker="HISTORY_PENDING",
    ) | changes


def basis_payload():
    return dict(source_contract="TUSHARE_STK_MINS_241_END_V1", trade_date=date(2026, 9, 30),
                anchor_date=date(2026, 9, 30), trade_date_factor=Decimal("2.75"),
                anchor_factor=Decimal("2.75"), verified_at=at())


def coverage_payload():
    return dict(through=at(), content_hash="c" * 64, anchor_date=date(2026, 9, 30),
                anchor_factor=Decimal("2.75"), generation="process-1")


def trigger_payload():
    return dict(bar_end=at(), close_fen=2419, source_hash="d" * 64,
                basis=basis_payload(), observed_at=at())


def test_private_state_exposes_actual_definition_hash_and_unresolved_interval():
    state = DailyBuySuspensionState.model_validate(state_payload())
    assert state.outcome == "UNVERIFIED"
    assert state.unresolved_interval == (at("2026-09-30T09:30:00"), at())
    assert len(state.state_hash) == len(state.definition_hash) == 64
    assert state.model_validate_json(state.model_dump_json()) == state
    changed = state.model_copy(update={"blocker": "PROOF_INVALIDATED"})
    assert changed.state_hash != state.state_hash
    assert changed.definition_hash == state.definition_hash


def test_clear_empty_and_nonempty_intervals_require_coverage():
    payload = state_payload()
    payload.update(coverage=coverage_payload(), blocker=None)
    state = DailyBuySuspensionState.model_validate(payload)
    assert state.outcome == "CLEAR_THROUGH_TARGET"
    assert state.unresolved_interval == (None, None)
    empty = state.model_copy(update={"target": at("2026-09-30T09:30:00"),
        "coverage": {**coverage_payload(), "through": at("2026-09-30T09:30:00")}})
    assert empty.outcome == "CLEAR_THROUGH_TARGET"


def test_trigger_is_observed_evidence_even_without_continuous_coverage():
    payload = state_payload()
    payload.update(trigger=trigger_payload(), blocker=None)
    state = DailyBuySuspensionState.model_validate(payload)
    assert state.outcome == "LATCHED"
    # The earlier interval remains unproved; a breach does not backfill it.
    assert state.unresolved_interval == (at("2026-09-30T09:30:00"), at())


def test_calendar_proved_empty_prefix_does_not_invent_a_price_factor():
    payload = state_payload(target=at("2026-09-30T09:30:00"), blocker=None)
    payload["coverage"] = dict(through=payload["target"], content_hash="c" * 64,
                               anchor_date=None, anchor_factor=None, generation="process-1")
    state = DailyBuySuspensionState.model_validate(payload)
    assert state.outcome == "CLEAR_THROUGH_TARGET"
    with pytest.raises(ValueError):
        state.model_copy(update={"coverage": {**payload["coverage"],
                                               "anchor_factor": Decimal("2.75")}})


@pytest.mark.parametrize("blocker", ["PROOF_INVALIDATED", "GENERATION_CHANGED"])
def test_invalidated_proof_cannot_hide_the_unresolved_interval(blocker):
    with pytest.raises(ValueError):
        DailyBuySuspensionState.model_validate(state_payload(
            blocker=blocker, coverage=coverage_payload()))
    reset = DailyBuySuspensionState.model_validate(state_payload(blocker=blocker))
    assert reset.unresolved_interval == (reset.definition.effective_from, reset.target)


def test_minute_gap_retains_the_actual_verified_partial_prefix():
    state = DailyBuySuspensionState.model_validate(state_payload(
        target=at("2026-09-30T09:40:00"), evaluated_at=at("2026-09-30T09:40:00"),
        coverage=coverage_payload(), blocker="MINUTE_GAP"))
    assert state.unresolved_interval == (at(), at("2026-09-30T09:40:00"))


@pytest.mark.parametrize("blocker", ["HISTORY_PENDING", "MINUTE_GAP", "CALENDAR_UNVERIFIED",
    "PRICE_BASIS_UNVERIFIED", "SOURCE_UNVERIFIED", "BATCH_BUDGET_EXHAUSTED"])
def test_unknown_cannot_claim_complete_effective_coverage(blocker):
    with pytest.raises(ValueError):
        DailyBuySuspensionState.model_validate(state_payload(
            blocker=blocker, coverage=coverage_payload()))


@pytest.mark.parametrize("change", [
    {"version": "buy-suspension-state-v2"}, {"unlock": True},
    {"birth_activation_revision": True}, {"source_hash": "not-a-hash"},
    {"target": at("2026-09-30T09:40:00")},
    {"target": at("2026-09-30T09:33:00")},
    {"blocker": None},
    {"coverage": {**coverage_payload(), "through": at("2026-09-30T09:40:00")}},
    {"coverage": {**coverage_payload(), "through": at("2026-09-30T09:25:00")}},
    {"trigger": {**trigger_payload(), "close_fen": 2420}},
    {"trigger": {**trigger_payload(), "bar_end": at("2026-09-30T09:30:00")}},
    {"trigger": {**trigger_payload(), "basis": {**basis_payload(),
                                                   "trade_date_factor": Decimal("1")}}},
    {"trigger": {**trigger_payload(), "observed_at": at("2026-09-30T09:40:00")}},
])
def test_invalid_state_fails_closed(change):
    payload = state_payload()
    payload.update(change)
    with pytest.raises(ValueError):
        DailyBuySuspensionState.model_validate(payload)
