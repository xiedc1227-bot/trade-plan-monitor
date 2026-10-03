import pytest
from pydantic import TypeAdapter, ValidationError

from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition


def unified_payload():
    from tests.unit.test_daily_plan import synthetic_plan_payload

    raw = synthetic_plan_payload()
    raw.update(
        schema_version=5, execution_mode="CONDITION_PLAN", execution_version="condition-plan-v1"
    )
    raw["monitoring"].pop("timeframe")
    raw["execution_policy"].pop("confirmation")
    raw["execution_policy"].pop("ordinary_window")
    rules = []
    for rule in raw["ordinary_rules"]:
        if rule["status"] == "DISABLED":
            continue
        roots = [rule.pop(name) for name in ("price_structure", "volume_or_candle", "technical")]
        roots.extend(rule.pop("prerequisites"))
        rule.update(
            condition={"type": "ALL", "conditions": roots},
            confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
            execution_window="NEXT_EXCHANGE_SESSION_ONLY",
        )
        rules.append(rule)
    raw["ordinary_rules"] = rules
    for risk in raw["risk_branches"]:
        risk["condition"] = (
            None
            if risk["kind"] == "ORDINARY_TECHNICAL"
            else {
                "type": "ALL",
                "conditions": [
                    {
                        "type": "REVIEWED_FACT",
                        "fact_kind": kind,
                        "evidence_requirement": "Review technical evidence for " + kind,
                        "validity_scope": "TRADE_DATE",
                    }
                    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION")
                ],
            }
        )
    return raw


def test_current_codec_roundtrip_and_separate_semantic_hash():
    from trade_plan_monitor.domain.daily_plan_validation import (
        daily_draft_content_sha256,
        load_daily_draft_json,
    )
    from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
    from trade_plan_monitor.domain.plan_hash import unified_plan_content_sha256
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    plan = UnifiedTradePlan.model_validate(unified_payload())
    document = dump_plan_json(plan)
    assert load_plan_json(document) == plan
    draft = load_daily_draft_json(document)
    assert isinstance(draft, UnifiedPlanDraft)
    assert draft.to_executable() == plan
    assert daily_draft_content_sha256(draft) == unified_plan_content_sha256(plan)


def test_simple_minute_plan_has_no_inferred_daily_strategy():
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = unified_payload()
    raw.update(levels=None, monitoring=None, risk_branches=[])
    raw["position"] = {"max_qty": 1000}
    rule = raw["ordinary_rules"][0]
    rule.update(
        zone=None,
        condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
    )
    plan = UnifiedTradePlan.model_validate(raw)
    assert plan.levels is None and plan.monitoring is None and not plan.risk_branches
    assert plan.position.core_target_qty is None
    assert plan.position.tactical_target_qty is None
    assert plan.position.allocation_provenance is None
    assert plan.position.allocation_evidence is None


def test_current_optional_allocation_retains_whole_lot_and_maximum_validation():
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = unified_payload()
    raw["position"].update(core_target_qty=700, tactical_target_qty=400, max_qty=1000)
    with pytest.raises(ValidationError):
        UnifiedTradePlan.model_validate(raw)
    raw["position"].update(core_target_qty=150, tactical_target_qty=None)
    with pytest.raises(ValidationError):
        UnifiedTradePlan.model_validate(raw)


def test_current_risk_scope_does_not_invent_a_global_allocation():
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = unified_payload()
    raw["position"] = {"max_qty": 1000}
    plan = UnifiedTradePlan.model_validate(raw)
    assert plan.position.core_target_qty is None
    assert plan.risk_branches[0].target_core_qty == raw["risk_branches"][0]["target_core_qty"]


def test_source_minute_risk_reminder_needs_no_invented_liquidation_policy():
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    raw = unified_payload()
    raw.update(ordinary_rules=[], risk_branches=[], levels=None, monitoring=None)
    raw["position"] = {"max_qty": 300}
    raw["alert_rules"] = [
        {
            "kind": "RISK_ALERT",
            "rule_id": "risk-950",
            "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 950},
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        }
    ]
    plan = UnifiedTradePlan.model_validate(raw)
    draft = UnifiedPlanDraft.from_executable(plan)
    assert draft.to_executable() == plan
    assert plan.alert_rules[0].condition.price_fen == 950
    assert not plan.ordinary_rules and not plan.risk_branches
    assert "quantity" not in plan.alert_rules[0].model_dump()


