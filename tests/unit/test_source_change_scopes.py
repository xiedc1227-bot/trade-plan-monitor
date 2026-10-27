"""Inherited BUY/SELL scope uses exact source leaves and verified stable identity."""

import json
from datetime import timedelta

import pytest
from tests.integration.test_current_plan_api import simple_plan
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_change_assurance import _NOW
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.daily_review import DailyClause, DailyMapping
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_change_scopes import inherit_change_scopes
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue, SourceObligation
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_PATH = "ordinary_rules[0].quantity"


def _parent(side="BUY"):
    draft = UnifiedPlanDraft.from_executable(simple_plan())
    draft = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0].model_copy(update={"side": side}),)})
    text, mapping = source_mapping(draft)
    source = PreparationSource(source_id="scope-parent", text=text,
        available_at=_NOW - timedelta(days=1),
        effective_trade_date=(_NOW - timedelta(days=1)).date())
    review = build_initial_review(draft, mapping, source)
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    assessment = assess_source_coverage(draft, mapping, text, normalization=trace, origin="AI_NEW")
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace, initial_coverage=assessment)
    parent = assess_initial_current(source, review, mapping, inputs,
                                    binding=_binding(source, review, inputs))
    assert parent.coverage_complete and not review.issues
    return draft, review, parent


def _current(draft, text=None, path=_PATH):
    text = text or f"{path} = 200"
    rules = list(draft.ordinary_rules)
    index = int(path.split("[", 1)[1].split("]", 1)[0]) if path.startswith(
        "ordinary_rules[") else 0
    rules[index] = rules[index].model_copy(update={"quantity": 200})
    proposed = draft.model_copy(update={"ordinary_rules": tuple(rules)})
    _, original = source_mapping(proposed)
    clauses = tuple(DailyClause.model_validate(clause.model_dump() | {
        "disposition": "POLICY", "semantic_role": "DIRECTIVE", "paths": (path,),
        "reason": "Exact local source declaration",
    }) for clause in server_source_clauses(text))
    mapping = DailyMapping.model_validate(original.model_dump(mode="python") | {
        "clauses": clauses,
        "bindings": tuple(binding.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in clauses),
        }) for binding in original.bindings if binding.path == path),
    })
    return proposed, analyze_source(proposed, mapping, text).obligations


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_exact_current_leaf_inherits_only_the_same_verified_parent_rule_side(side):
    draft, review, parent = _parent(side)
    proposed, obligations = _current(draft)
    assert len(obligations) == 1
    old = obligations[0]
    assert old.state == "MAPPED" and old.scope == "UNKNOWN"

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert issues == () and len(enriched) == 1
    new = enriched[0]
    assert new.scope == side and new.state == old.state
    assert new.obligation_id != old.obligation_id
    assert old.scope == "UNKNOWN"
    assert (new.source_hash, new.clause_id, new.start, new.end, new.excerpt, new.paths,
            new.group_id, new.relation_ids) == (
        old.source_hash, old.clause_id, old.start, old.end, old.excerpt, old.paths,
        old.group_id, old.relation_ids)
    meaning = json.loads(new.semantics_json)
    assert meaning["inherited_scope"]["parent_assurance_hash"] == parent.evidence_hash
    assert meaning["inherited_scope"]["rule_id"] == draft.ordinary_rules[0].rule_id
    assert meaning["inherited_scope"]["side"] == side
    owner = next(row for row in parent.owners if row.path == "ordinary_rules[0].side")
    assert meaning["inherited_scope"]["side_owner"] == owner.model_dump(mode="json")
    assert meaning["source_meaning"] == json.loads(old.semantics_json)


def _replace_obligation(old, **changes):
    return SourceObligation.build(**(
        old.model_dump(mode="python", exclude={"obligation_id"}) | changes))


def _replace_parent(parent, **changes):
    return type(parent).build(**(
        {name: getattr(parent, name) for name in type(parent).model_fields
         if name not in {"status", "evidence_hash"}} | changes))


@pytest.mark.parametrize("state", [
    "UNRESOLVED", "UNSUPPORTED", "CONFLICT", "MAPPED_WITH_REGISTERED_SUPPLEMENT",
    "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
])
def test_non_mapped_source_treatments_never_borrow_a_parent_scope(state):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    original = (_replace_obligation(obligations[0], state=state),)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and issues == ()


@pytest.mark.parametrize("scope", ["BUY", "SELL", "RISK", "PLAN", "ALERT"])
def test_already_scoped_obligations_keep_their_original_identity(scope):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    original = (_replace_obligation(obligations[0], scope=scope),)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and issues == ()


@pytest.mark.parametrize("text", [
    "Only buy when turnover exceeds 3 percent.",
    "所有风险退出必须先等蓝灯亮起才能执行。",
    "等那扇门打开后再行动。",
])
def test_unknown_prose_does_not_become_buy_scoped_from_an_ai_path_or_parent(text):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft, text=text)
    assert all(row.scope == "UNKNOWN" and row.state == "UNRESOLVED" for row in obligations)

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations and issues == ()


def test_even_a_self_consistent_mapped_label_cannot_turn_unknown_prose_into_a_declaration():
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    text = "所有风险退出必须先等蓝灯亮起才能执行。"
    original = (_replace_obligation(obligations[0], excerpt=text, start=0, end=len(text)),)

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and issues == ()


