"""Offline event-time replay through production decisions and simulated execution."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

import pytest

import trade_plan_monitor.backtest.application as application_module
import trade_plan_monitor.backtest.runner as runner_module
import trade_plan_monitor.decision.models as decision_models_module
from trade_plan_monitor.backtest.application import BacktestApplicationService
from trade_plan_monitor.backtest.control import BacktestCancellationResult, CancellationToken
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.reporting import persist_report, write_report_files
from trade_plan_monitor.backtest.results import BacktestDetailKind, BacktestResultStore
from trade_plan_monitor.backtest.run_input import BacktestInitialLotInput, BacktestRunInput
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner
from trade_plan_monitor.decision.conditions import evaluate_condition
from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DecisionZone,
    EvaluationContext,
    EvaluationResult,
    IntradayEvaluationTarget,
    NextStep,
    NextStepCode,
    RuleEvidence,
    SignalIntent,
    SignalType,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_models import PriceInZoneCondition, TradePlan
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "600000.SH"
TRADE_DATE = date(2026, 8, 24)
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
REPLAY_FIXTURE = Path("tests/fixtures/replay/backtest_two_symbol_20d.json")


class _ObservedFrozenReader:
    def __init__(self, reader, source: _FrozenReaderSource) -> None:
        self._reader = reader
        self._source = source

    @property
    def dataset_hash(self):
        return self._reader.dataset_hash

    @property
    def scope(self):
        return self._reader.scope

    def __iter__(self):
        for symbol_day in self._reader:
            self._source.last_yielded = (symbol_day.symbol, symbol_day.trade_date)
            self._source.yielded_by_open[-1].append(self._source.last_yielded)
            yield symbol_day


class _FrozenReaderSource:
    """Test adapter exposing only the bounded reader-opening contract."""

    def __init__(self, store: BacktestMarketStore) -> None:
        self._store = store
        self.open_count = 0
        self.last_yielded: tuple[str, date] | None = None
        self.yielded_by_open: list[list[tuple[str, date]]] = []

    @contextmanager
    def open_frozen_dataset(self, dataset_hash: str):
        self.open_count += 1
        self.yielded_by_open.append([])
        with self._store.open_frozen_dataset(dataset_hash) as reader:
            yield _ObservedFrozenReader(reader, self)


def _plan() -> TradePlan:
    source = Path("config/plans/003043.SZ.sample.yaml").read_text(encoding="utf-8")
    plan = load_plan_yaml(source)
    values = plan.model_dump(mode="python", round_trip=True)
    values.update({"symbol": SYMBOL, "market": "SSE", "name": "回测样例"})
    return TradePlan.model_validate(values)


def _execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        commission_rate=Decimal("0.0003"),
        minimum_commission_fen=500,
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        buy_slippage_bps=Decimal("2"),
        sell_slippage_bps=Decimal("2"),
    )


def _seed_dataset(store: BacktestMarketStore) -> str:
    warmup_start = TRADE_DATE - timedelta(days=60)
    previous_open = warmup_start - timedelta(days=3)
    calendar: list[TradingDay] = []
    daily: list[DailyBar] = []
    cursor = warmup_start
    while cursor <= TRADE_DATE:
        is_open = cursor.weekday() < 5
        calendar.append(
            TradingDay(
                exchange="SSE",
                cal_date=cursor,
                is_open=is_open,
                previous_trade_date=previous_open,
            )
        )
        if is_open:
            daily.append(
                DailyBar(
                    symbol=SYMBOL,
                    trade_date=cursor,
                    open_fen=6_400,
                    high_fen=6_420,
                    low_fen=6_380,
                    close_fen=6_400,
                    volume_shares=2_000_000,
                    amount_yuan=Decimal("128000000"),
                    is_official=True,
                    received_at=datetime.combine(cursor, time(15, 20), SHANGHAI),
                )
            )
            previous_open = cursor
        cursor += timedelta(days=1)
    store.record_trading_days(tuple(calendar))
    store.record_daily_bars(tuple(daily))
    bars = tuple(
        MinuteBar(
            symbol=SYMBOL,
            bar_end=bar_end,
            open_fen=6_400,
            high_fen=6_401,
            low_fen=6_399,
            close_fen=6_400,
            volume_shares=1_000,
            amount_yuan=Decimal("64000"),
            received_at=bar_end + timedelta(seconds=12),
        )
        for bar_end in expected_minute_ends(TRADE_DATE, is_open=True)
    )
    store.record_minute_batch(
        HistoricalMinuteBatch(
            symbol=SYMBOL,
            trade_date=TRADE_DATE,
            contract_version=PROFILE,
            bars=bars,
            opening_special=HistoricalOpeningSpecial(
                symbol=SYMBOL,
                source_time=datetime.combine(TRADE_DATE, time(9, 30), SHANGHAI),
                open_fen=6_400,
                high_fen=6_401,
                low_fen=6_399,
                close_fen=6_400,
                volume_shares=500,
                amount_yuan=Decimal("32000"),
            ),
        )
    )
    store.record_daily_limits(
        (
            DailyLimit(
                symbol=SYMBOL,
                trade_date=TRADE_DATE,
                up_limit_fen=7_040,
                down_limit_fen=5_760,
                received_at=datetime.combine(TRADE_DATE, time(9, 30), SHANGHAI),
            ),
        )
    )
    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=(SYMBOL,),
            start=TRADE_DATE,
            end=TRADE_DATE,
            warmup_start=warmup_start,
            historical_profile=PROFILE,
        )
    )
    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    return frozen.dataset_hash


def _seed_twenty_trading_day_dataset(store: BacktestMarketStore) -> str:
    trade_dates: list[date] = []
    cursor = TRADE_DATE
    while len(trade_dates) < 20:
        if cursor.weekday() < 5:
            trade_dates.append(cursor)
        cursor -= timedelta(days=1)
    trade_dates.reverse()
    start = trade_dates[0]
    end = trade_dates[-1]
    warmup_start = start - timedelta(days=60)
    previous_open = warmup_start - timedelta(days=3)
    calendar: list[TradingDay] = []
    daily: list[DailyBar] = []
    cursor = warmup_start
    while cursor <= end:
        is_open = cursor.weekday() < 5
        calendar.append(
            TradingDay(
                exchange="SSE",
                cal_date=cursor,
                is_open=is_open,
                previous_trade_date=previous_open,
            )
        )
        if is_open:
            close_fen = 6_400 + (cursor - warmup_start).days
            daily.append(
                DailyBar(
                    symbol=SYMBOL,
                    trade_date=cursor,
                    open_fen=close_fen,
                    high_fen=close_fen + 2,
                    low_fen=close_fen - 2,
                    close_fen=close_fen,
                    volume_shares=2_000_000,
                    amount_yuan=Decimal(close_fen * 20_000),
                    is_official=True,
                    received_at=datetime.combine(cursor, time(15, 20), SHANGHAI),
                )
            )
            previous_open = cursor
        cursor += timedelta(days=1)
    store.record_trading_days(tuple(calendar))
    store.record_daily_bars(tuple(daily))

    minute_count = 0
    for trade_date in trade_dates:
        close_fen = 6_400 + (trade_date - warmup_start).days
        bars = tuple(
            MinuteBar(
                symbol=SYMBOL,
                bar_end=bar_end,
                open_fen=close_fen,
                high_fen=close_fen + 1,
                low_fen=close_fen - 1,
                close_fen=close_fen,
                volume_shares=1_000,
                amount_yuan=Decimal(close_fen * 10),
                received_at=bar_end + timedelta(seconds=12),
            )
            for bar_end in expected_minute_ends(trade_date, is_open=True)
        )
        minute_count += len(bars)
        store.record_minute_batch(
            HistoricalMinuteBatch(
                symbol=SYMBOL,
                trade_date=trade_date,
                contract_version=PROFILE,
                bars=bars,
                opening_special=HistoricalOpeningSpecial(
                    symbol=SYMBOL,
                    source_time=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                    open_fen=close_fen,
                    high_fen=close_fen + 1,
                    low_fen=close_fen - 1,
                    close_fen=close_fen,
                    volume_shares=500,
                    amount_yuan=Decimal(close_fen * 5),
                ),
            )
        )
        store.record_daily_limits(
            (
                DailyLimit(
                    symbol=SYMBOL,
                    trade_date=trade_date,
                    up_limit_fen=close_fen * 11 // 10,
                    down_limit_fen=close_fen * 9 // 10,
                    received_at=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                ),
            )
        )

    assert minute_count == 4_800
    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=(SYMBOL,),
            start=start,
            end=end,
            warmup_start=warmup_start,
            historical_profile=PROFILE,
        )
    )
    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    return frozen.dataset_hash


def _extend_dataset_to_second_day(store: BacktestMarketStore, dataset_hash: str) -> str:
    second_day = TRADE_DATE + timedelta(days=1)
    manifest = store.dataset_manifest(dataset_hash)
    store.record_trading_days(
        (
            TradingDay(
                exchange="SSE",
                cal_date=second_day,
                is_open=True,
                previous_trade_date=TRADE_DATE,
            ),
        )
    )
    store.record_daily_bars(
        (
            DailyBar(
                symbol=SYMBOL,
                trade_date=second_day,
                open_fen=6_500,
                high_fen=6_520,
                low_fen=6_480,
                close_fen=6_500,
                volume_shares=2_000_000,
                amount_yuan=Decimal("130000000"),
                is_official=True,
                received_at=datetime.combine(second_day, time(15, 20), SHANGHAI),
            ),
        )
    )
    bars = tuple(
        MinuteBar(
            symbol=SYMBOL,
            bar_end=bar_end,
            open_fen=6_500,
            high_fen=6_501,
            low_fen=6_499,
            close_fen=6_500,
            volume_shares=1_000,
            amount_yuan=Decimal("65000"),
            received_at=bar_end + timedelta(seconds=12),
        )
        for bar_end in expected_minute_ends(second_day, is_open=True)
    )
    store.record_minute_batch(
        HistoricalMinuteBatch(
            symbol=SYMBOL,
            trade_date=second_day,
            contract_version=PROFILE,
            bars=bars,
            opening_special=HistoricalOpeningSpecial(
                symbol=SYMBOL,
                source_time=datetime.combine(second_day, time(9, 30), SHANGHAI),
                open_fen=6_500,
                high_fen=6_501,
                low_fen=6_499,
                close_fen=6_500,
                volume_shares=500,
                amount_yuan=Decimal("32500"),
            ),
        )
    )
    store.record_daily_limits(
        (
            DailyLimit(
                symbol=SYMBOL,
                trade_date=second_day,
                up_limit_fen=7_150,
                down_limit_fen=5_850,
                received_at=datetime.combine(second_day, time(9, 30), SHANGHAI),
            ),
        )
    )
    frozen = store.freeze_dataset(manifest.scope.model_copy(update={"end": second_day}))
    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    return frozen.dataset_hash


def _replay_fixture() -> dict[str, object]:
    fixture = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schemaVersion"] == "backtest-two-symbol-20d-v1"
    return fixture


def _plan_for_fixture_symbol(symbol_fixture: dict[str, object]) -> TradePlan:
    values = _plan().model_dump(mode="python", round_trip=True)
    values.update(
        {
            "symbol": symbol_fixture["symbol"],
            "market": symbol_fixture["market"],
            "name": symbol_fixture["name"],
        }
    )
    return TradePlan.model_validate(values)


def _seed_two_symbol_replay_dataset(store: BacktestMarketStore) -> tuple[str, dict[str, object]]:
    fixture = _replay_fixture()
    warmup_start = date.fromisoformat(str(fixture["warmupStart"]))
    start = date.fromisoformat(str(fixture["start"]))
    end = date.fromisoformat(str(fixture["end"]))
    symbol_fixtures = tuple(fixture["symbols"])
    assert (end - start).days + 1 == 20
    event_dates = tuple(date.fromisoformat(str(value)) for value in fixture["openTradeDates"])
    assert len(event_dates) == 2

    previous_open = {
        str(item["market"]): warmup_start - timedelta(days=3) for item in symbol_fixtures
    }
    calendar: list[TradingDay] = []
    daily: list[DailyBar] = []
    cursor = warmup_start
    while cursor <= end:
        is_open = cursor.weekday() < 5 and (cursor < start or cursor in event_dates)
        for symbol_fixture in symbol_fixtures:
            exchange = str(symbol_fixture["market"])
            calendar.append(
                TradingDay(
                    exchange=exchange,
                    cal_date=cursor,
                    is_open=is_open,
                    previous_trade_date=previous_open[exchange],
                )
            )
            if not is_open:
                continue
            symbol = str(symbol_fixture["symbol"])
            close_fen = int(symbol_fixture["basePriceFen"]) + (cursor - warmup_start).days
            daily.append(
                DailyBar(
                    symbol=symbol,
                    trade_date=cursor,
                    open_fen=close_fen,
                    high_fen=close_fen + 2,
                    low_fen=close_fen - 2,
                    close_fen=close_fen,
                    volume_shares=2_000_000,
                    amount_yuan=Decimal(close_fen * 20_000),
                    is_official=True,
                    received_at=datetime.combine(cursor, time(15, 20), SHANGHAI),
                )
            )
            previous_open[exchange] = cursor
        cursor += timedelta(days=1)
    store.record_trading_days(tuple(calendar))
    store.record_daily_bars(tuple(daily))

    for symbol_fixture in symbol_fixtures:
        symbol = str(symbol_fixture["symbol"])
        for trade_date in event_dates:
            close_fen = int(symbol_fixture["basePriceFen"]) + (trade_date - warmup_start).days
            minutes = tuple(
                MinuteBar(
                    symbol=symbol,
                    bar_end=bar_end,
                    open_fen=close_fen,
                    high_fen=close_fen + 1,
                    low_fen=close_fen - 1,
                    close_fen=close_fen,
                    volume_shares=1_000,
                    amount_yuan=Decimal(close_fen * 10),
                    received_at=bar_end + timedelta(seconds=12),
                )
                for bar_end in expected_minute_ends(trade_date, is_open=True)
            )
            store.record_minute_batch(
                HistoricalMinuteBatch(
                    symbol=symbol,
                    trade_date=trade_date,
                    contract_version=PROFILE,
                    bars=minutes,
                    opening_special=HistoricalOpeningSpecial(
                        symbol=symbol,
                        source_time=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                        open_fen=close_fen,
                        high_fen=close_fen + 1,
                        low_fen=close_fen - 1,
                        close_fen=close_fen,
                        volume_shares=500,
                        amount_yuan=Decimal(close_fen * 5),
                    ),
                )
            )
            store.record_daily_limits(
                (
                    DailyLimit(
                        symbol=symbol,
                        trade_date=trade_date,
                        up_limit_fen=close_fen * 11 // 10,
                        down_limit_fen=close_fen * 9 // 10,
                        received_at=datetime.combine(trade_date, time(9, 30), SHANGHAI),
                    ),
                )
            )

    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=tuple(str(item["symbol"]) for item in symbol_fixtures),
            start=start,
            end=end,
            warmup_start=warmup_start,
            historical_profile=PROFILE,
        )
    )
    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    return frozen.dataset_hash, fixture


def _actionable_fixture(context: EvaluationContext) -> EvaluationResult:
    return _actionable_fixture_for_dates(
        context,
        buy_date=TRADE_DATE,
        sell_date=TRADE_DATE + timedelta(days=1),
    )


def _actionable_fixture_for_dates(
    context: EvaluationContext,
    *,
    buy_date: date,
    sell_date: date,
) -> EvaluationResult:
    base = evaluate(context)
    if not isinstance(context.target, IntradayEvaluationTarget):
        return base
    if context.target.bucket_end.time() != time(9, 35):
        return base
    if context.trade_date == buy_date and not context.positions:
        signal_type = ActionableSignalType.BUY_TACTICAL_READY
        zone = "LOW_BUY"
        decision_zone = DecisionZone.LOW_BUY
        target_lot_id = None
    elif context.trade_date == sell_date and context.positions:
        signal_type = ActionableSignalType.PRESSURE_REDUCE_READY
        zone = "PRESSURE"
        decision_zone = DecisionZone.PRESSURE
        target_lot_id = context.positions[0].lot_id
    else:
        return base
    evidence = ConditionEvidence(
        condition=PriceInZoneCondition(zone=zone),
        outcome=ConditionOutcome.SATISFIED,
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    snapshot = base.snapshot.model_copy(
        update={
            "zone": decision_zone,
            "signal_type": SignalType(signal_type.value),
            "condition_evidence": (evidence,),
            "next_step": next_step,
        }
    )
    signal = SignalIntent(
        signal_type=signal_type,
        plan_hash=context.plan_hash,
        symbol=context.plan.symbol,
        trading_date=context.trade_date,
        cause_id=f"fixture_{signal_type.value.casefold()}",
        quantity=100,
        bucket="TACTICAL",
        target_lot_id=target_lot_id,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=base.transitions,
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=base.evaluation_identity,
    )


def test_bounded_reader_cancellation_returns_no_partial_report(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(store)
    source = _FrozenReaderSource(store)
    cancellation_token = CancellationToken()
    cancellation_token.cancel()

    result = OfflineBacktestRunner(source).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        cancellation_token=cancellation_token,
    )

    assert result == BacktestCancellationResult(
        phase="RUN_DAY_TRANSITION",
        last_safe_event_id=None,
    )
    assert not hasattr(result, "report_hash")
    assert source.open_count == 0
    with pytest.raises(ValueError):
        BacktestCancellationResult(phase="SYNC_DAILY", last_safe_event_id=None)


def test_runner_consumes_only_the_bounded_reader_contract(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(store)
    source = _FrozenReaderSource(store)

    report = OfflineBacktestRunner(source).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert report.status == "COMPLETED"
    assert len(report.decisions) == 49
    assert source.open_count == 1


def test_runner_selects_only_the_plan_symbol_when_the_source_supports_it(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "selective-market.sqlite3")
    dataset_hash, fixture = _seed_two_symbol_replay_dataset(store)
    selected_symbol = str(fixture["symbols"][0]["symbol"])

    class SelectiveSource:
        def __init__(self) -> None:
            self.selected: list[tuple[str, str]] = []

        @contextmanager
        def open_frozen_dataset(self, dataset_hash: str):
            del dataset_hash
            raise AssertionError("runner opened the full multi-symbol stream")
            yield

        @contextmanager
        def open_frozen_symbol_dataset(self, dataset_hash: str, symbol: str):
            self.selected.append((dataset_hash, symbol))
            with store.open_frozen_symbol_dataset(dataset_hash, symbol) as reader:
                yield reader

    source = SelectiveSource()
    report = OfflineBacktestRunner(source).run(
        plan=_plan_for_fixture_symbol(fixture["symbols"][0]),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert report.status == "COMPLETED"
    assert len(report.daily_equity) == 2
    assert source.selected == [(dataset_hash, selected_symbol)]


def test_runner_reuses_validated_context_once_for_internal_conditions(
    tmp_path,
    monkeypatch,
) -> None:
    store = BacktestMarketStore(tmp_path / "validated-context.sqlite3")
    dataset_hash = _seed_dataset(store)
    source = _FrozenReaderSource(store)
    validation_count = 0
    latest_context: EvaluationContext | None = None
    original_model_validate = EvaluationContext.model_validate

    def counted_model_validate(cls, value, *args, **kwargs):
        nonlocal validation_count
        validation_count += 1
        return original_model_validate(value, *args, **kwargs)

    def observed_evaluator(context: EvaluationContext) -> EvaluationResult:
        nonlocal latest_context
        latest_context = context
        return evaluate(context)

    monkeypatch.setattr(
        EvaluationContext,
        "model_validate",
        classmethod(counted_model_validate),
    )
    report = OfflineBacktestRunner(source, evaluator=observed_evaluator).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert len(report.decisions) == 49
    assert validation_count <= len(report.decisions)
    assert latest_context is not None
    restored = original_model_validate(latest_context.model_dump(mode="python", round_trip=True))
    assert restored == latest_context
    before_public_call = validation_count
    evaluate_condition(latest_context.plan.entry.condition, latest_context)
    assert validation_count == before_public_call + 1


def test_runner_uses_the_validated_internal_context_handoff(tmp_path, monkeypatch) -> None:
    store = BacktestMarketStore(tmp_path / "trusted-context.sqlite3")
    dataset_hash = _seed_dataset(store)

    def reject_redundant_init(self, **values):
        del self, values
        raise AssertionError("runner repeated public context validation")

    monkeypatch.setattr(EvaluationContext, "__init__", reject_redundant_init)

    report = OfflineBacktestRunner(store).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert len(report.decisions) == 49


def test_twenty_trading_day_latency_keeps_the_complete_ordered_report(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "twenty-trading-days.sqlite3")
    dataset_hash = _seed_twenty_trading_day_dataset(store)
    source = _FrozenReaderSource(store)

    started = perf_counter()
    report = OfflineBacktestRunner(source).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    elapsed_seconds = perf_counter() - started

    assert len(report.decisions) == 20 * 49
    assert len(report.daily_equity) == 20
    assert source.open_count == 1
    assert elapsed_seconds <= 30


def test_long_replay_reclaims_transient_memory_at_bounded_day_intervals(
    tmp_path,
    monkeypatch,
) -> None:
    store = BacktestMarketStore(tmp_path / "replay-memory-reclaim.sqlite3")
    dataset_hash = _seed_twenty_trading_day_dataset(store)
    reclaim_count = 0

    def observed_reclaim() -> None:
        nonlocal reclaim_count
        reclaim_count += 1

    monkeypatch.setattr(runner_module, "_reclaim_replay_temporaries", observed_reclaim)

    report = OfflineBacktestRunner(store).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert len(report.daily_equity) == 20
    assert reclaim_count == 1


def test_report_build_streams_without_full_dump_or_recursive_normalization(
    tmp_path,
    monkeypatch,
) -> None:
    store = BacktestMarketStore(tmp_path / "report-build.sqlite3")
    report = OfflineBacktestRunner(store).run(
        plan=_plan(),
        dataset_hash=_seed_dataset(store),
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    values = report.model_dump(
        mode="python",
        round_trip=True,
        exclude={"report_hash"},
    )
    original = runner_module._BacktestRunReportPayload.model_dump
    dump_count = 0

    def observed_dump(self, *args, **kwargs):
        nonlocal dump_count
        dump_count += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        runner_module._BacktestRunReportPayload,
        "model_dump",
        observed_dump,
    )

    def reject_recursive_normalization(value):
        del value
        raise AssertionError("report hashing repeated recursive normalization")

    monkeypatch.setattr(runner_module, "_canonical_json", reject_recursive_normalization)

    rebuilt = runner_module.BacktestRunReport.build(**values)

    assert dump_count == 0
    assert rebuilt == report


def test_runner_hashes_each_generated_decision_only_once(tmp_path, monkeypatch) -> None:
    store = BacktestMarketStore(tmp_path / "decision-hash-count.sqlite3")
    dataset_hash = _seed_dataset(store)
    original = decision_models_module._evaluation_result_digest
    digest_count = 0

    def observed_digest(payload):
        nonlocal digest_count
        digest_count += 1
        return original(payload)

    monkeypatch.setattr(
        decision_models_module,
        "_evaluation_result_digest",
        observed_digest,
    )

    report = OfflineBacktestRunner(store).run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert len(report.decisions) == 49
    assert digest_count == len(report.decisions)


def test_runner_interns_repeated_immutable_decision_evidence(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "decision-evidence-interning.sqlite3")
    report = OfflineBacktestRunner(store).run(
        plan=_plan(),
        dataset_hash=_seed_dataset(store),
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    rules = tuple(
        evidence
        for decision in report.decisions
        for evidence in decision.snapshot.condition_evidence
        if isinstance(evidence, RuleEvidence)
    )

    assert len(rules) > 1
    assert len({id(evidence) for evidence in rules}) == 1
    restored = EvaluationResult.model_validate_json(report.decisions[-1].model_dump_json())
    assert restored == report.decisions[-1]


def test_midrun_cancellation_and_restart_replay_from_the_frozen_beginning(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(store)
    source = _FrozenReaderSource(store)
    cancellation_token = CancellationToken()

    def cancelling_evaluator(context: EvaluationContext) -> EvaluationResult:
        assert source.last_yielded == (context.plan.symbol, context.trade_date)
        result = _actionable_fixture(context)
        if isinstance(
            context.target, IntradayEvaluationTarget
        ) and context.target.bucket_end.time() == time(9, 35):
            cancellation_token.cancel()
        return result

    runner = OfflineBacktestRunner(source, evaluator=cancelling_evaluator)
    cancelled = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        cancellation_token=cancellation_token,
    )

    assert isinstance(cancelled, BacktestCancellationResult)
    assert cancelled.phase == "RUN_MINUTE"
    assert cancelled.last_safe_event_id is not None
    assert re.fullmatch(r"[0-9a-f]{64}", cancelled.last_safe_event_id)
    assert not hasattr(cancelled, "decisions")

    restarted = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    repeated = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert restarted.canonical_json() == repeated.canonical_json()
    assert source.open_count == 3
    assert len(source.yielded_by_open) == 3
    assert len({trace[0] for trace in source.yielded_by_open}) == 1


def test_second_symbol_twenty_day_replays_are_actionable_stable_and_shanghai(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "two-symbol-20d.sqlite3")
    dataset_hash, fixture = _seed_two_symbol_replay_dataset(store)
    source = _FrozenReaderSource(store)
    buy_date = date.fromisoformat(str(fixture["start"]))
    sell_date = buy_date + timedelta(days=1)

    def actionable(context: EvaluationContext) -> EvaluationResult:
        assert source.last_yielded == (context.plan.symbol, context.trade_date)
        return _actionable_fixture_for_dates(
            context,
            buy_date=buy_date,
            sell_date=sell_date,
        )

    for symbol_fixture in fixture["symbols"]:
        runner = OfflineBacktestRunner(source, evaluator=actionable)
        arguments = {
            "plan": _plan_for_fixture_symbol(symbol_fixture),
            "dataset_hash": dataset_hash,
            "initial_cash_fen": 10_000_000,
            "execution_config": _execution_config(),
            "manual_event_risk": False,
        }
        first = runner.run(**arguments)
        second = runner.run(**arguments)

        assert first.canonical_json() == second.canonical_json()
        assert tuple(fill.side.value for fill in first.fills) == ("BUY", "SELL")
        assert first.fills[1].filled_at.date() > first.fills[0].filled_at.date()
        assert len(first.daily_equity) == 2
        timestamps = re.findall(
            r'\d{4}-\d{2}-\d{2}T[^"\\]+',
            first.canonical_json(),
        )
        assert timestamps
        assert all(
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}[+]08:00",
                timestamp,
            )
            for timestamp in timestamps
        )

    assert source.open_count == 4


def test_runner_v2_initial_lot_preserves_t1_equity_and_restart_bytes(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "initial-lot.sqlite3")
    dataset_hash, fixture = _seed_two_symbol_replay_dataset(store)
    plan = _plan_for_fixture_symbol(fixture["symbols"][0])
    start = date.fromisoformat(str(fixture["start"]))
    initial_lot = BacktestInitialLotInput(
        lot_key="same-day-tactical",
        bucket="TACTICAL",
        acquired_trade_date=start,
        quantity=100,
        cost_basis_fen=640_000,
    )
    run_input = BacktestRunInput.create(
        plan=plan,
        manifest=store.dataset_manifest(dataset_hash),
        initial_cash_fen=10_000_000,
        initial_lots=(initial_lot,),
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    expected_lot_id = run_input.derive_position_lots()[0].lot_id
    cancellation_token = CancellationToken()
    cancel_once = True

    def sell_existing_tactical(context: EvaluationContext) -> EvaluationResult:
        nonlocal cancel_once
        result = _actionable_fixture_for_dates(
            context,
            buy_date=date.min,
            sell_date=context.trade_date,
        )
        if (
            cancel_once
            and isinstance(context.target, IntradayEvaluationTarget)
            and context.target.bucket_end.time() == time(9, 35)
        ):
            cancellation_token.cancel()
            cancel_once = False
        return result

    runner = OfflineBacktestRunner(store, evaluator=sell_existing_tactical)
    arguments = {
        "plan": plan,
        "dataset_hash": dataset_hash,
        "initial_cash_fen": 10_000_000,
        "initial_lots": (initial_lot,),
        "execution_config": _execution_config(),
        "manual_event_risk": False,
    }
    cancelled = runner.run(**arguments, cancellation_token=cancellation_token)
    restarted = runner.run(**arguments)
    repeated = runner.run(**arguments)
    assert isinstance(cancelled, BacktestCancellationResult) and cancelled.phase == "RUN_MINUTE"
    assert restarted.canonical_json() == repeated.canonical_json()
    assert restarted.run_id == run_input.run_id
    assert restarted.metrics.initial_equity_fen == 10_647_400
    assert tuple(snapshot.position_quantity for snapshot in restarted.daily_equity) == (100, 0)
    assert tuple(snapshot.cost_basis_fen for snapshot in restarted.daily_equity) == (640_000, 0)
    assert restarted.outcomes[0].reason.value == "T_PLUS_ONE"
    assert restarted.fills[0].filled_at.date() > initial_lot.acquired_trade_date
    assert {signal.target_lot_id for signal in restarted.signals} == {expected_lot_id}


def test_offline_runner_is_byte_stable_and_emits_only_daily_equity(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(store)
    runner = OfflineBacktestRunner(store)

    first = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    second = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert first.run_id == second.run_id
    assert first.report_hash == second.report_hash
    assert first.canonical_json() == second.canonical_json()
    assert len(first.decisions) == 49
    assert len(first.daily_equity) == 1
    assert first.daily_equity[0].marked_at == datetime.combine(
        TRADE_DATE,
        time(15, 20),
        SHANGHAI,
    )
    assert first.limitations == (
        "UNADJUSTED_PRICES_NO_CORPORATE_ACTIONS",
        "SIMULATED_EXECUTION_NO_BROKER",
        "ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY",
        "FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME",
        "CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE",
        "DAILY_EQUITY_DRAWDOWN_SAMPLING",
        "WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP",
        "METRIC_DECIMAL_PRECISION_28_HALF_EVEN",
        "HISTORICAL_MINUTES_DO_NOT_VERIFY_REALTIME",
        "BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR",
    )

    result_store = BacktestResultStore(tmp_path / "results.sqlite3")
    persisted = persist_report(result_store, first)
    duplicate = persist_report(result_store, second)
    json_path, csv_path = write_report_files(
        first,
        json_path=tmp_path / "report.json",
        csv_path=tmp_path / "fills.csv",
    )
    assert persisted.summary_created is True
    assert duplicate.summary_created is False
    assert duplicate.fills_created == 0
    assert duplicate.details_created == 0
    assert result_store.statistics().run_count == 1
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary["schemaVersion"] == "backtest-report-summary-v1"
    assert summary["runId"] == first.run_id
    assert summary["reportHash"] == first.report_hash
    assert "decisions" not in summary
    assert csv_path.read_text(encoding="utf-8").startswith("run_id,fill_id,filled_at,")

    result_store.prune_details(as_of=datetime(2027, 1, 1, tzinfo=UTC))
    assert result_store.list_details(first.run_id) == ()
    replay_after_retention = persist_report(result_store, first)
    assert replay_after_retention.details_created == 0
    assert result_store.list_details(first.run_id) == ()


def test_runner_wires_actionable_signals_to_next_tradable_fills_and_persistence(
    tmp_path,
) -> None:
    market_store = BacktestMarketStore(tmp_path / "market.sqlite3")
    first_dataset = _seed_dataset(market_store)
    dataset_hash = _extend_dataset_to_second_day(market_store, first_dataset)
    runner = OfflineBacktestRunner(
        market_store,
        evaluator=_actionable_fixture,
    )
    scaled_config = _execution_config().model_copy(
        update={
            "commission_rate": Decimal("0.00030"),
            "stamp_duty_rate": Decimal("0.00050"),
            "transfer_fee_rate": Decimal("0.000010"),
            "buy_slippage_bps": Decimal("2.0"),
            "sell_slippage_bps": Decimal("2.00"),
        }
    )
    with localcontext() as context:
        context.prec = 6
        report = runner.run(
            plan=_plan(),
            dataset_hash=dataset_hash,
            initial_cash_fen=10_000_003,
            execution_config=scaled_config,
            manual_event_risk=False,
        )
    with localcontext() as context:
        context.prec = 50
        high_precision_report = runner.run(
            plan=_plan(),
            dataset_hash=dataset_hash,
            initial_cash_fen=10_000_003,
            execution_config=_execution_config(),
            manual_event_risk=False,
        )

    assert scaled_config.config_hash == _execution_config().config_hash
    assert high_precision_report.run_id == report.run_id
    assert high_precision_report.report_hash == report.report_hash
    assert high_precision_report.canonical_json() == report.canonical_json()

    assert tuple(signal.signal_type for signal in report.signals) == (
        ActionableSignalType.BUY_TACTICAL_READY,
        ActionableSignalType.PRESSURE_REDUCE_READY,
    )
    assert len(report.orders) == len(report.fills) == len(report.outcomes) == 2
    assert all(outcome.status.value == "FILLED" for outcome in report.outcomes)
    decisions = {decision.result_hash: decision for decision in report.decisions}
    for signal in report.signals:
        decision = decisions[signal.result_hash]
        assert signal.signal_at == decision.snapshot.evaluated_at
        assert signal.signal_at.second == 12
    assert tuple(fill.filled_at for fill in report.fills) == (
        datetime.combine(TRADE_DATE, time(9, 36), SHANGHAI),
        datetime.combine(TRADE_DATE + timedelta(days=1), time(9, 36), SHANGHAI),
    )
    assert tuple(outcome.resolved_at for outcome in report.outcomes) == tuple(
        fill.filled_at for fill in report.fills
    )
    assert tuple(outcome.source_bar_id for outcome in report.outcomes) == tuple(
        fill.source_bar_id for fill in report.fills
    )
    assert report.fills[0].side.value == "BUY"
    assert report.fills[1].side.value == "SELL"
    assert report.fills[1].filled_at.date() > report.fills[0].filled_at.date()
    assert all(fill.fees.total_fen > 0 for fill in report.fills)
    assert report.fills[1].realized_pnl_fen is not None

    result_store = BacktestResultStore(tmp_path / "results.sqlite3")
    persist_report(result_store, report)
    persisted_fills = result_store.list_fills(report.run_id)
    persisted_signals = result_store.list_details(
        report.run_id,
        kind=BacktestDetailKind.SIGNAL,
    )
    persisted_outcomes = result_store.list_details(
        report.run_id,
        kind=BacktestDetailKind.EXECUTION_OUTCOME,
    )
    assert tuple(item.fill_id for item in persisted_fills) == tuple(
        fill.fill_id for fill in report.fills
    )
    assert tuple(item.payload["signal_id"] for item in persisted_signals) == tuple(
        signal.signal_id for signal in report.signals
    )
    assert tuple(item.event_at for item in persisted_outcomes) == tuple(
        outcome.resolved_at.astimezone(UTC) for outcome in report.outcomes
    )
    assert tuple(item.payload["source_bar_id"] for item in persisted_outcomes) == tuple(
        outcome.source_bar_id for outcome in report.outcomes
    )


def test_frozen_dataset_report_ignores_a_later_provider_head_correction(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(store)
    runner = OfflineBacktestRunner(store)
    first = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    original = store.dataset_daily_bar(dataset_hash, SYMBOL, TRADE_DATE)
    store.record_daily_bars((original.model_copy(update={"close_fen": 6_401}),))

    replay = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )

    assert replay.canonical_json() == first.canonical_json()
    revised = store.freeze_dataset(store.dataset_manifest(dataset_hash).scope)
    assert revised.dataset_hash is not None
    corrected = runner.run(
        plan=_plan(),
        dataset_hash=revised.dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    assert tuple(item.result_hash for item in corrected.decisions[:-1]) == tuple(
        item.result_hash for item in first.decisions[:-1]
    )


def test_two_execution_configs_can_persist_shared_decisions(tmp_path) -> None:
    market_store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _seed_dataset(market_store)
    runner = OfflineBacktestRunner(market_store)
    first = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    second_config = _execution_config().model_copy(update={"commission_rate": Decimal("0.0004")})
    second = runner.run(
        plan=_plan(),
        dataset_hash=dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=second_config,
        manual_event_risk=False,
    )
    assert first.run_id != second.run_id
    assert first.decisions[0].result_hash == second.decisions[0].result_hash

    result_store = BacktestResultStore(tmp_path / "results.sqlite3")
    persist_report(result_store, first)
    persist_report(result_store, second)

    assert result_store.statistics().run_count == 2


def test_interrupted_detail_persistence_stays_hidden_and_resumes(
    tmp_path,
    monkeypatch,
) -> None:
    market_store = BacktestMarketStore(tmp_path / "market.sqlite3")
    report = OfflineBacktestRunner(market_store).run(
        plan=_plan(),
        dataset_hash=_seed_dataset(market_store),
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
    )
    result_store = BacktestResultStore(tmp_path / "results.sqlite3")
    original = BacktestResultStore.record_details

    def fail_details(self, run_id, details):
        del self, run_id, details
        raise OSError("injected detail write failure")

    monkeypatch.setattr(BacktestResultStore, "record_details", fail_details)
    with pytest.raises(OSError, match="injected detail"):
        persist_report(result_store, report)

    assert result_store.get_run(report.run_id) is None
    assert result_store.get_run(report.run_id, include_unmaterialized=True) is not None

    monkeypatch.setattr(BacktestResultStore, "record_details", original)
    resumed = persist_report(result_store, report)

    assert resumed.summary_created is False
    assert result_store.get_run(report.run_id) is not None


def test_missing_report_files_are_rebuilt_from_materialized_results(
    tmp_path,
    monkeypatch,
) -> None:
    market_path = tmp_path / "market.sqlite3"
    dataset_hash = _seed_dataset(BacktestMarketStore(market_path))
    result_path = tmp_path / "results.sqlite3"
    report_directory = tmp_path / "reports"
    service = BacktestApplicationService(
        config_path=tmp_path / "unused.yaml",
        market_database=market_path,
        results_database=result_path,
        report_directory=report_directory,
    )
    monkeypatch.setattr(application_module, "_load_plan", lambda _path: _plan())
    original_write = application_module.write_report_files

    def fail_report_write(*_args, **_kwargs):
        raise OSError("injected report write failure")

    monkeypatch.setattr(application_module, "write_report_files", fail_report_write)
    arguments = {
        "dataset_hash": dataset_hash,
        "plan_path": tmp_path / "plan.yaml",
        "initial_cash_yuan": Decimal("100000"),
        "commission_rate": Decimal("0.0003"),
        "minimum_commission_yuan": Decimal("5"),
        "stamp_duty_rate": Decimal("0.0005"),
        "transfer_fee_rate": Decimal("0.00001"),
        "buy_slippage_bps": Decimal("2"),
        "sell_slippage_bps": Decimal("2"),
        "manual_event_risk": False,
    }
    with pytest.raises(OSError, match="injected report"):
        service.run(**arguments)

    run = BacktestResultStore(result_path).list_runs()[0]
    json_path = report_directory / f"{run.run_id}.json"
    csv_path = report_directory / f"{run.run_id}.fills.csv"
    assert not json_path.exists()
    assert not csv_path.exists()

    monkeypatch.setattr(application_module, "write_report_files", original_write)
    recovered = service.run(**arguments)

    assert recovered.reused is True
    assert json_path.exists()
    assert csv_path.exists()
