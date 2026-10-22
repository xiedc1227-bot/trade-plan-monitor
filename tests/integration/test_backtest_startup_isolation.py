"""ML-T31: a backtest-only defect must not own monitor readiness."""

from threading import Event

from fastapi.testclient import TestClient

from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_contract import BacktestServiceState
from trade_plan_monitor.backtest.service_lifecycle import LazyBacktestLifecycle
from trade_plan_monitor.web.app import create_app


class Runtime:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def test_startup_schema_status_and_unused_shutdown_never_call_backtest_factory() -> None:
    runtime = Runtime()
    calls = []

    def broken_factory():
        calls.append("factory")
        raise OSError("unusable backtest-only store")

    app = create_app(runtime_factory=lambda: runtime, backtest_lifecycle_factory=broken_factory)
    with TestClient(app) as client:
        assert runtime.started and not runtime.stopped
        assert app.state.backtest_lifecycle.snapshot.state is BacktestServiceState.NOT_INITIALIZED
        assert "/api/v1/backtest-runs" in client.get("/openapi.json").json()["paths"]
        assert calls == []
    assert runtime.stopped
    assert calls == []


def test_first_use_failure_is_cached_and_monitor_stays_started() -> None:
    runtime = Runtime()
    calls = []

    def broken_factory():
        calls.append("factory")
        raise OSError("private path must not leak into response")

    app = create_app(runtime_factory=lambda: runtime, backtest_lifecycle_factory=broken_factory)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/api/v1/backtest-datasets")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "private path" not in response.text
            assert not runtime.stopped
        assert calls == ["factory"]
        assert app.state.backtest_lifecycle.snapshot.state is BacktestServiceState.DEGRADED
    assert runtime.stopped


def test_invalid_submission_does_not_initialize_backtest() -> None:
    calls = []

    def factory():
        calls.append("factory")
        raise AssertionError("invalid request cannot prepare backtest")

    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=factory)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post(
            "/api/v1/backtest-runs", json={},
            headers={"Origin": "http://127.0.0.1:8765", "Idempotency-Key": "invalid-intent"},
        )
        assert response.status_code == 422
        assert calls == []


def test_pending_initialization_returns_503_retry_after_without_false_empty_result() -> None:
    release = Event()

    def factory():
        assert release.wait(2)
        raise OSError("test completes with controlled preparation failure")

    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=factory)
    with TestClient(app) as client:
        app.state.backtest_lifecycle = LazyBacktestLifecycle(factory, config=BacktestServiceConfig(
            request_wait_seconds=0.01,
        ))
        try:
            response = client.get("/api/v1/backtest-datasets")
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            assert "items" not in response.json()
        finally:
            release.set()
            client.portal.call(app.state.backtest_lifecycle.stop)


def test_initialization_failure_logs_safe_code_and_origin_without_private_content(caplog) -> None:
    from trade_plan_monitor.backtest.migration import MigrationPreflightError

    def failing_store_preflight():
        error = MigrationPreflightError("SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT")
        error.args = ("private database path and credentials",)
        raise error

    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=failing_store_preflight)
    with TestClient(app) as client:
        response = client.get("/api/v1/backtest-datasets")
        assert response.status_code == 503
        assert "SQLITE_SIDECARS" not in response.text
    assert "code=SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT" in caplog.text
    assert "origin=failing_store_preflight:" in caplog.text
    assert "generation=0" in caplog.text
    assert "private database path and credentials" not in caplog.text


def test_initialization_failure_does_not_log_untrusted_exception_codes(caplog) -> None:
    from trade_plan_monitor.backtest.migration import MigrationPreflightError

    def broken_factory():
        raise MigrationPreflightError("private/path\nsecret-token")

    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=broken_factory)
    with TestClient(app) as client:
        assert client.get("/api/v1/backtest-datasets").status_code == 503
    assert "code=UNCLASSIFIED" in caplog.text
    assert "private/path" not in caplog.text
    assert "secret-token" not in caplog.text
