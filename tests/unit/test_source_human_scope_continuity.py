"""Scope continuity consumes a complete, upstream-authenticated human parent.

The pure helper cannot authenticate SQL registration from an opaque receipt hash.
Fixtures assume the state adapter has authenticated that parent and independently
check only the exact source/owner/supplement dependencies available to this helper.
"""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_semantics import _rebuilt_source
from tests.unit.test_source_human_initial_assurance import _case as _initial_case

from trade_plan_monitor.ai.daily_review import DailyClause, DailySupplement
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_candidate_models import source_prefix_hash
from trade_plan_monitor.ai.source_change_scopes import inherit_change_scopes
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_human_initial_assurance import assess_human_initial_current
from trade_plan_monitor.ai.update_review import PlanCandidateReview, build_initial_review
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate
from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand


def _human_parent(*, side_fill=None):
    source, review, mapping, operation, binding, *_ = _initial_case()
    if side_fill is not None:
        side_path = f"ordinary_rules[{side_fill}].side"
        _, raw_mapping = source_mapping(review.draft)
        text, mapping, _ = _rebuilt_source(review.draft, raw_mapping,
            replacements={"position.max_qty": None, side_path: None})
        cap = operation.resolved_mapping.supplements[0]
        supplement = DailySupplement(supplement_id=f"registered-side-{side_fill}",
            candidate_content_hash=mapping.candidate_content_hash, path=side_path,
            value=review.draft.ordinary_rules[side_fill].side,
            reason="Explicit existing registered fill of the source-null direction")
        fills = {row.path: row for row in (cap, supplement)}
        mapping = mapping.model_copy(update=dict(supplements=(cap, supplement),
            bindings=tuple(row.model_copy(update=dict(origin="HUMAN_SUPPLEMENT", clause_ids=(),
                supplement_id=fills[row.path].supplement_id)) if row.path in fills else row
                for row in mapping.bindings)))
        source = source.model_copy(update={"text": text})
        review = build_initial_review(review.draft, mapping, source)
        old = PlanCandidateReview.model_validate_json(operation.original_candidate.payload_json)
        before = old.model_copy(update={"source_hash": source.binding_hash})
        original = CollectionPreparationCandidate(**before.to_preparation_candidate().model_dump(),
            source_revision=1, source_hash=source.binding_hash, base_hash=None)
        after = CollectionPreparationCandidate(**review.to_preparation_candidate().model_dump(),
            source_revision=1, source_hash=source.binding_hash, base_hash=None)
        binding = binding.model_copy(update=dict(source_binding_hash=source.binding_hash,
            candidate_hash=after.candidate_hash, review_evidence_hash=review.evidence_hash))
        command = CollectionItemCorrectionCommand.model_validate_json(operation.command_json)
        command = command.model_copy(update=dict(mapping=mapping,
            binding=command.binding.model_copy(update=dict(candidate_hash=original.candidate_hash,
                                                           evidence_hash=original.evidence_hash))))
        operation = PreparationHumanOperation.build(**(
            {name: getattr(operation, name) for name in type(operation).model_fields
             if name not in {"evidence_key", "evidence_hash"}}
            | dict(source=source, original_candidate=original,
                before_candidate_hash=original.candidate_hash,
                before_evidence_hash=original.evidence_hash,
                after_candidate_hash=after.candidate_hash, after_evidence_hash=after.evidence_hash,
                command_json=canonical_json(command), resolved_mapping=mapping,
                resolved_review=review, assessment_binding=binding,
                prefix_hash=source_prefix_hash((), binding))))
    operation = PreparationHumanOperation.build(**(
        {name: getattr(operation, name) for name in type(operation).model_fields
         if name not in {"evidence_key", "evidence_hash"}}
        | dict(command_id="upstream-authenticated-human-command", command_request_hash="a" * 64,
               after_record_hash="b" * 64)))
    parent = assess_human_initial_current(source, review, mapping, operation, binding=binding)
    assert parent.coverage_complete and review.issues == ()
    assert parent.source_assessment.origin == "HUMAN" and review.draft.position.max_qty == 300
    assert source.text.count("position.max_qty = null") == 1
    return source, review, mapping, operation, parent


