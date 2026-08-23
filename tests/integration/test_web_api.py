from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EvaluationResult,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationIdentity,
    NextStep,
    NextStepCode,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json, load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import PriceInZoneCondition
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import (
    AlertEvent,
    AlertPayload,
    AlertPriceZone,
    AlertSeverity,
)
from trade_plan_monitor.notifications.render import render_alert
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


_PLAN_VERSION_ID = "10000000-0000-4000-8000-000000000001"
_BLOCKED_PLAN_VERSION_ID = "10000000-0000-4000-8000-000000000002"
_EXTRACTION_ID = "20000000-0000-4000-8000-000000000001"
_PROVIDER_ID = "30000000-0000-4000-8000-000000000001"
_PROVIDER_TEST_ID = "40000000-0000-4000-8000-000000000001"
_API_NOW = datetime(2026, 8, 24, 11, 0, tzinfo=_SHANGHAI)


def _sample_plan_document() -> tuple[str, str]:
    plan = load_plan_yaml(Path("config/plans/003043.SZ.sample.yaml").read_text(encoding="utf-8"))
    return dump_plan_json(plan), plan_sha256(plan)


def _plan_version_payload(
    *,
    version_id: str = _PLAN_VERSION_ID,
    blocked: bool = False,
) -> dict[str, object]:
    plan_json, plan_hash = _sample_plan_document()
    review_issues = (
        [
            {
                "kind": "WARNING",
                "path": "levels.pressure",
                "material": True,
                "resolved": False,
            }
        ]
        if blocked
        else []
    )
    return {
        "id": version_id,
        "planId": "huaya-smart",
        "version": 1,
        "symbol": "003043.SZ",
        "planHash": plan_hash,
        "status": "DRAFT",
        "planJson": plan_json,
        "sourceText": "华亚智能结构化交易计划",
        "reviewIssues": review_issues,
        "validationIssues": [],
        "canActivate": not blocked,
        "revision": 3,
        "createdAt": _API_NOW,
    }


def _provider_config_payload() -> dict[str, object]:
    return {
        "providerId": _PROVIDER_ID,
        "displayName": "Local provider",
        "providerType": "OPENAI_COMPATIBLE",
        "baseUrl": "https://ai.example.test/v1",
        "model": "example-model",
        "secretReference": {
            "key": "ai/provider/local",
            "environmentVariable": "LOCAL_AI_KEY",
        },
        "timeoutSeconds": 30,
        "maxRetries": 2,
        "maxInputChars": 50_000,
        "maxOutputTokens": 4_096,
        "temperature": 0,
        "promptVersion": "plan-extract-v1",
        "allowRedirects": False,
        "enabled": True,
    }


def _provider_payload(*, configured: bool = False) -> dict[str, object]:
    return {
        "config": _provider_config_payload(),
        "secretStatus": {
            "configured": configured,
            "source": "STORE" if configured else "NONE",
            "maskedValue": "********" if configured else None,
            "generation": 1 if configured else 0,
        },
        "revision": 4 if configured else 3,
        "createdAt": _API_NOW,
        "updatedAt": _API_NOW,
    }


class _FakePlanOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.background_runs = 0
        self.activation_runs = 0

    async def list_plan_versions(self, *, offset: int, limit: int) -> object:
        self.calls.append(("list_plan_versions", offset, limit))
        return {
            "items": [_plan_version_payload()],
            "offset": offset,
            "limit": limit,
            "total": 1,
        }

    async def get_plan_version(self, *, version_id: str) -> object | None:
        self.calls.append(("get_plan_version", version_id))
        if version_id == _BLOCKED_PLAN_VERSION_ID:
            return _plan_version_payload(version_id=version_id, blocked=True)
        if version_id != _PLAN_VERSION_ID:
            return None
        return _plan_version_payload()

    async def save_plan_draft(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "save_plan_draft",
                command.expected_revision,
                context.idempotency_key,
                context.request_id,
            )
        )
        return _plan_version_payload()

    async def import_plan(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "import_plan",
                command.format,
                command.expected_revision,
                context.idempotency_key,
            )
        )
        payload = _plan_version_payload()
        payload["sourceText"] = command.document
        return payload

    async def submit_plan_extraction(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "submit_plan_extraction",
                str(command.provider_id),
                command.expected_revision,
                context.idempotency_key,
            )
        )
        return {
            "operationId": _EXTRACTION_ID,
            "kind": "PLAN_EXTRACTION",
            "status": "QUEUED",
            "submittedAt": _API_NOW,
        }

    async def get_plan_extraction(self, *, operation_id: str) -> object | None:
        self.calls.append(("get_plan_extraction", operation_id))
        if operation_id != _EXTRACTION_ID:
            return None
        plan_json, _ = _sample_plan_document()
        return {
            "id": _EXTRACTION_ID,
            "providerId": _PROVIDER_ID,
            "status": "SUCCEEDED",
            "submittedAt": _API_NOW - timedelta(seconds=2),
            "startedAt": _API_NOW - timedelta(seconds=1),
            "completedAt": _API_NOW,
            "sourceTextSha256": "c" * 64,
            "model": "example-model",
            "promptVersion": "plan-extract-v1",
            "draftPlanJson": plan_json,
            "evidence": [
                {
                    "path": "plan_id",
                    "excerpt": "华亚智能交易计划",
                    "start": 0,
                    "end": 8,
                }
            ],
            "assumptions": [],
            "warnings": [],
            "unmappedText": [],
            "validationIssues": [
                {
                    "code": "AI_EVIDENCE_REVIEW_REQUIRED",
                    "path": "draft",
                    "severity": "WARNING",
                    "message": "Review AI field evidence before activation.",
                    "activationBlocking": True,
                }
            ],
            "usage": {
                "promptTokens": 100,
                "completionTokens": 50,
                "totalTokens": 150,
            },
        }

    async def activate_plan(self, *, command: object, context: object) -> object:
        self.activation_runs += 1
        self.calls.append(
            (
                "activate_plan",
                str(command.plan_version_id),
                command.expected_revision,
                context.idempotency_key,
            )
        )
        if str(command.plan_version_id) == _BLOCKED_PLAN_VERSION_ID:
            raise ApiError(ApiErrorCode.CONFLICT)
        return {
            "symbol": "003043.SZ",
            "planVersionId": _PLAN_VERSION_ID,
            "active": True,
            "revision": 4,
            "changedAt": _API_NOW,
        }

    async def deactivate_plan(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "deactivate_plan",
                command.symbol,
                command.expected_revision,
                context.idempotency_key,
            )
        )
        return {
            "symbol": command.symbol,
            "planVersionId": None,
            "active": False,
            "revision": command.expected_revision + 1,
            "changedAt": _API_NOW,
        }


class _FakeAIOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.provider_test_runs = 0

    async def list_ai_providers(self, *, offset: int, limit: int) -> object:
        self.calls.append(("list_ai_providers", offset, limit))
        return {
            "items": [_provider_payload()],
            "offset": offset,
            "limit": limit,
            "total": 1,
        }

    async def create_ai_provider(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "create_ai_provider",
                str(command.config.provider_id),
                command.expected_revision,
                context.idempotency_key,
            )
        )
        payload = _provider_payload()
        payload["revision"] = 0
        return payload

    async def update_ai_provider(
        self,
        *,
        provider_id: str,
        command: object,
        context: object,
    ) -> object | None:
        self.calls.append(
            (
                "update_ai_provider",
                provider_id,
                command.expected_revision,
                context.idempotency_key,
            )
        )
        payload = _provider_payload()
        payload["revision"] = command.expected_revision + 1
        return payload

    async def replace_ai_provider_secret(
        self,
        *,
        command: object,
        context: object,
    ) -> object:
        self.calls.append(
            (
                "replace_ai_provider_secret",
                str(command.provider_id),
                command.expected_revision,
                context.idempotency_key,
                repr(command.secret),
            )
        )
        return _provider_payload(configured=True)

    async def submit_ai_provider_test(
        self,
        *,
        command: object,
        context: object,
    ) -> object:
        self.calls.append(
            (
                "submit_ai_provider_test",
                str(command.provider_id),
                command.expected_revision,
                context.idempotency_key,
            )
        )
        return {
            "operationId": _PROVIDER_TEST_ID,
            "kind": "AI_PROVIDER_TEST",
            "status": "QUEUED",
            "submittedAt": _API_NOW,
        }


