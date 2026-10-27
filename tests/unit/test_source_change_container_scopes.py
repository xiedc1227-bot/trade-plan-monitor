"""Complete source containers and relation atoms borrow only proven stable-rule sides."""

import json
from datetime import timedelta

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import _NOW, _assemble
from tests.unit.test_source_change_scopes import _parent, _replace_obligation
from tests.unit.test_source_initial_assurance import _binding

from trade_plan_monitor.ai.daily_review import DailyClause, DailyFieldBinding, semantic_values
from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_change_composition import assess_change_current
from trade_plan_monitor.ai.source_change_scopes import inherit_change_scopes
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.update_review import build_initial_review, context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

_PATH = "ordinary_rules[0].condition"


def _condition(relation="ALL"):
    return dict(type=relation, conditions=[
        dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=3900),
        dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=3800),
    ])


def _container_case(side="BUY", relation="ALL", *, text=None, condition=None):
    draft, base, parent = _parent(side)
    proposed = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0].model_copy(update={"condition": condition or _condition(relation)}),
    )})
    text = text or _PATH + " = " + canonical(
        proposed.ordinary_rules[0].condition.model_dump(mode="json"))
    mapping = _mapping(proposed, text)
    analysis = analyze_source(proposed, mapping, text)
    return proposed, base, parent, text, analysis


def _mapping(draft, text):
    _, original = source_mapping(draft)
    paths = tuple(path for path in semantic_values(draft)
                  if path == _PATH or path.startswith(_PATH + "."))
    clauses = tuple(DailyClause.model_validate(clause.model_dump() | dict(
        disposition="POLICY", semantic_role="DIRECTIVE", paths=paths,
        reason="Exact complete synthetic source condition declaration"))
        for clause in server_source_clauses(text))
    return original.model_copy(update=dict(clauses=clauses, bindings=tuple(
        row.model_copy(update={"clause_ids": tuple(clause.clause_id for clause in clauses)})
        for row in original.bindings if row.path in paths)))


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("relation", ["ALL", "ANY"])
def test_complete_container_and_native_relations_inherit_the_exact_parent_side(side, relation):
    proposed, base, parent, source, analysis = _container_case(side, relation)
    old_wire, parent_wire = tuple(row.model_dump_json() for row in analysis.obligations), (
        parent.model_dump_json())
    assert analysis.issues == ()
    assert analysis.obligations and all(row.state == "MAPPED" and row.scope == "UNKNOWN"
                                        for row in analysis.obligations)
    assert any(row.kind == "RELATION" for row in analysis.obligations)

    enriched, issues = inherit_change_scopes(
        analysis.obligations, proposed, base, parent, source=source)

    assert issues == () and len(enriched) == len(analysis.obligations)
    assert all(row.scope == side and row.state == "MAPPED" for row in enriched)
    for old, row in zip(analysis.obligations, enriched, strict=True):
        assert row.obligation_id != old.obligation_id
        assert (row.source_hash, row.clause_id, row.start, row.end, row.excerpt, row.paths,
                row.group_id, row.relation_ids) == (
            old.source_hash, old.clause_id, old.start, old.end, old.excerpt, old.paths,
            old.group_id, old.relation_ids)
        meaning = json.loads(row.semantics_json)
        assert meaning["source_meaning"]["declaration"]["path"] == _PATH
        assert meaning["source_meaning"]["declaration"]["value"] == (
            proposed.ordinary_rules[0].condition.model_dump(mode="json"))
        assert meaning["source_meaning"]["obligation"] == json.loads(old.semantics_json)
        assert meaning["inherited_scope"]["parent_assurance_hash"] == parent.evidence_hash
        assert meaning["inherited_scope"]["side_owner"]["path"] == "ordinary_rules[0].side"
    assert tuple(row.model_dump_json() for row in analysis.obligations) == old_wire
    assert parent.model_dump_json() == parent_wire


def test_container_without_complete_original_source_stays_conservatively_unknown():
    proposed, base, parent, _, analysis = _container_case()
    assert inherit_change_scopes(analysis.obligations, proposed, base, parent) == (
        analysis.obligations, ())


