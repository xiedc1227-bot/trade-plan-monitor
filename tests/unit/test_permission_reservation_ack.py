"""A durable permission reservation acknowledges once before physical work."""

import asyncio
import threading
from datetime import timedelta

import pytest
from test_request_recovery_admission import Clock, controller, fail

from trade_plan_monitor.market_data.tushare import TushareErrorCode
from trade_plan_monitor.runtime.request_control import (
    PermissionReservationCallbackError,
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
    TushareOperation,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpointError,
)

OPERATION = TushareOperation.DAILY_BARS


def _bound(tmp_path, repository_type=ProviderRecoveryRepository):
    engine = create_sqlite_engine(tmp_path / "reservation-ack.db")
    upgrade_database(engine)
    repository = repository_type(
        create_session_factory(engine), provider_identity="a" * 64,
    )
    clock = Clock()
    return engine, repository, clock, controller(clock, repository)


async def _block(control) -> None:
    with pytest.raises(RequestControlError) as caught:
        await control.execute(
            OPERATION, lambda: fail(TushareErrorCode.BLOCKED_PERMISSION),
            work_key="stock",
        )
    assert caught.value.code is RequestControlErrorCode.BLOCKED_PERMISSION


def test_ack_observes_independent_session_commit_before_sdk_and_coalesces_cancelled_waiter(
    tmp_path,
) -> None:
    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path)
        started, release = threading.Event(), threading.Event()
        sdk_starts: list[str] = []
        acknowledgements: list[str] = []

        def probe() -> str:
            sdk_starts.append("sdk")
            started.set()
            release.wait(3)
            return "allowed"

        def first_ack() -> None:
            assert sdk_starts == []
            persisted = next(
                row for row in repository.load()
                if row.kind == "permission" and row.scope_key == OPERATION.value
            )
            assert persisted.retry_at == clock.now() + timedelta(seconds=300)
            acknowledgements.append("first")

        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            first = asyncio.create_task(control.recheck_permission(
                OPERATION, probe, work_key="stock", on_reserved=first_ack,
            ))
            assert await asyncio.to_thread(started.wait, 1)
            second = asyncio.create_task(control.recheck_permission(
                OPERATION, probe, work_key="stock",
                on_reserved=lambda: acknowledgements.append("second"),
            ))
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            assert await second == "allowed"
            assert sdk_starts == ["sdk"]
            assert acknowledgements == ["first"]
        finally:
            release.set()
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ("raise", "value", "awaitable"))
def test_ack_fault_is_sanitized_after_durable_save_without_sdk_or_controller_fault(
    tmp_path, outcome,
) -> None:
    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path)
        sdk_starts: list[str] = []

        async def awaitable_result():
            return None

        def bad_ack():
            if outcome == "raise":
                raise RuntimeError("private provider token should never escape")
            if outcome == "value":
                return "private provider token should never escape"
            return awaitable_result()

        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            with pytest.raises(PermissionReservationCallbackError) as caught:
                await control.recheck_permission(
                    OPERATION, lambda: sdk_starts.append("sdk"),
                    work_key="stock", on_reserved=bad_ack,
                )
            assert str(caught.value) == "permission reservation callback failed"
            assert caught.value.__cause__ is None
            assert caught.value.__context__ is None
            assert sdk_starts == []
            assert control.repository_bound
            assert not control._closed
            assert not control._recovery_fault
            assert control.is_permission_blocked(OPERATION)
            assert control.raw_permission_retry_at(OPERATION) == (
                clock.now() + timedelta(seconds=300)
            )
            assert next(
                row.retry_at for row in repository.load()
                if row.kind == "permission" and row.scope_key == OPERATION.value
            ) == control.raw_permission_retry_at(OPERATION)
        finally:
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_ack_validates_sync_and_bound_repository_before_any_new_save(tmp_path) -> None:
    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path)

        async def async_ack() -> None:
            return None

        class AsyncCallable:
            async def __call__(self) -> None:
                return None

        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            prior = repository.load()
            for invalid in (42, async_ack, AsyncCallable()):
                with pytest.raises(TypeError):
                    await control.recheck_permission(
                        OPERATION, lambda: "unexpected", work_key="stock",
                        on_reserved=invalid,
                    )
                assert repository.load() == prior
        finally:
            await control.aclose()
            engine.dispose()

        unbound = controller(clock)
        starts: list[str] = []
        try:
            await _block(unbound)
            clock.current += timedelta(seconds=300)
            old_due = unbound.raw_permission_retry_at(OPERATION)
            with pytest.raises(RecoveryCheckpointError, match="bound repository"):
                await unbound.recheck_permission(
                    OPERATION, lambda: starts.append("sdk"), work_key="stock",
                    on_reserved=lambda: starts.append("ack"),
                )
            assert unbound.raw_permission_retry_at(OPERATION) == old_due
            assert starts == []
        finally:
            await unbound.aclose()

    asyncio.run(scenario())


