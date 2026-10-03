"""Literal source remains an independent oracle for the one current plan API."""

import asyncio
import copy
import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.integration.test_current_plan_api import make_app, post, review_payload
from tests.unit.test_ai_plan_extraction_v4 import _config, _StaticProvider
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.ai.daily_review import DailyMapping, semantic_values
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import PlanReviewProvenance

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/ai/explicit-plan-literal-source-v3.json").read_text(
        "utf-8"
    )
)
SOURCE = FIXTURE["sourceText"]

# These values are enumerated from literal source, rather than provider/serializer output.
SOURCE_VALUES = {
    "position.max_qty": (300, 2, "SHARES"),
    "ordinary_rules[0].quantity": (100, 7, "SHARES"),
    "ordinary_rules[0].condition.conditions[0].low_fen": (980, 3, "FEN_FROM_YUAN"),
    "ordinary_rules[0].condition.conditions[0].high_fen": (1000, 3, "FEN_FROM_YUAN"),
    "ordinary_rules[0].condition.conditions[1].window_bars": (5, 5, "JSON"),
    "ordinary_rules[0].condition.conditions[1].minimum_ratio": ("1.5", 6, "RATIO"),
    "ordinary_rules[1].quantity": (100, 10, "SHARES"),
    "ordinary_rules[1].condition.low_fen": (1080, 8, "FEN_FROM_YUAN"),
    "ordinary_rules[1].condition.high_fen": (1100, 8, "FEN_FROM_YUAN"),
    "alert_rules[0].condition.price_fen": (950, 11, "FEN_FROM_YUAN"),
}


def path_value(data, path):
    value = data
    for key, index in re.findall(r"([a-z_]+)|\[(\d+)\]", path):
        value = value[int(index)] if index else value[key]
    return value


def literal_draft(*, complete):
    def rule(side, condition):
        return {
            "status": "ENABLED",
            "side": side,
            "rule_id": side.lower() + "-100",
            "quantity": 100,
            "bucket": "TACTICAL",
            "zone": None,
            "condition": condition,
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            "execution_window": "CURRENT_SESSION",
            "validity": {
                "mode": "DATE_RANGE",
                "start_date": "2026-09-14",
                "end_date": "2026-09-14",
            },
            "invalidation": "RISK_OR_REVIEWED_INVALIDATION",
            "independent_signal": {
                "mode": "REVIEWED_INDEPENDENT_EVENT",
                "evidence_requirement": "Human confirms a new independent technical event",
            }
            if complete
            else None,
        }

    return UnifiedPlanDraft.model_validate(
        {
            "schema_version": 5,
            "execution_mode": "CONDITION_PLAN",
            "execution_version": "condition-plan-v1",
            "plan_id": "literal-current",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "Literal current source",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "MANUAL"} if complete else None,
            "levels": None,
            "position": {"max_qty": 300},
            "monitoring": None,
            "ordinary_rules": [
                rule(
                    "BUY",
                    {
                        "type": "ALL",
                        "conditions": [
                            {
                                "type": "MINUTE_CLOSE_IN_RANGE",
                                "timeframe_minutes": 5,
                                "low_fen": 980,
                                "high_fen": 1000,
                                "include_low": True,
                                "include_high": True,
                            },
                            {
                                "type": "MINUTE_VOLUME_TO_MEAN_GTE",
                                "timeframe_minutes": 5,
                                "window_bars": 5,
                                "minimum_ratio": "1.5",
                                "history_scope": "CONTIGUOUS_TRADING_BARS",
                            },
                        ],
                    },
                ),
                rule(
                    "SELL",
                    {
                        "type": "MINUTE_CLOSE_IN_RANGE",
                        "timeframe_minutes": 5,
                        "low_fen": 1080,
                        "high_fen": 1100,
                        "include_low": True,
                        "include_high": True,
                    },
                ),
            ],
            "alert_rules": [
                {
                    "kind": "RISK_ALERT",
                    "rule_id": "risk-950",
                    "condition": {
                        "type": "MINUTE_CLOSE_BELOW",
                        "timeframe_minutes": 5,
                        "price_fen": 950,
                    },
                    "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                }
            ],
            "risk_branches": [],
            "execution_policy": {
                "same_signal": "ONE_PLANNED_QUANTITY",
                "risk_priority": "SEVERE_THEN_ORDINARY",
                "ordinary_conflict": "BLOCK_BOTH",
            },
        }
    )


def literal_mapping(draft):
    raw = reviewed_mapping(draft, SOURCE).model_dump(mode="json")
    raw["supplements"] = [s for s in raw["supplements"] if s["path"] not in SOURCE_VALUES]
    for binding in raw["bindings"]:
        path = binding["path"]
        if path in SOURCE_VALUES:
            _, index, unit = SOURCE_VALUES[path]
            binding.update(
                origin="SOURCE",
                unit=unit,
                supplement_id=None,
                clause_ids=[raw["clauses"][index]["clause_id"]],
            )
    for clause in raw["clauses"][:2]:
        clause.update(
            disposition="INVENTORY_ASSERTION",
            paths=[],
            reason="Historical holdings assertion is context only; no inventory initialized.",
        )
    return DailyMapping.model_validate(raw)


