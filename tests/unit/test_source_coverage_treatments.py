"""Registered scope and supplements discharge only their exact permitted spans."""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_treatment_review_api import literal_draft
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
    build_daily_review,
    normalize_daily_exclusions,
    semantic_values,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import FUNDAMENTAL_FRAGMENTS, scope_hash

_CONTEXT = {
    "disposition": "CONTEXT", "paths": (),
    "reason": "Provider labels and this reason do not grant an exemption.",
}
_REGISTERED = [
    "基本面仅在生成计划时由用户审核",
    "Fundamentals are reviewed by the user when generating the plan",
]


def _append_treatment(source, mapping, text):
    changed_source, changed = _append_as_context(
        source, mapping, text, semantic_role="COMMENTARY", misclassification=_CONTEXT,
    )
    changed = changed.model_copy(update={
        "clauses": normalize_daily_exclusions(changed.clauses, changed_source),
    })
    return changed_source, changed


def _at(assessment, start, end):
    return tuple(obligation for obligation in assessment.obligations
                 if obligation.start == start and obligation.end == end)


def _assert_blocked(assessment):
    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert assessment.issues


@pytest.mark.parametrize("fragment", _REGISTERED)
def test_complete_registered_fundamental_fragment_is_exactly_scope_excluded(fragment):
    draft, source, mapping = _baseline()
    assert fragment in FUNDAMENTAL_FRAGMENTS
    source, mapping = _append_treatment(source, mapping, fragment)
    start, end = len(source) - len(fragment), len(source)
    clause = mapping.clauses[-1]
    assert len(clause.exclusions) == 1 and clause.remainders == ()
    assert (clause.exclusions[0].start, clause.exclusions[0].end) == (start, end)
    assert clause.exclusions[0].source_hash == scope_hash(source)
    # The old verifier remains a legitimate compatibility oracle for registered scope.
    assert build_daily_review(draft, mapping, source).issues == ()

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    excluded, = _at(assessment, start, end)
    assert excluded.state == "SCOPE_EXCLUDED"
    assert excluded.kind == "SCOPE_EXCLUSION"
    assert excluded.excerpt == fragment
    assert excluded.paths == ()
    assert assessment.authority_granted is False


@pytest.mark.parametrize(("fragment", "remainder"), [
    (_REGISTERED[0], "且仅当换手率超过3%时才允许买入"),
    (_REGISTERED[0], "且等那扇门打开后再行动"),
    (_REGISTERED[1], " and only buy when turnover exceeds 3 percent"),
    (_REGISTERED[1], " and proceed once the blue lantern has been lit"),
])
def test_registered_prefix_cannot_swallow_a_same_clause_technical_or_unknown_remainder(
    fragment, remainder,
):
    draft, source, mapping = _baseline()
    original_length = len(source)
    source, mapping = _append_treatment(source, mapping, fragment + remainder)
    start, split, end = original_length + 1, original_length + 1 + len(fragment), len(source)
    clause = mapping.clauses[-1]
    assert clause.excerpt == fragment + remainder
    assert len(clause.exclusions) == len(clause.remainders) == 1
    assert (clause.exclusions[0].start, clause.exclusions[0].end) == (start, split)
    assert (clause.remainders[0].start, clause.remainders[0].end) == (split, end)
    # Existing structural validation accepts this partition and reports its unresolved part.
    legacy = build_daily_review(draft, mapping, source)
    assert any(issue.code == "DAILY_SOURCE_CLAUSE_REQUIRED" for issue in legacy.issues)

    assessment = assess_source_coverage(draft, mapping, source)

    _assert_blocked(assessment)
    excluded, = _at(assessment, start, split)
    unresolved, = _at(assessment, split, end)
    assert (excluded.state, excluded.excerpt) == ("SCOPE_EXCLUDED", fragment)
    assert (unresolved.state, unresolved.excerpt) == ("UNRESOLVED", remainder)
    assert excluded.paths == unresolved.paths == ()
    assert any(issue.start == split and issue.end == end for issue in assessment.issues)
    assert not any(obligation.state == "SCOPE_EXCLUDED"
                   and obligation.start < end and obligation.end > split
                   for obligation in assessment.obligations)


