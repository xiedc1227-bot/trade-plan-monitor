"""Current coverage must reject the independently frozen historical blind spot."""

import json
from pathlib import Path

import pytest
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline
from trade_plan_monitor.ai.source_coverage import assess_source_coverage

_COUNTEREXAMPLE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "pma_counterexample.json").read_text(
        encoding="utf-8"
    )
)


def assert_source_blocked(assessment, source, appended_start):
    """A semantic blocker must point to the unaccounted source, not hide the draft."""
    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    assert assessment.issues
    local = [issue for issue in assessment.issues if issue.start >= appended_start]
    assert local
    for issue in local:
        assert issue.code.startswith("SOURCE_")
        assert 0 <= issue.start < issue.end <= len(source)
        assert isinstance(issue.path, str) and issue.path


def test_complete_explicit_source_is_covered_without_granting_authority():
    draft, source, mapping = _baseline()
    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.obligations
    assert assessment.authority_granted is False


@pytest.mark.parametrize(
    "case", _COUNTEREXAMPLE["appended_requirements"], ids=lambda case: case["case_id"]
)
@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_context_label_cannot_discharge_an_appended_mandatory_buy_condition(case, role):
    draft, source, mapping = _baseline()
    original_candidate = draft.model_dump_json()
    original_mapping = mapping.model_dump_json()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, case["text"], semantic_role=role,
        misclassification=_COUNTEREXAMPLE["misclassification"],
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert_source_blocked(assessment, changed_source, len(source) + 1)
    assert changed_mapping.bindings == mapping.bindings
    assert draft.model_dump_json() == original_candidate
    assert mapping.model_dump_json() == original_mapping


@pytest.mark.parametrize("text", [
    "等那扇门打开后再行动。",
    "Proceed once the red gate has opened.",
    "Everything else depends on the blue lantern.",
])
def test_unrecognized_keyword_free_prose_does_not_become_verified_context(text):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role="COMMENTARY",
        misclassification=_COUNTEREXAMPLE["misclassification"],
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert_source_blocked(assessment, changed_source, len(source) + 1)
