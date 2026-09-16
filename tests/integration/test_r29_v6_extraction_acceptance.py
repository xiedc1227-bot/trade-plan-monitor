from __future__ import annotations

import asyncio
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from scripts import r14_bounded_acceptance as bounded
from scripts import r29_v6_extraction_acceptance as r29
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_source_treatment_review_api import SOURCE as LITERAL_SOURCE
from tests.integration.test_source_treatment_review_api import _literal_mapping

from trade_plan_monitor.ai.models import (
    AIUsageSnapshot,
    ExplicitPlanDraft,
    ExtractionDiagnostic,
    PlanExtractionResult,
    PlanExtractionStatus,
)
from trade_plan_monitor.web.ai_diagnostics import append_extraction_diagnostic
from trade_plan_monitor.web.ai_service import _completed_extraction_view
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000029")
_OPERATION_ID = UUID("00000000-0000-4000-8000-000000000129")
_NOW = datetime(2026, 9, 17, 10, 30, tzinfo=_SHANGHAI)


def _result(
    *,
    draft: ExplicitPlanDraft | None,
    status: PlanExtractionStatus = PlanExtractionStatus.SUCCEEDED,
    diagnostic: ExtractionDiagnostic | None = None,
) -> PlanExtractionResult:
    return PlanExtractionResult(
        request_id=_OPERATION_ID,
        provider_id=_PROVIDER_ID,
        model=bounded.APPROVED_MODEL,
        prompt_version=r29.PROMPT_VERSION,
        source_text_sha256=sha256(LITERAL_SOURCE.encode("utf-8")).hexdigest(),
        draft=draft,
        mapping=None if draft is None else _literal_mapping(draft, supplemented=False),
        usage=AIUsageSnapshot(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        diagnostic=diagnostic
        or ExtractionDiagnostic(
            stage="completed",
            reason="NONE",
            finish_reason="stop",
            model_matches_configured=True,
            attempts=1,
        ),
        status=status,
    )


def _view_and_sidecar(tmp_path: Path, result: PlanExtractionResult):
    sidecar = tmp_path / "monitor.ai-extraction-diagnostics.jsonl"
    append_extraction_diagnostic(
        sidecar,
        result=result,
        configured_model=bounded.APPROVED_MODEL,
        completed_at=_NOW,
    )
    view = _completed_extraction_view(
        result=result,
        submitted_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
        diagnostic_status="RECORDED",
    )
    return view, sidecar


def test_r29_contract_is_v6_one_ai_zero_market_and_globally_bounded() -> None:
    assert r29._eligible(datetime(2026, 9, 16, 13, 30, tzinfo=_SHANGHAI))
    assert r29._eligible(datetime(2026, 9, 16, 15, 0, tzinfo=_SHANGHAI))
    assert not r29._eligible(datetime(2026, 9, 16, 15, 0, 1, tzinfo=_SHANGHAI))
    assert r29.PROMPT_VERSION == "plan-extract-v6"
    assert r29.AI_CAPS == {"LITERAL": 1}
    assert r29.AI_TOTAL == 1
    assert r29.MARKET_TOTAL == 0
    assert all(value == 0 for value in r29.MARKET_CAPS.values())
    assert r29.PROVIDER_TIMEOUT_SECONDS == 30
    assert r29.TOTAL_SECONDS == 45
    assert r29.CLEANUP_SECONDS == 15
    assert r29.AI_OUTPUT_TOKENS == 8192


def test_r29_material_freezes_exact_v6_source_prompt_body_and_review(tmp_path: Path) -> None:
    material = r29._egress_review_material()
    request = material["requests"]["LITERAL"]
    prompt = request["body"]["messages"][0]["content"]

    assert material["destination"] == "https://api.deepseek.com/chat/completions"
    assert tuple(material["requests"]) == ("LITERAL",)
    assert request["sourceText"] == LITERAL_SOURCE
    assert request["sourceSha256"] == r29.EXPECTED_SOURCE_HASH
    assert request["promptSha256"] == r29.EXPECTED_PROMPT_HASH
    assert len(prompt.encode("utf-8")) == r29.EXPECTED_PROMPT_UTF8_BYTES == 19_359
    assert request["body"] == r29._request_body(prompt)
    assert r29._validate_material(material) is True

    english, chinese = r29._write_egress_review_package(tmp_path)
    for document in (english.read_text("utf-8"), chinese.read_text("utf-8")):
        assert LITERAL_SOURCE in document
        assert prompt in document
        assert "plan-extract-v5" in document and "plan-extract-v6" in document
        assert r29.EXPECTED_SOURCE_HASH in document
        assert r29.EXPECTED_PROMPT_HASH in document
        assert "<credential omitted" in document
    assert {
        path.name: r29._file_sha256(path)
        for path in (
            tmp_path / "egress-material.json",
            english,
            chinese,
            tmp_path / "manifest.json",
        )
    } == r29.EXPECTED_REVIEW_HASHES
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["packageSha256"] == (
        "328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda material: material.__setitem__("destination", "https://example.invalid"),
        lambda material: material["requests"]["LITERAL"].__setitem__(
            "sourceText", material["requests"]["LITERAL"]["sourceText"] + "x"
        ),
        lambda material: material["requests"]["LITERAL"]["body"].__setitem__("temperature", 1),
        lambda material: material["requests"]["LITERAL"]["body"]["messages"][0].__setitem__(
            "content",
            material["requests"]["LITERAL"]["body"]["messages"][0]["content"] + "x",
        ),
    ],
)
def test_r29_material_gate_rejects_destination_source_prompt_or_body_change(mutation) -> None:
    material = r29._egress_review_material()
    mutation(material)
    assert r29._validate_material(material) is False


