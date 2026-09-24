"""Production evidence is revalidated at each physical request boundary."""

import asyncio
from datetime import timedelta

import pytest
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.market_data.models import ProviderCapabilityStatus
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import AlertEvent, EvaluationResult, RuntimeLiveness
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


def _composition(
    tmp_path, monkeypatch, *, invalidate_during_request=None, fail_realtime_once=False,
):
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    database = tmp_path / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0))
    plan = _sample_plan()
    _activate_plans(database, clock, (plan,))
    seeded_engine = create_sqlite_engine(database)
    try:
        with create_session_factory(seeded_engine).begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0,
                last_alive_at=clock.now().isoformat(),
            ))
    finally:
        seeded_engine.dispose()
    clock.current = NOW
    config = _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=False)
    certification = tmp_path / "data/live-certification/tushare-stock-live.json"
    semantic_contract = certification.parent / "stock-semantic.json"

    class InvalidatingSDK(OfflineSDK):
        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                result = request(**kwargs)
                if (
                    fail_realtime_once
                    and name == "rt_min"
                    and sum(item == "rt_min" for item, _ in self.calls) == 1
                ):
                    raise ProviderConnectionError("offline transport interruption")
                if len(self.calls) == 1:
                    if invalidate_during_request == "remove_semantic":
                        semantic_contract.unlink()
                    elif invalidate_during_request == "corrupt_semantic":
                        semantic_contract.write_text("{}", encoding="utf-8")
                return result

            return call

    sdk = InvalidatingSDK(clock, (plan.symbol,))

    def controller_factory(*, clock):
        pace = VirtualPace()
        return create_live_tushare_request_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
        )

    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
    monkeypatch.setattr(
        monitor_composition, "create_live_tushare_request_controller", controller_factory
    )
    monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
    return (
        create_monitor_composition(config_path=config, database_path=database),
        sdk,
        certification,
    )


@pytest.mark.parametrize("invalidated_by", ("remove_semantic", "corrupt_semantic"))
def test_startup_stops_physical_stock_calls_when_semantics_become_invalid(
    tmp_path, monkeypatch, invalidated_by
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, invalidate_during_request=invalidated_by
        )
        try:
            with pytest.raises(RequestControlError) as caught:
                await composition.start()
            assert caught.value.code is RequestControlErrorCode.ERROR
            assert [name for name, _ in sdk.calls] == ["trade_cal"]
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_repeated_capability_probe_discards_the_previous_ready_pipeline(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, certification = _composition(tmp_path, monkeypatch)
        state = composition._runtime._probe_capabilities.__self__
        try:
            assert state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.READY
            assert state._pipeline is not None
            certification.write_text("{}", encoding="utf-8")
            (certification.parent / "stock-semantic.json").write_text(
                "{}", encoding="utf-8"
            )
            assert (
                state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
            )
            assert state._pipeline is None
            assert not sdk.calls
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_cold_reference_cache_does_not_repeat_a_committed_deadline(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._run_deadline.__self__
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            results = await state.run_deadline(deadline)
            assert len(results) == 1 and results[0].status.value == "COMMITTED"
            calls = tuple(sdk.calls)
            with state._session_factory() as session:
                before = (
                    session.scalar(select(func.count()).select_from(EvaluationResult)),
                    session.scalar(select(func.count()).select_from(AlertEvent)),
                )
            state._pipeline._reference_key = None
            assert await state.run_deadline(deadline) == ()
            assert sum(name == "rt_min" for name, _ in sdk.calls) == sum(
                name == "rt_min" for name, _ in calls
            )
            with state._session_factory() as session:
                assert before == (
                    session.scalar(select(func.count()).select_from(EvaluationResult)),
                    session.scalar(select(func.count()).select_from(AlertEvent)),
                )
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_production_composition_resumes_after_one_runtime_transport_failure(
    tmp_path, monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, fail_realtime_once=True,
        )
        runtime = composition._runtime
        controller = runtime._request_controller
        state = runtime._run_deadline.__self__
        state._clock.released_sleeps = 2
        controller._backoff = (timedelta(milliseconds=10),)
        runtime._retry_interval_seconds = 0.01
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            for _ in range(200):
                if sum(name == "rt_min" for name, _ in sdk.calls) >= 2:
                    break
                await asyncio.sleep(0.01)
            assert sum(name == "rt_min" for name, _ in sdk.calls) >= 2
            assert composition._runtime is runtime
            assert runtime._request_controller is controller
            assert runtime.status is RuntimeServiceStatus.RUNNING
            assert not controller._closed
        finally:
            await composition.stop()
        assert controller._closed

    asyncio.run(scenario())


def test_next_minute_cannot_bypass_realtime_transport_backoff(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, fail_realtime_once=True,
        )
        runtime = composition._runtime
        controller = runtime._request_controller
        state = runtime._run_deadline.__self__
        state._clock.released_sleeps = 2
        controller._backoff = (timedelta(minutes=5),)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            for _ in range(200):
                if len(state._clock.sleep_calls) >= 3:
                    break
                await asyncio.sleep(0.01)
            assert len(state._clock.sleep_calls) >= 3
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
            assert runtime.status is RuntimeServiceStatus.RUNNING
        finally:
            await composition.stop()

    asyncio.run(scenario())
