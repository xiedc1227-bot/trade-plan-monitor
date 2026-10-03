"""Registered human supplements survive batches/previews only for their exact candidate."""

import pytest
from test_daily_plan_chain import Chain
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft as DailyPlanDraft

SOURCE = "Synthetic independently reviewed daily technical policy supplements."


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
    reviewed = chain.post("plan-review-confirmations", {**binding, "expectedRevision": 0})
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
