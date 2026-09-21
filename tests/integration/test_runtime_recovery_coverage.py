"""Opt-in scoped acquisition verifies committed coverage against a frozen cutoff."""

import asyncio
import threading
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.reconciliation import (
    RecoveryCoordinator,
    RecoveryDisposition,
    RecoveryRequirement,
    RecoveryStepResult,
)
from trade_plan_monitor.runtime.recovery import RecoveryErrorCode, RecoveryService
from trade_plan_monitor.runtime.recovery_targets import derive_recovery_target
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.repositories import MarketHistoryRepository

SYMBOL = "600000.SH"
SIBLING = "000001.SZ"


def stamp(clock, day="2026-09-21"):
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=SHANGHAI)


def minute(clock, symbol=SYMBOL, day="2026-09-21"):
    return MinuteBar(
        symbol=symbol, bar_end=stamp(clock, day), received_at=stamp(clock, day),
        open_fen=1000, high_fen=1000, low_fen=1000, close_fen=1000,
        volume_shares=100, amount_yuan=Decimal("1000"),
    )


class Clock:
    current = stamp("09:32:30")

    def now(self):
        return self.current

    async def sleep_until(self, deadline):
        self.current = max(self.current, deadline)


class Provider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.on_call = lambda: None

    def current_day_minutes(self, symbol):
        self.calls.append(symbol)
        self.on_call()
        return self.responses[symbol]


