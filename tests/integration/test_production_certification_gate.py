"""Production evidence is revalidated at each physical request boundary."""

import asyncio
from datetime import timedelta

import pytest
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
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


def _composition(tmp_path, monkeypatch, *, invalidate_during_request=None):
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    database = tmp_path / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0))
    plan = _sample_plan()
    _activate_plans(database, clock, (plan,))
    clock.current = NOW
    config = _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=False)
    certification = tmp_path / "data/live-certification/tushare-stock-live.json"

    class InvalidatingSDK(OfflineSDK):
        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                result = request(**kwargs)
                if len(self.calls) == 1:
                    if invalidate_during_request == "expiry":
                        clock.current += timedelta(days=8)
                    elif invalidate_during_request == "tamper":
                        certification.write_text("{}", encoding="utf-8")
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


@pytest.mark.parametrize("invalidated_by", ("expiry", "tamper"))
def test_startup_stops_physical_stock_calls_when_evidence_becomes_invalid(
    tmp_path, monkeypatch, invalidated_by
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, invalidate_during_request=invalidated_by
        )
        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.DEGRADED
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
            assert (
                state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
            )
            assert state._pipeline is None
            assert not sdk.calls
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_duplicate_deadline_short_circuits_even_with_a_cold_reference_cache(tmp_path, monkeypatch):
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
            state._pipeline._reference_key = None
            assert await state.run_deadline(deadline) == ()
            assert tuple(sdk.calls) == calls
        finally:
            await composition.stop()

    asyncio.run(scenario())
