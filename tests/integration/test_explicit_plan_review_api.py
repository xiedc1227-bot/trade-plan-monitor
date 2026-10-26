"""The public review workflow uses schema5 and server-owned current extraction."""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_current_plan_api import make_app, post, review_payload, reviewed_save
from tests.integration.test_source_treatment_review_api import (
    SOURCE,
    assert_semantic_review,
    literal_draft,
    literal_mapping,
    register,
    save,
)
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.ai.daily_review import DailyMapping, daily_source_clauses
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_json,
)
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

_ORIGINAL_SOURCE = (
    "003043.SZ现有100股且今日可卖，最高300股。"
    "五分钟收盘价在9.80至10.00元（含端点）且当前成交量不少于前5根已完成五分钟K线"
    "成交量算术平均值的1.5倍时买入100股；五分钟收盘价在10.80至11.00元（含端点）时卖出100股；"
    "五分钟收盘价低于9.50元时风险提醒。提醒和确认不代表成交。"
)


def record_current(
    lifecycle, draft, *, source=SOURCE, config_label="plan-extract-v9", finish="stop"
):
    config = _config().model_copy(update={"prompt_version": config_label})
    identity = uuid4()

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "plan-extract-v11"
            return RawAIResponse(
                request_id=identity,
                provider_id=config.provider_id,
                model=config.model,
                content=json.dumps(
                    {
                        "draft": draft.model_dump(mode="json"),
                        "bindings": [],
                        "clauses": [
                            c.model_dump(mode="json") for c in daily_source_clauses(source)
                        ],
                    }
                ),
                usage=None,
                attempts=1,
                finish_reason=finish,
            )

    result = asyncio.run(
        extract_plan(request_id=identity, source_text=source, config=config, provider=Provider())
    )
    if result.status is PlanExtractionStatus.SUCCEEDED:
        asyncio.run(lifecycle.record_plan_extraction(result))
    return result


def save_extracted(client, result, source=SOURCE):
    return post(
        client,
        "plan-drafts",
        {
            "extractionId": str(result.request_id),
            "sourceText": source,
            "planJson": daily_draft_json(result.draft),
            "dailyMapping": result.daily_mapping.model_dump(mode="json"),
            "expectedRevision": 0,
        },
    )


@pytest.mark.parametrize("config_label", ["plan-extract-v4", "plan-extract-v5", "plan-extract-v6"])
def test_mapping_extraction_save_review_and_public_activation_are_server_bound(
    tmp_path, config_label
):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        draft = literal_draft(complete=True)
        result = record_current(app.state.plan_web_lifecycle, draft, config_label=config_label)
        assert result.prompt_version == "plan-extract-v11"
        first = save_extracted(client, result)
        assert first["contentHash"] and first["sourceHash"] and first["reviewEvidenceHash"]
        assert first["reviewRevision"] == 0 and first["reviewId"] is None
        assert first["canActivate"] is False and first["dailyIssues"]
        post(
            client, "plan-review-confirmations", review_payload(first, resolutions=[]), expected=422
        )
        post(
            client,
            "plan-review-confirmations",
            review_payload(
                first,
                resolutions=[
                    {
                        "issueId": "issue-000000000000000000000000",
                        "resolution": "CONFIRM_MAPPING",
                        "bindingPath": "symbol",
                    }
                ],
            ),
            expected=422,
        )
        post(
            client,
            "plan-review-confirmations",
            review_payload(first, reviewEvidenceHash="e" * 64),
            expected=422,
        )
        mapping = literal_mapping(draft)
        register(client, draft, mapping)
        current = save(client, draft, mapping, base=first["id"])
        assert_semantic_review(current)
        reviewed = post(client, "plan-review-confirmations", review_payload(current))
        assert reviewed["canActivate"] and reviewed["revision"] == 1 and reviewed["reviewId"]
        post(client, "plan-review-confirmations", review_payload(current), expected=409)
        post(
            client,
            "plan-activations",
            {"planVersionId": current["id"], "expectedRevision": 0},
            expected=409,
        )
        active = post(
            client,
            "plan-activations",
            review_payload(current, reviewId=reviewed["reviewId"], reviewRevision=1),
        )
        assert active["active"] and active["planVersionId"] == current["id"]
        before = client.get("/api/v1/plan-activation-states/003043.SZ").json()
        truncated = record_current(
            app.state.plan_web_lifecycle, draft, config_label=config_label, finish="length"
        )
        assert truncated.status is PlanExtractionStatus.INVALID_OUTPUT
        assert truncated.draft is None and getattr(truncated, "daily_mapping", None) is None
        assert client.get("/api/v1/plan-activation-states/003043.SZ").json() == before
        capability = client.get("/api/v1/plan-capabilities").json()
        assert capability["schemaVersion"] == 5 and capability["publicActivationAvailable"]
        assert (
            capability["isolatedTrustedReviewOnly"] is False
            and capability["pendingRequirements"] == []
        )


