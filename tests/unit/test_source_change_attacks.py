"""Admitted delta operations cannot erase or borrow current source requirements.

Every fixture uses the real local delta expansion and three-stage derivation.
These tests perform no provider calls, database access or human authorization.
"""

import json
from datetime import timedelta
from uuid import UUID

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import _NOW, _assemble, _assess, _case, _parent
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.source_obligations import declarations
from trade_plan_monitor.ai.update_review import build_initial_review, context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _source(text):
    return PreparationSource(source_id="current-attack", text=text, available_at=_NOW,
                             effective_trade_date=_NOW.date())


def _two_rule_parent():
    base, _ = _parent()
    rule = base.draft.ordinary_rules[0]
    draft = UnifiedPlanDraft.model_validate(base.draft.model_dump(mode="python") | {
        "ordinary_rules": (rule, rule.model_copy(update={
            "rule_id": "remaining-sell", "side": "SELL",
        })),
    })
    text, mapping = source_mapping(draft)
    source = PreparationSource(source_id="two-rule-parent", text=text,
        available_at=_NOW - timedelta(days=1),
        effective_trade_date=(_NOW - timedelta(days=1)).date())
    review = build_initial_review(draft, mapping, source)
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace)
    parent = assess_initial_current(source, review, mapping, inputs,
                                    binding=_binding(source, review, inputs))
    assert parent.coverage_complete is True and review.issues == ()
    return review, parent


def _attack(kind):
    base, parent = _two_rule_parent() if kind == "implicit_cancellation" else _parent()
    identity = base.draft.ordinary_rules[0].rule_id
    if kind == "retain_erases_declaration":
        text = "position.max_qty = 500"
        _, patch = delta(text, target="position", action="RETAIN")
    elif kind == "same_value_wrong_clause":
        text = ("position.max_qty = 100\nordinary_rules[0].side = \"BUY\"\n"
                "ordinary_rules[0].quantity = 100")
        _, patch = delta(text, values={"max_qty": 100})
        quantity_start = text.index("ordinary_rules[0].quantity")
        chosen = tuple(clause.clause_id for clause in server_source_clauses(text)
                       if clause.start >= quantity_start)
        patch = patch.model_copy(update={
            "operations": tuple(operation.model_copy(update={"clause_ids": chosen})
                                for operation in patch.operations),
            "clauses": tuple(clause if clause.clause_id in chosen else clause.model_copy(
                update={"disposition": "BACKGROUND", "meaning": "COMMENTARY", "paths": ()})
                for clause in patch.clauses),
        })
    elif kind == "all_weakened_to_any":
        children = [
            dict(type="REVIEWED_FACT", fact_kind="VOLUME_OR_CANDLE",
                 evidence_requirement="明显下影", validity_scope="SIGNAL"),
            dict(type="REVIEWED_FACT", fact_kind="VOLUME_OR_CANDLE",
                 evidence_requirement="量能不能异常放大", validity_scope="SIGNAL"),
        ]
        required = dict(type="ALL", conditions=children)
        text = ('ordinary_rules[0].side = "BUY"\nordinary_rules[0].condition = '
                + json.dumps(required, ensure_ascii=False))
        _, patch = delta(text, target="ordinary_rules", rule_id=identity,
                         values={"condition": dict(type="ANY", conditions=children)})
    elif kind == "implicit_cancellation":
        # This complete source says to keep a position cap. It contains no
        # cancellation instruction for the independently inherited BUY rule.
        text = "position.max_qty = 1000"
        _, patch = delta(text, target="ordinary_rules", rule_id=identity, action="REVOKE")
    else:
        raise AssertionError("unknown attack fixture")
    source = _source(text)
    context = context_from_review(base, parent.binding.candidate_hash)
    case = _assemble(base, parent, source, patch, context)
    assert parent.coverage_complete is True
    assert len(case[3].derivation.stages) == 3
    assert case[2].review.issues == ()
    return case