def test_plan_versions_are_paginated_and_details_revalidate_canonical_identity() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    client = TestClient(app)

    page = client.get("/api/v1/plan-versions", params={"offset": 0, "limit": 20})
    detail = client.get(f"/api/v1/plan-versions/{_PLAN_VERSION_ID}")
    missing_id = "90000000-0000-4000-8000-000000000009"
    missing = client.get(f"/api/v1/plan-versions/{missing_id}")

    assert page.status_code == 200
    assert page.json()["items"][0]["planId"] == "huaya-smart"
    assert page.json()["limit"] == 20
    assert detail.status_code == 200
    assert detail.json()["planJson"].startswith('{"activation"')
    _assert_error_envelope(missing, status=404, code="NOT_FOUND")
    assert service.calls == [
        ("list_plan_versions", 0, 20),
        ("get_plan_version", _PLAN_VERSION_ID),
        ("get_plan_version", missing_id),
    ]


def test_plan_draft_and_import_require_current_revision_and_idempotency_context() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    client = TestClient(app)
    plan_json, _ = _sample_plan_document()

    draft = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "plan-write-1"},
        json={
            "planJson": plan_json,
            "sourceText": "华亚智能结构化交易计划",
            "reviewIssues": [],
            "expectedRevision": 0,
        },
    )
    imported = client.post(
        "/api/v1/plan-imports",
        headers={"Idempotency-Key": "plan-import-1"},
        json={"format": "JSON", "document": plan_json, "expectedRevision": 2},
    )

    assert draft.status_code == 200
    assert imported.status_code == 200
    assert service.calls[0][:3] == ("save_plan_draft", 0, "plan-write-1")
    assert re.fullmatch(r"[0-9a-f]{32}", service.calls[0][3])
    assert service.calls[1] == ("import_plan", "JSON", 2, "plan-import-1")


def test_plan_draft_rejects_a_service_response_for_another_plan_identity() -> None:
    class _MismatchedPlanService(_FakePlanOperationService):
        async def save_plan_draft(self, *, command: object, context: object) -> object:
            return _plan_version_payload()

    service = _MismatchedPlanService()
    app = create_app(plan_service=service)
    plan = load_plan_json(_sample_plan_document()[0]).model_copy(update={"version": 2})

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "mismatched-plan"},
        json={
            "planJson": dump_plan_json(plan),
            "sourceText": "华亚智能结构化交易计划第二版",
            "reviewIssues": [],
            "expectedRevision": 1,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_plan_draft_and_import_cannot_return_an_active_version() -> None:
    class _ActiveDraftService(_FakePlanOperationService):
        async def save_plan_draft(self, *, command: object, context: object) -> object:
            payload = _plan_version_payload()
            payload["status"] = "ACTIVE"
            return payload

        async def import_plan(self, *, command: object, context: object) -> object:
            payload = await super().import_plan(command=command, context=context)
            assert isinstance(payload, dict)
            payload["status"] = "ACTIVE"
            return payload

    app = create_app(plan_service=_ActiveDraftService())
    client = TestClient(app, raise_server_exceptions=False)
    plan_json, _ = _sample_plan_document()

    draft = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "active-draft"},
        json={
            "planJson": plan_json,
            "sourceText": "华亚智能结构化交易计划",
            "reviewIssues": [],
            "expectedRevision": 0,
        },
    )
    imported = client.post(
        "/api/v1/plan-imports",
        headers={"Idempotency-Key": "active-import"},
        json={"format": "JSON", "document": plan_json, "expectedRevision": 0},
    )

    _assert_error_envelope(draft, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(imported, status=500, code="INTERNAL_ERROR")


def test_plan_draft_service_cannot_drop_an_unresolved_review_issue() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    plan_json, _ = _sample_plan_document()

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "preserve-review-issue"},
        json={
            "planJson": plan_json,
            "sourceText": "华亚智能结构化交易计划",
            "reviewIssues": [
                {
                    "kind": "WARNING",
                    "path": "levels.pressure",
                    "material": True,
                    "resolved": False,
                }
            ],
            "expectedRevision": 0,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_plan_extraction_returns_bounded_202_without_running_or_activating_in_handler() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)

    response = TestClient(app).post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": "extract-1"},
        json={
            "providerId": _PROVIDER_ID,
            "sourceText": "请将这份中文计划整理为待审核草稿",
            "expectedRevision": 3,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "operationId": _EXTRACTION_ID,
        "kind": "PLAN_EXTRACTION",
        "status": "QUEUED",
        "submittedAt": "2026-08-24T11:00:00+08:00",
    }
    assert service.background_runs == 0
    assert service.activation_runs == 0
    assert service.calls == [("submit_plan_extraction", _PROVIDER_ID, 3, "extract-1")]


