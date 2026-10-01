from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from scripts import ai_timeout_budget_acceptance as r30
from scripts import ai_transient_acceptance as r32
from scripts import bounded_live_acceptance as bounded
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_source_treatment_review_api import SOURCE as LITERAL_SOURCE
from tests.integration.test_source_treatment_review_api import _literal_mapping

from trade_plan_monitor.ai import openai_compatible
from trade_plan_monitor.ai.models import ExplicitPlanDraft

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000032")


def _config(path: Path) -> Path:
    path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek
  base_url: https://api.deepseek.com
  model: deepseek-flash
  api_key: offline-r32-key
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


def test_r32_contract_uses_new_identity_and_keeps_the_r30_request_and_budgets() -> None:
    assert r32.PROPOSAL_ID == "R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1"
    assert r32.RUN_ID == "r32-20260917-a"
    assert r32.PROPOSAL_ID != r30.PROPOSAL_ID
    assert r32.RUN_ID != r30.RUN_ID
    assert r32.SESSION_ROOT != r30.SESSION_ROOT
    assert r32.REVIEW_ROOT != r30.REVIEW_ROOT
    assert r32._eligible(datetime(2026, 9, 17, 0, 0, tzinfo=_SHANGHAI))
    assert not r32._eligible(datetime(2026, 9, 18, 0, 0, tzinfo=_SHANGHAI))
    assert r32.EXPECTED_REQUEST_BODY_HASH == r30.EXPECTED_REQUEST_BODY_HASH
    assert r32.EXPECTED_SOURCE_HASH == r30.EXPECTED_SOURCE_HASH
    assert r32.EXPECTED_PROMPT_HASH == r30.EXPECTED_PROMPT_HASH
    assert r32.EXPECTED_PROMPT_UTF8_BYTES == r30.EXPECTED_PROMPT_UTF8_BYTES
    assert r32.AI_CAPS == {"LITERAL": 1}
    assert r32.AI_TOTAL == 1
    assert r32.MARKET_TOTAL == 0
    assert all(value == 0 for value in r32.MARKET_CAPS.values())
    assert r32.TRANSPORT_TIMEOUT_SECONDS == 30
    assert r32.READ_TIMEOUT_SECONDS == 60
    assert r32.PROVIDER_TIMEOUT_SECONDS == 65
    assert r32.TERMINAL_WAIT_SECONDS == 66
    assert r32.CLEANUP_SECONDS == 15
    assert r32.TOTAL_SECONDS == 81


