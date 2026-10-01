"""R27 one-POST AI timeout diagnostic. Default invocation is offline-only."""

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
from scripts import plan_extraction_acceptance as r25

from trade_plan_monitor.ai.models import PlanExtractionResult
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5
from trade_plan_monitor.ai.provider import AIProviderTransientKind
from trade_plan_monitor.web.routers.plans import (
    PlanExtractionCommand,
    PlanExtractionOperationStatus,
    PlanExtractionService,
    PlanExtractionView,
)
from trade_plan_monitor.web.schemas import MutationContext

PROPOSAL_ID = "R27-20260916-AI-TIMEOUT-DIAGNOSTIC-1"
AUTHORIZATION = "R27_20260916_LITERAL_ONE_AI_ZERO_MARKET_DIAGNOSTIC_V2"
RUN_ID = "r27-20260916-a"
CASE_ID = "LITERAL"
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V5
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
SESSION_ROOT = bounded._ROOT / "data/r27-ai-timeout-diagnostic"
REVIEW_ROOT = bounded._ROOT / "data/r27-ai-timeout-review"
EXTERNAL_DESTINATION = "https://api.deepseek.com/chat/completions"
EXPECTED_SOURCE_HASH = "0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191"
EXPECTED_PROMPT_HASH = "660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89"
EXPECTED_REVIEW_HASHES = {
    "egress-review.md": "cb0217addc5efde66f5f1a50d6b1eceac2c6b09121a422d92bfe1e0712e23554",
    "egress-review.zh-CN.md": "4f282bd6cd384ca24e351c3fd3eae03db23d678ffd349ddff1d386a1a249250b",
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
_SAFE_DIAGNOSTIC_FIELDS = (
    "version",
    "operationId",
    "status",
    "stage",
    "reason",
    "path",
    "schemaErrorType",
    "providerErrorCode",
    "transientKind",
    "timeoutKind",
    "timeoutElapsedMs",
    "finishReason",
    "modelMatchesConfigured",
    "attempts",
)
_SAFE_TRANSIENT_KINDS = frozenset(kind.value for kind in AIProviderTransientKind)


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 16) and time(10, 0) <= now.time() <= time(12, 0)


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
        "sourceClassification": "SYNTHETIC_VERSIONED_TEST_FIXTURE",
        "containsSyntheticHoldingLanguage": True,
        "containsRealAccountOrCredential": False,
        "authorizationHeader": "<credential omitted; not part of approval material>",
        "priorApprovalPackage": {
            "englishSha256": "6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d",
            "chineseSha256": "4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0",
            "scope": "R25 exact LITERAL source and sole user prompt",
        },
        "requests": {
            CASE_ID: {
                "purpose": "one-shot timeout-phase diagnosis or literal extraction result",
                "origin": "tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText",
                "sourceText": source,
                "sourceSha256": sha256(source.encode("utf-8")).hexdigest(),
                "promptSha256": sha256(prompt.encode("utf-8")).hexdigest(),
                "body": _request_body(prompt),
            }
        },
    }


def _validate_material(material: dict[str, object]) -> bool:
    try:
        approved_source, approved_prompt = bounded.approved_sources(
            prompt_version=PROMPT_VERSION
        )[CASE_ID]
        requests = material["requests"]
        request = requests[CASE_ID]
        body = request["body"]
        source = request["sourceText"]
        prompt = body["messages"][0]["content"]
        return bool(
            material["destination"] == EXTERNAL_DESTINATION
            and material["method"] == "POST"
            and tuple(requests) == (CASE_ID,)
            and source.encode("utf-8") == approved_source.encode("utf-8")
            and prompt.encode("utf-8") == approved_prompt.encode("utf-8")
            and sha256(source.encode("utf-8")).hexdigest() == EXPECTED_SOURCE_HASH
            and sha256(prompt.encode("utf-8")).hexdigest() == EXPECTED_PROMPT_HASH
            and request["sourceSha256"] == EXPECTED_SOURCE_HASH
            and request["promptSha256"] == EXPECTED_PROMPT_HASH
            and body == _request_body(approved_prompt)
        )
    except (AttributeError, KeyError, TypeError, UnicodeError):
        return False


