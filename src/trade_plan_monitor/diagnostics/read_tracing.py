"""Short-lived, allowlisted read traces; observation cannot authorize a read."""

import asyncio
import inspect
import json
import os
import re
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from logging import LogRecord
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import perf_counter_ns, thread_time_ns, time_ns
from uuid import uuid4

_ENTRIES = frozenset({
    "http.result", "http.monitor", "http.backtest", "monitor.read",
    "metadata.physical", "result.physical", "monitor.heartbeat", "monitor.socket",
    "index.physical",
})
_STAGES = frozenset({
    "http.headers", "http.body", "metadata.admission", "metadata.observe",
    "result.admission", "result.observe", "result.join", "worker.submit", "worker.execute",
    "result.service", "result.input", "result.publication", "result.copied_input",
    "result.report", "result.audit", "result.public_validation", "result.endpoint_return",
    "monitor.authority_before", "monitor.authority_after", "monitor.snapshot",
    "monitor.activation_reread", "monitor.observe",
    "socket.accept", "socket.disconnect", "socket.terminal", "socket.heartbeat_admission",
    "socket.observer_cancelled", "socket.children_drained",
    "authority.health", "authority.delivery", "authority.configuration",
    "authority.progress", "authority.dependencies", "authority.plans",
    "index.scan", "index.collect", "index.compare", "index.wait", "index.validate",
    "index.input", "index.join", "index.fallback", "monitor.loop_lag",
})
_TRACE: ContextVar[ReadTrace | None] = ContextVar("read_trace", default=None)
trace_window: ContextVar[ReadTraceWindow | None] = ContextVar("read_trace_window", default=None)


class _QuietRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # Observation failure must neither leak file paths nor affect business work.
        pass


class ReadTraceWindow:
    def __init__(
        self, *, directory: Path | None = None, max_traces: int = 1024,
        max_active: int = 64, max_spans: int = 64,
    ):
        if not (1 <= max_traces <= 1024 and 1 <= max_active <= 64 and 1 <= max_spans <= 64):
            raise ValueError("diagnostic bounds exceeded")
        self.records = deque(maxlen=128)
        self._deadline_ns = perf_counter_ns() + 1800 * 10**9
        self._maximum, self._max_active, self.max_spans = max_traces, max_active, max_spans
        self._admitted = self._active = 0
        self._lock = Lock()
        self._handler = None
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            self._handler = _QuietRotatingHandler(
                directory / "read-traces.jsonl", maxBytes=1024**2, backupCount=2,
                encoding="utf-8", delay=True,
            )

    @property
    def active(self):
        with self._lock:
            return self._active

    def start(self, entry: str, parent_id: str | None = None):
        try:
            if entry not in _ENTRIES:
                return None
            with self._lock:
                if (perf_counter_ns() >= self._deadline_ns or self._admitted >= self._maximum
                        or self._active >= self._max_active):
                    return None
                trace = ReadTrace(self, entry, parent_id)
                self._admitted += 1
                self._active += 1
                return trace
        except Exception:
            return None

    def _complete(self, record):
        try:
            with self._lock:
                self._active -= 1
                self.records.append(record)
            self._write(record)
        except Exception:
            pass

    def _write(self, record):
        text = json.dumps(record, separators=(",", ":"), ensure_ascii=True)
        if len(text.encode("utf-8")) <= 16384 and self._handler is not None:
            self._handler.handle(LogRecord("read_trace", 20, "", 0, text, (), None))

    def close(self):
        try:
            if self._handler is not None:
                self._handler.close()
        except Exception:
            pass


class ReadTrace:
    def __init__(self, window: ReadTraceWindow, entry: str, parent_id: str | None):
        self.window, self.entry = window, entry
        self.trace_id, self.parent_id = uuid4().hex, parent_id
        self.started_ns = perf_counter_ns()
        self.started_epoch_ns = time_ns()
        self._spans, self._dropped, self._finished = [], 0, False
        self._lock = Lock()

    def add(
        self, stage: str, start_ns: int, end_ns: int, *,
        cpu_ns: int | None = None, status: str = "ok", **fields,
    ):
        try:
            if stage not in _STAGES or status not in {"ok", "error", "cancelled"}:
                return
            safe = {}
            for key, value in fields.items():
                if key == "physicalId" and isinstance(value, str) and re.fullmatch(
                    r"[0-9a-f]{32}", value,
                ):
                    safe[key] = value
                elif key == "joined" and type(value) is bool:
                    safe[key] = value
                elif key in {"count", "bytes", "statusCode", "activeNs"} and type(value) is int:
                    safe[key] = max(0, min(value, 2**53 - 1))
            span = {"stage": stage, "startNs": start_ns, "endNs": end_ns,
                    "status": status, **safe}
            if cpu_ns is not None:
                span["threadCpuNs"] = cpu_ns
            with self._lock:
                if self._finished:
                    return
                if len(self._spans) < self.window.max_spans:
                    self._spans.append(span)
                else:
                    self._dropped += 1
        except Exception:
            pass

    def finish(self, status="ok"):
        try:
            with self._lock:
                if self._finished:
                    return
                self._finished = True
                record = dict(
                    traceId=self.trace_id, parentId=self.parent_id, entry=self.entry,
                    startedNs=self.started_ns, endedNs=perf_counter_ns(), status=status,
                    startedEpochNs=self.started_epoch_ns,
                    spans=self._spans, droppedSpans=self._dropped,
                )
            self.window._complete(record)
        except Exception:
            pass