def test_partial_draft_persists_and_stale_review_cannot_cross_an_immutable_edit(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        partial = literal_draft(complete=False)
        first = reviewed_save(client, partial, source=SOURCE)
        restored = client.get("/api/v1/plan-versions/" + first["id"]).json()
        assert (
            restored["planJson"] == daily_draft_json(partial) and restored["canActivate"] is False
        )
        data = partial.model_dump(mode="json")
        data["version"] = 99
        data["ordinary_rules"][0]["condition"]["conditions"][0]["low_fen"] = 970
        edited = UnifiedPlanDraft.model_validate(data)
        second = reviewed_save(client, edited, source=SOURCE, base=first["id"])
        assert second["version"] == 2 and second["contentHash"] != first["contentHash"]
        assert second["reviewId"] is None
        post(
            client,
            "plan-review-confirmations",
            review_payload(
                second,
                contentHash=first["contentHash"],
                sourceHash=first["sourceHash"],
                reviewEvidenceHash=first["reviewEvidenceHash"],
            ),
            expected=422,
        )
        assert (
            client.get("/api/v1/plan-versions/" + first["id"]).json()["planJson"]
            == restored["planJson"]
        )


def test_original_source_partial_save_current_edit_and_semantic_review_stay_bound(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        partial = literal_draft(complete=False)
        result = record_current(app.state.plan_web_lifecycle, partial, source=_ORIGINAL_SOURCE)
        first = save_extracted(client, result, _ORIGINAL_SOURCE)
        assert first["sourceText"] == _ORIGINAL_SOURCE and first["canActivate"] is False
        assert first["dailyMapping"]["supplements"] == []
        assert {
            i["path"] for i in first["dailyIssues"] if i["code"] == "PLAN_PARAMETER_REQUIRED"
        } >= {"activation"}
        complete = literal_draft(complete=True)
        raw_mapping = reviewed_mapping(complete, _ORIGINAL_SOURCE).model_dump(mode="json")
        # Independent source oracle keeps exact values/units/clause ownership;
        # software codes, timing policies and logical interpretation remain
        # separately registered human supplements.
        numeric = {
            "position.max_qty": (300, 1, "SHARES"),
            "ordinary_rules[0].quantity": (100, 2, "SHARES"),
            "ordinary_rules[0].condition.conditions[0].low_fen": (980, 2, "FEN_FROM_YUAN"),
            "ordinary_rules[0].condition.conditions[0].high_fen": (1000, 2, "FEN_FROM_YUAN"),
            "ordinary_rules[0].condition.conditions[1].window_bars": (5, 2, "JSON"),
            "ordinary_rules[0].condition.conditions[1].minimum_ratio": ("1.5", 2, "RATIO"),
            "ordinary_rules[1].quantity": (100, 3, "SHARES"),
            "ordinary_rules[1].condition.low_fen": (1080, 3, "FEN_FROM_YUAN"),
            "ordinary_rules[1].condition.high_fen": (1100, 3, "FEN_FROM_YUAN"),
            "alert_rules[0].condition.price_fen": (950, 4, "FEN_FROM_YUAN"),
        }
        raw_mapping["supplements"] = [
            x for x in raw_mapping["supplements"] if x["path"] not in numeric
        ]
        for binding in raw_mapping["bindings"]:
            if binding["path"] in numeric:
                value, index, unit = numeric[binding["path"]]
                assert binding["value"] == value
                binding.update(
                    origin="SOURCE",
                    unit=unit,
                    supplement_id=None,
                    clause_ids=[raw_mapping["clauses"][index]["clause_id"]],
                )
        for clause in (raw_mapping["clauses"][0], raw_mapping["clauses"][-1]):
            clause.update(
                disposition="UNRESOLVED", paths=[], reason="Confirm source context explicitly."
            )
        mapping = DailyMapping.model_validate(raw_mapping)
        register(client, complete, mapping)
        second = post(
            client,
            "plan-drafts",
            {
                "basePlanVersionId": first["id"],
                "sourceText": _ORIGINAL_SOURCE,
                "planJson": daily_draft_json(complete),
                "expectedRevision": 0,
                "dailyMapping": mapping.model_dump(mode="json"),
            },
        )
        assert (
            second["sourceHash"] == first["sourceHash"]
            and second["contentHash"] != first["contentHash"]
        )
        assert second["sourceText"] == _ORIGINAL_SOURCE
        supplements = second["dailyMapping"]["supplements"]
        assert {item["path"] for item in supplements} == {item.path for item in mapping.supplements}
        assert supplements == [item.model_dump(mode="json") for item in mapping.supplements]
        unreviewed = [
            c["excerpt"]
            for c in second["dailyMapping"]["clauses"]
            if c["disposition"] == "UNRESOLVED"
        ]
        assert unreviewed == ["003043.SZ现有100股且今日可卖，", "提醒和确认不代表成交。"]
        assert len(second["dailyIssues"]) == 2
        assert all(i["code"] == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in second["dailyIssues"])
        assert [c["excerpt"] for c in second["dailyMapping"]["clauses"]] == [
            c.excerpt for c in daily_source_clauses(_ORIGINAL_SOURCE)
        ]
        post(client, "plan-review-confirmations", review_payload(second), expected=422)
        assert second["canActivate"] is False and second["reviewId"] is None
        body = json.loads(second["planJson"])
        assert body["ordinary_rules"][0]["condition"]["type"] == "ALL"
        assert (
            body["alert_rules"][0]["condition"]["price_fen"] == 950 and body["risk_branches"] == []
        )
