"""Deterministic intraday/official evaluation and committed-event publication."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from inspect import isawaitable
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationResult,
    IntradayEvaluationIdentity,
    IntradayEvaluationTarget,
    OfficialCloseEvaluationIdentity,
    OfficialCloseEvaluationTarget,
    RiskTransitionIntent,
    SignalType,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    aggregate_provisional_daily_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.indicators import calculate_ta_v1
from trade_plan_monitor.market_data.models import (
    DailyBar,
    MinuteBar,
    ProviderCapabilities,
    ProviderCapabilityStatus,
    ShanghaiDatetime,
)
from trade_plan_monitor.market_data.reconciliation import (
    CloseReconciliationIntent,
    CloseReconciliationStatus,
    reconcile_daily_close,
)
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertEvent, build_alert_payload
from trade_plan_monitor.runtime.clock import Clock, SystemClock, _canonical_shanghai
from trade_plan_monitor.runtime.health import (
    RuntimeHealthDetails,
    RuntimeHealthSnapshot,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.scheduler import MarketDeadline
from trade_plan_monitor.state.events import (
    MonitorEvent,
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import EvaluationKind, SymbolHealthStatus
from trade_plan_monitor.state.repositories import (
    EpisodeIdentityConflictError,
    EpisodeNotFoundError,
    FiveMinuteBarRecord,
)
from trade_plan_monitor.state.unit_of_work import UnitOfWork

_MAX_FETCHED_MINUTES = 1_000
_MAX_CURRENT_DAY_MINUTES = 240
_MAX_CURRENT_DAY_BUCKETS = _MAX_CURRENT_DAY_MINUTES // 5
_MAX_OFFICIAL_DAILY_BARS = 10_000
_CLOSE_PENDING_DATE_KEY = "closePendingTradeDate"
_CLOSE_PENDING_RESUME_KEY = "resume"
_INVALID_JSON = object()
_SHANGHAI_DATETIME = TypeAdapter(ShanghaiDatetime)
_OFFICIAL_RISK_SIGNAL_TYPES = frozenset(
    {
        SignalType.RISK_BREACH,
        SignalType.RISK_RECOVERED,
        SignalType.RISK_EXIT_READY,
        SignalType.RISK_EXIT_PENDING_SETTLEMENT,
    }
)

FetchMinutes = Callable[[str, datetime], Awaitable[list[MinuteBar] | tuple[MinuteBar, ...]]]
FetchOfficialDaily = Callable[
    [str, date, int],
    Awaitable[list[DailyBar] | tuple[DailyBar, ...]],
]
UnitOfWorkFactory = Callable[[], UnitOfWork]
ContextBuilder = Callable[[TradePlan, "IntradayMarketFacts"], EvaluationContext]
OfficialContextBuilder = Callable[[TradePlan, "OfficialCloseMarketFacts"], EvaluationContext]
OfficialObservedAt = Callable[[datetime], datetime]
Evaluator = Callable[[EvaluationContext], EvaluationResult]
CommittedEventPublisher = Callable[[MonitorEvent], object]
EventIdFactory = Callable[[], UUID]


class _RuntimeValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class IntradayMarketFacts(_RuntimeValue):
    """Exact persisted market facts supplied to immutable context assembly."""

    symbol: str
    bucket_end: ShanghaiDatetime
    evaluated_at: ShanghaiDatetime
    formula_version: str
    current_day_minutes: tuple[MinuteBar, ...] = Field(
        min_length=5,
        max_length=_MAX_CURRENT_DAY_MINUTES,
    )
    complete_five_minute_bars: tuple[FiveMinuteBar, ...] = Field(
        min_length=1,
        max_length=_MAX_CURRENT_DAY_BUCKETS,
    )
    provisional_daily_bar: DailyBar
    source_as_of: ShanghaiDatetime
    provenance: DailyIndicatorProvenance = DailyIndicatorProvenance.PROVISIONAL

    @model_validator(mode="after")
    def validate_exact_source(self) -> Self:
        if self.source_as_of != self.bucket_end:
            raise ValueError("provisional source_as_of must match the intraday bucket")
        if self.evaluated_at < self.bucket_end:
            raise ValueError("evaluation time cannot precede the intraday bucket")
        if self.provenance is not DailyIndicatorProvenance.PROVISIONAL:
            raise ValueError("intraday market facts require PROVISIONAL provenance")
        if self.provisional_daily_bar.is_official:
            raise ValueError("intraday market facts cannot contain an official daily bar")
        expected_daily = aggregate_provisional_daily_bar(
            current_day_minutes=self.current_day_minutes,
            source_as_of=self.source_as_of,
        )
        if expected_daily is None or expected_daily != self.provisional_daily_bar:
            raise ValueError("provisional daily bar must match the exact minute slice")
        if any(minute.received_at > self.evaluated_at for minute in self.current_day_minutes):
            raise ValueError("current-day minutes cannot be received after evaluation")
        if len(self.current_day_minutes) != len(self.complete_five_minute_bars) * 5:
            raise ValueError("every current-day minute bucket must have one complete bar")
        for index, bar in enumerate(self.complete_five_minute_bars):
            group = self.current_day_minutes[index * 5 : (index + 1) * 5]
            expected_bar = aggregate_five_minute_bar(
                group,
                bucket_end=group[-1].bar_end,
                is_open=True,
            )
            if expected_bar != bar:
                raise ValueError("complete bars must match the exact current-day minutes")
        if self.complete_five_minute_bars[-1].bar_end != self.bucket_end:
            raise ValueError("latest complete bar must match the intraday bucket")
        if any(
            bar.symbol != self.symbol or bar.formula_version != self.formula_version
            for bar in self.complete_five_minute_bars
        ):
            raise ValueError("complete bars must match runtime identity")
        return self


class IntradayCycleStatus(StrEnum):
    """Stable outcome of one requested intraday target."""

    INCOMPLETE = "INCOMPLETE"
    DUPLICATE = "DUPLICATE"
    COMMITTED = "COMMITTED"


class IntradayCycleResult(_RuntimeValue):
    """Immutable outcome for persistence, evaluation claim, and publication."""

    status: IntradayCycleStatus
    facts: IntradayMarketFacts | None
    evaluation_result: EvaluationResult | None
    claim_created: bool = Field(strict=True)
    committed_event: AlertEvent | None

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        if self.status is IntradayCycleStatus.INCOMPLETE:
            if (
                any(
                    value is not None
                    for value in (self.facts, self.evaluation_result, self.committed_event)
                )
                or self.claim_created
            ):
                raise ValueError("incomplete cycles cannot contain evaluated facts")
        elif self.facts is None or self.evaluation_result is None:
            raise ValueError("evaluated cycles require market facts and a decision result")
        elif self.status is IntradayCycleStatus.DUPLICATE:
            if self.claim_created or self.committed_event is not None:
                raise ValueError("duplicate cycles cannot create or publish an event")
        elif not self.claim_created:
            raise ValueError("committed cycles require a new evaluation claim")
        return self


class OfficialCloseErrorCode(StrEnum):
    """Sanitized reason why an official-close target did not evaluate."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    FETCH_FAILED = "FETCH_FAILED"
    EARLIER_CLOSE_PENDING = "EARLIER_CLOSE_PENDING"


