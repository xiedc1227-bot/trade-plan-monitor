"""Stable secret-free exception mapping for the local FastAPI boundary."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from http import HTTPStatus
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trade_plan_monitor.web.schemas import (
    ApiErrorCode,
    ErrorDetail,
    ErrorPayload,
    ErrorResponse,
)

_REQUEST_ID_HEADER: Final = "X-Request-ID"
_MAX_VALIDATION_DETAILS: Final = 100
_CODE_PARTS = re.compile(r"[^A-Z0-9]+")

_ERROR_STATUS: Final[Mapping[ApiErrorCode, int]] = {
    ApiErrorCode.BAD_REQUEST: HTTPStatus.BAD_REQUEST,
    ApiErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ApiErrorCode.UNAUTHORIZED: HTTPStatus.UNAUTHORIZED,
    ApiErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ApiErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ApiErrorCode.METHOD_NOT_ALLOWED: HTTPStatus.METHOD_NOT_ALLOWED,
    ApiErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ApiErrorCode.PAYLOAD_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ApiErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ApiErrorCode.SERVICE_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ApiErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}

_ERROR_MESSAGES: Final[Mapping[ApiErrorCode, str]] = {
    ApiErrorCode.BAD_REQUEST: "Bad request",
    ApiErrorCode.VALIDATION_ERROR: "Request validation failed",
    ApiErrorCode.UNAUTHORIZED: "Authentication required",
    ApiErrorCode.FORBIDDEN: "Request forbidden",
    ApiErrorCode.NOT_FOUND: "Resource not found",
    ApiErrorCode.METHOD_NOT_ALLOWED: "Method not allowed",
    ApiErrorCode.CONFLICT: "Request conflicts with current state",
    ApiErrorCode.PAYLOAD_TOO_LARGE: "Request payload too large",
    ApiErrorCode.RATE_LIMITED: "Too many requests",
    ApiErrorCode.SERVICE_UNAVAILABLE: "Service unavailable",
    ApiErrorCode.INTERNAL_ERROR: "Internal server error",
}

_HTTP_ERROR_CODES: Final[Mapping[int, ApiErrorCode]] = {
    status: code
    for code, status in _ERROR_STATUS.items()
    if code is not ApiErrorCode.INTERNAL_ERROR
}


class ApiError(Exception):
    """A public error selected from fixed messages instead of raw exception text."""

    def __init__(
        self,
        code: ApiErrorCode,
        *,
        details: tuple[ErrorDetail, ...] = (),
    ) -> None:
        if not isinstance(code, ApiErrorCode):
            raise TypeError("code must be an ApiErrorCode")
        if type(details) is not tuple or any(
            not isinstance(detail, ErrorDetail) for detail in details
        ):
            raise TypeError("details must be a tuple of ErrorDetail values")
        if len(details) > _MAX_VALIDATION_DETAILS:
            raise ValueError("API error details exceed the public bound")
        self.code = code
        self.details = details
        super().__init__(code.value)


def install_error_boundary(app: FastAPI) -> None:
    """Install request IDs and the one approved API error representation."""

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = _request_id(request)
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return _error_response(
            request,
            code=error.code,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            code=ApiErrorCode.VALIDATION_ERROR,
            details=_validation_details(error),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(error.status_code)
        if code is None:
            code = (
                ApiErrorCode.BAD_REQUEST
                if HTTPStatus.BAD_REQUEST <= error.status_code < HTTPStatus.INTERNAL_SERVER_ERROR
                else ApiErrorCode.INTERNAL_ERROR
            )
        return _error_response(request, code=code, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        return _error_response(request, code=ApiErrorCode.INTERNAL_ERROR)


def _validation_details(error: RequestValidationError) -> tuple[ErrorDetail, ...]:
    details: list[ErrorDetail] = []
    for item in error.errors()[:_MAX_VALIDATION_DETAILS]:
        location = tuple(_safe_location_part(part) for part in item.get("loc", ()))[:16]
        if not location:
            location = ("request",)
        raw_code = item.get("type")
        code = _safe_detail_code(raw_code if isinstance(raw_code, str) else "invalid_value")
        message = "Field required" if code == "MISSING" else "Invalid value"
        details.append(ErrorDetail(location=location, code=code, message=message))
    return tuple(details)


def _safe_location_part(value: object) -> str | int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value:
        return value[:64]
    return "unknown"


def _safe_detail_code(value: str) -> str:
    code = _CODE_PARTS.sub("_", value.upper()).strip("_")[:64]
    if not code:
        return "INVALID_VALUE"
    if not code[0].isalpha():
        return f"ERROR_{code}"[:64]
    return code


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and re.fullmatch(r"[0-9a-f]{32}", request_id):
        return request_id
    request_id = uuid4().hex
    request.state.request_id = request_id
    return request_id


def _error_response(
    request: Request,
    *,
    code: ApiErrorCode,
    details: tuple[ErrorDetail, ...] = (),
    status_code: int | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorResponse(
        error=ErrorPayload(
            code=code,
            message=_ERROR_MESSAGES[code],
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status_code or _ERROR_STATUS[code],
        content=body.model_dump(mode="json", by_alias=True),
        headers={_REQUEST_ID_HEADER: request_id},
    )


__all__ = ["ApiError", "ApiErrorCode", "install_error_boundary"]
