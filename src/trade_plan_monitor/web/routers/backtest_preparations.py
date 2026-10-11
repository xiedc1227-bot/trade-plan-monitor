"""One-source preparation HTTP commands; no provider or SQL work in handlers."""

from collections import Counter
from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import TypeAdapter

from trade_plan_monitor.backtest.jobs import JobAdmissionError
from trade_plan_monitor.backtest.models import StableIdentifier
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    PreparationRecord,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.preparation_schemas import (
    CollectionExtractionCommand,
    CollectionItemCorrectionInput,
    CollectionItemsPage,
    CollectionPreparationFrozenView,
    CollectionPreparationView,
    CollectionRecoveryCommand,
    CollectionReviewInput,
    CollectionRevisionCommand,
    CollectionSourceCommand,
    PreparationCreateCommand,
    PreparationFrozenView,
    PreparationProgressView,
    PreparationRecoveryCommand,
    PreparationReviewInput,
    PreparationRevisionCommand,
    PreparationSourceCommand,
    PreparationView,
    project_collection_frozen,
    project_collection_items,
    project_preparation,
)
from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    ErrorDetail,
    ErrorResponse,
    MutationContextDependency,
)

_CACHE_HEADERS = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
_PROGRESS_HEADERS = {
    **_CACHE_HEADERS,
    "Location": {
        "schema": {
            "type": "string",
            "maxLength": len("/api/v1/backtest-preparations/") + 128,
            "pattern": r"^/api/v1/backtest-preparations/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        }
    },
}
_ACCEPTED_HEADERS = {
    **_PROGRESS_HEADERS,
    "Retry-After": {"schema": {"type": "integer", "const": 2}},
}


def _progress_responses(*statuses: int) -> dict[int, dict[str, object]]:
    return {
        status: {
            "model": PreparationProgressView,
            "headers": _ACCEPTED_HEADERS if status == 202 else _PROGRESS_HEADERS,
        }
        for status in statuses
    }


router = APIRouter(
    prefix="/api/v1/backtest-preparations",
    tags=["backtest-preparations"],
    responses={
        503: {
            "model": ErrorResponse,
            "headers": {
                "Retry-After": {"schema": {"type": "integer", "minimum": 1, "maximum": 1}},
            },
        }
    },
)
_IDENTIFIER = TypeAdapter(StableIdentifier)
PreparationId = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


def require_preparation_request(request: Request) -> None:
    if request.url.path.endswith("/items") and request.method == "GET":
        pairs = request.query_params.multi_items()
        if (any(name not in {"expectedRevision", "offset", "limit"} or not value.isascii()
                or not value.isdecimal() or len(value) > 16 for name, value in pairs)
                or any(count != 1 for count in Counter(name for name, _ in pairs).values())):
            raise ApiError(ApiErrorCode.VALIDATION_ERROR)
        values = dict(pairs)
        if ("expectedRevision" not in values
                or not 1 <= int(values["expectedRevision"]) <= 9_007_199_254_740_991
                or not 0 <= int(values.get("offset", "0")) <= 255
                or not 1 <= int(values.get("limit", "20")) <= 100):
            raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    elif request.query_params:
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


@router.post(
    "", response_model=PreparationProgressView, status_code=201, responses=_progress_responses(201)
)
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


@router.get("/{preparation_id}", response_model=PreparationProgressView,
            responses=_progress_responses(200))
async def get_preparation(preparation_id: PreparationId, service: Service, response: Response):
    record = await _invoke(service.get(preparation_id))
    if record is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    return _view(record, response)


@router.put(
    "/{preparation_id}/source", response_model=PreparationProgressView,
    responses=_progress_responses(200)
)
async def edit_preparation(
    preparation_id: PreparationId,
    command: PreparationSourceCommand | CollectionSourceCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    collection = isinstance(command, CollectionSourceCommand)
    await _require_schema(service, preparation_id, collection)
    kwargs = dict(source=command.source, expected_revision=command.expected_revision,
                  idempotency_key=context.idempotency_key)
    if collection:
        operation = service.edit_collection(
            preparation_id, source_order=command.source_order, **kwargs,
        )
    else:
        operation = service.edit_source(preparation_id, **kwargs)
    return _view(await _invoke(operation), response)



@router.post(
    "/{preparation_id}/extractions",
    response_model=PreparationProgressView,
    status_code=202,
    responses=_progress_responses(202),
)
async def extract_preparation(
    preparation_id: PreparationId,
    command: PreparationRevisionCommand | CollectionExtractionCommand,
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
            collection_mode=isinstance(command, CollectionExtractionCommand),
            item_binding=(command.source_id, command.expected_source_revision,
                          command.expected_base_hash)
            if isinstance(command, CollectionExtractionCommand) and command.source_id else None,
        )
    )
    return _view(record, response, accepted=True)


@router.post(
    "/{preparation_id}/cancellations",
    response_model=PreparationProgressView,
    responses=_progress_responses(200, 202),
)
async def cancel_preparation(
    preparation_id: PreparationId,
    command: PreparationRevisionCommand | CollectionRevisionCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    await _require_schema(service, preparation_id, isinstance(command, CollectionRevisionCommand))
    record = await _invoke(
        service.cancel(
            preparation_id,
            expected_revision=command.expected_revision,
            idempotency_key=context.idempotency_key,
        )
    )
    return _view(record, response, accepted=record.status == "CANCEL_REQUESTED")


@router.post(
    "/{preparation_id}/reviews",
    response_model=(PreparationFrozenView | CollectionPreparationFrozenView
                    | CollectionPreparationView),
    responses={200: {"headers": _CACHE_HEADERS}},
)
async def review_preparation(
    preparation_id: PreparationId,
    command: PreparationReviewInput | CollectionReviewInput | CollectionItemCorrectionInput,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    collection = isinstance(command, (CollectionReviewInput, CollectionItemCorrectionInput))
    await _require_schema(service, preparation_id, collection)
    if isinstance(command, CollectionItemCorrectionInput):
        corrected = await _invoke(service.correct_collection_item(
            preparation_id, command=command.review, idempotency_key=context.idempotency_key,
        ))
        return _view(corrected, response)
    frozen = await _invoke(
        service.review_and_freeze(
            preparation_id, command=command.review, idempotency_key=context.idempotency_key
        )
    )
    response.headers["Cache-Control"] = "no-store"
    if collection:
        return project_collection_frozen(frozen)
    return PreparationFrozenView(
        preparation_id=preparation_id, manifest_hash=frozen.manifest_hash, frozen=frozen
    )


@router.post(
    "/{preparation_id}/recoveries",
    response_model=PreparationProgressView,
    responses=_progress_responses(200),
)
async def recover_preparation(
    preparation_id: PreparationId,
    command: PreparationRecoveryCommand | CollectionRecoveryCommand,
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    await _require_schema(service, preparation_id, isinstance(command, CollectionRecoveryCommand))
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


async def _require_schema(service, identity, collection):
    record = await _invoke(service.get(identity))
    if record is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    if isinstance(record, CollectionPreparationRecord) != collection:
        raise ApiError(ApiErrorCode.CONFLICT, details=(ErrorDetail(
            location=("preparation",), code="PREPARATION_SCHEMA_CONFLICT",
            message="Preparation command does not match the stored schema.",
        ),))
    return record


@router.get("/{preparation_id}/items", response_model=CollectionItemsPage,
            responses={200: {"headers": _CACHE_HEADERS}})
async def get_preparation_items(
    preparation_id: PreparationId,
    service: Service,
    response: Response,
    expected_revision: Annotated[int, Query(alias="expectedRevision", ge=1,
                                         le=9_007_199_254_740_991)],
    offset: Annotated[int, Query(ge=0, le=255)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    record = await _require_schema(service, preparation_id, True)
    if record.revision != expected_revision:
        raise ApiError(ApiErrorCode.CONFLICT, details=(ErrorDetail(
            location=("preparation",), code="PREPARATION_REVISION_CONFLICT",
            message="Preparation revision changed; reload its progress.",
        ),))
    response.headers["Cache-Control"] = "no-store"
    try:
        return project_collection_items(record, offset=offset, limit=limit)
    except PreparationConflictError as error:
        raise ApiError(ApiErrorCode.CONFLICT, details=(ErrorDetail(
            location=("preparation",), code=error.code,
            message="Preparation item exceeds the bounded projection.",
        ),)) from None
