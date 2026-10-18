"""The actual successor response must not invent holdings or fail on an empty context."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.preparation_wire import CompactUpdateOutput

FIXTURE = Path(__file__).parents[1] / "fixtures/ai/shengxin-unified-update-04.json"


def test_successor_normalization_preserves_untouched_predecessor_risk_branch():
    from datetime import date

    from trade_plan_monitor.ai.preparation_wire import expand_compact_output
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    source = PreparationSource(source_id="third", effective_trade_date=date(2026, 9, 30),
        text=(FIXTURE.parents[1] / "shengxin_sources/03-20260930-095728.txt").read_text(
            "utf-8-sig"))
    wire = CompactUpdateOutput.model_validate_json(
        FIXTURE.with_name("shengxin-chain-wire-03.json").read_text("utf-8"))
    expanded = expand_compact_output(wire, source)
    assert expanded.draft.risk_branches == wire.draft.risk_branches
    assert len(expanded.draft.risk_branches) == 1
    assert expanded.draft.risk_branches[0].suspension_confirmation_policy == "RESUME_FIRST_CLOSE"


@pytest.mark.parametrize("text,valid", [
    ("不能因为随后反弹就直接取消风控，", True),
    ("", False), ("假设不能因为随后反弹就直接取消风控，", False),
])
def test_explicit_risk_retention_preserves_prior_evidence_without_repeating_exit(text, valid):
    from types import SimpleNamespace as NS

    from trade_plan_monitor.ai.daily_review import semantic_values
    from trade_plan_monitor.ai.update_review import PlanCandidateReview, _covered_retention

    base = PlanCandidateReview.model_validate_json(
        FIXTURE.with_name("shengxin-chain-reviewed-03.json").read_text("utf-8"))
    output = NS(draft=base.draft, operations=(), clauses=(NS(excerpt=text),))
    current = NS(issues=(), mapping=NS(bindings=tuple(
        NS(path=p, origin="SOURCE") for p in semantic_values(base.draft)
        if not p.startswith("risk_branches["))))
    assert _covered_retention(base, output, current) is valid


@pytest.mark.parametrize("change", [None, "price", "partial"])
def test_new_position_exclusion_never_authorizes_whole_risk_cancellation(change):
    from datetime import date

    from trade_plan_monitor.ai.preparation_wire import expand_compact_output
    from trade_plan_monitor.ai.update_review import PlanCandidateReview, build_update_review
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    base = PlanCandidateReview.model_validate_json(
        FIXTURE.with_name("shengxin-chain-reviewed-03.json").read_text("utf-8"))
    source = PreparationSource(source_id="fourth", effective_trade_date=date(2026, 10, 9),
        text=(FIXTURE.parents[1] / "shengxin_sources/04-20261009-091956.txt").read_text(
            "utf-8-sig"))
    wire = CompactUpdateOutput.model_validate_json(
        FIXTURE.with_name("shengxin-chain-reviewed-wire-04.json").read_text("utf-8"))
    output = expand_compact_output(wire, source)
    if change == "price":
        raw = base.model_dump(mode="json")
        raw["draft"]["levels"]["risk_line_fen"] = 2600
        for bound in raw["bindings"]:
            if bound["path"] == "levels.risk_line_fen":
                bound["binding"]["value"] = 2600
        base = PlanCandidateReview.model_validate_json(json.dumps(raw))
    elif change == "partial":
        output = output.model_copy(update={"operations": tuple(
            op.model_copy(update={"clause_ids": op.clause_ids[:1]})
            if op.target == "risk_branches" else op for op in output.operations)})
    review = build_update_review(base, source, output)
    assert review.issues
    assert not review.to_preparation_candidate().policy_ready
    assert review.draft.risk_branches == base.draft.risk_branches
    assert review.draft.levels.risk_line_fen == base.draft.levels.risk_line_fen
    assert not any(c.action == "REVOKE" and c.target == "risk_branches" for c in review.changes)


def test_explicit_source_cancellation_reconciles_removed_buy_update_operation():
    from datetime import date

    from trade_plan_monitor.ai.preparation_wire import expand_compact_output
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    source = PreparationSource(source_id="second", effective_trade_date=date(2026, 9, 28),
        text=FIXTURE.with_name("shengxin-chain-source-02.txt").read_text("utf-8"))
    wire = CompactUpdateOutput.model_validate_json(
        FIXTURE.with_name("shengxin-chain-update-02.json").read_text("utf-8"))
    expanded = expand_compact_output(wire, source)
    assert expanded.draft.ordinary_rules == ()
    operation = next(op for op in expanded.operations if op.target == "ordinary_rules")
    assert operation.action == "REVOKE"
    clauses = {c.clause_id: c.excerpt for c in expanded.clauses}
    assert all("低吸计划" in clauses[c] and "取消" in clauses[c]
               for c in operation.clause_ids)


def test_actual_update_empty_account_context_means_no_new_holdings_assertion():
    value = CompactUpdateOutput.model_validate_json(FIXTURE.read_text("utf-8-sig"))
    assert value.account_context is None


def test_empty_context_cannot_discard_account_dependent_rules_or_unknown_fields():
    for change in ({"dependent_rule_ids": ["buy"]}, {"cash": 100000}):
        raw = json.loads(FIXTURE.read_text("utf-8-sig"))
        raw["account_context"].update(change)
        with pytest.raises(ValidationError):
            CompactUpdateOutput.model_validate_json(json.dumps(raw))


def test_actual_update_merges_repeated_evidence_for_the_same_operation():
    from datetime import date

    from trade_plan_monitor.ai.preparation_wire import expand_compact_output
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    source = PreparationSource(
        source_id="fourth",
        effective_trade_date=date(2026, 10, 9),
        text=(FIXTURE.parents[1] / "shengxin_sources/04-20261009-091956.txt").read_text(
            "utf-8-sig"
        ),
    )
    wire = CompactUpdateOutput.model_validate_json(FIXTURE.read_text("utf-8-sig"))
    expanded = expand_compact_output(wire, source)
    assert len(expanded.operations) == 4
    assert set(expanded.operations[0].clause_ids) == {
        key for op in wire.operations if op.target == "levels" for key in op.clause_ids
    }
    conflicting = wire.model_copy(
        update={
            "operations": (
                *wire.operations,
                wire.operations[0].model_copy(update={"action": "RETAIN"}),
            )
        }
    )
    with pytest.raises(ValueError, match="conflicting"):
        expand_compact_output(conflicting, source)


def actual_successor_review():
    from datetime import date

    from trade_plan_monitor.ai.preparation_wire import CompactInitialOutput, expand_compact_output
    from trade_plan_monitor.ai.update_review import build_initial_review
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    sources = [
        PreparationSource(
            source_id=name,
            effective_trade_date=day,
            text=(FIXTURE.parents[1] / f"shengxin_sources/{name}.txt").read_text("utf-8-sig"),
        )
        for name, day in [
            ("03-20260930-095728", date(2026, 9, 30)),
            ("04-20261009-091956", date(2026, 10, 9)),
        ]
    ]
    initial = expand_compact_output(
        CompactInitialOutput.model_validate_json(
            FIXTURE.with_name("shengxin-unified-base-03.json").read_text("utf-8-sig")
        ),
        sources[0],
    )
    base = build_initial_review(initial.draft, initial.review(sources[0].text).mapping, sources[0])
    output = expand_compact_output(
        CompactUpdateOutput.model_validate_json(FIXTURE.read_text("utf-8-sig")), sources[1]
    )
    return base, sources[1], output


def test_actual_successor_restatements_and_new_tranche_do_not_need_internal_rule_names():
    from trade_plan_monitor.ai.update_review import build_update_review

    base, source, output = actual_successor_review()
    result = build_update_review(base, source, output)
    assert not result.issues
    assert result.draft.position.max_qty == 300
    assert [rule.quantity for rule in result.draft.ordinary_rules] == [100, 100]
    assert result.draft.ordinary_rules[1].independent_signal.mode == "AFTER_RULE_COMPLETED"
    assert result.draft.levels.risk_line_fen is None
    assert {c.action for c in result.changes} == {"MODIFY", "ADD", "RETAIN"}


def test_restatements_cannot_silently_preserve_an_unmentioned_changed_maximum():
    from trade_plan_monitor.ai.update_review import build_update_review

    base, source, output = actual_successor_review()
    # A previously reviewed 500-share limit cannot be implicitly retained when
    # the new original says 300 and the model omitted the position operation.
    raw = base.model_dump(mode="json")
    raw["draft"]["position"]["max_qty"] = 500
    for binding in raw["bindings"]:
        if binding["path"] == "position.max_qty":
            binding["binding"]["value"] = 500
    from trade_plan_monitor.ai.update_review import PlanCandidateReview

    changed_base = PlanCandidateReview.model_validate_json(json.dumps(raw))
    result = build_update_review(changed_base, source, output)
    assert "UPDATE_RETENTION_EVIDENCE_REQUIRED" in result.issues
