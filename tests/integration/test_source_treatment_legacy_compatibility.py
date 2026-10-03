"""Historical plan-mapping-v1 rows retain their review identity after the v2 addition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.history.explicit_review_fixtures import (
    _EXTRACTION_ID,
    _NOW,
    _PROVIDER_ID,
    _SOURCE,
    _app,
    _confirmation_resolutions,
    _draft_payload,
    _mapping,
)

from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    PlanExtractionResult,
    PlanExtractionStatus,
    ReviewResolution,
    build_plan_extraction_review,
)
from trade_plan_monitor.ai.review import build_server_review_snapshot
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    PlanReviewOrigin,
    PlanReviewProvenance,
    StoredPlanExtractionReview,
)

# Independently reproduced with ai/review.py at f5a421b, before source treatments existed.
LEGACY_EVIDENCE_HASH = "067dd4a86bb6fd1ae5350111be01b11d646af6f3c0aedf993e307502422bd39f"
LEGACY_CONTENT_HASH = "316adf0a2d2115660fff2d0eb25e146b8637f189d8d98c2a7ce5dc41f65290bd"
LEGACY_SOURCE_HASH = "e2ef6107df263a42cfa5d4b5d0af709ae2ee2441b8d47a2f18b8d568f99a63c0"
BASE_URL = "http://127.0.0.1:8765"


@pytest.mark.parametrize("reviewed", [False, True])
def test_historical_v1_storage_reads_after_restart_without_rehashing_or_upgrading(
    tmp_path: Path, reviewed: bool
) -> None:
    database_path = tmp_path / f"historical-v1-{reviewed}.sqlite3"
    app, lifecycle = _app(database_path)
    engine = create_sqlite_engine(database_path)
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload()))
    try:
        with TestClient(app, base_url=BASE_URL) as client:
            # Construct frozen database rows directly. No current extraction,
            # save, confirmation or activation endpoint grants historical authority.
            mapping = _mapping(draft)
            snapshot = build_server_review_snapshot(
                draft=draft, mapping=mapping, source_text=_SOURCE
            )
            result = PlanExtractionResult(
                request_id=_EXTRACTION_ID,
                provider_id=_PROVIDER_ID,
                model="offline-v4",
                prompt_version="plan-extract-v4",
                source_text_sha256=LEGACY_SOURCE_HASH,
                draft=draft,
                mapping=mapping,
                usage=None,
                status=PlanExtractionStatus.SUCCEEDED,
            )
            with lifecycle._unit_of_work() as work:
                work.plans.record_extraction_review(
                    build_plan_extraction_review(result), completed_at=_NOW
                )
                row = work.plans.save_draft(
                    draft,
                    source_text=_SOURCE,
                    review_origin=PlanReviewOrigin.AI_EXTRACTION,
                    extraction_id=str(_EXTRACTION_ID),
                    explicit_snapshot=snapshot,
                )
                work.commit()
            before = client.get(f"/api/v1/plan-versions/{row.id}").json()
            assert before["mapping"]["mappingVersion"] == "plan-mapping-v1"
            assert before["reviewEvidenceHash"] == LEGACY_EVIDENCE_HASH
            assert before["contentHash"] == LEGACY_CONTENT_HASH
            assert before["sourceHash"] == LEGACY_SOURCE_HASH
            if reviewed:
                with lifecycle._unit_of_work() as work:
                    work.plans.confirm_explicit_review(
                        plan_version_id=row.id,
                        content_hash=LEGACY_CONTENT_HASH,
                        source_hash=LEGACY_SOURCE_HASH,
                        review_evidence_hash=LEGACY_EVIDENCE_HASH,
                        expected_revision=0,
                        resolutions=tuple(
                            ReviewResolution.model_validate_json(
                                json.dumps(
                                    {
                                        "issue_id": item["issueId"],
                                        "resolution": item["resolution"],
                                        "binding_path": item.get("bindingPath"),
                                        "supplement_id": item.get("supplementId"),
                                    }
                                )
                            )
                            for item in _confirmation_resolutions(before)
                        ),
                    )
                    work.commit()
                before = client.get(f"/api/v1/plan-versions/{row.id}").json()
            assert before["canActivate"] is False
            assert before["obsoleteReason"] == "LEGACY_PLANS_REQUIRE_REVIEW"
            assert (before["reviewId"] is not None) is reviewed
            assert before["reviewRevision"] == (1 if reviewed else 0)
            denied_review = client.post(
                "/api/v1/plan-review-confirmations",
                headers={"Idempotency-Key": "legacy-review-is-read-only"},
                json={
                    "planVersionId": row.id,
                    "contentHash": LEGACY_CONTENT_HASH,
                    "sourceHash": LEGACY_SOURCE_HASH,
                    "reviewEvidenceHash": LEGACY_EVIDENCE_HASH,
                    "expectedRevision": before["reviewRevision"],
                    "resolutions": [],
                },
            )
            assert denied_review.status_code == 422
            denied_activation = client.post(
                "/api/v1/plan-activations",
                headers={"Idempotency-Key": "legacy-activation-denied"},
                json={
                    "planVersionId": row.id,
                    "expectedRevision": 0,
                },
            )
            assert denied_activation.status_code == 409

            with create_session_factory(engine)() as session:
                for model in (PlanReviewProvenance, StoredPlanExtractionReview):
                    rows = session.scalars(select(model)).all()
                    assert len(rows) == 1
                    mapping = json.loads(rows[0].mapping_json)
                    mapping.pop("source_processing", None)
                    assert mapping["mapping_version"] == "plan-mapping-v1"
                    rows[0].mapping_json = json.dumps(mapping)
                session.commit()
    finally:
        engine.dispose()

    restarted_app, _ = _app(database_path)
    with TestClient(restarted_app, base_url=BASE_URL) as client:
        restored = client.get(f"/api/v1/plan-versions/{before['id']}")
        assert restored.status_code == 200, restored.text
        assert restored.json() == before
        assert restored.json()["reviewEvidenceHash"] == LEGACY_EVIDENCE_HASH
        assert restored.json()["mapping"]["mappingVersion"] == "plan-mapping-v1"
        assert restored.json()["mapping"]["sourceProcessing"] is None
        capability = client.get("/api/v1/plan-capabilities").json()
        assert capability["publicActivationAvailable"] is True
        assert capability["isolatedTrustedReviewOnly"] is False
        assert capability["pendingRequirements"] == []
