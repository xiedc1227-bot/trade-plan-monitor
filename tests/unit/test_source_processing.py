from __future__ import annotations

import json

import pytest

from trade_plan_monitor.ai.source_processing import derive_source_processing


def test_inventory_and_product_treatments_preserve_exact_subspans_without_writes() -> None:
    source = (
        "003043.SZ当前持仓100股，均为测试日前已持有且当日可卖；\n"
        "提醒及确认收到提醒不代表成交，未登记成交时持仓不变。"
    )
    processing = derive_source_processing(source, symbol="003043.SZ")

    inventory, product = processing.treatments
    assert inventory.kind == "INVENTORY_ASSERTION"
    assert inventory.total_quantity == inventory.sellable_quantity == 100
    assert inventory.contract_id == "independent-inventory-v1"
    assert inventory.symbol_span.excerpt == "003043.SZ"
    assert [span.excerpt for span in inventory.spans] == [
        "当前持仓100股，",
        "均为测试日前已持有且当日可卖；",
    ]
    assert product.kind == "PRODUCT_GUARANTEE"
    assert product.contract_id == "alert-position-isolation-v1"
    for treatment in processing.treatments:
        for span in treatment.spans:
            assert source[span.start : span.end] == span.excerpt
    assert derive_source_processing(source, symbol="003043.SZ") == processing


@pytest.mark.parametrize("quantity", [0, 100, 230, 500])
def test_inventory_grammar_preserves_source_quantity_without_rounding(quantity: int) -> None:
    source = f"003043.SZ当前持仓{quantity}股，均为测试日前已持有且当日可卖；"
    [item] = derive_source_processing(source, symbol="003043.SZ").treatments
    assert item.total_quantity == item.sellable_quantity == quantity


@pytest.mark.parametrize(
    "source",
    [
        "003043.SZ当前持仓100股且价格低于10元时卖出100股，均为测试日前已持有且当日可卖；",
        "003043.SZ当前持仓100股，均为测试日前已持有且当日不可卖；",
        "003043.SZ当前持仓100股，均为测试日前已持有且当日可卖且有效跌破时卖出；",
        "提醒及确认收到提醒代表成交，未登记成交时持仓不变。",
        "提醒及确认收到提醒不代表成交且价格低于9元卖出100股，未登记成交时持仓不变。",
        "提醒及确认收到提醒不代表成交，未登记成交时持仓增加100股。",
    ],
)
def test_mixed_clause_negation_or_trading_injection_cannot_receive_a_treatment(source: str) -> None:
    assert derive_source_processing(source, symbol="003043.SZ").treatments == ()


def test_source_symbol_mismatch_does_not_route_inventory_to_another_security() -> None:
    source = "003043.SZ当前持仓100股，均为测试日前已持有且当日可卖；"
    assert derive_source_processing(source, symbol="000001.SZ").treatments == ()


def test_source_quantity_outside_web_safe_integer_range_stays_unresolved() -> None:
    source = "003043.SZ当前持仓9007199254740992股，均为测试日前已持有且当日可卖；"
    assert derive_source_processing(source, symbol="003043.SZ").treatments == ()


def test_v2_snapshot_requires_treatment_confirmation_and_rederives_values() -> None:
    from trade_plan_monitor.ai.models import ExplicitPlanDraft, PlanMapping
    from trade_plan_monitor.ai.review import build_server_review_snapshot, server_source_clauses
    from trade_plan_monitor.ai.source_processing import upgrade_source_mapping

    source = "003043.SZ当前持仓100股，均为测试日前已持有且当日可卖；"
    draft = ExplicitPlanDraft.model_validate_json(
        json.dumps(
            {
                "plan_id": "source-treatment",
                "version": 1,
                "symbol": "003043.SZ",
                "name": "Synthetic",
                "market": "SZSE",
                "metadata": {},
                "activation": None,
                "position": {"inventory_scope": None, "lot_size": None, "max_qty": None},
                "monitoring": {"timeframe_minutes": None, "indicator_formula_version": None},
                "rules": [
                    {
                        "rule_id": "risk",
                        "condition": None,
                        "action": {"type": "RISK_ALERT"},
                        "confirmation": None,
                        "repeat_policy": None,
                        "safety_conditions": None,
                    }
                ],
                "conflict_policy": None,
            }
        )
    )
    mapping = upgrade_source_mapping(
        draft=draft,
        mapping=PlanMapping(source_clauses=server_source_clauses(source)),
        source_text=source,
    )
    snapshot = build_server_review_snapshot(draft=draft, mapping=mapping, source_text=source)
    assert any(
        issue.code == "SOURCE_TREATMENT_REVIEW_REQUIRED" for issue in snapshot.required_issues
    )
    assert any(issue.path == "symbol" for issue in snapshot.required_issues)
    assert not any(issue.code == "UNRESOLVED_SEMANTICS" for issue in snapshot.required_issues)
    forged = mapping.model_dump(mode="json")
    forged["source_processing"]["treatments"][0]["total_quantity"] = 200
    with pytest.raises(ValueError, match="source processing"):
        build_server_review_snapshot(
            draft=draft,
            mapping=PlanMapping.model_validate_json(json.dumps(forged)),
            source_text=source,
        )


