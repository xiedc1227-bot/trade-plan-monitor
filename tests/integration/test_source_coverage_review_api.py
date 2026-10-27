"""Current HTTP review binds exact coverage without weakening historical source review."""

import json
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_current_plan_api import post, review_payload
from tests.integration.test_web_api import _FakeLifecycle
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.state.models import PlanReviewProvenance
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


@pytest.fixture
def workspace(tmp_path):
    lifecycle = PersistentPlanWebLifecycle(
        database_path=tmp_path / "coverage-review-api.sqlite3",
        clock=lambda: datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    app = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_lifecycle_factory=lambda: lifecycle,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, lifecycle


def _save(client, *, source=None, mapping=None):
    draft, original_source, original_mapping = _baseline()
    return post(client, "plan-drafts", {
        "planJson": daily_draft_json(draft),
        "sourceText": original_source if source is None else source,
        "dailyMapping": (original_mapping if mapping is None else mapping).model_dump(mode="json"),
        "expectedRevision": 0,
    })


def _proof(lifecycle, version_id):
    assert lifecycle._session_factory is not None
    with lifecycle._session_factory() as session:
        stored = SourceCoverageStore(session).latest(version_id)
        assert stored is not None
        return stored


def _command(saved, stored, **updates):
    return review_payload(saved, **({
        "coverageEvidenceHash": stored.assessment.evidence_hash,
        "coverageRulesVersion": stored.assessment.rules_version,
    } | updates))


def _assert_conflict(response, reason):
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "CONFLICT"
    assert reason in {detail["code"] for detail in error["details"]}


def _assert_unreviewed(lifecycle, version_id):
    with lifecycle._session_factory() as session:
        original = session.get(PlanReviewProvenance, version_id)
        assert original.review_id is None
        assert original.review_revision == 0
        assert original.confirmed_at is None


def test_review_missing_current_coverage_binding_is_a_structured_conflict(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    assert _proof(lifecycle, saved["id"]).assessment.coverage_complete is True

    response = client.post("/api/v1/plan-review-confirmations", json=review_payload(saved),
                           headers={"Idempotency-Key": "missing-coverage-binding"})

    _assert_conflict(response, "SOURCE_COVERAGE_REQUIRED")
    assert client.get("/api/v1/plan-versions/" + saved["id"]).json()["reviewId"] is None
    _assert_unreviewed(lifecycle, saved["id"])


def test_review_matching_current_coverage_creates_an_exact_persistent_receipt(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    assert stored.assessment.coverage_complete is True

    reviewed = post(client, "plan-review-confirmations", _command(saved, stored))

    assert reviewed["canActivate"] is True
    assert reviewed["revision"] == 1
    assert UUID(reviewed["reviewId"])
    with lifecycle._session_factory() as session:
        receipt = SourceCoverageStore(session).receipt(reviewed["reviewId"])
        assert receipt is not None
        assert receipt.plan_version_id == saved["id"]
        assert receipt.review_id == reviewed["reviewId"]
        assert receipt.review_revision == reviewed["revision"]
        assert receipt.coverage_revision == stored.revision
        assert receipt.coverage_bundle_hash == stored.evidence_hash
        assert receipt.coverage_evidence_hash == stored.assessment.evidence_hash
        assert receipt.coverage_rules_version == stored.assessment.rules_version
        assert receipt.source_hash == saved["sourceHash"]
        assert receipt.content_hash == saved["contentHash"]
        assert receipt.mapping_hash == stored.assessment.mapping_hash
        assert receipt.original_review_evidence_hash == saved["reviewEvidenceHash"]
        assert receipt.authority_granted is False


@pytest.mark.parametrize("missing", ["coverageEvidenceHash", "coverageRulesVersion"])
def test_review_with_only_one_coverage_binding_field_is_a_conflict(workspace, missing):
    client, lifecycle = workspace
    saved = _save(client)
    command = _command(saved, _proof(lifecycle, saved["id"]))
    command.pop(missing)

    response = client.post("/api/v1/plan-review-confirmations", json=command,
                           headers={"Idempotency-Key": "one-missing-coverage-field"})

    _assert_conflict(response, "SOURCE_COVERAGE_REQUIRED")
    _assert_unreviewed(lifecycle, saved["id"])


@pytest.mark.parametrize("updates", [
    {"coverageEvidenceHash": "0" * 64},
    {"coverageRulesVersion": "source-coverage-rules-v0"},
])
def test_well_formed_wrong_coverage_hash_or_rules_is_a_stale_conflict(workspace, updates):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])

    response = client.post("/api/v1/plan-review-confirmations",
                           json=_command(saved, stored, **updates),
                           headers={"Idempotency-Key": "wrong-coverage-binding"})

    _assert_conflict(response, "SOURCE_COVERAGE_STALE")
    _assert_unreviewed(lifecycle, saved["id"])
    assert _proof(lifecycle, saved["id"]) == stored


def test_explicit_null_coverage_binding_is_a_state_conflict_not_a_body_error(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])

    response = client.post("/api/v1/plan-review-confirmations", json=_command(
        saved, stored, coverageEvidenceHash=None, coverageRulesVersion=None,
    ), headers={"Idempotency-Key": "null-coverage-binding"})

    _assert_conflict(response, "SOURCE_COVERAGE_REQUIRED")
    _assert_unreviewed(lifecycle, saved["id"])


