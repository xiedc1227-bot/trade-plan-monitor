"""Scope restrictions must not become whole-rule cancellation or executable retention."""

import json
from datetime import date
from pathlib import Path

import pytest
from tests.unit.test_plan_delta_wire import delta

from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.update_review import (
    PlanCandidateReview,
    build_update_review,
    context_from_review,
)
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.backtest.preparation_repairs import correction_feedback


def baseline():
    return PlanCandidateReview.model_validate_json(
        (Path(__file__).parents[1] / "fixtures/ai/shengxin-chain-reviewed-03.json").read_text(
            "utf-8"
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "这条止损不再用于后来新开的仓位，旧持仓的处理办法维持。",
        "新增批次不适用此前风控线；既有批次仍按原规则处理。",
        "The previous exit continues for existing lots; exclude future entries.",
    ],
)
@pytest.mark.parametrize("action", ["REVOKE", "RETAIN"])
@pytest.mark.parametrize("intent", ["ASSERTED", "CONTEXT"])
def test_partial_scope_remains_non_executable_without_deleting_prior_evidence(text, action, intent):
    base = baseline()
    _, wire = delta(text, target="risk_branches", rule_id="ORDINARY_TECHNICAL", action=action)
    wire = wire.model_copy(
        update={
            "schema_version": "monitor-loop-delta-wire-v4",
            "operations": tuple(
                op.model_copy(update={"scope_assessment": "PARTIAL_RULE", "intent": intent})
                for op in wire.operations
            ),
        }
    )
    source = PreparationSource(
        source_id="scoped", text=text, effective_trade_date=date(2026, 10, 9)
    )
    context = context_from_review(base, "a" * 64)
    expanded = expand_compact_output(expand_delta_output(wire, context), source, context=context)
    review = build_update_review(base, source, expanded)
    assert "UPDATE_SCOPE_DIRECTION_REQUIRED: risk_branches.ORDINARY_TECHNICAL" in review.issues
    assert review.draft.risk_branches == base.draft.risk_branches
    assert review.draft.levels.risk_line_fen == 2599
    assert not review.to_preparation_candidate().policy_ready
    assert any("UPDATE_SCOPE_DIRECTION_REQUIRED" in issue
               for issue in correction_feedback(review.to_preparation_candidate()))
    assert all(c.action == "RETAIN" for c in review.changes if c.target == "risk_branches")
    assert next(b for b in review.bindings if b.path == "risk_branches[0].target_core_qty") == next(
        b for b in base.bindings if b.path == "risk_branches[0].target_core_qty"
    )


def test_explicit_entire_rule_cancellation_still_works():
    base = baseline()
    text = "对全部新旧持仓一并废止此前普通技术退出规则，今后不再执行该规则。"
    _, wire = delta(text, target="risk_branches", rule_id="ORDINARY_TECHNICAL", action="REVOKE")
    wire = wire.model_copy(
        update={
            "schema_version": "monitor-loop-delta-wire-v4",
            "operations": tuple(
                op.model_copy(update={"scope_assessment": "ENTIRE_RULE"}) for op in wire.operations
            ),
        }
    )
    context = context_from_review(base, "a" * 64)
    source = PreparationSource(source_id="whole", text=text, effective_trade_date=date(2026, 10, 9))
    output = expand_compact_output(expand_delta_output(wire, context), source, context=context)
    review = build_update_review(base, source, output)
    assert not review.issues
    assert review.draft.risk_branches == ()


def test_v4_cannot_hide_scope_change_by_omitting_risk_operation():
    base = baseline()
    _, wire = delta("持仓上限保持300股。", action="RETAIN")
    wire = wire.model_copy(update={"schema_version": "monitor-loop-delta-wire-v4"})
    with pytest.raises(ValueError, match="applicability assessment required"):
        expand_delta_output(wire, context_from_review(base, "a" * 64))


def test_scope_metadata_survives_round_trip():
    from trade_plan_monitor.ai.plan_delta_wire import CompactDeltaOutput

    _, wire = delta(
        "仅豁免新仓。", target="risk_branches", rule_id="ORDINARY_TECHNICAL", action="RETAIN"
    )
    raw = wire.model_dump(mode="json")
    raw["operations"][0]["scope_assessment"] = "PARTIAL_RULE"
    assert (
        CompactDeltaOutput.model_validate_json(json.dumps(raw)).operations[0].scope_assessment
        == "PARTIAL_RULE"
    )


@pytest.mark.parametrize("action", ["RETAIN", "MODIFY", "REVOKE"])
def test_unclear_scope_never_grants_execution_authority(action):
    from trade_plan_monitor.ai.risk_withdrawal_scope import risk_scope_issue

    _, wire = delta(
        "风险适用范围尚不明确。",
        target="risk_branches",
        rule_id="ORDINARY_TECHNICAL",
        action=action,
    )
    operation = wire.operations[0].model_copy(update={"scope_assessment": "UNCLEAR"})
    assert risk_scope_issue(operation) == "UPDATE_SOURCE_AMBIGUITY"