def _current(review, index=0, kind="quantity", *, text=None, rule_id=None):
    raw = review.draft.model_dump(mode="json")
    rule = raw["ordinary_rules"][index]
    if rule_id is not None:
        rule["rule_id"] = rule_id
    path = f"ordinary_rules[{index}]"
    if kind == "quantity":
        path += ".quantity"
        value = rule["quantity"] = 200
    else:
        condition = rule["condition"]
        path += ".condition"
        if condition["type"] == "ALL":
            condition = condition["conditions"][0]
            path += ".conditions[0]"
        path += ".low_fen"
        value = condition["low_fen"] = condition["low_fen"] + 1
    proposed = type(review.draft).model_validate(raw)
    _, original = source_mapping(proposed)
    text = text or path + " = " + json.dumps(value)
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
        disposition="POLICY", semantic_role="DIRECTIVE", paths=(path,),
        reason="Fresh exact current scalar declaration")) for row in server_source_clauses(text))
    mapping = original.model_copy(update={"clauses": clauses,
        "bindings": tuple(row.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in clauses)})
            for row in original.bindings if row.path == path)})
    analysis = analyze_source(proposed, mapping, text)
    return proposed, analysis.obligations, text, path


@pytest.mark.parametrize("index,side", [(0, "BUY"), (1, "SELL")])
@pytest.mark.parametrize("kind", ["quantity", "condition"])
def test_source_proven_side_in_human_initial_parent_survives_scalar_change(index, side, kind):
    source, review, _, operation, parent = _human_parent()
    side_path = f"ordinary_rules[{index}].side"
    bound = next(row for row in review.bindings if row.path == side_path)
    owner = next(row for row in parent.owners if row.path == side_path)
    assert bound.binding.origin == "SOURCE" and bound.binding.value == side
    assert owner.origin == "HUMAN" and owner.human_receipt_hash == operation.evidence_hash
    assert any(row.excerpt == side_path + ' = "' + side + '"'
               and row.state == "MAPPED" and row.scope == side
               for row in parent.source_assessment.obligations)
    proposed, original, text, _ = _current(review, index, kind)
    assert len(original) == 1 and original[0].state == "MAPPED"
    assert original[0].scope == "UNKNOWN"
    before = (parent.model_dump_json(), review.model_dump_json())

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert issues == () and enriched[0].scope == side
    assert enriched[0].obligation_id != original[0].obligation_id
    assert original[0].scope == "UNKNOWN" and enriched[0].state == "MAPPED"
    assert text[enriched[0].start:enriched[0].end] == enriched[0].excerpt
    meaning = json.loads(enriched[0].semantics_json)["inherited_scope"]
    assert meaning["parent_assurance_hash"] == parent.evidence_hash
    assert meaning["rule_id"] == proposed.ordinary_rules[index].rule_id
    assert meaning["side_owner"] == owner.model_dump(mode="json")
    assert meaning["side_owner"]["human_receipt_hash"] == operation.evidence_hash
    assert owner.source_binding_hash == source.binding_hash
    assert (parent.model_dump_json(), review.model_dump_json()) == before


@pytest.mark.parametrize("index,side", [(0, "BUY"), (1, "SELL")])
def test_existing_null_side_registry_requires_exact_human_field_source_and_supplement(index, side):
    source, review, mapping, operation, parent = _human_parent(side_fill=index)
    path = f"ordinary_rules[{index}].side"
    bound = next(row for row in review.bindings if row.path == path)
    owner = next(row for row in parent.owners if row.path == path)
    assert bound.binding.origin == "HUMAN_SUPPLEMENT" and bound.binding.clause_ids == ()
    assert bound.supplement.path == path and bound.supplement.value == side
    assert bound.supplement.candidate_content_hash == mapping.candidate_content_hash
    assert bound.binding.supplement_id == bound.supplement.supplement_id
    assert owner.human_receipt_hash == operation.evidence_hash and owner.origin == "HUMAN"
    assert owner.source_binding_hash == bound.source_hash == source.binding_hash
    atom, = [row for row in parent.source_assessment.obligations if row.paths == (path,)]
    assert atom.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT" and atom.scope == side
    assert source.text[atom.start:atom.end] == atom.excerpt == path + " = null"


@pytest.mark.parametrize("index,side", [(0, "BUY"), (1, "SELL")])
def test_registered_source_null_human_side_survives_an_exact_current_quantity_change(index, side):
    _, review, _, operation, parent = _human_parent(side_fill=index)
    proposed, original, _, _ = _current(review, index)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert issues == () and enriched[0].scope == side
    owner = json.loads(enriched[0].semantics_json)["inherited_scope"]["side_owner"]
    assert owner["human_receipt_hash"] == operation.evidence_hash
    assert owner["path"] == f"ordinary_rules[{index}].side"


def _replace_parent(parent, **changes):
    return type(parent).build(**(
        {name: getattr(parent, name) for name in type(parent).model_fields
         if name not in {"status", "evidence_hash"}} | changes))


