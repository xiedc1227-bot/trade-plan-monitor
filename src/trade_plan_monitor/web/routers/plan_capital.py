"""Local capital review resources and explicit simulation opening commands."""

from fastapi import APIRouter

from trade_plan_monitor.web.p3_schemas import (
    CapitalBookView,
    CapitalOpeningApiCommand,
    CapitalOpeningReceipt,
    CapitalPreviewCommand,
    CapitalPreviewView,
)
from trade_plan_monitor.web.routers.plans import PlanServiceDependency, PlanSymbolPath
from trade_plan_monitor.web.schemas import MutationContextDependency

router = APIRouter(prefix="/api/v1", tags=["plans"])


@router.get("/simulation-capital-books/{symbol}", response_model=CapitalBookView)
async def book(symbol: PlanSymbolPath, service: PlanServiceDependency):
    return await service.read_capital_book(symbol=symbol)


@router.post("/simulation-capital-openings", response_model=CapitalOpeningReceipt)
async def opening(command: CapitalOpeningApiCommand, service: PlanServiceDependency,
                  context: MutationContextDependency):
    return await service.open_capital(command=command, context=context)


@router.post("/plan-capital-previews", response_model=CapitalPreviewView)
async def preview(command: CapitalPreviewCommand, service: PlanServiceDependency,
                  context: MutationContextDependency):
    return await service.preview_capital(command=command)
