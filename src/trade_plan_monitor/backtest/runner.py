"""Deterministic event-time replay over one frozen local market dataset."""

from __future__ import annotations

import gc
import json
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from datetime import date, datetime, time
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import Enum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.backtest.canonical import canonical_decimal, canonical_json
from trade_plan_monitor.backtest.control import (
    BacktestCancellationResult,
    BacktestOperationCancelled,
    CancellationToken,
    check_cancelled,
    validate_operation_controls,
)
from trade_plan_monitor.backtest.dataset import (
    DatasetManifest,
    FrozenDatasetReader,
    FrozenDatasetSource,
    FrozenMarketIndexDatasetReader,
    SymbolFilteredFrozenDatasetSource,
)
from trade_plan_monitor.backtest.execution import DeterministicExecutionEngine
from trade_plan_monitor.backtest.index_data import (
    BacktestReferenceMarketResult,
    MarketIndexReplaySeries,
    build_backtest_index_requirement,
    build_reference_market_result,
)
from trade_plan_monitor.backtest.models import (
    EquitySnapshot,
    ExecutionBar,
    ExecutionConfig,
    ExecutionFill,
    ExecutionOrder,
    ExecutionOutcome,
    ExecutionSignal,
    PositionLot,
    PositionSnapshot,
)
from trade_plan_monitor.backtest.research_input import UnifiedResearchInput
from trade_plan_monitor.backtest.research_report import UnifiedReplayReport
from trade_plan_monitor.backtest.run_input import (
    CALENDAR_CONTEXT_DAYS,
    DAILY_CONTEXT_BARS,
    FIVE_MINUTE_CONTEXT_BARS,
    RUN_FORMULA_V1,
    BacktestInitialLotInput,
    BacktestRunInput,
)
from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationEvidence,
    EvaluationResult,
    EvidenceFact,
    IntradayEvaluationTarget,
    NextStep,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    RuleEvidence,
    SignalType,
)
from trade_plan_monitor.domain.plan_models import TradePlan, activation_is_eligible_on
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    validate_trade_plan,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    aggregate_provisional_daily_bar,
)
from trade_plan_monitor.market_data.indicators import (
    _calculate_daily_ta_v1_from_prefix,
    _calculate_daily_ta_v1_prefix,
    _DailyTaV1Prefix,
    calculate_ta_v1,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close

SHANGHAI = ZoneInfo("Asia/Shanghai")
RUN_FORMULA_VERSION = RUN_FORMULA_V1
_REPORT_SCHEMA_VERSION = "backtest-report-v1"
_INDEX_REPORT_SCHEMA_VERSION = "backtest-report-v2"
_FIVE_MINUTE_CONTEXT_BARS = FIVE_MINUTE_CONTEXT_BARS
_DAILY_CONTEXT_BARS = DAILY_CONTEXT_BARS
_CALENDAR_CONTEXT_DAYS = CALENDAR_CONTEXT_DAYS
_METRIC_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_REPLAY_MEMORY_RECLAIM_DAYS = 20
_LIMITATIONS = (
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

Evaluator = Callable[[EvaluationContext], EvaluationResult]


def _trusted_rebind_equal[T: BaseModel](value: T, **updates: object) -> T:
    for name, replacement in updates.items():
        if replacement != getattr(value, name):
            raise RuntimeError("replay interning cannot change validated decision values")
    value.__dict__.update(updates)
    return value


def _intern[K, V](cache: dict[K, V], key: K, value: V) -> V:
    existing = cache.get(key)
    if existing is not None:
        return existing
    cache[key] = value
    return value


class _ReplayInternPool:
    """Share equal frozen evidence subtrees within one bounded replay."""

    def __init__(self) -> None:
        self._facts: dict[tuple[object, ...], EvidenceFact] = {}
        self._evidence: dict[tuple[object, ...], EvaluationEvidence] = {}
        self._next_steps: dict[tuple[object, ...], NextStep] = {}
        self._positions: dict[tuple[object, ...], PositionSummary] = {}

    def fact(self, value: EvidenceFact) -> EvidenceFact:
        return _intern(
            self._facts,
            (value.key, value.value, value.unit),
            value,
        )

    def evidence(self, value: EvaluationEvidence) -> EvaluationEvidence:
        facts = tuple(self.fact(fact) for fact in value.facts)
        if isinstance(value, ConditionEvidence):
            children = tuple(self.evidence(child) for child in value.children)
            normalized = _trusted_rebind_equal(value, facts=facts, children=children)
            key = (
                ConditionEvidence,
                id(value.condition),
                value.outcome,
                tuple(id(fact) for fact in facts),
                value.missing_inputs,
                tuple(id(child) for child in children),
                value.index_evidence,
            )
        elif isinstance(value, RuleEvidence):
            normalized = _trusted_rebind_equal(value, facts=facts)
            key = (
                RuleEvidence,
                value.code,
                value.outcome,
                tuple(id(fact) for fact in facts),
                value.missing_inputs,
            )
        else:  # pragma: no cover - closed EvaluationEvidence union
            raise TypeError("unsupported evaluation evidence")
        return _intern(self._evidence, key, normalized)

    def result(self, value: EvaluationResult) -> EvaluationResult:
        next_step = _intern(
            self._next_steps,
            (
                value.next_step.code,
                value.next_step.not_before,
                value.next_step.required_inputs,
            ),
            value.next_step,
        )
        condition_evidence = tuple(
            self.evidence(evidence) for evidence in value.snapshot.condition_evidence
        )
        snapshot = _trusted_rebind_equal(
            value.snapshot,
            condition_evidence=condition_evidence,
            next_step=next_step,
            position=_intern(
                self._positions,
                tuple(
                    getattr(value.snapshot.position, name)
                    for name in type(value.snapshot.position).model_fields
                ),
                value.snapshot.position,
            ),
        )
        signal_intent = value.signal_intent
        if signal_intent is not None:
            signal_intent = _trusted_rebind_equal(
                signal_intent,
                matched_conditions=tuple(
                    self.evidence(evidence) for evidence in signal_intent.matched_conditions
                ),
                blockers=tuple(self.evidence(evidence) for evidence in signal_intent.blockers),
                next_step=next_step,
            )
        return _trusted_rebind_equal(
            value,
            snapshot=snapshot,
            signal_intent=signal_intent,
            satisfied_conditions=tuple(
                self.evidence(evidence) for evidence in value.satisfied_conditions
            ),
            unmet_conditions=tuple(self.evidence(evidence) for evidence in value.unmet_conditions),
            blockers=tuple(self.evidence(evidence) for evidence in value.blockers),
            next_step=next_step,
        )


class _BacktestValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BacktestMetrics(_BacktestValue):
    """Exact end-of-run metrics without binary floating-point money."""

    initial_cash_fen: int = Field(strict=True, gt=0)
    initial_equity_fen: int = Field(strict=True, gt=0)
    final_cash_fen: int = Field(strict=True, ge=0)
    final_equity_fen: int = Field(strict=True, ge=0)
    total_return: Decimal
    maximum_drawdown: Decimal
    trade_count: int = Field(strict=True, ge=0)
    winning_sell_count: int = Field(strict=True, ge=0)
    win_rate: Decimal
    turnover_fen: int = Field(strict=True, ge=0)
    total_cost_fen: int = Field(strict=True, ge=0)
    realized_pnl_fen: int = Field(strict=True)
    unrealized_pnl_fen: int = Field(strict=True)
    blocked_count: int = Field(strict=True, ge=0)
    skipped_count: int = Field(strict=True, ge=0)


class _BacktestRunReportPayload(_BacktestValue):
    schema_version: Literal["backtest-report-v1", "backtest-report-v2"] = _REPORT_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETED"] = "COMPLETED"
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str
    start: date
    end: date
    manual_event_risk: bool
    execution_config: ExecutionConfig
    decisions: tuple[EvaluationResult, ...]
    signals: tuple[ExecutionSignal, ...]
    orders: tuple[ExecutionOrder, ...]
    fills: tuple[ExecutionFill, ...]
    outcomes: tuple[ExecutionOutcome, ...]
    daily_equity: tuple[EquitySnapshot, ...]
    final_positions: tuple[PositionSnapshot, ...]
    metrics: BacktestMetrics
    limitations: tuple[str, ...] = _LIMITATIONS
    reference_market: BacktestReferenceMarketResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_schema_version(self) -> Self:
        if (self.schema_version == _INDEX_REPORT_SCHEMA_VERSION) != (
            self.reference_market is not None
        ):
            raise ValueError("report schema version must match reference-market content")
        return self


class BacktestRunReport(_BacktestRunReportPayload):
    """Complete stable MVP report returned before isolated result persistence."""

    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values: object) -> Self:
        if "report_hash" in values:
            raise TypeError("build computes report_hash")
        payload = _BacktestRunReportPayload.model_validate(values)
        return cls._from_validated_payload(payload)

    @classmethod
    def _build_from_validated(cls, **values: object) -> Self:
        """Build from runner-owned values that have already crossed strict boundaries."""
        if "report_hash" in values:
            raise TypeError("build computes report_hash")
        return cls._from_validated_payload(_BacktestRunReportPayload.model_construct(**values))

    @classmethod
    def _from_validated_payload(cls, payload: _BacktestRunReportPayload) -> Self:
        digest = _stable_model_hash(
            payload,
            domain=payload.schema_version,
            exclude_fields=(
                frozenset({"reference_market"})
                if payload.schema_version == _REPORT_SCHEMA_VERSION
                else frozenset()
            ),
        )
        return cls.model_construct(
            **{name: getattr(payload, name) for name in _BacktestRunReportPayload.model_fields},
            report_hash=digest,
        )

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="python", round_trip=True))

    @model_validator(mode="after")
    def validate_report_hash(self) -> Self:
        expected = _stable_model_hash(
            self,
            domain=self.schema_version,
            exclude_fields=(
                frozenset({"report_hash", "reference_market"})
                if self.schema_version == _REPORT_SCHEMA_VERSION
                else frozenset({"report_hash"})
            ),
        )
        if self.report_hash != expected:
            raise ValueError("report_hash must match the canonical report")
        return self


