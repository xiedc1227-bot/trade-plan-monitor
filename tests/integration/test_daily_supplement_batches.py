"""Registered human supplements survive batches/previews only for their exact candidate."""

import pytest
from test_daily_plan_chain import Chain
from tests.integration.test_current_plan_api import coverage_review_payload
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft as DailyPlanDraft

SOURCE = "# Trade plan"


@pytest.fixture
def batch_chain(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        yield chain


def preview(chain, draft, mapping=None):
    return chain.post(
        "plan-review-previews",
        {
            "candidateJson": daily_draft_json(draft),
            "sourceText": SOURCE,
            "mapping": None if mapping is None else mapping.model_dump(mode="json"),
        },
    )


def register(chain, draft, items, revision):
    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

    return chain.post(
        "plan-review-supplements",
        {
            "candidateJson": daily_draft_json(draft),
            "contentHash": daily_draft_content_sha256(draft),
            "supplements": [item.model_dump(mode="json") for item in items],
            "expectedRevision": revision,
        },
    )


def test_two_batches_repreview_reload_save_review_and_activate(batch_chain):
    from trade_plan_monitor.ai.daily_review import DailyMapping

    chain = batch_chain
    draft = DailyPlanDraft.from_executable(chain.plan)
    mapping = reviewed_mapping(draft, SOURCE)
    midpoint = len(mapping.supplements) // 2
    first_items = mapping.supplements[:midpoint]
    first = register(chain, draft, first_items, 0)
    partial = preview(chain, draft, mapping)
    assert partial["supplementRevision"] == first["revision"] == 1
    assert {s["supplement_id"] for s in partial["review"]["mapping"]["supplements"]} == {
        s.supplement_id for s in first_items
    }
    assert partial["review"]["issues"]
    second = register(chain, draft, mapping.supplements, partial["supplementRevision"])
    complete = preview(chain, draft, mapping)
    assert complete["supplementRevision"] == second["revision"] == 2
    assert complete["review"]["issues"] == []
    # No client mapping is needed to recover server-registered human authority after reload.
    recovered = preview(chain, draft)
    assert recovered["supplementRevision"] == 2
    assert (
        recovered["review"]["mapping"]["supplements"]
        == complete["review"]["mapping"]["supplements"]
    )
    repeated = preview(chain, draft, DailyMapping.model_validate(complete["review"]["mapping"]))
    assert repeated["review"] == complete["review"]
    saved = chain.post(
        "plan-drafts",
        {
            "planJson": complete["candidateJson"],
            "sourceText": SOURCE,
            "dailyMapping": complete["review"]["mapping"],
            "expectedRevision": 0,
        },
    )
    assert saved["dailyIssues"] == []
    binding = {
        "planVersionId": saved["id"],
        "contentHash": saved["contentHash"],
        "sourceHash": saved["sourceHash"],
        "reviewEvidenceHash": saved["reviewEvidenceHash"],
    }
    reviewed = chain.post("plan-review-confirmations", coverage_review_payload(chain.client, saved))
    activated = chain.post(
        "plan-activations",
        {**binding, "reviewId": reviewed["reviewId"], "reviewRevision": 1, "expectedRevision": 0},
    )
    assert activated["active"] is True


def test_client_cannot_invent_registered_supplements(batch_chain):
    chain = batch_chain
    draft = DailyPlanDraft.from_executable(chain.plan)
    forged = reviewed_mapping(draft, SOURCE)
    result = preview(chain, draft, forged)
    assert result["supplementRevision"] == 0
    assert result["review"]["mapping"]["supplements"] == []
    assert all(b["origin"] != "HUMAN_SUPPLEMENT" for b in result["review"]["mapping"]["bindings"])
    assert result["review"]["issues"]


def test_content_edit_invalidates_old_registry_and_review_binding(batch_chain):
    chain = batch_chain
    draft = DailyPlanDraft.from_executable(chain.plan)
    old = reviewed_mapping(draft, SOURCE)
    register(chain, draft, old.supplements, 0)
    edited = draft.model_dump(mode="json")
    edited["levels"]["low_buy"]["include_low"] = False
    changed = DailyPlanDraft.model_validate(edited)
    result = preview(chain, changed, old)
    assert result["supplementRevision"] == 0
    assert result["review"]["content_hash"] != old.candidate_content_hash
    assert result["review"]["mapping"]["supplements"] == []
    assert all(b["origin"] != "HUMAN_SUPPLEMENT" for b in result["review"]["mapping"]["bindings"])
    assert result["review"]["issues"]
    chain.post(
        "plan-drafts",
        {
            "planJson": daily_draft_json(changed),
            "sourceText": SOURCE,
            "dailyMapping": old.model_dump(mode="json"),
            "expectedRevision": 0,
        },
        status=422,
    )


def test_duplicate_version_is_controlled_conflict_and_preserves_saved_document(batch_chain):
    chain = batch_chain
    draft = DailyPlanDraft.from_executable(chain.plan)
    mapping = reviewed_mapping(draft, SOURCE)
    register(chain, draft, mapping.supplements, 0)
    body = {
        "planJson": daily_draft_json(draft),
        "sourceText": SOURCE,
        "dailyMapping": mapping.model_dump(mode="json"),
        "expectedRevision": 0,
    }
    saved = chain.post("plan-drafts", body, key="first-version-save")
    duplicate = chain.post("plan-drafts", body, key="second-version-save", status=409)
    assert duplicate["error"]["code"] == "CONFLICT"
    response = chain.client.get("/api/v1/plan-versions/" + saved["id"])
    assert response.status_code == 200, response.text
    unchanged = response.json()
    assert unchanged["planJson"] == saved["planJson"]
    assert unchanged["planHash"] == saved["planHash"]
    assert unchanged["contentHash"] == saved["contentHash"]
    assert unchanged["reviewEvidenceHash"] == saved["reviewEvidenceHash"]
    assert unchanged["sourceText"] == SOURCE


def _pbs_command(draft, source, mapping, *, revision=0):
    return dict(candidateJson=daily_draft_json(draft), contentHash=mapping.candidate_content_hash,
                sourceText=source, supplements=[s.model_dump(mode="json")
                for s in mapping.supplements], expectedRevision=revision)


def test_buy_suspension_registered_clarification_survives_preview_save_and_current_read(
    batch_chain,
):
    from tests.unit.test_plan_buy_suspension_coverage import complete_suspension_case

    from trade_plan_monitor.state.daily_review_store import save_daily_draft
    from trade_plan_monitor.state.source_coverage_authority import require_current_coverage

    chain = batch_chain
    draft, source, mapping, obligation = complete_suspension_case(clarified=True)
    registered = chain.post("plan-review-supplements", _pbs_command(draft, source, mapping))
    result = chain.post("plan-review-previews", dict(candidateJson=daily_draft_json(draft),
        sourceText=source, mapping=mapping.model_dump(mode="json")))
    assert result["supplementRevision"] == registered["revision"] == 1
    assert result["review"]["issues"] == []
    with chain.plans._unit_of_work() as work:
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                   clock=chain.plans._clock)
        proof = require_current_coverage(work, work.plans.get_version_details(identity))
        assert proof.assessment.coverage_complete
        assert next(o for o in proof.assessment.obligations
                    if o.obligation_id == obligation.obligation_id).state == (
                        "MAPPED_WITH_REGISTERED_SUPPLEMENT")
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert require_current_coverage(work, work.plans.get_version_details(identity)) == proof
        assert work.plans.get_active(draft.symbol) is None


