"""A/B partitions and exact deadline adjustments never grant blanket source waivers."""

import json

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_persistent_rule_validity import persistent_draft
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyMapping,
    DailySupplement,
    build_daily_review,
    semantic_values,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

_SECTIONS = [
    ("A. 执行计划", "B. 背景说明", "历史记录：2026-10-01买入100股。", "账户记录：当前持仓0股。"),
    ("A. Executable plan", "B. Background",
     "Historical record: bought 100 shares on 2026-10-01.",
     "Account record: current holdings are 0 shares."),
]
_MODE_PATH = "ordinary_rules[0].validity.mode"
_DEADLINE = "本规则有效至2026-09-30。"


def _field_rows(draft):
    return [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}")
            for path, value in semantic_values(draft).items()]


def _rebuild_mapping(draft, rows):
    """Regenerate every source identity; declaration values stay bound to the candidate."""
    _, original = source_mapping(draft)
    source = "\n".join(text for _, text in rows)
    canonical = server_source_clauses(source)
    by_path, ranges, clauses, cursor = {}, {}, [], 0
    for path, text in rows:
        selected = tuple(clause for clause in canonical
                         if cursor <= clause.start < cursor + len(text))
        assert selected
        ranges.setdefault(path, []).append((cursor, cursor + len(text)))
        if path is not None:
            by_path.setdefault(path, []).extend(selected)
        for clause in selected:
            clauses.append(DailyClause.model_validate({
                **clause.model_dump(), "disposition": "POLICY" if path else "CONTEXT",
                "paths": (path,) if path else (), "semantic_role": "DIRECTIVE" if path
                else "COMMENTARY", "reason": "Exact complete test source; labels grant no waiver.",
            }))
        cursor += len(text) + 1
    mapping = DailyMapping.model_validate({
        **original.model_dump(mode="python"), "clauses": tuple(clauses),
        "bindings": tuple(binding.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in by_path[binding.path]),
        }) for binding in original.bindings),
    })
    assert [(clause.clause_id, clause.start, clause.end, clause.excerpt)
            for clause in mapping.clauses] == [
        (clause.clause_id, clause.start, clause.end, clause.excerpt) for clause in canonical
    ]
    assert mapping.candidate_content_hash == daily_draft_content_sha256(draft)
    assert [(binding.path, binding.value) for binding in mapping.bindings] == [
        (binding.path, binding.value) for binding in original.bindings
    ]
    return source, mapping, ranges


def _partitioned(section, *, moved_path=None):
    draft, _, _ = _baseline()
    marker_a, marker_b, history, account = section
    rows = _field_rows(draft)
    moved = [row for row in rows if row[0] == moved_path]
    if moved_path:
        assert len(moved) == 1
    arranged = [(None, marker_a), *(row for row in rows if row[0] != moved_path),
                (None, marker_b), (None, history), (None, account), *moved]
    source, mapping, ranges = _rebuild_mapping(draft, arranged)
    # The old review permits these exact values. New failures must be partition failures.
    assert build_daily_review(draft, mapping, source).issues == ()
    return draft, source, mapping, ranges


@pytest.mark.parametrize("section", _SECTIONS, ids=["chinese", "english"])
def test_complete_executable_a_with_only_positive_history_and_account_b_is_covered(section):
    draft, source, mapping, _ = _partitioned(section)

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False
    for marker in section[:2]:
        assert any(obligation.excerpt == marker and obligation.state == "CONTEXT_VERIFIED"
                   for obligation in assessment.obligations)


@pytest.mark.parametrize("section", _SECTIONS, ids=["chinese", "english"])
@pytest.mark.parametrize("moved_path", [
    "ordinary_rules[0].pretrade_policy.sizing.base_qty",
    "ordinary_rules[0].validity.end_date",
])
def test_mandatory_field_moved_to_b_conflicts_even_with_same_candidate_and_valid_bindings(
    section, moved_path,
):
    draft, source, mapping, ranges = _partitioned(section, moved_path=moved_path)
    (start, end), = ranges[moved_path]
    assert source.index(section[1]) < start
    candidate_before, mapping_before = draft.model_dump_json(), mapping.model_dump_json()

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert any(issue.code == "SOURCE_RELATION_MISMATCH" and issue.path == moved_path
               and issue.start == start and issue.end == end for issue in assessment.issues)
    obligation, = (obligation for obligation in assessment.obligations
                   if obligation.start == start and obligation.end == end)
    assert obligation.state == "CONFLICT"
    assert obligation.paths == (moved_path,)
    assert draft.model_dump_json() == candidate_before
    assert mapping.model_dump_json() == mapping_before


