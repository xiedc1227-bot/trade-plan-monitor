"""Keep a blocked monitor generation read-only except reviewed maintenance."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

_MAINTENANCE_PATH = "/api/v1/system/legacy-plan-invalidation"
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def enforce_blocked_read_only(connection: HTTPConnection) -> None:
    """Reject ordinary mutations while legacy plans await explicit invalidation."""

    if connection.scope["type"] != "http":
        return
    method = connection.scope["method"]
    if method in _READ_METHODS:
        return
    runtime = getattr(connection.app.state, "runtime_lifecycle", None)
    health = getattr(runtime, "health", None)
    if not callable(health):
        return
    snapshot = health()
    if snapshot.status is not RuntimeServiceStatus.BLOCKED:
        return
    if method == "POST" and connection.url.path == _MAINTENANCE_PATH:
        return
    raise ApiError(ApiErrorCode.CONFLICT)