def test_r29_transport_admits_one_exact_v6_post_and_rejects_a_second() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r29.AI_CAPS, seconds=45)
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        prompt_version=r29.PROMPT_VERSION,
        max_output_tokens=r29.AI_OUTPUT_TOKENS,
        max_prompt_utf8_bytes=r29.EXPECTED_PROMPT_UTF8_BYTES,
    )
    body = r29._egress_review_material()["requests"]["LITERAL"]["body"]
    request = httpx.Request("POST", r29.EXTERNAL_DESTINATION, json=body)

    async def scenario() -> None:
        assert (await transport.handle_async_request(request)).status_code == 200
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())
    assert starts == 1
    assert budget.snapshot()["totalAttempts"] == 1
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def test_r29_v6_prompt_requires_its_exact_ceiling_while_old_default_stays_closed() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r29.AI_CAPS, seconds=45)
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        prompt_version=r29.PROMPT_VERSION,
        max_output_tokens=r29.AI_OUTPUT_TOKENS,
    )
    request = httpx.Request(
        "POST",
        r29.EXTERNAL_DESTINATION,
        json=r29._egress_review_material()["requests"]["LITERAL"]["body"],
    )

    async def scenario() -> None:
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())
    assert starts == 0
    assert budget.snapshot()["totalAttempts"] == 0
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def test_r29_success_requires_v6_literal_oracle_and_retains_review_only(tmp_path: Path) -> None:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    view, sidecar = _view_and_sidecar(tmp_path, _result(draft=draft))

    outcome, review = r29._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is True
    assert outcome["oracleStatus"] == "ACCEPTED"
    assert outcome["diagnostic"]["stage"] == "completed"
    assert outcome["diagnostic"]["reason"] == "NONE"
    assert outcome["diagnostic"]["modelMatchesConfigured"] is True
    assert review is not None
    assert LITERAL_SOURCE not in json.dumps(review)
    assert r29._review_receipt_matches(outcome, review, [str(_OPERATION_ID)])
    assert not r29._review_receipt_matches(outcome, review, [])
    assert not r29._review_receipt_matches(outcome, None, [str(_OPERATION_ID)])


def test_r29_oracle_mismatch_stops_without_review_artifact(tmp_path: Path) -> None:
    payload = _draft_payload(complete=False)
    payload["position"]["max_qty"] = 400
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(payload))
    view, sidecar = _view_and_sidecar(tmp_path, _result(draft=draft))

    outcome, review = r29._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is False
    assert outcome["oracleStatus"] == "MISMATCH"
    assert outcome["reason"] == "ORACLE_MISMATCH"
    assert review is None