class OfficialCloseMarketFacts(_RuntimeValue):
    """Exact reconciled official facts supplied to one immutable close context."""

    symbol: str
    trade_date: date
    evaluated_at: ShanghaiDatetime
    close_attempt: int = Field(strict=True, ge=1)
    formula_version: str
    official_daily_bars: tuple[DailyBar, ...] = Field(
        default=(),
        max_length=_MAX_OFFICIAL_DAILY_BARS,
    )
    close_reconciliation: CloseReconciliationIntent
    daily_indicator_snapshot: DailyIndicatorSnapshot
    source_as_of: ShanghaiDatetime
    provenance: DailyIndicatorProvenance = DailyIndicatorProvenance.OFFICIAL

    @model_validator(mode="after")
    def validate_official_source(self) -> Self:
        if isinstance(self.trade_date, datetime):
            raise ValueError("official trade_date must be a calendar date")
        expected_source = datetime.combine(self.trade_date, time(15, 0), self.evaluated_at.tzinfo)
        if self.source_as_of != expected_source or self.source_as_of > self.evaluated_at:
            raise ValueError("official source_as_of must be the elapsed 15:00 cutoff")
        if self.provenance is not DailyIndicatorProvenance.OFFICIAL:
            raise ValueError("official-close facts require OFFICIAL provenance")
        reconciliation = self.close_reconciliation
        if (
            reconciliation.symbol != self.symbol
            or reconciliation.trade_date != self.trade_date
            or reconciliation.status is not CloseReconciliationStatus.OFFICIAL_READY
            or not reconciliation.advance_close_risk
            or reconciliation.official_bar is None
        ):
            raise ValueError("official-close facts require matching ready reconciliation")
        official_bar = reconciliation.official_bar
        if official_bar.received_at > self.evaluated_at:
            raise ValueError("official daily bar cannot be received after evaluation")
        if any(
            not bar.is_official
            or bar.symbol != self.symbol
            or bar.trade_date >= self.trade_date
            or bar.received_at > self.evaluated_at
            for bar in self.official_daily_bars
        ):
            raise ValueError("official daily history must strictly precede the target")
        history_dates = tuple(bar.trade_date for bar in self.official_daily_bars)
        if history_dates != tuple(sorted(set(history_dates))):
            raise ValueError("official daily history must be unique and strictly ordered")
        snapshot = self.daily_indicator_snapshot
        if (
            snapshot.provenance is not self.provenance
            or snapshot.source_as_of != self.source_as_of
            or snapshot.source_bar != official_bar
            or snapshot.series != calculate_ta_v1((*self.official_daily_bars, official_bar))
        ):
            raise ValueError("official indicators must be recomputed from exact official history")
        return self


class OfficialCloseCycleStatus(StrEnum):
    """Stable outcome of one requested official-close attempt."""

    CLOSE_PENDING = "CLOSE_PENDING"
    BLOCKED_PENDING = "BLOCKED_PENDING"
    DUPLICATE = "DUPLICATE"
    COMMITTED = "COMMITTED"


class OfficialCloseCycleResult(_RuntimeValue):
    """Immutable reconciliation, evaluation, and publication outcome."""

    status: OfficialCloseCycleStatus
    trade_date: date
    close_attempt: int = Field(strict=True, ge=1)
    pending_trade_date: date | None
    close_reconciliation: CloseReconciliationIntent | None
    facts: OfficialCloseMarketFacts | None
    evaluation_result: EvaluationResult | None
    claim_created: bool = Field(strict=True)
    committed_event: AlertEvent | None
    error_code: OfficialCloseErrorCode | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        if isinstance(self.trade_date, datetime) or isinstance(self.pending_trade_date, datetime):
            raise ValueError("close result dates must be calendar dates")
        reconciliation = self.close_reconciliation
        pending_status = self.status in {
            OfficialCloseCycleStatus.CLOSE_PENDING,
            OfficialCloseCycleStatus.BLOCKED_PENDING,
        }
        if pending_status:
            if (
                reconciliation is None
                or reconciliation.trade_date != self.trade_date
                or any(
                    value is not None
                    for value in (self.facts, self.evaluation_result, self.committed_event)
                )
                or self.claim_created
            ):
                raise ValueError("pending close results cannot contain evaluated facts")
            if self.error_code is None or self.pending_trade_date is None:
                raise ValueError("pending close results require a sanitized reason and date")
            if self.status is OfficialCloseCycleStatus.CLOSE_PENDING:
                if self.pending_trade_date != self.trade_date:
                    raise ValueError("CLOSE_PENDING must identify its requested date")
            elif self.pending_trade_date >= self.trade_date:
                raise ValueError("blocked close requires an earlier unresolved date")
            return self
        if (
            self.status is OfficialCloseCycleStatus.DUPLICATE
            and reconciliation is None
            and self.facts is None
            and self.evaluation_result is None
        ):
            if (
                self.pending_trade_date is not None
                or self.error_code is not None
                or self.claim_created
                or self.committed_event is not None
            ):
                raise ValueError("completed duplicate results contain only their identity")
            return self
        if reconciliation is None or reconciliation.trade_date != self.trade_date:
            raise ValueError("evaluated close result reconciliation must match its target")
        if self.pending_trade_date is not None or self.error_code is not None:
            raise ValueError("evaluated close results cannot retain a pending reason")
        if self.facts is None or self.evaluation_result is None:
            raise ValueError("evaluated close results require official facts and a decision")
        if self.close_reconciliation != self.facts.close_reconciliation:
            raise ValueError("evaluated close result must retain exact reconciliation")
        if self.status is OfficialCloseCycleStatus.DUPLICATE:
            if self.claim_created or self.committed_event is not None:
                raise ValueError("duplicate close results cannot create or publish an event")
        elif not self.claim_created:
            raise ValueError("committed close results require a new evaluation claim")
        return self