def test_plan_extraction_status_exposes_review_data_but_no_raw_model_output() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)

    response = TestClient(app).get(f"/api/v1/plan-extractions/{_EXTRACTION_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["evidence"][0]["path"] == "plan_id"
    assert payload["usage"] == {
        "promptTokens": 100,
        "completionTokens": 50,
        "totalTokens": 150,
    }
    assert "raw" not in response.text.casefold()
    assert "authorization" not in response.text.casefold()


def test_plan_extraction_status_preserves_mandatory_review_blockers() -> None:
    class _UnsafeExtractionService(_FakePlanOperationService):
        def __init__(self, *, discard_warning: bool) -> None:
            super().__init__()
            self.discard_warning = discard_warning

        async def get_plan_extraction(self, *, operation_id: str) -> object:
            payload = await super().get_plan_extraction(operation_id=operation_id)
            assert isinstance(payload, dict)
            if self.discard_warning:
                payload["validationIssues"] = []
            else:
                payload["unmappedText"] = [
                    {
                        "path": "entry.condition",
                        "excerpt": "不支持的动态公式",
                        "reason": "Unsupported executable formula.",
                        "material": False,
                        "start": 9,
                        "end": 17,
                    }
                ]
            return payload

    missing_warning = TestClient(
        create_app(plan_service=_UnsafeExtractionService(discard_warning=True)),
        raise_server_exceptions=False,
    ).get(f"/api/v1/plan-extractions/{_EXTRACTION_ID}")
    downgraded_unmapped = TestClient(
        create_app(plan_service=_UnsafeExtractionService(discard_warning=False)),
        raise_server_exceptions=False,
    ).get(f"/api/v1/plan-extractions/{_EXTRACTION_ID}")

    _assert_error_envelope(missing_warning, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(downgraded_unmapped, status=500, code="INTERNAL_ERROR")


def test_plan_activation_is_separate_and_unresolved_material_warning_is_blocked() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    client = TestClient(app)

    blocked_detail = client.get(f"/api/v1/plan-versions/{_BLOCKED_PLAN_VERSION_ID}")
    blocked = client.post(
        "/api/v1/plan-activations",
        headers={"Idempotency-Key": "activate-blocked"},
        json={"planVersionId": _BLOCKED_PLAN_VERSION_ID, "expectedRevision": 3},
    )
    activated = client.post(
        "/api/v1/plan-activations",
        headers={"Idempotency-Key": "activate-ready"},
        json={"planVersionId": _PLAN_VERSION_ID, "expectedRevision": 3},
    )
    deactivated = client.post(
        "/api/v1/plan-deactivations",
        headers={"Idempotency-Key": "deactivate-1"},
        json={"symbol": "003043.SZ", "expectedRevision": 4},
    )

    assert blocked_detail.json()["canActivate"] is False
    assert blocked_detail.json()["reviewIssues"][0]["resolved"] is False
    _assert_error_envelope(blocked, status=409, code="CONFLICT")
    assert activated.status_code == 200
    assert activated.json()["active"] is True
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False


def test_plan_activation_and_deactivation_require_an_advanced_revision_receipt() -> None:
    class _StaleActivationService(_FakePlanOperationService):
        async def activate_plan(self, *, command: object, context: object) -> object:
            payload = await super().activate_plan(command=command, context=context)
            assert isinstance(payload, dict)
            payload["revision"] = command.expected_revision
            return payload

        async def deactivate_plan(self, *, command: object, context: object) -> object:
            payload = await super().deactivate_plan(command=command, context=context)
            assert isinstance(payload, dict)
            payload["revision"] = command.expected_revision
            return payload

    app = create_app(plan_service=_StaleActivationService())
    client = TestClient(app, raise_server_exceptions=False)

    activated = client.post(
        "/api/v1/plan-activations",
        headers={"Idempotency-Key": "stale-activation"},
        json={"planVersionId": _PLAN_VERSION_ID, "expectedRevision": 3},
    )
    deactivated = client.post(
        "/api/v1/plan-deactivations",
        headers={"Idempotency-Key": "stale-deactivation"},
        json={"symbol": "003043.SZ", "expectedRevision": 4},
    )

    _assert_error_envelope(activated, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(deactivated, status=500, code="INTERNAL_ERROR")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/plan-drafts",
            {
                "planJson": _sample_plan_document()[0],
                "sourceText": "华亚智能结构化交易计划",
                "reviewIssues": [],
                "expectedRevision": 0,
            },
        ),
        (
            "/api/v1/plan-imports",
            {
                "format": "JSON",
                "document": _sample_plan_document()[0],
                "expectedRevision": 0,
            },
        ),
        (
            "/api/v1/plan-extractions",
            {
                "providerId": _PROVIDER_ID,
                "sourceText": "中文计划",
                "expectedRevision": 0,
            },
        ),
        (
            "/api/v1/plan-activations",
            {"planVersionId": _PLAN_VERSION_ID, "expectedRevision": 0},
        ),
        (
            "/api/v1/plan-deactivations",
            {"symbol": "003043.SZ", "expectedRevision": 0},
        ),
    ],
)
def test_plan_mutations_require_idempotency_key(path: str, body: dict[str, object]) -> None:
    app = create_app(plan_service=_FakePlanOperationService())

    response = TestClient(app).post(path, json=body)

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert any(detail["location"][-1] == "Idempotency-Key" for detail in error["details"])


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/plan-drafts",
            {
                "planJson": _sample_plan_document()[0],
                "sourceText": "华亚智能结构化交易计划",
                "reviewIssues": [],
            },
        ),
        (
            "/api/v1/plan-imports",
            {"format": "JSON", "document": _sample_plan_document()[0]},
        ),
        (
            "/api/v1/plan-extractions",
            {"providerId": _PROVIDER_ID, "sourceText": "中文计划"},
        ),
        (
            "/api/v1/plan-activations",
            {"planVersionId": _PLAN_VERSION_ID},
        ),
        (
            "/api/v1/plan-deactivations",
            {"symbol": "003043.SZ"},
        ),
    ],
)
def test_plan_mutations_require_expected_revision(
    path: str,
    body: dict[str, object],
) -> None:
    app = create_app(plan_service=_FakePlanOperationService())

    response = TestClient(app).post(
        path,
        headers={"Idempotency-Key": "revision-required"},
        json=body,
    )

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert any(detail["location"][-1] == "expectedRevision" for detail in error["details"])


def test_plan_idempotency_conflict_mismatch_and_completed_replay_are_stable() -> None:
    class _IdempotentService(_FakePlanOperationService):
        def __init__(self) -> None:
            super().__init__()
            self.claims: dict[str, str] = {}

        async def save_plan_draft(self, *, command: object, context: object) -> object:
            key = context.idempotency_key
            fingerprint = command.model_dump_json()
            if key == "pending-intent":
                raise ApiError(ApiErrorCode.CONFLICT)
            existing = self.claims.get(key)
            if existing is not None and existing != fingerprint:
                raise ApiError(ApiErrorCode.VALIDATION_ERROR)
            self.claims[key] = fingerprint
            return _plan_version_payload()

    service = _IdempotentService()
    app = create_app(plan_service=service)
    client = TestClient(app)
    plan_json, _ = _sample_plan_document()
    body = {
        "planJson": plan_json,
        "sourceText": "华亚智能结构化交易计划",
        "reviewIssues": [],
        "expectedRevision": 0,
    }

    conflict = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "pending-intent"},
        json=body,
    )
    first = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "completed-intent"},
        json=body,
    )
    replay = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "completed-intent"},
        json=body,
    )
    mismatch = client.post(
        "/api/v1/plan-drafts",
        headers={"Idempotency-Key": "completed-intent"},
        json={**body, "sourceText": "changed source"},
    )

    _assert_error_envelope(conflict, status=409, code="CONFLICT")
    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.content == replay.content
    _assert_error_envelope(mismatch, status=422, code="VALIDATION_ERROR")