@pytest.mark.parametrize("field,value", [
    ("source_hash", "f" * 64), ("clause_id", "another-clause"),
    ("start", 1), ("kind", "RELATION"), ("group_id", "f" * 64),
    ("relation_ids", ("f" * 64,)), ("paths", (_PATH + ".conditions[1]",)),
    ("semantics_json", canonical(dict(path=_PATH, value={"type": "ANY"}))),
], ids=["source-hash", "clause", "span", "kind", "group", "relations", "path", "meaning"])
def test_selfhashed_mapped_atom_must_match_independent_full_source_graph(field, value):
    proposed, base, parent, source, analysis = _container_case()
    old = next(row for row in analysis.obligations
               if row.paths == (_PATH + ".conditions[0]",))
    changes = {field: value}
    if field == "start":
        changes |= dict(excerpt=source[value:old.end])
    forged = _replace_obligation(old, **changes)

    enriched, _ = inherit_change_scopes((forged,), proposed, base, parent, source=source)

    assert enriched == (forged,) and enriched[0].scope == "UNKNOWN"


def test_matching_local_json_excerpt_cannot_hide_unknown_whole_source_prose():
    proposed, base, parent, _, analysis = _container_case()
    old = analysis.obligations[0]
    source = "Only buy when turnover exceeds 3 percent. " + old.excerpt
    clause = server_source_clauses(source)[0]
    forged = _replace_obligation(old, source_hash=scope_hash(source), clause_id=clause.clause_id,
        start=clause.start, end=clause.end, excerpt=clause.excerpt)

    enriched, _ = inherit_change_scopes((forged,), proposed, base, parent, source=source)

    assert enriched == (forged,)


def test_unknown_remainder_and_its_existing_issues_survive_valid_container_enrichment():
    unknown = "Everything else depends on the blue lantern."
    source = _PATH + " = " + canonical(_condition()) + "\n" + unknown
    proposed, base, parent, source, analysis = _container_case(text=source)
    issues_before = tuple(row.model_dump_json() for row in analysis.issues)
    unresolved = next(row for row in analysis.obligations if row.excerpt == unknown)
    assert unresolved.scope == "UNKNOWN" and unresolved.state == "UNRESOLVED"

    enriched, issues = inherit_change_scopes(
        analysis.obligations, proposed, base, parent, source=source)

    assert issues == () and unresolved in enriched
    assert any(row.scope == "BUY" for row in enriched)
    assert tuple(row.model_dump_json() for row in analysis.issues) == issues_before
    assert analysis.issues


def test_whole_container_must_equal_the_actual_complete_candidate():
    proposed, base, parent, source, analysis = _container_case()
    changed = proposed.model_copy(update={"ordinary_rules": (
        proposed.ordinary_rules[0].model_copy(update={"condition": _condition("ANY")}),)})

    enriched, issues = inherit_change_scopes(
        analysis.obligations, changed, base, parent, source=source)

    assert enriched == analysis.obligations and issues == ()


def test_explicit_current_direction_conflict_cannot_borrow_parent_buy_scope():
    source = _PATH + " = " + canonical(_condition()) + '\nordinary_rules[0].side = "SELL"'
    proposed, base, parent, source, analysis = _container_case(text=source)

    enriched, issues = inherit_change_scopes(
        analysis.obligations, proposed, base, parent, source=source)

    assert all(row.scope == "UNKNOWN" for row in enriched)
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in issues)
    assert analysis.issues


def test_long_native_atom_is_verified_against_full_source_and_clipped_to_canonical_clauses():
    condition = dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=3900)
    text = _PATH + " = " + canonical(condition).replace('"price_fen":', '"price_fen":' + " " * 600)
    proposed, base, parent, source, analysis = _container_case(text=text, condition=condition)
    assert len(source) > 512 and analysis.issues == ()
    assert all(row.end - row.start <= 512 for row in analysis.obligations)

    enriched, issues = inherit_change_scopes(
        analysis.obligations, proposed, base, parent, source=source)

    assert issues == () and all(row.scope == "BUY" for row in enriched)
    assert all(row.excerpt == source[row.start:row.end] for row in enriched)


