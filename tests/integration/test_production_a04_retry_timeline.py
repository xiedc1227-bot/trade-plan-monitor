"""Offline installed-runtime recovery on one coherent virtual time line."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select
from test_live_pipeline_acceptance import (
    NOW,
    OfflineSDK,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.runtime.health import RuntimeResourceStatus, RuntimeServiceStatus
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.runtime.service import RuntimeLifecycleService, _RetryWaitOutcome
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertEvent,
    EvaluationResult,
    RuntimeLiveness,
    SymbolDecisionHead,
)
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


@dataclass
class RetryGate:
    started_at: datetime
    delay: float
    calls_before: int
    release: asyncio.Event


class UnifiedTimeline:
    """Advance business and monotonic time together for pacing and owned waits."""

    def __init__(self, current: datetime) -> None:
        self.current = current
        self.elapsed = 0.0
        self.retry_gates: list[RetryGate] = []
        self.scheduler_deadlines: list[datetime] = []
        self.scheduler_release = asyncio.Event()

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        assert seconds >= 0
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds

    async def pace_sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)

    async def sleep_until(self, deadline: datetime) -> None:
        self.scheduler_deadlines.append(deadline)
        await self.scheduler_release.wait()
        self.scheduler_release.clear()
        self.advance(max(0.0, (deadline - self.current).total_seconds()))
        await asyncio.sleep(0)


async def _until(predicate) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=10)


def test_installed_composition_recovers_after_four_calendar_transport_failures(
    tmp_path,
    monkeypatch,
) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    async def scenario() -> None:
        timeline = UnifiedTimeline(NOW)
        database = tmp_path / "monitor.sqlite3"
        plan = _sample_plan()
        _activate_plans(database, timeline, (plan,))
        engine = create_sqlite_engine(database)
        try:
            with create_session_factory(engine).begin() as session:
                session.add(
                    RuntimeLiveness(
                        id=1,
                        schema_version=1,
                        revision=0,
                        last_alive_at=timeline.now().isoformat(),
                    )
                )
        finally:
            engine.dispose()
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=NOW,
            include_index=False,
        )

        class FailingCalendarSDK(OfflineSDK):
            def __getattr__(self, name):
                request = super().__getattr__(name)

                def call(**kwargs):
                    result = request(**kwargs)
                    if (
                        name == "trade_cal"
                        and sum(item == "trade_cal" for item, _ in self.calls) <= 4
                    ):
                        raise ProviderConnectionError("offline calendar interruption")
                    return result

                return call

        sdk = FailingCalendarSDK(timeline, (plan.symbol,))

        async def retry_wait(shutdown_event: asyncio.Event, delay: float) -> _RetryWaitOutcome:
            gate = RetryGate(
                timeline.now(),
                delay,
                len(sdk.calls),
                asyncio.Event(),
            )
            timeline.retry_gates.append(gate)
            release = asyncio.create_task(gate.release.wait())
            shutdown = asyncio.create_task(shutdown_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (release, shutdown),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if shutdown in done:
                    return _RetryWaitOutcome.SHUTDOWN
                timeline.advance(delay)
                return _RetryWaitOutcome.TIMEOUT
            finally:
                for task in (release, shutdown):
                    task.cancel()
                await asyncio.gather(release, shutdown, return_exceptions=True)

        class GatedLifecycle(RuntimeLifecycleService):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, retry_wait=retry_wait)

        def controller_factory(*, clock, require_repository_binding=False):
            return create_live_tushare_request_controller(
                clock=clock,
                monotonic=timeline.monotonic,
                pace_sleep=timeline.pace_sleep,
                require_repository_binding=require_repository_binding,
            )

        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: timeline)
        monkeypatch.setattr(monitor_composition, "RuntimeLifecycleService", GatedLifecycle)
        monkeypatch.setattr(
            monitor_composition,
            "create_live_tushare_request_controller",
            controller_factory,
        )
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        composition = create_monitor_composition(config_path=config, database_path=database)
        runtime = composition._runtime
        controller = runtime._request_controller
        generation = runtime.runtime_generation
        state = runtime._probe_capabilities.__self__
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            owner = state._liveness_revision
            assert owner is not None
            await _until(lambda: len(timeline.retry_gates) == 1)
            assert [name for name, _ in sdk.calls] == ["trade_cal"]
            assert (
                await composition.read_service.get_health()
            ).status is RuntimeServiceStatus.DEGRADED
            await composition.read_service.get_dashboard()
            assert composition._restart_attempts == 0

            for attempt, floor in enumerate((30, 60, 120, 300), start=1):
                gate = timeline.retry_gates[attempt - 1]
                assert gate.delay >= floor
                assert gate.calls_before == attempt
                assert runtime._retry_at is not None
                assert gate.started_at + timedelta(seconds=gate.delay) >= runtime._retry_at
                retry_due = gate.started_at + timedelta(seconds=gate.delay)
                health = await composition.read_service.get_health()
                assert health.status is RuntimeServiceStatus.DEGRADED and health.read_only
                assert health.degraded_reason == "REFERENCE_REFRESH_FAILED"
                assert health.block_reason is None
                assert health.next_retry_at == runtime._retry_at == retry_due
                assert health.database.status is RuntimeResourceStatus.READY
                assert health.database.wal_status is RuntimeResourceStatus.READY
                assert composition._runtime is runtime
                assert runtime.runtime_generation == generation
                assert state._liveness_revision == owner
                assert not composition._runner_failed and composition._restart_attempts == 0
                dashboard = await composition.read_service.get_dashboard()
                assert dashboard.availability == "UNAVAILABLE"
                assert dashboard.reason.value == "AWAITING_FIRST_EVALUATION"
                assert await composition.read_service.get_symbol_health(symbol=plan.symbol) is None
                frame = composition.websocket_service._heartbeat_frame(dashboard.sequence)
                assert frame["runtimeLive"] is False and frame["runtimeGeneration"] is None
                with state._session_factory() as session:
                    assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                    assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
                backoff = controller.backoff_until(f"calendar:SSE:{NOW.date()}")
                assert backoff is not None
                assert gate.started_at + timedelta(seconds=gate.delay) >= backoff
                if controller.cooldown_until is not None:
                    assert gate.started_at + timedelta(seconds=gate.delay) >= (
                        controller.cooldown_until
                    )
                assert len(sdk.calls) == attempt  # Nothing physical before the retry due.
                gate.release.set()
                if attempt < 4:
                    expected_gates = attempt + 1
                    await _until(
                        lambda expected=expected_gates: len(timeline.retry_gates) == expected
                    )
                    assert len(sdk.calls) == attempt + 1
                else:
                    await _until(
                        lambda: composition.health().status is RuntimeServiceStatus.RUNNING
                    )
                    assert len(sdk.calls) >= 5

            calendar_calls = [kwargs for name, kwargs in sdk.calls if name == "trade_cal"]
            assert len(calendar_calls) == 6  # Four failed SSE, recovered SSE, then SZSE.
            assert all(kwargs == calendar_calls[0] for kwargs in calendar_calls[:5])
            assert calendar_calls[5]["exchange"] == "SZSE"
            assert runtime is composition._runtime
            assert controller is runtime._request_controller
            assert generation == runtime.runtime_generation
            assert owner == state._liveness_revision
            assert composition._restart_attempts == 0
            await _until(lambda: bool(timeline.scheduler_deadlines))
            first_deadline = timeline.scheduler_deadlines[0]
            assert first_deadline > timeline.now()
            assert first_deadline.hour == 10 and first_deadline.minute == 9
            timeline.scheduler_release.set()
            await _until(lambda: len(timeline.scheduler_deadlines) == 2)
            with state._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            evaluation_due = NOW.replace(hour=10, minute=10, second=12, microsecond=0)
            target = NOW.replace(hour=10, minute=10, second=0, microsecond=0).isoformat()
            # New maintenance duties may legitimately wake before the original
            # market target. Release real waits, never infer a duty from its ordinal.
            for _ in range(8):
                deadline = timeline.scheduler_deadlines[-1]
                assert deadline <= evaluation_due
                if deadline == evaluation_due:
                    break
                count = len(timeline.scheduler_deadlines)
                timeline.scheduler_release.set()
                await _until(lambda previous=count: len(timeline.scheduler_deadlines) > previous)
                assert composition._runtime is runtime
                assert runtime.runtime_generation == generation
                assert not composition._runner_failed and composition._restart_attempts == 0
                with state._session_factory() as session:
                    assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 0
                    assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            else:
                raise AssertionError("original 10:10:12 duty was not reached within eight wakes")
            assert timeline.scheduler_deadlines[-1] == evaluation_due
            timeline.scheduler_release.set()

            def committed() -> bool:
                with state._session_factory() as session:
                    return (
                        session.scalar(
                            select(func.count())
                            .select_from(EvaluationResult)
                            .where(
                                EvaluationResult.plan_hash == plan_sha256(plan),
                                EvaluationResult.symbol == plan.symbol,
                                EvaluationResult.evaluation_kind == "INTRADAY",
                                EvaluationResult.target_value == target,
                            )
                        )
                        == 1
                    )

            await _until(committed)
            assert composition._runtime is runtime
            assert runtime.runtime_generation == generation
            assert not composition._runner_failed
            with state._session_factory() as session:
                results = tuple(session.scalars(select(EvaluationResult)))
                assert len(results) == 1
                assert results[0].target_value == target
                assert results[0].evaluated_at == evaluation_due.isoformat()
                head = session.get(SymbolDecisionHead, plan.symbol)
                assert head is not None
                assert head.plan_hash == plan_sha256(plan)
                assert head.activation_revision == 1
                assert head.target_value == target
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            assert composition._restart_attempts == 0
        finally:
            for gate in timeline.retry_gates:
                gate.release.set()
            await composition.stop()

    asyncio.run(scenario())
