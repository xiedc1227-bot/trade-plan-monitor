"""ML-T34: local request-start pacing using deterministic offline providers."""

import asyncio
from datetime import date
from threading import Thread, local

import pytest
from tests.integration.test_backtest_sync import _Controller, _Provider, _scope

from trade_plan_monitor.backtest import sync as sync_module
from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.sync import BacktestSyncService, BlockingBacktestSyncCore
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.request_control import RequestPriority, TushareOperation


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def sleep(self, seconds):
        assert seconds > 0
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(sync_module, "monotonic", lambda: value.now, raising=False)
    monkeypatch.setattr(sync_module, "sleep", value.sleep, raising=False)
    monkeypatch.setattr(BlockingBacktestSyncCore, "_worker_pacing", local())
    return value


def service(tmp_path, controller=None):
    return BacktestSyncService(
        provider=_Provider(), store=BacktestMarketStore(tmp_path / "market.sqlite3"),
        request_controller=controller or _Controller(), today=lambda: date(2026, 8, 25),
    )


def execute(sync_service, call, *, token=None, phase="SYNC_MINUTE"):
    return asyncio.run(sync_service._execute(
        TushareOperation.HISTORICAL_MINUTES, call, work_key="backtest:test:pacing",
        cancellation_token=token, phase=phase,
    ))


@pytest.mark.parametrize("duration", (0.0, 0.4, 1.25, 2.0))
def test_full_sync_spaces_every_surface_from_actual_start_and_has_no_cache_wait(
    tmp_path, clock, duration,
):
    starts = []

    sync_service = service(tmp_path)
    # Record at the real provider boundary rather than outer controller admission.
    provider = sync_service._provider
    for name, operation in (
        ("trading_calendar", TushareOperation.TRADING_CALENDAR),
        ("daily_bars", TushareOperation.DAILY_BARS),
        ("historical_minute_batch", TushareOperation.HISTORICAL_MINUTES),
        ("daily_limits", TushareOperation.DAILY_LIMITS),
    ):
        original = getattr(provider, name)

        def recorded(*args, original=original, operation=operation):
            starts.append((operation, clock.now))
            result = original(*args)
            clock.now += duration
            return result

        setattr(provider, name, recorded)
    result = asyncio.run(sync_service.sync(_scope()))
    assert result.network_calls == 4
    assert [operation for operation, _ in starts] == [
        TushareOperation.TRADING_CALENDAR, TushareOperation.DAILY_BARS,
        TushareOperation.HISTORICAL_MINUTES, TushareOperation.DAILY_LIMITS,
    ]
    assert [start for _, start in starts] == pytest.approx(
        [index * max(1.25, duration) for index in range(4)],
    )
    assert sync_service._store.freeze_dataset(_scope()).ready
    waits = tuple(clock.waits)
    assert asyncio.run(sync_service.sync(_scope())).network_calls == 0
    assert tuple(clock.waits) == waits


def test_controller_delays_and_repeated_callbacks_cannot_compress_provider_starts(
    tmp_path, clock,
):
    starts = []

    class Controller(_Controller):
        async def execute(self, operation, call, *, work_key, priority):
            assert priority is RequestPriority.BACKGROUND
            clock.now += 2.0
            first = await super().execute(operation, call, work_key=work_key, priority=priority)
            call()  # Existing controller policy; the sync service adds no retries.
            return first

    sync_service = service(tmp_path, Controller())
    assert execute(sync_service, lambda: starts.append(clock.now) or "result") == "result"
    assert execute(sync_service, lambda: starts.append(clock.now) or "result") == "result"
    assert starts == pytest.approx([2.0, 3.25, 5.25, 6.5])


@pytest.mark.parametrize("phase", ("SYNC_CALENDAR", "SYNC_DAILY", "SYNC_MINUTE", "SYNC_LIMIT"))
def test_cancellation_during_pacing_starts_no_next_provider_call(
    tmp_path, clock, monkeypatch, phase,
):
    sync_service = service(tmp_path)
    starts = []
    token = CancellationToken()
    execute(sync_service, lambda: starts.append(clock.now), token=token, phase=phase)

    def cancel_during_wait(seconds):
        clock.sleep(seconds)
        thread = Thread(target=token.cancel)
        thread.start()
        thread.join()

    monkeypatch.setattr(sync_module, "sleep", cancel_during_wait, raising=False)
    with pytest.raises(BacktestOperationCancelled) as cancelled:
        execute(sync_service, lambda: starts.append(clock.now), token=token, phase=phase)
    assert cancelled.value.phase == phase
    assert starts == [0.0]
    assert 0 < clock.now <= 0.05


@pytest.mark.parametrize("code", (TushareErrorCode.TIMEOUT, TushareErrorCode.RATE_LIMITED))
def test_error_is_unchanged_without_retry_and_failed_start_still_counts(tmp_path, clock, code):
    sync_service = service(tmp_path)
    error = TushareProviderError(code, "stk_mins")
    starts = []

    def failed():
        starts.append(clock.now)
        raise error

    with pytest.raises(TushareProviderError) as raised:
        execute(sync_service, failed)
    assert raised.value is error
    assert starts == [0.0]
    execute(sync_service, lambda: starts.append(clock.now))
    assert starts == pytest.approx([0.0, 1.25])


def test_blocking_core_keeps_pacing_across_sync_invocations(tmp_path, clock):
    core = BlockingBacktestSyncCore(
        provider=_Provider(), store=BacktestMarketStore(tmp_path / "market.sqlite3"),
        today=lambda: date(2026, 8, 25),
    )
    assert core.sync(_scope()).network_calls == 4
    first_end = clock.now
    assert core.sync(_scope(), refresh=True).network_calls == 4
    assert first_end == pytest.approx(3.75)
    assert clock.now == pytest.approx(8.75)


def test_fresh_cores_on_one_worker_keep_spacing_between_jobs(tmp_path, clock):
    for index in range(2):
        core = BlockingBacktestSyncCore(
            provider=_Provider(),
            store=BacktestMarketStore(tmp_path / f"market-{index}.sqlite3"),
            today=lambda: date(2026, 8, 25),
        )
        assert core.sync(_scope()).network_calls == 4
        assert clock.now == pytest.approx(3.75 if index == 0 else 8.75)


def test_ten_stock_offline_sync_retains_global_worker_spacing_and_frozen_coverage(
    tmp_path, clock,
):
    from tests.integration.test_backtest_isolation_fault_matrix import FIXTURE

    symbols = tuple(FIXTURE["symbols"])
    starts = []

    class Provider(_Provider):
        def daily_limits(self, trade_date):
            first = super().daily_limits(trade_date)[0]
            return tuple(first.model_copy(update={"symbol": symbol}) for symbol in symbols)

    provider = Provider()
    for name in ("trading_calendar", "daily_bars", "historical_minute_batch", "daily_limits"):
        original = getattr(provider, name)

        def recorded(*args, original=original):
            starts.append(clock.now)
            return original(*args)

        setattr(provider, name, recorded)
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    controller = _Controller()
    sync = BacktestSyncService(
        provider=provider, store=store, request_controller=controller,
        today=lambda: date(2026, 8, 25),
    )
    scope = _scope().model_copy(update={"symbols": symbols})
    result = asyncio.run(sync.sync(scope))
    assert result.network_calls == 22
    assert starts == pytest.approx([index * 1.25 for index in range(22)])
    assert set(controller.priorities) == {RequestPriority.BACKGROUND}
    assert store.freeze_dataset(scope).ready
    assert asyncio.run(sync.sync(scope)).network_calls == 0
    assert len(starts) == 22
