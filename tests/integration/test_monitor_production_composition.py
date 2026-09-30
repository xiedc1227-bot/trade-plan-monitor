"""WEBF05 coverage for the default monitoring production composition."""

from __future__ import annotations

import asyncio
from datetime import datetime
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from fastapi.testclient import TestClient

import trade_plan_monitor.web.app as web_app
from trade_plan_monitor.runtime.health import (
    DatabaseHealthSnapshot,
    DeliveryHealthSnapshot,
    ExecutorHealthSnapshot,
    RuntimeHealthSnapshot,
    RuntimeResourceStatus,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.service import RuntimeLifecycleService
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_OBSERVED_AT = datetime(2026, 9, 3, 10, 30, tzinfo=_SHANGHAI)


class _InertAIService:
    """Avoid project configuration and credential reads in composition tests."""


class _InertBacktestLifecycle:
    read_service = object()
    operation_service = object()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _DegradedReadService:
    async def get_health(self) -> RuntimeHealthSnapshot:
        return RuntimeHealthSnapshot(
            status=RuntimeServiceStatus.DEGRADED,
            read_only=True,
            observed_at=_OBSERVED_AT,
            started_at=_OBSERVED_AT,
            executor=ExecutorHealthSnapshot(max_workers=2, active_count=0, waiting_count=0),
            database=DatabaseHealthSnapshot(
                status=RuntimeResourceStatus.UNVERIFIED,
                wal_status=RuntimeResourceStatus.UNVERIFIED,
            ),
            delivery=DeliveryHealthSnapshot(
                status=RuntimeResourceStatus.UNVERIFIED,
                pending_count=0,
                failed_count=0,
            ),
        )


class _DegradedMonitorComposition:
    """A startup-safe fake: no scheduler or data-provider work is available."""

    def __init__(self, events: list[str], requests: list[str]) -> None:
        self._events = events
        self._requests = requests
        self.read_service = _DegradedReadService()
        self.position_service = object()
        self.alert_service = object()
        self.websocket_service = object()
        self.market_index_read_service = None

    async def start(self) -> RuntimeHealthSnapshot:
        self._events.append("monitor.start")
        return await self.read_service.get_health()

    async def stop(self) -> None:
        self._events.append("monitor.stop")


class _InjectedRuntime:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> object:
        self._events.append("injected.start")
        return object()

    async def stop(self) -> None:
        self._events.append("injected.stop")


class _RecordingRuntime:
    def __init__(self, *, status: RuntimeServiceStatus) -> None:
        self._status = status
        self.start_calls = 0
        self.run_calls = 0
        self.stop_calls = 0
        self.run_started = asyncio.Event()
        self.allow_run_exit = asyncio.Event()
        self.run_finished = asyncio.Event()

    def health(self) -> RuntimeHealthSnapshot:
        return RuntimeHealthSnapshot(
            status=self._status,
            read_only=self._status is RuntimeServiceStatus.DEGRADED,
            observed_at=_OBSERVED_AT,
            started_at=_OBSERVED_AT,
            executor=ExecutorHealthSnapshot(max_workers=2, active_count=0, waiting_count=0),
            database=DatabaseHealthSnapshot(
                status=RuntimeResourceStatus.READY,
                wal_status=RuntimeResourceStatus.READY,
            ),
            delivery=DeliveryHealthSnapshot(
                status=RuntimeResourceStatus.READY,
                pending_count=0,
                failed_count=0,
            ),
        )

    async def start(self) -> RuntimeHealthSnapshot:
        self.start_calls += 1
        return self.health()

    async def run(self) -> None:
        self.run_calls += 1
        self.run_started.set()
        await self.allow_run_exit.wait()
        self.run_finished.set()

    async def stop(self) -> None:
        self.stop_calls += 1
        self.allow_run_exit.set()


class _DegradedOwnedRuntime(_RecordingRuntime, RuntimeLifecycleService):
    """Exercise the lifecycle-specific degraded runner admission boundary."""


class _ControlledRestartDelay:
    def __init__(self) -> None:
        self.calls: list[float] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, delay_seconds: float) -> None:
        self.calls.append(delay_seconds)
        self.entered.set()
        await self.release.wait()


class _CleanupFailingRuntime(_RecordingRuntime):
    async def stop(self) -> None:
        self.stop_calls += 1
        self.allow_run_exit.set()
        raise RuntimeError("sanitized cleanup failure")


