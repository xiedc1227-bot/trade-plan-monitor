"""Offline A06 mixed-family continuation through real processes and the scheduler."""

import asyncio
from datetime import timedelta
from multiprocessing import get_context
from pathlib import Path

import pytest
import test_explicit_runtime_production as explicit_fixture
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

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertEvent,
    EvaluationResult,
    ExplicitEvaluationLedger,
    MarketIndexSnapshot,
    RuntimeLiveness,
    SymbolDecisionHead,
)

LEGACY_SYMBOL = "003043.SZ"
EXPLICIT_SYMBOL = "300001.SZ"
FIRST_CLOCK = NOW.replace(minute=0, second=0) - timedelta(seconds=30)
SECOND_CLOCK = NOW.replace(minute=5, second=0) - timedelta(seconds=30)
FIRST_TARGET = NOW.replace(second=0).isoformat()
SECOND_TARGET = (NOW.replace(second=0) + timedelta(minutes=5)).isoformat()


def _run_scheduled_monitor(root: str, observed_at, failed_symbol: str | None, outcomes) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    base = Path(root)
    clock = ControlledClock(observed_at, released_sleeps=1)

    class FakeSDK(OfflineSDK):
        def _stock_minutes(self, name, kwargs):
            frame = super()._stock_minutes(name, kwargs)
            if failed_symbol is not None and name == "rt_min":
                frame.loc[frame["ts_code"] == failed_symbol, "close"] = "malformed"
            return frame

    sdk = FakeSDK(clock, (LEGACY_SYMBOL, EXPLICIT_SYMBOL))
    delivered = []

    class FakeChannel:
        channel = DeliveryChannel.IN_APP
        enabled = True

        async def deliver(self, event):
            delivered.append(event.symbol)
            return ChannelDeliveryResult(
                channel=self.channel, delivered=True, retryable=False,
            )

    real_controller = monitor_composition.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
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
        composition._runtime._dispatcher._channels = (FakeChannel(),)
        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.RUNNING

            async def scheduler_reached_next_sleep():
                while len(clock.sleep_calls) < 2:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(scheduler_reached_next_sleep(), timeout=15)
            assert clock.sleep_calls[0] == (
                observed_at + timedelta(minutes=1)
            ).replace(second=12)
            return (
                tuple(clock.sleep_calls),
                tuple(name for name, _ in sdk.calls),
                tuple(delivered),
            )
        finally:
            await composition.stop()

    outcomes.put(asyncio.run(scenario()))


def _spawn_scheduled_monitor(root: Path, observed_at, *, failed_symbol: str | None):
    context = get_context("spawn")
    outcomes = context.Queue()
    process = context.Process(
        target=_run_scheduled_monitor,
        args=(str(root), observed_at, failed_symbol, outcomes),
    )
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("offline scheduled monitor child did not stop")
    assert process.exitcode == 0
    return outcomes.get(timeout=5)


