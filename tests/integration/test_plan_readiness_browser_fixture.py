"""The browser adapter must expose actual owned work, never manufactured readiness."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from importlib import import_module

import httpx
import pytest
from sqlalchemy import event


@asynccontextmanager
async def workspace(root):
    module = import_module("tests.browser.plan_readiness_server")
    app = module.create_fixture_app(root)
    state = app.state.readiness_fixture
    try:
        async with app.router.lifespan_context(app):
            async with httpx.ASGITransport(app, client=("127.0.0.1", 50000)) as transport:
                yield state, transport
        assert state.case.composition.read_service.outstanding_work == 0
        assert state.case.composition._runtime.progress_snapshot().state == "STOPPED"
    finally:
        state.restore_boundaries()


async def request(transport, path, *, method="GET", body=None):
    response = await transport.handle_async_request(
        httpx.Request(
            method,
            "http://127.0.0.1:8765" + path,
            json=body,
        )
    )
    await response.aread()
    return response


def test_saved_source_public_get_uses_the_actual_owner_and_real_sqlite(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            detail = await request(transport, "/api/v1/plan-versions/" + state.version)
            assert detail.status_code == 200, detail.text
            saved = detail.json()
            assert saved["sourceCoverage"]["currentReviewBound"] is True
            assert saved["sourceCoverage"]["coverageComplete"] is True
            native = await state.case.composition.read_service.get_plan_readiness(
                version_id=state.version,
            )
            response = await request(transport, state.readiness_path)
            assert response.status_code == 200, response.text
            assert response.json() == native.model_dump(mode="json", by_alias=True)
            assert response.json()["summary"] == "READY_FOR_MONITORING", {
                "now": state.case.clock.now().isoformat(),
                "progress": str(state.case.composition._runtime.progress_snapshot()),
                "parked": str(state.case.clock.parked[0]),
                "axes": [(axis.axis, axis.state, axis.reason) for axis in native.axes],
            }
            assert response.json()["authorityGranted"] is False
            assert response.json()["rules"][0]["state"] == "CONDITION_FALSE"
            assert native.fresh_until > native.snapshot.computed_at + timedelta(milliseconds=1)
            assert (tmp_path / "monitor.sqlite3").is_file()
            assert state.case.composition._runtime.runtime_generation == (
                native.snapshot.context.runtime_generation
            )

    asyncio.run(scenario())


def test_two_scheduled_targets_need_no_new_fact_or_review(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            before = state.inspect()
            first = (await request(transport, state.readiness_path)).json()
            response = await request(
                transport, state.prefix + "/next-target", method="POST", body={}
            )
            assert response.status_code == 200, response.text
            after = response.json()
            second = (await request(transport, state.readiness_path)).json()
            assert second["summary"] == "READY_FOR_MONITORING"
            assert second["rules"][0]["state"] == "CONDITION_FALSE"
            assert second["snapshot"]["context"] == first["snapshot"]["context"]
            a, b = first["rules"][0]["facts"], second["rules"][0]["facts"]
            assert a["evaluatedTarget"] != b["evaluatedTarget"]
            assert a["evaluatedAt"] < b["evaluatedAt"]
            assert before["completionResultHash"] != after["completionResultHash"]
            for table in ("source_coverage_review", "plan_review_provenance", "plan_version"):
                assert before["storage"][table] == after["storage"][table]
            assert before["storage"]["dailyKinds"].get("FACT", 0) == (
                after["storage"]["dailyKinds"].get("FACT", 0)
            )
            assert (
                after["storage"]["dailyKinds"]["EVALUATION"]
                > (before["storage"]["dailyKinds"]["EVALUATION"])
            )
            assert after["externalAttempts"] == []

    asyncio.run(scenario())


def test_repeated_public_reads_do_not_write_acquire_evaluate_or_renew_expiry(tmp_path, monkeypatch):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            before = state.inspect()
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            statements = []

            def forbidden(*_args, **_kwargs):
                pytest.fail("GET attempted native producer or SDK work")

            def readonly(_connection, _cursor, sql, _parameters, _context, _many):
                verb = sql.lstrip().split()[0].upper()
                statements.append(verb)
                assert verb not in {
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "REPLACE",
                    "CREATE",
                    "ALTER",
                    "DROP",
                }

            with monkeypatch.context() as patch:
                for name in ("run_deadline", "prepare_daily_inputs", "refresh_references"):
                    patch.setattr(pipeline, name, forbidden)
                patch.setattr(state.case.sdk, "_stock_minutes", forbidden)
                engine = state.case.composition._runtime._liveness_owner._engine
                event.listen(engine, "before_cursor_execute", readonly)
                try:
                    a = await request(transport, state.readiness_path)
                    b = await request(transport, state.readiness_path)
                finally:
                    event.remove(engine, "before_cursor_execute", readonly)
            assert a.status_code == b.status_code == 200
            assert a.json() == b.json()
            assert a.json()["freshUntil"] is not None
            assert "SELECT" in statements
            assert state.inspect() == before

    asyncio.run(scenario())


def test_fixture_rejects_nonlocal_controls_extra_fields_and_third_cycle(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            invalid = await request(
                transport,
                state.prefix + "/next-target",
                method="POST",
                body={"completion": "invented"},
            )
            assert invalid.status_code == 422
            assert state.cycles == 1
            async with httpx.ASGITransport(state.app, client=("192.0.2.1", 50000)) as foreign:
                rejected = await request(foreign, state.prefix + "/inspect")
                assert rejected.status_code == 403
            assert (
                await request(transport, state.prefix + "/next-target", method="POST", body={})
            ).status_code == 200
            assert (
                await request(transport, state.prefix + "/next-target", method="POST", body={})
            ).status_code == 409

    asyncio.run(scenario())
