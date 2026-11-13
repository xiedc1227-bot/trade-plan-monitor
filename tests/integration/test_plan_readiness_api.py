"""Readiness HTTP observes the installed profile's existing physical owner."""

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, inspect
from tests.integration.test_plan_readiness_profile_ownership import (
    installed,
    owned_reader,
    start_current,
)
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority_save import _NOW

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_read_ownership import current_read_lease
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

PATH = "/api/v1/plan-versions/{}/monitor-readiness"


async def get(app, version_id):
    # Direct ASGI transport keeps the fixture's real-network send prohibition intact.
    async with httpx.ASGITransport(app=app, raise_app_exceptions=False) as transport:
        response = await transport.handle_async_request(httpx.Request(
            "GET", "http://127.0.0.1:8765" + PATH.format(version_id)))
        await response.aread()
        return response


@asynccontextmanager
async def serve(case, profile):
    def factory():
        return case.composition

    factory.monitor_contract_version = profile
    app = create_app(runtime_factory=factory, monitor_contract_version=profile)
    async with app.router.lifespan_context(app):
        assert app.state.monitor_read_service is case.composition.read_service
        version = await start_current(case)
        yield app, version


@pytest.mark.parametrize("profile", [1, 2])
def test_http_current_uses_same_real_owner_and_performs_no_work(tmp_path, monkeypatch, profile):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = installed(tmp_path, monkeypatch, profile)
    original = projection.read_plan_readiness
    leases = []

    def leased(*args):
        lease = current_read_lease.get()
        assert lease is not None and not lease.cancelled.is_set()
        leases.append(lease)
        return original(*args)

    def readonly(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}

    async def scenario():
        async with serve(case, profile) as (app, version):
            state = case.composition._runtime._liveness_owner
            selected = app.state.monitor_read_service
            owner = owned_reader(case)._read_owner
            calls = tuple(case.sdk.calls)
            monkeypatch.setattr(projection, "read_plan_readiness", leased)
            event.listen(state._engine, "before_cursor_execute", readonly)
            try:
                direct = await selected.get_plan_readiness(version_id=version)
                response = await get(app, version)
                assert response.status_code == 200, response.text
                assert response.json() == json.loads(direct.model_dump_json(by_alias=True))
                assert response.json()["summary"] == "READY_FOR_MONITORING"
                assert response.json()["authorityGranted"] is False
                assert response.json()["snapshot"]["context"]["planVersionId"] == version
                assert len(response.content) <= 1024 * 1024
                assert len(leases) == 2 and leases[0] is not leases[1]
                assert owned_reader(case)._read_owner is owner and selected.outstanding_work == 0
                assert tuple(case.sdk.calls) == calls
            finally:
                event.remove(state._engine, "before_cursor_execute", readonly)

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_http_missing_capability_and_exact_unknown_version_are_distinct(
    tmp_path, monkeypatch, profile,
):
    case = installed(tmp_path, monkeypatch, profile)

    async def scenario():
        async with serve(case, profile) as (app, version):
            selected = app.state.monitor_read_service
            calls = tuple(case.sdk.calls)
            for missing in (None, object(), SimpleNamespace(get_plan_readiness=False)):
                app.state.monitor_read_service = missing
                response = await get(app, version)
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            app.state.monitor_read_service = selected
            response = await get(app, uuid4())
            assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
            malformed = await get(app, "not-a-uuid")
            assert malformed.status_code == 422
            assert tuple(case.sdk.calls) == calls

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_http_storage_pause_expiry_and_stop_cannot_return_current(tmp_path, monkeypatch, profile):
    case = installed(tmp_path, monkeypatch, profile)

    async def scenario():
        async with serve(case, profile) as (app, version):
            selected = app.state.monitor_read_service
            generation = case.composition._runtime.runtime_generation
            await selected.suspend_for_storage(generation)
            response = await get(app, version)
            assert response.status_code == 503
            selected.resume_after_storage(generation)
            current = await get(app, version)
            assert current.status_code == 200
            assert current.json()["summary"] == "READY_FOR_MONITORING"
            case.clock.current = datetime.fromisoformat(current.json()["freshUntil"])
            stale = await get(app, version)
            assert stale.status_code == 200 and stale.json()["summary"] == "UNKNOWN"
            assert stale.json()["freshUntil"] is None
            await case.composition.stop()
            stopped = await get(app, version)
            assert stopped.status_code == 503
            assert stopped.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_http_revalidates_real_response_identity_shape_and_native_size_bound(
    tmp_path, monkeypatch, profile,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = installed(tmp_path, monkeypatch, profile)

    async def scenario():
        async with serve(case, profile) as (app, version):
            selected = app.state.monitor_read_service
            original = selected.get_plan_readiness
            real = json.loads((await original(version_id=version)).model_dump_json(by_alias=True))
            wrong_version, grants_authority, unregistered = (deepcopy(real) for _ in range(3))
            wrong_version["snapshot"]["context"]["planVersionId"] = str(uuid4())
            grants_authority["authorityGranted"] = True
            unregistered["privateToken"] = "must-never-leak"
            for value in (wrong_version, grants_authority, unregistered):
                async def invalid(*, version_id, value=value):
                    return value

                # Negative response corruption only; every successful fact came from real work.
                with monkeypatch.context() as patch:
                    patch.setattr(selected, "get_plan_readiness", invalid)
                    response = await get(app, version)
                assert response.status_code == 500
                assert response.json()["error"]["code"] == "INTERNAL_ERROR"
                assert "must-never-leak" not in response.text and "snapshot" not in response.json()
            with monkeypatch.context() as patch:
                patch.setattr(projection, "MAX_READINESS_BYTES", 1)
                oversized = await get(app, version)
            assert oversized.status_code == 503
            assert oversized.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("condition", ["no-runtime", "unreviewed", "source-gap", "upgrade"])
def test_http_persisted_installations_preserve_original_unknown_and_review_states(
    legacy, profile, condition,
):
    options = {"confirmed": False} if condition == "unreviewed" else {
        "extra": "Only buy when turnover exceeds 3 percent."} if condition == "source-gap" else {
        "upgraded": False} if condition == "upgrade" else {}
    case = legacy(**options)
    # A genuine persisted-only installation has no live authority provider.
    reader = RuntimeStatusReadService(case.sessions, lambda: None,
                                     clock=lambda: _NOW + timedelta(minutes=3))
    selected = reader if profile == 2 else PersistentMonitorReadService(
        case.work, lambda: None, clock=lambda: _NOW + timedelta(minutes=3),
        readiness_service=reader)
    app = create_app(read_service=selected, monitor_contract_version=profile)
    tables = inspect(case.engine).get_table_names()

    async def scenario():
        try:
            response = await get(app, case.id)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["authorityGranted"] is False and body["freshUntil"] is None
            axes = {axis["axis"]: axis for axis in body["axes"]}
            assert axes["RUNTIME_OWNERSHIP"]["state"] == "UNKNOWN"
            if condition == "upgrade":
                assert axes["SOURCE_COVERAGE"]["reason"] == "UPGRADE_REQUIRED"
                assert body["summary"] == "UNKNOWN"
            elif condition in {"unreviewed", "source-gap"}:
                assert body["summary"] == "NEEDS_REVIEW"
                assert any(axis["state"] == "BLOCKED" and axis["reason"] == "SOURCE_REVIEW_REQUIRED"
                           for axis in body["axes"])
            else:
                # Original legacy review lacks a coverage receipt.
                assert body["summary"] == "NEEDS_REVIEW"
            assert inspect(case.engine).get_table_names() == tables
        finally:
            await selected.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_http_current_review_without_started_runtime_is_unknown(tmp_path, monkeypatch, profile):
    from sqlalchemy import select

    from trade_plan_monitor.state.models import PlanVersion

    case = installed(tmp_path, monkeypatch, profile)
    state = case.composition._runtime._liveness_owner
    with state._session_factory() as session:
        version = session.scalar(select(PlanVersion.id))
    app = create_app(read_service=case.composition.read_service, monitor_contract_version=profile)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 200, response.text
            body = response.json()
            axes = {axis["axis"]: axis for axis in body["axes"]}
            assert axes["SOURCE_COVERAGE"]["state"] == "PASS"
            assert axes["REVIEW_ACTIVATION"]["state"] == "PASS"
            assert axes["RUNTIME_OWNERSHIP"]["state"] == "UNKNOWN"
            assert body["summary"] == "UNKNOWN" and body["freshUntil"] is None
            assert case.sdk.calls == []
        finally:
            await case.composition.stop()
            state._engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_http_unsupported_historical_plan_stays_unavailable(tmp_path, profile):
    from sqlalchemy import select
    from tests.integration.test_explicit_runtime_production import NOW, _database

    from trade_plan_monitor.state.database import create_session_factory
    from trade_plan_monitor.state.models import PlanVersion
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

    engine, _plan = _database(tmp_path, "historical.sqlite3")
    sessions = create_session_factory(engine)
    with sessions() as session:
        version = session.scalar(select(PlanVersion.id))
    reader = RuntimeStatusReadService(sessions, lambda: None, clock=lambda: NOW)
    selected = reader if profile == 2 else PersistentMonitorReadService(
        lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW), lambda: None,
        clock=lambda: NOW, readiness_service=reader)
    app = create_app(read_service=selected, monitor_contract_version=profile)
    tables = inspect(engine).get_table_names()

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "rules" not in response.json()
            assert inspect(engine).get_table_names() == tables
        finally:
            await selected.stop()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("profile", [1, 2])
