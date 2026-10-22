"""Bounded local metadata calls with physical drain before resource release."""

import asyncio
from collections.abc import Callable

from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.backtest.thread_ownership import BacktestThreadOwner
from trade_plan_monitor.diagnostics.read_tracing import (
    current_trace,
    new_read_trace,
    read_span,
    trace_point,
    use_read_trace,
)


class BacktestMetadataThread:
    """One physical call; read-only bursts may wait within a finite local bound."""

    def __init__(
        self, *, max_waiting_reads: int = 8, read_wait_seconds: float = 5.0,
        thread_name_prefix: str = "backtest-metadata",
    ) -> None:
        self._owner = BacktestThreadOwner(thread_name_prefix=thread_name_prefix)
        self._gate = asyncio.Lock()
        self._waiting_reads = 0
        self._max_waiting_reads = max_waiting_reads
        self._read_wait_seconds = read_wait_seconds
        self._stopping = False
        self._trace_kind = "result" if thread_name_prefix == "backtest-results" else "metadata"

    @property
    def outstanding_work(self) -> int:
        return self._owner.outstanding_work

    @property
    def occupied(self) -> bool:
        return self._gate.locked() or self._waiting_reads > 0

    async def run[ResultT](
        self, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        if self._stopping or self.occupied:
            raise BacktestServiceUnavailable()
        await self._gate.acquire()
        return await self._invoke(function, *args, **kwargs)

    async def read[ResultT](
        self, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        if self._stopping or self._waiting_reads >= self._max_waiting_reads:
            raise BacktestServiceUnavailable()
        self._waiting_reads += 1
        try:
            with read_span(f"{self._trace_kind}.admission"):
                async with asyncio.timeout(self._read_wait_seconds):
                    await self._gate.acquire()
        except TimeoutError:
            raise BacktestServiceUnavailable() from None
        finally:
            self._waiting_reads -= 1
        if self._stopping:
            self._gate.release()
            raise BacktestServiceUnavailable()
        return await self._invoke(function, *args, **kwargs)

    async def _invoke[ResultT](
        self, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        loop = asyncio.get_running_loop()
        metadata = self._trace_kind == "metadata"
        physical = new_read_trace("metadata.physical") if metadata else current_trace()
        trace_point("worker.submit", **({} if physical is None else {
            "physicalId": physical.trace_id,
        }))

        def invoke():
            # Propagate diagnostic context only, never caller authority/session context.
            with use_read_trace(physical, finish=metadata), read_span("worker.execute", cpu=True):
                return function(*args, **kwargs)

        try:
            future = self._owner.submit(invoke)
        except RuntimeError:
            if metadata and physical is not None:
                physical.finish("error")
            self._gate.release()
            raise BacktestServiceUnavailable() from None
        # Cancellation of the HTTP waiter cannot release physically running work.
        future.add_done_callback(lambda _future: loop.call_soon_threadsafe(self._gate.release))
        return await asyncio.shield(asyncio.wrap_future(future))

    async def stop(self) -> None:
        self._stopping = True
        pending = self._owner.begin_shutdown()
        await asyncio.gather(
            *(asyncio.shield(asyncio.wrap_future(future)) for future in pending),
            return_exceptions=True,
        )
        self._owner.close()


class BacktestResultReadThread(BacktestMetadataThread):
    """Isolate expensive verified reads; overlapping identical reads share work.

    Only in-flight results are shared. Every later request verifies storage again.
    Cancelled HTTP observers cannot release physical work or cancel other readers.
    """

    def __init__(self, *, max_readers: int = 8, read_wait_seconds: float = 60.0) -> None:
        super().__init__(
            max_waiting_reads=max_readers, read_wait_seconds=read_wait_seconds,
            thread_name_prefix="backtest-results",
        )
        self._max_readers = max_readers
        self._readers = 0
        self._shared: dict[tuple[str, ...], asyncio.Task] = {}
        self._shared_trace_ids: dict[tuple[str, ...], str] = {}

    async def read_shared[ResultT](
        self, key: tuple[str, ...], function: Callable[..., ResultT], /,
        *args: object, **kwargs: object,
    ) -> ResultT:
        if self._stopping or self._readers >= self._max_readers:
            raise BacktestServiceUnavailable()
        task = self._shared.get(key)
        joined = task is not None
        if task is None:
            if len(self._shared) >= self._max_readers:
                raise BacktestServiceUnavailable()
            physical = new_read_trace("result.physical")

            async def owned():
                with use_read_trace(physical):
                    return await self.read(function, *args, **kwargs)

            task = asyncio.create_task(owned())
            if physical is not None:
                self._shared_trace_ids[key] = physical.trace_id
            self._shared[key] = task
            task.add_done_callback(lambda finished: self._finished_read(key, finished))
        self._readers += 1
        if (physical_id := self._shared_trace_ids.get(key)) is not None:
            trace_point("result.join", physicalId=physical_id, joined=joined)
        try:
            with read_span("result.observe"):
                return await asyncio.shield(task)
        finally:
            self._readers -= 1

    def _finished_read(self, key: tuple[str, ...], task: asyncio.Task) -> None:
        if self._shared.get(key) is task:
            self._shared.pop(key)
            self._shared_trace_ids.pop(key, None)
        if not task.cancelled():
            task.exception()  # Observe errors even when every HTTP observer left.

    async def stop(self) -> None:
        await super().stop()
        await asyncio.gather(*tuple(self._shared.values()), return_exceptions=True)
