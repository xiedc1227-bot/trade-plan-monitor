"""Thin HTTP adapters for completed backtest runs and run mutations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pydantic import Field, ValidationError

from trade_plan_monitor.web.backtest_schemas import (
    BacktestJobReceipt,
    BacktestLoopRunView,
    BacktestRunCommand,
    BacktestRunFiltersView,
    BacktestRunPage,
    BacktestRunView,
    PreparedBacktestRunCommand,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    ApiValue,
    MutationContext,
    MutationContextDependency,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["backtest-runs"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_EXPECTED_REVISION = 9_007_199_254_740_991
_RETRY_AFTER_SECONDS = 2
_JOB_LOCATION_PREFIX = "/api/v1/backtest-jobs/"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SYMBOL_PATTERN = r"^[0-9]{6}\.(?:SH|SZ)$"
_CURSOR_PATTERN = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"
_NONTERMINAL_STATUSES = frozenset({"QUEUED", "RUNNING", "CANCEL_REQUESTED"})
_RUN_COLLECTION_QUERY_FIELDS = frozenset(
    {
        "symbol",
        "planVersionId",
        "datasetHash",
        "completedFrom",
        "completedTo",
        "pinned",
        "limit",
        "cursor",
    }
)

RunIdPath = Annotated[
    str,
    Path(min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
SymbolQuery = Annotated[
    str | None,
    Query(min_length=9, max_length=9, pattern=_SYMBOL_PATTERN),
]
PlanVersionIdQuery = Annotated[
    str | None,
    Query(alias="planVersionId", min_length=36, max_length=36),
]
DatasetHashQuery = Annotated[
    str | None,
    Query(alias="datasetHash", min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
CompletedFromQuery = Annotated[
    str | None,
    Query(alias="completedFrom", min_length=25, max_length=40),
]
CompletedToQuery = Annotated[
    str | None,
    Query(alias="completedTo", min_length=25, max_length=40),
]
PinnedQuery = Annotated[
    Literal["true", "false"] | None,
    Query(),
]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
CursorQuery = Annotated[
    str | None,
    Query(min_length=3, max_length=512, pattern=_CURSOR_PATTERN),
]
NonNegativeRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_EXPECTED_REVISION),
]


class BacktestRunPinCommand(ApiValue):
    """The exact public pin mutation with optimistic concurrency."""

    pinned: bool = Field(strict=True)
    expected_revision: NonNegativeRevision


@dataclass(frozen=True, slots=True)
class BacktestRunSubmissionOutcome:
    """Application-owned run receipt and validated transport metadata."""

    receipt: object
    location: str
    retry_after_seconds: Literal[2] | None


class BacktestRunReadService(Protocol):
    """Read-only run query boundary implemented outside the HTTP adapter."""

    async def list_runs(
        self,
        *,
        filters: BacktestRunFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestRunPage: ...

    async def get_run(self, *, run_id: str) -> BacktestRunView | BacktestLoopRunView | None: ...


class BacktestRunOperationService(Protocol):
    """Atomic submission, idempotency, and pin boundary owned by the application."""

    async def submit_run(
        self,
        *,
        command: BacktestRunCommand | PreparedBacktestRunCommand,
        context: MutationContext,
    ) -> BacktestRunSubmissionOutcome: ...

    async def pin_run(
        self,
        *,
        run_id: str,
        command: BacktestRunPinCommand,
        context: MutationContext,
    ) -> BacktestRunView | BacktestLoopRunView: ...


def get_backtest_run_read_service(request: Request) -> BacktestRunReadService:
    service = getattr(request.app.state, "backtest_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestRunReadService, service)


def get_backtest_run_operation_service(request: Request) -> BacktestRunOperationService:
    service = getattr(request.app.state, "backtest_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestRunOperationService, service)


BacktestRunReadServiceDependency = Annotated[
    BacktestRunReadService,
    Depends(get_backtest_run_read_service),
]
BacktestRunOperationServiceDependency = Annotated[
    BacktestRunOperationService,
    Depends(get_backtest_run_operation_service),
]


def require_run_collection_query(request: Request) -> None:
    names = tuple(name for name, _value in request.query_params.multi_items())
    counts = Counter(names)
    if not counts.keys() <= _RUN_COLLECTION_QUERY_FIELDS or any(
        count != 1 for count in counts.values()
    ):
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)


RunCollectionQueryDependency = Annotated[
    None,
    Depends(require_run_collection_query),
]


@router.get("/backtest-runs", response_model=BacktestRunPage)
async def list_backtest_runs(
    _query: RunCollectionQueryDependency,
    service: BacktestRunReadServiceDependency,
    symbol: SymbolQuery = None,
    plan_version_id: PlanVersionIdQuery = None,
    dataset_hash: DatasetHashQuery = None,
    completed_from: CompletedFromQuery = None,
    completed_to: CompletedToQuery = None,
    pinned: PinnedQuery = None,
    limit: LimitQuery = _DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> BacktestRunPage:
    filters = _run_filters(
        symbol=symbol,
        plan_version_id=plan_version_id,
        dataset_hash=dataset_hash,
        completed_from=completed_from,
        completed_to=completed_to,
        pinned=None if pinned is None else pinned == "true",
    )
    page = validate_api_response(
        await service.list_runs(filters=filters, limit=limit, cursor=cursor),
        BacktestRunPage,
    )
    if page.filters != filters or page.limit != limit:
        raise RuntimeError("backtest run service returned mismatched pagination")
    return page


@router.get("/backtest-runs/{run_id}", response_model=BacktestRunView | BacktestLoopRunView)
async def get_backtest_run(
    run_id: RunIdPath,
    service: BacktestRunReadServiceDependency,
) -> BacktestRunView | BacktestLoopRunView:
    value = await service.get_run(run_id=run_id)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    run = _validated_run(value)
    if run.run_id != run_id:
        raise RuntimeError("backtest run service returned a mismatched run")
    return run


@router.post(
    "/backtest-runs",
    response_model=BacktestJobReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_backtest_run(
    command: BacktestRunCommand | PreparedBacktestRunCommand,
    context: MutationContextDependency,
    service: BacktestRunOperationServiceDependency,
    response: Response,
) -> BacktestJobReceipt:
    outcome = await service.submit_run(command=command, context=context)
    if not isinstance(outcome, BacktestRunSubmissionOutcome):
        raise RuntimeError("backtest operation service returned an invalid submission outcome")
    receipt = validate_api_response(outcome.receipt, BacktestJobReceipt)
    expected_location = f"{_JOB_LOCATION_PREFIX}{receipt.job_id}"
    if (
        receipt.kind != "BACKTEST_RUN"
        or isinstance(command, BacktestRunCommand)
        and receipt.dataset_hash != command.dataset_hash
        or outcome.location != expected_location
    ):
        raise RuntimeError("backtest operation service returned a mismatched run receipt")
    if receipt.status in _NONTERMINAL_STATUSES:
        if outcome.retry_after_seconds != _RETRY_AFTER_SECONDS:
            raise RuntimeError("backtest operation service returned an invalid active outcome")
        response.headers["Retry-After"] = str(outcome.retry_after_seconds)
    elif outcome.retry_after_seconds is not None:
        raise RuntimeError("backtest operation service returned an invalid terminal outcome")
    response.headers["Location"] = outcome.location
    return receipt


@router.patch("/backtest-runs/{run_id}", response_model=BacktestRunView | BacktestLoopRunView)
async def pin_backtest_run(
    run_id: RunIdPath,
    command: BacktestRunPinCommand,
    context: MutationContextDependency,
    service: BacktestRunOperationServiceDependency,
) -> BacktestRunView | BacktestLoopRunView:
    run = _validated_run(
        await service.pin_run(run_id=run_id, command=command, context=context),
    )
    if run.run_id != run_id or run.pinned != command.pinned:
        raise RuntimeError("backtest operation service returned a mismatched pinned run")
    return run


def _validated_run(value: object) -> BacktestRunView | BacktestLoopRunView:
    if isinstance(value, BacktestLoopRunView) or (
        isinstance(value, dict) and value.get("schemaVersion") == "monitor-loop-result-v1"
    ):
        return validate_api_response(value, BacktestLoopRunView)
    return validate_api_response(value, BacktestRunView)


def _run_filters(
    *,
    symbol: str | None,
    plan_version_id: str | None,
    dataset_hash: str | None,
    completed_from: str | None,
    completed_to: str | None,
    pinned: bool | None,
) -> BacktestRunFiltersView:
    try:
        return BacktestRunFiltersView.model_validate(
            {
                "symbol": symbol,
                "planVersionId": plan_version_id,
                "datasetHash": dataset_hash,
                "completedFrom": completed_from,
                "completedTo": completed_to,
                "pinned": pinned,
            }
        )
    except ValidationError:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


__all__ = [
    "BacktestRunOperationService",
    "BacktestRunPinCommand",
    "BacktestRunReadService",
    "BacktestRunSubmissionOutcome",
    "router",
]
