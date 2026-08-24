"""Side-effect-free FastAPI application factory for the local API boundary."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, Response

from trade_plan_monitor.web.errors import install_error_boundary
from trade_plan_monitor.web.lifespan import RuntimeLifecycleFactory, create_runtime_lifespan
from trade_plan_monitor.web.origin_guard import (
    DEFAULT_WEB_PORT,
    LOOPBACK_HOST,
    LocalSpaRoute,
    LocalSpaStaticFiles,
    LocalWebSecurityMiddleware,
    local_http_origin,
)
from trade_plan_monitor.web.routers.ai import AIOperationService
from trade_plan_monitor.web.routers.ai import router as ai_router
from trade_plan_monitor.web.routers.alerts import AlertOperationService
from trade_plan_monitor.web.routers.alerts import router as alerts_router
from trade_plan_monitor.web.routers.dashboard import MonitorReadService
from trade_plan_monitor.web.routers.dashboard import router as dashboard_router
from trade_plan_monitor.web.routers.health import router as health_router
from trade_plan_monitor.web.routers.plans import PlanOperationService
from trade_plan_monitor.web.routers.plans import router as plans_router
from trade_plan_monitor.web.routers.positions import PositionOperationService
from trade_plan_monitor.web.routers.positions import router as positions_router
from trade_plan_monitor.web.routers.symbols import router as symbols_router
from trade_plan_monitor.web.websocket import MonitorWebSocketService
from trade_plan_monitor.web.websocket import router as websocket_router


def create_app(
    *,
    runtime_factory: RuntimeLifecycleFactory | None = None,
    read_service: MonitorReadService | None = None,
    plan_service: PlanOperationService | None = None,
    ai_service: AIOperationService | None = None,
    position_service: PositionOperationService | None = None,
    alert_service: AlertOperationService | None = None,
    websocket_service: MonitorWebSocketService | None = None,
    bind_host: str = LOOPBACK_HOST,
    bind_port: int = DEFAULT_WEB_PORT,
    static_directory: Path | None = None,
) -> FastAPI:
    """Build the local API adapter without starting runtime or network work."""

    allowed_origin = local_http_origin(bind_host, bind_port)
    static_files = LocalSpaStaticFiles(static_directory) if static_directory is not None else None
    app = FastAPI(
        title="Trade Plan Monitor API",
        version="0.1.0",
        lifespan=create_runtime_lifespan(
            runtime_factory,
            bind_host=bind_host,
            bind_port=bind_port,
        ),
    )
    app.add_middleware(LocalWebSecurityMiddleware, allowed_origin=allowed_origin)
    install_error_boundary(app)
    if read_service is not None:
        app.state.monitor_read_service = read_service
    if plan_service is not None:
        app.state.plan_operation_service = plan_service
    if ai_service is not None:
        app.state.ai_operation_service = ai_service
    if position_service is not None:
        app.state.position_operation_service = position_service
    if alert_service is not None:
        app.state.alert_operation_service = alert_service
    if websocket_service is not None:
        app.state.monitor_websocket_service = websocket_service
    app.include_router(dashboard_router)
    app.include_router(symbols_router)
    app.include_router(health_router)
    app.include_router(plans_router)
    app.include_router(ai_router)
    app.include_router(positions_router)
    app.include_router(alerts_router)
    app.include_router(websocket_router)
    if static_files is not None:

        async def serve_static(request: Request) -> Response:
            asset_path = request.path_params["asset_path"]
            return await static_files.get_response(asset_path, request.scope)

        app.router.routes.append(
            LocalSpaRoute(
                "/{asset_path:path}",
                serve_static,
                methods=("GET", "HEAD"),
                name="local-spa",
            )
        )
    return app


__all__ = ["create_app"]