class BacktestBlockedError(RuntimeError):
    """Stable fail-closed blockers raised before a result can be claimed complete."""

    def __init__(self, *blockers: str) -> None:
        if not blockers or any(type(value) is not str or not value for value in blockers):
            raise ValueError("backtest blockers must be non-empty strings")
        self.blockers = tuple(blockers)
        super().__init__("backtest blocked: " + ",".join(self.blockers))


class OfflineBacktestRunner:
    """Replay only frozen local facts through the production pure decision engine."""

    def __init__(
        self,
        dataset_source: FrozenDatasetSource,
        *,
        evaluator: Evaluator = evaluate,
    ) -> None:
        if not isinstance(dataset_source, FrozenDatasetSource):
            raise TypeError("dataset_source must open frozen dataset readers")
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        self._dataset_source = dataset_source
        self._evaluator = evaluator

    def run(
        self,
        *,
        plan: TradePlan | UnifiedTradePlan,
        dataset_hash: str,
        initial_cash_fen: int,
        execution_config: ExecutionConfig,
        manual_event_risk: bool,
        plan_version_id: UUID | None = None,
        initial_lots: tuple[BacktestInitialLotInput, ...] = (),
        cancellation_token: CancellationToken | None = None,
        research_input: UnifiedResearchInput | None = None,
    ) -> BacktestRunReport | UnifiedReplayReport | BacktestCancellationResult:
        """Run a finite offline replay; no provider, scheduler, or notification is reachable."""

        if not isinstance(plan, UnifiedTradePlan):
            if research_input is not None:
                raise ValueError("RESEARCH_INPUT_FORBIDDEN")
            self._validate_request(
                plan=plan,
                initial_cash_fen=initial_cash_fen,
                execution_config=execution_config,
                manual_event_risk=manual_event_risk,
                plan_version_id=plan_version_id,
                initial_lots=initial_lots,
            )
        validate_operation_controls(cancellation_token, None)
        try:
            check_cancelled(cancellation_token, "RUN_DAY_TRANSITION")
            if isinstance(self._dataset_source, SymbolFilteredFrozenDatasetSource):
                reader_context = self._dataset_source.open_frozen_symbol_dataset(
                    dataset_hash,
                    plan.symbol,
                )
            else:
                reader_context = self._dataset_source.open_frozen_dataset(dataset_hash)
            with reader_context as reader:
                if isinstance(plan, UnifiedTradePlan):
                    from trade_plan_monitor.backtest.research_runner import replay_current

                    return replay_current(
                        reader,
                        plan=plan,
                        initial_cash_fen=initial_cash_fen,
                        initial_lots=initial_lots,
                        execution_config=execution_config,
                        manual_event_risk=manual_event_risk,
                        plan_version_id=plan_version_id,
                        research_input=research_input,
                        cancellation_token=cancellation_token,
                    )
                return self._run_from_reader(
                    reader=reader,
                    plan=plan,
                    dataset_hash=dataset_hash,
                    initial_cash_fen=initial_cash_fen,
                    execution_config=execution_config,
                    manual_event_risk=manual_event_risk,
                    plan_version_id=plan_version_id,
                    initial_lots=initial_lots,
                    cancellation_token=cancellation_token,
                )
        except BacktestOperationCancelled as cancelled:
            return BacktestCancellationResult(
                phase=cancelled.phase,
                last_safe_event_id=cancelled.last_safe_event_id,
            )

    def _run_from_reader(
        self,
        *,
        reader: FrozenDatasetReader,
        plan: TradePlan,
        dataset_hash: str,
        initial_cash_fen: int,
        execution_config: ExecutionConfig,
        manual_event_risk: bool,
        plan_version_id: UUID | None,
        initial_lots: tuple[BacktestInitialLotInput, ...],
        cancellation_token: CancellationToken | None,
    ) -> BacktestRunReport:
        if reader.dataset_hash != dataset_hash:
            raise BacktestBlockedError("DATASET_READER_IDENTITY_MISMATCH")
        scope = reader.scope
        if plan.symbol not in scope.symbols:
            raise BacktestBlockedError(f"PLAN_SYMBOL_NOT_IN_DATASET:{plan.symbol}")
        index_requirement = build_backtest_index_requirement(plan)
        index_series: MarketIndexReplaySeries | None = None
        index_bars = ()
        index_official_open_dates: tuple[date, ...] = ()
        reference_market: BacktestReferenceMarketResult | None = None
        if index_requirement.required:
            if not isinstance(reader, FrozenMarketIndexDatasetReader):
                raise BacktestBlockedError("MISSING_REFERENCE_MARKET_DATASET")
            manifest = reader.manifest
            if manifest.dataset_hash != dataset_hash:
                raise BacktestBlockedError("DATASET_READER_IDENTITY_MISMATCH")
            binding = index_requirement.binding
            if binding is None:  # pragma: no cover - requirement model guards this
                raise BacktestBlockedError("MISSING_REFERENCE_MARKET_BINDING")
            index_bars = reader.market_index_bars(binding.index_code)
            index_official_open_dates = tuple(
                sorted(
                    {
                        item.trade_date
                        for item in manifest.items
                        if item.kind == "DAILY" and item.symbol == plan.symbol
                    }
                )
            )
            index_series = MarketIndexReplaySeries(
                index_code=binding.index_code,
                bars=index_bars,
                dataset_revision=reader.dataset_revision,
            )
        else:
            manifest = DatasetManifest(dataset_hash=dataset_hash, scope=scope, items=())
        run_input = BacktestRunInput.create(
            plan=plan,
            manifest=manifest,
            initial_cash_fen=initial_cash_fen,
            initial_lots=initial_lots,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
            plan_version_id=plan_version_id,
        )
        if index_requirement.required:
            if run_input.market_index_data_hash is None:  # pragma: no cover - v3 guard
                raise BacktestBlockedError("MISSING_INDEX_DATA_HASH")
            reference_market = build_reference_market_result(
                plan=plan,
                dataset_hash=dataset_hash,
                market_data_hash=run_input.market_index_data_hash,
                event_start=scope.start,
                dataset_warmup_start=scope.warmup_start,
                official_open_dates=index_official_open_dates,
                bars=index_bars,
            )
            if reference_market.blockers:
                raise BacktestBlockedError(*reference_market.blockers)
        position_lots = run_input.derive_position_lots()
        plan_hash = run_input.plan_sha256
        run_id = run_input.run_id
        engine = DeterministicExecutionEngine(
            config=execution_config,
            run_id=run_id,
            plan_hash=plan_hash,
            dataset_hash=dataset_hash,
            symbol=plan.symbol,
            initial_cash_fen=initial_cash_fen,
            max_position_qty=plan.position.max_qty,
            core_target_qty=plan.position.core_target_qty,
            tactical_target_qty=plan.position.tactical_target_qty,
            initial_lots=position_lots,
        )
        activation_origin = datetime.combine(scope.start, time(9, 0), SHANGHAI)
        risk_state: RiskStateSnapshot | None = None
        episode = None
        intern_pool = _ReplayInternPool()
        decisions: list[EvaluationResult] = []
        signals: list[ExecutionSignal] = []
        orders: list[ExecutionOrder] = []
        fills: list[ExecutionFill] = []
        outcomes: list[ExecutionOutcome] = []
        daily_equity: list[EquitySnapshot] = []
        complete_five_minute_bars: deque[FiveMinuteBar] = deque(maxlen=_FIVE_MINUTE_CONTEXT_BARS)
        trading_calendar: deque[TradingDay] = deque(maxlen=_CALENDAR_CONTEXT_DAYS)
        official_history: deque[DailyBar] = deque(maxlen=_DAILY_CONTEXT_BARS)
        required_warmup = _required_daily_warmup(plan)
        initial_equity_fen: int | None = None
        open_day_count = 0
        last_safe_event_id: str | None = None

        for symbol_day in reader:
            check_cancelled(
                cancellation_token,
                "RUN_DAY_TRANSITION",
                last_safe_event_id,
            )
            if symbol_day.symbol != plan.symbol:
                continue
            trade_date = symbol_day.trade_date
            trading_day = symbol_day.trading_day
            trading_calendar.append(trading_day)
            official_bar = symbol_day.daily_bar
            if trade_date < scope.start:
                if trading_day.is_open:
                    if official_bar is None:  # pragma: no cover - dataset model guards this
                        raise BacktestBlockedError(
                            f"MISSING_WARMUP_DAILY:{plan.symbol}:{trade_date.isoformat()}"
                        )
                    official_history.append(official_bar)
                    last_safe_event_id = _safe_event_id(official_bar)
                continue
            if trade_date > scope.end:
                raise BacktestBlockedError("DATASET_READER_SCOPE_MISMATCH")
            if not trading_day.is_open:
                continue
            if len(official_history) < required_warmup:
                raise BacktestBlockedError(
                    f"INSUFFICIENT_DAILY_WARMUP:{len(official_history)}:{required_warmup}"
                )
            if risk_state is None:
                prior_close_fen = official_history[-1].close_fen
                initial_equity_fen = initial_cash_fen + sum(
                    lot.remaining_quantity * prior_close_fen for lot in position_lots
                )
                risk_state = RiskStateSnapshot(
                    symbol=plan.symbol,
                    plan_hash=plan_hash,
                    status=RiskStatus.CLEAR,
                    breach_trade_date=None,
                    prior_close_fen=prior_close_fen,
                    revision=0,
                    updated_at=activation_origin,
                )
            if (
                symbol_day.daily_limit is None or official_bar is None or not symbol_day.minutes
            ):  # pragma: no cover - dataset model guards this
                raise BacktestBlockedError(
                    f"INCOMPLETE_SYMBOL_DAY:{plan.symbol}:{trade_date.isoformat()}"
                )
            daily_limit = symbol_day.daily_limit
            minutes = symbol_day.minutes
            self._validate_day_facts(trading_day, daily_limit, minutes, official_bar)
            daily_indicator_prefix = _calculate_daily_ta_v1_prefix(tuple(official_history))
            open_day_count += 1
            day_minutes: list[MinuteBar] = []
            provisional: DailyBar | None = None

            for minute_index, minute in enumerate(minutes, start=1):
                check_cancelled(cancellation_token, "RUN_MINUTE", last_safe_event_id)
                execution_bar = ExecutionBar.create(
                    symbol=minute.symbol,
                    bar_end=minute.bar_end,
                    open_fen=minute.open_fen,
                    high_fen=minute.high_fen,
                    low_fen=minute.low_fen,
                    close_fen=minute.close_fen,
                    volume_shares=minute.volume_shares,
                    is_tradable=minute.volume_shares > 0,
                )
                execution_batch = engine.process_bar(
                    execution_bar,
                    daily_limit,
                )
                fills.extend(execution_batch.fills)
                outcomes.extend(execution_batch.outcomes)
                last_safe_event_id = execution_bar.source_bar_id
                day_minutes.append(minute)
                if minute_index % 5:
                    continue
                five_minute = aggregate_five_minute_bar(
                    tuple(day_minutes[-5:]),
                    bucket_end=minute.bar_end,
                    is_open=True,
                )
                if five_minute is None:
                    raise BacktestBlockedError(
                        f"INCOMPLETE_FIVE_MINUTE_BUCKET:{plan.symbol}:{minute.bar_end.isoformat()}"
                    )
                complete_five_minute_bars.append(five_minute)
                provisional = aggregate_provisional_daily_bar(
                    current_day_minutes=tuple(day_minutes),
                    source_as_of=minute.bar_end,
                )
                if provisional is None:
                    raise BacktestBlockedError(
                        f"MISSING_PROVISIONAL_DAILY:{plan.symbol}:{trade_date.isoformat()}"
                    )
                context = self._intraday_context(
                    plan=plan,
                    plan_hash=plan_hash,
                    trading_calendar=tuple(trading_calendar),
                    daily_limit=daily_limit,
                    official_history=tuple(official_history),
                    current_minutes=tuple(day_minutes),
                    five_minute_bars=tuple(complete_five_minute_bars),
                    provisional=provisional,
                    daily_indicator_prefix=daily_indicator_prefix,
                    risk_state=risk_state,
                    episode=episode,
                    engine=engine,
                    manual_event_risk=manual_event_risk,
                    activation_origin=activation_origin,
                    index_series=index_series,
                    index_requests=index_requirement.fact_requests,
                )
                check_cancelled(cancellation_token, "RUN_EVALUATION", last_safe_event_id)
                result = self._evaluate_context(context, intern_pool)
                decisions.append(result)
                episode, risk_state = _advance_state(result, episode, risk_state)
                if result.signal_intent is not None:
                    signal = ExecutionSignal.from_intent(
                        result.signal_intent,
                        run_id=run_id,
                        dataset_hash=dataset_hash,
                        result_hash=result.result_hash,
                        signal_at=result.snapshot.evaluated_at,
                    )
                    signals.append(signal)
                    submitted = engine.submit_signal(signal)
                    orders.extend(submitted.orders)
                    outcomes.extend(submitted.outcomes)
                last_safe_event_id = result.result_hash

            if provisional is None:
                raise BacktestBlockedError(
                    f"MISSING_COMPLETE_DAY:{plan.symbol}:{trade_date.isoformat()}"
                )
            official_context = self._official_context(
                plan=plan,
                plan_hash=plan_hash,
                trading_calendar=tuple(trading_calendar),
                daily_limit=daily_limit,
                official_history=tuple(official_history),
                current_minutes=tuple(day_minutes),
                five_minute_bars=tuple(complete_five_minute_bars),
                provisional=provisional,
                official=official_bar,
                daily_indicator_prefix=daily_indicator_prefix,
                risk_state=risk_state,
                episode=episode,
                engine=engine,
                manual_event_risk=manual_event_risk,
                activation_origin=activation_origin,
                index_series=index_series,
                index_requests=index_requirement.fact_requests,
            )
            check_cancelled(cancellation_token, "RUN_EVALUATION", last_safe_event_id)
            official_result = self._evaluate_context(official_context, intern_pool)
            decisions.append(official_result)
            episode, risk_state = _advance_state(official_result, episode, risk_state)
            if official_result.signal_intent is not None:
                signal = ExecutionSignal.from_intent(
                    official_result.signal_intent,
                    run_id=run_id,
                    dataset_hash=dataset_hash,
                    result_hash=official_result.result_hash,
                    signal_at=official_result.snapshot.evaluated_at,
                )
                signals.append(signal)
                submitted = engine.submit_signal(signal)
                orders.extend(submitted.orders)
                outcomes.extend(submitted.outcomes)
            last_safe_event_id = official_result.result_hash
            daily_equity.append(
                engine.equity_snapshot(
                    at=official_bar.received_at,
                    mark_price_fen=official_bar.close_fen,
                )
            )
            official_history.append(official_bar)
            if open_day_count % _REPLAY_MEMORY_RECLAIM_DAYS == 0:
                _reclaim_replay_temporaries()

        if open_day_count == 0:
            raise BacktestBlockedError("NO_OPEN_TRADING_DAYS")
        if initial_equity_fen is None:  # pragma: no cover - open-day guard initializes it
            raise BacktestBlockedError("INITIAL_EQUITY_UNAVAILABLE")
        replay_boundary = max(decision.snapshot.evaluated_at for decision in decisions)
        check_cancelled(cancellation_token, "RUN_FINALIZE", last_safe_event_id)
        finalized = engine.finalize(replay_boundary=replay_boundary)
        outcomes.extend(finalized.outcomes)
        metrics = _metrics(
            initial_cash_fen=initial_cash_fen,
            initial_equity_fen=initial_equity_fen,
            engine=engine,
            decisions=tuple(decisions),
            fills=tuple(fills),
            daily_equity=tuple(daily_equity),
        )
        check_cancelled(cancellation_token, "RUN_REPORT_HANDOFF", last_safe_event_id)
        if reference_market is not None:
            reference_market = build_reference_market_result(
                plan=plan,
                dataset_hash=dataset_hash,
                market_data_hash=reference_market.market_index_data_hash,
                event_start=scope.start,
                dataset_warmup_start=scope.warmup_start,
                official_open_dates=index_official_open_dates,
                bars=index_bars,
                decisions=tuple(decisions),
            )
        # Every nested model and scalar below was created by a strict public model
        # boundary or derived from those values inside this replay.
        return BacktestRunReport._build_from_validated(
            schema_version=(
                _INDEX_REPORT_SCHEMA_VERSION
                if reference_market is not None
                else _REPORT_SCHEMA_VERSION
            ),
            run_id=run_id,
            plan_hash=plan_hash,
            dataset_hash=dataset_hash,
            symbol=plan.symbol,
            start=scope.start,
            end=scope.end,
            manual_event_risk=manual_event_risk,
            execution_config=execution_config,
            decisions=tuple(decisions),
            signals=tuple(signals),
            orders=tuple(orders),
            fills=tuple(fills),
            outcomes=tuple(outcomes),
            daily_equity=tuple(daily_equity),
            final_positions=engine.position_snapshots,
            metrics=metrics,
            reference_market=reference_market,
        )

    @staticmethod
    def _validate_request(
        *,
        plan: TradePlan,
        initial_cash_fen: int,
        execution_config: ExecutionConfig,
        manual_event_risk: bool,
        plan_version_id: UUID | None,
        initial_lots: tuple[BacktestInitialLotInput, ...],
    ) -> None:
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        validation = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)
        if not validation.can_activate:
            raise BacktestBlockedError("PLAN_NOT_ACTIVATABLE")
        if type(initial_cash_fen) is not int or initial_cash_fen <= 0:
            raise ValueError("initial_cash_fen must be a positive integer")
        if not isinstance(execution_config, ExecutionConfig):
            raise TypeError("execution_config must be an ExecutionConfig")
        if type(manual_event_risk) is not bool:
            raise TypeError("manual_event_risk must be an explicit bool")
        _validate_plan_version_id(plan_version_id)
        if type(initial_lots) is not tuple or any(
            not isinstance(item, BacktestInitialLotInput) for item in initial_lots
        ):
            raise TypeError("initial_lots must be a tuple of BacktestInitialLotInput values")

    def _intraday_context(
        self,
        *,
        plan: TradePlan,
        plan_hash: str,
        trading_calendar: tuple[TradingDay, ...],
        daily_limit: DailyLimit,
        official_history: tuple[DailyBar, ...],
        current_minutes: tuple[MinuteBar, ...],
        five_minute_bars: tuple[FiveMinuteBar, ...],
        provisional: DailyBar,
        daily_indicator_prefix: _DailyTaV1Prefix,
        risk_state: RiskStateSnapshot,
        episode,
        engine: DeterministicExecutionEngine,
        manual_event_risk: bool,
        activation_origin: datetime,
        index_series: MarketIndexReplaySeries | None,
        index_requests: tuple,
    ) -> EvaluationContext:
        bucket_end = five_minute_bars[-1].bar_end
        evaluated_at = current_minutes[-1].received_at
        active, activated_at = _activation_at(plan, bucket_end.date(), activation_origin)
        reconciliation = reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=bucket_end.date(),
            daily_bars=(provisional,),
        )
        # The frozen reader, day guard, and aggregate constructors already validate
        # every value below; the public EvaluationContext constructor stays strict.
        return EvaluationContext.model_construct(
            evaluated_at=evaluated_at,
            target=IntradayEvaluationTarget(bucket_end=bucket_end),
            plan=plan,
            plan_hash=plan_hash,
            plan_active=active,
            activated_at=activated_at,
            current_day_minutes=current_minutes,
            complete_5m_bars=five_minute_bars,
            official_daily_bars=official_history,
            five_minute_indicators=calculate_ta_v1(five_minute_bars),
            daily_indicator_snapshot=DailyIndicatorSnapshot(
                series=_calculate_daily_ta_v1_from_prefix(
                    (*official_history, provisional),
                    daily_indicator_prefix,
                ),
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=bucket_end,
                source_bar=provisional,
            ),
            close_reconciliation=reconciliation,
            trading_calendar=trading_calendar,
            daily_limit=daily_limit,
            data_health=DataHealthSnapshot(
                symbol=plan.symbol,
                status=DataHealthStatus.LIVE,
                latest_bar_end=bucket_end,
                data_age_seconds=int((evaluated_at - bucket_end).total_seconds()),
                required_data_complete=True,
                fresh=True,
            ),
            positions=_position_lots(engine.open_lots),
            low_zone_episode=episode,
            risk_state=risk_state,
            manual_event_risk=manual_event_risk,
            reference_market_snapshot=(
                None
                if index_series is None
                else index_series.snapshot(
                    decision_cutoff=bucket_end,
                    requests=index_requests,
                    observed_no_later_than=evaluated_at,
                )
            ),
        )

    def _official_context(
        self,
        *,
        plan: TradePlan,
        plan_hash: str,
        trading_calendar: tuple[TradingDay, ...],
        daily_limit: DailyLimit,
        official_history: tuple[DailyBar, ...],
        current_minutes: tuple[MinuteBar, ...],
        five_minute_bars: tuple[FiveMinuteBar, ...],
        provisional: DailyBar,
        official: DailyBar,
        daily_indicator_prefix: _DailyTaV1Prefix,
        risk_state: RiskStateSnapshot,
        episode,
        engine: DeterministicExecutionEngine,
        manual_event_risk: bool,
        activation_origin: datetime,
        index_series: MarketIndexReplaySeries | None,
        index_requests: tuple,
    ) -> EvaluationContext:
        cutoff = datetime.combine(official.trade_date, time(15, 0), SHANGHAI)
        evaluated_at = official.received_at
        active, activated_at = _activation_at(plan, official.trade_date, activation_origin)
        reconciliation = reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=official.trade_date,
            daily_bars=(provisional, official),
        )
        # Preserve the same trusted replay handoff used by the intraday path.
        return EvaluationContext.model_construct(
            evaluated_at=evaluated_at,
            target=OfficialCloseEvaluationTarget(trade_date=official.trade_date),
            plan=plan,
            plan_hash=plan_hash,
            plan_active=active,
            activated_at=activated_at,
            current_day_minutes=current_minutes,
            complete_5m_bars=five_minute_bars,
            official_daily_bars=official_history,
            five_minute_indicators=calculate_ta_v1(five_minute_bars),
            daily_indicator_snapshot=DailyIndicatorSnapshot(
                series=_calculate_daily_ta_v1_from_prefix(
                    (*official_history, official),
                    daily_indicator_prefix,
                ),
                provenance=DailyIndicatorProvenance.OFFICIAL,
                source_as_of=cutoff,
                source_bar=official,
            ),
            close_reconciliation=reconciliation,
            trading_calendar=trading_calendar,
            daily_limit=daily_limit,
            data_health=DataHealthSnapshot(
                symbol=plan.symbol,
                status=DataHealthStatus.STALE,
                latest_bar_end=five_minute_bars[-1].bar_end,
                data_age_seconds=int((evaluated_at - five_minute_bars[-1].bar_end).total_seconds()),
                required_data_complete=True,
                fresh=False,
            ),
            positions=_position_lots(engine.open_lots),
            low_zone_episode=episode,
            risk_state=risk_state,
            manual_event_risk=manual_event_risk,
            reference_market_snapshot=(
                None
                if index_series is None
                else index_series.snapshot(
                    decision_cutoff=cutoff,
                    requests=index_requests,
                    observed_no_later_than=evaluated_at,
                )
            ),
        )

    def _evaluate_context(
        self,
        context: EvaluationContext,
        intern_pool: _ReplayInternPool,
    ) -> EvaluationResult:
        result = self._evaluator(context)
        if not isinstance(result, EvaluationResult):
            raise TypeError("evaluator must return an EvaluationResult")
        return intern_pool.result(result)

    @staticmethod
    def _validate_day_facts(
        trading_day: TradingDay,
        daily_limit: DailyLimit,
        minutes: tuple[MinuteBar, ...],
        official: DailyBar,
    ) -> None:
        if not trading_day.is_open:
            raise BacktestBlockedError(
                f"CLOSED_DAY_HAS_MARKET_DATA:{trading_day.cal_date.isoformat()}"
            )
        if not official.is_official:
            raise BacktestBlockedError(
                f"DAILY_BAR_NOT_OFFICIAL:{official.symbol}:{official.trade_date.isoformat()}"
            )
        cutoff = datetime.combine(official.trade_date, time(15, 0), SHANGHAI)
        if official.received_at < cutoff:
            raise BacktestBlockedError(
                f"OFFICIAL_DAILY_VISIBLE_TOO_EARLY:{official.symbol}:"
                f"{official.trade_date.isoformat()}"
            )
        if daily_limit.received_at > minutes[0].received_at:
            raise BacktestBlockedError(
                f"DAILY_LIMIT_VISIBLE_TOO_LATE:{daily_limit.symbol}:"
                f"{daily_limit.trade_date.isoformat()}"
            )


