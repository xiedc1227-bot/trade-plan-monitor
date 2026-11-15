"""Engineering-only current source-change flow; no original-source approval claims."""

import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_plan_buy_suspension_contract import suspension_payload
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.plan_update_extraction import (
    BuySuspensionPlanUpdateExtractionOutput,
    extract_buy_suspension_plan_update,
)
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.source_derivation_replay import verify_update_derivation
from trade_plan_monitor.ai.update_review import (
    PlanCandidateReview,
    build_update_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.plan_updates import MaterializedPlanUpdate, materialize_plan_update
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan


def flow_inputs():
    raw = research_plan().model_dump(mode="json")
    raw.update(
        schema_version=10,
        execution_version="condition-plan-v6",
        buy_suspension=suspension_payload()["buy_suspension"],
    )
    base = prior_review(BuySuspensionTradePlan.model_validate_json(json.dumps(raw)))
    source, old_output = current_update()
    raw = old_output.model_dump(mode="json")
    raw["schema_version"] = "monitor-loop-update-extraction-v2"
    # Ordinary continuation must preserve the predecessor guard despite model omission.
    raw["draft"].update(
        schema_version=10, execution_version="condition-plan-v6", buy_suspension=None
    )
    return (
        base,
        source,
        BuySuspensionPlanUpdateExtractionOutput.model_validate_json(json.dumps(raw)),
    )


def test_current_update_preserves_definition_start_and_exact_inherited_evidence():
    base, source, output = flow_inputs()
    assert base.issues == ()
    context = context_from_review(base, base.evidence_hash)
    merged = materialize_plan_update(context.snapshot, output)
    reviewed = build_update_review(base, source, output)
    assert merged.draft == reviewed.draft
    assert reviewed.issues == ()
    assert reviewed.draft.position.max_qty == 300
    assert reviewed.draft.buy_suspension == base.draft.buy_suspension
    guard_origins = [row for row in merged.origins if row.path.startswith("buy_suspension.")]
    assert guard_origins and all(row.origin == "BASE" for row in guard_origins)
    before = [row for row in base.bindings if row.path.startswith("buy_suspension.")]
    assert {
        row.path: row for row in reviewed.bindings if row.path.startswith("buy_suspension.")
    } == {row.path: row for row in before}
    assert any(row.target == "buy_suspension" and row.action == "RETAIN" for row in merged.changes)
    with pytest.raises(ValidationError):
        MaterializedPlanUpdate.model_validate_json(merged.model_dump_json())
    with pytest.raises(ValidationError):
        PlanCandidateReview.model_validate_json(reviewed.model_dump_json())
    with pytest.raises(ValueError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        reviewed.to_preparation_candidate()


def test_callable_v2_extract_materialize_review_and_derivation_replay_form_one_flow():
    base, source, output = flow_inputs()
    context = context_from_review(base, base.evidence_hash)
    calls = []

    class Provider:
        async def extract_plan(self, request):
            calls.append(request)
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=output.model_dump_json(),
                finish_reason="stop",
                attempts=1,
                usage=None,
            )

    extraction = asyncio.run(
        extract_buy_suspension_plan_update(
            request_id=uuid4(),
            source=source,
            context=context,
            provider=Provider(),
            config=_config().model_copy(
                update={"prompt_version": "plan-extract-v13", "max_input_chars": 200000}
            ),
        )
    )
    result = materialize_extraction(base, base.evidence_hash, source, extraction)
    assert len(calls) == 1 and not result.extraction.derivation_issues
    assert result.review.issues == ()
    assert result.review.draft.buy_suspension == base.draft.buy_suspension
    assert len(result.extraction.source_derivation.stages) == 3
    assert (
        verify_update_derivation(
            result.extraction.source_derivation, source, context, extraction.output
        )
        == extraction.output
    )
    with pytest.raises(ValueError, match="predecessor"):
        materialize_extraction(base, "c" * 64, source, extraction)
    with pytest.raises(ValueError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        result.to_preparation_candidate()


def test_explicit_guard_retirement_proposal_stays_blocked_for_separate_review():
    base, source, output = flow_inputs()
    raw = output.model_dump(mode="json")
    raw["operations"].append(
        {
            "target": "buy_suspension",
            "action": "MODIFY",
            "rule_id": None,
            "clause_ids": list(output.scope_clause_ids),
        }
    )
    proposal = BuySuspensionPlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    reviewed = build_update_review(base, source, proposal)
    assert reviewed.draft.buy_suspension is None
    assert "BUY_SUSPENSION_REPLACEMENT_REVIEW_REQUIRED" in reviewed.issues


def test_current_cannot_use_historical_materialization_to_bypass_review():
    base, _, output = flow_inputs()
    with pytest.raises(ValueError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        materialize_plan_update(base.draft.to_executable(), output, historical=True)
