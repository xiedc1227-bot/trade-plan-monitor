"""Exact MRD surface removal preserves every earlier approval's original bytes.

These literal fingerprints freeze reviewed implementation shapes under MRD-S01–10;
they are regression fixtures, not a new human signature or runtime-model oracle.
"""

import json
import shutil
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from scripts import generate_frontend_types as generator
from tests.contract.test_plan_buy_suspension_api_projection import (
    ADDED_SHA256,
    buy_suspension_projection,
)

ROOT = Path(__file__).resolve().parents[2]
READINESS_PATH = "/api/v1/plan-versions/{version_id}/monitor-readiness"
PATH_SHA256 = "7e5de925ef181c59bd875317046ce5dac16ecea47ababc276043747f20f827e4"
H04_HASHES = {
    1: ("8821fa8577e72eab4b607bf18306c0ccca4e30b00fa686616c9f84abcdc66563",
        "0e160cf924a1376893b2b463d6aac4970ca22c33caf4d2f13798dad6a985efb8"),
    2: ("27f111593d3d95d2df5722122f5ec914c068494c69ef0b0ed6986e6c59d72bba",
        "1780d5e3801ddeef0f7105bfcd70ecfc5bd134bc0859ce010a0d9b396f9621f7"),
}
CANDIDATE_HASHES = {
    1: ("4b606849eb334bfb19888319ac40ba955d8eae61dd3a7e2204ac52ea76e5e301",
        "bc2d5f7e0315490d47d98593843110ce5fab62e4f0c815df6ab1bddeacee8f4b"),
    2: ("57985edb074683be169ea674a8b4c503402fad7a6b55917b839dff566c181464",
        "622ead01cea642615080d4e0df75e3567498d2b807fb82fa60ef706d4e1a88a2"),
}
# Complete per-component canonical JSON fingerprints include every property,
# required array, reference, enum, default, bound and nested nullable/discriminator.
COMPONENT_SHA256 = {
    "AxisReadiness": "bb1c3cd5d2df585a67a25ce9f58372c00302e760644f08a2f26317f848da7491",
    "ChannelErrorCode": "0a25352eb0bbe5dab2f9bf2fb5babc814dffbfed7e9b30dfeebcfb50646c6e35",
    "ConditionReadiness": "1c49c8439b6c8a4b41e15f85998a483ca5598af44fe86b6220ad13c7032da873",
    "DailyRiskBirth": "c04e14cfe41efbb52e3fab9203937e51d1640838284cf8fb88b1fd9ef9e812ae",
    "DailyRiskEvaluation": "c6b44196f59724506894a3afaa8dcf30614f2be90a156d44519ced47bcf9376d",
    "DeliveryAttemptStatus": "80762a2ed1375b1821f5dbbb5bbab9bedeec5698c3cb0c5e217b3f761a6ef211",
    "DeliveryChannel": "a12a13f176159e3476fc1acfd952a5434002aa4c3b8df027dd01f0bff0c1ad29",
    "ExpectedConfirmation": "2661a97d4376195565f04f8bbfb1c5f74a273aad9350f5e9b9989e6ac9a0b369",
    "IntradayEvaluationTarget": "5446d158a1fd77b53c57a9d187a6ad3e26462c36bb62b9711da8059112dac833",
    "InventoryRequirements": "701857e1d30fc29512242c0450c9ca81a1b910009eb48fdd9ace09db988facc7",
    "OfficialCloseEvaluationTarget":
        "d6b686cba0fef2ec0d8b2c6b32d00d7ac9e2c0297b4767408a3548452aedb0b9",
    "OrdinaryRiskCloseObservation":
        "476a6cc80f712e99e63e18157b7a0a7c5cb07f6ef8c3586b0bc0e94a12660f67",
    "ReadinessAssessment": "69912ca1a12bd70c549212697823fd61bdca2c51d66fbf53eaba33d24f9b74f1",
    "ReadinessContext": "7fcbd1895f151e8d3597caf4fef2b869833fbd9824e486ffa0220cbcfb7af397",
    "ReadinessDeliveryAttempt": "fc71274fd678115d577d91ed2dce0a5a08f11c080411059301278e5bee6b7c37",
    "ReadinessExecutionState": "f35fdabc169ffe4854cbff7bf421c20d84fc2711fadf216693180899e9227cde",
    "ReadinessMoneyFacts": "f8806607f9515201f966bc04d6e7ab7278a76cc8e30b0f2a13ac108ec80315c3",
    "ReadinessNotificationChannel":
        "6c388de783b156e71e2c470635fd28783cb6a57dcbfa235ba80202a274932ded",
    "ReadinessNotificationFacts":
        "6192d02f0218a5a2a2b4a20dc8f8bc33b93575f1ab8df522cb82c9aa81ccbd30",
    "ReadinessObservation": "06757f750381bf20051826f92cbd732b4a0759120d3a58f30edf589b90e7ad59",
    "ReadinessRiskFacts": "e7e7eaa13acc697e8e911f3673cbf79f99925f9962c5c9e055984724b163ebc3",
    "ReadinessRiskObligation": "7b87c5fd5ee423ba3f5fe79717aea39d764d9da8c975fe5abfeee87ef608c526",
    "ReadinessRiskOrigin": "d1ac8f6cefa5a790b9e2d04a87f7c7146b81faa53981e3f17714e98087853656",
    "ReadinessSnapshot": "78737ecabd9eef03a00512f679e4efb4d4e6fe3d908cc01381e1d52ea99acb73",
    "RecoveryDeliveryStatus": "41ee8d9c698f6de0ad65aa24ff6671f2042c5799223d315b7c8edeee691f737c",
    "RuleReadiness": "cd150d302a65308fac5d1257fc75b5dc5fb4c6d755371a112bc492fb4768005d",
    "RuleReadinessFacts": "bca23a565822b471b3e3f441c60e250d86d6609744f85843836115b2cfb4c061",
}


