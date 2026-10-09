"""Mounted service status/control never admit work implicitly."""

from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_backtest_startup_isolation import Runtime

from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_lifecycle import LazyBacktestLifecycle
from trade_plan_monitor.web.app import create_app

ORIGIN = "http://127.0.0.1:8765"


class Service:
    read_service = operation_service = object()
    authorized_job_ids = frozenset()
    outstanding_work = 0

    def __init__(self):
        self.calls = []

    async def start(self):
        self.calls.append("start")

    async def stop(self):
        self.calls.append("stop")

    async def resume_jobs(self, ids):
        self.calls.append(("resume", ids))
        self.authorized_job_ids = ids


def status(client):
    response = client.get("/api/v1/backtest-service")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    return response.json()


def control(client, path, body, key="control"):
    return client.post(
        "/api/v1/backtest-service/" + path,
        json=body,
        headers={"Origin": ORIGIN, "Idempotency-Key": key},
    )


def wait_state(client, wanted):
    deadline = monotonic() + 3
    while True:
        value = status(client)
        if value["state"] == wanted:
            return value
        assert monotonic() < deadline, value
        sleep(0.01)


def test_unused_status_and_stop_never_initialize_and_receipts_are_exact():
    calls = []
    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=lambda: calls.append(1))
    with TestClient(app, base_url=ORIGIN) as client:
        before = status(client)
        assert before["state"] == "NOT_INITIALIZED" and not before["canRead"]
        body = {"epoch": before["epoch"], "expectedRevision": before["revision"]}
        accepted = control(client, "stop-requests", body)
        assert accepted.status_code == 202 and accepted.headers["Retry-After"] == "1"
        assert accepted.headers["Location"] == "/api/v1/backtest-service"
        wait_state(client, "STOPPED")
        assert control(client, "stop-requests", body).json() == accepted.json()
        assert control(client, "stop-requests", body | {"expectedRevision": 9}).status_code == 409
        assert calls == []
    assert calls == []


def test_first_use_failure_stays_scoped_then_explicit_retry_initializes_once():
    calls, service = [], Service()

    def factory():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("private failure path")
        return service

    runtime = Runtime()
    app = create_app(runtime_factory=lambda: runtime, backtest_lifecycle_factory=factory)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v1/backtest-datasets").status_code == 503
        value = status(client)
        assert value["state"] == "DEGRADED" and "private" not in str(value)
        for _ in range(3):
            status(client)
            assert client.get("/api/v1/backtest-datasets").status_code == 503
        assert len(calls) == 1 and not runtime.stopped
        body = {
            "epoch": value["epoch"],
            "expectedRevision": value["revision"],
            "action": "RETRY_PREPARATION",
            "resumeJobIds": [],
        }
        accepted = control(client, "recovery-requests", body)
        assert accepted.status_code == 202
        ready = wait_state(client, "READ_READY")
        assert ready["canRead"] and not ready["canSubmit"] and service.calls == []
        assert control(client, "recovery-requests", body).json() == accepted.json()
        assert len(calls) == 2 and not runtime.stopped


@pytest.mark.parametrize(
    "change",
    [
        {"epoch": "0" * 32},
        {"expectedRevision": 9},
        {"resumeJobIds": ["one", "two"]},
        {"resumeJobIds": []},
        {"resumeJobIds": ["bad/id"]},
        {"extra": True},
    ],
)
def test_invalid_control_cannot_activate_or_resume(change):
    calls = []
    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=lambda: calls.append(1))
    with TestClient(app, base_url=ORIGIN) as client:
        value = status(client)
        body = {
            "epoch": value["epoch"],
            "expectedRevision": value["revision"],
            "action": "RESUME_JOBS",
            "resumeJobIds": ["selected"],
        } | change
        assert control(client, "recovery-requests", body).status_code in (409, 422)
        assert calls == []


def test_selected_resume_activates_only_one_id_and_status_never_resumes_backlog():
    service = Service()
    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=lambda: service)
    with TestClient(app, base_url=ORIGIN) as client:
        value = status(client)
        body = {
            "epoch": value["epoch"],
            "expectedRevision": value["revision"],
            "action": "RESUME_JOBS",
            "resumeJobIds": ["selected"],
        }
        assert control(client, "recovery-requests", body).status_code == 202
        ready = wait_state(client, "READY")
        assert ready["authorizedJobIds"] == ["selected"] and ready["canSubmit"]
        for _ in range(3):
            status(client)
        assert service.calls == ["start", ("resume", frozenset({"selected"}))]


def test_pending_first_use_returns_retry_after_and_repair_waits_for_physical_drain():
    block, entered = Event(), Event()
    service = Service()

    def factory():
        entered.set()
        assert block.wait(3)
        return service

    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=factory)
    with TestClient(app, base_url=ORIGIN) as client:
        manager = LazyBacktestLifecycle(
            factory, config=BacktestServiceConfig(request_wait_seconds=0.01)
        )
        app.state.backtest_lifecycle = manager
        try:
            response = client.get("/api/v1/backtest-datasets")
            assert entered.is_set() and response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            value = status(client)
            assert not value["physicallyDrained"]
            body = {
                "epoch": value["epoch"],
                "expectedRevision": value["revision"],
                "action": "RETRY_PREPARATION",
                "resumeJobIds": [],
            }
            assert control(client, "recovery-requests", body).status_code == 409
        finally:
            block.set()
            client.portal.call(manager.stop)


def test_controls_use_existing_origin_and_idempotency_guards():
    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=Service)
    with TestClient(app, base_url=ORIGIN) as client:
        value = status(client)
        body = {"epoch": value["epoch"], "expectedRevision": value["revision"]}
        assert (
            client.post(
                "/api/v1/backtest-service/stop-requests",
                json=body,
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/backtest-service/stop-requests", json=body, headers={"Origin": ORIGIN}
            ).status_code
            == 422
        )
        assert status(client)["state"] == "NOT_INITIALIZED"


def test_old_boot_epoch_and_concurrent_revision_do_not_acquire_resources():
    calls = []
    old = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=Service)
    with TestClient(old, base_url=ORIGIN) as client:
        epoch = status(client)["epoch"]
    app = create_app(runtime_factory=Runtime, backtest_lifecycle_factory=lambda: calls.append(1))
    with TestClient(app, base_url=ORIGIN) as client:
        value = status(client)
        assert value["epoch"] != epoch
        body = {"epoch": epoch, "expectedRevision": 0}
        assert control(client, "stop-requests", body).status_code == 409
        body["epoch"] = value["epoch"]
        assert control(client, "stop-requests", body, "first").status_code == 202
        assert control(client, "stop-requests", body, "second").status_code == 409
        assert calls == []


def test_control_receipts_are_bounded_without_changing_original_epoch():
    import asyncio

    async def scenario():
        manager = LazyBacktestLifecycle(Service)
        epoch = manager.epoch
        for revision in range(1001):
            assert (
                manager.request_control(
                    epoch=epoch, revision=revision, key=str(revision), action="STOP"
                )
                == revision + 1
            )
            await manager._control_task
        assert len(manager._control_receipts) == 1000
        assert manager.epoch == epoch
        with pytest.raises(ValueError):
            manager.request_control(epoch=epoch, revision=0, key="0", action="STOP")
        await manager.stop()

    asyncio.run(scenario())
