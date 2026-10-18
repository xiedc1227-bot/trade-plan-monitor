"""Source facts must survive imperfect model output without invented strategy rules."""

import json
from datetime import date
from pathlib import Path

import pytest

from trade_plan_monitor.ai.daily_review import daily_source_clauses
from trade_plan_monitor.ai.loop_plan_extraction import validate_opening_evidence
from trade_plan_monitor.ai.preparation_wire import CompactInitialOutput, expand_compact_output
from trade_plan_monitor.backtest.preparation_models import PreparationSource

FIXTURES = Path(__file__).parents[1] / "fixtures"
EFFECTIVE_DATES = (date(2026, 9, 24), date(2026, 9, 28), date(2026, 9, 30), date(2026, 10, 9))


def recorded_candidate(number):
    original = sorted((FIXTURES / "shengxin_sources").glob("*.txt"))[number - 1]
    source = PreparationSource(
        source_id=original.stem,
        text=original.read_text(encoding="utf-8-sig"),
        effective_trade_date=EFFECTIVE_DATES[number - 1],
    )
    output = CompactInitialOutput.model_validate_json(
        (FIXTURES / f"ai/shengxin-live-wire-final-{number:02d}.json").read_text(encoding="utf-8")
    )
    return source, expand_compact_output(output, source)


def test_explicit_zero_holdings_are_recovered_when_the_model_omits_them():
    source, candidate = recorded_candidate(1)

    fact = candidate.opening_account.inventory_quantity
    assert fact is not None, "The source states zero holdings; omission by AI is not missing input."
    assert fact.value == 0
    assert source.text[fact.start:fact.end] == fact.excerpt
    validate_opening_evidence(candidate.opening_account, source.text)
    assert candidate.opening_account.lots == ()
    assert candidate.opening_account.cash_fen is None, "Do not infer unrelated account facts."


@pytest.mark.parametrize("number", [2, 3, 4])
def test_explicitly_inactive_low_buy_zones_do_not_request_numeric_boundaries(number):
    from tests.unit.test_daily_conditions import synthetic_series

    from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition

    source, candidate = recorded_candidate(number)
    review = candidate.review(source.text)

    boundary_issues = [
        issue for issue in review.issues
        if issue.path.startswith("levels.low_buy.")
    ]
    assert not boundary_issues, "A deliberately inactive zone has no numeric boundaries to supply."
    series, _ = synthetic_series(count=1)
    for rule in candidate.draft.ordinary_rules:
        assert evaluate_unified_condition(rule.condition, series, facts=()).outcome != "SATISFIED"


@pytest.mark.parametrize("number", [1, 2, 3, 4])
def test_plain_section_headings_are_retained_without_becoming_confirmation_requests(number):
    source, candidate = recorded_candidate(number)
    review = candidate.review(source.text)
    heading = next(
        clause for clause in review.mapping.clauses
        if clause.excerpt.strip() in {"## 1. 当前结论与行情摘要", "## 1. 23日行情与结论"}
    )

    assert source.text[heading.start:heading.end] == heading.excerpt
    assert not any(issue.path == "source." + heading.clause_id for issue in review.issues), (
        "A plain structural heading must not require the user to confirm a trading condition."
    )


def test_explicit_repair_threshold_is_not_represented_as_a_new_position_stop():
    source, candidate = recorded_candidate(4)

    assert "而不是给新仓位直接设止损" in source.text
    assert candidate.draft.levels.risk_line_fen is None, (
        "The original explicitly distinguishes 25.99 repair from a new-position stop."
    )
    assert candidate.draft.levels.risk_comparison is None
    assert any("25.99" in clause.excerpt for clause in candidate.clauses), (
        "Removing a false stop must retain the actual repair condition for review."
    )