def _advance_state(result, episode, risk_state):
    next_episode = episode
    next_risk = risk_state
    for transition in result.transitions:
        if isinstance(transition, EpisodeTransitionIntent):
            next_episode = transition.episode
        elif isinstance(transition, RiskTransitionIntent):
            next_risk = transition.risk
    return next_episode, next_risk


def _position_lots(values: tuple[PositionLot, ...]) -> tuple[PositionLotSnapshot, ...]:
    return tuple(
        PositionLotSnapshot(
            lot_id=value.lot_id,
            symbol=value.symbol,
            bucket=value.bucket,
            quantity=value.original_quantity,
            remaining_quantity=value.remaining_quantity,
            acquired_trade_date=value.acquired_trade_date,
            cost_fen=max(1, value.cost_basis_fen // value.remaining_quantity),
        )
        for value in values
        if value.remaining_quantity > 0
    )


def _safe_event_id(value: DailyBar) -> str:
    """Identify the last fully consumed warm-up fact without retaining its payload."""

    return _stable_hash(
        value.model_dump(mode="python", round_trip=True),
        domain="backtest-safe-event-v1",
    )


def _activation_at(
    plan: TradePlan,
    trade_date: date,
    activation_origin: datetime,
) -> tuple[bool, datetime | None]:
    activation = plan.activation
    if activation.mode == "MANUAL":
        return True, activation_origin
    active = activation_is_eligible_on(activation, trade_date)
    if activation.mode == "TRADING_DAY":
        activated_at = datetime.combine(activation.trading_day, time(9, 0), SHANGHAI)
        return active, activated_at if active else None
    activated_at = datetime.combine(activation.start_date, time(9, 0), SHANGHAI)
    return active, activated_at if active else None


def _required_daily_warmup(plan: TradePlan) -> int:
    required = 1
    stack: list[object] = [plan.model_dump(mode="python")]
    indicator_periods = {"EMA10": 10, "MA20": 20, "MA50": 50, "MA200": 200, "BOLL_MIDDLE": 20}
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            condition_type = value.get("type")
            if condition_type == "MACD_HIST_IMPROVEMENT_GTE":
                required = max(required, 35)
            elif condition_type == "LOWER_BAND_HITS_LTE":
                required = max(required, 20)
            indicator = value.get("indicator")
            if isinstance(indicator, str):
                required = max(required, indicator_periods.get(indicator, 1))
            stack.extend(value.values())
        elif isinstance(value, tuple | list):
            stack.extend(value)
    return required


def backtest_run_id(
    *,
    plan: TradePlan,
    manifest: DatasetManifest,
    initial_cash_fen: int,
    execution_config: ExecutionConfig,
    manual_event_risk: bool,
    plan_version_id: UUID | None = None,
    initial_lots: tuple[BacktestInitialLotInput, ...] = (),
) -> str:
    """Return the exact v1/v2 identity selected by normalized initial-lot inputs."""

    return BacktestRunInput.create(
        plan=plan,
        manifest=manifest,
        initial_cash_fen=initial_cash_fen,
        initial_lots=initial_lots,
        execution_config=execution_config,
        manual_event_risk=manual_event_risk,
        plan_version_id=plan_version_id,
    ).run_id


def _validate_plan_version_id(plan_version_id: UUID | None) -> None:
    if plan_version_id is not None and not isinstance(plan_version_id, UUID):
        raise TypeError("plan_version_id must be a UUID or None")


def _metrics(
    *,
    initial_cash_fen: int,
    initial_equity_fen: int,
    engine: DeterministicExecutionEngine,
    decisions: tuple[EvaluationResult, ...],
    fills: tuple[ExecutionFill, ...],
    daily_equity: tuple[EquitySnapshot, ...],
) -> BacktestMetrics:
    final_equity = daily_equity[-1].equity_fen if daily_equity else initial_equity_fen
    peak = initial_equity_fen
    maximum_drawdown = Decimal("0")
    for snapshot in daily_equity:
        peak = max(peak, snapshot.equity_fen)
        drawdown = _metric_ratio(peak - snapshot.equity_fen, peak)
        maximum_drawdown = max(maximum_drawdown, drawdown)
    sell_fills = tuple(fill for fill in fills if fill.side.value == "SELL")
    winning_sells = sum(1 for fill in sell_fills if (fill.realized_pnl_fen or 0) > 0)
    blocked = sum(
        1
        for result in decisions
        if result.snapshot.signal_type in {SignalType.BLOCKED_DATA, SignalType.BLOCKED_RISK}
    )
    skipped = sum(
        1
        for result in decisions
        if result.snapshot.signal_type in {SignalType.WAIT, SignalType.LOW_ZONE_WATCH}
    )
    return BacktestMetrics(
        initial_cash_fen=initial_cash_fen,
        initial_equity_fen=initial_equity_fen,
        final_cash_fen=engine.cash_fen,
        final_equity_fen=final_equity,
        total_return=_metric_ratio(final_equity - initial_equity_fen, initial_equity_fen),
        maximum_drawdown=maximum_drawdown,
        trade_count=len(fills),
        winning_sell_count=winning_sells,
        win_rate=(_metric_ratio(winning_sells, len(sell_fills)) if sell_fills else Decimal("0")),
        turnover_fen=sum(fill.notional_fen for fill in fills),
        total_cost_fen=engine.total_cost_fen,
        realized_pnl_fen=engine.realized_pnl_fen,
        unrealized_pnl_fen=(daily_equity[-1].unrealized_pnl_fen if daily_equity else 0),
        blocked_count=blocked,
        skipped_count=skipped,
    )


def _metric_ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        raise ValueError("metric ratio denominator must be positive")
    with localcontext(_METRIC_DECIMAL_CONTEXT):
        return Decimal(numerator) / Decimal(denominator)


def _canonical_json(value: object) -> str:
    return canonical_json(value)


def _stable_hash(value: object, *, domain: str) -> str:
    return sha256((domain + "\0" + _canonical_json(value)).encode("utf-8")).hexdigest()


def _stable_model_hash(
    value: BaseModel,
    *,
    domain: str,
    exclude_fields: frozenset[str] = frozenset(),
) -> str:
    """Hash canonical model JSON without materializing a second complete tree."""

    digest = sha256((domain + "\0").encode("utf-8"))
    digest.update(b"{")
    field_names = tuple(
        name for name in sorted(type(value).model_fields) if name not in exclude_fields
    )
    for index, name in enumerate(field_names):
        if index:
            digest.update(b",")
        digest.update(json.dumps(name, ensure_ascii=False).encode("utf-8"))
        digest.update(b":")
        for fragment in _iter_stable_json(getattr(value, name)):
            digest.update(fragment.encode("utf-8"))
    digest.update(b"}")
    return digest.hexdigest()


def _iter_stable_json(value: object) -> Iterator[str]:
    if isinstance(value, BaseModel):
        yield json.dumps(
            value.model_dump(mode="python", round_trip=True),
            default=_canonical_json_default,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("canonical model mapping keys must be strings")
        yield "{"
        for index, key in enumerate(sorted(value)):
            if index:
                yield ","
            yield json.dumps(key, ensure_ascii=False)
            yield ":"
            yield from _iter_stable_json(value[key])
        yield "}"
        return
    if isinstance(value, tuple | list):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _iter_stable_json(item)
        yield "]"
        return
    if isinstance(value, Decimal | datetime | date | Enum):
        value = _canonical_json_default(value)
    yield json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _canonical_json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical datetimes must be timezone-aware")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _reclaim_replay_temporaries() -> None:
    """Collect unreachable replay temporaries at a bounded safe day boundary."""

    gc.collect()


__all__ = [
    "BacktestBlockedError",
    "BacktestMetrics",
    "BacktestRunReport",
    "OfflineBacktestRunner",
    "RUN_FORMULA_VERSION",
    "backtest_run_id",
]
