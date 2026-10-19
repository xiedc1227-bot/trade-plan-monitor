"""Both mounted contract profiles publish lifecycle transport without approving it."""

import json
import subprocess
from pathlib import Path

import pytest
from scripts import generate_frontend_types as generator
from tests.integration.test_plan_preparation_contract import resolved

ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/backtest-service"


@pytest.fixture(params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def contract(request):
    return request.param, generator.build_openapi_document(monitor_contract_version=request.param)


def test_generated_documents_and_types_match_mounted_service_routes(contract):
    version, document = contract
    snapshot = "openapi.json" if version == 1 else "openapi.runtime-status.json"
    types = "generated.ts" if version == 1 else "generated-runtime-status.ts"
    assert json.loads((ROOT / snapshot).read_text(encoding="utf-8")) == document
    assert (ROOT / "web/src/api" / types).read_text(encoding="utf-8") == (
        generator.render_typescript_contracts(document, monitor_contract_version=version)
    )
    paths = document["paths"]
    assert set(paths[BASE]) == {"get"}
    for path in (BASE + "/recovery-requests", BASE + "/stop-requests"):
        operation = paths[path]["post"]
        assert "202" in operation["responses"] and "200" not in operation["responses"]
        assert operation["responses"]["202"]["headers"]["Retry-After"]["schema"]["const"] == 1
        assert operation["responses"]["202"]["headers"]["Location"]["schema"]["const"] == BASE
        headers = {value["name"] for value in operation["parameters"] if value["in"] == "header"}
        assert "Idempotency-Key" in headers
        for status in ("409", "422", "503"):
            assert operation["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }


def test_lifecycle_values_and_explicit_resume_bounds_are_closed(contract):
    _, document = contract
    schemas = document["components"]["schemas"]
    recovery = schemas["BacktestServiceRecoveryCommand"]
    assert recovery["additionalProperties"] is False
    assert set(recovery["required"]) == {"epoch", "expectedRevision", "action", "resumeJobIds"}
    assert recovery["properties"]["resumeJobIds"]["maxItems"] == 1
    assert recovery["properties"]["expectedRevision"]["maximum"] == 9_007_199_254_740_991
    assert recovery["properties"]["epoch"]["pattern"] == r"^[0-9a-f]{32}$"
    assert set(recovery["properties"]["action"]["enum"]) == {"RESUME_JOBS", "RETRY_PREPARATION"}
    view = schemas["BacktestServiceView"]
    assert view["additionalProperties"] is False
    assert set(resolved(document, view["properties"]["state"])["enum"]) == {
        "DISABLED",
        "NOT_INITIALIZED",
        "STARTING",
        "READ_READY",
        "READY",
        "RECOVERING",
        "DEGRADED",
        "STOPPING",
        "STOPPED",
    }
    assert all(
        view["properties"][field]["type"] == "boolean"
        for field in ("canRead", "canSubmit", "canCancel", "canExport", "physicallyDrained")
    )


def test_all_prior_routes_and_schemas_preserve_their_mounted_meaning(contract):
    version, document = contract
    snapshot = "openapi.json" if version == 1 else "openapi.runtime-status.json"
    # The last pre-reuse contract already contains preparation/data and lifecycle APIs.
    before = json.loads(subprocess.check_output(["git", "show", f"81aae039:{snapshot}"], cwd=ROOT))
    assert set(document["paths"]) - set(before["paths"]) == {
        "/api/v1/backtest-plan-selections",
        "/api/v1/backtest-plan-selections/{selection_id}",
    }
    assert set(before["paths"]) - set(document["paths"]) == {"/api/v1/plan-imports"}

    def without_workbench(schema):
        if isinstance(schema, list):
            return [without_workbench(item) for item in schema]
        if not isinstance(schema, dict):
            return schema
        result = {key: without_workbench(value) for key, value in schema.items()}
        alternatives = schema.get("anyOf", [])
        prior = [item for item in alternatives
                 if not item.get("$ref", "").startswith("#/components/schemas/Workbench")]
        if len(prior) != len(alternatives):
            if len(prior) == 1:
                return prior[0]
            result["anyOf"] = prior
        return result

    for path, operation in before["paths"].items():
        if path == "/api/v1/plan-imports":
            continue
        current = without_workbench(document["paths"][path])
        if path == "/api/v1/backtest-run-data":
            parameters = current["get"]["parameters"]
            current["get"]["parameters"] = [
                parameter for parameter in parameters
                if parameter["name"] not in {"selectionId", "selectionHash"}
            ]
            for parameter in current["get"]["parameters"]:
                if parameter["name"] in {"preparationId", "manifestHash"}:
                    schema = parameter["schema"]
                    parameter["required"] = True
                    parameter["schema"] = schema["anyOf"][0] | {"title": schema["title"]}
        assert current == operation, path
    assert set(before["components"]["schemas"]) - set(document["components"]["schemas"]) == {
        "PlanDocumentFormat", "PlanImportCommand",
    }
    for name, schema in before["components"]["schemas"].items():
        if name in {"PlanDocumentFormat", "PlanImportCommand"}:
            continue
        assert document["components"]["schemas"][name] == schema, name
