"""Bounded discovery observes absent closes without executing or permitting replay."""

from datetime import date, datetime, timedelta

import pytest
from test_decision_engine import _official_risk_context

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import EvaluationResult
from trade_plan_monitor.domain.plan_models import DateRangeActivation, TradingDayActivation
from trade_plan_monitor.market_data.sessions import SHANGHAI
from trade_plan_monitor.runtime.missed_close_recovery import (
    CompletionStatus,
    MissedCloseScope,
    OfficialCloseCompletion,
    discover_missed_closes,
)


def scope_for(*, activated_at=None, observed_at=None, plan=None):
    context = _official_risk_context()
    return MissedCloseScope(
        plan=plan or context.plan, plan_version_id="version-1", activation_revision=2,
        activated_at=activated_at or datetime(2026, 8, 5, 9, tzinfo=SHANGHAI),
        observed_at=observed_at or datetime(2026, 8, 7, 16, tzinfo=SHANGHAI),
    )


def evidence(scope, identity, status=CompletionStatus.ABSENT, **updates):
    values = dict(
        identity=identity, plan_version_id=scope.plan_version_id,
        activation_revision=scope.activation_revision, activated_at=scope.activated_at,
        observed_at=scope.observed_at, status=status,
    )
    values.update(updates)
    return OfficialCloseCompletion(**values)


def discover(scope, *, is_open_on=lambda day: True, completion_on=None, **kwargs):
    return discover_missed_closes(
        scope=scope, is_open_on=is_open_on,
        completion_on=completion_on or (lambda identity: evidence(scope, identity)), **kwargs,
    )


def test_entirely_absent_closes_are_ordered_without_pending_rows():
    scope = scope_for()
    window = discover(scope)
    assert [row.identity.official_trade_date for row in window.candidates] == [
        date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7),
    ]
    assert all(row.status is CompletionStatus.ABSENT for row in window.candidates)
    assert all(row.source_cutoff.hour == 15 for row in window.candidates)
    assert window.next_window_start is None


@pytest.mark.parametrize("minute, count", [(19, 0), (20, 1)])
def test_same_day_first_attempt_boundary(minute, count):
    scope = scope_for(
        activated_at=datetime(2026, 8, 7, 15, tzinfo=SHANGHAI),
        observed_at=datetime(2026, 8, 7, 15, minute, tzinfo=SHANGHAI),
    )
    assert len(discover(scope).candidates) == count


def test_activation_after_source_close_excludes_that_day():
    scope = scope_for(activated_at=datetime(2026, 8, 7, 15, 1, tzinfo=SHANGHAI))
    assert discover(scope).candidates == ()


def test_expired_policy_still_discovers_its_historical_obligation():
    plan = scope_for().plan.model_copy(update={
        "activation": TradingDayActivation(trading_day=date(2026, 8, 6)),
    })
    window = discover(scope_for(plan=plan))
    assert [row.identity.official_trade_date for row in window.candidates] == [date(2026, 8, 6)]


def test_calendar_unknown_remains_visible_and_closed_days_do_not_lookup_completion():
    scope = scope_for()
    calls = []

    def completion(identity):
        calls.append(identity.official_trade_date)
        return evidence(scope, identity)

    window = discover(scope, is_open_on=lambda day: {5: False, 6: None, 7: True}[day.day],
                      completion_on=completion)
    assert [(row.identity.official_trade_date.day, row.status) for row in window.candidates] == [
        (6, CompletionStatus.UNKNOWN), (7, CompletionStatus.ABSENT),
    ]
    assert window.candidates[0].reason == "calendar_unknown"
    assert calls == [date(2026, 8, 7)]


def test_maximum_window_has_bounded_callbacks_and_explicit_continuation():
    scope = scope_for(observed_at=datetime(2026, 10, 1, 16, tzinfo=SHANGHAI))
    calls = []
    window = discover(scope, is_open_on=lambda day: calls.append(day) or True)
    assert len(calls) == len(window.candidates) == 32
    assert window.next_window_start == date(2026, 9, 6)
    next_window = discover(scope, window_start=window.next_window_start)
    assert next_window.window_start == date(2026, 9, 6)
    assert next_window.next_window_start is None
    assert not hasattr(next_window, "ready")