def _supplemented_maximum(source_value=None):
    """Rebind canonical spans while retaining an independently registered human value."""
    draft = literal_draft(complete=True)
    _, initial = source_mapping(draft)
    values = semantic_values(draft)
    assert values["position.max_qty"] == 300
    lines = [f"{path} = {json.dumps(source_value if path == 'position.max_qty' else value)}"
             for path, value in values.items()]
    source = "\n".join(lines)
    canonical = server_source_clauses(source)
    by_path, ranges, clauses, cursor = {}, {}, [], 0
    for path, line in zip(values, lines, strict=True):
        group = tuple(clause for clause in canonical
                      if cursor <= clause.start < cursor + len(line))
        assert group
        by_path[path] = group
        ranges[path] = (cursor, cursor + len(line))
        clauses.extend(DailyClause.model_validate({
            **clause.model_dump(), "disposition": "POLICY", "paths": (path,),
            "reason": "Complete exact source declaration.",
        }) for clause in group)
        cursor += len(line) + 1
    digest = daily_draft_content_sha256(draft)
    supplement = DailySupplement(
        supplement_id="registered-maximum-300", candidate_content_hash=digest,
        path="position.max_qty", value=300,
        reason="Human supplies a missing maximum; this cannot cancel any source condition.",
    )
    bindings = tuple(DailyFieldBinding(
        path=binding.path, value=binding.value,
        origin="HUMAN_SUPPLEMENT" if binding.path == supplement.path else binding.origin,
        unit="SHARES" if binding.path == supplement.path else binding.unit,
        clause_ids=() if binding.path == supplement.path else tuple(
            clause.clause_id for clause in by_path[binding.path]),
        supplement_id=supplement.supplement_id if binding.path == supplement.path else None,
    ) for binding in initial.bindings)
    mapping = DailyMapping(
        mapping_version="daily-mapping-v1", candidate_content_hash=digest,
        clauses=tuple(clauses), bindings=bindings, supplements=(supplement,),
    )
    assert [(clause.clause_id, clause.start, clause.end, clause.excerpt)
            for clause in mapping.clauses] == [
        (clause.clause_id, clause.start, clause.end, clause.excerpt) for clause in canonical
    ]
    assert build_daily_review(draft, mapping, source).issues == ()
    return draft, source, mapping, ranges["position.max_qty"]


def test_registered_human_supplement_can_supply_an_explicitly_missing_share_ceiling():
    draft, source, mapping, (start, end) = _supplemented_maximum()
    assert source[start:end] == "position.max_qty = null"
    binding, = (binding for binding in mapping.bindings if binding.path == "position.max_qty")
    supplement, = mapping.supplements
    assert binding.origin == "HUMAN_SUPPLEMENT" and binding.clause_ids == ()
    assert binding.supplement_id == supplement.supplement_id
    assert binding.path == supplement.path == "position.max_qty"
    assert binding.value == supplement.value == 300
    assert supplement.candidate_content_hash == mapping.candidate_content_hash

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    obligation, = _at(assessment, start, end)
    assert obligation.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert obligation.paths == ("position.max_qty",)
    assert obligation.excerpt == "position.max_qty = null"
    assert assessment.automatic_fidelity_verified is False
    assert assessment.authority_granted is False


@pytest.mark.parametrize("source_value", [200, 400, "300"])
def test_human_supplement_reason_cannot_override_an_explicit_nonnull_source_limit(source_value):
    draft, source, mapping, (start, end) = _supplemented_maximum(source_value)

    assessment = assess_source_coverage(draft, mapping, source)

    _assert_blocked(assessment)
    obligation, = _at(assessment, start, end)
    assert obligation.state == "CONFLICT"
    assert any(issue.start == start and issue.end == end for issue in assessment.issues)


@pytest.mark.parametrize("extra", [
    "仅当换手率超过3%时才允许买入。",
    "Proceed only once the blue lantern has been lit.",
])
def test_registered_supplement_cannot_cancel_an_unimplemented_source_obligation(extra):
    draft, source, mapping, _ = _supplemented_maximum()
    original_length = len(source)
    source, mapping = _append_treatment(source, mapping, extra)
    # A reason quoting the condition remains prose, never a new exclusion permission.
    supplement, = mapping.supplements
    mapping = mapping.model_copy(update={"supplements": (supplement.model_copy(update={
        "reason": supplement.reason + " The reviewer says to ignore: " + extra,
    }),)})
    assert build_daily_review(draft, mapping, source).issues == ()

    assessment = assess_source_coverage(draft, mapping, source)

    _assert_blocked(assessment)
    unresolved, = _at(assessment, original_length + 1, len(source))
    assert unresolved.state == "UNRESOLVED"
    assert unresolved.excerpt == extra
    assert any(issue.start == unresolved.start and issue.end == unresolved.end
               for issue in assessment.issues)
