"""Deterministic intraday/official evaluation and committed-event publication."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from inspect import isawaitable
from types import MappingProxyType
from typing import Self, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
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
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    ExecutableTradePlan,
    ExplicitTradePlan,
    TradePlan,
    activation_is_eligible_on,
)
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
from trade_plan_monitor.market_index.canonical import validate_market_index_snapshot_integrity
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexSnapshot,
)
from trade_plan_monitor.market_index.requirements import iter_plan_index_conditions
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertEvent, build_alert_payload
from trade_plan_monitor.runtime.clock import Clock, SystemClock, _canonical_shanghai
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeCycleResult,
    ExplicitRuntimeEvaluationService,
)
from trade_plan_monitor.runtime.health import (
    LEGACY_RUNTIME_GENERATION,
    RuntimeHealthDetails,
    RuntimeHealthSnapshot,
    RuntimeServiceStatus,
    SymbolHealthErrorCode,
    SymbolHealthSnapshot,
)
from trade_plan_monitor.runtime.market_indexes import (
    RuntimeMarketIndexBatch,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.symbol_service import SymbolHealthRestoreState, SymbolService
from trade_plan_monitor.state.events import (
    MonitorEvent,
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import EvaluationKind, SymbolHealthStatus
from trade_plan_monitor.state.projections import ProjectionIdentityConflictError
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
ActivePlans = Callable[[], tuple[ExecutableTradePlan, ...]]


def _ceil_to_whole_second(value: datetime) -> datetime:
    canonical = _SHANGHAI_DATETIME.validate_python(value, strict=True)
    if canonical.microsecond:
        canonical += timedelta(seconds=1)
    return canonical.replace(microsecond=0)


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


class _PersistedSymbolHealth(_RuntimeValue):
    """Closed public projection shape used to hydrate runtime tracker state."""

    symbol: str
    observed_at: ShanghaiDatetime = Field(alias="observedAt")
    target_end: ShanghaiDatetime = Field(alias="targetEnd")
    status: DataHealthStatus
    latest_bar_end: ShanghaiDatetime | None = Field(alias="latestBarEnd")
    data_age_seconds: int | None = Field(alias="dataAgeSeconds", ge=0)
    required_data_complete: bool = Field(alias="requiredDataComplete", strict=True)
    fresh: bool = Field(strict=True)
    gaps: tuple[ShanghaiDatetime, ...] = ()
    consecutive_incomplete_buckets: int = Field(
        alias="consecutiveIncompleteBuckets",
        ge=0,
    )
    last_required_bucket_end: ShanghaiDatetime | None = Field(
        default=None,
        alias="lastRequiredBucketEnd",
    )
    error_code: SymbolHealthErrorCode | None = Field(alias="errorCode")
    actionable: bool = Field(strict=True)

    def snapshot(self) -> SymbolHealthSnapshot:
        snapshot = SymbolHealthSnapshot(
            symbol=self.symbol,
            observed_at=self.observed_at,
            target_end=self.target_end,
            data_health=DataHealthSnapshot(
                symbol=self.symbol,
                status=self.status,
                latest_bar_end=self.latest_bar_end,
                data_age_seconds=self.data_age_seconds,
                required_data_complete=self.required_data_complete,
                fresh=self.fresh,
            ),
            gaps=self.gaps,
            consecutive_incomplete_buckets=self.consecutive_incomplete_buckets,
            last_required_bucket_end=self.last_required_bucket_end,
            error_code=self.error_code,
        )
        if snapshot.actionable is not self.actionable:
            raise ValueError("persisted symbol health actionable flag is invalid")
        return snapshot


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


class StaleActivationGenerationError(RuntimeError):
    """Expected control-flow outcome when a UI plan mutation wins a runtime race."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"plan activation generation changed for {symbol}")


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
        market_index_service: RuntimeMarketIndexService | None = None,
        runtime_generation: UUID = LEGACY_RUNTIME_GENERATION,
        clock: Clock | None = None,
        recovery_delivery: bool = False,
    ) -> None:
        if type(recovery_delivery) is not bool:
            raise TypeError("recovery_delivery must be a bool")
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
        if market_index_service is not None and not isinstance(
            market_index_service,
            RuntimeMarketIndexService,
        ):
            raise TypeError("market_index_service must be a RuntimeMarketIndexService")
        if type(runtime_generation) is not UUID:
            raise TypeError("runtime_generation must be a UUID")
        if runtime_generation.version != 4:
            raise ValueError("runtime_generation must be a UUIDv4")
        if clock is not None and not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
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
        self._market_index_service = market_index_service
        self._runtime_generation = runtime_generation
        self._clock = clock
        # Storage-only opt-in; the existing dispatcher does not enforce this HOLD.
        self._recovery_delivery = recovery_delivery
        self._official_serial = asyncio.Lock()

    async def _post_fetch_official_observed_at(
        self,
        requested_at: datetime,
    ) -> datetime:
        observed_at = _ceil_to_whole_second(self._official_observed_at(requested_at))
        if self._clock is None:
            return observed_at
        now = _canonical_shanghai(self._clock.now())
        observed_at = max(observed_at, _ceil_to_whole_second(now))
        if now < observed_at:
            await self._clock.sleep_until(observed_at)
            if _canonical_shanghai(self._clock.now()) < observed_at:
                raise RuntimeError("clock returned before the official observation boundary")
        return observed_at

    async def run_intraday(
        self,
        *,
        plan: TradePlan,
        bucket_end: datetime,
        evaluated_at: datetime,
    ) -> IntradayCycleResult:
        """Run one intraday target without provider or publisher work in a transaction."""

        evaluated_at = _ceil_to_whole_second(evaluated_at)
        prepared = await self.prepare_intraday_market_indexes(
            plans=(plan,),
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
        )
        reference_market_snapshot = None if prepared is None else prepared.snapshot_for_plan(plan)
        return await self._run_intraday_with_snapshot(
            plan=plan,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
            reference_market_snapshot=reference_market_snapshot,
            health_snapshot=None,
        )

    async def run_intraday_batch(
        self,
        *,
        plans: tuple[TradePlan, ...],
        bucket_end: datetime,
        evaluated_at: datetime,
    ) -> tuple[IntradayCycleResult, ...]:
        """Union index needs, then evaluate an active-plan batch without cancellation."""

        return await self._run_intraday_batch(
            plans=plans,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
            minutes_by_symbol=None,
        )

    async def run_intraday_batch_from_minutes(
        self,
        *,
        plans: tuple[TradePlan, ...],
        bucket_end: datetime,
        evaluated_at: datetime,
        minutes_by_symbol: Mapping[str, tuple[MinuteBar, ...]],
        health_by_symbol: Mapping[str, SymbolHealthSnapshot] | None = None,
        activation_revisions: Mapping[str, int] | None = None,
        market_index_batch: RuntimeMarketIndexBatch | None = None,
    ) -> tuple[IntradayCycleResult, ...]:
        """Evaluate one deadline from its single, already acquired stock batch."""

        validated = self._validated_prefetched_minutes(plans, minutes_by_symbol)
        return await self._run_intraday_batch(
            plans=plans,
            bucket_end=bucket_end,
            evaluated_at=evaluated_at,
            minutes_by_symbol=validated,
            health_by_symbol=health_by_symbol,
            activation_revisions=activation_revisions,
            market_index_batch=market_index_batch,
        )

    async def prepare_intraday_market_indexes(
        self,
        *,
        plans: tuple[TradePlan, ...],
        bucket_end: datetime,
        evaluated_at: datetime,
    ) -> RuntimeMarketIndexBatch | None:
        """Acquire and persist one shared index batch before the stock observation."""

        if type(plans) is not tuple or any(not isinstance(plan, TradePlan) for plan in plans):
            raise TypeError("plans must be a tuple of TradePlan values")
        if len(plans) > 10:
            raise ValueError("runtime supports at most 10 active plans")
        if self._market_index_service is None:
            return None
        prepared = await self._market_index_service.prepare(
            plans=plans,
            decision_cutoff=expected_five_minute_ends(bucket_end)[-1],
            observed_no_later_than=_ceil_to_whole_second(evaluated_at),
        )
        prepared, events = self._persist_market_index_batch(prepared)
        await self._publish_committed_events(events)
        return prepared

    async def retry_intraday_market_indexes(
        self,
        *,
        bucket_end: datetime,
        evaluated_at: datetime,
    ) -> RuntimeMarketIndexBatch | None:
        """Persist only the indexes still lagging at the prior five-minute cutoff."""

        if self._market_index_service is None:
            return None
        prepared = await self._market_index_service.retry_publication_lag(
            decision_cutoff=expected_five_minute_ends(bucket_end)[-1],
            observed_no_later_than=_ceil_to_whole_second(evaluated_at),
        )
        if prepared is None:
            return None
        prepared, events = self._persist_market_index_batch(prepared)
        await self._publish_committed_events(events)
        return prepared

    async def recover_transient_market_indexes(
        self, *, evaluated_at: datetime
    ) -> RuntimeMarketIndexBatch | None:
        """Publish a due, index-only recovery without replaying plan decisions."""
        if self._market_index_service is None:
            return None
        prepared = await self._market_index_service.retry_recoverable(
            observed_no_later_than=_ceil_to_whole_second(evaluated_at)
        )
        if prepared is None or not prepared.snapshots_by_index:
            return None
        prepared, events = self._persist_market_index_batch(prepared)
        await self._publish_committed_events(events)
        return prepared

    def load_persisted_symbol_health(
        self,
        symbols: tuple[str, ...],
    ) -> tuple[SymbolHealthRestoreState, ...]:
        """Load the exact durable tracker state before a post-restart batch."""

        if type(symbols) is not tuple or len(symbols) > 10:
            raise ValueError("symbols must be a tuple capped at 10")
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbols must be unique")
        states: list[SymbolHealthRestoreState] = []
        with self._unit_of_work_factory() as unit_of_work:
            for symbol in symbols:
                active = unit_of_work.plans.get_active(symbol)
                if active is None:
                    activation_state = unit_of_work.plans.get_activation_state(symbol)
                    states.append(
                        SymbolHealthRestoreState(
                            symbol=symbol,
                            activation_revision=(
                                1 if activation_state is None else activation_state.revision
                            ),
                            snapshot=None,
                        )
                    )
                    continue
                record = unit_of_work.projections.get_symbol_health(symbol)
                if record is None or record.activation_revision != active.revision:
                    snapshot = None
                else:
                    projection = _validate_persisted_symbol_health(record.projection)
                    if projection.symbol != symbol or projection.observed_at != record.observed_at:
                        raise ValueError("persisted symbol health identity is inconsistent")
                    snapshot = projection.snapshot()
                states.append(
                    SymbolHealthRestoreState(
                        symbol=symbol,
                        activation_revision=active.revision,
                        snapshot=snapshot,
                    )
                )
        return tuple(states)

    async def persist_symbol_health_batch(
        self,
        snapshots: tuple[SymbolHealthSnapshot, ...],
        *,
        activation_revisions: Mapping[str, int],
    ) -> None:
        """Commit exact non-evaluated runtime health and publish its durable events."""

        if (
            type(snapshots) is not tuple
            or len(snapshots) > 10
            or any(not isinstance(item, SymbolHealthSnapshot) for item in snapshots)
        ):
            raise TypeError("snapshots must be a tuple of at most 10 health snapshots")
        symbols = tuple(item.symbol for item in snapshots)
        if len(set(symbols)) != len(symbols):
            raise ValueError("health snapshot symbols must be unique")
        if (
            not isinstance(activation_revisions, Mapping)
            or set(activation_revisions) != set(symbols)
            or any(type(value) is not int or value < 1 for value in activation_revisions.values())
        ):
            raise ValueError("activation revisions must match the health symbols exactly")
        if not snapshots:
            return
        committed: list[MonitorEvent] = []
        with self._unit_of_work_factory() as unit_of_work:
            for snapshot in snapshots:
                expected_activation_revision = activation_revisions[snapshot.symbol]
                try:
                    self._require_symbol_activation_revision(
                        unit_of_work,
                        symbol=snapshot.symbol,
                        expected_revision=expected_activation_revision,
                    )
                except StaleActivationGenerationError:
                    continue
                health = snapshot.data_health
                current = unit_of_work.health.get_symbol(snapshot.symbol)
                after = unit_of_work.health.upsert_symbol(
                    symbol=snapshot.symbol,
                    status=SymbolHealthStatus(health.status.value),
                    latest_bar_end=health.latest_bar_end,
                    data_age_seconds=(
                        0 if health.data_age_seconds is None else health.data_age_seconds
                    ),
                    gaps=tuple(gap.isoformat() for gap in snapshot.gaps),
                    error_streak=(
                        0
                        if snapshot.actionable
                        else 1
                        if current is None
                        else current.error_streak + 1
                    ),
                    expected_revision=0 if current is None else current.revision,
                )
                unit_of_work.projections.put_symbol_health(
                    symbol=snapshot.symbol,
                    revision=after.revision,
                    activation_revision=expected_activation_revision,
                    runtime_generation=self._runtime_generation,
                    projection={
                        "symbol": snapshot.symbol,
                        "observedAt": snapshot.observed_at,
                        "targetEnd": snapshot.target_end,
                        "status": health.status,
                        "latestBarEnd": health.latest_bar_end,
                        "dataAgeSeconds": health.data_age_seconds,
                        "requiredDataComplete": health.required_data_complete,
                        "fresh": health.fresh,
                        "gaps": snapshot.gaps,
                        "consecutiveIncompleteBuckets": (snapshot.consecutive_incomplete_buckets),
                        "lastRequiredBucketEnd": snapshot.last_required_bucket_end,
                        "errorCode": snapshot.error_code,
                        "actionable": snapshot.actionable,
                    },
                    observed_at=snapshot.observed_at,
                )
                committed.append(
                    unit_of_work.events.get(
                        monitor_event_id(
                            MonitorEventType.SYMBOL_HEALTH_UPDATED,
                            after.symbol,
                            str(after.revision),
                        )
                    )
                )
            unit_of_work.commit()
        await self._publish_committed_events(tuple(committed))

    async def _run_intraday_batch(
        self,
        *,
        plans: tuple[TradePlan, ...],
        bucket_end: datetime,
        evaluated_at: datetime,
        minutes_by_symbol: Mapping[str, tuple[MinuteBar, ...]] | None,
        health_by_symbol: Mapping[str, SymbolHealthSnapshot] | None = None,
        activation_revisions: Mapping[str, int] | None = None,
        market_index_batch: RuntimeMarketIndexBatch | None = None,
    ) -> tuple[IntradayCycleResult, ...]:
        if type(plans) is not tuple or any(not isinstance(plan, TradePlan) for plan in plans):
            raise TypeError("plans must be a tuple of TradePlan values")
        if len(plans) > 10:
            raise ValueError("runtime supports at most 10 active plans")
        evaluated_at = _ceil_to_whole_second(evaluated_at)
        plan_symbols = {plan.symbol for plan in plans}
        if activation_revisions is not None and (
            not isinstance(activation_revisions, Mapping)
            or set(activation_revisions) != plan_symbols
            or any(type(value) is not int or value < 1 for value in activation_revisions.values())
        ):
            raise ValueError("activation revisions must match the intraday plans exactly")
        prepared = market_index_batch
        if prepared is None:
            prepared = await self.prepare_intraday_market_indexes(
                plans=plans,
                bucket_end=bucket_end,
                evaluated_at=evaluated_at,
            )
        elif not isinstance(prepared, RuntimeMarketIndexBatch):
            raise TypeError("market_index_batch must be a RuntimeMarketIndexBatch")
        if prepared is not None:
            if prepared.decision_cutoff != expected_five_minute_ends(bucket_end)[-1]:
                raise ValueError("market index batch must match the intraday cutoff")
            if any(
                snapshot.observed_at > evaluated_at
                for snapshot in prepared.snapshots_by_index.values()
            ):
                raise ValueError("index snapshot observation cannot follow evaluation time")
        results = await asyncio.gather(
            *(
                self._run_intraday_with_snapshot(
                    plan=plan,
                    bucket_end=bucket_end,
                    evaluated_at=evaluated_at,
                    reference_market_snapshot=(
                        None if prepared is None else prepared.snapshot_for_plan(plan)
                    ),
                    health_snapshot=(
                        None if health_by_symbol is None else health_by_symbol[plan.symbol]
                    ),
                    fetched_minutes=(
                        None if minutes_by_symbol is None else minutes_by_symbol[plan.symbol]
                    ),
                    activation_revision=(
                        None if activation_revisions is None else activation_revisions[plan.symbol]
                    ),
                )
                for plan in plans
            ),
            return_exceptions=True,
        )
        first_error = next(
            (
                item
                for item in results
                if isinstance(item, BaseException)
                and not isinstance(item, StaleActivationGenerationError)
            ),
            None,
        )
        if first_error is not None:
            raise first_error
        return tuple(item for item in results if isinstance(item, IntradayCycleResult))

    async def _run_intraday_with_snapshot(
        self,
        *,
        plan: TradePlan,
        bucket_end: datetime,
        evaluated_at: datetime,
        reference_market_snapshot: MarketIndexSnapshot | None,
        health_snapshot: SymbolHealthSnapshot | None,
        fetched_minutes: tuple[MinuteBar, ...] | None = None,
        activation_revision: int | None = None,
    ) -> IntradayCycleResult:
        """Evaluate one plan using an already shared reference-index snapshot."""

        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        canonical_bucket = expected_five_minute_ends(bucket_end)[-1]
        canonical_evaluated_at = _ceil_to_whole_second(evaluated_at)
        if canonical_evaluated_at < canonical_bucket:
            raise ValueError("evaluated_at cannot precede bucket_end")
        if activation_revision is None:
            activation_revision = self._capture_plan_activation_revision(plan)

        fetched = (
            await self._fetch_minutes(plan.symbol, canonical_bucket)
            if fetched_minutes is None
            else fetched_minutes
        )
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
        if not isinstance(context, EvaluationContext):
            raise TypeError("context_builder must return an EvaluationContext")
        context_updates: dict[str, object] = {
            "reference_market_snapshot": reference_market_snapshot
        }
        if health_snapshot is not None:
            self._validate_runtime_health_snapshot(
                plan=plan,
                facts=facts,
                health_snapshot=health_snapshot,
            )
            context_updates["data_health"] = health_snapshot.data_health
        context = context.model_copy(update=context_updates)
        self._validate_context(
            plan=plan,
            facts=facts,
            context=context,
            reference_market_snapshot=reference_market_snapshot,
            health_snapshot=health_snapshot,
        )
        result = self._evaluator(context)
        self._validate_result(plan=plan, facts=facts, result=result)

        committed_event: AlertEvent | None = None
        publication_event: MonitorEvent | None = None
        health_event: MonitorEvent | None = None
        with self._unit_of_work_factory() as unit_of_work:
            self._require_evaluated_plan_active(
                unit_of_work,
                plan,
                expected_revision=activation_revision,
                market_date=canonical_bucket.date(),
            )
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
                health_event = self._persist_projection_dependencies(
                    unit_of_work,
                    result,
                    plan=plan,
                    reference_market_snapshot=reference_market_snapshot,
                    health_snapshot=health_snapshot,
                    activation_revision=activation_revision,
                    runtime_generation=self._runtime_generation,
                )
                unit_of_work.projections.add_evaluation_result(
                    result,
                    position_lots=unit_of_work.positions.list_open_lots(identity.symbol),
                )
                snapshot_event = self._append_snapshot_event(unit_of_work, result)
                unit_of_work.projections.advance_decision_head(
                    result=result,
                    event_sequence=snapshot_event.sequence,
                    activation_revision=activation_revision,
                )
                publication_event = snapshot_event
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
                        committed_event = (
                            unit_of_work.alerts.enqueue_recoverable(payload)
                            if self._recovery_delivery
                            else unit_of_work.alerts.enqueue(payload)
                        )
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
        await self._publish_committed_events((publication_event, health_event))
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
            pending = unit_of_work.projections.list_pending_official_closes(symbol=symbol)
            health = unit_of_work.health.get_symbol(symbol)
        if pending:
            if len(pending) != 1:
                raise ValueError("one symbol cannot retain multiple pending close identities")
            return pending[0].trade_date
        if health is None or health.status is not SymbolHealthStatus.CLOSE_PENDING:
            return None
        pending_date, _resume = _close_pending_payload(health.gap_json)
        return pending_date

    async def run_official_close_batch(
        self,
        *,
        plans: tuple[TradePlan, ...],
        trade_date: date,
        evaluated_at: datetime,
        close_attempt: int,
    ) -> tuple[OfficialCloseCycleResult, ...]:
        """Union index needs, then serialize official-close evaluation for a plan batch."""

        if type(plans) is not tuple or any(not isinstance(plan, TradePlan) for plan in plans):
            raise TypeError("plans must be a tuple of TradePlan values")
        if len(plans) > 10:
            raise ValueError("runtime supports at most 10 active plans")
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        if type(close_attempt) is not int or close_attempt < 1:
            raise ValueError("close_attempt must be a positive integer")
        canonical_evaluated_at = _ceil_to_whole_second(evaluated_at)
        cutoff = datetime.combine(
            trade_date,
            time(15, 0),
            canonical_evaluated_at.tzinfo,
        )
        prepared = (
            None
            if self._market_index_service is None
            else await self._market_index_service.prepare(
                plans=plans,
                decision_cutoff=cutoff,
                observed_no_later_than=canonical_evaluated_at,
            )
        )
        if prepared is not None:
            prepared, events = self._persist_market_index_batch(prepared)
            await self._publish_committed_events(events)
        results: list[OfficialCloseCycleResult] = []
        async with self._official_serial:
            for plan in plans:
                try:
                    results.append(
                        await self._run_official_close_unlocked(
                            plan=plan,
                            trade_date=trade_date,
                            evaluated_at=canonical_evaluated_at,
                            close_attempt=close_attempt,
                            reference_market_snapshot=(
                                None if prepared is None else prepared.snapshot_for_plan(plan)
                            ),
                        )
                    )
                except StaleActivationGenerationError:
                    continue
        return tuple(results)

    async def run_official_close(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        close_attempt: int,
    ) -> OfficialCloseCycleResult:
        """Reconcile one official date without provider or publisher I/O in a transaction."""

        evaluated_at = _ceil_to_whole_second(evaluated_at)
        reference_market_snapshot = None
        if self._market_index_service is not None:
            cutoff = datetime.combine(trade_date, time(15, 0), evaluated_at.tzinfo)
            prepared = await self._market_index_service.prepare(
                plans=(plan,),
                decision_cutoff=cutoff,
                observed_no_later_than=evaluated_at,
            )
            prepared, events = self._persist_market_index_batch(prepared)
            await self._publish_committed_events(events)
            reference_market_snapshot = prepared.snapshot_for_plan(plan)
        async with self._official_serial:
            return await self._run_official_close_unlocked(
                plan=plan,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                close_attempt=close_attempt,
                reference_market_snapshot=reference_market_snapshot,
            )

    async def _run_official_close_unlocked(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        close_attempt: int,
        reference_market_snapshot: MarketIndexSnapshot | None,
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
        canonical_evaluated_at = _ceil_to_whole_second(evaluated_at)
        source_as_of = datetime.combine(
            trade_date,
            time(15, 0),
            canonical_evaluated_at.tzinfo,
        )
        if canonical_evaluated_at < source_as_of:
            raise ValueError("official close cannot be evaluated before the 15:00 cutoff")
        activation_revision = self._capture_plan_activation_revision(plan)

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
        if await self._official_close_completed(
            plan=plan,
            trade_date=trade_date,
            evaluated_at=canonical_evaluated_at,
            activation_revision=activation_revision,
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
        observed_at = await self._post_fetch_official_observed_at(canonical_evaluated_at)
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
            activation_revision=activation_revision,
        )
        reconciliation, official_history, pending_event = persisted
        await self._publish_committed_events((pending_event,))
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
        if not isinstance(context, EvaluationContext):
            raise TypeError("official_context_builder must return an EvaluationContext")
        context = context.model_copy(
            update={"reference_market_snapshot": reference_market_snapshot}
        )
        self._validate_official_context(
            plan=plan,
            facts=facts,
            context=context,
            reference_market_snapshot=reference_market_snapshot,
        )
        result = self._evaluator(context)
        self._validate_official_result(plan=plan, facts=facts, result=result)

        committed_event: AlertEvent | None = None
        publication_event: MonitorEvent | None = None
        projection_health_event: MonitorEvent | None = None
        with self._unit_of_work_factory() as unit_of_work:
            self._require_evaluated_plan_active(
                unit_of_work,
                plan,
                expected_revision=activation_revision,
                market_date=trade_date,
            )
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
                projection_health_event = self._persist_projection_dependencies(
                    unit_of_work,
                    result,
                    plan=plan,
                    reference_market_snapshot=reference_market_snapshot,
                    health_snapshot=None,
                    activation_revision=activation_revision,
                    runtime_generation=self._runtime_generation,
                )
                unit_of_work.projections.add_evaluation_result(
                    result,
                    position_lots=unit_of_work.positions.list_open_lots(identity.symbol),
                )
                snapshot_event = self._append_snapshot_event(unit_of_work, result)
                unit_of_work.projections.advance_decision_head(
                    result=result,
                    event_sequence=snapshot_event.sequence,
                    activation_revision=activation_revision,
                )
                publication_event = snapshot_event
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
                        committed_event = (
                            unit_of_work.alerts.enqueue_recoverable(payload)
                            if self._recovery_delivery
                            else unit_of_work.alerts.enqueue(payload)
                        )
                        publication_event = unit_of_work.events.get(payload.event_id)
            health_event = self._clear_close_pending(
                unit_of_work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=trade_date,
                evaluated_at=canonical_evaluated_at,
                activation_revision=activation_revision,
                runtime_generation=self._runtime_generation,
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
        await self._publish_committed_events(
            (publication_event, projection_health_event, health_event)
        )
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

    async def _official_close_completed(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        activation_revision: int,
    ) -> bool:
        health_event: MonitorEvent | None = None
        with self._unit_of_work_factory() as unit_of_work:
            self._require_evaluated_plan_active(
                unit_of_work,
                plan,
                expected_revision=activation_revision,
                market_date=trade_date,
            )
            completed = unit_of_work.evaluations.has_claim(
                plan_hash=plan_sha256(plan),
                symbol=plan.symbol,
                evaluation_kind=EvaluationKind.OFFICIAL_CLOSE,
                bucket_end=None,
                official_trade_date=trade_date,
                formula_version=plan.monitoring.indicator_formula_version,
            )
            if completed:
                health_event = self._clear_close_pending(
                    unit_of_work,
                    plan=plan,
                    symbol=plan.symbol,
                    trade_date=trade_date,
                    evaluated_at=evaluated_at,
                    activation_revision=activation_revision,
                    runtime_generation=self._runtime_generation,
                )
                unit_of_work.commit()
        await self._publish_committed_events((health_event,))
        return completed

    def _persist_official_market_context(
        self,
        *,
        plan: TradePlan,
        trade_date: date,
        evaluated_at: datetime,
        source_as_of: datetime,
        incoming: tuple[DailyBar, ...],
        activation_revision: int,
    ) -> tuple[CloseReconciliationIntent, tuple[DailyBar, ...], MonitorEvent]:
        with self._unit_of_work_factory() as unit_of_work:
            self._require_evaluated_plan_active(
                unit_of_work,
                plan,
                expected_revision=activation_revision,
                market_date=trade_date,
            )
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
            pending_event = self._mark_close_pending(
                unit_of_work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                activation_revision=activation_revision,
                runtime_generation=self._runtime_generation,
            )
            unit_of_work.commit()
        if source_as_of > evaluated_at:  # pragma: no cover - validated by caller
            raise ValueError("official source cutoff cannot follow evaluation")
        return reconciliation, official_history, pending_event

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
    def _validated_prefetched_minutes(
        plans: object,
        minutes_by_symbol: object,
    ) -> dict[str, tuple[MinuteBar, ...]]:
        if type(plans) is not tuple or any(not isinstance(plan, TradePlan) for plan in plans):
            raise TypeError("plans must be a tuple of TradePlan values")
        if not isinstance(minutes_by_symbol, Mapping):
            raise TypeError("minutes_by_symbol must be a mapping")
        expected_symbols = {plan.symbol for plan in plans}
        if set(minutes_by_symbol) != expected_symbols:
            raise ValueError("minutes_by_symbol must contain exactly the due plan symbols")
        validated: dict[str, tuple[MinuteBar, ...]] = {}
        for symbol, minutes in minutes_by_symbol.items():
            if type(symbol) is not str or type(minutes) is not tuple:
                raise TypeError("prefetched minute batches must use string keys and tuple values")
            if len(minutes) > _MAX_FETCHED_MINUTES or any(
                not isinstance(minute, MinuteBar) for minute in minutes
            ):
                raise ValueError("prefetched minute batches must contain normalized bounded rows")
            validated[symbol] = minutes
        return validated

    @staticmethod
    def _validate_context(
        *,
        plan: TradePlan,
        facts: IntradayMarketFacts,
        context: object,
        reference_market_snapshot: MarketIndexSnapshot | None,
        health_snapshot: SymbolHealthSnapshot | None,
    ) -> None:
        if not isinstance(context, EvaluationContext):
            raise TypeError("context_builder must return an EvaluationContext")
        if context.plan != plan or context.plan_hash != plan_sha256(plan):
            raise ValueError("evaluation context must match the requested plan")
        if context.reference_market_snapshot != reference_market_snapshot:
            raise ValueError("evaluation context must retain the shared market-index snapshot")
        if reference_market_snapshot is not None and (
            reference_market_snapshot.observed_at > facts.evaluated_at
        ):
            raise ValueError("index snapshot observation cannot follow evaluation time")
        if health_snapshot is not None and context.data_health != health_snapshot.data_health:
            raise ValueError("evaluation context must retain the captured runtime health")
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
    def _validate_runtime_health_snapshot(
        *,
        plan: TradePlan,
        facts: IntradayMarketFacts,
        health_snapshot: SymbolHealthSnapshot,
    ) -> None:
        if not isinstance(health_snapshot, SymbolHealthSnapshot):
            raise TypeError("health snapshot must be a SymbolHealthSnapshot")
        if (
            health_snapshot.symbol != plan.symbol
            or health_snapshot.target_end != facts.bucket_end
            or health_snapshot.observed_at != facts.evaluated_at
        ):
            raise ValueError("runtime health snapshot must match symbol, target, and observation")

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
        reference_market_snapshot: MarketIndexSnapshot | None,
    ) -> None:
        if not isinstance(context, EvaluationContext):
            raise TypeError("official_context_builder must return an EvaluationContext")
        if context.plan != plan or context.plan_hash != plan_sha256(plan):
            raise ValueError("official evaluation context must match the requested plan")
        if context.reference_market_snapshot != reference_market_snapshot:
            raise ValueError("official context must retain the shared market-index snapshot")
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
        plan: TradePlan,
        symbol: str,
        trade_date: date,
        evaluated_at: datetime,
        activation_revision: int,
        runtime_generation: UUID = LEGACY_RUNTIME_GENERATION,
    ) -> MonitorEvent:
        current = unit_of_work.health.get_symbol(symbol)
        if current is not None and current.status is SymbolHealthStatus.CLOSE_PENDING:
            persisted_date, resume = _close_pending_payload(current.gap_json)
            if persisted_date != trade_date:
                raise ValueError("one symbol cannot retain two CLOSE_PENDING dates")
            existing_pending = unit_of_work.projections.get_pending_official_close(
                symbol=symbol,
                trade_date=trade_date,
            )
            if existing_pending is None:
                raise ValueError("CLOSE_PENDING health has no exact durable identity")
            resume_projection = existing_pending.pending.get("resumeProjection")
            resume_projection_generation = existing_pending.pending.get(
                "resumeProjectionGeneration"
            )
        else:
            resume = {
                "status": (
                    SymbolHealthStatus.BLOCKED.value if current is None else current.status.value
                ),
                "gaps": [] if current is None else _json_value(current.gap_json),
                "errorStreak": 0 if current is None else current.error_streak,
                "latestBarEnd": (
                    None
                    if current is None or current.latest_bar_end is None
                    else current.latest_bar_end.isoformat()
                ),
                "dataAgeSeconds": 0 if current is None else current.data_age_seconds,
            }
            current_projection = unit_of_work.projections.get_symbol_health(symbol)
            resume_projection = (
                None if current_projection is None else current_projection.projection
            )
            resume_projection_generation = (
                None if current_projection is None else str(current_projection.runtime_generation)
            )
        latest_bar_end = None if current is None else current.latest_bar_end
        data_age_seconds = (
            0
            if latest_bar_end is None
            else max(0, int((evaluated_at - latest_bar_end).total_seconds()))
        )
        after = unit_of_work.health.upsert_symbol(
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
        unit_of_work.projections.put_symbol_health(
            symbol=symbol,
            revision=after.revision,
            activation_revision=activation_revision,
            runtime_generation=runtime_generation,
            projection={
                "symbol": symbol,
                "observedAt": evaluated_at,
                "targetEnd": datetime.combine(
                    trade_date,
                    time(15, 0),
                    evaluated_at.tzinfo,
                ),
                "status": "CLOSE_PENDING",
                "latestBarEnd": latest_bar_end,
                "dataAgeSeconds": None if latest_bar_end is None else data_age_seconds,
                "requiredDataComplete": False,
                "fresh": False,
                "gaps": (),
                "consecutiveIncompleteBuckets": 0,
                "lastRequiredBucketEnd": None,
                "errorCode": SymbolHealthErrorCode.INCOMPLETE_BUCKET,
                "actionable": False,
            },
            observed_at=evaluated_at,
        )
        unit_of_work.projections.put_pending_official_close(
            plan_hash=plan_sha256(plan),
            symbol=symbol,
            trade_date=trade_date,
            formula_version=plan.monitoring.indicator_formula_version,
            pending={
                "latestBarEnd": (None if latest_bar_end is None else latest_bar_end.isoformat()),
                "resume": resume,
                "resumeProjection": resume_projection,
                "resumeProjectionGeneration": resume_projection_generation,
            },
            observed_at=evaluated_at,
        )
        return unit_of_work.events.get(
            monitor_event_id(
                MonitorEventType.SYMBOL_HEALTH_UPDATED,
                after.symbol,
                str(after.revision),
            )
        )

    @staticmethod
    def _clear_close_pending(
        unit_of_work: UnitOfWork,
        *,
        plan: TradePlan,
        symbol: str,
        trade_date: date,
        evaluated_at: datetime,
        activation_revision: int,
        runtime_generation: UUID = LEGACY_RUNTIME_GENERATION,
    ) -> MonitorEvent | None:
        pending = unit_of_work.projections.get_pending_official_close(
            symbol=symbol,
            trade_date=trade_date,
        )
        current = unit_of_work.health.get_symbol(symbol)
        if pending is None:
            if current is None or current.status is not SymbolHealthStatus.CLOSE_PENDING:
                return None
            raise ValueError("official close pending identity is missing")
        cleared = unit_of_work.projections.clear_pending_official_close(
            plan_hash=plan_sha256(plan),
            symbol=symbol,
            trade_date=trade_date,
            formula_version=plan.monitoring.indicator_formula_version,
        )
        if not cleared:
            raise ValueError("official close pending identity does not match the active plan")
        if current is None or current.status is not SymbolHealthStatus.CLOSE_PENDING:
            return None
        persisted_date, resume = _close_pending_payload(current.gap_json)
        if persisted_date != trade_date:
            raise ValueError("cannot clear another official close pending date")
        raw_resume_projection = pending.pending.get("resumeProjection")
        resume_projection = (
            None
            if raw_resume_projection is None
            else _validate_persisted_symbol_health(raw_resume_projection)
        )
        if resume_projection is not None and resume_projection.symbol != symbol:
            raise ValueError("pending health projection crosses symbol identity")
        raw_resume_generation = pending.pending.get("resumeProjectionGeneration")
        resume_projection_generation = (
            None
            if resume_projection is None
            else LEGACY_RUNTIME_GENERATION
            if raw_resume_generation is None
            else _runtime_generation(
                raw_resume_generation,
                name="CLOSE_PENDING resume projection generation",
            )
        )
        latest_bar_end = _optional_market_datetime(
            resume.get("latestBarEnd", pending.pending.get("latestBarEnd")),
            name="CLOSE_PENDING resume latestBarEnd",
        )
        restored_status = cast(SymbolHealthStatus, resume["status"])
        restored_gaps = resume["gaps"]
        restored_streak = cast(int, resume["errorStreak"])
        raw_data_age_seconds = resume.get("dataAgeSeconds")
        data_age_seconds = (
            max(0, int((evaluated_at - latest_bar_end).total_seconds()))
            if raw_data_age_seconds is None and latest_bar_end is not None
            else 0
            if raw_data_age_seconds is None
            else cast(int, raw_data_age_seconds)
        )
        after = unit_of_work.health.upsert_symbol(
            symbol=symbol,
            status=restored_status,
            latest_bar_end=latest_bar_end,
            data_age_seconds=data_age_seconds,
            gaps=restored_gaps,
            error_streak=restored_streak,
            expected_revision=current.revision,
        )
        if resume_projection is None:
            restored_public_gaps = _legacy_resume_gaps(restored_gaps)
            target_end = datetime.combine(
                trade_date,
                time(15, 0),
                evaluated_at.tzinfo,
            )
            public_status = (
                SymbolHealthStatus.STALE
                if restored_status is SymbolHealthStatus.LIVE
                else restored_status
            )
            error_code = {
                SymbolHealthStatus.STALE: SymbolHealthErrorCode.STALE_DATA,
                SymbolHealthStatus.GAPPED: SymbolHealthErrorCode.HISTORY_GAP,
                SymbolHealthStatus.DEGRADED: SymbolHealthErrorCode.PROVIDER_BLOCKED,
                SymbolHealthStatus.BLOCKED: SymbolHealthErrorCode.INVALID_CONTEXT,
                SymbolHealthStatus.STARTING: SymbolHealthErrorCode.INVALID_CONTEXT,
            }.get(public_status)
            projection: Mapping[str, object] = {
                "symbol": symbol,
                "observedAt": evaluated_at,
                "targetEnd": target_end,
                "status": public_status,
                "latestBarEnd": latest_bar_end,
                "dataAgeSeconds": (
                    None
                    if latest_bar_end is None
                    else max(0, int((evaluated_at - latest_bar_end).total_seconds()))
                ),
                "requiredDataComplete": False,
                "fresh": False,
                "gaps": restored_public_gaps,
                "consecutiveIncompleteBuckets": restored_streak,
                "lastRequiredBucketEnd": target_end if restored_streak > 0 else None,
                "errorCode": error_code,
                "actionable": False,
            }
            projection_observed_at = evaluated_at
        else:
            projection = resume_projection.model_dump(
                mode="python",
                round_trip=True,
                by_alias=True,
            )
            projection_observed_at = resume_projection.observed_at
        unit_of_work.projections.put_symbol_health(
            symbol=symbol,
            revision=after.revision,
            activation_revision=activation_revision,
            runtime_generation=(
                runtime_generation
                if resume_projection_generation is None
                else resume_projection_generation
            ),
            projection=projection,
            observed_at=projection_observed_at,
        )
        return unit_of_work.events.get(
            monitor_event_id(
                MonitorEventType.SYMBOL_HEALTH_UPDATED,
                after.symbol,
                str(after.revision),
            )
        )

    def _persist_market_index_batch(
        self,
        prepared: RuntimeMarketIndexBatch,
    ) -> tuple[RuntimeMarketIndexBatch, tuple[MonitorEvent, ...]]:
        if not isinstance(prepared, RuntimeMarketIndexBatch):
            raise TypeError("prepared must be a RuntimeMarketIndexBatch")
        canonical: dict[MarketIndexCode, MarketIndexSnapshot] = {}
        events: list[MonitorEvent] = []
        with self._unit_of_work_factory() as unit_of_work:
            previous_recoveries = {
                record[0]: record
                for record in unit_of_work.projections.list_market_index_recoveries()
            }
            for index_code, snapshot in sorted(
                prepared.snapshots_by_index.items(),
                key=lambda item: item[0].value,
            ):
                validate_market_index_snapshot_integrity(snapshot)
                provider_revision = snapshot.cache_key.provider_content_revision
                stored = unit_of_work.projections.get_market_index_snapshot_revision(
                    mapping_version=snapshot.mapping_version,
                    index_code=snapshot.index_code,
                    decision_cutoff=snapshot.decision_cutoff,
                    request_set_hash=snapshot.request_set_hash,
                    provider_content_revision=provider_revision,
                )
                current_head = unit_of_work.projections.get_market_index_head(
                    mapping_version=snapshot.mapping_version,
                    index_code=snapshot.index_code,
                    decision_cutoff=snapshot.decision_cutoff,
                    request_set_hash=snapshot.request_set_hash,
                )
                if (
                    current_head is not None
                    and current_head.snapshot.health is MarketIndexHealth.LIVE
                    and snapshot.health is not MarketIndexHealth.LIVE
                ) or (
                    current_head is not None
                    and current_head.snapshot.health is MarketIndexHealth.BLOCKED
                    and snapshot.health is MarketIndexHealth.BLOCKED
                    and current_head.snapshot.issues == snapshot.issues
                ):
                    canonical[index_code] = current_head.snapshot
                    continue
                if stored is not None:
                    if not _equivalent_market_index_capture(stored.snapshot, snapshot):
                        raise ProjectionIdentityConflictError(
                            "Market-index provider revision changed canonical content"
                        )
                    unit_of_work.projections.advance_market_index_head(
                        stored.snapshot,
                        provider_content_revision=provider_revision,
                        observed_at=snapshot.observed_at,
                    )
                    canonical[index_code] = stored.snapshot
                else:
                    unit_of_work.projections.put_market_index_snapshot(
                        snapshot,
                        provider_content_revision=provider_revision,
                    )
                    unit_of_work.projections.advance_market_index_head(
                        snapshot,
                        provider_content_revision=provider_revision,
                    )
                    canonical[index_code] = snapshot
                canonical_snapshot = canonical[index_code]
                if (
                    current_head is None
                    or current_head.snapshot.snapshot_hash != canonical_snapshot.snapshot_hash
                ):
                    events.append(
                        unit_of_work.events.append(
                            MonitorEventDraft(
                                event_id=monitor_event_id(
                                    MonitorEventType.MARKET_INDEX_UPDATED,
                                    canonical_snapshot.index_code.value,
                                    canonical_snapshot.decision_cutoff.isoformat(),
                                    canonical_snapshot.request_set_hash,
                                    canonical_snapshot.snapshot_hash,
                                    snapshot.observed_at.isoformat(),
                                ),
                                event_type=MonitorEventType.MARKET_INDEX_UPDATED,
                                aggregate_id=canonical_snapshot.index_code.value,
                                payload=MonitorEventPayload(
                                    entity_id=canonical_snapshot.index_code.value,
                                    revision=canonical_snapshot.revision,
                                    status=canonical_snapshot.health.value,
                                ),
                                occurred_at=snapshot.observed_at,
                            )
                        )
                    )
            if self._market_index_service is not None:
                recovery_records = self._market_index_service.recovery_records()
                current_recoveries = {record[0]: record for record in recovery_records}
                unit_of_work.projections.replace_market_index_recoveries(recovery_records)
                already_notified = {event.aggregate_id for event in events}
                for code, canonical_snapshot in canonical.items():
                    if (
                        code.value in already_notified
                        or previous_recoveries.get(code) == current_recoveries.get(code)
                    ):
                        continue
                    observed_at = prepared.snapshots_by_index[code].observed_at
                    state = current_recoveries.get(code)
                    events.append(
                        unit_of_work.events.append(
                            MonitorEventDraft(
                                event_id=monitor_event_id(
                                    MonitorEventType.MARKET_INDEX_UPDATED,
                                    code.value,
                                    canonical_snapshot.decision_cutoff.isoformat(),
                                    "recovery-state",
                                    observed_at.isoformat(),
                                    "done" if state is None else str(state[3]),
                                ),
                                event_type=MonitorEventType.MARKET_INDEX_UPDATED,
                                aggregate_id=code.value,
                                payload=MonitorEventPayload(
                                    entity_id=code.value,
                                    revision=canonical_snapshot.revision,
                                    status=canonical_snapshot.health.value,
                                ),
                                occurred_at=observed_at,
                            )
                        )
                    )
            unit_of_work.commit()
        return (
            RuntimeMarketIndexBatch(
                decision_cutoff=prepared.decision_cutoff,
                snapshots_by_index=MappingProxyType(canonical),
            ),
            tuple(events),
        )

    @staticmethod
    def _require_evaluated_plan_active(
        unit_of_work: UnitOfWork,
        plan: TradePlan,
        *,
        expected_revision: int,
        market_date: date,
    ) -> None:
        if not activation_is_eligible_on(plan.activation, market_date):
            raise StaleActivationGenerationError(plan.symbol)
        activation_state = unit_of_work.plans.get_activation_state(plan.symbol)
        # The runtime service is also used as a narrow persistence primitive in
        # tests and offline tooling that have no plan registry.  Once a symbol
        # has entered the registry, however, its activation state is
        # authoritative and a concurrent deactivation/rotation must fail closed.
        if activation_state is None:
            if expected_revision != 1:
                raise StaleActivationGenerationError(plan.symbol)
            return
        if activation_state.revision != expected_revision:
            raise StaleActivationGenerationError(plan.symbol)
        active = unit_of_work.plans.get_active(plan.symbol)
        if active is None or activation_state.plan_version_id != active.plan_version_id:
            raise StaleActivationGenerationError(plan.symbol)
        details = unit_of_work.plans.get_version_details(active.plan_version_id)
        if (
            details is None
            or details.plan_hash != plan_sha256(plan)
            or load_plan_json(details.payload_json) != plan
        ):
            raise StaleActivationGenerationError(plan.symbol)

    @staticmethod
    def _require_symbol_activation_revision(
        unit_of_work: UnitOfWork,
        *,
        symbol: str,
        expected_revision: int,
    ) -> None:
        state = unit_of_work.plans.get_activation_state(symbol)
        if state is None:
            if expected_revision != 1:
                raise StaleActivationGenerationError(symbol)
            return
        active = unit_of_work.plans.get_active(symbol)
        if (
            state.revision != expected_revision
            or active is None
            or active.revision != expected_revision
        ):
            raise StaleActivationGenerationError(symbol)

    def _capture_plan_activation_revision(self, plan: TradePlan) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            state = unit_of_work.plans.get_activation_state(plan.symbol)
            if state is None:
                return 1
            active = unit_of_work.plans.get_active(plan.symbol)
            if active is None or active.revision != state.revision:
                raise StaleActivationGenerationError(plan.symbol)
            details = unit_of_work.plans.get_version_details(active.plan_version_id)
            if (
                details is None
                or details.plan_hash != plan_sha256(plan)
                or load_plan_json(details.payload_json) != plan
            ):
                raise StaleActivationGenerationError(plan.symbol)
            return state.revision

    @staticmethod
    def _persist_projection_dependencies(
        unit_of_work: UnitOfWork,
        result: EvaluationResult,
        *,
        plan: TradePlan,
        reference_market_snapshot: MarketIndexSnapshot | None,
        health_snapshot: SymbolHealthSnapshot | None,
        activation_revision: int,
        runtime_generation: UUID,
    ) -> MonitorEvent:
        reference = result.snapshot.reference_market
        uses_index = bool(iter_plan_index_conditions(plan))
        if not uses_index and reference is not None:
            raise ValueError("stock-only plan cannot persist index-condition evidence")
        if uses_index and (reference is None) != (reference_market_snapshot is None):
            raise ValueError("result and context reference-market snapshots must agree")
        if uses_index and reference_market_snapshot is not None:
            if (
                reference is None
                or reference.snapshot_hash != reference_market_snapshot.snapshot_hash
            ):
                raise ValueError("result reference market crosses its immutable snapshot")
            stored = unit_of_work.projections.get_market_index_snapshot(
                reference_market_snapshot.snapshot_hash
            )
            if stored is None or stored.snapshot != reference_market_snapshot:
                raise ValueError("result reference market is not durably persisted")

        identity = result.evaluation_identity
        if isinstance(identity, IntradayEvaluationIdentity):
            target_end = identity.bucket_end
        elif isinstance(identity, OfficialCloseEvaluationIdentity):
            target_end = datetime.combine(
                identity.official_trade_date,
                time(15, 0),
                result.snapshot.evaluated_at.tzinfo,
            )
        else:  # pragma: no cover - closed EvaluationIdentity union
            raise TypeError("evaluation identity is not supported")

        health = result.snapshot.data_health
        if health_snapshot is not None and (
            health_snapshot.symbol != result.snapshot.symbol
            or health_snapshot.target_end != target_end
            or health_snapshot.observed_at != result.snapshot.evaluated_at
            or health_snapshot.data_health != health
        ):
            raise ValueError("runtime health snapshot must match its evaluation result")
        current_health = unit_of_work.health.get_symbol(result.snapshot.symbol)
        actionable = (
            health.status.value == "LIVE" and health.required_data_complete and health.fresh
        )
        error_code = None if health_snapshot is None else health_snapshot.error_code
        if not actionable and error_code is None:
            error_code = {
                "STALE": SymbolHealthErrorCode.STALE_DATA,
                "GAPPED": SymbolHealthErrorCode.HISTORY_GAP,
                "BLOCKED": SymbolHealthErrorCode.PROVIDER_BLOCKED,
            }.get(health.status.value, SymbolHealthErrorCode.INVALID_CONTEXT)
        gaps = () if health_snapshot is None else health_snapshot.gaps
        incomplete_streak = (
            (0 if actionable else 1)
            if health_snapshot is None
            else health_snapshot.consecutive_incomplete_buckets
        )
        after = unit_of_work.health.upsert_symbol(
            symbol=result.snapshot.symbol,
            status=SymbolHealthStatus(health.status.value),
            latest_bar_end=health.latest_bar_end,
            data_age_seconds=0 if health.data_age_seconds is None else health.data_age_seconds,
            gaps=tuple(gap.isoformat() for gap in gaps),
            error_streak=(
                0
                if actionable
                else 1
                if current_health is None
                else current_health.error_streak + 1
            ),
            expected_revision=0 if current_health is None else current_health.revision,
        )
        unit_of_work.projections.put_symbol_health(
            symbol=result.snapshot.symbol,
            revision=after.revision,
            activation_revision=activation_revision,
            runtime_generation=runtime_generation,
            projection={
                "symbol": result.snapshot.symbol,
                "observedAt": result.snapshot.evaluated_at,
                "targetEnd": target_end,
                "status": health.status,
                "latestBarEnd": health.latest_bar_end,
                "dataAgeSeconds": health.data_age_seconds,
                "requiredDataComplete": health.required_data_complete,
                "fresh": health.fresh,
                "gaps": gaps,
                "consecutiveIncompleteBuckets": incomplete_streak,
                "lastRequiredBucketEnd": (
                    health_snapshot.last_required_bucket_end
                    if health_snapshot is not None
                    else target_end
                    if incomplete_streak > 0
                    else None
                ),
                "errorCode": error_code,
                "actionable": actionable,
            },
            observed_at=result.snapshot.evaluated_at,
        )
        return unit_of_work.events.get(
            monitor_event_id(
                MonitorEventType.SYMBOL_HEALTH_UPDATED,
                after.symbol,
                str(after.revision),
            )
        )

    async def _publish_committed_events(
        self,
        events: tuple[MonitorEvent | None, ...],
    ) -> None:
        published: set[UUID] = set()
        for event in events:
            if event is None or event.event_id in published:
                continue
            publication = self._publisher(event)
            if isawaitable(publication):
                await publication
            published.add(event.event_id)

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


class RuntimeDeadlineCoordinator:
    """Own one stock acquisition and reuse its immutable rows for a whole deadline."""

    def __init__(
        self,
        *,
        clock: Clock,
        active_plans: ActivePlans,
        symbol_service: SymbolService,
        evaluation_service: RuntimeEvaluationService,
        explicit_evaluation_service: ExplicitRuntimeEvaluationService | None = None,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not callable(active_plans):
            raise TypeError("active_plans must be callable")
        if not isinstance(symbol_service, SymbolService):
            raise TypeError("symbol_service must be a SymbolService")
        if not isinstance(evaluation_service, RuntimeEvaluationService):
            raise TypeError("evaluation_service must be a RuntimeEvaluationService")
        if explicit_evaluation_service is not None and not isinstance(
            explicit_evaluation_service,
            ExplicitRuntimeEvaluationService,
        ):
            raise TypeError(
                "explicit_evaluation_service must be an ExplicitRuntimeEvaluationService"
            )
        self._clock = clock
        self._active_plans = active_plans
        self._symbol_service = symbol_service
        self._evaluation_service = evaluation_service
        self._explicit_evaluation_service = explicit_evaluation_service

    async def run_deadline(
        self,
        deadline: MarketDeadline,
    ) -> tuple[
        IntradayCycleResult | OfficialCloseCycleResult | ExplicitRuntimeCycleResult,
        ...,
    ]:
        """Execute one scheduler deadline without performing duplicate quote fetches."""

        if not isinstance(deadline, MarketDeadline):
            raise TypeError("deadline must be a MarketDeadline")
        plans = self._validated_active_plans(self._active_plans())
        legacy_plans = tuple(plan for plan in plans if isinstance(plan, TradePlan))
        explicit_plans = tuple(plan for plan in plans if isinstance(plan, ExplicitTradePlan))
        if explicit_plans and self._explicit_evaluation_service is None:
            raise RuntimeError("explicit plan runtime is not composed")
        observed_at = max(_canonical_shanghai(self._clock.now()), deadline.due_at)
        if deadline.kind is DeadlineKind.OFFICIAL_CLOSE:
            if deadline.close_attempt is None:  # protected by MarketDeadline validation
                raise ValueError("official-close deadline requires close_attempt")
            return await self._evaluation_service.run_official_close_batch(
                plans=legacy_plans,
                trade_date=deadline.trade_date,
                evaluated_at=observed_at,
                close_attempt=deadline.close_attempt,
            )

        bar_end = deadline.bar_end
        if bar_end is None:  # protected by MarketDeadline validation
            raise ValueError("realtime deadline requires bar_end")
        symbols = tuple(plan.symbol for plan in plans)
        restore_states = self._evaluation_service.load_persisted_symbol_health(symbols)
        self._symbol_service.restore_health(symbols=symbols, states=restore_states)
        activation_revisions = {state.symbol: state.activation_revision for state in restore_states}
        market_index_batch = None
        if legacy_plans and five_minute_bucket_end(bar_end) == bar_end:
            market_index_batch = await self._evaluation_service.prepare_intraday_market_indexes(
                plans=legacy_plans,
                bucket_end=bar_end,
                evaluated_at=observed_at,
            )
        batch = await self._symbol_service.run_realtime_batch(
            bar_end=bar_end,
            observed_at=observed_at,
            symbols=symbols,
        )
        observed_at = batch.observed_at
        if five_minute_bucket_end(bar_end) != bar_end:
            await self._evaluation_service.persist_symbol_health_batch(
                tuple(context.health for context in batch.contexts),
                activation_revisions={
                    context.symbol: activation_revisions[context.symbol]
                    for context in batch.contexts
                },
            )
            return ()
        complete_contexts = {
            context.symbol: context
            for context in batch.contexts
            if context.five_minute_bar is not None
        }
        await self._evaluation_service.persist_symbol_health_batch(
            tuple(
                context.health
                for context in batch.contexts
                if context.symbol not in complete_contexts
            ),
            activation_revisions={
                context.symbol: activation_revisions[context.symbol]
                for context in batch.contexts
                if context.symbol not in complete_contexts
            },
        )
        due_plans = tuple(plan for plan in plans if plan.symbol in complete_contexts)
        if not due_plans:
            return ()
        due_legacy_plans = tuple(
            plan for plan in due_plans if isinstance(plan, TradePlan)
        )
        due_explicit_plans = tuple(
            plan for plan in due_plans if isinstance(plan, ExplicitTradePlan)
        )
        await self._evaluation_service.persist_symbol_health_batch(
            tuple(complete_contexts[plan.symbol].health for plan in due_explicit_plans),
            activation_revisions={
                plan.symbol: activation_revisions[plan.symbol]
                for plan in due_explicit_plans
            },
        )
        minutes_by_symbol = {
            symbol: context.minutes for symbol, context in complete_contexts.items()
        }
        legacy_results = await self._evaluation_service.run_intraday_batch_from_minutes(
            plans=due_legacy_plans,
            bucket_end=bar_end,
            evaluated_at=observed_at,
            minutes_by_symbol={
                plan.symbol: minutes_by_symbol[plan.symbol]
                for plan in due_legacy_plans
            },
            health_by_symbol={
                plan.symbol: complete_contexts[plan.symbol].health
                for plan in due_legacy_plans
            },
            activation_revisions={
                plan.symbol: activation_revisions[plan.symbol]
                for plan in due_legacy_plans
            },
            market_index_batch=market_index_batch,
        )
        explicit_service = self._explicit_evaluation_service
        if due_explicit_plans and explicit_service is None:  # guarded before acquisition
            raise RuntimeError("explicit plan runtime is not composed")
        explicit_results = []
        if explicit_service is not None:
            for plan in due_explicit_plans:
                explicit_results.append(
                    await explicit_service.run_intraday_and_publish(
                        plan=plan,
                        target_bucket_end=bar_end,
                        evaluated_at=observed_at,
                    )
                )
        by_symbol = {
            result.evaluation_result.symbol: result for result in explicit_results
        }
        by_symbol.update(
            {
                result.facts.symbol: result
                for result in legacy_results
                if result.facts is not None
            }
        )
        if len(by_symbol) != len(due_plans):
            raise RuntimeError("deadline evaluation omitted a due plan")
        return tuple(by_symbol[plan.symbol] for plan in due_plans)

    @staticmethod
    def _validated_active_plans(value: object) -> tuple[ExecutableTradePlan, ...]:
        if type(value) is not tuple or any(
            not isinstance(plan, (TradePlan, ExplicitTradePlan)) for plan in value
        ):
            raise TypeError("active_plans must return executable trade plans")
        if len(value) > 10:
            raise ActiveSymbolLimitError(len(value))
        return value


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
        self._schedule_owner: asyncio.Task[object] | None = None
        self._schedule_wait_task: asyncio.Task[MarketDeadline | None] | None = None
        self._work_tasks: set[asyncio.Task[object]] = set()
        self._last_deadline_at: datetime | None = None
        self._unexpected_run_exit = False
        self._cleanup_failed = False
        self._cleanup_error: BaseException | None = None
        self._stopping = False
        self._cleanup_complete = False
        self._stop_task: asyncio.Task[None] | None = None
        self._shutdown_requested_event: asyncio.Event | None = None
        self._runtime_generation = uuid4()

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

    @property
    def runtime_generation(self) -> UUID:
        return self._runtime_generation

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
            runtime_generation=self._runtime_generation,
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
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
            if not self._stopping:
                try:
                    await self.stop()
                except BaseException:
                    pass
            raise
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

        schedule_owner = self._claim_schedule_owner()
        owns_startup = self._start_task is None and self._startup_result is None
        try:
            startup = await self.start()
            if startup.read_only or not self._accepting_work:
                return None
            deadline = await self._wait_for_next(after=None)
            if deadline is None or not self._accepting_work:
                return None
            self._advance_progress_deadline(deadline)
            return await self._execute_deadline(deadline)
        finally:
            try:
                if owns_startup:
                    await self.stop()
            finally:
                self._release_schedule_owner(schedule_owner)

    async def run(self) -> None:
        """Run scheduled deadlines until stopped, then close every owned resource."""

        schedule_owner = self._claim_schedule_owner()
        startup: RuntimeStartupResult | None = None
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
                self._advance_progress_deadline(deadline)
                try:
                    await self._execute_deadline(deadline)
                    following = self._scheduler.next_deadline(after=self._last_deadline_at)
                    self._next_poll_at = None if following is None else following.due_at
                except asyncio.CancelledError:
                    if not self._accepting_work:
                        break
                    raise
        finally:
            self._unexpected_run_exit = (
                startup is not None
                and startup.status is RuntimeServiceStatus.RUNNING
                and not self._stopping
            )
            try:
                await self.stop()
            finally:
                self._release_schedule_owner(schedule_owner)

    def _advance_progress_deadline(self, deadline: MarketDeadline) -> None:
        """Publish the following due time before current provider work can block."""

        self._last_deadline_at = deadline.due_at
        next_deadline = self._scheduler.next_deadline(after=self._last_deadline_at)
        if next_deadline is not None and not isinstance(next_deadline, MarketDeadline):
            raise TypeError("scheduler must return MarketDeadline or None")
        self._next_poll_at = None if next_deadline is None else next_deadline.due_at

    @property
    def unexpected_run_exit(self) -> bool:
        """Whether a RUNNING loop ended before an explicit stop request."""

        return self._unexpected_run_exit

    @property
    def cleanup_failed(self) -> bool:
        """Whether cleanup failed and a replacement runtime would be unsafe."""

        return self._cleanup_failed

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
        try:
            await asyncio.shield(stop_task)
        except asyncio.CancelledError:
            if stop_task.cancelled():
                self._record_cleanup_failure(RuntimeError("runtime cleanup task was cancelled"))
            raise
        except Exception as error:
            self._record_cleanup_failure(error)
            raise

    async def _stop_sequence(self, *, initiator: asyncio.Task[object] | None) -> None:
        """Run cleanup independently from any one public stop waiter."""

        self._stopping = True
        self._status = RuntimeServiceStatus.STOPPING
        self._accepting_work = False
        if self._shutdown_requested_event is not None:
            self._shutdown_requested_event.set()
        first_error: BaseException | None = None
        if not self._request_controller_closed:
            try:
                await self._invoke(self._request_controller.close)
            except BaseException as error:
                first_error = error
            else:
                self._request_controller_closed = not callable(
                    getattr(self._request_controller, "aclose", None)
                )
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
            first_error = RuntimeShutdownError(len(pending))
            if not self._request_controller_closed:
                try:
                    await self._invoke(
                        getattr(
                            self._request_controller,
                            "aclose",
                            self._request_controller.close,
                        )
                    )
                except BaseException:
                    pass
                else:
                    self._request_controller_closed = True
            raise first_error

        resources = (
            ("_dispatcher_closed", self._dispatcher.aclose),
            (
                "_request_controller_closed",
                getattr(
                    self._request_controller,
                    "aclose",
                    self._request_controller.close,
                ),
            ),
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
        self._cleanup_failed = False
        self._cleanup_error = None

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

    def _claim_schedule_owner(self) -> asyncio.Task[object]:
        owner = asyncio.current_task()
        if owner is None:  # pragma: no cover - public async methods always run in a task
            raise RuntimeError("runtime scheduling requires an asyncio task")
        existing = self._schedule_owner
        if existing is not None and not existing.done():
            raise RuntimeError("runtime scheduling loop is already active")
        self._schedule_owner = owner
        return owner

    def _release_schedule_owner(self, owner: asyncio.Task[object]) -> None:
        if self._schedule_owner is owner:
            self._schedule_owner = None

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

    def _observe_stop_result(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._record_cleanup_failure(RuntimeError("runtime cleanup task was cancelled"))
            return
        error = task.exception()
        if error is not None:
            self._record_cleanup_failure(error)

    def _record_cleanup_failure(self, error: BaseException) -> None:
        if self._cleanup_complete or self._cleanup_failed:
            return
        self._cleanup_failed = True
        self._cleanup_error = error

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


def _equivalent_market_index_capture(
    persisted: MarketIndexSnapshot,
    incoming: MarketIndexSnapshot,
) -> bool:
    """Match one provider revision while ignoring only capture-time metadata."""

    validate_market_index_snapshot_integrity(persisted)
    validate_market_index_snapshot_integrity(incoming)
    if persisted.observed_at > incoming.observed_at:
        return False

    def bar_content(bar: MarketIndexBar) -> object:
        return bar.model_dump(
            mode="python",
            round_trip=True,
            exclude={"observed_at"},
        )

    persisted_bars = persisted.five_minute_bars + persisted.official_daily_bars
    incoming_bars = incoming.five_minute_bars + incoming.official_daily_bars
    if len(persisted_bars) != len(incoming_bars) or any(
        old.observed_at > new.observed_at or bar_content(old) != bar_content(new)
        for old, new in zip(persisted_bars, incoming_bars, strict=True)
    ):
        return False
    old_latest = persisted.latest_completed_five_minute
    new_latest = incoming.latest_completed_five_minute
    if (old_latest is None) != (new_latest is None) or (
        old_latest is not None
        and new_latest is not None
        and (
            old_latest.observed_at > new_latest.observed_at
            or bar_content(old_latest) != bar_content(new_latest)
        )
    ):
        return False

    if len(persisted.indicator_facts) != len(incoming.indicator_facts) or any(
        old.model_dump(
            mode="python",
            round_trip=True,
            exclude={"source_bar_hash"},
        )
        != new.model_dump(
            mode="python",
            round_trip=True,
            exclude={"source_bar_hash"},
        )
        for old, new in zip(
            persisted.indicator_facts,
            incoming.indicator_facts,
            strict=True,
        )
    ):
        return False

    excluded = {
        "bar_set_hash",
        "five_minute_bars",
        "indicator_facts",
        "latest_completed_five_minute",
        "observed_at",
        "official_daily_bars",
        "snapshot_hash",
    }
    return persisted.model_dump(
        mode="python",
        round_trip=True,
        exclude=excluded,
    ) == incoming.model_dump(
        mode="python",
        round_trip=True,
        exclude=excluded,
    )


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


def _validate_persisted_symbol_health(value: object) -> _PersistedSymbolHealth:
    """Validate the actual JSON storage representation under strict model rules."""

    try:
        wire_value = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            default=_json_wire_default,
        )
        return _PersistedSymbolHealth.model_validate_json(wire_value)
    except TypeError, ValueError, RecursionError:
        raise ValueError("persisted symbol health projection is invalid") from None


def _optional_market_datetime(value: object, *, name: str) -> datetime | None:
    if value is None:
        return None
    candidate = value
    if type(value) is str:
        try:
            candidate = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{name} is invalid") from None
    try:
        return _SHANGHAI_DATETIME.validate_python(candidate, strict=True)
    except ValueError:
        raise ValueError(f"{name} is invalid") from None


def _runtime_generation(value: object, *, name: str) -> UUID:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a canonical UUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a canonical UUID string") from error
    if str(parsed) != value or parsed.version != 4:
        raise ValueError(f"{name} must be a canonical UUIDv4 string")
    return parsed


def _legacy_resume_gaps(value: object) -> tuple[datetime, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("persisted CLOSE_PENDING resume gaps are invalid")
    gaps: list[datetime] = []
    for item in value:
        gap = _optional_market_datetime(
            item,
            name="persisted CLOSE_PENDING resume gap",
        )
        if gap is None:
            raise ValueError("persisted CLOSE_PENDING resume gaps are invalid")
        gaps.append(gap)
    canonical = tuple(gaps)
    if canonical != tuple(sorted(set(canonical))):
        raise ValueError("persisted CLOSE_PENDING resume gaps are invalid")
    return canonical


def _json_wire_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported persisted JSON value: {type(value).__name__}")


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
        or not {"status", "gaps", "errorStreak"}.issubset(resume)
        or not set(resume).issubset(
            {"status", "gaps", "errorStreak", "latestBarEnd", "dataAgeSeconds"}
        )
    ):
        raise ValueError("persisted CLOSE_PENDING health is invalid") from None
    try:
        pending_date = date.fromisoformat(date_text)
        resume_status = SymbolHealthStatus(resume.get("status"))
    except TypeError, ValueError:
        pending_date = None
        resume_status = None
    error_streak = resume.get("errorStreak")
    data_age_seconds = resume.get("dataAgeSeconds")
    if data_age_seconds is not None and (type(data_age_seconds) is not int or data_age_seconds < 0):
        raise ValueError("persisted CLOSE_PENDING health is invalid") from None
    latest_bar_end = resume.get("latestBarEnd")
    _optional_market_datetime(
        latest_bar_end,
        name="persisted CLOSE_PENDING resume latestBarEnd",
    )
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
    restored: dict[str, object] = {
        "status": resume_status,
        "gaps": resume["gaps"],
        "errorStreak": error_streak,
    }
    if "latestBarEnd" in resume:
        restored["latestBarEnd"] = latest_bar_end
    if "dataAgeSeconds" in resume:
        restored["dataAgeSeconds"] = data_age_seconds
    return pending_date, restored


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
    "RuntimeDeadlineCoordinator",
    "RuntimeEvaluationService",
    "RuntimeLifecycleService",
    "RuntimeShutdownError",
    "RuntimeStartupResult",
    "StaleActivationGenerationError",
]
