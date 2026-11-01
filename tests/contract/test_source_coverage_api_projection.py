"""Both current coverage profiles preserve the exact approved older projection.

The historical digests belong to U-MLP3; this test never updates them. Current
source fields describe observations, not client-issued review/action authority.
"""

import json
import shutil
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from scripts import generate_frontend_types as generator

ROOT = Path(__file__).resolve().parents[2]
COVERAGE_PATH = "/api/v1/plan-versions/{version_id}/source-coverage"
LEGACY_HASHES = {
    1: ("4bd255a77fe39fb647a0475df4368bf5c32ff04c8da2ad8416f45fafdb32d148",
        "d76bca93615eb6c82c479228404916b5f70e26303cb11eef764f511e303c5ad6"),
    2: ("076ca6e32306c7cbe1fc3b2b2788ded8a36d823fe93d901fdefaa479b9e78c46",
        "24d090d32d7ed32b15c98c7b4efc695f017364b724022acccaad0922f0a49829"),
}
PRIOR_COVERAGE_HASHES = {
    1: ("c426102e7f9815b549a463a4fb4c38ec3c15c97213cd09864e65147a9a935cd7",
        "7db80baf8b0a53b837795ac1a0ae0bb8362c390af491068d5bbfc2a201d45256"),
    2: ("0361f3b1b69a23399ee8e3ec89cce87ef832c04980e7bcc88aeba72b2c0fd1f9",
        "8fdce46fec658cacfb7b782bcc91163c1ec0fa4b02d441c5d3c7356d114b5ddc"),
}
SOURCE_FIELDS = {
    "SourceCoveragePage": "authorityGranted planVersionId summary items limit returnedCount "
        "totalRows nextCursor",
    "SourceCoverageSummaryView": "status authorityGranted coverageComplete currentReviewBound "
        "canConfirmReview reviewState reason sourceHash candidatePlanHash contentHash mappingHash "
        "rulesVersion coverageEvidenceHash coverageRevision coverageBundleHash normalizationHash "
        "originalReviewEvidenceHash reviewId reviewRevision coverageReviewReceiptHash origin "
        "automaticFidelityVerified obligationCount issueCount normalizationChangeCount totalRows",
    "SourceObligationView": "version rulesVersion sourceHash clauseId start end excerpt kind scope "
        "serverState semanticsJson groupId relationIds paths obligationId mappingProposal "
        "humanSupplements",
    "SourceCoverageIssueView": "code path start end message",
    "SourceMappingProposalView": "proposedDisposition semanticRole reason proposedPaths",
    "SourceHumanSupplementLinkView": "supplementId path candidateContentHash",
    "SourceNormalizationChangeView": "path beforeJson afterJson reason traceRole sourceHash "
        "beforeHash afterHash evidenceHash",
    "SourceObligationRow": "kind rowIndex obligation",
    "SourceIssueRow": "kind rowIndex issue",
    "SourceNormalizationRow": "kind rowIndex change",
}


