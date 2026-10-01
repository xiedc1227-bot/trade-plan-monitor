from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from scripts import bounded_live_acceptance as bounded
from scripts import plan_extraction_acceptance as r25
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_source_treatment_review_api import (
    SOURCE as LITERAL_SOURCE,
)
from tests.integration.test_source_treatment_review_api import _literal_mapping
from tests.unit.test_explicit_plan_semantic_acceptance import _extract

from trade_plan_monitor.ai.models import ExplicitPlanDraft
from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5
from trade_plan_monitor.ai.review import build_server_review_snapshot
from trade_plan_monitor.web.schemas import OperationKind, OperationReceipt

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_r25_contract_is_fresh_extraction_only_and_bounded() -> None:
    assert r25._eligible(datetime(2026, 9, 16, 9, 30, tzinfo=_SHANGHAI))
    assert r25._eligible(datetime(2026, 9, 16, 9, 45, tzinfo=_SHANGHAI))
    assert not r25._eligible(datetime(2026, 9, 16, 9, 45, 1, tzinfo=_SHANGHAI))
    assert r25.PROPOSAL_ID == "R25-20260916-AM-EXTRACT-3"
    assert r25.RUN_ID == "r25-20260916-a"
    assert r25.BIND_PORT == 18770
    assert r25.SESSION_ROOT.name == "r25-extraction-acceptance"
    assert r25.PROMPT_VERSION == PLAN_EXTRACTION_PROMPT_V5
    assert r25.AI_OUTPUT_TOKENS == 8192
    assert r25.SOURCE_ORDER == ("LITERAL", "SEM-AMB-01", "SEM-UNS-01")
    assert r25.AI_CAPS == {case_id: 1 for case_id in r25.SOURCE_ORDER}
    assert r25.AI_TOTAL == 3
    assert r25.MARKET_CAPS == {
        "trade_cal": 1,
        "stk_limit": 0,
        "daily": 0,
        "rt_min_daily": 0,
        "rt_min": 0,
        "idx_mins": 0,
        "rt_idx_min_daily": 0,
        "index_daily": 0,
    }
    assert r25.MARKET_TOTAL == 1
    assert r25.WALL_SECONDS == 900
    assert r25.CLEANUP_SECONDS == 20


def test_r25_preflight_is_offline_and_exposes_exact_request_manifest(monkeypatch) -> None:
    monkeypatch.setattr(r25, "_eligible", lambda _now: True)

    result = r25._preflight()

    assert result["mode"] == "DRY_RUN_NO_NETWORK"
    assert result["proposalId"] == r25.PROPOSAL_ID
    assert result["runId"] == r25.RUN_ID
    assert result["extractionOnly"] is True
    assert result["activationAllowed"] is False
    assert result["humanReviewRequired"] is True
    assert result["externalDestination"] == "https://api.deepseek.com/chat/completions"
    assert result["limits"]["aiPhysicalAttempts"] == 3
    assert result["limits"]["aiPerInputAttempts"] == 1
    assert result["limits"]["marketPhysicalAttempts"] == 1
    assert result["limits"]["marketPerEndpointAttempts"] == r25.MARKET_CAPS
    assert result["limits"]["wallSeconds"] == 900
    assert result["limits"]["cleanupSeconds"] == 20
    assert result["limits"]["promptVersion"] == PLAN_EXTRACTION_PROMPT_V5
    assert result["limits"]["aiOutputTokensPerRequest"] == 8192
    assert tuple(result["sourceManifest"]) == r25.SOURCE_ORDER
    assert result["manifestMatchesCandidate"] is True
    assert all(len(item["sourceSha256"]) == 64 for item in result["sourceManifest"].values())
    assert all(len(item["promptSha256"]) == 64 for item in result["sourceManifest"].values())


