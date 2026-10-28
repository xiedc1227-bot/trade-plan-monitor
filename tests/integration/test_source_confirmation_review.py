"""Recorded failures stay blocked; explicitly synthetic proofs test successful review."""

import asyncio
from datetime import date
from uuid import UUID

import pytest
from tests.integration.source_confirmation_current_fixture import (
    preparation_checkpoint,
    read_only_preparation,
    recorded_case,
    synthetic_current_case,
)
from tests.integration.test_plan_preparation_review import collection_review_command
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.backtest.jobs import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_current_assurance import (
    read_current_assurance,
    require_current_preparation,
    require_current_reviewed_preparation,
)
from trade_plan_monitor.backtest.preparation_models import (
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_review_assurance_store import review_assurance
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor


@pytest.mark.parametrize("number", [1, 2, 3, 4])
@pytest.mark.parametrize("known_cash", [False, True])
@pytest.mark.parametrize("round_name", ["", "live-check-"])
def test_account_choice_does_not_hide_missing_policy_or_grant_automatic_approval(
    tmp_path,
    number,
    known_cash,
    round_name,
):
    """Original recorded bytes do not acquire current authority through cash review."""
    source, raw = recorded_case(number, round_name)

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
            checkpoint = preparation_checkpoint(store)
            with read_only_preparation(store) as connection:
                proofs = read_current_assurance(connection, record)
                assert len(proofs) == 1 and not proofs[0].coverage_complete
                assert not proofs[0].current_automatic_fidelity_verified
                source_proof = proofs[0].source_assessment
                assert any(
                    issue.code == "SOURCE_CONTEXT_UNVERIFIED" for issue in source_proof.issues
                )
                if number in {3, 4}:
                    assert any(
                        issue.code == "SOURCE_NORMALIZATION_LOSS" for issue in source_proof.issues
                    )
                evidence = store.input_evidence(
                    record.preparation_id, record.items[0].attempts[-1].attempt_id
                )
                assert evidence.inputs.normalization is not None
                assert evidence.candidate_json == record.items[0].candidate.payload_json
                assert (
                    review_assurance(connection, record.preparation_id, record.review_revision + 1)
                    is None
                )
                with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
                    require_current_preparation(connection, record)
            with pytest.raises(PreparationConflictError):
                store.review_and_freeze(
                    record.preparation_id, command=command, idempotency_key="test-review"
                )
            assert store.get(record.preparation_id) == record
            assert preparation_checkpoint(store) == checkpoint
            assert recorded_case(number, round_name) == (source, raw)
        finally:
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("number", [3, 4], ids=["synthetic-reuse-extraction", "synthetic-reuse"])
@pytest.mark.parametrize("known_cash", [False, True])
def test_synthetic_complete_source_preserves_account_review_and_predecessor_reuse(
    tmp_path,
    number,
    known_cash,
):
    """Preserve the original positive assertions using a full, synthetic current proof."""
    source, _ = synthetic_current_case(UUID(int=101))
    calls = []

    def call(identity, source, token, context=None):
        calls.append((source.source_id, context))
        if context is not None:
            return None  # Admission only; no AI successor is fabricated.
        owned_source, result = synthetic_current_case(identity)
        assert owned_source == source
        return result

    async def scenario():
        store = PreparationStore(tmp_path / "synthetic-current-preparation.sqlite3")
        service = PreparationService(
            store,
            BacktestJobRepository(tmp_path / "synthetic-jobs.sqlite3"),
            PreparationExtractor(call),
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
            with read_only_preparation(store) as connection:
                proofs = require_current_preparation(connection, record)
                assert len(proofs) == 1 and proofs[0].coverage_complete
            command = collection_review_command(record)
            if not known_cash:
                command = command.model_copy(update={"account": None})
            reviewed = store.review_and_freeze(
                record.preparation_id, command=command, idempotency_key="test-review"
            )
            frozen = frozen_preparation(reviewed)
            assert frozen.account.cash.kind == ("KNOWN" if known_cash else "POSITION_LIMIT_ONLY")
            assert frozen.account.inventory_known and frozen.account.lots == ()
            assert frozen.account.snapshot_at == source.execution_available_at
            assert frozen.opening_evidence.snapshot_at is None
            with read_only_preparation(store) as connection:
                assert require_current_reviewed_preparation(connection, reviewed)
                receipt = review_assurance(
                    connection, record.preparation_id, reviewed.review_revision
                )
                assert receipt.frozen_manifest_hash == frozen.manifest_hash
            # These assertions test synthetic account/reuse mechanics, not recorded-AI accuracy.
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
                    linked.preparation_id,
                    expected_revision=linked.revision,
                    idempotency_key="test-next-extract",
                    collection_mode=True,
                )
                await service.wait_for_drain()
                assert len(calls) == 2
                assert calls[-1][0] == "test-only-next-source"
                assert calls[-1][1].snapshot.position.max_qty == 300
                assert (await service.get(linked.preparation_id)).items[0] == reviewed.items[0]
        finally:
            await service.stop()

    asyncio.run(scenario())
