"""R30 one-POST v6 timeout-budget candidate. Default invocation is offline-only."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
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

PROPOSAL_ID = "R30-20260917-V6-LITERAL-TIMEOUT-BUDGET-1"
AUTHORIZATION = "R30_20260917_LITERAL_ONE_AI_ZERO_MARKET_TIMEOUT_BUDGET_ACCEPTANCE"
RUN_ID = "r30-20260917-a"
CASE_ID = "LITERAL"
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V6
AI_OUTPUT_TOKENS = 8192
AI_CAPS = {CASE_ID: 1}
AI_TOTAL = 1
MARKET_CAPS = {key: 0 for key in r29.MARKET_CAPS}
MARKET_TOTAL = 0
TRANSPORT_TIMEOUT_SECONDS = 30
READ_TIMEOUT_SECONDS = 60
PROVIDER_TIMEOUT_SECONDS = 65
TERMINAL_WAIT_SECONDS = 66
CLEANUP_SECONDS = 15
TOTAL_SECONDS = 81
SESSION_ROOT = bounded._ROOT / "data/r30-ai-timeout-budget-acceptance"
REVIEW_ROOT = bounded._ROOT / "data/r30-ai-timeout-budget-review"
EXTERNAL_DESTINATION = r29.EXTERNAL_DESTINATION
EXPECTED_SOURCE_HASH = r29.EXPECTED_SOURCE_HASH
EXPECTED_PROMPT_HASH = r29.EXPECTED_PROMPT_HASH
EXPECTED_PROMPT_UTF8_BYTES = r29.EXPECTED_PROMPT_UTF8_BYTES
EXPECTED_CONFIG_HASH = r29.EXPECTED_CONFIG_HASH
EXPECTED_REQUEST_BODY_HASH = "c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c"
R29_PACKAGE_HASH = "328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9"
OFFICIAL_DOCS_CHECKED_AT = "2026-09-17T09:43:04+08:00"
CONSERVATIVE_PEAK_COST_USD = "0.01582704"
EXPECTED_REVIEW_HASHES = {
    "egress-material.json": "3fc51132f4ac639cda3f076c821c182385141b5a5ca656d35558c76822d2183a",
    "egress-review.md": "9fc8143d6452029d9cd6e2dc122703081cc4a758177187803d83a0b3ba3b3d5f",
    "egress-review.zh-CN.md": "b66c61c3ce42a5845119d16babfe38f9af6da74608fc484eddc931311f8292cc",
    "manifest.json": "4a5277035418dfdcc237c51fd69281734354d78976e6d5b8ad9f4deb8ff181a3",
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
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _request_body(prompt: str) -> dict[str, object]:
    return r29._request_body(prompt)


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
            "connectWritePoolTimeoutSeconds": TRANSPORT_TIMEOUT_SECONDS,
            "readTimeoutSeconds": READ_TIMEOUT_SECONDS,
            "providerOverallTimeoutSeconds": PROVIDER_TIMEOUT_SECONDS,
            "terminalObservationSeconds": TERMINAL_WAIT_SECONDS,
            "totalSeconds": TOTAL_SECONDS,
            "cleanupSecondsMaximum": CLEANUP_SECONDS,
        },
        "controlledHypothesis": {
            "statement": (
                "R29 may have been locally truncated by its 30-second overall deadline; "
                "R30 tests one longer bounded wait without claiming a remote-provider fix"
            ),
            "evidence": {
                "r27ValidatedResponseSeconds": "29.542",
                "r29TimeoutKind": "OVERALL_DEADLINE",
                "r29TimeoutElapsedMs": 30009,
            },
            "unknowns": [
                "whether DeepSeek received, completed, or billed R29",
                "whether R30 will return before either local deadline",
                "actual generation throughput and response size",
            ],
        },
        "comparisonWithR29": {
            "r29PackageSha256": R29_PACKAGE_HASH,
            "sourceBytesChanged": False,
            "promptBytesChanged": False,
            "requestBodyBytesChanged": False,
            "requestBodyCanonicalSha256": EXPECTED_REQUEST_BODY_HASH,
            "sentFieldsChanged": [],
            "localOnlyChanges": [
                "read timeout 30s -> 60s",
                "provider overall deadline 30s -> 65s",
                "terminal observation 31s -> 66s",
                "candidate hard total 45s -> 81s",
            ],
            "unchangedLocalStages": "connect/write/pool remain 30 seconds",
        },
        "officialSnapshot": {
            "checkedAt": OFFICIAL_DOCS_CHECKED_AT,
            "requestAlias": bounded.APPROVED_MODEL,
            "documentedModelVersion": "DeepSeek-V4-Pro",
            "cacheHitInputUsdPerMillion": "0.003625",
            "cacheMissInputUsdPerMillion": "0.435",
            "outputUsdPerMillion": "0.87",
            "conservativeInputTokenBound": 20_000,
            "maximumOutputTokens": AI_OUTPUT_TOKENS,
            "conservativePeakEstimateUsd": CONSERVATIVE_PEAK_COST_USD,
            "actualBillingAndTaxes": "UNKNOWN",
            "sources": [
                "https://api-docs.deepseek.com/api/create-chat-completion/",
                "https://api-docs.deepseek.com/quick_start/pricing/",
                "https://www.python-httpx.org/advanced/timeouts/",
                "https://docs.python.org/3/library/asyncio-task.html#timeouts",
            ],
        },
        "requests": {
            CASE_ID: {
                "purpose": "one-shot real v6 extraction with an isolated client wait budget",
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
        requests = material["requests"]
        request = requests[CASE_ID]
        body = request["body"]
        comparison = material["comparisonWithR29"]
        candidate_source = request["sourceText"]
        candidate_prompt = body["messages"][0]["content"]
        return bool(
            material["destination"] == EXTERNAL_DESTINATION
            and material["method"] == "POST"
            and tuple(requests) == (CASE_ID,)
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
            and comparison["sourceBytesChanged"] is False
            and comparison["promptBytesChanged"] is False
            and comparison["requestBodyBytesChanged"] is False
            and comparison["sentFieldsChanged"] == []
        )
    except (AttributeError, KeyError, TypeError, UnicodeError):
        return False


def _render_review(material: dict[str, object], *, chinese: bool) -> str:
    request = material["requests"][CASE_ID]
    body = request["body"]
    prompt = body["messages"][0]["content"]
    fixed_body = {key: value for key, value in body.items() if key != "messages"}
    snapshot = material["officialSnapshot"]
    comparison = material["comparisonWithR29"]
    if chinese:
        title = "R30 AI 超时预算候选精确外发审阅材料"
        intro = (
            "本文件完整展示唯一拟外发的合成 LITERAL 原文、完整 v6 user 提示词及固定请求字段。"
            "原文、提示词与发送请求体相对 R29 逐字节不变；唯一实验变量是本地客户端等待预算。"
        )
        hypothesis = (
            "受控假设：R29 可能被本地 30 秒整体截止提前截断；R30 仅检验更长且有硬上限的等待，"
            "不宣称远端问题已修复。"
        )
        source_label = "将外发的精确原文"
        prompt_label = "将外发的精确唯一 user 提示词"
        body_label = "不含消息内容的固定请求体字段"
        cost = "保守单次峰值估算"
        billing = "真实用量、缓存拆分、税费及账户调整未知"
    else:
        title = "R30 AI timeout-budget exact egress review material"
        intro = (
            "This file shows the sole synthetic LITERAL source, complete v6 user prompt, and "
            "fixed request fields proposed for egress. Source, prompt, and sent request-body "
            "bytes are unchanged from R29; only local client wait budgets change."
        )
        hypothesis = (
            "Controlled hypothesis: R29 may have been cut off by its local 30-second overall "
            "deadline. R30 tests one longer hard-bounded wait and does not claim a remote fix."
        )
        source_label = "Exact source text to be sent"
        prompt_label = "Exact sole user prompt to be sent"
        body_label = "Fixed request-body fields excluding message content"
        cost = "Conservative single-request peak estimate"
        billing = "Actual usage, cache split, taxes, and account adjustments are unknown"
    return "\n".join(
        [
            f"# {title}",
            "",
            intro,
            "",
            hypothesis,
            "",
            f"- Recipient: `{material['recipient']}`",
            f"- Destination: `{material['destination']}`",
            f"- Method: `{material['method']}`",
            "- Authorization header: `<credential omitted; not part of approval material>`",
            "- Physical POST cap: `1`; retries: `0`; market calls (including trade_cal): `0`",
            f"- Source SHA-256: `{request['sourceSha256']}`",
            f"- Prompt SHA-256: `{request['promptSha256']}`",
            f"- Request-body canonical SHA-256: `{request['bodyCanonicalSha256']}`",
            f"- R29 package SHA-256 compared: `{comparison['r29PackageSha256']}`",
            "- Sent-field difference from R29: `NONE`",
            "- Local timeout difference: read `30s -> 60s`; overall `30s -> 65s`; "
            "connect/write/pool remain `30s`",
            "- Candidate hard total: `81s`, including terminal observation and at most "
            "`15s` cleanup",
            f"- {cost}: `USD {snapshot['conservativePeakEstimateUsd']}`; {billing}.",
            f"- Official snapshot time: `{snapshot['checkedAt']}`",
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
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_egress_review_package(root: Path = REVIEW_ROOT) -> tuple[Path, Path]:
    material = _egress_review_material()
    if not _validate_material(material):
        raise ValueError("R30 egress material does not match the frozen R29 request")
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


def _review_package_matches() -> bool:
    return all(
        (REVIEW_ROOT / name).is_file()
        and expected != "PENDING"
        and _file_sha256(REVIEW_ROOT / name) == expected
        for name, expected in EXPECTED_REVIEW_HASHES.items()
    )


def _git_state() -> tuple[bool, str | None]:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=bounded._ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=bounded._ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None
    return not status.stdout.strip(), head.stdout.strip() or None


def _preflight(*, config_path: Path | None = None) -> dict[str, object]:
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
    clean, head = _git_state()
    material_matches = _validate_material(_egress_review_material())
    package_matches = _review_package_matches()
    unclaimed = not (SESSION_ROOT / "_session_claimed").exists()
    eligible = _eligible(now)
    ready = bool(
        ai_ready and material_matches and package_matches and unclaimed and eligible and clean
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
        "freshClaimAvailable": unclaimed,
        "configSourceStatus": config_status,
        "configSha256Matches": config_hash_matches,
        "configCopiedIntoWorktree": False,
        "externalDestination": EXTERNAL_DESTINATION,
        "materialMatchesFrozenR29Request": material_matches,
        "reviewPackageMatchesCandidate": package_matches,
        "sourceSha256": EXPECTED_SOURCE_HASH,
        "promptSha256": EXPECTED_PROMPT_HASH,
        "requestBodyCanonicalSha256": EXPECTED_REQUEST_BODY_HASH,
        "ai": {
            "host": None if endpoint is None else endpoint.hostname,
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
        "officialRouteRecheckRequiredBeforeExecute": True,
        "officialPriceRecheckRequiredBeforeExecute": True,
        "balanceOrModelListProbeAllowed": False,
        "activationAllowed": False,
        "humanReviewRequired": True,
    }


def _assess_terminal(*args: object, **kwargs: object):
    return r29._assess_terminal(*args, **kwargs)


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
    return bounded._claim_session(root, RUN_ID)


def _database_counts(database: Path) -> dict[str, int]:
    return r29._database_counts(database)


async def _cleanup_with_hard_deadline(
    hard_deadline: float,
    *lifecycles: object | None,
    monotonic: Callable[[], float] = monotonic,
) -> bool:
    success = True
    for lifecycle in lifecycles:
        if lifecycle is None:
            continue
        stop = getattr(lifecycle, "stop", None)
        if not callable(stop):
            success = False
            continue
        remaining = min(float(CLEANUP_SECONDS), hard_deadline - monotonic())
        if remaining <= 0:
            success = False
            continue
        try:
            await asyncio.wait_for(stop(), timeout=remaining)
        except BaseException:
            success = False
    return success


async def _run_candidate(
    *,
    config_path: Path,
    session_root: Path = SESSION_ROOT,
    ai_inner_transport: httpx.AsyncBaseTransport | None = None,
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
        ai = bounded._bounded_ai_factory(
            config_path,
            review_store,
            ai_budget,
            database=database,
            inner_transport=ai_inner_transport,
            prompt_version=PROMPT_VERSION,
            max_output_tokens=AI_OUTPUT_TOKENS,
            max_prompt_utf8_bytes=EXPECTED_PROMPT_UTF8_BYTES,
            provider_timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
            transport_timeout_seconds=TRANSPORT_TIMEOUT_SECONDS,
            read_timeout_seconds=READ_TIMEOUT_SECONDS,
        )
        startup = await ai.start()
        if startup.get("configured") is not True or startup.get("diagnosticAvailable") is not True:
            raise bounded.BudgetDenied
        provider_id = (await ai.get_configured_ai()).provider_id
        source = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID][0]
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
            except (OSError, sqlite3.Error):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-egress-review", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config-path", type=Path)
    args = parser.parse_args(argv)
    if args.prepare_egress_review:
        _write_egress_review_package()
    preflight = _preflight(config_path=args.config_path)
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
    try:
        return asyncio.run(_run_candidate(config_path=args.config_path))
    except FileExistsError:
        print(json.dumps({"status": "NOT_RUN_SESSION_ALREADY_CLAIMED"}))
        return 2
    except bounded.BudgetDenied:
        print(json.dumps({"status": "NOT_RUN_PRECONDITION_DENIED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
