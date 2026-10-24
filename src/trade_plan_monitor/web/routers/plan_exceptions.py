"""Explicit local occurrence decisions; no client market facts or grants accepted."""

from fastapi import APIRouter, Request

from trade_plan_monitor.state.market_exception_service import (
    ExceptionDecisionCommand,
    ExceptionPreview,
    ExceptionPreviewCommand,
    ExceptionReceipt,
    ExceptionRevocationCommand,
)
from trade_plan_monitor.web.routers.plans import PlanServiceDependency
from trade_plan_monitor.web.schemas import ApiValue, MutationContextDependency

router = APIRouter(prefix="/api/v1", tags=["plans"])


class ExceptionPreviewApiCommand(ExceptionPreviewCommand, ApiValue):
    pass


class ExceptionDecisionApiCommand(ExceptionDecisionCommand, ApiValue):
    pass


class ExceptionRevocationApiCommand(ExceptionRevocationCommand, ApiValue):
    pass


class ExceptionPreviewApiView(ExceptionPreview, ApiValue):
    # Domain digest covers snake_case content independently of transport aliases.
    pass


class ExceptionReceiptApiView(ExceptionReceipt, ApiValue):
    pass


@router.post("/plan-exception-previews", response_model=ExceptionPreviewApiView)
async def previews(command: ExceptionPreviewApiCommand, service: PlanServiceDependency,
                   context: MutationContextDependency):
    return await service.mutate_exception(operation="PREVIEW", command=command, context=context)


async def _refresh(request, result):
    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is not None and hasattr(runtime, "reevaluate_daily"):
        await runtime.reevaluate_daily(result.candidate.binding.plan_version_id)


@router.post("/plan-exception-decisions", response_model=ExceptionReceiptApiView)
async def decisions(command: ExceptionDecisionApiCommand, service: PlanServiceDependency,
                    context: MutationContextDependency, request: Request):
    result = await service.mutate_exception(operation="DECISION", command=command, context=context)
    await _refresh(request, result)
    return result


@router.post("/plan-exception-revocations", response_model=ExceptionReceiptApiView)
async def revocations(command: ExceptionRevocationApiCommand, service: PlanServiceDependency,
                      context: MutationContextDependency, request: Request):
    result = await service.mutate_exception(operation="REVOKE", command=command, context=context)
    await _refresh(request, result)
    return result
