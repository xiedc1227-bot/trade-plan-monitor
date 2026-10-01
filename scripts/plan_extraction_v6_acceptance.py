"""R29 one-POST plan-extract-v6 acceptance candidate. Default invocation is offline-only."""

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
from scripts import ai_timeout_diagnostic as r27
from scripts import bounded_live_acceptance as bounded
from scripts import plan_extraction_acceptance as r25

from trade_plan_monitor.ai.models import PlanExtractionResult
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V6
from trade_plan_monitor.ai.review import (
    build_server_review_snapshot,
    load_explicit_plan_draft_json,
)
from trade_plan_monitor.web.routers.plans import (
    PlanExtractionCommand,
    PlanExtractionOperationStatus,
    PlanExtractionService,
    PlanExtractionView,
)
from trade_plan_monitor.web.schemas import MutationContext

PROPOSAL_ID = "R29-20260917-V6-LITERAL-ACCEPTANCE-1"
AUTHORIZATION = "R29_20260917_LITERAL_ONE_AI_ZERO_MARKET_V6_ACCEPTANCE"
RUN_ID = "r29-20260917-a"
CASE_ID = "LITERAL"
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V6
AI_OUTPUT_TOKENS = 8192
AI_CAPS = {CASE_ID: 1}
AI_TOTAL = 1
MARKET_CAPS = {
    "trade_cal": 0,
    "stk_limit": 0,
    "daily": 0,
    "rt_min_daily": 0,
    "rt_min": 0,
    "idx_mins": 0,
    "rt_idx_min_daily": 0,
    "index_daily": 0,
}
MARKET_TOTAL = 0
PROVIDER_TIMEOUT_SECONDS = 30
TERMINAL_WAIT_SECONDS = 31
CLEANUP_SECONDS = 15
TOTAL_SECONDS = 45
SESSION_ROOT = bounded._ROOT / "data/r29-v6-extraction-acceptance"
REVIEW_ROOT = bounded._ROOT / "data/r29-v6-extraction-review"
EXTERNAL_DESTINATION = "https://api.deepseek.com/chat/completions"
EXPECTED_SOURCE_HASH = "0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191"
EXPECTED_PROMPT_HASH = "7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba"
EXPECTED_PROMPT_UTF8_BYTES = 19_359
EXPECTED_CONFIG_HASH = "89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428"
V5_LITERAL_PROMPT_HASH = "660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89"
OFFICIAL_DOCS_CHECKED_AT = "2026-09-16T11:09:28+08:00"
CONSERVATIVE_PEAK_COST_USD = "0.05884032"
EXPECTED_REVIEW_HASHES = {
    "egress-material.json": "e017fc3d453c943a020cb438644ae05e41f1738d8055ddd4d8c73404187b5bc1",
    "egress-review.md": "aadffd35eda02ef3cfe238ed00abd5215fc8c0ade48f012dce19e22055d2b030",
    "egress-review.zh-CN.md": "28e493b5a50f31ca20f3d8db88924b62e37f6cd6a2b37a33fcb85e87a69f38b8",
    "manifest.json": "ef8d955294d7bac991f104604243887cb4a180968d3e209bec5c956c0f662240",
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
_SAFE_DIAGNOSTIC_FIELDS = r27._SAFE_DIAGNOSTIC_FIELDS


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 16) and time(13, 30) <= now.time() <= time(15, 0)


def _request_body(prompt: str) -> dict[str, object]:
    return {
        "model": bounded.APPROVED_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": AI_OUTPUT_TOKENS,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def _egress_review_material() -> dict[str, object]:
    source, prompt = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID]
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
            "providerTimeoutSeconds": PROVIDER_TIMEOUT_SECONDS,
            "totalSeconds": TOTAL_SECONDS,
            "cleanupSecondsMaximum": CLEANUP_SECONDS,
        },
        "v5ToV6Change": {
            "previousPromptVersion": "plan-extract-v5",
            "previousLiteralPromptSha256": V5_LITERAL_PROMPT_HASH,
            "candidatePromptVersion": PROMPT_VERSION,
            "candidateLiteralPromptSha256": EXPECTED_PROMPT_HASH,
            "summary": (
                "v6 adds rules 12-14 for the exact origin/reference matrix, unique binding "
                "identities, scalar type/value/unit checks, ALL/ANY structure bindings, and "
                "reciprocal SOURCE mapping; the output schema is unchanged"
            ),
            "priorApprovalCoverage": "NO; v5 approval does not cover changed v6 prompt bytes",
        },
        "officialSnapshot": {
            "checkedAt": OFFICIAL_DOCS_CHECKED_AT,
            "requestAlias": bounded.APPROVED_MODEL,
            "documentedModelVersion": "DeepSeek-V4-Pro-0813",
            "peakCacheMissInputUsdPerMillion": "1.32",
            "peakOutputUsdPerMillion": "3.96",
            "conservativeInputTokenBound": 20_000,
            "maximumOutputTokens": AI_OUTPUT_TOKENS,
            "conservativePeakEstimateUsd": CONSERVATIVE_PEAK_COST_USD,
            "actualBillingAndTaxes": "UNKNOWN",
            "sources": [
                "https://api-docs.deepseek.com/api/create-chat-completion/",
                "https://api-docs.deepseek.com/quick_start/pricing/",
            ],
        },
        "requests": {
            CASE_ID: {
                "purpose": "one-shot real v6 literal extraction acceptance candidate",
                "origin": "tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText",
                "sourceText": source,
                "sourceSha256": sha256(source.encode("utf-8")).hexdigest(),
                "promptSha256": sha256(prompt.encode("utf-8")).hexdigest(),
                "promptUtf8Bytes": len(prompt.encode("utf-8")),
                "body": _request_body(prompt),
            }
        },
    }


