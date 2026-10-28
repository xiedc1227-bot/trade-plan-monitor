"""Oversized-but-native-valid sources remain exact, inspectable blocked drafts."""

import pytest
from tests.integration.test_source_coverage_authority import _command
from tests.integration.test_source_coverage_authority_save import _NOW, _ai_result
from tests.integration.test_source_coverage_authority_save import _save as save_result
from tests.integration.test_source_coverage_authority_save import state as state
from tests.integration.test_source_coverage_read import client_for, page, storage_snapshot
from tests.unit.test_source_coverage_source_limit import large_case

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.state.daily_review_store import confirm_daily_review
from trade_plan_monitor.state.source_coverage_authority import (
    SourceCoverageAuthorityError,
    read_version_coverage,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


@pytest.mark.parametrize("ai_new", [False, True])
def test_large_source_save_reload_and_current_coverage_share_one_blocked_hash_without_truncation(
    state, ai_new,
):
    draft, source, mapping = large_case()
    assert len(source) == 200_017 and len(mapping.clauses) == 391
    digest = daily_draft_content_sha256(draft)
    with state.work() as work:
        work.daily.save(daily_hash("daily-human-supplements-v1", dict(
            symbol=draft.symbol, content_hash=digest)), kind="DRAFT", symbol=draft.symbol,
            lineage=digest, expected_revision=0, payload=dict(content_hash=digest,
                source="EXPLICIT_HUMAN_OPERATION",
                supplements=[row.model_dump(mode="json") for row in mapping.supplements]))
        work.commit()
    original = _ai_result(draft, source, mapping) if ai_new else None
    identity = save_result(state, draft, source, mapping, extraction=original)
    before = storage_snapshot(state.engine)
    with state.work() as work:
        details = work.plans.get_version_details(identity)
        stored = SourceCoverageStore(work.daily.session).latest(identity)
        assert details.source_text == source and details.daily_mapping == mapping
        assert stored.assessment.status == "BLOCKED" and stored.assessment.obligations == ()
        assert stored.assessment.issues[0].code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"
        assert not stored.assessment.automatic_fidelity_verified
        assert stored.assessment.normalization_hash is None
        assert read_version_coverage(work, details) == stored
        if ai_new:
            assert stored.inputs.normalization == original.normalization_trace
            assert stored.inputs.initial_coverage == original.coverage
            assert stored.assessment.origin == "AI_NEW"
        with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
            confirm_daily_review(work, _command(work, identity), clock=lambda: _NOW)
        assert work.plans.get_version_details(identity).review_id is None
    with client_for(state.sessions, state.engine) as (client, _):
        value = page(client, identity)
        assert value["summary"]["status"] == "BLOCKED"
        assert not value["summary"]["canConfirmReview"]
        assert not value["summary"]["currentReviewBound"]
        assert value["summary"]["obligationCount"] == 0
        assert any(row["kind"] == "ISSUE" and row["issue"]["code"] ==
                   "SOURCE_COVERAGE_LIMIT_EXCEEDED" for row in value["items"])
        response = client.get(f"/api/v1/plan-versions/{identity}")
        assert response.status_code == 200
        assert response.json()["sourceText"] == source
        assert not response.json()["canActivate"]
    assert storage_snapshot(state.engine) == before
