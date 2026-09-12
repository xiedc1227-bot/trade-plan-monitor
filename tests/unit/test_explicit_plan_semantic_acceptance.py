from __future__ import annotations

import asyncio
import copy
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderType,
    BindingKind,
    BindingOrigin,
    ClauseDisposition,
    ExplicitPlanDraft,
    PlanExtractionStatus,
    PlanMapping,
    SecretReference,
)
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V4
from trade_plan_monitor.ai.provider import PlanExtractionRequest, RawAIResponse
from trade_plan_monitor.ai.review import build_server_review_snapshot, server_source_clauses

_CORPUS_PATH = (
    Path(__file__).parents[1] / "fixtures" / "ai" / "explicit-plan-semantic-acceptance-v2.json"
)
_PROVIDER_ID = UUID("8494b550-7119-4c66-8e32-3339ab6c95b3")
_REQUEST_ID = UUID("927b1e10-44a4-4e2f-8db0-579059a20351")
_SEMANTIC_CODES = frozenset({"UNRESOLVED_SEMANTICS", "UNSUPPORTED_SEMANTICS"})


class _StaticProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.request: PlanExtractionRequest | None = None

    async def test_connection(self, config: AIProviderConfig) -> None:
        raise AssertionError("not used")

    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse:
        self.request = request
        return RawAIResponse(
            request_id=request.request_id,
            provider_id=request.config.provider_id,
            model=request.config.model,
            content=self.content,
            finish_reason="stop",
            usage=None,
            attempts=1,
        )


def _config() -> AIProviderConfig:
    return AIProviderConfig(
        provider_id=_PROVIDER_ID,
        display_name="Offline semantic acceptance provider",
        provider_type=AIProviderType.OPENAI_COMPATIBLE,
        base_url="https://ai.example.test/v1",
        model="offline-semantic-v2",
        secret_ref=SecretReference(key="ai/provider/offline-semantic-v2"),
        prompt_version=PLAN_EXTRACTION_PROMPT_V4,
        max_retries=0,
    )


def _corpus() -> dict[str, object]:
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _get_path(value: object, path: str) -> object:
    current = value
    for part in path.replace("]", "").replace("[", ".").split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _scalar_paths(value: object, path: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _scalar_paths(child, f"{path}.{key}" if path else key)
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _scalar_paths(child, f"{path}[{index}]")
        ]
    return [] if value is None else [(path, value)]


def _is_contract_path(path: str) -> bool:
    return path in {
        "schema_version",
        "execution_mode",
        "execution_version",
        "plan_id",
        "version",
        "name",
        "market",
        "position.inventory_scope",
        "position.lot_size",
        "monitoring.indicator_formula_version",
    } or path.endswith(".rule_id")


def _draft(case: dict[str, object]) -> ExplicitPlanDraft:
    response = case["simulatedProviderResponse"]
    partial = response["partialDraft"]
    return ExplicitPlanDraft.model_validate_json(
        json.dumps(
            {
                "schema_version": 3,
                "execution_mode": "EXPLICIT_RULES",
                "execution_version": "explicit-rules-v1",
                "plan_id": str(case["id"]).lower(),
                "version": 1,
                "symbol": "003043.SZ",
                "name": str(case["id"]),
                "market": "SZSE",
                "metadata": {},
                "activation": partial.get("activation"),
                "position": {
                    "inventory_scope": "ALL_REGISTERED",
                    "lot_size": 100,
                    "max_qty": partial.get("positionMaxQty"),
                },
                "monitoring": {
                    "timeframe_minutes": partial.get("monitoringTimeframeMinutes"),
                    "indicator_formula_version": "ta-v1",
                },
                "rules": partial["rules"],
                "conflict_policy": partial.get("conflictPolicy"),
            },
            ensure_ascii=False,
        )
    )


