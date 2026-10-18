"""Bounded local metadata calls with physical drain before resource release."""

import asyncio
from collections.abc import Callable
from functools import partial

from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.backtest.thread_ownership import BacktestThreadOwner


class BacktestMetadataThread:
    """One physical call; read-only bursts may wait within a finite local bound."""

    def __init__(self, *, max_waiting_reads: int = 8, read_wait_seconds: float = 5.0) -> None:
        self._owner = BacktestThreadOwner(thread_name_prefix="backtest-metadata")
        self._gate = asyncio.Lock()
        self._waiting_reads = 0
        self._max_waiting_reads = max_waiting_reads
        self._read_wait_seconds = read_wait_seconds
        self._stopping = False

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
        try:
            future = self._owner.submit(partial(function, *args, **kwargs))
        except RuntimeError:
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