def test_r32_material_is_byte_identical_to_r30_and_manifest_detects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = r32._egress_review_material()
    r32_request = material["requests"]["LITERAL"]
    r30_request = r30._egress_review_material()["requests"]["LITERAL"]

    assert r32_request["sourceText"].encode() == r30_request["sourceText"].encode()
    assert r32_request["body"]["messages"][0]["content"].encode() == (
        r30_request["body"]["messages"][0]["content"].encode()
    )
    assert r32_request["body"] == r30_request["body"]
    assert r32_request["bodyCanonicalSha256"] == r32.EXPECTED_REQUEST_BODY_HASH
    assert material["comparisonWithR30"]["sentFieldsChanged"] == []
    assert material["limits"]["stopOnEveryTerminalResultIncludingUnknown"] is True
    assert material["historicalPriceSnapshot"]["notCurrentPriceGuarantee"] is True
    assert material["historicalPriceSnapshot"]["notAHardCostGate"] is True
    assert r32._validate_material(material) is True

    english, chinese = r32._write_egress_review_package(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for review in (english.read_text("utf-8"), chinese.read_text("utf-8")):
        assert LITERAL_SOURCE in review
        assert r32.EXPECTED_PROMPT_HASH in review
        assert r32.EXPECTED_REQUEST_BODY_HASH in review
        assert r32.R30_PACKAGE_HASH in review
        assert "POST https://api.deepseek.com/chat/completions" in review
        assert "offline-r32-key" not in review
    components = {
        path.name: r32._file_sha256(path)
        for path in (tmp_path / "egress-material.json", english, chinese)
    }
    assert manifest["components"] == components
    package_digest = sha256()
    for name in manifest["packageOrder"]:
        package_digest.update((tmp_path / name).read_bytes())
    assert manifest["packageSha256"] == package_digest.hexdigest() == r32.EXPECTED_PACKAGE_HASH
    assert {
        **components,
        "manifest.json": r32._file_sha256(manifest_path),
    } == r32.EXPECTED_REVIEW_HASHES

    expected = {**components, "manifest.json": r32._file_sha256(manifest_path)}
    monkeypatch.setattr(r32, "EXPECTED_REVIEW_HASHES", expected)
    assert r32._review_package_matches(tmp_path) is True
    english.write_text(english.read_text("utf-8") + "tampered\n", encoding="utf-8")
    assert r32._review_package_matches(tmp_path) is False


def test_r32_default_invocation_is_offline_and_does_not_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_root = tmp_path / "session"
    monkeypatch.setattr(r32, "SESSION_ROOT", session_root)
    monkeypatch.setattr(r32, "_run_candidate", lambda **_kwargs: pytest.fail("must not execute"))

    assert r32.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "DRY_RUN_NO_NETWORK"
    assert output["ready"] is False
    assert output["freshExplicitApprovalRequired"] is True
    assert not (session_root / "_session_claimed").exists()


def test_r32_transport_allows_one_exact_post_and_rejects_second() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r32.AI_CAPS, seconds=r32.TOTAL_SECONDS)
    transport = bounded.AIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        prompt_version=r32.PROMPT_VERSION,
        max_output_tokens=r32.AI_OUTPUT_TOKENS,
        max_prompt_utf8_bytes=r32.EXPECTED_PROMPT_UTF8_BYTES,
    )
    request = httpx.Request(
        "POST",
        r32.EXTERNAL_DESTINATION,
        json=r32._egress_review_material()["requests"]["LITERAL"]["body"],
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


def test_r32_exact_transport_rejects_unapproved_extra_fields_before_network() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r32.AI_CAPS, seconds=r32.TOTAL_SECONDS)
    transport = r32.ExactAIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        expected_body_hash=r32.EXPECTED_REQUEST_BODY_HASH,
    )
    body = json.loads(
        json.dumps(r32._egress_review_material()["requests"]["LITERAL"]["body"])
    )
    body["messages"][0]["prefix"] = True
    request = httpx.Request("POST", r32.EXTERNAL_DESTINATION, json=body)

    async def scenario() -> None:
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())
    assert starts == 0
    assert budget.snapshot()["totalAttempts"] == 0
    assert budget.snapshot()["deniedBeforeNetwork"] == 1


def test_r32_exact_transport_rebuilds_upstream_float_as_reviewed_integer() -> None:
    observed_hashes: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_hashes.append(r32._canonical_json_hash(json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r32.AI_CAPS, seconds=r32.TOTAL_SECONDS)
    transport = r32.ExactAIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        expected_body_hash=r32.EXPECTED_REQUEST_BODY_HASH,
    )
    body = json.loads(
        json.dumps(r32._egress_review_material()["requests"]["LITERAL"]["body"])
    )
    body["temperature"] = 0.0
    request = httpx.Request("POST", r32.EXTERNAL_DESTINATION, json=body)

    async def scenario() -> None:
        assert (await transport.handle_async_request(request)).status_code == 200
        await transport.aclose()

    asyncio.run(scenario())
    assert observed_hashes == [r32.EXPECTED_REQUEST_BODY_HASH]


def test_r32_exact_transport_rejects_boolean_temperature_before_network() -> None:
    starts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        return httpx.Response(200, json={"ok": True})

    budget = bounded.Budget(total=1, per_key=r32.AI_CAPS, seconds=r32.TOTAL_SECONDS)
    transport = r32.ExactAIBudgetTransport(
        budget,
        inner=httpx.MockTransport(handler),
        expected_body_hash=r32.EXPECTED_REQUEST_BODY_HASH,
    )
    body = json.loads(
        json.dumps(r32._egress_review_material()["requests"]["LITERAL"]["body"])
    )
    body["temperature"] = False
    request = httpx.Request("POST", r32.EXTERNAL_DESTINATION, json=body)

    async def scenario() -> None:
        with pytest.raises(bounded.BudgetDenied):
            await transport.handle_async_request(request)
        await transport.aclose()

    asyncio.run(scenario())
    assert starts == 0


def test_r32_preflight_requires_the_reviewed_branch_and_exact_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path / "app.yaml")
    monkeypatch.setattr(r32, "EXPECTED_CONFIG_HASH", r32._file_sha256(config_path))
    monkeypatch.setattr(r32, "_review_package_matches", lambda: True)
    monkeypatch.setattr(
        r32,
        "_git_state",
        lambda: (True, "different-clean-head", r32.EXPECTED_BRANCH),
    )

    preflight = r32._preflight(
        config_path=config_path,
        expected_head="reviewed-head",
        approval_attestation_path=tmp_path / "approval.json",
        expected_approval_attestation_hash="unused",
    )

    assert preflight["ready"] is False
    assert preflight["gitBranchMatches"] is True
    assert preflight["gitHeadMatches"] is False


