"""Owned FastAPI lifespan integration for the headless runtime lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from anyio import to_thread
from fastapi import FastAPI, Request

from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.origin_guard import (
    DEFAULT_WEB_PORT,
    LOOPBACK_HOST,
    local_http_origin,
)


class RuntimeLifecycle(Protocol):
    """The T034 lifecycle surface owned by one FastAPI application lifespan."""

    async def start(self) -> object: ...

    async def stop(self) -> None: ...


RuntimeLifecycleFactory = Callable[[], RuntimeLifecycle]


class BacktestLifecycle(Protocol):
    """One production backtest composition owned by the Web lifespan."""

    @property
    def read_service(self) -> object: ...

    @property
    def operation_service(self) -> object: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


BacktestLifecycleFactory = Callable[[], BacktestLifecycle]


def create_runtime_lifespan(
    runtime_factory: RuntimeLifecycleFactory | None,
    *,
    backtest_lifecycle_factory: BacktestLifecycleFactory | None = None,
    bind_host: str = LOOPBACK_HOST,
    bind_port: int = DEFAULT_WEB_PORT,
) -> Callable[[FastAPI], AsyncIterator[None]]:
    """Own runtime and optional backtest resources in strict reverse order."""

    local_http_origin(bind_host, bind_port)

    @asynccontextmanager
    async def runtime_lifespan(app: FastAPI) -> AsyncIterator[None]:
        if runtime_factory is None:
            raise RuntimeError("runtime lifecycle factory is not configured")
        runtime = runtime_factory()
        start = getattr(runtime, "start", None)
        stop = getattr(runtime, "stop", None)
        if not callable(start) or not callable(stop):
            raise TypeError("runtime lifecycle must expose start and stop")
        backtest: BacktestLifecycle | None = None
        backtest_stop: Callable[[], object] | None = None
        app.state.runtime_lifecycle = runtime
        try:
            app.state.runtime_startup = await start()
            if backtest_lifecycle_factory is not None:
                backtest = await to_thread.run_sync(backtest_lifecycle_factory)
                backtest_start = getattr(backtest, "start", None)
                backtest_stop = getattr(backtest, "stop", None)
                if not callable(backtest_start) or not callable(backtest_stop):
                    raise TypeError("backtest lifecycle must expose start and stop")
                if not hasattr(backtest, "read_service") or not hasattr(
                    backtest,
                    "operation_service",
                ):
                    raise TypeError("backtest lifecycle must expose both services")
                app.state.backtest_lifecycle = backtest
                await backtest_start()
                app.state.backtest_read_service = backtest.read_service
                app.state.backtest_operation_service = backtest.operation_service
            yield
        finally:
            try:
                if backtest_stop is not None:
                    _clear_backtest_service_state(app)
                    await backtest_stop()
            finally:
                try:
                    await stop()
                finally:
                    _clear_backtest_state(app)
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


def _clear_backtest_service_state(app: FastAPI) -> None:
    for name in ("backtest_operation_service", "backtest_read_service"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def _clear_backtest_state(app: FastAPI) -> None:
    if hasattr(app.state, "backtest_lifecycle"):
        delattr(app.state, "backtest_lifecycle")


__all__ = [
    "BacktestLifecycle",
    "BacktestLifecycleFactory",
    "RuntimeLifecycle",
    "RuntimeLifecycleFactory",
    "create_runtime_lifespan",
    "get_runtime_lifecycle",
]
