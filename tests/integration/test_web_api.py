from __future__ import annotations

import re
import socket
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated
from zoneinfo import ZoneInfo

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
_SHANGHAI = ZoneInfo("Asia/Shanghai")


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


def _decision_payload(
    *,
    symbol: str = "003043.SZ",
    health_status: str = "LIVE",
) -> dict[str, object]:
    evaluated_at = datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI)
    market_data_at = evaluated_at - timedelta(seconds=60)
    fresh = health_status == "LIVE"
    complete = health_status not in {"GAPPED", "BLOCKED"}
    return {
        "symbol": symbol,
        "resultHash": "a" * 64,
        "planId": "sample-plan",
        "planVersion": 3,
        "planHash": "b" * 64,
        "evaluatedAt": evaluated_at,
        "marketDataAt": market_data_at,
        "dataAgeSeconds": 60,
        "priceFen": 1_234,
        "zone": "LOW_BUY",
        "signalType": "BUY_CORE_READY",
        "position": {
            "coreQuantity": 1_000,
            "tacticalQuantity": 0,
            "totalQuantity": 1_000,
            "sellableCoreQuantity": 1_000,
            "sellableTacticalQuantity": 0,
        },
        "episodeStatus": "ALERTED",
        "episodeLowFen": 1_220,
        "riskStatus": "CLEAR",
        "riskBreachTradeDate": None,
        "dataHealth": {
            "status": health_status,
            "latestBarEnd": market_data_at,
            "dataAgeSeconds": 60,
            "requiredDataComplete": complete,
            "fresh": fresh,
        },
        "evidence": [
            {
                "kind": "RULE",
                "code": "BUY_CONDITION",
                "outcome": "SATISFIED",
                "facts": [
                    {
                        "key": "price_fen",
                        "value": 1_234,
                        "unit": "FEN",
                    }
                ],
                "missingInputs": [],
                "children": [],
            }
        ],
        "nextStep": {
            "code": "RECORD_CONFIRMED_FILL",
            "notBefore": None,
            "requiredInputs": [],
        },
    }


def _symbol_summary_payload(
    *,
    symbol: str = "003043.SZ",
    connected: bool = True,
    health_status: str = "LIVE",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "name": "Huaya Intelligence",
        "observedAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
        "connected": connected,
        "riskDistanceFen": 34,
        "satisfiedConditionCount": 1,
        "totalConditionCount": 1,
        "decision": _decision_payload(symbol=symbol, health_status=health_status),
    }


def _dashboard_payload() -> dict[str, object]:
    return {
        "sequence": 18,
        "observedAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
        "connectionStatus": "CONNECTED",
        "dataAgeSeconds": 60,
        "counts": {
            "actionable": 1,
            "lowZoneWatch": 0,
            "blocked": 0,
            "risk": 0,
            "stale": 0,
            "normal": 0,
        },
        "symbols": [_symbol_summary_payload()],
    }


def _runtime_health_payload() -> dict[str, object]:
    return {
        "status": "RUNNING",
        "readOnly": False,
        "observedAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
        "startedAt": datetime(2026, 8, 24, 9, 0, tzinfo=_SHANGHAI),
        "stoppedAt": None,
        "lastCompletedMinute": datetime(2026, 8, 24, 10, 4, tzinfo=_SHANGHAI),
        "lastCompletedMinuteAgeSeconds": 60,
        "latestEvaluationAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
        "latestEvaluationAgeSeconds": 0,
        "gaps": [],
        "nextRetryAt": None,
        "cooldownUntil": None,
        "providers": [
            {
                "capability": "realtime_minutes",
                "status": "READY",
                "checkedAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
                "latencyMs": 12,
                "errorCode": None,
                "nextRetryAt": None,
            }
        ],
        "executor": {"maxWorkers": 2, "activeCount": 1, "waitingCount": 0},
        "database": {
            "status": "READY",
            "walStatus": "READY",
            "lastCheckpointAt": datetime(2026, 8, 24, 10, 0, tzinfo=_SHANGHAI),
            "lastBackupAt": datetime(2026, 8, 24, 9, 0, tzinfo=_SHANGHAI),
            "errorCode": None,
        },
        "delivery": {
            "status": "READY",
            "pendingCount": 0,
            "failedCount": 0,
            "lastDeliveredAt": None,
            "nextRetryAt": None,
            "errorCode": None,
        },
        "nextPollAt": datetime(2026, 8, 24, 10, 5, 12, tzinfo=_SHANGHAI),
    }


