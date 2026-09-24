"""T030-T033 ten-symbol orchestration, recovery, and evaluation contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, func, select

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DailyIndicatorProvenance,
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EpisodeStatus,
    EpisodeTransitionAction,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationResult,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationIdentity,
    IntradayEvaluationTarget,
    LowZoneEpisodeSnapshot,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationTarget,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    OfficialCloseBelowLevelCondition,
    PriceInZoneCondition,
    TradePlan,
)
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    migrate_trade_plan_to_schema_v2,
    validate_trade_plan,
)
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    expected_five_minute_ends,
)
from trade_plan_monitor.market_data.indicators import calculate_ta_v1
from trade_plan_monitor.market_data.models import (
    DailyBar,
    MinuteBar,
    ProviderCapabilities,
    TradingDay,
)
from trade_plan_monitor.market_data.reconciliation import (
    CloseReconciliationStatus,
    reconcile_daily_close,
)
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.runtime.clock import Clock
from trade_plan_monitor.runtime.health import (
    SymbolHealthErrorCode,
    SymbolHealthSnapshot,
    SymbolHealthTracker,
)
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.production_context import ProductionContextBuilder
from trade_plan_monitor.runtime.recovery import (
    RecoveryErrorCode,
    RecoveryMode,
    RecoveryService,
)
from trade_plan_monitor.runtime.request_control import TushareRequestController
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import (
    IntradayCycleStatus,
    IntradayMarketFacts,
    OfficialCloseCycleStatus,
    OfficialCloseMarketFacts,
    RuntimeDeadlineCoordinator,
    RuntimeEvaluationService,
    StaleActivationGenerationError,
)
from trade_plan_monitor.runtime.symbol_service import SymbolService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEvent, MonitorEventType
from trade_plan_monitor.state.models import (
    AlertEvent as AlertEventRow,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    EvaluationLedger,
    PendingOfficialClose,
    RiskState,
    SymbolDecisionHead,
    SymbolHealth,
    ZoneEpisode,
)
from trade_plan_monitor.state.models import (
    DailyBar as DailyBarRow,
)
from trade_plan_monitor.state.models import (
    EvaluationResult as EvaluationResultRow,
)
from trade_plan_monitor.state.models import (
    FiveMinuteBar as FiveMinuteBarRow,
)
from trade_plan_monitor.state.models import (
    MinuteBar as MinuteBarRow,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
SYMBOLS: Final = tuple(f"{index:06d}.SZ" for index in range(1, 11))
SAMPLE_PLAN_PATH: Final = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"


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
    health_tracker: SymbolHealthTracker | None = None,
    clock: Clock | None = None,
) -> SymbolService:
    return SymbolService(
        provider=provider,
        request_controller=controller,
        active_symbols=active,
        persist_minutes=history.persist_minutes,
        load_minutes=history.load_minutes,
        persist_five_minute=history.persist_five_minute,
        is_open_on=is_open_on or (lambda _trade_date: True),
        health_tracker=health_tracker or SymbolHealthTracker(stale_after=timedelta(seconds=60)),
        clock=clock,
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


@pytest.mark.parametrize("restart", [False, True])
def test_repaired_historical_gap_clears_on_the_next_bucket(
    restart: bool,
) -> None:
    symbol = SYMBOLS[0]
    first_end = _at(9, 35)
    next_end = _at(9, 40)
    provider = _FakeProvider([])
    active = _ActiveSymbols((symbol,))
    history = _FakeHistory()
    history.seed_before_target((symbol,), first_end)
    controller = _controller(_at(9, 35, 12))
    tracker = SymbolHealthTracker(stale_after=timedelta(seconds=60))
    service = _service(
        provider=provider,
        active=active,
        history=history,
        controller=controller,
        health_tracker=tracker,
    )

    try:
        first = asyncio.run(
            service.run_realtime_batch(
                bar_end=first_end,
                observed_at=_at(9, 35, 12),
            )
        ).context_for(symbol)
        assert first.health.gaps == (first_end,)

        provider.recovery_rows[symbol] = [_bar(symbol, first_end)]
        recovery = _recovery_service(
            provider=provider,
            active=active,
            history=history,
            controller=controller,
        )
        repaired = asyncio.run(
            recovery.repair_detected_gaps(
                trade_date=first_end.date(),
                gaps={symbol: first.health.gaps},
            )
        )
        assert repaired.results[0].recovered_ends == (first_end,)

        history.seed_before_target((symbol,), next_end)
        provider.rows = [_bar(symbol, next_end)]
        if restart:
            tracker = SymbolHealthTracker(stale_after=timedelta(seconds=60))
            tracker.restore((first.health,))
            service = _service(
                provider=provider,
                active=active,
                history=history,
                controller=controller,
                health_tracker=tracker,
            )

        following = asyncio.run(
            service.run_realtime_batch(
                bar_end=next_end,
                observed_at=_at(9, 40, 12),
            )
        ).context_for(symbol)
    finally:
        controller.close()

    assert following.five_minute_bar is not None
    assert following.health.gaps == ()
    assert following.health.data_health.status.value == "LIVE"
    assert following.health.actionable is True


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


@pytest.fixture
def runtime_engine(tmp_path: Path) -> Engine:
    engine = create_sqlite_engine(tmp_path / "runtime.db")
    upgrade_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


class _FailingAlertOutbox:
    def has_dedup_key(self, _dedup_key: str) -> bool:
        return False

    def enqueue(self, _payload: object) -> None:
        raise RuntimeError("forced outbox failure")


class _TrackedUnitOfWork:
    def __init__(
        self,
        inner: SqlAlchemyUnitOfWork,
        tracker: dict[str, int],
        *,
        fail_alert: bool,
    ) -> None:
        self._inner = inner
        self._tracker = tracker
        self._fail_alert = fail_alert

    def __enter__(self):
        self._tracker["active"] += 1
        try:
            self._inner.__enter__()
        except BaseException:
            self._tracker["active"] -= 1
            raise
        return self

    def __exit__(self, error_type, error, traceback) -> None:
        try:
            self._inner.__exit__(error_type, error, traceback)
        finally:
            self._tracker["active"] -= 1

    @property
    def alerts(self):
        if self._fail_alert:
            return _FailingAlertOutbox()
        return self._inner.alerts

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _runtime_uow_factory(
    engine: Engine,
    tracker: dict[str, int],
    *,
    now: datetime,
    fail_alert: bool = False,
):
    session_factory = create_session_factory(engine)

    def factory() -> _TrackedUnitOfWork:
        return _TrackedUnitOfWork(
            SqlAlchemyUnitOfWork(session_factory, clock=lambda: now),
            tracker,
            fail_alert=fail_alert,
        )

    return factory


def _runtime_plan() -> TradePlan:
    return load_plan_yaml(SAMPLE_PLAN_PATH.read_text(encoding="utf-8"))


def _runtime_context(
    plan: TradePlan,
    facts: IntradayMarketFacts,
) -> EvaluationContext:
    plan_hash = plan_sha256(plan)
    evaluated_at = facts.evaluated_at
    return EvaluationContext(
        evaluated_at=evaluated_at,
        target=IntradayEvaluationTarget(bucket_end=facts.bucket_end),
        plan=plan,
        plan_hash=plan_hash,
        plan_active=True,
        activated_at=facts.bucket_end.replace(hour=9, minute=0),
        current_day_minutes=facts.current_day_minutes,
        complete_5m_bars=facts.complete_five_minute_bars,
        official_daily_bars=(),
        five_minute_indicators=None,
        daily_indicator_snapshot=None,
        close_reconciliation=reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=facts.bucket_end.date(),
            daily_bars=(facts.provisional_daily_bar,),
        ),
        trading_calendar=(
            TradingDay(
                exchange=plan.market,
                cal_date=facts.bucket_end.date(),
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        ),
        daily_limit=None,
        data_health=DataHealthSnapshot(
            symbol=plan.symbol,
            status=DataHealthStatus.LIVE,
            latest_bar_end=facts.bucket_end,
            data_age_seconds=int((evaluated_at - facts.bucket_end).total_seconds()),
            required_data_complete=True,
            fresh=True,
        ),
        positions=(),
        low_zone_episode=None,
        risk_state=RiskStateSnapshot(
            symbol=plan.symbol,
            plan_hash=plan_hash,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=6080,
            revision=0,
            updated_at=facts.bucket_end,
        ),
        manual_event_risk=False,
    )


def _daily_bar(
    *,
    trade_date: date,
    close_fen: int,
    is_official: bool,
    received_at: datetime | None = None,
) -> DailyBar:
    return DailyBar(
        symbol="003043.SZ",
        trade_date=trade_date,
        open_fen=6100,
        high_fen=max(6150, close_fen),
        low_fen=min(6000, close_fen),
        close_fen=close_fen,
        volume_shares=1_000_000,
        amount_yuan=Decimal("61000000"),
        is_official=is_official,
        received_at=received_at
        or datetime.combine(
            trade_date,
            time(15, 20) if is_official else time(15, 0),
            SHANGHAI,
        ),
    )


def _official_context(
    plan: TradePlan,
    facts: OfficialCloseMarketFacts,
) -> EvaluationContext:
    plan_hash = plan_sha256(plan)
    return EvaluationContext(
        evaluated_at=facts.evaluated_at,
        target=OfficialCloseEvaluationTarget(trade_date=facts.trade_date),
        plan=plan,
        plan_hash=plan_hash,
        plan_active=True,
        activated_at=datetime.combine(facts.trade_date, time(9, 0), SHANGHAI),
        current_day_minutes=(),
        complete_5m_bars=(),
        official_daily_bars=facts.official_daily_bars,
        five_minute_indicators=None,
        daily_indicator_snapshot=facts.daily_indicator_snapshot,
        close_reconciliation=facts.close_reconciliation,
        trading_calendar=(
            TradingDay(
                exchange=plan.market,
                cal_date=facts.trade_date,
                is_open=True,
                previous_trade_date=facts.trade_date - timedelta(days=3),
            ),
        ),
        daily_limit=None,
        data_health=DataHealthSnapshot(
            symbol=plan.symbol,
            status=DataHealthStatus.STARTING,
            latest_bar_end=None,
            data_age_seconds=None,
            required_data_complete=False,
            fresh=False,
        ),
        positions=(),
        low_zone_episode=None,
        risk_state=RiskStateSnapshot(
            symbol=plan.symbol,
            plan_hash=plan_hash,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=plan.levels.risk_line_fen,
            revision=0,
            updated_at=facts.source_as_of,
        ),
        manual_event_risk=False,
    )


def _actionable_episode_result(
    plan: TradePlan,
    context: EvaluationContext,
) -> EvaluationResult:
    plan_hash = plan_sha256(plan)
    target = context.target
    assert isinstance(target, IntradayEvaluationTarget)
    evidence = ConditionEvidence(
        condition=PriceInZoneCondition(zone="LOW_BUY"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=context.current_day_minutes[-1].close_fen,
                unit=EvidenceUnit.FEN,
            ),
        ),
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    episode = LowZoneEpisodeSnapshot(
        episode_id="episode-runtime-001",
        plan_hash=plan_hash,
        symbol=plan.symbol,
        started_at=target.bucket_end.replace(hour=9, minute=31),
        episode_low_fen=min(bar.low_fen for bar in context.current_day_minutes),
        bars_since_low=1,
        last_processed_bucket_end=target.bucket_end,
        status=EpisodeStatus.ALERTED,
        alerted_signal="BUY_CORE_READY",
    )
    signal = SignalIntent(
        signal_type=ActionableSignalType.BUY_CORE_READY,
        plan_hash=plan_hash,
        symbol=plan.symbol,
        trading_date=target.bucket_end.date(),
        cause_id=episode.episode_id,
        quantity=100,
        bucket="CORE",
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    snapshot = SymbolDecisionSnapshot(
        symbol=plan.symbol,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=target.bucket_end,
        price_fen=context.current_day_minutes[-1].close_fen,
        zone=DecisionZone.LOW_BUY,
        signal_type=SignalType.BUY_CORE_READY,
        position=PositionSummary(
            core_quantity=0,
            tactical_quantity=0,
            total_quantity=0,
            sellable_core_quantity=0,
            sellable_tactical_quantity=0,
        ),
        episode=episode,
        risk=context.risk_state,
        data_health=context.data_health,
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=(
            EpisodeTransitionIntent(
                action=EpisodeTransitionAction.UPSERT,
                episode=episode,
            ),
        ),
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=plan_hash,
            symbol=plan.symbol,
            bucket_end=target.bucket_end,
        ),
    )


def test_intraday_service_fetches_outside_transaction_and_assembles_exact_context(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    minute_ends = expected_five_minute_ends(bucket_end)
    fetched = [_bar(plan.symbol, minute_end) for minute_end in minute_ends]
    tracker = {"active": 0}
    observed: list[str] = []
    published: list[MonitorEvent] = []

    async def fetch_minutes(symbol: str, target: datetime) -> list[MinuteBar]:
        assert tracker["active"] == 0
        assert (symbol, target) == (plan.symbol, bucket_end)
        observed.append("fetch")
        return fetched

    def build_context(
        context_plan: TradePlan,
        facts: IntradayMarketFacts,
    ) -> EvaluationContext:
        assert tracker["active"] == 0
        observed.append("context")
        assert facts.current_day_minutes == tuple(fetched)
        assert facts.source_as_of == bucket_end
        assert facts.provenance.value == "PROVISIONAL"
        assert facts.provisional_daily_bar.is_official is False
        with pytest.raises(ValidationError):
            facts.model_copy(update={"source_as_of": _at(9, 40)})
        return _runtime_context(context_plan, facts)

    def pure_evaluator(context: EvaluationContext) -> EvaluationResult:
        assert tracker["active"] == 0
        observed.append("evaluate")
        with pytest.raises(ValidationError, match="frozen"):
            context.plan_active = False
        return evaluate(context)

    def publish(event: MonitorEvent) -> None:
        assert tracker["active"] == 0
        observed.append("publish")
        published.append(event)

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=build_context,
        evaluator=pure_evaluator,
        committed_event_publisher=publish,
    )

    result = asyncio.run(
        service.run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert result.status is IntradayCycleStatus.COMMITTED
    assert result.claim_created is True
    assert result.committed_event is None
    assert observed == ["fetch", "context", "evaluate", "publish", "publish"]
    assert len(published) == 2
    assert published[0].event_type is MonitorEventType.SYMBOL_SNAPSHOT_UPDATED
    assert published[1].event_type is MonitorEventType.SYMBOL_HEALTH_UPDATED
    assert published[0].payload.symbol == plan.symbol
    assert published[0].payload.result_hash == result.evaluation_result.result_hash
    assert tracker["active"] == 0
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(MinuteBarRow)) == 5
        assert session.scalar(select(func.count()).select_from(FiveMinuteBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 1
        head = session.get(SymbolDecisionHead, plan.symbol)
        assert head is not None
        assert head.result_hash == result.evaluation_result.result_hash
        assert head.event_sequence == published[0].sequence


def test_intraday_service_injects_one_validated_reference_snapshot(
    runtime_engine: Engine,
) -> None:
    original = _runtime_plan()
    migrated = migrate_trade_plan_to_schema_v2(original, new_version=2)
    plan_payload = migrated.model_dump(mode="python", round_trip=True)
    plan_payload["entry"] = {
        "condition": {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    }
    plan = TradePlan.model_validate(plan_payload)
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    fetched = [
        _bar(plan.symbol, minute_end) for minute_end in expected_five_minute_ends(bucket_end)
    ]

    def index_bar(
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        bar_at: datetime,
    ) -> MarketIndexBar:
        return MarketIndexBar(
            index_code=index_code,
            interval=interval,
            bar_at=bar_at,
            open_points=Decimal("100"),
            high_points=Decimal("100"),
            low_points=Decimal("100"),
            close_points=Decimal("100"),
            observed_at=(
                evaluated_at
                if interval is MarketIndexInterval.FIVE_MINUTE
                else bar_at + timedelta(minutes=1)
            ),
            source_kind=(
                MarketIndexSourceKind.PROVISIONAL
                if interval is MarketIndexInterval.FIVE_MINUTE
                else MarketIndexSourceKind.OFFICIAL
            ),
            provider_revision=1,
        )

    class IndexProvider:
        def __init__(self) -> None:
            self.call_count = 0

        async def acquire_index_data(
            self,
            *,
            index_code: MarketIndexCode,
            decision_cutoff: datetime,
            five_minute_bar_count: int,
            official_daily_bar_count: int,
        ) -> MarketIndexProviderBatch:
            self.call_count += 1
            assert decision_cutoff == bucket_end
            assert (five_minute_bar_count, official_daily_bar_count) == (1, 2)
            return MarketIndexProviderBatch(
                index_code=index_code,
                five_minute_bars=(
                    index_bar(index_code, MarketIndexInterval.FIVE_MINUTE, bucket_end),
                ),
                official_daily_bars=tuple(
                    index_bar(
                        index_code,
                        MarketIndexInterval.OFFICIAL_DAILY,
                        datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
                    )
                    for day in (22, 23)
                ),
                content_revision=1,
                observed_at=evaluated_at,
            )

    provider = IndexProvider()
    captured: list[EvaluationContext] = []

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return fetched

    def evaluator(context: EvaluationContext) -> EvaluationResult:
        captured.append(context)
        return evaluate(context)

    tracker = {"active": 0}
    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        evaluator=evaluator,
        committed_event_publisher=lambda _event: None,
        market_index_service=RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider)),
    )

    result = asyncio.run(
        service.run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert result.status is IntradayCycleStatus.COMMITTED
    assert provider.call_count == len(ALWAYS_ON_INDEX_CODES)
    assert len(captured) == 1
    snapshot = captured[0].reference_market_snapshot
    assert snapshot is not None
    assert snapshot.index_code is MarketIndexCode.SHENZHEN_COMPONENT
    assert snapshot.snapshot_hash


def test_intraday_batch_uses_prefetched_deadline_minutes_without_second_fetch(
    runtime_engine: Engine,
) -> None:
    first_plan = _runtime_plan()
    second_payload = first_plan.model_dump(mode="python", round_trip=True)
    second_payload.update(
        {
            "plan_id": "runtime-prefetched-second",
            "symbol": "000002.SZ",
            "name": "Runtime Prefetched Second",
        }
    )
    second_plan = TradePlan.model_validate(second_payload)
    plans = (first_plan, second_plan)
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    prefetched = {
        plan.symbol: tuple(
            _bar(plan.symbol, minute_end) for minute_end in expected_five_minute_ends(bucket_end)
        )
        for plan in plans
    }
    fetch_count = 0

    async def forbidden_fetch(_symbol: str, _target: datetime) -> list[MinuteBar]:
        nonlocal fetch_count
        fetch_count += 1
        pytest.fail("prefetched deadline evaluation must not fetch quotes")

    tracker = {"active": 0}
    service = RuntimeEvaluationService(
        fetch_minutes=forbidden_fetch,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )

    results = asyncio.run(
        service.run_intraday_batch_from_minutes(
            plans=plans,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
            minutes_by_symbol=prefetched,
        )
    )

    assert fetch_count == 0
    assert len(results) == 2
    assert all(result.status is IntradayCycleStatus.COMMITTED for result in results)


def test_prefetched_symbol_health_replaces_context_builder_health_without_promotion(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    minutes = tuple(
        _bar(plan.symbol, minute_end) for minute_end in expected_five_minute_ends(bucket_end)
    )
    captured: list[EvaluationContext] = []
    health = SymbolHealthSnapshot(
        symbol=plan.symbol,
        observed_at=evaluated_at,
        target_end=bucket_end,
        data_health=DataHealthSnapshot(
            symbol=plan.symbol,
            status=DataHealthStatus.GAPPED,
            latest_bar_end=bucket_end,
            data_age_seconds=20,
            required_data_complete=False,
            fresh=True,
        ),
        gaps=(_at(9, 34),),
        consecutive_incomplete_buckets=0,
        last_required_bucket_end=bucket_end,
        error_code=SymbolHealthErrorCode.HISTORY_GAP,
    )

    def evaluator(context: EvaluationContext) -> EvaluationResult:
        captured.append(context)
        return evaluate(context)

    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: pytest.fail("prefetched minutes must be reused"),
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            {"active": 0},
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        evaluator=evaluator,
        committed_event_publisher=lambda _event: None,
    )

    result = asyncio.run(
        service.run_intraday_batch_from_minutes(
            plans=(plan,),
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
            minutes_by_symbol={plan.symbol: minutes},
            health_by_symbol={plan.symbol: health},
        )
    )[0]

    assert result.status is IntradayCycleStatus.COMMITTED
    assert captured[0].data_health is health.data_health
    assert captured[0].data_health.status is DataHealthStatus.GAPPED


def test_plan_rotation_during_fetch_is_discarded_and_next_cycle_still_commits(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    source_text = SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    seed_factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=datetime(2026, 8, 24, 9, 0, tzinfo=SHANGHAI),
    )
    with seed_factory() as work:
        work.plans.save_draft(plan, source_text=source_text)
        work.plans.activate(
            plan,
            expected_revision=0,
            validation=validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            ),
        )
        work.commit()

    factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=evaluated_at + timedelta(seconds=1),
    )

    calls = 0

    async def rotating_fetch(symbol: str, target: datetime) -> list[MinuteBar]:
        nonlocal calls
        calls += 1
        if calls == 1:
            with factory() as work:
                work.plans.deactivate(symbol, expected_revision=1)
                work.commit()
        return [_bar(symbol, end) for end in expected_five_minute_ends(target)]

    service = RuntimeEvaluationService(
        fetch_minutes=rotating_fetch,
        unit_of_work_factory=factory,
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )

    stale_results = asyncio.run(
        service.run_intraday_batch(
            plans=(plan,),
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )
    assert stale_results == ()
    inactive_restore = service.load_persisted_symbol_health((plan.symbol,))
    assert inactive_restore[0].activation_revision == 2
    assert inactive_restore[0].snapshot is None
    with factory() as work:
        assert work.projections.get_decision_head(plan.symbol) is None
        work.plans.activate(
            plan,
            expected_revision=2,
            validation=validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            ),
        )
        work.commit()

    recovered = asyncio.run(
        service.run_intraday_batch(
            plans=(plan,),
            bucket_end=bucket_end,
            evaluated_at=evaluated_at + timedelta(seconds=1),
        )
    )
    assert len(recovered) == 1
    assert recovered[0].status is IntradayCycleStatus.COMMITTED
    assert calls == 2


def test_stale_activation_error_is_a_typed_expected_runtime_outcome() -> None:
    error = StaleActivationGenerationError("003043.SZ")

    assert error.symbol == "003043.SZ"
    assert "003043.SZ" in str(error)


def test_final_commit_fence_rejects_a_plan_outside_its_market_date(
    runtime_engine: Engine,
) -> None:
    payload = _runtime_plan().model_dump(mode="python", round_trip=True)
    payload["activation"] = {
        "mode": "DATE_RANGE",
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 24),
    }
    plan = TradePlan.model_validate(payload)
    factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=datetime(2026, 8, 24, 9, 0, tzinfo=SHANGHAI),
    )
    with factory() as work:
        work.plans.save_draft(
            plan,
            source_text=SAMPLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
        work.plans.activate(
            plan,
            expected_revision=0,
            validation=validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            ),
        )
        work.commit()

    with factory() as work:
        RuntimeEvaluationService._require_evaluated_plan_active(
            work,
            plan,
            expected_revision=1,
            market_date=date(2026, 8, 24),
        )
        with pytest.raises(StaleActivationGenerationError):
            RuntimeEvaluationService._require_evaluated_plan_active(
                work,
                plan,
                expected_revision=1,
                market_date=date(2026, 8, 25),
            )


def test_production_context_marks_an_out_of_validity_market_date_inactive(
    runtime_engine: Engine,
) -> None:
    payload = _runtime_plan().model_dump(mode="python", round_trip=True)
    payload["activation"] = {
        "mode": "TRADING_DAY",
        "trading_day": date(2026, 8, 24),
    }
    plan = TradePlan.model_validate(payload)
    bucket_end = _at(9, 35, day=25)
    evaluated_at = bucket_end + timedelta(seconds=20)
    seed_factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=datetime(2026, 8, 24, 9, 0, tzinfo=SHANGHAI),
    )
    with seed_factory() as work:
        work.plans.save_draft(
            plan,
            source_text=SAMPLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
        work.plans.activate(
            plan,
            expected_revision=0,
            validation=validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            ),
        )
        work.history.upsert_daily_bars(
            (
                _daily_bar(
                    trade_date=date(2026, 8, 24),
                    close_fen=6400,
                    is_official=True,
                ),
            )
        )
        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange=plan.market,
                    cal_date=bucket_end.date(),
                    is_open=True,
                    previous_trade_date=date(2026, 8, 24),
                ),
            )
        )
        work.commit()

    factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=evaluated_at + timedelta(seconds=1),
    )

    captured: list[EvaluationContext] = []
    production_builder = ProductionContextBuilder(factory)

    def context_builder(
        candidate: TradePlan,
        facts: IntradayMarketFacts,
    ) -> EvaluationContext:
        context = production_builder(candidate, facts)
        captured.append(context)
        return context

    async def fetch_minutes(_symbol: str, target: datetime) -> list[MinuteBar]:
        return [_bar(plan.symbol, minute_end) for minute_end in expected_five_minute_ends(target)]

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=factory,
        context_builder=context_builder,
        committed_event_publisher=lambda _event: None,
    )

    results = asyncio.run(
        service.run_intraday_batch(
            plans=(plan,),
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert results == ()
    assert len(captured) == 1
    assert captured[0].plan_active is False
    with factory() as work:
        assert work.projections.get_decision_head(plan.symbol) is None


def test_deadline_coordinator_starts_one_stock_batch_and_reuses_it_for_every_plan(
    runtime_engine: Engine,
) -> None:
    first_plan = _runtime_plan()
    second_payload = first_plan.model_dump(mode="python", round_trip=True)
    second_payload.update(
        {
            "plan_id": "runtime-deadline-second",
            "symbol": "000002.SZ",
            "name": "Runtime Deadline Second",
        }
    )
    plans = (first_plan, TradePlan.model_validate(second_payload))
    symbols = tuple(plan.symbol for plan in plans)
    bucket_end = _at(9, 35)
    observed_at = bucket_end + timedelta(seconds=12)
    provider = _FakeProvider([_bar(symbol, bucket_end) for symbol in symbols])
    history = _FakeHistory()
    history.seed_before_target(symbols, bucket_end)
    controller = _controller(observed_at)
    symbol_service = _service(
        provider=provider,
        active=_ActiveSymbols(symbols),
        history=history,
        controller=controller,
    )
    fetch_count = 0

    async def forbidden_fetch(_symbol: str, _target: datetime) -> list[MinuteBar]:
        nonlocal fetch_count
        fetch_count += 1
        pytest.fail("deadline evaluation must reuse its realtime batch")

    evaluation_service = RuntimeEvaluationService(
        fetch_minutes=forbidden_fetch,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            {"active": 0},
            now=observed_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )
    coordinator = RuntimeDeadlineCoordinator(
        clock=_ImmediateClock(observed_at),
        active_plans=lambda: plans,
        symbol_service=symbol_service,
        evaluation_service=evaluation_service,
    )
    deadline = MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=bucket_end.date(),
        due_at=observed_at,
        bar_end=bucket_end,
    )

    try:
        results = asyncio.run(coordinator.run_deadline(deadline))
    finally:
        controller.close()

    assert provider.calls == [symbols]
    assert fetch_count == 0
    assert len(results) == len(plans)
    assert all(result.status is IntradayCycleStatus.COMMITTED for result in results)


def test_deadline_uses_post_fetch_whole_second_for_health_and_evaluation(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 35)
    requested_at = bucket_end + timedelta(seconds=12)
    received_at = requested_at + timedelta(microseconds=250_000)
    expected_observed_at = bucket_end + timedelta(seconds=13)
    clock = _ImmediateClock(requested_at)

    class DelayedProvider(_FakeProvider):
        def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]:
            clock.current = received_at
            return super().realtime_minutes(symbols)

    current = _bar(plan.symbol, bucket_end).model_copy(update={"received_at": received_at})
    provider = DelayedProvider([current])
    history = _FakeHistory()
    history.seed_before_target((plan.symbol,), bucket_end)
    controller = _controller(requested_at)
    symbol_service = _service(
        provider=provider,
        active=_ActiveSymbols((plan.symbol,)),
        history=history,
        controller=controller,
        clock=clock,
    )
    evaluation_service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: pytest.fail("prefetched minutes must be reused"),
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            {"active": 0},
            now=expected_observed_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )
    coordinator = RuntimeDeadlineCoordinator(
        clock=clock,
        active_plans=lambda: (plan,),
        symbol_service=symbol_service,
        evaluation_service=evaluation_service,
    )
    deadline = MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=bucket_end.date(),
        due_at=requested_at,
        bar_end=bucket_end,
    )

    try:
        result = asyncio.run(coordinator.run_deadline(deadline))[0]
    finally:
        controller.close()

    assert result.status is IntradayCycleStatus.COMMITTED
    assert result.facts is not None
    assert result.facts.evaluated_at == expected_observed_at
    assert result.facts.current_day_minutes[-1].received_at == received_at
    assert clock.now() == expected_observed_at


@pytest.mark.parametrize("minute", (31, 35))
def test_deadline_uses_immutable_plan_symbol_snapshot_when_active_set_changes(
    runtime_engine: Engine,
    minute: int,
) -> None:
    plan = _runtime_plan()
    bar_end = _at(9, minute)
    observed_at = bar_end + timedelta(seconds=12)
    active_symbols = _ActiveSymbols((plan.symbol,))
    provider = _FakeProvider([])
    history = _FakeHistory()
    controller = _controller(observed_at)
    symbol_service = _service(
        provider=provider,
        active=active_symbols,
        history=history,
        controller=controller,
    )
    evaluation_service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: (),  # type: ignore[arg-type]
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            {"active": 0},
            now=observed_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )

    def plans_before_concurrent_activation() -> tuple[TradePlan, ...]:
        active_symbols.symbols = (plan.symbol, "000002.SZ")
        return (plan,)

    coordinator = RuntimeDeadlineCoordinator(
        clock=_ImmediateClock(observed_at),
        active_plans=plans_before_concurrent_activation,
        symbol_service=symbol_service,
        evaluation_service=evaluation_service,
    )
    deadline = MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=bar_end.date(),
        due_at=observed_at,
        bar_end=bar_end,
    )
    try:
        assert asyncio.run(coordinator.run_deadline(deadline)) == ()
    finally:
        controller.close()
    assert provider.calls == [(plan.symbol,)]


def test_intraday_batch_unions_requirements_and_shares_one_snapshot_across_plans(
    runtime_engine: Engine,
) -> None:
    original = _runtime_plan()
    migrated = migrate_trade_plan_to_schema_v2(original, new_version=2)
    first_payload = migrated.model_dump(mode="python", round_trip=True)
    first_payload["entry"] = {
        "condition": {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    }
    first_plan = TradePlan.model_validate(first_payload)
    second_payload = migrated.model_dump(mode="python", round_trip=True)
    second_payload.update(
        {
            "plan_id": "runtime-index-batch-second",
            "symbol": "000002.SZ",
            "name": "Runtime Index Batch Second",
            "entry": {
                "condition": {
                    "type": "INDEX_CLOSE_LTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 3,
                }
            },
        }
    )
    second_plan = TradePlan.model_validate(second_payload)
    plans = (first_plan, second_plan)
    bucket_end = _at(9, 40)
    evaluated_at = bucket_end + timedelta(seconds=20)

    def index_bar(
        interval: MarketIndexInterval,
        bar_at: datetime,
        close: str,
    ) -> MarketIndexBar:
        value = Decimal(close)
        return MarketIndexBar(
            index_code=MarketIndexCode.SHENZHEN_COMPONENT,
            interval=interval,
            bar_at=bar_at,
            open_points=value,
            high_points=value,
            low_points=value,
            close_points=value,
            observed_at=(
                evaluated_at
                if interval is MarketIndexInterval.FIVE_MINUTE
                else bar_at + timedelta(minutes=1)
            ),
            source_kind=(
                MarketIndexSourceKind.PROVISIONAL
                if interval is MarketIndexInterval.FIVE_MINUTE
                else MarketIndexSourceKind.OFFICIAL
            ),
            provider_revision=1,
        )

    class IndexProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def acquire_index_data(
            self,
            *,
            index_code: MarketIndexCode,
            decision_cutoff: datetime,
            five_minute_bar_count: int,
            official_daily_bar_count: int,
        ) -> MarketIndexProviderBatch:
            assert index_code is MarketIndexCode.SHENZHEN_COMPONENT
            assert decision_cutoff == bucket_end
            self.calls.append((five_minute_bar_count, official_daily_bar_count))
            return MarketIndexProviderBatch(
                index_code=index_code,
                five_minute_bars=(index_bar(MarketIndexInterval.FIVE_MINUTE, bucket_end, "100"),),
                official_daily_bars=tuple(
                    index_bar(
                        MarketIndexInterval.OFFICIAL_DAILY,
                        datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
                        "90",
                    )
                    for day in (21, 22, 23)
                ),
                content_revision=1,
                observed_at=evaluated_at,
            )

    provider = IndexProvider()
    captured: list[EvaluationContext] = []

    async def fetch_minutes(symbol: str, target: datetime) -> list[MinuteBar]:
        return [
            MinuteBar(
                symbol=symbol,
                bar_end=minute_end,
                open_fen=6400,
                high_fen=6410,
                low_fen=6390,
                close_fen=6405,
                volume_shares=1_000,
                amount_yuan=Decimal("64000"),
                received_at=minute_end + timedelta(seconds=12),
            )
            for minute_end in expected_minute_ends(target.date(), is_open=True)
            if minute_end <= target
        ]

    def evaluator(context: EvaluationContext) -> EvaluationResult:
        captured.append(context)
        return evaluate(context)

    tracker = {"active": 0}
    results = asyncio.run(
        RuntimeEvaluationService(
            fetch_minutes=fetch_minutes,
            unit_of_work_factory=_runtime_uow_factory(
                runtime_engine,
                tracker,
                now=evaluated_at + timedelta(seconds=1),
            ),
            context_builder=_runtime_context,
            evaluator=evaluator,
            committed_event_publisher=lambda _event: None,
            market_index_service=RuntimeMarketIndexService(
                MarketIndexSnapshotCoordinator(provider)
            ),
        ).run_intraday_batch(
            plans=plans,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert provider.calls == [(1, 3)]
    assert len(results) == len(captured) == 2
    assert all(result.status is IntradayCycleStatus.COMMITTED for result in results)
    snapshots = tuple(context.reference_market_snapshot for context in captured)
    snapshot = snapshots[0]
    assert snapshot is not None
    assert snapshot is snapshots[1]
    assert len(snapshot.fact_requests) == 2
    assert {context.plan_hash for context in captured} == {
        plan_sha256(first_plan),
        plan_sha256(second_plan),
    }


def test_intraday_service_latest_quote_cannot_hide_gapped_current_day_context(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 35)
    tracker = {"active": 0}

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return [_bar(plan.symbol, bucket_end)]

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=bucket_end + timedelta(seconds=30),
        ),
        context_builder=lambda _plan, _facts: pytest.fail("context must stay blocked"),
        committed_event_publisher=lambda _event: pytest.fail("nothing may publish"),
    )

    result = asyncio.run(
        service.run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=bucket_end + timedelta(seconds=20),
        )
    )

    assert result.status is IntradayCycleStatus.INCOMPLETE
    assert result.claim_created is False
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(MinuteBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 0
        assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 0

    expected = expected_five_minute_ends(bucket_end)

    async def recover_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return [_bar(plan.symbol, minute_end) for minute_end in expected[:-1]]

    recovery_publications: list[MonitorEvent] = []
    recovered = RuntimeEvaluationService(
        fetch_minutes=recover_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=bucket_end + timedelta(seconds=30),
        ),
        context_builder=_runtime_context,
        evaluator=evaluate,
        committed_event_publisher=recovery_publications.append,
    )
    recovery_result = asyncio.run(
        recovered.run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=bucket_end + timedelta(seconds=20),
        )
    )

    assert recovery_result.status is IntradayCycleStatus.COMMITTED
    assert [event.event_type for event in recovery_publications] == [
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]
    assert recovery_result.facts is not None
    assert recovery_result.facts.current_day_minutes == tuple(
        _bar(plan.symbol, minute_end) for minute_end in expected
    )
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(MinuteBarRow)) == 5
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1


def test_intraday_service_assembles_full_240_minute_provisional_close(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(15, 0)
    evaluated_at = bucket_end + timedelta(seconds=20)
    full_day_ends = expected_minute_ends(bucket_end.date(), is_open=True)
    fetched = [_bar(plan.symbol, minute_end) for minute_end in full_day_ends]
    tracker = {"active": 0}
    publications: list[MonitorEvent] = []

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return fetched

    def build_context(plan_value: TradePlan, facts: IntradayMarketFacts) -> EvaluationContext:
        assert len(facts.current_day_minutes) == 240
        assert len(facts.complete_five_minute_bars) == 48
        assert facts.source_as_of == bucket_end
        assert facts.provisional_daily_bar.is_official is False
        return _runtime_context(plan_value, facts)

    result = asyncio.run(
        RuntimeEvaluationService(
            fetch_minutes=fetch_minutes,
            unit_of_work_factory=_runtime_uow_factory(
                runtime_engine,
                tracker,
                now=evaluated_at + timedelta(seconds=1),
            ),
            context_builder=build_context,
            evaluator=evaluate,
            committed_event_publisher=publications.append,
        ).run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert result.status is IntradayCycleStatus.COMMITTED
    assert [event.event_type for event in publications] == [
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]
    assert result.facts is not None
    assert len(result.facts.current_day_minutes) == 240
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(MinuteBarRow)) == 240
        assert session.scalar(select(func.count()).select_from(FiveMinuteBarRow)) == 48
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1


def test_intraday_service_rolls_back_atomic_application_then_restarts_exactly_once(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 40)
    evaluated_at = bucket_end + timedelta(seconds=20)
    all_minute_ends = tuple(
        minute_end for minute_end in (_at(9, minute) for minute in range(31, 41))
    )
    fetched = [_bar(plan.symbol, minute_end) for minute_end in all_minute_ends]
    tracker = {"active": 0}
    published: list[MonitorEvent] = []
    event_id = UUID("00000000-0000-0000-0000-000000000032")

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        assert tracker["active"] == 0
        return fetched

    def actionable(context: EvaluationContext) -> EvaluationResult:
        assert tracker["active"] == 0
        return _actionable_episode_result(plan, context)

    failing = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
            fail_alert=True,
        ),
        context_builder=_runtime_context,
        evaluator=actionable,
        committed_event_publisher=lambda _event: pytest.fail("rollback cannot publish"),
        event_id_factory=lambda: event_id,
    )

    with pytest.raises(RuntimeError, match="forced outbox failure"):
        asyncio.run(
            failing.run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )

    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 0
        assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 0
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0
        assert session.scalar(select(func.count()).select_from(ZoneEpisode)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert session.scalar(select(func.count()).select_from(MinuteBarRow)) == 10
        assert session.scalar(select(func.count()).select_from(FiveMinuteBarRow)) == 2

    def publish_after_commit(event) -> None:
        assert tracker["active"] == 0
        with create_session_factory(runtime_engine)() as session:
            if event.event_type is MonitorEventType.ALERT_CREATED:
                assert session.get(AlertEventRow, str(event.event_id)) is not None
            assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
            assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 1
            assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 1
        if event.event_type is MonitorEventType.ALERT_CREATED:
            published.append(event.event_id)

    def create_service() -> RuntimeEvaluationService:
        return RuntimeEvaluationService(
            fetch_minutes=fetch_minutes,
            unit_of_work_factory=_runtime_uow_factory(
                runtime_engine,
                tracker,
                now=evaluated_at + timedelta(seconds=1),
            ),
            context_builder=_runtime_context,
            evaluator=actionable,
            committed_event_publisher=publish_after_commit,
            event_id_factory=lambda: event_id,
        )

    first = asyncio.run(
        create_service().run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )
    duplicate = asyncio.run(
        create_service().run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )
    restarted = asyncio.run(
        create_service().run_intraday(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
    )

    assert first.status is IntradayCycleStatus.COMMITTED
    assert duplicate.status is IntradayCycleStatus.DUPLICATE
    assert restarted.status is IntradayCycleStatus.DUPLICATE
    assert published == [event_id]
    assert tracker["active"] == 0
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 1
        assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 1
        assert session.scalar(select(func.count()).select_from(ZoneEpisode)) == 1
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_intraday_service_publisher_failure_cannot_undo_committed_outbox(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 40)
    evaluated_at = bucket_end + timedelta(seconds=20)
    fetched = [_bar(plan.symbol, _at(9, minute)) for minute in range(31, 41)]
    tracker = {"active": 0}
    event_id = UUID("00000000-0000-0000-0000-000000000033")

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return fetched

    def publisher(_event) -> None:
        assert tracker["active"] == 0
        raise RuntimeError("publisher unavailable")

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        evaluator=lambda context: _actionable_episode_result(plan, context),
        committed_event_publisher=publisher,
        event_id_factory=lambda: event_id,
    )

    with pytest.raises(RuntimeError, match="publisher unavailable"):
        asyncio.run(
            service.run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )

    assert tracker["active"] == 0
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 1
        assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 1
        assert session.scalar(select(func.count()).select_from(ZoneEpisode)) == 1
        assert session.get(AlertEventRow, str(event_id)) is not None


def test_intraday_service_never_applies_official_close_risk_transition(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(15, 0)
    evaluated_at = bucket_end + timedelta(seconds=20)
    fetched = [
        _bar(plan.symbol, minute_end)
        for minute_end in expected_minute_ends(bucket_end.date(), is_open=True)
    ]
    tracker = {"active": 0}

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return fetched

    def forged_intraday_risk(context: EvaluationContext) -> EvaluationResult:
        base = evaluate(context)
        risk = RiskStateSnapshot(
            symbol=plan.symbol,
            plan_hash=plan_sha256(plan),
            status=RiskStatus.BREACHED_PENDING_CONFIRMATION,
            breach_trade_date=bucket_end.date(),
            prior_close_fen=6080,
            revision=1,
            updated_at=bucket_end,
        )
        snapshot = base.snapshot.model_copy(update={"risk": risk})
        payload = base.model_dump(
            mode="python",
            round_trip=True,
            exclude={"result_hash", "snapshot", "transitions"},
        )
        return EvaluationResult.build(
            **payload,
            snapshot=snapshot,
            transitions=(RiskTransitionIntent(risk=risk, expected_revision=0),),
        )

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        evaluator=forged_intraday_risk,
        committed_event_publisher=lambda _event: pytest.fail("risk forgery cannot publish"),
    )

    with pytest.raises(ValueError, match="official-close risk"):
        asyncio.run(
            service.run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )

    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0


def test_intraday_service_never_enqueues_official_close_risk_signal(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    bucket_end = _at(9, 35)
    evaluated_at = bucket_end + timedelta(seconds=20)
    fetched = [
        _bar(plan.symbol, minute_end) for minute_end in expected_five_minute_ends(bucket_end)
    ]
    tracker = {"active": 0}

    async def fetch_minutes(_symbol: str, _target: datetime) -> list[MinuteBar]:
        return fetched

    def forged_intraday_risk_signal(context: EvaluationContext) -> EvaluationResult:
        base = evaluate(context)
        evidence = ConditionEvidence(
            condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
            outcome=ConditionOutcome.SATISFIED,
            facts=(
                EvidenceFact(
                    key="current_price_fen",
                    value=context.current_day_minutes[-1].close_fen,
                    unit=EvidenceUnit.FEN,
                ),
            ),
        )
        next_step = NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
        signal = SignalIntent(
            signal_type=ActionableSignalType.RISK_BREACH,
            plan_hash=plan_sha256(plan),
            symbol=plan.symbol,
            trading_date=bucket_end.date(),
            cause_id="forged-intraday-risk",
            quantity=None,
            bucket=None,
            target_lot_id=None,
            matched_conditions=(evidence,),
            blockers=(),
            next_step=next_step,
        )
        snapshot = base.snapshot.model_copy(
            update={
                "zone": DecisionZone.BELOW_RISK,
                "signal_type": SignalType.RISK_BREACH,
                "condition_evidence": (evidence,),
                "next_step": next_step,
            }
        )
        return EvaluationResult.build(
            snapshot=snapshot,
            transitions=(),
            signal_intent=signal,
            satisfied_conditions=(evidence,),
            unmet_conditions=(),
            blockers=(),
            next_step=next_step,
            evaluation_identity=base.evaluation_identity,
        )

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        evaluator=forged_intraday_risk_signal,
        committed_event_publisher=lambda _event: pytest.fail("risk forgery cannot publish"),
    )

    with pytest.raises(ValueError, match="official-close risk"):
        asyncio.run(
            service.run_intraday(
                plan=plan,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        )

    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0


def test_intraday_service_same_cause_commits_later_bucket_without_republish(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    first_bucket = _at(9, 40)
    later_bucket = _at(9, 45)
    tracker = {"active": 0}
    published: list[MonitorEvent] = []
    event_ids = iter(
        (
            UUID("00000000-0000-0000-0000-000000000034"),
            UUID("00000000-0000-0000-0000-000000000035"),
        )
    )

    async def fetch_minutes(_symbol: str, target: datetime) -> list[MinuteBar]:
        minute_count = 10 if target == first_bucket else 15
        return [_bar(plan.symbol, _at(9, minute)) for minute in range(31, 31 + minute_count)]

    service = RuntimeEvaluationService(
        fetch_minutes=fetch_minutes,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=later_bucket + timedelta(seconds=30),
        ),
        context_builder=_runtime_context,
        evaluator=lambda context: _actionable_episode_result(plan, context),
        committed_event_publisher=published.append,
        event_id_factory=lambda: next(event_ids),
    )

    first = asyncio.run(
        service.run_intraday(
            plan=plan,
            bucket_end=first_bucket,
            evaluated_at=first_bucket + timedelta(seconds=20),
        )
    )
    later = asyncio.run(
        service.run_intraday(
            plan=plan,
            bucket_end=later_bucket,
            evaluated_at=later_bucket + timedelta(seconds=20),
        )
    )

    assert first.status is IntradayCycleStatus.COMMITTED
    assert later.status is IntradayCycleStatus.COMMITTED
    assert later.committed_event is None
    assert [event.event_type for event in published] == [
        MonitorEventType.ALERT_CREATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]
    assert published[0].event_id == UUID("00000000-0000-0000-0000-000000000034")
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 2
        assert session.scalar(select(func.count()).select_from(ZoneEpisode)) == 1
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 1
        episode = session.scalar(select(ZoneEpisode))
        assert episode is not None
        assert episode.last_processed_bucket_end == later_bucket.isoformat()


def test_official_close_uses_trusted_post_fetch_observation_time(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    requested_at = datetime.combine(trade_date, time(15, 20), SHANGHAI)
    received_at = requested_at + timedelta(seconds=1)
    observed_at = requested_at + timedelta(seconds=1, microseconds=250_000)
    expected_observed_at = requested_at + timedelta(seconds=2)
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6200,
        is_official=True,
        received_at=received_at,
    )
    tracker = {"active": 0}
    publications: list[MonitorEvent] = []

    async def fetch_official_daily(
        _symbol: str,
        _trade_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        clock.current = observed_at
        return [official]

    clock = _ImmediateClock(requested_at)

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda _requested_at: observed_at,
        clock=clock,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=expected_observed_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=evaluate,
        committed_event_publisher=publications.append,
    )

    result = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=requested_at,
            close_attempt=1,
        )
    )

    assert result.status is OfficialCloseCycleStatus.COMMITTED
    assert [event.event_type for event in publications] == [
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]
    assert result.facts is not None
    assert result.facts.evaluated_at == expected_observed_at
    assert result.facts.close_reconciliation.official_bar == official
    assert clock.now() == expected_observed_at


def test_completed_official_close_short_circuits_later_attempt_after_restart(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    first_requested_at = datetime.combine(trade_date, time(15, 20), SHANGHAI)
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6200,
        is_official=True,
        received_at=first_requested_at + timedelta(seconds=1),
    )
    tracker = {"active": 0}
    fetch_calls: list[int] = []
    evaluation_calls: list[datetime] = []
    publications: list[MonitorEvent] = []

    async def fetch_first(
        _symbol: str,
        _trade_date: date,
        close_attempt: int,
    ) -> list[DailyBar]:
        fetch_calls.append(close_attempt)
        return [official]

    def evaluate_first(context: EvaluationContext) -> EvaluationResult:
        evaluation_calls.append(context.evaluated_at)
        return evaluate(context)

    first_service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_first,
        official_observed_at=lambda requested_at: requested_at + timedelta(seconds=2),
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=first_requested_at + timedelta(minutes=1),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=evaluate_first,
        committed_event_publisher=publications.append,
    )
    first = asyncio.run(
        first_service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=first_requested_at,
            close_attempt=1,
        )
    )
    assert first.status is OfficialCloseCycleStatus.COMMITTED
    assert [event.event_type for event in publications] == [
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]

    restarted = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=lambda _symbol, _trade_date, _attempt: pytest.fail(
            "completed close cannot fetch again"
        ),
        official_observed_at=lambda requested_at: requested_at + timedelta(seconds=2),
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(trade_date, time(16, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=lambda _plan, _facts: pytest.fail(
            "completed close cannot rebuild context"
        ),
        evaluator=lambda _context: pytest.fail("completed close cannot evaluate again"),
        committed_event_publisher=lambda _event: pytest.fail("duplicate cannot publish"),
    )
    duplicate = asyncio.run(
        restarted.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(16, 0), SHANGHAI),
            close_attempt=2,
        )
    )

    assert duplicate.status is OfficialCloseCycleStatus.DUPLICATE
    assert duplicate.claim_created is False
    assert duplicate.close_reconciliation is None
    assert duplicate.facts is None
    assert duplicate.evaluation_result is None
    assert fetch_calls == [1]
    assert evaluation_calls == [first_requested_at + timedelta(seconds=2)]
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0

    # Model a concurrent completed claim with a remaining pending row. Clearing
    # the row produces no health event because health is no longer CLOSE_PENDING.
    assert first.facts is not None
    with _runtime_uow_factory(
        runtime_engine, tracker, now=first_requested_at + timedelta(minutes=1),
    )() as work:
        work.projections.put_pending_official_close(
            plan_hash=plan_sha256(plan), symbol=plan.symbol, trade_date=trade_date,
            formula_version=plan.monitoring.indicator_formula_version,
            pending={}, observed_at=first_requested_at,
        )
        work.commit()

    async def concurrent_claim_not_yet_visible(**_kwargs):
        return False

    first_service._official_close_completed = concurrent_claim_not_yet_visible
    first_service._persist_official_market_context = lambda **_kwargs: (
        first.close_reconciliation, first.facts.official_daily_bars, None,
    )
    first_service._commit_admission = lambda: False
    with pytest.raises(RuntimeError, match="commit admission revoked"):
        asyncio.run(first_service.run_official_close(
            plan=plan, trade_date=trade_date, evaluated_at=first_requested_at,
            close_attempt=2,
        ))
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 1


def test_official_close_accepts_scheduler_attempt_beyond_ten(runtime_engine: Engine) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    evaluated_at = datetime.combine(trade_date, time(17, 1), SHANGHAI)
    tracker = {"active": 0}
    publications: list[MonitorEvent] = []

    async def fetch_official_daily(
        _symbol: str,
        _trade_date: date,
        close_attempt: int,
    ) -> list[DailyBar]:
        assert close_attempt == 11
        return []

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=evaluated_at + timedelta(seconds=1),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=evaluate,
        committed_event_publisher=publications.append,
    )

    result = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            close_attempt=11,
        )
    )

    assert result.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert result.close_attempt == 11
    assert [event.event_type for event in publications] == [MonitorEventType.SYMBOL_HEALTH_UPDATED]


def test_official_close_attempts_persist_pending_then_commit_matching_official_risk(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    provisional = _daily_bar(
        trade_date=trade_date,
        close_fen=6070,
        is_official=False,
    )
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6000,
        is_official=True,
        received_at=datetime.combine(trade_date, time(17, 0), SHANGHAI),
    )
    wrong_date = _daily_bar(
        trade_date=trade_date - timedelta(days=3),
        close_fen=5990,
        is_official=True,
    )
    tracker = {"active": 0}
    calls: list[tuple[str, date, int]] = []
    published: list[UUID] = []
    event_id = UUID("00000000-0000-0000-0000-000000000036")

    with _runtime_uow_factory(
        runtime_engine,
        tracker,
        now=datetime.combine(trade_date, time(15, 1), SHANGHAI),
    )() as unit_of_work:
        unit_of_work.history.upsert_daily_bars((provisional,))
        unit_of_work.commit()

    async def fetch_official_daily(
        symbol: str,
        requested_date: date,
        close_attempt: int,
    ) -> list[DailyBar]:
        assert tracker["active"] == 0
        calls.append((symbol, requested_date, close_attempt))
        if close_attempt == 1:
            return []
        if close_attempt == 2:
            return [wrong_date]
        return [official]

    def build_context(plan_value: TradePlan, facts: OfficialCloseMarketFacts):
        assert tracker["active"] == 0
        assert facts.provenance is DailyIndicatorProvenance.OFFICIAL
        assert facts.source_as_of == datetime.combine(trade_date, time(15, 0), SHANGHAI)
        assert facts.daily_indicator_snapshot.series == calculate_ta_v1((official,))
        return _official_context(plan_value, facts)

    def publish_after_commit(event) -> None:
        assert tracker["active"] == 0
        with create_session_factory(runtime_engine)() as session:
            if event.event_type is MonitorEventType.ALERT_CREATED:
                assert session.get(AlertEventRow, str(event.event_id)) is not None
                assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
                assert session.scalar(select(func.count()).select_from(RiskState)) == 1
        if event.event_type is MonitorEventType.ALERT_CREATED:
            published.append(event.event_id)

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(trade_date, time(17, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=build_context,
        evaluator=evaluate,
        committed_event_publisher=publish_after_commit,
        event_id_factory=lambda: event_id,
    )

    first = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(15, 20), SHANGHAI),
            close_attempt=1,
        )
    )
    second = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(16, 0), SHANGHAI),
            close_attempt=2,
        )
    )

    assert first.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert second.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert first.close_reconciliation.status is CloseReconciliationStatus.CLOSE_PENDING
    assert first.evaluation_result is None
    assert service.pending_close_date(plan.symbol) == trade_date
    with create_session_factory(runtime_engine)() as session:
        health = session.get(SymbolHealth, plan.symbol)
        assert health is not None
        assert health.status == "CLOSE_PENDING"
        assert health.latest_bar_end is None
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 1
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1

    third = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(17, 0), SHANGHAI),
            close_attempt=3,
        )
    )

    assert calls == [
        (plan.symbol, trade_date, 1),
        (plan.symbol, trade_date, 2),
        (plan.symbol, trade_date, 3),
    ]
    assert third.status is OfficialCloseCycleStatus.COMMITTED
    assert third.claim_created is True
    assert third.facts is not None
    assert third.facts.close_reconciliation.official_bar == official
    assert third.facts.close_reconciliation.close_delta_fen == -70
    assert third.evaluation_result is not None
    assert third.evaluation_result.snapshot.signal_type is SignalType.RISK_BREACH
    assert published == [event_id]
    assert service.pending_close_date(plan.symbol) is None
    with create_session_factory(runtime_engine)() as session:
        ledger = session.scalar(select(EvaluationLedger))
        assert ledger is not None
        assert ledger.evaluation_kind == "OFFICIAL_CLOSE"
        assert ledger.target_value == trade_date.isoformat()
        assert session.scalar(select(func.count()).select_from(EvaluationResultRow)) == 1
        assert session.scalar(select(func.count()).select_from(SymbolDecisionHead)) == 1
        assert session.scalar(select(func.count()).select_from(PendingOfficialClose)) == 0
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 2
        risk = session.get(RiskState, plan.symbol)
        assert risk is not None
        assert risk.status == "BREACHED_PENDING_CONFIRMATION"


def test_official_close_replaces_cross_plan_risk_with_storage_revision_cas(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    prior = _daily_bar(
        trade_date=trade_date - timedelta(days=3),
        close_fen=6200,
        is_official=True,
    )
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6000,
        is_official=True,
        received_at=datetime.combine(trade_date, time(17, 0), SHANGHAI),
    )
    seed_factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=datetime.combine(trade_date, time(9, 0), SHANGHAI),
    )
    with seed_factory() as work:
        work.plans.save_draft(
            plan,
            source_text=SAMPLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
        work.plans.activate(
            plan,
            expected_revision=0,
            validation=validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            ),
        )
        work.history.upsert_daily_bars((prior,))
        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange=plan.market,
                    cal_date=trade_date,
                    is_open=True,
                    previous_trade_date=prior.trade_date,
                ),
            )
        )
        old_risk = work.risk.upsert(
            symbol=plan.symbol,
            plan_hash="a" * 64,
            status=RiskStatus.BREACHED_PENDING_CONFIRMATION.value,
            breach_trade_date=prior.trade_date,
            prior_close_fen=6100,
            expected_revision=0,
        )
        work.commit()
    assert old_risk.revision == 1

    service_factory = _runtime_uow_factory(
        runtime_engine,
        {"active": 0},
        now=datetime.combine(trade_date, time(17, 1), SHANGHAI),
    )

    async def fetch_official_daily(
        _symbol: str,
        _trade_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        return [official]

    service = RuntimeEvaluationService(
        fetch_minutes=lambda *_args: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=service_factory,
        context_builder=ProductionContextBuilder(service_factory),
        official_context_builder=ProductionContextBuilder(service_factory),
        committed_event_publisher=lambda _event: None,
    )

    result = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(17, 0), SHANGHAI),
            close_attempt=1,
        )
    )

    assert result.status is OfficialCloseCycleStatus.COMMITTED
    assert result.evaluation_result is not None
    transition = next(
        item
        for item in result.evaluation_result.transitions
        if isinstance(item, RiskTransitionIntent)
    )
    assert transition.expected_revision == old_risk.revision
    with service_factory() as work:
        risk = work.risk.get(plan.symbol)
    assert risk is not None
    assert risk.plan_hash == plan_sha256(plan)
    assert risk.status == RiskStatus.BREACHED_PENDING_CONFIRMATION.value
    assert risk.revision == old_risk.revision + 1


def test_official_close_rejects_provisional_fetch_and_mixed_context(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    provisional = _daily_bar(
        trade_date=trade_date,
        close_fen=6000,
        is_official=False,
    )
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6000,
        is_official=True,
    )
    unrelated_history = _daily_bar(
        trade_date=trade_date - timedelta(days=3),
        close_fen=6200,
        is_official=True,
    )
    tracker = {"active": 0}
    fetched: list[DailyBar] = [provisional]
    publications: list[MonitorEvent] = []

    async def fetch_official_daily(
        _symbol: str,
        _trade_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        return list(fetched)

    def mixed_context(plan_value: TradePlan, facts: OfficialCloseMarketFacts):
        context = _official_context(plan_value, facts)
        return context.model_copy(update={"official_daily_bars": (unrelated_history,)})

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(trade_date, time(17, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=mixed_context,
        evaluator=evaluate,
        committed_event_publisher=publications.append,
    )

    pending = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=datetime.combine(trade_date, time(15, 20), SHANGHAI),
            close_attempt=1,
        )
    )
    assert pending.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert service.pending_close_date(plan.symbol) == trade_date

    fetched[:] = [official]
    with pytest.raises(ValueError, match="daily indicator identities|exact official market facts"):
        asyncio.run(
            service.run_official_close(
                plan=plan,
                trade_date=trade_date,
                evaluated_at=datetime.combine(trade_date, time(16, 0), SHANGHAI),
                close_attempt=2,
            )
        )

    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0
    assert publications
    assert all(event.event_type is MonitorEventType.SYMBOL_HEALTH_UPDATED for event in publications)


def test_official_evaluation_failure_retains_pending_and_blocks_later_close(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    first_date = date(2026, 8, 24)
    next_date = date(2026, 8, 25)
    tracker = {"active": 0}
    calls: list[date] = []
    publications: list[MonitorEvent] = []

    async def fetch_official_daily(
        _symbol: str,
        requested_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        calls.append(requested_date)
        return [
            _daily_bar(
                trade_date=requested_date,
                close_fen=6200,
                is_official=True,
            )
        ]

    def fail_evaluation(_context: EvaluationContext) -> EvaluationResult:
        raise RuntimeError("evaluation failed")

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(next_date, time(17, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=fail_evaluation,
        committed_event_publisher=publications.append,
    )

    with pytest.raises(RuntimeError, match="evaluation failed"):
        asyncio.run(
            service.run_official_close(
                plan=plan,
                trade_date=first_date,
                evaluated_at=datetime.combine(first_date, time(17, 0), SHANGHAI),
                close_attempt=3,
            )
        )

    assert service.pending_close_date(plan.symbol) == first_date
    blocked = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=next_date,
            evaluated_at=datetime.combine(next_date, time(15, 20), SHANGHAI),
            close_attempt=1,
        )
    )
    assert blocked.status is OfficialCloseCycleStatus.BLOCKED_PENDING
    assert blocked.pending_trade_date == first_date
    assert calls == [first_date]
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0
    assert publications
    assert all(event.event_type is MonitorEventType.SYMBOL_HEALTH_UPDATED for event in publications)


def test_official_close_rolls_back_application_then_restarts_exactly_once(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    trade_date = date(2026, 8, 24)
    evaluated_at = datetime.combine(trade_date, time(17, 0), SHANGHAI)
    official = _daily_bar(
        trade_date=trade_date,
        close_fen=6000,
        is_official=True,
        received_at=evaluated_at,
    )
    tracker = {"active": 0}
    published: list[UUID] = []
    event_id = UUID("00000000-0000-0000-0000-000000000037")

    def publish_alert(event: MonitorEvent) -> None:
        if event.event_type is MonitorEventType.ALERT_CREATED:
            published.append(event.event_id)

    async def fetch_official_daily(
        _symbol: str,
        _trade_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        return [official]

    def create_service(*, fail_alert: bool = False) -> RuntimeEvaluationService:
        return RuntimeEvaluationService(
            fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
            fetch_official_daily=fetch_official_daily,
            official_observed_at=lambda requested_at: requested_at,
            unit_of_work_factory=_runtime_uow_factory(
                runtime_engine,
                tracker,
                now=evaluated_at + timedelta(minutes=1),
                fail_alert=fail_alert,
            ),
            context_builder=_runtime_context,
            official_context_builder=_official_context,
            evaluator=evaluate,
            committed_event_publisher=publish_alert,
            event_id_factory=lambda: event_id,
        )

    failing = create_service(fail_alert=True)
    with pytest.raises(RuntimeError, match="forced outbox failure"):
        asyncio.run(
            failing.run_official_close(
                plan=plan,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                close_attempt=3,
            )
        )

    assert failing.pending_close_date(plan.symbol) == trade_date
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 0
        assert session.scalar(select(func.count()).select_from(RiskState)) == 0
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0

    first = asyncio.run(
        create_service().run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            close_attempt=3,
        )
    )
    restarted = asyncio.run(
        create_service().run_official_close(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            close_attempt=3,
        )
    )

    assert first.status is OfficialCloseCycleStatus.COMMITTED
    assert restarted.status is OfficialCloseCycleStatus.DUPLICATE
    assert published == [event_id]
    assert create_service().pending_close_date(plan.symbol) is None
    with create_session_factory(runtime_engine)() as session:
        assert session.scalar(select(func.count()).select_from(DailyBarRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationLedger)) == 1
        assert session.scalar(select(func.count()).select_from(RiskState)) == 1
        assert session.scalar(select(func.count()).select_from(AlertEventRow)) == 1


def test_unresolved_close_pending_blocks_next_day_until_original_date_resolves(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    first_date = date(2026, 8, 24)
    next_date = date(2026, 8, 25)
    tracker = {"active": 0}
    ready: set[date] = set()
    calls: list[date] = []
    publications: list[MonitorEvent] = []

    async def fetch_official_daily(
        _symbol: str,
        requested_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        calls.append(requested_date)
        if requested_date not in ready:
            return []
        return [
            _daily_bar(
                trade_date=requested_date,
                close_fen=6200,
                is_official=True,
            )
        ]

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(next_date, time(17, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=evaluate,
        committed_event_publisher=publications.append,
    )

    pending = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=first_date,
            evaluated_at=datetime.combine(first_date, time(17, 0), SHANGHAI),
            close_attempt=3,
        )
    )
    blocked = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=next_date,
            evaluated_at=datetime.combine(next_date, time(15, 20), SHANGHAI),
            close_attempt=1,
        )
    )

    assert pending.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert blocked.status is OfficialCloseCycleStatus.BLOCKED_PENDING
    assert blocked.pending_trade_date == first_date
    assert calls == [first_date]

    ready.add(first_date)
    resolved = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=first_date,
            evaluated_at=datetime.combine(next_date, time(9, 0), SHANGHAI),
            close_attempt=4,
        )
    )
    ready.add(next_date)
    next_close = asyncio.run(
        service.run_official_close(
            plan=plan,
            trade_date=next_date,
            evaluated_at=datetime.combine(next_date, time(17, 0), SHANGHAI),
            close_attempt=3,
        )
    )

    assert resolved.status is OfficialCloseCycleStatus.COMMITTED
    assert next_close.status is OfficialCloseCycleStatus.COMMITTED
    assert [event.event_type for event in publications] == [
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
        MonitorEventType.SYMBOL_HEALTH_UPDATED,
    ]
    assert calls == [first_date, first_date, next_date]
    with create_session_factory(runtime_engine)() as session:
        identities = session.scalars(
            select(EvaluationLedger).order_by(EvaluationLedger.target_value)
        ).all()
        assert [row.target_value for row in identities] == [
            first_date.isoformat(),
            next_date.isoformat(),
        ]
        assert all(row.evaluation_kind == "OFFICIAL_CLOSE" for row in identities)


def test_concurrent_official_close_attempts_serialize_before_next_day_transition(
    runtime_engine: Engine,
) -> None:
    plan = _runtime_plan()
    first_date = date(2026, 8, 24)
    next_date = date(2026, 8, 25)
    tracker = {"active": 0}
    first_fetch_started = asyncio.Event()
    release_first_fetch = asyncio.Event()
    calls: list[date] = []

    async def fetch_official_daily(
        _symbol: str,
        requested_date: date,
        _close_attempt: int,
    ) -> list[DailyBar]:
        calls.append(requested_date)
        if requested_date == first_date:
            first_fetch_started.set()
            await release_first_fetch.wait()
        return []

    service = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: pytest.fail("intraday fetch is out of scope"),
        fetch_official_daily=fetch_official_daily,
        official_observed_at=lambda requested_at: requested_at,
        unit_of_work_factory=_runtime_uow_factory(
            runtime_engine,
            tracker,
            now=datetime.combine(next_date, time(17, 1), SHANGHAI),
        ),
        context_builder=_runtime_context,
        official_context_builder=_official_context,
        evaluator=evaluate,
        committed_event_publisher=lambda _event: None,
    )

    async def run_both():
        first = asyncio.create_task(
            service.run_official_close(
                plan=plan,
                trade_date=first_date,
                evaluated_at=datetime.combine(first_date, time(17, 0), SHANGHAI),
                close_attempt=3,
            )
        )
        await first_fetch_started.wait()
        later = asyncio.create_task(
            service.run_official_close(
                plan=plan,
                trade_date=next_date,
                evaluated_at=datetime.combine(next_date, time(15, 20), SHANGHAI),
                close_attempt=1,
            )
        )
        await asyncio.sleep(0)
        release_first_fetch.set()
        return await asyncio.gather(first, later)

    first, later = asyncio.run(run_both())

    assert first.status is OfficialCloseCycleStatus.CLOSE_PENDING
    assert later.status is OfficialCloseCycleStatus.BLOCKED_PENDING
    assert later.pending_trade_date == first_date
    assert calls == [first_date]


def test_startup_recovery_resolves_close_pending_before_current_day_minutes() -> None:
    symbol = SYMBOLS[0]
    startup_date = date(2026, 8, 24)
    pending_date = startup_date - timedelta(days=3)
    provider = _FakeProvider([])
    provider.recovery_rows[symbol] = [_bar(symbol, _at(9, 31))]
    history = _FakeHistory()
    controller = _controller(_at(9, 31, 12))
    pending_by_symbol: dict[str, date] = {symbol: pending_date}
    close_calls: list[tuple[str, date]] = []

    async def recover_pending_close(requested_symbol: str, requested_date: date) -> bool:
        assert provider.recovery_calls == []
        close_calls.append((requested_symbol, requested_date))
        pending_by_symbol.pop(requested_symbol)
        return True

    service = RecoveryService(
        provider=provider,
        request_controller=controller,
        active_symbols=_ActiveSymbols((symbol,)),
        persist_minutes=history.persist_minutes,
        is_open_on=lambda _trade_date: True,
        realtime_pending=lambda: False,
        pending_close_date=lambda requested_symbol: pending_by_symbol.get(requested_symbol),
        recover_pending_close=recover_pending_close,
    )

    try:
        result = asyncio.run(service.recover_startup(trade_date=startup_date))
    finally:
        controller.close()

    assert close_calls == [(symbol, pending_date)]
    assert provider.recovery_calls == [symbol]
    assert len(result.pending_close_results) == 1
    assert result.pending_close_results[0].resolved is True
    assert result.pending_close_results[0].trade_date == pending_date
    assert result.persisted_bar_count == 1
