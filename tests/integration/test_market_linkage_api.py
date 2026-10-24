"""Public API keeps sizing authority on the server and reads without mutations."""

from datetime import datetime, time, timedelta

import pytest
from tests.integration import test_market_linkage_runtime as linkage_fixture
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_linkage_runtime import (
    index_snapshot,
    linked_inputs,
)

linked_chain = linkage_fixture.linked_chain


def schema5_projection(document):
    """Remove only the approved additive fields/union variants for legacy comparisons."""
    from copy import deepcopy

    result = deepcopy(document)
    schemas = result["components"]["schemas"]
    additions = {
        "DailyEditorSchemaView": (
            "supportedSchemaVersions",
            "linkedCandidateSchema",
            "linkedPolicyDefinitions",
        ),
        "DailyEvaluationApiView": ("marketLinkage", "linkedIndexSource"),
        "DailySignalApiView": ("marketLinkage",),
        "DailySignalState": ("market_linkage",),
        "ExplicitPlanCapabilityView": ("supportedSchemaVersions", "linkedExecutionVersion"),
        "LoopEvaluation": ("market_linkage",),
        "ResearchDecisionEvent": ("market_linkage",),
    }
    for name, fields in additions.items():
        for field in fields:
            assert field in schemas[name]["properties"]
            del schemas[name]["properties"][field]
        if "required" in schemas[name]:
            schemas[name]["required"] = [f for f in schemas[name]["required"] if f not in fields]
    for name in (
        "CollectionCandidateView",
        "CollectionCorrectionDeclaration",
        "PlanCandidateReview",
        "PlanUpdateExtractionOutput",
        "PlanUpdateExtractionOutputInput",
        "PreparationExtractionCandidate",
        "PreparationReviewDeclaration",
        "LoopPlanVersion",
    ):
        field = "snapshot" if name == "LoopPlanVersion" else "draft"
        node = schemas[name]["properties"][field]
        nullable = {"type": "null"} in node.get("anyOf", [])
        union = node["anyOf"][0] if nullable else node
        variants = union.get("oneOf", union.get("anyOf"))
        assert len(variants) == 2
        assert variants[0]["$ref"].startswith("#/components/schemas/MarketLinked")
        assert variants[1]["$ref"].startswith("#/components/schemas/Unified")
        schemas[name]["properties"][field] = (
            {"anyOf": [variants[1], {"type": "null"}]} if nullable else variants[1]
        )
    return result


@pytest.mark.parametrize("profile", [1, 2])
def test_all_pre_linkage_schema_shapes_and_routes_are_preserved(profile):
    import json
    import subprocess
    from pathlib import Path

    from scripts import generate_frontend_types as generator

    root = Path(__file__).resolve().parents[2]
    path = "openapi.json" if profile == 1 else "openapi.runtime-status.json"
    prior = json.loads(subprocess.check_output(["git", "show", "c7378a4:" + path], cwd=root))
    current = schema5_projection(generator.build_openapi_document(monitor_contract_version=profile))
    assert current["paths"] == prior["paths"]
    for name, schema in prior["components"]["schemas"].items():
        assert current["components"]["schemas"][name] == schema, name


def ready(chain):
    chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    with chain.plans._unit_of_work() as work:
        revision = work.daily.get("simulation-position-" + chain.plan.symbol)["revision"]
    signal = result.snapshot["signals"][0]
    return {
        "planVersionId": chain.version["id"],
        "causeId": signal["signal_id"],
        "expectedCauseRevision": signal["revision"],
        "expectedInventoryRevision": revision,
        "quantity": 300,
    }


def test_generated_numeric_discriminator_and_fixed_tuple_keep_their_types():
    from tests.integration.test_openapi_snapshot import _load_generator

    document = {
        "components": {
            "schemas": {
                "Linked": {
                    "type": "object",
                    "properties": {"schema_version": {"const": 6}},
                    "required": ["schema_version"],
                },
                "Candidate": {
                    "oneOf": [{"$ref": "#/components/schemas/Linked"}],
                    "discriminator": {
                        "propertyName": "schema_version",
                        "mapping": {"6": "#/components/schemas/Linked"},
                    },
                },
                "Pair": {
                    "type": "array",
                    "prefixItems": [{"type": "string"}, {"type": "number"}],
                    "minItems": 2,
                    "maxItems": 2,
                },
            }
        },
        "paths": {},
    }
    typescript = _load_generator().render_typescript_contracts(document)
    assert "schema_version: 6" in typescript
    assert 'schema_version: "6"' not in typescript
    assert "[string, number]" in typescript


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 100},
        {"quantity": 400},
        {"expectedCauseRevision": 0},
        {"expectedInventoryRevision": 0},
    ],
)
def test_public_simulation_rejects_partial_override_and_stale_revision(linked_chain, change):
    chain = linked_chain
    command = ready(chain)
    chain.post(
        "simulated-trades", {**command, **change}, status=422 if "quantity" in change else 409
    )
    response = chain.client.get(
        "/api/v1/simulation-position-inventory",
        params={"symbol": chain.plan.symbol, "asOfTradeDate": str(TUESDAY)},
    )
    assert response.status_code == 200
    assert response.json()["snapshot"]["totalQty"] == 100


def test_public_schema_and_read_projection_preserve_linked_authority(linked_chain):
    chain = linked_chain
    command = ready(chain)
    contract = chain.client.get("/api/v1/plan-editor-schema").json()
    assert contract["supportedSchemaVersions"] == [5, 6]
    assert len(contract["linkedPolicyDefinitions"]) == 8
    first = chain.client.get("/api/v1/plan-runtime/" + chain.plan.symbol).json()
    assert first["snapshot"]["marketLinkage"][0]["calculation"]["authorized_quantity"] == 300
    with chain.plans._unit_of_work() as work:
        changed, _ = index_snapshot(chain.plan, correction=True)
        chain.now += timedelta(seconds=1)
        work.projections.put_market_index_snapshot(changed, provider_content_revision=2)
        work.projections.advance_market_index_head(
            changed, provider_content_revision=2, observed_at=chain.now
        )
        work.commit()
    with chain.plans._engine.connect() as connection:
        before = tuple(connection.connection.driver_connection.iterdump())
    blocked = chain.client.get("/api/v1/plan-runtime/" + chain.plan.symbol)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["reason"] == "MARKET_LINKAGE_SOURCE_CHANGED"
    assert blocked.json()["snapshot"]["signals"][0]["executableQty"] == 0
    with chain.plans._engine.connect() as connection:
        assert tuple(connection.connection.driver_connection.iterdump()) == before
    # A subsequent evaluation with an old cached input cannot restore the head.
    chain.now += timedelta(seconds=1)
    stale = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    assert stale.snapshot["signals"][0]["state"] == "INVALIDATED"
    chain.post("simulated-trades", command, status=409)
