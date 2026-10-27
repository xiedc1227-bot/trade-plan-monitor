"""Complete opening-account facts are context, never an inventory attestation."""

import pytest
from tests.unit.test_source_coverage import assert_source_blocked
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.source_context import positive_context
from trade_plan_monitor.ai.source_coverage import assess_source_coverage

_FACTS = (
    "实际持仓100股。", "CORE持仓100股。", "TACTICAL持仓0股。",
    "每股成本40.105元/股。", "账户快照2026-08-20T09:00:00+08:00。",
)
_CONTEXT = dict(disposition="CONTEXT", paths=[], reason="Untrusted proposed factual role")


@pytest.mark.parametrize("text", _FACTS)
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
def test_complete_actual_account_fact_is_context_under_each_untrusted_role(text, role):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(source, mapping, text,
        semantic_role=role, misclassification=_CONTEXT)

    proof = assess_source_coverage(draft, changed_mapping, changed_source)

    assert proof.coverage_complete and not proof.issues and proof.authority_granted is False
    row = proof.obligations[-1]
    assert (row.kind, row.scope, row.state, row.paths) == (
        "CONTEXT", "PLAN", "CONTEXT_VERIFIED", ())
    assert changed_source[row.start:row.end] == row.excerpt == text


@pytest.mark.parametrize("text", [
    "实际持仓100股且仅当换手率超过3%才允许买入。",
    "CORE持仓100股时必须先等蓝灯亮起。", "TACTICAL持仓0股才能买入。",
    "每股成本40.105元/股且跌破成本必须卖出。",
    "账户快照2026-08-20T09:00:00+08:00后禁止买入。",
    "假设实际持仓100股。", "CORE目标持仓100股。", "TACTICAL拟持仓100股。",
    "若实际持仓100股。", "实际持仓100股？", "每股成本不高于40.105元/股。",
    "每股成本40.105元/股/年。", "账户快照2026-02-30T09:00:00+08:00。",
    "账户快照2026-08-20T09:00:00。", "账户快照2026-08-20T09:00:00+00:00。",
    "账户快照2026-08-20T24:00:00+08:00。",
    "实际持仓-1股。", "实际持仓1.5股。", "实际持仓9007199254740992股。",
    "每股成本9007199254740992元/股。", "每股成本NaN元/股。",
])
def test_nonfactual_partial_invalid_and_forward_account_forms_stay_blocked(text):
    assert positive_context(text) is None
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(source, mapping, text,
        semantic_role="ACCOUNT", misclassification=_CONTEXT)

    proof = assess_source_coverage(draft, changed_mapping, changed_source)

    assert_source_blocked(proof, changed_source, len(source) + 1)


@pytest.mark.parametrize("text", [
    "实际持仓0股。", "实际持仓9007199254740991股。", "CORE持仓1股。",
    "每股成本0元/股。", "每股成本0.000000000000000001元/股。",
    "每股成本9007199254740991元/股。",
])
def test_context_recognition_preserves_exact_safe_nonnegative_facts_without_grid_or_rounding(text):
    assert positive_context(text) is not None


def test_a_registered_account_sentence_does_not_waive_an_unknown_following_condition():
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(source, mapping, "实际持仓100股。",
        semantic_role="ACCOUNT", misclassification=_CONTEXT)
    changed_source, changed_mapping = _append_as_context(changed_source, changed_mapping,
        "等那扇门打开后再行动。", semantic_role="ACCOUNT", misclassification=_CONTEXT)

    proof = assess_source_coverage(draft, changed_mapping, changed_source)

    assert not proof.coverage_complete and proof.authority_granted is False
    assert proof.obligations[-2].state == "CONTEXT_VERIFIED"
    assert proof.obligations[-1].state == "UNRESOLVED"
