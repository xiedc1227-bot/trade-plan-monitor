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
from scripts import ai_timeout_diagnostic as r27
from scripts import bounded_live_acceptance as bounded
from scripts import plan_extraction_acceptance as r25
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_source_treatment_review_api import (
    SOURCE as LITERAL_SOURCE,
)
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
_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000027")
_OPERATION_ID = UUID("00000000-0000-4000-8000-000000000127")
_NOW = datetime(2026, 9, 16, 10, 30, tzinfo=_SHANGHAI)


def test_r27_contract_is_one_ai_zero_market_and_globally_bounded() -> None:
    assert r27._eligible(datetime(2026, 9, 16, 10, 0, tzinfo=_SHANGHAI))
    assert r27._eligible(datetime(2026, 9, 16, 12, 0, tzinfo=_SHANGHAI))
    assert not r27._eligible(datetime(2026, 9, 16, 12, 0, 1, tzinfo=_SHANGHAI))
    assert r27.CASE_ID == "LITERAL"
    assert r27.AI_CAPS == {"LITERAL": 1}
    assert r27.AI_TOTAL == 1
    assert r27.MARKET_TOTAL == 0
    assert all(value == 0 for value in r27.MARKET_CAPS.values())
    assert r27.PROVIDER_TIMEOUT_SECONDS == 30
    assert r27.TOTAL_SECONDS == 45
    assert r27.CLEANUP_SECONDS == 15
    assert r27.AI_OUTPUT_TOKENS == 8192


def test_r27_material_is_byte_identical_to_approved_r25_literal_subset(
    tmp_path: Path,
) -> None:
    material = r27._egress_review_material()
    approved = r25._egress_review_material()["requests"]["LITERAL"]
    request = material["requests"]["LITERAL"]

    assert material["destination"] == "https://api.deepseek.com/chat/completions"
    assert tuple(material["requests"]) == ("LITERAL",)
    assert request["sourceText"].encode("utf-8") == approved["sourceText"].encode("utf-8")
    assert request["body"] == approved["body"]
    assert request["sourceSha256"] == r27.EXPECTED_SOURCE_HASH
    assert request["promptSha256"] == r27.EXPECTED_PROMPT_HASH
    assert r27._validate_material(material) is True

    english, chinese = r27._write_egress_review_package(tmp_path)
    for document in (english.read_text("utf-8"), chinese.read_text("utf-8")):
        assert request["sourceText"] in document
        assert request["body"]["messages"][0]["content"] in document
        assert "R25" in document
        assert "once" in document or "一次" in document
        assert "<credential omitted" in document


@pytest.mark.parametrize(
    "mutation",
    [
        lambda material: material["requests"]["LITERAL"].__setitem__(
            "sourceText", material["requests"]["LITERAL"]["sourceText"] + "x"
        ),
        lambda material: material["requests"]["LITERAL"]["body"].__setitem__(
            "temperature", 1
        ),
        lambda material: material["requests"]["LITERAL"]["body"]["messages"][0].__setitem__(
            "content",
            material["requests"]["LITERAL"]["body"]["messages"][0]["content"] + "x",
        ),
    ],
)
def test_r27_material_gate_rejects_any_source_prompt_or_body_change(mutation) -> None:
    material = r27._egress_review_material()
    mutation(material)
    assert r27._validate_material(material) is False


def test_r27_transport_admits_one_exact_post_and_rejects_a_second() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r27.AI_CAPS, seconds=45)
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        prompt_version=r27.PROMPT_VERSION,
        max_output_tokens=r27.AI_OUTPUT_TOKENS,
    )
    body = r27._egress_review_material()["requests"]["LITERAL"]["body"]
    request = httpx.Request("POST", r27.EXTERNAL_DESTINATION, json=body)

    async def scenario() -> None:
        response = await transport.handle_async_request(request)
        assert response.status_code == 200
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())

    assert starts == 1
    assert budget.snapshot()["totalAttempts"] == 1
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def _write_result_diagnostic(tmp_path: Path, result: PlanExtractionResult) -> Path:
    path = tmp_path / "monitor.ai-extraction-diagnostics.jsonl"
    append_extraction_diagnostic(
        path,
        result=result,
        configured_model=bounded.APPROVED_MODEL,
        completed_at=_NOW,
    )
    return path


