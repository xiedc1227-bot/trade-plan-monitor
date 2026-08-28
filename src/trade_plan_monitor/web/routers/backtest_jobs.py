"""Thin HTTP adapters for durable backtest job reads and cancellation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import Field, ValidationError

from trade_plan_monitor.web.backtest_schemas import (
    BacktestJobFiltersView,
    BacktestJobKind,
    BacktestJobPage,
    BacktestJobStatus,
    BacktestJobView,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    ApiValue,
    MutationContext,
    MutationContextDependency,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["backtest-jobs"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_RETRY_AFTER_SECONDS = 2
_JOB_LOCATION_PREFIX = "/api/v1/backtest-jobs/"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_JOB_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_CURSOR_PATTERN = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"

JobIdPath = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=_JOB_ID_PATTERN),
]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
CursorQuery = Annotated[
    str | None,
    Query(min_length=3, max_length=512, pattern=_CURSOR_PATTERN),
]
KindQuery = Annotated[list[BacktestJobKind] | None, Query()]
StatusQuery = Annotated[list[BacktestJobStatus] | None, Query()]
RunIdQuery = Annotated[
    str | None,
    Query(alias="runId", min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
DatasetHashQuery = Annotated[
    str | None,
    Query(alias="datasetHash", min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
CreatedFromQuery = Annotated[
    str | None,
    Query(alias="createdFrom", min_length=25, max_length=40),
]
CreatedToQuery = Annotated[
    str | None,
    Query(alias="createdTo", min_length=25, max_length=40),
]
JobIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=128, pattern=_JOB_ID_PATTERN),
]


class BacktestJobCancellationCommand(ApiValue):
    """The exact public cancellation body; idempotency remains in its header."""

    job_id: JobIdentifier


@dataclass(frozen=True, slots=True)
class BacktestJobCancellationOutcome:
    """Application-owned canonical cancellation response and transport metadata."""

    job: object
    status_code: Literal[200, 202]
    location: str | None
    retry_after_seconds: Literal[2] | None


class BacktestReadService(Protocol):
    """Read-only job query boundary implemented outside the HTTP adapter."""

    async def list_jobs(
        self,
        *,
        filters: BacktestJobFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestJobPage: ...

    async def get_job(self, *, job_id: str) -> BacktestJobView | None: ...


class BacktestOperationService(Protocol):
    """Atomic cancellation/idempotency boundary implemented by the application layer."""

    async def request_cancel(
        self,
        *,
        command: BacktestJobCancellationCommand,
        context: MutationContext,
    ) -> BacktestJobCancellationOutcome: ...


def get_backtest_read_service(request: Request) -> BacktestReadService:
    service = getattr(request.app.state, "backtest_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestReadService, service)


def get_backtest_operation_service(request: Request) -> BacktestOperationService:
    service = getattr(request.app.state, "backtest_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestOperationService, service)


BacktestReadServiceDependency = Annotated[
    BacktestReadService,
    Depends(get_backtest_read_service),
]
BacktestOperationServiceDependency = Annotated[
    BacktestOperationService,
    Depends(get_backtest_operation_service),
]


@router.get("/backtest-jobs", response_model=BacktestJobPage)
async def list_backtest_jobs(
    service: BacktestReadServiceDependency,
    kind: KindQuery = None,
    status: StatusQuery = None,
    run_id: RunIdQuery = None,
    dataset_hash: DatasetHashQuery = None,
    created_from: CreatedFromQuery = None,
    created_to: CreatedToQuery = None,
    limit: LimitQuery = _DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> BacktestJobPage:
    filters = _job_filters(
        kind=kind,
        status=status,
        run_id=run_id,
        dataset_hash=dataset_hash,
        created_from=created_from,
        created_to=created_to,
    )
    page = validate_api_response(
        await service.list_jobs(filters=filters, limit=limit, cursor=cursor),
        BacktestJobPage,
    )
    if page.filters != filters or page.limit != limit:
        raise RuntimeError("backtest job service returned mismatched pagination")
    return page


@router.get("/backtest-jobs/{job_id}", response_model=BacktestJobView)
async def get_backtest_job(
    job_id: JobIdPath,
    service: BacktestReadServiceDependency,
) -> BacktestJobView:
    value = await service.get_job(job_id=job_id)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    job = validate_api_response(value, BacktestJobView)
    if job.job_id != job_id:
        raise RuntimeError("backtest job service returned a mismatched job")
    return job


@router.post(
    "/backtest-job-cancellations",
    response_model=BacktestJobView,
    responses={202: {"model": BacktestJobView}},
)
async def request_backtest_job_cancellation(
    command: BacktestJobCancellationCommand,
    context: MutationContextDependency,
    service: BacktestOperationServiceDependency,
    response: Response,
) -> BacktestJobView:
    outcome = await service.request_cancel(command=command, context=context)
    if not isinstance(outcome, BacktestJobCancellationOutcome):
        raise RuntimeError("backtest operation service returned an invalid cancellation outcome")
    job = validate_api_response(outcome.job, BacktestJobView)
    if job.job_id != command.job_id:
        raise RuntimeError("backtest operation service returned a mismatched job")
    expected_location = f"{_JOB_LOCATION_PREFIX}{job.job_id}"
    if outcome.status_code == 200:
        if (
            job.status != "CANCELLED"
            or outcome.location is not None
            or outcome.retry_after_seconds is not None
        ):
            raise RuntimeError("backtest operation service returned an invalid terminal outcome")
    elif outcome.status_code == 202:
        if (
            job.status != "CANCEL_REQUESTED"
            or outcome.location != expected_location
            or outcome.retry_after_seconds != _RETRY_AFTER_SECONDS
        ):
            raise RuntimeError("backtest operation service returned an invalid active outcome")
        response.headers["Location"] = outcome.location
        response.headers["Retry-After"] = str(outcome.retry_after_seconds)
    else:  # pragma: no cover - guarded by the closed application result contract
        raise RuntimeError("backtest operation service returned an invalid HTTP status")
    response.status_code = outcome.status_code
    return job


def _job_filters(
    *,
    kind: list[BacktestJobKind] | None,
    status: list[BacktestJobStatus] | None,
    run_id: str | None,
    dataset_hash: str | None,
    created_from: str | None,
    created_to: str | None,
) -> BacktestJobFiltersView:
    try:
        return BacktestJobFiltersView.model_validate(
            {
                "kind": kind,
                "status": status,
                "runId": run_id,
                "datasetHash": dataset_hash,
                "createdFrom": created_from,
                "createdTo": created_to,
            }
        )
    except ValidationError:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


__all__ = [
    "BacktestJobCancellationCommand",
    "BacktestJobCancellationOutcome",
    "BacktestOperationService",
    "BacktestReadService",
    "router",
]
