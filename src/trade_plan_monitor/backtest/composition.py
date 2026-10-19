"""Lazy production composition for the isolated backtest HTTP resources."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import UUID

from anyio import sleep
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from trade_plan_monitor.backtest.application import (
    create_backtest_job_operations,
)
from trade_plan_monitor.backtest.canonical import canonical_decimal, canonical_json
from trade_plan_monitor.backtest.cursor_key_security import (
    create_cursor_key_file,
    read_cursor_key_file,
)
from trade_plan_monitor.backtest.dataset import FrozenMarketIndexDatasetReader
from trade_plan_monitor.backtest.dataset_service import (
    BacktestDatasetFilters,
    BacktestDatasetService,
    DatasetNotFoundError,
)
from trade_plan_monitor.backtest.index_data import (
    MarketIndexReplaySeries,
    build_backtest_index_requirement,
    build_reference_market_result,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestJobCoordinator,
    BacktestJobKind,
    BacktestJobRepository,
    BacktestJobStatus,
    BacktestRunJobRequest,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestJobReceipt as DomainBacktestJobReceipt,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestJobView as DomainBacktestJobView,
)
from trade_plan_monitor.backtest.jobs.models import LoopInputReference, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import (
    BacktestJobSubmissionBinding,
    BacktestRunSubmissionReservation,
    JobAdmissionError,
)
from trade_plan_monitor.backtest.loop_dataset import (
    freeze_scheduled_loop_dataset,
)
from trade_plan_monitor.backtest.loop_input import (
    LoopCosts,
    LoopResponsePolicy,
    MonitorLoopInput,
    ScheduledLoopInput,
    WorkbenchLoopInput,
)
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.pagination import HmacCursorSigner, InvalidCursorError
from trade_plan_monitor.backtest.preparation_review import (
    FrozenPreparedCollection,
    FrozenPreparedPlan,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.reference_projection import (
    project_decision_reference_market,
)
from trade_plan_monitor.backtest.reporting import iter_export_fills, iter_export_summary
from trade_plan_monitor.backtest.result_service import (
    BacktestDetailFilters,
    BacktestResultNotFoundError,
    BacktestResultService,
    BacktestRunFilters,
    BacktestRunMembershipConflictError,
)
from trade_plan_monitor.backtest.results import (
    BacktestArtifactAvailability,
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunRecord,
    ResultConflictError,
)
from trade_plan_monitor.backtest.run_input import (
    BacktestInitialLotInput,
    BacktestRunInput,
)
from trade_plan_monitor.backtest.service_lifecycle import (
    BacktestServiceUnavailable,
    LazyBacktestLifecycle,
)
from trade_plan_monitor.backtest.thread_lifecycle import (
    BacktestMetadataThread,
    BacktestResultReadThread,
)
from trade_plan_monitor.backtest.time import (
    SHANGHAI,
    format_shanghai_datetime,
    parse_shanghai_datetime,
)
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchPlanSelection,
    WorkbenchSelectionView,
)
from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    EvaluationResult,
    RuleEvidence,
)
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_index.identity import resolve_board_reference
from trade_plan_monitor.market_index.models import (
    MarketIndexIndicatorFact,
    MarketIndexInterval,
)
from trade_plan_monitor.web.backtest_export import (
    BacktestExportKind,
    PreparedBacktestExport,
)
from trade_plan_monitor.web.backtest_pagination import (
    BacktestApiCursorSigner,
    BacktestCursorState,
    BacktestMembershipConflictError,
)
from trade_plan_monitor.web.backtest_schemas import (
    BacktestDatasetFiltersView,
    BacktestDatasetPage,
    BacktestDatasetScopeInput,
    BacktestDatasetVerificationCommand,
    BacktestDatasetView,
    BacktestDataSyncCommand,
    BacktestDecisionEvidenceView,
    BacktestDecisionView,
    BacktestDetailFiltersView,
    BacktestDetailPage,
    BacktestEquityPointView,
    BacktestEquitySeries,
    BacktestExecutionOutcomeView,
    BacktestFillFiltersView,
    BacktestFillPage,
    BacktestFillView,
    BacktestJobFiltersView,
    BacktestJobPage,
    BacktestJobReceipt,
    BacktestJobView,
    BacktestLoopEventView,
    BacktestLoopFillView,
    BacktestLoopRunSummaryView,
    BacktestLoopRunView,
    BacktestMarketIndexPointView,
    BacktestMarketIndexSeriesView,
    BacktestReferenceMarketCoverageView,
    BacktestReferenceMarketView,
    BacktestRunCommand,
    BacktestRunFiltersView,
    BacktestRunPage,
    BacktestRunSummaryView,
    BacktestRunView,
    BacktestScheduledEventView,
    BacktestScheduledRunSummaryView,
    BacktestScheduledRunView,
    BacktestSignalView,
    PreparedBacktestDataView,
    PreparedBacktestRunCommand,
    ScheduledPreparedBacktestRunCommand,
    WorkbenchBacktestDataView,
    WorkbenchBacktestRunCommand,
    WorkbenchBacktestRunView,
)
from trade_plan_monitor.web.cursor_keys import load_or_create_cursor_key
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers.backtest_data import BacktestJobSubmissionOutcome
from trade_plan_monitor.web.routers.backtest_jobs import (
    BacktestJobCancellationCommand,
    BacktestJobCancellationOutcome,
)
from trade_plan_monitor.web.routers.backtest_results import downsample_market_index_points
from trade_plan_monitor.web.routers.backtest_runs import (
    BacktestRunPinCommand,
    BacktestRunSubmissionOutcome,
)
from trade_plan_monitor.web.routers.plans import PlanVersionView
from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    ErrorDetail,
    MutationContext,
    validate_api_response,
)

DEFAULT_BACKTEST_MARKET_DATABASE = Path("data/backtest-market.sqlite3")
DEFAULT_BACKTEST_RESULTS_DATABASE = Path("data/backtest-results.sqlite3")
DEFAULT_BACKTEST_CURSOR_KEY = Path("data/backtest-cursor.key")
DEFAULT_BACKTEST_PREPARATION_DATABASE = Path("data/backtest-preparation.sqlite3")
_SQLITE_BUSY_TIMEOUT_MS = 2_000
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_RETRY_AFTER_SECONDS = 2
_RUN_CLAIM_POLL_SECONDS = 0.025
_RUN_CLAIM_POLL_ATTEMPTS = 200
_RUN_RESERVATION_HEARTBEAT_SECONDS = 10.0
_JOB_ROUTE = "/backtest-jobs"
_JOB_ORDER = "createdAt DESC,jobId DESC"
_EMPTY_JOB_HIGH_WATER = ("1970-01-01T00:00:00.000000+08:00", "0")
_EMPTY_RESULT_HIGH_WATER = ("1970-01-01T00:00:00.000000+08:00", "0")
_RUN_ROUTE = "runs"
_FILL_ROUTE = "backtest-results:fills"
_DETAIL_ROUTE = "backtest-results:details"
_RUN_ORDER = "completedAt:desc,runId:desc"
_FILL_ORDER = "filledAt:asc,fillId:asc"
_DETAIL_ORDER = "eventAt:asc,detailId:asc"


class PlanSnapshotReader(Protocol):
    """Read exactly one immutable live plan version for a new run intent."""

    async def get_plan_version(self, *, version_id: str) -> object | None: ...


class Coordinator(Protocol):
    async def start(self) -> None: ...

    async def shutdown(self) -> None: ...


class _DeferredCoordinator:
    """Metadata preparation retains no coordinator or execution thread."""

    def __init__(self, factory: Callable[[], BacktestJobCoordinator]) -> None:
        self._factory = factory
        self._instance: BacktestJobCoordinator | None = None
        self._lock = Lock()
        self._pending_authorizations: frozenset[str] = frozenset()

    async def start(self) -> None:
        with self._lock:
            if self._instance is None:
                self._instance = self._factory()
                self._instance.authorize_jobs(self._pending_authorizations)
                self._pending_authorizations = frozenset()
        await self._instance.start()

    @property
    def authorized_job_ids(self) -> frozenset[str]:
        with self._lock:
            return (
                self._pending_authorizations if self._instance is None
                else self._instance.authorized_job_ids
            )

    @property
    def physically_drained(self) -> bool:
        return self._instance is None or self._instance.physically_drained

    def authorize_new_job(self, job_id: str) -> None:
        with self._lock:
            if self._instance is None:
                self._pending_authorizations = frozenset({job_id})
            elif self._instance.accepting:
                self._instance.authorize_jobs(frozenset({job_id}))

    def authorize_jobs(self, job_ids: frozenset[str]) -> None:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("execution must be explicitly activated before resume")
            self._instance.authorize_jobs(job_ids)

    async def shutdown(self) -> None:
        if self._instance is not None:
            await self._instance.shutdown()

    def raise_if_failed(self) -> None:
        if self._instance is not None:
            self._instance.raise_if_failed()


class _PreparationLifecycle:
    """Acquire only the existing tagged preparation store; AI remains unbound on reads."""

    def __init__(self, path: Path, repository: BacktestJobRepository):
        store = PreparationStore(path, busy_timeout_ms=_SQLITE_BUSY_TIMEOUT_MS)
        self.read_service = self.operation_service = PreparationService(store, repository)

    @property
    def outstanding_work(self):
        return self.read_service.outstanding_work

    async def start(self):
        pass  # PreparationService admits its own calls; there is no job coordinator here.

    async def stop(self):
        try:
            await self.read_service.stop()
        except BacktestServiceUnavailable:
            await self.read_service.wait_for_drain()


class BacktestComposition:
    """Own one service façade and exactly one coordinator lifecycle."""

    def __init__(
        self,
        *,
        read_service: object,
        operation_service: object,
        coordinator: Coordinator,
        preparation_factory: Callable[[], _PreparationLifecycle] | None = None,
    ) -> None:
        if not callable(getattr(coordinator, "start", None)) or not callable(
            getattr(coordinator, "shutdown", None)
        ):
            raise TypeError("coordinator must expose start and shutdown")
        self._read_service = read_service
        self._operation_service = operation_service
        self._coordinator = coordinator
        self._started = False
        self._stopped = False
        self._preparations = (
            LazyBacktestLifecycle(preparation_factory) if preparation_factory is not None else None
        )

    @property
    def read_service(self) -> object:
        return self._read_service

    @property
    def operation_service(self) -> object:
        return self._operation_service

    @property
    def authorized_job_ids(self) -> frozenset[str]:
        return getattr(self._coordinator, "authorized_job_ids", frozenset())

    @property
    def outstanding_work(self) -> int:
        return (
            int(not getattr(self._coordinator, "physically_drained", True))
            + getattr(self._read_service, "outstanding_work", 0)
            + (self._preparations.snapshot.outstanding_work if self._preparations else 0)
        )

    async def ensure_preparations(self) -> PreparationService:
        if self._stopped or self._preparations is None:
            raise BacktestServiceUnavailable()
        capability = await self._preparations.ensure()
        return capability.read_service

    async def resume_jobs(self, job_ids: frozenset[str]) -> None:
        await self._operation_service.resume_jobs(job_ids)

    async def start(self) -> None:
        if self._stopped:
            raise RuntimeError("backtest composition is already stopped")
        if self._started:
            return
        await self._coordinator.start()
        self._started = True

    async def stop(self) -> None:
        if self._stopped:
            return
        if self._preparations is not None:
            try:
                await self._preparations.stop()
            except BacktestServiceUnavailable:
                # The outer lazy owner observes timeout; cleanup keeps physical ownership.
                await self._preparations.wait_for_drain()
        await self._coordinator.shutdown()
        stop_metadata = getattr(self._read_service, "stop_metadata", None)
        if stop_metadata is not None:
            await stop_metadata()
        self._stopped = True
        self._started = False


def create_backtest_composition_factory(
    *,
    config_path: Path,
    plan_snapshot_reader: PlanSnapshotReader | None,
    market_database: Path = DEFAULT_BACKTEST_MARKET_DATABASE,
    results_database: Path = DEFAULT_BACKTEST_RESULTS_DATABASE,
    cursor_key_path: Path = DEFAULT_BACKTEST_CURSOR_KEY,
    preparation_database: Path = DEFAULT_BACKTEST_PREPARATION_DATABASE,
) -> Callable[[], BacktestComposition]:
    """Return an inert closure; stores, key material, and threads stay unopened."""

    for name, value in (
        ("config_path", config_path),
        ("market_database", market_database),
        ("results_database", results_database),
        ("cursor_key_path", cursor_key_path),
        ("preparation_database", preparation_database),
    ):
        if not isinstance(value, Path):
            raise TypeError(f"{name} must be a Path")
    if plan_snapshot_reader is not None and not callable(
        getattr(plan_snapshot_reader, "get_plan_version", None)
    ):
        raise TypeError("plan_snapshot_reader must expose get_plan_version")

    def factory() -> BacktestComposition:
        return create_backtest_composition(
            config_path=config_path,
            plan_snapshot_reader=plan_snapshot_reader,
            market_database=market_database,
            results_database=results_database,
            cursor_key_path=cursor_key_path,
            preparation_database=preparation_database,
        )

    return factory


def create_backtest_composition(
    *,
    config_path: Path,
    plan_snapshot_reader: PlanSnapshotReader | None,
    market_database: Path = DEFAULT_BACKTEST_MARKET_DATABASE,
    results_database: Path = DEFAULT_BACKTEST_RESULTS_DATABASE,
    cursor_key_path: Path = DEFAULT_BACKTEST_CURSOR_KEY,
    preparation_database: Path = DEFAULT_BACKTEST_PREPARATION_DATABASE,
) -> BacktestComposition:
    """Prepare local metadata only after explicit use; execution stays dormant."""

    key = _load_or_create_cursor_key(cursor_key_path)
    market_store = BacktestMarketStore(
        market_database,
        busy_timeout_ms=_SQLITE_BUSY_TIMEOUT_MS,
    )
    repository = BacktestJobRepository(
        results_database,
        busy_timeout_ms=_SQLITE_BUSY_TIMEOUT_MS,
    )
    result_store = BacktestResultStore(
        results_database,
        busy_timeout_ms=_SQLITE_BUSY_TIMEOUT_MS,
    )
    coordinator = _DeferredCoordinator(
        lambda: BacktestJobCoordinator(
            repository=repository,
            operations=create_backtest_job_operations(
                config_path=config_path, market_store=market_store, result_store=result_store,
            ),
            shutdown_timeout_seconds=_SHUTDOWN_TIMEOUT_SECONDS,
            authorized_job_ids=frozenset(),
        ),
    )
    domain_signer = HmacCursorSigner(key)

    async def read_prepared(identity: str) -> FrozenPreparedPlan:
        preparation = await composition.ensure_preparations()
        return await preparation.get_frozen(identity)

    service = _ProductionBacktestService(
        plan_snapshot_reader=plan_snapshot_reader,
        market_store=market_store,
        repository=repository,
        result_store=result_store,
        dataset_service=BacktestDatasetService(
            store=market_store,
            cursor_signer=domain_signer,
        ),
        result_service=BacktestResultService(
            store=result_store,
            cursor_signer=domain_signer,
        ),
        coordinator=coordinator,
        result_cursor_signer=domain_signer,
        job_cursor_signer=BacktestApiCursorSigner(key),
        prepared_plan_reader=read_prepared,
        preparation_service_reader=lambda: composition.ensure_preparations(),
    )
    composition = BacktestComposition(
        read_service=service,
        operation_service=service,
        coordinator=coordinator,
        preparation_factory=lambda: _PreparationLifecycle(preparation_database, repository),
    )
    return composition


class _ProductionBacktestService:
    """Closed application façade shared by every focused backtest router."""

    def __init__(
        self,
        *,
        plan_snapshot_reader: PlanSnapshotReader | None,
        market_store: object,
        repository: BacktestJobRepository,
        result_store: BacktestResultStore,
        dataset_service: BacktestDatasetService,
        result_service: BacktestResultService,
        coordinator: BacktestJobCoordinator,
        result_cursor_signer: HmacCursorSigner,
        job_cursor_signer: BacktestApiCursorSigner,
        prepared_plan_reader: Callable[[str], Awaitable[FrozenPreparedPlan]] | None = None,
        preparation_service_reader=None,
    ) -> None:
        self._plan_snapshot_reader = plan_snapshot_reader
        self._market_store = market_store
        self._repository = repository
        self._result_store = result_store
        self._datasets = dataset_service
        self._results = result_service
        self._coordinator = coordinator
        self._result_cursor_signer = result_cursor_signer
        self._job_cursor_signer = job_cursor_signer
        self._prepared_plan_reader = prepared_plan_reader
        self._preparation_service_reader = preparation_service_reader
        self._metadata_thread = BacktestMetadataThread()
        self._reservation_thread = BacktestMetadataThread()
        self._result_thread = BacktestResultReadThread()

    @property
    def outstanding_work(self) -> int:
        return (self._metadata_thread.outstanding_work
                + self._reservation_thread.outstanding_work
                + self._result_thread.outstanding_work)

    async def stop_metadata(self) -> None:
        await self._metadata_thread.stop()
        await self._reservation_thread.stop()
        await self._result_thread.stop()

    async def _run_sync[ResultT](
        self, function: Callable[..., ResultT], /, *args: object,
        _read_only: bool = False, **kwargs: object,
    ) -> ResultT:
        runner = self._metadata_thread.read if _read_only else self._metadata_thread.run
        return await self._call_sync(runner, function, *args, **kwargs)

    async def _call_sync[ResultT](
        self, runner, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        try:
            return await runner(function, *args, **kwargs)
        except BacktestServiceUnavailable:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) not in {
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
            }:
                raise
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None

    async def _read_sync[ResultT](
        self, function: Callable[..., ResultT], /, *args: object, **kwargs: object,
    ) -> ResultT:
        return await self._run_sync(function, *args, _read_only=True, **kwargs)

    async def _read_result[ResultT](
        self, key: tuple[str, ...], function: Callable[..., ResultT], /,
        *args: object, **kwargs: object,
    ) -> ResultT:
        return await self._call_sync(
            partial(self._result_thread.read_shared, key), function, *args, **kwargs,
        )

    async def _selection_operation(self, operation, *args):
        if self._preparation_service_reader is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        try:
            service = await self._preparation_service_reader()
            return await service.selection(operation, *args)
        except PreparationConflictError:
            raise ApiError(ApiErrorCode.CONFLICT) from None
        except BacktestServiceUnavailable:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) not in {
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
            }:
                raise
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        except ValueError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None

    async def create_plan_selection(self, *, command, context):
        previous = await self._selection_operation("replay", command, context.idempotency_key)
        if previous is not None:
            return WorkbenchSelectionView.project(previous)
        reader = getattr(self._plan_snapshot_reader, "get_reviewed_backtest_plan", None)
        if reader is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        from trade_plan_monitor.web.plan_service import PlanSaveBlockedError

        try:
            reviewed = await reader(version_id=str(command.plan.plan_version_id))
        except PlanSaveBlockedError:
            raise ApiError(ApiErrorCode.CONFLICT) from None
        except (sqlite3.OperationalError, SQLAlchemyOperationalError) as error:
            original = error.orig if isinstance(error, SQLAlchemyOperationalError) else error
            if getattr(original, "sqlite_errorcode", None) not in {
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
            }:
                raise
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        if reviewed is None:
            raise ApiError(ApiErrorCode.NOT_FOUND)
        selected = await self._selection_operation(
            "save", command, reviewed, context.idempotency_key
        )
        return WorkbenchSelectionView.project(selected)

    async def get_plan_selection(self, *, selection_id):
        value = await self._selection_operation("get", selection_id)
        if value is None:
            raise ApiError(ApiErrorCode.NOT_FOUND)
        return WorkbenchSelectionView.project(value)

    async def _read_selection(self, selection_id, selection_hash):
        value = (await self.get_plan_selection(selection_id=selection_id)).frozen
        if value.manifest_hash != selection_hash:
            raise ApiError(ApiErrorCode.CONFLICT)
        return value

    async def check_selection_data(self, *, selection_id, selection_hash, end_date=None):
        selected = await self._read_selection(selection_id, selection_hash)
        return await self._read_sync(self._check_prepared_data, selected, end_date)

    async def submit_data_sync(
        self,
        *,
        command: BacktestDataSyncCommand,
        context: MutationContext,
    ) -> BacktestJobSubmissionOutcome:
        self._require_coordinator_healthy()
        request = DataSyncJobRequest(
            scope=_scope_request(command.scope),
            refresh=command.refresh,
            allow_network=True,
        )
        try:
            receipt = await self._run_sync(
                self._repository.submit,
                request,
                context.idempotency_key,
                request_id=context.request_id,
                on_admitted=self._coordinator.authorize_new_job,
            )
        except JobAdmissionError as error:
            raise _job_admission_api_error(error) from None
        return _data_submission_outcome(receipt)

    async def submit_dataset_verification(
        self,
        *,
        command: BacktestDatasetVerificationCommand,
        context: MutationContext,
    ) -> BacktestJobSubmissionOutcome:
        self._require_coordinator_healthy()
        try:
            receipt = await self._run_sync(
                self._repository.submit,
                DatasetVerifyJobRequest(scope=_scope_request(command.scope)),
                context.idempotency_key,
                on_admitted=self._coordinator.authorize_new_job,
            )
        except JobAdmissionError as error:
            raise _job_admission_api_error(error) from None
        return _data_submission_outcome(receipt)

    async def submit_run(
        self,
        *,
        command: BacktestRunCommand | PreparedBacktestRunCommand,
        context: MutationContext,
    ) -> BacktestRunSubmissionOutcome:
        self._require_coordinator_healthy()
        reservation: BacktestRunSubmissionReservation | None = None
        reservation_lost = asyncio.Event()
        reservation_heartbeat: asyncio.Task[None] | None = None
        intent_json = canonical_json(command.canonical_payload())
        try:
            for _attempt in range(_RUN_CLAIM_POLL_ATTEMPTS):
                claim = await self._run_sync(
                    self._repository.claim_run_submission,
                    intent_json,
                    context.idempotency_key,
                )
                if isinstance(claim, BacktestJobSubmissionBinding):
                    if isinstance(
                        command, (PreparedBacktestRunCommand, WorkbenchBacktestRunCommand)
                    ):
                        _verify_prepared_submission_binding(claim)
                        return _run_submission_outcome(claim.receipt)
                    if (
                        claim.receipt.kind is not BacktestJobKind.BACKTEST_RUN
                        or not _persisted_run_matches_command(
                            claim.canonical_request_json,
                            command,
                        )
                    ):
                        raise ApiError(ApiErrorCode.CONFLICT)
                    return _run_submission_outcome(claim.receipt)
                if isinstance(claim, BacktestRunSubmissionReservation):
                    reservation = claim
                    reservation_heartbeat = asyncio.create_task(
                        self._keep_run_reservation_alive(reservation, reservation_lost),
                        name="backtest-run-submission-reservation",
                    )
                    break
                await sleep(_RUN_CLAIM_POLL_SECONDS)
            else:
                raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
            if isinstance(command, (PreparedBacktestRunCommand, WorkbenchBacktestRunCommand)):
                receipt = await self._submit_prepared_run(command, reservation, reservation_lost)
                reservation = None
                return _run_submission_outcome(receipt)
            if self._plan_snapshot_reader is None:
                raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
            value = await self._plan_snapshot_reader.get_plan_version(
                version_id=str(command.plan_version_id),
            )
            if value is None:
                raise ApiError(ApiErrorCode.NOT_FOUND)
            try:
                snapshot = validate_api_response(value, PlanVersionView)
            except ValidationError:
                raise RuntimeError("plan snapshot reader returned an invalid version") from None
            # Isolated historical backtests inspect frozen plans independently
            # of current activation authority. Other unresolved review blockers
            # still prevent accepting a snapshot for a new run.
            historical_review_only = (
                snapshot.obsolete_reason == "LEGACY_PLANS_REQUIRE_REVIEW"
                and all(
                    not issue.activation_blocking or issue.code == "LEGACY_PLANS_REQUIRE_REVIEW"
                    for issue in snapshot.validation_issues
                )
                and not any(not issue.resolved for issue in snapshot.review_issues)
                and not snapshot.unresolved_review_issues
            )
            if snapshot.id != command.plan_version_id or (
                not snapshot.can_activate and not historical_review_only
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
            plan = load_plan_json(snapshot.plan_json)
            current = plan.schema_version == 5
            if current and (snapshot.review_id is None or snapshot.content_hash is None
                or command.research_input is None
                or command.research_input.review.content_hash != snapshot.content_hash):
                raise ApiError(ApiErrorCode.CONFLICT)
            try:
                manifest = await self._run_sync(
                    self._market_store.dataset_manifest,
                    command.dataset_hash,
                )
            except KeyError:
                raise ApiError(ApiErrorCode.NOT_FOUND) from None
            if plan.symbol not in manifest.scope.symbols:
                raise ApiError(ApiErrorCode.CONFLICT)
            try:
                command.validate_initial_lot_limits(
                    dataset_start=manifest.scope.start,
                    core_target_qty=None if current else plan.position.core_target_qty,
                    tactical_target_qty=None if current else plan.position.tactical_target_qty,
                    max_qty=plan.position.max_qty,
                )
                run_input = BacktestRunInput.create(
                    plan=plan,
                    manifest=manifest,
                    initial_cash_fen=command.initial_cash_fen,
                    initial_lots=tuple(
                        BacktestInitialLotInput(
                            lot_key=item.lot_key,
                            bucket=item.bucket,
                            acquired_trade_date=item.acquired_trade_date,
                            quantity=item.quantity,
                            cost_basis_fen=item.cost_basis_fen,
                        )
                        for item in command.initial_lots
                    ),
                    execution_config=ExecutionConfig(
                        commission_rate=command.execution_config.commission_rate,
                        minimum_commission_fen=(command.execution_config.minimum_commission_fen),
                        stamp_duty_rate=command.execution_config.stamp_duty_rate,
                        transfer_fee_rate=command.execution_config.transfer_fee_rate,
                        buy_slippage_bps=command.execution_config.buy_slippage_bps,
                        sell_slippage_bps=command.execution_config.sell_slippage_bps,
                    ),
                    manual_event_risk=(command.event_risk_assumption == "MANUAL_EVENT_RISK"),
                    plan_version_id=command.plan_version_id,
                    research_input=command.research_input,
                )
            except ValueError:
                raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
            if reservation_lost.is_set():
                raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
            receipt = await self._run_sync(
                self._repository.finalize_run_submission,
                BacktestRunJobRequest(run_input=run_input),
                reservation,
                on_admitted=self._coordinator.authorize_new_job,
            )
            reservation = None
            return _run_submission_outcome(receipt)
        except JobAdmissionError as error:
            raise _job_admission_api_error(error) from None
        finally:
            if reservation_heartbeat is not None:
                reservation_heartbeat.cancel()
                await asyncio.gather(reservation_heartbeat, return_exceptions=True)
            if reservation is not None:
                # A cancelled waiter cannot release admission while its owned copy still runs.
                while self._metadata_thread.occupied:
                    await sleep(_RUN_CLAIM_POLL_SECONDS)
                await self._run_sync(
                    self._repository.release_run_submission,
                    reservation,
                )

    async def check_prepared_data(self, *, preparation_id, manifest_hash, end_date=None):
        """Check local evidence only; a read never starts a provider or worker."""
        if self._prepared_plan_reader is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        try:
            prepared = await self._prepared_plan_reader(preparation_id)
        except PreparationConflictError as error:
            raise ApiError(ApiErrorCode.NOT_FOUND if error.code == "PREPARATION_NOT_FOUND"
                           else ApiErrorCode.CONFLICT) from None
        except BacktestServiceUnavailable:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        if prepared.preparation_id != preparation_id or prepared.manifest_hash != manifest_hash:
            raise ApiError(ApiErrorCode.CONFLICT)
        return await self._read_sync(self._check_prepared_data, prepared, end_date)

    def _check_prepared_data(self, prepared, end_date):
        from trade_plan_monitor.backtest.automatic_data import now, prepared_dataset_request

        submitted = now()
        try:
            request = prepared_dataset_request(
                self._market_store, prepared, submitted_at=submitted, end_date=end_date,
            )
        except ValueError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        result = (freeze_scheduled_loop_dataset(self._market_store, request)
                  if isinstance(prepared, FrozenPreparedCollection)
                  else self._market_store.freeze_loop_dataset(request))
        cached = (self._result_store.reusable_loop_market(prepared, request)
                  if not result.ready else None)
        sync_scope = None
        if not result.ready and cached is None:
            expanded = prepared_dataset_request(
                self._market_store, prepared, submitted_at=submitted, end_date=end_date,
                expand_missing=True,
            )
            scope = expanded.scope
            closed_end = min(scope.end, submitted.date() - timedelta(days=1))
            if scope.warmup_start <= closed_end:
                sync_scope = BacktestDatasetScopeInput.model_validate({
                    "symbols": list(scope.symbols), "start": str(scope.warmup_start),
                    "warmupStart": str(scope.warmup_start), "end": str(closed_end),
                    "historicalProfile": scope.historical_profile.value,
                    "adjustmentPolicy": scope.adjustment_policy,
                })
        view = (
            WorkbenchBacktestDataView
            if isinstance(prepared, WorkbenchPlanSelection)
            else PreparedBacktestDataView
        )
        identity = (
            {"selectionId": prepared.selection_id, "selectionHash": prepared.manifest_hash}
            if isinstance(prepared, WorkbenchPlanSelection)
            else {"preparationId": prepared.preparation_id, "manifestHash": prepared.manifest_hash}
        )
        return view(
            **identity,
            endDate=str(request.scope.end), ready=result.ready or cached is not None,
            syncScope=sync_scope, blockers=() if cached is not None else result.blockers,
        )

    async def _submit_prepared_run(
        self,
        command: PreparedBacktestRunCommand,
        reservation: BacktestRunSubmissionReservation,
        lost: asyncio.Event,
    ) -> DomainBacktestJobReceipt:
        if isinstance(command, WorkbenchBacktestRunCommand):
            prepared = await self._read_selection(command.selection_id, command.selection_hash)
        else:
            prepared = await self._load_command_preparation(command)
        try:
            reference = await self._run_sync(
                self._freeze_prepared_input, prepared, command, reservation
            )
        except ValueError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        if lost.is_set():
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        return await self._run_sync(
            self._repository.finalize_run_submission,
            MonitorLoopJobRequest(input_reference=reference),
            reservation,
            on_admitted=self._coordinator.authorize_new_job,
        )

    async def _load_command_preparation(self, command):
        if self._prepared_plan_reader is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        try:
            prepared = await self._prepared_plan_reader(command.preparation_id)
        except PreparationConflictError as error:
            raise ApiError(
                ApiErrorCode.NOT_FOUND
                if error.code == "PREPARATION_NOT_FOUND"
                else ApiErrorCode.CONFLICT
            ) from None
        except BacktestServiceUnavailable:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None
        if (
            isinstance(prepared, FrozenPreparedCollection)
            != isinstance(command, ScheduledPreparedBacktestRunCommand)
            or prepared.preparation_id != command.preparation_id
            or prepared.manifest_hash != command.manifest_hash
        ):
            raise ApiError(ApiErrorCode.CONFLICT)
        return prepared

    def _freeze_prepared_input(
        self,
        prepared: FrozenPreparedPlan | FrozenPreparedCollection,
        command: PreparedBacktestRunCommand,
        reservation: BacktestRunSubmissionReservation,
    ) -> LoopInputReference:
        from trade_plan_monitor.backtest.automatic_data import prepared_dataset_request

        scheduled = isinstance(prepared, FrozenPreparedCollection)
        request = prepared_dataset_request(
            self._market_store, prepared, submitted_at=reservation.claimed_at,
            end_date=command.end_date,
        )
        boundary = request.boundary
        result = (freeze_scheduled_loop_dataset(self._market_store, request) if scheduled
                  else self._market_store.freeze_loop_dataset(request))
        cached = (self._result_store.reusable_loop_market(prepared, request)
                  if not result.ready else None)
        if not result.ready and cached is None:
            raise ApiError(
                ApiErrorCode.CONFLICT,
                details=tuple(
                    ErrorDetail(
                        location=("marketEvidence",),
                        code=blocker.split(":", 1)[0],
                        message="Required closed evidence or plan warm-up is unavailable.",
                    )
                    for blocker in result.blockers
                ),
            )
        dataset = result.manifest
        if cached is not None:
            # Rebind the new submission boundary; retain every immutable fact/hash.
            dataset = type(cached.dataset).build(
                boundary=boundary,
                **{name: getattr(cached.dataset, name) for name in cached.dataset.model_dump()
                   if name not in {"schema_version", "dataset_hash", "boundary"}},
            )
        workbench = isinstance(prepared, WorkbenchPlanSelection)
        input_type = (WorkbenchLoopInput if workbench else
                      ScheduledLoopInput if scheduled else MonitorLoopInput)
        run_input = input_type(
            **({"selection_hash": prepared.manifest_hash} if workbench else {}),
            schedule=prepared.schedule,
            initial_account=prepared.account,
            boundary=boundary,
            dataset_hash=dataset.dataset_hash,
            response=LoopResponsePolicy(
                mode=command.response.mode,
                response_delay_seconds=command.response.response_delay_seconds,
            ),
            costs=LoopCosts(**command.costs.model_dump(mode="python", by_alias=False)),
        )
        return self._result_store.record_loop_input(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            market_source=None if cached is not None else self._market_store,
            frozen_source=None if cached is None else cached.reference,
        )

    async def _keep_run_reservation_alive(
        self,
        reservation: BacktestRunSubmissionReservation,
        lost: asyncio.Event,
    ) -> None:
        while True:
            await sleep(_RUN_RESERVATION_HEARTBEAT_SECONDS)
            if not await self._reservation_thread.run(
                self._repository.renew_run_submission,
                reservation,
            ):
                lost.set()
                return

    async def request_cancel(
        self,
        *,
        command: BacktestJobCancellationCommand,
        context: MutationContext,
    ) -> BacktestJobCancellationOutcome:
        try:
            binding = await self._run_sync(
                self._repository.request_cancel_with_view,
                command.job_id,
                context.idempotency_key,
            )
        except KeyError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except JobAdmissionError as error:
            raise _job_admission_api_error(error) from None
        receipt = binding.receipt
        if receipt.status in {BacktestJobStatus.COMPLETED, BacktestJobStatus.FAILED}:
            raise ApiError(ApiErrorCode.CONFLICT)
        active = receipt.status is BacktestJobStatus.CANCEL_REQUESTED
        return BacktestJobCancellationOutcome(
            job=_job_view(binding.job),
            status_code=202 if active else 200,
            location=f"/api/v1/backtest-jobs/{command.job_id}" if active else None,
            retry_after_seconds=_RETRY_AFTER_SECONDS if active else None,
        )

    async def resume_jobs(self, job_ids: frozenset[str]) -> None:
        """Validate explicitly selected pending work without changing its attempts."""
        if not isinstance(job_ids, frozenset) or len(job_ids) != 1:
            raise ValueError("resume requires one selected job ID")
        for job_id in job_ids:
            job = await self._run_sync(self._repository.get, job_id)
            if job is None or job.status not in (
                BacktestJobStatus.QUEUED, BacktestJobStatus.RUNNING,
                BacktestJobStatus.CANCEL_REQUESTED,
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
        self._coordinator.authorize_jobs(job_ids)

    def _require_coordinator_healthy(self) -> None:
        try:
            self._coordinator.raise_if_failed()
        except RuntimeError:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None

    async def pin_run(
        self,
        *,
        run_id: str,
        command: BacktestRunPinCommand,
        context: MutationContext,
    ) -> BacktestRunView | BacktestLoopRunView:
        try:
            record = await self._run_sync(
                self._results.set_pinned,
                run_id,
                pinned=command.pinned,
                expected_revision=command.expected_revision,
                idempotency_key=context.idempotency_key,
            )
        except BacktestResultNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except ResultConflictError:
            raise ApiError(ApiErrorCode.CONFLICT) from None
        return await self._run_view(record)

    async def list_datasets(
        self,
        *,
        filters: BacktestDatasetFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestDatasetPage:
        domain_filters = BacktestDatasetFilters(
            symbol=filters.symbol,
            start_on_or_after=filters.start_on_or_after,
            end_on_or_before=filters.end_on_or_before,
            historical_profile=(
                None
                if filters.historical_profile is None
                else HistoricalMinuteProfile(filters.historical_profile)
            ),
            adjustment_policy=filters.adjustment_policy,
        )
        try:
            page = await self._read_sync(
                self._datasets.list_datasets,
                filters=domain_filters,
                limit=limit,
                cursor=cursor,
            )
        except InvalidCursorError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        return BacktestDatasetPage.model_validate(
            {
                "filters": filters.canonical_payload(),
                "items": [_dataset_view(item).canonical_payload() for item in page.items],
                "limit": page.limit,
                "nextCursor": page.next_cursor,
                "hasMore": page.has_more,
                "highWatermark": page.high_watermark,
            }
        )

    async def get_dataset(self, *, dataset_hash: str) -> BacktestDatasetView | None:
        try:
            value = await self._read_sync(self._datasets.get_dataset, dataset_hash)
        except DatasetNotFoundError:
            return None
        return _dataset_view(value)

    async def get_reference_market_coverage(
        self,
        *,
        dataset_hash: str,
        plan_version_id: str,
    ) -> BacktestReferenceMarketCoverageView:
        if self._plan_snapshot_reader is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        value = await self._plan_snapshot_reader.get_plan_version(
            version_id=plan_version_id,
        )
        if value is None:
            raise ApiError(ApiErrorCode.NOT_FOUND)
        try:
            snapshot = validate_api_response(value, PlanVersionView)
        except ValidationError:
            raise RuntimeError("plan snapshot reader returned an invalid version") from None
        if str(snapshot.id) != plan_version_id:
            raise RuntimeError("plan snapshot reader returned a mismatched version")
        plan = load_plan_json(snapshot.plan_json)
        try:
            manifest = await self._read_sync(
                self._market_store.dataset_manifest,
                dataset_hash,
            )
        except KeyError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        if plan.symbol not in manifest.scope.symbols:
            raise ApiError(ApiErrorCode.CONFLICT)
        requirement = build_backtest_index_requirement(plan)
        resolved = resolve_board_reference(plan.symbol)
        binding = {
            "selection": "AUTO_BOARD",
            "mappingVersion": resolved.mapping_version,
            "indexCode": resolved.index_code.value,
            "displayName": resolved.display_name,
            "board": resolved.board.value,
        }
        common = {
            "planVersionId": plan_version_id,
            "datasetHash": dataset_hash,
            "binding": binding,
            "conditionPaths": list(requirement.condition_paths),
            "requiredFiveMinuteCount": requirement.required_five_minute_count,
            "requiredOfficialDayCount": requirement.required_official_day_count,
            "warmupStart": manifest.scope.warmup_start.isoformat(),
            "warmupEnd": manifest.scope.start.isoformat(),
            "indexRequirementHash": requirement.index_requirement_hash,
            "formulaDefinitionHash": requirement.formula_definition_hash,
        }
        if not requirement.required:
            return BacktestReferenceMarketCoverageView.model_validate(
                common
                | {
                    "required": False,
                    "availableFiveMinuteCount": 0,
                    "availableOfficialDayCount": 0,
                    "coverageStatus": "NOT_REQUIRED",
                    "blockers": [],
                    "marketIndexDataHash": manifest.market_index_data_hash,
                }
            )
        if manifest.schema_version != "backtest-dataset-v2":
            return BacktestReferenceMarketCoverageView.model_validate(
                common
                | {
                    "required": True,
                    "availableFiveMinuteCount": 0,
                    "availableOfficialDayCount": 0,
                    "coverageStatus": "BLOCKED",
                    "blockers": ["MISSING_REFERENCE_MARKET_DATASET"],
                    "marketIndexDataHash": None,
                }
            )
        if manifest.market_index_data_hash is None:  # pragma: no cover - manifest guard
            raise RuntimeError("v2 dataset is missing its market-index data hash")
        _revision, bars = await self._read_sync(
            _read_frozen_market_index_membership,
            self._market_store,
            dataset_hash,
            resolved.index_code,
        )
        result = build_reference_market_result(
            plan=plan,
            dataset_hash=dataset_hash,
            market_data_hash=manifest.market_index_data_hash,
            event_start=manifest.scope.start,
            dataset_warmup_start=manifest.scope.warmup_start,
            official_open_dates=tuple(
                sorted(
                    {
                        item.trade_date
                        for item in manifest.items
                        if item.kind == "DAILY" and item.symbol == plan.symbol
                    }
                )
            ),
            bars=bars,
        )
        return BacktestReferenceMarketCoverageView.model_validate(
            common
            | {
                "required": True,
                "availableFiveMinuteCount": result.available_five_minute_count,
                "availableOfficialDayCount": result.available_official_day_count,
                "warmupStart": result.warmup_start.isoformat(),
                "warmupEnd": result.warmup_end.isoformat(),
                "coverageStatus": result.coverage_status,
                "blockers": list(result.blockers),
                "marketIndexDataHash": result.market_index_data_hash,
            }
        )

    async def list_jobs(
        self,
        *,
        filters: BacktestJobFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestJobPage:
        filter_payload = filters.canonical_payload()
        membership_sensitive = filters.status is not None or filters.dataset_hash is not None
        current_revision = (
            await self._read_sync(self._repository.current_membership_revision)
            if membership_sensitive
            else None
        )
        cursor_state: BacktestCursorState | None = None
        high_water: tuple[datetime, str] | None = None
        after: tuple[datetime, str] | None = None
        if cursor is not None:
            cursor_state = self._job_cursor_signer.decode(
                cursor,
                route=_JOB_ROUTE,
                filters=filter_payload,
                order=_JOB_ORDER,
                current_membership_revision=current_revision,
            )
            high_water = _job_position(cursor_state.high_water)
            if cursor_state.last_seen is None:
                raise ApiError(ApiErrorCode.VALIDATION_ERROR)
            after = _job_position(cursor_state.last_seen)
        result = await self._read_sync(
            self._repository.query_jobs,
            kinds=tuple(BacktestJobKind(value) for value in (filters.kind or ())),
            statuses=tuple(BacktestJobStatus(value) for value in (filters.status or ())),
            run_id=filters.run_id,
            dataset_hash=filters.dataset_hash,
            created_from=filters.created_from,
            created_to=filters.created_to,
            high_water=high_water,
            after=after,
            limit=limit + 1,
        )
        if (
            cursor_state is not None
            and membership_sensitive
            and cursor_state.membership_revision != result.membership_revision
        ):
            raise BacktestMembershipConflictError
        page_rows = result.items[:limit]
        has_more = len(result.items) > limit
        if cursor_state is None:
            high_water_text = (
                _job_position_text(page_rows[0]) if page_rows else _EMPTY_JOB_HIGH_WATER
            )
            cursor_state = BacktestCursorState(
                high_water=high_water_text,
                last_seen=None,
                membership_revision=(result.membership_revision if membership_sensitive else None),
            )
        high_watermark = self._job_cursor_signer.high_watermark(
            route=_JOB_ROUTE,
            filters=filter_payload,
            order=_JOB_ORDER,
            state=cursor_state,
        )
        next_cursor = None
        if has_more:
            next_cursor = self._job_cursor_signer.encode(
                route=_JOB_ROUTE,
                filters=filter_payload,
                order=_JOB_ORDER,
                high_water=cursor_state.high_water,
                last_seen=_job_position_text(page_rows[-1]),
                membership_revision=cursor_state.membership_revision,
            )
        return BacktestJobPage.model_validate(
            {
                "filters": filter_payload,
                "items": [_job_view(item).canonical_payload() for item in page_rows],
                "limit": limit,
                "nextCursor": next_cursor,
                "hasMore": has_more,
                "highWatermark": high_watermark,
            }
        )

    async def get_job(self, *, job_id: str) -> BacktestJobView | None:
        value = await self._read_sync(self._repository.get, job_id)
        return None if value is None else _job_view(value)

    async def list_runs(
        self,
        *,
        filters: BacktestRunFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestRunPage:
        domain_filters = BacktestRunFilters(
            event_end_from=filters.event_end_from,
            event_end_to=filters.event_end_to,
            symbol=filters.symbol,
            plan_version_id=filters.plan_version_id,
            dataset_hash=filters.dataset_hash,
            completed_from=filters.completed_from,
            completed_to=filters.completed_to,
            pinned=filters.pinned,
        )
        try:
            page = await self._read_sync(
                self._results.list_runs,
                filters=domain_filters,
                limit=limit,
                cursor=cursor,
            )
        except InvalidCursorError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except BacktestRunMembershipConflictError:
            raise ApiError(ApiErrorCode.CONFLICT) from None
        high_watermark = self._result_cursor_signer.encode(
            route=_RUN_ROUTE,
            filters=domain_filters.model_dump(mode="json"),
            order=_RUN_ORDER,
            high_water=page.high_watermark,
            last_seen=None,
            snapshot=page.snapshot,
        )
        return await self._read_sync(
            lambda: BacktestRunPage.model_validate(
                {
                    "filters": filters.canonical_payload(),
                    "items": [
                        self._run_summary_view(item).canonical_payload() for item in page.items
                    ],
                    "limit": page.limit,
                    "nextCursor": page.next_cursor,
                    "hasMore": page.has_more,
                    "highWatermark": high_watermark,
                }
            )
        )

    async def get_run(self, *, run_id: str) -> BacktestRunView | BacktestLoopRunView | None:
        try:
            record = await self._read_sync(self._results.get_run, run_id)
        except BacktestResultNotFoundError:
            return None
        return await self._run_view(record)

    async def get_rule_changes(self, *, run_id: str, source_id: str):
        return await self._read_result(
            ("rule-changes", run_id, source_id), self._project_rule_changes, run_id, source_id,
        )

    def _project_rule_changes(self, run_id: str, source_id: str):
        from trade_plan_monitor.web.result_rule_changes import project_rule_changes

        try:
            self._results.get_run(run_id)
        except BacktestResultNotFoundError:
            return None
        reference = self._result_store.get_run_input(run_id)
        if not isinstance(reference, LoopInputReference):
            return None
        stored = self._result_store.get_loop_input(reference)
        if not isinstance(stored.prepared, FrozenPreparedCollection):
            return None
        return project_rule_changes(run_id, stored.prepared, source_id)

    async def list_fills(
        self,
        *,
        run_id: str,
        limit: int,
        cursor: str | None,
    ) -> BacktestFillPage:
        try:
            page = await self._read_sync(
                self._results.list_fills,
                run_id,
                limit=limit,
                cursor=cursor,
            )
        except BacktestResultNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except InvalidCursorError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        high_water = page.high_watermark or _EMPTY_RESULT_HIGH_WATER
        high_watermark = self._result_cursor_signer.encode(
            route=_FILL_ROUTE,
            filters={"runId": run_id},
            order=_FILL_ORDER,
            high_water=high_water,
            last_seen=None,
        )
        return await self._read_sync(
            lambda: BacktestFillPage.model_validate(
                {
                    "filters": BacktestFillFiltersView().canonical_payload(),
                    "items": [_fill_view(item).canonical_payload() for item in page.items],
                    "limit": page.limit,
                    "nextCursor": page.next_cursor,
                    "hasMore": page.has_more,
                    "highWatermark": high_watermark,
                }
            )
        )

    async def list_details(
        self,
        *,
        run_id: str,
        filters: BacktestDetailFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestDetailPage:
        domain_filters = BacktestDetailFilters(kind=BacktestDetailKind(filters.kind))
        try:
            page = await self._read_sync(
                self._results.list_details,
                run_id,
                filters=domain_filters,
                limit=limit,
                cursor=cursor,
            )
        except BacktestResultNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except InvalidCursorError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        filter_context = {"kind": filters.kind, "runId": run_id}
        high_water = page.high_watermark or _EMPTY_RESULT_HIGH_WATER
        high_watermark = self._result_cursor_signer.encode(
            route=_DETAIL_ROUTE,
            filters=filter_context,
            order=_DETAIL_ORDER,
            high_water=high_water,
            last_seen=None,
        )
        return await self._read_sync(
            lambda: BacktestDetailPage.model_validate(
                {
                    "kind": filters.kind,
                    "availability": page.availability.value,
                    "filters": filters.canonical_payload(),
                    "items": [_detail_view(item).canonical_payload() for item in page.items],
                    "limit": page.limit,
                    "nextCursor": page.next_cursor,
                    "hasMore": page.has_more,
                    "highWatermark": high_watermark,
                }
            )
        )

    async def get_equity_series(self, *, run_id: str) -> BacktestEquitySeries:
        return await self._read_result(("equity", run_id), self._equity_series_view, run_id)

    def _equity_series_view(self, run_id: str) -> BacktestEquitySeries:
        try:
            series = self._result_store.get_loop_equity_series(run_id)
            if series is None:
                series = self._results.get_equity_series(run_id)
        except BacktestResultNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        return BacktestEquitySeries.model_validate(
            {
                "availability": series.availability.value,
                "items": [_equity_view(item) for item in series.items],
            }
        )

    async def get_market_index_series(
        self,
        *,
        run_id: str,
        start_on: date | None,
        end_on: date | None,
        limit: int,
    ) -> BacktestMarketIndexSeriesView:
        try:
            record = await self._read_sync(self._results.get_run, run_id)
        except BacktestResultNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        reference = _reference_market_view(record)
        if reference is None:
            return BacktestMarketIndexSeriesView.model_validate(
                {
                    "runId": run_id,
                    "referenceMarket": None,
                    "items": [],
                    "healthTimeline": [],
                    "conditionSummaries": [],
                }
            )
        run_input = await self._read_sync(self._result_store.get_run_input, run_id)
        if run_input is None:
            raise RuntimeError("index-bearing run is missing its immutable input")
        requirement = build_backtest_index_requirement(run_input.plan_snapshot)
        if not requirement.required or requirement.binding is None:
            raise RuntimeError("stored reference-market identity contradicts the run input")
        dataset_revision, bars = await self._read_sync(
            _read_frozen_market_index_membership,
            self._market_store,
            run_input.dataset_hash,
            requirement.binding.index_code,
        )
        replay = MarketIndexReplaySeries(
            index_code=requirement.binding.index_code,
            bars=bars,
            dataset_revision=dataset_revision,
        )
        official = tuple(
            bar
            for bar in bars
            if bar.interval is MarketIndexInterval.OFFICIAL_DAILY
            and (start_on is None or bar.bar_at.date() >= start_on)
            and (end_on is None or bar.bar_at.date() <= end_on)
        )
        points: list[BacktestMarketIndexPointView] = []
        for bar in official:
            snapshot = replay.snapshot(
                decision_cutoff=bar.bar_at,
                requests=requirement.fact_requests,
                observed_no_later_than=bar.observed_at,
            )
            points.append(
                BacktestMarketIndexPointView.model_validate(
                    {
                        "tradeDate": bar.bar_at.date().isoformat(),
                        "dataAt": format_shanghai_datetime(bar.bar_at),
                        "closePoints": canonical_decimal(bar.close_points),
                        "snapshotHash": snapshot.snapshot_hash,
                        "indicatorFacts": [
                            _market_index_fact_view(fact) for fact in snapshot.indicator_facts
                        ],
                        "health": snapshot.health.value,
                        "issues": [issue.value for issue in snapshot.issues],
                    }
                )
            )
        selected = downsample_market_index_points(tuple(points), limit=limit)
        return BacktestMarketIndexSeriesView.model_validate(
            {
                "runId": run_id,
                "referenceMarket": reference.canonical_payload(),
                "items": [item.canonical_payload() for item in selected],
                "healthTimeline": [
                    {
                        "dataAt": format_shanghai_datetime(item.data_at),
                        "health": item.health.value,
                        "issues": [issue.value for issue in item.issues],
                    }
                    for item in selected
                ],
                "conditionSummaries": [
                    item.canonical_payload() for item in reference.condition_summaries
                ],
            }
        )

    async def prepare_export(
        self,
        *,
        run_id: str,
        export_kind: BacktestExportKind,
        cancelled: Callable[[], bool],
    ) -> PreparedBacktestExport | None:
        record = await self._read_sync(self._result_store.get_result_run, run_id)
        if record is None:
            return None
        if record.summary.formula_versions.get("report") in {
            "backtest-report-v4", "backtest-report-v5",
        }:
            raise ApiError(ApiErrorCode.CONFLICT)
        if export_kind == "SUMMARY_JSON":
            chunks = iter_export_summary(self._result_store, run_id, cancelled)
            schema_version = (
                "backtest-report-summary-v4"
                if record.summary.formula_versions.get("report") == "backtest-report-v3"
                else "backtest-report-summary-v3"
                if _reference_market_view(record) is not None
                else "backtest-report-summary-v2"
            )
        else:
            chunks = iter_export_fills(self._result_store, run_id, cancelled)
            schema_version = (
                "explicit-simulation-valuation-v1"
                if record.summary.formula_versions.get("report") == "backtest-report-v3"
                else "backtest-simulated-fills-v2"
            )
        return PreparedBacktestExport(
            run_id=run_id,
            export_kind=export_kind,
            schema_version=schema_version,
            chunks=chunks,
        )

    def _run_summary_view(
        self, record: BacktestRunRecord
    ) -> BacktestRunSummaryView | BacktestLoopRunSummaryView:
        return _run_summary_view(record)

    async def _run_view(self, record: BacktestRunRecord) -> BacktestRunView | BacktestLoopRunView:
        return await self._read_result(
            ("run", record.summary.run_id, str(record.summary.pinned)), self._project_run, record,
        )

    def _project_run(self, record: BacktestRunRecord) -> BacktestRunView | BacktestLoopRunView:
        run_input = self._result_store.get_run_input(record.summary.run_id)
        if run_input is None:
            raise RuntimeError("verified result is missing its immutable run input")
        if isinstance(run_input, LoopInputReference):
            result = self._result_store.get_loop_result(record.summary.run_id)
            if result is None:
                raise RuntimeError("verified loop result is missing its immutable report")
            stored, report, diagnostics = result
            prepared = stored.prepared
            if isinstance(prepared, FrozenPreparedCollection):
                from trade_plan_monitor.web.preparation_schemas import project_collection_frozen

                frozen = project_collection_frozen(prepared)
                return BacktestScheduledRunView.model_validate(
                    _run_summary_view(record).canonical_payload() | {
                        "provenance": {
                            "preparationId": prepared.preparation_id,
                            "manifestHash": prepared.manifest_hash,
                            "inputHash": run_input.input_hash,
                            "revision": prepared.revision,
                            "sources": tuple({
                                "sourceId": item.source.source_id,
                                "sourceHash": item.source.binding_hash,
                                "sourceRevision": item.source_revision,
                                "candidateRevision": item.extraction_candidate_revision,
                                "candidateHash": item.extraction_candidate_hash,
                                "evidenceHash": item.extraction_evidence_hash,
                                "baseHash": item.base_hash,
                            } for item in prepared.items),
                        },
                        "versions": frozen.versions,
                        "planDiagnostics": diagnostics,
                        "openingAccount": stored.run_input.initial_account,
                        "response": stored.run_input.response,
                        "costs": stored.run_input.costs,
                        "report": report.model_dump(
                            mode="json", exclude={"schedule", "schema_version"},
                        )
                        | {"report_schema_version": report.schema_version},
                    }
                )
            if isinstance(prepared, WorkbenchPlanSelection):
                ref = prepared.reviewed.reference
                return WorkbenchBacktestRunView.model_validate(
                    _run_summary_view(record).canonical_payload()
                    | {
                        "schemaVersion": "monitor-loop-result-workbench-v1",
                        "provenance": {
                            "selectionId": prepared.selection_id,
                            "selectionHash": prepared.manifest_hash,
                            "planVersionId": str(ref.plan_version_id),
                            "reviewId": str(ref.review_id),
                            "reviewRevision": ref.review_revision,
                            "confirmedAt": format_shanghai_datetime(prepared.confirmed_at),
                            "inputHash": run_input.input_hash,
                        },
                        "frozenPlan": prepared.version,
                        "planDiagnostics": diagnostics,
                        "openingAccount": stored.run_input.initial_account,
                        "response": stored.run_input.response,
                        "costs": stored.run_input.costs,
                        "report": report,
                    }
                )
            return BacktestLoopRunView.model_validate(
                _run_summary_view(record).canonical_payload()
                | {
                    "provenance": {
                        "preparationId": prepared.preparation_id,
                        "manifestHash": prepared.manifest_hash,
                        "sourceRevision": prepared.source_revision,
                        "candidateRevision": prepared.extraction_candidate_revision,
                        "candidateHash": prepared.extraction_candidate_hash,
                        "inputHash": run_input.input_hash,
                    },
                    "frozenPlan": prepared.version,
                    "planDiagnostics": diagnostics,
                    "openingAccount": stored.run_input.initial_account,
                    "response": stored.run_input.response,
                    "costs": stored.run_input.costs,
                    "report": report,
                }
            )
        return _run_view(record, run_input)


def _load_or_create_cursor_key(path: Path) -> bytes:
    """Load one local 256-bit cursor key, creating it with owner-only mode."""

    return load_or_create_cursor_key(
        path,
        create=create_cursor_key_file,
        read=_read_cursor_key,
    )


def _read_cursor_key(path: Path) -> bytes:
    return read_cursor_key_file(path)


def _scope_request(scope: BacktestDatasetScopeInput) -> BacktestDatasetScopeRequest:
    return BacktestDatasetScopeRequest(
        symbols=scope.symbols,
        start=scope.start,
        end=scope.end,
        warmup_start=scope.warmup_start,
        historical_profile=HistoricalMinuteProfile(scope.historical_profile),
        adjustment_policy=scope.adjustment_policy,
    )


def _job_admission_api_error(error: JobAdmissionError) -> ApiError:
    if error.code in {"IDEMPOTENCY_CONFLICT", "BACKTEST_BUSY"}:
        return ApiError(ApiErrorCode.CONFLICT)
    raise RuntimeError("unknown backtest job admission error")


def _data_submission_outcome(
    receipt: DomainBacktestJobReceipt,
) -> BacktestJobSubmissionOutcome:
    return BacktestJobSubmissionOutcome(
        receipt=_job_receipt(receipt),
        location=f"/api/v1/backtest-jobs/{receipt.job_id}",
        retry_after_seconds=(
            _RETRY_AFTER_SECONDS if receipt.status in _ACTIVE_JOB_STATUSES else None
        ),
    )


def _run_submission_outcome(
    receipt: DomainBacktestJobReceipt,
) -> BacktestRunSubmissionOutcome:
    return BacktestRunSubmissionOutcome(
        receipt=_job_receipt(receipt),
        location=f"/api/v1/backtest-jobs/{receipt.job_id}",
        retry_after_seconds=(
            _RETRY_AFTER_SECONDS if receipt.status in _ACTIVE_JOB_STATUSES else None
        ),
    )


_ACTIVE_JOB_STATUSES = frozenset(
    {
        BacktestJobStatus.QUEUED,
        BacktestJobStatus.RUNNING,
        BacktestJobStatus.CANCEL_REQUESTED,
    }
)


def _job_receipt(receipt: DomainBacktestJobReceipt) -> BacktestJobReceipt:
    return BacktestJobReceipt.model_validate(_public_value(receipt))


def _verify_prepared_submission_binding(binding: BacktestJobSubmissionBinding) -> None:
    """Intent was already compared atomically; replay needs no mutable source or clock."""
    root = json.loads(binding.canonical_request_json)
    if not isinstance(root, dict) or set(root) != {"kind", "inputReference"}:
        raise RuntimeError("stored prepared submission envelope is invalid")
    reference = LoopInputReference.model_validate_json(canonical_json(root["inputReference"]))
    if (
        root["kind"] != BacktestJobKind.BACKTEST_RUN.value
        or binding.receipt.kind is not BacktestJobKind.BACKTEST_RUN
        or binding.receipt.run_id != reference.run_id
        or binding.receipt.dataset_hash != reference.dataset_hash
    ):
        raise RuntimeError("stored prepared submission identity is invalid")


def _persisted_run_matches_command(
    canonical_request_json: str,
    command: BacktestRunCommand,
) -> bool:
    try:
        root = json.loads(canonical_request_json)
    except TypeError, ValueError:
        raise RuntimeError("stored backtest request is not canonical JSON") from None
    if not isinstance(root, dict) or set(root) != {"kind", "runInput"}:
        raise RuntimeError("stored run request has an invalid envelope")
    run_input = root.get("runInput")
    if root.get("kind") != BacktestJobKind.BACKTEST_RUN.value or not isinstance(
        run_input,
        dict,
    ):
        raise RuntimeError("stored run request has an invalid envelope")
    execution = run_input.get("execution_config")
    initial_lots = run_input.get("initial_lots")
    if (
        not isinstance(execution, dict)
        or not isinstance(initial_lots, list)
        or type(run_input.get("manual_event_risk")) is not bool
    ):
        raise RuntimeError("stored run request is missing immutable input fields")
    try:
        public_lots = [
            {
                "lotKey": item["lot_key"],
                "bucket": item["bucket"],
                "acquiredTradeDate": item["acquired_trade_date"],
                "quantity": item["quantity"],
                "costBasisFen": item["cost_basis_fen"],
            }
            for item in initial_lots
            if isinstance(item, dict)
        ]
        payload = {
            "planVersionId": run_input["plan_version_id"],
            "datasetHash": run_input["dataset_hash"],
            "initialCashFen": run_input["initial_cash_fen"],
            "initialLots": public_lots,
            "executionConfig": {
                "commissionRate": execution["commission_rate"],
                "minimumCommissionFen": execution["minimum_commission_fen"],
                "stampDutyRate": execution["stamp_duty_rate"],
                "transferFeeRate": execution["transfer_fee_rate"],
                "buySlippageBps": execution["buy_slippage_bps"],
                "sellSlippageBps": execution["sell_slippage_bps"],
            },
            "eventRiskAssumption": (
                "MANUAL_EVENT_RISK" if run_input["manual_event_risk"] is True else "NO_EVENT_RISK"
            ),
        }
    except KeyError:
        raise RuntimeError("stored run request is missing immutable input fields") from None
    if len(public_lots) != len(initial_lots):
        raise RuntimeError("stored run request contains an invalid initial lot")
    if run_input.get("research_input") is not None:
        payload["researchInput"] = run_input["research_input"]
    return payload == command.canonical_payload()


def _dataset_view(value: object) -> BacktestDatasetView:
    return BacktestDatasetView.model_validate(_public_value(value))


def _job_view(value: DomainBacktestJobView) -> BacktestJobView:
    payload = _public_value(value)
    if not isinstance(payload, dict):
        raise TypeError("job projection must be an object")
    if value.status is BacktestJobStatus.FAILED:
        payload["errorCode"] = value.error_code or "JOB_FAILED"
        payload["errorMessage"] = "The job failed."
    elif value.status is BacktestJobStatus.CANCELLED:
        payload["errorCode"] = value.error_code or "JOB_CANCELLED"
        payload["errorMessage"] = "The job was cancelled."
    else:
        payload["errorCode"] = None
        payload["errorMessage"] = None
    return BacktestJobView.model_validate(payload)


def _job_position(value: tuple[str, ...]) -> tuple[datetime, str]:
    if len(value) != 2:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    try:
        created_at = parse_shanghai_datetime(value[0])
    except ValueError:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
    if format_shanghai_datetime(created_at) != value[0] or not value[1]:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    return created_at, value[1]


def _job_position_text(value: DomainBacktestJobView) -> tuple[str, str]:
    return format_shanghai_datetime(value.created_at), value.job_id


def _reference_market_view(
    record: BacktestRunRecord,
) -> BacktestReferenceMarketView | None:
    raw = record.summary.assumptions.get("referenceMarket")
    if raw is None:
        return None
    public = _public_value(raw)
    if not isinstance(public, dict):
        raise RuntimeError("verified reference-market result is invalid")
    keys = (
        "binding",
        "required",
        "conditionPaths",
        "warmupStart",
        "coverageStatus",
        "blockers",
        "marketIndexDataHash",
        "indexRequirementHash",
        "formulaDefinitionHash",
        "datasetHash",
        "conditionSummaries",
    )
    try:
        payload = {key: public[key] for key in keys}
    except KeyError:
        raise RuntimeError("verified reference-market result is incomplete") from None
    return BacktestReferenceMarketView.model_validate(payload)


def _read_frozen_market_index_membership(
    market_store: object,
    dataset_hash: str,
    index_code: object,
) -> tuple[int, tuple[object, ...]]:
    open_dataset = getattr(market_store, "open_frozen_dataset", None)
    if not callable(open_dataset):
        raise RuntimeError("market store cannot open a frozen dataset")
    with open_dataset(dataset_hash) as reader:
        if not isinstance(reader, FrozenMarketIndexDatasetReader):
            raise RuntimeError("index-bearing run references a stock-only dataset")
        return reader.dataset_revision, reader.market_index_bars(index_code)


def _market_index_fact_view(fact: MarketIndexIndicatorFact) -> dict[str, object]:
    if type(fact) is not MarketIndexIndicatorFact:
        raise TypeError("fact must be an exact MarketIndexIndicatorFact")
    request = _public_value(fact.request)
    if not isinstance(request, dict):  # pragma: no cover - model boundary
        raise TypeError("market-index fact request must be an object")
    payload = dict(request)
    payload.update(
        value=canonical_decimal(fact.value),
        unit=fact.unit.value,
        sourceBarHash=fact.source_bar_hash,
        formulaDefinitionHash=fact.formula_definition_hash,
    )
    if fact.comparison_value is not None:
        payload["comparisonValue"] = canonical_decimal(fact.comparison_value)
    return payload


def _run_summary_view(
    record: BacktestRunRecord,
) -> BacktestRunSummaryView | BacktestLoopRunSummaryView:
    summary = record.summary
    if len(summary.symbols) != 1:
        raise RuntimeError("public backtest runs require exactly one symbol")
    report_hash = summary.assumptions.get("reportHash")
    if not isinstance(report_hash, str):
        raise RuntimeError("verified backtest run is missing reportHash")
    payload = {
        "runId": summary.run_id,
        "reportHash": report_hash,
        "planVersionId": record.plan_version_id,
        "planHash": summary.plan_sha256,
        "datasetHash": summary.dataset_hash,
        "symbol": summary.symbols[0],
        "status": summary.status.value,
        "eventStart": summary.event_start.isoformat(),
        "eventEnd": summary.event_end.isoformat(),
        "completedAt": format_shanghai_datetime(summary.completed_at.astimezone(SHANGHAI)),
        "pinned": summary.pinned,
        "revision": record.revision,
        "fillCount": record.fill_count,
        "metrics": _public_value(summary.final_metrics),
        "availability": _availability(record),
    }
    if summary.formula_versions.get("report") in {"backtest-report-v4", "backtest-report-v5"}:
        scheduled = summary.formula_versions.get("report") == "backtest-report-v5"
        if scheduled:
            payload["availability"]["equitySeries"] = payload["availability"]["decisionDetails"]
        model = BacktestScheduledRunSummaryView if scheduled else BacktestLoopRunSummaryView
        return model.model_validate(
            payload
            | {
                "schemaVersion": (
                    "monitor-loop-result-v2" if scheduled else "monitor-loop-result-v1"
                ),
                "metrics": json.loads(canonical_json(summary.final_metrics)),
            }
        )
    return BacktestRunSummaryView.model_validate(payload)


def _run_view(record: BacktestRunRecord, run_input: BacktestRunInput) -> BacktestRunView:
    summary_view = _run_summary_view(record)
    summary = record.summary
    coverage = summary.coverage
    assumptions = summary.assumptions
    execution = run_input.execution_config
    limitations = assumptions.get("limitations")
    if not isinstance(limitations, (list, tuple)) or any(
        not isinstance(item, str) for item in limitations
    ):
        raise RuntimeError("verified backtest run is missing limitations")
    payload = summary_view.canonical_payload() | {
        "initialCashFen": str(run_input.initial_cash_fen),
        "coverage": {
            "eventStart": summary.event_start.isoformat(),
            "eventEnd": summary.event_end.isoformat(),
            "tradingDayCount": _coverage_count(coverage, "dailyEquityCount"),
            "decisionCount": _coverage_count(coverage, "decisionCount"),
            "signalCount": _coverage_count(coverage, "signalCount"),
            "orderCount": _coverage_count(coverage, "orderCount"),
            "fillCount": _coverage_count(coverage, "fillCount"),
            "outcomeCount": _coverage_count(coverage, "outcomeCount"),
            "equityPointCount": _coverage_count(coverage, "dailyEquityCount"),
        },
        "assumptions": {
            "eventRiskAssumption": (
                "MANUAL_EVENT_RISK" if run_input.manual_event_risk else "NO_EVENT_RISK"
            ),
            "executionConfig": {
                "commissionRate": canonical_decimal(execution.commission_rate),
                "minimumCommissionFen": str(execution.minimum_commission_fen),
                "stampDutyRate": canonical_decimal(execution.stamp_duty_rate),
                "transferFeeRate": canonical_decimal(execution.transfer_fee_rate),
                "buySlippageBps": canonical_decimal(execution.buy_slippage_bps),
                "sellSlippageBps": canonical_decimal(execution.sell_slippage_bps),
            },
            "executionConfigHash": execution.config_hash,
            "priceAdjustmentPolicy": "NONE",
            "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        },
        "formulaVersions": {
            "runFormulaVersion": run_input.run_formula_version,
            "reportSchemaVersion": summary.formula_versions.get(
                "report",
                "backtest-report-v1",
            ),
            "executionFormulaVersion": execution.formula_version,
            "metricFormulaVersion": "backtest-metrics-v1",
        },
        "limitations": sorted(set(limitations)),
        "referenceMarket": (
            None
            if (reference_market := _reference_market_view(record)) is None
            else reference_market.canonical_payload()
        ),
    }
    return BacktestRunView.model_validate(payload)


def _coverage_count(coverage: Mapping[str, object], key: str) -> int:
    value = coverage.get(key)
    if type(value) is not int or value < 0:
        raise RuntimeError(f"verified backtest run is missing {key}")
    return value


def _availability(record: BacktestRunRecord) -> dict[str, str]:
    state_by_kind = {state.kind: state.availability.value for state in record.availability}
    return {
        "decisionDetails": state_by_kind.get(
            BacktestDetailKind.DECISION,
            BacktestArtifactAvailability.NOT_RECORDED.value,
        ),
        "signalDetails": state_by_kind.get(
            BacktestDetailKind.SIGNAL,
            BacktestArtifactAvailability.NOT_RECORDED.value,
        ),
        "executionOutcomeDetails": state_by_kind.get(
            BacktestDetailKind.EXECUTION_OUTCOME,
            BacktestArtifactAvailability.NOT_RECORDED.value,
        ),
        "equitySeries": state_by_kind.get(
            BacktestDetailKind.DAILY_EQUITY,
            BacktestArtifactAvailability.NOT_RECORDED.value,
        ),
    }


def _fill_view(record: BacktestFillRecord) -> BacktestFillView | BacktestLoopFillView:
    if record.payload.get("schema_version") == "monitor-loop-fill-v1":
        return BacktestLoopFillView.model_validate(
            {
                "schemaVersion": "monitor-loop-fill-v1",
                "fillId": record.payload["receipt"]["authority_receipt"]["simulation_id"],
                "runId": record.run_id,
                "filledAt": format_shanghai_datetime(record.filled_at.astimezone(SHANGHAI)),
                "eventId": record.payload["event_id"],
                "receipt": record.payload["receipt"],
            }
        )
    payload = _public_value(record.payload)
    if not isinstance(payload, dict):
        raise TypeError("fill payload must be an object")
    payload.update(
        fillId=record.fill_id,
        runId=record.run_id,
        filledAt=format_shanghai_datetime(record.filled_at.astimezone(SHANGHAI)),
    )
    return BacktestFillView.model_validate(payload)


def _detail_view(
    record: BacktestDetailRecord,
) -> (
    BacktestDecisionView | BacktestSignalView | BacktestExecutionOutcomeView | BacktestLoopEventView
):
    event_at = format_shanghai_datetime(record.event_at.astimezone(SHANGHAI))
    payload = record.payload
    if payload.get("schema_version") in {"monitor-loop-event-v1", "monitor-loop-event-v2"}:
        model = (BacktestScheduledEventView if payload["schema_version"] == "monitor-loop-event-v2"
                 else BacktestLoopEventView)
        return model.model_validate(
            {
                "schemaVersion": payload["schema_version"],
                "detailId": record.detail_id,
                "runId": record.run_id,
                "kind": record.kind.value,
                "eventAt": event_at,
                "event": payload,
            }
        )
    from trade_plan_monitor.web.backtest_schemas import ResearchDecisionView, ResearchOperationView

    current_types = {
        "unified-research-decision-v1": (ResearchDecisionView, "researchDecision"),
        "unified-research-operation-v1": (ResearchOperationView, "researchOperation"),
    }
    if payload.get("schema_version") in current_types:
        model, key = current_types[payload["schema_version"]]
        return model.model_validate(
            {
                "detailId": record.detail_id,
                "runId": record.run_id,
                "kind": record.kind.value,
                "eventAt": event_at,
                key: payload,
            }
        )
    if record.kind is BacktestDetailKind.DECISION:
        result = EvaluationResult.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        return BacktestDecisionView.model_validate(
            {
                "detailId": record.detail_id,
                "runId": record.run_id,
                "kind": "DECISION",
                "eventAt": event_at,
                "resultHash": result.result_hash,
                "decision": _decision_projection(result),
            }
        )
    if record.kind is BacktestDetailKind.SIGNAL:
        return BacktestSignalView.model_validate(
            {
                "detailId": record.detail_id,
                "runId": record.run_id,
                "kind": "SIGNAL",
                "eventAt": event_at,
                "signalId": payload.get("signal_id"),
                "resultHash": payload.get("result_hash"),
                "signalType": payload.get("signal_type"),
                "symbol": payload.get("symbol"),
                "quantity": payload.get("quantity"),
                "bucket": payload.get("bucket"),
                "targetLotId": payload.get("target_lot_id"),
                "causeId": payload.get("cause_id"),
            }
        )
    if record.kind is BacktestDetailKind.EXECUTION_OUTCOME:
        return BacktestExecutionOutcomeView.model_validate(
            {
                "detailId": record.detail_id,
                "runId": record.run_id,
                "kind": "EXECUTION_OUTCOME",
                "eventAt": event_at,
                "outcomeId": payload.get("outcome_id"),
                "signalId": payload.get("signal_id"),
                "orderId": payload.get("order_id"),
                "sourceBarId": payload.get("source_bar_id"),
                "status": payload.get("status"),
                "reason": payload.get("reason"),
                "fillId": payload.get("fill_id"),
            }
        )
    raise RuntimeError("unsupported public backtest detail kind")


def _decision_projection(result: EvaluationResult) -> dict[str, object]:
    snapshot = result.snapshot
    market_data_at = snapshot.market_data_at
    episode = snapshot.episode
    risk = snapshot.risk
    health = snapshot.data_health
    reference_market = project_decision_reference_market(result)
    return {
        "symbol": snapshot.symbol,
        "resultHash": result.result_hash,
        "planId": snapshot.plan_id,
        "planVersion": snapshot.plan_version,
        "planHash": snapshot.plan_hash,
        "evaluatedAt": format_shanghai_datetime(snapshot.evaluated_at),
        "marketDataAt": (
            None if market_data_at is None else format_shanghai_datetime(market_data_at)
        ),
        "dataAgeSeconds": (
            None
            if market_data_at is None
            else int((snapshot.evaluated_at - market_data_at).total_seconds())
        ),
        "priceFen": None if snapshot.price_fen is None else str(snapshot.price_fen),
        "zone": snapshot.zone.value,
        "signalType": snapshot.signal_type.value,
        "position": _public_value(snapshot.position),
        "episodeStatus": None if episode is None else episode.status.value,
        "episodeLowFen": None if episode is None else str(episode.episode_low_fen),
        "riskStatus": risk.status.value,
        "riskBreachTradeDate": (
            None if risk.breach_trade_date is None else risk.breach_trade_date.isoformat()
        ),
        "dataHealth": {
            "status": health.status.value,
            "latestBarEnd": (
                None
                if health.latest_bar_end is None
                else format_shanghai_datetime(health.latest_bar_end)
            ),
            "dataAgeSeconds": health.data_age_seconds,
            "requiredDataComplete": health.required_data_complete,
            "fresh": health.fresh,
        },
        "evidence": [
            _evidence_view(item).canonical_payload() for item in snapshot.condition_evidence
        ],
        "nextStep": _public_value(snapshot.next_step),
        "referenceMarket": reference_market,
    }


def _evidence_view(value: ConditionEvidence | RuleEvidence) -> BacktestDecisionEvidenceView:
    if isinstance(value, ConditionEvidence):
        code = value.condition.type
        children = tuple(_evidence_view(child) for child in value.children)
        kind = "CONDITION"
    else:
        code = value.code.value
        children = ()
        kind = "RULE"
    facts = []
    for fact in value.facts:
        fact_value = fact.value
        if isinstance(fact_value, datetime):
            fact_value = format_shanghai_datetime(fact_value)
        elif type(fact_value) is date:
            fact_value = fact_value.isoformat()
        elif isinstance(fact_value, Enum):
            fact_value = fact_value.value
        facts.append({"key": fact.key, "value": fact_value, "unit": fact.unit.value})
    return BacktestDecisionEvidenceView.model_validate(
        {
            "kind": kind,
            "code": code,
            "outcome": value.outcome.value,
            "facts": facts,
            "missingInputs": [item.value for item in value.missing_inputs],
            "children": list(children),
        }
    )


def _equity_view(record: BacktestDetailRecord) -> dict[str, object]:
    if record.kind is not BacktestDetailKind.DAILY_EQUITY:
        raise RuntimeError("equity series contains a non-equity artifact")
    payload = _public_value(record.payload)
    if not isinstance(payload, dict):
        raise TypeError("equity payload must be an object")
    payload.update(
        snapshotId=record.payload.get("snapshot_id"),
        runId=record.run_id,
        markedAt=format_shanghai_datetime(record.event_at.astimezone(SHANGHAI)),
    )
    if record.payload.get("schema_version") == "unified-research-equity-v1":
        from trade_plan_monitor.web.backtest_schemas import ResearchEquityView
        return ResearchEquityView.model_validate(payload).canonical_payload()
    return BacktestEquityPointView.model_validate(payload).canonical_payload()


def _public_value(value: object, *, field_name: str | None = None) -> object:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", round_trip=True)
    if isinstance(value, Mapping):
        return {
            _camel_key(key): _public_value(item, field_name=_camel_key(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if isinstance(value, datetime):
        return format_shanghai_datetime(value.astimezone(SHANGHAI))
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Decimal):
        text = canonical_decimal(value)
        return text
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if field_name is not None and field_name.endswith("Fen") and type(value) is int:
        return str(value)
    return value


def _camel_key(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("public projection keys must be strings")
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


__all__ = [
    "BacktestComposition",
    "DEFAULT_BACKTEST_CURSOR_KEY",
    "DEFAULT_BACKTEST_MARKET_DATABASE",
    "DEFAULT_BACKTEST_RESULTS_DATABASE",
    "PlanSnapshotReader",
    "create_backtest_composition",
    "create_backtest_composition_factory",
]