class _FakeMonitorReadService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def get_dashboard(self) -> object:
        self.calls.append(("dashboard",))
        return deepcopy(_dashboard_payload())

    async def list_symbols(self, *, offset: int, limit: int) -> object:
        self.calls.append(("symbols", offset, limit))
        return {
            "items": [deepcopy(_symbol_summary_payload())],
            "offset": offset,
            "limit": limit,
            "total": 1,
        }

    async def get_symbol(self, *, symbol: str) -> object | None:
        self.calls.append(("symbol", symbol))
        if symbol != "003043.SZ":
            return None
        return {
            "summary": deepcopy(_symbol_summary_payload()),
            "positionLots": [
                {
                    "lotId": "lot-1",
                    "bucket": "CORE",
                    "quantity": 1_000,
                    "remainingQuantity": 1_000,
                    "sellableQuantity": 1_000,
                    "acquiredTradeDate": date(2026, 8, 21),
                    "costFen": 1_200,
                }
            ],
        }

    async def list_symbol_bars(
        self,
        *,
        symbol: str,
        interval: str,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> object | None:
        self.calls.append(("bars", symbol, interval, start_at, end_at, offset, limit))
        if symbol != "003043.SZ":
            return None
        return {
            "items": [
                {
                    "symbol": symbol,
                    "interval": interval,
                    "barEnd": datetime(2026, 8, 24, 10, 4, tzinfo=_SHANGHAI),
                    "openFen": 1_230,
                    "highFen": 1_240,
                    "lowFen": 1_225,
                    "closeFen": 1_234,
                    "volumeShares": 12_300,
                    "amountYuan": Decimal("151782.00"),
                    "receivedAt": datetime(2026, 8, 24, 10, 4, 12, tzinfo=_SHANGHAI),
                    "formulaVersion": None,
                }
            ],
            "offset": offset,
            "limit": limit,
            "total": 1,
            "startAt": start_at.isoformat(),
            "endAt": end_at.isoformat(),
        }

    async def list_symbol_events(
        self,
        *,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> object | None:
        self.calls.append(("events", symbol, start_at, end_at, offset, limit))
        if symbol != "003043.SZ":
            return None
        return {
            "items": [
                {
                    "symbol": symbol,
                    "sequence": 18,
                    "eventId": "8f466ae8-18d0-4219-a4e4-bcaebcb2878a",
                    "eventType": "DECISION",
                    "occurredAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
                    "signalType": "BUY_CORE_READY",
                    "resultHash": "a" * 64,
                    "messageText": "Deterministic decision recorded.",
                }
            ],
            "offset": offset,
            "limit": limit,
            "total": 1,
            "startAt": start_at.isoformat(),
            "endAt": end_at.isoformat(),
        }

    async def get_health(self) -> object:
        self.calls.append(("health",))
        return deepcopy(_runtime_health_payload())

    async def get_symbol_health(self, *, symbol: str) -> object | None:
        self.calls.append(("symbol_health", symbol))
        if symbol != "003043.SZ":
            return None
        return {
            "symbol": symbol,
            "observedAt": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
            "targetEnd": datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI),
            "status": "LIVE",
            "latestBarEnd": datetime(2026, 8, 24, 10, 4, tzinfo=_SHANGHAI),
            "dataAgeSeconds": 60,
            "requiredDataComplete": True,
            "fresh": True,
            "gaps": [],
            "consecutiveIncompleteBuckets": 0,
            "errorCode": None,
            "actionable": True,
        }


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


def test_dashboard_returns_authoritative_decision_evidence_and_data_age() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)

    response = TestClient(app).get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "sequence",
        "observedAt",
        "connectionStatus",
        "dataAgeSeconds",
        "counts",
        "symbols",
    }
    assert payload["connectionStatus"] == "CONNECTED"
    decision = payload["symbols"][0]["decision"]
    assert decision["resultHash"] == "a" * 64
    assert decision["dataAgeSeconds"] == 60
    assert decision["signalType"] == "BUY_CORE_READY"
    assert decision["evidence"] == [
        {
            "kind": "RULE",
            "code": "BUY_CONDITION",
            "outcome": "SATISFIED",
            "facts": [{"key": "price_fen", "value": 1_234, "unit": "FEN"}],
            "missingInputs": [],
            "children": [],
        }
    ]
    assert "result_hash" not in response.text
    assert service.calls == [("dashboard",)]


