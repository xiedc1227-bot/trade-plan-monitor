"""Fail-closed local-origin, response, and request-size security boundary."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Match, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOOPBACK_HOST: Final = "127.0.0.1"
DEFAULT_WEB_PORT: Final = 8765
MAX_REQUEST_BODY_BYTES: Final = 4 * 1024 * 1024
WEBSOCKET_POLICY_VIOLATION: Final = 1008

_REQUEST_ID_HEADER: Final = "X-Request-ID"
_CSP: Final = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'; "
    "script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; manifest-src 'self'"
)
SECURITY_HEADERS: Final[Mapping[str, str]] = {
    "Content-Security-Policy": _CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
}
_RESERVED_PREFIXES: Final = ("api/v1", "ws/v1")
_SPA_STOCK_SUFFIXES: Final = frozenset({".BJ", ".SH", ".SZ"})


class _PayloadTooLarge(Exception):
    """Internal control flow raised before an oversized body reaches a route."""


class LocalWebSecurityMiddleware:
    """Enforce the browser-origin boundary and uniform HTTP protections."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origin: str,
        max_request_body_bytes: int = MAX_REQUEST_BODY_BYTES,
    ) -> None:
        if not isinstance(allowed_origin, str) or not allowed_origin:
            raise TypeError("allowed_origin must be a non-empty string")
        if type(max_request_body_bytes) is not int or max_request_body_bytes <= 0:
            raise ValueError("max_request_body_bytes must be a positive integer")
        self._app = app
        self._allowed_origin = allowed_origin.encode("ascii")
        self._max_request_body_bytes = max_request_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "websocket":
            if not self._origin_is_allowed(scope):
                await send(
                    {
                        "type": "websocket.close",
                        "code": WEBSOCKET_POLICY_VIOLATION,
                        "reason": "",
                    }
                )
                return
            await self._app(scope, receive, send)
            return
        if scope_type != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable_message = dict(message)
                mutable_message["headers"] = list(message.get("headers", ()))
                headers = MutableHeaders(scope=mutable_message)
                for name in tuple(headers):
                    if name.lower().startswith("access-control-"):
                        del headers[name]
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                message = mutable_message
            await send(message)

        if not self._origin_is_allowed(scope):
            await _send_error(
                scope,
                send_with_security_headers,
                status=HTTPStatus.FORBIDDEN,
                code="FORBIDDEN",
                message="Request forbidden",
            )
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self._max_request_body_bytes:
            await _send_payload_too_large(scope, send_with_security_headers)
            return

        try:
            body = await _read_bounded_body(receive, self._max_request_body_bytes)
        except _PayloadTooLarge:
            await _send_payload_too_large(scope, send_with_security_headers)
            return
        if body is None:
            return

        body_replayed = False

        async def replay_body() -> Message:
            nonlocal body_replayed
            if not body_replayed:
                body_replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self._app(scope, replay_body, send_with_security_headers)

    def _origin_is_allowed(self, scope: Scope) -> bool:
        origins = _header_values(scope, b"origin")
        return not origins or origins == (self._allowed_origin,)


