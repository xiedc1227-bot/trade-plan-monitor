"""Typed manual-position HTTP adapters over an injected application service."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator

from trade_plan_monitor.domain.plan_models import PositionBucket
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import (
    ApiValue,
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












class PositionOpeningBalanceView(ApiValue):
    """Ordinary settled inventory with no fabricated cost or acquisition date."""

    opening_balance_id: UUID = Field(strict=False)
    symbol: AShareSymbol
    original_quantity: PositiveBoardLotQuantity
    remaining_quantity: NonNegativeBoardLotQuantity
    sellable_from: Annotated[date, Field(strict=True)]
    revision: NonNegativeRevision


class PositionInventoryView(ApiValue):
    """Three-state-safe authoritative inventory projection."""

    symbol: AShareSymbol
    status: Literal["KNOWN", "UNKNOWN"]
    as_of_trade_date: Annotated[date, Field(strict=True)]
    cutoff: ShanghaiDatetime
    inventory_revision: NonNegativeRevision
    total_quantity: NonNegativeBoardLotQuantity | None
    sellable_quantity: NonNegativeBoardLotQuantity | None
    confirmation_id: UUID | None = Field(default=None, strict=False)
    confirmed_at: ShanghaiDatetime | None
    included_lot_ids: tuple[UUID, ...] = Field(default=(), max_length=200, strict=False)
    opening_balances: tuple[PositionOpeningBalanceView, ...] = Field(default=(), max_length=200)
    missing_reasons: tuple[Literal["POSITION_UNKNOWN", "SELLABLE_QUANTITY_UNKNOWN"], ...] = Field(
        default=(),
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_inventory_state(self) -> Self:
        if self.status == "KNOWN":
            if self.total_quantity is None:
                raise ValueError("known inventory requires total quantity")
            if self.sellable_quantity is None:
                if self.missing_reasons != ("SELLABLE_QUANTITY_UNKNOWN",):
                    raise ValueError("unknown sellability requires its missing reason")
            elif self.sellable_quantity > self.total_quantity or self.missing_reasons:
                raise ValueError("known inventory quantities are inconsistent")
        elif self.total_quantity is not None or self.sellable_quantity is not None:
            raise ValueError("unknown inventory cannot guess numeric quantities")
        elif self.missing_reasons != ("POSITION_UNKNOWN",):
            raise ValueError("unknown inventory requires its missing reason")
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




    async def get_position_inventory(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
    ) -> PositionInventoryView: ...



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








@router.get("/position-inventory", response_model=PositionInventoryView)
async def get_position_inventory(
    service: PositionServiceDependency,
    symbol: SymbolQuery,
    as_of_trade_date: AsOfTradeDateQuery,
) -> PositionInventoryView:
    result = validate_api_response(
        await service.get_position_inventory(
            symbol=symbol,
            as_of_trade_date=as_of_trade_date,
        ),
        PositionInventoryView,
    )
    if result.symbol != symbol or result.as_of_trade_date != as_of_trade_date:
        raise RuntimeError("position service returned mismatched inventory")
    return result




__all__ = [
    "PositionLotPage",
    "PositionLotView",
    "PositionInventoryView",
    "PositionOpeningBalanceView",
    "PositionOperationService",
    "router",
]