@pytest.mark.parametrize("change", ["new_identity", "opposite_side"])
def test_different_or_changed_rule_identity_cannot_borrow_old_buy_scope(change):
    draft, review, parent = _parent()
    updates = {"rule_id": "new-rule"} if change == "new_identity" else {"side": "SELL"}
    draft = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0].model_copy(update=updates),)})
    proposed, obligations = _current(draft)

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in issues)


def test_reordered_rule_uses_stable_identity_rather_than_the_old_index():
    draft, review, parent = _parent()
    old = draft.ordinary_rules[0]
    added = old.model_copy(update={"rule_id": "unrelated-sell", "side": "SELL"})
    draft = draft.model_copy(update={"ordinary_rules": (added, old)})
    proposed, obligations = _current(draft, path="ordinary_rules[1].quantity")

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert issues == () and enriched[0].scope == "BUY"
    proof = json.loads(enriched[0].semantics_json)["inherited_scope"]
    assert proof["rule_id"] == old.rule_id
    assert proof["side_owner"]["path"] == "ordinary_rules[0].side"


@pytest.mark.parametrize("field,value", [
    ("source_id", "another-source"), ("source_hash", "a" * 64),
    ("available_at", _NOW - timedelta(days=2)),
])
def test_wrong_parent_source_or_review_identity_is_structural_tamper(field, value):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    wrong = review.model_copy(update={field: value})

    with pytest.raises(ValueError):
        inherit_change_scopes(obligations, proposed, wrong, parent)


def test_incomplete_parent_keeps_current_scope_unknown_and_explains_the_blocker():
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    parent = _replace_parent(parent, issues=(CoverageIssue(
        code="SOURCE_COVERAGE_REQUIRED", message="Unproven prior condition"),))
    assert not parent.coverage_complete

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in issues)


@pytest.mark.parametrize("problem", ["missing_owner", "unrelated_obligation", "product_owner"])
def test_side_owner_must_independently_prove_the_actual_parent_side(problem):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    other = next(row for row in parent.source_assessment.obligations
                 if row.paths == ("ordinary_rules[0].quantity",))
    owners = []
    for owner in parent.owners:
        if owner.path == "ordinary_rules[0].side":
            if problem == "missing_owner":
                continue
            owner = owner.model_copy(update=(
                {"obligation_ids": (other.obligation_id,)} if problem == "unrelated_obligation"
                else {"origin": "PRODUCT_CONTRACT"}))
        owners.append(owner)
    parent = _replace_parent(parent, owners=tuple(owners))
    assert parent.coverage_complete

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in issues)


def test_container_predicate_atoms_are_outside_the_first_scalar_scope_slice():
    draft, review, parent = _parent()
    path = "ordinary_rules[0].condition"
    text = path + " = " + json.dumps(draft.ordinary_rules[0].condition.model_dump(mode="json"))
    proposed, obligations = _current(draft, text=text, path=path)
    assert obligations and all(row.scope == "UNKNOWN" for row in obligations)

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations and issues == ()


@pytest.mark.parametrize("count", [65, 4097])
def test_overflow_retains_all_original_obligations_and_emits_an_explicit_limit(count):
    draft, review, parent = _parent()
    proposed, obligations = _current(draft)
    original = tuple(_replace_obligation(obligations[0],
        clause_id=("shared-clause" if count == 65 else f"clause-{index}"))
        for index in range(count))

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert len(enriched) == count and enriched == original
    assert any(row.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED" for row in issues)


@pytest.mark.parametrize("kind", ["bool_integer", "integer_float"])
def test_scalar_meaning_requires_exact_json_types_not_python_numeric_equality(kind):
    draft, review, parent = _parent()
    if kind == "bool_integer":
        path = "ordinary_rules[0].condition.include_low"
        condition = dict(type="MINUTE_CLOSE_IN_RANGE", timeframe_minutes=5,
                         low_fen=3900, high_fen=4000, include_low=True, include_high=True)
        draft = draft.model_copy(update={"ordinary_rules": (
            draft.ordinary_rules[0].model_copy(update={"condition": condition}),)})
        proposed, obligations = _current(draft, text=path + " = true", path=path)
        wrong = 1
    else:
        path = _PATH
        proposed, obligations = _current(draft)
        wrong = 200.0
    original = (_replace_obligation(obligations[0],
        semantics_json=json.dumps({"path": path, "value": wrong},
                                  sort_keys=True, separators=(",", ":"))),)
    assert original[0].state == "MAPPED" and original[0].scope == "UNKNOWN"

    enriched, issues = inherit_change_scopes(original, proposed, review, parent)

    assert enriched == original and issues == ()


@pytest.mark.parametrize("side", ['"SELL"', "null"])
def test_explicit_current_side_conflict_keeps_all_unknown_trade_scopes_unknown(side):
    draft, review, parent = _parent()
    text = f"{_PATH} = 200\nordinary_rules[0].side = {side}"
    proposed, obligations = _current(draft, text=text)
    assert any(row.state == "MAPPED" and row.paths == (_PATH,) for row in obligations)
    assert all(row.scope == "UNKNOWN" for row in obligations)

    enriched, issues = inherit_change_scopes(obligations, proposed, review, parent)

    assert enriched == obligations
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in issues)
