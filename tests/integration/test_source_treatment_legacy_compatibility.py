"""Historical plan-mapping-v1 rows retain their review identity after the v2 addition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.integration.test_explicit_plan_review_api import (
    _EXTRACTION_ID,
    _SOURCE,
    _app,
    _confirmation_resolutions,
    _draft_payload,
    _record_extraction,
)

from trade_plan_monitor.ai.models import ExplicitPlanDraft
from trade_plan_monitor.ai.review import dump_explicit_plan_draft_json
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import PlanReviewProvenance, StoredPlanExtractionReview

# Independently reproduced with ai/review.py at f5a421b, before source treatments existed.
LEGACY_EVIDENCE_HASH = "067dd4a86bb6fd1ae5350111be01b11d646af6f3c0aedf993e307502422bd39f"
LEGACY_CONTENT_HASH = "316adf0a2d2115660fff2d0eb25e146b8637f189d8d98c2a7ce5dc41f65290bd"
LEGACY_SOURCE_HASH = "e2ef6107df263a42cfa5d4b5d0af709ae2ee2441b8d47a2f18b8d568f99a63c0"
BASE_URL = "http://127.0.0.1:8765"


@pytest.mark.parametrize("reviewed", [False, True])
def test_historical_v1_storage_reads_after_restart_without_rehashing_or_upgrading(
    tmp_path: Path, monkeypatch, reviewed: bool
) -> None:
    database_path = tmp_path / f"historical-v1-{reviewed}.sqlite3"
    app, lifecycle = _app(database_path)
    engine = create_sqlite_engine(database_path)
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload()))
    try:
        with TestClient(app, base_url=BASE_URL) as client:
            _record_extraction(lifecycle, draft)
            # Seed the historical storage shape by bypassing only the new save adapter.
            # All ordinary reads and review confirmations below use unpatched production code.
            with monkeypatch.context() as fixture_patch:
                fixture_patch.setattr(
                    "trade_plan_monitor.ai.source_processing.upgrade_source_mapping",
                    lambda **arguments: arguments["mapping"],
                )
                saved = client.post(
                    "/api/v1/plan-drafts",
                    headers={"Idempotency-Key": "legacy-v1-seed"},
                    json={
                        "extractionId": str(_EXTRACTION_ID),
                        "planJson": dump_explicit_plan_draft_json(draft),
                        "sourceText": _SOURCE,
                        "expectedRevision": 0,
                    },
                )
            assert saved.status_code == 200, saved.text
            before = saved.json()
            assert before["mapping"]["mappingVersion"] == "plan-mapping-v1"
            assert before["reviewEvidenceHash"] == LEGACY_EVIDENCE_HASH
            assert before["contentHash"] == LEGACY_CONTENT_HASH
            assert before["sourceHash"] == LEGACY_SOURCE_HASH
            if reviewed:
                confirmed = client.post(
                    "/api/v1/plan-review-confirmations",
                    headers={"Idempotency-Key": "legacy-v1-review"},
                    json={
                        "planVersionId": before["id"],
                        "contentHash": before["contentHash"],
                        "sourceHash": before["sourceHash"],
                        "reviewEvidenceHash": before["reviewEvidenceHash"],
                        "expectedRevision": 0,
                        "resolutions": _confirmation_resolutions(before),
                    },
                )
                assert confirmed.status_code == 200, confirmed.text
                assert confirmed.json()["canActivate"] is True
                before = client.get(f"/api/v1/plan-versions/{before['id']}").json()
            assert before["canActivate"] is reviewed
            assert (before["reviewId"] is not None) is reviewed

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