class RuntimeEvaluationService:
    """Persist exact market facts, evaluate purely, then apply results atomically."""

    def __init__(
        self,
        *,
        fetch_minutes: FetchMinutes,
        fetch_official_daily: FetchOfficialDaily | None = None,
        official_observed_at: OfficialObservedAt | None = None,
        unit_of_work_factory: UnitOfWorkFactory,
        context_builder: ContextBuilder,
        official_context_builder: OfficialContextBuilder | None = None,
        committed_event_publisher: CommittedEventPublisher,
        evaluator: Evaluator = evaluate,
        event_id_factory: EventIdFactory = uuid4,
    ) -> None:
        dependencies = (
            fetch_minutes,
            unit_of_work_factory,
            context_builder,
            committed_event_publisher,
            evaluator,
            event_id_factory,
        )
        if any(not callable(dependency) for dependency in dependencies):
            raise TypeError("runtime evaluation dependencies must be callable")
        if (fetch_official_daily is None) != (official_context_builder is None):
            raise TypeError("official fetch and context builder must be configured together")
        if official_observed_at is not None and not callable(official_observed_at):
            raise TypeError("official_observed_at must be callable")
        system_clock = SystemClock()
        self._fetch_minutes = fetch_minutes
        self._fetch_official_daily = fetch_official_daily
        self._official_observed_at = official_observed_at or (
            lambda requested_at: max(requested_at, system_clock.now())
        )
        self._unit_of_work_factory = unit_of_work_factory
        self._context_builder = context_builder
        self._official_context_builder = official_context_builder
        self._publisher = committed_event_publisher
        self._evaluator = evaluator
        self._event_id_factory = event_id_factory
        self._official_serial = asyncio.Lock()

    async def run_intraday(
        self,
        *,
        plan: TradePlan,
        bucket_end: datetime,
        evaluated_at: datetime,
    ) -> IntradayCycleResult:
        """Run one intraday target without provider or publisher work in a transaction."""

        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        canonical_bucket = expected_five_minute_ends(bucket_end)[-1]
        canonical_evaluated_at = _SHANGHAI_DATETIME.validate_python(
            evaluated_at,
            strict=True,
        )
        if canonical_evaluated_at < canonical_bucket:
            raise ValueError("evaluated_at cannot precede bucket_end")

        fetched = await self._fetch_minutes(plan.symbol, canonical_bucket)
        incoming = self._validated_fetch(
            fetched,
            symbol=plan.symbol,
            bucket_end=canonical_bucket,
        )
        persisted = self._persist_market_context(
            plan=plan,
            bucket_end=canonical_bucket,
            incoming=incoming,
        )
        if persisted is None:
            return IntradayCycleResult(
                status=IntradayCycleStatus.INCOMPLETE,
                facts=None,
                evaluation_result=None,
                claim_created=False,
                committed_event=None,
            )

        current_day_minutes, complete_bars, provisional = persisted
        facts = IntradayMarketFacts(
            symbol=plan.symbol,
            bucket_end=canonical_bucket,
            evaluated_at=canonical_evaluated_at,
            formula_version=plan.monitoring.indicator_formula_version,
            current_day_minutes=current_day_minutes,
            complete_five_minute_bars=complete_bars,
            provisional_daily_bar=provisional,
            source_as_of=canonical_bucket,
            provenance=DailyIndicatorProvenance.PROVISIONAL,
        )
        context = self._context_builder(plan, facts)
        self._validate_context(plan=plan, facts=facts, context=context)
        result = self._evaluator(context)
        self._validate_result(plan=plan, facts=facts, result=result)

        committed_event: AlertEvent | None = None
        publication_event: MonitorEvent | None = None
        with self._unit_of_work_factory() as unit_of_work:
            identity = result.evaluation_identity
            claim = unit_of_work.evaluations.claim(
                plan_hash=identity.plan_hash,
                symbol=identity.symbol,
                evaluation_kind=EvaluationKind.INTRADAY,
                bucket_end=identity.bucket_end,
                official_trade_date=None,
                formula_version=identity.formula_version,
                result_hash=result.result_hash,
                evaluated_at=result.snapshot.evaluated_at,
            )
            if claim.created:
                publication_event = self._append_snapshot_event(unit_of_work, result)
                self._apply_transitions(unit_of_work, result)
                if result.signal_intent is not None:
                    dedup_key = alert_dedup_key(result.signal_intent)
                    if not unit_of_work.alerts.has_dedup_key(dedup_key):
                        event_id = self._event_id_factory()
                        if type(event_id) is not UUID:
                            raise TypeError("event_id_factory must return a UUID")
                        payload = build_alert_payload(
                            event_id=event_id,
                            plan=plan,
                            result=result,
                        )
                        committed_event = unit_of_work.alerts.enqueue(payload)
                        publication_event = unit_of_work.events.get(payload.event_id)
            unit_of_work.commit()

        if not claim.created:
            return IntradayCycleResult(
                status=IntradayCycleStatus.DUPLICATE,
                facts=facts,
                evaluation_result=result,
                claim_created=False,
                committed_event=None,
            )
        if publication_event is not None:
            publication = self._publisher(publication_event)
            if isawaitable(publication):
                await publication
        return IntradayCycleResult(
            status=IntradayCycleStatus.COMMITTED,
            facts=facts,
            evaluation_result=result,
            claim_created=True,
            committed_event=committed_event,
        )

    def pending_close_date(self, symbol: str) -> date | None:
        """Return one validated durable close-pending date for startup recovery."""

        with self._unit_of_work_factory() as unit_of_work:
            health = unit_of_work.health.get_symbol(symbol)
        if health is None or health.status is not SymbolHealthStatus.CLOSE_PENDING:
            return None
        pending_date, _resume = _close_pending_payload(health.gap_json)
        return pending_date

    async def run_official_close(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        close_attempt: int,
    ) -> OfficialCloseCycleResult:
        """Reconcile one official date without provider or publisher I/O in a transaction."""

        async with self._official_serial:
            return await self._run_official_close_unlocked(
                plan=plan,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                close_attempt=close_attempt,
            )

    async def _run_official_close_unlocked(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        close_attempt: int,
    ) -> OfficialCloseCycleResult:
        """Own the serialized official-close workflow for one runtime instance."""

        if self._fetch_official_daily is None or self._official_context_builder is None:
            raise RuntimeError("official-close evaluation is not configured")
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        if type(close_attempt) is not int or close_attempt < 1:
            raise ValueError("close_attempt must be a positive integer")
        canonical_evaluated_at = _SHANGHAI_DATETIME.validate_python(
            evaluated_at,
            strict=True,
        )
        source_as_of = datetime.combine(
            trade_date,
            time(15, 0),
            canonical_evaluated_at.tzinfo,
        )
        if canonical_evaluated_at < source_as_of:
            raise ValueError("official close cannot be evaluated before the 15:00 cutoff")

        pending_date = self.pending_close_date(plan.symbol)
        if pending_date is not None and pending_date > trade_date:
            raise ValueError("persisted CLOSE_PENDING date cannot follow the requested target")
        if pending_date is not None and pending_date < trade_date:
            reconciliation = reconcile_daily_close(
                symbol=plan.symbol,
                current_trade_date=trade_date,
                daily_bars=(),
            )
            return OfficialCloseCycleResult(
                status=OfficialCloseCycleStatus.BLOCKED_PENDING,
                trade_date=trade_date,
                close_attempt=close_attempt,
                pending_trade_date=pending_date,
                close_reconciliation=reconciliation,
                facts=None,
                evaluation_result=None,
                claim_created=False,
                committed_event=None,
                error_code=OfficialCloseErrorCode.EARLIER_CLOSE_PENDING,
            )
        if self._official_close_completed(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=canonical_evaluated_at,
        ):
            return OfficialCloseCycleResult(
                status=OfficialCloseCycleStatus.DUPLICATE,
                trade_date=trade_date,
                close_attempt=close_attempt,
                pending_trade_date=None,
                close_reconciliation=None,
                facts=None,
                evaluation_result=None,
                claim_created=False,
                committed_event=None,
                error_code=None,
            )

        fetch_error: OfficialCloseErrorCode | None = None
        try:
            fetched = await self._fetch_official_daily(
                plan.symbol,
                trade_date,
                close_attempt,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            fetched = ()
            fetch_error = OfficialCloseErrorCode.FETCH_FAILED
        observed_at = _SHANGHAI_DATETIME.validate_python(
            self._official_observed_at(canonical_evaluated_at),
            strict=True,
        )
        if observed_at < canonical_evaluated_at:
            raise ValueError("official observation cannot precede its requested evaluation time")
        canonical_evaluated_at = observed_at
        incoming, validation_error = self._validated_official_fetch(
            fetched,
            symbol=plan.symbol,
            trade_date=trade_date,
            evaluated_at=canonical_evaluated_at,
        )
        if fetch_error is None:
            fetch_error = validation_error

        persisted = self._persist_official_market_context(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=canonical_evaluated_at,
            source_as_of=source_as_of,
            incoming=incoming,
        )
        reconciliation, official_history = persisted
        if not reconciliation.advance_close_risk or reconciliation.official_bar is None:
            return OfficialCloseCycleResult(
                status=OfficialCloseCycleStatus.CLOSE_PENDING,
                trade_date=trade_date,
                close_attempt=close_attempt,
                pending_trade_date=trade_date,
                close_reconciliation=reconciliation,
                facts=None,
                evaluation_result=None,
                claim_created=False,
                committed_event=None,
                error_code=fetch_error or OfficialCloseErrorCode.NOT_AVAILABLE,
            )

        official_bar = reconciliation.official_bar
        indicator_snapshot = DailyIndicatorSnapshot(
            series=calculate_ta_v1((*official_history, official_bar)),
            provenance=DailyIndicatorProvenance.OFFICIAL,
            source_as_of=source_as_of,
            source_bar=official_bar,
        )
        facts = OfficialCloseMarketFacts(
            symbol=plan.symbol,
            trade_date=trade_date,
            evaluated_at=canonical_evaluated_at,
            close_attempt=close_attempt,
            formula_version=plan.monitoring.indicator_formula_version,
            official_daily_bars=official_history,
            close_reconciliation=reconciliation,
            daily_indicator_snapshot=indicator_snapshot,
            source_as_of=source_as_of,
            provenance=DailyIndicatorProvenance.OFFICIAL,
        )
        context = self._official_context_builder(plan, facts)
        self._validate_official_context(plan=plan, facts=facts, context=context)
        result = self._evaluator(context)
        self._validate_official_result(plan=plan, facts=facts, result=result)

        committed_event: AlertEvent | None = None
        publication_event: MonitorEvent | None = None
        with self._unit_of_work_factory() as unit_of_work:
            identity = result.evaluation_identity
            claim = unit_of_work.evaluations.claim(
                plan_hash=identity.plan_hash,
                symbol=identity.symbol,
                evaluation_kind=EvaluationKind.OFFICIAL_CLOSE,
                bucket_end=None,
                official_trade_date=identity.official_trade_date,
                formula_version=identity.formula_version,
                result_hash=result.result_hash,
                evaluated_at=result.snapshot.evaluated_at,
            )
            if claim.created:
                publication_event = self._append_snapshot_event(unit_of_work, result)
                self._apply_transitions(unit_of_work, result)
                if result.signal_intent is not None:
                    dedup_key = alert_dedup_key(result.signal_intent)
                    if not unit_of_work.alerts.has_dedup_key(dedup_key):
                        event_id = self._event_id_factory()
                        if type(event_id) is not UUID:
                            raise TypeError("event_id_factory must return a UUID")
                        payload = build_alert_payload(
                            event_id=event_id,
                            plan=plan,
                            result=result,
                        )
                        committed_event = unit_of_work.alerts.enqueue(payload)
                        publication_event = unit_of_work.events.get(payload.event_id)
            self._clear_close_pending(
                unit_of_work,
                symbol=plan.symbol,
                trade_date=trade_date,
                evaluated_at=canonical_evaluated_at,
            )
            unit_of_work.commit()

        if not claim.created:
            return OfficialCloseCycleResult(
                status=OfficialCloseCycleStatus.DUPLICATE,
                trade_date=trade_date,
                close_attempt=close_attempt,
                pending_trade_date=None,
                close_reconciliation=reconciliation,
                facts=facts,
                evaluation_result=result,
                claim_created=False,
                committed_event=None,
                error_code=None,
            )
        if publication_event is not None:
            publication = self._publisher(publication_event)
            if isawaitable(publication):
                await publication
        return OfficialCloseCycleResult(
            status=OfficialCloseCycleStatus.COMMITTED,
            trade_date=trade_date,
            close_attempt=close_attempt,
            pending_trade_date=None,
            close_reconciliation=reconciliation,
            facts=facts,
            evaluation_result=result,
            claim_created=True,
            committed_event=committed_event,
            error_code=None,
        )

    @staticmethod
    def _append_snapshot_event(
        unit_of_work: UnitOfWork,
        result: EvaluationResult,
    ) -> MonitorEvent:
        identity = result.evaluation_identity
        return unit_of_work.events.append(
            MonitorEventDraft(
                event_id=monitor_event_id(
                    MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                    identity.symbol,
                    identity.model_dump_json(),
                    result.result_hash,
                ),
                event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                aggregate_id=identity.symbol,
                payload=MonitorEventPayload(
                    entity_id=identity.symbol,
                    symbol=identity.symbol,
                    result_hash=result.result_hash,
                ),
                occurred_at=result.snapshot.evaluated_at,
            )
        )

    def _official_close_completed(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
    ) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            completed = unit_of_work.evaluations.has_claim(
                plan_hash=plan_sha256(plan),
                symbol=plan.symbol,
                evaluation_kind=EvaluationKind.OFFICIAL_CLOSE,
                bucket_end=None,
                official_trade_date=trade_date,
                formula_version=plan.monitoring.indicator_formula_version,
            )
            if completed:
                self._clear_close_pending(
                    unit_of_work,
                    symbol=plan.symbol,
                    trade_date=trade_date,
                    evaluated_at=evaluated_at,
                )
                unit_of_work.commit()
        return completed

    def _persist_official_market_context(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        source_as_of: datetime,
        incoming: tuple[DailyBar, ...],
    ) -> tuple[CloseReconciliationIntent, tuple[DailyBar, ...]]:
        with self._unit_of_work_factory() as unit_of_work:
            if incoming:
                unit_of_work.history.upsert_daily_bars(incoming)
            rows = unit_of_work.history.list_daily_bars(
                plan.symbol,
                start=date.min,
                end=trade_date,
            )
            current_rows = tuple(row for row in rows if row.trade_date == trade_date)
            reconciliation = reconcile_daily_close(
                symbol=plan.symbol,
                current_trade_date=trade_date,
                daily_bars=current_rows,
            )
            official_history = tuple(
                row for row in rows if row.is_official and row.trade_date < trade_date
            )
            if any(row.received_at > evaluated_at for row in (*official_history, *current_rows)):
                raise ValueError("persisted official market facts cannot be from the future")
            self._mark_close_pending(
                unit_of_work,
                symbol=plan.symbol,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
            )
            unit_of_work.commit()
        if source_as_of > evaluated_at:  # pragma: no cover - validated by caller
            raise ValueError("official source cutoff cannot follow evaluation")
        return reconciliation, official_history

    @staticmethod
    def _validated_official_fetch(
        value: object,
        *,
        symbol: str,
        trade_date: date,
        evaluated_at: datetime,
    ) -> tuple[tuple[DailyBar, ...], OfficialCloseErrorCode | None]:
        if type(value) not in {list, tuple} or len(value) > _MAX_FETCHED_MINUTES:
            return (), OfficialCloseErrorCode.INVALID_RESPONSE
        if not value:
            return (), OfficialCloseErrorCode.NOT_AVAILABLE
        unique: DailyBar | None = None
        for item in value:
            if (
                not isinstance(item, DailyBar)
                or item.symbol != symbol
                or item.trade_date != trade_date
                or not item.is_official
                or item.received_at > evaluated_at
            ):
                return (), OfficialCloseErrorCode.INVALID_RESPONSE
            if unique is None:
                unique = item
            elif item != unique:
                return (), OfficialCloseErrorCode.INVALID_RESPONSE
        if unique is None:  # pragma: no cover - empty input returned above
            return (), OfficialCloseErrorCode.NOT_AVAILABLE
        return (unique,), None

    def _persist_market_context(
        self,
        *,
        plan: TradePlan,
        bucket_end: datetime,
        incoming: tuple[MinuteBar, ...],
    ) -> tuple[tuple[MinuteBar, ...], tuple[FiveMinuteBar, ...], DailyBar] | None:
        canonical_day = expected_minute_ends(bucket_end.date(), is_open=True)
        expected_slice = tuple(end for end in canonical_day if end <= bucket_end)
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.history.upsert_minutes(incoming)
            current_day_minutes = unit_of_work.history.list_minutes(
                plan.symbol,
                start=expected_slice[0],
                end=bucket_end,
            )
            provisional = aggregate_provisional_daily_bar(
                current_day_minutes=current_day_minutes,
                source_as_of=bucket_end,
            )
            if provisional is None:
                unit_of_work.commit()
                return None

            complete_bars: list[FiveMinuteBar] = []
            for offset in range(0, len(current_day_minutes), 5):
                group = current_day_minutes[offset : offset + 5]
                aggregate = aggregate_five_minute_bar(
                    group,
                    bucket_end=group[-1].bar_end,
                    is_open=True,
                )
                if aggregate is None:  # pragma: no cover - provisional exactness protects this
                    raise ValueError("persisted current-day slice contains an incomplete bucket")
                record = unit_of_work.history.upsert_five_minute(
                    **aggregate.model_dump(mode="python", round_trip=True)
                )
                complete_bars.append(_five_minute_value(record))
            unit_of_work.history.upsert_daily_bars((provisional,))
            unit_of_work.commit()
        return current_day_minutes, tuple(complete_bars), provisional

    @staticmethod
    def _validated_fetch(
        value: object,
        *,
        symbol: str,
        bucket_end: datetime,
    ) -> tuple[MinuteBar, ...]:
        if type(value) not in {list, tuple}:
            raise TypeError("fetched minutes must be a bounded list or tuple")
        if len(value) > _MAX_FETCHED_MINUTES:
            raise ValueError("fetched minute batch exceeds 1000 rows")
        if any(not isinstance(item, MinuteBar) for item in value):
            raise TypeError("fetched rows must be normalized MinuteBar values")
        minutes = tuple(value)
        if any(
            minute.symbol != symbol
            or minute.bar_end.date() != bucket_end.date()
            or minute.bar_end > bucket_end
            for minute in minutes
        ):
            raise ValueError("fetched minutes must match the requested symbol and cutoff")
        return tuple(sorted(minutes, key=lambda minute: (minute.bar_end, minute.received_at)))

    @staticmethod
    def _validate_context(
        *,
        plan: TradePlan,
        facts: IntradayMarketFacts,
        context: object,
    ) -> None:
        if not isinstance(context, EvaluationContext):
            raise TypeError("context_builder must return an EvaluationContext")
        if context.plan != plan or context.plan_hash != plan_sha256(plan):
            raise ValueError("evaluation context must match the requested plan")
        if not isinstance(context.target, IntradayEvaluationTarget):
            raise ValueError("intraday runtime requires an intraday evaluation target")
        if (
            context.target.bucket_end != facts.bucket_end
            or context.evaluated_at != facts.evaluated_at
            or context.current_day_minutes != facts.current_day_minutes
            or context.complete_5m_bars != facts.complete_five_minute_bars
        ):
            raise ValueError("evaluation context must retain the exact persisted market facts")
        reconciliation = context.close_reconciliation
        if reconciliation is None or reconciliation.provisional_bar != facts.provisional_daily_bar:
            raise ValueError("evaluation context must retain provisional source provenance")
        snapshot = context.daily_indicator_snapshot
        if snapshot is not None and (
            snapshot.provenance is not facts.provenance
            or snapshot.source_as_of != facts.source_as_of
            or snapshot.source_bar != facts.provisional_daily_bar
        ):
            raise ValueError("daily indicators must retain exact provisional provenance")

    @staticmethod
    def _validate_result(
        *,
        plan: TradePlan,
        facts: IntradayMarketFacts,
        result: object,
    ) -> None:
        if not isinstance(result, EvaluationResult):
            raise TypeError("evaluator must return an EvaluationResult")
        identity = result.evaluation_identity
        if not isinstance(identity, IntradayEvaluationIdentity):
            raise ValueError("intraday runtime cannot apply an official-close result")
        if (
            identity.plan_hash != plan_sha256(plan)
            or identity.symbol != plan.symbol
            or identity.bucket_end != facts.bucket_end
            or identity.formula_version != facts.formula_version
            or result.snapshot.evaluated_at != facts.evaluated_at
        ):
            raise ValueError("evaluation result must match the exact intraday runtime identity")
        if any(isinstance(item, RiskTransitionIntent) for item in result.transitions):
            raise ValueError("intraday evaluation cannot apply an official-close risk transition")
        if result.snapshot.signal_type in _OFFICIAL_RISK_SIGNAL_TYPES:
            raise ValueError("intraday evaluation cannot emit an official-close risk signal")

    @staticmethod
    def _validate_official_context(
        *,
        plan: TradePlan,
        facts: OfficialCloseMarketFacts,
        context: object,
    ) -> None:
        if not isinstance(context, EvaluationContext):
            raise TypeError("official_context_builder must return an EvaluationContext")
        if context.plan != plan or context.plan_hash != plan_sha256(plan):
            raise ValueError("official evaluation context must match the requested plan")
        if not isinstance(context.target, OfficialCloseEvaluationTarget):
            raise ValueError("official runtime requires an official-close target")
        if (
            context.target.trade_date != facts.trade_date
            or context.evaluated_at != facts.evaluated_at
            or context.current_day_minutes
            or context.complete_5m_bars
            or context.official_daily_bars != facts.official_daily_bars
            or context.close_reconciliation != facts.close_reconciliation
            or context.daily_indicator_snapshot != facts.daily_indicator_snapshot
        ):
            raise ValueError("evaluation context must retain the exact official market facts")

    @staticmethod
    def _validate_official_result(
        *,
        plan: TradePlan,
        facts: OfficialCloseMarketFacts,
        result: object,
    ) -> None:
        if not isinstance(result, EvaluationResult):
            raise TypeError("evaluator must return an EvaluationResult")
        identity = result.evaluation_identity
        if not isinstance(identity, OfficialCloseEvaluationIdentity):
            raise ValueError("official runtime cannot apply an intraday result")
        if (
            identity.plan_hash != plan_sha256(plan)
            or identity.symbol != plan.symbol
            or identity.official_trade_date != facts.trade_date
            or identity.formula_version != facts.formula_version
            or result.snapshot.evaluated_at != facts.evaluated_at
        ):
            raise ValueError("evaluation result must match the exact official runtime identity")
        if any(not isinstance(item, RiskTransitionIntent) for item in result.transitions):
            raise ValueError("official-close evaluation can apply only risk transitions")
        if result.snapshot.signal_type not in {
            SignalType.WAIT,
            SignalType.BLOCKED_DATA,
            *_OFFICIAL_RISK_SIGNAL_TYPES,
        }:
            raise ValueError("official-close evaluation emitted an intraday signal")

    @staticmethod
    def _mark_close_pending(
        unit_of_work: UnitOfWork,
        *,
        symbol: str,
        trade_date: date,
        evaluated_at: datetime,
    ) -> None:
        current = unit_of_work.health.get_symbol(symbol)
        if current is not None and current.status is SymbolHealthStatus.CLOSE_PENDING:
            persisted_date, resume = _close_pending_payload(current.gap_json)
            if persisted_date != trade_date:
                raise ValueError("one symbol cannot retain two CLOSE_PENDING dates")
        else:
            resume = {
                "status": (
                    SymbolHealthStatus.LIVE.value if current is None else current.status.value
                ),
                "gaps": [] if current is None else _json_value(current.gap_json),
                "errorStreak": 0 if current is None else current.error_streak,
            }
        latest_bar_end = None if current is None else current.latest_bar_end
        data_age_seconds = (
            0
            if latest_bar_end is None
            else max(0, int((evaluated_at - latest_bar_end).total_seconds()))
        )
        unit_of_work.health.upsert_symbol(
            symbol=symbol,
            status=SymbolHealthStatus.CLOSE_PENDING,
            latest_bar_end=latest_bar_end,
            data_age_seconds=data_age_seconds,
            gaps={
                _CLOSE_PENDING_DATE_KEY: trade_date.isoformat(),
                _CLOSE_PENDING_RESUME_KEY: resume,
            },
            error_streak=1 if current is None else current.error_streak + 1,
            expected_revision=0 if current is None else current.revision,
        )

    @staticmethod
    def _clear_close_pending(
        unit_of_work: UnitOfWork,
        *,
        symbol: str,
        trade_date: date,
        evaluated_at: datetime,
    ) -> None:
        current = unit_of_work.health.get_symbol(symbol)
        if current is None or current.status is not SymbolHealthStatus.CLOSE_PENDING:
            return
        persisted_date, resume = _close_pending_payload(current.gap_json)
        if persisted_date != trade_date:
            raise ValueError("cannot clear another official close pending date")
        latest_bar_end = current.latest_bar_end
        data_age_seconds = (
            0
            if latest_bar_end is None
            else max(0, int((evaluated_at - latest_bar_end).total_seconds()))
        )
        unit_of_work.health.upsert_symbol(
            symbol=symbol,
            status=resume["status"],
            latest_bar_end=latest_bar_end,
            data_age_seconds=data_age_seconds,
            gaps=resume["gaps"],
            error_streak=resume["errorStreak"],
            expected_revision=current.revision,
        )

    @staticmethod
    def _apply_transitions(unit_of_work: UnitOfWork, result: EvaluationResult) -> None:
        for transition in result.transitions:
            if isinstance(transition, EpisodeTransitionIntent):
                RuntimeEvaluationService._apply_episode(unit_of_work, transition)
            elif isinstance(transition, RiskTransitionIntent):
                risk = transition.risk
                unit_of_work.risk.upsert(
                    symbol=risk.symbol,
                    plan_hash=risk.plan_hash,
                    status=risk.status.value,
                    breach_trade_date=risk.breach_trade_date,
                    prior_close_fen=risk.prior_close_fen,
                    expected_revision=transition.expected_revision,
                )
            else:  # pragma: no cover - closed discriminated union
                raise TypeError("unsupported state transition intent")

    @staticmethod
    def _apply_episode(
        unit_of_work: UnitOfWork,
        transition: EpisodeTransitionIntent,
    ) -> None:
        episode = transition.episode
        try:
            current = unit_of_work.episodes.get(episode.episode_id)
        except EpisodeNotFoundError:
            current = unit_of_work.episodes.start(
                episode_id=episode.episode_id,
                plan_hash=episode.plan_hash,
                symbol=episode.symbol,
                zone="LOW_BUY",
                started_at=episode.started_at,
                episode_low_fen=episode.episode_low_fen,
                last_processed_bucket_end=five_minute_bucket_end(episode.started_at),
            )
        if (
            current.plan_hash != episode.plan_hash
            or current.symbol != episode.symbol
            or current.started_at != episode.started_at
        ):
            raise EpisodeIdentityConflictError(
                "Episode identifier is bound to another runtime identity"
            )
        unit_of_work.episodes.revise(
            episode.episode_id,
            episode_low_fen=episode.episode_low_fen,
            bars_since_low=episode.bars_since_low,
            status=episode.status.value,
            alerted_signal=episode.alerted_signal,
            last_processed_bucket_end=episode.last_processed_bucket_end,
        )


class ActiveSymbolLimitError(RuntimeError):
    """The persisted active set exceeds the approved single-process bound."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__("runtime supports at most 10 active symbols")


class RuntimeShutdownError(RuntimeError):
    """Owned work did not honor the bounded shutdown cancellation contract."""

    def __init__(self, pending_count: int) -> None:
        self.pending_count = pending_count
        super().__init__("runtime shutdown has an owned task that did not stop")


class RuntimeStartupResult(_RuntimeValue):
    """Sanitized result of one owned startup sequence."""

    status: RuntimeServiceStatus
    read_only: bool = Field(strict=True)
    active_symbols: tuple[str, ...] = Field(default=(), max_length=10)
    capabilities: ProviderCapabilities
    next_poll_at: ShanghaiDatetime | None = None

    @model_validator(mode="after")
    def validate_startup_state(self) -> Self:
        if len(self.active_symbols) != len(set(self.active_symbols)):
            raise ValueError("active symbols must be unique")
        if any(not symbol for symbol in self.active_symbols):
            raise ValueError("active symbols cannot be empty")
        if self.read_only != (self.status is RuntimeServiceStatus.DEGRADED):
            raise ValueError("read-only startup must be degraded")
        return self


class RuntimeLifecycleService:
    """Own startup, scheduling tasks, resource shutdown, and WAL checkpointing."""

    def __init__(
        self,
        *,
        clock: Clock,
        validate_configuration: Callable[[], object],
        open_database: Callable[[], object],
        load_active_symbols: Callable[[], object],
        probe_capabilities: Callable[[], object],
        refresh_references: Callable[[date], object],
        recover_startup: Callable[[date], object],
        scheduler: object,
        run_deadline: Callable[[MarketDeadline], object],
        dispatcher: object,
        request_controller: object,
        checkpoint_wal: Callable[[], object],
        close_database: Callable[[], object],
        health_details: Callable[[], RuntimeHealthDetails],
        shutdown_timeout_seconds: float = 5.0,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        dependencies = (
            validate_configuration,
            open_database,
            load_active_symbols,
            probe_capabilities,
            refresh_references,
            recover_startup,
            run_deadline,
            checkpoint_wal,
            close_database,
            health_details,
        )
        if any(not callable(dependency) for dependency in dependencies):
            raise TypeError("runtime lifecycle dependencies must be callable")
        if not callable(getattr(scheduler, "next_deadline", None)) or not callable(
            getattr(scheduler, "wait_for_next", None)
        ):
            raise TypeError("scheduler must expose next_deadline and wait_for_next")
        if not callable(getattr(dispatcher, "aclose", None)):
            raise TypeError("dispatcher must expose aclose")
        if not callable(getattr(request_controller, "close", None)):
            raise TypeError("request_controller must expose close")
        if (
            isinstance(shutdown_timeout_seconds, bool)
            or not isinstance(shutdown_timeout_seconds, int | float)
            or not 0 < shutdown_timeout_seconds <= 60
        ):
            raise ValueError("shutdown_timeout_seconds must be between 0 and 60")

        self._clock = clock
        self._validate_configuration = validate_configuration
        self._open_database = open_database
        self._load_active_symbols = load_active_symbols
        self._probe_capabilities = probe_capabilities
        self._refresh_references = refresh_references
        self._recover_startup = recover_startup
        self._scheduler = scheduler
        self._run_deadline = run_deadline
        self._dispatcher = dispatcher
        self._request_controller = request_controller
        self._checkpoint_wal = checkpoint_wal
        self._close_database = close_database
        self._health_details = health_details
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._status = RuntimeServiceStatus.STOPPED
        self._read_only = True
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._next_poll_at: datetime | None = None
        self._startup_result: RuntimeStartupResult | None = None
        self._start_task: asyncio.Task[RuntimeStartupResult] | None = None
        self._accepting_work = False
        self._database_opened = False
        self._dispatcher_closed = False
        self._request_controller_closed = False
        self._wal_checkpointed = False
        self._schedule_wait_task: asyncio.Task[MarketDeadline | None] | None = None
        self._work_tasks: set[asyncio.Task[object]] = set()
        self._last_deadline_at: datetime | None = None
        self._stopping = False
        self._cleanup_complete = False
        self._stop_task: asyncio.Task[None] | None = None
        self._shutdown_requested_event: asyncio.Event | None = None

    @property
    def status(self) -> RuntimeServiceStatus:
        return self._status

    @property
    def owned_task_count(self) -> int:
        waiting = self._schedule_wait_task
        starting = self._start_task
        stopping = self._stop_task
        return (
            len(self._work_tasks)
            + int(waiting is not None and not waiting.done())
            + int(starting is not None and not starting.done())
            + int(stopping is not None and not stopping.done())
        )

    def health(self) -> RuntimeHealthSnapshot:
        """Build one current snapshot from owned lifecycle and injected dynamic facts."""

        if self._started_at is None:
            raise RuntimeError("runtime health is unavailable before startup")
        details = self._health_details()
        if not isinstance(details, RuntimeHealthDetails):
            raise TypeError("health_details must return RuntimeHealthDetails")
        observed_at = _canonical_shanghai(self._clock.now())
        return RuntimeHealthSnapshot(
            **details.model_dump(mode="python", round_trip=True),
            status=self._status,
            read_only=self._read_only,
            observed_at=observed_at,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            last_completed_minute_age_seconds=self._age_seconds(
                details.last_completed_minute,
                observed_at,
            ),
            latest_evaluation_age_seconds=self._age_seconds(
                details.latest_evaluation_at,
                observed_at,
            ),
            next_poll_at=self._next_poll_at,
        )

    async def start(self) -> RuntimeStartupResult:
        """Run the fixed startup sequence once and return honest readiness."""

        if self._cleanup_complete or self._stopping:
            raise RuntimeError("stopped runtime lifecycle cannot be restarted")
        if self._startup_result is not None:
            return self._startup_result
        if self._start_task is None:
            self._status = RuntimeServiceStatus.STARTING
            self._read_only = True
            self._started_at = _canonical_shanghai(self._clock.now())
            self._start_task = asyncio.create_task(self._start_sequence())
        start_task = self._start_task
        try:
            return await asyncio.shield(start_task)
        except BaseException:
            if not self._stopping:
                try:
                    await self.stop()
                except BaseException:
                    pass
            raise

    async def _start_sequence(self) -> RuntimeStartupResult:
        await self._invoke(self._validate_configuration)
        await self._invoke(self._open_database)
        self._database_opened = True
        raw_symbols = await self._invoke(self._load_active_symbols)
        active_symbols = self._active_symbols(raw_symbols)
        raw_capabilities = await self._invoke(self._probe_capabilities)
        if not isinstance(raw_capabilities, ProviderCapabilities):
            raise TypeError("provider probe must return ProviderCapabilities")

        read_only = not self._all_capabilities_ready(raw_capabilities)
        trade_date = _canonical_shanghai(self._clock.now()).date()
        for startup_operation in (
            self._refresh_references,
            self._recover_startup,
        ):
            try:
                await self._invoke(startup_operation, trade_date)
            except asyncio.CancelledError:
                raise
            except Exception:
                read_only = True

        next_deadline = self._scheduler.next_deadline()
        if next_deadline is not None and not isinstance(next_deadline, MarketDeadline):
            raise TypeError("scheduler must return MarketDeadline or None")
        if next_deadline is None:
            read_only = True
        status = RuntimeServiceStatus.DEGRADED if read_only else RuntimeServiceStatus.RUNNING
        self._status = status
        self._read_only = read_only
        self._accepting_work = not read_only
        self._next_poll_at = None if read_only or next_deadline is None else next_deadline.due_at
        self._startup_result = RuntimeStartupResult(
            status=status,
            read_only=read_only,
            active_symbols=active_symbols,
            capabilities=raw_capabilities,
            next_poll_at=self._next_poll_at,
        )
        return self._startup_result

    async def run_once(self) -> object | None:
        """Run at most one eligible deadline and clean up if this call started runtime."""

        owns_startup = self._startup_result is None
        try:
            startup = await self.start()
            if startup.read_only or not self._accepting_work:
                return None
            deadline = await self._wait_for_next(after=None)
            if deadline is None or not self._accepting_work:
                return None
            return await self._execute_deadline(deadline)
        finally:
            if owns_startup:
                await self.stop()

    async def run(self) -> None:
        """Run scheduled deadlines until stopped, then close every owned resource."""

        try:
            startup = await self.start()
            if startup.read_only:
                shutdown_event = asyncio.Event()
                self._shutdown_requested_event = shutdown_event
                if self._stopping or self._cleanup_complete:
                    shutdown_event.set()
                await shutdown_event.wait()
                return
            while self._accepting_work:
                try:
                    deadline = await self._wait_for_next(after=self._last_deadline_at)
                except asyncio.CancelledError:
                    if not self._accepting_work:
                        break
                    raise
                if deadline is None or not self._accepting_work:
                    break
                try:
                    await self._execute_deadline(deadline)
                except asyncio.CancelledError:
                    if not self._accepting_work:
                        break
                    raise
                self._last_deadline_at = deadline.due_at
                next_deadline = self._scheduler.next_deadline(after=self._last_deadline_at)
                self._next_poll_at = None if next_deadline is None else next_deadline.due_at
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop admission, bound task completion, close resources, and checkpoint WAL."""

        if self._cleanup_complete:
            return
        stop_task = self._stop_task
        if stop_task is None or stop_task.done():
            caller = asyncio.current_task()
            initiator = caller if caller in self._work_tasks else None
            stop_task = asyncio.create_task(self._stop_sequence(initiator=initiator))
            stop_task.add_done_callback(self._observe_stop_result)
            self._stop_task = stop_task
        await asyncio.shield(stop_task)

    async def _stop_sequence(self, *, initiator: asyncio.Task[object] | None) -> None:
        """Run cleanup independently from any one public stop waiter."""

        self._stopping = True
        self._status = RuntimeServiceStatus.STOPPING
        self._accepting_work = False
        if self._shutdown_requested_event is not None:
            self._shutdown_requested_event.set()
        first_error: BaseException | None = None
        current_task = asyncio.current_task()
        start_task = self._start_task
        if start_task is not None and start_task is not current_task and not start_task.done():
            start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)

        wait_task = self._schedule_wait_task
        if wait_task is not None and not wait_task.done():
            wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)
        self._schedule_wait_task = None

        active = tuple(
            task for task in self._work_tasks if task is not initiator and not task.done()
        )
        pending = await self._finish_owned_tasks(active) if active else set()
        self._work_tasks = {task for task in self._work_tasks if not task.done()}
        if pending:
            raise RuntimeShutdownError(len(pending))

        resources = (
            ("_dispatcher_closed", self._dispatcher.aclose),
            ("_request_controller_closed", self._request_controller.close),
        )
        for state_name, operation in resources:
            if getattr(self, state_name):
                continue
            try:
                await self._invoke(operation)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            else:
                setattr(self, state_name, True)
        if self._database_opened:
            if not self._wal_checkpointed:
                try:
                    await self._invoke(self._checkpoint_wal)
                except BaseException as error:
                    if first_error is None:
                        first_error = error
                else:
                    self._wal_checkpointed = True
            if self._wal_checkpointed:
                try:
                    await self._invoke(self._close_database)
                except BaseException as error:
                    if first_error is None:
                        first_error = error
                else:
                    self._database_opened = False
        if first_error is not None:
            raise first_error
        self._status = RuntimeServiceStatus.STOPPED
        self._stopped_at = _canonical_shanghai(self._clock.now())
        self._cleanup_complete = True

    async def _wait_for_next(self, *, after: datetime | None) -> MarketDeadline | None:
        wait_task = asyncio.create_task(self._scheduler.wait_for_next(after=after))
        self._schedule_wait_task = wait_task
        try:
            deadline = await wait_task
        finally:
            if self._schedule_wait_task is wait_task:
                self._schedule_wait_task = None
        if deadline is not None and not isinstance(deadline, MarketDeadline):
            raise TypeError("scheduler must return MarketDeadline or None")
        return deadline

    async def _execute_deadline(self, deadline: MarketDeadline) -> object:
        work_task = asyncio.create_task(self._invoke(self._run_deadline, deadline))
        self._work_tasks.add(work_task)
        try:
            return await work_task
        finally:
            self._work_tasks.discard(work_task)

    async def _finish_owned_tasks(
        self,
        tasks: tuple[asyncio.Task[object], ...],
    ) -> set[asyncio.Task[object]]:
        _, pending = await asyncio.wait(
            tasks,
            timeout=self._shutdown_timeout_seconds,
        )
        for _ in range(2):
            if not pending:
                return set()
            for task in pending:
                task.cancel()
            _, pending = await asyncio.wait(
                pending,
                timeout=self._shutdown_timeout_seconds,
            )
        return set(pending)

    @staticmethod
    def _observe_stop_result(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    async def _invoke(operation: Callable[..., object], *args: object) -> object:
        result = operation(*args)
        return await result if isawaitable(result) else result

    @staticmethod
    def _active_symbols(raw_symbols: object) -> tuple[str, ...]:
        if type(raw_symbols) is not tuple or any(
            type(symbol) is not str or not symbol for symbol in raw_symbols
        ):
            raise TypeError("active symbols must be a tuple of non-empty strings")
        if len(raw_symbols) > 10:
            raise ActiveSymbolLimitError(len(raw_symbols))
        if len(raw_symbols) != len(set(raw_symbols)):
            raise ValueError("active symbols must be unique")
        return raw_symbols

    @staticmethod
    def _all_capabilities_ready(capabilities: ProviderCapabilities) -> bool:
        return all(
            status is ProviderCapabilityStatus.READY
            for status in (
                capabilities.realtime_minutes,
                capabilities.current_day_minutes,
                capabilities.trading_calendar,
                capabilities.daily_limits,
                capabilities.daily_bars,
            )
        )

    @staticmethod
    def _age_seconds(value: datetime | None, observed_at: datetime) -> int | None:
        if value is None:
            return None
        age = observed_at - value
        if age < timedelta(0):
            raise ValueError("health timestamps cannot be in the future")
        return int(age.total_seconds())


class MaintenanceCommandService:
    """Thin asynchronous command surface over runtime and maintenance operations."""

    def __init__(
        self,
        *,
        lifecycle: object,
        validate: Callable[[], object],
        replay: Callable[[], object],
        backup: Callable[[], object],
    ) -> None:
        if not callable(getattr(lifecycle, "run_once", None)) or not callable(
            getattr(lifecycle, "run", None)
        ):
            raise TypeError("lifecycle must expose run_once and run")
        if any(not callable(operation) for operation in (validate, replay, backup)):
            raise TypeError("maintenance operations must be callable")
        self._lifecycle = lifecycle
        self._validate = validate
        self._replay = replay
        self._backup = backup

    async def validate(self) -> object:
        return await RuntimeLifecycleService._invoke(self._validate)

    async def once(self) -> object:
        return await self._lifecycle.run_once()

    async def run(self) -> object:
        return await self._lifecycle.run()

    async def replay(self) -> object:
        return await RuntimeLifecycleService._invoke(self._replay)

    async def backup(self) -> object:
        return await RuntimeLifecycleService._invoke(self._backup)


def _five_minute_value(record: FiveMinuteBarRecord) -> FiveMinuteBar:
    return FiveMinuteBar.model_validate(record.model_dump(mode="python", round_trip=True))


def _json_value(value: str) -> object:
    try:
        parsed = json.loads(value)
    except TypeError, ValueError, RecursionError:
        parsed = _INVALID_JSON
    if parsed is _INVALID_JSON:
        raise ValueError("persisted symbol health gaps are invalid") from None
    return parsed


def _close_pending_payload(value: str) -> tuple[date, dict[str, object]]:
    parsed = _json_value(value)
    if not isinstance(parsed, dict) or set(parsed) != {
        _CLOSE_PENDING_DATE_KEY,
        _CLOSE_PENDING_RESUME_KEY,
    }:
        raise ValueError("persisted CLOSE_PENDING health is invalid") from None
    date_text = parsed.get(_CLOSE_PENDING_DATE_KEY)
    resume = parsed.get(_CLOSE_PENDING_RESUME_KEY)
    if (
        type(date_text) is not str
        or not isinstance(resume, dict)
        or set(resume)
        != {
            "status",
            "gaps",
            "errorStreak",
        }
    ):
        raise ValueError("persisted CLOSE_PENDING health is invalid") from None
    try:
        pending_date = date.fromisoformat(date_text)
        resume_status = SymbolHealthStatus(resume.get("status"))
    except TypeError, ValueError:
        pending_date = None
        resume_status = None
    error_streak = resume.get("errorStreak")
    if (
        pending_date is None
        or pending_date.isoformat() != date_text
        or resume_status is None
        or resume_status is SymbolHealthStatus.CLOSE_PENDING
        or type(error_streak) is not int
        or error_streak < 0
        or "gaps" not in resume
    ):
        raise ValueError("persisted CLOSE_PENDING health is invalid") from None
    return pending_date, {
        "status": resume_status,
        "gaps": resume["gaps"],
        "errorStreak": error_streak,
    }


__all__ = [
    "ActiveSymbolLimitError",
    "IntradayCycleResult",
    "IntradayCycleStatus",
    "IntradayMarketFacts",
    "MaintenanceCommandService",
    "OfficialCloseCycleResult",
    "OfficialCloseCycleStatus",
    "OfficialCloseErrorCode",
    "OfficialCloseMarketFacts",
    "RuntimeEvaluationService",
    "RuntimeLifecycleService",
    "RuntimeShutdownError",
    "RuntimeStartupResult",
]
