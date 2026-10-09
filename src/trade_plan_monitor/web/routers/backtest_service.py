"""Inert lightweight status; explicit controls are acknowledged before draining."""

from fastapi import APIRouter, Request, Response

from trade_plan_monitor.backtest.service_contract import BacktestCapability, BacktestServiceState
from trade_plan_monitor.backtest.service_lifecycle import BacktestControlConflict
from trade_plan_monitor.web.backtest_service_schemas import (
    BacktestServiceControlReceipt,
    BacktestServiceRecoveryCommand,
    BacktestServiceStopCommand,
    BacktestServiceView,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode, ErrorResponse, MutationContextDependency

_HEADERS = {
    "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
    "Location": {"schema": {"type": "string", "const": "/api/v1/backtest-service"}},
    "Retry-After": {"schema": {"type": "integer", "const": 1}},
}
router = APIRouter(
    prefix="/api/v1/backtest-service",
    tags=["backtest-service"],
    responses={
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


@router.get(
    "",
    response_model=BacktestServiceView,
    responses={200: {"headers": {"Cache-Control": _HEADERS["Cache-Control"]}}},
)
async def get_status(request: Request, response: Response) -> BacktestServiceView:
    response.headers["Cache-Control"] = "no-store"
    manager = getattr(request.app.state, "backtest_lifecycle", None)
    if manager is None:
        return BacktestServiceView(
            epoch=None,
            revision=0,
            generation=0,
            state=BacktestServiceState.DISABLED,
            can_read=False,
            can_submit=False,
            can_cancel=False,
            can_export=False,
            physically_drained=True,
            authorized_job_ids=(),
            reason=None,
        )
    value = manager.snapshot
    readable = value.allows(BacktestCapability.METADATA)
    return BacktestServiceView(
        epoch=manager.epoch,
        revision=manager.control_revision,
        generation=value.generation,
        state=value.state,
        can_read=readable,
        can_submit=value.allows(BacktestCapability.EXECUTION),
        can_cancel=readable,
        can_export=readable,
        physically_drained=value.physically_drained,
        authorized_job_ids=tuple(sorted(value.authorized_job_ids)),
        reason="SERVICE_REPAIR_REQUIRED" if value.state is BacktestServiceState.DEGRADED else None,
    )


def _control(request, response, command, mutation, action, ids=()):
    manager = getattr(request.app.state, "backtest_lifecycle", None)
    if manager is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    try:
        revision = manager.request_control(
            epoch=command.epoch,
            revision=command.expected_revision,
            key=mutation.idempotency_key,
            action=action,
            job_ids=ids,
        )
    except BacktestControlConflict:
        raise ApiError(ApiErrorCode.CONFLICT) from None
    response.headers.update(
        {"Cache-Control": "no-store", "Location": "/api/v1/backtest-service", "Retry-After": "1"}
    )
    return BacktestServiceControlReceipt(epoch=manager.epoch, revision=revision, action=action)


@router.post(
    "/recovery-requests",
    status_code=202,
    response_model=BacktestServiceControlReceipt,
    responses={202: {"headers": _HEADERS}},
)
async def recover(
    command: BacktestServiceRecoveryCommand,
    request: Request,
    response: Response,
    mutation: MutationContextDependency,
) -> BacktestServiceControlReceipt:
    return _control(request, response, command, mutation, command.action, command.resume_job_ids)


@router.post(
    "/stop-requests",
    status_code=202,
    response_model=BacktestServiceControlReceipt,
    responses={202: {"headers": _HEADERS}},
)
async def stop(
    command: BacktestServiceStopCommand,
    request: Request,
    response: Response,
    mutation: MutationContextDependency,
) -> BacktestServiceControlReceipt:
    return _control(request, response, command, mutation, "STOP")
