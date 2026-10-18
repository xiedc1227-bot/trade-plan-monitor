"""Natural-language plan changes retain exact evidence, without granting approval."""

import json

import pytest
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_source_tranches import tranche_plan
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.update_review import build_update_review


@pytest.mark.parametrize("target,expected", [("ordinary_rules", True), ("alert_rules", False)])
def test_adding_to_empty_collection_does_not_require_retaining_its_empty_value(target, expected):
    from types import SimpleNamespace as NS

    from trade_plan_monitor.ai.daily_review import semantic_values
    from trade_plan_monitor.ai.update_review import _covered_retention
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    proposed = UnifiedPlanDraft.from_executable(research_plan())
    base = NS(draft=proposed.model_copy(update={"ordinary_rules": ()}))
    output = NS(draft=proposed, clauses=(), operations=(NS(target=target, action="ADD",
        rule_id=proposed.ordinary_rules[0].rule_id),))
    current = NS(issues=(), mapping=NS(bindings=tuple(
        NS(path=p, origin="SOURCE") for p in semantic_values(proposed))))
    assert _covered_retention(base, output, current) is expected


def maximum_update(text="最大持仓由300股调整为500股，其余规则不变。"):
    source, output = current_update(text)
    raw = output.model_dump(mode="json")
    raw["draft"]["position"]["max_qty"] = 500
    raw["bindings"][0]["value"] = 500
    return source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))


def reviewed_three_hundred_share_plan():
    plan = research_plan()
    return prior_review(
        plan.model_copy(
            update={
                "position": plan.position.model_copy(update={"max_qty": 300}),
            }
        )
    )


def buy_and_sell_plan():
    plan = research_plan()
    buy = plan.ordinary_rules[0]
    sell = buy.model_copy(update={"rule_id": "keep-sell", "side": "SELL", "quantity": 200})
    return plan.model_copy(update={"ordinary_rules": (buy, sell)})


def revoke_update(plan, text, *, rule_id=None):
    source, output = current_update(text)
    raw = output.model_dump(mode="json")
    raw.update(draft=plan.model_dump(mode="json"), bindings=[])
    raw["operations"] = [
        {
            "target": "ordinary_rules",
            "action": "REVOKE",
            "rule_id": rule_id or plan.ordinary_rules[0].rule_id,
            "clause_ids": [raw["clauses"][0]["clause_id"]],
        }
    ]
    for clause in raw["clauses"]:
        clause.update(disposition="UNRESOLVED", paths=[])
    return source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))


def test_explicit_maximum_holdings_change_needs_no_internal_section_word():
    base = reviewed_three_hundred_share_plan()
    old_hash = base.evidence_hash
    source, output = maximum_update()

    result = build_update_review(base, source, output)

    assert result.issues == ()
    assert result.draft.position.max_qty == 500
    assert result.draft.ordinary_rules == base.draft.ordinary_rules
    change = next(item for item in result.changes if item.target == "position")
    assert change.action == "MODIFY"
    assert change.before["max_qty"] == 300 and change.after["max_qty"] == 500
    assert any(item.action == "RETAIN" for item in result.changes)
    assert base.draft.position.max_qty == 300 and base.evidence_hash == old_hash
    assert "confirmed" not in json.loads(result.to_preparation_candidate().payload_json)


def test_changed_maximum_uses_current_source_and_retained_rules_keep_original_evidence():
    base = reviewed_three_hundred_share_plan()
    source, output = maximum_update()

    result = build_update_review(base, source, output)

    changed = next(item for item in result.bindings if item.path == "position.max_qty")
    assert changed.source_id == source.source_id
    assert changed.source_hash == source.binding_hash
    assert changed.binding.value == 500
    assert changed.clauses[0].excerpt == "最大持仓由300股调整为500股，"
    assert source.text[changed.clauses[0].start : changed.clauses[0].end] == (
        changed.clauses[0].excerpt
    )
    old = next(item for item in base.bindings if item.path == "ordinary_rules[0].quantity")
    retained = next(item for item in result.bindings if item.path == old.path)
    assert retained == old


def test_partial_position_change_preserves_an_unchanged_core_target_and_its_evidence():
    plan = research_plan()
    base = prior_review(
        plan.model_copy(
            update={
                "position": plan.position.model_copy(
                    update={"max_qty": 300, "core_target_qty": 100}
                ),
            }
        )
    )
    source, output = maximum_update()
    raw = output.model_dump(mode="json")
    raw["draft"]["position"]["core_target_qty"] = 100
    result = build_update_review(
        base,
        source,
        PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw)),
    )
    assert not result.issues
    old = next(item for item in base.bindings if item.path == "position.core_target_qty")
    assert next(item for item in result.bindings if item.path == old.path) == old
    raw["draft"]["position"]["core_target_qty"] = 0
    changed = build_update_review(
        base,
        source,
        PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw)),
    )
    assert "UPDATE_SOURCE_BINDING_REQUIRED: position.core_target_qty" in changed.issues