@pytest.fixture(scope="module", params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def contract(request):
    return request.param, generator.build_openapi_document(monitor_contract_version=request.param)


def _nullable_value(schema):
    assert len(schema["anyOf"]) == 2 and schema["anyOf"][1] == {"type": "null"}
    return schema["anyOf"][0]


def _assert_source_surface(document):
    schemas = document["components"]["schemas"]
    # Explicit names/fields, never a broad Source* or optional-property waiver.
    for name, fields in SOURCE_FIELDS.items():
        assert set(schemas[name]["properties"]) == set(fields.split()), name
        assert schemas[name]["additionalProperties"] is False
    for name in ("SourceCoveragePage", "SourceCoverageSummaryView"):
        flag = schemas[name]["properties"]["authorityGranted"]
        assert flag == {"const": False, "default": False, "title": "Authoritygranted",
                        "type": "boolean"}
    page = schemas["SourceCoveragePage"]["properties"]
    assert page["items"]["maxItems"] == 100
    assert page["limit"]["minimum"] == 1 and page["limit"]["maximum"] == 100
    assert _nullable_value(page["nextCursor"])["maxLength"] == 512
    union = page["items"]["items"]
    assert union["discriminator"] == dict(propertyName="kind", mapping={
        "OBLIGATION": "#/components/schemas/SourceObligationRow",
        "ISSUE": "#/components/schemas/SourceIssueRow",
        "NORMALIZATION_CHANGE": "#/components/schemas/SourceNormalizationRow"})
    assert union["oneOf"] == [
        {"$ref": "#/components/schemas/SourceObligationRow"},
        {"$ref": "#/components/schemas/SourceIssueRow"},
        {"$ref": "#/components/schemas/SourceNormalizationRow"}]
    obligation = schemas["SourceObligationView"]["properties"]
    for name in ("start", "end"):
        assert obligation[name]["maximum"] == 150_000
    assert obligation["excerpt"]["maxLength"] == 512
    assert obligation["paths"]["maxItems"] == 512
    assert obligation["paths"]["items"]["maxLength"] == 512
    assert obligation["relationIds"]["maxItems"] == 64
    assert _nullable_value(obligation["semanticsJson"])["maxLength"] == 8192
    assert set(obligation["serverState"]["enum"]) == {
        "MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
        "UNRESOLVED", "UNSUPPORTED", "CONFLICT"}
    summary = schemas["SourceCoverageSummaryView"]["properties"]
    assert set(summary["status"]["enum"]) == {
        "COMPLETE", "BLOCKED", "LEGACY_UNASSESSED", "UNKNOWN"}
    assert summary["obligationCount"]["maximum"] == 4096
    assert summary["issueCount"]["maximum"] == 8192
    assert summary["normalizationChangeCount"]["maximum"] == 2000
    assert summary["totalRows"]["maximum"] == 14288
    assert schemas["SourceNormalizationChangeView"]["properties"]["traceRole"]["enum"] == [
        "CURRENT_ASSESSMENT", "HISTORICAL_INPUT"]


def condition_selection_projection(document):
    """Remove only H04's exact selector, preserving every unrelated change."""
    schemas = document["components"]["schemas"]
    command = schemas["DailyFactCommand"]
    assert "conditionSelection" in command["properties"]
    assert "conditionSelection" not in command["required"]
    assert command["properties"]["conditionSelection"] == {
        "$ref": "#/components/schemas/DailyFactConditionSelection"}
    assert "DailyFactConditionSelection" in schemas
    # JSON comparison preserves literal types: Python dict equality conflates
    # True with1, which must not hide an invalid schema-bound mutation.
    assert json.dumps(schemas["DailyFactConditionSelection"], sort_keys=True) == json.dumps({
        "additionalProperties": False,
        "properties": {
            "ownerKind": {"enum": ["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"],
                          "title": "Ownerkind", "type": "string"},
            "ownerId": {"maxLength": 128, "minLength": 1,
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$",
                        "title": "Ownerid", "type": "string"},
            "conditionPath": {"maxLength": 512, "minLength": 1,
                              "title": "Conditionpath", "type": "string"},
        },
        "required": ["ownerKind", "ownerId", "conditionPath"],
        "title": "DailyFactConditionSelection", "type": "object",
    }, sort_keys=True)
    result = deepcopy(document)
    del result["components"]["schemas"]["DailyFactCommand"]["properties"]["conditionSelection"]
    del result["components"]["schemas"]["DailyFactConditionSelection"]
    return result


def source_coverage_projection(document):
    """Remove only approved PMA additions for the older historical shape gates.

    Call this before the earlier P0–P3/schema5 projection. It does not evaluate a
    plan or create authority. Full old-document hashes are checked separately.
    """
    document = condition_selection_projection(document)
    _assert_source_surface(document)
    result = deepcopy(document)
    assert set(result["paths"][COVERAGE_PATH]) == {"get"}
    response = result["paths"][COVERAGE_PATH]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SourceCoveragePage"}
    del result["paths"][COVERAGE_PATH]
    schemas = result["components"]["schemas"]
    for name in ("PlanVersionSummary", "PlanVersionView", "PlanExtractionView"):
        assert "sourceCoverage" not in schemas[name]["required"]
        assert schemas[name]["properties"].pop("sourceCoverage") == {
            "anyOf": [{"$ref": "#/components/schemas/SourceCoverageSummaryView"},
                      {"type": "null"}]}
    command = schemas["PlanReviewConfirmationCommand"]
    for name, expected in {
        "coverageEvidenceHash": dict(anyOf=[dict(type="string", minLength=64, maxLength=64,
            pattern="^[0-9a-f]{64}$"), dict(type="null")], title="Coverageevidencehash"),
        "coverageRulesVersion": dict(anyOf=[dict(type="string", minLength=1, maxLength=64),
            dict(type="null")], title="Coveragerulesversion"),
    }.items():
        assert name not in command["required"]
        assert command["properties"].pop(name) == expected
    for name in SOURCE_FIELDS:
        del schemas[name]
    return result


def _assert_old_hashes(document, version):
    projected = source_coverage_projection(document)
    assert sha256(generator.render_openapi_snapshot(projected).encode()).hexdigest() == (
        LEGACY_HASHES[version][0])
    typescript = generator.render_typescript_contracts(projected, monitor_contract_version=version)
    assert sha256(typescript.encode()).hexdigest() == LEGACY_HASHES[version][1]


def test_generated_coverage_contracts_match_the_frozen_actual_route_and_fields(contract):
    version, document = contract
    snapshot = ROOT / ("openapi.json" if version == 1 else "openapi.runtime-status.json")
    filename = "generated.ts" if version == 1 else "generated-runtime-status.ts"
    types = ROOT / "web/src/api" / filename
    committed = json.loads(snapshot.read_bytes())
    assert COVERAGE_PATH in set(committed["paths"])
    assert snapshot.read_bytes() == generator.render_openapi_snapshot(document).encode()
    assert types.read_bytes() == generator.render_typescript_contracts(
        document, monitor_contract_version=version).encode()
    for path in (snapshot, types):
        raw = path.read_bytes()
        assert raw.endswith(b"\n") and b"\r\n" not in raw


def test_only_approved_additions_restore_exact_old_openapi_and_typescript_hashes(contract):
    version, document = contract
    original = deepcopy(document)
    _assert_old_hashes(document, version)
    assert document == original


def test_selector_only_projection_restores_fixed_prior_coverage_hashes_without_mutation(contract):
    version, document = contract
    original = deepcopy(document)
    projected = condition_selection_projection(document)
    assert document == original
    assert sha256(generator.render_openapi_snapshot(projected).encode()).hexdigest() == (
        PRIOR_COVERAGE_HASHES[version][0])
    assert sha256(generator.render_typescript_contracts(
        projected, monitor_contract_version=version).encode()).hexdigest() == (
            PRIOR_COVERAGE_HASHES[version][1])
    _assert_old_hashes(document, version)
    assert document == original


@pytest.mark.parametrize("attack", ["nullable", "required", "default", "extra-authority",
    "open-object", "owner-bound", "owner-pattern", "owner-enum", "missing-required",
    "component-default", "boolean-bound", "unrelated-field", "unrelated-component"])
def test_selector_projection_rejects_changed_shape_and_unrelated_drift(contract, attack):
    version, original = contract
    document = deepcopy(original)
    schemas = document["components"]["schemas"]
    command = schemas["DailyFactCommand"]
    selection = schemas["DailyFactConditionSelection"]
    if attack == "nullable":
        command["properties"]["conditionSelection"] = dict(anyOf=[
            command["properties"]["conditionSelection"], {"type": "null"}])
    elif attack == "required":
        command["required"].append("conditionSelection")
    elif attack == "default":
        command["properties"]["conditionSelection"]["default"] = None
    elif attack == "extra-authority":
        selection["properties"]["sourceHash"] = {"type": "string"}
    elif attack == "open-object":
        selection["additionalProperties"] = True
    elif attack == "owner-bound":
        selection["properties"]["ownerId"]["maxLength"] = 129
    elif attack == "owner-pattern":
        selection["properties"]["ownerId"]["pattern"] = ".*"
    elif attack == "owner-enum":
        selection["properties"]["ownerKind"]["enum"].append("CONTROL")
    elif attack == "missing-required":
        selection["required"].remove("conditionPath")
    elif attack == "component-default":
        selection["default"] = {}
    elif attack == "boolean-bound":
        selection["properties"]["ownerId"]["minLength"] = True
    elif attack == "unrelated-field":
        command["properties"]["ignoreSelection"] = {"type": "boolean"}
    else:
        schemas["DailyFactUnapprovedSelection"] = {"type": "object"}
    before = deepcopy(document)
    with pytest.raises(AssertionError):
        projected = condition_selection_projection(document)
        assert sha256(generator.render_openapi_snapshot(projected).encode()).hexdigest() == (
            PRIOR_COVERAGE_HASHES[version][0])
        assert sha256(generator.render_typescript_contracts(
            projected, monitor_contract_version=version).encode()).hexdigest() == (
                PRIOR_COVERAGE_HASHES[version][1])
    assert document == before


@pytest.mark.parametrize("attack", ["old-bound", "old-response", "new-component", "old-field",
                                    "source-field", "source-bound", "mutation-route"])
def test_projection_rejects_unapproved_drift_instead_of_erasing_it(contract, attack):
    version, original = contract
    document = deepcopy(original)
    schemas = document["components"]["schemas"]
    if attack == "old-bound":
        schemas["PlanVersionSummary"]["properties"]["revision"]["maximum"] += 1
    elif attack == "old-response":
        document["paths"]["/api/v1/plan-versions"]["get"]["responses"]["200"][
            "description"] = "Unapproved response change"
    elif attack == "new-component":
        schemas["SourceUnapprovedComponent"] = dict(type="object")
    elif attack == "old-field":
        schemas["PlanVersionSummary"]["properties"]["ignoreCoverage"] = dict(type="boolean")
    elif attack == "source-field":
        schemas["SourceCoverageSummaryView"]["properties"]["ignoreCoverage"] = dict(type="boolean")
    elif attack == "source-bound":
        schemas["SourceCoveragePage"]["properties"]["items"]["maxItems"] = 101
    else:
        document["paths"][COVERAGE_PATH]["post"] = deepcopy(
            document["paths"][COVERAGE_PATH]["get"])
    with pytest.raises(AssertionError):
        _assert_old_hashes(document, version)


def test_current_get_retains_bounded_query_public_errors_and_private_carrier_separation(contract):
    _, document = contract
    operation = document["paths"][COVERAGE_PATH]["get"]
    parameters = {row["name"]: row for row in operation["parameters"]}
    assert set(parameters) == {"version_id", "limit", "cursor"}
    assert parameters["version_id"]["required"]
    assert parameters["version_id"]["schema"]["format"] == "uuid"
    assert parameters["limit"]["schema"]["default"] == 50
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert _nullable_value(parameters["cursor"]["schema"])["maxLength"] == 512
    assert "requestBody" not in operation
    for code in ("400", "401", "403", "404", "405", "409", "413", "422", "429", "500", "503"):
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"}
    schemas = document["components"]["schemas"]
    private = {"rawJson", "raw_json", "contextJson", "context_json", "sourceDerivation",
               "source_derivation", "privateInputs", "payloadJson", "providerResponse", "stages"}
    for name in SOURCE_FIELDS:
        properties = schemas[name]["properties"]
        assert private.isdisjoint(properties)
        assert all("_" not in field for field in properties)
    _assert_source_surface(document)


def test_typescript_narrows_all_rows_and_keeps_review_binding_optional_at_parse(contract, tmp_path):
    version, document = contract
    node = shutil.which("node")
    compiler = ROOT / "web/node_modules/typescript/bin/tsc"
    assert node and compiler.is_file()
    (tmp_path / "generated.ts").write_text(generator.render_typescript_contracts(
        document, monitor_contract_version=version), encoding="utf-8")
    source = tmp_path / "probe.ts"
    imports = 'import type { components, paths } from "./generated";\n'
    positive = imports + '''
type Read = paths["/api/v1/plan-versions/{version_id}/source-coverage"]["get"];
type Page = Read["responses"][200]["content"]["application/json"];
export function inspect(page: Page): string {
  const noAuthority: false | undefined = page.authorityGranted;
  const noSummaryAuthority: false | undefined = page.summary.authorityGranted;
  return page.items.map(row => {
    switch (row.kind) {
      case "OBLIGATION": return row.obligation.serverState + row.obligation.mappingProposal?.reason;
      case "ISSUE": return row.issue.code;
      case "NORMALIZATION_CHANGE": return row.change.traceRole + row.change.beforeJson;
      default: { const exhaustive: never = row; return exhaustive; }
    }
  }).join(",");
}
type Review = components["schemas"]["PlanReviewConfirmationCommand"];
export function optionalAtParse(original: Review): Review {
  return { ...original, coverageEvidenceHash: null, coverageRulesVersion: "older-rule-version" };
}
export const missing: Review = { planVersionId: "id", contentHash: "hash", sourceHash: "hash",
  reviewEvidenceHash: "hash", expectedRevision: 0 };
export const list: Pick<components["schemas"]["PlanVersionSummary"], "sourceCoverage"> = {};
export const detail: Pick<components["schemas"]["PlanVersionView"], "sourceCoverage"> = {};
export const extraction: Pick<components["schemas"]["PlanExtractionView"], "sourceCoverage"> = {};
'''

    def compile_text(value):
        source.write_text(value, encoding="utf-8")
        return subprocess.run([node, str(compiler), "--strict", "--noEmit", "--skipLibCheck",
            "--target", "ES2022", "--types", "node", "--typeRoots",
            str(ROOT / "web/node_modules/@types"), str(source)], capture_output=True,
            text=True, encoding="utf-8", check=False)

    result = compile_text(positive)
    assert result.returncode == 0, result.stdout + result.stderr
    for attack in (
        'const value: Pick<components["schemas"]["SourceCoveragePage"], "authorityGranted"> = '
        '{ authorityGranted: true };',
        'const value: components["schemas"]["SourceCoverageSummaryView"]["status"] = "PASS";',
        'const value: components["schemas"]["SourceCoverageIssueView"]["start"] = "1";',
        'const value: components["schemas"]["SourceObligationRow"]["kind"] = "IGNORED";',
        'const value: components["schemas"]["PlanReviewConfirmationCommand"] = '
        '{ planVersionId: "id", contentHash: "hash", sourceHash: "hash", '
        'reviewEvidenceHash: "hash", expectedRevision: 0, ignoreCoverage: true };',
        'declare const value: components["schemas"]["SourceCoveragePage"]; value.rawJson;',
        'declare const value: components["schemas"]["SourceCoveragePage"]; value.contextJson;',
    ):
        result = compile_text(imports + attack)
        assert result.returncode != 0, attack
