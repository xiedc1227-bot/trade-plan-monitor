"""Freeze the historical blind spot; legacy success is never current authority."""

import hashlib
import json
from pathlib import Path

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.ai.daily_review import DailyClause, build_daily_review
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.p3_validation import P3PlanDraft

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "pma_counterexample.json"


@pytest.fixture
def frozen_counterexample():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _baseline():
    draft = P3PlanDraft.model_validate(p3_payload())
    source, mapping = source_mapping(draft)
    return draft, source, mapping


def _append_as_context(source, mapping, text, *, semantic_role, misclassification):
    changed_source = source + "\n" + text
    canonical = server_source_clauses(changed_source)
    assert canonical[:-1] == server_source_clauses(source)
    assert canonical[-1].excerpt == text
    value = canonical[-1].model_dump()
    value.update(
        disposition=misclassification["disposition"],
        semantic_role=semantic_role,
        paths=tuple(misclassification["paths"]),
        reason=misclassification["reason"],
    )
    changed = mapping.model_copy(
        update={"clauses": (*mapping.clauses, DailyClause.model_validate(value))}
    )
    return changed_source, changed


def test_fixture_declares_a_blind_spot_not_an_authorized_plan(frozen_counterexample):
    frozen = frozen_counterexample
    assert frozen["fixture_version"] == "pma-counterexample-v1"
    assert frozen["baseline_revision"] == "a5546ad"
    assert frozen["evidence_class"] == "SYNTHETIC_HISTORICAL_VALIDATION_BLINDNESS"
    assert frozen["activation_performed"] is False
    assert frozen["confers_authority"] is False
    expected = frozen["required_current_assessment"]
    assert expected["coverage_complete"] is False
    assert expected["can_confirm"] is False
    assert expected["can_activate"] is False
    assert [case["text"] for case in frozen["appended_requirements"]] == [
        "Only buy when turnover exceeds 3 percent.",
        "仅当换手率超过3%时才允许买入。",
    ]


def test_legacy_baseline_has_exact_frozen_content_and_counts(frozen_counterexample):
    draft, source, mapping = _baseline()
    expected = frozen_counterexample["baseline"]
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == expected["source_sha256_utf8"]
    assert daily_draft_content_sha256(draft) == expected["candidate_content_hash"]
    assert len(mapping.clauses) == expected["clause_count"] == 145
    assert len(mapping.bindings) == expected["binding_count"] == 128
    assert (
        len(build_daily_review(draft, mapping, source).issues)
        == expected["legacy_issue_count"] == 0
    )


@pytest.mark.parametrize("case_index", [0, 1], ids=["english", "chinese"])
@pytest.mark.parametrize("semantic_role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_legacy_context_role_accepts_a_missing_mandatory_prerequisite(
    frozen_counterexample, case_index, semantic_role,
):
    """This pins old verification only; new current coverage must block it."""
    draft, source, mapping = _baseline()
    before = build_daily_review(draft, mapping, source)
    candidate_bytes = draft.model_dump_json()
    extra = frozen_counterexample["appended_requirements"][case_index]["text"]
    changed_source, changed = _append_as_context(
        source, mapping, extra, semantic_role=semantic_role,
        misclassification=frozen_counterexample["misclassification"],
    )

    after = build_daily_review(draft, changed, changed_source)
    expected = frozen_counterexample["after_append"]
    assert len(changed.clauses) == expected["clause_count"] == 146
    assert len(changed.bindings) == expected["binding_count"] == 128
    assert changed.bindings == mapping.bindings
    assert changed.clauses[-1].paths == ()
    assert changed.clauses[-1].semantic_role == semantic_role
    assert changed.clauses[-1].disposition == "CONTEXT"
    assert len(after.issues) == expected["legacy_issue_count"] == 0
    assert after.content_hash == before.content_hash
    assert after.source_hash != before.source_hash
    assert after.evidence_hash != before.evidence_hash
    assert draft.model_dump_json() == candidate_bytes
    assert draft.to_executable() is not None  # Structural validity, never approval.


@pytest.mark.parametrize("case_index", [0, 1], ids=["english", "chinese"])
def test_legacy_context_without_the_semantic_role_shortcut_is_rejected(
    frozen_counterexample, case_index,
):
    draft, source, mapping = _baseline()
    extra = frozen_counterexample["appended_requirements"][case_index]["text"]
    changed_source, changed = _append_as_context(
        source, mapping, extra, semantic_role="AMBIGUOUS",
        misclassification=frozen_counterexample["misclassification"],
    )
    with pytest.raises(ValueError, match="context cannot hide a forward trading instruction"):
        build_daily_review(draft, changed, changed_source)
