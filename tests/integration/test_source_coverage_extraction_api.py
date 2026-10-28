"""Extraction source summaries describe captured proof, never save/review authority.

The actual parser and Web owner consume static synthetic transport responses.
All persistence is temporary; no real provider or user database is accessed.
"""

import asyncio
import json
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from tests.integration.test_current_plan_api import post
from tests.integration.test_web_api import _FakeLifecycle
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.extraction import _blocking_warning, extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionResult
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_json,
)
from trade_plan_monitor.state.models import PlanVersion
from trade_plan_monitor.state.source_coverage_models import CoverageReviewRow
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle, _completed_extraction_view
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanExtractionView

_AT = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _case(blocked=False):
    draft, source, mapping = _baseline()
    if blocked:
        source, mapping = _append_as_context(
            source,
            mapping,
            "Only buy when turnover exceeds 3 percent.",
            semantic_role="COMMENTARY",
            misclassification=dict(
                disposition="CONTEXT", paths=[], reason="Proposed background, not server proof."
            ),
        )
    return source, dict(
        draft=draft.model_dump(mode="json"),
        clauses=[row.model_dump(mode="json") for row in mapping.clauses],
        bindings=[row.model_dump(mode="json") for row in mapping.bindings],
    )


def _result(blocked=False):
    source, output = _case(blocked)
    identity, config = uuid4(), _config().model_copy(update={"max_input_chars": 200000})

    class StaticProvider:
        async def extract_plan(self, request):
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=json.dumps(output),
                finish_reason="stop",
                attempts=1,
                usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            )

    result = asyncio.run(
        extract_plan(
            request_id=identity, source_text=source, config=config, provider=StaticProvider()
        )
    )
    assert isinstance(result, CurrentPlanExtractionResult)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.coverage.coverage_complete is not blocked
    assert result.normalization_trace is not None
    return source, result


def _view(result):
    return _completed_extraction_view(
        result=result, submitted_at=_AT, started_at=_AT, completed_at=_AT
    ).model_dump(mode="json", by_alias=True)


def _assert_unsaved(summary):
    assert summary["authorityGranted"] is False
    assert summary["currentReviewBound"] is False and summary["canConfirmReview"] is False
    assert summary["reviewId"] is None and summary["reviewRevision"] == 0
    assert summary["coverageRevision"] is None
    assert summary["coverageBundleHash"] is None
    assert summary["coverageReviewReceiptHash"] is None


@pytest.mark.parametrize("blocked", [False, True], ids=["complete", "mandatory-background"])
def test_real_http_extraction_keeps_candidate_and_captured_source_summary(tmp_path, blocked):
    source, output = _case(blocked)
    calls = []

    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json=dict(
                model="deepseek-v4-flash",
                choices=[
                    dict(
                        index=0,
                        message=dict(role="assistant", content=json.dumps(output)),
                        finish_reason="stop",
                    )
                ],
                usage=dict(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            ),
        )

    config = tmp_path / "offline-ai.yaml"
    config.write_text(
        "ai:\n  profile: DEEPSEEK\n  base_url: https://api.deepseek.com\n"
        "  model: deepseek-v4-flash\n  api_key: offline-local-fixture\n"
        "  max_retries: 0\n  max_input_chars: 200000\n",
        encoding="utf-8",
    )
    plans = PersistentPlanWebLifecycle(
        database_path=tmp_path / "extraction.sqlite3", clock=lambda: _AT
    )
    ai = ConfiguredAIWebLifecycle(
        config_path=config,
        review_store=plans,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(transport), trust_env=False
        ),
    )
    app = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_lifecycle_factory=lambda: plans,
        ai_lifecycle_factory=lambda: ai,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        provider = client.get("/api/v1/ai-runtime").json()["providerId"]
        receipt = post(
            client,
            "plan-extractions",
            dict(providerId=provider, sourceText=source, expectedRevision=0),
            expected=202,
        )
        for _ in range(100):
            response = client.get("/api/v1/plan-extractions/" + receipt["operationId"])
            assert response.status_code == 200
            value = response.json()
            if value["status"] not in {"QUEUED", "RUNNING"}:
                break
        assert value["status"] == "SUCCEEDED"
        summary = value["sourceCoverage"]
        assert summary["status"] == ("BLOCKED" if blocked else "COMPLETE")
        assert summary["coverageComplete"] is not blocked
        assert summary["automaticFidelityVerified"] is not blocked
        _assert_unsaved(summary)
        assert value["draftPlanJson"] == daily_draft_json(_baseline()[0])
        assert value["dailyMapping"]["clauses"][-1]["excerpt"] in source
        with plans._session_factory() as session:
            inputs = SourceCoverageStore(session).input(receipt["operationId"])
            assert inputs.initial_coverage.evidence_hash == summary["coverageEvidenceHash"]
            assert inputs.normalization.evidence_hash == summary["normalizationHash"]
            assert session.scalar(select(func.count()).select_from(PlanVersion)) == 0
            assert session.scalar(select(func.count()).select_from(CoverageReviewRow)) == 0
        assert len(calls) == 1