def test_plan_extraction_input_and_idempotency_key_are_bounded_before_service_call() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    client = TestClient(app)
    body = {
        "providerId": _PROVIDER_ID,
        "sourceText": "x" * 200_001,
        "expectedRevision": 3,
    }

    oversized_source = client.post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": "bounded-source"},
        json=body,
    )
    oversized_key = client.post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": "k" * 129},
        json={**body, "sourceText": "bounded source"},
    )

    _assert_error_envelope(oversized_source, status=422, code="VALIDATION_ERROR")
    _assert_error_envelope(oversized_key, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


def test_plan_extraction_rejects_a_wrong_operation_receipt_kind() -> None:
    class _WrongReceiptService(_FakePlanOperationService):
        async def submit_plan_extraction(self, *, command: object, context: object) -> object:
            receipt = await super().submit_plan_extraction(command=command, context=context)
            assert isinstance(receipt, dict)
            receipt["kind"] = "AI_PROVIDER_TEST"
            return receipt

    app = create_app(plan_service=_WrongReceiptService())

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": "wrong-operation-kind"},
        json={
            "providerId": _PROVIDER_ID,
            "sourceText": "中文计划",
            "expectedRevision": 3,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_ai_provider_configuration_is_paginated_created_and_replaced_by_revision() -> None:
    service = _FakeAIOperationService()
    app = create_app(ai_service=service)
    client = TestClient(app)
    config = _provider_config_payload()

    page = client.get("/api/v1/ai-providers", params={"offset": 0, "limit": 20})
    created = client.post(
        "/api/v1/ai-providers",
        headers={"Idempotency-Key": "provider-create"},
        json={"config": config, "expectedRevision": 0},
    )
    updated = client.patch(
        f"/api/v1/ai-providers/{_PROVIDER_ID}",
        headers={"Idempotency-Key": "provider-update"},
        json={"config": config, "expectedRevision": 3},
    )

    assert page.status_code == 200
    assert page.json()["items"][0]["config"]["providerId"] == _PROVIDER_ID
    assert created.status_code == 200
    assert updated.status_code == 200
    assert service.calls == [
        ("list_ai_providers", 0, 20),
        ("create_ai_provider", _PROVIDER_ID, 0, "provider-create"),
        ("update_ai_provider", _PROVIDER_ID, 3, "provider-update"),
    ]


def test_ai_provider_create_and_update_reject_mismatched_service_configuration() -> None:
    class _MismatchedProviderService(_FakeAIOperationService):
        async def create_ai_provider(self, *, command: object, context: object) -> object:
            payload = _provider_payload()
            config = payload["config"]
            assert isinstance(config, dict)
            config["model"] = "other-model"
            return payload

        async def update_ai_provider(
            self,
            *,
            provider_id: str,
            command: object,
            context: object,
        ) -> object:
            return await self.create_ai_provider(command=command, context=context)

    app = create_app(ai_service=_MismatchedProviderService())
    client = TestClient(app, raise_server_exceptions=False)
    body = {"config": _provider_config_payload(), "expectedRevision": 3}

    created = client.post(
        "/api/v1/ai-providers",
        headers={"Idempotency-Key": "mismatched-create"},
        json={**body, "expectedRevision": 0},
    )
    updated = client.patch(
        f"/api/v1/ai-providers/{_PROVIDER_ID}",
        headers={"Idempotency-Key": "mismatched-update"},
        json=body,
    )

    _assert_error_envelope(created, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(updated, status=500, code="INTERNAL_ERROR")


def test_plan_and_ai_provider_empty_pages_allow_offset_after_total() -> None:
    class _EmptyPlanPageService(_FakePlanOperationService):
        async def list_plan_versions(self, *, offset: int, limit: int) -> object:
            return {"items": [], "offset": offset, "limit": limit, "total": 1}

    class _EmptyProviderPageService(_FakeAIOperationService):
        async def list_ai_providers(self, *, offset: int, limit: int) -> object:
            return {"items": [], "offset": offset, "limit": limit, "total": 1}

    plan_response = TestClient(
        create_app(plan_service=_EmptyPlanPageService()),
        raise_server_exceptions=False,
    ).get("/api/v1/plan-versions", params={"offset": 20, "limit": 20})
    provider_response = TestClient(
        create_app(ai_service=_EmptyProviderPageService()),
        raise_server_exceptions=False,
    ).get("/api/v1/ai-providers", params={"offset": 20, "limit": 20})

    assert plan_response.status_code == 200
    assert plan_response.json()["items"] == []
    assert provider_response.status_code == 200
    assert provider_response.json()["items"] == []


def test_ai_provider_secret_is_write_only_masked_and_never_reaches_response() -> None:
    secret = "api-key-that-must-never-leak"
    service = _FakeAIOperationService()
    app = create_app(ai_service=service)

    response = TestClient(app).post(
        "/api/v1/ai-provider-secrets",
        headers={"Idempotency-Key": "provider-secret"},
        json={
            "providerId": _PROVIDER_ID,
            "secret": {"value": secret},
            "expectedRevision": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["secretStatus"] == {
        "configured": True,
        "source": "STORE",
        "maskedValue": "********",
        "generation": 1,
    }
    assert secret not in response.text
    assert secret not in repr(service.calls)
    assert "********" in service.calls[0][-1]


def test_ai_provider_update_and_secret_replace_require_advanced_revision_receipts() -> None:
    class _StaleProviderService(_FakeAIOperationService):
        async def update_ai_provider(
            self,
            *,
            provider_id: str,
            command: object,
            context: object,
        ) -> object:
            return _provider_payload()

        async def replace_ai_provider_secret(
            self,
            *,
            command: object,
            context: object,
        ) -> object:
            return _provider_payload()

    app = create_app(ai_service=_StaleProviderService())
    client = TestClient(app, raise_server_exceptions=False)

    updated = client.patch(
        f"/api/v1/ai-providers/{_PROVIDER_ID}",
        headers={"Idempotency-Key": "stale-provider-update"},
        json={"config": _provider_config_payload(), "expectedRevision": 3},
    )
    secret = client.post(
        "/api/v1/ai-provider-secrets",
        headers={"Idempotency-Key": "stale-provider-secret"},
        json={
            "providerId": _PROVIDER_ID,
            "secret": {"value": "replacement-secret"},
            "expectedRevision": 3,
        },
    )

    _assert_error_envelope(updated, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(secret, status=500, code="INTERNAL_ERROR")


def test_ai_provider_test_returns_202_and_never_runs_provider_in_request_handler() -> None:
    service = _FakeAIOperationService()
    app = create_app(ai_service=service)

    response = TestClient(app).post(
        "/api/v1/ai-provider-tests",
        headers={"Idempotency-Key": "provider-test"},
        json={"providerId": _PROVIDER_ID, "expectedRevision": 3},
    )

    assert response.status_code == 202
    assert response.json()["operationId"] == _PROVIDER_TEST_ID
    assert response.json()["status"] == "QUEUED"
    assert service.provider_test_runs == 0
    assert service.calls == [("submit_ai_provider_test", _PROVIDER_ID, 3, "provider-test")]


def test_ai_provider_test_rejects_a_wrong_operation_receipt_kind() -> None:
    class _WrongReceiptService(_FakeAIOperationService):
        async def submit_ai_provider_test(
            self,
            *,
            command: object,
            context: object,
        ) -> object:
            receipt = await super().submit_ai_provider_test(command=command, context=context)
            assert isinstance(receipt, dict)
            receipt["kind"] = "PLAN_EXTRACTION"
            return receipt

    app = create_app(ai_service=_WrongReceiptService())

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/ai-provider-tests",
        headers={"Idempotency-Key": "wrong-operation-kind"},
        json={"providerId": _PROVIDER_ID, "expectedRevision": 3},
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_ai_provider_response_cannot_expose_secret_material_or_raw_provider_body() -> None:
    secret = "server-side-secret-material"

    class _UnsafeProviderService(_FakeAIOperationService):
        async def list_ai_providers(self, *, offset: int, limit: int) -> object:
            payload = await super().list_ai_providers(offset=offset, limit=limit)
            assert isinstance(payload, dict)
            item = payload["items"][0]
            assert isinstance(item, dict)
            item["secretValue"] = secret
            item["rawProviderBody"] = "raw upstream body"
            return payload

    app = create_app(ai_service=_UnsafeProviderService())

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/ai-providers")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")
    assert secret not in response.text
    assert "raw upstream body" not in response.text


def test_ai_provider_configuration_rejects_unsafe_remote_http_before_service_call() -> None:
    service = _FakeAIOperationService()
    app = create_app(ai_service=service)
    config = _provider_config_payload()
    config["baseUrl"] = "http://remote.example.test/v1"

    response = TestClient(app).post(
        "/api/v1/ai-providers",
        headers={"Idempotency-Key": "unsafe-provider-url"},
        json={"config": config, "expectedRevision": 0},
    )

    _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "post",
            "/api/v1/ai-providers",
            {"config": _provider_config_payload()},
        ),
        (
            "patch",
            f"/api/v1/ai-providers/{_PROVIDER_ID}",
            {"config": _provider_config_payload()},
        ),
        (
            "post",
            "/api/v1/ai-provider-secrets",
            {"providerId": _PROVIDER_ID, "secret": {"value": "secret"}},
        ),
        (
            "post",
            "/api/v1/ai-provider-tests",
            {"providerId": _PROVIDER_ID},
        ),
    ],
)
def test_ai_provider_mutations_require_expected_revision(
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    app = create_app(ai_service=_FakeAIOperationService())

    response = getattr(TestClient(app), method)(
        path,
        headers={"Idempotency-Key": "revision-required"},
        json=body,
    )

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert any(detail["location"][-1] == "expectedRevision" for detail in error["details"])


def test_ai_provider_invalid_secret_error_never_echoes_input() -> None:
    app = create_app(ai_service=_FakeAIOperationService())
    secret = "s" * 8_193

    response = TestClient(app).post(
        "/api/v1/ai-provider-secrets",
        headers={"Idempotency-Key": "invalid-secret"},
        json={
            "providerId": _PROVIDER_ID,
            "secret": {"value": secret},
            "expectedRevision": 3,
        },
    )

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert secret not in response.text
    assert all("input" not in detail for detail in error["details"])


def test_plan_extraction_rejects_lone_surrogate_before_service_call_without_leak() -> None:
    service = _FakePlanOperationService()
    app = create_app(plan_service=service)
    source = "sensitive-source-\ud800"

    response = TestClient(app).post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": "surrogate-source"},
        content=json.dumps(
            {
                "providerId": _PROVIDER_ID,
                "sourceText": source,
                "expectedRevision": 3,
            },
            ensure_ascii=True,
        ),
    )

    _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert service.calls == []
    assert "sensitive-source" not in response.text


_POSITION_LOT_ID = "50000000-0000-4000-8000-000000000001"
_ALERT_ID = "60000000-0000-4000-8000-000000000001"


def _position_lot_payload(
    *,
    remaining_quantity: int = 100,
    sellable_quantity: int = 100,
    closed_at: datetime | None = None,
    revision: int | None = None,
) -> dict[str, object]:
    if revision is None:
        revision = (100 - remaining_quantity) // 100
    return {
        "lotId": _POSITION_LOT_ID,
        "symbol": "003043.SZ",
        "bucket": "CORE",
        "quantity": 100,
        "remainingQuantity": remaining_quantity,
        "sellableQuantity": sellable_quantity,
        "acquiredTradeDate": date(2026, 8, 21),
        "costFen": 6_400,
        "relatedAlertId": _ALERT_ID,
        "closedAt": closed_at,
        "revision": revision,
    }


def _alert_event(
    *,
    event_id: str = _ALERT_ID,
    sequence: int = 23,
    acknowledged_at: datetime | None = None,
) -> AlertEvent:
    evaluated_at = datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI)
    evidence = ConditionEvidence(
        condition=PriceInZoneCondition(zone="LOW_BUY"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=6_420,
                unit=EvidenceUnit.FEN,
            ),
        ),
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    signal = SignalIntent(
        signal_type=ActionableSignalType.BUY_CORE_READY,
        plan_hash="b" * 64,
        symbol="003043.SZ",
        trading_date=date(2026, 8, 24),
        cause_id="episode-001",
        quantity=100,
        bucket="CORE",
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    payload = AlertPayload(
        event_id=UUID(event_id),
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash="b" * 64,
        symbol="003043.SZ",
        name="华亚智能",
        signal_type=signal.signal_type,
        severity=AlertSeverity.ACTION,
        trading_date=date(2026, 8, 24),
        cause_id=signal.cause_id,
        evaluated_at=evaluated_at,
        market_data_at=evaluated_at - timedelta(seconds=60),
        data_age_seconds=60,
        price_fen=6_420,
        quantity=signal.quantity,
        bucket=signal.bucket,
        target_lot_id=signal.target_lot_id,
        matched_conditions=signal.matched_conditions,
        satisfied_conditions=signal.matched_conditions,
        unmet_conditions=(),
        blockers=(),
        zone=DecisionZone.LOW_BUY,
        relevant_zone=AlertPriceZone(
            zone=DecisionZone.LOW_BUY,
            low_fen=6_300,
            high_fen=6_450,
            include_low=True,
            include_high=True,
        ),
        risk_line_fen=6_080,
        next_step=next_step,
    )
    return AlertEvent(
        **payload.model_dump(mode="python", round_trip=True),
        sequence=sequence,
        message_text=render_alert(payload),
        created_at=evaluated_at,
        acknowledged_at=acknowledged_at,
    )


def _alert_record_payload(
    *,
    event_id: str = _ALERT_ID,
    sequence: int = 23,
    acknowledged_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "event": _alert_event(
            event_id=event_id,
            sequence=sequence,
            acknowledged_at=acknowledged_at,
        ),
        "revision": 1 if acknowledged_at is not None else 0,
        "positionPrefill": {
            "action": "BUY",
            "symbol": "003043.SZ",
            "bucket": "CORE",
            "quantity": 100,
            "targetLotId": None,
            "relatedAlertId": event_id,
        },
    }


def _diagnostic_result(bucket_end: datetime) -> EvaluationResult:
    evidence = ConditionEvidence(
        condition=PriceInZoneCondition(zone="LOW_BUY"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(EvidenceFact(key="current_price_fen", value=1_234, unit=EvidenceUnit.FEN),),
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    signal = SignalIntent(
        signal_type=ActionableSignalType.BUY_CORE_READY,
        plan_hash="b" * 64,
        symbol="003043.SZ",
        trading_date=bucket_end.date(),
        cause_id="episode-001",
        quantity=100,
        bucket="CORE",
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    snapshot = SymbolDecisionSnapshot(
        symbol="003043.SZ",
        plan_id="sample-plan",
        plan_version=3,
        plan_hash="b" * 64,
        evaluated_at=bucket_end,
        market_data_at=bucket_end,
        price_fen=1_234,
        zone=DecisionZone.LOW_BUY,
        signal_type=SignalType.BUY_CORE_READY,
        position=PositionSummary(
            core_quantity=1_000,
            tactical_quantity=0,
            total_quantity=1_000,
            sellable_core_quantity=1_000,
            sellable_tactical_quantity=0,
        ),
        episode=None,
        risk=RiskStateSnapshot(
            symbol="003043.SZ",
            plan_hash="b" * 64,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=1_200,
            revision=0,
            updated_at=bucket_end,
        ),
        data_health=DataHealthSnapshot(
            symbol="003043.SZ",
            status=DataHealthStatus.LIVE,
            latest_bar_end=bucket_end,
            data_age_seconds=0,
            required_data_complete=True,
            fresh=True,
        ),
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    return EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash="b" * 64,
            symbol="003043.SZ",
            bucket_end=bucket_end,
        ),
    )


class _FakePositionOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def list_position_lots(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
        offset: int,
        limit: int,
    ) -> object:
        self.calls.append(("list_position_lots", symbol, as_of_trade_date, offset, limit))
        return {
            "items": [_position_lot_payload()],
            "symbol": symbol,
            "asOfTradeDate": as_of_trade_date,
            "offset": offset,
            "limit": limit,
            "total": max(1, offset + 1),
        }

    async def record_position_lot(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "record_position_lot",
                command.symbol,
                command.bucket,
                command.quantity,
                command.acquired_trade_date,
                command.cost_fen,
                str(command.related_alert_id),
                command.expected_revision,
                context.idempotency_key,
                context.request_id,
            )
        )
        return _position_lot_payload()

    async def close_position_lot(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "close_position_lot",
                str(command.lot_id),
                command.quantity,
                command.trade_date,
                command.expected_revision,
                context.idempotency_key,
            )
        )
        return {
            "lot": _position_lot_payload(
                remaining_quantity=0,
                sellable_quantity=0,
                closed_at=_API_NOW,
            ),
            "appliedQuantity": command.quantity,
            "tradeDate": command.trade_date,
            "beforeRemainingQuantity": 100,
            "afterRemainingQuantity": 0,
        }


class _FakeAlertOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def list_alerts(
        self,
        *,
        symbol: str | None,
        signal_type: str | None,
        acknowledged: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> object:
        self.calls.append(
            (
                "list_alerts",
                symbol,
                signal_type,
                acknowledged,
                start_at,
                end_at,
                offset,
                limit,
            )
        )
        return {
            "items": [_alert_record_payload()],
            "symbol": symbol,
            "signalType": signal_type,
            "acknowledged": acknowledged,
            "startAt": start_at,
            "endAt": end_at,
            "offset": offset,
            "limit": limit,
            "total": 1,
        }

    async def acknowledge_alert(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "acknowledge_alert",
                str(command.alert_id),
                command.expected_revision,
                context.idempotency_key,
                context.request_id,
            )
        )
        return _alert_record_payload(
            acknowledged_at=_API_NOW + timedelta(minutes=1),
        )

    async def evaluate_diagnostic(self, *, command: object, context: object) -> object:
        self.calls.append(
            (
                "evaluate_diagnostic",
                command.symbol,
                command.evaluation_kind,
                command.bucket_end,
                command.official_trade_date,
                command.expected_revision,
                context.idempotency_key,
            )
        )
        return {
            "result": _diagnostic_result(command.bucket_end),
            "sourceRevision": command.expected_revision,
            "stateMutationApplied": False,
            "alertEnqueued": False,
            "positionChanged": False,
            "audited": False,
        }


def test_position_lots_are_paginated_and_manual_create_close_are_explicit() -> None:
    service = _FakePositionOperationService()
    app = create_app(position_service=service)
    client = TestClient(app)

    page = client.get(
        "/api/v1/position-lots",
        params={
            "symbol": "003043.SZ",
            "asOfTradeDate": "2026-08-24",
            "offset": 2,
            "limit": 5,
        },
    )
    created = client.post(
        "/api/v1/position-lots",
        headers={"Idempotency-Key": "position-buy-1"},
        json={
            "symbol": "003043.SZ",
            "bucket": "CORE",
            "quantity": 100,
            "acquiredTradeDate": "2026-08-21",
            "costFen": 6_400,
            "relatedAlertId": _ALERT_ID,
            "expectedRevision": 0,
        },
    )
    closed = client.post(
        "/api/v1/position-lot-closures",
        headers={"Idempotency-Key": "position-close-1"},
        json={
            "lotId": _POSITION_LOT_ID,
            "quantity": 100,
            "tradeDate": "2026-08-24",
            "expectedRevision": 0,
        },
    )

    assert page.status_code == 200
    assert page.json()["symbol"] == "003043.SZ"
    assert page.json()["asOfTradeDate"] == "2026-08-24"
    assert page.json()["offset"] == 2
    assert page.json()["limit"] == 5
    assert page.json()["items"][0]["sellableQuantity"] == 100
    assert created.status_code == 200
    assert created.json()["revision"] == 0
    assert created.json()["relatedAlertId"] == _ALERT_ID
    assert closed.status_code == 200
    assert closed.json()["lot"]["remainingQuantity"] == 0
    assert closed.json()["lot"]["closedAt"] is not None
    assert closed.json()["appliedQuantity"] == 100
    assert closed.json()["beforeRemainingQuantity"] == 100
    assert closed.json()["afterRemainingQuantity"] == 0
    assert service.calls[0] == (
        "list_position_lots",
        "003043.SZ",
        date(2026, 8, 24),
        2,
        5,
    )
    assert _REQUEST_ID_PATTERN.fullmatch(service.calls[1][-1])


def test_position_commands_enforce_board_lot_maximum_and_t_plus_one() -> None:
    class _PolicyService(_FakePositionOperationService):
        async def record_position_lot(self, *, command: object, context: object) -> object:
            self.calls.append(("record_position_lot", command.quantity))
            raise ApiError(ApiErrorCode.CONFLICT)

        async def close_position_lot(self, *, command: object, context: object) -> object:
            self.calls.append(("close_position_lot", command.trade_date))
            raise ApiError(ApiErrorCode.CONFLICT)

    service = _PolicyService()
    app = create_app(position_service=service)
    client = TestClient(app)
    base = {
        "symbol": "003043.SZ",
        "bucket": "CORE",
        "acquiredTradeDate": "2026-08-24",
        "costFen": 6_400,
        "expectedRevision": 0,
    }

    board_lot = client.post(
        "/api/v1/position-lots",
        headers={"Idempotency-Key": "bad-board-lot"},
        json={**base, "quantity": 50},
    )
    maximum = client.post(
        "/api/v1/position-lots",
        headers={"Idempotency-Key": "maximum-position"},
        json={**base, "quantity": 100},
    )
    t_plus_one = client.post(
        "/api/v1/position-lot-closures",
        headers={"Idempotency-Key": "same-day-close"},
        json={
            "lotId": _POSITION_LOT_ID,
            "quantity": 100,
            "tradeDate": "2026-08-24",
            "expectedRevision": 0,
        },
    )

    _assert_error_envelope(board_lot, status=422, code="VALIDATION_ERROR")
    _assert_error_envelope(maximum, status=409, code="CONFLICT")
    _assert_error_envelope(t_plus_one, status=409, code="CONFLICT")
    assert service.calls == [
        ("record_position_lot", 100),
        ("close_position_lot", date(2026, 8, 24)),
    ]


def test_alerts_filter_and_paginate_with_non_submitting_position_prefill() -> None:
    alert_service = _FakeAlertOperationService()
    position_service = _FakePositionOperationService()
    app = create_app(
        alert_service=alert_service,
        position_service=position_service,
    )
    start_at = datetime(2026, 8, 24, 9, 30, tzinfo=_SHANGHAI)
    end_at = datetime(2026, 8, 24, 15, 0, tzinfo=_SHANGHAI)

    response = TestClient(app).get(
        "/api/v1/alerts",
        params={
            "symbol": "003043.SZ",
            "signalType": "BUY_CORE_READY",
            "acknowledged": "false",
            "startAt": start_at.isoformat(),
            "endAt": end_at.isoformat(),
            "offset": 0,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["offset"] == 0
    assert body["limit"] == 10
    assert body["symbol"] == "003043.SZ"
    assert body["signalType"] == "BUY_CORE_READY"
    assert body["acknowledged"] is False
    assert body["startAt"] == start_at.isoformat()
    assert body["endAt"] == end_at.isoformat()
    assert body["items"][0]["acknowledgedAt"] is None
    assert body["items"][0]["revision"] == 0
    assert body["items"][0]["dedupKey"] == _alert_event().dedup_key
    assert body["items"][0]["relevantZone"]["zone"] == "LOW_BUY"
    assert body["items"][0]["positionPrefill"] == {
        "action": "BUY",
        "symbol": "003043.SZ",
        "bucket": "CORE",
        "quantity": 100,
        "targetLotId": None,
        "relatedAlertId": _ALERT_ID,
    }
    assert alert_service.calls == [
        (
            "list_alerts",
            "003043.SZ",
            "BUY_CORE_READY",
            False,
            start_at,
            end_at,
            0,
            10,
        )
    ]
    assert position_service.calls == []


def test_alert_acknowledgement_is_idempotent_and_never_records_a_fill() -> None:
    alert_service = _FakeAlertOperationService()
    position_service = _FakePositionOperationService()
    app = create_app(
        alert_service=alert_service,
        position_service=position_service,
    )

    response = TestClient(app).post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "alert-ack-1"},
        json={"alertId": _ALERT_ID, "expectedRevision": 0},
    )

    assert response.status_code == 200
    assert response.json()["eventId"] == _ALERT_ID
    assert response.json()["acknowledgedAt"] is not None
    assert response.json()["revision"] == 1
    assert alert_service.calls[0][0:4] == (
        "acknowledge_alert",
        _ALERT_ID,
        0,
        "alert-ack-1",
    )
    assert position_service.calls == []


def test_diagnostic_evaluation_returns_authoritative_result_without_mutation() -> None:
    service = _FakeAlertOperationService()
    app = create_app(alert_service=service)
    bucket_end = datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI)

    response = TestClient(app).post(
        "/api/v1/diagnostic-evaluations",
        headers={"Idempotency-Key": "diagnostic-1"},
        json={
            "symbol": "003043.SZ",
            "evaluationKind": "INTRADAY",
            "bucketEnd": bucket_end.isoformat(),
            "officialTradeDate": None,
            "expectedRevision": 11,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["resultHash"] == _diagnostic_result(bucket_end).result_hash
    assert body["decision"]["symbol"] == "003043.SZ"
    assert body["evaluationIdentity"] == {
        "kind": "INTRADAY",
        "planHash": "b" * 64,
        "symbol": "003043.SZ",
        "bucketEnd": bucket_end.isoformat(),
        "formulaVersion": "ta-v1",
    }
    assert body["sourceRevision"] == 11
    assert body["stateMutationApplied"] is False
    assert body["alertEnqueued"] is False
    assert body["positionChanged"] is False
    assert body["audited"] is False
    assert service.calls == [
        (
            "evaluate_diagnostic",
            "003043.SZ",
            "INTRADAY",
            bucket_end,
            None,
            11,
            "diagnostic-1",
        )
    ]


def test_diagnostic_rejects_a_non_session_or_noncanonical_intraday_target() -> None:
    service = _FakeAlertOperationService()
    client = TestClient(create_app(alert_service=service))

    lunch = client.post(
        "/api/v1/diagnostic-evaluations",
        headers={"Idempotency-Key": "diagnostic-lunch"},
        json={
            "symbol": "003043.SZ",
            "evaluationKind": "INTRADAY",
            "bucketEnd": "2026-08-24T12:00:00+08:00",
            "officialTradeDate": None,
            "expectedRevision": 11,
        },
    )
    fractional = client.post(
        "/api/v1/diagnostic-evaluations",
        headers={"Idempotency-Key": "diagnostic-fractional"},
        json={
            "symbol": "003043.SZ",
            "evaluationKind": "INTRADAY",
            "bucketEnd": "2026-08-24T10:05:00.500000+08:00",
            "officialTradeDate": None,
            "expectedRevision": 11,
        },
    )

    _assert_error_envelope(lunch, status=422, code="VALIDATION_ERROR")
    _assert_error_envelope(fractional, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


def test_alert_response_rejects_signal_severity_drift() -> None:
    class _UnsafeAlertService(_FakeAlertOperationService):
        async def list_alerts(self, **kwargs: object) -> object:
            payload = await super().list_alerts(**kwargs)
            event = payload["items"][0]["event"].model_dump(
                mode="python",
                round_trip=True,
            )
            event["severity"] = "CRITICAL"
            payload["items"][0]["event"] = event
            return payload

    response = TestClient(
        create_app(alert_service=_UnsafeAlertService()),
        raise_server_exceptions=False,
    ).get("/api/v1/alerts")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_alert_response_rejects_multiline_name_injection() -> None:
    class _UnsafeAlertService(_FakeAlertOperationService):
        async def list_alerts(self, **kwargs: object) -> object:
            payload = await super().list_alerts(**kwargs)
            event = payload["items"][0]["event"].model_dump(
                mode="python",
                round_trip=True,
            )
            event["name"] = "华亚\n智能"
            payload["items"][0]["event"] = event
            return payload

    response = TestClient(
        create_app(alert_service=_UnsafeAlertService()),
        raise_server_exceptions=False,
    ).get("/api/v1/alerts")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_alert_response_rejects_noncanonical_rendered_message() -> None:
    class _UnsafeAlertService(_FakeAlertOperationService):
        async def list_alerts(self, **kwargs: object) -> object:
            payload = await super().list_alerts(**kwargs)
            event = payload["items"][0]["event"].model_dump(
                mode="python",
                round_trip=True,
            )
            event["message_text"] = "已自动下单。仅提醒，不会自动下单。"
            payload["items"][0]["event"] = event
            return payload

    response = TestClient(
        create_app(alert_service=_UnsafeAlertService()),
        raise_server_exceptions=False,
    ).get("/api/v1/alerts")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_alert_page_rejects_duplicate_sequence_with_distinct_event_ids() -> None:
    class _DuplicateSequenceService(_FakeAlertOperationService):
        async def list_alerts(self, **kwargs: object) -> object:
            payload = await super().list_alerts(**kwargs)
            payload["items"].append(
                _alert_record_payload(
                    event_id="60000000-0000-4000-8000-000000000002",
                    sequence=23,
                )
            )
            payload["total"] = 2
            return payload

    response = TestClient(
        create_app(alert_service=_DuplicateSequenceService()),
        raise_server_exceptions=False,
    ).get("/api/v1/alerts")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_unacknowledged_alert_cannot_claim_acknowledged_revision() -> None:
    class _RevisionDriftService(_FakeAlertOperationService):
        async def list_alerts(self, **kwargs: object) -> object:
            payload = await super().list_alerts(**kwargs)
            payload["items"][0]["revision"] = 1
            return payload

    response = TestClient(
        create_app(alert_service=_RevisionDriftService()),
        raise_server_exceptions=False,
    ).get("/api/v1/alerts")

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_acknowledging_an_already_acknowledged_alert_is_a_revision_noop() -> None:
    service = _FakeAlertOperationService()
    response = TestClient(create_app(alert_service=service)).post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "alert-ack-noop"},
        json={"alertId": _ALERT_ID, "expectedRevision": 1},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 1


def test_position_response_rejects_non_durable_revision_and_closure_drift() -> None:
    class _UnsafePositionService(_FakePositionOperationService):
        async def list_position_lots(self, **kwargs: object) -> object:
            payload = await super().list_position_lots(**kwargs)
            payload["items"][0]["revision"] = 7
            return payload

        async def close_position_lot(self, **kwargs: object) -> object:
            payload = await super().close_position_lot(**kwargs)
            payload["appliedQuantity"] = 200
            return payload

    client = TestClient(
        create_app(position_service=_UnsafePositionService()),
        raise_server_exceptions=False,
    )
    listed = client.get(
        "/api/v1/position-lots",
        params={"symbol": "003043.SZ", "asOfTradeDate": "2026-08-24"},
    )
    closed = client.post(
        "/api/v1/position-lot-closures",
        headers={"Idempotency-Key": "closure-drift"},
        json={
            "lotId": _POSITION_LOT_ID,
            "quantity": 100,
            "tradeDate": "2026-08-24",
            "expectedRevision": 0,
        },
    )

    _assert_error_envelope(listed, status=500, code="INTERNAL_ERROR")
    _assert_error_envelope(closed, status=500, code="INTERNAL_ERROR")


def test_position_closure_response_rejects_same_day_acquisition() -> None:
    class _SameDayClosureService(_FakePositionOperationService):
        async def close_position_lot(self, **kwargs: object) -> object:
            payload = await super().close_position_lot(**kwargs)
            payload["lot"]["acquiredTradeDate"] = date(2026, 8, 24)
            return payload

    response = TestClient(
        create_app(position_service=_SameDayClosureService()),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/position-lot-closures",
        headers={"Idempotency-Key": "same-day-receipt-drift"},
        json={
            "lotId": _POSITION_LOT_ID,
            "quantity": 100,
            "tradeDate": "2026-08-24",
            "expectedRevision": 0,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_diagnostic_response_rejects_evaluation_identity_drift() -> None:
    class _IdentityDriftService(_FakeAlertOperationService):
        async def evaluate_diagnostic(self, **kwargs: object) -> object:
            payload = await super().evaluate_diagnostic(**kwargs)
            result = payload["result"].model_dump(mode="python", round_trip=True)
            result["evaluation_identity"]["bucket_end"] = datetime(
                2026,
                8,
                24,
                10,
                10,
                tzinfo=_SHANGHAI,
            )
            payload["result"] = result
            return payload

    response = TestClient(
        create_app(alert_service=_IdentityDriftService()),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/diagnostic-evaluations",
        headers={"Idempotency-Key": "diagnostic-identity-drift"},
        json={
            "symbol": "003043.SZ",
            "evaluationKind": "INTRADAY",
            "bucketEnd": "2026-08-24T10:05:00+08:00",
            "officialTradeDate": None,
            "expectedRevision": 11,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_diagnostic_response_rejects_a_decision_from_another_target() -> None:
    class _WrongTargetDecisionService(_FakeAlertOperationService):
        async def evaluate_diagnostic(self, **kwargs: object) -> object:
            payload = await super().evaluate_diagnostic(**kwargs)
            payload["result"] = _diagnostic_result(datetime(2026, 8, 24, 10, 5, tzinfo=_SHANGHAI))
            return payload

    response = TestClient(
        create_app(alert_service=_WrongTargetDecisionService()),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/diagnostic-evaluations",
        headers={"Idempotency-Key": "diagnostic-decision-drift"},
        json={
            "symbol": "003043.SZ",
            "evaluationKind": "INTRADAY",
            "bucketEnd": "2026-08-24T10:10:00+08:00",
            "officialTradeDate": None,
            "expectedRevision": 11,
        },
    )

    _assert_error_envelope(response, status=500, code="INTERNAL_ERROR")


def test_t038_idempotency_conflict_mismatch_and_completed_replay_are_stable() -> None:
    class _IdempotentAlertService(_FakeAlertOperationService):
        def __init__(self) -> None:
            super().__init__()
            self.responses: dict[str, object] = {}

        async def acknowledge_alert(self, *, command: object, context: object) -> object:
            key = context.idempotency_key
            self.calls.append((key, command.expected_revision))
            if key == "pending":
                raise ApiError(ApiErrorCode.CONFLICT)
            if key == "reused":
                raise ApiError(ApiErrorCode.VALIDATION_ERROR)
            response = self.responses.setdefault(
                key,
                _alert_record_payload(
                    acknowledged_at=_API_NOW + timedelta(minutes=1),
                ),
            )
            return deepcopy(response)

    service = _IdempotentAlertService()
    client = TestClient(create_app(alert_service=service))
    body = {"alertId": _ALERT_ID, "expectedRevision": 0}

    pending = client.post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "pending"},
        json=body,
    )
    reused = client.post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "reused"},
        json=body,
    )
    first = client.post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "completed"},
        json=body,
    )
    replay = client.post(
        "/api/v1/alert-acknowledgements",
        headers={"Idempotency-Key": "completed"},
        json=body,
    )

    _assert_error_envelope(pending, status=409, code="CONFLICT")
    _assert_error_envelope(reused, status=422, code="VALIDATION_ERROR")
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/position-lots",
            {
                "symbol": "003043.SZ",
                "bucket": "CORE",
                "quantity": 100,
                "acquiredTradeDate": "2026-08-21",
                "costFen": 6_400,
                "expectedRevision": 0,
            },
        ),
        (
            "/api/v1/position-lot-closures",
            {
                "lotId": _POSITION_LOT_ID,
                "quantity": 100,
                "tradeDate": "2026-08-24",
                "expectedRevision": 0,
            },
        ),
        (
            "/api/v1/alert-acknowledgements",
            {"alertId": _ALERT_ID, "expectedRevision": 0},
        ),
        (
            "/api/v1/diagnostic-evaluations",
            {
                "symbol": "003043.SZ",
                "evaluationKind": "INTRADAY",
                "bucketEnd": "2026-08-24T10:05:00+08:00",
                "officialTradeDate": None,
                "expectedRevision": 11,
            },
        ),
    ],
)
def test_t038_mutations_require_idempotency_key(
    path: str,
    body: dict[str, object],
) -> None:
    app = create_app(
        position_service=_FakePositionOperationService(),
        alert_service=_FakeAlertOperationService(),
    )

    response = TestClient(app).post(path, json=body)

    _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/position-lots",
            {
                "symbol": "003043.SZ",
                "bucket": "CORE",
                "quantity": 100,
                "acquiredTradeDate": "2026-08-21",
                "costFen": 6_400,
            },
        ),
        (
            "/api/v1/position-lot-closures",
            {
                "lotId": _POSITION_LOT_ID,
                "quantity": 100,
                "tradeDate": "2026-08-24",
            },
        ),
        (
            "/api/v1/alert-acknowledgements",
            {"alertId": _ALERT_ID},
        ),
        (
            "/api/v1/diagnostic-evaluations",
            {
                "symbol": "003043.SZ",
                "evaluationKind": "INTRADAY",
                "bucketEnd": "2026-08-24T10:05:00+08:00",
                "officialTradeDate": None,
            },
        ),
    ],
)
def test_t038_mutations_require_expected_revision(
    path: str,
    body: dict[str, object],
) -> None:
    position_service = _FakePositionOperationService()
    alert_service = _FakeAlertOperationService()
    app = create_app(
        position_service=position_service,
        alert_service=alert_service,
    )

    response = TestClient(app).post(
        path,
        headers={"Idempotency-Key": "revision-required"},
        json=body,
    )

    error = _assert_error_envelope(response, status=422, code="VALIDATION_ERROR")
    assert any(detail["location"][-1] == "expectedRevision" for detail in error["details"])
    assert position_service.calls == []
    assert alert_service.calls == []


def test_t038_routes_fail_closed_without_their_injected_services() -> None:
    app = create_app()
    client = TestClient(app)

    positions = client.get(
        "/api/v1/position-lots",
        params={"symbol": "003043.SZ", "asOfTradeDate": "2026-08-24"},
    )
    alerts = client.get("/api/v1/alerts")

    _assert_error_envelope(positions, status=503, code="SERVICE_UNAVAILABLE")
    _assert_error_envelope(alerts, status=503, code="SERVICE_UNAVAILABLE")


def test_alert_time_filters_require_one_ordered_pair_before_service_call() -> None:
    service = _FakeAlertOperationService()
    client = TestClient(create_app(alert_service=service))

    partial = client.get(
        "/api/v1/alerts",
        params={"startAt": "2026-08-24T09:30:00+08:00"},
    )
    reversed_range = client.get(
        "/api/v1/alerts",
        params={
            "startAt": "2026-08-24T15:00:00+08:00",
            "endAt": "2026-08-24T09:30:00+08:00",
        },
    )

    _assert_error_envelope(partial, status=400, code="BAD_REQUEST")
    _assert_error_envelope(reversed_range, status=400, code="BAD_REQUEST")
    assert service.calls == []