@pytest.mark.parametrize("value", [0, 33, True, 1.5])
def test_invalid_window_bounds_rejected_before_callbacks(value):
    with pytest.raises((TypeError, ValueError)):
        discover(scope_for(), max_calendar_days=value)


@pytest.mark.parametrize("day", [date(2026, 8, 4), date(2026, 8, 8), "2026-08-05"])
def test_window_start_must_be_within_observed_activation_history(day):
    with pytest.raises((TypeError, ValueError)):
        discover(scope_for(), window_start=day)


def test_missing_authority_is_unknown_never_absent():
    window = discover(scope_for(), completion_on=lambda identity: None)
    assert all(row.status is CompletionStatus.UNKNOWN for row in window.candidates)


@pytest.mark.parametrize("field, value", [
    ("activation_revision", 1), ("plan_version_id", "version-elsewhere"),
    ("activated_at", datetime(2026, 8, 4, 9, tzinfo=SHANGHAI)),
    ("observed_at", datetime(2026, 8, 7, 15, tzinfo=SHANGHAI)),
])
def test_wrong_authority_binding_cannot_prove_absence(field, value):
    scope = scope_for()
    window = discover(scope, completion_on=lambda identity: evidence(
        scope, identity, **{field: value},
    ))
    assert all(row.status is CompletionStatus.UNKNOWN for row in window.candidates)


@pytest.mark.parametrize("certified", [False, True])
def test_proven_requires_full_result_and_committed_publication(certified):
    scope = scope_for()
    window = discover(scope, completion_on=lambda identity: evidence(
        scope, identity, CompletionStatus.PROVEN, committed_publication=certified,
    ))
    assert all(row.status is CompletionStatus.UNKNOWN for row in window.candidates)


def test_proven_committed_occurrence_after_absence_marks_causal_gap():
    scope = scope_for()
    result = evaluate(_official_risk_context())

    def completion(identity):
        if identity == result.evaluation_identity:
            return evidence(scope, identity, CompletionStatus.PROVEN,
                            result=result, committed_publication=True)
        return evidence(scope, identity)

    window = discover(scope, completion_on=completion)
    assert window.candidates[-1].status is CompletionStatus.PROVEN
    assert window.candidates[-1].causal_history_gap
    assert not window.candidates[0].causal_history_gap


def test_unknown_claim_after_absence_also_marks_potential_causal_gap():
    scope = scope_for()
    window = discover(scope, completion_on=lambda identity: (
        evidence(scope, identity) if identity.official_trade_date.day == 5 else None
    ))
    assert all(row.causal_history_gap for row in window.candidates[1:])


def test_source_failures_propagate():
    def fail(_):
        raise RuntimeError("storage unavailable")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        discover(scope_for(), completion_on=fail)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        discover(scope_for(), is_open_on=fail)


def test_forged_result_digest_cannot_prove_completion():
    scope = scope_for()
    result = evaluate(_official_risk_context())
    forged = EvaluationResult.model_construct(**dict(result.__dict__, result_hash="0" * 64))
    window = discover(scope, completion_on=lambda identity: evidence(
        scope, identity, CompletionStatus.PROVEN, committed_publication=True,
    ).model_copy(update={"result": forged}))
    assert all(row.status is CompletionStatus.UNKNOWN for row in window.candidates)


def test_evaluation_after_observation_cannot_prove_completion():
    scope = scope_for(observed_at=datetime(2026, 8, 7, 15, 20, tzinfo=SHANGHAI))
    result = evaluate(_official_risk_context())
    window = discover(scope, completion_on=lambda identity: evidence(
        scope, identity, CompletionStatus.PROVEN, result=result, committed_publication=True,
    ))
    assert window.candidates[-1].status is CompletionStatus.UNKNOWN


def test_scope_rejects_future_activation_and_invalid_legacy_plan():
    with pytest.raises(ValueError):
        scope_for(activated_at=scope_for().observed_at + timedelta(seconds=1))
    plan = scope_for().plan.model_copy(update={"schema_version": 3})
    with pytest.raises(ValueError):
        discover(scope_for(plan=plan))


