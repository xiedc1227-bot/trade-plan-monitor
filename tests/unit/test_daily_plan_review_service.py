"""Real persisted review→activation via the normal plan application service."""

import asyncio
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from test_daily_review import reviewed_mapping
from test_unified_plan_domain import unified_payload as synthetic_plan_payload

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan as DailyTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft as DailyPlanDraft
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.daily_plans import DailySupplementCommand
from trade_plan_monitor.web.routers.plans import (
    PlanActivationCommand,
    PlanDraftCommand,
    PlanReviewConfirmationCommand,
)
from trade_plan_monitor.web.schemas import MutationContext


def context():
    return MutationContext(request_id=uuid4().hex, idempotency_key=str(uuid4()))


def test_persistent_daily_review_activation_and_restart(tmp_path):
    async def run():
        def clock():
            return datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

        lifecycle = PersistentPlanWebLifecycle(database_path=tmp_path / "daily.sqlite", clock=clock)
        await lifecycle.start()
        draft = DailyPlanDraft.from_executable(
            DailyTradePlan.model_validate(synthetic_plan_payload())
        )
        command = PlanDraftCommand(
            plan_json=daily_draft_json(draft),
            source_text="Synthetic human-reviewed supplements for this fixture.",
            daily_mapping=reviewed_mapping(draft),
            expected_revision=0,
        )
        await lifecycle.mutate_daily(
            operation="SUPPLEMENT",
            command=DailySupplementCommand(
                candidate_json=command.plan_json,
                content_hash=command.daily_mapping.candidate_content_hash,
                supplements=command.daily_mapping.supplements,
                expected_revision=0,
            ),
            context=context(),
        )
        saved = await lifecycle.save_plan_draft(command=command, context=context())
        assert saved.can_activate is False
        confirmed = await lifecycle.confirm_plan_review(
            command=PlanReviewConfirmationCommand(
                plan_version_id=saved.id,
                content_hash=saved.content_hash,
                source_hash=saved.source_hash,
                review_evidence_hash=saved.review_evidence_hash,
                expected_revision=0,
            ),
            context=context(),
        )
        assert confirmed.can_activate
        activated = await lifecycle.activate_plan(
            command=PlanActivationCommand(
                plan_version_id=saved.id,
                content_hash=saved.content_hash,
                source_hash=saved.source_hash,
                review_evidence_hash=saved.review_evidence_hash,
                review_revision=1,
                review_id=confirmed.review_id,
                expected_revision=0,
            ),
            context=context(),
        )
        assert activated.revision == 1
        await lifecycle.stop()
        await lifecycle.start()
        view = await lifecycle.get_plan_version(version_id=str(saved.id))
        assert view.can_activate and view.review_id == confirmed.review_id
        await lifecycle.stop()

    asyncio.run(run())