@pytest.mark.parametrize("failed_symbol", (LEGACY_SYMBOL, EXPLICIT_SYMBOL))
def test_malformed_family_row_recovers_in_new_process_via_scheduler(
    tmp_path, monkeypatch, failed_symbol,
):
    database = tmp_path / "monitor.sqlite3"
    seed_clock = ControlledClock(NOW.replace(hour=9, minute=0))
    legacy_plan = _sample_plan()
    _activate_plans(database, seed_clock, (legacy_plan,))
    payload = explicit_fixture._plan(active_date=NOW.date()).model_dump(
        mode="python", round_trip=True,
    )
    payload.update(
        plan_id="offline-a06-scheduled-explicit", symbol=EXPLICIT_SYMBOL,
        name="OFFLINE A06 SCHEDULED EXPLICIT",
    )
    explicit_plan = ExplicitTradePlan.model_validate(payload)
    monkeypatch.setattr(explicit_fixture, "PREPARED_AT", NOW - timedelta(minutes=30))
    engine = create_sqlite_engine(database)
    try:
        explicit_fixture._seed_active(engine, explicit_plan)
        with create_session_factory(engine).begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0,
                last_alive_at=seed_clock.now().isoformat(),
            ))
    finally:
        engine.dispose()
    _write_configuration_and_evidence(
        tmp_path, observed_at=FIRST_CLOCK, include_index=True,
    )

    first_sleeps, first_calls, first_delivered = _spawn_scheduled_monitor(
        tmp_path, FIRST_CLOCK, failed_symbol=failed_symbol,
    )
    assert first_sleeps[0].minute == 0
    assert "rt_min" in first_calls
    assert first_delivered == ()
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine)() as session:
            legacy_first = session.scalar(
                select(func.count()).select_from(EvaluationResult).where(
                    EvaluationResult.symbol == LEGACY_SYMBOL,
                    EvaluationResult.plan_hash == plan_sha256(legacy_plan),
                    EvaluationResult.evaluation_kind == "INTRADAY",
                    EvaluationResult.target_value == FIRST_TARGET,
                )
            )
            explicit_first = session.scalar(
                select(func.count()).select_from(ExplicitEvaluationLedger).where(
                    ExplicitEvaluationLedger.symbol == EXPLICIT_SYMBOL,
                    ExplicitEvaluationLedger.plan_hash == plan_sha256(explicit_plan),
                    ExplicitEvaluationLedger.activation_revision == 1,
                    ExplicitEvaluationLedger.target_value == FIRST_TARGET,
                )
            )
            assert (legacy_first, explicit_first) == (
                (0, 1) if failed_symbol == LEGACY_SYMBOL else (1, 0)
            )
            assert session.scalar(
                select(func.count()).select_from(EvaluationResult).where(
                    EvaluationResult.symbol == LEGACY_SYMBOL,
                    EvaluationResult.target_value == FIRST_TARGET,
                )
            ) == legacy_first
            assert session.scalar(
                select(func.count()).select_from(ExplicitEvaluationLedger).where(
                    ExplicitEvaluationLedger.symbol == EXPLICIT_SYMBOL,
                    ExplicitEvaluationLedger.target_value == FIRST_TARGET,
                )
            ) == explicit_first
            if failed_symbol == EXPLICIT_SYMBOL:
                head = session.get(SymbolDecisionHead, LEGACY_SYMBOL)
                assert head is not None
                assert head.plan_hash == plan_sha256(legacy_plan)
                assert head.activation_revision == 1
                assert head.target_value == FIRST_TARGET
            assert session.scalar(
                select(func.count(func.distinct(MarketIndexSnapshot.index_code)))
            ) == 5
            first_alerts = session.scalar(select(func.count()).select_from(AlertEvent))
            assert first_alerts == 0
    finally:
        engine.dispose()

    second_sleeps, second_calls, second_delivered = _spawn_scheduled_monitor(
        tmp_path, SECOND_CLOCK, failed_symbol=None,
    )
    assert second_sleeps[0].minute == 5
    assert "rt_min" in second_calls
    assert second_delivered == ()
    engine = create_sqlite_engine(database)
    try:
        with create_session_factory(engine)() as session:
            assert session.scalar(
                select(func.count()).select_from(EvaluationResult).where(
                    EvaluationResult.symbol == LEGACY_SYMBOL,
                    EvaluationResult.plan_hash == plan_sha256(legacy_plan),
                    EvaluationResult.evaluation_kind == "INTRADAY",
                    EvaluationResult.target_value == SECOND_TARGET,
                )
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(EvaluationResult).where(
                    EvaluationResult.symbol == LEGACY_SYMBOL,
                    EvaluationResult.target_value == SECOND_TARGET,
                )
            ) == 1
            head = session.get(SymbolDecisionHead, LEGACY_SYMBOL)
            assert head is not None
            assert head.plan_hash == plan_sha256(legacy_plan)
            assert head.activation_revision == 1
            assert head.target_value == SECOND_TARGET
            assert session.scalar(
                select(func.count()).select_from(ExplicitEvaluationLedger).where(
                    ExplicitEvaluationLedger.symbol == EXPLICIT_SYMBOL,
                    ExplicitEvaluationLedger.plan_hash == plan_sha256(explicit_plan),
                    ExplicitEvaluationLedger.activation_revision == 1,
                    ExplicitEvaluationLedger.target_value == SECOND_TARGET,
                )
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(ExplicitEvaluationLedger).where(
                    ExplicitEvaluationLedger.symbol == EXPLICIT_SYMBOL,
                    ExplicitEvaluationLedger.target_value == SECOND_TARGET,
                )
            ) == 1
            if failed_symbol == EXPLICIT_SYMBOL:
                assert session.scalar(
                    select(func.count()).select_from(EvaluationResult).where(
                        EvaluationResult.symbol == LEGACY_SYMBOL,
                        EvaluationResult.plan_hash == plan_sha256(legacy_plan),
                        EvaluationResult.evaluation_kind == "INTRADAY",
                        EvaluationResult.target_value == FIRST_TARGET,
                    )
                ) == 1
            else:
                assert session.scalar(
                    select(func.count()).select_from(ExplicitEvaluationLedger).where(
                        ExplicitEvaluationLedger.symbol == EXPLICIT_SYMBOL,
                        ExplicitEvaluationLedger.plan_hash == plan_sha256(explicit_plan),
                        ExplicitEvaluationLedger.activation_revision == 1,
                        ExplicitEvaluationLedger.target_value == FIRST_TARGET,
                    )
                ) == 1
            assert session.scalar(select(func.count()).select_from(AlertEvent)) == first_alerts
    finally:
        engine.dispose()
