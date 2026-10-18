"""Side-effect-free FastAPI application factory for the local API boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.web.blocked_mutations import enforce_blocked_read_only
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode, install_error_boundary
from trade_plan_monitor.web.lifespan import (
    AIWebLifecycleFactory,
    BacktestLifecycleFactory,
    PlanWebLifecycleFactory,
    RuntimeLifecycleFactory,
    create_runtime_lifespan,
)
from trade_plan_monitor.web.monitor_composition import create_monitor_composition_factory
from trade_plan_monitor.web.monitor_contract import (
    MonitorContractGuard,
    MonitorContractResponseHeaders,
    install_monitor_contract_schema,
    validate_monitor_assets,
)
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
from trade_plan_monitor.web.routers.backtest_data import router as backtest_data_router
from trade_plan_monitor.web.routers.backtest_exports import router as backtest_exports_router
from trade_plan_monitor.web.routers.backtest_jobs import router as backtest_jobs_router
from trade_plan_monitor.web.routers.backtest_preparations import require_preparation_request
from trade_plan_monitor.web.routers.backtest_preparations import (
    router as backtest_preparations_router,
)
from trade_plan_monitor.web.routers.backtest_results import router as backtest_results_router
from trade_plan_monitor.web.routers.backtest_runs import router as backtest_runs_router
from trade_plan_monitor.web.routers.backtest_service import router as backtest_service_router
from trade_plan_monitor.web.routers.daily_plans import router as daily_plans_router
from trade_plan_monitor.web.routers.dashboard import MonitorReadService
from trade_plan_monitor.web.routers.dashboard import router as dashboard_router
from trade_plan_monitor.web.routers.health import router as health_router
from trade_plan_monitor.web.routers.manual_event_risk import ManualEventRiskOperationService
from trade_plan_monitor.web.routers.manual_event_risk import router as manual_event_risk_router
from trade_plan_monitor.web.routers.market_indexes import MarketIndexReadService
from trade_plan_monitor.web.routers.market_indexes import router as market_indexes_router
from trade_plan_monitor.web.routers.plan_library import router as plan_library_router
from trade_plan_monitor.web.routers.plans import PlanOperationService
from trade_plan_monitor.web.routers.plans import router as plans_router
from trade_plan_monitor.web.routers.positions import PositionOperationService
from trade_plan_monitor.web.routers.positions import router as positions_router
from trade_plan_monitor.web.routers.runtime_status import router as runtime_status_router
from trade_plan_monitor.web.routers.symbols import router as symbols_router
from trade_plan_monitor.web.routers.system import router as system_router
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


async def _prepare_backtest_request(request: Request) -> None:
    """Actual backtest data use prepares only the capability that it needs."""

    if not request.url.path.startswith("/api/v1/backtest-"):
        return
    preparation_request = request.url.path.startswith((
        "/api/v1/backtest-preparations", "/api/v1/backtest-plan-library",
    ))
    if request.url.path.startswith("/api/v1/backtest-preparations"):
        require_preparation_request(request)
    manager = getattr(request.app.state, "backtest_lifecycle", None)
    if manager is None:
        return
    execution = request.method == "POST" and request.url.path in {
        "/api/v1/backtest-data-syncs",
        "/api/v1/backtest-dataset-verifications",
        "/api/v1/backtest-runs",
    }
    if request.method == "POST" or (preparation_request and request.method == "PUT"):
        # FastAPI resolves router dependencies before validating the endpoint body.
        # Reuse its mounted command model so rejected input cannot acquire resources.
        body_field = getattr(request.scope.get("route"), "body_field", None)
        if body_field is not None:
            _value, errors = body_field.validate(await request.json(), loc=("body",))
            if errors:
                raise RequestValidationError(errors) from None
        from trade_plan_monitor.web.schemas import MutationContext

        try:
            MutationContext(
                idempotency_key=request.headers.get("Idempotency-Key"),
                request_id=request.state.request_id,
            )
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from None
    try:
        composition = await manager.ensure(execution=execution)
    except BacktestServiceUnavailable:
        snapshot = manager.snapshot
        from trade_plan_monitor.backtest.service_contract import BacktestServiceState

        retry_after = (
            1 if snapshot.outstanding_work and snapshot.state is not BacktestServiceState.DEGRADED
            else None
        )
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=retry_after) from None
    request.app.state.backtest_read_service = composition.read_service
    request.app.state.backtest_operation_service = composition.operation_service
    if preparation_request:
        try:
            request.state.preparation_service = await composition.ensure_preparations()
        except BacktestServiceUnavailable:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE, retry_after_seconds=1) from None


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
    database_path: Path = Path("data/monitor.sqlite3"),
    runtime_factory: RuntimeLifecycleFactory | None = None,
    read_service: MonitorReadService | None = None,
    plan_service: PlanOperationService | None = None,
    ai_service: AIOperationService | None = None,
    ai_lifecycle_factory: AIWebLifecycleFactory | None = None,
    position_service: PositionOperationService | None = None,
    manual_event_risk_service: ManualEventRiskOperationService | None = None,
    alert_service: AlertOperationService | None = None,
    websocket_service: MonitorWebSocketService | None = None,
    market_index_read_service: MarketIndexReadService | None = None,
    backtest_lifecycle_factory: BacktestLifecycleFactory | None = None,
    bind_host: str = LOOPBACK_HOST,
    bind_port: int = DEFAULT_WEB_PORT,
    monitor_contract_version: int = 2,
) -> Iterator[FastAPI]:
    """Compose the installed SPA and local transport for one server lifetime."""

    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a Path")
    if ai_service is not None and ai_lifecycle_factory is not None:
        raise ValueError("AI service and lifecycle factory are mutually exclusive")
    lifecycle_factory = runtime_factory
    has_explicit_monitor_service = any(
        service is not None
        for service in (
            read_service,
            position_service,
            manual_event_risk_service,
            alert_service,
            websocket_service,
            market_index_read_service,
        )
    )
    if lifecycle_factory is None and not has_explicit_monitor_service:
        lifecycle_factory = create_monitor_composition_factory(
            config_path=config_path,
            database_path=database_path,
            **({"monitor_contract_version": 2} if monitor_contract_version == 2 else {}),
        )
    plan_lifecycle_factory: PlanWebLifecycleFactory | None = None
    plan_snapshot_reader = plan_service
    persistent_plan_lifecycle = None
    if plan_service is None:
        from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

        persistent_plan_lifecycle = PersistentPlanWebLifecycle(database_path=database_path)

        def create_persistent_plan_lifecycle() -> PersistentPlanWebLifecycle:
            return persistent_plan_lifecycle

        plan_lifecycle_factory = create_persistent_plan_lifecycle
        plan_snapshot_reader = persistent_plan_lifecycle
    if ai_service is None and ai_lifecycle_factory is None:
        from trade_plan_monitor.web.ai_diagnostics import diagnostic_path_for_database
        from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle

        def create_configured_ai_lifecycle() -> ConfiguredAIWebLifecycle:
            return ConfiguredAIWebLifecycle(
                config_path=config_path,
                review_store=persistent_plan_lifecycle,
                diagnostic_path=diagnostic_path_for_database(database_path),
            )

        ai_lifecycle_factory = create_configured_ai_lifecycle
    if backtest_lifecycle_factory is None:
        from trade_plan_monitor.backtest.composition import (
            create_backtest_composition_factory,
        )

        backtest_lifecycle_factory = create_backtest_composition_factory(
            config_path=config_path,
            plan_snapshot_reader=plan_snapshot_reader,
        )
    with installed_web_assets() as static_directory:
        yield create_app(
            runtime_factory=lifecycle_factory,
            backtest_lifecycle_factory=backtest_lifecycle_factory,
            read_service=read_service,
            plan_service=plan_service,
            plan_lifecycle_factory=plan_lifecycle_factory,
            ai_service=ai_service,
            ai_lifecycle_factory=ai_lifecycle_factory,
            position_service=position_service,
            manual_event_risk_service=manual_event_risk_service,
            alert_service=alert_service,
            websocket_service=websocket_service,
            market_index_read_service=market_index_read_service,
            bind_host=bind_host,
            bind_port=bind_port,
            static_directory=static_directory,
            monitor_contract_version=monitor_contract_version,
        )


def create_app(
    *,
    runtime_factory: RuntimeLifecycleFactory | None = None,
    read_service: MonitorReadService | None = None,
    plan_service: PlanOperationService | None = None,
    plan_lifecycle_factory: PlanWebLifecycleFactory | None = None,
    ai_service: AIOperationService | None = None,
    ai_lifecycle_factory: AIWebLifecycleFactory | None = None,
    position_service: PositionOperationService | None = None,
    manual_event_risk_service: ManualEventRiskOperationService | None = None,
    alert_service: AlertOperationService | None = None,
    websocket_service: MonitorWebSocketService | None = None,
    market_index_read_service: MarketIndexReadService | None = None,
    backtest_read_service: object | None = None,
    backtest_operation_service: object | None = None,
    backtest_lifecycle_factory: BacktestLifecycleFactory | None = None,
    bind_host: str = LOOPBACK_HOST,
    bind_port: int = DEFAULT_WEB_PORT,
    static_directory: Path | None = None,
    monitor_contract_version: int = 1,
) -> FastAPI:
    """Build the local API adapter without starting runtime or network work."""

    if type(monitor_contract_version) is not int or monitor_contract_version not in (1, 2):
        raise ValueError("unsupported monitor contract version")
    if monitor_contract_version == 2 and (
        getattr(read_service, "monitor_contract_version", None) != 2
        and not (
            read_service is None and getattr(runtime_factory, "monitor_contract_version", None) == 2
        )
    ):
        raise ValueError("monitor contract 2 requires an authoritative v2 read service")
    validate_monitor_assets(static_directory, monitor_contract_version)
    if backtest_lifecycle_factory is not None and (
        backtest_read_service is not None or backtest_operation_service is not None
    ):
        raise ValueError("backtest services and lifecycle factory are mutually exclusive")
    if ai_lifecycle_factory is not None and ai_service is not None:
        raise ValueError("AI service and lifecycle factory are mutually exclusive")
    if plan_lifecycle_factory is not None and plan_service is not None:
        raise ValueError("plan service and lifecycle factory are mutually exclusive")

    allowed_origin = local_http_origin(bind_host, bind_port)
    static_files = LocalSpaStaticFiles(static_directory) if static_directory is not None else None
    app = FastAPI(
        title="Trade Plan Monitor API",
        version="0.1.0",
        dependencies=[Depends(enforce_blocked_read_only)],
        responses=_PUBLIC_ERROR_RESPONSES,
        lifespan=create_runtime_lifespan(
            runtime_factory,
            ai_lifecycle_factory=ai_lifecycle_factory,
            plan_lifecycle_factory=plan_lifecycle_factory,
            backtest_lifecycle_factory=backtest_lifecycle_factory,
            bind_host=bind_host,
            bind_port=bind_port,
        ),
    )
    app.state.monitor_contract_version = monitor_contract_version
    if monitor_contract_version == 2:
        app.add_middleware(MonitorContractGuard)
    app.add_middleware(LocalWebSecurityMiddleware, allowed_origin=allowed_origin)
    install_error_boundary(app)
    if monitor_contract_version == 2:
        app.add_middleware(MonitorContractResponseHeaders)
    if read_service is not None:
        app.state.monitor_read_service = read_service
    if plan_service is not None:
        app.state.plan_operation_service = plan_service
    if ai_service is not None:
        app.state.ai_operation_service = ai_service
    if position_service is not None:
        app.state.position_operation_service = position_service
    if manual_event_risk_service is not None:
        app.state.manual_event_risk_operation_service = manual_event_risk_service
    if alert_service is not None:
        app.state.alert_operation_service = alert_service
    if websocket_service is not None:
        app.state.monitor_websocket_service = websocket_service
    if market_index_read_service is not None:
        app.state.market_index_read_service = market_index_read_service
    if backtest_read_service is not None:
        app.state.backtest_read_service = backtest_read_service
    if backtest_operation_service is not None:
        app.state.backtest_operation_service = backtest_operation_service
    if monitor_contract_version == 1:
        app.include_router(dashboard_router)
        app.include_router(symbols_router)
        app.include_router(health_router)
        app.include_router(plans_router)
    else:
        app.include_router(runtime_status_router)
        # FastAPI clones included routes; never mutate the shared v1 routers.
        replaced = {"/api/v1/symbols", "/api/v1/symbols/{symbol}"}
        retained = APIRouter()
        retained.routes.extend(
            route for route in symbols_router.routes if route.path not in replaced
        )
        app.include_router(retained)
        app.include_router(plans_router)
    app.include_router(daily_plans_router)
    app.include_router(system_router)
    app.include_router(ai_router)
    app.include_router(positions_router)
    app.include_router(manual_event_risk_router)
    app.include_router(alerts_router)
    app.include_router(websocket_router)
    app.include_router(market_indexes_router)
    app.include_router(backtest_service_router)
    for backtest_router in (
        backtest_data_router, backtest_jobs_router, backtest_runs_router,
        backtest_results_router, backtest_exports_router, backtest_preparations_router,
        plan_library_router,
    ):
        app.include_router(backtest_router, dependencies=[Depends(_prepare_backtest_request)])
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
    if monitor_contract_version == 2:
        install_monitor_contract_schema(app)
    return app


__all__ = [
    "ProductionAssetError",
    "create_app",
    "create_production_app",
    "installed_web_assets",
]