def _canonical(value):
    # Preserve literal types: False/0 and True/1 must never compare as equivalent.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def readiness_projection(document):
    """Verify the entire fixed additive surface, then remove only its exact names."""
    if set(ADDED_SHA256) & document["components"]["schemas"].keys():
        document = buy_suspension_projection(document)
    assert READINESS_PATH in document["paths"]
    assert sha256(_canonical(document["paths"][READINESS_PATH]).encode()).hexdigest() == PATH_SHA256
    schemas = document["components"]["schemas"]
    for name, digest in COMPONENT_SHA256.items():
        assert name in schemas, name
        assert sha256(_canonical(schemas[name]).encode()).hexdigest() == digest, name
    result = deepcopy(document)
    del result["paths"][READINESS_PATH]
    for name in COMPONENT_SHA256:
        del result["components"]["schemas"][name]
    return result


def assert_h04_hashes(document, version):
    assert sha256(generator.render_openapi_snapshot(document).encode()).hexdigest() == (
        H04_HASHES[version][0])
    assert sha256(generator.render_typescript_contracts(
        document, monitor_contract_version=version).encode()).hexdigest() == H04_HASHES[version][1]


@pytest.fixture(scope="module", params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def contract(request):
    return request.param, buy_suspension_projection(
        generator.build_openapi_document(monitor_contract_version=request.param))


def test_projection_restores_fixed_h04_bytes_without_mutating_input(contract):
    version, document = contract
    original = _canonical(document)
    assert_h04_hashes(readiness_projection(document), version)
    assert _canonical(document) == original
    assert sha256(generator.render_openapi_snapshot(document).encode()).hexdigest() == (
        CANDIDATE_HASHES[version][0])
    assert sha256(generator.render_typescript_contracts(
        document, monitor_contract_version=version).encode()).hexdigest() == (
            CANDIDATE_HASHES[version][1])


def test_fixed_surface_retains_literals_bounds_and_private_separation(contract):
    _, document = contract
    readiness_projection(document)
    operation = document["paths"][READINESS_PATH]["get"]
    assert set(operation["responses"]) == {
        "200", "400", "401", "403", "404", "405", "409", "413", "422", "429", "500", "503"}
    assert operation["parameters"] == [{"name": "version_id", "in": "path", "required": True,
        "schema": {"type": "string", "format": "uuid", "title": "Version Id"}}]
    assert "requestBody" not in operation
    schemas = document["components"]["schemas"]
    for name in COMPONENT_SHA256:
        if schemas[name].get("type") == "object":
            assert schemas[name]["additionalProperties"] is False
    assessment = schemas["ReadinessAssessment"]["properties"]
    assert assessment["authorityGranted"]["const"] is False
    assert assessment["authorityGranted"]["default"] is False
    assert assessment["contractVersion"]["const"] == "plan-monitor-readiness-v1"
    for name in ("ReadinessAssessment", "ReadinessSnapshot"):
        props = schemas[name]["properties"]
        assert props["axes"]["minItems"] == props["axes"]["maxItems"] == 6
        assert props["rules"]["minItems"] == 1 and props["rules"]["maxItems"] == 76
    assert schemas["RuleReadinessFacts"]["properties"]["leaves"]["maxItems"] == 50
    observation = schemas["ReadinessObservation"]["properties"]
    assert observation["evidenceRefs"]["maxItems"] == 128
    assert observation["evidenceRefs"]["items"]["maxLength"] == 256
    assert schemas["ReadinessNotificationFacts"]["properties"]["channels"]["maxItems"] == 3
    assert schemas["ReadinessRiskOrigin"]["properties"]["activationRevision"]["maximum"] == (
        9_007_199_254_740_991)
    assert schemas["ReadinessContext"]["properties"]["contentHash"]["pattern"] == (
        "^[0-9a-f]{64}$")
    assert "DailyOrdinaryEvaluation" not in schemas
    assert {"ordinaryEvaluations", "ordinary_evaluations"}.isdisjoint(
        schemas["DailyEvaluationApiView"]["properties"])
    for name in COMPONENT_SHA256:
        assert {"token", "rawJson", "rawError", "approvalToken"}.isdisjoint(
            schemas[name].get("properties", {}))


def test_every_component_is_required_and_frozen_in_full(contract):
    _, original = contract
    before = _canonical(original)
    for name in COMPONENT_SHA256:
        for missing in (True, False):
            changed = deepcopy(original)
            schemas = changed["components"]["schemas"]
            if missing:
                del schemas[name]
            else:
                schemas[name]["unapprovedNestedShape"] = {"type": "boolean"}
            corrupted = _canonical(changed)
            with pytest.raises(AssertionError):
                readiness_projection(changed)
            assert _canonical(changed) == corrupted
    assert _canonical(original) == before


def test_fixed_get_rejects_path_parameters_responses_and_new_operations(contract):
    _, original = contract
    for attack in ("missing", "post", "query", "header", "numeric-required", "uuid", "response",
                   "request-body", "response-code", "path-field"):
        changed = deepcopy(original)
        path = changed["paths"][READINESS_PATH]
        operation = path["get"]
        if attack == "missing":
            del changed["paths"][READINESS_PATH]
        elif attack == "post":
            path["post"] = deepcopy(operation)
        elif attack in {"query", "header"}:
            operation["parameters"].append({"name": "permission", "in": attack,
                "required": True, "schema": {"type": "string"}})
        elif attack == "numeric-required":
            operation["parameters"][0]["required"] = 1
        elif attack == "uuid":
            operation["parameters"][0]["schema"]["format"] = "password"
        elif attack == "response":
            operation["responses"]["200"]["content"]["application/json"]["schema"] = {
                "$ref": "#/components/schemas/ErrorResponse"}
        elif attack == "request-body":
            operation["requestBody"] = {"required": True}
        elif attack == "response-code":
            operation["responses"]["418"] = deepcopy(operation["responses"]["200"])
        else:
            path["description"] = "unapproved"
        before = _canonical(changed)
        with pytest.raises(AssertionError):
            readiness_projection(changed)
        assert _canonical(changed) == before


def test_nested_constraints_reject_enum_required_authority_and_numeric_coercion(contract):
    _, original = contract
    changes = [
        ("ReadinessAssessment", ("properties", "authorityGranted", "const"), 0),
        ("ReadinessAssessment", ("properties", "authorityGranted", "default"), 0),
        ("ReadinessAssessment", ("properties", "authorityGranted", "const"), True),
        ("ReadinessAssessment", ("properties", "axes", "maxItems"), 7),
        ("ReadinessAssessment", ("properties", "rules", "maxItems"), 77),
        ("ReadinessAssessment", ("required",), ["snapshot", "axes", "summary", "freshUntil"]),
        ("RuleReadinessFacts", ("properties", "leaves", "maxItems"), 51),
        ("ReadinessContext", ("additionalProperties",), 0),
        ("ConditionReadiness", ("properties", "conditionPath", "minLength"), True),
        ("ReadinessRiskOrigin", ("properties", "activationRevision", "minimum"), True),
        ("ExpectedConfirmation", ("properties", "priorInputsComplete", "type"), "integer"),
        ("IntradayEvaluationTarget", ("properties", "kind", "const"), "OFFICIAL_CLOSE"),
        ("DailyRiskEvaluation", ("properties", "risk_identity", "pattern"), ".*"),
        ("OrdinaryRiskCloseObservation", ("properties", "close_fen", "type"), "number"),
        ("DeliveryChannel", ("enum",), ["IN_APP", "CONSOLE", "WEBHOOK", "BROKER"]),
        ("DeliveryAttemptStatus", ("enum",), ["CLAIMED", "RETRY_PENDING", "FAILED"]),
        ("ReadinessDeliveryAttempt", ("properties", "errorCode"), {"type": "string"}),
        ("ReadinessObservation", ("properties", "evidenceRefs", "maxItems"), 129),
    ]
    for name, path, value in changes:
        changed = deepcopy(original)
        node = changed["components"]["schemas"][name]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(AssertionError):
            readiness_projection(changed)


def test_unrelated_drift_is_retained_and_fails_old_fixed_hashes(contract):
    version, original = contract
    for attack in ("component", "readiness-prefix", "field", "old-bound", "old-response", "path",
                   "top-level"):
        changed = deepcopy(original)
        schemas = changed["components"]["schemas"]
        if attack in {"component", "readiness-prefix"}:
            name = "ReadinessUnapproved" if attack == "readiness-prefix" else "OtherUnapproved"
            schemas[name] = {"type": "object"}
        elif attack == "field":
            schemas["PlanVersionSummary"]["properties"]["permit"] = {"type": "boolean"}
        elif attack == "old-bound":
            schemas["DailyFactConditionSelection"]["properties"]["ownerId"]["minLength"] = True
        elif attack == "old-response":
            changed["paths"]["/api/v1/plan-versions"]["get"]["responses"]["200"][
                "description"] = "unapproved"
        elif attack == "path":
            changed["paths"][READINESS_PATH + "/approve"] = deepcopy(
                changed["paths"][READINESS_PATH])
        else:
            changed["info"]["version"] = "unapproved"
        before = _canonical(changed)
        projected = readiness_projection(changed)
        with pytest.raises(AssertionError):
            assert_h04_hashes(projected, version)
        assert _canonical(changed) == before


def test_current_typescript_preserves_no_authority_and_closed_native_facts(contract, tmp_path):
    version, document = contract
    node = shutil.which("node")
    compiler = ROOT / "web/node_modules/typescript/bin/tsc"
    assert node and compiler.is_file()
    (tmp_path / "generated.ts").write_text(generator.render_typescript_contracts(
        document, monitor_contract_version=version), encoding="utf-8")
    source = tmp_path / "probe.ts"
    imports = 'import type { components, paths } from "./generated";\n'
    positive = imports + '''
type Read = paths["/api/v1/plan-versions/{version_id}/monitor-readiness"]["get"];
type Assessment = Read["responses"][200]["content"]["application/json"];
export function inspect(value: Assessment): string | undefined {
  const noAuthority: false | undefined = value.authorityGranted;
  return value.rules[0].facts.risk?.current?.risk_identity;
}
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
        'const grant: Pick<components["schemas"]["ReadinessAssessment"], "authorityGranted"> = '
        '{ authorityGranted: true };',
        'const status: components["schemas"]["RuleReadiness"]["state"] = "READY";',
        'declare const value: components["schemas"]["DailyEvaluationApiView"]; '
        'value.ordinaryEvaluations;',
    ):
        result = compile_text(imports + attack)
        assert result.returncode != 0, attack
