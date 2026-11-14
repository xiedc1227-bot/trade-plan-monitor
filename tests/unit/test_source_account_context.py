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
_PREPARATION_FACTS = (
    "持仓账户现金余额5000元。", "持仓取得日期2026-08-19。", "持仓可卖100股。",
    "持仓账户快照2026-08-20T09:00:00+08:00。",
)


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


@pytest.mark.parametrize("text", _PREPARATION_FACTS)
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
def test_frozen_preparation_account_forms_keep_exact_context_without_authority(
    text, role,
):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(source, mapping, text,
        semantic_role=role, misclassification=_CONTEXT)
    type(mapping).model_validate_json(changed_mapping.model_dump_json())
    proof = assess_source_coverage(draft, changed_mapping, changed_source)
    assert proof.coverage_complete and proof.authority_granted is False
    row = proof.obligations[-1]
    assert (row.kind, row.scope, row.state, row.paths) == (
        "CONTEXT", "PLAN", "CONTEXT_VERIFIED", ())
    assert changed_source[row.start:row.end] == row.excerpt == text


@pytest.mark.parametrize("text", _PREPARATION_FACTS)
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
def test_background_account_label_retains_rejection_and_independent_fact_classification(text, role):
    draft, source, mapping = _baseline()
    control = assess_source_coverage(draft, mapping, source)
    assert control.coverage_complete and control.authority_granted is False
    changed_source, proposed = _append_as_context(source, mapping, text,
        semantic_role=role, misclassification=_CONTEXT | dict(disposition="BACKGROUND"))
    type(mapping).model_validate_json(proposed.model_dump_json())
    proof = assess_source_coverage(draft, proposed, changed_source)
    assert proof.status == "BLOCKED" and proof.authority_granted is False
    row = proof.obligations[-1]
    assert (row.kind, row.scope, row.state, row.paths) == (
        "CONTEXT", "PLAN", "CONTEXT_VERIFIED", ())
    assert changed_source[row.start:row.end] == row.excerpt == text


def _assert_preparation_text_blocked(proof, source, start, end):
    assert proof.status == "BLOCKED" and not proof.coverage_complete
    assert proof.authority_granted is False
    local = [issue for issue in proof.issues if issue.start is not None
             and start <= issue.start < end]
    assert local and all(0 <= issue.start < issue.end <= len(source) for issue in local)
    assert any(row.state == "UNRESOLVED" and start <= row.start < end
               and source[row.start:row.end] == row.excerpt for row in proof.obligations)


@pytest.mark.parametrize("text", [
    "持仓账户现金余额0元。", "持仓账户现金余额90071992547409.91元。",
    "持仓可卖0股。", "持仓可卖9007199254740991股。", "持仓取得日期2024-02-29。",
    "持仓账户快照2024-02-29T23:59:59+08:00。",
])
def test_preparation_fact_numeric_and_calendar_boundaries_remain_exact(text):
    assert positive_context(text) is not None


@pytest.mark.parametrize("text", [
    "持仓账户现金余额5000元且仅当换手率超过3%才允许买入。", "持仓可卖100股才允许买入。",
    "持仓取得日期2026-08-19后必须卖出。", "持仓账户快照2026-08-20T09:00:00+08:00后禁止买入。",
    *[prefix + fact for fact in _PREPARATION_FACTS for prefix in ("假设", "若", "并非")],
    *[fact[:-1] + "？" for fact in _PREPARATION_FACTS],
    "持仓账户现金余额-1元。", "持仓账户现金余额01元。", "持仓账户现金余额1.001元。",
    "持仓账户现金余额90071992547409.92元。", "持仓账户现金余额NaN元。",
    "持仓账户现金余额1美元。", "持仓可卖-1股。", "持仓可卖1.5股。", "持仓可卖01股。",
    "持仓可卖9007199254740992股。", "持仓取得日期2026-02-30。", "持仓取得日期2026-2-01。",
    "持仓账户快照2026-08-20T09:00:00。", "持仓账户快照2026-08-20T09:00:00+00:00。",
    "持仓账户快照2026-08-20T24:00:00+08:00。",
])
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
@pytest.mark.parametrize("disposition", ["BACKGROUND", "CONTEXT"])
def test_preparation_account_labels_cannot_hide_invalid_or_conditional_text(
    text, role, disposition,
):
    assert positive_context(text) is None
    draft, source, mapping = _baseline()
    control = assess_source_coverage(draft, mapping, source)
    assert control.coverage_complete and control.authority_granted is False
    changed_source, changed_mapping = _append_as_context(source, mapping, text,
        semantic_role=role, misclassification=_CONTEXT | dict(disposition=disposition))
    type(mapping).model_validate_json(changed_mapping.model_dump_json())
    proof = assess_source_coverage(draft, changed_mapping, changed_source)
    _assert_preparation_text_blocked(proof, changed_source, len(source) + 1, len(changed_source))


@pytest.mark.parametrize("text", _PREPARATION_FACTS)
def test_new_account_form_does_not_waive_a_following_mandatory_sentence(text):
    draft, source, mapping = _baseline()
    control = assess_source_coverage(draft, mapping, source)
    assert control.coverage_complete and control.authority_granted is False
    changed, proposed = _append_as_context(source, mapping, text,
        semantic_role="ACCOUNT", misclassification=_CONTEXT)
    changed, proposed = _append_as_context(changed, proposed,
        "仅当换手率超过3%才允许买入。", semantic_role="ACCOUNT", misclassification=_CONTEXT)
    type(mapping).model_validate_json(proposed.model_dump_json())
    proof = assess_source_coverage(draft, proposed, changed)
    assert proof.obligations[-2].state == "CONTEXT_VERIFIED"
    _assert_preparation_text_blocked(proof, changed, len(source) + 1 + len(text) + 1, len(changed))
