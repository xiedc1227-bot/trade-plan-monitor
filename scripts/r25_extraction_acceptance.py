"""R25 extraction-only live candidate. Default invocation makes no network calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from scripts import r14_bounded_acceptance as bounded

from trade_plan_monitor.ai.models import PlanMapping, ServerReviewSnapshot
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5
from trade_plan_monitor.ai.review import (
    build_server_review_snapshot,
    load_explicit_plan_draft_json,
    server_source_clauses,
)
from trade_plan_monitor.web.routers.plans import (
    PlanExtractionCommand,
    PlanExtractionOperationStatus,
    PlanExtractionService,
    PlanExtractionView,
)
from trade_plan_monitor.web.schemas import MutationContext

PROPOSAL_ID = "R25-20260916-AM-EXTRACT-3"
AUTHORIZATION = "R25_20260916_AM_3_AI_1_TRADE_CAL_EXTRACT_ONLY_15MIN_V5_8192"
RUN_ID = "r25-20260916-a"
BIND_PORT = 18770
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V5
AI_OUTPUT_TOKENS = 8192
SOURCE_ORDER = ("LITERAL", "SEM-AMB-01", "SEM-UNS-01")
EXPECTED_SOURCE_HASHES = {
    "LITERAL": "0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191",
    "SEM-AMB-01": "26760155a5c87044b514ab2cff3a162dcef45d739dc863961ee629573e9e991e",
    "SEM-UNS-01": "23401380e6f188abe6da02c2e77db8e4f67bb8e7133efa191329cf505baa11b0",
}
EXPECTED_PROMPT_HASHES = {
    "LITERAL": "660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89",
    "SEM-AMB-01": "f4e5a48d49dbbf582dae883af8dfe724b133df465dd92ff7363dadb6c4e5e2a7",
    "SEM-UNS-01": "fea166298e40b143a5ae261bc7efdf17b3ce8f95869df6ee9c2bdf7cef451455",
}
AI_CAPS = {case_id: 1 for case_id in SOURCE_ORDER}
AI_TOTAL = 3
MARKET_CAPS = {
    "trade_cal": 1,
    "stk_limit": 0,
    "daily": 0,
    "rt_min_daily": 0,
    "rt_min": 0,
    "idx_mins": 0,
    "rt_idx_min_daily": 0,
    "index_daily": 0,
}
MARKET_TOTAL = 1
WALL_SECONDS = 900
CLEANUP_SECONDS = 20
SESSION_ROOT = bounded._ROOT / "data/r25-extraction-acceptance"
REVIEW_ROOT = bounded._ROOT / "data/r25-extraction-review"
EXTERNAL_DESTINATION = "https://api.deepseek.com/chat/completions"
_TERMINAL_EXTRACTION_STATUSES = frozenset(
    status
    for status in PlanExtractionOperationStatus
    if status not in {
        PlanExtractionOperationStatus.QUEUED,
        PlanExtractionOperationStatus.RUNNING,
    }
)


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 16) and time(9, 30) <= now.time() <= time(9, 45)


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
    sources = bounded.approved_sources(prompt_version=PROMPT_VERSION)
    origins = {
        "LITERAL": "tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText",
        "SEM-AMB-01": (
            "tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json"
            "#cases[id=SEM-AMB-01].sourceText"
        ),
        "SEM-UNS-01": (
            "tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json"
            "#cases[id=SEM-UNS-01].sourceText"
        ),
    }
    requests: dict[str, object] = {}
    for case_id in SOURCE_ORDER:
        source, prompt = sources[case_id]
        requests[case_id] = {
            "purpose": (
                "15-clause literal mapping acceptance"
                if case_id == "LITERAL"
                else "ambiguity blocker acceptance"
                if case_id == "SEM-AMB-01"
                else "unsupported-semantics blocker acceptance"
            ),
            "origin": origins[case_id],
            "sourceText": source,
            "sourceSha256": sha256(source.encode("utf-8")).hexdigest(),
            "promptSha256": sha256(prompt.encode("utf-8")).hexdigest(),
            "body": _request_body(prompt),
        }
    return {
        "proposalId": PROPOSAL_ID,
        "destination": EXTERNAL_DESTINATION,
        "recipient": "DeepSeek API service operated by DeepSeek",
        "method": "POST",
        "sourceClassification": "SYNTHETIC_VERSIONED_TEST_FIXTURES",
        "containsSyntheticHoldingLanguage": True,
        "containsRealAccountOrCredential": False,
        "authorizationHeader": "<credential omitted; not part of approval material>",
        "requests": requests,
    }


def _render_review(material: dict[str, object], *, chinese: bool) -> str:
    title = "R25 精确外发审阅材料" if chinese else "R25 exact egress review material"
    intro = (
        "本文件完整展示拟发送给 DeepSeek 的三份合成测试原文和每次唯一 user 提示词。"
        "原文及提示词保持逐字不翻译。凭据不属于审阅材料且未写入本文件。"
        if chinese
        else "This file shows the complete three synthetic test sources and the sole user "
        "message proposed for each DeepSeek request. Source and prompt text are exact and "
        "untranslated. Credentials are not approval material and are not written here."
    )
    labels = (
        {
            "recipient": "接收方",
            "destination": "目的地址",
            "method": "方法",
            "classification": "分类",
            "credential": "Authorization Header",
            "purpose": "用途",
            "origin": "来源",
            "source_hash": "原文 SHA-256",
            "prompt_hash": "提示词 SHA-256",
            "source": "将外发的精确原文",
            "prompt": "将外发的精确 user 提示词",
            "body": "请求体固定字段",
        }
        if chinese
        else {
            "recipient": "Recipient",
            "destination": "Destination",
            "method": "Method",
            "classification": "Classification",
            "credential": "Authorization header",
            "purpose": "Purpose",
            "origin": "Origin",
            "source_hash": "Source SHA-256",
            "prompt_hash": "Prompt SHA-256",
            "source": "Exact source text to be sent",
            "prompt": "Exact sole user message to be sent",
            "body": "Fixed request-body fields",
        }
    )
    lines = [
        f"# {title}",
        "",
        intro,
        "",
        f"- {labels['recipient']}: `{material['recipient']}`",
        f"- {labels['destination']}: `{material['destination']}`",
        f"- {labels['method']}: `{material['method']}`",
        f"- {labels['classification']}: `{material['sourceClassification']}`",
        f"- {labels['credential']}: `{material['authorizationHeader']}`",
        "",
    ]
    requests = material["requests"]
    assert isinstance(requests, dict)
    for case_id in SOURCE_ORDER:
        request = requests[case_id]
        assert isinstance(request, dict)
        body = request["body"]
        assert isinstance(body, dict)
        fixed_body = {key: value for key, value in body.items() if key != "messages"}
        prompt = body["messages"][0]["content"]
        lines.extend(
            [
                f"## {case_id}",
                "",
                f"- {labels['purpose']}: {request['purpose']}",
                f"- {labels['origin']}: `{request['origin']}`",
                f"- {labels['source_hash']}: `{request['sourceSha256']}`",
                f"- {labels['prompt_hash']}: `{request['promptSha256']}`",
                "",
                f"### {labels['source']}",
                "",
                "`````text",
                str(request["sourceText"]),
                "`````",
                "",
                f"### {labels['prompt']}",
                "",
                "`````text",
                str(prompt),
                "`````",
                "",
                f"### {labels['body']}",
                "",
                "```json",
                json.dumps(fixed_body, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _write_egress_review_package(root: Path = REVIEW_ROOT) -> tuple[Path, Path]:
    material = _egress_review_material()
    root.mkdir(parents=True, exist_ok=True)
    english = root / "egress-review.md"
    chinese = root / "egress-review.zh-CN.md"
    english.write_text(_render_review(material, chinese=False), encoding="utf-8", newline="\n")
    chinese.write_text(_render_review(material, chinese=True), encoding="utf-8", newline="\n")
    return english, chinese


async def _run_ordered_sequence(
    run_case: Callable[[str], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for case_id in SOURCE_ORDER:
        outcome = await run_case(case_id)
        outcomes.append(outcome)
        if outcome.get("accepted") is not True:
            break
    return outcomes


def _get_path(value: object, path: str) -> object:
    current = value
    for part in path.replace("]", "").replace("[", ".").split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _literal_fixture() -> dict[str, object]:
    path = bounded._ROOT / "tests/fixtures/ai/explicit-plan-literal-source-v3.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_case(case_id: str) -> dict[str, object]:
    path = bounded._ROOT / "tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return next(case for case in cases if case["id"] == case_id)


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


def _semantic_oracle_matches(
    *,
    case: dict[str, object],
    draft_data: dict[str, object],
    snapshot: ServerReviewSnapshot,
) -> bool:
    oracle = case["oracle"]
    source_bindings = [
        item for item in snapshot.mapping.field_bindings if item.origin.value == "SOURCE"
    ]
    clauses = {item.clause_id: item for item in snapshot.mapping.source_clauses}
    for expected in oracle["fields"]:
        if _get_path(draft_data, expected["path"]) != expected["value"]:
            return False
        bindings = [item for item in source_bindings if item.path == expected["path"]]
        if len(bindings) != 1:
            return False
        binding = bindings[0]
        if binding.value != expected["value"] or binding.unit.value != expected["unit"]:
            return False
        if {clauses[clause_id].excerpt for clause_id in binding.clause_ids} != {
            expected["sourceExcerpt"]
        }:
            return False
    for expected in oracle["structures"]:
        structure = _get_path(draft_data, expected["path"])
        if not isinstance(structure, dict):
            return False
        if structure.get("type") != expected["operator"]:
            return False
        if [item.get("type") for item in structure.get("conditions", [])] != expected[
            "childTypes"
        ]:
            return False
        if not any(
            item.binding_kind.value == "STRUCTURE"
            and item.path == expected["path"]
            and item.value == expected["operator"]
            for item in source_bindings
        ):
            return False
    required_issues = snapshot.required_issues
    unresolved = sorted(
        issue.path for issue in required_issues if issue.code == "UNRESOLVED_EXECUTION_POLICY"
    )
    semantic_codes = sorted(
        {
            issue.code
            for issue in required_issues
            if issue.code in {"UNRESOLVED_SEMANTICS", "UNSUPPORTED_SEMANTICS"}
        }
    )
    if unresolved != sorted(oracle["unresolvedPaths"]):
        return False
    if semantic_codes != sorted(oracle["semanticCodes"]):
        return False
    return all(
        any(
            issue.code == "UNSUPPORTED_SEMANTICS" and fragment in issue.reason
            for issue in required_issues
        )
        for fragment in oracle["unsupportedReasonFragments"]
    )


def _literal_oracle_matches(
    *, draft_data: dict[str, object], mapping: PlanMapping, source_text: str
) -> bool:
    fixture = _literal_fixture()
    clauses = server_source_clauses(source_text)
    mapped_clause_identity = tuple(
        (item.clause_id, item.start, item.end, item.excerpt) for item in mapping.source_clauses
    )
    server_clause_identity = tuple(
        (item.clause_id, item.start, item.end, item.excerpt) for item in clauses
    )
    if len(clauses) != 15 or mapped_clause_identity != server_clause_identity:
        return False
    supplement_paths = tuple(fixture["humanTestSupplements"])
    for path, expected in fixture["independentExpectedValues"].items():
        expected_before_review = (
            None
            if any(item == path or item.startswith(f"{path}.") for item in supplement_paths)
            else expected
        )
        if _get_path(draft_data, path) != expected_before_review:
            return False
    source_bindings = [
        item for item in mapping.field_bindings if item.origin.value == "SOURCE"
    ]
    for path, clause_index in fixture["expectedSourceClauses"].items():
        clause_id = clauses[clause_index].clause_id
        if not any(item.path == path and clause_id in item.clause_ids for item in source_bindings):
            return False
    for path, unit in fixture["expectedSourceUnits"].items():
        if not any(item.path == path and item.unit.value == unit for item in source_bindings):
            return False
    return True


def _assess_extraction(
    *, case_id: str, source_text: str, view: PlanExtractionView, diagnostic_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    diagnostic = _read_diagnostic(diagnostic_path, view.id)
    base: dict[str, object] = {
        "caseId": case_id,
        "operationId": str(view.id),
        "status": view.status.value,
        "sourceSha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "diagnosticStatus": view.diagnostic_status,
        "returnedModelMatchesConfigured": (
            None if diagnostic is None else diagnostic.get("modelMatchesConfigured")
        ),
        "accepted": False,
    }
    validated = view.model_dump(mode="json", by_alias=True)
    if (
        view.status is not PlanExtractionOperationStatus.SUCCEEDED
        or view.source_text_sha256 != base["sourceSha256"]
        or view.model != bounded.APPROVED_MODEL
        or view.prompt_version != PROMPT_VERSION
        or view.diagnostic_status != "RECORDED"
        or diagnostic is None
        or diagnostic.get("modelMatchesConfigured") is not True
        or view.draft_plan_json is None
        or view.mapping is None
    ):
        base["reason"] = "EXTRACTION_OR_DIAGNOSTIC_REJECTED"
        return base, validated
    try:
        draft = load_explicit_plan_draft_json(view.draft_plan_json)
        mapping = view.mapping.to_domain()
        snapshot = build_server_review_snapshot(
            source_text=source_text,
            draft=draft,
            mapping=mapping,
        )
        draft_data = draft.model_dump(mode="json")
        accepted = (
            _literal_oracle_matches(
                draft_data=draft_data,
                mapping=mapping,
                source_text=source_text,
            )
            if case_id == "LITERAL"
            else (
                not snapshot.can_activate
                and _semantic_oracle_matches(
                    case=_semantic_case(case_id),
                    draft_data=draft_data,
                    snapshot=snapshot,
                )
            )
        )
    except (IndexError, KeyError, TypeError, UnicodeError, ValueError):
        accepted = False
        snapshot = None
    base["accepted"] = accepted
    base["reason"] = "ORACLE_ACCEPTED" if accepted else "ORACLE_MISMATCH"
    if snapshot is not None:
        base["reviewIssueCodes"] = sorted({item.code for item in snapshot.required_issues})
        base["canActivateBeforeHumanReview"] = snapshot.can_activate
    if view.usage is not None:
        base["usage"] = view.usage.model_dump(mode="json", by_alias=True)
    return base, validated


async def _submit_and_wait(
    *,
    service: PlanExtractionService,
    provider_id: UUID,
    case_id: str,
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
                idempotency_key=f"{RUN_ID}-{case_id.lower()}",
                request_id=uuid4().hex,
            ),
        )
        operation_id = receipt.operation_id
        while monotonic() < deadline:
            view = await service.get_plan_extraction(operation_id=str(operation_id))
            if view is None:
                break
            if view.status in _TERMINAL_EXTRACTION_STATUSES:
                return _assess_extraction(
                    case_id=case_id,
                    source_text=source_text,
                    view=view,
                    diagnostic_path=diagnostic_path,
                )
            await asyncio.sleep(0.1)
    except Exception:
        pass
    return (
        {
            "caseId": case_id,
            "operationId": None if operation_id is None else str(operation_id),
            "sourceSha256": sha256(source_text.encode("utf-8")).hexdigest(),
            "status": "RECEIPT_OR_QUERY_UNCERTAIN",
            "accepted": False,
            "reason": "STOP_WITHOUT_RESUBMISSION",
        },
        None,
    )


def _database_counts(database: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        queries = {
            "plan_extraction_review": "SELECT COUNT(*) FROM plan_extraction_review",
            "plan_version": "SELECT COUNT(*) FROM plan_version",
            "plan_activation_state": "SELECT COUNT(*) FROM plan_activation_state",
            "active_plan": "SELECT COUNT(*) FROM active_plan",
        }
        return {
            table: int(connection.execute(query).fetchone()[0])
            for table, query in queries.items()
        }


async def _cleanup_with_deadline(*lifecycles: object | None) -> bool:
    deadline = monotonic() + CLEANUP_SECONDS
    success = True
    for lifecycle in lifecycles:
        if lifecycle is None:
            continue
        stop = getattr(lifecycle, "stop", None)
        if not callable(stop):
            success = False
            continue
        try:
            await asyncio.wait_for(stop(), timeout=max(0.001, deadline - monotonic()))
        except BaseException:
            success = False
    return success


async def _run_candidate() -> int:
    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.runtime import production
    from trade_plan_monitor.web.ai_diagnostics import diagnostic_path_for_database
    from trade_plan_monitor.web.monitor_composition import create_monitor_composition
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", BIND_PORT))
    except OSError:
        listener.close()
        raise bounded.BudgetDenied from None
    try:
        folder = bounded._claim_session(SESSION_ROOT, RUN_ID)
    except BaseException:
        listener.close()
        raise
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
        "validatedReviewArtifact": "validated-review-results.json",
        "channel": "LOCAL_REVIEW_ONLY",
        "status": "STARTED",
        "humanReviewStatus": "REQUIRED_NOT_PERFORMED",
        "activationAllowed": False,
    }
    failure_lock = threading.Lock()
    first_market_failure: dict[str, object] | None = None
    reference_failure_code: str | None = None

    def stop_candidate() -> None:
        return None

    def record_market_failure(operation: str, failure: dict[str, object]) -> None:
        nonlocal first_market_failure
        with failure_lock:
            if first_market_failure is None:
                first_market_failure = {"operation": operation, **failure}
        journal.record_market_failure(operation, failure)

    def record_reference_failure(code: str) -> None:
        nonlocal reference_failure_code
        with failure_lock:
            if reference_failure_code is None:
                reference_failure_code = code
        journal.record_reference_failure(code)

    ai_budget, market_budget = bounded._session_budgets(
        stop_candidate,
        ai_total=AI_TOTAL,
        ai_caps=AI_CAPS,
        market_caps=MARKET_CAPS,
        market_total=MARKET_TOTAL,
        wall_seconds=WALL_SECONDS,
        on_ai_snapshot=lambda snapshot: journal.record_budget("ai", snapshot),
        on_market_snapshot=lambda snapshot: journal.record_budget("market", snapshot),
    )
    journal.record_budget("ai", ai_budget.snapshot())
    journal.record_budget("market", market_budget.snapshot())
    original_factory = production.create_tushare_client
    runtime = None
    plans = None
    ai = None
    return_code = 1
    validated_results: dict[str, object] = {}
    try:
        configuration = load_application_config(bounded._ROOT / "config/app.yaml")
        if configuration.tushare.connect_ip is None:
            raise bounded.BudgetDenied
        guard = bounded.MarketBudget(
            market_budget,
            stop_on_failure_keys=frozenset({"trade_cal"}),
            on_failure=record_market_failure,
        )
        production.create_tushare_client = bounded._guarded_market_factory(original_factory, guard)
        runtime = create_monitor_composition(
            config_path=bounded._ROOT / "config/app.yaml",
            database_path=database,
            on_reference_failure=record_reference_failure,
        )
        await runtime.start()
        market_snapshot = market_budget.snapshot()
        with failure_lock:
            reference_failed = (
                reference_failure_code is not None or first_market_failure is not None
            )
        if reference_failed or market_snapshot["attempts"] != {"trade_cal": 1}:
            audit["status"] = "REFERENCE_FAILED"
        else:
            plans = PersistentPlanWebLifecycle(
                database_path=database,
                clock=lambda: datetime.now(bounded._SHANGHAI),
            )
            await plans.start()
            ai = bounded._bounded_ai_factory(
                bounded._ROOT / "config/app.yaml",
                plans,
                ai_budget,
                database=database,
                prompt_version=PROMPT_VERSION,
                max_output_tokens=AI_OUTPUT_TOKENS,
            )
            ai_startup = await ai.start()
            if ai_startup.get("configured") is not True or ai_startup.get(
                "diagnosticAvailable"
            ) is not True:
                raise bounded.BudgetDenied
            provider_id = (await ai.get_configured_ai()).provider_id
            sources = bounded.approved_sources(prompt_version=PROMPT_VERSION)
            deadline = monotonic() + WALL_SECONDS

            async def run_case(case_id: str) -> dict[str, object]:
                outcome, validated = await _submit_and_wait(
                    service=ai,
                    provider_id=provider_id,
                    case_id=case_id,
                    source_text=sources[case_id][0],
                    diagnostic_path=diagnostics,
                    deadline=deadline,
                )
                if validated is not None:
                    validated_results[case_id] = validated
                return outcome

            outcomes = await _run_ordered_sequence(run_case)
            audit["cases"] = outcomes
            passed = len(outcomes) == len(SOURCE_ORDER) and all(
                outcome.get("accepted") is True for outcome in outcomes
            )
            audit["status"] = (
                "EXTRACTION_ACCEPTANCE_PASS_REVIEW_REQUIRED"
                if passed
                else "EXTRACTION_ACCEPTANCE_FAILED"
            )
            return_code = 0 if passed else 1
            bounded._write_json_atomic(
                folder / "validated-review-results.json",
                {
                    "proposalId": PROPOSAL_ID,
                    "runId": RUN_ID,
                    "humanReviewStatus": "REQUIRED_NOT_PERFORMED",
                    "activationAllowed": False,
                    "results": validated_results,
                },
            )
    except BaseException as error:
        audit["status"] = "FAILED"
        audit["errorType"] = type(error).__name__
    finally:
        ai_budget.stop()
        cleanup_ok = await _cleanup_with_deadline(ai, plans, runtime)
        production.create_tushare_client = original_factory
        listener.close()
        audit["cleanupStatus"] = "COMPLETE" if cleanup_ok else "FAILED"
        audit["finishedAt"] = datetime.now(bounded._SHANGHAI).isoformat()
        audit["ai"] = ai_budget.snapshot()
        audit["market"] = market_budget.snapshot()
        if first_market_failure is not None:
            audit["firstMarketFailure"] = first_market_failure
        if reference_failure_code is not None:
            audit["referenceFailureCode"] = reference_failure_code
        if database.exists():
            try:
                counts = _database_counts(database)
            except (OSError, sqlite3.Error):
                counts = {}
                audit["status"] = "LOCAL_STATE_VERIFICATION_FAILED"
                return_code = 1
            audit["databaseCounts"] = counts
            state_tables = ("plan_version", "plan_activation_state", "active_plan")
            if any(counts.get(table, 0) for table in state_tables):
                audit["status"] = "ISOLATION_VIOLATION"
                return_code = 1
        if not cleanup_ok:
            audit["status"] = "SHUTDOWN_FAILED"
            return_code = 1
        bounded._write_json_atomic(folder / "audit.json", audit)
        journal.complete(status=str(audit["status"]), ai=audit["ai"], market=audit["market"])
        print(json.dumps(audit, ensure_ascii=True, sort_keys=True), flush=True)
    return return_code


def _source_manifest() -> dict[str, dict[str, object]]:
    material = _egress_review_material()
    requests = material["requests"]
    assert isinstance(requests, dict)
    return {
        case_id: {
            "origin": request["origin"],
            "sourceSha256": request["sourceSha256"],
            "promptSha256": request["promptSha256"],
        }
        for case_id, request in requests.items()
    }


def _preflight() -> dict[str, object]:
    result = bounded._preflight(
        start_window_eligible=_eligible,
        market_caps=MARKET_CAPS,
        market_total=MARKET_TOTAL,
        wall_seconds=WALL_SECONDS,
        bind_port=BIND_PORT,
        ai_output_tokens=AI_OUTPUT_TOKENS,
        prompt_version=PROMPT_VERSION,
        ai_total=AI_TOTAL,
    )
    source_manifest = _source_manifest()
    manifest_matches = all(
        source_manifest[case_id]["sourceSha256"] == EXPECTED_SOURCE_HASHES[case_id]
        and source_manifest[case_id]["promptSha256"] == EXPECTED_PROMPT_HASHES[case_id]
        for case_id in SOURCE_ORDER
    )
    return {
        **result,
        "ready": bool(result.get("ready") and manifest_matches),
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
        "extractionOnly": True,
        "activationAllowed": False,
        "humanReviewRequired": True,
        "externalDestination": EXTERNAL_DESTINATION,
        "sourceOrder": list(SOURCE_ORDER),
        "sourceManifest": source_manifest,
        "manifestMatchesCandidate": manifest_matches,
        "limits": {**result.get("limits", {}), "cleanupSeconds": CLEANUP_SECONDS},
        "officialRouteSnapshot": "DeepSeek-V4-Pro-0813",
        "officialRouteSnapshotAsOf": "2026-09-15",
        "officialPriceRecheckRequiredBeforeExecute": True,
        "pricingStatus": "CURRENT_OFFICIAL_RATES_VARIABLE_NO_BALANCE_PROBE",
    }


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
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
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
