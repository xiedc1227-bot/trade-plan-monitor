"""Actual-response regressions use isolated stores and explicit test-only review."""

import asyncio
from datetime import date
from pathlib import Path

import pytest
from tests.integration.test_plan_preparation_review import collection_review_command
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.backtest.jobs import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor

FIXTURES = Path(__file__).parents[1] / "fixtures"
DATES = ("2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09")


@pytest.mark.parametrize("number", [1, 2, 3, 4])
@pytest.mark.parametrize("known_cash", [False, True])
@pytest.mark.parametrize("round_name", ["", "live-check-"])
def test_account_choice_does_not_hide_missing_policy_or_grant_automatic_approval(
    tmp_path,
    number,
    known_cash,
    round_name,
):
    original = sorted((FIXTURES / "shengxin_sources").glob("*.txt"))[number - 1]
    source = PreparationSource(
        source_id=original.stem,
        text=original.read_text("utf-8-sig"),
        effective_trade_date=date.fromisoformat(DATES[number - 1]),
    )
    raw = (FIXTURES / f"ai/shengxin-source-resolution-{round_name}{number:02d}.json").read_text(
        "utf-8"
    )

    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content=raw,
                finish_reason="stop",
                attempts=1,
                usage=None,
            )

    calls = []

    def call(identity, source, token, context=None):
        calls.append((source.source_id, context))
        if context is not None:
            # Admission/prefix regression only; do not invent an AI update.
            return None
        return asyncio.run(
            extract_loop_plan(
                request_id=identity,
                source=source,
                config=_config().model_copy(
                    update={"max_input_chars": 50000, "max_output_tokens": 16384}
                ),
                provider=Provider(),
                compact=True,
            )
        )

    async def scenario():
        store = PreparationStore(tmp_path / "preparation.sqlite3")
        service = PreparationService(
            store, BacktestJobRepository(tmp_path / "jobs.sqlite3"), PreparationExtractor(call)
        )
        try:
            record = await service.library_write(
                SingleSourcePreparationInput(preparation_id="test-only", source=source),
                idempotency_key="create",
            )
            await service.submit_extraction(
                record.preparation_id,
                expected_revision=record.revision,
                idempotency_key="extract",
                collection_mode=True,
            )
            await service.wait_for_drain()
            record = await service.get(record.preparation_id)
            assert record.status == "CANDIDATE" and record.review is None
            command = collection_review_command(record)
            if not known_cash:
                command = command.model_copy(update={"account": None})
            if number in {1, 2}:
                with pytest.raises(PreparationConflictError):
                    store.review_and_freeze(
                        record.preparation_id, command=command, idempotency_key="test-review"
                    )
                assert store.get(record.preparation_id) == record
            else:
                reviewed = store.review_and_freeze(
                    record.preparation_id, command=command, idempotency_key="test-review"
                )
                frozen = frozen_preparation(reviewed)
                assert frozen.account.cash.kind == (
                    "KNOWN" if known_cash else "POSITION_LIMIT_ONLY"
                )
                assert frozen.account.inventory_known and frozen.account.lots == ()
                assert frozen.account.snapshot_at == source.execution_available_at
                assert frozen.opening_evidence.snapshot_at is None
                # A reviewed cash-unknown predecessor remains immutable; the
                # next preparation must target the new source, not re-extract it.
                from trade_plan_monitor.backtest.plan_library import create_single_preparation
                from trade_plan_monitor.backtest.preparation_models import ReviewedPlanReference

                linked = create_single_preparation(
                    store,
                    SingleSourcePreparationInput(
                        preparation_id="test-only-next",
                        source=source.model_copy(
                            update={
                                "source_id": "test-only-next-source",
                                "effective_trade_date": date(2026, 10, 19),
                            }
                        ),
                        reviewed_base=ReviewedPlanReference(
                            preparation_id=record.preparation_id,
                            manifest_hash=frozen.manifest_hash,
                        ),
                    ),
                    idempotency_key="test-next",
                )
                assert store.next_collection_item(linked)[0] == 1
                assert linked.items[0] == reviewed.items[0]
                if number == 3:
                    await service.submit_extraction(
                        linked.preparation_id, expected_revision=linked.revision,
                        idempotency_key="test-next-extract", collection_mode=True,
                    )
                    await service.wait_for_drain()
                    assert len(calls) == 2
                    assert calls[-1][0] == "test-only-next-source"
                    assert calls[-1][1].snapshot.position.max_qty == 300
                    assert (await service.get(linked.preparation_id)).items[0] == reviewed.items[0]
        finally:
            await service.stop()

    asyncio.run(scenario())