class LocalSpaStaticFiles(StaticFiles):
    """Serve one explicit Vue build with an extensionless SPA fallback."""

    def __init__(self, directory: Path) -> None:
        resolved_directory = _validated_static_directory(directory)
        super().__init__(directory=resolved_directory, html=False, check_dir=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if _is_reserved_path(scope.get("path", "")):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != HTTPStatus.NOT_FOUND or not _is_spa_route(path, scope):
                raise
        return await super().get_response("index.html", scope)


class LocalSpaRoute(Route):
    """Match static GET/HEAD paths only outside the API and WebSocket namespaces."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and _is_reserved_path(scope.get("path", "")):
            return Match.NONE, {}
        return super().matches(scope)


def local_http_origin(host: str, port: int) -> str:
    """Return the one browser origin permitted by a local listener."""

    validate_loopback_host(host)
    validate_web_port(port)
    if port == 80:
        return f"http://{host}"
    return f"http://{host}:{port}"


def validate_loopback_host(host: str) -> str:
    """Reject aliases and wildcard addresses at every composition boundary."""

    if host != LOOPBACK_HOST:
        raise ValueError("web host must be exactly 127.0.0.1; public exposure is unsupported")
    return host


def validate_web_port(port: int) -> int:
    """Require a concrete TCP user-selected port."""

    if type(port) is not int or not 1 <= port <= 65_535:
        raise ValueError("web port must be an integer from 1 through 65535")
    return port


def _validated_static_directory(directory: Path) -> Path:
    candidate = Path(directory)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError, RuntimeError:
        raise RuntimeError("static build directory does not exist") from None
    if not resolved.is_dir():
        raise RuntimeError("static build path is not a directory")
    index = resolved / "index.html"
    try:
        resolved_index = index.resolve(strict=True)
    except OSError, RuntimeError:
        raise RuntimeError("static build must contain index.html") from None
    if not resolved_index.is_file() or not resolved_index.is_relative_to(resolved):
        raise RuntimeError("static build must contain a local index.html file")
    return resolved


def _header_values(scope: Scope, name: bytes) -> tuple[bytes, ...]:
    return tuple(
        value for header_name, value in scope.get("headers", ()) if header_name.lower() == name
    )


def _content_length(scope: Scope) -> int | None:
    values = _header_values(scope, b"content-length")
    if len(values) != 1:
        return None
    try:
        value = int(values[0].decode("ascii"))
    except UnicodeDecodeError, ValueError:
        return None
    return value if value >= 0 else None


def _request_id(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        request_id = state.get("request_id")
        if isinstance(request_id, str) and len(request_id) == 32:
            return request_id
    return uuid4().hex


async def _send_payload_too_large(scope: Scope, send: Send) -> None:
    await _send_error(
        scope,
        send,
        status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        code="PAYLOAD_TOO_LARGE",
        message="Request payload too large",
    )


async def _send_error(
    scope: Scope,
    send: Send,
    *,
    status: int,
    code: str,
    message: str,
) -> None:
    request_id = _request_id(scope)
    response = JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": [],
                "requestId": request_id,
            }
        },
        headers={_REQUEST_ID_HEADER: request_id},
    )
    await response(scope, receive=_empty_receive, send=send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


async def _read_bounded_body(receive: Receive, maximum: int) -> bytes | None:
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        if message["type"] != "http.request":
            continue
        chunk = message.get("body", b"")
        if len(chunk) > maximum - len(body):
            raise _PayloadTooLarge
        body.extend(chunk)
        if not message.get("more_body", False):
            return bytes(body)


def _is_reserved_path(path: str) -> bool:
    normalized = path.lstrip("/")
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in _RESERVED_PREFIXES
    )


def _is_spa_route(path: str, scope: Scope) -> bool:
    normalized = path.lstrip("/")
    candidate = PurePosixPath(normalized.rstrip("/"))
    if (
        candidate.parts
        and candidate.parts[0] == "assets"
        or candidate.suffix
        and candidate.suffix.upper() not in _SPA_STOCK_SUFFIXES
    ):
        return False
    name = candidate.name
    return not name or "." not in name or _accepts_html(scope)


def _accepts_html(scope: Scope) -> bool:
    accept = Headers(scope=scope).get("accept", "")
    for item in accept.lower().split(","):
        media_type, *parameters = (part.strip() for part in item.split(";"))
        if media_type not in {"text/html", "application/xhtml+xml"}:
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, raw_value = parameter.partition("=")
            if name.strip() == "q" and separator:
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            return True
    return False


__all__ = [
    "DEFAULT_WEB_PORT",
    "LOOPBACK_HOST",
    "LocalSpaStaticFiles",
    "LocalSpaRoute",
    "LocalWebSecurityMiddleware",
    "MAX_REQUEST_BODY_BYTES",
    "SECURITY_HEADERS",
    "local_http_origin",
    "validate_loopback_host",
    "validate_web_port",
]
