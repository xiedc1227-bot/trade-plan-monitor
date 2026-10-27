"""A complete JSON subtree still exposes its source-owned predicates and join."""

import json

import pytest
from tests.unit.test_source_coverage_semantics import _native_baseline

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyMapping,
    build_daily_review,
    semantic_values,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_obligations import MISSING, declarations, value_at
from trade_plan_monitor.ai.source_semantic_atoms import semantic_atoms

_ROOT = "alert_rules[0].condition"


def _one_condition_container():
    draft, _, old = _native_baseline()
    values = semantic_values(draft)
    condition = draft.alert_rules[0].condition.model_dump(mode="json")
    covered = tuple(path for path in values if path == _ROOT or path.startswith(_ROOT + "."))
    rows = []
    for path, value in values.items():
        if path == _ROOT:
            rows.append((path, f"{path} = {json.dumps(condition, ensure_ascii=False)}"))
        elif path not in covered:
            rows.append((path, f"{path} = {json.dumps(value, ensure_ascii=False)}"))
    source = "\n".join(line for _, line in rows)
    canonical = server_source_clauses(source)
    groups, ranges, cursor = {}, {}, 0
    for path, line in rows:
        groups[path] = tuple(c for c in canonical if cursor <= c.start < cursor + len(line))
        ranges[path] = (cursor, cursor + len(line))
        cursor += len(line) + 1
    clauses = tuple(DailyClause.model_validate(clause.model_dump() | dict(
        disposition="POLICY", paths=covered if path == _ROOT else (path,),
        reason="One exact complete native JSON declaration",
    )) for path, _ in rows for clause in groups[path])
    bindings = tuple(binding.model_copy(update={
        "clause_ids": tuple(c.clause_id for c in groups[
            _ROOT if binding.path in covered else binding.path]),
    }) for binding in old.bindings)
    mapping = DailyMapping.model_validate(old.model_dump(mode="python") | dict(
        clauses=clauses, bindings=bindings,
    ))
    assert len(groups[_ROOT]) >= 2  # The unchanged native subtree crosses512 code points.
    assert not build_daily_review(draft, mapping, source).issues
    return draft, source, mapping, condition, ranges[_ROOT]


def _meaning_at(obligation, path):
    meaning = json.loads(obligation.semantics_json or "null")
    if not isinstance(meaning, dict) or not isinstance(meaning.get("path"), str):
        return MISSING
    root, value = meaning["path"], meaning.get("value", MISSING)
    if root == path:
        return value
    if path.startswith(root + "."):
        return value_at(value, path[len(root) + 1:])
    return MISSING


def test_complete_native_container_retains_independent_all_and_price_atoms():
    draft, source, mapping, condition, container_span = _one_condition_container()

    result = assess_source_coverage(draft, mapping, source)

    assert result.coverage_complete is True
    assert result.issues == ()
    assert result.authority_granted is False
    canonical = {clause.clause_id: clause for clause in server_source_clauses(source)}
    for atom in result.obligations:
        assert atom.excerpt == source[atom.start:atom.end]
        owner = canonical[atom.clause_id]
        assert owner.start <= atom.start < atom.end <= owner.end
    relevant = [o for o in result.obligations
                if container_span[0] <= o.start < o.end <= container_span[1]]
    joins = [o for o in relevant if o.kind == "RELATION" and (
        _meaning_at(o, _ROOT + ".type") == "ALL" or _meaning_at(o, _ROOT) == "ALL")]
    assert joins, "A full-object comparison must not hide its ALL relation"
    parent_ids = {identity for o in joins for identity in (o.obligation_id, o.group_id) if identity}
    used_predicates = []
    for index, node in enumerate(condition["conditions"]):
        path = f"{_ROOT}.conditions[{index}]"
        atoms = [o for o in relevant if o.kind == "PREDICATE" and any(
            p == path or p.startswith(path + ".") for p in o.paths)]
        assert atoms, f"Missing independent native predicate for {path}"
        assert all(o.scope == "ALERT" for o in atoms)
        assert any(parent_ids.intersection(o.relation_ids) for o in atoms)
        for suffix in ("type", "field", "comparator", "offset", "reference.mode"):
            expected = value_at(node, suffix)
            assert any(_meaning_at(o, path + "." + suffix) == expected for o in atoms)
        reference_key = "reference.unit" if index == 0 else "reference.indicator"
        assert any(_meaning_at(o, path + "." + reference_key) == value_at(node, reference_key)
                   for o in atoms)
        used_predicates.append({o.obligation_id for o in atoms})
    assert used_predicates[0].isdisjoint(used_predicates[1])


def test_native_atom_count_at_bound_is_complete_with_exact_spans():
    source = "untrusted = [" + ",".join("0" for _ in range(4096)) + "]"
    declaration, = declarations(source)

    atoms = semantic_atoms(source, declaration)

    assert len(atoms) == 4096
    assert len({atom.path for atom in atoms}) == 4096
    assert atoms[-1].path == "untrusted[4095]"
    assert all(source[atom.start:atom.end] == "0" for atom in atoms)


def test_native_atom_count_above_bound_explicitly_rejects_without_partial_result():
    source = "untrusted = [" + ",".join("0" for _ in range(4097)) + "]"
    declaration, = declarations(source)

    with pytest.raises(ValueError, match="^SOURCE_COVERAGE_LIMIT_EXCEEDED$"):
        semantic_atoms(source, declaration)


def _append_untrusted_container(value):
    draft, source, mapping, _, _ = _one_condition_container()
    extra_start = len(source) + 1
    source += "\nuntrusted = " + json.dumps(value)
    extra = tuple(DailyClause.model_validate(clause.model_dump() | dict(
        disposition="CONTEXT", paths=(), reason="Provider claimed background",
    )) for clause in server_source_clauses(source) if clause.start >= extra_start)
    mapping = mapping.model_copy(update={"clauses": (*mapping.clauses, *extra)})
    assert not build_daily_review(draft, mapping, source).issues
    return draft, source, mapping


@pytest.mark.parametrize("value", [{"type": "ALL"}, {"type": "ANY"}])
def test_incomplete_untrusted_relation_retains_blocked_assessment(value):
    draft, source, mapping = _append_untrusted_container(value)

    result = assess_source_coverage(draft, mapping, source)

    assert result.coverage_complete is False
    assert result.authority_granted is False
    assert result.issues