def _provider_payload(case: dict[str, object]) -> dict[str, object]:
    source_text = str(case["sourceText"])
    draft = _draft(case)
    response = case["simulatedProviderResponse"]
    clauses = server_source_clauses(source_text)
    source_bindings = response["sourceBindings"]
    field_bindings = [
        {
            "path": item["path"],
            "value": item["value"],
            "unit": item["unit"],
            "origin": "SOURCE",
            "binding_kind": item.get("bindingKind", "VALUE"),
            "clause_ids": [clauses[item["clauseIndex"]].clause_id],
        }
        for item in source_bindings
    ]
    source_identities = {
        (item.get("bindingKind", "VALUE"), item["path"]) for item in source_bindings
    }
    for index, (path, value) in enumerate(_scalar_paths(draft.model_dump(mode="json"))):
        if _is_contract_path(path) and ("VALUE", path) not in source_identities:
            field_bindings.append(
                {
                    "path": path,
                    "value": value,
                    "unit": "SHARES" if path.endswith("lot_size") else "NONE",
                    "origin": "CONTRACT",
                    "contract_id": f"schema-v3-{index}",
                }
            )

    unresolved = set(response.get("unresolvedClauseIndexes", []))
    unsupported = set(response.get("unsupportedClauseIndexes", []))
    source_clauses = []
    for index, clause in enumerate(clauses):
        paths = tuple(item["path"] for item in source_bindings if item["clauseIndex"] == index)
        disposition = (
            ClauseDisposition.UNSUPPORTED
            if index in unsupported
            else ClauseDisposition.UNRESOLVED
            if index in unresolved
            else ClauseDisposition.MAPPED
        )
        source_clauses.append(
            clause.model_copy(update={"disposition": disposition, "paths": paths}).model_dump(
                mode="json"
            )
        )
    return {
        "draft": draft.model_dump(mode="json"),
        "mapping_version": "plan-mapping-v1",
        "source_clauses": source_clauses,
        "field_bindings": field_bindings,
        "assumptions": [],
        "warnings": [],
    }


def _extract(case: dict[str, object]):
    provider = _StaticProvider(json.dumps(_provider_payload(case), ensure_ascii=False))
    result = asyncio.run(
        extract_plan(
            request_id=_REQUEST_ID,
            source_text=str(case["sourceText"]),
            config=_config(),
            provider=provider,
        )
    )
    assert provider.request is not None
    assert "Prompt version: plan-extract-v4" in provider.request.prompt
    return result


def _cases() -> list[dict[str, object]]:
    return _corpus()["cases"]


def _counterexamples() -> list[dict[str, object]]:
    return _corpus()["supportedDefinitionCounterexamples"]


def test_v2_corpus_is_a_separate_simulated_provider_acceptance_oracle() -> None:
    corpus = _corpus()
    cases = corpus["cases"]

    assert corpus["schemaVersion"] == "explicit-plan-semantic-acceptance-v2"
    assert corpus["evidenceKind"] == "SIMULATED_PROVIDER_RESPONSE_NOT_REAL_AI"
    assert len(cases) == 20
    assert {
        category: sum(item["category"] == category for item in cases)
        for category in {"EXPLICIT", "AMBIGUOUS", "UNSUPPORTED"}
    } == {"EXPLICIT": 8, "AMBIGUOUS": 6, "UNSUPPORTED": 6}
    assert len({item["id"] for item in cases}) == 20
    assert all(item["simulatedProviderResponse"]["partialDraft"]["rules"] for item in cases)
    assert all(
        isinstance(item["simulatedProviderResponse"]["humanConfirmedTestSupplements"], list)
        for item in cases
    )
    assert all(item["simulatedProviderResponse"]["sourceBindings"] for item in cases)
    assert [item["id"] for item in corpus["supportedDefinitionCounterexamples"]] == [
        "SEM-CTX-01",
        "SEM-DEF-01",
    ]


@pytest.mark.parametrize("case", _cases(), ids=lambda item: str(item["id"]))
def test_each_v2_case_crosses_provider_parse_and_server_review_with_its_own_meaning(
    case: dict[str, object],
) -> None:
    result = _extract(case)

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert isinstance(result.draft, ExplicitPlanDraft)
    assert isinstance(result.mapping, PlanMapping)
    snapshot = build_server_review_snapshot(
        source_text=str(case["sourceText"]),
        draft=result.draft,
        mapping=result.mapping,
    )
    oracle = case["oracle"]
    draft_data = result.draft.model_dump(mode="json")
    source_bindings = [
        item for item in result.mapping.field_bindings if item.origin is BindingOrigin.SOURCE
    ]
    clauses = {item.clause_id: item for item in result.mapping.source_clauses}

    for expected in oracle["fields"]:
        assert _get_path(draft_data, expected["path"]) == expected["value"]
        [binding] = [item for item in source_bindings if item.path == expected["path"]]
        assert binding.value == expected["value"]
        assert binding.unit.value == expected["unit"]
        assert {clauses[clause_id].excerpt for clause_id in binding.clause_ids} == {
            expected["sourceExcerpt"]
        }
        assert any(
            issue.code == "SOURCE_MAPPING_REVIEW_REQUIRED"
            and issue.binding_path == expected["path"]
            and issue.clause_id in binding.clause_ids
            for issue in snapshot.required_issues
        )

    for expected in oracle["structures"]:
        structure = _get_path(draft_data, expected["path"])
        assert structure["type"] == expected["operator"]
        assert [item["type"] for item in structure["conditions"]] == expected["childTypes"]
        assert any(
            item.binding_kind is BindingKind.STRUCTURE
            and item.path == expected["path"]
            and item.value == expected["operator"]
            for item in source_bindings
        )

    actual_unresolved = sorted(
        issue.path
        for issue in snapshot.required_issues
        if issue.code == "UNRESOLVED_EXECUTION_POLICY"
    )
    actual_semantic = sorted(
        {issue.code for issue in snapshot.required_issues if issue.code in _SEMANTIC_CODES}
    )
    assert actual_unresolved == sorted(oracle["unresolvedPaths"])
    assert actual_semantic == sorted(oracle["semanticCodes"])
    for reason in oracle["unsupportedReasonFragments"]:
        assert any(
            issue.code == "UNSUPPORTED_SEMANTICS" and reason in issue.reason
            for issue in snapshot.required_issues
        )
    assert snapshot.can_activate is False


