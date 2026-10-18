"""Fresh real responses retain business unknowns without internal mapping blockers."""

from datetime import date
from pathlib import Path

import pytest

from trade_plan_monitor.ai.preparation_wire import CompactInitialOutput, expand_compact_output
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.backtest.preparation_review import _source_account
from trade_plan_monitor.web.preparation_confirmations import confirmation_summary

FIXTURES = Path(__file__).parents[1] / "fixtures"
DATES = ("2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09")


@pytest.mark.parametrize("number", [1, 2, 3, 4])
@pytest.mark.parametrize("round_name", ["", "live-check-"])
def test_actual_responses_have_only_genuine_confirmation_questions(number, round_name):
    original = sorted((FIXTURES / "shengxin_sources").glob("*.txt"))[number - 1]
    source = PreparationSource(
        source_id=original.stem,
        text=original.read_text("utf-8-sig"),
        effective_trade_date=date.fromisoformat(DATES[number - 1]),
    )
    response = CompactInitialOutput.model_validate_json(
        (FIXTURES / f"ai/shengxin-source-resolution-{round_name}{number:02d}.json").read_text(
            "utf-8"
        )
    )
    candidate = expand_compact_output(response, source)
    review = candidate.review(source.text)
    assert not any(issue.code.startswith("DAILY_SOURCE") for issue in review.issues)
    expected_paths = {
        1: {"position.max_qty"},
        2: {
            "risk_branches.0.involves_core",
            "risk_branches.0.target_core_qty",
            "risk_branches.0.target_tactical_qty",
        },
        3: set(),
        4: set(),
    }
    assert {issue.path for issue in review.issues} == expected_paths[number]
    summary = confirmation_summary(
        source, candidate.draft, review.mapping, review.issues, candidate.opening_account
    )
    assert not summary.processing_issues
    assert "opening-cash" not in {q.question_id for q in summary.questions}
    assert "effective-date" not in {q.question_id for q in summary.questions}
    assert candidate.opening_account.inventory_quantity.value == 0
    assert candidate.opening_account.snapshot_at is None
    account = _source_account(candidate.opening_account, source)
    assert account.snapshot_at == source.execution_available_at
    assert account.cash.kind == "POSITION_LIMIT_ONLY"
    assert account.inventory_known and account.lots == ()


def test_genuine_scope_question_is_separate_from_model_mapping_errors():
    from tests.unit.test_plan_update_bindings import current_update

    source, output = current_update("最大持仓调整为500股，其余规则是否继续待确认。")
    summary = confirmation_summary(source, output.draft, None, (
        "UPDATE_SCOPE_UNRESOLVED", "UPDATE_RETENTION_EVIDENCE_REQUIRED",
        "UPDATE_OPERATION_EVIDENCE_REQUIRED: ordinary_rules.buy",
    ))
    assert summary.processing_issues
    assert [q.question_id for q in summary.questions].count("rule-inheritance") == 1
    assert "未提及的规则默认保留" in next(q.message for q in summary.questions
                                      if q.question_id == "rule-inheritance")


def test_old_scope_limitation_message_requests_new_extraction_not_manual_facts():
    from tests.unit.test_plan_update_bindings import current_update

    source, output = current_update("最大持仓保持300股。")
    summary = confirmation_summary(source, output.draft, None,
        ("UPDATE_PARTIAL_SCOPE_UNSUPPORTED: risk_branches.ORDINARY_TECHNICAL",))
    assert any("已支持按新旧持仓批次执行" in issue for issue in summary.processing_issues)
    assert not any("尚不能区分" in issue for issue in summary.processing_issues)
    assert not any(q.question_id in {"rule-inheritance", "exit-scope"} for q in summary.questions)
