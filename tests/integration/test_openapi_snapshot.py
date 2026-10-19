from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = PROJECT_ROOT / "scripts" / "generate_frontend_types.py"
OPENAPI_PATH = PROJECT_ROOT / "openapi.json"
TYPESCRIPT_PATH = PROJECT_ROOT / "web" / "src" / "api" / "generated.ts"
SPA_ENTRY_PATH = PROJECT_ROOT / "web" / "index.html"
LOCAL_WEB_SPEC_PATH = (
    PROJECT_ROOT / "docs" / "specifications" / "monitoring" / "SPEC-unified-plan.md"
)
LOCAL_WEB_SPEC_ZH_PATH = (
    PROJECT_ROOT / "docs" / "specifications" / "monitoring" / "SPEC-unified-plan.zh-CN.md"
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991

APPROVED_PATHS = {
    "/api/v1/ai-runtime",
    "/api/v1/ai-providers",
    "/api/v1/alert-acknowledgements",
    "/api/v1/alerts",
    "/api/v1/backtest-data-syncs",
    "/api/v1/backtest-dataset-verifications",
    "/api/v1/backtest-datasets",
    "/api/v1/backtest-datasets/{dataset_hash}",
    "/api/v1/backtest-datasets/{dataset_hash}/reference-market-coverage",
    "/api/v1/backtest-job-cancellations",
    "/api/v1/backtest-jobs",
    "/api/v1/backtest-jobs/{job_id}",
    "/api/v1/backtest-plan-library",
    "/api/v1/backtest-plan-library/preparations",
    "/api/v1/backtest-plan-library/compositions",
    "/api/v1/backtest-preparations",
    "/api/v1/backtest-preparations/{preparation_id}",
    "/api/v1/backtest-preparations/{preparation_id}/cancellations",
    "/api/v1/backtest-preparations/{preparation_id}/extractions",
    "/api/v1/backtest-preparations/{preparation_id}/items",
    "/api/v1/backtest-preparations/{preparation_id}/recoveries",
    "/api/v1/backtest-preparations/{preparation_id}/reviews",
    "/api/v1/backtest-preparations/{preparation_id}/source",
    "/api/v1/backtest-runs",
    "/api/v1/backtest-run-data",
    "/api/v1/backtest-runs/{run_id}",
    "/api/v1/backtest-runs/{run_id}/details",
    "/api/v1/backtest-runs/{run_id}/equity-series",
    "/api/v1/backtest-runs/{run_id}/exports/{export_kind}",
    "/api/v1/backtest-runs/{run_id}/fills",
    "/api/v1/backtest-runs/{run_id}/market-index-series",
    "/api/v1/backtest-runs/{run_id}/rule-changes/{source_id}",
    "/api/v1/backtest-service",
    "/api/v1/backtest-service/recovery-requests",
    "/api/v1/backtest-service/stop-requests",
    "/api/v1/dashboard",
    "/api/v1/simulated-trades",
    "/api/v1/plan-editor-schema",
    "/api/v1/plan-facts",
    "/api/v1/plan-review-previews",
    "/api/v1/plan-review-supplements",
    "/api/v1/plan-runtime/{symbol}",
    "/api/v1/simulation-position-confirmations",
    "/api/v1/simulation-position-inventory",
    "/api/v1/plan-risk-reassessments",
    "/api/v1/diagnostic-evaluations",
    "/api/v1/health",
    "/api/v1/health/symbols/{symbol}",
    "/api/v1/manual-event-risk",
    "/api/v1/market-indexes/{indexCode}/bars",
    "/api/v1/market-indexes/overview",
    "/api/v1/plan-activation-states/{symbol}",
    "/api/v1/plan-activations",
    "/api/v1/plan-capabilities",
    "/api/v1/plan-deactivations",
    "/api/v1/plan-drafts",
    "/api/v1/plan-extractions",
    "/api/v1/plan-extractions/{operation_id}",
    "/api/v1/plan-imports",
    "/api/v1/plan-review-confirmations",
    "/api/v1/plan-versions",
    "/api/v1/plan-versions/{version_id}",
    "/api/v1/position-lots",
    "/api/v1/position-inventory",
    "/api/v1/symbols",
    "/api/v1/symbols/{symbol}",
    "/api/v1/symbols/{symbol}/bars",
    "/api/v1/symbols/{symbol}/events",
    "/api/v1/system/legacy-plan-invalidation",
}
PUBLIC_ERROR_STATUSES = {
    "400",
    "401",
    "403",
    "404",
    "405",
    "409",
    "413",
    "422",
    "429",
    "500",
    "503",
}
PUBLIC_ERROR_SCHEMAS = {
    "ApiErrorCode",
    "ErrorDetail",
    "ErrorPayload",
    "ErrorResponse",
}


def _load_generator() -> ModuleType:
    assert GENERATOR_PATH.is_file(), "T041 generator is not implemented"
    spec = importlib.util.spec_from_file_location("generate_frontend_types", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generated_documents() -> tuple[ModuleType, str, str]:
    generator = _load_generator()
    document = generator.build_openapi_document()
    return (
        generator,
        generator.render_openapi_snapshot(document),
        generator.render_typescript_contracts(document),
    )


def test_openapi_snapshot_is_deterministic_canonical_and_current() -> None:
    generator, snapshot, _typescript = _generated_documents()

    assert snapshot == generator.render_openapi_snapshot(generator.build_openapi_document())
    assert snapshot.endswith("\n")
    assert (
        snapshot
        == json.dumps(
            json.loads(snapshot),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    assert OPENAPI_PATH.read_text(encoding="utf-8") == snapshot


def test_openapi_change_requires_bilingual_spec_approval() -> None:
    _generator, snapshot, _typescript = _generated_documents()
    digest = sha256(snapshot.encode("utf-8")).hexdigest()

    assert f"OpenAPI snapshot SHA-256: `{digest}`" in LOCAL_WEB_SPEC_PATH.read_text(
        encoding="utf-8"
    )
    assert f"OpenAPI 快照 SHA-256：`{digest}`" in LOCAL_WEB_SPEC_ZH_PATH.read_text(encoding="utf-8")


def test_openapi_contains_only_approved_paths_and_public_error_schemas() -> None:
    generator = _load_generator()
    document = generator.build_openapi_document()

    assert set(document["paths"]) == APPROVED_PATHS
    schemas = document["components"]["schemas"]
    assert PUBLIC_ERROR_SCHEMAS <= set(schemas)
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas

    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "patch", "post"}:
                continue
            responses = operation["responses"]
            assert PUBLIC_ERROR_STATUSES <= set(responses)
            for status_code in PUBLIC_ERROR_STATUSES:
                schema = responses[status_code]["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_plan_contract_exposes_server_versioning_and_lightweight_summaries() -> None:
    document = _load_generator().build_openapi_document()
    schemas = document["components"]["schemas"]

    draft = schemas["PlanDraftCommand"]
    assert "basePlanVersionId" in draft["properties"]
    assert "basePlanVersionId" not in draft["required"]

    imported = schemas["PlanImportCommand"]
    assert "symbol" in imported["required"]

    page = schemas["PlanVersionPage"]
    assert page["properties"]["items"]["items"] == {
        "$ref": "#/components/schemas/PlanVersionSummary"
    }
    summary_fields = set(schemas["PlanVersionSummary"]["properties"])
    assert summary_fields == {
        "obsoleteReason",
        "canActivate",
        "createdAt",
        "id",
        "planHash",
        "planId",
        "revision",
        "status",
        "symbol",
        "version",
    }
    detail_only_fields = {
        "planJson",
        "reviewIssues",
        "sourceText",
        "validationIssues",
    }
    assert detail_only_fields <= set(schemas["PlanVersionView"]["properties"])
    assert detail_only_fields.isdisjoint(summary_fields)
    assert schemas["PlanVersionSummary"]["properties"]["version"]["maximum"] == (MAX_SAFE_INTEGER)
    assert schemas["PlanVersionSummary"]["properties"]["revision"]["maximum"] == (MAX_SAFE_INTEGER)
    assert draft["properties"]["expectedRevision"]["maximum"] == MAX_SAFE_INTEGER
    assert imported["properties"]["expectedRevision"]["maximum"] == MAX_SAFE_INTEGER
    assert schemas["PlanActivationCommand"]["properties"]["expectedRevision"]["maximum"] == (
        MAX_SAFE_INTEGER - 2
    )
    assert schemas["PlanDeactivationCommand"]["properties"]["expectedRevision"]["maximum"] == (
        MAX_SAFE_INTEGER - 1
    )
    assert schemas["ActivePlanView"]["properties"]["revision"]["maximum"] == (MAX_SAFE_INTEGER)


def test_typescript_contract_is_generated_from_the_snapshot() -> None:
    _generator, _snapshot, typescript = _generated_documents()

    assert TYPESCRIPT_PATH.read_text(encoding="utf-8") == typescript
    assert "export interface components" in typescript
    assert "export interface paths" in typescript
    assert "This file is generated from openapi.json" in typescript
    assert "HTTPValidationError" not in typescript


def test_typescript_parameter_group_is_required_when_any_member_is_required() -> None:
    generator = _load_generator()
    typescript = generator.render_typescript_contracts(
        {
            "components": {"schemas": {}},
            "paths": {
                "/probe": {
                    "get": {
                        "parameters": [
                            {
                                "in": "query",
                                "name": "requiredValue",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                            {
                                "in": "query",
                                "name": "optionalValue",
                                "required": False,
                                "schema": {"type": "integer"},
                            },
                        ],
                        "responses": {"204": {"description": "No Content"}},
                    }
                }
            },
        }
    )

    assert "      query: {" in typescript
    assert "      query?: {" not in typescript
    assert "        requiredValue: string;" in typescript
    assert "        optionalValue?: number;" in typescript


@pytest.mark.parametrize("reserved_name", ["export", "string"])
def test_typescript_schema_names_reject_reserved_identifiers(reserved_name: str) -> None:
    generator = _load_generator()

    with pytest.raises(ValueError, match="not a usable TypeScript identifier"):
        generator.render_typescript_contracts(
            {
                "components": {"schemas": {reserved_name: {"type": "string"}}},
                "paths": {},
            }
        )


def test_generator_check_detects_snapshot_and_type_drift(tmp_path: Path) -> None:
    generator, snapshot, typescript = _generated_documents()
    snapshot_path = tmp_path / "openapi.json"
    typescript_path = tmp_path / "generated.ts"
    snapshot_path.write_text("{}\n", encoding="utf-8")
    typescript_path.write_text("// stale\n", encoding="utf-8")

    assert generator.find_stale_outputs(
        snapshot=snapshot,
        typescript=typescript,
        snapshot_path=snapshot_path,
        typescript_path=typescript_path,
    ) == (snapshot_path, typescript_path)

    snapshot_path.write_bytes(snapshot.encode("utf-8"))
    typescript_path.write_bytes(typescript.encode("utf-8"))
    assert (
        generator.find_stale_outputs(
            snapshot=snapshot,
            typescript=typescript,
            snapshot_path=snapshot_path,
            typescript_path=typescript_path,
        )
        == ()
    )


def test_generator_check_command_passes_for_committed_outputs() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stdout + result.stderr


class _SpaEntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_language: str | None = None
        self.app_roots = 0
        self.module_scripts: list[str | None] = []
        self.inline_style_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.html_language = attributes.get("lang")
        elif tag == "div" and attributes.get("id") == "app":
            self.app_roots += 1
        elif tag == "script":
            assert attributes.get("type") == "module"
            self.module_scripts.append(attributes.get("src"))
        elif tag == "style":
            self.inline_style_count += 1


def test_spa_document_is_a_stable_csp_compatible_vite_entry() -> None:
    document = SPA_ENTRY_PATH.read_text(encoding="utf-8")
    parser = _SpaEntryParser()
    parser.feed(document)

    assert document.startswith("<!doctype html>\n")
    assert '<meta charset="UTF-8">' in document
    assert 'name="viewport"' in document
    assert parser.html_language == "zh-CN"
    assert parser.app_roots == 1
    assert parser.module_scripts == ["/src/runtime-status/main.ts"]
    assert parser.inline_style_count == 0


@pytest.mark.parametrize("path", [OPENAPI_PATH, TYPESCRIPT_PATH, SPA_ENTRY_PATH])
def test_generated_contract_outputs_use_lf_and_end_with_newline(path: Path) -> None:
    content = path.read_bytes()

    assert content.endswith(b"\n")
    assert b"\r\n" not in content
