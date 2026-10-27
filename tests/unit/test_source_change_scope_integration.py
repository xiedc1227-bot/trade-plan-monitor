"""Real scalar deltas bind their inferred side to the exact current parent proof."""

import json

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import _NOW, _assemble
from tests.unit.test_source_change_scopes import _parent

from trade_plan_monitor.ai.daily_review import DailyFieldBinding
from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_change_composition import assess_change_current
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_real_delta_uses_parent_side_without_requoting_unchanged_source(side):
    _, base, parent = _parent(side)
    text = "ordinary_rules[0].quantity = 200"
    source = PreparationSource(source_id="scope-change", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    _, patch = delta(text, target="ordinary_rules", rule_id=base.draft.ordinary_rules[0].rule_id,
                     values={"quantity": 200})
    context = context_from_review(base, parent.binding.candidate_hash)
    # Use the actual full update protocol with an exact literal binding. The
    # existing compact decoder does not infer machine-path quantity citations.
    expanded = expand_compact_output(expand_delta_output(patch, context), source, context=context)
    path = "ordinary_rules[0].quantity"
    expanded = expanded.model_copy(update={"bindings": (
        *(row for row in expanded.bindings if row.path != path),
        DailyFieldBinding(path=path, value=200, origin="SOURCE", unit="JSON",
            clause_ids=tuple(row.clause_id for row in expanded.clauses), supplement_id=None),
    )})
    source, output, materialized, inputs, context, base, parent, binding = _assemble(
        base, parent, source, expanded, context)
    assert materialized.review.issues == ()
    result = assess_change_current(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding, prefix=(
            PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash),))
    assert result.coverage_complete is True
    atoms = result.source_assessment.obligations
    assert len(atoms) == 1 and atoms[0].scope == side
    assert json.loads(atoms[0].semantics_json)["inherited_scope"][
        "parent_assurance_hash"] == parent.evidence_hash
    assert result.current_automatic_fidelity_verified is False
    assert result.authority_granted is False
