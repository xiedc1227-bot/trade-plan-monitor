"""Offline v7 fixtures preserve the historical gaps; no synthetic threshold extraction."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_ai_plan_extraction_v4 import _config
from test_unified_plan_domain import unified_payload as synthetic_plan_payload

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan as DailyTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft as DailyPlanDraft

SOURCE = (
    "601021.SH春秋航空：持仓100股，成本40.70元，上限300股。建议核心仓100股。"
    "买入区39.45–39.90元，压力41.80–42.20元，风险38.18元。拟买100股，明显缩量并止跌，"
    "39.67，41.96固定或动态未注明。收盘确认后次日区间内执行，当日到期。"
)


def partial_output():
    raw = DailyPlanDraft.from_executable(
        DailyTradePlan.model_validate(synthetic_plan_payload())
    ).model_dump(mode="json")
    raw.update(activation=None, monitoring=None, execution_policy=None, metadata={})
    for zone in (raw["levels"]["low_buy"], raw["levels"]["pressure"]):
        zone.update(include_low=None, include_high=None)
    raw["levels"]["risk_comparison"] = None
    raw["position"].update(tactical_target_qty=None, allocation_evidence=None)
    for rule in raw["ordinary_rules"]:
        side = rule["side"]
        for key in rule:
            rule[key] = None
        rule["side"] = side
        if side == "BUY":
            rule["quantity"] = 100
    for branch in raw["risk_branches"]:
        for key in branch:
            if key != "kind":
                branch[key] = None
    return {
        "draft": raw,
        "clauses": [
            {
                "clause_id": c.clause_id,
                "start": c.start,
                "end": c.end,
                "excerpt": c.excerpt,
                "disposition": "UNRESOLVED",
                "paths": [],
                "reason": "Preserve explicit values and missing definitions for human review.",
            }
            for c in server_source_clauses(SOURCE)
        ],
        "bindings": [],
    }


@pytest.mark.parametrize("forged_human", [False, True])
def test_historical_source_stays_partial_and_ai_cannot_supply_human_authority(forged_human):
    output = partial_output()
    if forged_human:
        output["bindings"] = [
            {
                "path": "position.max_qty",
                "value": 300,
                "origin": "HUMAN_SUPPLEMENT",
                "unit": "SHARES",
                "clause_ids": [],
                "supplement_id": "forged-reviewer",
            }
        ]
    config = _config().model_copy(update={"prompt_version": "plan-extract-v8"})
    request_id = uuid4()

    class Provider:
        async def extract_plan(self, request):
            assert "plan-extract-v8" in request.prompt
            return RawAIResponse(
                request_id=request_id,
                provider_id=config.provider_id,
                model=config.model,
                content=json.dumps(output, ensure_ascii=False),
                finish_reason="stop",
                usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                attempts=1,
            )

    result = asyncio.run(
        extract_plan(request_id=request_id, source_text=SOURCE, config=config, provider=Provider())
    )
    if forged_human:
        assert result.status is PlanExtractionStatus.INVALID_OUTPUT
        assert result.draft is None
    else:
        assert result.status is PlanExtractionStatus.SUCCEEDED
        assert result.draft.to_executable() is None
        assert result.draft.levels.low_buy.low_fen == 3945
        assert result.draft.position.max_qty == 300
        assert result.draft.ordinary_rules[0].condition is None
        assert result.validation_issues