@pytest.mark.parametrize("side_fill", [None, 0])
@pytest.mark.parametrize("problem", ["missing_receipt", "blocked_parent", "changed_rule",
                                    "current_side_conflict"])
def test_human_scope_stays_unknown_when_receipt_parent_rule_or_current_source_is_unproven(
    side_fill, problem,
):
    _, review, _, _, parent = _human_parent(side_fill=side_fill)
    changes = {}
    if problem == "missing_receipt":
        owners = tuple(row.model_copy(update={"human_receipt_hash": None})
                       if row.path == "ordinary_rules[0].side" else row for row in parent.owners)
        parent = _replace_parent(parent, owners=owners)
        assert not parent.coverage_complete
    elif problem == "blocked_parent":
        parent = _replace_parent(parent, issues=(CoverageIssue(
            code="SOURCE_COVERAGE_REQUIRED", message="Unresolved inherited source condition"),))
    elif problem == "changed_rule":
        changes = dict(rule_id="new-stable-rule")
    else:
        changes = dict(text='ordinary_rules[0].quantity = 200\nordinary_rules[0].side = "SELL"')
    proposed, original, _, _ = _current(review, **changes)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and all(row.scope == "UNKNOWN" for row in enriched)
    assert issues


def test_base_owner_cannot_hide_the_missing_receipt_of_a_human_supplied_direction():
    _, review, _, _, parent = _human_parent(side_fill=0)
    owners = tuple(row.model_copy(update={"origin": "BASE", "human_receipt_hash": None})
                   if row.path == "ordinary_rules[0].side" else row for row in parent.owners)
    parent = _replace_parent(parent, owners=owners)
    assert parent.coverage_complete
    proposed, original, _, _ = _current(review)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and enriched[0].scope == "UNKNOWN" and issues


@pytest.mark.parametrize("problem", ["supplement_reason", "supplement_content", "source_path"])
def test_complete_parent_headers_cannot_replace_the_exact_proven_side_supplement(problem):
    source, review, _, _, parent = _human_parent(side_fill=0)
    path = "ordinary_rules[0].side"
    old = next(row for row in review.bindings if row.path == path)
    updates = {}
    if problem == "supplement_reason":
        updates["supplement"] = old.supplement.model_copy(update={
            "reason": "A different unproven supplementary assertion"})
    elif problem == "supplement_content":
        updates["supplement"] = old.supplement.model_copy(update={
            "candidate_content_hash": "f" * 64})
        updates["candidate_content_hash"] = "f" * 64
    else:
        wrong_path = "ordinary_rules[1].side"
        updates = dict(original_path=wrong_path,
            binding=old.binding.model_copy(update={"path": wrong_path}),
            supplement=old.supplement.model_copy(update={"path": wrong_path}))
    changed = old.model_copy(update=updates)
    review = review.model_copy(update={"bindings": tuple(
        changed if row.path == path else row for row in review.bindings)})
    candidate = CollectionPreparationCandidate(**review.to_preparation_candidate().model_dump(),
        source_revision=1, source_hash=source.binding_hash, base_hash=None)
    binding = parent.binding.model_copy(update=dict(candidate_hash=candidate.candidate_hash,
                                                    review_evidence_hash=review.evidence_hash))
    owners = tuple(row.model_copy(update={"original_path": changed.original_path})
                   if row.path == path else row for row in parent.owners)
    parent = _replace_parent(parent, binding=binding, owners=owners,
                             prefix_hash=source_prefix_hash((), binding))
    assert parent.coverage_complete
    proposed, original, _, _ = _current(review)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and enriched[0].scope == "UNKNOWN" and issues


@pytest.mark.parametrize("text", [
    "所有风险退出必须先等蓝灯亮起才能执行。", "Proceed once the blue lantern opens.",
])
def test_verified_human_side_does_not_assign_buy_scope_to_unregistered_current_prose(text):
    _, review, _, _, parent = _human_parent(side_fill=0)
    proposed, original, _, _ = _current(review, text=text)
    assert original
    assert all(row.state == "UNRESOLVED" and row.scope == "UNKNOWN" for row in original)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and issues == ()


def test_current_human_proof_cannot_hide_its_missing_receipt_under_a_source_owner_label():
    _, review, _, _, parent = _human_parent()
    owners = tuple(row.model_copy(update={"origin": "CURRENT", "human_receipt_hash": None})
                   if row.path == "ordinary_rules[0].side" else row for row in parent.owners)
    parent = _replace_parent(parent, owners=owners)
    assert parent.coverage_complete and parent.source_assessment.origin == "HUMAN"
    proposed, original, _, _ = _current(review)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and enriched[0].scope == "UNKNOWN" and issues