def _deadline_mapping(*, deadline=_DEADLINE, reason=None, mutation=None):
    draft = persistent_draft()
    assert len(draft.ordinary_rules) == 1
    assert draft.ordinary_rules[0].validity.mode == "PLAN_ACTIVE"
    source, mapping, _ = _rebuild_mapping(draft, [*_field_rows(draft), (None, deadline)])
    digest = daily_draft_content_sha256(draft)
    supplement = DailySupplement(
        supplement_id="registered-deadline-conversion", candidate_content_hash=digest,
        path=_MODE_PATH, value="PLAN_ACTIVE",
        reason=reason or f"引用原句：{deadline} 改为持续有效；重新审核并明确启用。",
    )
    if mutation:
        supplement = supplement.model_copy(update=mutation)
    mapping = mapping.model_copy(update={
        "bindings": tuple(binding.model_copy(update={
            "origin": "HUMAN_SUPPLEMENT", "unit": "TEXT", "clause_ids": (),
            "supplement_id": "registered-deadline-conversion",
        }) if binding.path == _MODE_PATH else binding for binding in mapping.bindings),
        "supplements": (supplement,),
    })
    start, end = len(source) - len(deadline), len(source)
    assert all(binding.origin.startswith("SOURCE") for binding in mapping.bindings
               if binding.path != _MODE_PATH)
    return draft, source, mapping, (start, end)


def test_exact_registered_deadline_override_is_visible_as_a_human_adjustment():
    draft, source, mapping, (start, end) = _deadline_mapping()
    supplement, = mapping.supplements
    binding, = (binding for binding in mapping.bindings if binding.path == _MODE_PATH)
    assert supplement.supplement_id == binding.supplement_id
    assert supplement.path == binding.path == _MODE_PATH
    assert supplement.value == binding.value == "PLAN_ACTIVE"
    assert supplement.candidate_content_hash == mapping.candidate_content_hash
    assert _DEADLINE in supplement.reason and "改为持续有效" in supplement.reason
    assert build_daily_review(draft, mapping, source).issues == ()

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    obligation, = (obligation for obligation in assessment.obligations
                   if obligation.start == start and obligation.end == end)
    assert obligation.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert obligation.paths == (_MODE_PATH,)
    assert assessment.automatic_fidelity_verified is False
    assert assessment.authority_granted is False


@pytest.mark.parametrize("mutation", [
    {"candidate_content_hash": "f" * 64},
    {"path": "ordinary_rules[1].validity.mode"},
    {"value": "DATE_RANGE"},
    {"supplement_id": "a-different-human-adjustment"},
])
def test_deadline_override_requires_the_same_rule_path_value_id_and_content(mutation):
    draft, source, mapping, (start, end) = _deadline_mapping(mutation=mutation)

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert assessment.issues
    assert not any(obligation.start == start and obligation.end == end
                   and obligation.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
                   for obligation in assessment.obligations)


@pytest.mark.parametrize("reason", [
    "引用原句：本规则有效至2026-10-01。 改为持续有效；重新审核并明确启用。",
    "引用原句：本规则有效至2026-09-30。 维持原文期限；重新审核并明确启用。",
])
def test_deadline_override_requires_the_exact_date_quote_and_explicit_conversion(reason):
    draft, source, mapping, (start, end) = _deadline_mapping(reason=reason)
    legacy = build_daily_review(draft, mapping, source)
    assert any(issue.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for issue in legacy.issues)

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert not any(obligation.start == start and obligation.end == end
                   and obligation.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
                   for obligation in assessment.obligations)


@pytest.mark.parametrize("tail", ["且等蓝灯亮起后再行动。", "且仅当换手率超过3%才允许买入。"])
def test_deadline_override_quoting_a_mixed_clause_does_not_waive_its_unknown_tail(tail):
    deadline = _DEADLINE.removesuffix("。") + tail
    draft, source, mapping, (_, end) = _deadline_mapping(deadline=deadline)
    # The old guard accepted this complete quote. Current coverage must still inspect the tail.
    assert build_daily_review(draft, mapping, source).issues == ()
    start = end - len(tail)

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert any(obligation.start < end and obligation.end > start
               and obligation.state in {"UNRESOLVED", "UNSUPPORTED", "CONFLICT"}
               for obligation in assessment.obligations)
    assert any(isinstance(issue.start, int) and issue.start < end and issue.end > start
               for issue in assessment.issues)
