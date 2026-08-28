"""One-slot asynchronous coordinator backed by one owned worker thread."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
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
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="backtest-job-worker",
        )
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._active_cancellation: CancellationToken | None = None
        self._stopping = False
        self._closed = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

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
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._shutdown_timeout_seconds,
                )
            except TimeoutError as error:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._closed = True
                raise RuntimeError(
                    "backtest coordinator operation violated its shutdown safe boundary"
                ) from error
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._closed = True

    stop = shutdown

    async def _run(self) -> None:
        while not self._stopping:
            claim = self._repository.recover_expired()
            if claim is None:
                claim = self._repository.claim_next()
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

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            self._executor,
            partial(
                self._operations.execute,
                claim,
                cancellation_token=token,
                progress_callback=progress_callback,
            ),
        )
        try:
            while not future.done():
                await asyncio.wait(
                    (future,),
                    timeout=self._heartbeat_interval_seconds,
                )
                if future.done():
                    break
                view = self._repository.get(claim.job_id)
                if self._stopping or (
                    view is not None and view.status is BacktestJobStatus.CANCEL_REQUESTED
                ):
                    token.cancel()
                if not self._repository.heartbeat(claim.job_id, claim_token):
                    token.cancel()
            result = await future
        except BacktestOperationCancelled:
            self._acknowledge_external_cancellation(claim, claim_token)
            return
        except Exception:
            if self._acknowledge_external_cancellation(claim, claim_token):
                return
            if not self._stopping:
                self._repository.fail(
                    claim.job_id,
                    claim_token,
                    "BACKTEST_OPERATION_FAILED",
                    "Backtest operation failed.",
                )
            return
        finally:
            self._active_cancellation = None

        if self._stopping or token.cancelled:
            self._acknowledge_external_cancellation(claim, claim_token)
            return
        if self._acknowledge_external_cancellation(claim, claim_token):
            return
        self._repository.complete(claim.job_id, claim_token, result)

    def _acknowledge_external_cancellation(
        self,
        claim: BacktestJobClaim,
        claim_token: str,
    ) -> bool:
        view = self._repository.get(claim.job_id)
        if view is None or view.status is not BacktestJobStatus.CANCEL_REQUESTED:
            return False
        return self._repository.acknowledge_cancel(claim.job_id, claim_token)


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
