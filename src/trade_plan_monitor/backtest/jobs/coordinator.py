"""One-slot asynchronous coordinator backed by one owned worker thread."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from threading import Lock
from typing import Protocol

from trade_plan_monitor.backtest.control import (
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.jobs.models import (
    BacktestJobClaim,
    BacktestJobPhase,
    BacktestJobResult,
    BacktestJobStatus,
)


class BacktestJobRepositoryPort(Protocol):
    """Repository surface required by the coordinator lifecycle."""

    def claim_next(self) -> BacktestJobClaim | None: ...

    def recover_expired(self) -> BacktestJobClaim | None: ...

    def heartbeat(self, job_id: str, claim_token: str) -> bool: ...

    def update_progress(
        self,
        job_id: str,
        claim_token: str,
        *,
        phase: BacktestJobPhase,
        completed_units: int,
        total_units: int | None = None,
    ) -> bool: ...

    def complete(self, job_id: str, claim_token: str, result: BacktestJobResult) -> bool: ...

    def fail(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> bool: ...

    def acknowledge_cancel(self, job_id: str, claim_token: str) -> bool: ...

    def get(self, job_id: str): ...


class BacktestJobOperationPort(Protocol):
    def execute(
        self,
        claim: BacktestJobClaim,
        *,
        cancellation_token: CancellationToken,
        progress_callback,
    ) -> BacktestJobResult: ...


class _TrackedExecutor(ThreadPoolExecutor):
    def __init__(self, track: Callable[[Future], Future], *, thread_name_prefix: str) -> None:
        super().__init__(max_workers=1, thread_name_prefix=thread_name_prefix)
        self._track = track

    def submit(self, function, /, *args, **kwargs):
        return self._track(super().submit(function, *args, **kwargs))


class BacktestJobCoordinator:
    """Claim durable jobs while all blocking operation work stays on one thread."""

    def __init__(
        self,
        *,
        repository: BacktestJobRepositoryPort,
        operations: BacktestJobOperationPort,
        poll_interval_seconds: float = 0.1,
        heartbeat_interval_seconds: float = 1.0,
        shutdown_timeout_seconds: float = 5.0,
        authorized_job_ids: frozenset[str] | None = None,
    ) -> None:
        required_repository_methods = (
            "claim_next",
            "recover_expired",
            "heartbeat",
            "update_progress",
            "complete",
            "fail",
            "acknowledge_cancel",
            "get",
        )
        if any(
            not callable(getattr(repository, method, None))
            for method in required_repository_methods
        ):
            raise TypeError("repository does not satisfy the coordinator contract")
        if not callable(getattr(operations, "execute", None)):
            raise TypeError("operations must expose execute")
        if authorized_job_ids is not None and (
            not isinstance(authorized_job_ids, frozenset) or len(authorized_job_ids) > 1
        ):
            raise ValueError("explicit authorization requires at most one immutable job ID")
        self._poll_interval_seconds = _bounded_seconds(
            poll_interval_seconds,
            name="poll_interval_seconds",
            maximum=10.0,
        )
        self._heartbeat_interval_seconds = _bounded_seconds(
            heartbeat_interval_seconds,
            name="heartbeat_interval_seconds",
            maximum=10.0,
        )
        self._shutdown_timeout_seconds = _bounded_seconds(
            shutdown_timeout_seconds,
            name="shutdown_timeout_seconds",
            maximum=5.0,
        )
        self._repository = repository
        self._operations = operations
        self._authorization_lock = Lock()
        self._authorized_job_ids = authorized_job_ids
        self._physical_futures: set[Future] = set()
        self._drain_task: asyncio.Task[None] | None = None
        self._shutdown_error: BaseException | None = None
        self._executor = _TrackedExecutor(
            self._track,
            thread_name_prefix="backtest-job-worker",
        )
        self._repository_executor = _TrackedExecutor(
            self._track,
            thread_name_prefix="backtest-job-store",
        )
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._active_cancellation: CancellationToken | None = None
        self._failure: BaseException | None = None
        self._stopping = False
        self._closed = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def authorized_job_ids(self) -> frozenset[str]:
        with self._authorization_lock:
            return self._authorized_job_ids or frozenset()

    @property
    def physically_drained(self) -> bool:
        with self._authorization_lock:
            return not self._physical_futures

    @property
    def accepting(self) -> bool:
        return not self._stopping and not self._closed

    def authorize_jobs(self, job_ids: frozenset[str]) -> None:
        """Thread-safe current-session authority; readiness grants no job IDs."""
        if not isinstance(job_ids, frozenset) or len(job_ids) > 1:
            raise ValueError("explicit authorization requires at most one immutable job ID")
        with self._authorization_lock:
            if self._stopping or self._closed:
                raise RuntimeError("backtest coordinator is stopping")
            if self._authorized_job_ids is not None:
                self._authorized_job_ids = job_ids

    def _track(self, future: Future) -> Future:
        with self._authorization_lock:
            self._physical_futures.add(future)
        future.add_done_callback(self._physical_finished)
        return future

    def _physical_finished(self, future: Future) -> None:
        with self._authorization_lock:
            self._physical_futures.discard(future)

    def raise_if_failed(self) -> None:
        """Fail closed once the owned background task terminates unexpectedly."""

        if self._stopping:
            return
        if self._failure is not None:
            raise RuntimeError("backtest job coordinator failed") from self._failure
        task = self._task
        if task is None or not task.done():
            return
        if task.cancelled():
            raise RuntimeError("backtest job coordinator stopped unexpectedly")
        failure = task.exception()
        if failure is not None:
            raise RuntimeError("backtest job coordinator failed") from failure
        raise RuntimeError("backtest job coordinator stopped unexpectedly")

    async def start(self) -> None:
        """Start one owned coordinator task without claiming work at import time."""

        if self._closed:
            raise RuntimeError("backtest job coordinator is closed")
        if self.running:
            return
        if self._task is not None:
            await self._task
        self._stopping = False
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="backtest-job-coordinator",
        )

    async def shutdown(self) -> None:
        """Stop claims and join resources under the production safe-boundary policy.

        Production composition must bound provider transport, SQLite waits, and
        operation safe boundaries below ``shutdown_timeout_seconds``. A timeout is
        therefore a contract violation; Python cannot safely terminate an arbitrary
        already-running worker thread under the approved single-thread architecture.
        """

        if self._closed:
            return
        self._stopping = True
        if self._wake_event is not None:
            self._wake_event.set()
        if self._active_cancellation is not None:
            self._active_cancellation.cancel()
        if self._drain_task is None:
            self._drain_task = asyncio.create_task(self._drain_and_close())
        try:
            await asyncio.wait_for(
                asyncio.shield(self._drain_task), self._shutdown_timeout_seconds,
            )
        except TimeoutError as error:
            raise RuntimeError(
                "backtest coordinator operation violated its shutdown safe boundary"
            ) from error
        if self._shutdown_error is not None:
            raise self._shutdown_error

    async def _drain_and_close(self) -> None:
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except BaseException as error:
                self._shutdown_error = error
        while not self.physically_drained:
            with self._authorization_lock:
                pending = tuple(self._physical_futures)
            await asyncio.gather(
                *(asyncio.shield(asyncio.wrap_future(future)) for future in pending),
                return_exceptions=True,
            )
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._repository_executor.shutdown(wait=True, cancel_futures=True)
        self._closed = True

    stop = shutdown

    async def _run(self) -> None:
        try:
            while not self._stopping:
                with self._authorization_lock:
                    authorized = self._authorized_job_ids
                recovery = self._repository.recover_expired
                next_claim = self._repository.claim_next
                if authorized is not None:
                    recovery = partial(recovery, authorized_job_ids=authorized)
                    next_claim = partial(next_claim, authorized_job_ids=authorized)
                claim = await self._repository_call(recovery)
                if claim is None:
                    claim = await self._repository_call(next_claim)
                if claim is None:
                    if self._wake_event is None:  # pragma: no cover - start owns initialization
                        raise RuntimeError("coordinator wake event is unavailable")
                    try:
                        await asyncio.wait_for(
                            self._wake_event.wait(),
                            timeout=self._poll_interval_seconds,
                        )
                    except TimeoutError:
                        pass
                    continue
                await self._execute_claim(claim)
                with self._authorization_lock:
                    if self._authorized_job_ids is not None:
                        self._authorized_job_ids -= {claim.job_id}
        except asyncio.CancelledError:
            if self._active_cancellation is not None:
                self._active_cancellation.cancel()
            raise
        except BaseException as error:
            if not self._stopping and self._failure is None:
                self._failure = error
            if self._active_cancellation is not None:
                self._active_cancellation.cancel()
            raise

    async def _execute_claim(self, claim: BacktestJobClaim) -> None:
        token = CancellationToken()
        self._active_cancellation = token
        claim_token = claim.claim_token.get_secret_value()

        def progress_callback(progress: BacktestProgress) -> None:
            phase = _job_phase(progress)
            self._repository.update_progress(
                claim.job_id,
                claim_token,
                phase=phase,
                completed_units=progress.completed_units,
                total_units=progress.total_units,
            )

        future = asyncio.get_running_loop().run_in_executor(
            self._executor,
            partial(
                self._operations.execute,
                claim,
                cancellation_token=token,
                progress_callback=progress_callback,
            ),
        )
        try:
            try:
                while not future.done():
                    await asyncio.wait(
                        (future,),
                        timeout=self._heartbeat_interval_seconds,
                    )
                    if future.done():
                        break
                    view = await self._repository_call(self._repository.get, claim.job_id)
                    if self._stopping or (
                        view is not None and view.status is BacktestJobStatus.CANCEL_REQUESTED
                    ):
                        token.cancel()
                    if not await self._repository_call(
                        self._repository.heartbeat,
                        claim.job_id,
                        claim_token,
                    ):
                        token.cancel()
            except Exception as coordination_error:
                if not self._stopping and self._failure is None:
                    self._failure = coordination_error
                token.cancel()
                await asyncio.gather(asyncio.shield(future), return_exceptions=True)
                raise

            try:
                result = await asyncio.shield(future)
            except BacktestOperationCancelled:
                await self._acknowledge_external_cancellation(claim, claim_token)
                return
            except Exception:
                if await self._acknowledge_external_cancellation(claim, claim_token):
                    return
                if not self._stopping:
                    await self._repository_call(
                        self._repository.fail,
                        claim.job_id,
                        claim_token,
                        "BACKTEST_OPERATION_FAILED",
                        "Backtest operation failed.",
                    )
                return
        finally:
            self._active_cancellation = None

        if self._stopping or token.cancelled:
            await self._acknowledge_external_cancellation(claim, claim_token)
            return
        if await self._acknowledge_external_cancellation(claim, claim_token):
            return
        await self._repository_call(
            self._repository.complete,
            claim.job_id,
            claim_token,
            result,
        )

    async def _acknowledge_external_cancellation(
        self,
        claim: BacktestJobClaim,
        claim_token: str,
    ) -> bool:
        view = await self._repository_call(self._repository.get, claim.job_id)
        if view is None or view.status is not BacktestJobStatus.CANCEL_REQUESTED:
            return False
        return await self._repository_call(
            self._repository.acknowledge_cancel,
            claim.job_id,
            claim_token,
        )

    async def _repository_call[ResultT](
        self,
        function: Callable[..., ResultT],
        /,
        *args: object,
    ) -> ResultT:
        future = asyncio.get_running_loop().run_in_executor(
            self._repository_executor, partial(function, *args),
        )
        return await asyncio.shield(future)


def _job_phase(progress: BacktestProgress) -> BacktestJobPhase:
    if progress.phase.startswith("SYNC_"):
        return BacktestJobPhase.SYNCING_DATA
    if progress.phase.startswith("FREEZE_"):
        return BacktestJobPhase.VERIFYING_DATASET
    if progress.phase in {"RUN_FINALIZE", "RUN_REPORT_HANDOFF"}:
        return BacktestJobPhase.MATERIALIZING_RESULTS
    if progress.phase.startswith("RUN_"):
        return BacktestJobPhase.REPLAYING
    raise AssertionError(f"unhandled backtest operation phase: {progress.phase}")


def _bounded_seconds(value: float, *, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not 0 < normalized <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum:g}")
    return normalized


__all__ = [
    "BacktestJobCoordinator",
    "BacktestJobOperationPort",
    "BacktestJobRepositoryPort",
]