def _render_review(material: dict[str, object], *, chinese: bool) -> str:
    request = material["requests"][CASE_ID]
    body = request["body"]
    fixed_body = {key: value for key, value in body.items() if key != "messages"}
    prompt = body["messages"][0]["content"]
    if chinese:
        title = "R27 精确外发审阅材料"
        intro = (
            "本候选仅发送一次 R25 已精确批准的 LITERAL 原文与唯一 user 提示词；"
            "两者逐字节不变。新目的仅为记录 v2 超时阶段或取得真实字面提取结果，"
            "不会发起行情请求，也不构成完整业务验收。该请求可能再次产生费用。"
        )
        source_label = "将外发的精确原文"
        prompt_label = "将外发的精确唯一 user 提示词"
        body_label = "不含消息内容的固定请求体字段"
        approval = "批准来源：R25 精确外发审阅包及用户后续“继续下一步”指令"
        once = "物理 POST 上限：一次；重试：零；行情调用：零"
    else:
        title = "R27 exact egress review material"
        intro = (
            "This candidate sends once only the exact R25-approved LITERAL source and sole "
            "user prompt; both are byte-identical. The new purpose is limited to recording a "
            "v2 timeout phase or obtaining a real literal extraction result. It makes no market "
            "request and is not full business acceptance. The request may incur another charge."
        )
        source_label = "Exact source text to be sent"
        prompt_label = "Exact sole user prompt to be sent"
        body_label = "Fixed request body fields excluding message content"
        approval = "Approval basis: R25 exact egress package and the user's follow-up instruction"
        once = "Physical POST cap: once; retries: zero; market calls: zero"
    return "\n".join(
        [
            f"# {title}",
            "",
            intro,
            "",
            f"- Recipient: `{material['recipient']}`",
            f"- Destination: `{material['destination']}`",
            f"- Method: `{material['method']}`",
            f"- {approval}",
            f"- {once}",
            f"- Source SHA-256: `{request['sourceSha256']}`",
            f"- Prompt SHA-256: `{request['promptSha256']}`",
            f"- Authorization header: `{material['authorizationHeader']}`",
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
        raise ValueError("R27 egress material does not match the approved LITERAL contract")
    root.mkdir(parents=True, exist_ok=True)
    english = root / "egress-review.md"
    chinese = root / "egress-review.zh-CN.md"
    english.write_text(_render_review(material, chinese=False), encoding="utf-8", newline="\n")
    chinese.write_text(_render_review(material, chinese=True), encoding="utf-8", newline="\n")
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
    except (OSError, subprocess.SubprocessError):
        return False, None
    return not status.stdout.strip(), head.stdout.strip() or None


def _preflight() -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config

    config_path = bounded._ROOT / "config/app.yaml"
    try:
        configuration = load_application_config(config_path)
        ai = configuration.ai
        endpoint = urlsplit(str(ai.base_url))
        key_present = bool(ai.api_key)
        selected = bounded.APPROVED_MODEL in {
            ai.model,
            *(item.model for item in ai.additional_models),
        }
        ai_ready = bool(
            key_present
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
        endpoint = None
        key_present = False
        selected = False
        ai_ready = False
    now = datetime.now(bounded._SHANGHAI)
    clean, head = _git_state()
    material_matches = _validate_material(_egress_review_material())
    package_matches = _review_package_matches()
    unclaimed = not (SESSION_ROOT / "_session_claimed").exists()
    eligible = _eligible(now)
    ready = bool(
        ai_ready
        and material_matches
        and package_matches
        and unclaimed
        and eligible
        and clean
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
        "extractionDiagnosticOnly": True,
        "activationAllowed": False,
        "humanReviewRequired": True,
        "externalDestination": EXTERNAL_DESTINATION,
        "materialMatchesApprovedLiteral": material_matches,
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
            "aiOutputTokensPerRequest": AI_OUTPUT_TOKENS,
        },
        "officialRouteRecheckRequiredBeforeExecute": True,
        "officialPriceRecheckRequiredBeforeExecute": True,
        "balanceOrModelListProbeAllowed": False,
    }


def _read_diagnostic(path: Path, operation_id: UUID) -> dict[str, object] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        if record.get("operationId") == str(operation_id):
            return record
    return None


def _safe_diagnostic(record: dict[str, object] | None) -> dict[str, object] | None:
    if record is None:
        return None
    summary = {field: record.get(field) for field in _SAFE_DIAGNOSTIC_FIELDS}
    transient_kind = record.get("transientKind")
    safe_transient_kind = None
    if record.get("version") == 3 and record.get("providerErrorCode") == "TRANSIENT":
        safe_transient_kind = (
            transient_kind if transient_kind in _SAFE_TRANSIENT_KINDS else "UNKNOWN"
        )
    summary["transientKind"] = safe_transient_kind
    summary["usageAvailable"] = record.get("usage") is not None
    return summary


def _supported_diagnostic_record(record: dict[str, object]) -> bool:
    version = record.get("version")
    if version == 2:
        return True
    if version != 3:
        return False
    transient_kind = record.get("transientKind")
    if record.get("providerErrorCode") == "TRANSIENT":
        return transient_kind in _SAFE_TRANSIENT_KINDS
    return transient_kind is None


def _assess_terminal(
    *,
    source_text: str,
    view: PlanExtractionView,
    diagnostic_path: Path,
) -> tuple[dict[str, object], dict[str, object] | None]:
    record = _read_diagnostic(diagnostic_path, view.id)
    safe = _safe_diagnostic(record)
    base: dict[str, object] = {
        "caseId": CASE_ID,
        "operationId": str(view.id),
        "status": view.status.value,
        "sourceSha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "accepted": False,
        "oracleStatus": "NOT_RUN",
        "diagnostic": safe,
    }
    if (
        record is None
        or not _supported_diagnostic_record(record)
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
    assessed, review = r25._assess_extraction(
        case_id=CASE_ID,
        source_text=source_text,
        view=view,
        diagnostic_path=diagnostic_path,
    )
    assessed["diagnostic"] = safe
    assessed["oracleStatus"] = "ACCEPTED" if assessed.get("accepted") is True else "MISMATCH"
    return assessed, review


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
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if row[0] not in {"alembic_version", "monitor_sequence", "sqlite_sequence"}
        ]
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }


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
            bounded._ROOT / "config/app.yaml",
            review_store,
            ai_budget,
            database=database,
            inner_transport=ai_inner_transport,
            prompt_version=PROMPT_VERSION,
            max_output_tokens=AI_OUTPUT_TOKENS,
        )
        startup = await ai.start()
        if startup.get("configured") is not True or startup.get("diagnosticAvailable") is not True:
            raise bounded.BudgetDenied
        provider_id = (await ai.get_configured_ai()).provider_id
        source = bounded.approved_sources(prompt_version=PROMPT_VERSION)[CASE_ID][0]
        operation_deadline = min(hard_deadline, session_started + TERMINAL_WAIT_SECONDS)
        outcome, review = await _submit_and_wait(
            service=ai,
            provider_id=provider_id,
            source_text=source,
            diagnostic_path=diagnostics,
            deadline=operation_deadline,
        )
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
            audit["status"] = "LITERAL_EXTRACTION_SUCCEEDED_REVIEW_REQUIRED"
            return_code = 0
        elif outcome.get("reason") == "TIMEOUT_DIAGNOSTIC_RECORDED":
            audit["status"] = "AI_TIMEOUT_DIAGNOSED"
        else:
            audit["status"] = "AI_DIAGNOSTIC_FAILED"
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
    args = parser.parse_args(argv)
    if args.prepare_egress_review:
        _write_egress_review_package()
    preflight = _preflight()
    if not args.execute:
        print(json.dumps(preflight, ensure_ascii=True, sort_keys=True))
        return 0
    if args.authorize != AUTHORIZATION or not preflight.get("ready"):
        print(json.dumps({"status": "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"}))
        return 2
    if args.run_id != RUN_ID or not _eligible(datetime.now(bounded._SHANGHAI)):
        print(json.dumps({"status": "NOT_RUN_INVALID_ID_OR_WINDOW"}))
        return 2
    try:
        return asyncio.run(_run_candidate())
    except FileExistsError:
        print(json.dumps({"status": "NOT_RUN_SESSION_ALREADY_CLAIMED"}))
        return 2
    except bounded.BudgetDenied:
        print(json.dumps({"status": "NOT_RUN_PRECONDITION_DENIED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
