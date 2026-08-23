"""Typed manual-position HTTP adapters over an injected application service."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator

from trade_plan_monitor.domain.plan_models import PositionBucket
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import (
    ApiValue,
    MutationContext,
    MutationContextDependency,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["positions"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_ROWS = 10_000
_MAX_EXPECTED_REVISION = 9_223_372_036_854_775_806

OffsetQuery = Annotated[int, Query(ge=0, le=_MAX_ROWS)]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
SymbolQuery = Annotated[AShareSymbol, Query()]
AsOfTradeDateQuery = Annotated[date, Query(alias="asOfTradeDate")]
NonNegativeRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_EXPECTED_REVISION),
]
PositiveBoardLotQuantity = Annotated[
    int,
    Field(strict=True, gt=0, multiple_of=100),
]
NonNegativeBoardLotQuantity = Annotated[
    int,
    Field(strict=True, ge=0, multiple_of=100),
]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]


class PositionLotView(ApiValue):
    """One manually confirmed lot with an explicit T+1 sellable projection."""

    lot_id: UUID = Field(strict=False)
    symbol: AShareSymbol
    bucket: PositionBucket
    quantity: PositiveBoardLotQuantity
    remaining_quantity: NonNegativeBoardLotQuantity
    sellable_quantity: NonNegativeBoardLotQuantity
    acquired_trade_date: Annotated[date, Field(strict=True)]
    cost_fen: PositiveFen
    related_alert_id: UUID | None = Field(default=None, strict=False)
    closed_at: ShanghaiDatetime | None = None
    revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_lot_state(self) -> Self:
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining quantity cannot exceed original quantity")
        if self.sellable_quantity > self.remaining_quantity:
            raise ValueError("sellable quantity cannot exceed remaining quantity")
        if (self.remaining_quantity == 0) != (self.closed_at is not None):
            raise ValueError("only an exhausted lot can be closed")
        expected_revision = (self.quantity - self.remaining_quantity) // 100
        if self.revision != expected_revision:
            raise ValueError("lot revision must equal its durable reduced board-lot count")
        return self


class PositionLotPage(ApiValue):
    items: tuple[PositionLotView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    symbol: AShareSymbol
    as_of_trade_date: Annotated[date, Field(strict=True)]
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit or (
            self.items and self.offset + len(self.items) > self.total
        ):
            raise ValueError("position page metadata is inconsistent")
        identities = tuple(item.lot_id for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("position lot identities must be unique")
        if any(item.symbol != self.symbol for item in self.items):
            raise ValueError("position page cannot mix symbols")
        if any(
            item.acquired_trade_date >= self.as_of_trade_date and item.sellable_quantity != 0
            for item in self.items
        ):
            raise ValueError("same-day or future lots cannot be sellable")
        return self


class PositionLotCreateCommand(ApiValue):
    symbol: AShareSymbol
    bucket: PositionBucket
    quantity: PositiveBoardLotQuantity
    acquired_trade_date: date = Field(strict=False)
    cost_fen: PositiveFen
    related_alert_id: UUID | None = Field(default=None, strict=False)
    expected_revision: NonNegativeRevision


class PositionLotClosureCommand(ApiValue):
    lot_id: UUID = Field(strict=False)
    quantity: PositiveBoardLotQuantity
    trade_date: date = Field(strict=False)
    expected_revision: NonNegativeRevision


class PositionLotClosureView(ApiValue):
    """Auditable reduction receipt bound to the exact command and lot transition."""

    lot: PositionLotView
    applied_quantity: PositiveBoardLotQuantity
    trade_date: Annotated[date, Field(strict=True)]
    before_remaining_quantity: PositiveBoardLotQuantity
    after_remaining_quantity: NonNegativeBoardLotQuantity

    @model_validator(mode="after")
    def validate_reduction(self) -> Self:
        if self.lot.acquired_trade_date >= self.trade_date:
            raise ValueError("a lot cannot be reduced on or before its acquisition date")
        if self.before_remaining_quantity > self.lot.quantity:
            raise ValueError("pre-reduction quantity cannot exceed original quantity")
        if self.after_remaining_quantity != self.lot.remaining_quantity:
            raise ValueError("receipt and lot remaining quantities must match")
        if self.before_remaining_quantity - self.after_remaining_quantity != (
            self.applied_quantity
        ):
            raise ValueError("receipt quantities must describe one exact reduction")
        return self


class PositionOperationService(Protocol):
    """Application service owning position policy, idempotency, and audit work."""

    async def list_position_lots(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
        offset: int,
        limit: int,
    ) -> PositionLotPage: ...

    async def record_position_lot(
        self,
        *,
        command: PositionLotCreateCommand,
        context: MutationContext,
    ) -> PositionLotView: ...

    async def close_position_lot(
        self,
        *,
        command: PositionLotClosureCommand,
        context: MutationContext,
    ) -> PositionLotClosureView: ...


def get_position_operation_service(request: Request) -> PositionOperationService:
    service = getattr(request.app.state, "position_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(PositionOperationService, service)


PositionServiceDependency = Annotated[
    PositionOperationService,
    Depends(get_position_operation_service),
]


@router.get("/position-lots", response_model=PositionLotPage)
async def list_position_lots(
    service: PositionServiceDependency,
    symbol: SymbolQuery,
    as_of_trade_date: AsOfTradeDateQuery,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> PositionLotPage:
    page = validate_api_response(
        await service.list_position_lots(
            symbol=symbol,
            as_of_trade_date=as_of_trade_date,
            offset=offset,
            limit=limit,
        ),
        PositionLotPage,
    )
    if (
        page.symbol != symbol
        or page.as_of_trade_date != as_of_trade_date
        or page.offset != offset
        or page.limit != limit
    ):
        raise RuntimeError("position service returned a mismatched page")
    return page


@router.post("/position-lots", response_model=PositionLotView)
async def record_position_lot(
    command: PositionLotCreateCommand,
    context: MutationContextDependency,
    service: PositionServiceDependency,
) -> PositionLotView:
    if command.expected_revision != 0:
        raise ApiError(ApiErrorCode.CONFLICT)
    result = validate_api_response(
        await service.record_position_lot(command=command, context=context),
        PositionLotView,
    )
    if (
        result.symbol != command.symbol
        or result.bucket != command.bucket
        or result.quantity != command.quantity
        or result.remaining_quantity != command.quantity
        or result.acquired_trade_date != command.acquired_trade_date
        or result.cost_fen != command.cost_fen
        or result.related_alert_id != command.related_alert_id
        or result.closed_at is not None
    ):
        raise RuntimeError("position service returned a mismatched new lot")
    if result.revision != 0:
        raise RuntimeError("a new position lot must start at revision zero")
    return result


@router.post("/position-lot-closures", response_model=PositionLotClosureView)
async def close_position_lot(
    command: PositionLotClosureCommand,
    context: MutationContextDependency,
    service: PositionServiceDependency,
) -> PositionLotClosureView:
    result = validate_api_response(
        await service.close_position_lot(command=command, context=context),
        PositionLotClosureView,
    )
    if (
        result.lot.lot_id != command.lot_id
        or result.applied_quantity != command.quantity
        or result.trade_date != command.trade_date
    ):
        raise RuntimeError("position service returned a mismatched lot")
    expected_before_revision = (result.lot.quantity - result.before_remaining_quantity) // 100
    expected_after_revision = expected_before_revision + command.quantity // 100
    if (
        command.expected_revision != expected_before_revision
        or result.lot.revision != expected_after_revision
    ):
        raise RuntimeError("position service returned a stale revision")
    return result


__all__ = [
    "PositionLotClosureCommand",
    "PositionLotClosureView",
    "PositionLotCreateCommand",
    "PositionLotPage",
    "PositionLotView",
    "PositionOperationService",
    "router",
]