@pytest.mark.parametrize(
    "text",
    [
        "最大持仓调整为500股。",
        "最大持仓调整为500股，其余规则是否保留待确认。",
        "最大持仓调整为500股，不保留其余规则。",
        "假设最大持仓调整为500股，其余规则不变。",
        "不要将最大持仓调整为500股，其余规则不变。",
    ],
)
def test_missing_ambiguous_or_negated_retention_cannot_be_resolved_by_ai_label(text):
    source, output = maximum_update(text)

    result = build_update_review(reviewed_three_hundred_share_plan(), source, output)

    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_explicit_cancellation_matches_unique_buy_without_internal_rule_id():
    plan = buy_and_sell_plan()
    base = prior_review(plan)
    source, output = revoke_update(plan, "取消原来的买入规则。其余规则不变。")
    assert plan.ordinary_rules[0].rule_id not in source.text

    result = build_update_review(base, source, output)

    assert result.issues == ()
    assert [item.rule_id for item in result.draft.ordinary_rules] == ["keep-sell"]
    removed = next(item for item in result.changes if item.action == "REVOKE")
    assert removed.rule_id == plan.ordinary_rules[0].rule_id
    assert removed.before["side"] == "BUY" and removed.after is None
    old = next(item for item in base.bindings if item.path == "ordinary_rules[1].quantity")
    moved = next(item for item in result.bindings if item.path == "ordinary_rules[0].quantity")
    assert moved == old.model_copy(update={"path": "ordinary_rules[0].quantity"})
    assert moved.original_path == moved.supplement.path == "ordinary_rules[1].quantity"


@pytest.mark.parametrize(
    "lower,expected_clear",
    [
        ("26.40", True),
        ("26.50", False),
        ("126.40", False),
    ],
)
def test_source_style_cancellation_matches_the_exact_previous_buy_zone(lower, expected_clear):
    from trade_plan_monitor.domain.unified_plan_models import UnifiedLevels

    plan = buy_and_sell_plan()
    levels = UnifiedLevels.model_validate(
        {
            "low_buy": {
                "low_fen": 2640,
                "high_fen": 2670,
                "include_low": True,
                "include_high": True,
            },
            "pressure": None,
            "risk_line_fen": None,
            "risk_comparison": None,
        }
    )
    plan = plan.model_copy(update={"levels": levels})
    source, output = revoke_update(plan, f"原{lower}—26.70低吸计划正式取消。其余规则不变。")
    result = build_update_review(prior_review(plan), source, output)
    assert (not result.issues) == expected_clear


@pytest.mark.parametrize(
    "text",
    [
        "取消原来的买入规则。其余规则不变。",
        "取消原来的规则。其余规则不变。",
        "不要取消原来的卖出规则。其余规则不变。",
        "假设取消原来的卖出规则。其余规则不变。",
    ],
)
def test_wrong_side_ambiguous_or_negated_cancellation_keeps_review_blocked(text):
    plan = buy_and_sell_plan()
    source, output = revoke_update(plan, text, rule_id="keep-sell")

    result = build_update_review(prior_review(plan), source, output)

    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_cancellation_cannot_hide_unprocessed_extra_trade_instruction():
    plan = buy_and_sell_plan()
    source, output = revoke_update(
        plan,
        "取消原来的买入规则但跌破30元必须卖出200股。其余规则不变。",
    )

    result = build_update_review(prior_review(plan), source, output)

    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_two_buy_rules_need_a_specific_target_before_either_can_be_cancelled():
    plan = tranche_plan()
    source, output = revoke_update(
        plan,
        "取消原来的买入规则。其余规则不变。",
        rule_id=plan.ordinary_rules[1].rule_id,
    )

    result = build_update_review(prior_review(plan), source, output)

    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


@pytest.mark.parametrize("tamper", ["amount", "excerpt"])
def test_natural_language_matching_does_not_accept_wrong_value_or_forged_source(tamper):
    source, output = maximum_update()
    raw = output.model_dump(mode="json")
    if tamper == "amount":
        raw["draft"]["position"]["max_qty"] = 600
        raw["bindings"][0]["value"] = 600
    else:
        raw["clauses"][0]["excerpt"] = "最大持仓调整为600股。"

    with pytest.raises(ValueError):
        build_update_review(
            reviewed_three_hundred_share_plan(),
            source,
            PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw)),
        )
