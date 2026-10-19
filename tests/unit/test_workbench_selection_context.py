"""Workbench reuse preserves exact approval and separate historical account facts."""

from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_monitor_loop_input import account
from tests.unit.test_monitor_loop_schedule import at, version

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchPlanReference,
    WorkbenchReplayContext,
    WorkbenchReviewedPlan,
    freeze_workbench_selection,
)
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def reviewed():
    value = version()
    draft = UnifiedPlanDraft.from_executable(value.snapshot)
    source = "Synthetic human-reviewed supplements for this fixture."
    mapping = reviewed_mapping(draft, source)
    review = build_daily_review(draft, mapping, source)
    value = value.model_copy(
        update={
            "version_id": "77777777-7777-4777-8777-777777777777",
            "source_hashes": (review.source_hash,),
            "evidence_hash": review.evidence_hash,
            "review": value.review.model_copy(
                update={
                    "source_hashes": (review.source_hash,),
                    "evidence_hash": review.evidence_hash,
                }
            ),
        }
    )
    return WorkbenchReviewedPlan(
        reference=WorkbenchPlanReference(
            origin="WORKBENCH",
            plan_version_id=UUID("77777777-7777-4777-8777-777777777777"),
            plan_hash=daily_draft_sha256(draft),
            content_hash=value.review.content_hash,
            source_hash=value.source_hashes[0],
            review_evidence_hash=value.evidence_hash,
            review_id=UUID("88888888-8888-4888-8888-888888888888"),
            review_revision=1,
        ),
        version=value,
        draft_json=daily_draft_json(draft),
        source_text=source,
        mapping_json=mapping.model_dump_json(),
    )


def context():
    return WorkbenchReplayContext(
        effective_trade_date=date(2026, 8, 20),
        available_at=None,
        information_cutoff=at(20, 9),
        initial_account=account(),
        confirmed=True,
        evidence="Confirmed historical opening facts for offline research.",
    )


def test_selection_uses_original_approval_and_explicit_opening_context():
    original = reviewed()
    selected = freeze_workbench_selection(
        original, context(), selection_id="selection-one", confirmed_at=at(28, 10)
    )
    assert selected.version.snapshot == original.version.snapshot
    assert selected.version.review == original.version.review
    assert selected.source.execution_available_at == at(20, 9, 30)
    assert selected.account == context().initial_account
    assert selected.confirmed_at == at(28, 10)
    assert type(selected).model_validate_json(selected.model_dump_json()) == selected
    assert (
        selected.manifest_hash
        != selected.model_copy(update={"confirmed_at": at(28, 11)}).manifest_hash
    )


def test_context_does_not_invent_empty_holdings_or_widen_plan_dates():
    with pytest.raises(ValidationError):
        context().model_copy(update={"confirmed": False})
    with pytest.raises(ValueError):
        freeze_workbench_selection(
            reviewed(),
            context().model_copy(update={"information_cutoff": at(21, 9)}),
            selection_id="bad",
            confirmed_at=at(28, 10),
        )


def test_workbench_input_binds_research_declaration_without_changing_the_legacy_input():
    from tests.unit.test_monitor_loop_input import costs

    from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy, WorkbenchLoopInput
    from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary

    selected = freeze_workbench_selection(
        reviewed(), context(), selection_id="one", confirmed_at=at(28, 10)
    )
    run = WorkbenchLoopInput(
        selection_hash=selected.manifest_hash,
        schedule=selected.schedule,
        initial_account=selected.account,
        boundary=LoopEndBoundary.resolve(started_at=at(20, 9, 30), submitted_at=at(28, 10)),
        dataset_hash="a" * 64,
        response=LoopResponsePolicy(mode="OBSERVE_ONLY"),
        costs=costs(),
    )
    assert run.input_hash != run.model_copy(update={"selection_hash": "b" * 64}).input_hash
    assert run.run_formula_version == "backtest-run-v5"
