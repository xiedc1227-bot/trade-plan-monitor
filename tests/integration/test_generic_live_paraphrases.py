"""Recorded responses retain historical semantics and current coverage blockers."""

import asyncio
import json
from hashlib import sha256
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
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
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
    assert result.coverage is not None and result.coverage.status == "BLOCKED"
    assert not result.coverage.coverage_complete and not result.coverage.authority_granted
    assert result.validation_issues and all(i.activation_blocking for i in result.validation_issues)
    assert {i.code for i in result.validation_issues} == {
        "SOURCE_CONTEXT_UNVERIFIED", "SOURCE_RELATION_MISMATCH",
    }
    assert tuple((i.code, i.path) for i in result.validation_issues) == tuple(
        (i.code, i.path) for i in result.coverage.issues)
    assert len(result.coverage.issues) == len(result.validation_issues) == 154
    codes = [i.code for i in result.coverage.issues]
    assert codes.count("SOURCE_CONTEXT_UNVERIFIED") == 91
    assert codes.count("SOURCE_RELATION_MISMATCH") == 63
    # Fixed from the original recorded-response diagnosis, including every span and message.
    coverage_issues = json.dumps([i.model_dump(mode="json") for i in result.coverage.issues],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert sha256(coverage_issues).hexdigest() == (
        "b75916e28ee1a687d56da928d798f7498233d44bbf6d0bddc1178c1d591bf563")
    validation_issues = json.dumps([i.model_dump(mode="json") for i in result.validation_issues],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert sha256(validation_issues).hexdigest() == (
        "05b80066a45c8bedec968bce57e98129191d8d1663b30299feb4155c5e42c818")
    assert result.coverage.origin == "AI_NEW" and not result.coverage.automatic_fidelity_verified
    assert result.coverage.source_hash == result.source_text_sha256 == (
        scope_hash(args["source"].text))
    assert result.source_text_sha256 == sha256(args["source"].text.encode("utf-8")).hexdigest()
    assert result.coverage.content_hash == result.daily_mapping.candidate_content_hash == (
        daily_draft_content_sha256(result.draft))
    assert result.coverage.mapping_hash == daily_hash(
        "source-coverage-mapping-v1", result.daily_mapping.model_dump(mode="json"))
    assert result.normalization_trace is not None
    assert result.normalization_trace.source_hash == result.coverage.source_hash
    assert result.coverage.normalization_hash == result.normalization_trace.evidence_hash
    assert result.normalization_trace.after_hash == daily_hash(
        "source-normalization-candidate-v1", result.draft.model_dump(mode="json"))
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
    decoded = MaterializedUpdateCandidate.model_validate_json(candidate.payload_json)
    assert decoded.model_dump(mode="json") == materialized.model_dump(mode="json")
    assert decoded.review == materialized.review
    assert (
        decoded.review.evidence_hash == materialized.review.evidence_hash == candidate.evidence_hash
    )
    assert decoded.extraction.evidence_hash == materialized.extraction.evidence_hash
    assert decoded.extraction.diagnostic is None
    assert decoded.extraction.source_derivation is None
    assert decoded.extraction.derivation_issues == ()
    assert decoded.to_preparation_candidate().payload_json.encode("utf-8") == (
        candidate.payload_json.encode("utf-8"))
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
    # Local historical update readiness cannot replace the blocked parent's current assurance.
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
