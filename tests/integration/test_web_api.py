from __future__ import annotations

import re
import socket
import subprocess
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.lifespan import get_runtime_lifecycle
from trade_plan_monitor.web.schemas import ErrorDetail, ErrorPayload, ErrorResponse

_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class _RequestBody(BaseModel):
    retry_count: Annotated[int, Field(alias="retryCount", strict=True)]


class _FakeLifecycle:
    def __init__(
        self,
        *,
        events: list[str],
        startup_result: object | None = None,
        start_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.startup_result = startup_result or SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
        )
        self.start_error = start_error

    async def start(self) -> object:
        self.events.append("start")
        if self.start_error is not None:
            raise self.start_error
        return self.startup_result

    async def stop(self) -> None:
        self.events.append("stop")


def _factory_for(lifecycle: _FakeLifecycle, events: list[str]) -> Callable[[], _FakeLifecycle]:
    def create() -> _FakeLifecycle:
        events.append("create")
        return lifecycle

    return create


def _assert_error_envelope(response, *, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "requestId"}
    assert error["code"] == code
    assert _REQUEST_ID_PATTERN.fullmatch(error["requestId"])
    assert response.headers["x-request-id"] == error["requestId"]
    return error


def test_app_factory_is_side_effect_free_and_opens_no_socket(monkeypatch) -> None:
    events: list[str] = []
    lifecycle = _FakeLifecycle(events=events)

    def reject_bind(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("application construction must not bind a socket")

    monkeypatch.setattr(socket.socket, "bind", reject_bind)
    app = create_app(runtime_factory=_factory_for(lifecycle, events))

    assert events == []
    assert not hasattr(app.state, "runtime_lifecycle")
    assert not hasattr(app.state, "runtime_startup")


def test_app_import_starts_no_task_database_or_network_work() -> None:
    script = """
import asyncio
import socket
import sqlite3

def forbidden(*args, **kwargs):
    raise AssertionError("import started external work")

asyncio.create_task = forbidden
socket.socket.bind = forbidden
socket.socket.connect = forbidden
sqlite3.connect = forbidden
import trade_plan_monitor.web.app
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_app_lifespan_starts_and_stops_the_injected_runtime() -> None:
    events: list[str] = []
    lifecycle = _FakeLifecycle(events=events)
    app = create_app(runtime_factory=_factory_for(lifecycle, events))

    with TestClient(app):
        assert events == ["create", "start"]
        assert app.state.runtime_lifecycle is lifecycle
        assert app.state.runtime_startup is lifecycle.startup_result

    assert events == ["create", "start", "stop"]


def test_app_lifespan_accepts_degraded_read_only_startup() -> None:
    events: list[str] = []
    degraded = SimpleNamespace(status=RuntimeServiceStatus.DEGRADED, read_only=True)
    lifecycle = _FakeLifecycle(events=events, startup_result=degraded)
    app = create_app(runtime_factory=_factory_for(lifecycle, events))

    with TestClient(app):
        assert app.state.runtime_startup is degraded
        assert events == ["create", "start"]

    assert events == ["create", "start", "stop"]


def test_app_lifespan_stops_an_owned_runtime_when_start_fails() -> None:
    events: list[str] = []
    lifecycle = _FakeLifecycle(
        events=events,
        start_error=RuntimeError("sanitized startup failure"),
    )
    app = create_app(runtime_factory=_factory_for(lifecycle, events))

    with pytest.raises(RuntimeError, match="sanitized startup failure"):
        with TestClient(app):
            pass

    assert events == ["create", "start", "stop"]


def test_app_lifespan_fails_closed_without_runtime_factory() -> None:
    app = create_app()

    with pytest.raises(RuntimeError, match="runtime lifecycle factory is not configured"):
        with TestClient(app):
            pass


def test_app_dependency_resolves_only_the_lifespan_owned_runtime() -> None:
    events: list[str] = []
    lifecycle = _FakeLifecycle(events=events)
    app = create_app(runtime_factory=_factory_for(lifecycle, events))

    @app.get("/api/v1/runtime")
    async def runtime_probe(runtime: object = Depends(get_runtime_lifecycle)) -> dict[str, bool]:
        return {"sameRuntime": runtime is lifecycle}

    without_lifespan = TestClient(app).get("/api/v1/runtime")
    _assert_error_envelope(without_lifespan, status=503, code="SERVICE_UNAVAILABLE")

    with TestClient(app) as client:
        response = client.get("/api/v1/runtime")

    assert response.status_code == 200
    assert response.json() == {"sameRuntime": True}
    assert _REQUEST_ID_PATTERN.fullmatch(response.headers["x-request-id"])
    after_lifespan = TestClient(app).get("/api/v1/runtime")
    _assert_error_envelope(after_lifespan, status=503, code="SERVICE_UNAVAILABLE")


def test_error_unknown_api_route_uses_the_stable_envelope() -> None:
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    response = TestClient(app).get("/api/v1/missing")

    error = _assert_error_envelope(response, status=404, code="NOT_FOUND")
    assert error["message"] == "Resource not found"
    assert error["details"] == []


def test_error_method_not_allowed_uses_the_stable_envelope() -> None:
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/read-only")
    async def read_only() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post("/api/v1/read-only")

    error = _assert_error_envelope(response, status=405, code="METHOD_NOT_ALLOWED")
    assert error["message"] == "Method not allowed"
    assert error["details"] == []


def test_error_http_exception_does_not_echo_raw_detail() -> None:
    secret = "tushare-secret-http-detail"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/explicit-not-found")
    async def explicit_not_found() -> None:
        raise HTTPException(status_code=404, detail=secret)

    response = TestClient(app).get("/api/v1/explicit-not-found")

    _assert_error_envelope(response, status=404, code="NOT_FOUND")
    assert secret not in response.text


def test_error_validation_details_are_typed_and_exclude_secret_input() -> None:
    secret = "ai-secret-validation-input"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.post("/api/v1/validate")
    async def validate_body(body: _RequestBody) -> dict[str, bool]:
        del body
        return {"valid": True}

    response = TestClient(app).post(
        "/api/v1/validate",
        json={"retryCount": secret},
    )

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert error["message"] == "Request validation failed"
    assert error["details"] == [
        {
            "location": ["body", "retryCount"],
            "code": "INT_TYPE",
            "message": "Invalid value",
        }
    ]
    assert secret not in response.text


def test_error_validation_code_is_sanitized_to_the_public_schema() -> None:
    secret = "validation-message-and-context-secret"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/custom-validation")
    async def custom_validation() -> None:
        raise RequestValidationError(
            [
                {
                    "type": "123.bad-code",
                    "loc": ("query", "value"),
                    "msg": secret,
                    "input": secret,
                    "ctx": {"error": RuntimeError(secret)},
                }
            ]
        )

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/custom-validation")

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert error["details"] == [
        {
            "location": ["query", "value"],
            "code": "ERROR_123_BAD_CODE",
            "message": "Invalid value",
        }
    ]
    assert secret not in response.text


def test_error_domain_mapping_uses_fixed_public_message_and_hides_cause() -> None:
    secret = "database-secret-cause"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/conflict")
    async def conflict() -> None:
        try:
            raise RuntimeError(secret)
        except RuntimeError as error:
            raise ApiError(ApiErrorCode.CONFLICT) from error

    response = TestClient(app).get("/api/v1/conflict")

    error = _assert_error_envelope(response, status=409, code="CONFLICT")
    assert error["message"] == "Request conflicts with current state"
    assert error["details"] == []
    assert secret not in response.text


def test_error_unhandled_exception_is_generic_and_hides_cause() -> None:
    secret = "provider-raw-response-secret"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/failure")
    async def failure() -> None:
        raise RuntimeError(secret)

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/failure")

    error = _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")
    assert error["message"] == "Internal server error"
    assert error["details"] == []
    assert secret not in response.text


def test_error_request_ids_are_generated_per_request_and_ignore_input() -> None:
    secret = "user-supplied-request-id-secret"
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))
    client = TestClient(app)

    first = client.get("/api/v1/missing", headers={"X-Request-ID": secret})
    second = client.get("/api/v1/missing")

    first_error = _assert_error_envelope(first, status=404, code="NOT_FOUND")
    second_error = _assert_error_envelope(second, status=404, code="NOT_FOUND")
    assert first_error["requestId"] != second_error["requestId"]
    assert secret not in first.text


def test_error_replaces_invalid_internal_request_id_state() -> None:
    invalid_request_id = "z" * 32
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]))

    @app.get("/api/v1/corrupt-request-id")
    async def corrupt_request_id(request: Request) -> None:
        request.state.request_id = invalid_request_id
        raise ApiError(ApiErrorCode.CONFLICT)

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/corrupt-request-id")

    error = _assert_error_envelope(response, status=409, code="CONFLICT")
    assert error["requestId"] != invalid_request_id


def test_error_schema_is_strict_frozen_and_serializes_camel_case() -> None:
    request_id = "a" * 32
    response = ErrorResponse(
        error=ErrorPayload(
            code=ApiErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            details=(
                ErrorDetail(
                    location=("body", "fieldName"),
                    code="MISSING",
                    message="Field required",
                ),
            ),
            request_id=request_id,
        )
    )

    assert response.model_dump(mode="json", by_alias=True) == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": [
                {
                    "location": ["body", "fieldName"],
                    "code": "MISSING",
                    "message": "Field required",
                }
            ],
            "requestId": request_id,
        }
    }
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate(
            {
                "error": response.error,
                "unexpected": "forbidden",
            }
        )
    with pytest.raises(ValidationError):
        response.error.message = "changed"
    with pytest.raises(ValidationError):
        response.model_copy(update={"error": "invalid"})
    with pytest.raises(ValidationError):
        ErrorDetail(
            location=("x" * 65,),
            code="INVALID_VALUE",
            message="Invalid value",
        )
