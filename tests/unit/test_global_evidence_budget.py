"""Pre-allocation ownership, not post-allocation accounting."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from scripts.experiments.global_evidence_budget import Budget, BudgetUnavailable


def test_exact_limit_and_no_partial_reservation():
    assert Budget().limit == 64*1024*1024
    budget = Budget(1024)
    lease = budget.acquire(1024, 'raw')
    assert budget.snapshot()['used'] == 1024
    with pytest.raises(BudgetUnavailable):
        budget.acquire(1, 'work', deadline=monotonic())
    with pytest.raises(BudgetUnavailable):
        budget.acquire(1025, 'work')
    assert budget.snapshot()['used'] == 1024
    lease.close()
    lease.close()
    assert budget.snapshot()['used'] == 0


def test_waiter_cancellation_cannot_refund_owned_bytes():
    budget, cancelled = Budget(10), Event()
    owner = budget.acquire(10, 'raw')
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(budget.acquire, 1, 'work', cancelled=cancelled)
        with budget.condition:
            assert budget.condition.wait_for(lambda: budget.waiters == 1, timeout=3)
        cancelled.set()
        with pytest.raises(BudgetUnavailable):
            pending.result(timeout=3)
    assert budget.snapshot()['used'] == 10
    owner.close()


def test_shutdown_wakes_waiter_but_requires_physical_release():
    budget = Budget(10)
    lease = budget.acquire(10, 'raw')
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(budget.acquire, 1, 'work')
        with budget.condition:
            assert budget.condition.wait_for(lambda: budget.waiters == 1, timeout=3)
        budget.stop()
        with pytest.raises(BudgetUnavailable):
            pending.result(timeout=3)
    with pytest.raises(TimeoutError):
        budget.drain(0.01)
    lease.close()
    budget.drain(0.01)


def test_failed_resource_cleanup_fences_and_keeps_bytes():
    budget = Budget(10)
    lease = budget.acquire(10, 'raw')
    def failed():
        raise OSError('cleanup failed')
    with pytest.raises(OSError):
        lease.close(failed)
    assert budget.snapshot()['used'] == 10
    with pytest.raises(BudgetUnavailable):
        budget.acquire(0, 'work')
    with pytest.raises(TimeoutError):
        budget.drain(0.01)


def test_parallel_exact_reservations_never_cross_limit():
    budget = Budget(8)
    def run(_):
        with budget.acquire(1, 'work'):
            assert budget.snapshot()['used'] <= 8
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(run, range(100)))
    assert budget.snapshot()['used'] == 0