def source_candidate(
    text, *, binding_path=None, quantity=None, pressure_price=None, inventory_fact=None,
):
    """A model response with no account facts and optional proposed source binding."""
    source = PreparationSource(source_id="negative-source", text=text)
    payload = json.loads((FIXTURES / "ai/shengxin-live-wire-final-01.json").read_text("utf-8"))
    clauses = daily_source_clauses(text)
    payload["clauses"] = [
        {"clause_id": clause.clause_id,
         "disposition": "POLICY" if binding_path else "BACKGROUND",
         "reason": "Proposed source interpretation requiring ordinary overall review."}
        for clause in clauses
    ]
    payload["bindings"] = [] if not binding_path else [
        {"path": binding_path, "clause_ids": [clauses[0].clause_id]}
    ]
    payload["warnings"] = []
    payload["opening_account"]["inventory_quantity"] = inventory_fact
    if quantity is not None:
        payload["draft"]["ordinary_rules"][0]["quantity"] = quantity
    if pressure_price is not None:
        payload["draft"]["levels"]["pressure"]["low_fen"] = pressure_price
    candidate = expand_compact_output(
        CompactInitialOutput.model_validate_json(json.dumps(payload)), source,
    )
    return source, candidate


@pytest.mark.parametrize("text", [
    "假设你目前0股持仓。",
    "如果你目前0股持仓，继续等待。",
    "目标持仓0股。",
    "预计你本身已经0股。",
    "实际买入0股，实际卖出0股。",
])
def test_hypothetical_or_transaction_zero_does_not_initialize_holdings(text):
    _, candidate = source_candidate(text)
    assert candidate.opening_account.inventory_quantity is None


@pytest.mark.parametrize("positive", [
    "当前持仓100股。",
    "当前持仓 100 股。",
    "当前库存100股。",
    "Current holdings 100 shares.",
])
def test_competing_positive_holdings_prevent_automatic_zero_recovery(positive):
    _, candidate = source_candidate("你目前0股持仓。" + positive)
    assert candidate.opening_account.inventory_quantity is None, (
        "Conflicting account assertions require review rather than selecting the zero value."
    )


@pytest.mark.parametrize("text", [
    "如果收盘站上26.70，买入100股。",
    "买入200股。",
    "卖出200股。",
    "清仓。",
    "收盘高于26.70时加仓200股。",
    "## 如果收盘高于26.70则买入100股",
])
def test_background_label_cannot_hide_a_trading_instruction(text):
    source, candidate = source_candidate(text)
    review = candidate.review(source.text)
    actionable = [clause for clause in review.mapping.clauses
                  if any(word in clause.excerpt for word in ("买入", "卖出", "清仓", "加仓"))]
    assert actionable
    assert all(clause.disposition != "CONTEXT" for clause in actionable)


@pytest.mark.parametrize("path,text,quantity,pressure_price", [
    ("ordinary_rules[0].quantity", "首次买入100股。", 200, None),
    ("ordinary_rules[0].quantity", "首次买入100股，成交量200万股。", 200, None),
    ("levels.pressure.low_fen", "压力区为27.30至27.70元。", None, 12345),
])
def test_interpreted_evidence_cannot_supply_an_unsupported_quantity_or_price(
    path, text, quantity, pressure_price,
):
    source, candidate = source_candidate(
        text, binding_path=path, quantity=quantity, pressure_price=pressure_price,
    )
    review = candidate.review(source.text)
    assert not any(binding.path == path for binding in review.mapping.bindings)
    assert any(issue.path == path and issue.code == "DAILY_SOURCE_BINDING_REQUIRED"
               for issue in review.issues)


def test_valid_zero_evidence_does_not_override_a_conflicting_positive_holding():
    text = "你目前0股持仓。当前持仓100股。"
    _, candidate = source_candidate(text, inventory_fact={
        "value": 0, "start": 0, "end": 8, "excerpt": text[:8],
    })
    assert candidate.opening_account.inventory_quantity is None, (
        "Even an exact zero span cannot resolve a contradictory account assertion."
    )


