"""Current lifecycle engineering coverage, separate from natural-language accuracy.

The explicit FIELD source is a synthetic complete carrier, not a rewrite of the
original unknown source or evidence of AI semantic extraction accuracy. The old
workflow's positive assertions remain here; its unknown-source negatives retain
their original text in test_current_plan_api.
"""

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.integration.preparation_review_current_fixtures import field_source, reviewed_mapping
from tests.integration.test_current_plan_api import (
    coverage_review_payload,
    make_app,
    post,
    review_payload,
    simple_plan,
)

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def _field_save(client, draft, *, base=None, activation_revision=0, revised=False):
    source = field_source(draft, tail=("# Trade plan",) if revised else ())
    mapping = reviewed_mapping(draft, source)
    assert not mapping.supplements
    return post(client, "plan-drafts", dict(
        basePlanVersionId=base, planJson=daily_draft_json(draft), sourceText=source,
        dailyMapping=mapping.model_dump(mode="json"), expectedRevision=activation_revision))


def test_complete_field_source_edit_review_activate_restart_and_source_replacement(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        initial = UnifiedPlanDraft.from_executable(simple_plan())
        saved_unresolved = _field_save(client, initial)
        assert not saved_unresolved["canActivate"]
        edited = json.loads(saved_unresolved["planJson"])
        edited["ordinary_rules"][0]["quantity"] = 200
        draft = UnifiedPlanDraft.model_validate(edited)
        saved = _field_save(client, draft, base=saved_unresolved["id"])
        assert saved["version"] == 2 and saved["reviewId"] is None
        stale = post(client, "plan-review-confirmations", review_payload(saved,
            sourceHash="0" * 64), expected=409)
        assert stale["error"]["details"][0]["code"] == "SOURCE_COVERAGE_STALE"
        review_key = str(uuid4())
        review = post(client, "plan-review-confirmations", coverage_review_payload(client, saved),
                      key=review_key)
        # Keep the old assertion's native command shape; this local value is the
        # actual source-bound confirmation payload, not an activation payload.
        confirmed_payload = coverage_review_payload(client, saved)
        assert (
            post(client, "plan-review-confirmations", confirmed_payload, key=review_key)
            == review
        )
        active_command = review_payload(saved, reviewId=review["reviewId"], reviewRevision=1)
        active = post(client, "plan-activations", active_command)
        assert active["active"] and active["revision"] == 1
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active

    # A new lifecycle reads the same SQLite store; review identity and activation survive.
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        restored = client.get("/api/v1/plan-versions/" + saved["id"]).json()
        assert restored["reviewId"] == review["reviewId"] and restored["canActivate"]
        assert client.get("/api/v1/plan-activation-states/601021.SH").json()["active"]
        changed_source = _field_save(client, draft, base=saved["id"],
                                     activation_revision=1, revised=True)
        assert changed_source["sourceHash"] != saved["sourceHash"]
        assert changed_source["reviewId"] is None and not changed_source["canActivate"]
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active
        stale = {**active_command, "planVersionId": changed_source["id"], "expectedRevision": 1}
        post(client, "plan-activations", stale, expected=409)
        post(
            client,
            "plan-review-confirmations",
            review_payload(saved, expectedRevision=0),
            expected=409,
        )
        replacement_review = post(client, "plan-review-confirmations",
                                 coverage_review_payload(client, changed_source))
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active
        replacement_active = post(client, "plan-activations", review_payload(
            changed_source, reviewId=replacement_review["reviewId"], reviewRevision=1,
            expectedRevision=1))
        assert replacement_active["revision"] == 2
        assert replacement_active["planVersionId"] == changed_source["id"]