def assert_semantic_review(detail):
    data = json.loads(detail["planJson"])
    mapping = detail["dailyMapping"]
    clauses = mapping["clauses"]
    source_bindings = {b["path"]: b for b in mapping["bindings"] if b["origin"] == "SOURCE"}
    assert set(source_bindings) == set(SOURCE_VALUES)
    for path, (expected, index, unit) in SOURCE_VALUES.items():
        binding = source_bindings[path]
        assert path_value(data, path) == binding["value"] == expected, path
        assert binding["unit"] == unit
        assert binding["clause_ids"] == [clauses[index]["clause_id"]]
        assert path in clauses[index]["paths"]
    for clause in clauses:
        assert clause["excerpt"] == SOURCE[clause["start"] : clause["end"]]
    for clause in clauses[:2]:
        assert clause["disposition"] == "INVENTORY_ASSERTION" and clause["paths"] == []
        assert "no inventory initialized" in clause["reason"]
    assert data["symbol"] == "003043.SZ"
    buy, sell = data["ordinary_rules"]
    assert buy["side"] == "BUY" and sell["side"] == "SELL"
    assert buy["condition"]["type"] == "ALL"
    for price in (buy["condition"]["conditions"][0], sell["condition"]):
        assert price["include_low"] is price["include_high"] is True
        assert price["timeframe_minutes"] == 5
    assert data["alert_rules"][0]["condition"]["type"] == "MINUTE_CLOSE_BELOW"
    assert "quantity" not in data["alert_rules"][0] and data["risk_branches"] == []
    supplement_values = {s["path"]: s["value"] for s in mapping["supplements"]}
    for path, value in supplement_values.items():
        actual = path_value(data, path)
        assert (actual["type"] if isinstance(actual, dict) else actual) == value
    assert set(semantic_values(UnifiedPlanDraft.model_validate(data))) == (
        set(source_bindings) | set(supplement_values)
    )


def register(client, draft, mapping):
    post(
        client,
        "plan-review-supplements",
        {
            "candidateJson": daily_draft_json(draft),
            "contentHash": mapping.candidate_content_hash,
            "supplements": [s.model_dump(mode="json") for s in mapping.supplements],
            "expectedRevision": 0,
        },
    )


def save(client, draft, mapping, *, base=None):
    return post(
        client,
        "plan-drafts",
        {
            "planJson": daily_draft_json(draft),
            "sourceText": SOURCE,
            "dailyMapping": mapping.model_dump(mode="json"),
            "expectedRevision": 0,
            "basePlanVersionId": base,
        },
    )