def test_symbols_are_paginated_and_symbol_detail_is_thin_service_read() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)
    client = TestClient(app)

    symbols = client.get("/api/v1/symbols", params={"offset": 0, "limit": 10})
    detail = client.get("/api/v1/symbols/003043.SZ")

    assert symbols.status_code == 200
    assert symbols.json()["offset"] == 0
    assert symbols.json()["limit"] == 10
    assert symbols.json()["total"] == 1
    assert symbols.json()["items"][0]["symbol"] == "003043.SZ"
    assert detail.status_code == 200
    assert detail.json()["summary"]["decision"]["resultHash"] == "a" * 64
    assert detail.json()["positionLots"][0]["sellableQuantity"] == 1_000
    assert service.calls == [
        ("symbols", 0, 10),
        ("symbol", "003043.SZ"),
    ]


def test_symbol_bars_require_an_inclusive_range_and_preserve_pagination() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)
    client = TestClient(app)
    params = {
        "interval": "ONE_MINUTE",
        "startAt": "2026-08-24T10:00:00+08:00",
        "endAt": "2026-08-24T10:05:00+08:00",
        "offset": 0,
        "limit": 20,
    }

    response = client.get("/api/v1/symbols/003043.SZ/bars", params=params)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "symbol": "003043.SZ",
                "interval": "ONE_MINUTE",
                "barEnd": "2026-08-24T10:04:00+08:00",
                "openFen": 1_230,
                "highFen": 1_240,
                "lowFen": 1_225,
                "closeFen": 1_234,
                "volumeShares": 12_300,
                "amountYuan": "151782.00",
                "receivedAt": "2026-08-24T10:04:12+08:00",
                "formulaVersion": None,
            }
        ],
        "offset": 0,
        "limit": 20,
        "total": 1,
        "startAt": "2026-08-24T10:00:00+08:00",
        "endAt": "2026-08-24T10:05:00+08:00",
    }
    assert client.get("/api/v1/symbols/003043.SZ/bars").status_code == 422
    reversed_range = client.get(
        "/api/v1/symbols/003043.SZ/bars",
        params={
            "startAt": "2026-08-24T10:05:00+08:00",
            "endAt": "2026-08-24T10:00:00+08:00",
        },
    )
    _assert_error_envelope(reversed_range, status=400, code="BAD_REQUEST")


def test_symbol_events_are_range_bounded_paginated_and_upper_snake() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)

    response = TestClient(app).get(
        "/api/v1/symbols/003043.SZ/events",
        params={
            "startAt": "2026-08-24T09:30:00+08:00",
            "endAt": "2026-08-24T15:00:00+08:00",
            "offset": 0,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "symbol": "003043.SZ",
        "sequence": 18,
        "eventId": "8f466ae8-18d0-4219-a4e4-bcaebcb2878a",
        "eventType": "DECISION",
        "occurredAt": "2026-08-24T10:05:00+08:00",
        "signalType": "BUY_CORE_READY",
        "resultHash": "a" * 64,
        "messageText": "Deterministic decision recorded.",
    }
    assert response.json()["total"] == 1


def test_health_and_symbol_health_expose_only_sanitized_typed_facts() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)
    client = TestClient(app)

    health = client.get("/api/v1/health")
    symbol_health = client.get("/api/v1/health/symbols/003043.SZ")

    assert health.status_code == 200
    assert health.json()["providers"] == [
        {
            "capability": "realtime_minutes",
            "status": "READY",
            "checkedAt": "2026-08-24T10:05:00+08:00",
            "latencyMs": 12,
            "errorCode": None,
            "nextRetryAt": None,
        }
    ]
    assert health.json()["database"]["walStatus"] == "READY"
    assert symbol_health.status_code == 200
    assert symbol_health.json()["status"] == "LIVE"
    assert symbol_health.json()["dataAgeSeconds"] == 60
    assert symbol_health.json()["actionable"] is True