def test_r32_approval_attestation_is_package_bound_and_tamper_evident(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    attestation = {
        "proposalId": r32.PROPOSAL_ID,
        "runId": r32.RUN_ID,
        "packageSha256": r32.EXPECTED_PACKAGE_HASH,
        "status": "APPROVED",
        "destination": r32.EXTERNAL_DESTINATION,
        "method": "POST",
        "physicalPosts": 1,
        "retries": 0,
        "marketCalls": 0,
        "accountCalls": 0,
        "possibleFeeAccepted": True,
        "officialReviewStatus": "PASS",
    }
    path.write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
    expected_hash = sha256(path.read_bytes()).hexdigest()

    assert r32._approval_attestation_matches(path, expected_hash)
    attestation["retries"] = 1
    path.write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
    assert not r32._approval_attestation_matches(path, expected_hash)


def test_r32_existing_run_directory_is_rejected_without_consuming_another_claim(
    tmp_path: Path,
) -> None:
    root = tmp_path / "session"
    (root / r32.RUN_ID).mkdir(parents=True)

    with pytest.raises(FileExistsError):
        r32._claim_session(root)

    assert not (root / "_session_claimed").exists()


def test_r32_invalid_config_never_reports_a_rejected_direct_ip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: Rejected
  base_url: https://192.0.2.10
  model: deepseek-v4-pro
  api_key: offline-rejected-key
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(r32, "EXPECTED_CONFIG_HASH", r32._file_sha256(config_path))

    preflight = r32._preflight(config_path=config_path)

    assert preflight["ready"] is False
    assert preflight["ai"]["host"] is None
    assert "192.0.2.10" not in json.dumps(preflight)


def test_r32_cleanup_uses_one_shared_deadline_for_all_lifecycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r32, "CLEANUP_SECONDS", 0.03)

    class SlowLifecycle:
        async def stop(self) -> None:
            await asyncio.sleep(0.025)

    started = monotonic()
    result = asyncio.run(
        r32._cleanup_with_hard_deadline(
            started + 1,
            SlowLifecycle(),
            SlowLifecycle(),
        )
    )
    elapsed = monotonic() - started

    assert result is False
    assert elapsed < 0.06


def test_r32_parent_watchdog_redacts_child_timeout_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_root = tmp_path / "session"
    folder = session_root / r32.RUN_ID
    folder.mkdir(parents=True)
    journal_path = folder / "physical-attempts.json"
    journal_path.write_text(
        json.dumps(
            {
                "proposalId": r32.PROPOSAL_ID,
                "runId": r32.RUN_ID,
                "status": "ACTIVE",
                "normalAuditPresent": False,
            }
        ),
        encoding="utf-8",
    )
    audit_path = folder / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "proposalId": r32.PROPOSAL_ID,
                "runId": r32.RUN_ID,
                "status": "SHUTDOWN_FAILED",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(r32, "SESSION_ROOT", session_root)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["python", "secret-config-path"],
            timeout=r32.TOTAL_SECONDS,
            output=b"provider-secret-output",
            stderr=b"provider-secret-error",
        )

    monkeypatch.setattr(r32.subprocess, "run", timeout)

    result = r32._run_under_parent_watchdog({})
    output = capsys.readouterr().out

    assert result == 1
    assert json.loads(output)["status"] == "HARD_DEADLINE_EXCEEDED"
    assert "secret" not in output
    assert json.loads((folder / "watchdog-terminal.json").read_text("utf-8"))["status"] == (
        "HARD_DEADLINE_EXCEEDED"
    )
    journal = json.loads(journal_path.read_text("utf-8"))
    assert journal["status"] == "HARD_DEADLINE_EXCEEDED"
    assert journal["watchdogTerminalPresent"] is True
    audit = json.loads(audit_path.read_text("utf-8"))
    assert audit["status"] == journal["status"]
    assert audit["candidateStatusBeforeWatchdog"] == "SHUTDOWN_FAILED"


