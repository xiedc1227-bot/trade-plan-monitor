"""A committed 429 checkpoint survives a controlled production process restart."""

import asyncio
from datetime import timedelta
from multiprocessing import get_context
from pathlib import Path

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

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness


def _run_monitor(root: str, observed_at, induce_limit: bool, outcomes) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    class OfflineRateLimitedSDK(OfflineSDK):
        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                result = request(**kwargs)
                if induce_limit and name == "rt_min":
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
                return result

            return call

    base = Path(root)
    clock = ControlledClock(observed_at)
    first_market_due = NOW.replace(minute=1, second=12, microsecond=0)
    released = []

    if induce_limit:
        async def sleep_until(deadline):
            # Maintenance may wake before the first real market duty. Release
            # actual deadlines through that target, not a fixed sleep ordinal.
            clock.sleep_calls.append(deadline)
            if deadline <= first_market_due:
                assert len(released) < 8, "too many wakes before the first market target"
                released.append(deadline)
                clock.current = max(clock.current, deadline)
                await asyncio.sleep(0)
                return
            await asyncio.Event().wait()

        clock.sleep_until = sleep_until
    sdk = OfflineRateLimitedSDK(clock, (_sample_plan().symbol,))
    real_controller = monitor_composition.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monitor_composition.SystemClock = lambda: clock
    monitor_composition.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _config: sdk

    async def scenario():
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config/app.yaml",
            database_path=base / "monitor.sqlite3",
        )
        try:
            health = await composition.start()
            if induce_limit:
                assert health.status is RuntimeServiceStatus.RUNNING
                for _ in range(200):
                    if composition._runtime._request_controller.cooldown_until is not None:
                        break
                    await asyncio.sleep(0.01)
                assert first_market_due in released and clock.now() == first_market_due
                assert composition._runtime._request_controller.cooldown_until == (
                    first_market_due + timedelta(seconds=300)
                )
                assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
            else:
                assert health.status is RuntimeServiceStatus.DEGRADED
            return (
                composition._runtime._request_controller.cooldown_until.isoformat(),
                tuple(name for name, _ in sdk.calls),
            )
        finally:
            await composition.stop()

    outcomes.put(asyncio.run(scenario()))


def _spawn(root: Path, observed_at, induce_limit: bool):
    context = get_context("spawn")
    outcomes = context.Queue()
    process = context.Process(
        target=_run_monitor,
        args=(str(root), observed_at, induce_limit, outcomes),
    )
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("offline monitor child did not stop")
    assert process.exitcode == 0
    return outcomes.get(timeout=5)


@pytest.mark.parametrize("change_token", (False, True))
def test_observed_429_blocks_physical_work_after_controlled_process_restart(
    tmp_path, change_token: bool,
):
    database = tmp_path / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0))
    _activate_plans(database, clock, (_sample_plan(),))
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine).begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0,
                last_alive_at=clock.now().isoformat(),
            ))
    finally:
        engine.dispose()
    _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=False)

    first_cooldown, first_calls = _spawn(tmp_path, NOW, True)
    if change_token:
        config = tmp_path / "config/app.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "offline-test-token", "offline-new-token"
            ),
            encoding="utf-8",
        )
    second_cooldown, second_calls = _spawn(
        tmp_path, NOW + timedelta(minutes=2), False,
    )
    assert first_cooldown == second_cooldown
    assert first_calls.count("rt_min") == 1
    assert second_calls == ()