@pytest.mark.parametrize("origin", ["HUMAN", "AI_HISTORICAL"])
@pytest.mark.parametrize("include_trace", [False, True])
def test_projection_of_human_or_historical_assessment_never_claims_automatic_fidelity(
    origin,
    include_trace,
):
    """Pure captured-value projection, not a claim of registered human approval."""
    source, result = _result()
    trace = result.normalization_trace if include_trace else None
    assessment = assess_source_coverage(
        result.draft, result.daily_mapping, source, normalization=trace, origin=origin
    )
    assert assessment.coverage_complete
    value = _view(result.model_copy(update={"coverage": assessment, "normalization_trace": trace}))
    summary = value["sourceCoverage"]
    assert summary["status"] == "COMPLETE" and summary["origin"] == origin
    assert summary["automaticFidelityVerified"] is False
    _assert_unsaved(summary)


def test_redecoded_historical_result_missing_private_inputs_stays_unknown():
    _, actual = _result()
    replay = CurrentPlanExtractionResult.model_validate_json(actual.model_dump_json())
    assert replay.coverage is None and replay.normalization_trace is None
    value = _view(replay)
    assert value["status"] == "SUCCEEDED" and value["draftPlanJson"] is not None
    summary = value["sourceCoverage"]
    assert summary["status"] == "UNKNOWN" and not summary["coverageComplete"]
    assert not summary["automaticFidelityVerified"]
    assert summary["coverageEvidenceHash"] is None
    _assert_unsaved(summary)


def test_lost_new_ai_preimage_cannot_reuse_a_complete_private_label():
    _, actual = _result()
    changed = actual.model_copy(update={"normalization_trace": None})
    summary = _view(changed)["sourceCoverage"]
    assert summary["status"] == "UNKNOWN" and not summary["automaticFidelityVerified"]
    assert summary["reason"] == "SOURCE_COVERAGE_REQUIRED"
    _assert_unsaved(summary)