class _StartupFailingRuntime(_RecordingRuntime):
    async def start(self) -> RuntimeHealthSnapshot:
        self.start_calls += 1
        raise RuntimeError("sanitized startup failure")


class _WebSocketService:
    async def serve(self, websocket, *, after: int) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "heartbeat", "sequence": after})
        await websocket.close(code=1000)


class _UnavailableProjectionReadService(_DegradedReadService):
    async def get_dashboard(self) -> object:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)


def _write_distribution(directory: Path) -> None:
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (assets / "app.js").write_text("export {};", encoding="utf-8")


def _production_app(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: object,
):
    _write_distribution(tmp_path / "dist")
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    return create_production_app(monitor_contract_version=1,
        config_path=tmp_path / "config" / "app.yaml",
        database_path=tmp_path / "state" / "monitor.sqlite3",
        ai_service=_InertAIService(),
        backtest_lifecycle_factory=_InertBacktestLifecycle,
        **kwargs,
    )


def test_default_production_app_defers_monitor_composition_without_construction_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(web_app, "_ReadOnlyPackagedLifecycle")
    factory_arguments: list[tuple[Path, Path]] = []
    created: list[_DegradedMonitorComposition] = []
    events: list[str] = []
    provider_requests: list[str] = []

    def create_monitor_composition_factory(*, config_path: Path, database_path: Path):
        factory_arguments.append((config_path, database_path))

        def factory() -> _DegradedMonitorComposition:
            composition = _DegradedMonitorComposition(events, provider_requests)
            created.append(composition)
            return composition

        return factory

    monkeypatch.setattr(
        web_app,
        "create_monitor_composition_factory",
        create_monitor_composition_factory,
        raising=False,
    )

    with _production_app(tmp_path=tmp_path, monkeypatch=monkeypatch) as app:
        assert factory_arguments == [
            (tmp_path / "config" / "app.yaml", tmp_path / "state" / "monitor.sqlite3")
        ]
        assert created == []
        assert events == []
        assert provider_requests == []

        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["readOnly"] is True
    assert response.json()["nextPollAt"] is None
    assert len(created) == 1
    assert events == ["monitor.start", "monitor.stop"]
    assert provider_requests == []


def test_explicit_monitor_runtime_and_services_bypass_default_composer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_default_composer(**_kwargs: object) -> object:
        raise AssertionError("explicit monitor dependencies must bypass the default composer")

    monkeypatch.setattr(
        web_app,
        "create_monitor_composition_factory",
        unexpected_default_composer,
        raising=False,
    )
    events: list[str] = []
    read_service = _DegradedReadService()

    with _production_app(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        runtime_factory=lambda: _InjectedRuntime(events),
        read_service=read_service,
        position_service=object(),
        alert_service=object(),
        websocket_service=object(),
        market_index_read_service=object(),
    ) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "DEGRADED"
    assert events == ["injected.start", "injected.stop"]


def test_explicit_monitor_service_without_runtime_bypasses_default_composer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_default_composer(**_kwargs: object) -> object:
        raise AssertionError("an explicit monitor service must remain authoritative")

    monkeypatch.setattr(
        web_app,
        "create_monitor_composition_factory",
        unexpected_default_composer,
        raising=False,
    )

    with _production_app(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        read_service=_DegradedReadService(),
    ) as app:
        with pytest.raises(
            RuntimeError,
            match="runtime lifecycle factory is not configured",
        ):
            with TestClient(app, base_url="http://127.0.0.1:8765"):
                pass


