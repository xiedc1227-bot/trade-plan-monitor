"""Side-effect-free FastAPI application factory for the local API boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from typing import Final

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
from trade_plan_monitor.web.schemas import ErrorResponse
from trade_plan_monitor.web.websocket import MonitorWebSocketService
from trade_plan_monitor.web.websocket import router as websocket_router

_PUBLIC_ERROR_STATUSES: Final = (
    HTTPStatus.BAD_REQUEST,
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.METHOD_NOT_ALLOWED,
    HTTPStatus.CONFLICT,
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    HTTPStatus.UNPROCESSABLE_CONTENT,
    HTTPStatus.TOO_MANY_REQUESTS,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.SERVICE_UNAVAILABLE,
)
_PUBLIC_ERROR_RESPONSES: Final = {
    int(status): {"model": ErrorResponse, "description": status.phrase}
    for status in _PUBLIC_ERROR_STATUSES
}
_WEB_ASSET_DIRECTORY: Final = "dist"
_WEB_ASSET_ERROR: Final = "Installed Web assets are unavailable."


class ProductionAssetError(RuntimeError):
    """The installed distribution does not contain a complete Vue build."""

    code = "WEB_ASSETS_UNAVAILABLE"


class _ReadOnlyPackagedLifecycle:
    """Keep the packaged transport available without inventing runtime readiness."""

    async def start(self) -> dict[str, object]:
        return {
            "status": "DEGRADED",
            "readOnly": True,
            "reason": "APPLICATION_SERVICES_UNAVAILABLE",
        }

    async def stop(self) -> None:
        return None


@contextmanager
def installed_web_assets() -> Iterator[Path]:
    """Yield only the Vue build shipped inside the installed Python package."""

    stack = ExitStack()
    resource_failed = False
    directory: Path | None = None
    try:
        build_resource = resources.files("trade_plan_monitor.web").joinpath(_WEB_ASSET_DIRECTORY)
        directory = Path(stack.enter_context(resources.as_file(build_resource)))
    except FileNotFoundError, ModuleNotFoundError, OSError, TypeError, ValueError:
        resource_failed = True

    if resource_failed or directory is None:
        stack.close()
        raise ProductionAssetError(_WEB_ASSET_ERROR)
    assets_directory = directory / "assets"
    distribution_complete = False
    try:
        distribution_complete = (
            directory.is_dir()
            and (directory / "index.html").is_file()
            and assets_directory.is_dir()
            and any(candidate.is_file() for candidate in assets_directory.iterdir())
        )
    except OSError:
        pass
    if not distribution_complete:
        stack.close()
        raise ProductionAssetError(_WEB_ASSET_ERROR)

    try:
        yield directory
    finally:
        stack.close()


@contextmanager
def create_production_app(
    *,
    config_path: Path = Path("config/app.yaml"),
    runtime_factory: RuntimeLifecycleFactory | None = None,
    read_service: MonitorReadService | None = None,
    plan_service: PlanOperationService | None = None,
    ai_service: AIOperationService | None = None,
    position_service: PositionOperationService | None = None,
    alert_service: AlertOperationService | None = None,
    websocket_service: MonitorWebSocketService | None = None,
    bind_host: str = LOOPBACK_HOST,
    bind_port: int = DEFAULT_WEB_PORT,
) -> Iterator[FastAPI]:
    """Compose the installed SPA and local transport for one server lifetime."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    lifecycle_factory = runtime_factory or _ReadOnlyPackagedLifecycle
    with installed_web_assets() as static_directory:
        yield create_app(
            runtime_factory=lifecycle_factory,
            read_service=read_service,
            plan_service=plan_service,
            ai_service=ai_service,
            position_service=position_service,
            alert_service=alert_service,
            websocket_service=websocket_service,
            bind_host=bind_host,
            bind_port=bind_port,
            static_directory=static_directory,
        )


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
        responses=_PUBLIC_ERROR_RESPONSES,
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


__all__ = [
    "ProductionAssetError",
    "create_app",
    "create_production_app",
    "installed_web_assets",
]
