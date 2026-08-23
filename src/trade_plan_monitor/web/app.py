"""Side-effect-free FastAPI application factory for the local API boundary."""

from __future__ import annotations

from fastapi import FastAPI

from trade_plan_monitor.web.errors import install_error_boundary
from trade_plan_monitor.web.lifespan import RuntimeLifecycleFactory, create_runtime_lifespan
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


def create_app(
    *,
    runtime_factory: RuntimeLifecycleFactory | None = None,
    read_service: MonitorReadService | None = None,
    plan_service: PlanOperationService | None = None,
    ai_service: AIOperationService | None = None,
    position_service: PositionOperationService | None = None,
    alert_service: AlertOperationService | None = None,
) -> FastAPI:
    """Build the local API adapter without starting runtime or network work."""

    app = FastAPI(
        title="Trade Plan Monitor API",
        version="0.1.0",
        lifespan=create_runtime_lifespan(runtime_factory),
    )
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
    app.include_router(dashboard_router)
    app.include_router(symbols_router)
    app.include_router(health_router)
    app.include_router(plans_router)
    app.include_router(ai_router)
    app.include_router(positions_router)
    app.include_router(alerts_router)
    return app


__all__ = ["create_app"]
