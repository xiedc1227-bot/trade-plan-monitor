"""Typed local API for explicit manual event-risk confirmation."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator

from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import (
    ApiValue,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["manual-event-risk"])

NonNegativeRevision = Annotated[int, Field(strict=True, ge=0, le=9_223_372_036_854_775_806)]
SymbolQuery = Annotated[AShareSymbol, Query()]


class ManualEventRiskViewStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    CLEAR = "CLEAR"
    RISK_PRESENT = "RISK_PRESENT"


class ManualEventRiskUnknownReason(StrEnum):
    NO_ACTIVE_PLAN = "NO_ACTIVE_PLAN"
    MISSING_CONFIRMATION = "MISSING_CONFIRMATION"
    PLAN_CHANGED = "PLAN_CHANGED"
    EXPIRED = "EXPIRED"


class ManualEventRiskView(ApiValue):
    """The current plan-scoped view; UNKNOWN is never silently converted to CLEAR."""

    symbol: AShareSymbol
    plan_version_id: UUID | None = Field(default=None, strict=False)
    status: ManualEventRiskViewStatus
    reason: ManualEventRiskUnknownReason | None = None
    expires_on: date | None = Field(default=None, strict=False)
    confirmed_at: ShanghaiDatetime | None = None
    revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        unknown = self.status is ManualEventRiskViewStatus.UNKNOWN
        if unknown != (self.reason is not None):
            raise ValueError("unknown manual event risk must have exactly one reason")
        if self.plan_version_id is None:
            if not (
                self.status is ManualEventRiskViewStatus.UNKNOWN
                and self.reason is ManualEventRiskUnknownReason.NO_ACTIVE_PLAN
                and self.expires_on is None
                and self.confirmed_at is None
                and self.revision == 0
            ):
                raise ValueError("missing active plan must be an empty unknown state")
        elif (self.expires_on is None) != (self.confirmed_at is None):
            raise ValueError("manual risk confirmation timestamps and expiry must be paired")
        return self




class ManualEventRiskOperationService(Protocol):
    async def get_manual_event_risk(self, *, symbol: str) -> ManualEventRiskView: ...



def get_manual_event_risk_operation_service(request: Request) -> ManualEventRiskOperationService:
    service = getattr(request.app.state, "manual_event_risk_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(ManualEventRiskOperationService, service)


ManualEventRiskServiceDependency = Annotated[
    ManualEventRiskOperationService,
    Depends(get_manual_event_risk_operation_service),
]


@router.get("/manual-event-risk", response_model=ManualEventRiskView)
async def get_manual_event_risk(
    service: ManualEventRiskServiceDependency,
    symbol: SymbolQuery,
) -> ManualEventRiskView:
    result = validate_api_response(
        await service.get_manual_event_risk(symbol=symbol),
        ManualEventRiskView,
    )
    if result.symbol != symbol:
        raise RuntimeError("manual event risk service returned another symbol")
    return result




__all__ = [
    "ManualEventRiskOperationService",
    "ManualEventRiskUnknownReason",
    "ManualEventRiskView",
    "ManualEventRiskViewStatus",
    "router",
]