@pytest.mark.parametrize(
    ("diagnostic", "status", "expected_reason"),
    [
        (
            ExtractionDiagnostic(
                stage="schema",
                reason="SCHEMA",
                path="field_bindings[4]",
                schema_error_type="field_binding_structure_value_invalid",
                finish_reason="stop",
                model_matches_configured=True,
                attempts=1,
            ),
            PlanExtractionStatus.INVALID_OUTPUT,
            "EXTRACTION_FAILED_DIAGNOSTIC_RECORDED",
        ),
        (
            ExtractionDiagnostic(
                stage="response",
                reason="FINISH_REASON",
                finish_reason="length",
                model_matches_configured=True,
                attempts=1,
            ),
            PlanExtractionStatus.INVALID_OUTPUT,
            "EXTRACTION_FAILED_DIAGNOSTIC_RECORDED",
        ),
        (
            ExtractionDiagnostic(
                stage="provider",
                reason="PROVIDER_ERROR",
                path="provider",
                provider_error_code="TIMEOUT",
                timeout_kind="READ",
                timeout_elapsed_ms=30_000,
                attempts=1,
            ),
            PlanExtractionStatus.PROVIDER_ERROR,
            "TIMEOUT_DIAGNOSTIC_RECORDED",
        ),
    ],
)
def test_r29_schema_length_and_timeout_failures_stop_with_safe_diagnostics(
    tmp_path: Path,
    diagnostic: ExtractionDiagnostic,
    status: PlanExtractionStatus,
    expected_reason: str,
) -> None:
    view, sidecar = _view_and_sidecar(
        tmp_path,
        _result(draft=None, status=status, diagnostic=diagnostic),
    )
    outcome, review = r29._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is False
    assert outcome["oracleStatus"] == "NOT_RUN"
    assert outcome["reason"] == expected_reason
    assert review is None
    assert LITERAL_SOURCE not in sidecar.read_text("utf-8")


def test_r29_model_mismatch_and_receipt_uncertainty_stop_without_resubmission(
    tmp_path: Path,
) -> None:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    mismatch = _result(
        draft=draft,
        diagnostic=ExtractionDiagnostic(
            stage="completed",
            reason="NONE",
            finish_reason="stop",
            model_matches_configured=False,
            attempts=1,
        ),
    )
    view, sidecar = _view_and_sidecar(tmp_path, mismatch)
    outcome, review = r29._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )
    assert outcome["accepted"] is False
    assert outcome["reason"] == "MODEL_OR_COMPLETION_RECEIPT_REJECTED"
    assert review is None

    class FailingService:
        calls = 0

        async def submit_plan_extraction(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("synthetic receipt uncertainty")

    service = FailingService()
    uncertain, uncertain_review = asyncio.run(
        r29._submit_and_wait(
            service=service,
            provider_id=_PROVIDER_ID,
            source_text=LITERAL_SOURCE,
            diagnostic_path=tmp_path / "absent.jsonl",
            deadline=0,
        )
    )
    assert service.calls == 1
    assert uncertain["reason"] == "STOP_WITHOUT_RESUBMISSION"
    assert uncertain_review is None


def test_r29_claim_cleanup_and_isolated_database_are_safe(tmp_path: Path) -> None:
    first = r29._claim_session(tmp_path)
    assert first.name == r29.RUN_ID
    with pytest.raises(FileExistsError):
        r29._claim_session(tmp_path)

    stopped: list[str] = []

    class Lifecycle:
        async def stop(self) -> None:
            stopped.append("stopped")

    assert asyncio.run(
        r29._cleanup_with_hard_deadline(
            10_000.0,
            Lifecycle(),
            monotonic=lambda: 9_999.0,
        )
    )
    assert stopped == ["stopped"]

    database = tmp_path / "isolated.sqlite3"
    plans = PersistentPlanWebLifecycle(database_path=database, clock=lambda: _NOW)

    async def initialize_and_stop() -> None:
        await plans.start()
        assert all(count == 0 for count in r29._database_counts(database).values())
        assert await r29._cleanup_with_hard_deadline(
            10_000.0,
            plans,
            monotonic=lambda: 9_999.0,
        )

    asyncio.run(initialize_and_stop())


def test_r29_missing_read_only_config_keeps_preflight_not_ready_without_claim(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "app.yaml"
    preflight = r29._preflight(config_path=missing)

    assert preflight["ready"] is False
    assert preflight["configSourceStatus"] == "MISSING"
    assert not (r29.SESSION_ROOT / "_session_claimed").exists()
