"""Owned FastAPI lifespan integration for the headless runtime lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Request

from trade_plan_monitor.web.errors import ApiError, ApiErrorCode


class RuntimeLifecycle(Protocol):
    """The T034 lifecycle surface owned by one FastAPI application lifespan."""

    async def start(self) -> object: ...

    async def stop(self) -> None: ...


RuntimeLifecycleFactory = Callable[[], RuntimeLifecycle]


def create_runtime_lifespan(
    runtime_factory: RuntimeLifecycleFactory | None,
) -> Callable[[FastAPI], AsyncIterator[None]]:
    """Create an inert lifespan closure that owns one injected runtime instance."""

    @asynccontextmanager
    async def runtime_lifespan(app: FastAPI) -> AsyncIterator[None]:
        if runtime_factory is None:
            raise RuntimeError("runtime lifecycle factory is not configured")
        runtime = runtime_factory()
        start = getattr(runtime, "start", None)
        stop = getattr(runtime, "stop", None)
        if not callable(start) or not callable(stop):
            raise TypeError("runtime lifecycle must expose start and stop")
        app.state.runtime_lifecycle = runtime
        try:
            app.state.runtime_startup = await start()
            yield
        finally:
            try:
                await stop()
            finally:
                _clear_runtime_state(app)

    return runtime_lifespan


def get_runtime_lifecycle(request: Request) -> RuntimeLifecycle:
    """Resolve only the runtime instance currently owned by the active lifespan."""

    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return runtime


def _clear_runtime_state(app: FastAPI) -> None:
    for name in ("runtime_startup", "runtime_lifecycle"):
        if hasattr(app.state, name):
            delattr(app.state, name)


__all__ = [
    "RuntimeLifecycle",
    "RuntimeLifecycleFactory",
    "create_runtime_lifespan",
    "get_runtime_lifecycle",
]
