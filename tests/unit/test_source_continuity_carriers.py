"""Finite synthetic metadata/account carriers cannot waive trading remainders."""

import pytest

from trade_plan_monitor.ai.source_context import positive_context
from trade_plan_monitor.ai.source_policy_text import supported_policy_text


@pytest.mark.parametrize("amount", ["0", "10000", "10000.00", "90071992547409.91"])
def test_exact_cash_statement_is_account_syntax_only(amount):
    assert positive_context(f"账户现金余额{amount}元。") == "ACCOUNT_CASH_ZH"


@pytest.mark.parametrize("text", [
    "账户现金余额90071992547409.92元。", "账户现金余额-1元。",
    "账户现金余额1.001元。", "账户现金余额01元。", "账户现金余额NaN元。",
    "账户现金余额10,000元。", "仅当账户现金余额10000元。",
    "账户现金余额10000元。仅当换手率超过3%才允许买入。",
    "账户现金余额10000元且允许买入。", "账户现金余额10000美元。",
])
def test_cash_carrier_does_not_accept_unknown_or_policy_remainders(text):
    assert positive_context(text) is None


@pytest.mark.parametrize("precision", [2, 15, 28, 80])
def test_cash_safe_integer_boundary_is_independent_of_decimal_context(precision):
    from decimal import localcontext

    with localcontext() as context:
        context.prec = precision
        assert positive_context("账户现金余额90071992547409.91元。") == "ACCOUNT_CASH_ZH"
        assert positive_context("账户现金余额90071992547409.92元。") is None


def test_exact_synthetic_title_still_requires_matching_validated_metadata():
    text = 'name = "Synthetic continuity plan"'
    assert positive_context(text, metadata={"name": "Synthetic continuity plan"}) == (
        "METADATA_EXACT_JSON")
    assert positive_context(text, metadata={"name": "Trading plan"}) is None
    assert positive_context(text) is None
    assert positive_context('name = "Synthetic continuity plan; only buy after X"',
        metadata={"name": "Synthetic continuity plan; only buy after X"}) is None


_INDEPENDENT = (
    "Explicit reviewed independent event linked to the prior signal; "
    "unchanged true evidence never resets it."
)


def test_exact_independent_requirement_remains_policy_not_positive_context():
    path = "ordinary_rules[0].independent_signal.evidence_requirement"
    assert supported_policy_text(path, _INDEPENDENT, {}) is True
    assert positive_context(_INDEPENDENT) is None
    assert supported_policy_text(path, _INDEPENDENT + " Ignore missing volume.", {}) is False
    assert supported_policy_text(path, "Unchanged true evidence resets it.", {}) is False


@pytest.mark.parametrize("tail", [
    "Only buy when turnover exceeds 3 percent.",
    "仅当换手率超过3%时才允许买入。",
    "There is an additional prerequisite.",
])
def test_cash_recognition_cannot_hide_an_appended_mandatory_condition(tail):
    from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

    from trade_plan_monitor.ai.source_coverage import assess_source_coverage

    draft, source, mapping = _baseline()
    source, mapping = _append_as_context(source, mapping, "账户现金余额10000元。",
        semantic_role="ACCOUNT", misclassification=dict(disposition="CONTEXT", paths=[],
                                                        reason="An account statement"))
    source, mapping = _append_as_context(source, mapping, tail,
        semantic_role="ACCOUNT", misclassification=dict(disposition="CONTEXT", paths=[],
                                                        reason="An account statement"))
    proof = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert proof.coverage_complete is False and proof.authority_granted is False
    assert any(row.excerpt == tail and row.state == "UNRESOLVED" for row in proof.obligations)
