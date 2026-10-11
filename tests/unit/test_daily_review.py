"""Source fidelity and current-candidate review, with conspicuous synthetic supplements."""

import pytest
from tests.unit.test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review, semantic_values
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyPlanDraft,
    daily_draft_content_sha256,
)


def reviewed_mapping(draft, source="Synthetic human-reviewed supplements for this fixture."):
    from trade_plan_monitor.ai.review import server_source_clauses

    digest = daily_draft_content_sha256(draft)
    return DailyMapping.model_validate(
        {
            "mapping_version": "daily-mapping-v1",
            "candidate_content_hash": digest,
            "clauses": [
                {
                    "clause_id": c.clause_id,
                    "start": c.start,
                    "end": c.end,
                    "excerpt": c.excerpt,
                    "disposition": "POLICY",
                    "paths": list(semantic_values(draft)),
                    "reason": (
                        "Synthetic human-reviewed policy supplements, independently reviewed."
                    ),
                }
                for c in server_source_clauses(source)
            ],
            "bindings": [
                {
                    "path": path,
                    "value": value,
                    "origin": "HUMAN_SUPPLEMENT",
                    "unit": "JSON",
                    "clause_ids": [],
                    "supplement_id": "supplement-" + str(i),
                }
                for i, (path, value) in enumerate(semantic_values(draft).items())
            ],
            "supplements": [
                {
                    "supplement_id": "supplement-" + str(i),
                    "path": path,
                    "value": value,
                    "candidate_content_hash": digest,
                    "reason": (
                        "Synthetic human-reviewed supplements; proposed policy, "
                        "not registered inventory."
                    ),
                }
                for i, (path, value) in enumerate(semantic_values(draft).items())
            ],
        }
    )


def test_complete_review_has_no_issues_and_semantic_edit_invalidates_supplements():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    mapping = reviewed_mapping(draft)
    assert (
        build_daily_review(
            draft, mapping, "Synthetic human-reviewed supplements for this fixture."
        ).issues
        == ()
    )
    raw = draft.model_dump(mode="json")
    raw["levels"]["low_buy"]["include_low"] = False
    with pytest.raises(ValueError, match="candidate"):
        build_daily_review(
            DailyPlanDraft.model_validate(raw),
            mapping,
            "Synthetic human-reviewed supplements for this fixture.",
        )


def test_partial_missing_condition_cannot_be_acknowledged_away():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    raw = draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["technical"] = None
    partial = DailyPlanDraft.model_validate(raw)
    result = build_daily_review(
        partial, reviewed_mapping(partial), "Synthetic human-reviewed supplements for this fixture."
    )
    assert any("technical" in issue.path for issue in result.issues)


def test_forged_source_span_and_orphan_supplement_are_rejected():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    raw = reviewed_mapping(draft).model_dump(mode="json")
    raw["clauses"][0]["excerpt"] = "forged"
    with pytest.raises(ValueError, match="source"):
        build_daily_review(
            draft,
            DailyMapping.model_validate(raw),
            "Synthetic human-reviewed supplements for this fixture.",
        )
    raw = reviewed_mapping(draft).model_dump(mode="json")
    raw["bindings"] = raw["bindings"][1:]
    with pytest.raises(ValueError, match="orphan"):
        build_daily_review(
            draft,
            DailyMapping.model_validate(raw),
            "Synthetic human-reviewed supplements for this fixture.",
        )


def test_fixed_simulation_rules_are_bound_by_server_without_human_broker_evidence():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    mapping = reviewed_mapping(draft)
    mapping = mapping.model_copy(
        update={
            "bindings": tuple(
                b for b in mapping.bindings if not b.path.startswith("trading_rules.")
            ),
            "supplements": tuple(
                s for s in mapping.supplements if not s.path.startswith("trading_rules.")
            ),
        }
    )
    result = build_daily_review(
        draft, mapping, "Synthetic human-reviewed supplements for this fixture."
    )
    assert result.issues == ()
    rules = tuple(b for b in result.mapping.bindings if b.path.startswith("trading_rules."))
    assert len(rules) == 3
    assert all(b.origin == "PRODUCT_CONTRACT" and b.supplement_id is None for b in rules)


@pytest.mark.parametrize(("source", "accepted"), [
    ("risk_branches=[]", True), ("无风险分支。", True),
    ("ordinary_rules=[]", False), ("无普通规则。", False),
    ("风险规则没有写清楚。", False), ("如果放量，无风险分支。", False),
    ("例如 risk_branches=[]", False), ("并非无风险分支。", False),
    ("risk_branches=[]？", False), ("risk_branches=[] 或保留原规则", False),
])
def test_empty_unified_rules_require_exact_matching_source_declaration(source, accepted):
    from tests.unit.test_unified_replay_input import research_plan

    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    draft = UnifiedPlanDraft.from_executable(research_plan())
    raw = reviewed_mapping(draft, source).model_dump(mode="json")
    binding = next(item for item in raw["bindings"] if item["path"] == "risk_branches")
    supplement_id = binding["supplement_id"]
    binding.update(origin="SOURCE", clause_ids=[raw["clauses"][0]["clause_id"]],
                   supplement_id=None)
    raw["supplements"] = [s for s in raw["supplements"]
                          if s["supplement_id"] != supplement_id]
    mapping = DailyMapping.model_validate(raw)
    if accepted:
        assert build_daily_review(draft, mapping, source).issues == ()
    else:
        with pytest.raises(ValueError, match="empty rules"):
            build_daily_review(draft, mapping, source)
