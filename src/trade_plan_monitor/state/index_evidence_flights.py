"""Bounded synchronous evidence flights; no completed-result cache or ORM state."""

from concurrent.futures import Future
from dataclasses import dataclass
from itertools import zip_longest
from threading import Condition
from time import monotonic

from trade_plan_monitor.diagnostics.read_tracing import (
    current_trace,
    read_span,
    read_timed,
    read_trace,
    trace_point,
)


class EvidenceUnavailable(RuntimeError):
    """Evidence admission/cancellation cannot certify a result."""


@dataclass
class _Flight:
    scope: tuple
    rows: tuple
    size: int
    future: Future
    users: int = 1
    trace_id: str | None = None


def _outcome(verify, values):
    try:
        with read_span("index.validate", cpu=True):
            return verify(values), None
    except BaseException as error:
        # Futures never retain validator tracebacks (and their complete raw input).
        return None, (type(error), str(error)[:512])


def _consume(outcome):
    result, failure = outcome
    if failure is not None:
        error_type, message = failure
        try:
            error = error_type(message)
        except Exception:
            error = EvidenceUnavailable("Evidence verification failed")
        raise error from None
    return result


class IndexEvidenceFlights:
    """One physical validator; exact comparisons borrow immutable input leases."""

    def __init__(self, *, max_bytes=64 * 1024 * 1024, max_reads=8, wait_seconds=15):
        self._condition = Condition()
        self._max_bytes, self._max_reads = max_bytes, max_reads
        self._wait_seconds = wait_seconds
        self._closing = self._busy = False
        self._collecting = self._active = None
        self._calls = self._queued = self._retained = 0
        self._collect_waiters = 0
        self._counts = dict(physical_validations=0, joins=0, mismatches=0, budget_fallbacks=0)
        self._peak_retained = 0

    def snapshot(self):
        with self._condition:
            return {**self._counts, "active_calls": self._calls, "queued_owners": self._queued,
                    "retained_bytes": self._retained, "peak_retained_bytes": self._peak_retained}

    def begin_shutdown(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()

    def drain(self, *, timeout):
        with self._condition:
            if not self._condition.wait_for(
                lambda: self._calls == 0 and not self._busy and self._retained == 0,
                timeout=timeout,
            ):
                raise TimeoutError("Index evidence work has not physically drained")

    def _check(self, cancelled, deadline):
        if self._closing or (cancelled is not None and cancelled.is_set()):
            raise EvidenceUnavailable("Evidence read is no longer admitted")
        if monotonic() >= deadline:
            raise EvidenceUnavailable("Evidence read waiting deadline elapsed")

    def _release(self, flight):
        with self._condition:
            flight.users -= 1
            if flight.users == 0:
                flight.rows = ()
                self._retained -= flight.size
            self._condition.notify_all()

    @read_timed("index.compare")
    def _compare(self, flight, scan, cancelled, deadline):
        iterator = iter(scan())
        missing = object()
        try:
            for expected, actual in zip_longest(flight.rows, iterator, fillvalue=missing):
                self._check(cancelled, deadline)
                if expected is missing or actual is missing or not expected.exact(actual):
                    return False
            return True
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()

    def run(self, scope, scan, verify, *, cancelled=None, deadline=None):
        deadline = min(
            monotonic() + self._wait_seconds,
            float("inf") if deadline is None else deadline,
        )
        with self._condition:
            self._check(cancelled, deadline)
            if self._calls >= self._max_reads:
                raise EvidenceUnavailable("Too many owned evidence reads")
            self._calls += 1
        try:
            return self._run(scope, scan, verify, cancelled, deadline)
        finally:
            with self._condition:
                self._calls -= 1
                self._condition.notify_all()

    def _run(self, scope, scan, verify, cancelled, deadline):
        with self._condition:
            if self._busy and self._collecting == scope:
                self._collect_waiters += 1
                self._condition.notify_all()
                try:
                    with read_span("index.wait"):
                        while self._busy and self._collecting == scope:
                            self._check(cancelled, deadline)
                            self._condition.wait(0.05)
                finally:
                    self._collect_waiters -= 1
            flight = self._active
            if flight is not None and flight.scope == scope and not flight.future.done():
                flight.users += 1
            else:
                flight = None
        if flight is not None:
            try:
                equal = self._compare(flight, scan, cancelled, deadline)
                with self._condition:
                    join = equal and not flight.future.done()
                    self._counts["joins" if join else "mismatches"] += 1
                    self._condition.notify_all()
            finally:
                self._release(flight)
            if join:
                if flight.trace_id is not None:
                    trace_point("index.join", physicalId=flight.trace_id, joined=True)
                with read_span("index.wait"), self._condition:
                    while not flight.future.done():
                        self._check(cancelled, deadline)
                        self._condition.wait(0.05)
                return _consume(flight.future.result())

        with self._condition:
            self._check(cancelled, deadline)
            if self._busy:
                if self._queued:
                    raise EvidenceUnavailable("Evidence validation queue is full")
                self._queued += 1
                self._condition.notify_all()
                try:
                    with read_span("index.wait"):
                        while self._busy:
                            self._check(cancelled, deadline)
                            self._condition.wait(0.05)
                finally:
                    self._queued -= 1
            self._check(cancelled, deadline)
            self._busy, self._collecting = True, scope
        return self._lead(scope, scan, verify, cancelled, deadline)

    def _lead(self, scope, scan, verify, cancelled, deadline):
        with read_trace("index.physical"):
            return self._lead_owned(scope, scan, verify, cancelled, deadline)

    def _lead_owned(self, scope, scan, verify, cancelled, deadline):
        buffer, size, flight = [], 0, None
        iterator = None
        try:
            iterator = iter(scan())
            fallback = False
            with read_span("index.collect", cpu=True):
                for candidate in iterator:
                    self._check(cancelled, deadline)
                    required = candidate.retained_size()
                    with self._condition:
                        if self._retained + required > self._max_bytes:
                            fallback = True
                            self._counts["budget_fallbacks"] += 1
                            break
                        self._retained += required
                        self._peak_retained = max(self._peak_retained, self._retained)
                        size += required
                    buffer.append(candidate)
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
            if fallback:
                buffer.clear()
                with self._condition:
                    self._retained -= size
                    size = 0
                    self._collecting = None
                    self._counts["physical_validations"] += 1
                    self._condition.notify_all()
                trace_point("index.fallback")
                with read_span("index.validate", cpu=True):
                    return verify(scan())

            flight = _Flight(scope, tuple(buffer), size, Future())
            trace = current_trace()
            flight.trace_id = None if trace is None else trace.trace_id
            trace_point("index.input", count=len(buffer), bytes=size)
            buffer.clear()
            with self._condition:
                self._active, self._collecting = flight, None
                self._counts["physical_validations"] += 1
                self._condition.notify_all()
                # Finish comparisons already waiting on input collection before CPU validation.
                # No completed proof is held open; new arrivals still face the completion fence.
                with read_span("index.wait"):
                    while self._collect_waiters or flight.users > 1:
                        if self._closing or monotonic() >= deadline:
                            break
                        self._condition.wait(0.05)
            outcome = _outcome(verify, iter(flight.rows))
            with self._condition:
                flight.future.set_result(outcome)
                self._condition.notify_all()
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
            buffer.clear()
            with self._condition:
                self._active = self._collecting = None
                self._busy = False
                if flight is None:
                    self._retained -= size
                self._condition.notify_all()
            if flight is not None:
                self._release(flight)
        return _consume(outcome)
