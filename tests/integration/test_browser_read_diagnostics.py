"""Offline observation distinguishes bounded read races from unavailable evidence."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from test_persistent_monitor_read_service import _NOW, _setup
from tests.browser.read_diagnostics import observe_read_failures

from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.web import errors
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.mark.parametrize("failure", ["race", "storage", "unavailable", "healthy"])
def test_observation_preserves_real_read_outcome_and_request_identity(
    tmp_path, failure, monkeypatch,
):
    engine, _, _, health = _setup(tmp_path)
    calls = []

    def authority():
        calls.append(len(calls))
        if failure == "unavailable":
            return None
        return RuntimeReadAuthority(
            token=len(calls) if failure == "race" else "stable",
            lifecycle="STOPPED", progress=None, health=health, owner_absent=True,
        )

    def storage_failure():
        raise OperationalError("SELECT fixture", {}, RuntimeError("offline storage failure"))

    service = RuntimeStatusReadService(
        storage_failure if failure == "storage" else create_session_factory(engine),
        authority, clock=lambda: _NOW,
    )
    monkeypatch.setattr(errors, "uuid4", lambda: UUID("00000000-0000-4000-8000-000000000001"))
    statements = []
    event.listen(
        engine, "before_cursor_execute", lambda _c, _cu, sql, _p, _ctx, _m: statements.append(sql),
    )
    baseline_client = TestClient(create_app(monitor_contract_version=2, read_service=service))
    try:
        baseline = baseline_client.get(
            "/api/v1/dashboard", headers={"X-Monitor-Contract-Version": "2"},
        )
        baseline_statements = statements.copy()
    finally:
        baseline_client.close()
    statements.clear()
    calls.clear()
    app = create_app(monitor_contract_version=2, read_service=service)
    observe_read_failures(app, service)
    client = TestClient(app)
    try:
        response = client.get("/api/v1/dashboard", headers={"X-Monitor-Contract-Version": "2"})
        assert response.status_code == baseline.status_code
        assert response.content == baseline.content
        assert response.headers == baseline.headers
        assert statements == baseline_statements
        diagnostics = client.get("/_test/read-diagnostics").json()
        if failure == "healthy":
            assert response.status_code == 200
            assert diagnostics == []
            return
        assert response.status_code == 503
        assert response.headers["X-Monitor-Contract-Version"] == "2"
        assert response.json() == {"error": {
            "code": "SERVICE_UNAVAILABLE", "message": "Service unavailable", "details": [],
            "requestId": response.headers["X-Request-ID"],
        }}
        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        assert diagnostic["requestId"] == response.headers["X-Request-ID"]
        assert diagnostic["path"] == "/api/v1/dashboard"
        assert diagnostic["method"] == "GET"
        assert diagnostic["monitorContractVersion"] == "2"
        if failure == "race":
            assert len(calls) == 4  # The real reader still performs exactly two assemblies.
            assert diagnostic["cause"] == "BOUNDED_AUTHORITY_RACE"
            assert diagnostic["causeType"] == "ProjectionError"
            assert diagnostic["causeMessage"] == "Runtime authority changed during projection"
        else:
            assert diagnostic["cause"] == "OTHER_READ_FAILURE"
            assert diagnostic["causeType"] == (
                "OperationalError" if failure == "storage" else "ProjectionError"
            )
    finally:
        client.close()
        engine.dispose()
