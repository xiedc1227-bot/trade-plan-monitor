"""Opt-in recovery preserves cooldowns and coalesces controlled permission probes."""

import asyncio
import threading
from datetime import datetime, timedelta
from hashlib import sha256

import pytest
import requests
from sqlalchemy import text

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpoint,
    RecoveryCheckpointError,
)

OPERATION = TushareOperation.DAILY_BARS


class Clock:
    def __init__(self):
        self.current = datetime(2026, 9, 21, 10, tzinfo=SHANGHAI)

    def now(self):
        return self.current

    async def sleep_until(self, deadline):
        self.current = max(self.current, deadline)


def controller(clock, repository=None, *, require_binding=False):
    return TushareRequestController(
        clock=clock,
        executor_workers=1,
        max_concurrency=1,
        min_interval=timedelta(0),
        jitter=timedelta(0),
        in_cycle_retries=0,
        recovery_repository=repository,
        require_repository_binding=require_binding,
    )


def fail(code):
    raise TushareProviderError(code, OPERATION.value)


def test_required_repository_binding_blocks_requests_until_restored(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "bound.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64,
        )
        clock = Clock()
        control = controller(clock, require_binding=True)
        physical_calls = []

        def request():
            physical_calls.append(1)
            return "ok"

        try:
            with pytest.raises(RecoveryCheckpointError):
                await control.execute(OPERATION, request, work_key="stock")
            with pytest.raises(RecoveryCheckpointError):
                await control.recheck_permission(OPERATION, request, work_key="stock")
            with pytest.raises(RecoveryCheckpointError):
                control.reset_permission_block(OPERATION)
            assert physical_calls == []
            control.bind_recovery_repository(repository)
            assert await control.execute(OPERATION, request, work_key="stock") == "ok"
            assert physical_calls == [1]
        finally:
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_failed_repository_binding_releases_owner_without_admitting_work(tmp_path):
    class InvalidRepository(ProviderRecoveryRepository):
        def load(self):
            raise RecoveryCheckpointError("bad recovery record")

    async def scenario():
        engine = create_sqlite_engine(tmp_path / "invalid.db")
        upgrade_database(engine)
        factory = create_session_factory(engine)
        repository = InvalidRepository(factory, provider_identity="a" * 64)
        control = controller(Clock(), require_binding=True)
        try:
            with pytest.raises(RecoveryCheckpointError):
                control.bind_recovery_repository(repository)
            with pytest.raises(RecoveryCheckpointError):
                await control.execute(OPERATION, lambda: "unexpected", work_key="stock")
            replacement = controller(
                Clock(), ProviderRecoveryRepository(factory, provider_identity="a" * 64)
            )
            await replacement.aclose()
        finally:
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_new_production_owner_waits_one_full_pacing_interval_before_first_call(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "paced.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64,
        )
        elapsed = [0.0]

        async def advance(seconds):
            elapsed[0] += seconds
            await asyncio.sleep(0)

        control = TushareRequestController(
            clock=Clock(), executor_workers=1, max_concurrency=1,
            min_interval=timedelta(milliseconds=1_250), jitter=timedelta(0),
            in_cycle_retries=0, monotonic=lambda: elapsed[0],
            pace_sleep=advance, require_repository_binding=True,
        )
        physical_starts = []
        try:
            control.bind_recovery_repository(repository)
            assert await control.execute(
                OPERATION, lambda: physical_starts.append(elapsed[0]), work_key="stock",
            ) is None
            assert physical_starts == [1.25]
        finally:
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_shared_cooldown_and_stable_backoff_survive_controller_restart(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        clock = Clock()
        first = controller(clock, repository)
        with pytest.raises(RequestControlError):
            await first.execute(
                OPERATION, lambda: fail(TushareErrorCode.TRANSIENT), work_key="stock"
            )
        with pytest.raises(RequestControlError):
            await first.execute(
                OPERATION, lambda: fail(TushareErrorCode.RATE_LIMITED), work_key="other"
            )
        await first.aclose()
        second = controller(clock, repository)
        with pytest.raises(RequestControlError) as caught:
            await second.execute(TushareOperation.INDEX_DAILY, lambda: "unexpected", work_key="new")
        assert caught.value.code is RequestControlErrorCode.RATE_LIMITED
        assert caught.value.attempts == 0
        clock.current += timedelta(seconds=300)
        with pytest.raises(RequestControlError) as caught:
            await second.execute(
                OPERATION, lambda: fail(TushareErrorCode.TRANSIENT), work_key="stock"
            )
        assert caught.value.next_retry_at == clock.now() + timedelta(seconds=60)
        await second.aclose()
        engine.dispose()

    asyncio.run(scenario())


def test_permission_rechecks_coalesce_while_normal_work_stays_blocked():
    async def scenario():
        clock = Clock()
        control = controller(clock)
        started, release = threading.Event(), threading.Event()
        calls = []

        def probe():
            calls.append(1)
            started.set()
            release.wait(3)
            return "allowed"

        with pytest.raises(RequestControlError):
            await control.execute(
                OPERATION, lambda: fail(TushareErrorCode.BLOCKED_PERMISSION), work_key="stock"
            )
        with pytest.raises(RequestControlError):
            await control.recheck_permission(OPERATION, probe, work_key="stock")
        clock.current += timedelta(seconds=300)
        tasks = [
            asyncio.create_task(control.recheck_permission(OPERATION, probe, work_key="stock"))
            for _ in range(8)
        ]
        try:
            assert await asyncio.to_thread(started.wait, 1)
            with pytest.raises(RequestControlError) as caught:
                await control.execute(OPERATION, lambda: "unexpected", work_key="other")
            assert caught.value.code is RequestControlErrorCode.BLOCKED_PERMISSION
            release.set()
            assert await asyncio.gather(*tasks) == ["allowed"] * 8
            assert calls == [1]
            assert not control.is_permission_blocked(OPERATION)
        finally:
            release.set()
            await control.aclose()

    asyncio.run(scenario())


def test_failed_permission_recheck_preserves_block_and_shared_cooldown():
    async def scenario():
        clock = Clock()
        control = controller(clock)
        with pytest.raises(RequestControlError):
            await control.execute(
                OPERATION, lambda: fail(TushareErrorCode.BLOCKED_PERMISSION), work_key="stock"
            )
        clock.current += timedelta(seconds=300)
        with pytest.raises(RequestControlError):
            await control.recheck_permission(
                OPERATION, lambda: fail(TushareErrorCode.RATE_LIMITED), work_key="stock"
            )
        assert control.is_permission_blocked(OPERATION)
        assert control.permission_retry_at(OPERATION) == clock.now() + timedelta(seconds=300)
        control.reset_permission_block(OPERATION)
        with pytest.raises(RequestControlError) as caught:
            await control.execute(OPERATION, lambda: "unexpected", work_key="stock")
        assert caught.value.code is RequestControlErrorCode.RATE_LIMITED
        await control.aclose()

    asyncio.run(scenario())


def test_bound_provider_has_one_controller_owner_until_joined(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        factory = create_session_factory(engine)
        clock = Clock()
        first = controller(clock, ProviderRecoveryRepository(factory, provider_identity="a" * 64))
        first.close()
        with pytest.raises(RecoveryCheckpointError, match="already owned"):
            controller(clock, ProviderRecoveryRepository(factory, provider_identity="a" * 64))
        await first.aclose()
        replacement = controller(
            clock, ProviderRecoveryRepository(factory, provider_identity="a" * 64)
        )
        await replacement.aclose()
        engine.dispose()

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_reset_permission_reservation_or_latch(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64
        )
        clock = Clock()
        control = controller(clock, repository)
        started, release = threading.Event(), threading.Event()

        def probe():
            started.set()
            release.wait(3)
            fail(TushareErrorCode.TRANSIENT)

        with pytest.raises(RequestControlError):
            await control.execute(
                OPERATION, lambda: fail(TushareErrorCode.BLOCKED_PERMISSION), work_key="stock"
            )
        clock.current += timedelta(seconds=300)
        task = asyncio.create_task(control.recheck_permission(OPERATION, probe, work_key="stock"))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            pending = next(row for row in repository.load() if row.kind == "permission")
            assert pending.retry_at == clock.now() + timedelta(seconds=300)
            assert control.is_permission_blocked(OPERATION)
        finally:
            release.set()
            await control.aclose()
        replacement = controller(clock, repository)
        with pytest.raises(RequestControlError) as caught:
            await replacement.recheck_permission(OPERATION, lambda: "unexpected", work_key="stock")
        assert caught.value.attempts == 0
        assert caught.value.next_retry_at == clock.now() + timedelta(seconds=300)
        await replacement.aclose()
        engine.dispose()

    asyncio.run(scenario())


def test_persistence_failure_and_invalid_restore_admit_no_further_requests(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        control = controller(Clock(), repository)
        calls = []

        def transient():
            calls.append(1)
            raise requests.ConnectionError("private-provider-details")

        with engine.begin() as connection:
            connection.execute(text("DROP TABLE provider_recovery_checkpoint"))
        with pytest.raises(RecoveryCheckpointError) as caught:
            await control.execute(OPERATION, transient, work_key="stock")
        assert "private" not in str(caught.value)
        with pytest.raises(RecoveryCheckpointError):
            await control.execute(OPERATION, transient, work_key="different-stock")
        assert calls == [1]
        with pytest.raises(RecoveryCheckpointError, match="could not be checkpointed"):
            await control.aclose()
        with pytest.raises(RecoveryCheckpointError, match="already owned"):
            controller(Clock(), repository)
        repository.release_owner(control)
        with pytest.raises(RecoveryCheckpointError):
            controller(Clock(), repository)
        engine.dispose()

    asyncio.run(scenario())


def test_backoff_repeats_at_ceiling_and_persists_no_raw_work_key_or_error(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        clock = Clock()
        control = controller(clock, repository)

        def transient():
            raise requests.ConnectionError("private-provider-details")

        for seconds in (30, 60, 120, 300, 300, 300):
            with pytest.raises(RequestControlError) as caught:
                await control.execute(OPERATION, transient, work_key="private-work-key")
            assert caught.value.next_retry_at == clock.now() + timedelta(seconds=seconds)
            clock.current = caught.value.next_retry_at
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT * FROM provider_recovery_checkpoint")).all()
        assert len(rows) == 1
        assert "private" not in str(rows)
        await control.aclose()
        engine.dispose()

    asyncio.run(scenario())


def test_restored_expired_backoffs_reclaim_only_one_slot_and_keep_bound(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        clock = Clock()
        rows = tuple(
            RecoveryCheckpoint(
                "backoff",
                sha256(f"stock:{index}".encode()).hexdigest(),
                clock.now() - timedelta(seconds=64 - index),
                1,
            )
            for index in range(64)
        )
        repository.save(rows)
        control = controller(clock, repository)
        assert control.tracked_backoff_count == 64
        with pytest.raises(RequestControlError):
            await control.execute(
                OPERATION, lambda: fail(TushareErrorCode.TRANSIENT), work_key="new"
            )
        assert control.tracked_backoff_count == 64
        restored = repository.load()
        assert len(restored) == 64
        assert rows[0] not in restored
        assert set(rows[1:]) <= set(restored)
        await control.aclose()
        engine.dispose()

    asyncio.run(scenario())


def test_success_without_checkpoint_change_does_not_write_storage(tmp_path):
    class CountingRepository(ProviderRecoveryRepository):
        writes = 0

        def save(self, rows):
            self.writes += 1
            super().save(rows)

    async def scenario():
        engine = create_sqlite_engine(tmp_path / "recovery.db")
        upgrade_database(engine)
        repository = CountingRepository(create_session_factory(engine), provider_identity="a" * 64)
        control = controller(Clock(), repository)
        assert await control.execute(OPERATION, lambda: "ok", work_key="stock") == "ok"
        assert await control.execute(OPERATION, lambda: "ok", work_key="stock") == "ok"
        assert repository.writes == 0
        await control.aclose()
        engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    (
        TushareErrorCode.RATE_LIMITED,
        TushareErrorCode.BLOCKED_PERMISSION,
        TushareErrorCode.TRANSIENT,
        TushareErrorCode.TIMEOUT,
    ),
)
def test_cancelled_ordinary_call_persists_late_failure_before_replacement(tmp_path, failure):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "late.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        clock = Clock()
        control = controller(clock, repository)
        started, release = threading.Event(), threading.Event()

        def late_failure():
            started.set()
            release.wait(3)
            fail(failure)

        task = asyncio.create_task(control.execute(OPERATION, late_failure, work_key="stock"))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            await control.aclose()
            replacement = controller(clock, repository)
            try:
                with pytest.raises(RequestControlError) as caught:
                    await replacement.execute(OPERATION, lambda: "unexpected", work_key="stock")
                expected = (
                    RequestControlErrorCode.TRANSIENT
                    if failure is TushareErrorCode.TIMEOUT
                    else RequestControlErrorCode(failure.value)
                )
                assert caught.value.code is expected
                assert caught.value.attempts == 0
                if failure is TushareErrorCode.BLOCKED_PERMISSION:
                    assert replacement.permission_retry_at(OPERATION) == clock.now() + timedelta(
                        seconds=300
                    )
                elif failure is TushareErrorCode.RATE_LIMITED:
                    assert replacement.cooldown_until == clock.now() + timedelta(seconds=300)
                else:
                    assert replacement.backoff_until("stock") == clock.now() + timedelta(seconds=30)
            finally:
                await replacement.aclose()
        finally:
            release.set()
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", (TushareErrorCode.TRANSIENT, TushareErrorCode.INVALID_RESPONSE))
def test_queued_permission_recheck_reserves_actual_physical_start_across_restart(tmp_path, failure):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "queued.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity="a" * 64,
        )
        clock = Clock()
        control = controller(clock, repository)
        started, release = threading.Event(), threading.Event()
        physical_starts = []

        def hold_capacity():
            started.set()
            release.wait(3)

        def probe():
            physical_starts.append(clock.now())
            fail(failure)

        with pytest.raises(RequestControlError):
            await control.execute(
                OPERATION, lambda: fail(TushareErrorCode.BLOCKED_PERMISSION), work_key="stock"
            )
        clock.current += timedelta(seconds=300)
        blocker = asyncio.create_task(
            control.execute(
                TushareOperation.INDEX_DAILY,
                hold_capacity,
                work_key="index",
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        pending = asyncio.create_task(
            control.recheck_permission(OPERATION, probe, work_key="stock")
        )
        try:
            for _ in range(100):
                if control.waiting_count:
                    break
                await asyncio.sleep(0)
            assert control.waiting_count == 1
            clock.current += timedelta(seconds=10)
            release.set()
            await blocker
            with pytest.raises(RequestControlError):
                await pending
            actual_start = clock.now()
            await control.aclose()
            replacement = controller(clock, repository)
            try:
                assert replacement.permission_retry_at(OPERATION) == actual_start + timedelta(
                    seconds=300
                )
                clock.current = actual_start + timedelta(seconds=290)
                with pytest.raises(RequestControlError) as caught:
                    await replacement.recheck_permission(OPERATION, probe, work_key="stock")
                assert caught.value.attempts == 0
                assert physical_starts == [actual_start]
            finally:
                await replacement.aclose()
        finally:
            release.set()
            await asyncio.gather(blocker, pending, return_exceptions=True)
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_late_checkpoint_failure_blocks_admission_and_replacement(tmp_path):
    class FailingRepository(ProviderRecoveryRepository):
        def save(self, rows):
            raise RecoveryCheckpointError("checkpoint storage unavailable")

    async def scenario():
        engine = create_sqlite_engine(tmp_path / "fault.db")
        upgrade_database(engine)
        repository = FailingRepository(create_session_factory(engine), provider_identity="a" * 64)
        clock = Clock()
        control = controller(clock, repository)
        started, release = threading.Event(), threading.Event()

        def late_failure():
            started.set()
            release.wait(3)
            fail(TushareErrorCode.RATE_LIMITED)

        task = asyncio.create_task(control.execute(OPERATION, late_failure, work_key="stock"))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            for _ in range(100):
                if not control.active_count:
                    break
                await asyncio.sleep(0.001)
            assert control.active_count == 0
            with pytest.raises(RecoveryCheckpointError):
                await control.execute(OPERATION, lambda: "unexpected", work_key="other")
            with pytest.raises(RecoveryCheckpointError, match="could not be checkpointed"):
                await control.aclose()
            with pytest.raises(RecoveryCheckpointError, match="already owned"):
                controller(clock, repository)
        finally:
            release.set()
            # Test cleanup only: production keeps the failed owner quarantined.
            repository.release_owner(control)
            engine.dispose()

    asyncio.run(scenario())


def test_observed_one_write_failure_quarantines_owner_despite_readable_old_state(tmp_path):
    class FailOnceRepository(ProviderRecoveryRepository):
        failures_remaining = 1

        def save(self, rows):
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise RecoveryCheckpointError("one interrupted checkpoint write")
            super().save(rows)

    async def scenario():
        engine = create_sqlite_engine(tmp_path / "interrupted-write.db")
        upgrade_database(engine)
        repository = FailOnceRepository(create_session_factory(engine), provider_identity="a" * 64)
        clock = Clock()
        control = controller(clock, repository)
        try:
            with pytest.raises(RecoveryCheckpointError):
                await control.execute(
                    OPERATION,
                    lambda: fail(TushareErrorCode.RATE_LIMITED),
                    work_key="stock",
                )
            assert repository.load() == ()
            assert control.active_count == 0
            with pytest.raises(RecoveryCheckpointError):
                await control.aclose()
            with pytest.raises(RecoveryCheckpointError, match="already owned"):
                controller(clock, repository)
            assert repository.load() == ()
        finally:
            control.close()
            repository.release_owner(control)
            engine.dispose()

    asyncio.run(scenario())


def test_late_transient_after_observed_timeout_does_not_double_count_backoff(tmp_path):
    async def scenario():
        engine = create_sqlite_engine(tmp_path / "timeout.db")
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="a" * 64
        )
        clock = Clock()
        control = TushareRequestController(
            clock=clock,
            executor_workers=1,
            max_concurrency=1,
            min_interval=timedelta(0),
            jitter=timedelta(0),
            in_cycle_retries=0,
            timeout_seconds=0.05,
            recovery_repository=repository,
        )
        release = threading.Event()

        def late_failure():
            release.wait(3)
            fail(TushareErrorCode.TRANSIENT)

        try:
            with pytest.raises(RequestControlError) as caught:
                await control.execute(OPERATION, late_failure, work_key="stock")
            assert caught.value.code is RequestControlErrorCode.TIMEOUT
            release.set()
            await control.aclose()
            rows = repository.load()
            assert len(rows) == 1
            assert rows[0].failures == 1
            assert rows[0].retry_at == clock.now() + timedelta(seconds=30)
        finally:
            release.set()
            await control.aclose()
            engine.dispose()

    asyncio.run(scenario())
