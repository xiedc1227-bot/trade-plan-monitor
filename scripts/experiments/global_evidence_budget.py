"""P0 application-injected byte leases. Never registered in production."""

from collections import defaultdict, deque
from threading import Condition
from time import monotonic

MIB = 1024 * 1024


class BudgetUnavailable(RuntimeError):
    """No allocation or successful proof is authorized."""


class Lease:
    def __init__(self, budget, size, category):
        self.budget, self.size, self.category = budget, size, category
        self.closed = self.failed = False

    def close(self, cleanup=None):
        if self.closed or self.failed:
            return
        try:
            if cleanup is not None:
                cleanup()
        except BaseException:
            self.failed = True
            self.budget.stop()
            raise
        with self.budget.condition:
            self.budget.used -= self.size
            self.budget.categories[self.category] -= self.size
            self.closed = True
            self.budget.condition.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Budget:
    def __init__(self, limit=64*MIB):
        self.limit = limit
        self.condition = Condition()
        self.used = self.peak = self.waiters = 0
        self.wait_seconds = 0.0
        self.categories, self.peaks = defaultdict(int), defaultdict(int)
        self.queue, self.closing = deque(), False

    def acquire(self, size, category, *, cancelled=None, deadline=None):
        if type(size) is not int or size < 0 or size > self.limit:
            raise BudgetUnavailable('unadmittable allocation')
        deadline = monotonic()+15 if deadline is None else deadline
        started, ticket = monotonic(), object()
        with self.condition:
            self.queue.append(ticket)
            self.waiters += 1
            self.condition.notify_all()
            try:
                while True:
                    if (self.closing or monotonic() >= deadline
                            or (cancelled is not None and cancelled.is_set())):
                        raise BudgetUnavailable('allocation admission closed')
                    if self.queue[0] is ticket and self.used+size <= self.limit:
                        self.used += size
                        self.categories[category] += size
                        self.peak = max(self.peak, self.used)
                        self.peaks[category] = max(self.peaks[category], self.categories[category])
                        return Lease(self, size, category)
                    self.condition.wait(min(0.025, max(0, deadline-monotonic())))
            finally:
                self.queue.remove(ticket)
                self.waiters -= 1
                self.wait_seconds += monotonic()-started
                self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.closing = True
            self.condition.notify_all()

    def drain(self, timeout=15):
        with self.condition:
            if not self.condition.wait_for(lambda: self.used == 0 and self.waiters == 0, timeout):
                raise TimeoutError('byte owners have not drained')

    def snapshot(self):
        with self.condition:
            return dict(used=self.used, peak=self.peak, categories=dict(self.categories),
                        peaks=dict(self.peaks), waiters=self.waiters, waitSeconds=self.wait_seconds)
