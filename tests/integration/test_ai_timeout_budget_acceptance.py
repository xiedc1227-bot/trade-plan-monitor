from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from scripts import ai_timeout_budget_acceptance as r30
from scripts import bounded_live_acceptance as bounded
from scripts import plan_extraction_v6_acceptance as r29
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_source_treatment_review_api import SOURCE as LITERAL_SOURCE
from tests.integration.test_source_treatment_review_api import _literal_mapping

from trade_plan_monitor.ai import openai_compatible
from trade_plan_monitor.ai.models import ExplicitPlanDraft

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000030")


def _config(path: Path) -> Path:
    path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek
  base_url: https://api.deepseek.com
  model: deepseek-flash
  api_key: offline-r30-key
  timeout_seconds: 30
  max_retries: 0
  max_input_chars: 50000
  max_output_tokens: 8192
  temperature: 0
  prompt_version: plan-extract-v5
  additional_models:
    - display_name: DeepSeek V4 Pro
      model: deepseek-v4-pro
""",
        encoding="utf-8",
    )
    return path


def _provider_payload() -> dict[str, object]:
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    mapping = _literal_mapping(draft, supplemented=False)
    content = {
        "draft": draft.model_dump(mode="json"),
        "mapping_version": "plan-mapping-v1",
        "source_clauses": [item.model_dump(mode="json") for item in mapping.source_clauses],
        "field_bindings": [item.model_dump(mode="json") for item in mapping.field_bindings],
        "assumptions": [],
        "warnings": [],
    }
    return {
        "model": bounded.APPROVED_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 5_161,
            "completion_tokens": 4_340,
            "total_tokens": 9_501,
        },
    }


def test_r30_contract_changes_only_local_wait_budget_from_r29() -> None:
    assert r30._eligible(datetime(2026, 9, 17, 0, 0, tzinfo=_SHANGHAI))
    assert r30._eligible(datetime(2026, 9, 17, 23, 59, 59, tzinfo=_SHANGHAI))
    assert not r30._eligible(datetime(2026, 9, 18, 0, 0, tzinfo=_SHANGHAI))
    assert r30.PROMPT_VERSION == r29.PROMPT_VERSION == "plan-extract-v6"
    assert r30.AI_CAPS == {"LITERAL": 1}
    assert r30.AI_TOTAL == 1
    assert r30.MARKET_TOTAL == 0
    assert all(value == 0 for value in r30.MARKET_CAPS.values())
    assert r30.TRANSPORT_TIMEOUT_SECONDS == 30
    assert r30.READ_TIMEOUT_SECONDS == 60
    assert r30.PROVIDER_TIMEOUT_SECONDS == 65
    assert r30.TERMINAL_WAIT_SECONDS == 66
    assert r30.CLEANUP_SECONDS == 15
    assert r30.TOTAL_SECONDS == 81
    assert r30.AI_OUTPUT_TOKENS == r29.AI_OUTPUT_TOKENS == 8192


def test_r30_material_is_byte_identical_to_r29_request_and_records_local_delta(
    tmp_path: Path,
) -> None:
    material = r30._egress_review_material()
    r30_request = material["requests"]["LITERAL"]
    r29_request = r29._egress_review_material()["requests"]["LITERAL"]

    assert r30_request["sourceText"].encode() == r29_request["sourceText"].encode()
    assert r30_request["body"]["messages"][0]["content"].encode() == (
        r29_request["body"]["messages"][0]["content"].encode()
    )
    assert r30_request["body"] == r29_request["body"]
    assert r30_request["bodyCanonicalSha256"] == r30.EXPECTED_REQUEST_BODY_HASH
    assert material["comparisonWithR29"]["sentFieldsChanged"] == []
    assert r30._validate_material(material) is True

    english, chinese = r30._write_egress_review_package(tmp_path)
    for review in (english.read_text("utf-8"), chinese.read_text("utf-8")):
        assert LITERAL_SOURCE in review
        assert r30.EXPECTED_PROMPT_HASH in review
        assert r30.EXPECTED_REQUEST_BODY_HASH in review
        assert r30.R29_PACKAGE_HASH in review
        assert "https://api.deepseek.com/chat/completions" in review
        assert "offline-r30-key" not in review
    assert {
        path.name: r30._file_sha256(path)
        for path in (
            tmp_path / "egress-material.json",
            english,
            chinese,
            tmp_path / "manifest.json",
        )
    } == r30.EXPECTED_REVIEW_HASHES
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["packageSha256"] == (
        "282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10"
    )


def test_r30_transport_allows_one_exact_post_and_rejects_second() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r30.AI_CAPS, seconds=r30.TOTAL_SECONDS)
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        prompt_version=r30.PROMPT_VERSION,
        max_output_tokens=r30.AI_OUTPUT_TOKENS,
        max_prompt_utf8_bytes=r30.EXPECTED_PROMPT_UTF8_BYTES,
    )
    request = httpx.Request(
        "POST",
        r30.EXTERNAL_DESTINATION,
        json=r30._egress_review_material()["requests"]["LITERAL"]["body"],
    )

    async def scenario() -> None:
        assert (await transport.handle_async_request(request)).status_code == 200
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())
    assert starts == 1
    assert budget.snapshot()["totalAttempts"] == 1
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def test_r30_scaled_late_response_reaches_production_schema_mapping_and_oracle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _config(tmp_path / "app.yaml")
    session_root = tmp_path / "session"
    starts = 0
    timeout_shape: dict[str, float] = {}
    real_timeout = asyncio.timeout

    monkeypatch.setattr(
        openai_compatible.asyncio,
        "timeout",
        lambda seconds: real_timeout(float(seconds) / 1_000),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        timeout_shape.update(request.extensions["timeout"])
        await asyncio.sleep(0.04)
        return httpx.Response(200, json=_provider_payload())

    result = asyncio.run(
        r30._run_candidate(
            config_path=config_path,
            session_root=session_root,
            ai_inner_transport=httpx.MockTransport(handler),
        )
    )

    folder = session_root / r30.RUN_ID
    audit = json.loads((folder / "audit.json").read_text("utf-8"))
    journal = json.loads((folder / "physical-attempts.json").read_text("utf-8"))
    review = json.loads((folder / "validated-review-result.json").read_text("utf-8"))

    assert result == 0
    assert starts == 1
    assert timeout_shape == {"connect": 30.0, "read": 60.0, "write": 30.0, "pool": 30.0}
    assert audit["status"] == "LITERAL_V6_EXTRACTION_SUCCEEDED_REVIEW_REQUIRED"
    assert audit["case"]["accepted"] is True
    assert audit["case"]["oracleStatus"] == "ACCEPTED"
    assert audit["case"]["diagnostic"]["stage"] == "completed"
    assert audit["ai"]["totalAttempts"] == 1
    assert audit["market"]["totalAttempts"] == 0
    assert audit["cleanupStatus"] == "COMPLETE"
    assert all(count == 0 for count in audit["databaseCounts"].values())
    assert journal["status"] == audit["status"]
    assert journal["normalAuditPresent"] is True
    assert review["humanReviewStatus"] == "REQUIRED_NOT_PERFORMED"
    assert review["activationAllowed"] is False
    assert review["result"] is not None
    assert "offline-r30-key" not in json.dumps(audit)


def test_r30_transient_transport_failure_records_safe_category_and_stops_once(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path / "app.yaml")
    session_root = tmp_path / "session"
    starts = 0
    secret = "SECRET-r30-transport-detail"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        raise httpx.ConnectError(secret, request=request)

    result = asyncio.run(
        r30._run_candidate(
            config_path=config_path,
            session_root=session_root,
            ai_inner_transport=httpx.MockTransport(handler),
        )
    )

    folder = session_root / r30.RUN_ID
    audit_text = (folder / "audit.json").read_text("utf-8")
    diagnostic_text = (folder / "monitor.ai-extraction-diagnostics.jsonl").read_text("utf-8")
    audit = json.loads(audit_text)
    diagnostic = json.loads(diagnostic_text)

    assert result == 1
    assert starts == 1
    assert audit["status"] == "AI_ACCEPTANCE_FAILED"
    assert audit["case"]["diagnostic"]["providerErrorCode"] == "TRANSIENT"
    assert audit["case"]["diagnostic"]["transientKind"] == "CONNECT"
    assert diagnostic["version"] == 3
    assert diagnostic["transientKind"] == "CONNECT"
    assert audit["ai"]["totalAttempts"] == 1
    assert audit["ai"]["deniedBeforeNetwork"] == 0
    assert audit["market"]["totalAttempts"] == 0
    assert audit["cleanupStatus"] == "COMPLETE"
    assert all(count == 0 for count in audit["databaseCounts"].values())
    assert secret not in audit_text
    assert secret not in diagnostic_text


def test_r30_unknown_receipt_stops_without_resubmission(tmp_path: Path) -> None:
    class FailingService:
        calls = 0

        async def submit_plan_extraction(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("synthetic receipt uncertainty with SECRET")

    service = FailingService()
    outcome, review = asyncio.run(
        r30._submit_and_wait(
            service=service,
            provider_id=_PROVIDER_ID,
            source_text=LITERAL_SOURCE,
            diagnostic_path=tmp_path / "absent.jsonl",
            deadline=0,
        )
    )

    assert service.calls == 1
    assert outcome["reason"] == "STOP_WITHOUT_RESUBMISSION"
    assert outcome["diagnostic"] is None
    assert review is None
    assert "SECRET" not in json.dumps(outcome)


def test_r30_missing_config_is_offline_not_ready_and_does_not_claim(tmp_path: Path) -> None:
    missing = tmp_path / "app.yaml"
    preflight = r30._preflight(config_path=missing)

    assert preflight["ready"] is False
    assert preflight["mode"] == "DRY_RUN_NO_NETWORK"
    assert preflight["configSourceStatus"] == "MISSING"
    assert preflight["freshClaimAvailable"] is True
    assert not (r30.SESSION_ROOT / "_session_claimed").exists()
    assert preflight["balanceOrModelListProbeAllowed"] is False
