"""Delta decoding applies only explicit changes to stable predecessor identities."""

import json

import pytest
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_unified_preparation_updates import buy_and_sell_plan

from trade_plan_monitor.ai.plan_delta_wire import CompactDeltaOutput, expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.update_review import build_update_review, context_from_review


def delta(text, *, target="position", rule_id=None, action="MODIFY", values=None):
    source, old = current_update(text)
    ids = [c.clause_id for c in old.clauses]
    raw = dict(
        schema_version="monitor-loop-delta-wire-v1",
        operations=[
            dict(
                target=target,
                rule_id=rule_id,
                action=action,
                values=values or {},
                clause_ids=ids,
                intent="ASSERTED",
                rationale="The current source names this unique change.",
            )
        ],
        clauses=[
            dict(
                clause_id=c.clause_id,
                disposition="POLICY",
                meaning="DIRECTIVE",
                reason="Current source instruction.",
            )
            for c in old.clauses
        ],
    )
    return source, CompactDeltaOutput.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "text", ["总持仓最多500股。", "把持仓上限提到500股。", "最大仓位采用500股。"]
)
def test_partial_delta_needs_no_copy_of_predecessor(text):
    source, output = delta(text, values={"max_qty": 500})
    base = prior_review()
    context = context_from_review(base, "a" * 64)
    expanded = expand_compact_output(expand_delta_output(output, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert not review.issues
    assert review.draft.position.max_qty == 500
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert next(b for b in review.bindings if b.path == "ordinary_rules[0].quantity") == next(
        b for b in base.bindings if b.path == "ordinary_rules[0].quantity"
    )


def test_explicit_new_value_cannot_be_ignored_as_unmentioned_inheritance():
    source, output = delta("总持仓上限改为500股。", values={"max_qty": 500})
    output = output.model_copy(
        update={
            "operations": (),
            "clauses": tuple(
                c.model_copy(update={"paths": ("position.max_qty",)}) for c in output.clauses
            ),
        }
    )
    base = prior_review()
    context = context_from_review(base, "a" * 64)
    expanded = expand_compact_output(expand_delta_output(output, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert any("position.max_qty" in issue for issue in review.issues)


def test_ambiguous_directive_does_not_apply_the_models_guessed_cancellation():
    base = prior_review()
    source, output = delta(
        "取消之前某个条件，具体未说明。",
        target="ordinary_rules",
        action="REVOKE",
        rule_id=base.draft.ordinary_rules[0].rule_id,
    )
    output = output.model_copy(
        update={
            "operations": tuple(
                o.model_copy(update={"intent": "AMBIGUOUS"}) for o in output.operations
            )
        }
    )
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert any("AMBIGUOUS" in issue for issue in review.issues)


@pytest.mark.parametrize("text", ["撤下原来的入场指令。", "此前那笔买单就此作废。"])
def test_cancel_delta_removes_only_named_prior_rule(text):
    base = prior_review(buy_and_sell_plan())
    source, output = delta(
        text, target="ordinary_rules", action="REVOKE", rule_id=base.draft.ordinary_rules[0].rule_id
    )
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert not review.issues
    assert [r.side for r in review.draft.ordinary_rules] == ["SELL"]


def test_duplicate_or_nonexistent_target_cannot_cancel_something_else():
    source, output = delta(
        "取消原买单。", target="ordinary_rules", action="REVOKE", rule_id="absent"
    )
    with pytest.raises(ValueError, match="predecessor identity"):
        expand_delta_output(output, context_from_review(prior_review(), "a" * 64))
    source, output = delta("持仓上限500股。", values={"max_qty": 500})
    conflicting = output.operations[0].model_copy(update={"values": {"max_qty": 600}})
    with pytest.raises(ValueError, match="conflicting delta"):
        expand_delta_output(
            output.model_copy(update={"operations": (*output.operations, conflicting)}),
            context_from_review(prior_review(), "a" * 64),
        )


def test_revoke_then_add_two_rules_applies_limit_to_final_collection():
    from trade_plan_monitor.ai.plan_delta_wire import DeltaOperation

    base = prior_review()
    source, output = delta(
        "旧买单取消，分成两笔各100股。",
        target="ordinary_rules",
        action="REVOKE",
        rule_id=base.draft.ordinary_rules[0].rule_id,
    )
    additions = tuple(
        DeltaOperation.model_validate_json(
            json.dumps(
                {
                    "target": "ordinary_rules",
                    "action": "ADD",
                    "rule_id": identity,
                    "clause_ids": list(output.operations[0].clause_ids),
                    "intent": "ASSERTED",
                    "rationale": "Replace cancelled rule with two explicit tranches",
                    "values": base.draft.ordinary_rules[0].model_dump(mode="json")
                    | {"rule_id": identity},
                }
            )
        )
        for identity in ("new-first", "new-second")
    )
    expanded = expand_delta_output(
        output.model_copy(update={"operations": (*output.operations, *additions)}),
        context_from_review(base, "a" * 64),
    )
    assert [r.rule_id for r in expanded.draft.ordinary_rules] == ["new-first", "new-second"]
    assert any(b.path.startswith("ordinary_rules[0].") for b in expanded.bindings)
    assert not any(b.path.startswith("ordinary_rules[2].") for b in expanded.bindings)


def test_source_cannot_supply_an_invented_candle_ratio():
    from trade_plan_monitor.ai.semantic_validation import semantic_interpretation_matches

    draft = prior_review().draft
    path = "ordinary_rules[0].condition.ratio"
    assert not semantic_interpretation_matches(path, "1", "1. 出现明显下影后再观察。", draft)
    assert semantic_interpretation_matches(path, "0.5", "下影至少占全幅50%。", draft)


def test_no_operations_retains_the_exact_prior_plan_without_restatement():
    source, output = delta("今日休市，没有新增指令。")
    output = output.model_copy(
        update={
            "operations": (),
            "clauses": tuple(
                c.model_copy(update={"meaning": "COMMENTARY", "disposition": "BACKGROUND"})
                for c in output.clauses
            ),
        }
    )
    base = prior_review()
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert not review.issues
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert all(c.action == "RETAIN" for c in review.changes)


@pytest.mark.parametrize("text", ["不要撤销原买入指令。", "旧入场安排照常有效。"])
def test_negative_cancellation_is_explicit_retention_without_lexical_gate(text):
    base = prior_review(buy_and_sell_plan())
    source, output = delta(
        text, target="ordinary_rules", action="RETAIN", rule_id=base.draft.ordinary_rules[0].rule_id
    )
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert not review.issues
    assert review.draft.ordinary_rules == base.draft.ordinary_rules


def test_ambiguous_target_retains_all_rules_and_prompts_without_inventing_target():
    from trade_plan_monitor.backtest.preparation_repairs import correction_feedback

    base = prior_review(buy_and_sell_plan())
    source, output = delta("取消其中一条，具体哪条尚待确定。")
    output = output.model_copy(
        update={"operations": (), "ambiguities": tuple(c.clause_id for c in output.clauses)}
    )
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert any(i.startswith("SOURCE_CONTENT_AMBIGUOUS") for i in review.issues)
    assert correction_feedback(review.to_preparation_candidate()) == ()


def test_add_alert_keeps_prior_buy_and_sell_authority():
    base = prior_review(buy_and_sell_plan())
    source, output = delta(
        "5分钟收盘跌破24.50元时新增提醒，不卖出。",
        target="alert_rules",
        action="ADD",
        rule_id="new-observation",
        values={
            "kind": "RISK_ALERT",
            "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 2450},
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        },
    )
    context = context_from_review(base, "a" * 64)
    review = build_update_review(
        base,
        source,
        expand_compact_output(expand_delta_output(output, context), source, context=context),
    )
    assert not review.issues
    assert review.draft.ordinary_rules == base.draft.ordinary_rules
    assert review.draft.alert_rules[-1].rule_id == "new-observation"
    assert any(c.action == "ADD" for c in review.changes)
