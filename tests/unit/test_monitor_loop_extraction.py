"""One source yields review-only plan/account facts through the real trust boundary."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.backtest.preparation_models import PreparationSource

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures/ai/monitor-loop-extraction-cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


def test_opening_account_contract_calculates_total_without_unit_rounding():
    from trade_plan_monitor.ai.loop_plan_extraction import (
        OpeningAccountFacts,
        validate_opening_evidence,
    )

    account = OpeningAccountFacts.model_validate_json(
        json.dumps(output_for(CASES[0])["opening_account"])
    )
    assert account.cost_basis_fen == 401050
    assert account.lots[0].cost_basis_fen == 401050
    assert account.cash_fen is None
    validate_opening_evidence(account, CASES[0]["source"])


def test_target_source_cannot_prove_an_actual_opening_lot():
    from trade_plan_monitor.ai.loop_plan_extraction import (
        OpeningAccountFacts,
        validate_opening_evidence,
    )

    source = "CORE目标持仓100股。每股成本40.105元/股。"
    payload = output_for(CASES[0])["opening_account"]
    payload["inventory_quantity"] = None
    lot = payload["lots"][0]
    lot["quantity"] = fact(source, "持仓100股", 100)
    lot["bucket"] = fact(source, "CORE目标持仓100股", "CORE")
    lot["unit_cost_yuan"] = fact(source, "每股成本40.105元/股", "40.105")
    account = OpeningAccountFacts.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="nonactual"):
        validate_opening_evidence(account, source)


def fact(source, excerpt, value):
    start = source.index(excerpt)
    return {"value": value, "start": start, "end": start + len(excerpt), "excerpt": excerpt}


def output_for(case):
    source = case["source"]
    lots = []
    if case["lot_quantity"] is not None:
        lots.append(
            {
                "lot_key": "opening-core",
                "quantity": fact(source, "CORE持仓100股", 100),
                "bucket": fact(source, "CORE持仓100股", "CORE"),
                "unit_cost_yuan": fact(source, "每股成本40.105元/股", "40.105"),
                "acquired_trade_date": None,
                "sellable_quantity": None,
            }
        )
    return {
        "schema_version": "monitor-loop-extraction-v1",
        "draft": {
            "schema_version": 5,
            "execution_mode": "CONDITION_PLAN",
            "execution_version": "condition-plan-v1",
            "plan_id": "synthetic-loop",
            "version": 1,
            "symbol": "002240.SZ",
            "name": "SYNTHETIC LOOP",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "MANUAL"},
            "levels": None,
            "position": {"max_qty": case["position_max_qty"]},
            "monitoring": None,
            "ordinary_rules": [],
            "risk_branches": [],
            "execution_policy": None,
        },
        "clauses": [
            {
                **clause.model_dump(mode="json"),
                "disposition": "UNRESOLVED",
                "paths": [],
                "reason": "Preserve this source clause for explicit semantic review.",
            }
            for clause in server_source_clauses(source)
        ],
        "bindings": [],
        "opening_account": {
            "inventory_quantity": fact(source, "实际持仓100股", 100)
            if case["inventory_quantity"] is not None
            else None,
            "lots": lots,
            "cash_fen": None,
            "snapshot_at": None,
        },
    }


def extract(
    output,
    source,
    *,
    finish_reason="stop",
    envelope="valid",
    provider_error=None,
    max_input_chars=200000,
    **metadata,
):
    from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan

    class Provider:
        async def extract_plan(self, request):
            assert request.config.prompt_version == "monitor-loop-extract-v1"
            if provider_error is not None:
                raise provider_error
            return RawAIResponse(
                request_id=uuid4() if envelope == "request" else request.request_id,
                provider_id=uuid4() if envelope == "provider" else request.config.provider_id,
                model=request.config.model,
                content=output
                if isinstance(output, str)
                else json.dumps(output, ensure_ascii=False),
                finish_reason=finish_reason,
                attempts=1,
                usage=None,
            )

    return asyncio.run(
        extract_loop_plan(
            request_id=uuid4(),
            source=PreparationSource(source_id="source-1", text=source, **metadata),
            config=_config().model_copy(update={"max_input_chars": max_input_chars}),
            provider=Provider(),
        )
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_explicit_opening_facts_preserve_exact_cost_and_unknowns(case):
    result = extract(output_for(case), case["source"])

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.schema_version == "monitor-loop-extraction-v1"
    assert result.draft.schema_version == 5
    assert result.draft.position.max_qty == 300
    assert not result.draft.ordinary_rules  # No buy derived from an observation zone.
    assert result.opening_account.cost_basis_fen == case["cost_basis_fen"]
    assert result.opening_account.cash_fen is None
    assert result.opening_account.snapshot_at is None
    if result.opening_account.lots:
        lot = result.opening_account.lots[0]
        assert lot.quantity.value == 100
        assert lot.bucket.value == "CORE"
        assert str(lot.unit_cost_yuan.value) == "40.105"
        assert lot.acquired_trade_date is None
        assert lot.sellable_quantity is None
    assert result.available_at is None
    assert result.authored_at is None
    assert result.effective_trade_date is None
    assert result.to_preparation_candidate().validation == "UNRESOLVED"
    assert len(result.daily_mapping.clauses) == len(server_source_clauses(case["source"]))
    assert any(i.code == "LOOP_ACCOUNT_FACT_REQUIRED" for i in result.validation_issues)


@pytest.mark.parametrize(
    "text",
    [
        "目标持仓100股",
        "假设持仓100股",
        "假想持仓100股",
        "建议持仓100股",
        "尚未实际持仓100股",
        "没有持仓100股",
        "如果持仓100股",
        "拟持仓100股",
        "参考持仓100股",
        "模拟持仓100股",
        "not actual holdings 100 shares",
        "proposed holdings 100 shares",
        "hypothetical holdings 100 shares",
    ],
)
def test_nonactual_context_cannot_be_cut_off_an_opening_quantity(text):
    source = text + "。"
    output = output_for(CASES[1])
    output["clauses"] = [
        {
            **c.model_dump(mode="json"),
            "disposition": "UNRESOLVED",
            "paths": [],
            "reason": "Keep ambiguous holdings visible.",
        }
        for c in server_source_clauses(source)
    ]
    excerpt = "holdings 100 shares" if "holdings" in text else "持仓100股"
    output["opening_account"].update(
        inventory_quantity=fact(source, excerpt, 100),
        lots=[
            {
                "lot_key": "one",
                "quantity": fact(source, excerpt, 100),
                "bucket": None,
                "unit_cost_yuan": None,
                "acquired_trade_date": None,
                "sellable_quantity": None,
            }
        ],
    )
    result = extract(output, source)
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None


@pytest.mark.parametrize(
    "attack",
    [
        "forged_excerpt",
        "shifted_span",
        "quantity_mismatch",
        "cost_mismatch",
        "float_cost",
        "false_cash",
        "false_sellability",
        "wrong_bucket",
        "zero_bucket_as_lot",
        "double_lot",
        "overlapping_lots",
        "total_mismatch",
        "extra_account",
        "approval",
        "predecessor",
        "updates",
        "wrong_version",
        "missing_version",
        "missing_clause",
        "forged_human",
    ],
)
def test_loop_candidate_rejects_forged_facts_and_out_of_scope_authority(attack):
    output = output_for(CASES[0])
    account = output["opening_account"]
    lot = account["lots"][0]
    if attack == "forged_excerpt":
        lot["quantity"]["excerpt"] = "SECRET_untrusted"
    elif attack == "shifted_span":
        lot["quantity"]["start"] += 1
    elif attack == "quantity_mismatch":
        account["inventory_quantity"] = None
        lot["quantity"]["value"] = 200
    elif attack == "cost_mismatch":
        lot["unit_cost_yuan"]["value"] = "40.11"
    elif attack == "float_cost":
        lot["unit_cost_yuan"]["value"] = 40.105
    elif attack == "false_cash":
        account["cash_fen"] = fact(CASES[0]["source"], "参考行情28.98元", 2898)
    elif attack == "false_sellability":
        lot["sellable_quantity"] = lot["quantity"]
    elif attack == "wrong_bucket":
        lot["bucket"]["value"] = "TACTICAL"
    elif attack == "zero_bucket_as_lot":
        lot["bucket"] = fact(CASES[0]["source"], "TACTICAL持仓0股", "TACTICAL")
    elif attack in {"double_lot", "overlapping_lots"}:
        duplicate = json.loads(json.dumps(lot))
        duplicate["lot_key"] = "second"
        if attack == "overlapping_lots":
            duplicate["quantity"] = fact(CASES[0]["source"], "持仓100股", 100)
        account["lots"].append(duplicate)
        account["inventory_quantity"] = None
    elif attack == "total_mismatch":
        account["inventory_quantity"]["value"] = 300
    elif attack == "extra_account":
        account["opening_mark"] = 2898
    elif attack in {"approval", "predecessor", "updates"}:
        output[attack] = "SECRET_untrusted"
    elif attack == "wrong_version":
        output["schema_version"] = "monitor-loop-extraction-v2"
    elif attack == "missing_version":
        output.pop("schema_version")
    elif attack == "missing_clause":
        output["clauses"].pop()
    elif attack == "forged_human":
        output["bindings"] = [
            {
                "path": "position.max_qty",
                "value": 300,
                "origin": "HUMAN_SUPPLEMENT",
                "unit": "SHARES",
                "clause_ids": [],
                "supplement_id": "SECRET_untrusted",
            }
        ]
    result = extract(output, CASES[0]["source"])
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert "SECRET_untrusted" not in result.model_dump_json()
    assert result.diagnostic is not None


def test_hypothetical_cost_prefix_remains_context_outside_quoted_span():
    source = "实际持仓100股。CORE持仓100股。假设买入100股，每股成本28.70元/股。"
    case = CASES[0] | {"source": source}
    output = output_for(CASES[1])
    output["clauses"] = [
        {
            **c.model_dump(mode="json"),
            "disposition": "UNRESOLVED",
            "paths": [],
            "reason": "Preserve source context.",
        }
        for c in server_source_clauses(source)
    ]
    account = output_for(CASES[0])["opening_account"]
    account["inventory_quantity"] = fact(source, "实际持仓100股", 100)
    lot = account["lots"][0]
    lot["quantity"] = fact(source, "CORE持仓100股", 100)
    lot["bucket"] = fact(source, "CORE持仓100股", "CORE")
    lot["unit_cost_yuan"] = fact(source, "每股成本28.70元/股", "28.70")
    output["opening_account"] = account
    result = extract(output, case["source"])
    assert result.status is PlanExtractionStatus.INVALID_OUTPUT


