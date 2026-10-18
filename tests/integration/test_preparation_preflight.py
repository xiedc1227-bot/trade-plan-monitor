"""Missing dates block admission; input-budget failures retain their real cause."""

import asyncio
from datetime import date
from pathlib import Path

import pytest
from tests.integration.test_plan_preparation_worker import service_setup
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.backtest.preparation_models import (
    PlanCollectionPreparationInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor


def test_missing_date_is_rejected_without_attempt_or_provider_call(tmp_path):
    async def scenario():
        service, store, jobs, initial, calls = service_setup(tmp_path)
        initial = store.edit_source("one", source=initial.source.model_copy(update={
            "effective_trade_date": None,
        }), expected_revision=initial.revision, idempotency_key="clear-date")
        try:
            with pytest.raises(PreparationConflictError, match="SOURCE_DATE_REQUIRED"):
                await service.submit_extraction("one", expected_revision=initial.revision,
                                                idempotency_key="extract")
            assert store.get("one") == initial
            assert calls == []
            assert jobs.list_jobs() == ()
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_actual_sources_need_confirmation_before_any_extraction(tmp_path):
    async def scenario():
        service, store, _, _, calls = service_setup(tmp_path)
        sources = tuple(PreparationSource(source_id=path.stem,
            text=path.read_text(encoding="utf-8-sig")) for path in sorted(
                (Path(__file__).parents[1] / "fixtures/shengxin_sources").glob("*.txt")))
        initial = store.create(PlanCollectionPreparationInput(
            preparation_id="actual", sources=sources), idempotency_key="actual-create")
        try:
            with pytest.raises(PreparationConflictError, match="SOURCE_DATE_REQUIRED"):
                await service.submit_extraction("actual", expected_revision=initial.revision,
                                                idempotency_key="actual-extract")
            assert store.get("actual") == initial
            assert [item.status for item in initial.items] == [
                "DRAFT", "WAITING", "WAITING", "WAITING",
            ]
            assert calls == []
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_input_limit_reason_is_durable_and_never_automatically_retried(tmp_path):
    async def scenario():
        service, store, _, initial, _ = service_setup(tmp_path)
        source = initial.source.model_copy(update={"effective_trade_date": date(2026, 8, 20)})
        initial = store.edit_source("one", source=source,
            expected_revision=initial.revision, idempotency_key="dated")
        calls = []

        class NoProvider:
            async def extract_plan(self, request):
                pytest.fail("Oversized input must not reach a provider")

        def call(identity, source, token):
            calls.append(identity)
            return asyncio.run(extract_loop_plan(request_id=identity, source=source,
                config=_config().model_copy(update={"max_input_chars": 1}), provider=NoProvider()))

        try:
            await service.submit_extraction("one", expected_revision=initial.revision,
                idempotency_key="extract", extractor_factory=lambda: PreparationExtractor(
                    call, max_retries=2))
            await service.wait_for_drain()
            failed = store.get("one")
            assert failed.status == "FAILED"
            assert len(failed.attempts) == len(calls) == 1
            assert failed.attempts[-1].error_code == "AI_INPUT_TOO_LARGE"
            assert failed.attempts[-1].retryable
            assert failed.work_claim is None
        finally:
            await service.stop()

    asyncio.run(scenario())
