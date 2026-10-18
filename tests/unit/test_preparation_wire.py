"""Actual-text wire budgets and conservative server-owned evidence expansion."""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.test_monitor_loop_extraction import CASES, output_for

from trade_plan_monitor.ai.preparation_wire import (
    CompactInitialOutput,
    build_compact_prompt,
    expand_compact_output,
)
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.config import AIConfiguration


def wire(source):
    return dict(
        schema_version="monitor-loop-wire-v1",
        draft=output_for(CASES[0])["draft"],
        clauses=[],
        bindings=[],
        opening_account=dict(inventory_quantity=None, lots=[], cash_fen=None, snapshot_at=None),
    )


def test_backtest_budget_is_independent_of_short_ordinary_extractions():
    settings = AIConfiguration(max_output_tokens=4096, timeout_seconds=30)
    assert settings.backtest_max_output_tokens == 16384
    assert settings.backtest_timeout_seconds == 120
    assert settings.max_output_tokens == 4096


@pytest.mark.parametrize(
    "path", sorted((Path(__file__).parents[1] / "fixtures/shengxin_sources").glob("*.txt"))
)
def test_actual_source_compact_prompt_and_review_preserve_every_clause(path):
    source = PreparationSource(
        source_id=path.stem,
        text=path.read_text(encoding="utf-8-sig"),
        effective_trade_date=date(2026, 9, 24),
    )
    prompt = build_compact_prompt(source)
    assert len(prompt) < 50000
    data = json.loads(
        prompt.split("UNTRUSTED_PLAN_DATA_START\n")[1].split("\nUNTRUSTED_PLAN_DATA_END")[0]
    )
    assert data["source_text"] == source.text
    assert data["confirmed_effective_trade_date"] == "2026-09-24"
    payload = wire(source)
    payload["clauses"] = [
        dict(
            clause_id=c["clause_id"],
            disposition="BACKGROUND",
            reason="Historical context requiring review.",
        )
        for c in data["clauses"]
    ]
    output = CompactInitialOutput.model_validate_json(json.dumps(payload))
    expanded = expand_compact_output(output, source)
    review = expanded.review(source.text)
    assert review.issues
    assert len(review.mapping.clauses) == len(data["clauses"])
    assert all(source.text[c.start : c.end] == c.excerpt for c in review.mapping.clauses)
    assert expanded.opening_account.cash_fen is None


def test_exact_transport_marker_does_not_admit_other_extra_fields_or_invented_units():
    source = PreparationSource(source_id="test", text="继续等待。")
    payload = wire(source)
    output = CompactInitialOutput.model_validate_json(json.dumps(payload | {"type": "json_object"}))
    assert output.draft == CompactInitialOutput.model_validate_json(json.dumps(payload)).draft
    for extra in (
        {"type": "trade_authorized"},
        {"approved": True},
        {"bindings": [{"path": "position.max_qty", "clause_ids": ["fake"], "unit": "FEN"}]},
    ):
        with pytest.raises(ValidationError):
            CompactInitialOutput.model_validate_json(json.dumps(payload | extra))


def test_invalid_clause_reference_is_not_silently_accepted():
    source = PreparationSource(source_id="test", text="继续等待。")
    output = CompactInitialOutput.model_validate_json(
        json.dumps(
            wire(source)
            | {"bindings": [{"path": "position.max_qty", "clause_ids": ["unknown-clause"]}]}
        )
    )
    with pytest.raises(ValueError, match="reference"):
        expand_compact_output(output, source)


def test_semantic_redundant_opening_binding_does_not_override_account_facts():
    from trade_plan_monitor.ai.preparation_wire import CompactInitialV2Output
    from trade_plan_monitor.ai.prompt_encoding import source_clause_evidence

    source = PreparationSource(source_id="test", text="当前持仓0股。")
    clause_id = source_clause_evidence(source.text)[0]["clause_id"]
    payload = wire(source) | {
        "schema_version": "monitor-loop-wire-v2",
        "bindings": [{"path": "opening_account.inventory_quantity", "clause_ids": [clause_id]}],
    }
    output = CompactInitialV2Output.model_validate_json(json.dumps(payload))
    expanded = expand_compact_output(output, source)
    assert (
        expanded.opening_account
        == expand_compact_output(
            CompactInitialV2Output.model_validate_json(json.dumps(payload | {"bindings": []})),
            source,
        ).opening_account
    )


def test_update_prompt_preserves_policy_without_retransmitting_repeated_history():
    from tests.unit.test_plan_update_bindings import prior_review

    from trade_plan_monitor.ai.update_review import context_from_review

    base = prior_review()
    context = context_from_review(base, base.evidence_hash)
    for path in (Path(__file__).parents[1] / "fixtures/shengxin_sources").glob("*.txt"):
        source = PreparationSource(source_id=path.stem, text=path.read_text(encoding="utf-8-sig"))
        prompt = build_compact_prompt(source, context=context)
        assert len(prompt) < 50000
        data = json.loads(
            prompt.split("UNTRUSTED_PLAN_DATA_START\n")[1].split("\nUNTRUSTED_PLAN_DATA_END")[0]
        )
        assert data["source_text"] == source.text
        assert data["reviewed_predecessor"]["snapshot"] == context.snapshot.model_dump(mode="json")
        assert data["reviewed_predecessor"]["base_hash"] == context.base_hash
        assert "evidence" not in data["reviewed_predecessor"]


@pytest.mark.parametrize("number", [1, 2, 3, 4])
@pytest.mark.parametrize("round_name", ["", "final-"])
def test_recorded_live_outputs_produce_reviewable_candidates_without_invented_facts(
    number, round_name
):
    from trade_plan_monitor.ai.loop_plan_extraction import validate_opening_evidence

    fixtures = Path(__file__).parents[1] / "fixtures"
    payload = (fixtures / f"ai/shengxin-live-wire-{round_name}{number:02d}.json").read_text(
        encoding="utf-8"
    )
    original = sorted((fixtures / "shengxin_sources").glob("*.txt"))[number - 1]
    source = PreparationSource(
        source_id=original.stem, text=original.read_text(encoding="utf-8-sig")
    )
    output = CompactInitialOutput.model_validate_json(payload)
    expanded = expand_compact_output(output, source)
    review = expanded.review(source.text)
    validate_opening_evidence(expanded.opening_account, source.text)
    # Mapping completeness never attests a future market condition.
    from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition

    for rule in expanded.draft.ordinary_rules:
        if rule.condition:
            assert evaluate_unified_condition(rule.condition, None).outcome != "SATISFIED"
    assert review.mapping.clauses
    assert expanded.opening_account.cash_fen is None
    assert expanded.opening_account.snapshot_at is None
    if number == 4 and not round_name:
        assert expanded.draft.levels.risk_line_fen is None
        assert expanded.draft.levels.risk_comparison is None
        assert not expanded.draft.risk_branches
        assert expanded.draft.alert_rules  # Entry cancellation retains reminder authority only.


@pytest.mark.parametrize("prefix", ["假设", "目标", "预计", "示例"])
def test_reversed_holdings_label_does_not_turn_hypothetical_holdings_into_fact(prefix):
    from trade_plan_monitor.ai.loop_plan_extraction import OpeningFact, _check_fact
    from trade_plan_monitor.ai.review import server_source_clauses

    source = prefix + "0股持仓。"
    with pytest.raises(ValueError, match="nonactual"):
        _check_fact(
            OpeningFact[int](value=0, start=0, end=len(source), excerpt=source),
            "quantity",
            source,
            server_source_clauses(source),
        )