def test_malformed_coverage_hash_retains_the_existing_body_validation_boundary(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])

    response = client.post("/api/v1/plan-review-confirmations", json=_command(
        saved, stored, coverageEvidenceHash="not-a-sha256-hash",
    ), headers={"Idempotency-Key": "malformed-coverage-binding"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    _assert_unreviewed(lifecycle, saved["id"])


@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
@pytest.mark.parametrize("condition", [
    "仅当换手率超过3%时才允许买入。",
    "Only buy when turnover exceeds 3 percent.",
])
def test_background_labeled_mandatory_condition_is_savable_but_cannot_be_confirmed(
    workspace, role, condition,
):
    client, lifecycle = workspace
    draft, source, mapping = _baseline()
    source, mapping = _append_as_context(
        source, mapping, condition, semantic_role=role, misclassification={
            "disposition": "CONTEXT", "paths": (), "reason": "An untrusted background proposal.",
        },
    )
    assert build_daily_review(draft, mapping, source).issues == ()

    saved = _save(client, source=source, mapping=mapping)

    assert saved["status"] == "DRAFT"
    assert saved["sourceText"] == source
    assert saved["reviewId"] is None and saved["canActivate"] is False
    assert json.loads(saved["planJson"])["ordinary_rules"] == draft.model_dump(
        mode="json")["ordinary_rules"]
    stored = _proof(lifecycle, saved["id"])
    assert stored.assessment.coverage_complete is False
    assert stored.assessment.issues
    response = client.post("/api/v1/plan-review-confirmations", json=_command(saved, stored),
                           headers={"Idempotency-Key": "blocked-background-condition"})

    _assert_conflict(response, "SOURCE_COVERAGE_REQUIRED")
    _assert_unreviewed(lifecycle, saved["id"])
    assert _proof(lifecycle, saved["id"]) == stored
    detail = client.get("/api/v1/plan-versions/" + saved["id"]).json()
    assert detail["sourceText"] == source
    assert detail["reviewId"] is None and detail["canActivate"] is False


def test_exact_confirmation_replay_reuses_receipt_and_changed_proof_conflicts(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    command = _command(saved, stored)
    key = "exact-coverage-confirmation-intent"

    first = post(client, "plan-review-confirmations", command, key=key)
    assert post(client, "plan-review-confirmations", command, key=key) == first
    changed = client.post("/api/v1/plan-review-confirmations", json={
        **command, "coverageEvidenceHash": "0" * 64,
    }, headers={"Idempotency-Key": key})

    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "CONFLICT"
    with lifecycle._session_factory() as session:
        receipt = SourceCoverageStore(session).receipt(first["reviewId"])
        original = session.get(PlanReviewProvenance, saved["id"])
        assert receipt.coverage_evidence_hash == stored.assessment.evidence_hash
        assert original.review_id == first["reviewId"] and original.review_revision == 1
    assert _proof(lifecycle, saved["id"]) == stored


@pytest.mark.parametrize("field", ["contentHash", "sourceHash", "reviewEvidenceHash"])
def test_valid_but_mismatched_original_review_hash_is_a_stale_conflict(workspace, field):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    assert saved[field] != "0" * 64
    command = _command(saved, stored, **{field: "0" * 64})

    response = client.post("/api/v1/plan-review-confirmations", json=command,
                           headers={"Idempotency-Key": "mismatched-original-" + field})

    _assert_conflict(response, "SOURCE_COVERAGE_STALE")
    _assert_unreviewed(lifecycle, saved["id"])
    assert _proof(lifecycle, saved["id"]) == stored


def test_same_key_confirmation_replay_rechecks_the_current_coverage_bundle(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    original = _proof(lifecycle, saved["id"])
    command = _command(saved, original)
    key = "confirmation-before-reassessment"
    first = post(client, "plan-review-confirmations", command, key=key)
    with lifecycle._session_factory() as session, session.begin():
        store = SourceCoverageStore(session)
        receipt_before = store.receipt(first["reviewId"])
        current = store.append(
            saved["id"], original.assessment, inputs=original.inputs,
            expected_revision=original.revision, command_id="http-review-proof-reassessment",
            now=original.created_at + timedelta(minutes=1),
        )
        assert current.assessment.evidence_hash == original.assessment.evidence_hash
        assert current.evidence_hash != receipt_before.coverage_bundle_hash

    replay = client.post("/api/v1/plan-review-confirmations", json=command,
                         headers={"Idempotency-Key": key})

    _assert_conflict(replay, "SOURCE_COVERAGE_STALE")
    with lifecycle._session_factory() as session:
        store = SourceCoverageStore(session)
        assert store.receipt(first["reviewId"]) == receipt_before
        assert store.latest(saved["id"]) == current
        provenance = session.get(PlanReviewProvenance, saved["id"])
        assert provenance.review_id == first["reviewId"]
        assert provenance.review_revision == 1
