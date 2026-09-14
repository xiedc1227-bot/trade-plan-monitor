"""Certified live providers bound to the persistent monitoring services."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID

from trade_plan_monitor.ai.review import load_explicit_plan_draft_json
from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    ExecutableTradePlan,
    ExplicitTradePlan,
    TradePlan,
    activation_is_eligible_on,
)
from trade_plan_monitor.live_profiles import (
    StockLiveCertification,
    load_index_certification,
    load_stock_certification,
)
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar, five_minute_bucket_end
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexProvider,
    TushareMarketIndexProviderError,
    certified_tushare_market_index_profile,
    unverified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.clock import Clock
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.runtime.health import SymbolHealthTracker
from trade_plan_monitor.runtime.market_indexes import RuntimeMarketIndexService
from trade_plan_monitor.runtime.production_context import ProductionContextBuilder
from trade_plan_monitor.runtime.recovery import RecoveryBatchResult, RecoveryService
from trade_plan_monitor.runtime.request_control import (
    LIVE_TUSHARE_MIN_INTERVAL,
    LIVE_TUSHARE_TIMEOUT_SECONDS,
    RequestPriority,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.runtime.scheduler import (
    DEFAULT_OFFICIAL_CLOSE_ATTEMPTS,
    DeadlineKind,
    MarketDeadline,
)
from trade_plan_monitor.runtime.service import (
    CommittedEventPublisher,
    OfficialCloseCycleStatus,
    RuntimeDeadlineCoordinator,
    RuntimeEvaluationService,
    UnitOfWorkFactory,
)
from trade_plan_monitor.runtime.symbol_service import SymbolService
from trade_plan_monitor.state.models import EvaluationKind, PlanVersionStatus

_REFERENCE_DAYS = 366


def _load_active_plan(document: str) -> ExecutableTradePlan:
    """Load only a complete persisted plan; active partial drafts fail closed."""

    try:
        explicit = load_explicit_plan_draft_json(document).to_executable()
    except ValueError:
        return load_plan_json(document)
    if explicit is None:
        raise RuntimeError("active explicit plan is incomplete")
    return explicit


def create_explicit_runtime_evaluation_service(
    unit_of_work_factory: UnitOfWorkFactory,
    *,
    committed_event_publisher: CommittedEventPublisher | None = None,
) -> ExplicitRuntimeEvaluationService:
    """Compose the R09 BUY runtime against the production SQLite/event boundary."""

    return ExplicitRuntimeEvaluationService(
        unit_of_work_factory,
        committed_event_publisher=committed_event_publisher,
    )


class _CertifiedTushareClient:
    """Check evidence in the provider worker immediately before each SDK call."""

    def __init__(self, client: object, current: Callable[[], bool]) -> None:
        self._client = client
        self._current = current

    def __getattr__(self, operation: str):
        def request(**kwargs):
            if not self._current():
                raise RuntimeError("provider certification is not current")
            return getattr(self._client, operation)(**kwargs)

        return request


_GAP_REPAIR_RESERVE = (
    timedelta(seconds=2 * LIVE_TUSHARE_TIMEOUT_SECONDS) + LIVE_TUSHARE_MIN_INTERVAL
)


def _ensure_recovery_complete(result: RecoveryBatchResult) -> None:
    """Fail startup closed when current-day or pending-close recovery is incomplete."""

    if (
        any(item.error_code is not None for item in result.results)
        or any(not item.resolved for item in result.pending_close_results)
        or result.yielded_to_realtime
    ):
        raise RuntimeError("startup recovery failed")


class _FreshIndexProvider:
    """Apply the independent evidence gate before every index acquisition."""

    def __init__(self, provider: TushareMarketIndexProvider, current: Callable[[], bool]) -> None:
        self._provider = provider
        self._current = current

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ):
        if not self._current():
            raise TushareMarketIndexProviderError
        return await self._provider.acquire_index_data(
            index_code=index_code,
            decision_cutoff=decision_cutoff,
            five_minute_bar_count=five_minute_bar_count,
            official_daily_bar_count=official_daily_bar_count,
        )


class ProductionMonitorPipeline:
    """One runtime's providers, batch coordinator and serial recovery ownership."""

    def __init__(
        self,
        *,
        configuration: TushareConfiguration,
        certification_directory: Path,
        stock_certification: StockLiveCertification,
        clock: Clock,
        request_controller: TushareRequestController,
        unit_of_work_factory: UnitOfWorkFactory,
        runtime_generation: UUID,
        publisher: CommittedEventPublisher,
    ) -> None:
        self._clock = clock
        self._controller = request_controller
        self._work = unit_of_work_factory
        self._certifications = certification_directory
        self._endpoint = str(configuration.api_url).rstrip("/")
        self._stock_evidence = stock_certification
        self._calendar: dict[date, bool] = {}
        self._reference_key: tuple[date, tuple[str, ...]] | None = None
        self._deadline_plans: tuple[ExecutableTradePlan, ...] | None = None
        self._running_deadline = False
        self._gap_repair_due_at: datetime | None = None
        self.reference_stage = TushareOperation.TRADING_CALENDAR
        transport = configuration.model_copy(update={"timeout_seconds": 15})
        self.provider = TushareMarketDataProvider(
            _CertifiedTushareClient(
                create_tushare_client(transport), self._stock_certification_current
            ),
            now=clock.now,
            is_open_on=self.is_open_on,
            source_time_label=stock_certification.source_time_label,
        )
        index_evidence = load_index_certification(
            certification_directory / "tushare-board-index-live.json",
            now=clock.now(),
            endpoint_url=self._endpoint,
        )
        index_profile = (
            certified_tushare_market_index_profile(
                capabilities=index_evidence.capabilities,
                source_time_label=index_evidence.source_time_label,
            )
            if index_evidence is not None and index_evidence.ready_indexes
            else unverified_tushare_market_index_profile()
        )
        self._index_evidence = index_evidence
        self.index_provider = TushareMarketIndexProvider(
            profile=index_profile,
            client=_CertifiedTushareClient(
                create_tushare_client(transport), self._index_certification_current
            ),
            request_controller=request_controller,
            now=clock.now,
        )
        self.index_service = RuntimeMarketIndexService(
            MarketIndexSnapshotCoordinator(
                _FreshIndexProvider(self.index_provider, self._index_certification_current),
                clock=clock,
            )
        )
        self.health_tracker = SymbolHealthTracker(stale_after=timedelta(seconds=90))
        self.symbols = SymbolService(
            provider=self.provider,
            request_controller=request_controller,
            active_symbols=self.active_symbols,
            persist_minutes=self.persist_minutes,
            load_minutes=self.load_minutes,
            persist_five_minute=self.persist_five_minute,
            is_open_on=self.is_open_on,
            health_tracker=self.health_tracker,
            clock=clock,
        )
        context_builder = ProductionContextBuilder(unit_of_work_factory)
        self.evaluations = RuntimeEvaluationService(
            fetch_minutes=self._reject_refetch,
            fetch_official_daily=self.fetch_official_daily,
            official_observed_at=lambda requested: max(requested, clock.now()),
            unit_of_work_factory=unit_of_work_factory,
            context_builder=context_builder,
            official_context_builder=context_builder,
            committed_event_publisher=publisher,
            market_index_service=self.index_service,
            runtime_generation=runtime_generation,
            clock=clock,
        )
        self.explicit_evaluations = create_explicit_runtime_evaluation_service(
            unit_of_work_factory,
            committed_event_publisher=publisher,
        )
        self.coordinator = RuntimeDeadlineCoordinator(
            clock=clock,
            active_plans=self.deadline_plans,
            symbol_service=self.symbols,
            evaluation_service=self.evaluations,
            explicit_evaluation_service=self.explicit_evaluations,
        )
        self.recovery = RecoveryService(
            provider=self.provider,
            request_controller=request_controller,
            active_symbols=self.active_symbols,
            persist_minutes=self.persist_minutes,
            is_open_on=self.is_open_on,
            realtime_pending=self._realtime_pending,
        )

    def _stock_certification_current(self) -> bool:
        evidence = load_stock_certification(
            self._certifications / "tushare-stock-live.json",
            now=self._clock.now(),
            endpoint_url=self._endpoint,
        )
        return evidence is not None and evidence.ready and evidence == self._stock_evidence

    def _index_certification_current(self) -> bool:
        evidence = load_index_certification(
            self._certifications / "tushare-board-index-live.json",
            now=self._clock.now(),
            endpoint_url=self._endpoint,
        )
        return evidence is not None and evidence == self._index_evidence

    def _persisted_active_plans(self) -> tuple[ExecutableTradePlan, ...]:
        with self._work() as work:
            records, _ = work.plans.list_version_details(
                offset=0,
                limit=11,
                status=PlanVersionStatus.ACTIVE,
            )
        if len(records) > 10:
            raise ValueError("production supports at most ten active plans")
        return tuple(
            sorted(
                (_load_active_plan(record.payload_json) for record in records),
                key=lambda plan: plan.symbol,
            )
        )

    def active_plans(
        self,
        market_date: date | None = None,
    ) -> tuple[ExecutableTradePlan, ...]:
        """Return persisted ACTIVE plans eligible for one market date."""

        effective_date = self._clock.now().date() if market_date is None else market_date
        if isinstance(effective_date, datetime) or not isinstance(effective_date, date):
            raise TypeError("market_date must be a date")
        return tuple(
            plan
            for plan in self._persisted_active_plans()
            if activation_is_eligible_on(plan.activation, effective_date)
        )

    def active_symbols(self) -> tuple[str, ...]:
        return tuple(plan.symbol for plan in self.active_plans())

    def deadline_plans(self) -> tuple[ExecutableTradePlan, ...]:
        if self._deadline_plans is None:
            raise RuntimeError("deadline plan capture is unavailable")
        return self._deadline_plans

    def is_open_on(self, trade_date: date) -> bool | None:
        # Called inside provider workers: deliberately no database access.
        return self._calendar.get(trade_date)

    def _realtime_pending(self) -> bool:
        if (
            self._running_deadline
            or self._controller.active_count
            or self._controller.waiting_count
        ):
            return True
        due_at = self._gap_repair_due_at
        return due_at is not None and self._clock.now() + _GAP_REPAIR_RESERVE >= due_at

    def _next_deadline_due_at(self, deadline: MarketDeadline) -> datetime | None:
        if deadline.bar_end is None:
            return None
        grace = deadline.due_at - deadline.bar_end
        next_minute = next(
            (
                bar_end + grace
                for bar_end in expected_minute_ends(
                    deadline.trade_date,
                    is_open=self.is_open_on(deadline.trade_date),
                )
                if bar_end > deadline.bar_end
            ),
            None,
        )
        if next_minute is not None:
            return next_minute
        return datetime.combine(
            deadline.trade_date,
            DEFAULT_OFFICIAL_CLOSE_ATTEMPTS[0],
            deadline.due_at.tzinfo,
        )

    async def _repair_detected_gaps(
        self,
        *,
        deadline: MarketDeadline,
        plans: tuple[ExecutableTradePlan, ...],
    ) -> None:
        if deadline.bar_end is None or not plans:
            return
        self._gap_repair_due_at = self._next_deadline_due_at(deadline)
        try:
            if self._realtime_pending():
                return
            states = self.evaluations.load_persisted_symbol_health(
                tuple(plan.symbol for plan in plans)
            )
            gaps = {
                state.symbol: tuple(
                    gap
                    for gap in (() if state.snapshot is None else state.snapshot.gaps)
                    if gap.date() == deadline.trade_date and gap <= deadline.bar_end
                )
                for state in states
            }
            detected = {symbol: values for symbol, values in gaps.items() if values}
            if detected:
                await self.recovery.repair_detected_gaps(
                    trade_date=deadline.trade_date,
                    gaps=detected,
                )
        finally:
            self._gap_repair_due_at = None

    async def _request(self, operation: TushareOperation, call: Callable[[], object], key: str):
        self.reference_stage = operation
        return await self._controller.execute(
            operation,
            call,
            work_key=key,
            priority=RequestPriority.RECOVERY,
        )

    async def refresh_references(self, trade_date: date) -> None:
        plans = self.active_plans(trade_date)
        legacy_plans = tuple(plan for plan in plans if isinstance(plan, TradePlan))
        start = trade_date - timedelta(days=_REFERENCE_DAYS)
        end = trade_date + timedelta(days=32)
        for exchange in sorted({"SSE", *(plan.market for plan in plans)}):
            days = await self._request(
                TushareOperation.TRADING_CALENDAR,
                lambda exchange=exchange: self.provider.trading_calendar_for_exchange(
                    exchange, start, end
                ),
                f"calendar:{exchange}:{trade_date}",
            )
            if not any(day.cal_date == trade_date for day in days):
                raise RuntimeError("current trading calendar is unavailable")
            with self._work() as work:
                work.references.upsert_trading_days(days)
                work.commit()
            if exchange == "SSE":
                self._calendar = {day.cal_date: day.is_open for day in days}
        if legacy_plans and self.is_open_on(trade_date):
            limits = await self._request(
                TushareOperation.DAILY_LIMITS,
                lambda: self.provider.daily_limits(trade_date),
                f"limits:{trade_date}",
            )
            with self._work() as work:
                active_symbols = {plan.symbol for plan in legacy_plans}
                work.references.upsert_daily_limits(
                    tuple(row for row in limits if row.symbol in active_symbols)
                )
                work.commit()
        for plan in legacy_plans:
            bars = await self._request(
                TushareOperation.DAILY_BARS,
                lambda plan=plan: self.provider.daily_bars(
                    plan.symbol, start, trade_date - timedelta(days=1)
                ),
                f"daily-history:{plan.symbol}:{trade_date}",
            )
            if not bars:
                raise RuntimeError("official reference history is unavailable")
            with self._work() as work:
                work.history.upsert_daily_bars(bars)
                work.commit()
        self._reference_key = trade_date, tuple(plan.symbol for plan in plans)

    async def recover_startup(self, trade_date: date) -> None:
        # Hydrate the calendar even if the independent refresh stage failed.
        with self._work() as work:
            days = work.references.list_trading_days(
                "SSE",
                trade_date - timedelta(days=_REFERENCE_DAYS),
                trade_date + timedelta(days=32),
            )
        self._calendar = {day.cal_date: day.is_open for day in days}
        symbols = self.active_symbols()
        self.symbols.restore_health(
            symbols=symbols, states=self.evaluations.load_persisted_symbol_health(symbols)
        )
        await self._recover_pending_close_batches(trade_date)
        result = await self.recovery.recover_startup(trade_date=trade_date)
        _ensure_recovery_complete(result)

    async def _recover_pending_close_batches(self, startup_date: date) -> None:
        grouped: dict[date, list[TradePlan]] = {}
        for plan in self._persisted_active_plans():
            if isinstance(plan, ExplicitTradePlan):
                continue
            pending_date = self.evaluations.pending_close_date(plan.symbol)
            if pending_date is None:
                continue
            if pending_date > startup_date:
                raise RuntimeError("startup recovery failed")
            if not activation_is_eligible_on(plan.activation, pending_date):
                continue
            grouped.setdefault(pending_date, []).append(plan)
        for pending_date in sorted(grouped):
            plans = tuple(grouped[pending_date])
            results = await self.evaluations.run_official_close_batch(
                plans=plans,
                trade_date=pending_date,
                evaluated_at=self._clock.now(),
                close_attempt=1,
            )
            if len(results) != len(plans) or any(
                result.status
                not in {
                    OfficialCloseCycleStatus.COMMITTED,
                    OfficialCloseCycleStatus.DUPLICATE,
                }
                for result in results
            ):
                raise RuntimeError("startup recovery failed")
            if any(self.evaluations.pending_close_date(plan.symbol) is not None for plan in plans):
                raise RuntimeError("startup recovery failed")

    async def fetch_official_daily(self, symbol: str, trade_date: date, attempt: int):
        return await self._controller.execute(
            TushareOperation.DAILY_BARS,
            lambda: self.provider.daily_bars(symbol, trade_date, trade_date),
            work_key=f"official:{symbol}:{trade_date}:{attempt}",
            priority=RequestPriority.MARKET_DEADLINE,
        )

    @staticmethod
    async def _reject_refetch(symbol: str, bucket_end: datetime):
        raise RuntimeError("production evaluation requires the captured stock batch")

    def persist_minutes(self, bars: tuple[MinuteBar, ...]) -> None:
        with self._work() as work:
            work.history.upsert_minutes(bars)
            work.commit()

    def load_minutes(self, symbol: str, *, start: datetime, end: datetime):
        with self._work() as work:
            return work.history.list_minutes(symbol, start=start, end=end)

    def persist_five_minute(self, bar: FiveMinuteBar) -> None:
        with self._work() as work:
            work.history.upsert_five_minute(**bar.model_dump())
            work.commit()

    async def run_deadline(self, deadline: MarketDeadline):
        if not self._stock_certification_current():
            raise RuntimeError("stock certification must be refreshed before execution")
        plans = self.active_plans(deadline.trade_date)
        reference_key = deadline.trade_date, tuple(plan.symbol for plan in plans)
        cutoff = deadline.bar_end or datetime.combine(
            deadline.trade_date, time(15), deadline.due_at.tzinfo
        )
        selected = []
        with self._work() as work:
            for plan in plans:
                active = work.plans.get_active(plan.symbol)
                if active is None or active.activated_at > cutoff:
                    continue
                if (
                    isinstance(plan, ExplicitTradePlan)
                    and deadline.kind is DeadlineKind.OFFICIAL_CLOSE
                ):
                    continue
                evaluation_due = (
                    deadline.bar_end is None or five_minute_bucket_end(cutoff) == cutoff
                )
                if evaluation_due:
                    if isinstance(plan, ExplicitTradePlan):
                        if deadline.bar_end is not None and work.explicit_rules.get(
                            plan_hash=plan_sha256(plan),
                            symbol=plan.symbol,
                            target_bucket_end=deadline.bar_end,
                            activation_revision=active.revision,
                        ) is not None:
                            continue
                    elif work.evaluations.has_claim(
                        plan_hash=plan_sha256(plan),
                        symbol=plan.symbol,
                        evaluation_kind=(
                            EvaluationKind.INTRADAY
                            if deadline.bar_end
                            else EvaluationKind.OFFICIAL_CLOSE
                        ),
                        bucket_end=deadline.bar_end,
                        official_trade_date=(
                            None if deadline.bar_end else deadline.trade_date
                        ),
                        formula_version=plan.monitoring.indicator_formula_version,
                    ):
                        continue
                selected.append(plan)
        if not selected:
            await self._refresh_dashboard_indexes(deadline)
            return ()
        if self._reference_key != reference_key:
            await self.refresh_references(deadline.trade_date)
        self._deadline_plans = tuple(selected)
        self._running_deadline = True
        try:
            result = await self.coordinator.run_deadline(deadline)
            self._running_deadline = False
            await self._repair_detected_gaps(
                deadline=deadline,
                plans=tuple(selected),
            )
            if deadline.kind is DeadlineKind.REALTIME_MINUTE:
                await self._refresh_dashboard_indexes(deadline, exact_boundary=False)
            return result
        finally:
            self._running_deadline = False
            self._deadline_plans = None

    async def _refresh_dashboard_indexes(
        self,
        deadline: MarketDeadline,
        *,
        exact_boundary: bool = True,
    ) -> None:
        """Persist display-only index snapshots when no plan evaluation is due."""

        observed_at = max(self._clock.now(), deadline.due_at)
        if deadline.kind is DeadlineKind.REALTIME_MINUTE:
            if deadline.bar_end is None:
                return
            if five_minute_bucket_end(deadline.bar_end) == deadline.bar_end:
                if not exact_boundary:
                    return
                bucket_end = deadline.bar_end
            else:
                candidate = deadline.bar_end - timedelta(minutes=1)
                try:
                    follows_five_minute_boundary = five_minute_bucket_end(candidate) == candidate
                except ValueError:
                    follows_five_minute_boundary = False
                if not follows_five_minute_boundary:
                    return
                await self.evaluations.retry_intraday_market_indexes(
                    bucket_end=candidate,
                    evaluated_at=observed_at,
                )
                return
            await self.evaluations.prepare_intraday_market_indexes(
                plans=(),
                bucket_end=bucket_end,
                evaluated_at=observed_at,
            )
            return
        if deadline.close_attempt == 1:
            await self.evaluations.run_official_close_batch(
                plans=(),
                trade_date=deadline.trade_date,
                evaluated_at=observed_at,
                close_attempt=deadline.close_attempt,
            )