def test_unknown_and_malformed_symbols_use_stable_errors() -> None:
    service = _FakeMonitorReadService()
    app = create_app(read_service=service)
    client = TestClient(app)

    unknown = client.get("/api/v1/symbols/600000.SH")
    malformed = client.get("/api/v1/symbols/not-a-symbol")
    unknown_health = client.get("/api/v1/health/symbols/600000.SH")
    range_params = {
        "startAt": "2026-08-24T09:30:00+08:00",
        "endAt": "2026-08-24T15:00:00+08:00",
    }
    unknown_bars = client.get("/api/v1/symbols/600000.SH/bars", params=range_params)
    unknown_events = client.get("/api/v1/symbols/600000.SH/events", params=range_params)

    _assert_error_envelope(unknown, status=404, code="NOT_FOUND")
    _assert_error_envelope(malformed, status=422, code="VALIDATION_ERROR")
    _assert_error_envelope(unknown_health, status=404, code="NOT_FOUND")
    _assert_error_envelope(unknown_bars, status=404, code="NOT_FOUND")
    _assert_error_envelope(unknown_events, status=404, code="NOT_FOUND")


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/symbols", {"offset": -1}),
        ("/api/v1/symbols", {"limit": 101}),
        (
            "/api/v1/symbols/003043.SZ/events",
            {
                "startAt": "2026-08-24T09:30:00+08:00",
                "endAt": "2026-08-24T15:00:00+08:00",
                "limit": 0,
            },
        ),
    ],
)
def test_symbol_pagination_is_bounded(path: str, params: dict[str, object]) -> None:
    app = create_app(read_service=_FakeMonitorReadService())

    response = TestClient(app).get(path, params=params)

    _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")


def test_disconnected_or_stale_symbol_cannot_be_labelled_live() -> None:
    class _ContradictoryService(_FakeMonitorReadService):
        async def get_dashboard(self) -> object:
            payload = _dashboard_payload()
            payload["connectionStatus"] = "DISCONNECTED"
            symbol = payload["symbols"][0]
            assert isinstance(symbol, dict)
            symbol["connected"] = False
            return payload

    app = create_app(read_service=_ContradictoryService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/dashboard")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_read_service_payload_cannot_expose_raw_provider_bodies() -> None:
    secret = "provider-raw-body-secret"

    class _UnsafeService(_FakeMonitorReadService):
        async def get_health(self) -> object:
            payload = _runtime_health_payload()
            payload["rawProviderBody"] = secret
            return payload

    app = create_app(read_service=_UnsafeService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/health")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")
    assert secret not in response.text


def test_symbol_page_metadata_must_match_the_requested_pagination() -> None:
    class _MismatchedPageService(_FakeMonitorReadService):
        async def list_symbols(self, *, offset: int, limit: int) -> object:
            payload = await super().list_symbols(offset=offset, limit=limit)
            assert isinstance(payload, dict)
            payload["offset"] = offset + 1
            payload["total"] = 2
            return payload

    app = create_app(read_service=_MismatchedPageService())

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/symbols",
        params={"offset": 0, "limit": 10},
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_symbol_health_cannot_claim_live_with_incomplete_or_stale_facts() -> None:
    class _ContradictoryHealthService(_FakeMonitorReadService):
        async def get_symbol_health(self, *, symbol: str) -> object | None:
            payload = await super().get_symbol_health(symbol=symbol)
            assert isinstance(payload, dict)
            payload["fresh"] = False
            payload["actionable"] = False
            payload["errorCode"] = "STALE_DATA"
            return payload

    app = create_app(read_service=_ContradictoryHealthService())

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/health/symbols/003043.SZ"
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_authoritative_decision_rejects_contradictory_risk_state() -> None:
    class _ContradictoryRiskService(_FakeMonitorReadService):
        async def get_dashboard(self) -> object:
            payload = _dashboard_payload()
            symbol = payload["symbols"][0]
            assert isinstance(symbol, dict)
            decision = symbol["decision"]
            assert isinstance(decision, dict)
            decision["riskBreachTradeDate"] = date(2026, 8, 24)
            return payload

    app = create_app(read_service=_ContradictoryRiskService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/dashboard")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_symbol_detail_rejects_position_lots_that_contradict_the_decision() -> None:
    class _ContradictoryPositionService(_FakeMonitorReadService):
        async def get_symbol(self, *, symbol: str) -> object | None:
            payload = await super().get_symbol(symbol=symbol)
            assert isinstance(payload, dict)
            lots = payload["positionLots"]
            assert isinstance(lots, list)
            lot = lots[0]
            assert isinstance(lot, dict)
            lot["remainingQuantity"] = 900
            lot["sellableQuantity"] = 900
            return payload

    app = create_app(read_service=_ContradictoryPositionService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/symbols/003043.SZ")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_runtime_health_rejects_a_stop_before_startup() -> None:
    class _ContradictoryRuntimeHealthService(_FakeMonitorReadService):
        async def get_health(self) -> object:
            payload = _runtime_health_payload()
            payload["status"] = "STOPPED"
            payload["stoppedAt"] = datetime(2026, 8, 24, 8, 59, tzinfo=_SHANGHAI)
            return payload

    app = create_app(read_service=_ContradictoryRuntimeHealthService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/health")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")