def test_actual_openapi_adds_only_the_exact_readiness_surface(profile):
    from scripts.generate_frontend_types import build_openapi_document
    from tests.contract.test_plan_readiness_api_projection import (
        assert_h04_hashes,
        readiness_projection,
    )

    actual = build_openapi_document(monitor_contract_version=profile)
    previous = readiness_projection(actual)
    assert_h04_hashes(previous, profile)
    path = "/api/v1/plan-versions/{version_id}/monitor-readiness"
    expected = {
        "AxisReadiness", "ChannelErrorCode", "ConditionReadiness", "DailyRiskBirth",
        "DailyRiskEvaluation", "DeliveryAttemptStatus", "DeliveryChannel", "ExpectedConfirmation",
        "IntradayEvaluationTarget", "InventoryRequirements", "OfficialCloseEvaluationTarget",
        "OrdinaryRiskCloseObservation", "ReadinessAssessment", "ReadinessContext",
        "ReadinessDeliveryAttempt", "ReadinessExecutionState", "ReadinessMoneyFacts",
        "ReadinessNotificationChannel", "ReadinessNotificationFacts", "ReadinessObservation",
        "ReadinessRiskFacts", "ReadinessRiskObligation", "ReadinessRiskOrigin", "ReadinessSnapshot",
        "RecoveryDeliveryStatus", "RuleReadiness", "RuleReadinessFacts",
    }
    assert set(actual["paths"]) == set(previous["paths"]) | {path}
    assert set(actual["paths"][path]) == {"get"}
    assert all(actual["paths"][key] == value for key, value in previous["paths"].items())
    old, new = previous["components"]["schemas"], actual["components"]["schemas"]
    assert set(new) == set(old) | expected
    assert all(new[key] == value for key, value in old.items())
    assert {k: v for k, v in actual.items() if k not in {"paths", "components"}} == {
        k: v for k, v in previous.items() if k not in {"paths", "components"}}
