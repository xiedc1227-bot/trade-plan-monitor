"""R32 one-POST v6 transient-classification candidate. Default is offline-only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from scripts import ai_timeout_budget_acceptance as r30
from scripts import bounded_live_acceptance as bounded
from scripts import plan_extraction_v6_acceptance as r29

from trade_plan_monitor.ai.models import PlanExtractionResult
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V6
from trade_plan_monitor.web.routers.plans import (
    PlanExtractionCommand,
    PlanExtractionOperationStatus,
    PlanExtractionService,
)
from trade_plan_monitor.web.schemas import MutationContext

PROPOSAL_ID = "R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1"
AUTHORIZATION = "R32_20260917_LITERAL_ONE_AI_ZERO_MARKET_TRANSIENT_ACCEPTANCE"
RUN_ID = "r32-20260917-a"
CASE_ID = "LITERAL"
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V6
AI_OUTPUT_TOKENS = 8192
AI_CAPS = {CASE_ID: 1}
AI_TOTAL = 1
MARKET_CAPS = {key: 0 for key in r30.MARKET_CAPS}
MARKET_TOTAL = 0
TRANSPORT_TIMEOUT_SECONDS = 30
READ_TIMEOUT_SECONDS = 60
PROVIDER_TIMEOUT_SECONDS = 65
TERMINAL_WAIT_SECONDS = 66
CLEANUP_SECONDS = 15
TOTAL_SECONDS = 81
SESSION_ROOT = bounded._ROOT / "data/r32-ai-transient-acceptance"
REVIEW_ROOT = bounded._ROOT / "data/r32-ai-transient-review"
EXTERNAL_DESTINATION = r30.EXTERNAL_DESTINATION
EXPECTED_SOURCE_HASH = r30.EXPECTED_SOURCE_HASH
EXPECTED_PROMPT_HASH = r30.EXPECTED_PROMPT_HASH
EXPECTED_PROMPT_UTF8_BYTES = r30.EXPECTED_PROMPT_UTF8_BYTES
EXPECTED_CONFIG_HASH = r30.EXPECTED_CONFIG_HASH
EXPECTED_REQUEST_BODY_HASH = r30.EXPECTED_REQUEST_BODY_HASH
R30_PACKAGE_HASH = "282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10"
R30_PRICE_SNAPSHOT_AT = "2026-09-17T10:22:27.399234+08:00"
R30_PEAK_ESTIMATE_USD = "0.05884032"
R30_OFF_PEAK_ESTIMATE_USD = "0.02942016"
EXPECTED_PACKAGE_HASH = "7832b7e80f791c6a9f58fb30e1bd1f18f1958c60e6d845557d9b4f5e0916bfda"
EXPECTED_BRANCH = "codex/r32-ai-transient-acceptance"
EXPECTED_REVIEW_HASHES = {
    "egress-material.json": "0d21ba5216c8ff5b70aea3bc50fdbb4f0a9ca43e55bf8890065f873c7bd0941f",
    "egress-review.md": "401cc23111147d3389b474e5e2211fd2cac9110ebee852d5ff7563602930f2c0",
    "egress-review.zh-CN.md": "3d196b44697168688510c1e5a851282e932e66431126c4a40e78e76838f7739d",
    "manifest.json": "5a60e76e4499a921d09351adb2d0e7b38e66a3525526354d176436ca8d0e3b13",
}
_TERMINAL_STATUSES = frozenset(
    status
    for status in PlanExtractionOperationStatus
    if status
    not in {
        PlanExtractionOperationStatus.QUEUED,
        PlanExtractionOperationStatus.RUNNING,
    }
)


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 17) and time(0, 0) <= now.time() <= time(23, 59, 59)


def _canonical_json_hash(value: object) -> str:
    return r30._canonical_json_hash(value)


def _request_body(prompt: str) -> dict[str, object]:
    return r30._request_body(prompt)


class ExactAIBudgetTransport(bounded.AIBudgetTransport):
    """Reject any request whose complete canonical body differs from the reviewed body."""

    def __init__(
        self,
        budget: bounded.Budget,
        *,
        expected_body_hash: str,
        inner: httpx.AsyncBaseTransport | None = None,
        prompt_version: str = PROMPT_VERSION,
        max_output_tokens: int = AI_OUTPUT_TOKENS,
        max_prompt_utf8_bytes: int = EXPECTED_PROMPT_UTF8_BYTES,
    ) -> None:
        super().__init__(
            budget,
            inner=inner,
            prompt_version=prompt_version,
            max_output_tokens=max_output_tokens,
            max_prompt_utf8_bytes=max_prompt_utf8_bytes,
        )
        self._expected_body_hash = expected_body_hash
        _, prompt = bounded.approved_sources(prompt_version=prompt_version)[CASE_ID]
        self._expected_body = _request_body(prompt)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content)
        except (TypeError, UnicodeError, ValueError):
            self._budget.reject()
        if not isinstance(body, dict):
            self._budget.reject()
        # Pydantic represents the configured zero temperature as 0.0.  The
        # reviewed request fixes that JSON number as 0, so admit only that one
        # known representation difference and rebuild the actual outbound
        # request from the frozen body before it can reach the network.
        temperature = body.get("temperature")
        if type(temperature) is float and repr(temperature) == "0.0":
            body["temperature"] = 0
        if (
            body != self._expected_body
            or _canonical_json_hash(body) != self._expected_body_hash
        ):
            self._budget.reject()
        outbound = httpx.Request(
            request.method,
            request.url,
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() not in {"content-length", "transfer-encoding"}
            },
            json=self._expected_body,
            extensions=request.extensions,
        )
        if _canonical_json_hash(json.loads(outbound.content)) != self._expected_body_hash:
            self._budget.reject()
        return await super().handle_async_request(outbound)


def _egress_review_material() -> dict[str, object]:
    source, prompt = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID]
    body = _request_body(prompt)
    return {
        "proposalId": PROPOSAL_ID,
        "destination": EXTERNAL_DESTINATION,
        "recipient": "DeepSeek API service operated by DeepSeek",
        "method": "POST",
        "headers": {
            "Authorization": "<credential omitted; not part of approval material>",
            "Content-Type": "application/json",
        },
        "sourceClassification": "SYNTHETIC_VERSIONED_TEST_FIXTURE",
        "containsSyntheticHoldingLanguage": True,
        "containsRealAccountOrCredential": False,
        "limits": {
            "physicalPosts": 1,
            "retries": 0,
            "marketCalls": 0,
            "accountCalls": 0,
            "connectWritePoolTimeoutSeconds": TRANSPORT_TIMEOUT_SECONDS,
            "readTimeoutSeconds": READ_TIMEOUT_SECONDS,
            "providerOverallTimeoutSeconds": PROVIDER_TIMEOUT_SECONDS,
            "terminalObservationSeconds": TERMINAL_WAIT_SECONDS,
            "totalSeconds": TOTAL_SECONDS,
            "cleanupSecondsMaximum": CLEANUP_SECONDS,
            "stopOnEveryTerminalResultIncludingUnknown": True,
        },
        "diagnosticPurpose": {
            "statement": (
                "Test whether R31 content-free transientKind reaches the existing provider, "
                "extraction, sidecar, assessment, cleanup, and audit chain"
            ),
            "r30HistoricalResult": {
                "status": "PROVIDER_ERROR",
                "providerErrorCode": "TRANSIENT",
                "boundedWorkElapsedMs": 261,
                "responseAvailable": False,
                "usageAvailable": False,
                "oracleStatus": "NOT_RUN",
                "claimConsumed": True,
            },
            "unknowns": [
                "which structural transient category caused R30",
                "whether DeepSeek received, processed, or billed R30",
                "whether DeepSeek would receive, process, or bill the R32 candidate",
                "the actual charge of any future R32 request",
            ],
        },
        "comparisonWithR30": {
            "r30PackageSha256": R30_PACKAGE_HASH,
            "sourceBytesChanged": False,
            "promptBytesChanged": False,
            "requestBodyBytesChanged": False,
            "requestBodyCanonicalSha256": EXPECTED_REQUEST_BODY_HASH,
            "sentFieldsChanged": [],
            "localOnlyChanges": [
                "new proposal, run, operation, idempotency key, claim, and evidence identities",
                "R31 sidecar v3 closed transientKind classification is now observable",
            ],
        },
        "historicalPriceSnapshot": {
            "observedAt": R30_PRICE_SNAPSHOT_AT,
            "notCurrentPriceGuarantee": True,
            "peakEstimateUsd": R30_PEAK_ESTIMATE_USD,
            "offPeakEstimateUsd": R30_OFF_PEAK_ESTIMATE_USD,
            "notAHardCostGate": True,
            "actualTokenizationCacheBillingTaxesAndAdjustments": "UNKNOWN",
        },
        "requests": {
            CASE_ID: {
                "purpose": "one-shot real v6 extraction with R31 safe transient classification",
                "origin": "tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText",
                "sourceText": source,
                "sourceSha256": sha256(source.encode("utf-8")).hexdigest(),
                "promptSha256": sha256(prompt.encode("utf-8")).hexdigest(),
                "promptUtf8Bytes": len(prompt.encode("utf-8")),
                "bodyCanonicalSha256": _canonical_json_hash(body),
                "body": body,
            }
        },
    }


def _validate_material(material: dict[str, object]) -> bool:
    try:
        source, prompt = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID]
        request = material["requests"][CASE_ID]
        body = request["body"]
        comparison = material["comparisonWithR30"]
        candidate_source = request["sourceText"]
        candidate_prompt = body["messages"][0]["content"]
        return bool(
            material["proposalId"] == PROPOSAL_ID
            and material["destination"] == EXTERNAL_DESTINATION
            and material["method"] == "POST"
            and tuple(material["requests"]) == (CASE_ID,)
            and candidate_source.encode("utf-8") == source.encode("utf-8")
            and candidate_prompt.encode("utf-8") == prompt.encode("utf-8")
            and sha256(candidate_source.encode("utf-8")).hexdigest() == EXPECTED_SOURCE_HASH
            and sha256(candidate_prompt.encode("utf-8")).hexdigest() == EXPECTED_PROMPT_HASH
            and len(candidate_prompt.encode("utf-8")) == EXPECTED_PROMPT_UTF8_BYTES
            and request["sourceSha256"] == EXPECTED_SOURCE_HASH
            and request["promptSha256"] == EXPECTED_PROMPT_HASH
            and request["promptUtf8Bytes"] == EXPECTED_PROMPT_UTF8_BYTES
            and request["bodyCanonicalSha256"] == EXPECTED_REQUEST_BODY_HASH
            and _canonical_json_hash(body) == EXPECTED_REQUEST_BODY_HASH
            and body == _request_body(prompt)
            and comparison["r30PackageSha256"] == R30_PACKAGE_HASH
            and comparison["sourceBytesChanged"] is False
            and comparison["promptBytesChanged"] is False
            and comparison["requestBodyBytesChanged"] is False
            and comparison["sentFieldsChanged"] == []
        )
    except AttributeError, KeyError, TypeError, UnicodeError:
        return False


def _render_review(material: dict[str, object], *, chinese: bool) -> str:
    request = material["requests"][CASE_ID]
    body = request["body"]
    prompt = body["messages"][0]["content"]
    fixed_body = {key: value for key, value in body.items() if key != "messages"}
    snapshot = material["historicalPriceSnapshot"]
    comparison = material["comparisonWithR30"]
    if chinese:
        title = "R32 AI 瞬态分类候选精确外发审阅材料"
        intro = (
            "本文件完整展示唯一拟外发的合成 LITERAL 原文、完整 v6 user 提示词及固定请求字段。"
            "原文、提示词与发送请求体相对 R30 逐字节不变；R32 仅使用新身份验证 R31 安全分类链。"
        )
        purpose = (
            "诊断目的：若未来一次请求再次以瞬态错误结束，验证固定 transientKind "
            "能否进入 v3 sidecar、"
            "评估、清理和 audit；若返回有效响应，则继续既有严格 schema、mapping 与字面 oracle。"
        )
        source_label = "将外发的精确原文"
        prompt_label = "将外发的精确唯一 user 提示词"
        body_label = "不含消息内容的固定请求体字段"
        pricing = "历史价格快照（仅披露，不是当前报价保证或金额硬门槛）"
        billing = "真实分词、缓存拆分、输出、计费、税费及账户调整未知"
        uncertainty = "供应商是否接收、处理或计费可能仍无法确认"
    else:
        title = "R32 AI transient-classification exact egress review material"
        intro = (
            "This file shows the sole synthetic LITERAL source, complete v6 user prompt, and "
            "fixed request fields proposed for egress. Source, prompt, and sent request-body "
            "bytes are unchanged from R30; R32 uses new identities only to exercise the R31 "
            "safe-classification chain."
        )
        purpose = (
            "Diagnostic purpose: if one future request ends in another transient error, verify "
            "that a fixed transientKind reaches the v3 sidecar, assessment, cleanup, and audit. "
            "A valid response continues through the existing strict schema, mapping, and "
            "literal oracle."
        )
        source_label = "Exact source text to be sent"
        prompt_label = "Exact sole user prompt to be sent"
        body_label = "Fixed request-body fields excluding message content"
        pricing = (
            "Historical price snapshot (disclosure only; not a current quote or hard cost gate)"
        )
        billing = (
            "Actual tokenization, cache split, output, billing, taxes, and adjustments are unknown"
        )
        uncertainty = "Provider receipt, processing, and billing may remain unconfirmable"
    return "\n".join(
        [
            f"# {title}",
            "",
            intro,
            "",
            purpose,
            "",
            f"- Recipient: `{material['recipient']}`",
            f"- Destination: `{material['method']} {material['destination']}`",
            "- Authorization header: `<credential omitted; not part of approval material>`",
            "- Physical POST cap: `1`; retries/resubmissions: `0`; market calls: `0`; "
            "account calls: `0`",
            "- Every terminal result, including `UNKNOWN`, stops without another request",
            f"- Source SHA-256: `{request['sourceSha256']}`",
            f"- Prompt SHA-256: `{request['promptSha256']}`; UTF-8 bytes: "
            f"`{request['promptUtf8Bytes']}`",
            f"- Request-body canonical SHA-256: `{request['bodyCanonicalSha256']}`",
            f"- R30 package SHA-256 compared: `{comparison['r30PackageSha256']}`",
            "- Sent-field difference from R30: `NONE`",
            "- Local budgets: connect/write/pool `30s`; read `60s`; provider overall `65s`; "
            "terminal observation `66s`; cleanup at most `15s`; hard total `81s`",
            f"- {pricing}: observed `{snapshot['observedAt']}`; peak estimate "
            f"`USD {snapshot['peakEstimateUsd']}`; off-peak estimate "
            f"`USD {snapshot['offPeakEstimateUsd']}`; {billing}.",
            f"- {uncertainty}.",
            "",
            f"## {source_label}",
            "",
            "`````text",
            str(request["sourceText"]),
            "`````",
            "",
            f"## {prompt_label}",
            "",
            "`````text",
            str(prompt),
            "`````",
            "",
            f"## {body_label}",
            "",
            "```json",
            json.dumps(fixed_body, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def _file_sha256(path: Path) -> str:
    return r30._file_sha256(path)


def _write_egress_review_package(root: Path = REVIEW_ROOT) -> tuple[Path, Path]:
    material = _egress_review_material()
    if not _validate_material(material):
        raise ValueError("R32 egress material does not match the frozen R30 request")
    root.mkdir(parents=True, exist_ok=True)
    material_path = root / "egress-material.json"
    english = root / "egress-review.md"
    chinese = root / "egress-review.zh-CN.md"
    material_path.write_text(
        json.dumps(material, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    english.write_text(_render_review(material, chinese=False), encoding="utf-8", newline="\n")
    chinese.write_text(_render_review(material, chinese=True), encoding="utf-8", newline="\n")
    components = {path.name: _file_sha256(path) for path in (material_path, english, chinese)}
    package_digest = sha256()
    for path in (material_path, english, chinese):
        package_digest.update(path.read_bytes())
    manifest = {
        "proposalId": PROPOSAL_ID,
        "components": components,
        "packageSha256": package_digest.hexdigest(),
        "packageOrder": [material_path.name, english.name, chinese.name],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return english, chinese


def _review_package_matches(root: Path = REVIEW_ROOT) -> bool:
    return all(
        (root / name).is_file() and expected != "PENDING" and _file_sha256(root / name) == expected
        for name, expected in EXPECTED_REVIEW_HASHES.items()
    )


def _git_state() -> tuple[bool, str | None, str | None]:
    git = ["git", "-c", f"safe.directory={bounded._ROOT}"]
    try:
        status = subprocess.run(
            [*git, "status", "--porcelain"],
            cwd=bounded._ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        head = subprocess.run(
            [*git, "rev-parse", "HEAD"],
            cwd=bounded._ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        branch = subprocess.run(
            [*git, "branch", "--show-current"],
            cwd=bounded._ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None, None
    return (
        not status.stdout.strip(),
        head.stdout.strip() or None,
        branch.stdout.strip() or None,
    )


def _approval_attestation_matches(
    path: Path | None,
    expected_hash: str | None,
) -> bool:
    if path is None or expected_hash is None or not path.is_file():
        return False
    try:
        attestation_bytes = path.read_bytes()
        material = json.loads(attestation_bytes.decode("utf-8"))
        actual_hash = sha256(attestation_bytes).hexdigest()
    except (OSError, UnicodeError, ValueError):
        return False
    return bool(
        len(expected_hash) == 64
        and actual_hash == expected_hash
        and material.get("proposalId") == PROPOSAL_ID
        and material.get("runId") == RUN_ID
        and material.get("packageSha256") == EXPECTED_PACKAGE_HASH
        and material.get("status") == "APPROVED"
        and material.get("destination") == EXTERNAL_DESTINATION
        and material.get("method") == "POST"
        and material.get("physicalPosts") == 1
        and material.get("retries") == 0
        and material.get("marketCalls") == 0
        and material.get("accountCalls") == 0
        and material.get("possibleFeeAccepted") is True
        and material.get("officialReviewStatus") == "PASS"
    )


def _preflight(
    *,
    config_path: Path | None = None,
    expected_head: str | None = None,
    approval_attestation_path: Path | None = None,
    expected_approval_attestation_hash: str | None = None,
) -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config

    path = config_path or (bounded._ROOT / "config/app.yaml")
    config_status = "MISSING"
    endpoint = None
    key_present = False
    selected = False
    configured_timeout = None
    config_hash_matches = False
    ai_ready = False
    if path.is_file():
        try:
            config_hash_matches = _file_sha256(path) == EXPECTED_CONFIG_HASH
            configuration = load_application_config(path)
            ai = configuration.ai
            configured_timeout = ai.timeout_seconds
            endpoint = urlsplit(str(ai.base_url))
            key_present = bool(ai.api_key)
            selected = bounded.APPROVED_MODEL in {
                ai.model,
                *(item.model for item in ai.additional_models),
            }
            config_status = "READY" if config_hash_matches else "HASH_MISMATCH"
            ai_ready = bool(
                config_hash_matches
                and key_present
                and ai.profile.value == "DEEPSEEK"
                and endpoint.scheme == "https"
                and endpoint.hostname == "api.deepseek.com"
                and endpoint.port in (None, 443)
                and endpoint.path in ("", "/")
                and not endpoint.query
                and not endpoint.fragment
                and selected
            )
        except Exception:
            config_status = "INVALID"
    now = datetime.now(bounded._SHANGHAI)
    clean, head, branch = _git_state()
    branch_matches = branch == EXPECTED_BRANCH
    head_matches = expected_head is not None and head == expected_head
    material_matches = _validate_material(_egress_review_material())
    package_matches = _review_package_matches()
    unclaimed = not (SESSION_ROOT / "_session_claimed").exists() and not (
        SESSION_ROOT / RUN_ID
    ).exists()
    approval_matches = _approval_attestation_matches(
        approval_attestation_path,
        expected_approval_attestation_hash,
    )
    eligible = _eligible(now)
    ready = bool(
        ai_ready
        and material_matches
        and package_matches
        and unclaimed
        and eligible
        and clean
        and branch_matches
        and head_matches
        and approval_matches
    )
    return {
        "ready": ready,
        "mode": "DRY_RUN_NO_NETWORK",
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
        "timeShanghai": now.isoformat(),
        "windowEligible": eligible,
        "gitClean": clean,
        "gitHead": head,
        "gitBranch": branch,
        "gitBranchMatches": branch_matches,
        "gitHeadMatches": head_matches,
        "freshClaimAvailable": unclaimed,
        "approvalAttestationMatches": approval_matches,
        "configSourceStatus": config_status,
        "configSha256Matches": config_hash_matches,
        "configCopiedIntoWorktree": False,
        "externalDestination": EXTERNAL_DESTINATION,
        "materialMatchesFrozenR30Request": material_matches,
        "reviewPackageMatchesCandidate": package_matches,
        "sourceSha256": EXPECTED_SOURCE_HASH,
        "promptSha256": EXPECTED_PROMPT_HASH,
        "requestBodyCanonicalSha256": EXPECTED_REQUEST_BODY_HASH,
        "ai": {
            "host": endpoint.hostname if ai_ready else None,
            "selectedModelConfigured": selected,
            "model": bounded.APPROVED_MODEL,
            "keyPresent": key_present,
            "realConfigDefaultTimeoutSeconds": configured_timeout,
        },
        "limits": {
            "aiPhysicalAttempts": AI_TOTAL,
            "aiPerInputAttempts": AI_CAPS,
            "marketPhysicalAttempts": MARKET_TOTAL,
            "marketPerEndpointAttempts": MARKET_CAPS,
            "connectWritePoolTimeoutSeconds": TRANSPORT_TIMEOUT_SECONDS,
            "readTimeoutSeconds": READ_TIMEOUT_SECONDS,
            "providerOverallTimeoutSeconds": PROVIDER_TIMEOUT_SECONDS,
            "terminalObservationSeconds": TERMINAL_WAIT_SECONDS,
            "totalSeconds": TOTAL_SECONDS,
            "cleanupSecondsMaximum": CLEANUP_SECONDS,
            "promptVersion": PROMPT_VERSION,
            "promptUtf8Bytes": EXPECTED_PROMPT_UTF8_BYTES,
            "aiOutputTokensPerRequest": AI_OUTPUT_TOKENS,
        },
        "freshExplicitApprovalRequired": True,
        "officialRouteRecheckRequiredBeforeExecute": True,
        "officialPriceRecheckRequiredBeforeExecute": True,
        "balanceOrModelListProbeAllowed": False,
        "activationAllowed": False,
        "humanReviewRequired": True,
    }


def _execution_snapshot_matches(
    *,
    config_path: Path,
    expected_head: str,
    approval_attestation_path: Path,
    expected_approval_attestation_hash: str,
) -> bool:
    clean, head, branch = _git_state()
    try:
        config_matches = _file_sha256(config_path) == EXPECTED_CONFIG_HASH
    except OSError:
        config_matches = False
    return bool(
        clean
        and head == expected_head
        and branch == EXPECTED_BRANCH
        and config_matches
        and _validate_material(_egress_review_material())
        and _review_package_matches()
        and _approval_attestation_matches(
            approval_attestation_path,
            expected_approval_attestation_hash,
        )
        and _eligible(datetime.now(bounded._SHANGHAI))
    )


def _assess_terminal(*args: object, **kwargs: object):
    return r30._assess_terminal(*args, **kwargs)


async def _submit_and_wait(
    *,
    service: PlanExtractionService,
    provider_id: UUID,
    source_text: str,
    diagnostic_path: Path,
    deadline: float,
) -> tuple[dict[str, object], dict[str, object] | None]:
    operation_id: UUID | None = None
    try:
        receipt = await service.submit_plan_extraction(
            command=PlanExtractionCommand(
                provider_id=provider_id,
                source_text=source_text,
                expected_revision=0,
            ),
            context=MutationContext(
                idempotency_key=f"{RUN_ID}-{CASE_ID.lower()}",
                request_id=uuid4().hex,
            ),
        )
        operation_id = receipt.operation_id
        while monotonic() < deadline:
            view = await service.get_plan_extraction(operation_id=str(operation_id))
            if view is None:
                break
            if view.status in _TERMINAL_STATUSES:
                return _assess_terminal(
                    source_text=source_text,
                    view=view,
                    diagnostic_path=diagnostic_path,
                )
            await asyncio.sleep(0.05)
    except Exception:
        pass
    return (
        {
            "caseId": CASE_ID,
            "operationId": None if operation_id is None else str(operation_id),
            "sourceSha256": sha256(source_text.encode("utf-8")).hexdigest(),
            "status": "RECEIPT_OR_QUERY_UNCERTAIN",
            "accepted": False,
            "oracleStatus": "NOT_RUN",
            "reason": "STOP_WITHOUT_RESUBMISSION",
            "diagnostic": None,
        },
        None,
    )


class _IsolatedReviewStore:
    def __init__(self) -> None:
        self.operation_ids: list[str] = []

    async def record_plan_extraction(self, result: PlanExtractionResult) -> None:
        self.operation_ids.append(str(result.request_id))


def _claim_session(root: Path = SESSION_ROOT) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if (root / "_session_claimed").exists():
        raise FileExistsError("legacy R32 claim already exists")
    folder = root / RUN_ID
    folder.mkdir(exist_ok=False)
    bounded._write_json_atomic(
        folder / "claim.json",
        {
            "proposalId": PROPOSAL_ID,
            "runId": RUN_ID,
            "status": "CONSUMED",
            "packageSha256": EXPECTED_PACKAGE_HASH,
            "claimedAt": datetime.now(bounded._SHANGHAI).isoformat(),
        },
    )
    return folder


def _bounded_ai_factory(
    config_path: Path,
    plan_lifecycle: object,
    budget: bounded.Budget,
    *,
    database: Path,
    inner_transport: httpx.AsyncBaseTransport | None,
):
    from trade_plan_monitor.web.ai_diagnostics import diagnostic_path_for_database
    from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle

    class BoundedAIWebLifecycle(ConfiguredAIWebLifecycle):
        async def start(self) -> dict[str, object]:
            outcome = await super().start()
            if self._diagnostic_sink_available is False:
                raise bounded.BudgetDenied
            selected = self._bindings.get(
                next(
                    (
                        identity
                        for identity, binding in self._bindings.items()
                        if binding.config.model == bounded.APPROVED_MODEL
                    ),
                    None,
                )
            )
            if selected is None:
                raise bounded.BudgetDenied
            selected = replace(
                selected,
                config=selected.config.model_copy(
                    update={
                        "max_retries": 0,
                        "max_output_tokens": AI_OUTPUT_TOKENS,
                        "timeout_seconds": PROVIDER_TIMEOUT_SECONDS,
                        "transport_timeout_seconds": TRANSPORT_TIMEOUT_SECONDS,
                        "read_timeout_seconds": READ_TIMEOUT_SECONDS,
                        "prompt_version": PROMPT_VERSION,
                    }
                ),
            )
            self._binding = selected
            self._bindings = {selected.config.provider_id: selected}
            return outcome

    return BoundedAIWebLifecycle(
        config_path=config_path,
        client_factory=lambda: httpx.AsyncClient(
            transport=ExactAIBudgetTransport(
                budget,
                expected_body_hash=EXPECTED_REQUEST_BODY_HASH,
                inner=inner_transport,
            ),
            timeout=httpx.Timeout(
                TRANSPORT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
            ),
            follow_redirects=False,
            trust_env=False,
        ),
        review_store=plan_lifecycle,
        diagnostic_path=diagnostic_path_for_database(database),
    )


def _database_counts(database: Path) -> dict[str, int]:
    return r30._database_counts(database)


async def _cleanup_with_hard_deadline(
    hard_deadline: float,
    *lifecycles: object | None,
    monotonic: Callable[[], float] = monotonic,
) -> bool:
    success = True
    cleanup_deadline = min(hard_deadline, monotonic() + float(CLEANUP_SECONDS))
    for lifecycle in lifecycles:
        if lifecycle is None:
            continue
        stop = getattr(lifecycle, "stop", None)
        if not callable(stop):
            success = False
            continue
        remaining = cleanup_deadline - monotonic()
        if remaining <= 0:
            success = False
            continue
        task = asyncio.create_task(stop())
        done, pending = await asyncio.wait({task}, timeout=remaining)
        if pending:
            task.cancel()
            success = False
            continue
        try:
            task.result()
        except BaseException:
            success = False
    return success


async def _run_candidate(
    *,
    config_path: Path,
    session_root: Path = SESSION_ROOT,
    ai_inner_transport: httpx.AsyncBaseTransport | None = None,
    expected_head: str | None = None,
    approval_attestation_path: Path | None = None,
    expected_approval_attestation_hash: str | None = None,
) -> int:
    from trade_plan_monitor.web.ai_diagnostics import diagnostic_path_for_database
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    session_started = monotonic()
    hard_deadline = session_started + TOTAL_SECONDS
    folder = _claim_session(session_root)
    database = folder / "monitor.sqlite3"
    diagnostics = diagnostic_path_for_database(database)
    started_at = datetime.now(bounded._SHANGHAI).isoformat()
    journal = bounded.PhysicalAttemptJournal(
        folder / "physical-attempts.json",
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        started_at=started_at,
    )
    audit: dict[str, object] = {
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
        "startedAt": started_at,
        "database": "monitor.sqlite3",
        "diagnosticSidecar": "monitor.ai-extraction-diagnostics.jsonl",
        "validatedReviewArtifact": "validated-review-result.json",
        "channel": "LOCAL_REVIEW_ONLY",
        "status": "STARTED",
        "humanReviewStatus": "REQUIRED_NOT_PERFORMED",
        "activationAllowed": False,
        "marketLifecycleStarted": False,
        "configCopiedIntoWorktree": False,
        "requestBodyCanonicalSha256": EXPECTED_REQUEST_BODY_HASH,
        "timeoutBudget": {
            "connectWritePoolSeconds": TRANSPORT_TIMEOUT_SECONDS,
            "readSeconds": READ_TIMEOUT_SECONDS,
            "providerOverallSeconds": PROVIDER_TIMEOUT_SECONDS,
            "terminalObservationSeconds": TERMINAL_WAIT_SECONDS,
            "hardTotalSeconds": TOTAL_SECONDS,
            "cleanupSecondsMaximum": CLEANUP_SECONDS,
        },
    }
    ai_budget, market_budget = bounded._session_budgets(
        lambda: None,
        ai_total=AI_TOTAL,
        ai_caps=AI_CAPS,
        market_caps=MARKET_CAPS,
        market_total=MARKET_TOTAL,
        wall_seconds=TOTAL_SECONDS,
        on_ai_snapshot=lambda snapshot: journal.record_budget("ai", snapshot),
        on_market_snapshot=lambda snapshot: journal.record_budget("market", snapshot),
    )
    journal.record_budget("ai", ai_budget.snapshot())
    journal.record_budget("market", market_budget.snapshot())
    plans = None
    ai = None
    return_code = 1
    review_store = _IsolatedReviewStore()
    try:
        plans = PersistentPlanWebLifecycle(
            database_path=database,
            clock=lambda: datetime.now(bounded._SHANGHAI),
        )
        await plans.start()
        ai = _bounded_ai_factory(
            config_path,
            review_store,
            ai_budget,
            database=database,
            inner_transport=ai_inner_transport,
        )
        startup = await ai.start()
        if expected_head is not None:
            if (
                approval_attestation_path is None
                or expected_approval_attestation_hash is None
                or not _execution_snapshot_matches(
                    config_path=config_path,
                    expected_head=expected_head,
                    approval_attestation_path=approval_attestation_path,
                    expected_approval_attestation_hash=expected_approval_attestation_hash,
                )
            ):
                raise bounded.BudgetDenied
        if startup.get("configured") is not True or startup.get("diagnosticAvailable") is not True:
            raise bounded.BudgetDenied
        provider_id = (await ai.get_configured_ai()).provider_id
        source = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID][0]
        if sha256(source.encode("utf-8")).hexdigest() != EXPECTED_SOURCE_HASH:
            raise bounded.BudgetDenied
        outcome, review = await _submit_and_wait(
            service=ai,
            provider_id=provider_id,
            source_text=source,
            diagnostic_path=diagnostics,
            deadline=min(hard_deadline, session_started + TERMINAL_WAIT_SECONDS),
        )
        if outcome.get("accepted") is True and not r29._review_receipt_matches(
            outcome,
            review,
            review_store.operation_ids,
        ):
            outcome["accepted"] = False
            outcome["reason"] = "REVIEW_RECEIPT_MISMATCH"
            review = None
        audit["case"] = outcome
        audit["reviewSinkReceipts"] = len(review_store.operation_ids)
        bounded._write_json_atomic(
            folder / "validated-review-result.json",
            {
                "proposalId": PROPOSAL_ID,
                "runId": RUN_ID,
                "humanReviewStatus": "REQUIRED_NOT_PERFORMED",
                "activationAllowed": False,
                "result": review,
            },
        )
        if outcome.get("accepted") is True:
            audit["status"] = "LITERAL_V6_EXTRACTION_SUCCEEDED_REVIEW_REQUIRED"
            return_code = 0
        else:
            audit["status"] = "AI_ACCEPTANCE_FAILED"
    except BaseException as error:
        audit["status"] = "FAILED"
        audit["errorType"] = type(error).__name__
    finally:
        ai_budget.stop()
        cleanup_ok = await _cleanup_with_hard_deadline(hard_deadline, ai, plans)
        audit["cleanupStatus"] = "COMPLETE" if cleanup_ok else "FAILED"
        audit["finishedAt"] = datetime.now(bounded._SHANGHAI).isoformat()
        audit["boundedWorkElapsedMs"] = max(0, int((monotonic() - session_started) * 1_000))
        audit["ai"] = ai_budget.snapshot()
        audit["market"] = market_budget.snapshot()
        audit["marketCallsObserved"] = audit["market"]["totalAttempts"]
        if database.exists():
            try:
                counts = _database_counts(database)
            except OSError, sqlite3.Error:
                counts = {}
                audit["status"] = "LOCAL_STATE_VERIFICATION_FAILED"
                return_code = 1
            audit["databaseCounts"] = counts
            if any(counts.values()):
                audit["status"] = "ISOLATION_VIOLATION"
                return_code = 1
        if audit["ai"]["totalAttempts"] > 1 or audit["market"]["totalAttempts"] != 0:
            audit["status"] = "PHYSICAL_ATTEMPT_BOUNDARY_VIOLATION"
            return_code = 1
        if not cleanup_ok:
            audit["status"] = "SHUTDOWN_FAILED"
            return_code = 1
        bounded._write_json_atomic(folder / "audit.json", audit)
        journal.complete(status=str(audit["status"]), ai=audit["ai"], market=audit["market"])
        print(json.dumps(audit, ensure_ascii=True, sort_keys=True), flush=True)
    return return_code


_WATCHDOG_BOOTSTRAP = (
    "import json,sys; "
    "from scripts.ai_transient_acceptance import _watchdog_child_main; "
    "raise SystemExit(_watchdog_child_main(json.loads(sys.stdin.read())))"
)


def _run_under_parent_watchdog(child_payload: dict[str, str]) -> int:
    child_environment = os.environ.copy()
    existing_python_path = child_environment.get("PYTHONPATH", "")
    child_environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(bounded._ROOT / "src"), str(bounded._ROOT), existing_python_path)
        if part
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _WATCHDOG_BOOTSTRAP,
            ],
            cwd=bounded._ROOT,
            check=False,
            capture_output=True,
            env=child_environment,
            input=json.dumps(child_payload, ensure_ascii=True, sort_keys=True),
            text=True,
            timeout=TOTAL_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _record_watchdog_terminal("HARD_DEADLINE_EXCEEDED")
        print(json.dumps({"status": "HARD_DEADLINE_EXCEEDED"}, sort_keys=True))
        return 1
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({"status": "CHILD_PROCESS_UNAVAILABLE"}, sort_keys=True))
        return 1

    payload: dict[str, object] | None = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is None:
        payload = {"status": "CHILD_RESULT_UNAVAILABLE"}
    print(json.dumps(_safe_child_payload(payload), ensure_ascii=True, sort_keys=True), flush=True)
    return completed.returncode


_SAFE_CHILD_STATUSES = frozenset(
    {
        "LITERAL_V6_EXTRACTION_SUCCEEDED_REVIEW_REQUIRED",
        "AI_ACCEPTANCE_FAILED",
        "FAILED",
        "LOCAL_STATE_VERIFICATION_FAILED",
        "ISOLATION_VIOLATION",
        "PHYSICAL_ATTEMPT_BOUNDARY_VIOLATION",
        "SHUTDOWN_FAILED",
        "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT",
        "NOT_RUN_INVALID_ID_OR_WINDOW",
        "NOT_RUN_SESSION_ALREADY_CLAIMED",
    }
)


def _safe_child_payload(payload: dict[str, object]) -> dict[str, object]:
    status = payload.get("status")
    if not isinstance(status, str) or status not in _SAFE_CHILD_STATUSES:
        return {"status": "CHILD_RESULT_UNAVAILABLE"}
    safe: dict[str, object] = {"status": status}
    if payload.get("proposalId") == PROPOSAL_ID:
        safe["proposalId"] = PROPOSAL_ID
    if payload.get("runId") == RUN_ID:
        safe["runId"] = RUN_ID
    for source_key, target_key in (
        ("ai", "aiPhysicalAttempts"),
        ("market", "marketPhysicalAttempts"),
    ):
        snapshot = payload.get(source_key)
        if isinstance(snapshot, dict):
            attempts = snapshot.get("totalAttempts")
            if type(attempts) is int and attempts >= 0:
                safe[target_key] = attempts
    elapsed = payload.get("boundedWorkElapsedMs")
    if type(elapsed) is int and elapsed >= 0:
        safe["boundedWorkElapsedMs"] = elapsed
    return safe


def _record_watchdog_terminal(status: str) -> None:
    folder = SESSION_ROOT / RUN_ID
    if not folder.is_dir():
        return
    finished_at = datetime.now(bounded._SHANGHAI).isoformat()
    evidence = {
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
        "status": status,
        "packageSha256": EXPECTED_PACKAGE_HASH,
        "finishedAt": finished_at,
        "hardTotalSeconds": TOTAL_SECONDS,
    }
    try:
        bounded._write_json_atomic(folder / "watchdog-terminal.json", evidence)
        audit_path = folder / "audit.json"
        if audit_path.is_file():
            audit = json.loads(audit_path.read_text("utf-8"))
            if (
                isinstance(audit, dict)
                and audit.get("proposalId") == PROPOSAL_ID
                and audit.get("runId") == RUN_ID
            ):
                audit["candidateStatusBeforeWatchdog"] = audit.get("status")
                audit["status"] = status
                audit["watchdogTerminalPresent"] = True
                audit["finishedAt"] = finished_at
                bounded._write_json_atomic(audit_path, audit)
        journal_path = folder / "physical-attempts.json"
        if journal_path.is_file():
            journal = json.loads(journal_path.read_text("utf-8"))
            if (
                isinstance(journal, dict)
                and journal.get("proposalId") == PROPOSAL_ID
                and journal.get("runId") == RUN_ID
            ):
                journal["status"] = status
                journal["normalAuditPresent"] = audit_path.is_file()
                journal["watchdogTerminalPresent"] = True
                journal["finishedAt"] = finished_at
                bounded._write_json_atomic(journal_path, journal)
    except (OSError, UnicodeError, ValueError, TypeError):
        pass


def _watchdog_child_main(payload: object) -> int:
    required = {
        "authorization",
        "runId",
        "configPath",
        "expectedHead",
        "approvalAttestation",
        "approvalAttestationSha256",
    }
    if not isinstance(payload, dict) or set(payload) != required or not all(
        isinstance(payload[key], str) and payload[key] for key in required
    ):
        print(json.dumps({"status": "NOT_RUN_INVALID_CHILD_PAYLOAD"}))
        return 2
    config_path = Path(payload["configPath"])
    approval_path = Path(payload["approvalAttestation"])
    preflight = _preflight(
        config_path=config_path,
        expected_head=payload["expectedHead"],
        approval_attestation_path=approval_path,
        expected_approval_attestation_hash=payload["approvalAttestationSha256"],
    )
    if payload["authorization"] != AUTHORIZATION or not preflight.get("ready"):
        print(json.dumps({"status": "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"}))
        return 2
    if payload["runId"] != RUN_ID or not _eligible(datetime.now(bounded._SHANGHAI)):
        print(json.dumps({"status": "NOT_RUN_INVALID_ID_OR_WINDOW"}))
        return 2
    try:
        return asyncio.run(
            _run_candidate(
                config_path=config_path,
                expected_head=payload["expectedHead"],
                approval_attestation_path=approval_path,
                expected_approval_attestation_hash=payload[
                    "approvalAttestationSha256"
                ],
            )
        )
    except FileExistsError:
        print(json.dumps({"status": "NOT_RUN_SESSION_ALREADY_CLAIMED"}))
        return 2
    except BaseException:
        print(json.dumps({"status": "FAILED"}))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-egress-review", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config-path", type=Path)
    parser.add_argument("--expected-head", default="")
    parser.add_argument("--approval-attestation", type=Path)
    parser.add_argument("--approval-attestation-sha256", default="")
    args = parser.parse_args(argv)
    if args.prepare_egress_review:
        _write_egress_review_package()
    preflight = _preflight(
        config_path=args.config_path,
        expected_head=args.expected_head or None,
        approval_attestation_path=args.approval_attestation,
        expected_approval_attestation_hash=args.approval_attestation_sha256 or None,
    )
    if not args.execute:
        print(json.dumps(preflight, ensure_ascii=True, sort_keys=True))
        return 0
    if args.config_path is None:
        print(json.dumps({"status": "NOT_RUN_CONFIG_PATH_REQUIRED"}))
        return 2
    if args.authorize != AUTHORIZATION or not preflight.get("ready"):
        print(json.dumps({"status": "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"}))
        return 2
    if args.run_id != RUN_ID or not _eligible(datetime.now(bounded._SHANGHAI)):
        print(json.dumps({"status": "NOT_RUN_INVALID_ID_OR_WINDOW"}))
        return 2
    if args.execute:
        child_payload = {
            "authorization": args.authorize,
            "runId": args.run_id,
            "configPath": str(args.config_path),
            "expectedHead": args.expected_head,
            "approvalAttestation": str(args.approval_attestation),
            "approvalAttestationSha256": args.approval_attestation_sha256,
        }
        return _run_under_parent_watchdog(child_payload)
    raise AssertionError("unreachable execution mode")


if __name__ == "__main__":
    raise SystemExit(main())
