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
from tests.integration.test_plan_readiness_reads import guarded_read_case as guarded_read_case
from tests.integration.test_plan_readiness_reads import suspension_chain as suspension_chain
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.monitor_read_ownership import current_read_lease
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

PATH = "/api/v1/plan-versions/{}/monitor-readiness"


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("guarded_read_case", ["latched", "missing"], indirect=True)
def test_buy_suspension_http_repeated_get_has_zero_sql_network_or_transition(
    guarded_read_case, monkeypatch, profile,
):
    import socket

    import requests
    from sqlalchemy import text

    from trade_plan_monitor.decision import buy_suspension
    from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService
    from trade_plan_monitor.state.daily_repository import DailyRepository

    case = guarded_read_case
    selected = case.reader if profile == 2 else PersistentMonitorReadService(
        case.chain.plans._unit_of_work, lambda: None, clock=lambda: case.chain.now,
        readiness_service=case.reader)
    app = create_app(read_service=selected, monitor_contract_version=profile)
    before = _database_rows(case.engine)
    with case.engine.connect() as connection:
        schema = tuple(connection.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master"
            " ORDER BY type,name")))
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("GET attempted acquisition, transition, repair or write")

    def readonly(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}

    async def scenario():
        # Event-loop creation precedes Windows socket interception.
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "connect", denied)
            patch.setattr(socket.socket, "connect_ex", denied)
            patch.setattr(requests.Session, "request", denied)
            patch.setattr(requests, "post", denied)
            patch.setattr(httpx.Client, "send", denied)
            patch.setattr(httpx.AsyncClient, "send", denied)
            patch.setattr(buy_suspension, "transition_buy_suspension", denied)
            patch.setattr(case.pipeline, "advance_buy_suspension", denied)
            patch.setattr(case.pipeline, "buy_suspension_current", denied)
            patch.setattr(DailyRuntimeEvaluationService, "run_inputs", denied)
            patch.setattr(DailyRepository, "save", denied)
            patch.setattr(DailyRepository, "lock_symbol", denied)
            event.listen(case.engine, "before_cursor_execute", readonly)
            try:
                bodies = []
                for _ in range(3):
                    response = await get(app, case.version)
                    assert response.status_code == 200, response.text
                    body = response.json()
                    assert body["authorityGranted"] is False and len(body["axes"]) == 6
                    guard = body["snapshot"]["buySuspension"]
                    assert guard["ownerPlanVersionId"] == case.original_version
                    if case.mode == "missing":
                        assert guard["state"] is None and guard["stateRevision"] is None
                        assert guard["outcome"] == "UNVERIFIED"
                    else:
                        assert guard["state"]["trigger"]["close_fen"] == 2419
                    bodies.append(body)
                assert bodies[0] == bodies[1] == bodies[2]
            finally:
                event.remove(case.engine, "before_cursor_execute", readonly)
        await selected.stop()

    asyncio.run(scenario())
    assert attempts == [] and _database_rows(case.engine) == before
    with case.engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master"
            " ORDER BY type,name"))) == schema


def _incomplete_draft(state, profile, *, owner_case=None, authority=None):
    from tests.browser.source_coverage_server import SetupCommand, _payload
    from tests.integration.test_source_coverage_authority_save import _save

    draft, source, mapping = _payload(SetupCommand(scenario="missing-cap"))
    if owner_case:
        from tests.integration.test_market_linkage_review import source_mapping

        raw = draft.model_dump(mode="json")
        if owner_case == "missing":
            raw["ordinary_rules"][0]["rule_id"] = None
        elif owner_case == "missing-alert":
            raw["alert_rules"][0]["rule_id"] = None
        elif owner_case == "duplicate":
            raw["ordinary_rules"][1]["rule_id"] = raw["ordinary_rules"][0]["rule_id"]
        else:
            for rule in (*raw["ordinary_rules"], *raw["alert_rules"]):
                rule["rule_id"] = None
        draft = type(draft).model_validate(raw)
        source, mapping = source_mapping(draft)
    assert draft.schema_version == 5 and draft.position.max_qty is None
    version = _save(state, draft, source, mapping)
    reader = RuntimeStatusReadService(state.sessions, lambda: authority, clock=lambda: _NOW)
    selected = reader if profile == 2 else PersistentMonitorReadService(
        state.work, lambda: None, clock=lambda: _NOW, readiness_service=reader)
    return create_app(read_service=selected, monitor_contract_version=profile), selected, version


