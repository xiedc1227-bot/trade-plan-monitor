"""The opt-in routes publish v2 models without changing default v1 routes."""

from fastapi.testclient import TestClient
from scripts.generate_frontend_types import build_openapi_document, render_typescript_contracts

from trade_plan_monitor.web.app import create_app


class ReadService:
    monitor_contract_version = 2

    async def get_dashboard(self):
        return {
            "monitorContractVersion": 2,
            "runtimeGeneration": None,
            "observedAt": "2026-09-27T12:00:00.000000+08:00",
            "runtimeStatus": {
                "lifecycle": "STOPPED",
                "mode": "BLOCKED",
                "reasonCode": "RUNTIME_STOPPED",
                "nextWakeAt": None,
                "nextRetryAt": None,
                "lastProgressAt": None,
                "coordinator": {"state": "STOPPED", "progressDueAt": None},
                "scopes": [],
            },
            "sequence": 0,
            "counts": {
                "actionable": 0,
                "blocked": 0,
                "risk": 0,
                "stale": 0,
                "lowZoneWatch": 0,
                "normal": 0,
            },
            "symbols": [],
            "marketIndexes": [],
            "marketTurnover": None,
        }


def test_v2_dashboard_uses_its_closed_model_and_retains_nulls():
    service = ReadService()
    client = TestClient(create_app(monitor_contract_version=2, read_service=service))
    response = client.get("/api/v1/dashboard", headers={"X-Monitor-Contract-Version": "2"})
    assert response.status_code == 200, response.text
    assert response.json()["runtimeGeneration"] is None
    assert response.json()["marketTurnover"] is None
    assert response.json()["observedAt"] == "2026-09-27T12:00:00.000000+08:00"


def test_v2_openapi_replaces_current_monitor_read_operations():
    old = create_app().openapi()
    new = create_app(monitor_contract_version=2, read_service=ReadService()).openapi()
    expected = {
        "/api/v1/dashboard": "RuntimeDashboardResponse",
        "/api/v1/health": "RuntimeHealthV2Response",
        "/api/v1/health/symbols/{symbol}": "RuntimeSymbolHealthResponse",
        "/api/v1/symbols": "RuntimeSymbolCollectionResponse",
    }
    for path, model in expected.items():
        schema = new["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert schema["$ref"] == f"#/components/schemas/{model}"
    assert (
        old["paths"]["/api/v1/plan-activations"]["post"]["requestBody"]
        == (new["paths"]["/api/v1/plan-activations"]["post"]["requestBody"])
    )
    assert (
        old["paths"]["/api/v1/symbols/{symbol}/bars"]
        == new["paths"]["/api/v1/symbols/{symbol}/bars"]
    )


def test_v2_generator_includes_control_frames_without_extra_public_routes():
    old = build_openapi_document()
    new = build_openapi_document(monitor_contract_version=2)
    assert set(old["paths"]) == set(new["paths"])
    assert "RuntimeHeartbeatFrame" in new["components"]["schemas"]
    assert "RuntimeSnapshotRequiredFrame" in new["components"]["schemas"]
    output = render_typescript_contracts(new, monitor_contract_version=2)
    assert "openapi.runtime-status.json" in output.splitlines()[0]
    assert "export type RuntimeHeartbeatFrame" in output


def test_v2_openapi_declares_required_negotiation_and_response_headers():
    from trade_plan_monitor.web.monitor_contract import is_guarded_monitor_request

    document = create_app(monitor_contract_version=2, read_service=ReadService()).openapi()
    guarded = set()
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if is_guarded_monitor_request({"type": "http", "method": method.upper(), "path": path}):
                guarded.add((path, method))
                assert {
                    "name": "X-Monitor-Contract-Version",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "const": "2"},
                } in operation["parameters"]
                for response in operation["responses"].values():
                    assert (
                        response["headers"]["X-Monitor-Contract-Version"]["schema"]["const"] == "2"
                    )
    assert guarded == {
        (path, "get")
        for path in (
            "/api/v1/dashboard",
            "/api/v1/health",
            "/api/v1/health/symbols/{symbol}",
            "/api/v1/symbols",
            "/api/v1/symbols/{symbol}",
        )
    } | {
        (path, "post")
        for path in (
            "/api/v1/plan-activations",
            "/api/v1/plan-deactivations",
            "/api/v1/system/legacy-plan-invalidation",
            "/api/v1/alert-acknowledgements",
            "/api/v1/diagnostic-evaluations",
        )
    }