@pytest.mark.parametrize("kind", [
    "retain_erases_declaration", "same_value_wrong_clause", "all_weakened_to_any",
    "implicit_cancellation",
])
def test_admitted_operations_cannot_substitute_for_the_current_source_meaning(kind):
    source, output, materialized, inputs, context, base, parent, binding = _attack(kind)
    before = tuple(value.model_dump_json() for value in (
        source, output, materialized, inputs, context, base, parent, binding))
    raw = json.loads(inputs.derivation.raw_json)
    assert "draft" not in raw

    result = _assess(source, output, materialized, inputs, context=context,
                     base_review=base, verified_parent=parent, binding=binding)

    assert result.coverage_complete is False and result.status == "BLOCKED"
    assert result.issues and result.authority_granted is False
    assert result.raw_delta_verified is True
    assert result.provider_full_draft_supplied is False
    assert result.automatic_fidelity_verified is False
    assert tuple(value.model_dump_json() for value in (
        source, output, materialized, inputs, context, base, parent, binding)) == before
    assert result.source_hash == source.source_hash
    assert result.source_binding_hash == source.binding_hash
    assert all(atom.source_hash == source.source_hash for atom in result.obligations)
    assert all(source.text[atom.start:atom.end] == atom.excerpt for atom in result.obligations)
    if kind == "retain_erases_declaration":
        assert raw["operations"][0]["action"] == "RETAIN"
        assert materialized.review.draft.position.max_qty == 1000
        assert declarations(source.text)[0].value == 500
    elif kind == "same_value_wrong_clause":
        assert materialized.review.draft.position.max_qty == 100
        assert materialized.review.draft.ordinary_rules[0].quantity == 100
        current = next(item for item in materialized.review.bindings
                       if item.path == "position.max_qty")
        assert current.source_id == source.source_id
        assert all("ordinary_rules[0].quantity" in clause.excerpt for clause in current.clauses)
    elif kind == "all_weakened_to_any":
        assert materialized.review.draft.ordinary_rules[0].condition.type == "ANY"
        assert declarations(source.text)[1].value["type"] == "ALL"
        assert any(atom.kind == "RELATION" for atom in result.obligations)
    else:
        assert raw["operations"][0]["action"] == "REVOKE"
        assert [rule.rule_id for rule in materialized.review.draft.ordinary_rules] == [
            "remaining-sell",
        ]
        assert base.draft.ordinary_rules and "REVOKE" not in source.text
        retained = next(item for item in result.operations if item.rule_id == "remaining-sell")
        removed = next(item for item in result.operations if item.rule_id == "low-buy")
        assert retained.action == "RETAIN" and retained.changed_paths == ()
        assert retained.before_hash == retained.after_hash
        assert removed.action == "REVOKE" and removed.changed_paths
        assert set(result.changed_paths) == set(removed.changed_paths)


@pytest.mark.parametrize("field,value", [
    ("source_id", "other-source"),
    ("source_binding_hash", "a" * 64),
    ("source_text_sha256", "b" * 64),
    ("available_at", _NOW + timedelta(minutes=1)),
    ("authored_at", _NOW),
    ("effective_trade_date", (_NOW + timedelta(days=1)).date()),
    ("evidence_hash", "c" * 64),
    ("request_id", UUID(int=125)),
])
def test_a_valid_current_review_cannot_hide_a_different_extraction_header(field, value):
    source, output, materialized, inputs, context, base, parent, binding = _case()
    extraction = materialized.extraction.model_copy(update={field: value})
    # The altered header is structurally admissible, but its exact original
    # response/source/attempt binding no longer corresponds to this candidate.
    type(extraction).model_validate(extraction.model_dump(mode="python"))
    changed = materialized.model_copy(update={"extraction": extraction})
    assert changed.review == materialized.review and changed.review.issues == ()
    assert changed.extraction.source_derivation == inputs.derivation

    with pytest.raises(ValueError):
        _assess(source, output, changed, inputs, context=context,
                base_review=base, verified_parent=parent, binding=binding)