def _database_rows(engine):
    from sqlalchemy import text

    with engine.connect() as connection:
        return {name: tuple(tuple(row) for row in connection.execute(
            text('SELECT * FROM "' + name.replace('"', '""') + '"')))
            for name in inspect(engine).get_table_names()}


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("active_sibling", [False, True])
def test_http_incomplete_draft_retains_null_and_source_without_executing(
    state, monkeypatch, profile, active_sibling,
):
    from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService

    if active_sibling:
        from tests.integration.test_source_coverage_authority import _confirm, _save

        from trade_plan_monitor.domain.plan_validation import PlanValidationResult

        identity, draft = _save(state)
        _confirm(state, identity)
        with state.work() as work:
            work.plans.activate(draft.to_executable(), expected_revision=0,
                                validation=PlanValidationResult(issues=()))
            work.commit()
    app, selected, version = _incomplete_draft(state, profile)
    before = _database_rows(state.engine)
    with state.work() as work:
        details = work.plans.get_version_details(version)
        assert json.loads(details.payload_json)["position"]["max_qty"] is None
        assert "position.max_qty = null" in details.source_text

    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("incomplete readiness cannot execute or acquire external inputs")

    monkeypatch.setattr(DailyRuntimeEvaluationService, "run_inputs", denied)
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)
    from trade_plan_monitor.web import plan_readiness_service as projection

    monkeypatch.setattr(projection.DailyAccounting, "snapshot", denied)
    monkeypatch.setattr(projection, "current_capital_inputs", denied)
    monkeypatch.setattr(projection, "read_risk_origin", denied)
    monkeypatch.setattr(projection, "read_owned_notifications", denied)

    def readonly(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}

    async def scenario():
        import socket

        monkeypatch.setattr(socket.socket, "connect", denied)
        event.listen(state.engine, "before_cursor_execute", readonly)
        try:
            response = await get(app, version)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["summary"] == "NEEDS_REVIEW" and body["freshUntil"] is None
            assert body["authorityGranted"] is False and len(response.content) <= 1024 * 1024
            context = body["snapshot"]["context"]
            assert context["planVersionId"] == version
            assert context["contentHash"] == details.content_hash
            assert context["sourceHash"] == details.source_hash
            for key in ("reviewReceiptHash", "activationRevision", "runtimeGeneration",
                        "inventoryRevision", "bookRevision"):
                assert context[key] is None
            axes = {axis["axis"]: axis for axis in body["axes"]}
            assert axes["SOURCE_COVERAGE"]["state"] == "BLOCKED"
            assert axes["REVIEW_ACTIVATION"]["reason"] == "SOURCE_REVIEW_REQUIRED"
            for axis in ("RUNTIME_OWNERSHIP", "DATA_EVALUATION", "INVENTORY_CAPITAL",
                         "NOTIFICATION_DELIVERY"):
                assert axes[axis]["state"] == "UNKNOWN"
            assert body["rules"]
            for rule in body["rules"]:
                facts = rule["facts"]
                assert facts["rootOutcome"] is None and facts["evaluatedAt"] is None
                assert facts["evaluatedTarget"] is None and facts["expectedTarget"] is None
                assert facts["observation"] is None and facts["expectedConfirmation"] is None
                assert all(leaf["state"] == "UNKNOWN" for leaf in facts["leaves"])
                assert facts["execution"]["approvedQuantity"] is None
                assert facts["execution"]["consumed"] is None
                assert "money" not in facts and "risk" not in facts and "notification" not in facts
            assert selected.outstanding_work == 0 and attempts == []
        finally:
            event.remove(state.engine, "before_cursor_execute", readonly)
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("corruption", ["malformed", "invalid-parameter", "reviewed", "active"])
def test_http_incomplete_draft_does_not_hide_corruption_or_approved_states(
    state, profile, corruption,
):
    from sqlalchemy import update

    from trade_plan_monitor.state.models import PlanReviewProvenance, PlanVersion

    app, selected, version = _incomplete_draft(state, profile)
    with state.sessions() as session:
        row = session.get(PlanVersion, version)
        if corruption == "malformed":
            row.payload_json = "{"
        elif corruption == "invalid-parameter":
            raw = json.loads(row.payload_json)
            raw["position"]["max_qty"] = -100
            row.payload_json = json.dumps(raw)
        elif corruption == "active":
            row.status = "ACTIVE"
        else:
            session.execute(update(PlanReviewProvenance).where(
                PlanReviewProvenance.plan_version_id == version).values(
                    confirmed_at=_NOW.isoformat(), review_id=str(uuid4()), review_revision=1))
        session.commit()
    before = _database_rows(state.engine)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code >= 400, response.text
            assert "error" in response.json() and "snapshot" not in response.json()
            assert selected.outstanding_work == 0
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("owner_case", ["missing", "missing-alert", "duplicate"])
def test_http_incomplete_draft_missing_rule_identity_cannot_invent_an_owner(
    state, profile, owner_case,
):
    app, selected, version = _incomplete_draft(state, profile, owner_case=owner_case)
    before = _database_rows(state.engine)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 503, response.text
            body = response.json()
            assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
            # A partial view could falsely declare ALERT_ONLY or drop actual
            # inventory requirements. Missing/ambiguous owners remain unsupported.
            assert "snapshot" not in body and "rules" not in body and "summary" not in body
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("limit", ["bytes", "active-symbols"])
def test_http_incomplete_draft_keeps_existing_projection_limits(state, monkeypatch, profile, limit):
    from trade_plan_monitor.runtime.status_authority import PlanReadAuthority, RuntimeReadAuthority
    from trade_plan_monitor.web import plan_readiness_service as projection

    authority = None
    if limit == "bytes":
        monkeypatch.setattr(projection, "MAX_READINESS_BYTES", 1)
    else:
        # Over-bound authority is a negative admission input, never evidence.
        authority = RuntimeReadAuthority(token="overfull", lifecycle="STOPPED", progress=None,
            health=None, owner_absent=True, plans=tuple(PlanReadAuthority(
                symbol=f"00{index:04d}.SZ", plan_version_id=str(uuid4()), plan_hash="a" * 64,
                activation_revision=1, plan_family="CONDITION_PLAN") for index in range(11)))
    app, selected, version = _incomplete_draft(state, profile, authority=authority)
    before = _database_rows(state.engine)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "snapshot" not in response.json()
            assert selected.outstanding_work == 0
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
def test_http_incomplete_draft_without_any_identifiable_owner_remains_unavailable(state, profile):
    app, selected, version = _incomplete_draft(state, profile, owner_case="all-missing")
    before = _database_rows(state.engine)

    async def scenario():
        try:
            response = await get(app, version)
            # The existing public model requires at least one real rule owner.
            # This bounded fix cannot fabricate one or add an empty-owner model.
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "snapshot" not in response.json()
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
def test_http_incomplete_draft_preserves_native_coverage_upgrade_reason(
    state, monkeypatch, profile,
):
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageUpgradeRequired
    from trade_plan_monitor.web import source_coverage_read

    app, selected, version = _incomplete_draft(state, profile)
    before = _database_rows(state.engine)

    def old_rules(*args):
        raise SourceCoverageUpgradeRequired()

    # Exercise the native unsupported-rules error, never inject successful proof.
    monkeypatch.setattr(source_coverage_read, "read_version_coverage", old_rules)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["summary"] == "UNKNOWN" and body["freshUntil"] is None
            assert body["authorityGranted"] is False
            for axis in body["axes"]:
                if axis["axis"] in {"SOURCE_COVERAGE", "REVIEW_ACTIVATION"}:
                    assert axis["state"] == "UNKNOWN" and axis["reason"] == "UPGRADE_REQUIRED"
            assert body["snapshot"]["context"]["coverageHash"] is None
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
@pytest.mark.parametrize("schema_version", [6, 7, 8, 9])
def test_http_incomplete_linked_draft_keeps_the_explicit_schema5_boundary(
    state, profile, schema_version,
):
    from tests.integration.test_market_linkage_review import source_mapping
    from tests.integration.test_source_coverage_authority_save import _save
    from tests.unit.test_market_exception_contract import exception_payload
    from tests.unit.test_market_linkage_contract import linked_payload
    from tests.unit.test_p2_policy_contract import p2_payload
    from tests.unit.test_p3_policy_contract import p3_payload

    from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json

    raw = {6: linked_payload, 7: exception_payload, 8: p2_payload, 9: p3_payload}[
        schema_version]()
    buy = next(rule for rule in raw["ordinary_rules"] if rule["side"] == "BUY")
    if schema_version in {6, 7}:
        buy["quantity_policy"]["base_quantity"] = None
    else:
        buy["pretrade_policy"]["sizing"]["base_qty"] = None
    draft = load_daily_draft_json(json.dumps(raw))
    assert draft.schema_version == schema_version and draft.to_executable() is None
    source, mapping = source_mapping(draft)
    version = _save(state, draft, source, mapping)
    reader = RuntimeStatusReadService(state.sessions, lambda: None, clock=lambda: _NOW)
    selected = reader if profile == 2 else PersistentMonitorReadService(
        state.work, lambda: None, clock=lambda: _NOW, readiness_service=reader)
    app = create_app(read_service=selected, monitor_contract_version=profile)
    before = _database_rows(state.engine)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "snapshot" not in response.json()
        finally:
            await selected.stop()

    asyncio.run(scenario())
    assert _database_rows(state.engine) == before


@pytest.mark.parametrize("profile", [1, 2])
def test_http_incomplete_draft_second_read_retries_then_withholds_changed_context(
    state, monkeypatch, profile,
):
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
    from trade_plan_monitor.web import plan_readiness_service as projection

    app, selected, version = _incomplete_draft(state, profile)
    original = projection.read_readiness_binding
    changes = []

    def changed(*args):
        with state.work() as work:
            store = SourceCoverageStore(work.daily.session)
            old = store.latest(version)
            store.append(version, old.assessment, inputs=old.inputs,
                expected_revision=old.revision, command_id="draft-read-race-" + str(len(changes)),
                now=_NOW)
            work.commit()
        changes.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)

    async def scenario():
        try:
            response = await get(app, version)
            assert response.status_code == 200, response.text
            body = response.json()
            assert len(changes) == 2
            assert body["summary"] == "UNKNOWN" and body["freshUntil"] is None
            assert body["authorityGranted"] is False
            assert all(axis["reason"] == "CONTEXT_CHANGED" for axis in body["axes"])
            assert selected.outstanding_work == 0
        finally:
            await selected.stop()

    asyncio.run(scenario())


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
