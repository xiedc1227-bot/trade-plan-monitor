"""Side-effect-free FastAPI application factory for the local API boundary."""

from __future__ import annotations

from fastapi import FastAPI

from trade_plan_monitor.web.errors import install_error_boundary
from trade_plan_monitor.web.lifespan import RuntimeLifecycleFactory, create_runtime_lifespan


def create_app(*, runtime_factory: RuntimeLifecycleFactory | None = None) -> FastAPI:
    """Build the local API adapter without starting runtime or network work."""

    app = FastAPI(
        title="Trade Plan Monitor API",
        version="0.1.0",
        lifespan=create_runtime_lifespan(runtime_factory),
    )
    install_error_boundary(app)
    return app


__all__ = ["create_app"]