@pytest.mark.parametrize("certified, expected", [
    (True, CompletionStatus.PROVEN), (False, CompletionStatus.UNKNOWN),
])
def test_full_result_requires_publication_and_proves_only_occurrence(certified, expected):
    scope = scope_for(activated_at=datetime(2026, 8, 7, 9, tzinfo=SHANGHAI))
    result = evaluate(_official_risk_context())
    window = discover(scope, completion_on=lambda identity: evidence(
        scope, identity, CompletionStatus.PROVEN, result=result, committed_publication=certified,
    ))
    assert window.candidates[0].status is expected
    assert not window.candidates[0].causal_history_gap
    assert not hasattr(window, "complete")


def test_proven_after_unknown_calendar_retains_potential_causal_gap():
    scope = scope_for()
    result = evaluate(_official_risk_context())
    window = discover(scope, is_open_on=lambda day: True if day.day == 7 else None,
                      completion_on=lambda identity: evidence(
                          scope, identity, CompletionStatus.PROVEN,
                          result=result, committed_publication=True,
                      ))
    assert len(window.candidates) == 3
    assert window.candidates[-1].status is CompletionStatus.PROVEN
    assert window.candidates[-1].causal_history_gap


@pytest.mark.parametrize("update", [
    {"symbol": "600000.SH"}, {"plan_hash": "0" * 64},
    {"official_trade_date": date(2026, 8, 1)}, {"formula_version": "invalid"},
])
def test_wrong_canonical_identity_cannot_prove_absence(update):
    scope = scope_for()

    def completion(identity):
        wrong = type(identity).model_construct(**dict(identity.__dict__, **update))
        return evidence(scope, identity).model_copy(update={"identity": wrong})

    assert all(row.status is CompletionStatus.UNKNOWN for row in discover(
        scope, completion_on=completion,
    ).candidates)


@pytest.mark.parametrize("weekend_open, expected", [
    (False, ()), (None, (CompletionStatus.UNKNOWN, CompletionStatus.UNKNOWN)),
    (True, (CompletionStatus.ABSENT, CompletionStatus.ABSENT)),
])
def test_date_range_uses_authoritative_weekend_calendar(weekend_open, expected):
    plan = scope_for().plan.model_copy(update={
        "activation": DateRangeActivation(start_date=date(2026, 8, 8), end_date=date(2026, 8, 9)),
    })
    scope = scope_for(plan=plan, observed_at=datetime(2026, 8, 10, 16, tzinfo=SHANGHAI))
    window = discover(scope, is_open_on=lambda day: weekend_open)
    assert tuple(row.status for row in window.candidates) == expected


def test_date_max_window_does_not_overflow():
    scope = scope_for(
        activated_at=datetime(9999, 12, 31, 9, tzinfo=SHANGHAI),
        observed_at=datetime(9999, 12, 31, 16, tzinfo=SHANGHAI),
    )
    window = discover(scope)
    assert window.window_end == date.max
    assert window.next_window_start is None


def test_invalid_calendar_boolean_is_unknown_and_does_not_read_completion():
    scope = scope_for()

    def fail(_):
        raise AssertionError("completion must not be read for uncertain calendar")

    assert all(row.status is CompletionStatus.UNKNOWN for row in discover(
        scope, is_open_on=lambda day: 1, completion_on=fail,
    ).candidates)


def test_conflicting_absence_with_result_is_unknown():
    scope = scope_for()
    result = evaluate(_official_risk_context())
    assert all(row.status is CompletionStatus.UNKNOWN for row in discover(
        scope, completion_on=lambda identity: evidence(scope, identity, result=result),
    ).candidates)


def test_invalid_programming_return_type_propagates():
    with pytest.raises(TypeError, match="typed evidence"):
        discover(scope_for(), completion_on=lambda identity: {})


def test_scope_is_revalidated_before_reading_sources():
    scope = scope_for().model_copy(update={"activation_revision": True})
    with pytest.raises(ValueError):
        discover(scope)