@pytest.fixture
def workspace(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
        draft = literal_draft(complete=False)
        mapping = literal_mapping(draft)
        register(client, draft, mapping)
        first = save(client, draft, mapping)
        assert_semantic_review(first)
        yield client, tmp_path, draft, first


def complete(client, first):
    draft = literal_draft(complete=True)
    mapping = literal_mapping(draft)
    register(client, draft, mapping)
    result = save(client, draft, mapping, base=first["id"])
    assert_semantic_review(result)
    return result


def test_literal_source_completes_current_review_without_initializing_inventory(workspace):
    client, _, _, first = workspace
    assert (
        FIXTURE["literalUserSource"].replace(
            FIXTURE["soleSubstitution"]["from"], FIXTURE["soleSubstitution"]["to"]
        )
        == SOURCE
    )
    inventory_path = (
        "/api/v1/simulation-position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14"
    )
    before = client.get(inventory_path).json()
    assert not before["snapshot"]["known"]
    assert before["snapshot"]["coreQty"] is before["snapshot"]["tacticalQty"] is None
    post(client, "plan-review-confirmations", review_payload(first), expected=422)
    assert {i["path"] for i in first["dailyIssues"]} >= {
        "activation",
        "ordinary_rules.0.independent_signal",
        "ordinary_rules.1.independent_signal",
    }
    second = complete(client, first)
    assert second["contentHash"] != first["contentHash"]
    post(
        client,
        "plan-review-confirmations",
        review_payload(first, planVersionId=second["id"]),
        expected=422,
    )
    review = post(client, "plan-review-confirmations", review_payload(second))
    assert review["canActivate"] and review["reviewId"]
    active = post(
        client,
        "plan-activations",
        review_payload(
            second,
            reviewId=review["reviewId"],
            reviewRevision=1,
        ),
    )
    assert active["active"]
    runtime = client.get("/api/v1/plan-runtime/003043.SZ").json()
    assert runtime["status"] == "AWAITING_EVALUATION" and runtime["snapshot"] is None
    assert client.get(inventory_path).json() == before
    restored = client.get("/api/v1/plan-versions/" + second["id"]).json()
    assert restored["reviewId"] == review["reviewId"]
    assert restored["dailyMapping"] == second["dailyMapping"]


@pytest.mark.parametrize(
    "attack",
    ["quantity", "sellable", "contract", "span", "omit", "remove-processing", "remove-clause"],
)
def test_forged_source_processing_cannot_be_saved(workspace, attack):
    client, _, draft, first = workspace
    mapping = copy.deepcopy(first["dailyMapping"])
    if attack in {"quantity", "sellable"}:
        mapping["clauses"][0]["excerpt"] = SOURCE[:20].replace("100", "200")
    elif attack == "contract":
        item = next(b for b in mapping["bindings"] if b["path"] == "position.max_qty")
        item["origin"] = "PRODUCT_CONTRACT"
    elif attack == "span":
        mapping["clauses"][0]["start"] += 1
    elif attack == "omit":
        mapping["clauses"].pop()
    elif attack == "remove-processing":
        mapping["clauses"][0]["reason"] = "ignore"
    else:
        mapping["clauses"].pop(0)
    post(
        client,
        "plan-drafts",
        {
            "planJson": daily_draft_json(draft),
            "sourceText": SOURCE,
            "dailyMapping": mapping,
            "expectedRevision": 0,
            "basePlanVersionId": first["id"],
        },
        expected=422,
    )


@pytest.mark.parametrize("attack", ["processing", "resolution"])
def test_tampered_stored_processing_or_resolution_fails_closed(workspace, attack):
    client, root, _, first = workspace
    second = complete(client, first)
    post(client, "plan-review-confirmations", review_payload(second))
    engine = create_sqlite_engine(root / "current.sqlite")
    try:
        with create_session_factory(engine)() as session:
            row = session.scalar(
                select(PlanReviewProvenance).where(
                    PlanReviewProvenance.plan_version_id == second["id"],
                )
            )
            if attack == "processing":
                value = json.loads(row.mapping_json)
                value["clauses"][0]["excerpt"] = "Forged source holdings"
                row.mapping_json = json.dumps(value)
            else:
                row.resolutions_json = '[{"resolution":"CONFIRM_SOURCE_TREATMENT"}]'
            session.commit()
        response = client.get("/api/v1/plan-versions/" + second["id"])
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "Forged source holdings" not in response.text
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "attack", ["wrong-path", "supplement", "wrong-resolution", "invented-issue"]
)
def test_treatment_confirmation_cannot_be_forged(workspace, attack):
    client, _, _, first = workspace
    second = complete(client, first)
    item = {"issueId": "issue-000000000000000000000000", "resolution": "CONFIRM_SOURCE_TREATMENT"}
    if attack == "wrong-path":
        item["bindingPath"] = "symbol"
    elif attack == "supplement":
        item["supplementId"] = second["dailyMapping"]["supplements"][0]["supplement_id"]
    elif attack == "wrong-resolution":
        item["resolution"] = "CONFIRM_MAPPING"
    response = post(
        client,
        "plan-review-confirmations",
        review_payload(second, resolutions=[item]),
        expected=422,
    )
    assert response["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/plan-versions/" + second["id"]).json()["reviewId"] is None


@pytest.mark.parametrize("attack", ["price", "quantity", "logic", "clause"])
def test_current_semantic_oracle_refuses_source_wrong_but_internally_consistent_mapping(
    workspace, attack
):
    client, _, _, first = workspace
    current = copy.deepcopy(complete(client, first))
    data = json.loads(current["planJson"])
    path, value = "ordinary_rules[0].condition.conditions[0].low_fen", 980
    if attack == "price":
        value = data["ordinary_rules"][0]["condition"]["conditions"][0]["low_fen"] = 970
    elif attack == "quantity":
        path, value = "ordinary_rules[0].quantity", 200
        data["ordinary_rules"][0]["quantity"] = value
    elif attack == "logic":
        path, value = "ordinary_rules[0].condition.type", "ANY"
        data["ordinary_rules"][0]["condition"]["type"] = value
    for binding in current["dailyMapping"]["bindings"]:
        if binding["path"] == path:
            binding["value"] = value
            if attack == "clause":
                binding["clause_ids"] = [current["dailyMapping"]["clauses"][8]["clause_id"]]
    current["planJson"] = json.dumps(data)
    with pytest.raises(AssertionError):
        assert_semantic_review(current)


def test_literal_ai_output_is_only_a_candidate_and_cannot_claim_human_supplements():
    draft = literal_draft(complete=False)
    mapping = literal_mapping(draft)
    output = {
        "draft": draft.model_dump(mode="json"),
        "clauses": [c.model_dump(mode="json") for c in mapping.clauses],
        "bindings": [b.model_dump(mode="json") for b in mapping.bindings if b.origin == "SOURCE"],
    }
    result = asyncio.run(
        extract_plan(
            request_id=uuid4(),
            source_text=SOURCE,
            config=_config(),
            provider=_StaticProvider(json.dumps(output, ensure_ascii=False)),
        )
    )
    assert result.status is PlanExtractionStatus.SUCCEEDED and result.validation_issues
    assert result.draft.alert_rules[0].condition.price_fen == 950
    assert not result.daily_mapping.supplements
    assert all(i.activation_blocking for i in result.validation_issues)
