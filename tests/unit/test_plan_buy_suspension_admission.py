"""Parsing a new plan must not authorize historical frozen adapters or activation."""

from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError
from tests.unit.test_monitor_loop_schedule import version
from tests.unit.test_plan_buy_suspension_contract import suspension_payload
from tests.unit.test_unified_replay_input import create, research_input, research_plan

from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.backtest.plan_schedule import ScheduledPlanVersion
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft


def test_old_candidate_evidence_rejects_schema10_instead_of_reinterpreting_it():
    field = PlanCandidateReview.model_fields["draft"]
    adapter = TypeAdapter(Annotated[field.annotation, Field(discriminator=field.discriminator)])
    with pytest.raises(ValidationError):
        adapter.validate_python(suspension_payload())


def test_frozen_run_input_rejects_native_schema10_before_old_formula_can_accept_it():
    plan = BuySuspensionTradePlan.model_validate(suspension_payload())
    with pytest.raises(ValueError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        create(plan, research_input(plan))
    old = research_plan()
    payload = create(old, research_input(old)).model_dump(mode="python")
    payload["plan_snapshot"] = plan
    with pytest.raises(ValidationError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        BacktestRunInput.model_validate(payload)


@pytest.mark.parametrize("scheduled", [False, True])
def test_frozen_schedule_export_rejects_native_schema10(scheduled):
    plan = BuySuspensionTradePlan.model_validate(suspension_payload())
    if scheduled:
        payload = version().model_dump(mode="python")
        payload["snapshot"] = plan
        with pytest.raises(ValidationError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
            ScheduledPlanVersion.model_validate(payload)
    else:
        with pytest.raises(ValidationError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
            version(plan=plan)


def test_repository_requires_actual_saved_new_contract_before_activation(tmp_path):
    from trade_plan_monitor.state.database import (
        create_session_factory,
        create_sqlite_engine,
        upgrade_database,
    )
    from trade_plan_monitor.state.repositories import PlanVersionNotFoundError
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

    engine = create_sqlite_engine(tmp_path / "admission.sqlite")
    try:
        upgrade_database(engine)
        with SqlAlchemyUnitOfWork(create_session_factory(engine)) as work:
            plan = BuySuspensionTradePlan.model_validate(suspension_payload())
            with pytest.raises(
                PlanVersionNotFoundError, match="Plan version was not found",
            ):
                work.plans.activate(plan, expected_revision=0, validation=PlanValidationResult())
            assert work.plans.get_active(plan.symbol) is None
    finally:
        engine.dispose()


def test_public_lifecycle_new_schema_still_requires_exact_source_mapping(tmp_path):
    import asyncio
    from uuid import uuid4

    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
    from trade_plan_monitor.web.routers.plans import PlanDraftCommand
    from trade_plan_monitor.web.schemas import MutationContext

    lifecycle = PersistentPlanWebLifecycle(database_path=tmp_path / "public.sqlite")
    draft = BuySuspensionPlanDraft.model_validate(suspension_payload())

    async def scenario():
        await lifecycle.start()
        try:
            with pytest.raises(ApiError) as blocked:
                await lifecycle.save_plan_draft(
                    command=PlanDraftCommand(plan_json=draft.model_dump_json(),
                        source_text="Synthetic guard admission fixture", expected_revision=0),
                    context=MutationContext(request_id=uuid4().hex, idempotency_key=str(uuid4())))
            assert blocked.value.code == ApiErrorCode.VALIDATION_ERROR
        finally:
            await lifecycle.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["research", "loop"])
def test_private_legacy_context_adapter_never_accepts_schema10(kind):
    from types import SimpleNamespace

    from trade_plan_monitor.backtest.loop_session import _LoopPlans
    from trade_plan_monitor.backtest.research_session import _ResearchPlans

    plan = BuySuspensionTradePlan.model_validate(suspension_payload())
    adapter = (_ResearchPlans(SimpleNamespace(plan=plan)) if kind == "research"
        else _LoopPlans(None, SimpleNamespace(payload_json=plan.model_dump_json())))
    with pytest.raises(ValueError, match="BUY_SUSPENSION_FROZEN_UNSUPPORTED"):
        adapter._buy_suspension_context(None, plan.symbol)