@pytest.mark.parametrize("condition", [
    dict(type="REVIEWED_FACT", fact_kind="TECHNICAL", evidence_requirement="Wait for a blue lamp",
         validity_scope="SIGNAL"),
    dict(type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT", reference=dict(
        mode="DYNAMIC", indicator="MA20", parameters={}, formula_version="daily-ta-v2", offset=0)),
], ids=["unknown-text", "unsupported-native-parameters"])
def test_selfsigned_mapped_treatment_does_not_erase_unsupported_container_semantics(condition):
    proposed, base, parent, source, analysis = _container_case(condition=condition)
    assert analysis.issues
    forged = tuple(_replace_obligation(row, state="MAPPED") for row in analysis.obligations)

    enriched, _ = inherit_change_scopes(forged, proposed, base, parent, source=source)

    assert enriched == forged and all(row.scope == "UNKNOWN" for row in enriched)


def test_scalar_relation_declaration_requires_full_source_for_its_complete_relation_group():
    source = "\n".join((
        _PATH + '.type = "ALL"',
        _PATH + '.conditions[0].type = "MINUTE_CLOSE_BELOW"',
        _PATH + '.conditions[0].timeframe_minutes = 5',
        _PATH + '.conditions[0].price_fen = 3900',
        _PATH + '.conditions[1].type = "MINUTE_CLOSE_BELOW"',
        _PATH + '.conditions[1].timeframe_minutes = 5',
        _PATH + '.conditions[1].price_fen = 3800',
    ))
    proposed, base, parent, source, analysis = _container_case(text=source)
    relation = next(row for row in analysis.obligations if row.kind == "RELATION")
    assert relation.scope == "UNKNOWN"

    enriched, issues = inherit_change_scopes((relation,), proposed, base, parent, source=source)

    assert issues == () and enriched[0].scope == "BUY"
    assert enriched[0].group_id == relation.group_id
    assert json.loads(enriched[0].semantics_json)["source_meaning"]["obligation"] == (
        json.loads(relation.semantics_json))
    assert inherit_change_scopes((relation,), proposed, base, parent) == ((relation,), ())


def test_mixed_rule_collection_container_never_borrows_one_parents_buy_side():
    draft, base, parent = _parent()
    proposed = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0], draft.ordinary_rules[0].model_copy(update={
            "rule_id": "unrelated-sell", "side": "SELL"}),)})
    source = "ordinary_rules = " + canonical([
        row.model_dump(mode="json") for row in proposed.ordinary_rules])
    analysis = analyze_source(proposed, _mapping(proposed, source), source)
    row = next(row for row in analysis.obligations if row.paths == ("ordinary_rules",))
    row = _replace_obligation(row, scope="UNKNOWN")

    enriched, issues = inherit_change_scopes((row,), proposed, base, parent, source=source)

    assert enriched == (row,) and issues == ()


@pytest.mark.parametrize("source", ["x" * 150_001, "\n".join("unknown" for _ in range(513))],
                         ids=["source-length", "canonical-clause-count"])