@pytest.mark.parametrize("case", _counterexamples(), ids=lambda item: str(item["id"]))
def test_explicit_context_and_numeric_definitions_cross_the_same_v4_review_chain(
    case: dict[str, object],
) -> None:
    test_each_v2_case_crosses_provider_parse_and_server_review_with_its_own_meaning(case)


def test_adversarial_units_omissions_and_unreviewed_semantic_mutations_fail_closed() -> None:
    cases = {item["id"]: item for item in _cases()}

    wrong_unit = copy.deepcopy(cases["SEM-EXP-01"])
    wrong_unit["simulatedProviderResponse"]["sourceBindings"][1]["unit"] = "SHARES"
    assert _extract(wrong_unit).status is PlanExtractionStatus.INVALID_OUTPUT

    omitted_volume = copy.deepcopy(cases["SEM-EXP-03"])
    omitted_volume["simulatedProviderResponse"]["sourceBindings"] = [
        item
        for item in omitted_volume["simulatedProviderResponse"]["sourceBindings"]
        if item["path"] != "rules[0].condition.conditions[1].window_bars"
    ]
    omitted_result = _extract(omitted_volume)
    assert any(
        issue.code == "UNMAPPED_PLAN_FIELD"
        and issue.path == "rules[0].condition.conditions[1].window_bars"
        for issue in omitted_result.validation_issues
    )

    wrong_quantity = copy.deepcopy(cases["SEM-EXP-01"])
    wrong_quantity["simulatedProviderResponse"]["partialDraft"]["rules"][0]["action"][
        "quantity"
    ] = 200
    quantity_binding = next(
        item
        for item in wrong_quantity["simulatedProviderResponse"]["sourceBindings"]
        if item["path"] == "rules[0].action.quantity"
    )
    quantity_binding["value"] = 200
    quantity_result = _extract(wrong_quantity)
    quantity_snapshot = build_server_review_snapshot(
        source_text=wrong_quantity["sourceText"],
        draft=quantity_result.draft,
        mapping=quantity_result.mapping,
    )
    assert quantity_snapshot.can_activate is False
    assert any(
        issue.code == "SOURCE_MAPPING_REVIEW_REQUIRED"
        and issue.binding_path == "rules[0].action.quantity"
        for issue in quantity_snapshot.required_issues
    )

    wrong_action = copy.deepcopy(cases["SEM-EXP-01"])
    wrong_action["simulatedProviderResponse"]["partialDraft"]["rules"][0]["action"]["type"] = "SELL"
    wrong_action["simulatedProviderResponse"]["partialDraft"]["rules"][0]["action"][
        "inventory_scope"
    ] = None
    action_binding = next(
        item
        for item in wrong_action["simulatedProviderResponse"]["sourceBindings"]
        if item["path"] == "rules[0].action.type"
    )
    action_binding["value"] = "SELL"
    action_result = _extract(wrong_action)
    assert action_result.status is PlanExtractionStatus.SUCCEEDED
    action_snapshot = build_server_review_snapshot(
        source_text=wrong_action["sourceText"],
        draft=action_result.draft,
        mapping=action_result.mapping,
    )
    assert action_snapshot.can_activate is False
    assert any(
        issue.code == "SOURCE_MAPPING_REVIEW_REQUIRED"
        and issue.binding_path == "rules[0].action.type"
        for issue in action_snapshot.required_issues
    )

    wrong_logic = copy.deepcopy(cases["SEM-EXP-03"])
    condition = wrong_logic["simulatedProviderResponse"]["partialDraft"]["rules"][0]["condition"]
    condition["type"] = "ANY"
    for binding in wrong_logic["simulatedProviderResponse"]["sourceBindings"]:
        if binding["path"] in {"rules[0].condition", "rules[0].condition.type"}:
            binding["value"] = "ANY"
    logic_result = _extract(wrong_logic)
    logic_snapshot = build_server_review_snapshot(
        source_text=wrong_logic["sourceText"],
        draft=logic_result.draft,
        mapping=logic_result.mapping,
    )
    assert logic_snapshot.can_activate is False
    assert any(
        issue.code == "SOURCE_MAPPING_REVIEW_REQUIRED"
        and issue.binding_path == "rules[0].condition"
        for issue in logic_snapshot.required_issues
    )

    wrong_parent = copy.deepcopy(cases["SEM-EXP-03"])
    structure_binding = next(
        item
        for item in wrong_parent["simulatedProviderResponse"]["sourceBindings"]
        if item.get("bindingKind") == "STRUCTURE" and item["path"] == "rules[0].condition"
    )
    structure_binding["clauseIndex"] = 0
    parent_result = _extract(wrong_parent)
    assert parent_result.status is PlanExtractionStatus.SUCCEEDED
    parent_snapshot = build_server_review_snapshot(
        source_text=wrong_parent["sourceText"],
        draft=parent_result.draft,
        mapping=parent_result.mapping,
    )
    parent_clause = parent_result.mapping.source_clauses[0]
    assert parent_snapshot.can_activate is False
    assert any(
        issue.code == "SOURCE_MAPPING_REVIEW_REQUIRED"
        and issue.binding_path == "rules[0].condition"
        and issue.clause_id == parent_clause.clause_id
        for issue in parent_snapshot.required_issues
    )

    added_parameter = copy.deepcopy(cases["SEM-EXP-01"])
    added_parameter["simulatedProviderResponse"]["partialDraft"]["positionMaxQty"] = 400
    added_result = _extract(added_parameter)
    assert any(
        issue.code == "UNMAPPED_PLAN_FIELD" and issue.path == "position.max_qty"
        for issue in added_result.validation_issues
    )


