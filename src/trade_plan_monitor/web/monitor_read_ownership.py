"""Own physical monitor reads independently of HTTP/socket observers."""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event
from time import monotonic

from trade_plan_monitor.state.index_evidence_flights import EvidenceUnavailable


@dataclass(frozen=True)
class ReadLease:
    cancelled: Event
    deadline: float


current_read_lease: ContextVar[ReadLease | None] = ContextVar("monitor_read_lease", default=None)


class MonitorReadOwner:
    def __init__(self, *, maximum=8, wait_seconds=15):
        self._maximum, self._wait_seconds = maximum, wait_seconds
        self._closing = False
        self._storage_pauses = set()
        self._tasks = set()

    @property
    def outstanding_work(self):
        return len(self._tasks)

    def begin_shutdown(self):
        self._closing = True

    def pause_storage(self, owner):
        self._storage_pauses.add(owner)

    def resume_storage(self, owner):
        self._storage_pauses.discard(owner)

    def _finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def run(self, operation):
        if self._closing or self._storage_pauses or len(self._tasks) >= self._maximum:
            raise EvidenceUnavailable("Monitor read admission is closed or full")
        lease = ReadLease(Event(), monotonic() + self._wait_seconds)

        async def owned():
            token = current_read_lease.set(lease)
            try:
                return await operation()
            finally:
                current_read_lease.reset(token)

        task = asyncio.create_task(owned())
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        observer = asyncio.get_running_loop().create_future()

        def deliver(completed):
            if observer.done():
                return
            if completed.cancelled():
                observer.cancel()
            elif (error := completed.exception()) is not None:
                observer.set_exception(error)
            else:
                observer.set_result(completed.result())

        task.add_done_callback(deliver)
        try:
            # Cancel only this observer. The owned task observes its own final exception.
            return await observer
        except asyncio.CancelledError:
            lease.cancelled.set()
            raise
        finally:
            task.remove_done_callback(deliver)
            if observer.done() and not observer.cancelled():
                observer.exception()

    async def stop(self, *, timeout):
        self.begin_shutdown()
        await self.drain(timeout=timeout)

    async def drain(self, *, timeout):
        if self._tasks:
            await asyncio.wait_for(asyncio.shield(asyncio.gather(
                *tuple(self._tasks), return_exceptions=True,
            )), timeout=timeout)
