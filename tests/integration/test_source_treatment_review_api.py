"""Literal-source acceptance: model output is input, not the semantic oracle."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.integration.test_explicit_plan_review_api import (
    _EXTRACTION_ID,
    _NOW,
    _draft_payload,
    _get_path,
    _is_contract,
    _logical_paths,
    _Runtime,
    _scalar_paths,
    _unit,
)
from tests.integration.test_source_treatment_inventory_isolation import (
    CONFIRMATION,
    INVENTORY_QUERY,
    NOW,
    _seed_calendar,
    _work,
)
from tests.unit.test_ai_plan_extraction_v4 import _config, _StaticProvider

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    BindingKind,
    BindingOrigin,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanExtractionStatus,
    PlanMapping,
    UserSupplement,
)
from trade_plan_monitor.ai.review import dump_explicit_plan_draft_json, server_source_clauses
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import PlanReviewProvenance
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.position_service import PersistentPositionOperationService
from trade_plan_monitor.web.routers.plans import PlanMappingView

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/ai/explicit-plan-literal-source-v3.json").read_text(
        encoding="utf-8"
    )
)
SOURCE = FIXTURE["sourceText"]


def _literal_mapping(draft: ExplicitPlanDraft, *, supplemented: bool = False) -> PlanMapping:
    clauses = server_source_clauses(SOURCE)
    paths = [[] for _ in clauses]
    bindings = []
    supplements = []

    def source_index(path: str) -> int:
        if path == "symbol":
            return 0
        if path == "position.max_qty":
            return 2
        if path == "monitoring.timeframe_minutes":
            return 3
        if path.startswith("rules[0]."):
            if ".action." in path:
                return 7
            if path.endswith("minimum_ratio"):
                return 6
            if ".conditions[1]." in path or path in {
                "rules[0].condition",
                "rules[0].condition.type",
            }:
                return 5
            return 4 if path.endswith(("include_low", "include_high")) else 3
        if path.startswith("rules[1]."):
            if ".action." in path:
                return 10
            return 9 if path.endswith(("include_low", "include_high")) else 8
        if path.startswith("rules[2]."):
            return 12 if ".action." in path else 11
        raise AssertionError(f"No independent source assignment: {path}")

    data = draft.model_dump(mode="json")
    for path, value in _scalar_paths(data) + _logical_paths(data):
        kind = BindingKind.STRUCTURE if (path, value) in _logical_paths(data) else BindingKind.VALUE
        fields = {"path": path, "value": value, "unit": _unit(path), "binding_kind": kind}
        if _is_contract(path):
            bindings.append(
                FieldBinding(
                    **fields, origin=BindingOrigin.CONTRACT, contract_id="explicit-rules-v1"
                )
            )
        elif supplemented and path in FIXTURE["humanTestSupplements"]:
            item = UserSupplement(
                supplement_id=f"human-{len(supplements)}",
                path=path,
                value=value,
                unit=_unit(path),
                supplied_at=_NOW,
                label="human_confirmed_test_supplement",
            )
            supplements.append(item)
            bindings.append(
                FieldBinding(
                    **fields, origin=BindingOrigin.USER_SUPPLEMENT, supplement_id=item.supplement_id
                )
            )
        else:
            index = source_index(path)
            paths[index].append(path)
            bindings.append(
                FieldBinding(
                    **fields, origin=BindingOrigin.SOURCE, clause_ids=(clauses[index].clause_id,)
                )
            )
    return PlanMapping(
        source_clauses=tuple(
            clause.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED
                    if paths[index]
                    else ClauseDisposition.UNRESOLVED,
                    "paths": tuple(paths[index]),
                }
            )
            for index, clause in enumerate(clauses)
        ),
        field_bindings=tuple(bindings),
        user_supplements=tuple(supplements),
    )


def _extract_literal(lifecycle):
    simulated = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    mapping = _literal_mapping(simulated)
    output = {
        "draft": simulated.model_dump(mode="json"),
        "mapping_version": "plan-mapping-v1",
        "source_clauses": [item.model_dump(mode="json") for item in mapping.source_clauses],
        "field_bindings": [item.model_dump(mode="json") for item in mapping.field_bindings],
        "assumptions": [],
        "warnings": [],
    }
    provider = _StaticProvider(json.dumps(output, ensure_ascii=False))
    result = asyncio.run(
        extract_plan(
            request_id=_EXTRACTION_ID, source_text=SOURCE, config=_config(), provider=provider
        )
    )
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert json.dumps(SOURCE, ensure_ascii=False) in provider.request.prompt
    data = result.draft.model_dump(mode="json")
    for path, expected in FIXTURE["independentExpectedValues"].items():
        assert _get_path(data, path) == expected, path
    assert result.mapping.mapping_version == "plan-mapping-v1"
    asyncio.run(lifecycle.record_plan_extraction(result))
    return result.draft


def _save(client, draft, *, key, base=None, mapping=None):
    body = {
        "planJson": dump_explicit_plan_draft_json(draft),
        "sourceText": SOURCE,
        "expectedRevision": 0,
    }
    body.update(
        {"extractionId": str(_EXTRACTION_ID)} if base is None else {"basePlanVersionId": base}
    )
    if mapping is not None:
        body["mapping"] = mapping
    return client.post("/api/v1/plan-drafts", headers={"Idempotency-Key": key}, json=body)


def _assert_current_semantic_review(detail):
    """A simulated human checks CURRENT values and spans against a separate oracle."""
    data = json.loads(detail["planJson"])
    source_expected = FIXTURE["independentExpectedValues"]
    source_bindings = {
        item["path"]: item
        for item in detail["mapping"]["fieldBindings"]
        if item["origin"] == "SOURCE"
    }
    assert set(source_bindings) == set(FIXTURE["expectedSourceClauses"])
    clauses = server_source_clauses(SOURCE)
    for path, index in FIXTURE["expectedSourceClauses"].items():
        binding = source_bindings[path]
        structural = path == "rules[0].condition"
        expected = "ALL" if structural else source_expected[path]
        actual = _get_path(data, path)
        assert (actual["type"] if structural else actual) == expected, path
        assert binding["value"] == expected, path
        assert binding["unit"] == FIXTURE["expectedSourceUnits"].get(path, "NONE"), path
        assert binding["bindingKind"] == ("STRUCTURE" if structural else "VALUE"), path
        assert binding["clauseIds"] == [clauses[index].clause_id], path
        returned = detail["mapping"]["sourceClauses"][index]
        assert (
            returned["excerpt"]
            == SOURCE[returned["start"] : returned["end"]]
            == clauses[index].excerpt
        )
        assert path in returned["paths"]
    supplements = detail["mapping"]["userSupplements"]
    if supplements:
        assert {item["path"]: item["value"] for item in supplements} == FIXTURE[
            "humanTestSupplements"
        ]
        for item in supplements:
            assert _get_path(data, item["path"]) == item["value"]
            assert item["label"] == "human_confirmed_test_supplement"
    else:
        for path, expected in source_expected.items():
            assert _get_path(data, path) == expected, path
    # No trading scalar outside the independently enumerated origins is approved.
    assert {path for path, _ in _scalar_paths(data) if not _is_contract(path)} == (
        set(source_bindings) - {"rules[0].condition"}
    ) | {item["path"] for item in supplements}
    inventory, product = detail["mapping"]["sourceProcessing"]["treatments"]
    assert inventory["symbol"] == "003043.SZ"
    assert inventory["totalQuantity"] == inventory["sellableQuantity"] == 100
    assert inventory["contractId"] == "independent-inventory-v1"
    assert inventory["settlementBasis"] == "HELD_BEFORE_TEST_DATE_ALL_SELLABLE"
    assert inventory["ledgerEffect"] == "NONE_REQUIRES_INDEPENDENT_CONFIRMATION"
    assert inventory["symbolSpan"]["excerpt"] == "003043.SZ"
    assert [item["excerpt"] for item in inventory["spans"]] == [
        "当前持仓100股，",
        "均为测试日前已持有且当日可卖；",
    ]
    assert product["contractId"] == "alert-position-isolation-v1"
    assert [item["excerpt"] for item in product["spans"]] == [
        "提醒及确认收到提醒不代表成交，",
        "未登记成交时持仓不变。",
    ]
    for treatment in (inventory, product):
        for span in treatment["spans"]:
            assert SOURCE[span["start"] : span["end"]] == span["excerpt"]


def _resolutions(detail, *, include_treatments=True):
    _assert_current_semantic_review(detail)
    supplements = {
        item["path"]: item["supplementId"] for item in detail["mapping"]["userSupplements"]
    }
    result = []
    for issue in detail["requiredReviewIssues"]:
        kind = {
            "SOURCE_MAPPING_REVIEW_REQUIRED": "CONFIRM_MAPPING",
            "SOURCE_TREATMENT_REVIEW_REQUIRED": "CONFIRM_SOURCE_TREATMENT",
            "USER_SUPPLEMENT_REVIEW_REQUIRED": "CONFIRM_POLICY",
        }.get(issue["code"])
        if kind is None:
            continue
        assert kind in issue["allowedResolutions"]
        item = {"issueId": issue["issueId"], "resolution": kind}
        if kind == "CONFIRM_SOURCE_TREATMENT" and not include_treatments:
            continue
        if kind in {"CONFIRM_MAPPING", "CONFIRM_SOURCE_TREATMENT"}:
            item["bindingPath"] = issue["bindingPath"]
        elif kind == "CONFIRM_POLICY" and issue["path"] in supplements:
            item["supplementId"] = supplements[issue["path"]]
        else:
            continue
        result.append(item)
    return result


def _confirm(client, detail, resolutions, *, key, revision=0):
    return client.post(
        "/api/v1/plan-review-confirmations",
        headers={"Idempotency-Key": key},
        json={
            "planVersionId": detail["id"],
            "contentHash": detail["contentHash"],
            "sourceHash": detail["sourceHash"],
            "reviewEvidenceHash": detail["reviewEvidenceHash"],
            "expectedRevision": revision,
            "resolutions": resolutions,
        },
    )


@pytest.fixture
def workspace(tmp_path):
    database = tmp_path / "literal.sqlite3"
    engine = create_sqlite_engine(database)
    lifecycle = PersistentPlanWebLifecycle(database_path=database, clock=lambda: _NOW)
    app = create_app(
        runtime_factory=_Runtime,
        plan_lifecycle_factory=lambda: lifecycle,
        position_service=PersistentPositionOperationService(
            unit_of_work_factory=lambda: _work(engine), clock=lambda: NOW
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
        _seed_calendar(engine)
        draft = _extract_literal(lifecycle)
        response = _save(client, draft, key="literal-partial")
        assert response.status_code == 200, response.text
        yield client, engine, draft, response.json()
    engine.dispose()


def _complete(client, draft, first):
    data = _draft_payload(complete=True)
    data["version"] = 2
    data["activation"] = {"mode": "TRADING_DAY", "trading_day": "2026-09-14"}
    complete = ExplicitPlanDraft.model_validate_json(json.dumps(data))
    mapping = _literal_mapping(complete, supplemented=True)
    response = _save(
        client,
        complete,
        key="literal-complete",
        base=first["id"],
        mapping=PlanMappingView.from_domain(mapping).model_dump(mode="json", by_alias=True),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_literal_source_completes_current_review_without_initializing_inventory(workspace):
    client, _, draft, first = workspace
    assert (
        FIXTURE["literalUserSource"].replace(
            FIXTURE["soleSubstitution"]["from"], FIXTURE["soleSubstitution"]["to"]
        )
        == SOURCE
    )
    unknown = client.get("/api/v1/position-inventory", params=INVENTORY_QUERY).json()
    assert unknown["status"] == "UNKNOWN"
    assert unknown["totalQuantity"] is None and unknown["sellableQuantity"] is None
    assert first["sourceText"] == SOURCE and first["canActivate"] is False
    treatments = first["mapping"]["sourceProcessing"]["treatments"]
    assert [item["kind"] for item in treatments] == ["INVENTORY_ASSERTION", "PRODUCT_GUARANTEE"]
    assert treatments[0]["totalQuantity"] == treatments[0]["sellableQuantity"] == 100
    for item in treatments:
        for span in item["spans"]:
            assert SOURCE[span["start"] : span["end"]] == span["excerpt"]
    partial_review = _confirm(client, first, _resolutions(first), key="literal-missing-policies")
    assert partial_review.status_code == 200, partial_review.text
    assert (
        partial_review.json()["canActivate"] is False and partial_review.json()["reviewId"] is None
    )
    assert {item["path"] for item in partial_review.json()["unresolvedIssues"]} == {
        "activation",
        "conflict_policy",
        "rules[0].condition.conditions[1].history_scope",
        "rules[0].repeat_policy",
        "rules[1].repeat_policy",
        "rules[2].repeat_policy",
    }

    second = _complete(client, draft, first)
    assert second["contentHash"] != first["contentHash"]
    assert {
        item["path"]: item["value"] for item in second["mapping"]["userSupplements"]
    } == FIXTURE["humanTestSupplements"]
    assert {item["label"] for item in second["mapping"]["userSupplements"]} == {
        "human_confirmed_test_supplement"
    }
    stale = dict(first, id=second["id"])
    assert _confirm(client, stale, [], key="literal-stale").status_code == 409
    mappings_only = _confirm(
        client, second, _resolutions(second, include_treatments=False), key="literal-mappings-only"
    )
    assert mappings_only.status_code == 200, mappings_only.text
    assert mappings_only.json()["canActivate"] is False
    assert {issue["code"] for issue in mappings_only.json()["unresolvedIssues"]} == {
        "SOURCE_TREATMENT_REVIEW_REQUIRED"
    }
    reviewed = _confirm(client, second, _resolutions(second), key="literal-all-current", revision=1)
    assert reviewed.status_code == 200, reviewed.text
    approved = reviewed.json()
    assert approved["canActivate"] is True and approved["reviewId"]
    restored = client.get(f"/api/v1/plan-versions/{second['id']}")
    assert restored.status_code == 200 and restored.json()["canActivate"] is True
    assert restored.json()["executionReadiness"] == "NOT_EVALUATED"
    assert restored.json()["mapping"] == second["mapping"]
    assert client.get("/api/v1/position-inventory", params=INVENTORY_QUERY).json() == unknown
    activation = client.post(
        "/api/v1/plan-activations",
        headers={"Idempotency-Key": "literal-activation-blocked"},
        json={
            "planVersionId": second["id"],
            "reviewId": approved["reviewId"],
            "contentHash": second["contentHash"],
            "expectedRevision": 0,
        },
    )
    assert activation.status_code == 409
    assert client.get("/api/v1/plan-capabilities").json()["publicActivationAvailable"] is False
    # Separate public operation: source save/review above left the ledger UNKNOWN.
    registered = client.post(
        "/api/v1/position-inventory-confirmations",
        headers={"Idempotency-Key": "literal-register-independent-100"},
        json=CONFIRMATION,
    )
    assert registered.status_code == 200, registered.text
    known = registered.json()
    assert known["totalQuantity"] == known["sellableQuantity"] == 100
    retry = client.post(
        "/api/v1/position-inventory-confirmations",
        headers={"Idempotency-Key": "literal-register-independent-100"},
        json=CONFIRMATION,
    )
    assert retry.status_code == 200 and retry.json() == known
    reconfirm = client.post(
        "/api/v1/position-inventory-confirmations",
        headers={"Idempotency-Key": "literal-reconfirm-independent-100"},
        json=dict(CONFIRMATION, expectedRevision=1),
    )
    assert reconfirm.status_code == 200, reconfirm.text
    assert reconfirm.json()["totalQuantity"] == reconfirm.json()["sellableQuantity"] == 100
    assert reconfirm.json()["openingBalances"] == known["openingBalances"]
    after_inventory = client.get(f"/api/v1/plan-versions/{second['id']}").json()
    assert after_inventory["reviewId"] == approved["reviewId"]
    assert after_inventory["reviewEvidenceHash"] == second["reviewEvidenceHash"]


@pytest.mark.parametrize(
    "attack",
    ["quantity", "sellable", "contract", "span", "omit", "remove-processing", "remove-clause"],
)
def test_forged_source_processing_cannot_be_saved(workspace, attack):
    client, _, draft, first = workspace
    mapping = copy.deepcopy(first["mapping"])
    treatment = mapping["sourceProcessing"]["treatments"][0]
    if attack == "quantity":
        treatment["totalQuantity"] = 200
    elif attack == "sellable":
        treatment["sellableQuantity"] = 0
    elif attack == "contract":
        treatment["contractId"] = "trust-source-as-ledger-v1"
    elif attack == "span":
        treatment["spans"][0]["start"] += 1
    elif attack == "omit":
        mapping["sourceProcessing"]["treatments"].pop()
    elif attack == "remove-processing":
        mapping.pop("sourceProcessing")
    else:
        mapping["sourceClauses"].pop()
    response = _save(
        client, draft, key=f"literal-forge-{attack}", base=first["id"], mapping=mapping
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("attack", ["processing", "resolution"])
def test_tampered_stored_processing_or_resolution_fails_closed(workspace, attack):
    client, engine, draft, first = workspace
    second = _complete(client, draft, first)
    result = _confirm(client, second, _resolutions(second), key="literal-before-tamper")
    assert result.status_code == 200 and result.json()["canActivate"] is True
    with create_session_factory(engine)() as session:
        row = session.scalar(
            select(PlanReviewProvenance).where(PlanReviewProvenance.plan_version_id == second["id"])
        )
        if attack == "processing":
            value = json.loads(row.mapping_json)
            value["source_processing"]["treatments"][0]["sellable_quantity"] = 0
            row.mapping_json = json.dumps(value)
        else:
            value = json.loads(row.resolutions_json)
            item = next(item for item in value if item["resolution"] == "CONFIRM_SOURCE_TREATMENT")
            item["binding_path"] = "symbol"
            row.resolutions_json = json.dumps(value)
        session.commit()
    response = client.get(f"/api/v1/plan-versions/{second['id']}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "source_processing" not in response.text


@pytest.mark.parametrize(
    "attack", ["wrong-path", "supplement", "wrong-resolution", "invented-issue"]
)
def test_treatment_confirmation_cannot_be_forged(workspace, attack):
    client, _, draft, first = workspace
    second = _complete(client, draft, first)
    item = next(
        item for item in _resolutions(second) if item["resolution"] == "CONFIRM_SOURCE_TREATMENT"
    )
    if attack == "wrong-path":
        item["bindingPath"] = "symbol"
    elif attack == "supplement":
        item["supplementId"] = second["mapping"]["userSupplements"][0]["supplementId"]
    elif attack == "wrong-resolution":
        item["resolution"] = "CONFIRM_MAPPING"
    else:
        item["issueId"] = "issue-000000000000000000000000"
    response = _confirm(client, second, [item], key=f"forged-resolution-{attack}")
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/plan-versions/{second['id']}").json()["reviewId"] is None


@pytest.mark.parametrize("attack", ["price", "quantity", "logic", "clause"])
def test_current_semantic_oracle_refuses_source_wrong_but_internally_consistent_mapping(
    workspace, attack
):
    client, _, draft, first = workspace
    second = _complete(client, draft, first)
    current = copy.deepcopy(second)
    data = json.loads(current["planJson"])
    if attack == "price":
        data["rules"][0]["condition"]["conditions"][0]["low_fen"] = 970
        path, value = "rules[0].condition.conditions[0].low_fen", 970
    elif attack == "quantity":
        data["rules"][0]["action"]["quantity"] = 200
        path, value = "rules[0].action.quantity", 200
    elif attack == "logic":
        data["rules"][0]["condition"]["type"] = "ANY"
        path, value = "rules[0].condition.type", "ANY"
    else:
        path, value = "rules[0].condition.conditions[0].low_fen", 980
    for binding in current["mapping"]["fieldBindings"]:
        if binding["path"] == path:
            binding["value"] = value
            if attack == "clause":
                binding["clauseIds"] = [current["mapping"]["sourceClauses"][8]["clauseId"]]
        if attack == "logic" and binding["path"] == "rules[0].condition":
            binding["value"] = "ANY"
    current["planJson"] = json.dumps(data)
    with pytest.raises(AssertionError):
        _resolutions(current)
