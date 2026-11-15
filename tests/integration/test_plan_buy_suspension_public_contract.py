"""Public current JSON carriers preserve the exact reviewed PBS contract."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.integration.test_daily_plan_chain import Chain, OfflineRuntime
from tests.integration.test_plan_buy_suspension_activation import guard_draft, public_review
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_plan_buy_suspension_extraction import FIXTURE, suspension_output

from trade_plan_monitor.ai.extraction import _review_current_output
from trade_plan_monitor.ai.plan_extraction import BuySuspensionPlanExtractionOutput
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_json,
    daily_draft_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256, unified_plan_content_sha256
from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementIntent
from trade_plan_monitor.web.ai_service import _completed_extraction_view
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.routers.daily_plans import DailyReviewPreview
from trade_plan_monitor.web.routers.plans import PlanVersionView


@pytest.fixture(params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def public_chain(tmp_path, request):
    chain = Chain(tmp_path)
    chain.app = create_app(
        runtime_factory=lambda: OfflineRuntime(chain),
        plan_lifecycle_factory=lambda: chain.plans,
        monitor_contract_version=request.param,
        read_service=SimpleNamespace(monitor_contract_version=request.param),
    )
    chain.client = TestClient(chain.app, base_url="http://127.0.0.1:8765",
        headers={"X-Monitor-Contract-Version": str(request.param)})
    with chain.client:
        yield chain


def test_public_capability_and_editor_describe_the_exact_current_pbs_family(public_chain):
    capability = public_chain.client.get("/api/v1/plan-capabilities").json()
    assert capability["schemaVersion"] == 5
    assert capability["executionVersion"] == "condition-plan-v1"
    assert capability["supportedSchemaVersions"] == [5, 6, 7, 8, 9, 10]
    assert capability["buySuspensionExecutionVersion"] == "condition-plan-v6"
    editor = public_chain.client.get("/api/v1/plan-editor-schema").json()
    assert editor["candidateSchema"]["properties"]["schema_version"]["const"] == 5
    assert editor["supportedSchemaVersions"] == [5, 6, 7, 8, 9, 10]
    candidate = editor["buySuspensionCandidateSchema"]
    props = candidate["properties"]
    assert props["schema_version"]["const"] == 10
    assert props["execution_version"]["const"] == "condition-plan-v6"
    assert "buy_suspension" in props
    assert {"reference_market", "exception_policy", "capital_policy"}.isdisjoint(props)


def test_saved_current_plan_and_preview_roundtrip_every_field_and_content_hash(public_chain):
    draft = guard_draft(public_chain)
    saved, activation = public_review(public_chain, draft)
    canonical = daily_draft_json(draft)
    for body in (saved, public_chain.client.get("/api/v1/plan-versions/" + saved["id"]).json()):
        parsed = PlanVersionView.model_validate_json(json.dumps(body))
        assert parsed.plan_json == canonical == body["planJson"]
        restored = load_daily_draft_json(parsed.plan_json)
        assert restored == draft
        assert restored.model_dump(mode="json") == draft.model_dump(mode="json")
        assert daily_draft_sha256(restored) == parsed.plan_hash == (
            plan_sha256(draft.to_executable()))
        assert daily_draft_content_sha256(restored) == parsed.content_hash == (
            unified_plan_content_sha256(draft.to_executable()))
        assert json.loads(parsed.model_dump_json(by_alias=True))["planJson"] == canonical
    public_chain.post("plan-activations", activation)
    public_chain.plan = draft.to_executable()
    replacement = guard_draft(public_chain, plan_id="pbs-public-retirement", retire=True)
    replacement_saved, command = public_review(
        public_chain, replacement, replacement=True, retire=True)
    preview = public_chain.post("plan-review-previews", dict(
        candidateJson=replacement_saved["planJson"], sourceText=replacement_saved["sourceText"],
        mapping=replacement_saved["dailyMapping"]))
    typed = DailyReviewPreview.model_validate_json(json.dumps(preview))
    intent = typed.buy_suspension_replacement_intent
    assert type(intent) is BuySuspensionReplacementIntent
    assert intent.source_hash == replacement_saved["sourceHash"]
    assert intent.candidate_content_hash == replacement_saved["contentHash"]
    assert intent.retire_predecessor_guard and intent.acknowledge_unverified_predecessor
    assert intent.strategy_effective_from == public_chain.now
    assert intent.authority_granted is False
    assert typed.candidate_json == daily_draft_json(replacement)
    assert json.loads(typed.model_dump_json(by_alias=True)) == preview
    # Review/supplement receipts do not activate the proposed replacement.
    assert public_chain.client.get("/api/v1/plan-activation-states/" + draft.symbol).json()[
        "planVersionId"] == saved["id"]
    assert command["planVersionId"] == replacement_saved["id"]


def test_real_reviewed_workbench_reader_rejects_pbs_before_frozen_selection(public_chain):
    draft = guard_draft(public_chain)
    saved, _ = public_review(public_chain, draft)
    with pytest.raises(ValidationError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        public_chain.plans._get_reviewed_backtest_plan_sync(version_id=saved["id"])


def public_extraction_fixture():
    """The actual server projection, with deterministic synthetic identities and source."""
    request_id = UUID("51e37676-d62d-4bbc-873a-2b389f8d4611")
    config = _config().model_copy(update={"prompt_version": "plan-extract-v13"})
    output = BuySuspensionPlanExtractionOutput.model_validate_json(json.dumps(suspension_output()))
    raw = RawAIResponse(request_id=request_id, provider_id=config.provider_id, model=config.model,
        content=output.model_dump_json(), finish_reason="stop", attempts=1,
        usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20))
    result = _review_current_output(output, FIXTURE["explicit"], request_id, config, raw)
    at = datetime.fromisoformat("2026-11-15T10:00:00+08:00")
    return _completed_extraction_view(result=result, submitted_at=at, started_at=at,
        completed_at=at).model_dump(mode="json", by_alias=True)


def test_frontend_v13_fixture_is_the_actual_server_projection_with_no_loss_or_authority():
    root = Path(__file__).resolve().parents[2]
    wire = json.loads((root / "web/tests/fixtures/ai-buy-suspension-extraction.json").read_bytes())
    assert wire == public_extraction_fixture()
    draft = load_daily_draft_json(wire["draftPlanJson"])
    assert draft.schema_version == 10 and draft.execution_version == "condition-plan-v6"
    assert draft.buy_suspension.condition.price_fen == 2420
    assert draft.buy_suspension.effective_from.isoformat() == "2026-09-30T09:30:00+08:00"
    assert wire["dailyMapping"]["candidate_content_hash"] == daily_draft_content_sha256(draft)
    assert wire["sourceCoverage"]["candidatePlanHash"] == daily_draft_sha256(draft)
    assert wire["sourceCoverage"]["authorityGranted"] is False
    assert wire["sourceCoverage"]["currentReviewBound"] is False
