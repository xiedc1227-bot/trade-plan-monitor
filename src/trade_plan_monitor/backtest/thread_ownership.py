"""Track physical futures separately from cancelled asyncio waiters."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock


class BacktestThreadOwner:
    """One lazy preparation thread and at most one outstanding physical call."""

    def __init__(self, *, thread_name_prefix: str = "backtest-service") -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set[Future] = set()
        self._lock = Lock()
        self._closed = False
        self._thread_name_prefix = thread_name_prefix

    @property
    def outstanding_work(self) -> int:
        with self._lock:
            return len(self._futures)

    def submit[ResultT](self, function: Callable[[], ResultT]) -> Future[ResultT]:
        with self._lock:
            if self._closed or self._futures:
                raise RuntimeError("backtest preparation owner is closed or occupied")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=self._thread_name_prefix,
                )
            future = self._executor.submit(function)
            self._futures.add(future)
        future.add_done_callback(self._finished)
        return future

    def _finished(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def close(self) -> None:
        """Release a drained executor; never dispose ownership of running work."""
        with self._lock:
            if self._futures:
                raise RuntimeError("backtest preparation has not physically drained")
            self._closed = True
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def begin_shutdown(self) -> tuple[Future, ...]:
        with self._lock:
            self._closed = True
            return tuple(self._futures)
