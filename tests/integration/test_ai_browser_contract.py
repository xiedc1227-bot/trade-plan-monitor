"""Preserve the historical browser bytes and explicitly test approved current additions.

This is synthetic serializer evidence, not real-provider extraction acceptance.
"""

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from tests.unit.test_current_plan_extraction_security import current_output, extract

from trade_plan_monitor.ai.models import AIUsageSnapshot
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_sha256,
)
from trade_plan_monitor.web.ai_service import _completed_extraction_view
from trade_plan_monitor.web.source_coverage_schemas import SourceCoverageSummaryView

FIXTURE = Path(__file__).parents[2] / "web/tests/fixtures/ai-partial-extraction.json"
_FIXTURE_SHA256 = "2e9d713b607048f01690db94be61db08553454f1b56b218f4c0bff22da621209"
_SOURCE_CONTEXT_ISSUE = {
    "code": "SOURCE_CONTEXT_UNVERIFIED",
    "path": "source.clause-fc6f7f64a0fc6526",
    "severity": "WARNING",
    "message": "This source span has no proven complete policy or context treatment.",
    "activationBlocking": True,
}


def _partial_result():
    output = current_output()
    output["draft"]["activation"] = None
    output["draft"]["position"]["max_qty"] = None
    return extract(output).model_copy(
        update={
            "request_id": UUID("51e37676-d62d-4bbc-873a-2b389f8d4611"),
            "usage": AIUsageSnapshot(prompt_tokens=100, completion_tokens=100, total_tokens=200),
        }
    )


def production_partial_view(result=None):
    timestamp = datetime.fromisoformat("2026-09-14T10:00:00+08:00")
    return _completed_extraction_view(
        result=_partial_result() if result is None else result,
        submitted_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
        diagnostic_status="RECORDED",
    ).model_dump(mode="json", by_alias=True)


def test_browser_partial_extraction_fixture_matches_production_serialization():
    fixture_bytes = FIXTURE.read_bytes()
    assert sha256(fixture_bytes).hexdigest() == _FIXTURE_SHA256
    expected = json.loads(fixture_bytes)
    result = _partial_result()
    actual = production_partial_view(result)
    assert actual.keys() == expected.keys() | {"sourceCoverage"}
    assert len(expected["validationIssues"]) == 84
    assert len(actual["validationIssues"]) == 85
    assert actual["validationIssues"][:84] == expected["validationIssues"]
    assert actual["validationIssues"][84:] == [_SOURCE_CONTEXT_ISSUE]

    # Keep the original all-field equality after removing ONLY the exact current
    # additions asserted above. No SOURCE_* prefix filtering or golden rewrite.
    historical_projection = dict(actual, validationIssues=actual["validationIssues"][:84])
    del historical_projection["sourceCoverage"]
    assert historical_projection == expected

    source = SourceCoverageSummaryView.model_validate_json(json.dumps(actual["sourceCoverage"]))
    assert source.status == "BLOCKED" and source.coverage_complete is False
    assert source.reason == "SOURCE_COVERAGE_REQUIRED" and source.review_state == "NEEDS_REVIEW"
    assert source.authority_granted is False and source.automatic_fidelity_verified is False
    assert source.current_review_bound is False and source.can_confirm_review is False
    assert source.review_id is None and source.review_revision == 0
    assert source.coverage_revision is None and source.coverage_bundle_hash is None
    assert source.coverage_review_receipt_hash is None
    assert source.origin == "AI_NEW" and source.rules_version == "source-coverage-rules-v1"
    assert (
        source.obligation_count,
        source.issue_count,
        source.normalization_change_count,
        source.total_rows,
    ) == (1, 85, 0, 86)
    assert source.source_hash == actual["sourceTextSha256"] == result.source_text_sha256
    assert source.candidate_plan_hash == daily_draft_sha256(result.draft)
    assert source.content_hash == daily_draft_content_sha256(result.draft)
    mapping = result.daily_mapping.model_dump(mode="json")
    assert source.mapping_hash == daily_hash("source-coverage-mapping-v1", mapping)
    assert source.original_review_evidence_hash == daily_hash(
        "daily-plan-review-evidence-v1", mapping
    )
    assert source.coverage_evidence_hash == result.coverage.evidence_hash
    trace = result.normalization_trace
    assert source.normalization_hash == result.coverage.normalization_hash == trace.evidence_hash
    assert trace.source_hash == source.source_hash
    assert trace.after_hash == daily_hash(
        "source-normalization-candidate-v1", result.draft.model_dump(mode="json")
    )
    assert FIXTURE.read_bytes() == fixture_bytes
