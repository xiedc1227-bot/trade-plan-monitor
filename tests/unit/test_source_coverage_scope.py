"""Trade scope comes from complete source evidence, never candidate intent."""

import json
from copy import deepcopy

from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_semantics import _native_baseline, _rebuilt_source

from trade_plan_monitor.ai.daily_review import DailyClause, DailyMapping, semantic_values
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, SourceObligation
from trade_plan_monitor.domain.p3_validation import P3PlanDraft

_RULE = "ordinary_rules[0]"
_SIDE = _RULE + ".side"


def _rebuilt_rows(draft, original, rows, *, missing=None, one_ref_paths=()):
    """Give each row exact canonical spans; mappings cannot choose its true scope."""
    source = "\n".join(line for _, line, _ in rows)
    canonical = server_source_clauses(source)
    groups, owner, cursor = {}, {}, 0
    clauses = []
    for row_path, line, paths in rows:
        group = tuple(clause for clause in canonical if cursor <= clause.start < cursor + len(line))
        assert group
        groups[row_path] = group
        owner.update((path, row_path) for path in paths)
        clauses.extend(DailyClause.model_validate(clause.model_dump() | dict(
            disposition="POLICY", paths=paths, reason="Exact source declaration",
        )) for clause in group)
        cursor += len(line) + 1
    owner.update(missing or {})
    mapping = DailyMapping.model_validate(original.model_dump(mode="python") | dict(
        clauses=tuple(clauses),
        bindings=tuple(binding.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in (
                groups[owner[binding.path]][:1] if binding.path in one_ref_paths
                else groups[owner[binding.path]]
            )),
        }) for binding in original.bindings),
    ))
    assert [(c.clause_id, c.start, c.end, c.excerpt) for c in mapping.clauses] == [
        (c.clause_id, c.start, c.end, c.excerpt) for c in canonical
    ]
    return source, mapping


def _ordinary_atoms(result, prefix=_RULE):
    return [row for row in result.obligations if any(
        path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[")
        for path in row.paths
    )]


def test_source_sell_candidate_buy_conflict_has_unknown_trade_scope():
    draft, _, original = _native_baseline()
    source, mapping, _ = _rebuilt_source(draft, original, replacements={_SIDE: "SELL"})

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def test_unstated_side_cannot_borrow_candidate_buy_scope():
    draft, _, original = _native_baseline()
    values = semantic_values(draft)
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items() if path != _SIDE]
    source, mapping = _rebuilt_rows(draft, original, rows, missing={
        _SIDE: _RULE + ".rule_id",
    })

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def test_conflicting_source_side_declarations_do_not_select_one_buy_claim():
    draft, _, original = _native_baseline()
    values = semantic_values(draft)
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items()]
    rows.append(("conflicting-side", f'{_SIDE} = "SELL"', (_SIDE,)))
    source, mapping = _rebuilt_rows(draft, original, rows)

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def _buy_and_sell_container():
    before, _, _ = _native_baseline()
    raw = before.model_dump(mode="json")
    sell = deepcopy(raw["ordinary_rules"][0])
    for key in ("market_policy", "quantity_policy", "pretrade_policy"):
        sell.pop(key)
    sell.update(side="SELL", rule_id="source-scoped-sell", quantity=100, zone="PRESSURE",
                condition=raw["alert_rules"][0]["condition"])
    raw["ordinary_rules"].append(sell)
    draft = P3PlanDraft.model_validate(raw)
    _, original = source_mapping(draft)
    values = semantic_values(draft)
    owned = tuple(path for path in values if path.startswith("ordinary_rules["))
    container = [rule.model_dump(mode="json") for rule in draft.ordinary_rules]
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items() if path not in owned]
    rows.append(("ordinary_rules", "ordinary_rules = " + json.dumps(container), owned))
    # A container is one complete declaration; one genuine owning clause is a
    # bounded AI citation. The server must derive every child independently.
    source, mapping = _rebuilt_rows(draft, original, rows, one_ref_paths=owned)
    return draft, source, mapping


def test_complete_rules_container_scopes_each_native_atom_from_its_source_side():
    draft, source, mapping = _buy_and_sell_container()

    result = assess_source_coverage(draft, mapping, source)

    for index, side in enumerate(("BUY", "SELL")):
        atoms = _ordinary_atoms(result, f"ordinary_rules[{index}]")
        assert atoms
        assert all(atom.scope == side for atom in atoms)
        assert any(atom.kind == "RELATION" for atom in atoms)
        assert any(atom.kind == "PREDICATE" for atom in atoms)
    assert all(atom.excerpt == source[atom.start:atom.end] for atom in result.obligations)


def test_mapped_obligation_with_unknown_scope_cannot_make_current_complete():
    draft, source, mapping = _native_baseline()
    baseline = assess_source_coverage(draft, mapping, source)
    original = _ordinary_atoms(baseline)[0]
    unknown = SourceObligation.build(**(original.model_dump(mode="python", exclude={
        "obligation_id",
    }) | dict(scope="UNKNOWN", state="MAPPED")))

    result = CoverageAssessment.build(source_hash=baseline.source_hash,
        content_hash=baseline.content_hash, mapping_hash=baseline.mapping_hash,
        origin="AI_HISTORICAL", obligations=(unknown,), issues=())

    assert result.coverage_complete is False
    assert result.status == "BLOCKED"
    assert result.authority_granted is False


def test_unregistered_global_risk_requirement_inside_buy_keeps_unknown_scope():
    before, _, _ = _native_baseline()
    raw = before.model_dump(mode="json")
    path = _RULE + ".condition.conditions[0].evidence_requirement"
    requirement = "所有风险退出必须先等蓝灯亮起才能执行。"
    raw["ordinary_rules"][0]["condition"]["conditions"][0]["evidence_requirement"] = requirement
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    assert json.dumps(requirement, ensure_ascii=False) in source

    result = assess_source_coverage(draft, mapping, source)

    unknown = [atom for atom in result.obligations
               if path in atom.paths and atom.state == "UNRESOLVED"]
    assert result.status == "BLOCKED"
    assert result.authority_granted is False
    assert unknown
    assert all(atom.scope == "UNKNOWN" for atom in unknown)
