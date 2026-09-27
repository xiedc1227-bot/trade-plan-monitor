"""Offline admission and fencing for small, scoped recovery steps."""

from datetime import datetime, timedelta

import pytest

from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.reconciliation import (
    RecoveryDisposition,
    RecoveryRequirement,
    RecoverySchedule,
    RecoveryStepResult,
)

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=SHANGHAI)


def _requirement(key: str, revision: str = "activation-1:target-1") -> RecoveryRequirement:
    return RecoveryRequirement(scope_key=key, revision=revision)


def test_empty_schedule_has_a_maintenance_wake_not_a_provider_request() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize(())
    assert schedule.claim(now=NOW) is None
    assert schedule.next_wake_at(now=NOW) == NOW + timedelta(seconds=30)


def test_failure_does_not_starve_sibling_and_scope_has_one_owner() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"), _requirement("index:B")))
    first = schedule.claim(now=NOW)
    assert first is not None and first.requirement.scope_key == "stock:A"
    assert schedule.claim(now=NOW) is None
    assert schedule.complete(first, RecoveryStepResult.retry(NOW + timedelta(seconds=60)))
    second = schedule.claim(now=NOW)
    assert second is not None and second.requirement.scope_key == "index:B"
    assert schedule.complete(second, RecoveryStepResult.ready())
    assert schedule.claim(now=NOW) is None
    assert schedule.next_wake_at(now=NOW) == NOW + timedelta(seconds=30)
    assert schedule.claim(now=NOW + timedelta(seconds=60)).requirement.scope_key == "stock:A"


def test_owned_work_has_a_future_maintenance_wake_even_with_pending_siblings() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"), _requirement("index:B")))
    ticket = schedule.claim(now=NOW)
    assert ticket is not None
    assert schedule.next_wake_at(now=NOW) == NOW + timedelta(seconds=30)


def test_new_minute_target_does_not_bypass_stable_scope_retry() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"),))
    ticket = schedule.claim(now=NOW)
    schedule.complete(ticket, RecoveryStepResult.retry(NOW + timedelta(seconds=300)))
    schedule.synchronize((_requirement("stock:A", "activation-1:target-2"),))
    assert schedule.claim(now=NOW + timedelta(seconds=60)) is None
    assert schedule.claim(now=NOW + timedelta(seconds=300)).requirement.revision.endswith("2")


def test_inflight_retarget_discards_old_result_without_releasing_physical_owner_early() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"),))
    ticket = schedule.claim(now=NOW)
    schedule.synchronize((_requirement("stock:A", "activation-2:target-1"),))
    assert not schedule.is_current(ticket)
    assert schedule.claim(now=NOW) is None
    assert not schedule.complete(ticket, RecoveryStepResult.ready())
    replacement = schedule.claim(now=NOW)
    assert replacement is not None
    assert replacement.requirement.revision == "activation-2:target-1"


def test_removed_and_readded_identical_requirement_does_not_resurrect_old_ticket() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"),))
    ticket = schedule.claim(now=NOW)
    schedule.synchronize(())
    schedule.synchronize((_requirement("stock:A"),))
    assert not schedule.is_current(ticket)
    assert not schedule.complete(ticket, RecoveryStepResult.ready())
    assert schedule.claim(now=NOW) is not None


def test_failure_returning_after_target_change_still_defers_the_same_scope() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"),))
    ticket = schedule.claim(now=NOW)
    schedule.synchronize((_requirement("stock:A", "activation-1:target-2"),))
    assert not schedule.complete(ticket, RecoveryStepResult.retry(NOW + timedelta(seconds=300)))
    assert schedule.claim(now=NOW) is None
    assert schedule.claim(now=NOW + timedelta(seconds=299)) is None
    assert schedule.claim(now=NOW + timedelta(seconds=300)).requirement.revision.endswith("2")


def test_unchanged_requirements_coalesce_and_preserve_readiness() -> None:
    schedule = RecoverySchedule()
    requirement = _requirement("stock:A")
    schedule.synchronize((requirement,))
    ticket = schedule.claim(now=NOW)
    schedule.complete(ticket, RecoveryStepResult.ready())
    schedule.synchronize((requirement,))
    assert schedule.claim(now=NOW) is None
    assert schedule.snapshot()[0].disposition is RecoveryDisposition.READY


def test_bound_and_duplicate_validation_are_atomic() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("old"),))
    with pytest.raises(ValueError, match="32"):
        schedule.synchronize(tuple(_requirement(str(i)) for i in range(33)))
    with pytest.raises(ValueError, match="unique"):
        schedule.synchronize((_requirement("new"), _requirement("new")))
    assert schedule.claim(now=NOW).requirement.scope_key == "old"


def test_blocked_scope_requires_requirement_change_and_does_not_hide_siblings() -> None:
    schedule = RecoverySchedule()
    schedule.synchronize((_requirement("stock:A"), _requirement("index:B")))
    ticket = schedule.claim(now=NOW)
    schedule.complete(ticket, RecoveryStepResult.blocked())
    ticket = schedule.claim(now=NOW)
    assert ticket.requirement.scope_key == "index:B"
    schedule.complete(ticket, RecoveryStepResult.ready())
    assert schedule.claim(now=NOW + timedelta(days=7)) is None
    schedule.synchronize((_requirement("stock:A", "new-config"), _requirement("index:B")))
    assert schedule.claim(now=NOW).requirement.scope_key == "stock:A"