def configured_trace_window():
    directory = os.environ.get("TPM_READ_TRACE_DIR")
    if not directory:
        return None
    try:
        return ReadTraceWindow(directory=Path(directory))
    except Exception:
        return None


def current_trace():
    return _TRACE.get()


def new_read_trace(entry: str):
    parent = current_trace()
    window = parent.window if parent is not None else trace_window.get()
    return None if window is None else window.start(
        entry, None if parent is None else parent.trace_id,
    )


@contextmanager
def use_read_trace(trace, *, finish: bool = True):
    token = _TRACE.set(trace)
    status = "ok"
    try:
        yield trace
    except BaseException as error:
        status = "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
        raise
    finally:
        _TRACE.reset(token)
        if trace is not None and finish:
            trace.finish(status)


@contextmanager
def read_trace(entry: str, *, window: ReadTraceWindow | None = None):
    parent = current_trace()
    target = window or (parent.window if parent is not None else trace_window.get())
    trace = None if target is None else target.start(
        entry, None if parent is None else parent.trace_id,
    )
    with use_read_trace(trace):
        yield trace


@contextmanager
def read_span(stage: str, *, cpu: bool = False):
    trace = current_trace()
    if trace is None:
        yield
        return
    start, cpu_start, status = perf_counter_ns(), thread_time_ns() if cpu else None, "ok"
    try:
        yield
    except BaseException as error:
        status = "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
        raise
    finally:
        trace.add(stage, start, perf_counter_ns(), status=status,
                  cpu_ns=None if cpu_start is None else thread_time_ns() - cpu_start)


def trace_point(stage: str, **fields):
    trace = current_trace()
    if trace is not None:
        now = perf_counter_ns()
        trace.add(stage, now, now, **fields)


def read_timed(stage: str):
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                with read_span(stage):
                    return await function(*args, **kwargs)
            return asynchronous

        @wraps(function)
        def synchronous(*args, **kwargs):
            with read_span(stage, cpu=True):
                return function(*args, **kwargs)
        return synchronous
    return decorate


def trace_scan(values):
    """Aggregate iterator advance cost; never count time spent in its consumer as CPU."""
    trace = current_trace()
    if trace is None:
        return values

    def scan():
        start, active, cpu, count, status = perf_counter_ns(), 0, 0, 0, "ok"
        iterator = iter(values)
        try:
            while True:
                before, cpu_before = perf_counter_ns(), thread_time_ns()
                try:
                    value = next(iterator)
                except StopIteration:
                    return
                finally:
                    active += perf_counter_ns() - before
                    cpu += thread_time_ns() - cpu_before
                count += 1
                yield value
        except BaseException as error:
            status = (
                "cancelled"
                if isinstance(error, (GeneratorExit, asyncio.CancelledError)) else "error"
            )
            raise
        finally:
            try:
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
            finally:
                trace.add("index.scan", start, perf_counter_ns(), cpu_ns=cpu,
                          status=status, count=count, activeNs=active)
    return scan()


@contextmanager
def observe_loop_lag():
    """One aggregate per owned read; a loop timer needs no detached cleanup task."""
    trace = current_trace()
    if trace is None:
        yield
        return
    loop = asyncio.get_running_loop()
    interval = 50_000_000
    worst_start = worst_end = perf_counter_ns()
    due = worst_start + interval
    samples, handle = 0, None

    def sample():
        nonlocal due, worst_start, worst_end, samples
        try:
            now = perf_counter_ns()
            if now >= due:
                samples += 1
                if now - due > worst_end - worst_start:
                    worst_start, worst_end = due, now
            due = now + interval
        except Exception:
            pass

    try:
        def tick():
            nonlocal handle
            sample()
            try:
                handle = loop.call_later(interval / 1e9, tick)
            except Exception:
                pass

        handle = loop.call_later(interval / 1e9, tick)
    except Exception:
        handle = None
    try:
        yield
    finally:
        if handle is not None:
            handle.cancel()
        sample()
        trace.add("monitor.loop_lag", worst_start, worst_end, count=samples)
