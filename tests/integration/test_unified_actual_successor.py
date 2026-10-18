"""Actual source 3 -> 4 replay in isolated stores with explicit test-only reviews."""

import asyncio
from datetime import date
from pathlib import Path

from tests.integration.test_plan_preparation_review import collection_review_command
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.backtest.jobs import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor
from trade_plan_monitor.web.preparation_schemas import project_collection_items

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_actual_successor_can_be_reviewed_and_composed_without_account_reset(tmp_path):
    seen_contexts = []

    class Provider:
        def __init__(self, filename):
            self.filename = filename

        async def extract_plan(self, request):
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=(FIXTURES / "ai" / self.filename).read_text("utf-8-sig"),
                finish_reason="stop",
                attempts=1,
                usage=None,
            )

    def call(identity, source, token, context=None):
        seen_contexts.append(context)
        kwargs = dict(
            request_id=identity,
            source=source,
            compact=True,
            config=_config().model_copy(
                update={"max_input_chars": 50000, "max_output_tokens": 16384}
            ),
        )
        if context is None:
            return asyncio.run(
                extract_loop_plan(**kwargs, provider=Provider("shengxin-unified-base-03.json"))
            )
        return asyncio.run(
            extract_plan_update(
                **kwargs, context=context, provider=Provider("shengxin-unified-update-04.json")
            )
        )

    async def scenario():
        store = PreparationStore(tmp_path / "preparation.sqlite3")
        service = PreparationService(
            store,
            BacktestJobRepository(tmp_path / "jobs.sqlite3"),
            PreparationExtractor(call, max_retries=0),
        )
        references, frozen_versions = [], []
        try:
            for index, (name, day) in enumerate(
                [
                    ("03-20260930-095728", date(2026, 9, 30)),
                    ("04-20261009-091956", date(2026, 10, 9)),
                ]
            ):
                source = PreparationSource(
                    source_id=name,
                    effective_trade_date=day,
                    text=(FIXTURES / f"shengxin_sources/{name}.txt").read_text("utf-8-sig"),
                )
                record = await service.library_write(
                    SingleSourcePreparationInput(
                        preparation_id=name,
                        source=source,
                        reviewed_base=references[-1] if references else None,
                    ),
                    idempotency_key=name + "-create",
                )
                await service.submit_extraction(
                    name,
                    expected_revision=record.revision,
                    idempotency_key=name + "-extract",
                    collection_mode=True,
                )
                await service.wait_for_drain()
                record = await service.get(name)
                assert record.status == "CANDIDATE" and record.review is None
                if index:
                    page = project_collection_items(record, offset=1, limit=1)
                    candidate = page.items[0].candidate
                    assert candidate.validation == "VALID"
                    assert not candidate.confirmation_summary.processing_issues
                    assert "rule-inheritance" not in {
                        q.question_id for q in candidate.confirmation_summary.questions
                    }
                    assert {c.action for c in candidate.review.changes} == {
                        "ADD",
                        "MODIFY",
                        "RETAIN",
                    }
                command = collection_review_command(record).model_copy(update={"account": None})
                approved = store.review_and_freeze(
                    name, command=command, idempotency_key=name + "-explicit-test-review"
                )
                frozen = frozen_preparation(approved)
                frozen_versions.append(frozen)
                references.append(
                    ReviewedPlanReference(preparation_id=name, manifest_hash=frozen.manifest_hash)
                )
            combined = await service.library_write(
                PreparedPlanCompositionInput(
                    preparation_id="test-only-combined", plans=tuple(references)
                ),
                idempotency_key="test-only-combine",
            )
            frozen = frozen_preparation(combined)
            assert len(frozen.schedule.entries) == 2
            assert frozen.account == frozen_versions[0].account == frozen_versions[1].account
            assert frozen.account.cash.kind == "POSITION_LIMIT_ONLY" and frozen.account.lots == ()
            from trade_plan_monitor.domain.unified_plan_models import condition_leaves

            for item, day in zip(frozen.items, (date(2026, 9, 30), date(2026, 10, 9)), strict=True):
                leaves = condition_leaves(item.version.snapshot.ordinary_rules[0].condition)
                gate = next(c for c in leaves if c.type == "DAILY_PRIOR_CLOSE")
                assert gate.since_date == day and gate.price_fen == 2599
            assert len(seen_contexts) == 2 and seen_contexts[0] is None
            assert seen_contexts[1].snapshot.position.max_qty == 300
        finally:
            await service.stop()

    asyncio.run(scenario())
