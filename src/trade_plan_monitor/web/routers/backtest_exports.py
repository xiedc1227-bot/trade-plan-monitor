"""Thin HTTP adapter for active-v2 backtest result exports."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, Protocol, cast

from anyio import to_thread
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse

from trade_plan_monitor.web.backtest_export import (
    BacktestExportKind,
    CancellationToken,
    PreparedBacktestExport,
    disconnect_aware_chunks,
    prime_export_chunks,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode

router = APIRouter(prefix="/api/v1", tags=["backtest-exports"])

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_EXPORT_MEDIA_TYPES = {
    "SUMMARY_JSON": "application/json",
    "FILLS_CSV": "text/csv; charset=utf-8",
}
_EXPORT_SCHEMA_VERSIONS = {
    "SUMMARY_JSON": "backtest-report-summary-v2",
    "FILLS_CSV": "backtest-simulated-fills-v2",
}
_EXPORT_FILENAME_SUFFIXES = {
    "SUMMARY_JSON": "summary.json",
    "FILLS_CSV": "fills.csv",
}

RunIdPath = Annotated[
    str,
    Path(min_length=64, max_length=64, pattern=_SHA256_PATTERN),
]
ExportKindPath = Annotated[BacktestExportKind, Path()]


class BacktestExportService(Protocol):
    """Application boundary that validates active-v2 export facts before headers."""

    async def prepare_export(
        self,
        *,
        run_id: str,
        export_kind: BacktestExportKind,
        cancelled: Callable[[], bool],
    ) -> PreparedBacktestExport | None: ...


def get_backtest_export_service(request: Request) -> BacktestExportService:
    service = getattr(request.app.state, "backtest_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(BacktestExportService, service)


def require_empty_export_query(request: Request) -> None:
    if request.query_params:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)


BacktestExportServiceDependency = Annotated[
    BacktestExportService,
    Depends(get_backtest_export_service),
]
EmptyExportQueryDependency = Annotated[None, Depends(require_empty_export_query)]


@router.get(
    "/backtest-runs/{run_id}/exports/{export_kind}",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/json": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
            },
        },
    },
)
async def export_backtest_result(
    run_id: RunIdPath,
    export_kind: ExportKindPath,
    _query: EmptyExportQueryDependency,
    service: BacktestExportServiceDependency,
    request: Request,
) -> StreamingResponse:
    cancellation = CancellationToken()
    prepared = await service.prepare_export(
        run_id=run_id,
        export_kind=export_kind,
        cancelled=cancellation.cancelled,
    )
    if prepared is None:
        cancellation.cancel()
        raise ApiError(ApiErrorCode.NOT_FOUND)
    if not _matches_request(prepared, run_id=run_id, export_kind=export_kind):
        await _cancel_and_close(prepared, cancellation)
        raise RuntimeError("backtest export service returned a mismatched export")
    first_chunk = await prime_export_chunks(prepared.chunks, cancellation)
    filename = f"backtest-{run_id}-{_EXPORT_FILENAME_SUFFIXES[export_kind]}"
    return StreamingResponse(
        disconnect_aware_chunks(
            prepared.chunks,
            request,
            cancellation,
            first_chunk=first_chunk,
        ),
        status_code=200,
        headers={
            "Content-Type": _EXPORT_MEDIA_TYPES[export_kind],
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _matches_request(
    prepared: object,
    *,
    run_id: str,
    export_kind: BacktestExportKind,
) -> bool:
    return (
        type(prepared) is PreparedBacktestExport
        and prepared.run_id == run_id
        and prepared.export_kind == export_kind
        and prepared.schema_version == _EXPORT_SCHEMA_VERSIONS[export_kind]
        and isinstance(prepared.chunks, Iterator)
        and iter(prepared.chunks) is prepared.chunks
    )


async def _cancel_and_close(
    prepared: object,
    cancellation: CancellationToken,
) -> None:
    cancellation.cancel()
    chunks = getattr(prepared, "chunks", None)
    close = getattr(chunks, "close", None)
    if callable(close):
        await to_thread.run_sync(close)


__all__ = ["BacktestExportService", "get_backtest_export_service", "router"]
