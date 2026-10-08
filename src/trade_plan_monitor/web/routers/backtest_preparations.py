"""One-source preparation HTTP commands; no provider or SQL work in handlers."""

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import TypeAdapter

from trade_plan_monitor.backtest.jobs import JobAdmissionError
from trade_plan_monitor.backtest.models import StableIdentifier
from trade_plan_monitor.backtest.preparation_models import PreparationRecord
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.preparation_schemas import (
    PreparationCreateCommand,
    PreparationFrozenView,
    PreparationRecoveryCommand,
    PreparationReviewInput,
    PreparationRevisionCommand,
    PreparationSourceCommand,
    PreparationView,
    project_preparation,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, ErrorDetail, MutationContextDependency

# ML-T13 publishes schemas/contracts after this mounted HTTP application path is verified.
router = APIRouter(
    prefix="/api/v1/backtest-preparations", tags=["backtest-preparations"], include_in_schema=False
)
_IDENTIFIER = TypeAdapter(StableIdentifier)
PreparationId = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


def require_preparation_request(request: Request) -> None:
    if request.query_params:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    identity = request.path_params.get("preparation_id")
    if identity is not None:
        try:
            _IDENTIFIER.validate_python(identity)
        except ValueError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


def get_preparation_service(request: Request) -> PreparationService:
    service = getattr(request.state, "preparation_service", None)
    if not isinstance(service, PreparationService):
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return service


Service = Annotated[PreparationService, Depends(get_preparation_service)]


async def _invoke[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (PreparationConflictError, JobAdmissionError) as error:
        code = (
            ApiErrorCode.NOT_FOUND
            if error.code == "PREPARATION_NOT_FOUND"
            else ApiErrorCode.CONFLICT
        )
        raise ApiError(
            code,
            details=(
                ErrorDetail(
                    location=("preparation",),
                    code=error.code,
                    message="Preparation operation conflicts with current state.",
                ),
            ),
        ) from None
    except BacktestServiceUnavailable:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None


def _view(
    record: PreparationRecord, response: Response, *, accepted: bool = False
) -> PreparationView:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/backtest-preparations/{record.preparation_id}"
    if accepted:
        response.status_code = 202
        response.headers["Retry-After"] = "2"
    return project_preparation(record)


@router.post("", response_model=PreparationView, status_code=201)
async def create_preparation(
    command: PreparationCreateCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    return _view(
        await _invoke(service.create(command.input, idempotency_key=context.idempotency_key)),
        response,
    )


@router.get("/{preparation_id}", response_model=PreparationView)
async def get_preparation(preparation_id: PreparationId, service: Service, response: Response):
    record = await _invoke(service.get(preparation_id))
    if record is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    return _view(record, response)


@router.put("/{preparation_id}/source", response_model=PreparationView)
async def edit_preparation(
    preparation_id: PreparationId,
    command: PreparationSourceCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    return _view(
        await _invoke(
            service.edit_source(
                preparation_id,
                source=command.source,
                expected_revision=command.expected_revision,
                idempotency_key=context.idempotency_key,
            )
        ),
        response,
    )


@router.post("/{preparation_id}/extractions", response_model=PreparationView, status_code=202)
async def extract_preparation(
    preparation_id: PreparationId,
    command: PreparationRevisionCommand,
    context: MutationContextDependency,
    service: Service,
    request: Request,
    response: Response,
):
    def factory():
        configured = getattr(request.app.state, "plan_extraction_service", None)
        capture = getattr(configured, "backtest_extractor", None)
        if not callable(capture):
            raise BacktestServiceUnavailable()
        return capture()

    record = await _invoke(
        service.submit_extraction(
            preparation_id,
            expected_revision=command.expected_revision,
            idempotency_key=context.idempotency_key,
            extractor_factory=factory,
        )
    )
    return _view(record, response, accepted=True)


@router.post("/{preparation_id}/cancellations", response_model=PreparationView)
async def cancel_preparation(
    preparation_id: PreparationId,
    command: PreparationRevisionCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    record = await _invoke(
        service.cancel(
            preparation_id,
            expected_revision=command.expected_revision,
            idempotency_key=context.idempotency_key,
        )
    )
    return _view(record, response, accepted=record.status == "CANCEL_REQUESTED")


@router.post("/{preparation_id}/reviews", response_model=PreparationFrozenView)
async def review_preparation(
    preparation_id: PreparationId,
    command: PreparationReviewInput,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    frozen = await _invoke(
        service.review_and_freeze(
            preparation_id, command=command.review, idempotency_key=context.idempotency_key
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return PreparationFrozenView(
        preparation_id=preparation_id, manifest_hash=frozen.manifest_hash, frozen=frozen
    )


@router.post("/{preparation_id}/recoveries", response_model=PreparationView)
async def recover_preparation(
    preparation_id: PreparationId,
    command: PreparationRecoveryCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    record = await _invoke(
        service.recover(
            preparation_id,
            generation=command.generation,
            expected_revision=command.expected_revision,
            confirmed_ended=command.confirmed_ended,
            idempotency_key=context.idempotency_key,
        )
    )
    return _view(record, response)
