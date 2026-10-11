"""ML-T13 publishes typed one-source contracts without approving a new digest."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts import generate_frontend_types as generator
from tests.integration.test_plan_preparation_review import ready_preparation, review_command

from trade_plan_monitor.web.preparation_schemas import (
    PreparationFrozenView,
    PreparationReviewInput,
    PreparationView,
    project_preparation,
)

MAX_SAFE_INTEGER = 9_007_199_254_740_991
BASE = "/api/v1/backtest-preparations"
OPERATIONS = {
    BASE: ("post", {"201"}),
    BASE + "/{preparation_id}": ("get", {"200"}),
    BASE + "/{preparation_id}/items": ("get", {"200"}),
    BASE + "/{preparation_id}/source": ("put", {"200"}),
    BASE + "/{preparation_id}/extractions": ("post", {"202"}),
    BASE + "/{preparation_id}/cancellations": ("post", {"200", "202"}),
    BASE + "/{preparation_id}/reviews": ("post", {"200"}),
    BASE + "/{preparation_id}/recoveries": ("post", {"200"}),
}


@pytest.fixture(scope="module", params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def document(request):
    return generator.build_openapi_document(monitor_contract_version=request.param)


def resolved(document, schema):
    if "$ref" in schema:
        return document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def reference_names(schema):
    if "$ref" in schema:
        return {schema["$ref"].rsplit("/", 1)[1]}
    return set().union(
        *(reference_names(branch) for key in ("anyOf", "oneOf") for branch in schema.get(key, []))
    )


def test_generated_contracts_preserve_legacy_response_schema_names(document):
    schemas = document["components"]["schemas"]
    assert {"DailyCandleRatio", "DailyPriceCompare", "UnifiedAll", "UnifiedAny"} <= set(schemas)
    assert not any(name.endswith(("-Input", "-Output")) for name in schemas)
    assert schemas["DailyCandleRatio"]["properties"]["ratio"]["type"] == "string"
    assert "anyOf" in schemas["DailyCandleRatioInput"]["properties"]["ratio"]
    generator.render_typescript_contracts(document)


def test_mode_schema_name_collision_is_rejected():
    with pytest.raises(ValueError, match="schema name collision"):
        generator._normalize_mode_schema_names(
            {"components": {"schemas": {"Probe": {}, "Probe-Output": {}}}, "paths": {}}
        )


def test_published_references_resolve_and_progress_excludes_private_state(document):
    schemas = document["components"]["schemas"]
    private = {
        "owner_token",
        "ownerToken",
        "owner_pid",
        "ownerPid",
        "admission_key",
        "admissionKey",
        "payload_json",
        "payloadJson",
        "review_json",
        "reviewJson",
        "work_claim",
        "workClaim",
        "provider_diagnostics",
        "providerDiagnostics",
        "filesystem_path",
        "filesystemPath",
    }
    visited = set()

    def walk(value, *, public=False):
        if isinstance(value, dict):
            if public:
                assert private.isdisjoint(value.get("properties", {}))
            if "$ref" in value:
                reference = value["$ref"]
                assert reference.startswith("#/components/schemas/")
                name = reference.rsplit("/", 1)[1]
                assert name in schemas
                if public and name not in visited:
                    visited.add(name)
                    walk(schemas[name], public=True)
            for item in value.values():
                walk(item, public=public)
        elif isinstance(value, list):
            for item in value:
                walk(item, public=public)

    walk(document)
    for name in ("PreparationView", "PreparationFrozenView"):
        walk(schemas[name], public=True)
    assert {"PreparationRecord", "PreparationWorkClaim", "PreparationCandidateInput"}.isdisjoint(
        visited | set(schemas)
    )


def test_generated_types_narrow_candidates_and_reject_invalid_commands(document, tmp_path):
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    compiler = root / "web/node_modules/typescript/bin/tsc"
    assert node is not None and compiler.is_file(), "installed TypeScript compiler is required"
    contracts = tmp_path / "generated.ts"
    contracts.write_text(generator.render_typescript_contracts(document), encoding="utf-8")
    imports = 'import type { components, paths } from "./generated";\n'
    positive = (
        imports
        + """