def test_full_source_limits_retain_original_rows_and_emit_limit_instead_of_truncating(source):
    proposed, base, parent, _, analysis = _container_case()

    enriched, issues = inherit_change_scopes(
        analysis.obligations, proposed, base, parent, source=source)

    assert enriched == analysis.obligations
    assert any(row.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED" for row in issues)


def test_complete_container_meaning_over_8192_is_not_replaced_with_a_shorter_summary():
    draft, base, parent = _parent()
    predicate = dict(type="REVIEWED_FACT", fact_kind="SEVERE_STRUCTURE", validity_scope="SIGNAL",
                     evidence_requirement="Review technical evidence for SEVERE_STRUCTURE")
    condition = dict(type="ALL", conditions=[
        dict(type="ANY", conditions=[predicate] * 50),
        dict(type="ANY", conditions=[predicate] * 50),
    ])
    proposed = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0].model_copy(update={"condition": condition}),)})
    source = _PATH + " = " + canonical(condition)
    assert len(canonical(condition)) > 8192
    _, mapping = source_mapping(proposed)
    mapping = mapping.model_copy(update=dict(bindings=(), clauses=tuple(
        DailyClause.model_validate(clause.model_dump() | dict(disposition="POLICY",
            paths=(_PATH,), reason="Exact partial source graph for the independent bound test"))
        for clause in server_source_clauses(source))))
    analysis = analyze_source(proposed, mapping, source)
    assert analysis.issues == ()
    original = (analysis.obligations[0],)

    enriched, issues = inherit_change_scopes(original, proposed, base, parent, source=source)

    assert enriched == original and enriched[0].scope == "UNKNOWN"
    assert len(issues) == 1 and issues[0].code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"


def _wire_case(side, relation):
    draft, _, _ = _parent(side)
    condition = _condition(relation)
    condition["conditions"][0]["price_fen"] = 4100
    draft = draft.model_copy(update={"ordinary_rules": (
        draft.ordinary_rules[0].model_copy(update={"condition": condition}),)})
    parent_text, parent_mapping = source_mapping(draft)
    parent_source = PreparationSource(source_id="container-parent", text=parent_text,
        available_at=_NOW - timedelta(days=1),
        effective_trade_date=(_NOW - timedelta(days=1)).date())
    base = build_initial_review(draft, parent_mapping, parent_source)
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, parent_text)
    assessment = assess_source_coverage(draft, parent_mapping, parent_text,
                                       normalization=trace, origin="AI_NEW")
    parent_inputs = CoverageInputs.build(source_hash=parent_source.source_hash,
        source_binding_hash=parent_source.binding_hash, normalization=trace,
        initial_coverage=assessment)
    parent = assess_initial_current(parent_source, base, parent_mapping, parent_inputs,
        binding=_binding(parent_source, base, parent_inputs))
    assert parent.coverage_complete and base.issues == ()
    text = _PATH + " = " + canonical(_condition(relation))
    source = PreparationSource(source_id="container-change", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    context = context_from_review(base, parent.binding.candidate_hash)
    _, patch = delta(text, target="ordinary_rules", rule_id=base.draft.ordinary_rules[0].rule_id,
                     values={"condition": _condition(relation)})
    expanded = expand_compact_output(expand_delta_output(patch, context), source, context=context)
    paths = {path: value for path, value in semantic_values(expanded.draft).items()
             if path == _PATH or path.startswith(_PATH + ".")}
    ids = tuple(row.clause_id for row in expanded.clauses)
    expanded = expanded.model_copy(update=dict(
        clauses=tuple(row.model_copy(update={"paths": tuple(paths)}) for row in expanded.clauses),
        bindings=(*tuple(row for row in expanded.bindings
                         if row.origin == "PRODUCT_CONTRACT" and row.path not in paths), *tuple(
            DailyFieldBinding(path=path, value=value, origin=(
                "SOURCE_SEMANTIC" if value is None or type(value) is bool else "SOURCE"),
                unit="JSON", clause_ids=ids, supplement_id=None)
            for path, value in paths.items()))))
    return _assemble(base, parent, source, expanded, context)


@pytest.mark.parametrize("side,relation", [("BUY", "ALL"), ("SELL", "ANY")])
def test_real_full_update_replay_and_aggregate_use_complete_container_scope(side, relation):
    case = _wire_case(side, relation)
    source, output, materialized, inputs, context, base, parent, binding = case
    assert materialized.review.issues == ()
    result = assess_change_current(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding, prefix=(
            PrefixAssuranceRef(binding=parent.binding, assurance_hash=parent.evidence_hash),))

    assert result.coverage_complete, result.source_assessment.issues
    assert result.authority_granted is False
    assert all(row.scope == side for row in result.source_assessment.obligations)
