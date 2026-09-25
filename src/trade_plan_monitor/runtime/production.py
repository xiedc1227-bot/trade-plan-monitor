"""Certified live providers bound to the persistent monitoring services."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Event, Lock
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

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
from trade_plan_monitor.market_data.models import MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import (
    DEFAULT_DATA_GRACE,
    SourceTimeLabel,
    expected_minute_ends,
)
from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexHealth
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexProviderError,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
    unverified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.clock import Clock
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.runtime.health import RecoveryIssueSnapshot, SymbolHealthTracker
from trade_plan_monitor.runtime.historical_close_context import (
    HistoricalCloseUnavailableError,
    HistoricalOfficialContextBuilder,
    StaleHistoricalCloseError,
)
from trade_plan_monitor.runtime.historical_close_evidence import (
    LegacyHistoricalCloseReader,
    UnknownHistoricalClose,
)
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    RuntimeMarketIndexBatch,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.production_context import ProductionContextBuilder
from trade_plan_monitor.runtime.provider_contract import (
    ProviderSemanticContract,
    load_semantic_contract,
)
from trade_plan_monitor.runtime.recovery import (
    RecoveryBatchResult,
    RecoveryErrorCode,
    RecoveryService,
)
from trade_plan_monitor.runtime.request_control import (
    LIVE_TUSHARE_MIN_INTERVAL,
    LIVE_TUSHARE_TIMEOUT_SECONDS,
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
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
_INDEX_PERMISSION_GUARD = (
    timedelta(seconds=2 * LIVE_TUSHARE_TIMEOUT_SECONDS) + LIVE_TUSHARE_MIN_INTERVAL
)


class PermissionMaintenanceResult(StrEnum):
    SKIPPED = "SKIPPED"
    DEFERRED = "DEFERRED"
    PROBED = "PROBED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class _FrozenPermissionMarketWindow:
    captured_at: datetime
    latest_start_at: datetime
    deadlines: tuple[tuple[datetime, bool], ...]

    def blocker(self, now: datetime) -> tuple[datetime, bool] | None:
        """Check only immutable market times at queue and SDK worker boundaries."""
        if now < self.captured_at or now > self.latest_start_at:
            raise ValueError("permission market window expired or clock moved backward")
        horizon = now + _INDEX_PERMISSION_GUARD
        return min(
            (
                (due, known) for due, known in self.deadlines
                if due <= horizon and (known or due >= now)
            ),
            key=lambda item: item[0],
            default=None,
        )


@dataclass(frozen=True, slots=True)
class SemanticContractBinding:
    """The durable path and interpretation revision captured for one runtime scope."""

    path: Path
    expected_revision: str


@dataclass(frozen=True, slots=True)
class ProductionSemanticBindings:
    """Explicit opt-in; an absent scope blocks only that scope, with no legacy fallback."""

    stock: SemanticContractBinding | None
    index: SemanticContractBinding | None
    installed_sdk_version: Callable[[], str | None] | None = None


class ReferenceDataUnavailableError(RuntimeError):
    """A completed reference request yielded no usable data required for monitoring."""


class ReferenceDependenciesChangedError(ReferenceDataUnavailableError):
    """Reference acquisition no longer belongs to its captured plan activation."""

    def __init__(self) -> None:
        super().__init__("reference dependencies changed during acquisition")


@dataclass(frozen=True, slots=True)
class PlanReferenceDependency:
    """The complete plan hash binds its requirements to its actual active revision."""

    symbol: str
    family: Literal["LEGACY", "EXPLICIT_RULES"]
    plan_hash: str
    plan_version_id: str
    activation_revision: int
    activated_at: datetime


@dataclass(frozen=True, slots=True)
class ReferenceDependencyKey:
    """Reference reuse excludes evidence metadata and unrelated display indexes."""

    trade_date: date
    plans: tuple[PlanReferenceDependency, ...]
    stock_semantic_revision: str | None


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
    recovery_delivery: bool = False,
    commit_admission: Callable[[], bool] | None = None,
) -> ExplicitRuntimeEvaluationService:
    """Compose the R09 BUY runtime against the production SQLite/event boundary."""

    return ExplicitRuntimeEvaluationService(
        unit_of_work_factory,
        committed_event_publisher=committed_event_publisher,
        recovery_delivery=recovery_delivery,
        commit_admission=commit_admission,
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

    failures = tuple(item for item in result.results if item.error_code is not None)
    retryable = {
        RecoveryErrorCode.TRANSIENT,
        RecoveryErrorCode.TIMEOUT,
        RecoveryErrorCode.RATE_LIMITED,
    }
    if (
        failures and not result.pending_close_results and not result.yielded_to_realtime
        and all(item.error_code in retryable for item in failures)
    ):
        codes = {item.error_code for item in failures}
        code = next(
            candidate for candidate in (
                RequestControlErrorCode.RATE_LIMITED,
                RequestControlErrorCode.TIMEOUT,
                RequestControlErrorCode.TRANSIENT,
            ) if RecoveryErrorCode(candidate.value) in codes
        )
        deadlines = tuple(
            item.next_retry_at for item in failures if item.next_retry_at is not None
        )
        raise RequestControlError(
            code,
            TushareOperation.CURRENT_DAY_MINUTES,
            attempts=0,
            next_retry_at=max(deadlines) if deadlines else None,
        )
    if (
        failures
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
        stock_certification: StockLiveCertification | None,
        clock: Clock,
        request_controller: TushareRequestController,
        unit_of_work_factory: UnitOfWorkFactory,
        runtime_generation: UUID,
        publisher: CommittedEventPublisher,
        semantic_bindings: ProductionSemanticBindings | None = None,
        recovery_session_factory: Callable[[], Session] | None = None,
        configuration_current: Callable[[], bool] | None = None,
        generation_current: Callable[[], bool] | None = None,
        admission_revoked: Callable[[], bool] | None = None,
        on_semantic_revoked: Callable[[], None] | None = None,
        permission_market_window: (
            Callable[[datetime, datetime], tuple[tuple[datetime, bool], ...]] | None
        ) = None,
    ) -> None:
        self._clock = clock
        self._controller = request_controller
        self._configuration_current = configuration_current or (lambda: True)
        self._generation_current = generation_current or (lambda: True)
        self._admission_revoked = admission_revoked or (lambda: False)
        self._on_semantic_revoked = on_semantic_revoked or (lambda: None)
        self._permission_market_window = permission_market_window
        self._work = unit_of_work_factory
        self._certifications = certification_directory
        self._endpoint = str(configuration.api_url).rstrip("/")
        self._stock_evidence = stock_certification
        self._semantic_bindings = semantic_bindings
        self._stock_semantics = self._load_semantic_binding("STOCK")
        self._index_semantics = self._load_semantic_binding("BOARD_INDEX")
        if semantic_bindings is None:
            if stock_certification is None:
                raise ValueError("legacy pipeline requires stock certification")
            stock_label = stock_certification.source_time_label
        elif self._stock_semantics is None:
            stock_label = SourceTimeLabel.UNVERIFIED
        else:
            stock_label = SourceTimeLabel(self._stock_semantics.source_time_label)
        self._calendar: dict[date, bool] = {}
        self._calendar_epoch_lock = Lock()
        self._calendar_epoch = 0
        self._calendar_revoked = Event()
        self._historical_probe_deferred_until: datetime | None = None
        self._realtime_probe_deferred_until: datetime | None = None
        self._reference_key: ReferenceDependencyKey | None = None
        self._deadline_plans: tuple[ExecutableTradePlan, ...] | None = None
        self._running_deadline = False
        self._gap_repair_due_at: datetime | None = None
        self._historical_reader = (
            None if recovery_session_factory is None
            else LegacyHistoricalCloseReader(recovery_session_factory)
        )
        self._historical_blocked: dict[str, str] = {}
        self._historical_retry_at: dict[str, datetime] = {}
        self._historical_identity: dict[str, tuple[str, int, datetime]] = {}
        self.reference_stage = TushareOperation.TRADING_CALENDAR
        transport = configuration.model_copy(update={"timeout_seconds": 15})
        self.provider = TushareMarketDataProvider(
            _CertifiedTushareClient(
                create_tushare_client(transport), self._stock_certification_current
            ),
            now=clock.now,
            is_open_on=self.is_open_on,
            source_time_label=stock_label,
        )
        index_evidence = (
            None
            if semantic_bindings is not None
            else load_index_certification(
                certification_directory / "tushare-board-index-live.json",
                now=clock.now(),
                endpoint_url=self._endpoint,
            )
        )
        index_profile = (
            certified_tushare_market_index_profile(
                capabilities=index_evidence.capabilities,
                source_time_label=index_evidence.source_time_label,
            )
            if index_evidence is not None and index_evidence.ready_indexes
            else unverified_tushare_market_index_profile()
        )
        if semantic_bindings is not None:
            index_profile = unverified_tushare_market_index_profile()
            if self._index_semantics is not None:
                # The adapter's READY enum authorizes routing within verified scope.
                # It is not current permission or runtime health; snapshots still need
                # validated current responses and no health state is copied here.
                index_profile = certified_tushare_market_index_profile(
                    capabilities={
                        code: (
                            TushareMarketIndexCapabilityStatus.READY
                            if code.value in self._index_semantics.capability_scope
                            else TushareMarketIndexCapabilityStatus.DEFERRED
                        )
                        for code in MarketIndexCode
                    },
                    source_time_label=TushareMarketIndexSourceTimeLabel(
                        self._index_semantics.source_time_label
                    ),
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
            recovery_delivery=True,
            commit_admission=self._decision_commit_current,
            index_commit_admission=self._index_commit_current,
        )
        self.historical_evaluations = (
            None if self._historical_reader is None else RuntimeEvaluationService(
                fetch_minutes=self._reject_refetch,
                fetch_official_daily=self.fetch_official_daily,
                official_observed_at=lambda requested: max(requested, clock.now()),
                unit_of_work_factory=unit_of_work_factory,
                context_builder=context_builder,
                official_context_builder=HistoricalOfficialContextBuilder(
                    self._historical_reader,
                ),
                committed_event_publisher=publisher,
                market_index_service=self.index_service,
                runtime_generation=runtime_generation,
                clock=clock,
                recovery_delivery=True,
                commit_admission=self._decision_commit_current,
                index_commit_admission=self._index_commit_current,
            )
        )
        self.explicit_evaluations = create_explicit_runtime_evaluation_service(
            unit_of_work_factory,
            committed_event_publisher=publisher,
            recovery_delivery=True,
            commit_admission=self._decision_commit_current,
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

    def _load_semantic_binding(self, surface: str) -> ProviderSemanticContract | None:
        bindings = self._semantic_bindings
        if bindings is None:
            return None
        binding = bindings.stock if surface == "STOCK" else bindings.index
        if binding is None:
            return None
        version_options = (
            {}
            if bindings.installed_sdk_version is None
            else {"installed_sdk_version": bindings.installed_sdk_version}
        )
        record = load_semantic_contract(
            binding.path, now=self._clock.now(), endpoint_url=self._endpoint, **version_options
        )
        if (
            record is None
            or record.surface != surface
            or record.semantic_revision != binding.expected_revision
        ):
            return None
        return record

    def _stock_certification_current(self) -> bool:
        if not self._configuration_current():
            return False
        if self._semantic_bindings is not None:
            current = (
                self._stock_semantics is not None
                and self._load_semantic_binding("STOCK") is not None
            )
            if not current and self._stock_semantics is not None:
                self._on_semantic_revoked()
            return current
        evidence = load_stock_certification(
            self._certifications / "tushare-stock-live.json",
            now=self._clock.now(),
            endpoint_url=self._endpoint,
        )
        return evidence is not None and evidence.ready and evidence == self._stock_evidence

    def _decision_commit_current(self) -> bool:
        """Check frozen production authority just before a synchronous decision commit."""

        return (
            self._configuration_current()
            and self._stock_certification_current()
            and self._generation_current()
            and not self._admission_revoked()
        )

    def _index_commit_current(self, prepared: RuntimeMarketIndexBatch) -> bool:
        """Permit independent index status; require index evidence for nonblocked captures."""

        if not self._configuration_current() or not self._generation_current():
            return False
        if all(
            snapshot.health is MarketIndexHealth.BLOCKED
            for snapshot in prepared.snapshots_by_index.values()
        ):
            return not self._admission_revoked()
        return self._index_certification_current() and not self._admission_revoked()

    def _index_certification_current(self) -> bool:
        if not self._configuration_current():
            return False
        if self._semantic_bindings is not None:
            current = (
                self._index_semantics is not None
                and self._load_semantic_binding("BOARD_INDEX") is not None
            )
            if not current and self._index_semantics is not None:
                self._on_semantic_revoked()
            return current
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
        if operation is TushareOperation.TRADING_CALENDAR:
            await self._maybe_recheck_calendar_permission()
        return await self._controller.execute(
            operation,
            call,
            work_key=key,
            priority=RequestPriority.RECOVERY,
        )

    def _calendar_permission_anchor(self) -> date | None:
        """Choose a completed locally persisted day; absence never authorizes a probe."""

        yesterday = self._clock.now().date() - timedelta(days=1)
        with self._work() as work:
            days = work.references.list_trading_days(
                "SSE", yesterday - timedelta(days=6), yesterday,
            )
        return None if not days else days[-1].cal_date

    async def _maybe_recheck_calendar_permission(self) -> None:
        operation = TushareOperation.TRADING_CALENDAR
        if not self._controller.is_permission_blocked(operation):
            return
        due = self._controller.permission_retry_at(operation)
        if due is None or self._clock.now() < due:
            return
        anchor = self._calendar_permission_anchor()
        if anchor is None:
            return
        if not self._stock_certification_current() or not self._generation_current():
            return
        await self._controller.recheck_permission(
            operation,
            lambda: self.provider.probe_trading_calendar_permission("SSE", anchor),
            work_key="permission:trade_cal:SSE",
            validate_after=lambda: (
                self._stock_certification_current() and self._generation_current()
            ),
        )

    def _historical_index_permission_anchor(self) -> date | None:
        """Use only a persisted, already completed SSE open session."""

        yesterday = self._clock.now().date() - timedelta(days=1)
        with self._work() as work:
            days = work.references.list_trading_days(
                "SSE", yesterday - timedelta(days=6), yesterday,
            )
        return next((day.cal_date for day in reversed(days) if day.is_open), None)

    def next_historical_index_permission_due_at(self) -> datetime | None:
        """Expose one independent permission maintenance deadline while authority holds."""
        operation = TushareOperation.INDEX_HISTORICAL_MINUTES
        if not self._controller.is_permission_blocked(operation):
            return None
        now = self._clock.now()
        semantics = self._index_semantics
        if semantics is None or not self._historical_index_probe_current(
            now.date(), semantics.semantic_revision,
        ):
            return None
        if not any(
            code.value in semantics.capability_scope
            and self.index_provider.profile.capabilities[code]
            is TushareMarketIndexCapabilityStatus.READY
            for code in (MarketIndexCode.SSE_COMPOSITE, MarketIndexCode.STAR_50)
        ):
            return None
        due = self._controller.permission_retry_at(operation)
        if due is None:
            return None
        if self._historical_probe_deferred_until is not None:
            due = max(due, self._historical_probe_deferred_until)
        return due

    def next_realtime_index_permission_due_at(self) -> datetime | None:
        """Keep an independently blocked realtime endpoint on the maintenance clock."""

        operation = TushareOperation.INDEX_REALTIME_MINUTES
        if not self._controller.is_permission_blocked(operation):
            return None
        now = self._clock.now()
        semantics = self._index_semantics
        if semantics is None or not self._realtime_index_probe_current(
            now.date(), semantics.semantic_revision,
        ):
            return None
        if not any(
            code.value in semantics.capability_scope
            and self.index_provider.profile.capabilities[code]
            is TushareMarketIndexCapabilityStatus.READY
            for code in (MarketIndexCode.SSE_COMPOSITE, MarketIndexCode.STAR_50)
        ):
            return None
        due = self._controller.permission_retry_at(operation)
        if due is None:
            return None
        first_bar_due = datetime.combine(now.date(), time(9, 35), now.tzinfo)
        first_bar_due += DEFAULT_DATA_GRACE
        due = max(due, first_bar_due)
        if self._realtime_probe_deferred_until is not None:
            due = max(due, self._realtime_probe_deferred_until)
        return due

    def _realtime_index_probe_current(self, request_date: date, revision: str) -> bool:
        now = self._clock.now()
        semantics = self._index_semantics
        return (
            self._semantic_bindings is not None
            and semantics is not None
            and semantics.semantic_revision == revision
            and "rt_idx_min_daily" in semantics.interface_scope
            and now.date() == request_date
            and now < semantics.provenance.valid_until
            and self._configuration_current()
            and self._generation_current()
            and not self._admission_revoked()
            and self._index_certification_current()
        )

    def _persisted_sse_open_on(self, trade_date: date) -> bool:
        """Read the current SSE row on the owner thread, never in an SDK worker."""

        with self._work() as work:
            days = work.references.list_trading_days("SSE", trade_date, trade_date)
        return trade_date.weekday() < 5 and len(days) == 1 and days[0].is_open is True

    async def _maybe_recheck_realtime_index_permission(self) -> PermissionMaintenanceResult:
        """Reserve one current-day read proof without caching or business writes."""

        operation = TushareOperation.INDEX_REALTIME_MINUTES
        if not self._controller.is_permission_blocked(operation):
            return PermissionMaintenanceResult.SKIPPED
        now = self._clock.now()
        due = self.next_realtime_index_permission_due_at()
        if due is None or now < due:
            return PermissionMaintenanceResult.SKIPPED
        semantics = self._index_semantics
        if semantics is None or not self._realtime_index_probe_current(
            now.date(), semantics.semantic_revision,
        ):
            return PermissionMaintenanceResult.SKIPPED
        index_code = next((
            code for code in (MarketIndexCode.SSE_COMPOSITE, MarketIndexCode.STAR_50)
            if code.value in semantics.capability_scope
            and self.index_provider.profile.capabilities[code]
            is TushareMarketIndexCapabilityStatus.READY
        ), None)
        if index_code is None:
            return PermissionMaintenanceResult.SKIPPED
        if not self._persisted_sse_open_on(now.date()):
            self._realtime_probe_deferred_until = now + timedelta(seconds=30)
            return PermissionMaintenanceResult.DEFERRED
        if self._permission_market_window is None:
            self._realtime_probe_deferred_until = now + timedelta(seconds=30)
            return PermissionMaintenanceResult.DEFERRED
        with self._calendar_epoch_lock:
            if self._calendar_revoked.is_set():
                # A failed correction stays revoked until this fresh SQLite read.
                self._calendar_revoked = Event()
            epoch = self._calendar_epoch
            revoked = self._calendar_revoked
        try:
            latest_start = now + timedelta(seconds=LIVE_TUSHARE_TIMEOUT_SECONDS)
            market_window = _FrozenPermissionMarketWindow(
                captured_at=now,
                latest_start_at=latest_start,
                deadlines=self._permission_market_window(
                    now, latest_start + _INDEX_PERMISSION_GUARD,
                ),
            )
            blocker = market_window.blocker(now)
        except ValueError:
            self._realtime_probe_deferred_until = now + timedelta(seconds=30)
            return PermissionMaintenanceResult.DEFERRED
        if blocker is not None:
            self._realtime_probe_deferred_until = max(now, blocker[0]) + timedelta(
                microseconds=1,
            )
            return PermissionMaintenanceResult.DEFERRED
        request_date = now.date()
        revision = semantics.semantic_revision

        def current_token(at: datetime) -> bool:
            try:
                with self._calendar_epoch_lock:
                    return (
                        epoch == self._calendar_epoch
                        and revoked is self._calendar_revoked
                        and not revoked.is_set()
                        and market_window.blocker(at) is None
                    )
            except ValueError:
                return False

        def can_start() -> bool:
            return (
                self._realtime_index_probe_current(request_date, revision)
                and current_token(self._clock.now())
            )

        def probe() -> None:
            if not self._realtime_index_probe_current(request_date, revision):
                raise RequestNotStartedError("realtime index authority changed")
            with self._calendar_epoch_lock:
                admitted_at = self._clock.now()
                try:
                    admitted = (
                        epoch == self._calendar_epoch
                        and revoked is self._calendar_revoked
                        and not revoked.is_set()
                        and market_window.blocker(admitted_at) is None
                    )
                except ValueError:
                    admitted = False
            if not admitted:
                raise RequestNotStartedError("realtime index calendar or market time changed")

            def physical_start() -> datetime:
                if not self._realtime_index_probe_current(request_date, revision):
                    raise RequestNotStartedError("realtime index authority changed")
                at = self._clock.now()
                if not current_token(at):
                    raise RequestNotStartedError(
                        "realtime index calendar or market time changed before SDK call"
                    )
                return at

            self.index_provider.probe_realtime_minutes_permission(
                index_code, request_date, physical_start,
            )

        def validate_after() -> bool:
            return (
                self._realtime_index_probe_current(request_date, revision)
                and self._persisted_sse_open_on(request_date)
                and current_token(self._clock.now())
            )

        try:
            await self._controller.recheck_permission(
                operation, probe,
                work_key=f"permission:rt_idx_min_daily:{index_code.value}:{request_date}",
                validate_after=validate_after,
                can_start=can_start,
            )
            self._realtime_probe_deferred_until = None
            return PermissionMaintenanceResult.PROBED
        except RequestNotStartedError:
            return PermissionMaintenanceResult.DEFERRED
        except RequestControlError:
            return PermissionMaintenanceResult.FAILED

    def _historical_index_probe_current(self, request_date: date, revision: str) -> bool:
        now = self._clock.now()
        semantics = self._index_semantics
        return (
            self._semantic_bindings is not None
            and semantics is not None
            and semantics.semantic_revision == revision
            and "idx_mins" in semantics.interface_scope
            and now.date() == request_date
            and now < semantics.provenance.valid_until
            and self._configuration_current()
            and self._generation_current()
            and not self._admission_revoked()
            and self._index_certification_current()
        )

    async def _maybe_recheck_historical_index_permission(self) -> PermissionMaintenanceResult:
        """Reserve one exact `idx_mins` proof at an independent maintenance deadline."""

        operation = TushareOperation.INDEX_HISTORICAL_MINUTES
        if not self._controller.is_permission_blocked(operation):
            return PermissionMaintenanceResult.SKIPPED
        now = self._clock.now()
        due = self.next_historical_index_permission_due_at()
        if due is None or now < due:
            return PermissionMaintenanceResult.SKIPPED
        semantics = self._index_semantics
        if semantics is None or not self._historical_index_probe_current(
            now.date(), semantics.semantic_revision,
        ):
            return PermissionMaintenanceResult.SKIPPED
        index_code = next((
            code for code in (MarketIndexCode.SSE_COMPOSITE, MarketIndexCode.STAR_50)
            if code.value in semantics.capability_scope
            and self.index_provider.profile.capabilities[code]
            is TushareMarketIndexCapabilityStatus.READY
        ), None)
        if index_code is None:
            return PermissionMaintenanceResult.SKIPPED
        anchor = self._historical_index_permission_anchor()
        if anchor is None:
            self._historical_probe_deferred_until = now + timedelta(seconds=30)
            return PermissionMaintenanceResult.DEFERRED
        market_window = None
        if self._permission_market_window is not None:
            try:
                latest_start = now + timedelta(seconds=LIVE_TUSHARE_TIMEOUT_SECONDS)
                market_window = _FrozenPermissionMarketWindow(
                    captured_at=now,
                    latest_start_at=latest_start,
                    deadlines=self._permission_market_window(
                        now, latest_start + _INDEX_PERMISSION_GUARD,
                    ),
                )
                blocker = market_window.blocker(now)
            except ValueError:
                self._historical_probe_deferred_until = now + timedelta(seconds=30)
                return PermissionMaintenanceResult.DEFERRED
            if blocker is not None:
                blocked_due, _known = blocker
                self._historical_probe_deferred_until = max(
                    now, blocked_due,
                ) + timedelta(microseconds=1)
                return PermissionMaintenanceResult.DEFERRED
        request_date = now.date()
        revision = semantics.semantic_revision

        def can_start() -> bool:
            if not self._historical_index_probe_current(request_date, revision):
                return False
            if market_window is None:
                return True
            try:
                return market_window.blocker(self._clock.now()) is None
            except ValueError:
                return False

        def probe() -> None:
            if not can_start():
                raise RequestNotStartedError("historical index authority or market time changed")
            self.index_provider.probe_historical_minutes_permission(index_code, anchor)

        try:
            await self._controller.recheck_permission(
                operation,
                probe,
                work_key=f"permission:idx_mins:{index_code.value}:{anchor}",
                validate_after=lambda: self._historical_index_probe_current(
                    request_date, revision,
                ),
                can_start=can_start,
            )
            self._historical_probe_deferred_until = None
            return PermissionMaintenanceResult.PROBED
        except RequestNotStartedError:
            return PermissionMaintenanceResult.DEFERRED
        except RequestControlError:
            # The durable permission latch and 300-second reservation remain in place.
            return PermissionMaintenanceResult.FAILED

    def _defer_permission_blocked_index_recoveries(self, now: datetime) -> None:
        """A zero-call historical block cannot spend an index recovery attempt."""
        if not self._controller.is_permission_blocked(
            TushareOperation.INDEX_HISTORICAL_MINUTES
        ):
            return
        records = self.index_service.recovery_records()
        affected = frozenset(
            code for code, _cutoff, _first, _attempts, due in records
            if due <= now
            and not self.index_provider.historical_minutes_cached(code, _cutoff.date())
        )
        if affected:
            permission_due = self.next_historical_index_permission_due_at()
            self.index_service.defer_due_recoveries(
                now=now,
                until=max(now + timedelta(seconds=30), permission_due or now),
                index_codes=affected,
            )

    async def refresh_references(self, trade_date: date) -> None:
        plans = self.active_plans(trade_date)
        captured_key = self._reference_dependency_key(trade_date, plans)
        self._reference_key = None
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
                raise ReferenceDataUnavailableError("current trading calendar is unavailable")
            self._commit_trading_days(
                days, trade_date=trade_date, captured_key=captured_key,
            )
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
                self._assert_reference_generation(trade_date, captured_key)
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
                raise ReferenceDataUnavailableError("official reference history is unavailable")
            with self._work() as work:
                work.history.upsert_daily_bars(bars)
                self._assert_reference_generation(trade_date, captured_key)
                work.commit()
        current_key = self._reference_dependency_key(trade_date, self.active_plans(trade_date))
        if captured_key != current_key:
            raise ReferenceDependenciesChangedError
        self._reference_key = captured_key

    def _commit_trading_days(
        self, days: Sequence[TradingDay], *, trade_date: date,
        captured_key: ReferenceDependencyKey,
    ) -> None:
        """Revoke current SSE proof before the sole supported calendar write path."""

        sse_days = tuple(day for day in days if day.exchange == "SSE")
        if sse_days:
            with self._calendar_epoch_lock:
                self._calendar_epoch += 1
                self._calendar_revoked.set()
        with self._work() as work:
            work.references.upsert_trading_days(days)
            self._assert_reference_generation(trade_date, captured_key)
            work.commit()
        if sse_days:
            self._calendar = {day.cal_date: day.is_open for day in sse_days}
            with self._calendar_epoch_lock:
                self._calendar_revoked = Event()

    def _assert_reference_generation(
        self, trade_date: date, captured_key: ReferenceDependencyKey,
    ) -> None:
        if (
            not self._configuration_current()
            or not self._stock_certification_current()
            or not self._generation_current()
            or captured_key != self._reference_dependency_key(
                trade_date, self.active_plans(trade_date)
            )
            or self._admission_revoked()
        ):
            raise ReferenceDependenciesChangedError

    def _reference_dependency_key(
        self, trade_date: date, plans: tuple[ExecutableTradePlan, ...],
    ) -> ReferenceDependencyKey:
        """Read activation and immutable version together; never trust symbol alone.

        Plan content captures the required dependency set, including family and
        conditions. Only stock semantics govern these calendar/limits/history
        references. Operational observation metadata is deliberately excluded.
        """
        dependencies = []
        if plans:
            with self._work() as work:
                for plan in plans:
                    active = work.plans.get_active(plan.symbol)
                    version = work.plans.get_version(plan.plan_id, plan.version)
                    plan_hash = plan_sha256(plan)
                    if (
                        active is None or version is None
                        or active.plan_version_id != version.id
                        or version.plan_hash != plan_hash
                    ):
                        raise ReferenceDependenciesChangedError
                    dependencies.append(PlanReferenceDependency(
                        symbol=plan.symbol,
                        family=(
                            "EXPLICIT_RULES" if isinstance(plan, ExplicitTradePlan) else "LEGACY"
                        ),
                        plan_hash=plan_hash, plan_version_id=active.plan_version_id,
                        activation_revision=active.revision, activated_at=active.activated_at,
                    ))
        semantics = (
            self._load_semantic_binding("STOCK")
            if getattr(self, "_stock_semantics", None) is not None else None
        )
        return ReferenceDependencyKey(
            trade_date, tuple(sorted(dependencies, key=lambda item: item.symbol)),
            semantics.semantic_revision if semantics is not None else None,
        )

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
        self.restore_index_recoveries()
        if self._historical_reader is None:
            await self._recover_pending_close_batches(trade_date)
        else:
            await self._recover_historical_closes(
                before_date=(
                    trade_date
                    if self._clock.now().time() < DEFAULT_OFFICIAL_CLOSE_ATTEMPTS[0]
                    else None
                ),
            )
        result = await self.recovery.recover_startup(trade_date=trade_date)
        _ensure_recovery_complete(result)

    def restore_index_recoveries(self) -> None:
        """Restore persisted display-index retries without stock recovery work."""

        with self._work() as work:
            latest = work.projections.list_latest_market_index_snapshots(
                mapping_version="board-index-map-v1",
                index_codes=ALWAYS_ON_INDEX_CODES,
            )
            records = work.projections.list_market_index_recoveries()
        self.index_service.restore_recoveries(
            snapshots={record.snapshot.index_code: record.snapshot for record in latest},
            records=records,
            now=self._clock.now(),
        )

    async def _recover_historical_closes(self, *, before_date: date | None) -> None:
        """Resume each legacy plan independently after its last committed close."""

        reader = self._historical_reader
        evaluator = self.historical_evaluations
        if reader is None or evaluator is None:
            return
        observed_at = self._clock.now()
        active_plans = self._persisted_active_plans()
        current_symbols = {plan.symbol for plan in active_plans}
        for stale_symbol in set(self._historical_identity) - current_symbols:
            self._historical_identity.pop(stale_symbol, None)
            self._historical_blocked.pop(stale_symbol, None)
            self._historical_retry_at.pop(stale_symbol, None)
        for plan in active_plans:
            if not isinstance(plan, TradePlan):
                self._historical_identity.pop(plan.symbol, None)
                self._historical_blocked.pop(plan.symbol, None)
                self._historical_retry_at.pop(plan.symbol, None)
                continue
            with self._work() as work:
                active = work.plans.get_active(plan.symbol)
            if active is None:
                raise ReferenceDependenciesChangedError
            identity = (plan_sha256(plan), active.revision, active.activated_at)
            if self._historical_identity.get(plan.symbol) != identity:
                self._historical_identity[plan.symbol] = identity
                self._historical_blocked.pop(plan.symbol, None)
                self._historical_retry_at.pop(plan.symbol, None)
            retry_at = self._historical_retry_at.get(plan.symbol)
            if retry_at is not None and observed_at < retry_at:
                continue
            try:
                missing = reader.missing_targets(plan.symbol, observed_at)
                if isinstance(missing, UnknownHistoricalClose):
                    self._historical_blocked[plan.symbol] = missing.reason.value
                    self._historical_retry_at[plan.symbol] = observed_at + timedelta(minutes=5)
                    continue
                due = tuple(day for day in missing if before_date is None or day < before_date)
                for day in due:
                    with self._work() as work:
                        current = work.plans.get_active(plan.symbol)
                    current_identity = (
                        None if current is None
                        else (plan_sha256(plan), current.revision, current.activated_at)
                    )
                    if current_identity != identity:
                        raise ReferenceDependenciesChangedError
                    outcome = await evaluator.run_official_close(
                        plan=plan, trade_date=day,
                        evaluated_at=max(self._clock.now(), datetime.combine(
                            day, DEFAULT_OFFICIAL_CLOSE_ATTEMPTS[0], observed_at.tzinfo,
                        )),
                        close_attempt=1,
                    )
                    if outcome.status not in {
                        OfficialCloseCycleStatus.COMMITTED,
                        OfficialCloseCycleStatus.DUPLICATE,
                    }:
                        raise HistoricalCloseUnavailableError("Historical close remains incomplete")
            except ReferenceDependenciesChangedError:
                self._historical_identity.pop(plan.symbol, None)
                self._historical_blocked.pop(plan.symbol, None)
                self._historical_retry_at.pop(plan.symbol, None)
            except (HistoricalCloseUnavailableError, StaleHistoricalCloseError):
                self._historical_blocked[plan.symbol] = "HISTORICAL_EVIDENCE_UNAVAILABLE"
                self._historical_retry_at[plan.symbol] = observed_at + timedelta(minutes=5)
            except Exception:
                self._historical_blocked[plan.symbol] = "HISTORICAL_RECOVERY_FAILED"
                self._historical_retry_at[plan.symbol] = observed_at + timedelta(seconds=30)
            else:
                self._historical_blocked.pop(plan.symbol, None)
                self._historical_retry_at.pop(plan.symbol, None)

    def recovery_issues(self) -> tuple[RecoveryIssueSnapshot, ...]:
        """Expose only stable reasons; never leak provider or storage exception text."""

        return tuple(
            RecoveryIssueSnapshot(
                symbol=symbol,
                reason=reason,
                next_retry_at=self._historical_retry_at[symbol],
            )
            for symbol, reason in sorted(self._historical_blocked.items())
        )

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
            if not self._decision_commit_current():
                raise ReferenceDependenciesChangedError
            work.commit()

    def load_minutes(self, symbol: str, *, start: datetime, end: datetime):
        with self._work() as work:
            return work.history.list_minutes(symbol, start=start, end=end)

    def persist_five_minute(self, bar: FiveMinuteBar) -> None:
        with self._work() as work:
            work.history.upsert_five_minute(**bar.model_dump())
            if not self._decision_commit_current():
                raise ReferenceDependenciesChangedError
            work.commit()

    async def run_deadline(self, deadline: MarketDeadline):
        if deadline.kind is DeadlineKind.INDEX_PERMISSION:
            realtime_due = self.next_realtime_index_permission_due_at()
            historical_due = self.next_historical_index_permission_due_at()
            if realtime_due is not None and (
                historical_due is None or realtime_due < historical_due
            ):
                return await self._maybe_recheck_realtime_index_permission()
            return await self._maybe_recheck_historical_index_permission()
        if deadline.kind is DeadlineKind.INDEX_RECOVERY:
            self._defer_permission_blocked_index_recoveries(self._clock.now())
            return await self.evaluations.recover_transient_market_indexes(
                evaluated_at=max(self._clock.now(), deadline.due_at)
            )
        plans = self.active_plans(deadline.trade_date)
        if not plans:
            await self._refresh_dashboard_indexes(deadline)
            return ()
        if not self._stock_certification_current():
            raise RuntimeError("stock certification must be refreshed before execution")
        if (
            deadline.kind is DeadlineKind.REALTIME_MINUTE
            and deadline.bar_end is not None
            and plans
            and all(isinstance(plan, ExplicitTradePlan) for plan in plans)
        ):
            with self._work() as work:
                complete = all(
                    (active := work.plans.get_active(plan.symbol)) is not None
                    and active.activated_at <= deadline.bar_end
                    and work.explicit_rules.get(
                        plan_hash=plan_sha256(plan), symbol=plan.symbol,
                        target_bucket_end=deadline.bar_end,
                        activation_revision=active.revision,
                    ) is not None
                    for plan in plans
                )
            if complete:
                await self._refresh_dashboard_indexes(deadline)
                return ()
        reference_key = self._reference_dependency_key(deadline.trade_date, plans)
        if self._reference_key != reference_key:
            await self.refresh_references(deadline.trade_date)
        if self._reference_key != reference_key:
            raise ReferenceDependenciesChangedError
        await self._recover_historical_closes(before_date=deadline.trade_date)
        plans = self.active_plans(deadline.trade_date)
        if reference_key != self._reference_dependency_key(deadline.trade_date, plans):
            raise ReferenceDependenciesChangedError
        cutoff = deadline.bar_end or datetime.combine(
            deadline.trade_date, time(15), deadline.due_at.tzinfo
        )
        selected = []
        with self._work() as work:
            for plan in plans:
                if plan.symbol in self._historical_blocked:
                    continue
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
                        if (
                            deadline.bar_end is not None
                            and work.explicit_rules.get(
                                plan_hash=plan_sha256(plan),
                                symbol=plan.symbol,
                                target_bucket_end=deadline.bar_end,
                                activation_revision=active.revision,
                            )
                            is not None
                        ):
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
                        official_trade_date=(None if deadline.bar_end else deadline.trade_date),
                        formula_version=plan.monitoring.indicator_formula_version,
                    ):
                        continue
                selected.append(plan)
        if not selected:
            await self._refresh_dashboard_indexes(deadline)
            return ()
        if not self._stock_certification_current():
            raise RuntimeError("stock certification must be refreshed before execution")
        if self._reference_key != reference_key:
            await self.refresh_references(deadline.trade_date)
        if (
            self._reference_key != reference_key
            or reference_key != self._reference_dependency_key(
                deadline.trade_date, self.active_plans(deadline.trade_date),
            )
        ):
            raise ReferenceDependenciesChangedError
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
        if deadline.kind is DeadlineKind.OFFICIAL_CLOSE:
            await self.evaluations.run_official_close_batch(
                plans=(),
                trade_date=deadline.trade_date,
                evaluated_at=observed_at,
                close_attempt=deadline.close_attempt,
            )