def _validate_material(material: dict[str, object]) -> bool:
    try:
        source, prompt = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID]
        requests = material["requests"]
        request = requests[CASE_ID]
        body = request["body"]
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
            and body == _request_body(prompt)
        )
    except AttributeError, KeyError, TypeError, UnicodeError:
        return False


def _render_review(material: dict[str, object], *, chinese: bool) -> str:
    request = material["requests"][CASE_ID]
    body = request["body"]
    prompt = body["messages"][0]["content"]
    fixed_body = {key: value for key, value in body.items() if key != "messages"}
    snapshot = material["officialSnapshot"]
    change = material["v5ToV6Change"]
    if chinese:
        title = "R29 plan-extract-v6 精确外发审阅材料"
        intro = (
            "本文件完整展示唯一拟外发的合成 LITERAL 原文、完整 v6 user 提示词及其余"
            "固定请求字段。原文与提示词逐字保留且不翻译；凭据被排除。v6 改变了提示词"
            "字节，因此此前 v5 的 R25/R27 批准不覆盖本候选。"
        )
        change_label = "与 v5 的变化"
        source_label = "将外发的精确原文"
        prompt_label = "将外发的精确唯一 user 提示词"
        body_label = "不含消息内容的固定请求体字段"
        cost = "保守单次峰值估算"
        billing = "真实账单、缓存拆分、税费及账户调整未知"
    else:
        title = "R29 plan-extract-v6 exact egress review material"
        intro = (
            "This file shows the sole synthetic LITERAL source, complete v6 user prompt, and "
            "all other fixed request fields proposed for egress. Source and prompt bytes are "
            "exact and untranslated; credentials are excluded. Because v6 changes prompt "
            "bytes, the earlier R25/R27 v5 approvals do not cover this candidate."
        )
        change_label = "Change from v5"
        source_label = "Exact source text to be sent"
        prompt_label = "Exact sole user prompt to be sent"
        body_label = "Fixed request-body fields excluding message content"
        cost = "Conservative single-request peak estimate"
        billing = "Actual billing, cache split, taxes, and account adjustments are unknown"
    return "\n".join(
        [
            f"# {title}",
            "",
            intro,
            "",
            f"- Recipient: `{material['recipient']}`",
            f"- Destination: `{material['destination']}`",
            f"- Method: `{material['method']}`",
            "- Authorization header: `<credential omitted; not part of approval material>`",
            "- Content-Type: `application/json`",
            "- Physical POST cap: `1`; retries: `0`; market calls (including trade_cal): `0`",
            f"- Source SHA-256: `{request['sourceSha256']}`",
            f"- Prompt SHA-256: `{request['promptSha256']}`",
            f"- Prompt UTF-8 bytes: `{request['promptUtf8Bytes']}`",
            f"- {cost}: `USD {snapshot['conservativePeakEstimateUsd']}`; {billing}.",
            f"- Official snapshot time: `{snapshot['checkedAt']}`",
            "",
            f"## {change_label}",
            "",
            "- `plan-extract-v5` LITERAL prompt SHA-256: "
            f"`{change['previousLiteralPromptSha256']}`",
            "- `plan-extract-v6` LITERAL prompt SHA-256: "
            f"`{change['candidateLiteralPromptSha256']}`",
            f"- {change['summary']}",
            f"- Approval coverage: {change['priorApprovalCoverage']}",
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


def _write_egress_review_package(root: Path = REVIEW_ROOT) -> tuple[Path, Path]:
    material = _egress_review_material()
    if not _validate_material(material):
        raise ValueError("R29 egress material does not match the frozen v6 contract")
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


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    except OSError, subprocess.SubprocessError:
        return False, None
    return not status.stdout.strip(), head.stdout.strip() or None


def _preflight(*, config_path: Path | None = None) -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config

    path = config_path or (bounded._ROOT / "config/app.yaml")
    config_status = "MISSING"
    endpoint = None
    key_present = False
    selected = False
    config_hash_matches = False
    ai_ready = False
    if path.is_file():
        try:
            config_hash_matches = _file_sha256(path) == EXPECTED_CONFIG_HASH
            configuration = load_application_config(path)
            ai = configuration.ai
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
        "materialMatchesFrozenV6": material_matches,
        "reviewPackageMatchesCandidate": package_matches,
        "sourceSha256": EXPECTED_SOURCE_HASH,
        "promptSha256": EXPECTED_PROMPT_HASH,
        "ai": {
            "host": None if endpoint is None else endpoint.hostname,
            "selectedModelConfigured": selected,
            "model": bounded.APPROVED_MODEL,
            "keyPresent": key_present,
        },
        "limits": {
            "aiPhysicalAttempts": AI_TOTAL,
            "aiPerInputAttempts": AI_CAPS,
            "marketPhysicalAttempts": MARKET_TOTAL,
            "marketPerEndpointAttempts": MARKET_CAPS,
            "providerTimeoutSeconds": PROVIDER_TIMEOUT_SECONDS,
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


def _read_diagnostic(path: Path, operation_id: UUID) -> dict[str, object] | None:
    return r27._read_diagnostic(path, operation_id)


def _safe_diagnostic(record: dict[str, object] | None) -> dict[str, object] | None:
    return r27._safe_diagnostic(record)


def _assess_terminal(
    *,
    source_text: str,
    view: PlanExtractionView,
    diagnostic_path: Path,
) -> tuple[dict[str, object], dict[str, object] | None]:
    record = _read_diagnostic(diagnostic_path, view.id)
    safe = _safe_diagnostic(record)
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    base: dict[str, object] = {
        "caseId": CASE_ID,
        "operationId": str(view.id),
        "status": view.status.value,
        "sourceSha256": source_hash,
        "accepted": False,
        "oracleStatus": "NOT_RUN",
        "diagnostic": safe,
    }
    if (
        record is None
        or not r27._supported_diagnostic_record(record)
        or record.get("operationId") != str(view.id)
        or view.diagnostic_status != "RECORDED"
    ):
        base["reason"] = "V2_DIAGNOSTIC_MISSING_OR_INVALID"
        return base, None
    if view.status is not PlanExtractionOperationStatus.SUCCEEDED:
        base["reason"] = (
            "TIMEOUT_DIAGNOSTIC_RECORDED"
            if record.get("providerErrorCode") == "TIMEOUT"
            and record.get("timeoutKind") is not None
            and record.get("timeoutElapsedMs") is not None
            else "EXTRACTION_FAILED_DIAGNOSTIC_RECORDED"
        )
        return base, None
    if (
        view.source_text_sha256 != source_hash
        or view.model != bounded.APPROVED_MODEL
        or view.prompt_version != PROMPT_VERSION
        or record.get("stage") != "completed"
        or record.get("reason") != "NONE"
        or record.get("finishReason") != "stop"
        or record.get("modelMatchesConfigured") is not True
        or view.draft_plan_json is None
        or view.mapping is None
    ):
        base["reason"] = "MODEL_OR_COMPLETION_RECEIPT_REJECTED"
        return base, None
    try:
        draft = load_explicit_plan_draft_json(view.draft_plan_json)
        mapping = view.mapping.to_domain()
        snapshot = build_server_review_snapshot(
            source_text=source_text,
            draft=draft,
            mapping=mapping,
        )
        accepted = r25._literal_oracle_matches(
            draft_data=draft.model_dump(mode="json"),
            mapping=mapping,
            source_text=source_text,
        )
    except IndexError, KeyError, TypeError, UnicodeError, ValueError:
        accepted = False
        snapshot = None
    base["accepted"] = accepted
    base["oracleStatus"] = "ACCEPTED" if accepted else "MISMATCH"
    base["reason"] = "ORACLE_ACCEPTED" if accepted else "ORACLE_MISMATCH"
    if snapshot is not None:
        base["reviewIssueCodes"] = sorted({item.code for item in snapshot.required_issues})
        base["canActivateBeforeHumanReview"] = snapshot.can_activate
    if view.usage is not None:
        base["usage"] = view.usage.model_dump(mode="json", by_alias=True)
    return (
        base,
        view.model_dump(mode="json", by_alias=True) if accepted else None,
    )


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


def _review_receipt_matches(
    outcome: dict[str, object],
    review: dict[str, object] | None,
    operation_ids: list[str],
) -> bool:
    operation_id = outcome.get("operationId")
    return bool(
        outcome.get("accepted") is True
        and review is not None
        and isinstance(operation_id, str)
        and operation_ids == [operation_id]
    )


def _claim_session(root: Path = SESSION_ROOT) -> Path:
    return bounded._claim_session(root, RUN_ID)


def _database_counts(database: Path) -> dict[str, int]:
    return r27._database_counts(database)


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
        if outcome.get("accepted") is True and not _review_receipt_matches(
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
