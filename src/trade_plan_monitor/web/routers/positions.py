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


class PositionInventoryClosureCommand(ApiValue):
    """Debit one explicit ledger source after a real-world sale is recorded."""

    source_type: Literal["LOT", "OPENING_BALANCE"]
    source_id: UUID = Field(strict=False)
    quantity: PositiveBoardLotQuantity
    trade_date: date = Field(strict=False)
    expected_revision: NonNegativeRevision


class PositionInventoryClosureView(ApiValue):
    source_type: Literal["LOT", "OPENING_BALANCE"]
    source_id: UUID = Field(strict=False)
    symbol: AShareSymbol
    applied_quantity: PositiveBoardLotQuantity
    trade_date: Annotated[date, Field(strict=True)]
    before_remaining_quantity: PositiveBoardLotQuantity
    after_remaining_quantity: NonNegativeBoardLotQuantity
    revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_reduction(self) -> Self:
        if self.before_remaining_quantity - self.after_remaining_quantity != (
            self.applied_quantity
        ):
            raise ValueError("receipt quantities must describe one exact reduction")
        if self.revision < self.applied_quantity // 100:
            raise ValueError("closure revision cannot precede its applied quantity")
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


class PositionInventoryConfirmationCommand(ApiValue):
    symbol: AShareSymbol
    as_of_trade_date: date = Field(strict=False)
    expected_revision: NonNegativeRevision
    total_quantity: NonNegativeBoardLotQuantity
    sellable_quantity: NonNegativeBoardLotQuantity
    included_lot_ids: tuple[UUID, ...] = Field(default=(), max_length=200, strict=False)
    complete_registration: Literal[True]


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

    async def close_position_inventory(
        self,
        *,
        command: PositionInventoryClosureCommand,
        context: MutationContext,
    ) -> PositionInventoryClosureView: ...

    async def get_position_inventory(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
    ) -> PositionInventoryView: ...

    async def confirm_position_inventory(
        self,
        *,
        command: PositionInventoryConfirmationCommand,
        context: MutationContext,
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


@router.post(
    "/position-inventory-closures",
    response_model=PositionInventoryClosureView,
)
async def close_position_inventory(
    command: PositionInventoryClosureCommand,
    context: MutationContextDependency,
    service: PositionServiceDependency,
) -> PositionInventoryClosureView:
    result = validate_api_response(
        await service.close_position_inventory(command=command, context=context),
        PositionInventoryClosureView,
    )
    if (
        result.source_type != command.source_type
        or result.source_id != command.source_id
        or result.applied_quantity != command.quantity
        or result.trade_date != command.trade_date
    ):
        raise RuntimeError("position service returned a mismatched inventory closure")
    expected_after_revision = command.expected_revision + command.quantity // 100
    if result.revision != expected_after_revision:
        raise RuntimeError("position service returned a stale inventory closure revision")
    return result


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


@router.post(
    "/position-inventory-confirmations",
    response_model=PositionInventoryView,
)
async def confirm_position_inventory(
    command: PositionInventoryConfirmationCommand,
    context: MutationContextDependency,
    service: PositionServiceDependency,
) -> PositionInventoryView:
    result = validate_api_response(
        await service.confirm_position_inventory(command=command, context=context),
        PositionInventoryView,
    )
    if (
        result.symbol != command.symbol
        or result.as_of_trade_date != command.as_of_trade_date
        or result.inventory_revision != command.expected_revision + 1
        or result.total_quantity != command.total_quantity
        or result.sellable_quantity != command.sellable_quantity
        or result.status != "KNOWN"
    ):
        raise RuntimeError("position service returned mismatched confirmation")
    return result


__all__ = [
    "PositionInventoryClosureCommand",
    "PositionInventoryClosureView",
    "PositionLotClosureCommand",
    "PositionLotClosureView",
    "PositionLotCreateCommand",
    "PositionLotPage",
    "PositionLotView",
    "PositionInventoryConfirmationCommand",
    "PositionInventoryView",
    "PositionOpeningBalanceView",
    "PositionOperationService",
    "router",
]