@pytest.mark.parametrize(
    ("clause_index", "expected_path"),
    [(3, "rules[1].action.type"), (4, "rules[2].action.type")],
    ids=["omitted-sell-clause", "omitted-risk-clause"],
)
def test_full_plan_omitted_action_clauses_remain_explicitly_unresolved(
    clause_index: int,
    expected_path: str,
) -> None:
    case = copy.deepcopy(_corpus()["fullSyntheticPlan"])
    response = case["simulatedProviderResponse"]
    response["sourceBindings"] = [
        item for item in response["sourceBindings"] if item["clauseIndex"] != clause_index
    ]
    response["unresolvedClauseIndexes"].append(clause_index)

    result = _extract(case)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    omitted_clause = result.mapping.source_clauses[clause_index]
    assert omitted_clause.disposition is ClauseDisposition.UNRESOLVED
    snapshot = build_server_review_snapshot(
        source_text=case["sourceText"],
        draft=result.draft,
        mapping=result.mapping,
    )
    assert snapshot.can_activate is False
    assert any(
        issue.code == "UNRESOLVED_SEMANTICS" and issue.clause_id == omitted_clause.clause_id
        for issue in snapshot.required_issues
    )
    assert any(
        issue.code == "UNMAPPED_PLAN_FIELD" and issue.path == expected_path
        for issue in snapshot.required_issues
    )


def test_full_synthetic_plan_preserves_omitted_clauses_and_policy_gaps() -> None:
    case = _corpus()["fullSyntheticPlan"]
    result = _extract(case)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    snapshot = build_server_review_snapshot(
        source_text=case["sourceText"],
        draft=result.draft,
        mapping=result.mapping,
    )

    unresolved = {
        issue.path
        for issue in snapshot.required_issues
        if issue.code == "UNRESOLVED_EXECUTION_POLICY"
    }
    assert unresolved == {
        "activation",
        "conflict_policy",
        "rules[0].condition.conditions[1].history_scope",
        "rules[0].repeat_policy",
        "rules[1].repeat_policy",
        "rules[2].repeat_policy",
    }
    assertion_clause = result.mapping.source_clauses[-1]
    assert assertion_clause.excerpt == "提醒和确认不代表成交。"
    assert assertion_clause.disposition is ClauseDisposition.UNRESOLVED
    assert any(
        issue.code == "UNRESOLVED_SEMANTICS" and issue.clause_id == assertion_clause.clause_id
        for issue in snapshot.required_issues
    )
    assert snapshot.can_activate is False
    assert sha256(case["sourceText"].encode()).hexdigest() == snapshot.source_hash
