"""The opt-in v2 boundary rejects incompatible clients before any service work."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from trade_plan_monitor.web.app import create_app

READ_PATHS = (
    "/api/v1/health", "/api/v1/health/symbols/003043.SZ", "/api/v1/dashboard",
    "/api/v1/symbols", "/api/v1/symbols/003043.SZ",
    "/api/v1/explicit-plan-runtime/003043.SZ",
)
WRITE_PATHS = tuple(f"/api/v1/{name}" for name in (
    "plan-activations", "plan-deactivations", "position-lots", "position-lot-closures",
    "position-inventory-closures", "position-inventory-confirmations",
    "manual-event-risk-confirmations", "alert-acknowledgements", "diagnostic-evaluations",
    "system/legacy-plan-invalidation",
))


class UntouchedService:
    monitor_contract_version = 2

    def __getattr__(self, name):
        raise AssertionError(f"incompatible request reached service: {name}")


def client_v2():
    service = UntouchedService()
    return TestClient(create_app(
        monitor_contract_version=2, read_service=service, plan_service=service,
        position_service=service, alert_service=service, ai_service=service,
        manual_event_risk_service=service,
    ))


@pytest.mark.parametrize("method,path", [
    *(("GET", path) for path in READ_PATHS), *(("POST", path) for path in WRITE_PATHS),
])
@pytest.mark.parametrize("version_headers", [
    [], [("X-Monitor-Contract-Version", "1")], [("X-Monitor-Contract-Version", "02")],
    [("X-Monitor-Contract-Version", "2,2")],
    [("X-Monitor-Contract-Version", "2"), ("X-Monitor-Contract-Version", "2")],
])
def test_incompatible_requests_never_reach_services(method, path, version_headers):
    response = client_v2().request(
        method, path, headers=[("Origin", "http://127.0.0.1:8765"), *version_headers],
        content=b"invalid-json" if method == "POST" else None,
    )
    assert response.status_code == 409
    assert response.headers["X-Monitor-Contract-Version"] == "2"
    assert response.headers["Cache-Control"] == "no-store"
    error = response.json()["error"]
    assert error["code"] == "CONFLICT"
    assert error["requestId"] == response.headers["X-Request-ID"]
    assert error["details"] == [{
        "location": ["header", "X-Monitor-Contract-Version"],
        "code": "MONITOR_CONTRACT_MISMATCH",
        "message": "Reload the application to use monitor contract 2",
    }]


def test_origin_is_still_checked_before_protocol():
    response = client_v2().post(
        WRITE_PATHS[0], headers={"Origin": "https://untrusted.example"}, json={},
    )
    assert response.status_code == 403
    assert response.headers["X-Monitor-Contract-Version"] == "2"


def test_v2_requires_explicit_authoritative_read_service():
    with pytest.raises(ValueError, match="read service"):
        create_app(monitor_contract_version=2)


def test_default_application_keeps_v1_negotiation():
    response = TestClient(create_app()).get("/api/v1/health")
    assert response.status_code == 503
    assert "X-Monitor-Contract-Version" not in response.headers


@pytest.mark.parametrize("version", [0, 3, True, "2"])
def test_factory_rejects_unsupported_protocol(version):
    with pytest.raises(ValueError, match="monitor contract"):
        create_app(monitor_contract_version=version)


def test_static_assets_must_match_selected_protocol(tmp_path):
    (tmp_path / "index.html").write_text("<html>preview</html>", encoding="utf-8")
    (tmp_path / "monitor-contract.json").write_text(
        json.dumps({"monitorContractVersion": 2}), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="assets"):
        create_app(static_directory=tmp_path)
    create_app(
        monitor_contract_version=2, read_service=UntouchedService(), static_directory=tmp_path,
    )


def test_preview_requires_manifest(tmp_path):
    (tmp_path / "index.html").write_text("<html>preview</html>", encoding="utf-8")
    with pytest.raises(ValueError, match="assets"):
        create_app(
            monitor_contract_version=2, read_service=UntouchedService(), static_directory=tmp_path,
        )


def test_unexpected_errors_retain_version_and_no_store():
    class FailedService:
        monitor_contract_version = 2

        async def get_health(self):
            raise RuntimeError("private diagnostic")

    client = TestClient(create_app(
        monitor_contract_version=2, read_service=FailedService(),
    ), raise_server_exceptions=False)
    response = client.get("/api/v1/health", headers={"X-Monitor-Contract-Version": "2"})
    assert response.status_code == 500
    assert response.headers["X-Monitor-Contract-Version"] == "2"
    assert response.headers["Cache-Control"] == "no-store"
    assert "private diagnostic" not in response.text


@pytest.mark.parametrize("query", [
    "after=0", "after=0&monitorContractVersion=1", "after=0&monitorContractVersion=02",
    "after=0&monitorContractVersion=2&monitorContractVersion=2",
])
def test_incompatible_socket_rejected_before_service(query):
    with pytest.raises(WebSocketDisconnect) as error:
        with client_v2().websocket_connect(
            f"/ws/v1/monitor?{query}", headers={"Origin": "http://127.0.0.1:8765"},
        ) as socket:
            socket.receive_json()
    assert error.value.code == 1008
    assert error.value.reason == "MONITOR_CONTRACT_MISMATCH"


def test_compatible_socket_missing_service_retains_1013():
    with pytest.raises(WebSocketDisconnect) as error:
        with client_v2().websocket_connect(
            "/ws/v1/monitor?after=0&monitorContractVersion=2",
            headers={"Origin": "http://127.0.0.1:8765"},
        ) as socket:
            socket.receive_json()
    assert error.value.code == 1013
