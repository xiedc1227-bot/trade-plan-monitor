"""Both HTTP profiles use actual lifecycle proofs and one physical read owner."""

import asyncio
from threading import Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy import event
from tests.integration.current_activation_fixture import current_sample_plan, seed_current
from tests.integration.test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _write_configuration_and_evidence,
)
from tests.integration.test_s3_startup_outcome_association import _DeadlineClock

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime import production
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.web import monitor_composition as composition_module
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def owned_reader(case):
    selected = case.composition.read_service
    return (selected._readiness_service
            if isinstance(selected, PersistentMonitorReadService) else selected)


async def start_current(case):
    composition = case.composition
    assert (await composition.start()).status.value == "RUNNING"
    assert composition._runtime.progress_snapshot() is not None
    await case.clock.park()
    await case.clock.drive(case.clock.now().replace(minute=5, second=12))
    state = composition._runtime._liveness_owner
    assert state._pipeline.runtime_status_progress_ready
    _, _, plans = state._pipeline.runtime_status_snapshot()
    assert len(plans) == 1 and plans[0].completion is not None
    return plans[0].plan_version_id


def installed(tmp_path, monkeypatch, profile, *, plan=None, sdk_factory=None, activation_at=None):
    clock = _DeadlineClock(NOW.replace(minute=4, second=0))
    if plan is None:
        raw = current_sample_plan().model_dump(mode="json")
        raw["alert_rules"] = [{
            "kind": "RISK_ALERT", "rule_id": "minute-alert",
            "condition": raw["ordinary_rules"][0]["condition"],
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        }]
        raw["ordinary_rules"] = []
        plan = UnifiedTradePlan.model_validate(raw)
    seed_current(tmp_path, clock=ControlledClock(
        NOW.replace(hour=9, minute=0, second=0) if activation_at is None else activation_at),
                 plan=plan)
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    try:
        with create_session_factory(engine).begin() as session:
            session.add(RuntimeLiveness(id=1, schema_version=1, revision=0,
                last_alive_at=NOW.replace(hour=9, minute=0, second=0).isoformat()))
    finally:
        engine.dispose()
    config = _write_configuration_and_evidence(tmp_path, observed_at=clock.now(),
                                              include_index=False)
    if sdk_factory is None:
        sdk = OfflineSDK(clock, (plan.symbol,))
    else:
        sdk = sdk_factory(clock, (plan.symbol,))
    make_controller = composition_module.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return make_controller(clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
                               require_repository_binding=require_repository_binding)

    def offline(*args, **kwargs):
        pytest.fail("profile ownership tests must stay offline")

    monkeypatch.setattr(requests.Session, "request", offline)
    monkeypatch.setattr(httpx.Client, "send", offline)
    monkeypatch.setattr(httpx.AsyncClient, "send", offline)
    monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
    monkeypatch.setattr(composition_module, "SystemClock", lambda: clock)
    monkeypatch.setattr(composition_module, "create_live_tushare_request_controller",
                        controller_factory)
    composition = composition_module.create_monitor_composition(
        config_path=config, database_path=tmp_path / "monitor.sqlite3",
        monitor_contract_version=profile, progress_monotonic=lambda: clock.now().timestamp())
    return SimpleNamespace(composition=composition, clock=clock, sdk=sdk, plan=plan)


