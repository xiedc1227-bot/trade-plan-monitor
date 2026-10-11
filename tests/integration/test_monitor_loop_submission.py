"""One prepared submission binds its original cutoff under the existing reservation."""

import asyncio
import sqlite3
from datetime import timedelta
from threading import Event, current_thread, get_ident

import pytest
from pydantic import ValidationError
from tests.integration.test_backtest_run_api import _client
from tests.integration.test_monitor_loop_input_store import frozen_case, scheduled_frozen_case
from tests.unit.test_monitor_loop_schedule import at

import trade_plan_monitor.backtest.composition as composition_module
from trade_plan_monitor.backtest.composition import _ProductionBacktestService
from trade_plan_monitor.backtest.dataset_service import BacktestDatasetService
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.pagination import HmacCursorSigner
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.result_service import BacktestResultService
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.backtest_schemas import (
    BacktestDatasetVerificationCommand,
    PreparedBacktestRunCommand,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext


class Clock:
    def __init__(self):
        self.value = at(24, 10, 0, 12)

    def __call__(self):
        return self.value


class Coordinator:
    def __init__(self):
        self.authorized = []

    def raise_if_failed(self):
        pass

    def authorize_new_job(self, identity):
        self.authorized.append(identity)


def services(tmp_path, monkeypatch, *, scheduled=False):
    day = 20 if scheduled else 24
    monkeypatch.setattr("tests.integration.test_plan_preparation_review.NOW", at(day, 10))
    if scheduled:
        monkeypatch.setattr("tests.integration.test_plan_preparation_store.NOW", at(day, 10))
    fixture = scheduled_frozen_case if scheduled else frozen_case
    preparation, market, prepared, _, _ = fixture(tmp_path)
    clock = Clock()
    clock.value = at(day, 10, 0, 12)
    repository = BacktestJobRepository(tmp_path / "submission.sqlite3", clock=clock)
    results = BacktestResultStore(repository.database_path)
    preparations = PreparationService(preparation, repository)
    calls = []

    async def read_prepared(identity):
        calls.append(identity)
        return await preparations.get_frozen(identity)

    coordinator = Coordinator()
    signer = HmacCursorSigner(b"x" * 32)
    service = _ProductionBacktestService(
        plan_snapshot_reader=None,
        market_store=market,
        repository=repository,
        result_store=results,
        dataset_service=BacktestDatasetService(store=market, cursor_signer=signer),
        result_service=BacktestResultService(store=results, cursor_signer=signer),
        coordinator=coordinator,
        result_cursor_signer=signer,
        job_cursor_signer=BacktestApiCursorSigner(b"x" * 32),
        prepared_plan_reader=read_prepared,
    )
    return service, preparations, prepared, market, results, clock, calls, coordinator


def payload(prepared, **changes):
    value = {
        "preparationId": prepared.preparation_id,
        "manifestHash": prepared.manifest_hash,
        "response": {"mode": "FOLLOW_REMINDERS", "responseDelaySeconds": 0},
        "costs": {
            "commissionRate": "0.0003",
            "minimumCommissionFen": 500,
            "stampDutyRate": "0.0005",
            "transferFeeRate": "0.00001",
            "buySlippageFen": 1,
            "sellSlippageFen": 1,
        },
    }
    return value | changes


def context(key="one"):
    return MutationContext(idempotency_key=key, request_id="a" * 32)


def test_scheduled_submission_keeps_original_cutoff_complete_chain_and_same_job(
    tmp_path, monkeypatch
):
    service, preparations, prepared, _, results, clock, calls, coordinator = services(
        tmp_path,
        monkeypatch,
        scheduled=True,
    )
    command = PreparedBacktestRunCommand.model_validate(payload(prepared))

    async def run():
        try:
            first = await service.submit_run(command=command, context=context("scheduled"))
            reference = results.get_loop_input_reference(first.receipt.run_id)
            stored = results.get_loop_input(reference)
            assert stored.schema_version == "monitor-loop-stored-input-v2"
            assert stored.prepared == prepared
            assert stored.run_input.boundary.started_at == at(19)
            assert stored.run_input.boundary.evidence_cutoff == at(20, 10, 0, 12)
            assert stored.run_input.boundary.origin == "DEFAULTED"
            assert len(stored.dataset.plan_bindings) == len(stored.day_hashes) == 2
            original = preparations._store.get(prepared.preparation_id)
            preparations._store.edit_collection(
                original.preparation_id,
                source=original.items[1].source.model_copy(
                    update={"text": "Synthetic edit after submission."},
                ),
                expected_revision=original.revision,
                idempotency_key="edited-after-submission",
            )
            clock.value = at(21, 0, 5)
            replay = await service.submit_run(command=command, context=context("scheduled"))
            assert replay == first
            assert calls == [prepared.preparation_id]
            assert coordinator.authorized == [first.receipt.job_id]
            assert results.get_loop_input(reference) == stored
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=command, context=context("another"))
            assert error.value.code == ApiErrorCode.CONFLICT
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())


