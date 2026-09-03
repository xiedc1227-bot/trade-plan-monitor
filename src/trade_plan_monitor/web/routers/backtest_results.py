"""Thin HTTP adapters for completed backtest result reads."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, Path, Query, Request

from trade_plan_monitor.web.backtest_schemas import (
    BacktestDetailFiltersView,
    BacktestDetailPage,
    BacktestEquitySeries,
    BacktestFillFiltersView,
    BacktestFillPage,
    BacktestMarketIndexPointView,
    BacktestMarketIndexSeriesView,
    BacktestPublicDetailKind,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode, validate_api_response

router = APIRouter(prefix="/api/v1", tags=["backtest-results"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CURSOR_PATTERN = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"

RunIdPath = Annotated[
    str,
    Path(min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
DetailKindQuery = Annotated[BacktestPublicDetailKind, Query()]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
CursorQuery = Annotated[
    str | None,
    Query(min_length=3, max_length=512, pattern=_CURSOR_PATTERN),
]


class BacktestResultReadService(Protocol):
    """Completed-result Web projection boundary implemented by the application."""

    async def list_fills(
        self,
        *,
        run_id: str,
        limit: int,
        cursor: str | None,
    ) -> BacktestFillPage: ...

    async def list_details(
        self,
        *,
        run_id: str,
        filters: BacktestDetailFiltersView,
        limit: int,
        cursor: str | None,
    ) -> BacktestDetailPage: ...

    async def get_equity_series(self, *, run_id: str) -> BacktestEquitySeries: ...

    async def get_market_index_series(
        self,
        *,
        run_id: str,
        start_on: date | None,
        end_on: date | None,
        limit: int,
    ) -> BacktestMarketIndexSeriesView: ...


def get_backtest_result_read_service(request: Request) -> BacktestResultReadService:
    service = getattr(request.app.state, "backtest_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestResultReadService, service)


BacktestResultReadServiceDependency = Annotated[
    BacktestResultReadService,
    Depends(get_backtest_result_read_service),
]


def require_fill_query(request: Request) -> None:
    _require_closed_query(request, allowed=frozenset({"limit", "cursor"}))


def require_detail_query(request: Request) -> None:
    _require_closed_query(request, allowed=frozenset({"kind", "limit", "cursor"}))


def require_equity_query(request: Request) -> None:
    _require_closed_query(request, allowed=frozenset())


def require_market_index_series_query(request: Request) -> None:
    _require_closed_query(request, allowed=frozenset({"startOn", "endOn", "limit"}))


FillQueryDependency = Annotated[None, Depends(require_fill_query)]
DetailQueryDependency = Annotated[None, Depends(require_detail_query)]
EquityQueryDependency = Annotated[None, Depends(require_equity_query)]
MarketIndexSeriesQueryDependency = Annotated[
    None,
    Depends(require_market_index_series_query),
]


@router.get("/backtest-runs/{run_id}/fills", response_model=BacktestFillPage)
async def list_backtest_fills(
    run_id: RunIdPath,
    _query: FillQueryDependency,
    service: BacktestResultReadServiceDependency,
    limit: LimitQuery = _DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> BacktestFillPage:
    filters = BacktestFillFiltersView()
    page = validate_api_response(
        await service.list_fills(run_id=run_id, limit=limit, cursor=cursor),
        BacktestFillPage,
    )
    if (
        page.filters != filters
        or page.limit != limit
        or any(item.run_id != run_id for item in page.items)
    ):
        raise RuntimeError("backtest fill service returned a mismatched page")
    return page


@router.get("/backtest-runs/{run_id}/details", response_model=BacktestDetailPage)
async def list_backtest_details(
    run_id: RunIdPath,
    _query: DetailQueryDependency,
    service: BacktestResultReadServiceDependency,
    kind: DetailKindQuery,
    limit: LimitQuery = _DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> BacktestDetailPage:
    filters = BacktestDetailFiltersView(kind=kind)
    page = validate_api_response(
        await service.list_details(
            run_id=run_id,
            filters=filters,
            limit=limit,
            cursor=cursor,
        ),
        BacktestDetailPage,
    )
    if (
        page.kind != kind
        or page.filters != filters
        or page.limit != limit
        or any(item.run_id != run_id for item in page.items)
    ):
        raise RuntimeError("backtest detail service returned a mismatched page")
    return page


@router.get("/backtest-runs/{run_id}/equity-series", response_model=BacktestEquitySeries)
async def get_backtest_equity_series(
    run_id: RunIdPath,
    _query: EquityQueryDependency,
    service: BacktestResultReadServiceDependency,
) -> BacktestEquitySeries:
    series = validate_api_response(
        await service.get_equity_series(run_id=run_id),
        BacktestEquitySeries,
    )
    if any(item.run_id != run_id for item in series.items):
        raise RuntimeError("backtest equity service returned a mismatched series")
    return series


@router.get(
    "/backtest-runs/{run_id}/market-index-series",
    response_model=BacktestMarketIndexSeriesView,
)
async def get_backtest_market_index_series(
    run_id: RunIdPath,
    _query: MarketIndexSeriesQueryDependency,
    service: BacktestResultReadServiceDependency,
    start_on: Annotated[date | None, Query(alias="startOn")] = None,
    end_on: Annotated[date | None, Query(alias="endOn")] = None,
    limit: Annotated[int, Query(ge=1, le=512)] = 512,
) -> BacktestMarketIndexSeriesView:
    if start_on is not None and end_on is not None and start_on > end_on:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    series = validate_api_response(
        await service.get_market_index_series(
            run_id=run_id,
            start_on=start_on,
            end_on=end_on,
            limit=limit,
        ),
        BacktestMarketIndexSeriesView,
    )
    if series.run_id != run_id or len(series.items) > limit:
        raise RuntimeError("backtest index service returned a mismatched series")
    if start_on is not None and any(item.trade_date < start_on for item in series.items):
        raise RuntimeError("backtest index service ignored startOn")
    if end_on is not None and any(item.trade_date > end_on for item in series.items):
        raise RuntimeError("backtest index service ignored endOn")
    return series


def downsample_market_index_points(
    points: tuple[BacktestMarketIndexPointView, ...],
    *,
    limit: int,
) -> tuple[BacktestMarketIndexPointView, ...]:
    """Reduce display points deterministically while preserving both ends when possible."""

    if type(points) is not tuple or any(
        type(point) is not BacktestMarketIndexPointView for point in points
    ):
        raise TypeError("points must be an exact tuple of BacktestMarketIndexPointView")
    if type(limit) is not int or not 1 <= limit <= 512:
        raise ValueError("limit must be between 1 and 512")
    if len(points) <= limit:
        return points
    if limit == 1:
        return points[:1]
    last = len(points) - 1
    return tuple(points[index * last // (limit - 1)] for index in range(limit))


def _require_closed_query(request: Request, *, allowed: frozenset[str]) -> None:
    names = tuple(name for name, _value in request.query_params.multi_items())
    counts = Counter(names)
    if not counts.keys() <= allowed or any(count != 1 for count in counts.values()):
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)


__all__ = [
    "BacktestResultReadService",
    "downsample_market_index_points",
    "get_backtest_result_read_service",
    "router",
]
