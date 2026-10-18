"""Prior recovery is separate from a still-unquantified later retest."""

from datetime import date
from decimal import Decimal

from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_preparation_source_resolution import recorded_candidate

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.unified_plan_models import condition_leaves


def condition(since="2026-06-01"):
    from trade_plan_monitor.domain.unified_plan_models import DailyPriorClose

    return DailyPriorClose.model_validate_json(
        '{"type":"DAILY_PRIOR_CLOSE","since_date":"' + since + '",'
        '"price_fen":3901,"comparator":"GT"}'
    )


def test_recovery_requires_an_earlier_completed_close_not_current_or_intraday_high():
    series, _ = synthetic_series(3)
    # Prior closes 3900/3901 do not exceed 3901; today's close 3902 cannot authorize today's retest.
    result = evaluate_unified_condition(condition(), series)
    assert result.outcome == "UNSATISFIED"
    assert result.reason == "PRIOR_CLOSE_NOT_SATISFIED"
    assert result.operands == ("3900", "3901", "3901")
    assert series.bars[-1].bar_id not in result.bar_ids


def test_prior_recovery_is_not_replaced_by_a_new_current_close_requirement():
    series, _ = synthetic_series(4)
    bars = (*series.bars[:-1], series.bars[-1].model_copy(update={"close": Decimal("3899")}))
    result = evaluate_unified_condition(condition(), series.model_copy(update={"bars": bars}))
    assert result.outcome == "SATISFIED"
    assert result.session_dates == (date(2026, 6, 3),)


def test_unrelated_old_recovery_does_not_satisfy_new_source_window():
    series, _ = synthetic_series(4)
    assert evaluate_unified_condition(condition("2026-06-04"), series).outcome == "UNSATISFIED"
    assert evaluate_unified_condition(condition("2026-05-01"), series).outcome == "MISSING_INPUT"
    assert evaluate_unified_condition(condition(), None).outcome == "MISSING_INPUT"


def test_actual_third_source_splits_known_recovery_from_unknown_retest():
    source, candidate = recorded_candidate(3)
    leaves = condition_leaves(candidate.draft.ordinary_rules[0].condition)
    gate = next((c for c in leaves if c.type == "DAILY_PRIOR_CLOSE"), None)
    assert gate is not None and gate.price_fen == 2599
    assert gate.since_date == source.effective_trade_date
    assert any(c.type == "REVIEWED_FACT" and "回踩" in c.evidence_requirement for c in leaves)
    assert not candidate.review(source.text).issues


def test_recovery_window_is_not_inferred_when_source_does_not_say_unrecovered():
    from trade_plan_monitor.ai.source_resolution import normalize_prior_recovery

    source, candidate = recorded_candidate(3)
    data = candidate.draft.model_dump(mode="json")
    root = data["ordinary_rules"][0]["condition"]
    root["conditions"] = [c for c in root["conditions"] if c["type"] != "DAILY_PRIOR_CLOSE"]
    source = source.model_copy(
        update={"text": "如果完整日K重新收回25.99以上，之后回踩并重新收起。"}
    )
    normalize_prior_recovery(data, source)
    assert not any(c["type"] == "DAILY_PRIOR_CLOSE" for c in root["conditions"])


def test_known_recovery_is_shown_as_automatic_fact_not_question_context():
    from trade_plan_monitor.web.preparation_confirmations import confirmation_summary

    source, candidate = recorded_candidate(3)
    review = candidate.review(source.text)
    summary = confirmation_summary(source, candidate.draft, review.mapping, review.issues)
    assert any("先行收盘条件已自动提取" in f and "25.99" in f for f in summary.automatic_facts)
    question = next(q for q in summary.questions if q.question_id == "technical-criteria")
    assert any("回踩" in text for text in question.excerpts)
    assert all("原文约束：" not in text for text in question.excerpts)
    assert not summary.processing_issues