def test_r32_parent_only_emits_whitelisted_child_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = subprocess.CompletedProcess(
        args=["python"],
        returncode=1,
        stdout=json.dumps(
            {
                "status": "FAILED",
                "proposalId": r32.PROPOSAL_ID,
                "runId": r32.RUN_ID,
                "detail": "synthetic-provider-secret",
                "ai": {"totalAttempts": 1, "raw": "synthetic-provider-secret"},
            }
        ),
        stderr="synthetic-provider-secret",
    )
    monkeypatch.setattr(r32.subprocess, "run", lambda *_args, **_kwargs: child)

    assert r32._run_under_parent_watchdog({}) == 1
    output = capsys.readouterr().out

    assert "secret" not in output
    assert json.loads(output) == {
        "aiPhysicalAttempts": 1,
        "proposalId": r32.PROPOSAL_ID,
        "runId": r32.RUN_ID,
        "status": "FAILED",
    }


def test_r32_parent_rejects_non_scalar_child_status_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = subprocess.CompletedProcess(
        args=["python"],
        returncode=1,
        stdout=json.dumps({"status": [], "detail": "synthetic-provider-secret"}),
        stderr="synthetic-provider-secret",
    )
    monkeypatch.setattr(r32.subprocess, "run", lambda *_args, **_kwargs: child)

    assert r32._run_under_parent_watchdog({}) == 1
    output = capsys.readouterr().out

    assert json.loads(output) == {"status": "CHILD_RESULT_UNAVAILABLE"}
    assert "secret" not in output


def test_r32_internal_execution_cannot_bypass_parent_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(r32, "_preflight", lambda **_kwargs: pytest.fail("no preflight"))
    monkeypatch.setattr(r32, "_run_candidate", lambda **_kwargs: pytest.fail("no execute"))

    with pytest.raises(SystemExit) as caught:
        r32.main(["--internal-execute"])

    assert caught.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize("approved_day", [True, False])
def test_r32_execution_snapshot_detects_config_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    approved_day: bool,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            observed = datetime(2026, 9, 17 if approved_day else 18, 12, tzinfo=_SHANGHAI)
            return observed.astimezone(tz) if tz is not None else observed.replace(tzinfo=None)

    # Exercise the real date guard without depending on the machine's current date.
    monkeypatch.setattr(r32, "datetime", FrozenDateTime)
    config_path = _config(tmp_path / "app.yaml")
    expected_hash = r32._file_sha256(config_path)
    monkeypatch.setattr(r32, "EXPECTED_CONFIG_HASH", expected_hash)
    monkeypatch.setattr(r32, "_review_package_matches", lambda: True)
    monkeypatch.setattr(
        r32,
        "_git_state",
        lambda: (True, "reviewed-head", r32.EXPECTED_BRANCH),
    )
    monkeypatch.setattr(r32, "_approval_attestation_matches", lambda *_args: True)

    assert r32._execution_snapshot_matches(
        config_path=config_path,
        expected_head="reviewed-head",
        approval_attestation_path=tmp_path / "approval.json",
        expected_approval_attestation_hash="a" * 64,
    ) is approved_day
    config_path.write_text(config_path.read_text("utf-8") + "\n# changed\n", encoding="utf-8")
    assert not r32._execution_snapshot_matches(
        config_path=config_path,
        expected_head="reviewed-head",
        approval_attestation_path=tmp_path / "approval.json",
        expected_approval_attestation_hash="a" * 64,
    )


def test_r32_success_reaches_production_schema_mapping_oracle_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        r32._run_candidate(
            config_path=config_path,
            session_root=session_root,
            ai_inner_transport=httpx.MockTransport(handler),
        )
    )

    folder = session_root / r32.RUN_ID
    audit_text = (folder / "audit.json").read_text("utf-8")
    audit = json.loads(audit_text)
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
    assert "offline-r32-key" not in audit_text


