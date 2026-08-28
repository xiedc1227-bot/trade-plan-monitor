"""Thin HTTP adapters for durable backtest data jobs and dataset reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pydantic import ValidationError

from trade_plan_monitor.web.backtest_schemas import (
    BacktestDatasetFiltersView,
    BacktestDatasetPage,
    BacktestDatasetVerificationCommand,
    BacktestDatasetView,
    BacktestDataSyncCommand,
    BacktestJobKind,
    BacktestJobReceipt,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    MutationContext,
    MutationContextDependency,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["backtest-data"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_RETRY_AFTER_SECONDS = 2
_JOB_LOCATION_PREFIX = "/api/v1/backtest-jobs/"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SYMBOL_PATTERN = r"^[0-9]{6}\.(?:SH|SZ)$"
_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_CURSOR_PATTERN = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"
_NONTERMINAL_STATUSES = frozenset({"QUEUED", "RUNNING", "CANCEL_REQUESTED"})

DatasetHashPath = Annotated[
    str,
    Path(min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
SymbolQuery = Annotated[
    str | None,
    Query(min_length=9, max_length=9, pattern=_SYMBOL_PATTERN),
]
StartOnOrAfterQuery = Annotated[
    str | None,
    Query(alias="startOnOrAfter", min_length=10, max_length=10, pattern=_DATE_PATTERN),
]
EndOnOrBeforeQuery = Annotated[
    str | None,
    Query(alias="endOnOrBefore", min_length=10, max_length=10, pattern=_DATE_PATTERN),
]
HistoricalProfileQuery = Annotated[
    Literal["TUSHARE_STK_MINS_241_END_V1"] | None,
    Query(alias="historicalProfile"),
]
AdjustmentPolicyQuery = Annotated[
    Literal["NONE"] | None,
    Query(alias="adjustmentPolicy"),
]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
CursorQuery = Annotated[
    str | None,
    Query(min_length=3, max_length=512, pattern=_CURSOR_PATTERN),
]


@dataclass(frozen=True, slots=True)
class BacktestJobSubmissionOutcome:
    """Application-owned canonical submission receipt and transport metadata."""

    receipt: object
    location: str
    retry_after_seconds: Literal[2] | None


class BacktestDataReadService(Protocol):
    """Read-only dataset query boundary implemented outside the HTTP adapter."""

    async def list_datasets(
        self,
        *,
        filters: BacktestDatasetFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestDatasetPage: ...

    async def get_dataset(self, *, dataset_hash: str) -> BacktestDatasetView | None: ...


class BacktestDataOperationService(Protocol):
    """Durable data-job submission boundary implemented by the application layer."""

    async def submit_data_sync(
        self,
        *,
        command: BacktestDataSyncCommand,
        context: MutationContext,
    ) -> BacktestJobSubmissionOutcome: ...

    async def submit_dataset_verification(
        self,
        *,
        command: BacktestDatasetVerificationCommand,
        context: MutationContext,
    ) -> BacktestJobSubmissionOutcome: ...


def get_backtest_data_read_service(request: Request) -> BacktestDataReadService:
    service = getattr(request.app.state, "backtest_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestDataReadService, service)


def get_backtest_data_operation_service(request: Request) -> BacktestDataOperationService:
    service = getattr(request.app.state, "backtest_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestDataOperationService, service)


BacktestDataReadServiceDependency = Annotated[
    BacktestDataReadService,
    Depends(get_backtest_data_read_service),
]
BacktestDataOperationServiceDependency = Annotated[
    BacktestDataOperationService,
    Depends(get_backtest_data_operation_service),
]


@router.post(
    "/backtest-data-syncs",
    response_model=BacktestJobReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_backtest_data_sync(
    command: BacktestDataSyncCommand,
    context: MutationContextDependency,
    service: BacktestDataOperationServiceDependency,
    response: Response,
) -> BacktestJobReceipt:
    outcome = await service.submit_data_sync(command=command, context=context)
    return _submission_response(
        outcome=outcome,
        expected_kind="DATA_SYNC",
        response=response,
    )


@router.post(
    "/backtest-dataset-verifications",
    response_model=BacktestJobReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_backtest_dataset_verification(
    command: BacktestDatasetVerificationCommand,
    context: MutationContextDependency,
    service: BacktestDataOperationServiceDependency,
    response: Response,
) -> BacktestJobReceipt:
    outcome = await service.submit_dataset_verification(command=command, context=context)
    return _submission_response(
        outcome=outcome,
        expected_kind="DATASET_VERIFY",
        response=response,
    )


@router.get("/backtest-datasets", response_model=BacktestDatasetPage)
async def list_backtest_datasets(
    service: BacktestDataReadServiceDependency,
    symbol: SymbolQuery = None,
    start_on_or_after: StartOnOrAfterQuery = None,
    end_on_or_before: EndOnOrBeforeQuery = None,
    historical_profile: HistoricalProfileQuery = None,
    adjustment_policy: AdjustmentPolicyQuery = None,
    limit: LimitQuery = _DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> BacktestDatasetPage:
    filters = _dataset_filters(
        symbol=symbol,
        start_on_or_after=start_on_or_after,
        end_on_or_before=end_on_or_before,
        historical_profile=historical_profile,
        adjustment_policy=adjustment_policy,
    )
    page = validate_api_response(
        await service.list_datasets(filters=filters, limit=limit, cursor=cursor),
        BacktestDatasetPage,
    )
    if page.filters != filters or page.limit != limit:
        raise RuntimeError("backtest dataset service returned mismatched pagination")
    return page


@router.get("/backtest-datasets/{dataset_hash}", response_model=BacktestDatasetView)
async def get_backtest_dataset(
    dataset_hash: DatasetHashPath,
    service: BacktestDataReadServiceDependency,
) -> BacktestDatasetView:
    value = await service.get_dataset(dataset_hash=dataset_hash)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    dataset = validate_api_response(value, BacktestDatasetView)
    if dataset.dataset_hash != dataset_hash:
        raise RuntimeError("backtest dataset service returned a mismatched dataset")
    return dataset


def _submission_response(
    *,
    outcome: object,
    expected_kind: BacktestJobKind,
    response: Response,
) -> BacktestJobReceipt:
    if not isinstance(outcome, BacktestJobSubmissionOutcome):
        raise RuntimeError("backtest operation service returned an invalid submission outcome")
    receipt = validate_api_response(outcome.receipt, BacktestJobReceipt)
    if receipt.kind != expected_kind:
        raise RuntimeError("backtest operation service returned a mismatched receipt")
    expected_location = f"{_JOB_LOCATION_PREFIX}{receipt.job_id}"
    if outcome.location != expected_location:
        raise RuntimeError("backtest operation service returned an invalid job location")
    if receipt.status in _NONTERMINAL_STATUSES:
        if outcome.retry_after_seconds != _RETRY_AFTER_SECONDS:
            raise RuntimeError("backtest operation service returned an invalid active outcome")
        response.headers["Retry-After"] = str(outcome.retry_after_seconds)
    elif outcome.retry_after_seconds is not None:
        raise RuntimeError("backtest operation service returned an invalid terminal outcome")
    response.headers["Location"] = outcome.location
    return receipt


def _dataset_filters(
    *,
    symbol: str | None,
    start_on_or_after: str | None,
    end_on_or_before: str | None,
    historical_profile: Literal["TUSHARE_STK_MINS_241_END_V1"] | None,
    adjustment_policy: Literal["NONE"] | None,
) -> BacktestDatasetFiltersView:
    try:
        return BacktestDatasetFiltersView.model_validate(
            {
                "symbol": symbol,
                "startOnOrAfter": start_on_or_after,
                "endOnOrBefore": end_on_or_before,
                "historicalProfile": historical_profile,
                "adjustmentPolicy": adjustment_policy,
            }
        )
    except ValidationError:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


__all__ = [
    "BacktestDataOperationService",
    "BacktestDataReadService",
    "BacktestJobSubmissionOutcome",
    "router",
]