def test_scheduled_source_edit_rejects_stale_manifest_before_market_access(tmp_path, monkeypatch):
    service, preparations, prepared, _, results, _, _, _ = services(
        tmp_path,
        monkeypatch,
        scheduled=True,
    )
    record = preparations._store.get(prepared.preparation_id)
    preparations._store.edit_collection(
        record.preparation_id,
        source=record.items[1].source.model_copy(update={"text": "Synthetic revised source."}),
        expected_revision=record.revision,
        idempotency_key="edit",
    )

    def unexpected(*args, **kwargs):
        pytest.fail("stale collection review must fail before copying market evidence")

    monkeypatch.setattr(results, "record_loop_input", unexpected)

    async def run():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(
                    command=PreparedBacktestRunCommand.model_validate(payload(prepared)),
                    context=context(),
                )
            assert error.value.code == ApiErrorCode.CONFLICT
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())


def test_default_cutoff_is_original_reservation_and_midnight_replay_does_no_lookup(
    tmp_path, monkeypatch
):
    service, preparation, prepared, market, results, clock, calls, coordinator = services(
        tmp_path, monkeypatch
    )
    command = PreparedBacktestRunCommand.model_validate(payload(prepared))

    async def run():
        try:
            first = await service.submit_run(command=command, context=context())
            original = results.get_loop_input(
                results.get_loop_input_reference(first.receipt.run_id)
            )
            assert original.run_input.boundary.evidence_cutoff == at(24, 10, 0, 12)
            assert original.run_input.boundary.origin == "DEFAULTED"
            clock.value = at(25, 0, 5)
            second = await service.submit_run(command=command, context=context())
            assert first == second and calls == ["one"]
            assert coordinator.authorized == [first.receipt.job_id]
        finally:
            await service.stop_metadata()
            await preparation.stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"manifestHash": "f" * 64}, ApiErrorCode.CONFLICT),
        ({"preparationId": "missing"}, ApiErrorCode.NOT_FOUND),
        ({"endDate": "2026-08-23"}, ApiErrorCode.VALIDATION_ERROR),
        ({"endDate": "2026-08-25"}, ApiErrorCode.VALIDATION_ERROR),
    ],
)
def test_rejected_submission_releases_its_reservation_without_job(
    tmp_path, monkeypatch, changes, code
):
    service, preparation, prepared, _, results, _, _, _ = services(tmp_path, monkeypatch)
    command = PreparedBacktestRunCommand.model_validate(payload(prepared, **changes))

    async def run():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(command=command, context=context())
            assert error.value.code == code
            with sqlite3.connect(results.database_path) as connection:
                assert connection.execute("SELECT count(*) FROM backtest_job").fetchone()[0] == 0
                assert (
                    connection.execute("SELECT count(*) FROM backtest_job_idempotency").fetchone()[
                        0
                    ]
                    == 0
                )
        finally:
            await service.stop_metadata()
            await preparation.stop()

    asyncio.run(run())


