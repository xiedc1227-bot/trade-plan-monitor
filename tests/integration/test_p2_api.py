"""Read-only economics previews use server evidence and cannot grant authority."""

from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_p2_chain import p2_chain as p2_chain


def test_preview_is_read_only_and_uses_exact_server_quantity(p2_chain):
    chain = p2_chain
    before = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    candidates = before.snapshot.get("exception_candidates", [])
    body = {"planVersionId": chain.version["id"],
            "ruleId": chain.plan.ordinary_rules[0].rule_id,
            "occurrenceId": candidates[0]["candidate"]["candidate_id"] if candidates else None,
            "proposedQuantity": 300 if chain.route == "BROKEN_STRONG" else None}
    with chain.plans._unit_of_work() as work:
        from sqlalchemy import select

        from trade_plan_monitor.state.daily_models import DailyRecord
        state = tuple(work.daily.session.execute(select(DailyRecord.id, DailyRecord.revision)))
    result = chain.post("plan-economics-previews", body)
    assert result["quantity"] == (300 if chain.route == "BROKEN_STRONG"
                                  else 100 if candidates else 200)
    assert result["economics"]["outcome"] == "NONE"
    assert result["authorityGranted"] is False
    with chain.plans._unit_of_work() as work:
        after = tuple(work.daily.session.execute(select(DailyRecord.id, DailyRecord.revision)))
        assert after == state


def test_client_quote_and_policy_cannot_enter_preview(p2_chain):
    chain = p2_chain
    chain.post("plan-economics-previews", {"planVersionId": chain.version["id"],
        "ruleId": chain.plan.ordinary_rules[0].rule_id, "quoteFen": 1}, status=422)


def test_preview_for_unknown_rule_returns_conflict(p2_chain):
    chain = p2_chain
    chain.post("plan-economics-previews", {"planVersionId": chain.version["id"],
        "ruleId": "unreviewed-rule"}, status=409)


def test_long_unresolved_review_reason_is_retained_without_server_error(p2_chain):
    from tests.integration.test_market_linkage_review import source_mapping

    from trade_plan_monitor.ai.daily_review import build_daily_review
    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
    from trade_plan_monitor.domain.p2_validation import P2PlanDraft

    chain = p2_chain
    draft = P2PlanDraft.from_executable(chain.plan.model_copy(update={"version": 2}))
    source, mapping = source_mapping(draft)
    reason = ("Unresolved review evidence. " * 30).strip()
    mapping = mapping.model_copy(update={"clauses": (mapping.clauses[0].model_copy(
        update={"disposition": "UNRESOLVED", "paths": (), "reason": reason}),
        *mapping.clauses[1:]), "bindings": tuple(b for b in mapping.bindings
            if mapping.clauses[0].clause_id not in b.clause_ids)})
    review = build_daily_review(draft, mapping, source)
    assert any(i.reason == reason for i in review.issues)
    saved = chain.post("plan-drafts", {"planJson": daily_draft_json(draft),
        "sourceText": source, "dailyMapping": mapping.model_dump(mode="json"),
        "expectedRevision": 1})
    assert any(i["reason"] == reason for i in saved["dailyIssues"])
    assert all(len(i["message"]) <= 512 for i in saved["validationIssues"])
    assert saved["canActivate"] is False