def test_r27_success_runs_literal_oracle_and_retains_review_only(tmp_path: Path) -> None:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    result = PlanExtractionResult(
        request_id=_OPERATION_ID,
        provider_id=_PROVIDER_ID,
        model=bounded.APPROVED_MODEL,
        prompt_version=r27.PROMPT_VERSION,
        source_text_sha256=sha256(LITERAL_SOURCE.encode("utf-8")).hexdigest(),
        draft=draft,
        mapping=_literal_mapping(draft, supplemented=False),
        usage=AIUsageSnapshot(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        diagnostic=ExtractionDiagnostic(
            stage="completed",
            reason="NONE",
            finish_reason="stop",
            model_matches_configured=True,
            attempts=1,
        ),
        status=PlanExtractionStatus.SUCCEEDED,
    )
    sidecar = _write_result_diagnostic(tmp_path, result)
    view = _completed_extraction_view(
        result=result,
        submitted_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
        diagnostic_status="RECORDED",
    )

    outcome, review = r27._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is True
    assert outcome["oracleStatus"] == "ACCEPTED"
    assert outcome["diagnostic"]["version"] == 3
    assert outcome["diagnostic"]["usageAvailable"] is True
    assert outcome["diagnostic"]["modelMatchesConfigured"] is True
    assert review is not None
    assert LITERAL_SOURCE not in json.dumps(review)


def test_r27_reader_remains_compatible_with_legacy_v2_sidecars(tmp_path: Path) -> None:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    result = PlanExtractionResult(
        request_id=_OPERATION_ID,
        provider_id=_PROVIDER_ID,
        model=bounded.APPROVED_MODEL,
        prompt_version=r27.PROMPT_VERSION,
        source_text_sha256=sha256(LITERAL_SOURCE.encode("utf-8")).hexdigest(),
        draft=draft,
        mapping=_literal_mapping(draft, supplemented=False),
        usage=AIUsageSnapshot(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        diagnostic=ExtractionDiagnostic(
            stage="completed",
            reason="NONE",
            finish_reason="stop",
            model_matches_configured=True,
            attempts=1,
        ),
        status=PlanExtractionStatus.SUCCEEDED,
    )
    sidecar = _write_result_diagnostic(tmp_path, result)
    legacy = json.loads(sidecar.read_text("utf-8"))
    legacy["version"] = 2
    legacy.pop("transientKind")
    sidecar.write_text(json.dumps(legacy), encoding="utf-8")
    view = _completed_extraction_view(
        result=result,
        submitted_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
        diagnostic_status="RECORDED",
    )

    outcome, review = r27._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is True
    assert outcome["diagnostic"]["version"] == 2
    assert outcome["diagnostic"]["transientKind"] is None
    assert review is not None


def test_r27_reader_rejects_untrusted_v3_transient_kind_without_copying_it() -> None:
    secret = "SECRET-untrusted-transient-kind"
    record = {
        "version": 3,
        "providerErrorCode": "TRANSIENT",
        "transientKind": secret,
        "usage": None,
    }

    safe = r27._safe_diagnostic(record)

    assert r27._supported_diagnostic_record(record) is False
    assert safe is not None
    assert safe["transientKind"] == "UNKNOWN"
    assert secret not in json.dumps(safe)


@pytest.mark.parametrize(
    "timeout_kind",
    ["CONNECT", "READ", "WRITE", "POOL", "OVERALL_DEADLINE", "UNKNOWN"],
)
def test_r27_records_each_v2_timeout_kind_without_content(
    tmp_path: Path,
    timeout_kind: str,
) -> None:
    result = PlanExtractionResult(
        request_id=_OPERATION_ID,
        provider_id=_PROVIDER_ID,
        model=bounded.APPROVED_MODEL,
        prompt_version=r27.PROMPT_VERSION,
        source_text_sha256=sha256(LITERAL_SOURCE.encode("utf-8")).hexdigest(),
        draft=None,
        mapping=None,
        usage=None,
        diagnostic=ExtractionDiagnostic(
            stage="provider",
            reason="PROVIDER_ERROR",
            path="provider",
            provider_error_code="TIMEOUT",
            timeout_kind=timeout_kind,
            timeout_elapsed_ms=30_000,
            attempts=1,
        ),
        status=PlanExtractionStatus.PROVIDER_ERROR,
    )
    sidecar = _write_result_diagnostic(tmp_path, result)
    view = _completed_extraction_view(
        result=result,
        submitted_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
        diagnostic_status="RECORDED",
    )

    outcome, review = r27._assess_terminal(
        source_text=LITERAL_SOURCE,
        view=view,
        diagnostic_path=sidecar,
    )

    assert outcome["accepted"] is False
    assert outcome["oracleStatus"] == "NOT_RUN"
    assert outcome["diagnostic"]["timeoutKind"] == timeout_kind
    assert outcome["diagnostic"]["timeoutElapsedMs"] == 30_000
    assert outcome["diagnostic"]["usageAvailable"] is False
    assert review is None
    assert LITERAL_SOURCE not in sidecar.read_text("utf-8")


def test_r27_cleanup_stops_every_lifecycle_and_database_stays_business_empty(
    tmp_path: Path,
) -> None:
    stopped: list[str] = []

    class Lifecycle:
        def __init__(self, name: str) -> None:
            self.name = name

        async def stop(self) -> None:
            stopped.append(self.name)

    cleaned = asyncio.run(
        r27._cleanup_with_hard_deadline(
            10_000.0,
            Lifecycle("ai"),
            Lifecycle("plans"),
            monotonic=lambda: 9_999.0,
        )
    )

    assert cleaned is True
    assert stopped == ["ai", "plans"]

    database = tmp_path / "isolated.sqlite3"
    plans = PersistentPlanWebLifecycle(database_path=database, clock=lambda: _NOW)

    async def initialize_and_stop() -> None:
        await plans.start()
        assert all(count == 0 for count in r27._database_counts(database).values())
        assert await r27._cleanup_with_hard_deadline(
            10_000.0,
            plans,
            monotonic=lambda: 9_999.0,
        )

    asyncio.run(initialize_and_stop())


def test_r27_claim_is_new_and_second_claim_is_refused(tmp_path: Path) -> None:
    first = r27._claim_session(tmp_path)
    assert first.name == r27.RUN_ID
    with pytest.raises(FileExistsError):
        r27._claim_session(tmp_path)