@pytest.fixture
def history(tmp_path):
    engine = create_sqlite_engine(tmp_path / "coverage.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)

    class History:
        def persist(self, rows):
            with factory.begin() as session:
                MarketHistoryRepository(session).upsert_minutes(rows)

        def read(self, symbol, required):
            if not required:
                return ()
            with factory() as session:
                rows = MarketHistoryRepository(session).list_minutes(
                    symbol, start=min(required), end=max(required),
                )
                return tuple(row.bar_end for row in rows if row.bar_end in required)

    yield History()
    engine.dispose()


def setup_service(history, responses, *, persist=None, realtime_pending=lambda: False):
    clock = Clock()
    provider = Provider(responses)
    controller = TushareRequestController(
        clock=clock, executor_workers=1, max_concurrency=1,
        min_interval=timedelta(0), jitter=timedelta(0), in_cycle_retries=0,
    )
    service = RecoveryService(
        provider=provider, request_controller=controller,
        active_symbols=lambda: (SYMBOL, SIBLING), persist_minutes=persist or history.persist,
        is_open_on=lambda _: True, realtime_pending=realtime_pending,
    )
    return clock, provider, controller, service


async def recover(service, clock, history, *, symbol=SYMBOL, required=None, target=None):
    return await service.recover_scope(
        symbol=symbol,
        target=target or derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
        required_ends=required if required is not None else (stamp("09:31:00"), stamp("09:32:00")),
        read_persisted_ends=history.read, now=clock.now,
    )


@pytest.mark.parametrize("rows", [[], [minute("09:31:00")]])
def test_empty_or_partial_response_never_completes_persisted_coverage(history, rows):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {SYMBOL: rows})
        try:
            result = await recover(service, clock, history)
            assert not result.ready
            assert stamp("09:32:00") in result.coverage.missing_ends
            assert provider.calls == [SYMBOL]
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_frozen_cutoff_filters_future_rows_before_commit_and_rechecks_storage(history):
    async def scenario():
        rows = [minute("09:31:00"), minute("09:32:00"), minute("09:33:00")]
        clock, provider, controller, service = setup_service(history, {SYMBOL: rows})
        provider.on_call = lambda: setattr(clock, "current", stamp("09:34:00"))
        try:
            result = await recover(service, clock, history)
            assert result.ready
            assert result.target.completed_minute_end == stamp("09:32:00")
            assert history.read(SYMBOL, (stamp("09:33:00"),)) == ()
            again = await recover(service, clock, history, target=result.target)
            assert again.ready
            assert provider.calls == [SYMBOL]
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_successful_persist_callback_without_committed_rows_is_not_ready(history):
    async def scenario():
        clock, _, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00"), minute("09:32:00")]},
            persist=lambda _: None,
        )
        try:
            result = await recover(service, clock, history)
            assert not result.ready
            assert len(result.coverage.missing_ends) == 2
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_missing_prior_day_is_not_filled_by_current_day_endpoint(history):
    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00"), minute("09:32:00")]},
        )
        old = stamp("15:00:00", "2026-09-18")
        try:
            result = await recover(
                service, clock, history, required=(old, stamp("09:32:00")),
            )
            assert not result.ready
            assert result.coverage.missing_ends == (old,)
            again = await recover(
                service, clock, history, required=(old, stamp("09:32:00")),
            )
            assert not again.ready
            assert provider.calls == [SYMBOL]
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [stamp("00:00:00", "2026-09-22"), stamp("09:31:30")])
def test_clock_rollover_or_reversal_discards_acquisition_before_persist(history, changed):
    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00"), minute("09:32:00")]},
        )
        provider.on_call = lambda: setattr(clock, "current", changed)
        try:
            result = await recover(service, clock, history)
            assert not result.ready
            assert result.retarget_required
            assert history.read(SYMBOL, (stamp("09:31:00"), stamp("09:32:00"))) == ()
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_persistence_failure_does_not_prevent_sibling_scope_progress(history):
    def persist(rows):
        if rows[0].symbol == SYMBOL:
            raise OSError("private storage details")
        history.persist(rows)

    async def scenario():
        clock, provider, controller, service = setup_service(
            history,
            {SYMBOL: [minute("09:31:00")], SIBLING: [minute("09:31:00", SIBLING)]},
            persist=persist,
        )
        try:
            failed = await recover(service, clock, history, required=(stamp("09:31:00"),))
            sibling = await recover(
                service, clock, history, symbol=SIBLING, required=(stamp("09:31:00"),),
            )
            assert failed.error_code is RecoveryErrorCode.PERSISTENCE_FAILED
            assert not failed.ready
            assert sibling.ready
            assert provider.calls == [SYMBOL, SIBLING]
            assert "private" not in repr(failed)
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_realtime_work_yields_one_scope_without_any_all_symbol_startup_batch(history):
    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {}, realtime_pending=lambda: True,
        )
        try:
            result = await recover(service, clock, history)
            assert result.yielded_to_realtime
            assert not result.ready
            assert provider.calls == []
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("prior_failure", [False, True])
def test_queued_date_rollover_prevents_physical_current_day_request(history, prior_failure):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {SYMBOL: []})
        released = threading.Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def transient():
            raise TushareProviderError(TushareErrorCode.TRANSIENT, "rt_min_daily")

        if prior_failure:
            with pytest.raises(RequestControlError):
                await controller.execute(
                    TushareOperation.CURRENT_DAY_MINUTES, transient, work_key=f"recovery:{SYMBOL}",
                )
            clock.current += timedelta(seconds=30)

        def blocking_call():
            loop.call_soon_threadsafe(started.set)
            if not released.wait(timeout=5):
                raise TimeoutError("test failed to release provider")

        blocker = asyncio.create_task(controller.execute(
            TushareOperation.DAILY_BARS, blocking_call, work_key="other-operation",
        ))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            recovery = asyncio.create_task(recover(service, clock, history))
            async with asyncio.timeout(2):
                while controller.waiting_count != 1:
                    await asyncio.sleep(0)
            clock.current = stamp("00:00:00", "2026-09-22")
            released.set()
            await blocker
            result = await recovery
            assert result.retarget_required
            assert not result.ready
            assert provider.calls == []
            if prior_failure:
                with pytest.raises(RequestControlError) as caught:
                    await controller.execute(
                        TushareOperation.CURRENT_DAY_MINUTES, transient,
                        work_key=f"recovery:{SYMBOL}",
                    )
                assert caught.value.next_retry_at == clock.now() + timedelta(seconds=60)
        finally:
            released.set()
            await blocker
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("rows", [
    [minute("09:31:00", day="2026-09-18")],
    [minute("09:31:00", symbol=SIBLING)],
    ["raw-secret-response"],
    [minute("09:31:00")] * 241,
])
def test_invalid_provider_rows_fail_without_persisting_or_leaking_details(history, rows):
    async def scenario():
        clock, _, controller, service = setup_service(history, {SYMBOL: rows})
        try:
            result = await recover(service, clock, history)
            assert result.error_code is RecoveryErrorCode.INVALID_RESPONSE
            assert not result.ready
            assert history.read(SYMBOL, (stamp("09:31:00"),)) == ()
            assert "secret" not in repr(result)
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_persisted_coverage_read_failure_is_visible_and_avoids_provider_work(history):
    def unavailable(*_):
        raise OSError("secret storage path")

    async def scenario():
        clock, provider, controller, service = setup_service(history, {SYMBOL: []})
        history.read = unavailable
        try:
            result = await recover(service, clock, history)
            assert not result.ready
            assert result.error_code is RecoveryErrorCode.PERSISTENCE_FAILED
            assert provider.calls == []
            assert "secret" not in repr(result)
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_clock_rollover_after_committed_read_cannot_report_old_target_ready(history):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {SYMBOL: []})
        history.persist((minute("09:31:00"), minute("09:32:00")))
        original_read = history.read

        def rollover_read(symbol, required):
            rows = original_read(symbol, required)
            clock.current = stamp("00:00:00", "2026-09-22")
            return rows

        history.read = rollover_read
        try:
            result = await recover(service, clock, history)
            assert result.coverage.complete
            assert result.retarget_required
            assert not result.ready
            assert provider.calls == []
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("calendar", [True, None])
def test_no_completed_target_never_invents_minutes_or_establishes_readiness(history, calendar):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {})
        clock.current = stamp("08:00:00")
        target = derive_recovery_target(now=clock.now(), is_open_on=lambda _: calendar)
        try:
            result = await recover(service, clock, history, required=(), target=target)
            assert not result.ready
            assert provider.calls == []
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_owned_coordinator_recovers_after_transient_failure_without_starving_sibling(history):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {
            SYMBOL: [minute("09:31:00")], SIBLING: [minute("09:31:00", SIBLING)],
        })
        target = derive_recovery_target(now=clock.now(), is_open_on=lambda _: True)
        stop = asyncio.Event()
        ready = set()
        initial_time = clock.now()
        physical_starts = []

        def provider_outcome():
            physical_starts.append(clock.now())
            if len(provider.calls) == 1:
                raise TushareProviderError(TushareErrorCode.TRANSIENT, "rt_min_daily")

        provider.on_call = provider_outcome

        async def execute(ticket):
            result = await recover(
                service, clock, history, symbol=ticket.requirement.scope_key,
                required=(stamp("09:31:00"),), target=target,
            )
            assert result.error_code is not RecoveryErrorCode.PERSISTENCE_FAILED
            if result.ready:
                ready.add(result.symbol)
                if len(ready) == 2:
                    stop.set()
                return RecoveryStepResult.ready()
            assert result.error_code is RecoveryErrorCode.TRANSIENT
            return RecoveryStepResult.retry(result.next_retry_at)

        coordinator = RecoveryCoordinator(
            clock=clock,
            requirements=lambda now: (
                RecoveryRequirement(SYMBOL, "frozen-target"),
                RecoveryRequirement(SIBLING, "frozen-target"),
            ),
            execute=execute,
        )
        try:
            await asyncio.wait_for(coordinator.run(stop=stop), 3)
            assert provider.calls == [SYMBOL, SIBLING, SYMBOL]
            assert physical_starts[-1] >= initial_time + timedelta(seconds=30)
            assert all(
                item.disposition is RecoveryDisposition.READY for item in coordinator.snapshot()
            )
            assert history.read(SYMBOL, (stamp("09:31:00"),)) == (stamp("09:31:00"),)
            assert history.read(SIBLING, (stamp("09:31:00"),)) == (stamp("09:31:00"),)
        finally:
            stop.set()
            await controller.aclose()

    asyncio.run(scenario())