def test_monitor_composition_does_not_run_a_degraded_runtime() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtime = _RecordingRuntime(status=RuntimeServiceStatus.DEGRADED)
        composition = MonitorWebComposition(
            runtime=runtime,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        await asyncio.sleep(0)

        assert runtime.start_calls == 1
        assert runtime.run_calls == 0
        await composition.stop()
        assert runtime.stop_calls == 1

    asyncio.run(scenario())


def test_monitor_composition_owns_and_joins_the_running_runtime_task() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtime = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        composition = MonitorWebComposition(
            runtime=runtime,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        await asyncio.wait_for(runtime.run_started.wait(), timeout=0.2)
        assert runtime.run_calls == 1

        await composition.stop()

        assert runtime.stop_calls == 1
        assert runtime.allow_run_exit.is_set()
        assert runtime.run_finished.is_set()

    asyncio.run(scenario())


def test_monitor_composition_starts_exactly_one_runner_under_concurrency() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtime = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        composition = MonitorWebComposition(
            runtime=runtime,
            read_service=_DegradedReadService(),
        )

        first, second = await asyncio.gather(composition.start(), composition.start())

        assert first.status is RuntimeServiceStatus.RUNNING
        assert second.status is RuntimeServiceStatus.RUNNING
        assert runtime.start_calls == 1
        assert runtime.run_calls == 1
        await composition.stop()
        assert runtime.stop_calls == 1

    asyncio.run(scenario())


def test_monitor_composition_degrades_a_runtime_whose_runner_exits_early() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtime = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        runtime.allow_run_exit.set()
        composition = MonitorWebComposition(
            runtime=runtime,
            read_service=_DegradedReadService(),
        )

        startup = await composition.start()

        assert startup.status is RuntimeServiceStatus.DEGRADED
        assert startup.read_only is True
        assert startup.next_poll_at is None
        assert runtime.stop_calls == 1
        await composition.stop()

    asyncio.run(scenario())


def test_monitor_composition_projects_degraded_health_during_backoff_then_restarts_fresh(
) -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.allow_run_exit.set()
        recovered = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        replacements: list[_RecordingRuntime] = []
        delay = _ControlledRestartDelay()
        read_service = _DegradedReadService()

        def runtime_factory() -> _RecordingRuntime:
            replacements.append(recovered)
            return recovered

        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=runtime_factory,
            restart_sleep=delay,
            read_service=read_service,
        )

        await composition.start()
        await asyncio.wait_for(delay.entered.wait(), timeout=0.2)

        during_backoff = composition.health()
        assert during_backoff.status is RuntimeServiceStatus.DEGRADED
        assert during_backoff.degraded_reason == "RUNTIME_RUNNER_FAILED"
        assert during_backoff.read_only is True
        assert during_backoff.next_poll_at is None
        assert failed.stop_calls == 1
        assert replacements == []
        assert composition.read_service is read_service

        delay.release.set()
        await asyncio.wait_for(recovered.run_started.wait(), timeout=0.2)

        after_restart = composition.health()
        assert after_restart.status is RuntimeServiceStatus.RUNNING
        assert after_restart.read_only is False
        assert delay.calls == [1.0]
        assert replacements == [recovered]
        assert recovered.start_calls == 1
        assert recovered.run_calls == 1
        assert composition.read_service is read_service

        await composition.stop()
        assert recovered.stop_calls == 1

    asyncio.run(scenario())


def test_degraded_lifecycle_replacement_retains_its_retry_runner() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.allow_run_exit.set()
        recovered = _DegradedOwnedRuntime(status=RuntimeServiceStatus.DEGRADED)
        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=lambda: recovered,
            restart_sleep=lambda _delay: asyncio.sleep(0),
            read_service=_DegradedReadService(),
        )
        await composition.start()
        try:
            await asyncio.wait_for(recovered.run_started.wait(), timeout=0.2)
            assert recovered.start_calls == 1
            assert recovered.run_calls == 1
            assert composition.health().status is RuntimeServiceStatus.DEGRADED
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_monitor_composition_exhausts_exact_restart_budget_without_orphan_tasks() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtimes = [
            _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
            for _ in range(4)
        ]
        for runtime in runtimes:
            runtime.allow_run_exit.set()
        replacement_index = 1
        delays: list[float] = []

        def runtime_factory() -> _RecordingRuntime:
            nonlocal replacement_index
            runtime = runtimes[replacement_index]
            replacement_index += 1
            return runtime

        async def restart_sleep(delay_seconds: float) -> None:
            delays.append(delay_seconds)
            await asyncio.sleep(0)

        composition = MonitorWebComposition(
            runtime=runtimes[0],
            runtime_factory=runtime_factory,
            restart_sleep=restart_sleep,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        for _ in range(50):
            if all(runtime.stop_calls == 1 for runtime in runtimes):
                break
            await asyncio.sleep(0)

        exhausted = composition.health()
        assert exhausted.status is RuntimeServiceStatus.DEGRADED
        assert exhausted.read_only is True
        assert exhausted.next_poll_at is None
        assert delays == [1.0, 2.0, 4.0]
        assert replacement_index == 4
        assert [runtime.start_calls for runtime in runtimes] == [1, 1, 1, 1]
        assert [runtime.run_calls for runtime in runtimes] == [1, 1, 1, 1]
        assert [runtime.stop_calls for runtime in runtimes] == [1, 1, 1, 1]

        await composition.stop()
        await asyncio.sleep(0)
        assert not any(
            task.get_name() == "trade-plan-monitor-runtime"
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )

    asyncio.run(scenario())


def test_monitor_composition_never_restarts_after_cleanup_failure() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _CleanupFailingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.allow_run_exit.set()
        factory_calls = 0
        delays: list[float] = []

        def runtime_factory() -> _RecordingRuntime:
            nonlocal factory_calls
            factory_calls += 1
            return _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)

        async def restart_sleep(delay_seconds: float) -> None:
            delays.append(delay_seconds)

        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=runtime_factory,
            restart_sleep=restart_sleep,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        for _ in range(20):
            if failed.stop_calls:
                break
            await asyncio.sleep(0)

        snapshot = composition.health()
        assert snapshot.status is RuntimeServiceStatus.DEGRADED
        assert snapshot.read_only is True
        assert snapshot.next_poll_at is None
        assert failed.stop_calls == 1
        assert factory_calls == 0
        assert delays == []
        with pytest.raises(RuntimeError, match="cleanup failure"):
            await composition.stop()

    asyncio.run(scenario())


