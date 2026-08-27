"""Deterministic event-time replay over one frozen local market dataset."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import DatasetManifest, exchange_for_symbol
from trade_plan_monitor.backtest.execution import DeterministicExecutionEngine
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
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
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationResult,
    IntradayEvaluationTarget,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    SignalType,
)
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    validate_trade_plan,
)
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    aggregate_provisional_daily_bar,
)
from trade_plan_monitor.market_data.indicators import calculate_ta_v1
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close

SHANGHAI = ZoneInfo("Asia/Shanghai")
RUN_FORMULA_VERSION = RUN_FORMULA_V1
_REPORT_SCHEMA_VERSION = "backtest-report-v1"
_FIVE_MINUTE_CONTEXT_BARS = FIVE_MINUTE_CONTEXT_BARS
_DAILY_CONTEXT_BARS = DAILY_CONTEXT_BARS
_CALENDAR_CONTEXT_DAYS = CALENDAR_CONTEXT_DAYS
_METRIC_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
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
    schema_version: Literal["backtest-report-v1"] = _REPORT_SCHEMA_VERSION
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


class BacktestRunReport(_BacktestRunReportPayload):
    """Complete stable MVP report returned before isolated result persistence."""

    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values: object) -> Self:
        if "report_hash" in values:
            raise TypeError("build computes report_hash")
        payload = _BacktestRunReportPayload.model_validate(values)
        digest = _stable_hash(
            payload.model_dump(mode="python", round_trip=True),
            domain="backtest-report-v1",
        )
        return cls.model_validate(
            {**payload.model_dump(mode="python", round_trip=True), "report_hash": digest}
        )

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="python", round_trip=True))

    @model_validator(mode="after")
    def validate_report_hash(self) -> Self:
        expected = _stable_hash(
            self.model_dump(
                mode="python",
                round_trip=True,
                exclude={"report_hash"},
            ),
            domain="backtest-report-v1",
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
        market_store: BacktestMarketStore,
        *,
        evaluator: Evaluator = evaluate,
    ) -> None:
        if not isinstance(market_store, BacktestMarketStore):
            raise TypeError("market_store must be a BacktestMarketStore")
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        self._store = market_store
        self._evaluator = evaluator

    def run(
        self,
        *,
        plan: TradePlan,
        dataset_hash: str,
        initial_cash_fen: int,
        execution_config: ExecutionConfig,
        manual_event_risk: bool,
        plan_version_id: UUID | None = None,
        initial_lots: tuple[BacktestInitialLotInput, ...] = (),
    ) -> BacktestRunReport:
        """Run a finite offline replay; no provider, scheduler, or notification is reachable."""

        self._validate_request(
            plan=plan,
            initial_cash_fen=initial_cash_fen,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
            plan_version_id=plan_version_id,
            initial_lots=initial_lots,
        )
        manifest = self._store.dataset_manifest(dataset_hash)
        scope = manifest.scope
        if plan.symbol not in scope.symbols:
            raise BacktestBlockedError(f"PLAN_SYMBOL_NOT_IN_DATASET:{plan.symbol}")
        run_input = BacktestRunInput.create(
            plan=plan,
            manifest=manifest,
            initial_cash_fen=initial_cash_fen,
            initial_lots=initial_lots,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
            plan_version_id=plan_version_id,
        )
        position_lots = run_input.derive_position_lots()
        plan_hash = run_input.plan_sha256
        exchange = exchange_for_symbol(plan.symbol)
        frozen_calendar = self._store.dataset_trading_days(dataset_hash, exchange)
        calendar_by_date = {value.cal_date: value for value in frozen_calendar}
        frozen_daily = self._store.dataset_daily_bars(dataset_hash, plan.symbol)
        daily_by_date = {value.trade_date: value for value in frozen_daily}
        official_history = [value for value in frozen_daily if value.trade_date < scope.start]
        required_warmup = _required_daily_warmup(plan)
        if len(official_history) < required_warmup:
            raise BacktestBlockedError(
                f"INSUFFICIENT_DAILY_WARMUP:{len(official_history)}:{required_warmup}"
            )
        initial_equity_fen = initial_cash_fen + sum(
            lot.remaining_quantity * official_history[-1].close_fen for lot in position_lots
        )

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
        risk_state = RiskStateSnapshot(
            symbol=plan.symbol,
            plan_hash=plan_hash,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=official_history[-1].close_fen,
            revision=0,
            updated_at=activation_origin,
        )
        episode = None
        decisions: list[EvaluationResult] = []
        signals: list[ExecutionSignal] = []
        orders: list[ExecutionOrder] = []
        fills: list[ExecutionFill] = []
        outcomes: list[ExecutionOutcome] = []
        daily_equity: list[EquitySnapshot] = []
        complete_five_minute_bars: list[FiveMinuteBar] = []

        open_dates = tuple(
            value.cal_date
            for value in frozen_calendar
            if scope.start <= value.cal_date <= scope.end and value.is_open
        )
        if not open_dates:
            raise BacktestBlockedError("NO_OPEN_TRADING_DAYS")
        for trade_date in open_dates:
            trading_calendar = tuple(
                value for value in frozen_calendar if value.cal_date <= trade_date
            )[-_CALENDAR_CONTEXT_DAYS:]
            trading_day = calendar_by_date[trade_date]
            daily_limit = self._store.dataset_daily_limit(
                dataset_hash,
                plan.symbol,
                trade_date,
            )
            minutes = self._store.dataset_minutes(dataset_hash, plan.symbol, trade_date)
            official_bar = daily_by_date[trade_date]
            self._validate_day_facts(trading_day, daily_limit, minutes, official_bar)
            day_minutes: list[MinuteBar] = []
            provisional: DailyBar | None = None

            for minute_index, minute in enumerate(minutes, start=1):
                execution_batch = engine.process_bar(
                    ExecutionBar.create(
                        symbol=minute.symbol,
                        bar_end=minute.bar_end,
                        open_fen=minute.open_fen,
                        high_fen=minute.high_fen,
                        low_fen=minute.low_fen,
                        close_fen=minute.close_fen,
                        volume_shares=minute.volume_shares,
                        is_tradable=minute.volume_shares > 0,
                    ),
                    daily_limit,
                )
                fills.extend(execution_batch.fills)
                outcomes.extend(execution_batch.outcomes)
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
                    trading_calendar=trading_calendar,
                    daily_limit=daily_limit,
                    official_history=tuple(official_history[-_DAILY_CONTEXT_BARS:]),
                    current_minutes=tuple(day_minutes),
                    five_minute_bars=tuple(complete_five_minute_bars[-_FIVE_MINUTE_CONTEXT_BARS:]),
                    provisional=provisional,
                    risk_state=risk_state,
                    episode=episode,
                    engine=engine,
                    manual_event_risk=manual_event_risk,
                    activation_origin=activation_origin,
                )
                result = self._evaluate_context(context)
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

            if provisional is None:
                raise BacktestBlockedError(
                    f"MISSING_COMPLETE_DAY:{plan.symbol}:{trade_date.isoformat()}"
                )
            official_context = self._official_context(
                plan=plan,
                plan_hash=plan_hash,
                trading_calendar=trading_calendar,
                daily_limit=daily_limit,
                official_history=tuple(official_history[-_DAILY_CONTEXT_BARS:]),
                current_minutes=tuple(day_minutes),
                five_minute_bars=tuple(complete_five_minute_bars[-_FIVE_MINUTE_CONTEXT_BARS:]),
                provisional=provisional,
                official=official_bar,
                risk_state=risk_state,
                episode=episode,
                engine=engine,
                manual_event_risk=manual_event_risk,
                activation_origin=activation_origin,
            )
            official_result = self._evaluate_context(official_context)
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
            daily_equity.append(
                engine.equity_snapshot(
                    at=official_bar.received_at,
                    mark_price_fen=official_bar.close_fen,
                )
            )
            official_history.append(official_bar)

        replay_boundary = max(decision.snapshot.evaluated_at for decision in decisions)
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
        return BacktestRunReport.build(
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
        risk_state: RiskStateSnapshot,
        episode,
        engine: DeterministicExecutionEngine,
        manual_event_risk: bool,
        activation_origin: datetime,
    ) -> EvaluationContext:
        bucket_end = five_minute_bars[-1].bar_end
        evaluated_at = current_minutes[-1].received_at
        active, activated_at = _activation_at(plan, bucket_end.date(), activation_origin)
        reconciliation = reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=bucket_end.date(),
            daily_bars=(provisional,),
        )
        return EvaluationContext(
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
                series=calculate_ta_v1((*official_history, provisional)),
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
        risk_state: RiskStateSnapshot,
        episode,
        engine: DeterministicExecutionEngine,
        manual_event_risk: bool,
        activation_origin: datetime,
    ) -> EvaluationContext:
        cutoff = datetime.combine(official.trade_date, time(15, 0), SHANGHAI)
        evaluated_at = official.received_at
        active, activated_at = _activation_at(plan, official.trade_date, activation_origin)
        reconciliation = reconcile_daily_close(
            symbol=plan.symbol,
            current_trade_date=official.trade_date,
            daily_bars=(provisional, official),
        )
        return EvaluationContext(
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
                series=calculate_ta_v1((*official_history, official)),
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
        )

    def _evaluate_context(self, context: EvaluationContext) -> EvaluationResult:
        result = self._evaluator(context)
        if not isinstance(result, EvaluationResult):
            raise TypeError("evaluator must return an EvaluationResult")
        return result

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


def _activation_at(
    plan: TradePlan,
    trade_date: date,
    activation_origin: datetime,
) -> tuple[bool, datetime | None]:
    activation = plan.activation
    if activation.mode == "MANUAL":
        return True, activation_origin
    if activation.mode == "TRADING_DAY":
        active = trade_date == activation.trading_day
        activated_at = datetime.combine(activation.trading_day, time(9, 0), SHANGHAI)
        return active, activated_at if active else None
    active = activation.start_date <= trade_date <= activation.end_date
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


__all__ = [
    "BacktestBlockedError",
    "BacktestMetrics",
    "BacktestRunReport",
    "OfflineBacktestRunner",
    "RUN_FORMULA_VERSION",
    "backtest_run_id",
]
