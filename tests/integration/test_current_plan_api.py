"""Formal HTTP services preserve current source, review and activation authority."""

import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.integration.test_web_api import _FakeLifecycle
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.daily_review import daily_contract_bindings, daily_source_clauses
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.plan_codec import dump_plan_json, dump_plan_yaml
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

SOURCE = "Synthetic human-reviewed supplements for this fixture."


def simple_plan():
    raw = unified_payload()
    raw.update(levels=None, monitoring=None, risk_branches=[])
    raw["activation"] = {"mode": "MANUAL"}
    raw["position"] = {"max_qty": 1000}
    raw["ordinary_rules"][0].update(
        zone=None,
        condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
        validity={"mode": "PLAN_ACTIVE"},
    )
    return UnifiedTradePlan.model_validate(raw)


def post(client, path, payload, expected=200, *, key=None):
    response = client.post(
        "/api/v1/" + path,
        json=payload,
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == expected, response.text
    return response.json()


def review_payload(saved, **updates):
    return {
        "planVersionId": saved["id"],
        "contentHash": saved["contentHash"],
        "sourceHash": saved["sourceHash"],
        "reviewEvidenceHash": saved["reviewEvidenceHash"],
        "expectedRevision": 0,
        **updates,
    }


def reviewed_save(
    client,
    draft,
    *,
    source=SOURCE,
    base=None,
    activation_revision=0,
    supplement_revision=0,
):
    mapping = reviewed_mapping(draft, source)
    document = daily_draft_json(draft)
    post(
        client,
        "plan-review-supplements",
        {
            "candidateJson": document,
            "contentHash": mapping.candidate_content_hash,
            "supplements": [s.model_dump(mode="json") for s in mapping.supplements],
            "expectedRevision": supplement_revision,
        },
    )
    return post(
        client,
        "plan-drafts",
        {
            "basePlanVersionId": base,
            "planJson": document,
            "sourceText": source,
            "dailyMapping": mapping.model_dump(mode="json"),
            "expectedRevision": activation_revision,
        },
    )


def make_app(tmp_path, *, ai=False):
    lifecycle = PersistentPlanWebLifecycle(
        database_path=tmp_path / "current.sqlite",
        clock=lambda: datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    options = {}
    if ai:
        config_path = tmp_path / "app.yaml"
        config_path.write_text(
            "ai:\n  profile: DEEPSEEK\n  base_url: https://api.deepseek.com\n"
            "  model: deepseek-v4-flash\n  api_key: offline-fixture-key\n  max_retries: 0\n",
            encoding="utf-8",
        )

        def provider(request):
            messages = json.loads(request.content)["messages"]
            assert "plan-extract-v11" in messages[0]["content"]
            draft = UnifiedPlanDraft.from_executable(simple_plan())
            output = {
                "draft": draft.model_dump(mode="json"),
                "clauses": [c.model_dump(mode="json") for c in daily_source_clauses(SOURCE)],
                "bindings": [b.model_dump(mode="json") for b in daily_contract_bindings(draft)],
            }
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": json.dumps(output)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            )

        ai_lifecycle = ConfiguredAIWebLifecycle(
            config_path=config_path,
            review_store=lifecycle,
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        )
        options["ai_lifecycle_factory"] = lambda: ai_lifecycle
    return create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_lifecycle_factory=lambda: lifecycle,
        **options,
    )


def test_formal_extraction_edit_review_activate_and_restart_binding(tmp_path):
    app = make_app(tmp_path, ai=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        provider = client.get("/api/v1/ai-runtime").json()["providerId"]
        receipt = post(
            client,
            "plan-extractions",
            {
                "providerId": provider,
                "sourceText": SOURCE,
                "expectedRevision": 0,
            },
            expected=202,
        )
        for _ in range(100):
            result = client.get("/api/v1/plan-extractions/" + receipt["operationId"]).json()
            if result["status"] not in {"QUEUED", "RUNNING"}:
                break
        assert result["status"] == "SUCCEEDED"
        assert result["promptVersion"] == "plan-extract-v11"
        extracted = json.loads(result["draftPlanJson"])
        assert extracted["activation"] == {"mode": "MANUAL"}
        assert extracted["ordinary_rules"][0]["validity"] == {"mode": "PLAN_ACTIVE"}
        assert not any(i["path"] in {"activation.mode", "ordinary_rules[0].validity.mode"}
                       for i in result["validationIssues"])
        assert result["validationIssues"]
        saved_unresolved = post(
            client,
            "plan-drafts",
            {
                "extractionId": receipt["operationId"],
                "planJson": result["draftPlanJson"],
                "sourceText": SOURCE,
                "dailyMapping": result["dailyMapping"],
                "expectedRevision": 0,
            },
        )
        assert not saved_unresolved["canActivate"]
        post(client, "plan-review-confirmations", review_payload(saved_unresolved), expected=422)
        post(
            client,
            "plan-activations",
            {
                "planVersionId": saved_unresolved["id"],
                "expectedRevision": 0,
            },
            expected=409,
        )

        edited = json.loads(result["draftPlanJson"])
        edited["ordinary_rules"][0]["quantity"] = 200
        draft = UnifiedPlanDraft.model_validate(edited)
        saved = reviewed_save(client, draft, base=saved_unresolved["id"])
        assert saved["version"] == 2 and saved["reviewId"] is None
        post(
            client,
            "plan-review-confirmations",
            review_payload(saved, sourceHash="0" * 64),
            expected=422,
        )
        review_key = str(uuid4())
        review = post(client, "plan-review-confirmations", review_payload(saved), key=review_key)
        assert (
            post(client, "plan-review-confirmations", review_payload(saved), key=review_key)
            == review
        )
        active_command = review_payload(saved, reviewId=review["reviewId"], reviewRevision=1)
        active = post(client, "plan-activations", active_command)
        assert active["active"] and active["revision"] == 1
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active

    # A new lifecycle reads the same SQLite store; review identity and activation survive.
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        restored = client.get("/api/v1/plan-versions/" + saved["id"]).json()
        assert restored["reviewId"] == review["reviewId"] and restored["canActivate"]
        assert client.get("/api/v1/plan-activation-states/601021.SH").json()["active"]
        changed_source = reviewed_save(
            client,
            draft,
            source=SOURCE + " Revised technical scope.",
            base=saved["id"],
            activation_revision=1,
            supplement_revision=1,
        )
        assert changed_source["sourceHash"] != saved["sourceHash"]
        assert changed_source["reviewId"] is None and not changed_source["canActivate"]
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active
        stale = {**active_command, "planVersionId": changed_source["id"], "expectedRevision": 1}
        post(client, "plan-activations", stale, expected=409)
        post(
            client,
            "plan-review-confirmations",
            review_payload(saved, expectedRevision=0),
            expected=409,
        )
        replacement_review = post(
            client, "plan-review-confirmations", review_payload(changed_source))
        assert client.get("/api/v1/plan-activation-states/601021.SH").json() == active
        replacement_active = post(client, "plan-activations", review_payload(
            changed_source, reviewId=replacement_review["reviewId"], reviewRevision=1,
            expectedRevision=1))
        assert replacement_active["revision"] == 2
        assert replacement_active["planVersionId"] == changed_source["id"]


@pytest.mark.parametrize("format", ["JSON", "YAML"])
def test_plan_import_endpoint_is_removed_without_changing_saved_plans(tmp_path, format):
    plan = simple_plan()
    document = dump_plan_json(plan) if format == "JSON" else dump_plan_yaml(plan)
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        response = client.post("/api/v1/plan-imports", json={
            "symbol": plan.symbol, "format": format, "document": document, "expectedRevision": 0,
        }, headers={"Idempotency-Key": "removed-import"})
        assert response.status_code == 404, response.text
        assert client.get("/api/v1/plan-versions").json()["total"] == 0


@pytest.mark.parametrize("schema", [1, 2, 3, 4])
def test_historical_canonical_plan_is_read_only_even_if_old_active(schema, tmp_path):
    from hashlib import sha256

    from sqlalchemy import select
    from tests.integration.test_explicit_runtime_production import _plan, _seed_active
    from tests.unit.test_daily_plan import synthetic_plan_payload
    from tests.unit.test_plan_index_conditions import _v1_payload, _v2_payload

    from trade_plan_monitor.state.database import (
        create_session_factory,
        create_sqlite_engine,
        upgrade_database,
    )
    from trade_plan_monitor.state.models import PlanReviewProvenance, PlanVersion
    from trade_plan_monitor.web.app import create_app

    if schema == 3:
        plan = _plan()
    else:
        raw = {1: _v1_payload, 2: _v2_payload, 4: synthetic_plan_payload}[schema]()
        from trade_plan_monitor.domain.plan_codec import load_plan_json

        plan = load_plan_json(json.dumps(raw))
    database = tmp_path / "historical.sqlite3"
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    _seed_active(engine, plan)
    factory = create_session_factory(engine)
    with factory() as session:
        row = session.scalar(select(PlanVersion))
        identity, document, original_hash = row.id, row.payload_json, row.plan_hash
        provenance = session.get(PlanReviewProvenance, identity)
        old_provenance = (provenance.draft_hash, provenance.source_hash, provenance.confirmed_at)
    lifecycle = PersistentPlanWebLifecycle(database_path=database)
    with TestClient(
        create_app(
            runtime_factory=lambda: _FakeLifecycle(events=[]),
            plan_lifecycle_factory=lambda: lifecycle,
        ),
        base_url="http://127.0.0.1:8765",
    ) as client:
        page = client.get("/api/v1/plan-versions").json()
        detail_response = client.get(f"/api/v1/plan-versions/{identity}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["id"] == identity and detail["planJson"] == document
        assert detail["planHash"] == original_hash == sha256(document.encode()).hexdigest()
        assert detail["status"] == "ACTIVE" and detail["canActivate"] is False
        assert detail["obsoleteReason"] == "LEGACY_PLANS_REQUIRE_REVIEW"
        assert detail["reviewId"] is None and detail["dailyMapping"] is None
        assert detail["validationIssues"][0]["code"] == "LEGACY_PLANS_REQUIRE_REVIEW"
        assert detail["validationIssues"][0]["activationBlocking"] is True
        assert page["items"][0]["canActivate"] is False
        assert page["items"][0]["obsoleteReason"] == "LEGACY_PLANS_REQUIRE_REVIEW"
        assert (
            client.get("/api/v1/plan-versions", params={"canActivate": "true"}).json()["items"]
            == []
        )
    with factory() as session:
        row = session.get(PlanVersion, identity)
        provenance = session.get(PlanReviewProvenance, identity)
        assert (row.id, row.payload_json, row.plan_hash) == (identity, document, original_hash)
        assert (
            provenance.draft_hash,
            provenance.source_hash,
            provenance.confirmed_at,
        ) == old_provenance
    engine.dispose()


def test_successful_extraction_provenance_survives_lifecycle_restart_before_save(tmp_path):
    with TestClient(make_app(tmp_path, ai=True), base_url="http://127.0.0.1:8765") as client:
        provider = client.get("/api/v1/ai-runtime").json()["providerId"]
        receipt = post(
            client,
            "plan-extractions",
            {
                "providerId": provider,
                "sourceText": SOURCE,
                "expectedRevision": 0,
            },
            expected=202,
        )
        for _ in range(100):
            result = client.get("/api/v1/plan-extractions/" + receipt["operationId"]).json()
            if result["status"] not in {"QUEUED", "RUNNING"}:
                break
        assert result["status"] == "SUCCEEDED"
    # A separate UOW and a fresh service must find the committed extraction binding.
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        payload = {
            "extractionId": receipt["operationId"],
            "planJson": result["draftPlanJson"],
            "sourceText": SOURCE,
            "dailyMapping": result["dailyMapping"],
            "expectedRevision": 0,
        }
        post(client, "plan-drafts", {**payload, "extractionId": str(uuid4())}, expected=422)
        saved = post(client, "plan-drafts", payload)
        assert saved["dailyMapping"] == result["dailyMapping"]
        assert saved["canActivate"] is False and saved["reviewId"] is None
        assert saved["validationIssues"]