def test_r25_review_package_contains_exact_sources_prompts_and_no_credential(
    tmp_path: Path,
) -> None:
    material = r25._egress_review_material()
    approved = bounded.approved_sources(prompt_version=PLAN_EXTRACTION_PROMPT_V5)

    assert material["destination"] == "https://api.deepseek.com/chat/completions"
    assert material["sourceClassification"] == "SYNTHETIC_VERSIONED_TEST_FIXTURES"
    assert material["containsSyntheticHoldingLanguage"] is True
    assert material["containsRealAccountOrCredential"] is False
    assert tuple(material["requests"]) == r25.SOURCE_ORDER
    for case_id, request in material["requests"].items():
        source, prompt = approved[case_id]
        assert request["sourceText"] == source
        assert request["body"] == {
            "model": bounded.APPROVED_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        assert "Authorization" not in request

    english, chinese = r25._write_egress_review_package(tmp_path)
    assert english.name == "egress-review.md"
    assert chinese.name == "egress-review.zh-CN.md"
    for document in (english.read_text("utf-8"), chinese.read_text("utf-8")):
        assert "https://api.deepseek.com/chat/completions" in document
        assert all(source in document for source, _ in approved.values())
        assert all(prompt in document for _, prompt in approved.values())
        assert "<credential omitted; not part of approval material>" in document


def test_ordered_sequence_stops_after_literal_or_semantic_failure() -> None:
    async def scenario(failing_case: str | None) -> tuple[list[str], list[dict[str, object]]]:
        calls: list[str] = []

        async def run_case(case_id: str) -> dict[str, object]:
            calls.append(case_id)
            return {"caseId": case_id, "accepted": case_id != failing_case}

        outcomes = await r25._run_ordered_sequence(run_case)
        return calls, outcomes

    literal_calls, literal_outcomes = asyncio.run(scenario("LITERAL"))
    ambiguous_calls, ambiguous_outcomes = asyncio.run(scenario("SEM-AMB-01"))
    all_calls, all_outcomes = asyncio.run(scenario(None))

    assert literal_calls == ["LITERAL"]
    assert literal_outcomes[-1]["accepted"] is False
    assert ambiguous_calls == ["LITERAL", "SEM-AMB-01"]
    assert ambiguous_outcomes[-1]["accepted"] is False
    assert all_calls == list(r25.SOURCE_ORDER)
    assert all(item["accepted"] is True for item in all_outcomes)


def test_r25_literal_and_semantic_oracles_accept_only_the_frozen_expectations() -> None:
    draft_data = _draft_payload()
    draft_data["activation"] = None
    draft_data["conflict_policy"] = None
    for rule in draft_data["rules"]:
        rule["repeat_policy"] = None
    draft_data["rules"][0]["condition"]["conditions"][1]["history_scope"] = None
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(draft_data))
    mapping = _literal_mapping(draft, supplemented=False)
    literal_matches = r25._literal_oracle_matches(
        draft_data=draft.model_dump(mode="json"),
        mapping=mapping,
        source_text=LITERAL_SOURCE,
    )
    assert literal_matches is True

    for case_id in ("SEM-AMB-01", "SEM-UNS-01"):
        case = r25._semantic_case(case_id)
        result = _extract(case)
        snapshot = build_server_review_snapshot(
            source_text=case["sourceText"],
            draft=result.draft,
            mapping=result.mapping,
        )
        semantic_matches = r25._semantic_oracle_matches(
            case=case,
            draft_data=result.draft.model_dump(mode="json"),
            snapshot=snapshot,
        )
        assert semantic_matches is True
        mutated = result.draft.model_dump(mode="json")
        mutated["rules"][0]["action"]["quantity"] = 200
        mutated_matches = r25._semantic_oracle_matches(
            case=case,
            draft_data=mutated,
            snapshot=snapshot,
        )
        assert mutated_matches is False


def test_uncertain_query_preserves_operation_id_without_resubmitting(tmp_path: Path) -> None:
    operation_id = UUID("00000000-0000-4000-8000-000000000025")

    class UncertainService:
        def __init__(self) -> None:
            self.submissions = 0

        async def submit_plan_extraction(self, **_kwargs: object) -> OperationReceipt:
            self.submissions += 1
            return OperationReceipt(
                operation_id=operation_id,
                kind=OperationKind.PLAN_EXTRACTION,
                status="QUEUED",
                submitted_at=datetime(2026, 9, 16, 9, 30, tzinfo=_SHANGHAI),
            )

        async def get_plan_extraction(self, **_kwargs: object) -> None:
            raise RuntimeError("simulated local query uncertainty")

    service = UncertainService()
    outcome, validated = asyncio.run(
        r25._submit_and_wait(
            service=service,
            provider_id=UUID("00000000-0000-4000-8000-000000000026"),
            case_id="LITERAL",
            source_text="synthetic",
            diagnostic_path=tmp_path / "diagnostics.jsonl",
            deadline=float("inf"),
        )
    )

    assert service.submissions == 1
    assert outcome["operationId"] == str(operation_id)
    assert outcome["status"] == "RECEIPT_OR_QUERY_UNCERTAIN"
    assert outcome["reason"] == "STOP_WITHOUT_RESUBMISSION"
    assert validated is None


def test_execute_requires_the_exact_candidate_gate_without_calling_runner(
    monkeypatch, capsys
) -> None:
    calls = 0

    async def run_candidate() -> int:
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(r25, "_preflight", lambda: {"ready": True})
    monkeypatch.setattr(r25, "_eligible", lambda _now: True)
    monkeypatch.setattr(r25, "_run_candidate", run_candidate)

    assert r25.main(["--execute", "--authorize", "wrong", "--run-id", r25.RUN_ID]) == 2
    assert calls == 0
    assert json.loads(capsys.readouterr().out)["status"] == (
        "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"
    )
    assert (
        r25.main(
            [
                "--execute",
                "--authorize",
                r25.AUTHORIZATION,
                "--run-id",
                r25.RUN_ID,
            ]
        )
        == 0
    )
    assert calls == 1
