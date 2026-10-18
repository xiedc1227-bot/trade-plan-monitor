"""Different phrasing separates conditional entry from another discretionary decision."""

import asyncio
import json
from pathlib import Path

import pytest
from tests.integration.test_generic_live_paraphrases import kwargs

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.update_review import (
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.domain.unified_plan_models import condition_leaves

FIXTURES = Path(__file__).parents[1] / "fixtures/ai"
CASES = json.loads((FIXTURES / "generic-live-authority-cases.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def base():
    chain = json.loads((FIXTURES / "generic-live-four-plan-chain.json").read_text("utf-8"))
    args = kwargs(chain[0])
    result = asyncio.run(extract_loop_plan(**args))
    review = build_initial_review(result.draft, result.daily_mapping, args["source"])
    context = context_from_review(review, review.evidence_hash)
    args = kwargs(chain[1])
    result = asyncio.run(extract_plan_update(**args, context=context))
    return materialize_extraction(review, context.base_hash, args["source"], result).review


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_live_authority_and_temporal_order(base, case):
    context = context_from_review(base, base.evidence_hash)
    args = kwargs(case)
    result = asyncio.run(extract_plan_update(**args, context=context))
    materialized = materialize_extraction(base, context.base_hash, args["source"], result)
    assert materialized.to_preparation_candidate().policy_ready
    draft = materialized.review.draft
    assert draft.position.max_qty == 300 and draft.risk_branches == base.draft.risk_branches
    if case["name"] == "assessment-only":
        assert not draft.ordinary_rules
        assert len(draft.alert_rules) == len(base.draft.alert_rules) + 1
        assert draft.alert_rules[-1].condition.reference.value == 2710
        return
    assert len(draft.ordinary_rules) == 1
    rule = draft.ordinary_rules[0]
    assert rule.quantity == 100 and rule.execution_window == "NEXT_EXCHANGE_SESSION_ONLY"
    leaves = condition_leaves(rule.condition)
    prior = next(c for c in leaves if c.type == "DAILY_PRIOR_CLOSE")
    assert prior.price_fen == 2710 and prior.comparator == "GT"
    zone = next(c for c in leaves if c.type == "DAILY_PRICE_IN_RANGE")
    assert zone.field == "low" and (zone.range.low_fen, zone.range.high_fen) == (2680, 2710)
    assert any(c.type == "REVIEWED_FACT" for c in leaves)