def test_foreign_or_duplicate_completion_cannot_finish_owned_work() -> None:
    first, second = RecoverySchedule(), RecoverySchedule()
    for schedule in (first, second):
        schedule.synchronize((_requirement("stock:A"),))
    ticket = first.claim(now=NOW)
    foreign = second.claim(now=NOW)
    with pytest.raises(ValueError, match="owned"):
        first.complete(foreign, RecoveryStepResult.ready())
    assert first.is_current(ticket)
    assert first.complete(ticket, RecoveryStepResult.ready())
    with pytest.raises(ValueError, match="owned"):
        first.complete(ticket, RecoveryStepResult.ready())


def test_result_invariants_and_aware_timestamps() -> None:
    with pytest.raises(ValueError):
        RecoveryStepResult(RecoveryDisposition.READY, NOW)
    with pytest.raises(ValueError):
        RecoveryStepResult(RecoveryDisposition.RETRY, None)
    with pytest.raises(ValueError):
        RecoveryStepResult.retry(NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        RecoveryRequirement(scope_key="", revision="r")


@pytest.mark.parametrize("result", [RecoveryStepResult.ready(), RecoveryStepResult.blocked(),
                                   RecoveryStepResult.retry(NOW + timedelta(seconds=30))])
def test_local_resolution_preserves_future_retry_across_targets(result):
    schedule = RecoverySchedule()
    old, new = _requirement("A"), _requirement("A", "new-target")
    schedule.synchronize((old,))
    ticket = schedule.claim(now=NOW)
    schedule.complete(ticket, RecoveryStepResult.retry(NOW + timedelta(minutes=5)))
    schedule.synchronize((new,))
    before = schedule.snapshot()
    assert not schedule.resolve_local(new, result, now=NOW)
    assert schedule.snapshot() == before


@pytest.mark.parametrize("removed", [False, True])
def test_local_resolution_cannot_replace_old_scope_ticket_and_late_retry_floor(removed):
    schedule = RecoverySchedule()
    old, new = _requirement("A"), _requirement("A", "new-target")
    sibling = _requirement("B")
    schedule.synchronize((old, sibling))
    ticket = schedule.claim(now=NOW)
    if removed:
        schedule.synchronize((sibling,))
    schedule.synchronize((new, sibling))
    before = schedule.snapshot()[0]
    assert not schedule.resolve_local(new, RecoveryStepResult.ready(), now=NOW)
    assert schedule.snapshot()[0] == before
    assert schedule.resolve_local(sibling, RecoveryStepResult.ready(), now=NOW)
    assert schedule._owned is ticket
    assert schedule.claim(now=NOW) is None
    assert not schedule.complete(ticket, RecoveryStepResult.retry(NOW + timedelta(minutes=5)))
    assert schedule.snapshot()[0].next_retry_at == NOW + timedelta(minutes=5)


@pytest.mark.parametrize("disposition", [RecoveryStepResult.ready(), RecoveryStepResult.blocked()])
def test_local_resolution_does_not_rearm_terminal_state(disposition):
    schedule = RecoverySchedule()
    requirement = _requirement("A")
    schedule.synchronize((requirement,))
    assert schedule.resolve_local(requirement, disposition, now=NOW)
    before = schedule.snapshot()
    assert not schedule.resolve_local(
        requirement, RecoveryStepResult.retry(NOW + timedelta(days=2)),
        now=NOW + timedelta(days=1),
    )
    assert schedule.snapshot() == before


def test_local_resolution_only_exact_current_and_does_not_rotate():
    schedule = RecoverySchedule()
    a, b, c = (_requirement(key) for key in "ABC")
    schedule.synchronize((a, b, c))
    assert not schedule.resolve_local(
        _requirement("B", "stale"), RecoveryStepResult.ready(), now=NOW,
    )
    assert schedule.resolve_local(b, RecoveryStepResult.blocked(), now=NOW)
    assert schedule.claim(now=NOW).requirement == a


def test_local_retry_expiry_equality_is_eligible_but_replacement_must_be_future():
    schedule = RecoverySchedule()
    requirement = _requirement("A")
    schedule.synchronize((requirement,))
    assert schedule.resolve_local(
        requirement, RecoveryStepResult.retry(NOW + timedelta(seconds=30)), now=NOW,
    )
    assert schedule.resolve_local(requirement, RecoveryStepResult.ready(),
                                  now=NOW + timedelta(seconds=30))


@pytest.mark.parametrize("result", [RecoveryStepResult(RecoveryDisposition.PENDING),
                                   RecoveryStepResult.retry(NOW),
                                   RecoveryStepResult.retry(NOW - timedelta(seconds=1))])
def test_local_resolution_rejects_pending_and_nonfuture_retry(result):
    schedule = RecoverySchedule()
    requirement = _requirement("A")
    schedule.synchronize((requirement,))
    before = schedule.snapshot()
    with pytest.raises(ValueError):
        schedule.resolve_local(requirement, result, now=NOW)
    assert schedule.snapshot() == before
