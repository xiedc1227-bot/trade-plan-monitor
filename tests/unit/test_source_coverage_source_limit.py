"""Coverage's work cap cannot remove a structurally valid preserved draft source."""

import pytest
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.source_obligations import bounded_clauses
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def large_case(source=None, *, partial=False):
    source = "large provenance:" + "x" * 200_000 if source is None else source
    raw = UnifiedPlanDraft.from_executable(
        UnifiedTradePlan.model_validate(unified_payload())).model_dump(mode="json")
    if partial:
        raw["activation"] = None
    draft = UnifiedPlanDraft.model_validate(raw)
    return draft, source, reviewed_mapping(draft, source)


@pytest.mark.parametrize("source", ["x" * 150_001, "large provenance:" + "x" * 200_000,
                                  "😀" * 150_001], ids=["just-over", "original-200017", "unicode"])
def test_native_valid_source_above_coverage_work_bound_has_only_a_global_limit_ledger(source):
    draft, source, mapping = large_case(source)
    before = (draft.model_dump_json(), mapping.model_dump_json(), source)
    native = build_daily_review(draft, mapping, source)
    assert native.issues == ()

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED" and not result.coverage_complete
    assert not result.authority_granted and not result.automatic_fidelity_verified
    assert result.normalization_hash is None and result.obligations == ()
    issue, = result.issues
    assert issue.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"
    assert issue.path == "source" and issue.start is issue.end is None
    assert result.source_hash == scope_hash(source)
    assert result.content_hash == daily_draft_content_sha256(draft)
    assert result.mapping_hash == daily_hash("source-coverage-mapping-v1",
                                            native.mapping.model_dump(mode="json"))
    assert (draft.model_dump_json(), mapping.model_dump_json(), source) == before
    assert assess_source_coverage(draft, mapping, source) == result


def test_exact_coverage_bound_still_runs_full_analysis_and_does_not_report_budget_fallback():
    draft, source, mapping = large_case("x" * 150_000)
    result = assess_source_coverage(draft, mapping, source)
    assert result.obligations and result.status == "BLOCKED"
    assert all(row.end <= 150_000 for row in result.obligations)
    assert not any(row.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED" for row in result.issues)


def test_bounded_clause_parser_retains_its_exact_hard_work_cap():
    assert bounded_clauses("x" * 150_000)
    with pytest.raises(ValueError):
        bounded_clauses("x" * 150_001)


def test_preserved_budget_assessment_does_not_expand_the_native_512_clause_limit():
    source = "\n".join("x" * 293 for _ in range(512))
    assert len(source) > 150_000
    draft, source, mapping = large_case(source)
    assert len(mapping.clauses) == 512
    assert assess_source_coverage(draft, mapping, source).obligations == ()
    with pytest.raises(ValueError):
        assess_source_coverage(draft, mapping, source + "\nextra canonical clause")


@pytest.mark.parametrize("origin", ["AI_NEW", "AI_HISTORICAL", "HUMAN"])
def test_an_available_normalization_trace_is_retained_but_not_asserted_as_checked(origin):
    draft, source, mapping = large_case()
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, source)
    original = trace.model_dump_json()
    result = assess_source_coverage(draft, mapping, source, normalization=trace, origin=origin)
    assert result.origin == origin and result.status == "BLOCKED"
    assert result.normalization_hash is None and not result.automatic_fidelity_verified
    assert trace.model_dump_json() == original
    assert any(row.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED" for row in result.issues)


def test_valid_incomplete_native_draft_keeps_its_existing_parameter_diagnostics():
    draft, source, mapping = large_case(partial=True)
    native = build_daily_review(draft, mapping, source)
    assert any(row.code == "PLAN_PARAMETER_REQUIRED" for row in native.issues)
    result = assess_source_coverage(draft, mapping, source)
    assert not result.coverage_complete and result.obligations == ()
    assert {(row.code, row.path) for row in native.issues} <= {
        (row.code, row.path) for row in result.issues}
    assert result.issues[0].code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("tamper", ["span", "excerpt", "omit", "candidate-hash", "binding-value",
                                    "orphan-supplement", "extra-source-clause"])
def test_structural_or_mapping_corruption_is_not_reclassified_as_a_resource_blocker(tamper):
    draft, source, mapping = large_case()
    if tamper in {"span", "excerpt"}:
        clause = mapping.clauses[0].model_copy(update=(dict(start=1) if tamper == "span" else
                                                       dict(excerpt="forged source")))
        mapping = mapping.model_copy(update=dict(clauses=(clause, *mapping.clauses[1:])))
    elif tamper == "omit":
        mapping = mapping.model_copy(update=dict(clauses=mapping.clauses[:-1]))
    elif tamper == "candidate-hash":
        mapping = mapping.model_copy(update=dict(candidate_content_hash="a" * 64))
    elif tamper == "binding-value":
        binding = mapping.bindings[0].model_copy(update=dict(value="forged native value"))
        mapping = mapping.model_copy(update=dict(bindings=(binding, *mapping.bindings[1:])))
    elif tamper == "orphan-supplement":
        mapping = mapping.model_copy(update=dict(supplements=mapping.supplements[1:]))
    else:
        source += "\nAnother preserved source clause."
    with pytest.raises(ValueError):
        assess_source_coverage(draft, mapping, source)


@pytest.mark.parametrize("source", [" " * 150_001, "x" * 150_000 + "\ud800"],
                         ids=["blank", "invalid-utf8"])
def test_invalid_text_cannot_use_the_budget_preservation_route(source):
    draft, _, mapping = large_case()
    with pytest.raises(ValueError):
        assess_source_coverage(draft, mapping, source)