def test_freezing_and_copying_are_owned_and_missing_interval_is_visible(tmp_path, monkeypatch):
    service, preparation, prepared, market, _, _, _, _ = services(tmp_path, monkeypatch)
    threads = []
    original = market.freeze_loop_dataset

    def freeze(value, **controls):
        threads.append(current_thread().name)
        return original(value, **controls)

    monkeypatch.setattr(market, "freeze_loop_dataset", freeze)
    with sqlite3.connect(market.database_path) as connection:
        connection.execute("DELETE FROM market_minute_artifact WHERE bar_end LIKE '%09:32:%'")

    async def run():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(
                    command=PreparedBacktestRunCommand.model_validate(payload(prepared)),
                    context=context(),
                )
            assert error.value.code == ApiErrorCode.CONFLICT
            assert any(detail.code == "LOOP_MINUTE_NOT_AVAILABLE" for detail in error.value.details)
            assert threads and all("backtest-metadata" in name for name in threads)
        finally:
            await service.stop_metadata()
            await preparation.stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"planVersionId": "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"},
        {"preparationId": "../unsafe"},
        {"manifestHash": "bad"},
        {"endDate": "tomorrow"},
        {"response": {"mode": "RECORDED_ACTIONS", "responseDelaySeconds": 0}},
        {"initialCashFen": 10},
    ],
)
def test_prepared_command_rejects_mixed_or_unbound_inputs(tmp_path, monkeypatch, changes):
    _, _, prepared, _, _, _, _, _ = services(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        PreparedBacktestRunCommand.model_validate(payload(prepared, **changes))


def test_mounted_http_accepts_prepared_variant_and_keeps_job_headers(tmp_path, monkeypatch):
    service, preparations, prepared, _, _, _, _, _ = services(tmp_path, monkeypatch)
    client = _client(operation_service=service)
    try:
        response = client.post(
            "/api/v1/backtest-runs", json=payload(prepared), headers={"Idempotency-Key": "http-one"}
        )
        assert response.status_code == 202
        assert response.headers["Location"].endswith(response.json()["jobId"])
        assert response.headers["Retry-After"] == "2"
        assert (
            client.post(
                "/api/v1/backtest-runs",
                json=payload(prepared),
                headers={"Idempotency-Key": "http-one"},
            ).json()
            == response.json()
        )
    finally:
        asyncio.run(service.stop_metadata())
        asyncio.run(preparations.stop())


async def until_started(event):
    async def wait():
        while not event.is_set():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), timeout=5)


def test_reservation_renews_while_owned_freeze_is_busy_without_changing_cutoff(
    tmp_path, monkeypatch
):
    service, preparations, prepared, market, results, clock, _, _ = services(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    freeze = market.freeze_loop_dataset
    renew = service._repository.renew_run_submission
    renewals, copy_threads = [], []

    def blocked(value, **controls):
        copy_threads.append(get_ident())
        entered.set()
        assert release.wait(5)
        return freeze(value, **controls)

    def renewal(reservation):
        timestamp = clock.value
        result = renew(reservation)
        renewals.append((timestamp, get_ident(), result))
        return result

    monkeypatch.setattr(market, "freeze_loop_dataset", blocked)
    monkeypatch.setattr(service._repository, "renew_run_submission", renewal)
    monkeypatch.setattr(composition_module, "_RUN_RESERVATION_HEARTBEAT_SECONDS", 0.005)
    command = PreparedBacktestRunCommand.model_validate(payload(prepared))

    async def run():
        task = asyncio.create_task(service.submit_run(command=command, context=context()))
        try:
            await until_started(entered)
            for seconds in (20, 40, 60):
                clock.value = at(24, 10, 0, 12) + timedelta(seconds=seconds)

                async def renewed():
                    while not any(at_time == clock.value and ok for at_time, _, ok in renewals):
                        await asyncio.sleep(0.001)

                await asyncio.wait_for(renewed(), timeout=2)
            release.set()
            receipt = (await task).receipt
            stored = results.get_loop_input(results.get_loop_input_reference(receipt.run_id))
            assert stored.run_input.boundary.evidence_cutoff == at(24, 10, 0, 12)
            assert all(name not in copy_threads for _, name, _ in renewals)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())


def test_queued_run_blocks_new_intent_and_verification_but_replays_original(tmp_path, monkeypatch):
    from tests.integration.test_backtest_data_api import _scope_payload

    service, preparations, prepared, _, _, _, calls, _ = services(tmp_path, monkeypatch)
    command = PreparedBacktestRunCommand.model_validate(payload(prepared))

    async def run():
        try:
            first = await service.submit_run(command=command, context=context())
            changed = command.model_copy(update={"response": {"mode": "OBSERVE_ONLY"}})
            for key in ("one", "another"):
                with pytest.raises(ApiError) as error:
                    await service.submit_run(command=changed, context=context(key))
                assert error.value.code == ApiErrorCode.CONFLICT
            with pytest.raises(ApiError) as error:
                await service.submit_dataset_verification(
                    command=BacktestDatasetVerificationCommand.model_validate(
                        {"scope": _scope_payload()}
                    ),
                    context=context("verify"),
                )
            assert error.value.code == ApiErrorCode.CONFLICT
            assert await service.submit_run(command=command, context=context()) == first
            assert calls == ["one"]
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())


