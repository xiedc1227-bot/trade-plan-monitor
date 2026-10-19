"""Server-derived automatic preparation never mutates retained research inputs."""

import asyncio

import pytest
from tests.integration.test_monitor_loop_submission import services
from tests.unit.test_monitor_loop_schedule import at


@pytest.mark.parametrize("scheduled", [False, True])
def test_data_check_is_local_bound_and_accepts_cached_frozen_evidence(
    tmp_path, monkeypatch, scheduled,
):
    service, preparations, prepared, _, results, clock, _, coordinator = services(
        tmp_path, monkeypatch, scheduled=scheduled,
    )

    async def run():
        try:
            check = await service.check_prepared_data(
                preparation_id=prepared.preparation_id, manifest_hash=prepared.manifest_hash,
                end_date=clock.value.date(),
            )
            assert check.ready
            assert check.blockers == ()
            assert check.preparation_id == prepared.preparation_id
            assert check.manifest_hash == prepared.manifest_hash
            assert not coordinator.authorized
            assert not list(results.loop_input_store.root.glob("bundle-*.json"))
            from trade_plan_monitor.web.errors import ApiError
            with pytest.raises(ApiError):
                await service.check_prepared_data(
                    preparation_id=prepared.preparation_id, manifest_hash="0" * 64,
                    end_date=clock.value.date(),
                )
        finally:
            await service.stop_metadata()
            await preparations.stop()
    # The data check uses the same server clock as final submission.
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", clock)
    asyncio.run(run())


def test_verified_result_owned_market_copy_is_reused_without_rewriting_old_input(
    tmp_path, monkeypatch,
):
    from tests.integration.test_monitor_loop_submission import context, payload

    from trade_plan_monitor.backtest.market_store import BacktestMarketStore
    from trade_plan_monitor.web.backtest_schemas import ScheduledPreparedBacktestRunCommand

    service, preparations, prepared, _, results, clock, _, _ = services(
        tmp_path, monkeypatch, scheduled=True,
    )
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", clock)
    command = ScheduledPreparedBacktestRunCommand.model_validate(
        payload(prepared) | {"schemaVersion": "prepared-loop-plan-v2"},
    )

    async def run():
        try:
            original = await service.submit_run(command=command, context=context("cached-original"))
            reference = results.get_loop_input_reference(original.receipt.run_id)
            stored = results.get_loop_input(reference)
            raw_bundle = results.loop_input_store.bundle_path(reference).read_bytes()
            service._market_store = BacktestMarketStore(tmp_path / "no-mutable-cache.sqlite3")
            check = await service.check_prepared_data(
                preparation_id=prepared.preparation_id, manifest_hash=prepared.manifest_hash,
                end_date=None,
            )
            assert check.ready and check.sync_scope is None
            from trade_plan_monitor.web.routers.backtest_jobs import BacktestJobCancellationCommand
            await service.request_cancel(
                command=BacktestJobCancellationCommand(jobId=original.receipt.job_id),
                context=context("cancel-cached-original"),
            )
            changed = command.model_copy(update={"response": command.response.model_copy(
                update={"mode": "OBSERVE_ONLY"},
            )})
            new = await service.submit_run(command=changed, context=context("cached-new"))
            copied = results.get_loop_input(results.get_loop_input_reference(new.receipt.run_id))
            assert copied.run_input.response.mode == "OBSERVE_ONLY"
            assert copied.day_hashes == stored.day_hashes
            assert results.loop_input_store.bundle_path(reference).read_bytes() == raw_bundle
            assert results.get_loop_input(reference) == stored
            from datetime import timedelta

            from trade_plan_monitor.backtest.automatic_data import prepared_dataset_request
            later = prepared_dataset_request(service._market_store, prepared,
                submitted_at=clock.value + timedelta(seconds=1), end_date=None)
            assert results.reusable_loop_market(prepared, later) is None
        finally:
            await service.stop_metadata()
            await preparations.stop()
    asyncio.run(run())


def test_data_check_http_is_no_store_and_rejects_ambiguous_or_wrong_bindings(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.integration.test_monitor_loop_production_composition import Runtime

    from trade_plan_monitor.web.app import create_app

    service, preparations, prepared, _, _, clock, _, coordinator = services(tmp_path, monkeypatch)
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", clock)
    app = create_app(backtest_read_service=service, runtime_factory=Runtime)
    query = {"preparationId": prepared.preparation_id, "manifestHash": prepared.manifest_hash,
             "endDate": str(clock.value.date())}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/v1/backtest-run-data", params=query)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["ready"] is True
        for values in (query | {"unexpected": "x"}, query | {"manifestHash": "0" * 64},
                       query | {"endDate": "2026-02-31"}):
            assert client.get("/api/v1/backtest-run-data", params=values).status_code in (409, 422)
        assert not coordinator.authorized
        client.portal.call(service.stop_metadata)
        client.portal.call(preparations.stop)


def test_missing_calendar_yields_automatic_bounded_warmup_scope(tmp_path, monkeypatch):
    service, preparations, prepared, market, _, clock, _, _ = services(tmp_path, monkeypatch)
    from trade_plan_monitor.backtest.market_store import BacktestMarketStore
    service._market_store = BacktestMarketStore(tmp_path / "empty.sqlite3")
    clock.value = at(25, 10)
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", clock)

    async def run():
        try:
            check = await service.check_prepared_data(
                preparation_id=prepared.preparation_id, manifest_hash=prepared.manifest_hash,
                end_date=at(24).date(),
            )
            assert not check.ready
            assert check.sync_scope is not None
            assert check.sync_scope.symbols == (prepared.version.snapshot.symbol,)
            assert check.sync_scope.start == check.sync_scope.warmup_start
            assert check.sync_scope.end < clock.value.date()
            assert check.sync_scope.warmup_start <= check.sync_scope.end
            assert any(value.startswith("LOOP_CALENDAR_MISSING") for value in check.blockers)
        finally:
            await service.stop_metadata()
            await preparations.stop()
    asyncio.run(run())
