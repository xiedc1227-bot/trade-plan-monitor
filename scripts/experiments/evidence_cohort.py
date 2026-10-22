"""P0 funded cohorts and bounded diagnostic timeline, isolated from production."""

from concurrent.futures import Future
from dataclasses import dataclass
from itertools import zip_longest
from threading import Condition, get_ident
from time import monotonic

from scripts.experiments.bounded_codec import AdmissionError
from scripts.experiments.global_evidence_budget import MIB, BudgetUnavailable
from scripts.experiments.global_evidence_scan import META_BYTES

from trade_plan_monitor.state.index_evidence_flights import _consume, _outcome


@dataclass
class Flight:
    scope: tuple
    rows: list
    lease: object
    future: Future
    users: int = 1


class Flights:
    def __init__(self, budget, worker=None, *, funded=True):
        self.budget, self.worker = budget, worker
        self.condition = Condition()
        self.active = None
        self.funded = funded
        self.waiting, self.pending, self.prepaid = {}, set(), {}
        self.events = []
        self.busy = self.closing = False
        self.calls = self.queued = 0
        self.stats = dict(proofs=0, joins=0, mismatches=0, fallbacks=0)

    def event(self, name, **fields):
        with self.condition:
            if len(self.events) < 4096:
                self.events.append(dict(at=monotonic(), thread=get_ident(), name=name, **fields))

    def done(self, scan):
        with self.condition:
            lease = self.prepaid.pop(id(scan), None)
            if lease:
                lease.close()
            self.pending.discard(id(scan))
            self.condition.notify_all()

    def fund(self, scope):
        if not self.funded:
            return
        # No waits while holding coordinator locks. Existing budget waiters take precedence.
        for key, (requested, scan, size) in tuple(self.waiting.items()):
            if requested != scope:
                continue
            try:
                self.check(scan)
                with self.budget.condition:
                    if self.budget.queue or self.budget.used+size > self.budget.limit:
                        continue
                    lease = scan.acquire(size, 'scan')
            except BudgetUnavailable:
                continue
            self.prepaid[key] = lease
            self.pending.add(key)
        self.event('cohort.sealed', members=len(self.pending))

    def release(self, flight):
        with self.condition:
            flight.users -= 1
            if not flight.users:
                flight.rows.clear()
                flight.lease.close()
            self.condition.notify_all()

    def check(self, scan):
        scan.check()
        if self.closing:
            raise BudgetUnavailable('proof admission closed')

    def stop(self):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        self.budget.stop()

    def drain(self, timeout=15):
        with self.condition:
            if not self.condition.wait_for(lambda: self.calls == 0 and not self.busy, timeout):
                raise TimeoutError('physical proof not drained')
        self.budget.drain(timeout)

    def run(self, scope, scan, verify, codes):
        with self.condition:
            self.check(scan)
            if self.calls >= 8:
                raise BudgetUnavailable('reader limit')
            self.calls += 1
        try:
            with scan.metadata():
                self.event("preflight.start")
                raw, work, _ = scan.measure()
                self.event("preflight.end", raw=raw, work=work)
                return self._run(scope, scan, verify, codes, raw, work)
        finally:
            with self.condition:
                self.calls -= 1
                self.condition.notify_all()

    def _compare(self, flight, scan, work):
        missing = object()
        iterator = scan.rows(work)
        try:
            for expected, actual in zip_longest(flight.rows, iterator, fillvalue=missing):
                self.check(scan)
                if expected is missing or actual is missing or not expected.exact(actual):
                    return False
            return True
        finally:
            iterator.close()

    def _run(self, scope, scan, verify, codes, raw, work_size):
        try:
            return self._run_body(scope, scan, verify, codes, raw, work_size)
        finally:
            self.done(scan)

    def _run_body(self, scope, scan, verify, codes, raw, work_size):
        # Acquisition precedes pinning. Leaders never wait for pending comparisons.
        with self.condition:
            self.waiting[id(scan)] = (scope, scan, work_size)
            self.condition.notify_all()
            try:
                while self.busy and self.active is None:
                    self.check(scan)
                    self.condition.wait(0.025)
            finally:
                self.waiting.pop(id(scan), None)
            prepaid = self.prepaid.get(id(scan))
        self.event('workspace.wait')
        with prepaid if prepaid is not None else scan.acquire(work_size, 'scan') as work:
            self.event('workspace.granted')
            with self.condition:
                flight = self.active
                if flight and flight.scope == scope and not flight.future.done():
                    flight.users += 1
                else:
                    flight = None
            if flight:
                try:
                    self.event("compare.start")
                    equal = self._compare(flight, scan, work)
                    with self.condition:
                        joined = equal and not flight.future.done()
                        self.event('compare.end', equal=equal, joined=joined,
                                   completed=flight.future.done())
                        self.stats['joins' if joined else 'mismatches'] += 1
                        self.condition.notify_all()
                finally:
                    self.release(flight)
            else:
                joined = False
        # No SQL workspace or raw pin remains while waiting for a proof/owner.
        self.done(scan)
        if joined:
            with self.condition:
                while not flight.future.done():
                    self.check(scan)
                    self.condition.wait(0.025)
            return _consume(flight.future.result())
        with self.condition:
            self.check(scan)
            if self.busy:
                if self.queued:
                    self.event('queue.rejected')
                    raise BudgetUnavailable('owner queue full')
                self.queued += 1
                try:
                    while self.busy:
                        self.check(scan)
                        self.condition.wait(0.025)
                finally:
                    self.queued -= 1
            self.check(scan)
            self.busy = True
        try:
            with scan.acquire(work_size, 'scan') as work:
                return self._lead(scope, scan, verify, codes, raw, work)
        finally:
            with self.condition:
                self.busy = False
                self.active = None
                self.condition.notify_all()

    def _lead(self, scope, scan, verify, codes, raw, work):
        transport = 16*MIB if self.worker else 0
        self.stats['proofs'] += 1
        # Leave progress room for every admitted small scanner, including old borrowers.
        if raw+transport+work.size+7*MIB+8*META_BYTES > self.budget.limit:
            self.stats['fallbacks'] += 1
            return verify(scan.rows(work))
        lease = scan.acquire(raw+transport, 'raw_transport')
        rows, flight = [], None
        try:
            iterator = scan.rows(work)
            try:
                rows.extend(iterator)
            finally:
                iterator.close()
            flight = Flight(scope, rows, lease, Future())
            with self.condition:
                self.active = flight
                self.fund(scope)
                self.event('input.published')
                self.condition.notify_all()
                while self.pending:
                    # Stop waiting at the original boundary; physical cleanup remains owned.
                    if self.closing or monotonic() >= scan.deadline:
                        break
                    self.condition.wait(0.025)

            def physical(values):
                if self.worker:
                    # ChunkWorker's tuple view is charged in the conservative raw bound.
                    try:
                        return self.worker.validate(tuple(values), codes)
                    except AdmissionError:
                        # No child submission occurred; retain the same exact collected input.
                        self.stats['fallbacks'] += 1
                return verify(iter(rows))

            self.event("physical.start")
            outcome = _outcome(physical, iter(rows))
            self.event("physical.end")
            if self.worker and self.worker.retained_bytes:
                # A failed worker cleanup must not be refunded by the outer ledger.
                lease.failed = True
                self.budget.stop()
            with self.condition:
                flight.future.set_result(outcome)
                self.condition.notify_all()
        finally:
            if flight is not None:
                self.release(flight)
            else:
                rows.clear()
                lease.close()
        return _consume(outcome)
