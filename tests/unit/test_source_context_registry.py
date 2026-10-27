"""Only complete finite non-policy sentences may leave current coverage."""

from copy import deepcopy

import pytest

from trade_plan_monitor.ai.source_context import positive_context


@pytest.mark.parametrize("text,expected", [
    ("# Trade plan", "TITLE_EN"),
    ("# 交易计划", "TITLE_ZH"),
    ("历史记录：2026-10-01买入100股。", "HISTORICAL_TRADE_ZH"),
    ("历史记录：2024-02-29卖出17股。", "HISTORICAL_TRADE_ZH"),
    ("Historical record: bought 100 shares on 2026-10-01.", "HISTORICAL_TRADE_EN"),
    ("Historical record: sold 17 shares on 2024-02-29.", "HISTORICAL_TRADE_EN"),
    ("历史记录：2026-10-01买入0股。", "HISTORICAL_TRADE_ZH"),
    ("Historical record: sold 0 shares on 2026-10-01.", "HISTORICAL_TRADE_EN"),
    ("历史记录：2026-10-01买入9007199254740991股。", "HISTORICAL_TRADE_ZH"),
    ("Historical record: sold 9007199254740991 shares on 2026-10-01.",
     "HISTORICAL_TRADE_EN"),
    ("账户记录：当前持仓0股。", "ACCOUNT_ZERO_ZH"),
    ("当前账户持仓0股。", "ACCOUNT_ZERO_ZH"),
    ("账户持仓：0股。", "ACCOUNT_ZERO_ZH"),
    ("你没有持仓。", "ACCOUNT_ZERO_ZH"),
    ("你目前0股。", "ACCOUNT_ZERO_ZH"),
    ("你当前0股。", "ACCOUNT_ZERO_ZH"),
    ("Account record: current holdings are 0 shares.", "ACCOUNT_ZERO_EN"),
    ("Current account holdings: 0 shares.", "ACCOUNT_ZERO_EN"),
    ("Account holdings: 0 shares.", "ACCOUNT_ZERO_EN"),
    ("You currently hold 0 shares.", "ACCOUNT_ZERO_EN"),
])
def test_registered_complete_nonpolicy_text_has_an_explicit_proof_id(text, expected):
    assert positive_context(text) == expected


@pytest.mark.parametrize("text", [
    "# Trade plan only buy when turnover exceeds 3 percent",
    "# 交易计划仅当换手率超过3%才允许买入",
    "# Trade plan\nOnly buy when turnover exceeds 3 percent.",
    "历史记录：2026-10-01买入100股且今后仅当换手率超过3%才允许买入。",
    "Historical record: bought 100 shares on 2026-10-01 "
    "and now only buy when turnover exceeds 3 percent.",
    "历史记录：2026-10-01买入100股。仅当换手率超过3%才允许买入。",
    "Historical record: bought 100 shares on 2026-10-01. Only buy above 10.",
    "账户记录：当前持仓0股。若收盘高于10元才买入。",
    "Account holdings: 0 shares. Buy only after the close.",
    "保持0股。",
    "Do not buy.",
    "Proceed once the red gate has opened.",
    "等那扇门打开后再行动。",
    "Everything else depends on the blue lantern.",
    "plain background commentary",
    "# trade plan",
    "## Trade plan",
    "历史记录：2026-10-01考虑买入100股。",
    "Historical record: might buy 100 shares on 2026-10-01.",
])
def test_prefix_labels_unknown_prose_and_forward_remainders_are_not_context(text):
    assert positive_context(text) is None


@pytest.mark.parametrize("text", [
    "历史记录：2026-02-29买入100股。",
    "历史记录：2026-13-01买入100股。",
    "Historical record: bought 100 shares on 2026-02-29.",
    "Historical record: bought 100 shares on 2026-10-32.",
    "历史记录：2026-10-01买入-100股。",
    "历史记录：2026-10-01买入01股。",
    "历史记录：2026-10-01买入1.5股。",
    "历史记录：2026-10-01买入9007199254740992股。",
    "Historical record: bought -100 shares on 2026-10-01.",
    "Historical record: bought 01 shares on 2026-10-01.",
    "Historical record: bought NaN shares on 2026-10-01.",
    "Historical record: bought 9007199254740992 shares on 2026-10-01.",
])
def test_historical_dates_and_quantities_must_be_legal_exact_values(text):
    assert positive_context(text) is None


@pytest.fixture
def metadata():
    return {
        "plan_id": "observation-1",
        "version": 2,
        "name": "观察计划",
        "metadata": {"report_at": None, "reference_price_fen": 1234},
        "symbol": "601021.SH",
        "position": {"max_qty": 300},
    }


@pytest.mark.parametrize("text", [
    'plan_id = "observation-1"',
    'plan_id="observation-1"',
    "version = 2",
    'name = "观察计划"',
    "metadata.report_at = null",
    "metadata.reference_price_fen = 1234",
])
def test_complete_identity_or_existing_metadata_must_equal_the_exact_candidate(text, metadata):
    before = deepcopy(metadata)
    assert positive_context(text, metadata=metadata) == "METADATA_EXACT_JSON"
    assert metadata == before
    assert positive_context(text) is None


@pytest.mark.parametrize("text", [
    'plan_id = "another-plan"',
    "version = 3",
    "version = 2.0",
    "version = true",
    'name = "another name"',
    'name = "\\u89c2\\u5bdf\\u8ba1\\u5212"',
    "metadata.unknown = null",
    "metadata.report_at = false",
    "metadata.reference_price_fen = 12.34",
    "metadata.reference_price_fen = 1234 only buy after the close",
    'name = "观察计划"\nOnly buy above 10.',
    "metadata = {\"reference_price_fen\":1234,\"report_at\":null}",
    "position.max_qty = 300",
    'symbol = "601021.SH"',
    "schema_version = 9",
])
def test_metadata_does_not_waive_mismatches_unknown_paths_or_policy_fields(text, metadata):
    assert positive_context(text, metadata=metadata) is None


def test_outer_whitespace_does_not_hide_an_additional_statement():
    assert positive_context(" \t# Trade plan\r\n") == "TITLE_EN"
    assert positive_context(" \t# Trade plan\nOnly buy above 10.\r\n") is None


@pytest.mark.parametrize("text", [None, 3, True, (), {}])
def test_nontext_input_has_no_positive_context_proof(text):
    assert positive_context(text) is None