@pytest.mark.parametrize("profile", [1, 2])
def test_real_composition_supplies_current_readiness_in_both_profiles(
    tmp_path, monkeypatch, profile,
):
    case = installed(tmp_path, monkeypatch, profile)
    composition = case.composition

    async def scenario():
        try:
            async with asyncio.timeout(30):
                version = await start_current(case)
                state = composition._runtime._liveness_owner
                pipeline = state._pipeline
                assert pipeline._status_progress_owner is composition._runtime
                bound = state.notification_service_snapshot(
                    runtime_generation=composition._runtime.runtime_generation,
                    configuration_revision=pipeline.runtime_status_snapshot()[1],
                    plans=pipeline.runtime_status_snapshot()[2])
                assert bound is not None
                calls = tuple(case.sdk.calls)
                result = await composition.read_service.get_plan_readiness(
                    version_id=version)
                assert (result.snapshot.context.runtime_generation
                        == composition._runtime.runtime_generation)
                assert result.rules[0].state == "CONDITION_FALSE"
                assert result.summary == "READY_FOR_MONITORING"
                assert result.authority_granted is False
                assert composition.read_service.outstanding_work == 0
                assert tuple(case.sdk.calls) == calls
                assert owned_reader(case)._read_owner._maximum == 8
                assert owned_reader(case)._read_owner._wait_seconds == 15
                assert state._notification_service is bound
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_cancelled_observers_fill_one_lease_and_shutdown_drains_before_disposal(
    tmp_path, monkeypatch, profile,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = installed(tmp_path, monkeypatch, profile)
    composition, selected = case.composition, case.composition.read_service
    delegate = owned_reader(case)
    entered, release, lock = Event(), Event(), Lock()
    physical = []
    disposed = []
    original = projection.read_plan_readiness
    original_stop = selected.stop

    def held(*args):
        with lock:
            physical.append(True)
            if len(physical) == 8:
                entered.set()
        assert release.wait(10)
        assert not composition._runtime.business_commit_admission_open
        return original(*args)

    async def short_stop():
        await original_stop(timeout=0.01)

    async def scenario():
        tasks = []
        try:
            version = await start_current(case)
            engine = composition._runtime._liveness_owner._engine
            event.listen(engine, "engine_disposed", lambda _engine: disposed.append(
                selected.outstanding_work))
            monkeypatch.setattr(projection, "read_plan_readiness", held)
            tasks = [asyncio.create_task(selected.get_plan_readiness(version_id=version))
                     for _ in range(8)]
            await until(entered.is_set)
            assert selected.outstanding_work == delegate.outstanding_work == 8
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id=version)
            for task in tasks:
                task.cancel()
            assert all(isinstance(value, asyncio.CancelledError)
                       for value in await asyncio.gather(*tasks, return_exceptions=True))
            assert selected.outstanding_work == 8
            monkeypatch.setattr(selected, "stop", short_stop)
            with pytest.raises(TimeoutError):
                await composition.stop()
            assert not composition._stopped and not disposed
            assert not composition._runtime.business_commit_admission_open
            assert delegate._read_owner._closing
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id=version)
            release.set()
            await delegate._read_owner.drain(timeout=3)
            monkeypatch.setattr(selected, "stop", original_stop)
            await composition.stop()
            assert composition._stopped and selected.outstanding_work == 0
            assert disposed and set(disposed) == {0}
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id=version)
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            monkeypatch.setattr(selected, "stop", original_stop)
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_storage_pause_survives_timeout_until_real_cleanup(
    tmp_path, monkeypatch, profile,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = installed(tmp_path, monkeypatch, profile)
    composition, selected = case.composition, case.composition.read_service
    delegate = owned_reader(case)
    entered, release, disposed = Event(), Event(), []
    original, suspend = projection.read_plan_readiness, selected.suspend_for_storage

    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    async def short_suspend(owner):
        await suspend(owner, timeout=0.01)

    async def scenario():
        task = None
        try:
            version = await start_current(case)
            runtime = composition._runtime
            event.listen(runtime._liveness_owner._engine, "engine_disposed",
                         lambda _engine: disposed.append(selected.outstanding_work))
            monkeypatch.setattr(projection, "read_plan_readiness", held)
            monkeypatch.setattr(selected, "suspend_for_storage", short_suspend)
            task = asyncio.create_task(selected.get_plan_readiness(version_id=version))
            await until(entered.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(TimeoutError):
                await runtime._checkpoint_wal()
            assert selected.outstanding_work == 1 and not disposed
            assert not delegate._read_owner._closing
            assert runtime.runtime_generation in delegate._read_owner._storage_pauses
            selected.resume_after_storage(uuid4())
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id=version)
            release.set()
            await delegate._read_owner.drain(timeout=3)
            monkeypatch.setattr(projection, "read_plan_readiness", original)
            monkeypatch.setattr(selected, "suspend_for_storage", suspend)
            await runtime._checkpoint_wal()
            assert runtime.runtime_generation in delegate._read_owner._storage_pauses
            await runtime._close_database()
            assert disposed and set(disposed) == {0}
            assert not delegate._read_owner._storage_pauses
            unavailable = await selected.get_plan_readiness(version_id=version)
            assert unavailable.summary == "UNKNOWN"
            assert unavailable.fresh_until is None
            assert selected.outstanding_work == 0 and not delegate._read_owner._closing
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            monkeypatch.setattr(selected, "suspend_for_storage", suspend)
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_real_generation_replacement_never_borrows_old_current_proof(
    tmp_path, monkeypatch, profile,
):
    case = installed(tmp_path, monkeypatch, profile)
    composition, selected = case.composition, case.composition.read_service
    delegate = owned_reader(case)

    async def scenario():
        cleaned, replace = asyncio.Event(), asyncio.Event()
        original_owner = composition._runtime
        lease = delegate._read_owner

        async def restart_sleep(_delay):
            assert original_owner._cleanup_complete
            cleaned.set()
            await replace.wait()

        composition._restart_sleep = restart_sleep
        try:
            version = await start_current(case)
            original = await selected.get_plan_readiness(version_id=version)
            assert original.summary == "READY_FOR_MONITORING"
            original_owner._heartbeat_task.cancel()  # Actual owned-task failure, not forged health.
            await asyncio.wait_for(cleaned.wait(), 5)
            stopped = await selected.get_plan_readiness(version_id=version)
            assert stopped.summary == "UNKNOWN" and stopped.fresh_until is None
            replace.set()
            await until(lambda: composition._runtime is not original_owner)
            replacement = composition._runtime
            assert replacement.runtime_generation != original_owner.runtime_generation
            await case.clock.park()
            changed = await selected.get_plan_readiness(version_id=version)
            assert changed.snapshot.context.runtime_generation == replacement.runtime_generation
            assert not any(axis.state == "PASS" and axis.observation is not None
                           and axis.observation.context.runtime_generation
                           == original_owner.runtime_generation for axis in changed.axes)
            await case.clock.drive(case.clock.now().replace(minute=10, second=12))
            current = await selected.get_plan_readiness(version_id=version)
            assert current.summary == "READY_FOR_MONITORING"
            assert current.snapshot.context.runtime_generation == replacement.runtime_generation
            assert delegate._read_owner is lease
            await selected.suspend_for_storage(replacement.runtime_generation)
            await original_owner.stop()
            selected.resume_after_storage(original_owner.runtime_generation)
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id=version)
            selected.resume_after_storage(replacement.runtime_generation)
            restored = await selected.get_plan_readiness(version_id=version)
            assert restored.summary == "READY_FOR_MONITORING"
        finally:
            replace.set()
            await composition.stop()

    asyncio.run(scenario())