@pytest.mark.parametrize(
    "source",
    [
        "003043.SZ当前持仓100股且价格低于10元卖出100股，均为测试日前已持有且当日可卖；",
        "003043.SZ当前持仓100股，均为测试日前已持有且当日不可卖；",
        "提醒及确认收到提醒代表成交，未登记成交时持仓不变。",
        "提醒及确认收到提醒不代表成交且价格低于9元卖出100股，未登记成交时持仓不变。",
        "提醒及确认收到提醒不代表成交，未登记成交时持仓增加100股。",
    ],
)
def test_partially_mapping_mixed_source_does_not_hide_unhandled_meaning(source):
    from tests.unit.test_ai_plan_extraction_v4 import _partial_draft

    from trade_plan_monitor.ai.models import ExplicitPlanDraft, PlanMapping
    from trade_plan_monitor.ai.review import build_server_review_snapshot, server_source_clauses
    from trade_plan_monitor.ai.source_processing import upgrade_source_mapping

    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_partial_draft()))
    clauses = [
        item.model_dump(mode="json") | {"disposition": "MAPPED", "paths": ["symbol"]}
        for item in server_source_clauses(source)
    ]
    mapping = PlanMapping.model_validate_json(
        json.dumps(
            {
                "source_clauses": clauses,
                "field_bindings": [
                    {
                        "path": "symbol",
                        "value": draft.symbol,
                        "unit": "NONE",
                        "origin": "SOURCE",
                        "clause_ids": [item["clause_id"] for item in clauses],
                    }
                ],
            }
        )
    )
    mapping = upgrade_source_mapping(draft=draft, mapping=mapping, source_text=source)
    snapshot = build_server_review_snapshot(draft=draft, mapping=mapping, source_text=source)
    assert not snapshot.can_activate
    assert any(item.code == "UNRESOLVED_MIXED_SOURCE" for item in snapshot.required_issues)


def test_treatment_cannot_be_used_as_a_trading_field_source():
    from tests.unit.test_ai_plan_extraction_v4 import _partial_draft

    from trade_plan_monitor.ai.models import ExplicitPlanDraft, PlanMapping
    from trade_plan_monitor.ai.review import build_server_review_snapshot, server_source_clauses
    from trade_plan_monitor.ai.source_processing import upgrade_source_mapping

    source = "003043.SZ当前持仓100股，均为测试日前已持有且当日可卖；"
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_partial_draft()))
    clauses = [item.model_dump(mode="json") for item in server_source_clauses(source)]
    clauses[0].update(disposition="MAPPED", paths=["rules[0].action.quantity"])
    mapping = PlanMapping.model_validate_json(
        json.dumps(
            {
                "source_clauses": clauses,
                "field_bindings": [
                    {
                        "path": "rules[0].action.quantity",
                        "value": 100,
                        "unit": "SHARES",
                        "origin": "SOURCE",
                        "clause_ids": [clauses[0]["clause_id"]],
                    }
                ],
            }
        )
    )
    mapping = upgrade_source_mapping(draft=draft, mapping=mapping, source_text=source)
    with pytest.raises(ValueError, match="cannot supply a trading parameter"):
        build_server_review_snapshot(draft=draft, mapping=mapping, source_text=source)