def test_configuration_drift_never_enters_in_process_supervisor_replacement() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.configuration_restart_required = True
        failed.allow_run_exit.set()
        factory_calls = 0

        def runtime_factory() -> _RecordingRuntime:
            nonlocal factory_calls
            factory_calls += 1
            return _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)

        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=runtime_factory,
            restart_sleep=lambda _delay: asyncio.sleep(0),
            read_service=_DegradedReadService(),
        )
        await composition.start()
        for _ in range(20):
            await asyncio.sleep(0)
        snapshot = composition.health()
        assert snapshot.status is RuntimeServiceStatus.BLOCKED
        assert snapshot.read_only is True
        assert snapshot.block_reason == "NEEDS_RESTART"
        assert factory_calls == 0
        await composition.stop()

    asyncio.run(scenario())


def test_configuration_drift_overrides_degraded_retry_health() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    class Degraded(_RecordingRuntime):
        configuration_restart_required = True

        def health(self) -> RuntimeHealthSnapshot:
            return super().health().model_copy(
                update={"degraded_reason": "PROVIDER_UNAVAILABLE"}
            )

    async def scenario() -> None:
        composition = MonitorWebComposition(
            runtime=Degraded(status=RuntimeServiceStatus.DEGRADED),
            read_service=_DegradedReadService(),
        )
        snapshot = await composition.start()
        assert snapshot.status is RuntimeServiceStatus.BLOCKED
        assert snapshot.block_reason == "NEEDS_RESTART"
        assert snapshot.degraded_reason is None
        await composition.stop()

    asyncio.run(scenario())


def test_monitor_composition_never_retries_a_replacement_startup_failure() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.allow_run_exit.set()
        replacement = _StartupFailingRuntime(status=RuntimeServiceStatus.RUNNING)
        factory_calls = 0

        def runtime_factory() -> _StartupFailingRuntime:
            nonlocal factory_calls
            factory_calls += 1
            return replacement

        async def restart_sleep(_delay_seconds: float) -> None:
            await asyncio.sleep(0)

        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=runtime_factory,
            restart_sleep=restart_sleep,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        for _ in range(20):
            if replacement.stop_calls:
                break
            await asyncio.sleep(0)

        snapshot = composition.health()
        assert snapshot.status is RuntimeServiceStatus.DEGRADED
        assert snapshot.read_only is True
        assert snapshot.next_poll_at is None
        assert factory_calls == 1
        assert replacement.start_calls == 1
        assert replacement.run_calls == 0
        assert replacement.stop_calls == 1
        await composition.stop()

    asyncio.run(scenario())


