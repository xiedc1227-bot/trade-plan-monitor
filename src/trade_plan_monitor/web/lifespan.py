"""Owned FastAPI lifespan integration for the headless runtime lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from anyio import to_thread
from fastapi import FastAPI, Request

from trade_plan_monitor.backtest.service_lifecycle import LazyBacktestLifecycle
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

_MONITOR_SERVICE_BINDINGS = (
    ("read_service", "monitor_read_service"),
    ("position_service", "position_operation_service"),
    ("manual_event_risk_service", "manual_event_risk_operation_service"),
    ("alert_service", "alert_operation_service"),
    ("websocket_service", "monitor_websocket_service"),
    ("market_index_read_service", "market_index_read_service"),
)


class BacktestLifecycle(Protocol):
    """One production backtest composition owned by the Web lifespan."""

    @property
    def read_service(self) -> object: ...

    @property
    def operation_service(self) -> object: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


BacktestLifecycleFactory = Callable[[], BacktestLifecycle]


class AIWebLifecycle(Protocol):
    """One file-configured AI composition owned by the Web lifespan."""

    @property
    def ai_operation_service(self) -> object: ...

    @property
    def plan_extraction_service(self) -> object: ...

    async def start(self) -> object: ...

    async def stop(self) -> None: ...


AIWebLifecycleFactory = Callable[[], AIWebLifecycle]


class PlanWebLifecycle(Protocol):
    """One persistent plan service owned by the Web application lifespan."""

    @property
    def operation_service(self) -> object: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


PlanWebLifecycleFactory = Callable[[], PlanWebLifecycle]


def create_runtime_lifespan(
    runtime_factory: RuntimeLifecycleFactory | None,
    *,
    ai_lifecycle_factory: AIWebLifecycleFactory | None = None,
    plan_lifecycle_factory: PlanWebLifecycleFactory | None = None,
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
        backtest: LazyBacktestLifecycle | None = None
        backtest_stop: Callable[[], object] | None = None
        ai_lifecycle: AIWebLifecycle | None = None
        ai_stop: Callable[[], object] | None = None
        plan_lifecycle: PlanWebLifecycle | None = None
        plan_stop: Callable[[], object] | None = None
        monitor_service_state: tuple[str, ...] = ()
        app.state.runtime_lifecycle = runtime
        try:
            if getattr(app.state, "monitor_contract_version", 1) == 2:
                reader = getattr(app.state, "monitor_read_service", None)
                if reader is None:
                    reader = getattr(runtime, "read_service", None)
                if getattr(reader, "monitor_contract_version", None) != 2:
                    raise TypeError("monitor contract 2 requires an authoritative v2 read service")
            app.state.runtime_startup = await start()
            monitor_service_state = _bind_monitor_service_state(app, runtime)
            if ai_lifecycle_factory is not None:
                ai_lifecycle = await to_thread.run_sync(ai_lifecycle_factory)
                ai_start = getattr(ai_lifecycle, "start", None)
                ai_stop = getattr(ai_lifecycle, "stop", None)
                if not callable(ai_start) or not callable(ai_stop):
                    raise TypeError("AI Web lifecycle must expose start and stop")
                if not hasattr(ai_lifecycle, "ai_operation_service") or not hasattr(
                    ai_lifecycle,
                    "plan_extraction_service",
                ):
                    raise TypeError("AI Web lifecycle must expose both services")
                app.state.ai_web_lifecycle = ai_lifecycle
                app.state.ai_startup = await ai_start()
                app.state.ai_operation_service = ai_lifecycle.ai_operation_service
                app.state.plan_extraction_service = ai_lifecycle.plan_extraction_service
            if plan_lifecycle_factory is not None:
                plan_lifecycle = await to_thread.run_sync(plan_lifecycle_factory)
                plan_start = getattr(plan_lifecycle, "start", None)
                plan_stop = getattr(plan_lifecycle, "stop", None)
                if not callable(plan_start) or not callable(plan_stop):
                    raise TypeError("plan Web lifecycle must expose start and stop")
                if not hasattr(plan_lifecycle, "operation_service"):
                    raise TypeError("plan Web lifecycle must expose its operation service")
                app.state.plan_web_lifecycle = plan_lifecycle
                await plan_start()
                app.state.plan_operation_service = plan_lifecycle.operation_service
            if backtest_lifecycle_factory is not None:
                backtest = LazyBacktestLifecycle(backtest_lifecycle_factory)
                backtest_stop = backtest.stop
                app.state.backtest_lifecycle = backtest
            yield
        finally:
            try:
                if backtest_stop is not None:
                    _clear_backtest_service_state(app)
                    try:
                        await backtest_stop()
                    except Exception:
                        # A backtest cleanup defect must not prevent monitor cleanup.
                        app.state.backtest_cleanup_failed = True
            finally:
                try:
                    if plan_stop is not None:
                        _clear_plan_service_state(app)
                        await plan_stop()
                finally:
                    try:
                        if ai_stop is not None:
                            _clear_ai_service_state(app)
                            await ai_stop()
                    finally:
                        try:
                            _clear_monitor_service_state(app, monitor_service_state)
                            await stop()
                        finally:
                            _clear_backtest_state(app)
                            _clear_plan_state(app)
                            _clear_ai_state(app)
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


def _bind_monitor_service_state(app: FastAPI, runtime: RuntimeLifecycle) -> tuple[str, ...]:
    owned: list[str] = []
    try:
        for source_name, state_name in _MONITOR_SERVICE_BINDINGS:
            service = getattr(runtime, source_name, None)
            if service is None or hasattr(app.state, state_name):
                continue
            setattr(app.state, state_name, service)
            owned.append(state_name)
    except BaseException:
        _clear_monitor_service_state(app, tuple(owned))
        raise
    return tuple(owned)


def _clear_monitor_service_state(app: FastAPI, names: tuple[str, ...]) -> None:
    for name in names:
        if hasattr(app.state, name):
            delattr(app.state, name)


def _clear_backtest_service_state(app: FastAPI) -> None:
    for name in ("backtest_operation_service", "backtest_read_service"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def _clear_backtest_state(app: FastAPI) -> None:
    if hasattr(app.state, "backtest_lifecycle"):
        delattr(app.state, "backtest_lifecycle")


def _clear_plan_service_state(app: FastAPI) -> None:
    if hasattr(app.state, "plan_operation_service"):
        delattr(app.state, "plan_operation_service")


def _clear_plan_state(app: FastAPI) -> None:
    if hasattr(app.state, "plan_web_lifecycle"):
        delattr(app.state, "plan_web_lifecycle")


def _clear_ai_service_state(app: FastAPI) -> None:
    for name in ("ai_operation_service", "plan_extraction_service"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def _clear_ai_state(app: FastAPI) -> None:
    for name in ("ai_startup", "ai_web_lifecycle"):
        if hasattr(app.state, name):
            delattr(app.state, name)


__all__ = [
    "AIWebLifecycle",
    "AIWebLifecycleFactory",
    "BacktestLifecycle",
    "BacktestLifecycleFactory",
    "PlanWebLifecycle",
    "PlanWebLifecycleFactory",
    "RuntimeLifecycle",
    "RuntimeLifecycleFactory",
    "create_runtime_lifespan",
    "get_runtime_lifecycle",
]