def test_default_profile_keeps_legacy_projection_and_stream_shapes(tmp_path, monkeypatch):
    from trade_plan_monitor.web.websocket import CommittedMonitorEventStream

    case = installed(tmp_path, monkeypatch, 1)
    composition, selected = case.composition, case.composition.read_service
    baseline = PersistentMonitorReadService(selected._unit_of_work_factory,
        selected._health_provider, clock=case.clock.now)

    async def scenario():
        try:
            await start_current(case)
            assert isinstance(composition.websocket_service, CommittedMonitorEventStream)
            assert not hasattr(selected, "_read_owner")
            for name, args in (("get_dashboard", {}), ("list_symbols", {"offset": 0, "limit": 10}),
                               ("get_symbol", {"symbol": case.plan.symbol}), ("get_health", {}),
                               ("get_symbol_health", {"symbol": case.plan.symbol})):
                expected = await getattr(baseline, name)(**args)
                actual = await getattr(selected, name)(**args)
                assert actual.model_dump_json() == expected.model_dump_json(), name
            selected.begin_shutdown()
            with pytest.raises(ApiError):
                await selected.get_plan_readiness(version_id="unavailable")
            # Scope: old v1 projections retain their direct thread path, not the new lease.
            assert (await selected.get_health()).model_dump_json() == (
                await baseline.get_health()).model_dump_json()
        finally:
            await composition.stop()

    asyncio.run(scenario())