@pytest.mark.parametrize(
    ("error_factory", "expected_kind"),
    [
        (lambda secret, request: httpx.ConnectError(secret, request=request), "CONNECT"),
        (lambda secret, request: httpx.RequestError(secret, request=request), "UNKNOWN"),
    ],
)
def test_r32_transient_v3_category_is_redacted_and_stops_once(
    tmp_path: Path,
    error_factory,
    expected_kind: str,
) -> None:
    config_path = _config(tmp_path / "app.yaml")
    session_root = tmp_path / "session"
    starts = 0
    secret = "SECRET-r32-transport-detail https://192.0.2.10/path"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal starts
        starts += 1
        raise error_factory(secret, request)

    result = asyncio.run(
        r32._run_candidate(
            config_path=config_path,
            session_root=session_root,
            ai_inner_transport=httpx.MockTransport(handler),
        )
    )

    folder = session_root / r32.RUN_ID
    audit_text = (folder / "audit.json").read_text("utf-8")
    diagnostic_text = (folder / "monitor.ai-extraction-diagnostics.jsonl").read_text("utf-8")
    audit = json.loads(audit_text)
    diagnostic = json.loads(diagnostic_text)
    journal = json.loads((folder / "physical-attempts.json").read_text("utf-8"))

    assert result == 1
    assert starts == 1
    assert audit["status"] == "AI_ACCEPTANCE_FAILED"
    assert audit["case"]["diagnostic"]["providerErrorCode"] == "TRANSIENT"
    assert audit["case"]["diagnostic"]["transientKind"] == expected_kind
    assert diagnostic["version"] == 3
    assert diagnostic["transientKind"] == expected_kind
    assert audit["ai"]["totalAttempts"] == 1
    assert audit["ai"]["deniedBeforeNetwork"] == 0
    assert audit["market"]["totalAttempts"] == 0
    assert audit["cleanupStatus"] == "COMPLETE"
    assert all(count == 0 for count in audit["databaseCounts"].values())
    assert journal["status"] == audit["status"]
    assert journal["normalAuditPresent"] is True
    assert secret not in audit_text
    assert secret not in diagnostic_text
    assert "192.0.2.10" not in audit_text
    assert "192.0.2.10" not in diagnostic_text


def test_r32_overall_deadline_cancels_once_and_keeps_audit_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path / "app.yaml")
    session_root = tmp_path / "session"
    starts = 0
    cancelled = False
    real_timeout = asyncio.timeout

    monkeypatch.setattr(
        openai_compatible.asyncio,
        "timeout",
        lambda seconds: real_timeout(float(seconds) / 1_000),
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal starts, cancelled
        starts += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("unreachable")

    result = asyncio.run(
        r32._run_candidate(
            config_path=config_path,
            session_root=session_root,
            ai_inner_transport=httpx.MockTransport(handler),
        )
    )

    folder = session_root / r32.RUN_ID
    audit = json.loads((folder / "audit.json").read_text("utf-8"))
    diagnostic = json.loads((folder / "monitor.ai-extraction-diagnostics.jsonl").read_text("utf-8"))
    journal = json.loads((folder / "physical-attempts.json").read_text("utf-8"))

    assert result == 1
    assert starts == 1
    assert cancelled is True
    assert audit["case"]["diagnostic"]["providerErrorCode"] == "TIMEOUT"
    assert audit["case"]["diagnostic"]["timeoutKind"] == "OVERALL_DEADLINE"
    assert audit["case"]["diagnostic"]["transientKind"] is None
    assert diagnostic["version"] == 3
    assert audit["cleanupStatus"] == "COMPLETE"
    assert all(count == 0 for count in audit["databaseCounts"].values())
    assert journal["status"] == audit["status"]
    assert journal["normalAuditPresent"] is True


def test_r32_uncertain_receipt_stops_without_resubmission(tmp_path: Path) -> None:
    class FailingService:
        calls = 0

        async def submit_plan_extraction(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("synthetic receipt uncertainty with SECRET")

    service = FailingService()
    outcome, review = asyncio.run(
        r32._submit_and_wait(
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


def test_r32_missing_config_is_not_ready_and_does_not_claim(tmp_path: Path) -> None:
    missing = tmp_path / "app.yaml"
    preflight = r32._preflight(config_path=missing)

    assert preflight["ready"] is False
    assert preflight["mode"] == "DRY_RUN_NO_NETWORK"
    assert preflight["configSourceStatus"] == "MISSING"
    assert preflight["freshClaimAvailable"] is True
    assert not (r32.SESSION_ROOT / "_session_claimed").exists()
    assert preflight["balanceOrModelListProbeAllowed"] is False


def test_r32_execute_without_exact_approval_stops_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_root = tmp_path / "session"
    config_path = _config(tmp_path / "app.yaml")
    monkeypatch.setattr(r32, "SESSION_ROOT", session_root)
    monkeypatch.setattr(r32, "_preflight", lambda **_kwargs: {"ready": True})

    result = r32.main(
        [
            "--execute",
            "--authorize",
            "wrong-authorization",
            "--run-id",
            r32.RUN_ID,
            "--config-path",
            str(config_path),
        ]
    )

    assert result == 2
    assert json.loads(capsys.readouterr().out)["status"] == ("NOT_RUN_AUTHORIZATION_OR_PREFLIGHT")
    assert not (session_root / "_session_claimed").exists()