@pytest.mark.parametrize("attack", ["source", "obligation", "content", "value", "no-source"])
def test_buy_suspension_registration_rejects_wrong_binding_without_creating_evidence(
    batch_chain, attack,
):
    from tests.unit.test_plan_buy_suspension_coverage import complete_suspension_case

    chain = batch_chain
    draft, source, mapping, _ = complete_suspension_case(clarified=True)
    command = _pbs_command(draft, source, mapping)
    if attack == "no-source":
        command.pop("sourceText")
    else:
        key = {"source": "source_hash", "obligation": "obligation_id",
               "content": "candidate_content_hash", "value": "value"}[attack]
        command["supplements"][0][key] = "0" * 64
    chain.post("plan-review-supplements", command, status=422)
    assert chain.plans._session_factory is not None
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=draft.symbol, kind="DRAFT") == ()


def test_buy_suspension_forged_preview_and_unregistered_save_cannot_create_human_authority(
    batch_chain,
):
    from tests.unit.test_plan_buy_suspension_coverage import complete_suspension_case

    from trade_plan_monitor.state.daily_review_store import save_daily_draft

    chain = batch_chain
    draft, source, mapping, _ = complete_suspension_case(clarified=True)
    result = chain.post("plan-review-previews", dict(candidateJson=daily_draft_json(draft),
        sourceText=source, mapping=mapping.model_dump(mode="json")))
    assert result["supplementRevision"] == 0
    assert result["review"]["mapping"]["supplements"] == []
    assert result["review"]["issues"]
    with chain.plans._unit_of_work() as work, pytest.raises(ValueError, match="registered"):
        save_daily_draft(work, draft, mapping=mapping, source_text=source, clock=chain.plans._clock)


def test_buy_suspension_changed_source_and_stale_registration_cannot_reuse_approval(batch_chain):
    from tests.unit.test_plan_buy_suspension_coverage import complete_suspension_case

    from trade_plan_monitor.state.daily_review_store import save_daily_draft

    chain = batch_chain
    draft, source, mapping, _ = complete_suspension_case(clarified=True)
    command = _pbs_command(draft, source, mapping)
    chain.post("plan-review-supplements", command)
    chain.post("plan-review-supplements", command, status=409)
    changed = source.replace("24.20后", "24.21后")
    with chain.plans._unit_of_work() as work, pytest.raises(ValueError):
        from trade_plan_monitor.ai.daily_review import DailyClause
        from trade_plan_monitor.ai.review import server_source_clauses

        new_clauses = tuple(DailyClause.model_validate(c.model_dump() | {
            "disposition": old.disposition, "paths": old.paths, "reason": old.reason,
            "semantic_role": old.semantic_role,
        }) for c, old in zip(server_source_clauses(changed), mapping.clauses, strict=True))
        save_daily_draft(work, draft, mapping=mapping.model_copy(update={"clauses": new_clauses}),
                         source_text=changed, clock=chain.plans._clock)
