"""Typed symbol, bar, and event read routes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query
from pydantic import Field, model_validator

from trade_plan_monitor.decision.models import PositionBucket, SignalType
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import (
    IndexConditionEvidenceView,
    ProjectionUnavailableReason,
    ReadModel,
    ReadServiceDependency,
    SafeMonitorSequence,
    Sha256Hex,
    SymbolReferenceMarketView,
    SymbolSummaryView,
    validate_read_response,
)

router = APIRouter(prefix="/api/v1", tags=["monitor"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_ROWS = 10_000

OffsetQuery = Annotated[int, Query(ge=0, le=_MAX_ROWS)]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
SymbolPath = Annotated[AShareSymbol, Path()]
RangeStartQuery = Annotated[ShanghaiDatetime, Query(alias="startAt")]
RangeEndQuery = Annotated[ShanghaiDatetime, Query(alias="endAt")]


class BarInterval(StrEnum):
    ONE_MINUTE = "ONE_MINUTE"
    FIVE_MINUTES = "FIVE_MINUTES"


class SymbolEventType(StrEnum):
    DECISION = "DECISION"
    EPISODE = "EPISODE"
    RISK = "RISK"
    ALERT = "ALERT"
    HEALTH = "HEALTH"


class PositionLotView(ReadModel):
    lot_id: Annotated[str, Field(strict=True, min_length=1, max_length=36)]
    bucket: PositionBucket
    quantity: Annotated[int, Field(strict=True, gt=0, multiple_of=100)]
    remaining_quantity: Annotated[int, Field(strict=True, ge=0, multiple_of=100)]
    sellable_quantity: Annotated[int, Field(strict=True, ge=0, multiple_of=100)]
    acquired_trade_date: Annotated[date, Field(strict=True)]
    cost_fen: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def validate_quantities(self) -> PositionLotView:
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining quantity cannot exceed quantity")
        if self.sellable_quantity > self.remaining_quantity:
            raise ValueError("sellable quantity cannot exceed remaining quantity")
        return self


class SymbolDetailResponse(ReadModel):
    summary: SymbolSummaryView
    position_lots: tuple[PositionLotView, ...] = Field(default=(), max_length=200)
    reference_market: SymbolReferenceMarketView | None = None
    index_condition_evidence: tuple[IndexConditionEvidenceView, ...] = Field(
        default=(),
        max_length=50,
    )

    @model_validator(mode="after")
    def validate_positions(self) -> SymbolDetailResponse:
        lot_ids = tuple(lot.lot_id for lot in self.position_lots)
        if len(set(lot_ids)) != len(lot_ids):
            raise ValueError("position lot identities must be unique")
        position = self.summary.decision.position
        core_lots = tuple(lot for lot in self.position_lots if lot.bucket == "CORE")
        tactical_lots = tuple(lot for lot in self.position_lots if lot.bucket == "TACTICAL")
        if sum(lot.remaining_quantity for lot in core_lots) != position.core_quantity:
            raise ValueError("core lots must match the authoritative position summary")
        if sum(lot.remaining_quantity for lot in tactical_lots) != position.tactical_quantity:
            raise ValueError("tactical lots must match the authoritative position summary")
        if sum(lot.sellable_quantity for lot in core_lots) != position.sellable_core_quantity:
            raise ValueError("sellable core lots must match the authoritative position summary")
        if sum(lot.sellable_quantity for lot in tactical_lots) != (
            position.sellable_tactical_quantity
        ):
            raise ValueError("sellable tactical lots must match the authoritative position summary")
        if self.reference_market != self.summary.reference_market:
            raise ValueError("detail and summary reference-market projections must match")
        paths = tuple(item.plan_path for item in self.index_condition_evidence)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("index condition evidence must be unique and sorted by planPath")
        if self.reference_market is None and self.index_condition_evidence:
            raise ValueError("index evidence requires a reference-market projection")
        if self.reference_market is not None and any(
            item.index_code is not self.reference_market.index_code
            or item.mapping_version != self.reference_market.mapping_version
            for item in self.index_condition_evidence
        ):
            raise ValueError("index evidence identity must match the reference market")
        return self


class SymbolPage(ReadModel):
    items: tuple[SymbolSummaryView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=10)]

    @model_validator(mode="after")
    def validate_page(self) -> SymbolPage:
        _validate_page(self.items, self.offset, self.limit, self.total)
        identities = tuple(item.symbol for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("symbol page identities must be unique")
        return self


class SymbolCollectionUnavailableResponse(ReadModel):
    availability: Literal["UNAVAILABLE"]
    observed_at: ShanghaiDatetime
    reason: Literal[
        ProjectionUnavailableReason.EMPTY_DATABASE,
        ProjectionUnavailableReason.NO_ACTIVE_PLANS,
        ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
    ]
    sequence: SafeMonitorSequence


class SymbolDetailUnavailableResponse(ReadModel):
    availability: Literal["UNAVAILABLE"]
    observed_at: ShanghaiDatetime
    reason: Literal[
        ProjectionUnavailableReason.NO_ACTIVE_PLAN,
        ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
    ]
    sequence: SafeMonitorSequence
    symbol: AShareSymbol


SymbolCollectionResponse = SymbolPage | SymbolCollectionUnavailableResponse
SymbolDetailProjectionResponse = SymbolDetailResponse | SymbolDetailUnavailableResponse


def _validate_symbol_projection[
    ReadModelT: ReadModel
](
    value: object,
    model_type: type[ReadModelT],
    *,
    symbol: str | None,
) -> ReadModelT | SymbolCollectionUnavailableResponse | SymbolDetailUnavailableResponse:
    if isinstance(value, ReadModel):
        value = value.model_dump(mode="python", round_trip=True)
    if isinstance(value, dict) and value.get("availability") == "UNAVAILABLE":
        if symbol is None:
            return validate_read_response(value, SymbolCollectionUnavailableResponse)
        response = validate_read_response(value, SymbolDetailUnavailableResponse)
        if response.symbol != symbol:
            raise ValueError("unavailable projection scope does not match the request")
        return response
    return validate_read_response(value, model_type)


class BarView(ReadModel):
    symbol: AShareSymbol
    interval: BarInterval
    bar_end: ShanghaiDatetime
    open_fen: Annotated[int, Field(strict=True, gt=0)]
    high_fen: Annotated[int, Field(strict=True, gt=0)]
    low_fen: Annotated[int, Field(strict=True, gt=0)]
    close_fen: Annotated[int, Field(strict=True, gt=0)]
    volume_shares: Annotated[int, Field(strict=True, ge=0)]
    amount_yuan: Annotated[Decimal, Field(strict=True, ge=Decimal("0"), allow_inf_nan=False)]
    received_at: ShanghaiDatetime
    formula_version: Annotated[str, Field(strict=True, min_length=1, max_length=32)] | None

    @model_validator(mode="after")
    def validate_bar(self) -> BarView:
        if self.low_fen > self.high_fen:
            raise ValueError("bar low cannot exceed high")
        if not self.low_fen <= self.open_fen <= self.high_fen:
            raise ValueError("bar open must be within high and low")
        if not self.low_fen <= self.close_fen <= self.high_fen:
            raise ValueError("bar close must be within high and low")
        if self.received_at < self.bar_end:
            raise ValueError("bar receipt cannot precede bar end")
        if self.interval is BarInterval.ONE_MINUTE and self.formula_version is not None:
            raise ValueError("one-minute bars cannot have an aggregate formula version")
        if self.interval is BarInterval.FIVE_MINUTES and self.formula_version is None:
            raise ValueError("five-minute bars require a formula version")
        return self


class BarPage(ReadModel):
    items: tuple[BarView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    start_at: ShanghaiDatetime
    end_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_page(self) -> BarPage:
        _validate_page(self.items, self.offset, self.limit, self.total)
        _validate_range(self.start_at, self.end_at)
        if any(not self.start_at <= item.bar_end <= self.end_at for item in self.items):
            raise ValueError("bar page item lies outside its inclusive range")
        return self


class SymbolEventView(ReadModel):
    symbol: AShareSymbol
    sequence: SafeMonitorSequence
    event_id: Annotated[
        str,
        Field(
            strict=True,
            min_length=36,
            max_length=36,
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        ),
    ]
    event_type: SymbolEventType
    occurred_at: ShanghaiDatetime
    signal_type: SignalType | None
    result_hash: Sha256Hex | None
    message_text: Annotated[str, Field(strict=True, min_length=1, max_length=2_000)] | None


class SymbolEventPage(ReadModel):
    items: tuple[SymbolEventView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    start_at: ShanghaiDatetime
    end_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_page(self) -> SymbolEventPage:
        _validate_page(self.items, self.offset, self.limit, self.total)
        _validate_range(self.start_at, self.end_at)
        if any(not self.start_at <= item.occurred_at <= self.end_at for item in self.items):
            raise ValueError("event page item lies outside its inclusive range")
        return self


def _validate_page(items: tuple[object, ...], offset: int, limit: int, total: int) -> None:
    if len(items) > limit:
        raise ValueError("page item count cannot exceed its limit")
    if items and offset + len(items) > total:
        raise ValueError("page items cannot exceed total")


def _validate_range(start_at: datetime, end_at: datetime) -> None:
    if start_at > end_at:
        raise ApiError(ApiErrorCode.BAD_REQUEST)


def _ensure_symbol(items: tuple[object, ...], symbol: str) -> None:
    if any(getattr(item, "symbol", None) != symbol for item in items):
        raise ValueError("service response symbol does not match the requested symbol")


def _ensure_requested_page(
    *,
    response_offset: int,
    response_limit: int,
    request_offset: int,
    request_limit: int,
) -> None:
    if response_offset != request_offset or response_limit != request_limit:
        raise ValueError("service response pagination does not match the request")


@router.get(
    "/symbols",
    response_model=SymbolCollectionResponse,
    response_model_exclude_none=True,
)
async def list_symbols(
    service: ReadServiceDependency,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> SymbolCollectionResponse:
    response = _validate_symbol_projection(
        await service.list_symbols(offset=offset, limit=limit),
        SymbolPage,
        symbol=None,
    )
    if isinstance(response, SymbolCollectionUnavailableResponse):
        return response
    _ensure_requested_page(
        response_offset=response.offset,
        response_limit=response.limit,
        request_offset=offset,
        request_limit=limit,
    )
    return response


@router.get(
    "/symbols/{symbol}",
    response_model=SymbolDetailProjectionResponse,
    response_model_exclude_none=True,
)
async def get_symbol(
    symbol: SymbolPath,
    service: ReadServiceDependency,
) -> SymbolDetailProjectionResponse:
    value = await service.get_symbol(symbol=symbol)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = _validate_symbol_projection(value, SymbolDetailResponse, symbol=symbol)
    if isinstance(response, SymbolDetailUnavailableResponse):
        return response
    if response.summary.symbol != symbol:
        raise ValueError("service response symbol does not match the requested symbol")
    return response


@router.get("/symbols/{symbol}/bars", response_model=BarPage)
async def list_symbol_bars(
    symbol: SymbolPath,
    start_at: RangeStartQuery,
    end_at: RangeEndQuery,
    service: ReadServiceDependency,
    interval: Annotated[BarInterval, Query()] = BarInterval.ONE_MINUTE,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> BarPage:
    _validate_range(start_at, end_at)
    value = await service.list_symbol_bars(
        symbol=symbol,
        interval=interval,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
    )
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = validate_read_response(value, BarPage)
    _ensure_symbol(response.items, symbol)
    _ensure_requested_page(
        response_offset=response.offset,
        response_limit=response.limit,
        request_offset=offset,
        request_limit=limit,
    )
    if response.start_at != start_at or response.end_at != end_at:
        raise ValueError("service response range does not match the request")
    if any(item.interval is not interval for item in response.items):
        raise ValueError("service response interval does not match the request")
    return response


@router.get("/symbols/{symbol}/events", response_model=SymbolEventPage)
async def list_symbol_events(
    symbol: SymbolPath,
    start_at: RangeStartQuery,
    end_at: RangeEndQuery,
    service: ReadServiceDependency,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> SymbolEventPage:
    _validate_range(start_at, end_at)
    value = await service.list_symbol_events(
        symbol=symbol,
        start_at=start_at,
        end_at=end_at,
        offset=offset,
        limit=limit,
    )
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = validate_read_response(value, SymbolEventPage)
    _ensure_symbol(response.items, symbol)
    _ensure_requested_page(
        response_offset=response.offset,
        response_limit=response.limit,
        request_offset=offset,
        request_limit=limit,
    )
    if response.start_at != start_at or response.end_at != end_at:
        raise ValueError("service response range does not match the request")
    return response


__all__ = ["router"]
