"""Fresh prepared runs authenticate actual current review at final admission.

Synthetic raw inputs, registered human corrections, review receipts and offline
market data use the real preparation and submission services. No current proof,
fence, provider or user database is mocked.
"""

import asyncio
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from tests.integration.test_monitor_loop_submission import context, payload, services

from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_current_assurance import (
    require_current_reviewed_preparation,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
from trade_plan_monitor.web.backtest_schemas import (
    PreparedBacktestRunCommand,
    ScheduledPreparedBacktestRunCommand,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode


def _services(tmp_path, monkeypatch, *, scheduled=False):
    values = services(tmp_path, monkeypatch, scheduled=scheduled)
    service, preparations, prepared, *_ = values
    current_reads = []

    async def actual_preparation_service():
        current_reads.append(prepared.preparation_id)
        return preparations

    # Configure the existing server dependency, not a fake current reader/fence.
    service._preparation_service_reader = actual_preparation_service
    with closing(sqlite3.connect(preparations._store.database_path)) as connection:
        record = preparations._store._read(connection, prepared.preparation_id)
        receipt = require_current_reviewed_preparation(connection, record)
    assert receipt.proofs and all(proof.coverage_complete for proof in receipt.proofs)
    return (*values, current_reads)


def _command(prepared, *, scheduled=False):
    if scheduled:
        return ScheduledPreparedBacktestRunCommand.model_validate(
            payload(prepared) | {"schemaVersion": "prepared-loop-plan-v2"})
    return PreparedBacktestRunCommand.model_validate(payload(prepared))


def _edit(preparations, identity, *, key="edit-current-source", metadata_only=False):
    store = preparations._store
    record = store.get(identity)
    if hasattr(record, "items"):
        source = record.items[-1].source
        values = ({"authored_at": source.authored_at - timedelta(minutes=1)} if metadata_only else
                  {"text": source.text + "Changed after frozen copy."})
        return store.edit_collection(identity, expected_revision=record.revision,
            source=source.model_copy(update=values),
            idempotency_key=key)
    values = ({"authored_at": record.source.authored_at - timedelta(minutes=1)}
              if metadata_only else {"text": record.source.text + "Changed after frozen copy."})
    return store.edit_source(identity, expected_revision=record.revision,
        source=record.source.model_copy(update=values), idempotency_key=key)


def _not_admitted(results, coordinator, key, *, existing_jobs=0, authorized=()):
    with closing(sqlite3.connect(results.database_path)) as connection:
        count = connection.execute("SELECT count(*) FROM backtest_job").fetchone()[0]
        assert count == existing_jobs
        assert connection.execute("SELECT count(*) FROM backtest_job_idempotency "
            "WHERE idempotency_key=?", (key,)).fetchone()[0] == 0
    assert coordinator.authorized == list(authorized)


def _drop_current_review(preparations, identity):
    with closing(sqlite3.connect(preparations._store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_delete")
        connection.execute("DELETE FROM backtest_preparation_assurance "
                           "WHERE preparation_id=? AND kind='REVIEW'", (identity,))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_delete"])


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
@pytest.mark.parametrize("metadata_only", [False, True], ids=["source-text", "source-metadata"])
def test_actual_source_edit_after_frozen_copy_cannot_authorize_a_fresh_run(
    tmp_path, monkeypatch, scheduled, metadata_only,
):
    service, preparations, prepared, _, results, _, _, coordinator, _ = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    freeze = service._freeze_prepared_input
    copied = []

    def freeze_then_edit(*args):
        reference = freeze(*args)
        copied.append(reference)
        before = preparations._store.get(prepared.preparation_id)
        changed = _edit(preparations, prepared.preparation_id, metadata_only=metadata_only)
        if metadata_only:
            old_source = before.items[-1].source if scheduled else before.source
            new_source = changed.items[-1].source if scheduled else changed.source
            assert old_source.source_hash == new_source.source_hash
            assert old_source.binding_hash != new_source.binding_hash
        return reference

    monkeypatch.setattr(service, "_freeze_prepared_input", freeze_then_edit)

    async def scenario():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=_command(prepared, scheduled=scheduled),
                                         context=context("edited-after-copy"))
            assert error.value.code == ApiErrorCode.CONFLICT
            assert copied
            _not_admitted(results, coordinator, "edited-after-copy")
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_fresh_actual_current_review_passes_real_fence_into_final_job_admission(
    tmp_path, monkeypatch, scheduled,
):
    service, preparations, prepared, _, results, _, _, coordinator, reads = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    finalize = service._repository.finalize_run_submission
    guards = []

    def observe_finalize(*args, **kwargs):
        guard = kwargs.get("admission_guard")
        assert callable(guard)
        guards.append(guard)
        return finalize(*args, **kwargs)

    monkeypatch.setattr(service._repository, "finalize_run_submission", observe_finalize)
    authorize = coordinator.authorize_new_job
    observed_lock = []

    def observe_authorization(identity):
        # Observe the real preparation writer lock while the actual jobs writer
        # admits work; this does not replace the source fence or its verifier.
        with closing(sqlite3.connect(preparations._store.database_path, timeout=0)) as connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("BEGIN IMMEDIATE")
        observed_lock.append(identity)
        authorize(identity)

    monkeypatch.setattr(coordinator, "authorize_new_job", observe_authorization)

    async def scenario():
        try:
            outcome = await service.submit_run(command=_command(prepared, scheduled=scheduled),
                                               context=context("current-positive"))
            assert guards and reads and observed_lock == [outcome.receipt.job_id]
            assert coordinator.authorized == [outcome.receipt.job_id]
            reference = results.get_loop_input_reference(outcome.receipt.run_id)
            stored = results.get_loop_input(reference)
            assert stored.prepared == prepared
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_historical_frozen_and_data_reads_survive_missing_current_review_but_new_run_is_blocked(
    tmp_path, monkeypatch, scheduled,
):
    service, preparations, prepared, _, results, _, _, coordinator, _ = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    _drop_current_review(preparations, prepared.preparation_id)

    async def scenario():
        try:
            assert await preparations.get_frozen(prepared.preparation_id) == prepared
            data = await service.check_prepared_data(preparation_id=prepared.preparation_id,
                manifest_hash=prepared.manifest_hash,
                end_date=prepared.schedule.entries[-1].effective_trade_date)
            assert data.preparation_id == prepared.preparation_id
            assert data.manifest_hash == prepared.manifest_hash
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=_command(prepared, scheduled=scheduled),
                                         context=context("missing-current-review"))
            assert error.value.code == ApiErrorCode.CONFLICT
            _not_admitted(results, coordinator, "missing-current-review")
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_successful_same_key_replays_original_receipt_after_actual_source_edit_without_fresh_read(
    tmp_path, monkeypatch, scheduled,
):
    values = _services(tmp_path, monkeypatch, scheduled=scheduled)
    service, preparations, prepared, _, results, _, historical_reads, coordinator, reads = values
    command = _command(prepared, scheduled=scheduled)

    async def scenario():
        try:
            first = await service.submit_run(command=command, context=context("same-key"))
            assert reads
            before = (tuple(reads), tuple(historical_reads))
            reference = results.get_loop_input_reference(first.receipt.run_id)
            stored = results.get_loop_input(reference)
            _edit(preparations, prepared.preparation_id)
            replay = await service.submit_run(command=command, context=context("same-key"))
            assert replay == first and (tuple(reads), tuple(historical_reads)) == before
            assert results.get_loop_input(reference) == stored
            assert coordinator.authorized == [first.receipt.job_id]
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", ["service_reader", "current_fence"])
@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_new_run_without_actual_current_fence_capability_is_unavailable_before_market_copy(
    tmp_path, monkeypatch, scheduled, missing,
):
    service, preparations, prepared, _, results, _, _, coordinator, _ = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    if missing == "service_reader":
        service._preparation_service_reader = None
    else:
        monkeypatch.setattr(preparations, "current_run_fence", None, raising=False)
    freeze = service._freeze_prepared_input
    copied = []

    def observe_copy(*args):
        copied.append(True)
        return freeze(*args)

    monkeypatch.setattr(service, "_freeze_prepared_input", observe_copy)

    async def scenario():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=_command(prepared, scheduled=scheduled),
                                         context=context("missing-current-capability"))
            assert error.value.code == ApiErrorCode.SERVICE_UNAVAILABLE
            assert copied == []
            _not_admitted(results, coordinator, "missing-current-capability")
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_existing_active_job_cannot_give_a_new_key_authority_when_current_review_is_missing(
    tmp_path, monkeypatch, scheduled,
):
    service, preparations, prepared, _, results, _, _, coordinator, _ = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    command = _command(prepared, scheduled=scheduled)

    async def scenario():
        try:
            first = await service.submit_run(command=command, context=context("original-active"))
            _drop_current_review(preparations, prepared.preparation_id)
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=command, context=context("new-active-key"))
            assert error.value.code == ApiErrorCode.CONFLICT
            _not_admitted(results, coordinator, "new-active-key", existing_jobs=1,
                          authorized=(first.receipt.job_id,))
            replay = await service.submit_run(command=command, context=context("original-active"))
            assert replay == first
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("scheduled", [False, True], ids=["single", "scheduled"])
def test_actual_current_run_fence_binds_exact_requested_manifest(tmp_path, monkeypatch, scheduled):
    service, preparations, prepared, _, _, _, _, _, _ = _services(
        tmp_path, monkeypatch, scheduled=scheduled)
    try:
        with pytest.raises(PreparationConflictError):
            with preparations.current_run_fence(prepared.preparation_id, "0" * 64):
                pytest.fail("Another requested manifest must not acquire current run authority")
    finally:
        asyncio.run(service.stop_metadata())
        asyncio.run(preparations.stop())
