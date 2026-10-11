"""ML-T23 generates both closed run/result contracts without granting approval."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts import generate_frontend_types as generator
from tests.integration.test_plan_preparation_contract import resolved

from trade_plan_monitor.web.backtest_schemas import PreparedBacktestRunCommand

MAX_SAFE_INTEGER = 9_007_199_254_740_991
ROOT = Path(__file__).resolve().parents[2]
RUN = "/api/v1/backtest-runs"


@pytest.fixture(scope="module", params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def contract(request):
    return request.param, generator.build_openapi_document(monitor_contract_version=request.param)


def reference_names(schema):
    return {value["$ref"].rsplit("/", 1)[1] for value in schema["anyOf"]}


def test_committed_run_and_result_contracts_match_actual_routes(contract):
    version, document = contract
    snapshot = ROOT / ("openapi.json" if version == 1 else "openapi.runtime-status.json")
    types = (
        ROOT / "web/src/api" / ("generated.ts" if version == 1 else "generated-runtime-status.ts")
    )
    assert json.loads(snapshot.read_text(encoding="utf-8")) == document
    assert types.read_text(encoding="utf-8") == generator.render_typescript_contracts(
        document, monitor_contract_version=version
    )


def test_public_run_commands_and_results_preserve_explicit_legacy_variants(contract):
    _, document = contract
    operation = document["paths"][RUN]["post"]
    command = operation["requestBody"]["content"]["application/json"]["schema"]
    assert reference_names(command) == {
        "BacktestRunCommand",
        "PreparedBacktestRunCommand",
        "ScheduledPreparedBacktestRunCommand",
    }
    for method in ("get", "patch"):
        result = document["paths"][RUN + "/{run_id}"][method]["responses"]["200"]
        assert reference_names(result["content"]["application/json"]["schema"]) == {
            "BacktestRunView",
            "BacktestLoopRunView",
            "BacktestScheduledRunView",
        }
    schemas = document["components"]["schemas"]
    items = schemas["BacktestRunPage"]["properties"]["items"]["items"]
    assert reference_names(items) == {
        "BacktestRunSummaryView",
        "BacktestLoopRunSummaryView",
        "BacktestScheduledRunSummaryView",
    }
    detail = schemas["BacktestDetailPage"]["properties"]["items"]["items"]
    assert "BacktestLoopEventView" in reference_names(resolved(document, detail))
    assert "BacktestScheduledEventView" in reference_names(resolved(document, detail))
    assert schemas["BacktestLoopEventView"]["properties"]["schemaVersion"]["const"] == (
        "monitor-loop-event-v1"
    )
    assert schemas["BacktestLoopRunView"]["properties"]["schemaVersion"]["const"] == (
        "monitor-loop-result-v1"
    )
    kinds = schemas["LoopAuditPayload"]["discriminator"]
    assert kinds["propertyName"] == "kind"
    assert set(kinds["mapping"]) == {
        "EVALUATED",
        "REMINDED",
        "REQUESTED",
        "EXECUTED",
        "STATE",
        "VALUATION",
    }


def test_loop_contracts_keep_bounds_exact_values_and_unknown_facts(contract):
    _, document = contract
    schemas = document["components"]["schemas"]
    for name in ("BacktestRunPage", "BacktestDetailPage", "BacktestFillPage"):
        assert schemas[name]["properties"]["items"]["maxItems"] == 100
        assert schemas[name]["additionalProperties"] is False
    for name in (
        "BacktestLoopRunView",
        "BacktestLoopRunSummaryView",
        "BacktestScheduledRunView",
        "BacktestScheduledRunSummaryView",
    ):
        assert schemas[name]["additionalProperties"] is False
        for field in ("revision", "fillCount"):
            assert schemas[name]["properties"][field]["maximum"] == MAX_SAFE_INTEGER
    opening = schemas["LoopAccountInput"]
    assert opening["properties"]["lots"]["maxItems"] == 200
    assert set(opening["properties"]["cash"]["discriminator"]["mapping"]) == {"KNOWN", "UNKNOWN"}
    metrics = schemas["LoopMetrics"]["properties"]
    for field in ("initial_equity_fen", "final_equity_fen"):
        values = metrics[field]["anyOf"]
        assert values[0]["maximum"] == MAX_SAFE_INTEGER and values[1]["type"] == "null"
    assert metrics["interval_return"]["anyOf"][0]["type"] == "string"
    costs = schemas["BacktestLoopCostsInput"]["properties"]
    assert costs["buySlippageFen"]["maximum"] == MAX_SAFE_INTEGER
    assert costs["commissionRate"]["type"] == "string"
    policy = schemas["BacktestLoopResponseInput"]["properties"]["mode"]
    assert set(policy["enum"]) == {"FOLLOW_REMINDERS", "OBSERVE_ONLY"}
    command = schemas["PreparedBacktestRunCommand"]
    assert "endDate" not in command["required"]
    assert {"planVersionId", "initialCashFen", "initialLots", "actions"}.isdisjoint(
        command["properties"]
    )


def test_result_contract_has_frozen_provenance_without_owned_paths_or_source_text(contract):
    _, document = contract
    schemas = document["components"]["schemas"]
    visited = set()

    def walk(schema):
        if isinstance(schema, dict):
            if "$ref" in schema:
                name = schema["$ref"].rsplit("/", 1)[1]
                assert name in schemas
                if name in visited:
                    return
                visited.add(name)
                walk(resolved(document, schema))
            assert {
                "sourceText",
                "input_json",
                "bundle_hash",
                "filesystem_path",
                "claim_token",
                "owner_token",
                "provider_diagnostics",
            }.isdisjoint(schema.get("properties", {}))
            for value in schema.values():
                walk(value)
        elif isinstance(schema, list):
            for value in schema:
                walk(value)

    walk(schemas["BacktestLoopRunView"])
    assert {"LoopPlanVersion", "LoopAccountInput", "MonitorLoopReport"} <= visited
    assert {"PreparationSource", "StoredLoopInput", "LoopInputReference"}.isdisjoint(visited)
    visited.clear()
    walk(schemas["BacktestScheduledRunView"])
    assert {"BacktestScheduledReportHeader", "LoopAccountInput", "CollectionVersionView"} <= visited
    assert {
        "ScheduledMonitorLoopReport",
        "ScheduledLoopSchedule",
        "PreparationSource",
        "ScheduledStoredLoopInput",
        "LoopInputReference",
    }.isdisjoint(visited)


def test_scheduled_contract_header_preserves_native_fields_without_full_snapshots(contract):
    from trade_plan_monitor.backtest.loop_report import ScheduledMonitorLoopReport

    _, document = contract
    schemas = document["components"]["schemas"]
    header = schemas["BacktestScheduledReportHeader"]["properties"]
    assert set(header) == (
        set(ScheduledMonitorLoopReport.model_fields)
        - {
            "schema_version",
            "schedule",
        }
    ) | {"report_schema_version"}
    assert header["report_schema_version"]["const"] == "backtest-report-v5"
    command = schemas["ScheduledPreparedBacktestRunCommand"]
    assert "schemaVersion" in command["required"]
    assert command["properties"]["schemaVersion"]["const"] == "prepared-loop-plan-v2"
    root = schemas["BacktestScheduledRunView"]
    assert root["properties"]["schemaVersion"]["const"] == "monitor-loop-result-v2"
    assert root["properties"]["versions"]["maxItems"] == 256
    assert schemas["BacktestScheduledEventView"]["properties"]["schemaVersion"]["const"] == (
        "monitor-loop-event-v2"
    )


def test_generated_types_narrow_native_events_and_old_new_results(contract, tmp_path):
    version, document = contract
    node = shutil.which("node")
    compiler = ROOT / "web/node_modules/typescript/bin/tsc"
    assert node and compiler.is_file()
    (tmp_path / "generated.ts").write_text(
        generator.render_typescript_contracts(document, monitor_contract_version=version),
        encoding="utf-8",
    )
    imports = 'import type { components, paths } from "./generated";\n'
    positive = (
        imports
        + """
