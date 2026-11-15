"""Exact PBS public delta, preserving all pre-PBS OpenAPI/TypeScript bytes."""

import json
import shutil
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from scripts import generate_frontend_types as generator

# Literal reviewed shapes, independent of the runtime models and generated files.
ADDED_SHA256 = {
    "BuySuspensionCoverage": "d2dab8e40bce6a4a235256d00ba3f3ff047ef54ab93ed14beb7acd8819361584",
    "BuySuspensionDefinition": "17872b02c735839862de285f28cce118a908a74a0147e08d7db495efcd177369",
    "BuySuspensionDraftDefinition":
        "9ec2ed71e4f7fa5d28fcff513a04d92716626441858c44930d8e6c30a9e47145",
    "BuySuspensionPriceBasis": "ea58606be4c1c3b4b1aecad2a0a36f25246f1c070a6c56f2a67d6f5f40f0669f",
    "BuySuspensionReplacementBinding":
        "ff0adf6ce1aab95d55a1fb559ef239a52d1d5c7913cee08e40f867c6fd8a68d5",
    "BuySuspensionReplacementIntent":
        "2b63c829622b1369915fc1c18435f916f35fddc64f9345a8e3c277728905f2d5",
    "BuySuspensionTrigger": "672ef6052534fff5f42044b04dabeae69363295fbf129556eec7224368e3e833",
    "DailyBuySuspensionState": "d865340322f6164bb865ac2018460db3796e3debf9b68ce31368f3acdf35862d",
    "ReadinessBuySuspension": "f761f981b0d0657dc2b197dbd383d576fda0ca858e1dcf5293cf3acabe937199",
}
CHANGED_SHA256 = {
    "ExplicitPlanCapabilityView":
        "91ab58242bf183bcf6babbdec32abda198080549b810e213e160646bb8be17b3",
    "DailyEditorSchemaView": "31db8345e43288aa9430d941e63aeb9e21a545739756ebd809f8cb645f053c36",
    "AxisReadiness": "581f22761e93f8c73bc87c50554f81aa065fa136958edc499d275e2827c935bf",
    "ConditionReadiness": "3ca063750c95761a4c2d7aaffbf3574de3a36312580a40b07529709736c6626d",
    "DailyEvaluationApiView": "fa470989283565db91678f0ceab3c70dd29b94fd47ce24558ad5500542fd99f8",
    "DailyReviewPreview": "436b2c84d9caa1443e73b316bb52dce2bb0ffac4b7b69070c0a5267f95befbf8",
    "DailySupplement": "0493dab93b058957564def5e502135fe96de39aea8333988657e6963893c736e",
    "DailySupplementCommand": "85af95d67532ef2543599c4528a07f4e5d9e09a1c72f9b5a41158593cfc8edd6",
    "ReadinessSnapshot": "a4f070d9546a593f569eb18350b32c7a5a2b5546d55b0baca433dc78ba77dbab",
    "RuleReadiness": "addd49abe0f69ba5b8c8b8aa6d261d20ad17d596bb61fa34db629114a7791375",
}
PRE_PBS_HASHES = {
    1: ("4b606849eb334bfb19888319ac40ba955d8eae61dd3a7e2204ac52ea76e5e301",
        "bc2d5f7e0315490d47d98593843110ce5fab62e4f0c815df6ab1bddeacee8f4b"),
    2: ("57985edb074683be169ea674a8b4c503402fad7a6b55917b839dff566c181464",
        "622ead01cea642615080d4e0df75e3567498d2b807fb82fa60ef706d4e1a88a2"),
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def buy_suspension_projection(document):
    """Validate every PBS shape, then remove only its exact reviewed changes."""
    schemas = document["components"]["schemas"]
    for name, digest in (ADDED_SHA256 | CHANGED_SHA256).items():
        assert name in schemas, name
        assert sha256(_canonical(schemas[name]).encode()).hexdigest() == digest, name
    result = deepcopy(document)
    schemas = result["components"]["schemas"]
    for name in ADDED_SHA256:
        del schemas[name]
    for name in ("AxisReadiness", "ConditionReadiness", "RuleReadiness"):
        reasons = schemas[name]["properties"]["reason"]["anyOf"][0]["enum"]
        assert reasons[-2:] == ["BUY_SUSPENSION_LATCHED", "STRATEGY_START_NOT_REACHED"]
        del reasons[-2:]
    states = schemas["RuleReadiness"]["properties"]["state"]["enum"]
    assert states.pop() == "BUY_SUSPENDED"
    properties = {
        "ExplicitPlanCapabilityView": ("buySuspensionExecutionVersion",),
        "DailyEditorSchemaView": ("buySuspensionCandidateSchema",),
        "ReadinessSnapshot": ("buySuspension",),
        "DailyReviewPreview": ("buySuspensionReplacementIntent",),
        "DailySupplementCommand": ("sourceText", "buySuspensionReplacementIntent"),
        "DailySupplement": ("source_hash", "obligation_id", "buy_suspension_clarification"),
        "DailyEvaluationApiView": ("buySuspensionOwnerPlanVersionId", "buySuspensionRevision",
            "buySuspensionTarget", "buySuspensionBlocker", "buySuspensionSkippedRules"),
    }
    for name, fields in properties.items():
        for field in fields:
            assert field not in schemas[name].get("required", [])
            del schemas[name]["properties"][field]
    # Empty supplements now require the separately registered replacement intent.
    schemas["DailySupplementCommand"]["properties"]["supplements"]["minItems"] = 1
    for name in ("ExplicitPlanCapabilityView", "DailyEditorSchemaView"):
        versions = schemas[name]["properties"]["supportedSchemaVersions"]["default"]
        assert versions == [5, 6, 7, 8, 9, 10]
        versions.pop()
    return result


def assert_pre_pbs_hashes(document, version):
    assert sha256(generator.render_openapi_snapshot(document).encode()).hexdigest() == (
        PRE_PBS_HASHES[version][0])
    assert sha256(generator.render_typescript_contracts(
        document, monitor_contract_version=version).encode()).hexdigest() == (
            PRE_PBS_HASHES[version][1])


@pytest.fixture(scope="module", params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def contract(request):
    return request.param, generator.build_openapi_document(monitor_contract_version=request.param)


def test_exact_pbs_projection_restores_all_four_fixed_prior_bytes_without_mutation(contract):
    version, original = contract
    before = _canonical(original)
    projected = buy_suspension_projection(original)
    assert_pre_pbs_hashes(projected, version)
    assert _canonical(original) == before
    assert _canonical(projected["paths"]) == _canonical(original["paths"])
    assert set(original["components"]["schemas"]) - set(projected["components"]["schemas"]) == (
        set(ADDED_SHA256))


def test_each_pbs_component_is_required_and_checked_in_full(contract):
    _, original = contract
    for name in ADDED_SHA256 | CHANGED_SHA256:
        for missing in (True, False):
            changed = deepcopy(original)
            if missing:
                del changed["components"]["schemas"][name]
            else:
                changed["components"]["schemas"][name]["unapprovedNestedShape"] = True
            before = _canonical(changed)
            with pytest.raises(AssertionError):
                buy_suspension_projection(changed)
            assert _canonical(changed) == before


def test_pbs_projection_rejects_wrong_literals_bounds_and_authority(contract):
    _, original = contract
    mutations = [
        ("ReadinessBuySuspension", ("properties", "skippedRules", "maxItems"), 3),
        ("ReadinessBuySuspension", ("properties", "stateRevision", "anyOf", 0,
                                   "exclusiveMinimum"), False),
        ("DailyBuySuspensionState", ("properties", "version", "const"), "old-state"),
        ("BuySuspensionDefinition", ("required",), ["condition"]),
        ("BuySuspensionReplacementBinding", ("properties", "authority_granted", "const"), 0),
        ("RuleReadiness", ("properties", "state", "enum"), ["READY"]),
        ("DailySupplementCommand", ("properties", "supplements", "minItems"), 1),
    ]
    for name, path, value in mutations:
        changed = deepcopy(original)
        node = changed["components"]["schemas"][name]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(AssertionError):
            buy_suspension_projection(changed)


def test_pbs_projection_never_erases_unknown_schemas_fields_or_routes(contract):
    version, original = contract
    for attack in ("component", "pbs-prefix", "field", "path", "response", "literal"):
        changed = deepcopy(original)
        schemas = changed["components"]["schemas"]
        if attack in {"component", "pbs-prefix"}:
            schemas["BuySuspensionUnapproved" if attack == "pbs-prefix" else "Unapproved"] = {
                "type": "object"}
        elif attack == "field":
            schemas["PlanVersionView"]["properties"]["permit"] = {"type": "boolean"}
        elif attack == "path":
            changed["paths"]["/api/v1/buy-suspension-unlock"] = {"post": {}}
        elif attack == "response":
            changed["paths"]["/api/v1/plan-versions"]["get"]["responses"]["200"][
                "description"] = "unapproved"
        else:
            schemas["ReadinessAssessment"]["properties"]["authorityGranted"]["const"] = 0
        before = _canonical(changed)
        projected = buy_suspension_projection(changed)
        with pytest.raises(AssertionError):
            assert_pre_pbs_hashes(projected, version)
        assert _canonical(changed) == before


def test_both_generated_types_preserve_native_guard_receipts_and_fixed_authority(
    contract, tmp_path,
):
    version, document = contract
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    compiler = root / "web/node_modules/typescript/bin/tsc"
    assert node and compiler.is_file()
    filename = "generated.ts" if version == 1 else "generated-runtime-status.ts"
    actual = (root / "web/src/api" / filename).read_bytes()
    assert actual == generator.render_typescript_contracts(
        document, monitor_contract_version=version).encode()
    (tmp_path / "generated.ts").write_bytes(actual)
    source = tmp_path / "probe.ts"
    imports = 'import type { components, paths } from "./generated";\n'
    positive = imports + '''
type Read = paths["/api/v1/plan-versions/{version_id}/monitor-readiness"]["get"];
type Assessment = Read["responses"][200]["content"]["application/json"];
export function inspect(value: Assessment) {
  const noAuthority: false | undefined = value.authorityGranted;
  const guard = value.snapshot.buySuspension;
  const nativeOwner: string | undefined = guard?.state?.owner_plan_version_id;
  const stateVersion: "buy-suspension-state-v1" | undefined = guard?.state?.version;
  const replacementVersion: "buy-suspension-replacement-v1" | undefined =
    guard?.replacement?.version;
  const noReplacementAuthority: false | undefined = guard?.replacement?.authority_granted;
  return [guard?.definition?.effective_from, guard?.state?.trigger?.basis.anchor_factor,
    guard?.replacement?.intent.strategy_effective_from, guard?.strategyEffectiveFrom,
    nativeOwner, stateVersion, replacementVersion, noAuthority, noReplacementAuthority];
}
export const absent: Pick<components["schemas"]["ReadinessSnapshot"], "buySuspension"> = {};
export const state: components["schemas"]["RuleReadiness"]["state"] = "BUY_SUSPENDED";
'''

    def compile_text(value):
        source.write_text(value, encoding="utf-8")
        return subprocess.run([node, str(compiler), "--strict", "--noEmit", "--skipLibCheck",
            "--target", "ES2022", "--types", "node", "--typeRoots",
            str(root / "web/node_modules/@types"), str(source)], capture_output=True,
            text=True, encoding="utf-8", check=False)

    result = compile_text(positive)
    assert result.returncode == 0, result.stdout + result.stderr
    for attack in (
        'const grant: Pick<components["schemas"]["BuySuspensionReplacementBinding"], '
        '"authority_granted"> = { authority_granted: true };',
        'const guard: components["schemas"]["BuySuspensionDefinition"]["condition"] = '
        '{ type: "MINUTE_CLOSE_BELOW", timeframe_minutes: 1, price_fen: 2420 };',
        'declare const guard: components["schemas"]["ReadinessBuySuspension"]; '
        'guard.state?.ownerPlanVersionId;',
    ):
        result = compile_text(imports + attack)
        assert result.returncode != 0, attack