def test_bad_zero_span_observed_in_live_response_is_relocated_to_real_source_evidence():
    original = sorted((FIXTURES / "shengxin_sources").glob("*.txt"))[0]
    text = original.read_text(encoding="utf-8-sig")
    # Exact malformed fact returned in source-confirmations-final/http-response-01.json.
    source, candidate = source_candidate(text, inventory_fact={
        "value": 0, "start": 20, "end": 25, "excerpt": "继续0股；",
    })
    fact = candidate.opening_account.inventory_quantity
    assert fact is not None and fact.value == 0
    assert text[fact.start:fact.end] == fact.excerpt
    validate_opening_evidence(candidate.opening_account, source.text)


def test_invalid_ai_zero_is_not_relocated_when_the_original_has_no_account_fact():
    _, candidate = source_candidate("第一笔买入100股。", inventory_fact={
        "value": 0, "start": 0, "end": 5, "excerpt": "持仓0股。",
    })
    assert candidate.opening_account.inventory_quantity is None


@pytest.mark.parametrize("text", [
    "量能不能异常放大。",
    "## 清仓",
    "最好选择流动性好的时段，但如果跌破25.99就卖出200股。",
])
def test_background_label_cannot_hide_restrictions_or_actions_inside_preferences(text):
    source, candidate = source_candidate(text)
    review = candidate.review(source.text)
    important = [clause for clause in review.mapping.clauses
                 if any(marker in clause.excerpt for marker in ("不能", "清仓", "如果", "卖出"))]
    assert important
    assert all(clause.disposition != "CONTEXT" for clause in important)


def test_missing_ai_position_limit_is_not_reported_as_missing_from_original():
    from trade_plan_monitor.web.preparation_confirmations import confirmation_summary

    source, candidate = source_candidate("你目前0股持仓，最大计划300股。")
    review = candidate.review(source.text)
    result = confirmation_summary(
        source, candidate.draft, review.mapping, review.issues, candidate.opening_account,
    )
    assert not any(question.question_id == "position-limit"
                   and question.category == "SOURCE_MISSING" for question in result.questions)
    # Recovery or a software diagnostic is appropriate; a new user-supplied limit is not.
    assert candidate.draft.position.max_qty == 300 or result.processing_issues


@pytest.mark.parametrize("number", [1, 3, 4])
def test_source_interpretation_does_not_self_confirm_unresolved_market_conditions(number):
    from tests.unit.test_daily_conditions import synthetic_series

    from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
    from trade_plan_monitor.domain.unified_plan_models import condition_leaves

    _, candidate = recorded_candidate(number)
    series, _ = synthetic_series(count=1)
    checked = 0
    for rule in candidate.draft.ordinary_rules:
        leaves = [leaf for leaf in condition_leaves(rule.condition) if leaf.type == "REVIEWED_FACT"]
        if not leaves:
            continue
        checked += 1
        unverified = tuple({"id": f"unverified-{index}", "kind": leaf.fact_kind,
                            "verified": False, "trade_date": str(series.bars[-1].trade_date)}
                           for index, leaf in enumerate(leaves))
        for facts in ((), unverified):
            evidence = evaluate_unified_condition(rule.condition, series, facts=facts)
            assert evidence.outcome != "SATISFIED", (
                "Interpreting the source must never attest that a future vague condition is true."
            )
    assert checked, "The real sources retain qualitative conditions that need separate evidence."


@pytest.mark.parametrize("text", [
    "只有成交量正常才考虑第一笔100股。跌破24元必须卖出200股。",
    "再重新设置低吸区并评估第一笔100股。跌破24元必须卖出200股。",
])
def test_unmapped_sell_action_is_not_absorbed_into_buy_conditions_or_an_empty_order_list(text):
    source, candidate = source_candidate(text)
    review = candidate.review(source.text)
    sell_clause = next(clause for clause in review.mapping.clauses if "卖出200股" in clause.excerpt)
    if any(rule.side == "SELL" and rule.quantity == 200 for rule in candidate.draft.ordinary_rules):
        return
    assert any(issue.path == "source." + sell_clause.clause_id for issue in review.issues), (
        "A separate sell instruction must remain unresolved when no sell rule represents it; "
        "copying it into a BUY predicate or binding it to an empty collection is not resolution."
    )
