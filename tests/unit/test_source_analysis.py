"""Whole-source analysis is reusable evidence, never complete-draft authority."""

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import DailyMapping
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256


def test_full_initial_source_keeps_the_existing_exact_obligation_and_issue_derivation():
    draft, source, mapping = _baseline()
    full = assess_source_coverage(draft, mapping, source)

    analysis = analyze_source(draft, mapping, source)

    assert analysis.obligations == full.obligations
    assert analysis.issues == full.issues == ()
    assert analysis.source_hash == full.source_hash
    assert analysis.authority_granted is False
    assert not hasattr(analysis, "coverage_complete")
    assert not hasattr(analysis, "status")


def test_partial_change_analysis_does_not_claim_the_unmentioned_full_draft_is_covered():
    draft, _, _ = _baseline()
    path = "position.limit.capital_policy.cap_fen"
    source, mapping = source_mapping(draft)
    selected = tuple(clause for clause in mapping.clauses if path in clause.paths)
    original = source[selected[0].start:selected[-1].end]
    from trade_plan_monitor.ai.daily_review import DailyClause
    from trade_plan_monitor.ai.review import server_source_clauses

    clauses = tuple(DailyClause.model_validate(clause.model_dump() | dict(
        disposition="POLICY", paths=(path,), reason="Exact current scalar change"))
                    for clause in server_source_clauses(original))
    partial = DailyMapping(mapping_version="daily-mapping-v1",
        candidate_content_hash=daily_draft_content_sha256(draft), clauses=clauses,
        bindings=(next(row for row in mapping.bindings if row.path == path).model_copy(update={
            "clause_ids": tuple(row.clause_id for row in clauses),
        }),), supplements=())

    analysis = analyze_source(draft, partial, original)

    assert not analysis.issues
    assert set(analysis.proven_paths) == {path}
    assert all(path in row.paths for row in analysis.obligations)
    assert assess_source_coverage(draft, partial, original).status == "BLOCKED"


def test_shared_analysis_never_filters_the_unbound_unknown_source_remainder():
    draft, source, mapping = _baseline()
    source, mapping = _append_as_context(source, mapping, "Only buy after the green gate opens.",
        semantic_role="COMMENTARY", misclassification={"disposition": "CONTEXT", "paths": (),
                                                       "reason": "Untrusted background claim"})

    analysis = analyze_source(draft, mapping, source)

    unknown = [row for row in analysis.obligations if row.scope == "UNKNOWN"]
    assert unknown and analysis.issues
    assert all(row.excerpt == source[row.start:row.end] for row in unknown)
    assert {row.obligation_id for row in unknown} <= {
        row.obligation_id for row in assess_source_coverage(draft, mapping, source).obligations}


def test_shared_analysis_retains_the_structural_mapping_boundary():
    draft, source, mapping = _baseline()
    changed = mapping.model_copy(update={"candidate_content_hash": "0" * 64})
    with pytest.raises(ValueError, match="content changed"):
        analyze_source(draft, changed, source)
