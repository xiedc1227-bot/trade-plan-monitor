"""The six opt-in runtime-status reads, sharing the existing URL boundary."""

from fastapi import APIRouter

from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import ReadServiceDependency, validate_read_response
from trade_plan_monitor.web.routers.symbols import LimitQuery, OffsetQuery, SymbolPath
from trade_plan_monitor.web.runtime_status_models import (
    RuntimeDashboardResponse,
    RuntimeExplicitDetailResponse,
    RuntimeHealthV2Response,
    RuntimeInactiveSymbolResponse,
    RuntimeSymbolCollectionResponse,
    RuntimeSymbolDetailResponse,
    RuntimeSymbolHealthResponse,
)

router = APIRouter(prefix="/api/v1", tags=["monitor"])
DetailResponse = RuntimeSymbolDetailResponse | RuntimeInactiveSymbolResponse


@router.get("/dashboard", response_model=RuntimeDashboardResponse)
async def get_dashboard(service: ReadServiceDependency) -> RuntimeDashboardResponse:
    return validate_read_response(await service.get_dashboard(), RuntimeDashboardResponse)


@router.get("/health", response_model=RuntimeHealthV2Response)
async def get_health(service: ReadServiceDependency) -> RuntimeHealthV2Response:
    return validate_read_response(await service.get_health(), RuntimeHealthV2Response)


@router.get("/symbols", response_model=RuntimeSymbolCollectionResponse)
async def list_symbols(
    service: ReadServiceDependency,
    offset: OffsetQuery = 0,
    limit: LimitQuery = 20,
) -> RuntimeSymbolCollectionResponse:
    response = validate_read_response(
        await service.list_symbols(offset=offset, limit=limit),
        RuntimeSymbolCollectionResponse,
    )
    if response.offset != offset or response.limit != limit:
        raise ValueError("service pagination does not match the request")
    return response


def _detail(value: object, symbol: str) -> DetailResponse:
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    if isinstance(value, RuntimeInactiveSymbolResponse) or (
        isinstance(value, dict) and value.get("availability") == "UNAVAILABLE"
    ):
        response = validate_read_response(value, RuntimeInactiveSymbolResponse)
        actual_symbol = response.symbol
    else:
        response = validate_read_response(value, RuntimeSymbolDetailResponse)
        actual_symbol = response.summary.symbol
    if actual_symbol != symbol:
        raise ValueError("service symbol does not match the request")
    return response


@router.get("/symbols/{symbol}", response_model=DetailResponse)
async def get_symbol(symbol: SymbolPath, service: ReadServiceDependency) -> DetailResponse:
    return _detail(await service.get_symbol(symbol=symbol), symbol)


@router.get("/health/symbols/{symbol}", response_model=RuntimeSymbolHealthResponse)
async def get_symbol_health(
    symbol: SymbolPath,
    service: ReadServiceDependency,
) -> RuntimeSymbolHealthResponse:
    value = await service.get_symbol_health(symbol=symbol)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = validate_read_response(value, RuntimeSymbolHealthResponse)
    if response.scope.symbol != symbol:
        raise ValueError("service health scope does not match the request")
    return response


@router.get(
    "/explicit-plan-runtime/{symbol}",
    response_model=RuntimeExplicitDetailResponse | RuntimeInactiveSymbolResponse,
)
async def get_explicit_plan_runtime(
    symbol: SymbolPath,
    service: ReadServiceDependency,
) -> RuntimeExplicitDetailResponse | RuntimeInactiveSymbolResponse:
    response = _detail(await service.get_explicit_plan_runtime(symbol=symbol), symbol)
    if isinstance(response, RuntimeSymbolDetailResponse):
        if response.summary.plan_family != "EXPLICIT_RULES":
            raise ApiError(ApiErrorCode.NOT_FOUND)
        return validate_read_response(
            response.model_dump(mode="python", by_alias=True), RuntimeExplicitDetailResponse,
        )
    return response