def test_monitor_composition_initial_startup_failure_cleans_once_and_is_terminal() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        runtime = _StartupFailingRuntime(status=RuntimeServiceStatus.RUNNING)
        factory_calls = 0

        def runtime_factory() -> _RecordingRuntime:
            nonlocal factory_calls
            factory_calls += 1
            return _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)

        composition = MonitorWebComposition(
            runtime=runtime,
            runtime_factory=runtime_factory,
            read_service=_DegradedReadService(),
        )

        with pytest.raises(RuntimeError, match="startup failure"):
            await composition.start()

        assert runtime.start_calls == 1
        assert runtime.stop_calls == 1
        assert factory_calls == 0
        with pytest.raises(RuntimeError, match="already stopped"):
            await composition.start()

        await composition.stop()
        assert runtime.stop_calls == 1

    asyncio.run(scenario())


def test_monitor_composition_stop_cancels_and_joins_restart_delay() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    async def scenario() -> None:
        failed = _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)
        failed.allow_run_exit.set()
        delay = _ControlledRestartDelay()
        factory_calls = 0

        def runtime_factory() -> _RecordingRuntime:
            nonlocal factory_calls
            factory_calls += 1
            return _RecordingRuntime(status=RuntimeServiceStatus.RUNNING)

        composition = MonitorWebComposition(
            runtime=failed,
            runtime_factory=runtime_factory,
            restart_sleep=delay,
            read_service=_DegradedReadService(),
        )

        await composition.start()
        await asyncio.wait_for(delay.entered.wait(), timeout=0.2)
        await composition.stop()

        assert factory_calls == 0
        assert delay.calls == [1.0]
        assert failed.stop_calls == 1
        assert not any(
            task.get_name() == "trade-plan-monitor-runtime"
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )

    asyncio.run(scenario())


def test_lifespan_binds_composed_services_and_removes_only_owned_bindings() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    runtime = _RecordingRuntime(status=RuntimeServiceStatus.DEGRADED)
    read_service = _DegradedReadService()
    websocket_service = _WebSocketService()
    position_service = object()
    alert_service = object()
    market_index_read_service = object()
    composition = MonitorWebComposition(
        runtime=runtime,
        read_service=read_service,
        websocket_service=websocket_service,
        position_service=position_service,
        alert_service=alert_service,
        market_index_read_service=market_index_read_service,
    )
    app = create_app(runtime_factory=lambda: composition)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert app.state.monitor_read_service is read_service
        assert app.state.monitor_websocket_service is websocket_service
        assert app.state.position_operation_service is position_service
        assert app.state.alert_operation_service is alert_service
        assert app.state.market_index_read_service is market_index_read_service
        with client.websocket_connect("/ws/v1/monitor?after=0") as websocket:
            assert websocket.receive_json() == {"type": "heartbeat", "sequence": 0}

    for name in (
        "monitor_read_service",
        "monitor_websocket_service",
        "position_operation_service",
        "alert_operation_service",
        "market_index_read_service",
    ):
        assert not hasattr(app.state, name)


def test_lifespan_preserves_explicit_services_while_removing_composed_ones() -> None:
    from trade_plan_monitor.web.monitor_composition import MonitorWebComposition

    explicit_read_service = _DegradedReadService()
    explicit_websocket_service = _WebSocketService()
    composed_position_service = object()
    composition = MonitorWebComposition(
        runtime=_RecordingRuntime(status=RuntimeServiceStatus.DEGRADED),
        read_service=_DegradedReadService(),
        websocket_service=_WebSocketService(),
        position_service=composed_position_service,
    )
    app = create_app(
        runtime_factory=lambda: composition,
        read_service=explicit_read_service,
        websocket_service=explicit_websocket_service,
    )

    with TestClient(app):
        assert app.state.monitor_read_service is explicit_read_service
        assert app.state.monitor_websocket_service is explicit_websocket_service
        assert app.state.position_operation_service is composed_position_service

    assert app.state.monitor_read_service is explicit_read_service
    assert app.state.monitor_websocket_service is explicit_websocket_service
    assert not hasattr(app.state, "position_operation_service")


def test_lifespan_rolls_back_partial_monitor_service_binding() -> None:
    events: list[str] = []
    read_service = _DegradedReadService()

    class ExplodingServiceRuntime:
        @property
        def read_service(self) -> object:
            return read_service

        @property
        def position_service(self) -> object:
            raise RuntimeError("position service construction failed")

        async def start(self) -> object:
            events.append("start")
            return object()

        async def stop(self) -> None:
            events.append("stop")

    app = create_app(runtime_factory=ExplodingServiceRuntime)

    with pytest.raises(RuntimeError, match="position service construction failed"):
        with TestClient(app):
            pass

    assert not hasattr(app.state, "monitor_read_service")
    assert events == ["start", "stop"]


