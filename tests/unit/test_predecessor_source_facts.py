"""Literal predecessor evidence resolves facts, never guesses from later plans."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from trade_plan_monitor.ai.preparation_wire import CompactInitialOutput, expand_compact_output
from trade_plan_monitor.ai.source_resolution import interpretation_matches, normalize_source_draft
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.web.preparation_confirmations import confirmation_summary


def draft():
    return dict(
        position={"max_qty": None},
        levels={"risk_line_fen": 2599},
        ordinary_rules=[],
        risk_branches=[
            dict(
                kind="ORDINARY_TECHNICAL",
                condition=None,
                involves_core=None,
                target_core_qty=None,
                target_tactical_qty=None,
            )
        ],
    )


def normalize(text):
    return normalize_source_draft(
        draft(), SimpleNamespace(text=text, effective_trade_date=date(2026, 9, 28))
    )


def test_literal_maximum_plan_position_label():
    assert normalize("最大计划持仓：300股。")["position"]["max_qty"] == 300


EXIT = (
    "首次收盘跌破25.99但只是普通破位：下一交易日再观察一次收盘；"
    "仍未收回，则确认全部退出，再下一交易日执行。"
)


def test_literal_full_exit_resolves_targets_without_fixed_historical_quantity():
    branch = normalize(EXIT)["risk_branches"][0]
    assert (branch["involves_core"], branch["target_core_qty"], branch["target_tactical_qty"]) == (
        True,
        0,
        0,
    )
    for field, value in [
        ("involves_core", True),
        ("target_core_qty", 0),
        ("target_tactical_qty", 0),
    ]:
        assert interpretation_matches("risk_branches[0]." + field, value, "则确认全部退出，", None)


@pytest.mark.parametrize(
    "text",
    [
        "首次收盘跌破25.99但只是普通破位：仍未收回，则确认普通风险退出。",
        EXIT.replace("25.99", "26.40"),
        EXIT.replace("确认全部退出", "不确认全部退出"),
        EXIT.replace("确认全部退出", "是否确认全部退出"),
        EXIT.replace("普通破位", "严重破位"),
    ],
)
def test_missing_conflicting_or_different_branch_is_not_inferred(text):
    branches = normalize(text)["risk_branches"]
    if not branches:
        return
    branch = branches[0]
    assert branch["involves_core"] is None
    assert branch["target_core_qty"] is None
    assert branch["target_tactical_qty"] is None


def test_one_lot_is_not_a_maximum():
    assert normalize("下一交易日才考虑第一笔100股。")["position"]["max_qty"] is None


def test_risk_priority_is_a_product_constant_not_a_user_parameter():
    branch = normalize(EXIT)["risk_branches"][0]
    assert branch["priority"] == 3


def test_actual_second_response_with_verified_previous_rule_needs_no_exit_scope_input():
    fixtures = Path(__file__).parents[1] / "fixtures"
    source = PreparationSource(
        source_id="actual-second",
        effective_trade_date=date(2026, 9, 28),
        text=(fixtures / "shengxin_sources/02-20260928-092555.txt").read_text("utf-8-sig")
        + "\n\n"
        + EXIT,
    )
    wire = CompactInitialOutput.model_validate_json(
        (fixtures / "ai/shengxin-source-resolution-live-check-02.json").read_text("utf-8-sig")
    )
    candidate = expand_compact_output(wire, source)
    review = candidate.review(source.text)
    assert not any(i.code.startswith("DAILY_SOURCE") for i in review.issues)
    assert {i.path for i in review.issues} == {"risk_branches.0.suspension_confirmation_policy"}
    summary = confirmation_summary(
        source, candidate.draft, review.mapping, review.issues, candidate.opening_account
    )
    assert not summary.processing_issues
    assert "exit-scope" not in {q.question_id for q in summary.questions}
    assert "risk-suspension" in {q.question_id for q in summary.questions}
