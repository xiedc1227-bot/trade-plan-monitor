"""Deterministic intraday evaluation and atomic committed-event publication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from enum import StrEnum
from inspect import isawaitable
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import (
    DailyIndicatorProvenance,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationResult,
    IntradayEvaluationIdentity,
    IntradayEvaluationTarget,
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
from trade_plan_monitor.market_data.models import (
    DailyBar,
    MinuteBar,
    ShanghaiDatetime,
)
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertEvent, build_alert_payload
from trade_plan_monitor.state.models import EvaluationKind
from trade_plan_monitor.state.repositories import (
    EpisodeIdentityConflictError,
    EpisodeNotFoundError,
    FiveMinuteBarRecord,
)
from trade_plan_monitor.state.unit_of_work import UnitOfWork

_MAX_FETCHED_MINUTES = 1_000
_MAX_CURRENT_DAY_MINUTES = 240
_MAX_CURRENT_DAY_BUCKETS = _MAX_CURRENT_DAY_MINUTES // 5
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
UnitOfWorkFactory = Callable[[], UnitOfWork]
ContextBuilder = Callable[[TradePlan, "IntradayMarketFacts"], EvaluationContext]
Evaluator = Callable[[EvaluationContext], EvaluationResult]
CommittedEventPublisher = Callable[[AlertEvent], object]
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


class RuntimeEvaluationService:
    """Persist exact market facts, evaluate purely, then apply results atomically."""

    def __init__(
        self,
        *,
        fetch_minutes: FetchMinutes,
        unit_of_work_factory: UnitOfWorkFactory,
        context_builder: ContextBuilder,
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
        self._fetch_minutes = fetch_minutes
        self._unit_of_work_factory = unit_of_work_factory
        self._context_builder = context_builder
        self._publisher = committed_event_publisher
        self._evaluator = evaluator
        self._event_id_factory = event_id_factory

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
            unit_of_work.commit()

        if not claim.created:
            return IntradayCycleResult(
                status=IntradayCycleStatus.DUPLICATE,
                facts=facts,
                evaluation_result=result,
                claim_created=False,
                committed_event=None,
            )
        if committed_event is not None:
            publication = self._publisher(committed_event)
            if isawaitable(publication):
                await publication
        return IntradayCycleResult(
            status=IntradayCycleStatus.COMMITTED,
            facts=facts,
            evaluation_result=result,
            claim_created=True,
            committed_event=committed_event,
        )

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


def _five_minute_value(record: FiveMinuteBarRecord) -> FiveMinuteBar:
    return FiveMinuteBar.model_validate(record.model_dump(mode="python", round_trip=True))


__all__ = [
    "IntradayCycleResult",
    "IntradayCycleStatus",
    "IntradayMarketFacts",
    "RuntimeEvaluationService",
]