type ReadOperation = paths["/api/v1/backtest-runs/{run_id}"]["get"];
type Read = ReadOperation["responses"][200]["content"]["application/json"];
export function metric(value: Read): number | string | null {
  if ("schemaVersion" in value) {
    if (value.schemaVersion === "monitor-loop-result-v2") {
      const reportVersion: "backtest-report-v5" = value.report.report_schema_version;
      return value.versions.length + value.provenance.sources.length;
    }
    const version: "monitor-loop-result-v1" = value.schemaVersion;
    const reportVersion: "backtest-report-v4" = value.report.schema_version ?? "backtest-report-v4";
    return value.metrics.final_equity_fen;
  }
  return value.metrics.finalEquityFen;
}
export function event(value: components["schemas"]["LoopAuditPayload"]): string {
  switch (value.kind) {
    case "EVALUATED": return value.kind;
    case "REMINDED": return value.kind;
    case "REQUESTED": return value.kind;
    case "EXECUTED": return value.attempt.status;
    case "STATE": return value.kind;
    case "VALUATION": return value.kind;
    default: { const impossible: never = value; return impossible; }
  }
}
export const prepared: components["schemas"]["PreparedBacktestRunCommand"] = {
  preparationId: "p1", manifestHash: "a".repeat(64),
  response: { mode: "OBSERVE_ONLY", responseDelaySeconds: 0 },
  costs: { commissionRate: "0.0003", minimumCommissionFen: 500,
    stampDutyRate: "0.0005", transferFeeRate: "0.00001", buySlippageFen: 1, sellSlippageFen: 1 }
};
export const scheduled: components["schemas"]["ScheduledPreparedBacktestRunCommand"] = {
  ...prepared, schemaVersion: "prepared-loop-plan-v2"
};
"""
    )
    source = tmp_path / "probe.ts"

    def compile_text(value):
        source.write_text(value, encoding="utf-8")
        return subprocess.run(
            [
                node,
                str(compiler),
                "--strict",
                "--noEmit",
                "--skipLibCheck",
                "--target",
                "ES2022",
                "--types",
                "node",
                "--typeRoots",
                str(ROOT / "web/node_modules/@types"),
                str(source),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    valid = compile_text(positive)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    for invalid in (
        'const mode: components["schemas"]["BacktestLoopResponseInput"] = '
        '{ mode: "RECORDED_ACTIONS", responseDelaySeconds: 0 };',
        'const version: components["schemas"]["BacktestLoopEventView"]["schemaVersion"] = "old";',
        'const cash: components["schemas"]["UnknownLoopCash"] = '
        '{ kind: "UNKNOWN", balance_fen: 0 };',
    ):
        result = compile_text(imports + invalid)
        assert result.returncode != 0 and "error TS" in result.stdout


def test_prepared_command_rejects_unsafe_cash_and_recorded_public_policy():
    payload = {
        "preparationId": "p1",
        "manifestHash": "a" * 64,
        "response": {"mode": "OBSERVE_ONLY", "responseDelaySeconds": 0},
        "costs": {
            "commissionRate": "0.0003",
            "minimumCommissionFen": 500,
            "stampDutyRate": "0.0005",
            "transferFeeRate": "0.00001",
            "buySlippageFen": 1,
            "sellSlippageFen": 1,
        },
    }
    assert PreparedBacktestRunCommand.model_validate(payload).end_date is None
    for changed in (
        payload | {"initialCashFen": 1},
        payload | {"plans": ["one", "two"]},
        payload | {"response": {"mode": "RECORDED_ACTIONS", "responseDelaySeconds": 0}},
        payload | {"costs": payload["costs"] | {"buySlippageFen": MAX_SAFE_INTEGER + 1}},
    ):
        with pytest.raises(ValidationError):
            PreparedBacktestRunCommand.model_validate(changed)