type Read = paths["/api/v1/backtest-preparations/{preparation_id}"]["get"];
type Progress = Read["responses"][200]["content"]["application/json"];
export function inspect(value: Progress): string {
  if ("items" in value) return value.items.map(item => item.sourceId).join(",");
  const candidate = value.candidate;
  if (!candidate) return value.status;
  switch (candidate.kind) {
    case "EXTRACTION": return candidate.draft.plan_id + candidate.mapping.clauses.length;
    case "FROZEN": return candidate.frozen.version.version_id;
    case "UNAVAILABLE": {
      const invalid: "INVALID" = candidate.validation;
      return invalid;
    }
    default: { const exhaustive: never = candidate; return exhaustive; }
  }
}
type Recover = paths["/api/v1/backtest-preparations/{preparation_id}/recoveries"]["post"];
type Recovery = Recover["requestBody"]["content"]["application/json"];
export const recovery: Recovery = { expectedRevision: 1, generation: "g1", confirmedEnded: true };
export const cash: components["schemas"]["KnownLoopCash"] = { kind: "KNOWN", balance_fen: 0 };
export const unknownCash: components["schemas"]["UnknownLoopCash"] = { kind: "UNKNOWN" };
export const create: components["schemas"]["PreparationCreateCommand"] = {
  input: { preparation_id: "p1", sources: [{ source_id: "s1", text: "original" }] }
};
export const collection: components["schemas"]["PreparationCreateCommand"] = {
  input: { schema_version: "backtest-preparation-v2", preparation_id: "p2",
           sources: [{ source_id: "s1", text: "first" }, { source_id: "s2", text: "later" }] }
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
                str(root / "web/node_modules/@types"),
                str(source),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )

    valid = compile_text(positive)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    for invalid in (
        'const command: components["schemas"]["PreparationRecoveryCommand"] = '
        '{ expectedRevision: 1, generation: "g1", confirmedEnded: false };',
        'const candidate: components["schemas"]["PreparationFrozenCandidate"] = '
        '{ kind: "FROZEN", candidateHash: "h", evidenceHash: "e", issues: [], '
        'validation: "VALID", frozen: null };',
    ):
        result = compile_text(imports + invalid)
        assert result.returncode != 0
        assert "error TS2322" in result.stdout, result.stdout + result.stderr


def test_preparation_operations_publish_actual_success_and_existing_errors(document):
    from tests.integration.test_openapi_snapshot import PUBLIC_ERROR_STATUSES

    assert {path for path in document["paths"] if path.startswith(BASE)} == set(OPERATIONS)
    identities = set()
    for path, (method, success) in OPERATIONS.items():
        item = document["paths"][path]
        assert set(item) == {method}
        operation = item[method]
        assert operation["operationId"] not in identities
        identities.add(operation["operationId"])
        responses = operation["responses"]
        assert set(responses) == success | PUBLIC_ERROR_STATUSES
        for status in success:
            names = reference_names(responses[status]["content"]["application/json"]["schema"])
            if path.endswith("/items"):
                assert len(names) == 1
            else:
                expected = (
                    "PreparationFrozenView" if path.endswith("/reviews") else "PreparationView"
                )
                assert expected in names and len(names) >= 2
            assert responses[status]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
            if status == "202":
                assert responses[status]["headers"]["Retry-After"]["schema"]["const"] == 2
        for status in PUBLIC_ERROR_STATUSES:
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
        retry = responses["503"]["headers"]["Retry-After"]["schema"]
        assert retry["minimum"] == retry["maximum"] == 1
        parameters = operation["parameters"]
        queries = {
            parameter["name"]: parameter for parameter in parameters if parameter["in"] == "query"
        }
        if path.endswith("/items"):
            assert set(queries) == {"expectedRevision", "offset", "limit"}
            assert queries["expectedRevision"]["required"] is True
            assert queries["offset"]["schema"]["maximum"] == 255
            assert queries["limit"]["schema"]["maximum"] == 100
        else:
            assert not queries
        if method != "get":
            key = next(
                parameter for parameter in parameters if parameter["name"] == "Idempotency-Key"
            )
            assert key["required"] is True


def test_published_create_and_progress_are_single_source_and_bounded(document):
    operation = document["paths"][BASE]["post"]
    command = resolved(document, operation["requestBody"]["content"]["application/json"]["schema"])
    inputs = command["properties"]["input"]
    names = reference_names(inputs)
    assert names == {"SinglePlanPreparationInput", "PlanCollectionPreparationInput"}
    original = document["components"]["schemas"]["SinglePlanPreparationInput"]
    sources = original["properties"]["sources"]
    assert sources["minItems"] == sources["maxItems"] == 1
    source = resolved(document, sources["items"])
    assert source["properties"]["text"]["maxLength"] == 150000
    assert "source_id" in source["properties"] and "sourceId" not in source["properties"]
    view = document["components"]["schemas"]["PreparationView"]
    assert view["additionalProperties"] is False
    assert view["properties"]["attempts"]["maxItems"] == 3
    for name in ("revision", "sourceRevision", "candidateRevision", "reviewRevision"):
        assert view["properties"][name]["maximum"] == MAX_SAFE_INTEGER
    candidate = view["properties"]["candidate"]["anyOf"][0]
    assert candidate["discriminator"]["propertyName"] == "kind"
    assert set(candidate["discriminator"]["mapping"]) == {"EXTRACTION", "FROZEN", "UNAVAILABLE"}
    recovery = document["components"]["schemas"]["PreparationRecoveryCommand"]
    assert recovery["properties"]["confirmedEnded"]["const"] is True
    assert set(recovery["required"]) == {"expectedRevision", "generation", "confirmedEnded"}