@pytest.mark.parametrize("frame", ["matching", "wrong-source", "wrong-after", "corrupt-trace"])
def test_rejected_policy_normalization_still_discloses_only_its_matching_captured_changes(frame):
    """Synthetic capture of a forbidden policy edit, not an invented provider repair."""
    source, actual = _result()
    before = actual.draft.model_dump(mode="json")
    changed_json = actual.draft.model_dump(mode="json")
    changed_json["position"]["limit"]["capital_policy"]["cap_fen"] += 100
    changed = type(actual.draft).model_validate(changed_json)
    mapping = actual.daily_mapping.model_copy(
        update={
            "candidate_content_hash": daily_draft_content_sha256(changed),
        }
    )
    trace = capture_normalization(before, changed.model_dump(mode="json"), source)
    assessment = assess_source_coverage(
        changed, mapping, source, normalization=trace, origin="AI_NEW"
    )
    assert assessment.status == "BLOCKED" and assessment.normalization_hash is None
    assert len(trace.changes) == 1
    assert any(issue.code == "SOURCE_NORMALIZATION_LOSS" for issue in assessment.issues)
    if frame == "wrong-source":
        trace = capture_normalization(
            before, changed.model_dump(mode="json"), "Another source frame"
        )
    elif frame == "wrong-after":
        trace = capture_normalization(before, before, source)
    result = actual.model_copy(
        update={
            "draft": changed,
            "daily_mapping": mapping,
            "coverage": assessment,
            "normalization_trace": trace,
            "validation_issues": tuple(
                _blocking_warning(row.code, row.path, row.message) for row in assessment.issues
            ),
        }
    )
    if frame == "corrupt-trace":
        # Fault injection after valid capture; ordinary constructors already reject it.
        object.__setattr__(result.normalization_trace, "evidence_hash", "f" * 64)
    summary = _view(result)["sourceCoverage"]
    if frame == "matching":
        assert summary["status"] == "BLOCKED"
        assert summary["normalizationChangeCount"] == len(trace.changes) == 1
        assert summary["coverageEvidenceHash"] == assessment.evidence_hash
    else:
        assert summary["status"] == "UNKNOWN" and summary["reason"] == "SOURCE_COVERAGE_STALE"
        assert summary["normalizationChangeCount"] == 0
        assert summary["coverageEvidenceHash"] is None
    assert summary["normalizationHash"] is None and not summary["automaticFidelityVerified"]
    _assert_unsaved(summary)


@pytest.mark.parametrize("change", ["source", "candidate"])
def test_mismatching_private_source_or_candidate_proof_stays_visible_but_unknown(change):
    _, actual = _result()
    updates = (
        {"source_text_sha256": "f" * 64}
        if change == "source"
        else {
            "draft": actual.draft.model_copy(update={"name": "Changed candidate display"}),
        }
    )
    value = _view(actual.model_copy(update=updates))
    assert value["status"] == "SUCCEEDED" and value["draftPlanJson"] is not None
    summary = value["sourceCoverage"]
    assert summary["status"] == "UNKNOWN" and summary["reason"] == "SOURCE_COVERAGE_STALE"
    assert not summary["automaticFidelityVerified"] and summary["coverageEvidenceHash"] is None
    _assert_unsaved(summary)


@pytest.mark.parametrize(
    "status", ["QUEUED", "RUNNING", "INVALID_OUTPUT", "PROVIDER_ERROR", "CANCELLED"]
)
def test_unfinished_or_failed_dto_cannot_carry_a_source_proof(status):
    _, actual = _result()
    summary = _view(actual)["sourceCoverage"]
    body = dict(
        id=str(UUID(int=1)),
        providerId=str(UUID(int=2)),
        status=status,
        submittedAt=_AT.isoformat(),
        sourceCoverage=summary,
    )
    if status not in {"QUEUED", "CANCELLED"}:
        body["startedAt"] = _AT.isoformat()
    if status not in {"QUEUED", "RUNNING"}:
        body["completedAt"] = _AT.isoformat()
    with pytest.raises(ValidationError):
        PlanExtractionView.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("grant", ["confirmation", "current-review", "saved-bundle"])
def test_extraction_dto_rejects_a_saved_review_or_bundle_claim(grant):
    _, actual = _result()
    value = _view(actual)
    summary = value["sourceCoverage"]
    summary.update(coverageRevision=1, coverageBundleHash="a" * 64)
    if grant == "confirmation":
        summary["canConfirmReview"] = True
    elif grant == "current-review":
        summary.update(
            currentReviewBound=True,
            reviewId=str(UUID(int=7)),
            reviewRevision=1,
            coverageReviewReceiptHash="b" * 64,
            reviewState="CURRENT",
        )
    with pytest.raises(ValidationError):
        PlanExtractionView.model_validate_json(json.dumps(value))


def test_old_status_dto_preserves_absence_of_the_additive_source_field():
    body = dict(
        id=str(UUID(int=1)),
        providerId=str(UUID(int=2)),
        status="QUEUED",
        submittedAt=_AT.isoformat(),
    )
    value = PlanExtractionView.model_validate_json(json.dumps(body))
    assert "sourceCoverage" not in value.model_dump(mode="json", by_alias=True)
