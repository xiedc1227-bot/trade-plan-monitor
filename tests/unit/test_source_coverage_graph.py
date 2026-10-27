"""Source predicates retain graph relationships independently of AI clause roles."""

import json

from tests.unit.test_source_coverage_semantics import _native_baseline

from trade_plan_monitor.ai.source_coverage import assess_source_coverage


def test_all_relation_and_its_separate_predicates_share_a_source_graph():
    draft, source, mapping = _native_baseline()
    proof = assess_source_coverage(draft, mapping, source)
    root = "alert_rules[0].condition"
    relation = next(row for row in proof.obligations if root in row.paths)
    predicates = [row for row in proof.obligations
                  if any(path.startswith(root + ".conditions[") for path in row.paths)]
    assert proof.coverage_complete
    assert relation.kind == "RELATION"
    assert predicates and all(row.kind == "PREDICATE" for row in predicates)
    assert relation.group_id
    assert all(relation.group_id in row.relation_ids for row in predicates)
    meanings = [json.loads(row.semantics_json) for row in predicates]
    assert any(row["path"].endswith(".comparator") and row["value"] == "GT"
               for row in meanings)
    assert any(row["path"].endswith(".reference.unit") and row["value"] == "FEN"
               for row in meanings)


def test_graph_identity_does_not_depend_on_provider_background_treatment():
    draft, source, mapping = _native_baseline()
    first = assess_source_coverage(draft, mapping, source)
    changed = mapping.model_copy(update={"clauses": tuple(
        row.model_copy(update={"reason": "Provider proposed another explanation"})
        for row in mapping.clauses
    )})
    second = assess_source_coverage(draft, changed, source)
    assert [row.obligation_id for row in first.obligations] == [
        row.obligation_id for row in second.obligations
    ]
    assert first.mapping_hash != second.mapping_hash
    assert first.evidence_hash != second.evidence_hash
