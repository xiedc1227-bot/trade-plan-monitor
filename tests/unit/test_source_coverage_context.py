"""Positive non-policy spans are finite and never exempt a forward remainder."""

import json

import pytest
from tests.unit.test_source_coverage import assert_source_blocked
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline
from trade_plan_monitor.ai.source_coverage import assess_source_coverage

_CONTEXT = {
    "disposition": "CONTEXT",
    "paths": [],
    "reason": "The role and this reason are untrusted proposals.",
}


@pytest.mark.parametrize("text", [
    "历史记录：2026-10-01买入100股。",
    "Historical record: bought 100 shares on 2026-10-01.",
])
@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_complete_explicit_historical_record_is_positive_context(text, role):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role=role, misclassification=_CONTEXT,
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False


@pytest.mark.parametrize("identity", ["heading-zh", "heading-en", "plan_id", "version", "name"])
def test_exact_heading_or_identity_metadata_is_not_a_trading_requirement(identity):
    draft, source, mapping = _baseline()
    if identity == "heading-zh":
        text = "# 交易计划"
    elif identity == "heading-en":
        text = "# Trade plan"
    else:
        text = f"{identity} = {json.dumps(getattr(draft, identity), ensure_ascii=False)}"
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role="COMMENTARY", misclassification=_CONTEXT,
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False


@pytest.mark.parametrize("text", [
    "历史记录：2026-10-01买入100股且今后仅当换手率超过3%才允许买入。",
    "Historical record: bought 100 shares on 2026-10-01 "
    "and now only buy when turnover exceeds 3 percent.",
])
@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_historical_prefix_does_not_exempt_a_same_clause_forward_requirement(text, role):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role=role, misclassification=_CONTEXT,
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert_source_blocked(assessment, changed_source, len(source) + 1)


@pytest.mark.parametrize("text", [
    "# 交易计划仅当换手率超过3%才允许买入",
    "# Trade plan only buy when turnover exceeds 3 percent",
])
def test_heading_markup_does_not_exempt_a_forward_requirement(text):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role="COMMENTARY", misclassification=_CONTEXT,
    )

    assessment = assess_source_coverage(draft, changed_mapping, changed_source)

    assert_source_blocked(assessment, changed_source, len(source) + 1)
