"""Opt-in monitor protocol negotiation, independent of business authorization."""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from trade_plan_monitor.web.errors import ApiErrorCode, _error_response
from trade_plan_monitor.web.schemas import ErrorDetail

VERSION_HEADER = "X-Monitor-Contract-Version"
_READ_PATH = re.compile(
    r"^/api/v1/(?:health(?:/symbols/[^/]+)?|dashboard|symbols(?:/[^/]+)?)$"
)
_WRITE_PATHS = frozenset(
    f"/api/v1/{name}"
    for name in (
        "plan-activations",
        "plan-deactivations",
        "alert-acknowledgements",
        "diagnostic-evaluations",
        "system/legacy-plan-invalidation",
    )
)


def is_guarded_monitor_request(scope: Scope) -> bool:
    if scope["type"] != "http":
        return False
    return (scope["method"] == "GET" and _READ_PATH.fullmatch(scope["path"]) is not None) or (
        scope["method"] == "POST" and scope["path"] in _WRITE_PATHS
    )


def install_monitor_contract_schema(app) -> None:
    """Describe middleware negotiation without moving it after request parsing."""
    original = app.openapi

    def openapi():
        document = original()
        for path, operations in document["paths"].items():
            for method, operation in operations.items():
                if not is_guarded_monitor_request(
                    {"type": "http", "method": method.upper(), "path": path},
                ):
                    continue
                header = {
                    "name": VERSION_HEADER,
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "const": "2"},
                }
                parameters = operation.setdefault("parameters", [])
                if header not in parameters:
                    parameters.append(header)
                for response in operation["responses"].values():
                    response.setdefault("headers", {}).update(
                        {
                            VERSION_HEADER: {"schema": {"type": "string", "const": "2"}},
                            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
                        }
                    )
        return document

    app.openapi = openapi


class MonitorContractGuard:
    """Run inside Origin security, before body parsing and service dependencies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if is_guarded_monitor_request(scope):
            values = [
                value
                for name, value in scope["headers"]
                if name.lower() == b"x-monitor-contract-version"
            ]
            if values != [b"2"]:
                response = _error_response(
                    Request(scope),
                    code=ApiErrorCode.CONFLICT,
                    details=(
                        ErrorDetail(
                            location=("header", VERSION_HEADER),
                            code="MONITOR_CONTRACT_MISMATCH",
                            message="Reload the application to use monitor contract 2",
                        ),
                    ),
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class MonitorContractResponseHeaders:
    """Stamp guarded responses including security and validation rejections."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if is_guarded_monitor_request(scope):
            # ServerErrorMiddleware handles unexpected exceptions outside this wrapper.
            scope.setdefault("state", {})["_monitor_contract_response_version"] = 2

        async def send_versioned(message: Message) -> None:
            if message["type"] == "http.response.start" and is_guarded_monitor_request(scope):
                headers = MutableHeaders(scope=message)
                headers[VERSION_HEADER] = "2"
                headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_versioned)


def validate_monitor_assets(directory: Path | None, version: int) -> None:
    if directory is None:
        return
    manifest = directory / "monitor-contract.json"
    if version == 1 and not manifest.exists():
        # Existing installed v1 assets predate the manifest; never accept marked v2 assets.
        return
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raise ValueError("monitor assets require a valid protocol manifest") from None
    if (
        type(value) is not dict
        or set(value) != {"monitorContractVersion"}
        or type(value["monitorContractVersion"]) is not int
        or value["monitorContractVersion"] != version
    ):
        raise ValueError("monitor assets do not match the selected protocol")