def test_broken_injected_read_projection_remains_service_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_arguments: list[tuple[Path, Path]] = []
    composition = _DegradedMonitorComposition(events=[], requests=[])
    composition.read_service = _UnavailableProjectionReadService()

    def create_monitor_composition_factory(*, config_path: Path, database_path: Path):
        factory_arguments.append((config_path, database_path))
        return lambda: composition

    monkeypatch.setattr(
        web_app,
        "create_monitor_composition_factory",
        create_monitor_composition_factory,
        raising=False,
    )

    with _production_app(tmp_path=tmp_path, monkeypatch=monkeypatch) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.get("/api/v1/dashboard")

    assert factory_arguments == [
        (tmp_path / "config" / "app.yaml", tmp_path / "state" / "monitor.sqlite3")
    ]
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_default_monitor_composition_starts_offline_with_safe_health_and_websocket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config" / "app.yaml"
    config_path.parent.mkdir()
    config_path.write_text("{}\n", encoding="utf-8")
    database_path = tmp_path / "state" / "monitor.sqlite3"
    provider_requests: list[tuple[object, ...]] = []

    from tushare.pro.client import DataApi

    def reject_provider_request(_client: object, *args: object, **kwargs: object) -> None:
        provider_requests.append((args, kwargs))
        raise AssertionError("default offline monitor composition must not request a provider")

    monkeypatch.setattr(DataApi, "query", reject_provider_request)
    _write_distribution(tmp_path / "dist")
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)

    with create_production_app(monitor_contract_version=1,
        config_path=config_path,
        database_path=database_path,
        ai_service=_InertAIService(),
        backtest_lifecycle_factory=_InertBacktestLifecycle,
    ) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            from trade_plan_monitor.web.persistent_monitor_read_service import (
                PersistentMonitorReadService,
            )

            assert isinstance(app.state.monitor_read_service, PersistentMonitorReadService)
            health = client.get("/api/v1/health")
            dashboard = client.get("/api/v1/dashboard")
            with client.websocket_connect("/ws/v1/monitor?after=0"):
                pass

    assert health.status_code == 200
    assert health.json()["status"] == "DEGRADED"
    assert health.json()["readOnly"] is True
    assert health.json()["nextPollAt"] is None
    assert health.json()["database"]["status"] == "READY"
    assert health.json()["database"]["walStatus"] == "READY"
    assert health.json()["executor"]["maxWorkers"] == 1
    assert len(health.json()["providers"]) == 5
    assert {provider["status"] for provider in health.json()["providers"]} == {
        "ERROR"
    }
    assert {provider["errorCode"] for provider in health.json()["providers"]} == {
        "TUSHARE_NOT_CONFIGURED"
    }
    assert health.json()["nextRetryAt"] is not None
    assert dashboard.status_code == 200
    assert dashboard.json()["availability"] == "UNAVAILABLE"
    assert dashboard.json()["reason"] == "EMPTY_DATABASE"
    assert dashboard.json()["sequence"] == 0
    assert "token" not in health.text.casefold()
    assert str(tmp_path) not in health.text
    assert database_path.is_file()
    assert provider_requests == []


def test_default_monitor_composition_does_not_mask_invalid_yaml_as_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config" / "app.yaml"
    config_path.parent.mkdir()
    config_path.write_text("web: [\n", encoding="utf-8")
    database_path = tmp_path / "state" / "monitor.sqlite3"
    provider_requests: list[tuple[object, ...]] = []

    from tushare.pro.client import DataApi

    def reject_provider_request(_client: object, *args: object, **kwargs: object) -> None:
        provider_requests.append((args, kwargs))
        raise AssertionError("invalid configuration must fail before provider work")

    monkeypatch.setattr(DataApi, "query", reject_provider_request)

    with _production_app(tmp_path=tmp_path, monkeypatch=monkeypatch) as app:
        with pytest.raises(yaml.YAMLError):
            with TestClient(app, base_url="http://127.0.0.1:8765"):
                pass

    assert provider_requests == []
    assert not database_path.exists()
