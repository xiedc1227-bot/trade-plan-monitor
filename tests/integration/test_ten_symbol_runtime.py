"""T030-T031 ten-symbol runtime, health-isolation, and recovery contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.market_data.aggregation import FiveMinuteBar, expected_five_minute_ends
from trade_plan_monitor.market_data.models import MinuteBar, ProviderCapabilities
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import SymbolHealthErrorCode, SymbolHealthTracker
from trade_plan_monitor.runtime.recovery import (
    RecoveryErrorCode,
    RecoveryMode,
    RecoveryService,
)
from trade_plan_monitor.runtime.request_control import TushareRequestController
from trade_plan_monitor.runtime.symbol_service import SymbolService

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
SYMBOLS: Final = tuple(f"{index:06d}.SZ" for index in range(1, 11))


def _at(hour: int, minute: int, second: int = 0, *, day: int = 24) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, tzinfo=SHANGHAI)


def _bar(symbol: str, bar_end: datetime) -> MinuteBar:
    offset = int(symbol[:6])
    return MinuteBar(
        symbol=symbol,
        bar_end=bar_end,
        open_fen=6400 + offset,
        high_fen=6410 + offset,
        low_fen=6390 + offset,
        close_fen=6405 + offset,
        volume_shares=1_000 + offset,
        amount_yuan=Decimal("64000") + offset,
        received_at=bar_end + timedelta(seconds=12),
    )


class _ImmediateClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.current = max(self.current, deadline)


class _ActiveSymbols:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.symbols = symbols

    def __call__(self) -> tuple[str, ...]:
        return self.symbols


class _FakeProvider:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, ...]] = []
        self.error: BaseException | None = None
        self.recovery_rows: dict[str, list[object]] = {}
        self.recovery_errors: dict[str, BaseException] = {}
        self.recovery_calls: list[str] = []
        self.recovery_active = 0
        self.maximum_recovery_active = 0

    def probe_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]:
        self.calls.append(symbols)
        if self.error is not None:
            raise self.error
        return list(self.rows)  # type: ignore[return-value]

    def current_day_minutes(self, symbol: str) -> list[MinuteBar]:
        self.recovery_calls.append(symbol)
        self.recovery_active += 1
        self.maximum_recovery_active = max(
            self.maximum_recovery_active,
            self.recovery_active,
        )
        try:
            error = self.recovery_errors.get(symbol)
            if error is not None:
                raise error
            return list(self.recovery_rows.get(symbol, []))  # type: ignore[return-value]
        finally:
            self.recovery_active -= 1

    def trading_calendar(self, start: date, end: date) -> list[object]:
        raise AssertionError("calendar fetching is outside this T030 batch")

    def daily_limits(self, trade_date: date) -> list[object]:
        raise AssertionError("daily-limit fetching is outside this T030 batch")

    def daily_bars(self, symbol: str, start: date, end: date) -> list[object]:
        raise AssertionError("official-close fetching is outside T030")


class _FakeHistory:
    def __init__(self) -> None:
        self.minutes: dict[tuple[str, datetime], MinuteBar] = {}
        self.five_minute: dict[tuple[str, datetime], FiveMinuteBar] = {}
        self.persisted_symbols: list[str] = []
        self.persisted_batches: list[tuple[datetime, ...]] = []
        self.fail_symbol: str | None = None
        self.malformed_load_symbol: str | None = None

    def seed_before_target(self, symbols: tuple[str, ...], bucket_end: datetime) -> None:
        for symbol in symbols:
            for minute_end in expected_five_minute_ends(bucket_end)[:-1]:
                bar = _bar(symbol, minute_end)
                self.minutes[(symbol, minute_end)] = bar

    def persist_minutes(self, bars: tuple[MinuteBar, ...]) -> None:
        if any(bar.symbol == self.fail_symbol for bar in bars):
            raise RuntimeError("sensitive-storage-detail")
        self.persisted_batches.append(tuple(bar.bar_end for bar in bars))
        for bar in bars:
            self.persisted_symbols.append(bar.symbol)
            self.minutes[(bar.symbol, bar.bar_end)] = bar

    def load_minutes(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[MinuteBar, ...]:
        if symbol == self.malformed_load_symbol:
            return ({"bad": "row"},)  # type: ignore[return-value]
        return tuple(
            self.minutes[(symbol, minute_end)]
            for minute_end in sorted(
                minute_end
                for stored_symbol, minute_end in self.minutes
                if stored_symbol == symbol and start <= minute_end <= end
            )
        )

    def persist_five_minute(self, bar: FiveMinuteBar) -> None:
        self.five_minute[(bar.symbol, bar.bar_end)] = bar


def _controller(now: datetime) -> TushareRequestController:
    return TushareRequestController(
        clock=_ImmediateClock(now),
        min_interval=timedelta(0),
        jitter=timedelta(0),
        jitter_source=lambda: 0.0,
        timeout_seconds=1,
        in_cycle_retries=0,
    )


def _service(
    *,
    provider: _FakeProvider,
    active: _ActiveSymbols,
    history: _FakeHistory,
    controller: TushareRequestController,
    is_open_on: Callable[[date], bool | None] | None = None,
) -> SymbolService:
    return SymbolService(
        provider=provider,
        request_controller=controller,
        active_symbols=active,
        persist_minutes=history.persist_minutes,
        load_minutes=history.load_minutes,
        persist_five_minute=history.persist_five_minute,
        is_open_on=is_open_on or (lambda _trade_date: True),
        health_tracker=SymbolHealthTracker(stale_after=timedelta(seconds=60)),
    )


def test_ten_symbol_runtime_uses_one_batch_and_builds_immutable_live_contexts() -> None:
    bucket_end = _at(9, 35)
    active = _ActiveSymbols(SYMBOLS)
    provider = _FakeProvider([_bar(symbol, bucket_end) for symbol in reversed(SYMBOLS)])
    history = _FakeHistory()
    history.seed_before_target(SYMBOLS, bucket_end)
    controller = _controller(_at(9, 35, 12))
    calendar_calls: list[date] = []

    def is_open_on(trade_date: date) -> bool:
        calendar_calls.append(trade_date)
        return True

    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
        is_open_on=is_open_on,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
    finally:
        controller.close()

    assert provider.calls == [SYMBOLS]
    assert calendar_calls == [bucket_end.date()]
    assert tuple(context.symbol for context in result.contexts) == SYMBOLS
    assert len(history.persisted_symbols) == 10
    assert len(history.five_minute) == 10
    assert all(context.five_minute_bar is not None for context in result.contexts)
    assert all(context.health.actionable for context in result.contexts)
    assert result.health.active_symbol_count == 10
    assert result.health.live_symbol_count == 10
    assert result.health.all_symbols_actionable is True
    assert result.contexts[0].model_config["frozen"] is True


def test_runtime_persists_each_non_boundary_minute_without_premature_aggregation() -> None:
    bar_end = _at(9, 31)
    active_symbols = SYMBOLS[:2]
    active = _ActiveSymbols(active_symbols)
    provider = _FakeProvider([_bar(symbol, bar_end) for symbol in active_symbols])
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bar_end,
                observed_at=_at(9, 31, 12),
            )
        )
    finally:
        controller.close()

    assert provider.calls == [active_symbols]
    assert history.persisted_symbols == list(active_symbols)
    assert history.five_minute == {}
    assert all(context.minutes == (_bar(context.symbol, bar_end),) for context in result.contexts)
    assert all(context.five_minute_bar is None for context in result.contexts)
    assert result.health.live_symbol_count == 2


def test_partial_and_malformed_batch_blocks_only_affected_symbols() -> None:
    bucket_end = _at(9, 35)
    missing_symbol = SYMBOLS[-2]
    persistence_failure = SYMBOLS[-1]
    healthy_symbols = SYMBOLS[:-2]
    provider = _FakeProvider(
        [_bar(symbol, bucket_end) for symbol in healthy_symbols]
        + [{"symbol": missing_symbol, "close": "malformed"}]
        + [_bar(persistence_failure, bucket_end)]
    )
    active = _ActiveSymbols(SYMBOLS)
    history = _FakeHistory()
    history.seed_before_target(SYMBOLS, bucket_end)
    history.fail_symbol = persistence_failure
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
    finally:
        controller.close()

    by_symbol = {context.symbol: context for context in result.contexts}
    assert all(by_symbol[symbol].health.actionable for symbol in healthy_symbols)
    assert by_symbol[missing_symbol].health.data_health.status.value == "GAPPED"
    assert by_symbol[missing_symbol].health.actionable is False
    assert by_symbol[persistence_failure].health.data_health.status.value == "BLOCKED"
    assert (
        by_symbol[persistence_failure].health.error_code is SymbolHealthErrorCode.PERSISTENCE_FAILED
    )
    assert by_symbol[persistence_failure].health.actionable is False
    assert result.health.live_symbol_count == 8
    assert result.health.blocked_symbol_count == 1
    assert result.health.gapped_symbol_count == 1
    assert set(history.persisted_symbols) == set(healthy_symbols)


def test_missing_current_response_cannot_be_hidden_by_cached_target_minute() -> None:
    bucket_end = _at(9, 35)
    symbol = SYMBOLS[0]
    provider = _FakeProvider([])
    active = _ActiveSymbols((symbol,))
    history = _FakeHistory()
    history.seed_before_target((symbol,), bucket_end)
    cached_target = _bar(symbol, bucket_end)
    history.minutes[(symbol, bucket_end)] = cached_target
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
    finally:
        controller.close()

    context = result.context_for(symbol)
    assert cached_target not in context.minutes
    assert context.five_minute_bar is None
    assert context.health.data_health.status.value == "GAPPED"
    assert context.health.actionable is False
    assert context.health.error_code is SymbolHealthErrorCode.INCOMPLETE_BUCKET


def test_malformed_loaded_context_blocks_only_its_symbol_after_missing_response() -> None:
    bucket_end = _at(9, 35)
    malformed_symbol, healthy_symbol = SYMBOLS[:2]
    provider = _FakeProvider([_bar(healthy_symbol, bucket_end)])
    active = _ActiveSymbols((malformed_symbol, healthy_symbol))
    history = _FakeHistory()
    history.seed_before_target((malformed_symbol, healthy_symbol), bucket_end)
    history.malformed_load_symbol = malformed_symbol
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
    finally:
        controller.close()

    malformed = result.context_for(malformed_symbol)
    healthy = result.context_for(healthy_symbol)
    assert malformed.health.data_health.status.value == "BLOCKED"
    assert malformed.health.error_code is SymbolHealthErrorCode.INVALID_CONTEXT
    assert malformed.health.actionable is False
    assert healthy.health.data_health.status.value == "LIVE"
    assert healthy.health.actionable is True


def test_second_incomplete_bucket_degrades_one_symbol_without_cancelling_others() -> None:
    first_end = _at(9, 35)
    second_end = _at(9, 40)
    failed_symbol = SYMBOLS[0]
    active = _ActiveSymbols(SYMBOLS)
    provider = _FakeProvider([_bar(symbol, first_end) for symbol in SYMBOLS[1:]])
    history = _FakeHistory()
    history.seed_before_target(SYMBOLS, first_end)
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        first = asyncio.run(
            service.run_realtime_batch(
                bar_end=first_end,
                observed_at=_at(9, 35, 12),
            )
        )
        history.seed_before_target(SYMBOLS, second_end)
        provider.rows = [_bar(symbol, second_end) for symbol in SYMBOLS[1:]]
        second = asyncio.run(
            service.run_realtime_batch(
                bar_end=second_end,
                observed_at=_at(9, 40, 12),
            )
        )
    finally:
        controller.close()

    first_failed = first.context_for(failed_symbol)
    second_failed = second.context_for(failed_symbol)
    assert first_failed.health.data_health.status.value == "GAPPED"
    assert second_failed.health.data_health.status.value == "DEGRADED"
    assert second_failed.health.consecutive_incomplete_buckets == 2
    assert second.health.live_symbol_count == 9
    assert all(second.context_for(symbol).health.actionable for symbol in SYMBOLS[1:])


def test_dynamic_plan_enable_and_disable_changes_the_next_batch_without_restart() -> None:
    bucket_end = _at(9, 35)
    first_symbols = SYMBOLS[:4]
    second_symbols = SYMBOLS[4:7]
    active = _ActiveSymbols(first_symbols)
    provider = _FakeProvider([_bar(symbol, bucket_end) for symbol in SYMBOLS])
    history = _FakeHistory()
    history.seed_before_target(SYMBOLS, bucket_end)
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        first = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
        active.symbols = second_symbols
        second = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 20),
            )
        )
    finally:
        controller.close()

    assert provider.calls == [first_symbols, second_symbols]
    assert tuple(context.symbol for context in first.contexts) == first_symbols
    assert tuple(context.symbol for context in second.contexts) == second_symbols
    assert second.health.active_symbol_count == 3


def test_provider_block_marks_each_symbol_blocked_without_leaking_provider_detail() -> None:
    bucket_end = _at(9, 35)
    sentinel = "sensitive-provider-body"
    provider = _FakeProvider([])
    try:
        raise ValueError(sentinel)
    except ValueError as error:
        provider.error = TushareProviderError(
            TushareErrorCode.BLOCKED_PERMISSION,
            "rt_min",
        )
        provider.error.__context__ = error
    active = _ActiveSymbols(SYMBOLS[:2])
    history = _FakeHistory()
    history.seed_before_target(SYMBOLS[:2], bucket_end)
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.run_realtime_batch(
                bar_end=bucket_end,
                observed_at=_at(9, 35, 12),
            )
        )
    finally:
        controller.close()

    assert result.health.blocked_symbol_count == 2
    assert all(
        context.health.error_code is SymbolHealthErrorCode.PROVIDER_BLOCKED
        for context in result.contexts
    )
    assert sentinel not in repr(result)
    assert history.persisted_symbols == []


def test_runtime_rejects_more_than_ten_active_symbols_before_provider_call() -> None:
    active = _ActiveSymbols(SYMBOLS + ("000011.SZ",))
    provider = _FakeProvider([])
    history = _FakeHistory()
    controller = _controller(_at(9, 35, 12))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
    )

    try:
        with pytest.raises(ValueError, match="at most 10"):
            asyncio.run(
                service.run_realtime_batch(
                    bar_end=_at(9, 35),
                    observed_at=_at(9, 35, 12),
                )
            )
    finally:
        controller.close()

    assert provider.calls == []


def _recovery_service(
    *,
    provider: _FakeProvider,
    active: _ActiveSymbols,
    history: _FakeHistory,
    controller: TushareRequestController,
    realtime_pending: Callable[[], bool] | None = None,
) -> RecoveryService:
    return RecoveryService(
        provider=provider,
        request_controller=controller,
        active_symbols=active,
        persist_minutes=history.persist_minutes,
        is_open_on=lambda _trade_date: True,
        realtime_pending=realtime_pending or (lambda: False),
    )


def test_startup_recovery_is_serial_sorted_and_idempotent_for_active_symbols() -> None:
    symbols = SYMBOLS[:3]
    minute_ends = (_at(9, 31), _at(9, 32), _at(9, 33))
    provider = _FakeProvider([])
    for symbol in symbols:
        second = _bar(symbol, minute_ends[1])
        provider.recovery_rows[symbol] = [
            _bar(symbol, minute_ends[2]),
            second,
            _bar(symbol, minute_ends[0]),
            second,
        ]
    history = _FakeHistory()
    controller = _controller(_at(9, 33, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols(symbols),
        history=history,
        controller=controller,
    )

    try:
        first = asyncio.run(service.recover_startup(trade_date=minute_ends[0].date()))
        second = asyncio.run(service.recover_startup(trade_date=minute_ends[0].date()))
    finally:
        controller.close()

    assert first.mode is RecoveryMode.STARTUP
    assert first.attempted_symbols == symbols
    assert first.persisted_bar_count == 9
    assert second.persisted_bar_count == 9
    assert provider.recovery_calls == list(symbols + symbols)
    assert provider.maximum_recovery_active == 1
    assert len(history.minutes) == 9
    assert all(batch == minute_ends for batch in history.persisted_batches)
    assert all(result.error_code is None for result in first.results)


def test_targeted_recovery_persists_only_explicit_detected_gaps() -> None:
    symbol = SYMBOLS[0]
    all_ends = tuple(_at(9, minute) for minute in range(31, 36))
    requested_gaps = (all_ends[1], all_ends[3])
    provider = _FakeProvider([])
    provider.recovery_rows[symbol] = [_bar(symbol, end) for end in reversed(all_ends)]
    history = _FakeHistory()
    controller = _controller(_at(9, 35, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols(SYMBOLS[:2]),
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(
            service.repair_detected_gaps(
                trade_date=all_ends[0].date(),
                gaps={symbol: requested_gaps},
            )
        )
    finally:
        controller.close()

    assert result.mode is RecoveryMode.GAP_REPAIR
    assert result.attempted_symbols == (symbol,)
    assert result.persisted_bar_count == 2
    assert provider.recovery_calls == [symbol]
    assert history.persisted_batches == [requested_gaps]
    assert set(history.minutes) == {(symbol, end) for end in requested_gaps}
    assert result.results[0].requested_gaps == requested_gaps
    assert result.results[0].recovered_ends == requested_gaps
    assert result.results[0].remaining_gaps == ()


def test_recovery_yields_before_starting_another_symbol_when_realtime_is_pending() -> None:
    symbols = SYMBOLS[:3]
    provider = _FakeProvider([])
    for symbol in symbols:
        provider.recovery_rows[symbol] = [_bar(symbol, _at(9, 31))]
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols(symbols),
        history=history,
        controller=controller,
        realtime_pending=lambda: len(provider.recovery_calls) >= 1,
    )

    try:
        result = asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
    finally:
        controller.close()

    assert result.yielded_to_realtime is True
    assert result.attempted_symbols == (symbols[0],)
    assert provider.recovery_calls == [symbols[0]]
    assert history.persisted_symbols == [symbols[0]]


@pytest.mark.parametrize(
    ("provider_code", "expected_code"),
    [
        (TushareErrorCode.BLOCKED_PERMISSION, RecoveryErrorCode.BLOCKED_PERMISSION),
        (TushareErrorCode.RATE_LIMITED, RecoveryErrorCode.RATE_LIMITED),
    ],
)
def test_recovery_permission_and_rate_limit_fail_closed_without_detail(
    provider_code: TushareErrorCode,
    expected_code: RecoveryErrorCode,
) -> None:
    symbols = SYMBOLS[:2]
    sentinel = "sensitive-recovery-provider-body"
    provider = _FakeProvider([])
    try:
        raise ValueError(sentinel)
    except ValueError as error:
        blocked = TushareProviderError(provider_code, "rt_min_daily")
        blocked.__context__ = error
        provider.recovery_errors[symbols[0]] = blocked
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols(symbols),
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
    finally:
        controller.close()

    assert result.attempted_symbols == symbols
    assert provider.recovery_calls == [symbols[0]]
    assert all(item.error_code is expected_code for item in result.results)
    assert history.persisted_symbols == []
    assert sentinel not in repr(result)


def test_recovery_transient_backoff_is_shared_by_startup_and_gap_repair() -> None:
    symbol = SYMBOLS[0]
    provider = _FakeProvider([])
    provider.recovery_errors[symbol] = TushareProviderError(
        TushareErrorCode.TRANSIENT,
        "rt_min_daily",
    )
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols((symbol,)),
        history=history,
        controller=controller,
    )

    try:
        startup = asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
        provider.recovery_errors.clear()
        targeted = asyncio.run(
            service.repair_detected_gaps(
                trade_date=_at(9, 31).date(),
                gaps={symbol: (_at(9, 31),)},
            )
        )
    finally:
        controller.close()

    assert startup.results[0].error_code is RecoveryErrorCode.TRANSIENT
    assert targeted.results[0].error_code is RecoveryErrorCode.TRANSIENT
    assert targeted.results[0].next_retry_at == _at(9, 31, 42)
    assert provider.recovery_calls == [symbol]
    assert history.persisted_symbols == []


def test_recovery_rejects_invalid_symbol_or_wrong_date_rows_without_persistence() -> None:
    symbol = SYMBOLS[0]
    provider = _FakeProvider([])
    provider.recovery_rows[symbol] = [
        _bar(symbol, _at(9, 31, day=25)),
        _bar(SYMBOLS[1], _at(9, 31)),
    ]
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols((symbol,)),
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
    finally:
        controller.close()

    assert result.results[0].error_code is RecoveryErrorCode.INVALID_RESPONSE
    assert result.persisted_bar_count == 0
    assert history.persisted_symbols == []


def test_recovery_persistence_failure_isolated_without_leaking_storage_detail() -> None:
    failed_symbol, healthy_symbol = SYMBOLS[:2]
    provider = _FakeProvider([])
    provider.recovery_rows[failed_symbol] = [_bar(failed_symbol, _at(9, 31))]
    provider.recovery_rows[healthy_symbol] = [_bar(healthy_symbol, _at(9, 31))]
    history = _FakeHistory()
    history.fail_symbol = failed_symbol
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols((failed_symbol, healthy_symbol)),
        history=history,
        controller=controller,
    )

    try:
        result = asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
    finally:
        controller.close()

    assert result.results[0].error_code is RecoveryErrorCode.PERSISTENCE_FAILED
    assert result.results[1].error_code is None
    assert result.persisted_bar_count == 1
    assert provider.recovery_calls == [failed_symbol, healthy_symbol]
    assert history.persisted_symbols == [healthy_symbol]
    assert "sensitive-storage-detail" not in repr(result)


def test_recovery_rejects_more_than_ten_active_symbols_before_provider_call() -> None:
    provider = _FakeProvider([])
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    service = _recovery_service(
        provider=provider,
        active=_ActiveSymbols(SYMBOLS + ("000011.SZ",)),
        history=history,
        controller=controller,
    )

    try:
        with pytest.raises(ValueError, match="at most 10"):
            asyncio.run(service.recover_startup(trade_date=_at(9, 31).date()))
    finally:
        controller.close()

    assert provider.recovery_calls == []
    assert history.persisted_symbols == []