def test_ack_persistence_failure_calls_neither_callback_nor_sdk(tmp_path) -> None:
    class FailingRepository(ProviderRecoveryRepository):
        reject_save = False

        def save(self, rows):
            if self.reject_save:
                raise RecoveryCheckpointError("offline write failed")
            return super().save(rows)

    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path, FailingRepository)
        starts: list[str] = []
        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            repository.reject_save = True
            with pytest.raises(RecoveryCheckpointError):
                await control.recheck_permission(
                    OPERATION, lambda: starts.append("sdk"), work_key="stock",
                    on_reserved=lambda: starts.append("ack"),
                )
            assert starts == []
            with pytest.raises(RecoveryCheckpointError):
                await control.aclose()
        finally:
            control.close()
            repository.release_owner(control)
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("abort", ("queue", "stop"))
def test_ack_occurs_once_when_worker_never_starts(tmp_path, abort) -> None:
    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path)
        starts: list[str] = []
        hold_started, release = threading.Event(), threading.Event()

        def hold_capacity() -> None:
            hold_started.set()
            release.wait(3)

        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            if abort == "queue":
                with pytest.raises(RequestNotStartedError):
                    await control.recheck_permission(
                        OPERATION, lambda: starts.append("sdk"),
                        work_key="stock", can_start=lambda: False,
                        on_reserved=lambda: starts.append("ack"),
                    )
            else:
                blocker = asyncio.create_task(control.execute(
                    TushareOperation.INDEX_DAILY, hold_capacity, work_key="index",
                ))
                assert await asyncio.to_thread(hold_started.wait, 1)
                pending = asyncio.create_task(control.recheck_permission(
                    OPERATION, lambda: starts.append("sdk"), work_key="stock",
                    on_reserved=lambda: starts.append("ack"),
                ))
                for _ in range(100):
                    if control.waiting_count:
                        break
                    await asyncio.sleep(0)
                assert control.waiting_count == 1
                control.close()
                release.set()
                await blocker
                with pytest.raises(RequestControlError) as caught:
                    await pending
                assert caught.value.code is RequestControlErrorCode.CLOSED
            assert starts == ["ack"]
            assert control.is_permission_blocked(OPERATION)
            assert control.raw_permission_retry_at(OPERATION) == (
                clock.now() + timedelta(seconds=300)
            )
            assert any(row.kind == "permission" and row.scope_key == OPERATION.value
                       for row in repository.load())
        finally:
            release.set()
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_late_worker_retry_extension_does_not_ack_twice(tmp_path) -> None:
    async def scenario() -> None:
        engine, repository, clock, control = _bound(tmp_path)
        starts: list[str] = []
        sdk_started, release = threading.Event(), threading.Event()

        def probe() -> None:
            sdk_started.set()
            release.wait(3)
            fail(TushareErrorCode.BLOCKED_PERMISSION)

        try:
            await _block(control)
            clock.current += timedelta(seconds=300)
            task = asyncio.create_task(control.recheck_permission(
                OPERATION, probe, work_key="stock",
                on_reserved=lambda: starts.append("ack"),
            ))
            assert await asyncio.to_thread(sdk_started.wait, 1)
            clock.current += timedelta(seconds=10)
            release.set()
            with pytest.raises(RequestControlError):
                await task
            assert starts == ["ack"]
            assert control.raw_permission_retry_at(OPERATION) == (
                clock.now() + timedelta(seconds=300)
            )
            assert next(
                row.retry_at for row in repository.load()
                if row.kind == "permission" and row.scope_key == OPERATION.value
            ) == control.raw_permission_retry_at(OPERATION)
        finally:
            release.set()
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())