def test_source_edit_invalidates_authority_before_any_market_freeze(tmp_path, monkeypatch):
    service, preparations, prepared, market, _, _, _, _ = services(tmp_path, monkeypatch)
    record = preparations._store.get("one")
    preparations._store.edit_source(
        "one",
        source=record.source.model_copy(update={"text": record.source.text + "变更"}),
        expected_revision=record.revision,
        idempotency_key="edit",
    )

    def unexpected(*args, **kwargs):
        pytest.fail("stale review must fail before market access")

    monkeypatch.setattr(market, "freeze_loop_dataset", unexpected)

    async def run():
        try:
            with pytest.raises(ApiError) as error:
                await service.submit_run(
                    command=PreparedBacktestRunCommand.model_validate(payload(prepared)),
                    context=context(),
                )
            assert error.value.code == ApiErrorCode.CONFLICT
        finally:
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())


def test_unavailable_preparation_returns_scoped_retry_and_releases_claim(tmp_path, monkeypatch):
    service, preparations, prepared, _, _, _, _, _ = services(tmp_path, monkeypatch)

    async def unavailable(identity):
        raise BacktestServiceUnavailable()

    service._prepared_plan_reader = unavailable
    client = _client(operation_service=service)
    try:
        response = client.post(
            "/api/v1/backtest-runs",
            json=payload(prepared),
            headers={"Idempotency-Key": "unavailable"},
        )
        assert response.status_code == 503 and response.headers["Retry-After"] == "1"
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        intent = composition_module.canonical_json(
            PreparedBacktestRunCommand.model_validate(payload(prepared)).canonical_payload()
        )
        assert service._repository.get_run_submission_reservation(intent, "unavailable") is None
    finally:
        asyncio.run(service.stop_metadata())
        asyncio.run(preparations.stop())


@pytest.mark.parametrize(
    "field,value",
    [
        ("commissionRate", "1.1"),
        ("commissionRate", "-0.1"),
        ("minimumCommissionFen", True),
        ("buySlippageFen", -1),
        ("sellSlippageFen", 9007199254740992),
        ("transferFeeRate", 0.1),
    ],
)
def test_prepared_costs_keep_exact_rates_and_safe_whole_fen(field, value):
    from trade_plan_monitor.web.backtest_schemas import BacktestLoopCostsInput

    costs = {
        "commissionRate": "0",
        "minimumCommissionFen": 0,
        "stampDutyRate": "0",
        "transferFeeRate": "0",
        "buySlippageFen": 0,
        "sellSlippageFen": 0,
    }
    with pytest.raises(ValidationError):
        BacktestLoopCostsInput.model_validate(costs | {field: value})


def test_production_reader_uses_owned_preparation_and_defers_worker(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.integration.test_plan_preparation_review.NOW", at(24, 10))
    preparation, market, prepared, _, _ = frozen_case(tmp_path)
    monkeypatch.setattr(composition_module, "_load_or_create_cursor_key", lambda path: b"x" * 32)
    composition = composition_module.create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml",
        plan_snapshot_reader=None,
        market_database=market.database_path,
        preparation_database=preparation.database_path,
        results_database=tmp_path / "production.sqlite3",
        cursor_key_path=tmp_path / "absent.key",
    )()
    assert composition._coordinator._instance is None
    assert composition.outstanding_work == 0
    assert not composition.operation_service._result_store.loop_input_store.root.exists()

    async def run():
        try:
            outcome = await composition.operation_service.submit_run(
                command=PreparedBacktestRunCommand.model_validate(
                    payload(prepared, endDate="2026-08-24")
                ),
                context=context(),
            )
            assert composition.authorized_job_ids == frozenset({outcome.receipt.job_id})
            assert composition._coordinator._instance is None
            assert composition.outstanding_work == 0
        finally:
            await composition.stop()

    asyncio.run(run())


def test_cancellation_keeps_global_reservation_until_the_physical_copy_drains(
    tmp_path, monkeypatch
):
    service, preparations, prepared, market, results, _, _, _ = services(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    freeze = market.freeze_loop_dataset

    def blocked(value, **controls):
        entered.set()
        assert release.wait(5)
        return freeze(value, **controls)

    monkeypatch.setattr(market, "freeze_loop_dataset", blocked)
    command = PreparedBacktestRunCommand.model_validate(payload(prepared))
    intent = composition_module.canonical_json(command.canonical_payload())

    async def run():
        task = asyncio.create_task(service.submit_run(command=command, context=context()))
        try:
            await until_started(entered)
            task.cancel()
            await asyncio.sleep(0.03)
            assert not task.done()
            assert service._repository.get_run_submission_reservation(intent, "one") is not None
            with sqlite3.connect(results.database_path) as connection:
                assert connection.execute("SELECT count(*) FROM backtest_job").fetchone()[0] == 0
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert service.outstanding_work == 0
            assert service._repository.get_run_submission_reservation(intent, "one") is None
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.stop_metadata()
            await preparations.stop()

    asyncio.run(run())
