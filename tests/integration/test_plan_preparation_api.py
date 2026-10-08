"""ML-T12 owns preparation resources on demand and serves one bounded HTTP workflow."""

import asyncio

import pytest
from tests.integration.test_backtest_single_task import request

from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable


def command():
    return SinglePlanPreparationInput(
        preparation_id="one",
        sources=(PreparationSource(source_id="source-one", text="One supplied original source."),),
    )


def forbidden_ai(*args):
    pytest.fail("Metadata operations must not call AI")


@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
def test_create_obeys_global_admission_without_a_preparation_record(tmp_path, kind):
    store = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
    jobs.submit(request(kind), "existing", request_id="1" * 32)

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            with pytest.raises(JobAdmissionError) as busy:
                await service.create(command(), idempotency_key="create")
            assert busy.value.code == "BACKTEST_BUSY"
            assert store.get("one") is None
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_create_receipt_replays_after_source_edit_while_global_slot_is_busy(tmp_path):
    store = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            original = await service.create(command(), idempotency_key="create")
            changed = await service.edit_source(
                "one",
                source=original.source.model_copy(update={"text": "Explicit source correction."}),
                expected_revision=original.revision,
                idempotency_key="edit",
            )
            jobs.submit(request("VERIFY"), "existing")
            assert await service.create(command(), idempotency_key="create") == original
            assert store.get("one") == changed
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_preparation_store_is_owned_only_after_explicit_capability_use(tmp_path):
    preparation_path = tmp_path / "preparation.sqlite3"
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml",
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
        preparation_database=preparation_path,
    )
    assert not preparation_path.exists()
    composition = factory()
    assert not preparation_path.exists()

    async def scenario():
        try:
            service = await composition.ensure_preparations()
            assert preparation_path.exists()
            initial = await service.create(command(), idempotency_key="create")
            with pytest.raises(BacktestServiceUnavailable):
                await service.submit_extraction(
                    "one", expected_revision=initial.revision, idempotency_key="extract"
                )
            assert await service.get("one") == initial
            assert not composition._started and composition.authorized_job_ids == frozenset()
        finally:
            await composition.stop()
        assert service.outstanding_work == 0 and composition.outstanding_work == 0

    asyncio.run(scenario())


def test_unused_preparation_capability_is_not_acquired_for_shutdown(tmp_path):
    preparation_path = tmp_path / "preparation.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml",
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
        preparation_database=preparation_path,
    )()
    asyncio.run(composition.stop())
    assert not preparation_path.exists() and composition.outstanding_work == 0