def test_collection_contract_separates_bounded_summary_from_full_item_pages(document):
    schemas = document["components"]["schemas"]
    collection = schemas["PlanCollectionPreparationInput"]
    assert collection["properties"]["sources"]["minItems"] == 1
    assert collection["properties"]["sources"]["maxItems"] == 256
    response = document["paths"][BASE + "/{preparation_id}"]["get"]["responses"]["200"]
    names = reference_names(response["content"]["application/json"]["schema"])
    (collection_name,) = names - {"PreparationView"}
    root = schemas[collection_name]
    assert root["properties"]["schemaVersion"]["const"] == "backtest-preparation-v2"
    summary = resolved(document, root["properties"]["items"]["items"])
    assert {"sourceId", "sourceRevision", "candidateRevision", "status", "baseHash"} <= set(
        summary["properties"]
    )
    assert {"source", "candidate", "attempts"}.isdisjoint(summary["properties"])
    page_response = document["paths"][BASE + "/{preparation_id}/items"]["get"]["responses"]["200"]
    page = resolved(document, page_response["content"]["application/json"]["schema"])
    assert page["properties"]["items"]["maxItems"] == 100
    item = resolved(document, page["properties"]["items"]["items"])
    assert {"source", "candidate"} <= set(item["properties"])
    assert "nextOffset" in page["properties"]


@pytest.mark.parametrize("field", ["expected_revision", "source_revision", "candidate_revision"])
def test_collection_nested_review_revisions_reject_unsafe_integer(tmp_path, field):
    from tests.integration.test_plan_preparation_review import (
        collection_review_command,
        ready_collection,
    )

    from trade_plan_monitor.web.preparation_schemas import CollectionReviewInput

    _, record = ready_collection(tmp_path)
    review = collection_review_command(record).model_dump(mode="json")
    if field == "expected_revision":
        review[field] = MAX_SAFE_INTEGER + 1
    else:
        review["items"][0][field] = MAX_SAFE_INTEGER + 1
    with pytest.raises(ValidationError):
        CollectionReviewInput.model_validate_json(
            json.dumps(
                {
                    "schemaVersion": "backtest-preparation-v2",
                    "kind": "CHAIN_REVIEW",
                    "review": review,
                }
            )
        )


def test_candidate_schema_discriminates_extraction_frozen_and_unavailable():
    schema = PreparationView.model_json_schema(mode="serialization", by_alias=True)
    candidate = schema["properties"]["candidate"]["anyOf"][0]
    assert candidate["discriminator"]["propertyName"] == "kind"
    assert set(candidate["discriminator"]["mapping"]) == {"EXTRACTION", "FROZEN", "UNAVAILABLE"}
    for kind, reference in candidate["discriminator"]["mapping"].items():
        branch = schema["$defs"][reference.rsplit("/", 1)[1]]
        assert branch["properties"]["kind"]["const"] == kind
        if kind == "EXTRACTION":
            assert {"draft", "mapping", "openingAccount"} <= set(branch["required"])
            assert branch["properties"]["frozen"]["type"] == "null"
        elif kind == "FROZEN":
            assert "frozen" in branch["required"]
            assert branch["properties"]["draft"]["type"] == "null"
        else:
            assert branch["properties"]["validation"]["const"] == "INVALID"


@pytest.mark.parametrize(
    "case", ["missing-draft", "null-account", "frozen-missing", "unavailable-draft"]
)
def test_conflicting_candidate_variant_is_rejected(tmp_path, case):
    _store, record = ready_preparation(tmp_path)
    value = project_preparation(record).model_dump(mode="json", by_alias=True)
    candidate = value["candidate"]
    if case == "missing-draft":
        candidate.pop("draft")
    elif case == "null-account":
        candidate["openingAccount"] = None
    elif case == "frozen-missing":
        candidate.update(kind="FROZEN", draft=None, mapping=None, openingAccount=None)
    else:
        candidate.update(kind="UNAVAILABLE", validation="INVALID")
    with pytest.raises(ValidationError):
        PreparationView.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "field", ["expected_revision", "expected_source_revision", "expected_candidate_revision"]
)
def test_public_review_revision_rejects_unsafe_integer(tmp_path, field):
    _store, record = ready_preparation(tmp_path)
    review = review_command(record).model_dump(mode="json")
    review[field] = MAX_SAFE_INTEGER + 1
    with pytest.raises(ValidationError):
        PreparationReviewInput.model_validate_json(json.dumps({"review": review}))


def test_public_attempt_and_frozen_revision_schemas_are_safe():
    progress = PreparationView.model_json_schema(mode="serialization", by_alias=True)
    attempt_reference = progress["properties"]["attempts"]["items"]["$ref"]
    attempt = progress["$defs"][attempt_reference.rsplit("/", 1)[1]]
    assert attempt["properties"]["source_revision"]["maximum"] == MAX_SAFE_INTEGER
    frozen = PreparationFrozenView.model_json_schema(mode="serialization", by_alias=True)
    reference = frozen["properties"]["frozen"]["$ref"]
    manifest = frozen["$defs"][reference.rsplit("/", 1)[1]]
    for field in ("source_revision", "extraction_candidate_revision"):
        assert manifest["properties"][field]["maximum"] == MAX_SAFE_INTEGER
