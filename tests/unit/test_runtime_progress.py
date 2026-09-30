"""Progress comes from completed owner work, never observation traffic."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.progress import RuntimeProgress


class Clock:
    wall = datetime(2026, 9, 27, 12, tzinfo=SHANGHAI)
    tick = 100.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.tick


def tracker():
    clock = Clock()
    progress = RuntimeProgress(uuid4(), clock=clock.now, monotonic=clock.monotonic)
    return clock, progress


def test_reads_never_extend_work_deadline_or_record_progress():
    clock, progress = tracker()
    progress.begin_step(timeout_seconds=15)
    for second in (1, 10, 15, 16):
        clock.tick = 100 + second
        snapshot = progress.snapshot()
        assert snapshot.last_progress_at is None
    assert snapshot.state == "STALLED"
    assert snapshot.progress_due_at == clock.wall - timedelta(seconds=1)


def test_queued_parallel_unit_retains_its_original_absolute_deadline():
    clock, progress = tracker()
    original_deadline = clock.tick + 15
    first = progress.begin_step(timeout_seconds=15)
    clock.tick += 16
    progress.complete_step(first, next_wake_at=clock.wall + timedelta(seconds=30))
    queued = progress.begin_step_at(deadline=original_deadline)
    assert progress.snapshot().state == "STALLED"
    assert progress.snapshot().progress_due_at == clock.wall - timedelta(seconds=1)
    assert progress.complete_step(queued, next_wake_at=clock.wall + timedelta(seconds=30))


def test_only_exact_owned_completion_can_restore_progress():
    clock, progress = tracker()
    token = progress.begin_step(timeout_seconds=15)
    clock.tick += 16
    assert progress.snapshot().state == "STALLED"
    assert not progress.complete_step(object(), next_wake_at=clock.wall + timedelta(seconds=30))
    assert progress.snapshot().state == "STALLED"
    assert progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=30))
    snapshot = progress.snapshot()
    assert snapshot.state == "SCHEDULED"
    assert snapshot.last_progress_at == clock.wall
    assert snapshot.next_wake_at == clock.wall + timedelta(seconds=30)


@pytest.mark.parametrize("elapsed", [0, 16])
def test_begin_cannot_replace_unfinished_or_stalled_work(elapsed):
    clock, progress = tracker()
    progress.begin_step(timeout_seconds=15)
    clock.tick += elapsed
    with pytest.raises(RuntimeError, match="owned"):
        progress.begin_step(timeout_seconds=15)
    assert progress.snapshot().last_progress_at is None


def test_standby_requires_real_reconsideration_within_30_seconds():
    clock, progress = tracker()
    token = progress.begin_step(timeout_seconds=15)
    assert progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=30))
    clock.tick += 31
    assert progress.snapshot().state == "STALLED"
    # A new step may do the overdue local check, but beginning it does not cure the stall.
    token = progress.begin_step(timeout_seconds=15)
    assert progress.snapshot().state == "STALLED"
    clock.wall += timedelta(seconds=31)
    assert progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=30))
    assert progress.snapshot().state == "SCHEDULED"


def test_old_token_and_stopped_owner_cannot_publish_late_completion():
    clock, progress = tracker()
    old = progress.begin_step(timeout_seconds=15)
    progress.complete_step(old, next_wake_at=clock.wall + timedelta(seconds=30))
    current = progress.begin_step(timeout_seconds=15)
    assert not progress.complete_step(old, next_wake_at=clock.wall + timedelta(seconds=30))
    progress.stop()
    assert not progress.complete_step(current, next_wake_at=clock.wall + timedelta(seconds=30))
    snapshot = progress.snapshot()
    assert snapshot.state == "STOPPED"
    assert snapshot.next_wake_at is None and snapshot.progress_due_at is None
    with pytest.raises(RuntimeError, match="stopped"):
        progress.begin_step(timeout_seconds=15)


def test_wall_clock_reversal_cannot_restore_expired_progress():
    clock, progress = tracker()
    token = progress.begin_step(timeout_seconds=15)
    progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=30))
    clock.tick += 31
    clock.wall -= timedelta(hours=1)
    snapshot = progress.snapshot()
    assert snapshot.state == "STALLED"
    assert snapshot.last_progress_at is None  # Never invent a completed time in the new past.
    assert snapshot.runtime_generation == progress.runtime_generation


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), True])
def test_invalid_work_deadline_is_rejected(duration):
    _, progress = tracker()
    with pytest.raises(ValueError):
        progress.begin_step(timeout_seconds=duration)


def test_maintenance_cannot_be_scheduled_beyond_30_seconds():
    clock, progress = tracker()
    token = progress.begin_step(timeout_seconds=15)
    with pytest.raises(ValueError, match="30"):
        progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=31))
    assert progress.snapshot().state == "WORKING"


def test_snapshot_freezes_evidence_before_observing_clocks():
    clock, progress = tracker()
    token = progress.begin_step(timeout_seconds=15)
    progress.complete_step(token, next_wake_at=clock.wall + timedelta(seconds=30))
    # A concurrent owner change after capture must not mix evidence fields.
    def observe_and_stop():
        progress.stop()
        return clock.wall

    progress._clock = observe_and_stop
    snapshot = progress.snapshot()
    assert snapshot.state == "SCHEDULED"
    assert snapshot.next_wake_at == clock.wall + timedelta(seconds=30)
    assert snapshot.progress_due_at == snapshot.next_wake_at
    assert snapshot.last_progress_at == clock.wall
    assert progress.snapshot().state == "STOPPED"
