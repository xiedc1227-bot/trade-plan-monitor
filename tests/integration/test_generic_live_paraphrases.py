"""Unedited live responses: inheritance, changes, cancellation and genuine ambiguity."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    build_initial_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.backtest.preparation_repairs import correction_feedback
from trade_plan_monitor.domain.unified_plan_models import condition_leaves

BUNDLE = json.loads(
    (Path(__file__).parents[1] / "fixtures/ai/generic-live-paraphrases.json").read_text("utf-8")
)


class RecordedProvider:
    def __init__(self, response):
        self.response = response

    async def extract_plan(self, request):
        return RawAIResponse(
            request_id=request.request_id,
            provider_id=request.config.provider_id,
            model=request.config.model,
            content=self.response,
            finish_reason="stop",
            attempts=1,
            usage=None,
        )


def kwargs(case):
    return dict(
        request_id=uuid4(),
        compact=True,
        source=PreparationSource.model_validate_json(json.dumps(case["source"])),
        config=_config().model_copy(update={"max_input_chars": 50000, "max_output_tokens": 16384}),
        provider=RecordedProvider(case["response"]),
    )


@pytest.fixture(scope="module")
def reviewed_base():
    args = kwargs(BUNDLE["root"])
    result = asyncio.run(extract_loop_plan(**args))
    assert not result.validation_issues
    review = build_initial_review(result.draft, result.daily_mapping, args["source"])
    assert not review.issues and review.draft.position.max_qty == 300
    leaves = condition_leaves(review.draft.ordinary_rules[0].condition)
    assert any(c.type == "DAILY_CLOSE_SEQUENCE" and c.sessions == 2 for c in leaves)
    return review


@pytest.mark.parametrize("case", BUNDLE["cases"], ids=lambda c: c["name"])
def test_live_paraphrase_keeps_only_source_authorized_changes(reviewed_base, case):
    context = context_from_review(reviewed_base, "a" * 64)
    args = kwargs(case)
    result = asyncio.run(extract_plan_update(**args, context=context))
    materialized = materialize_extraction(reviewed_base, context.base_hash, args["source"], result)
    candidate = materialized.to_preparation_candidate()
    assert MaterializedUpdateCandidate.model_validate_json(candidate.payload_json) == materialized
    review = materialized.review
    name = case["name"]
    if name == "ambiguous":
        assert not candidate.policy_ready
        assert any("SOURCE_CONTENT_AMBIGUOUS" in i for i in candidate.issues)
        assert not correction_feedback(candidate)
        assert review.draft.version == reviewed_base.draft.version + 1
        assert review.draft.model_dump(exclude={"version"}) == reviewed_base.draft.model_dump(
            exclude={"version"}
        )
        return
    assert candidate.policy_ready and not review.issues
    assert review.draft.position.max_qty == (500 if name == "raise-cap" else 300)
    if name == "cancel":
        assert not review.draft.ordinary_rules
    else:
        assert len(review.draft.ordinary_rules) == 1
        assert review.draft.ordinary_rules[0].quantity == (200 if name == "quantity" else 100)
        assert (
            review.draft.ordinary_rules[0].condition
            == reviewed_base.draft.ordinary_rules[0].condition
        )
    if name == "add-alert":
        assert len(review.draft.alert_rules) == len(reviewed_base.draft.alert_rules) + 1
        alert = review.draft.alert_rules[-1]
        assert alert.condition.reference.value == 2400 and alert.condition.comparator == "LT"
    else:
        assert review.draft.alert_rules == reviewed_base.draft.alert_rules
