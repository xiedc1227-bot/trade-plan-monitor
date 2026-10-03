"""Exact daily-only source exclusions retain mixed technical remainder evidence."""

import pytest
from tests.unit.test_daily_plan import synthetic_plan_payload
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.ai.daily_review import (
    DailyMapping,
    build_daily_review,
    daily_source_clauses,
)
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.daily_plan_validation import DailyPlanDraft


def draft():
    return DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))


def test_fundamental_only_source_has_visible_exact_background_without_review_issue():
    source = "必要公告核验完成、未发现使买入逻辑失效的重大利空。"
    mapping = reviewed_mapping(draft(), source).model_copy(
        update={"clauses": daily_source_clauses(source)}
    )
    result = build_daily_review(draft(), mapping, source)
    assert result.issues == ()
    clause = result.mapping.clauses[0]
    assert clause.disposition == "BACKGROUND"
    assert clause.paths == ()
    assert clause.exclusions[0].excerpt == source[:-1]
    assert clause.exclusions[0].source_hash == result.source_hash


def test_mixed_source_keeps_missing_technical_remainder():
    source = "收盘确认止跌并且必要公告核验完成、未发现使买入逻辑失效的重大利空。"
    clauses = daily_source_clauses(source)
    mapping = reviewed_mapping(draft(), source).model_copy(update={"clauses": clauses})
    result = build_daily_review(draft(), mapping, source)
    assert any(issue.code == "DAILY_SOURCE_CLAUSE_REQUIRED" for issue in result.issues)
    assert clauses[0].remainders[0].excerpt == "收盘确认止跌并且"
    raw = mapping.model_dump(mode="json")
    raw["clauses"][0].update(disposition="BACKGROUND", paths=[])
    with pytest.raises(ValueError, match="remainder"):
        build_daily_review(draft(), DailyMapping.model_validate(raw), source)


def test_arbitrary_background_or_forged_span_cannot_hide_technical_policy():
    source = "收盘跌破38.18元停止加仓。"
    raw = reviewed_mapping(draft(), source).model_dump(mode="json")
    raw["clauses"][0].update(
        disposition="BACKGROUND",
        paths=[],
        reason="Fundamentals reviewed at plan generation and excluded from monitoring.",
    )
    with pytest.raises(ValueError, match="exclusion"):
        build_daily_review(draft(), DailyMapping.model_validate(raw), source)
    source = "必要公告核验完成、未发现使买入逻辑失效的重大利空。"
    raw = (
        reviewed_mapping(draft(), source)
        .model_copy(update={"clauses": daily_source_clauses(source)})
        .model_dump(mode="json")
    )
    raw["clauses"][0]["exclusions"][0]["end"] -= 1
    with pytest.raises(ValueError, match="exclusion"):
        build_daily_review(draft(), DailyMapping.model_validate(raw), source)


def test_excluded_source_cannot_be_relabelled_as_technical_policy():
    source = "必要公告核验完成、未发现使买入逻辑失效的重大利空。"
    raw = reviewed_mapping(draft(), source).model_dump(mode="json")
    raw["clauses"][0].update(paths=["ordinary_rules[0].technical.evidence_requirement"])
    with pytest.raises(ValueError, match="exclusion|excluded"):
        build_daily_review(draft(), DailyMapping.model_validate(raw), source)


def test_v7_review_normalizes_exact_background_and_rejects_ai_human_selection():
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.ai.plan_extraction import (
        CurrentPlanExtractionOutput as DailyExtractionOutput,
    )
    from trade_plan_monitor.ai.review import server_source_clauses
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    source = "Announcement verification is outside daily monitoring."
    clauses = [
        dict(c.model_dump(), disposition="UNRESOLVED", paths=(), reason="Unparsed AI text")
        for c in server_source_clauses(source)
    ]
    output = DailyExtractionOutput(
        draft=UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(unified_payload())),
        clauses=clauses,
        bindings=(),
    )
    review = output.review(source)
    assert review.mapping.clauses[0].disposition == "BACKGROUND"
    assert review.mapping.clauses[0].exclusions[0].excerpt == source[:-1]
    assert not any(i.code == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in review.issues)
    raw = output.model_dump(mode="json")
    raw["clauses"] = [c.model_dump(mode="json") for c in review.mapping.clauses]
    raw["clauses"][0]["exclusions"][0]["origin"] = "HUMAN_SCOPE_SELECTION"
    with pytest.raises(ValueError, match="AI cannot create human"):
        DailyExtractionOutput.model_validate(raw)
