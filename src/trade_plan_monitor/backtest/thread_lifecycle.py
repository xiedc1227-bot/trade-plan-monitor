"""Bounded local metadata calls with physical drain before resource release."""

import asyncio
from collections.abc import Callable
from functools import partial

from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.backtest.thread_ownership import BacktestThreadOwner


class BacktestMetadataThread:
    """One owned query thread; excess work is rejected instead of queued without a bound."""

    def __init__(self) -> None:
        self._owner = BacktestThreadOwner(thread_name_prefix="backtest-metadata")

    @property
    def outstanding_work(self) -> int:
        return self._owner.outstanding_work

    async def run[ResultT](
        self, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        try:
            future = self._owner.submit(partial(function, *args, **kwargs))
        except RuntimeError:
            raise BacktestServiceUnavailable() from None
        return await asyncio.shield(asyncio.wrap_future(future))

    async def stop(self) -> None:
        pending = self._owner.begin_shutdown()
        await asyncio.gather(
            *(asyncio.shield(asyncio.wrap_future(future)) for future in pending),
            return_exceptions=True,
        )
        self._owner.close()