def test_current_missing_maximum_keeps_a_draft_without_invented_allocation():
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    raw = unified_payload()
    raw["position"] = {"max_qty": None}
    raw["risk_branches"] = []
    draft = UnifiedPlanDraft.model_validate(raw)
    assert draft.to_executable() is None
    assert draft.position.core_target_qty is None


def test_current_persistent_review_and_activation(tmp_path):
    import asyncio
    from datetime import datetime
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    from tests.unit.test_daily_review import reviewed_mapping

    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
    from trade_plan_monitor.web.errors import ApiError
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
    from trade_plan_monitor.web.routers.daily_plans import DailySupplementCommand
    from trade_plan_monitor.web.routers.plans import (
        PlanActivationCommand,
        PlanDraftCommand,
        PlanReviewConfirmationCommand,
    )
    from trade_plan_monitor.web.schemas import MutationContext

    async def run():
        def context():
            return MutationContext(request_id=uuid4().hex, idempotency_key=str(uuid4()))

        lifecycle = PersistentPlanWebLifecycle(
            database_path=tmp_path / "current.sqlite",
            clock=lambda: datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        await lifecycle.start()
        try:
            draft = UnifiedPlanDraft.from_executable(
                UnifiedTradePlan.model_validate(unified_payload())
            )
            mapping = reviewed_mapping(draft)
            document = daily_draft_json(draft)
            await lifecycle.mutate_daily(
                operation="SUPPLEMENT",
                command=DailySupplementCommand(
                    candidate_json=document,
                    content_hash=mapping.candidate_content_hash,
                    supplements=mapping.supplements,
                    expected_revision=0,
                ),
                context=context(),
            )
            save_command = PlanDraftCommand(
                plan_json=document,
                source_text="Synthetic human-reviewed supplements for this fixture.",
                daily_mapping=mapping,
                expected_revision=0,
            )
            with pytest.raises(ApiError):
                await lifecycle.save_plan_draft(
                    command=save_command.model_copy(update={"extraction_id": uuid4()}),
                    context=context(),
                )
            with pytest.raises(ApiError):
                await lifecycle.save_plan_draft(
                    command=save_command.model_copy(update={"source_text": "Changed source."}),
                    context=context(),
                )
            saved = await lifecycle.save_plan_draft(
                command=PlanDraftCommand(
                    plan_json=document,
                    source_text="Synthetic human-reviewed supplements for this fixture.",
                    daily_mapping=mapping,
                    expected_revision=0,
                ),
                context=context(),
            )
            assert not saved.can_activate
            with pytest.raises(ApiError):
                await lifecycle.activate_plan(
                    command=PlanActivationCommand(plan_version_id=saved.id, expected_revision=0),
                    context=context(),
                )
            review_command = PlanReviewConfirmationCommand(
                plan_version_id=saved.id,
                content_hash=saved.content_hash,
                source_hash=saved.source_hash,
                review_evidence_hash=saved.review_evidence_hash,
                expected_revision=0,
            )
            with pytest.raises(ApiError):
                await lifecycle.confirm_plan_review(
                    command=review_command.model_copy(update={"source_hash": "0" * 64}),
                    context=context(),
                )
            reviewed = await lifecycle.confirm_plan_review(
                command=PlanReviewConfirmationCommand(
                    plan_version_id=saved.id,
                    content_hash=saved.content_hash,
                    source_hash=saved.source_hash,
                    review_evidence_hash=saved.review_evidence_hash,
                    expected_revision=0,
                ),
                context=context(),
            )
            active = await lifecycle.activate_plan(
                command=PlanActivationCommand(
                    plan_version_id=saved.id,
                    review_id=reviewed.review_id,
                    content_hash=saved.content_hash,
                    source_hash=saved.source_hash,
                    review_evidence_hash=saved.review_evidence_hash,
                    review_revision=1,
                    expected_revision=0,
                ),
                context=context(),
            )
            assert active.active
            await lifecycle.stop()
            await lifecycle.start()
            restored = await lifecycle.get_plan_version(version_id=str(saved.id))
            assert restored.review_id == reviewed.review_id and restored.can_activate
            edited_raw = draft.model_dump(mode="json")
            edited_raw["ordinary_rules"][0]["quantity"] = 200
            edited = UnifiedPlanDraft.model_validate(edited_raw)
            edited_mapping = reviewed_mapping(edited)
            await lifecycle.mutate_daily(
                operation="SUPPLEMENT",
                command=DailySupplementCommand(
                    candidate_json=daily_draft_json(edited),
                    content_hash=edited_mapping.candidate_content_hash,
                    supplements=edited_mapping.supplements,
                    expected_revision=0,
                ),
                context=context(),
            )
            edited_saved = await lifecycle.save_plan_draft(
                command=PlanDraftCommand(
                    base_plan_version_id=saved.id,
                    plan_json=daily_draft_json(edited),
                    source_text=save_command.source_text,
                    daily_mapping=edited_mapping,
                    expected_revision=1,
                ),
                context=context(),
            )
            assert not edited_saved.can_activate and edited_saved.review_id is None
            assert edited_saved.content_hash != saved.content_hash
            with pytest.raises(ApiError):
                await lifecycle.activate_plan(
                    command=PlanActivationCommand(
                        plan_version_id=edited_saved.id,
                        review_id=reviewed.review_id,
                        content_hash=saved.content_hash,
                        source_hash=saved.source_hash,
                        review_evidence_hash=saved.review_evidence_hash,
                        review_revision=1,
                        expected_revision=1,
                    ),
                    context=context(),
                )
        finally:
            await lifecycle.stop()

    asyncio.run(run())


def test_current_extraction_keeps_missing_review_and_mixed_conditions_visible():
    import asyncio
    import json
    from uuid import uuid4

    from tests.unit.test_ai_plan_extraction_v4 import _config

    from trade_plan_monitor.ai.extraction import extract_plan
    from trade_plan_monitor.ai.models import PlanExtractionStatus
    from trade_plan_monitor.ai.provider import RawAIResponse
    from trade_plan_monitor.ai.review import server_source_clauses
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    raw = unified_payload()
    raw["ordinary_rules"][0]["condition"]["conditions"].append(
        {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000}
    )
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source = (
        "Synthetic mixed daily and five-minute rule; every missing source binding needs review."
    )
    output = {
        "draft": draft.model_dump(mode="json"),
        "bindings": [],
        "clauses": [
            {
                **c.model_dump(mode="json"),
                "disposition": "UNRESOLVED",
                "paths": [],
                "reason": "Review synthetic source bindings.",
            }
            for c in server_source_clauses(source)
        ],
    }
    config = _config().model_copy(update={"prompt_version": "plan-extract-v9"})
    identity = uuid4()

    class Provider:
        async def extract_plan(self, request):
            assert "plan-extract-v9" in request.prompt
            return RawAIResponse(
                request_id=identity,
                provider_id=config.provider_id,
                model=config.model,
                content=json.dumps(output),
                finish_reason="stop",
                attempts=1,
                usage=None,
            )

    result = asyncio.run(
        extract_plan(request_id=identity, source_text=source, config=config, provider=Provider())
    )
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft.schema_version == 5
    assert result.draft.ordinary_rules[0].condition.conditions[-1].type == "MINUTE_CLOSE_BELOW"
    assert result.validation_issues
    assert not result.daily_mapping.supplements


def test_one_condition_tree_preserves_daily_and_minute_timeframes():
    raw = {
        "type": "ALL",
        "conditions": [
            {
                "type": "DAILY_PRICE_IN_RANGE",
                "field": "close",
                "offset": 0,
                "range": {
                    "low_fen": 1000,
                    "high_fen": 1200,
                    "include_low": True,
                    "include_high": True,
                },
            },
            {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 1150},
        ],
    }
    condition = TypeAdapter(UnifiedCondition).validate_python(raw)
    assert condition.model_dump(mode="json") == raw


def test_minute_condition_cannot_infer_a_timeframe_or_accept_one_minute():
    adapter = TypeAdapter(UnifiedCondition)
    for raw in (
        {"type": "MINUTE_CLOSE_BELOW", "price_fen": 1150},
        {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 1, "price_fen": 1150},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(raw)
